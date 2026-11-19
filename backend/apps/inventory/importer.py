"""Upload stock from an Excel (.xlsx) or CSV file.

Columns (header row; names are matched loosely, order doesn't matter):
  SKU | Barcode | Name | Category | Unit | Cost | Price | Quantity | Reorder level

Modes
  add   Goods arriving without a purchase order, or opening stock: Quantity is ADDED at Cost.
        Booked Dr Inventory / Cr Opening stock (equity) - the same as the opening balance.
  set   Stock count: Quantity is what is on the shelf. The difference is an adjustment (shrinkage/gain).

A row is matched to a product by Barcode (any UPC/EAN/GTIN length) or SKU. With catalog rights, rows
for products that don't exist yet create them (Name and Price needed). Every file is checked first
(preview); nothing is saved unless every row is valid, and then it is saved all at once.
"""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.catalog.models import Category, Product
from apps.core.models import audit

from .counts import find_product, normalize_code, on_hand
from .services import current_cost, move_stock

MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
ZERO = Decimal("0")

ALIASES = {
    "sku": ["sku", "code", "item code", "product code", "item no", "item number"],
    "barcode": ["barcode", "bar code", "ean", "upc", "gtin"],
    "name": ["name", "product", "product name", "item", "item name", "description"],
    "category": ["category", "department", "group", "category path"],
    "unit": ["unit", "uom", "unit of measure"],
    "cost": ["cost", "unit cost", "cost price", "buying price", "purchase price"],
    "price": ["price", "sell price", "selling price", "retail price", "sale price"],
    "quantity": ["quantity", "qty", "stock", "on hand", "count", "counted", "quantity on hand"],
    "reorder": ["reorder level", "reorder", "reorder at", "min stock", "minimum"],
}


class ImportError_(Exception):
    pass


def _key(h):
    h = re.sub(r"[^a-z0-9 ]+", " ", str(h or "").strip().lower())
    h = re.sub(r"\s+", " ", h).strip()
    for field, names in ALIASES.items():
        if h in names:
            return field
    return None


def read_rows(upload):
    """-> list of dicts keyed by our field names, plus the sheet row number as "_row"."""
    if upload.size > MAX_BYTES:
        raise ImportError_("The file is larger than 5 MB. Split it into smaller files.")
    name = (upload.name or "").lower()
    data = upload.read()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        table = list(csv.reader(io.StringIO(text)))
    elif name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ImportError_("That file couldn't be opened as an Excel workbook (.xlsx).")
        ws = wb["Stock"] if "Stock" in wb.sheetnames else wb.worksheets[0]
        table = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif name.endswith(".xls"):
        raise ImportError_("Old .xls files aren't supported. In Excel choose File > Save As > Excel Workbook (.xlsx).")
    else:
        raise ImportError_("Upload an Excel workbook (.xlsx) or a CSV file.")
    # The header is the first row that names at least a quantity and an identifier.
    for i, row in enumerate(table[:20]):
        keys = [_key(c) for c in row]
        if "quantity" in keys and ("sku" in keys or "barcode" in keys):
            header, start = keys, i + 1
            break
    else:
        raise ImportError_("No header row found. The sheet needs columns for SKU or Barcode, and Quantity "
                           "(download the template to see the layout).")
    rows = []
    for n, raw in enumerate(table[start:], start=start + 1):
        if not any(c not in (None, "") and str(c).strip() for c in raw):
            continue
        row = {"_row": n}
        for k, v in zip(header, raw):
            if k and k not in row:
                row[k] = v
        rows.append(row)
    if len(rows) > MAX_ROWS:
        raise ImportError_(f"The file has {len(rows)} rows; the limit is {MAX_ROWS} per upload.")
    if not rows:
        raise ImportError_("The sheet has a header but no rows.")
    return rows


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # Excel turns 6001234567890 into 6.00123456789e12
    return str(v).strip()


def _num(v, what, errors, allow_blank=True):
    s = _text(v).replace(",", "")
    if s == "":
        if not allow_blank:
            errors.append(f"{what} is missing")
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        errors.append(f"{what} '{_text(v)}' isn't a number")
        return None
    if d < 0:
        errors.append(f"{what} can't be negative")
        return None
    return d


def _category(org, path, create, cache):
    if not path:
        return None, None
    key = path.lower()
    if key in cache:
        return cache[key], None
    parent = None
    for part in [p.strip() for p in re.split(r"[/>]", path) if p.strip()]:
        c = Category.objects.filter(organization=org, parent=parent, name__iexact=part).first()
        if c is None:
            if not create:
                return None, f"category '{path}' doesn't exist"
            c = Category.objects.create(organization=org, parent=parent, name=part[:100])
        parent = c
    cache[key] = parent
    return parent, None


def check(rows, *, branch, mode, can_create):
    """Validate and work out what each row would do. Returns (results, summary)."""
    org = branch.organization
    out, seen = [], {}
    for r in rows:
        errors = []
        sku, barcode = _text(r.get("sku")), normalize_code(_text(r.get("barcode")))
        qty = _num(r.get("quantity"), "Quantity", errors, allow_blank=False)
        cost = _num(r.get("cost"), "Cost", errors)
        price = _num(r.get("price"), "Price", errors)
        reorder = _num(r.get("reorder"), "Reorder level", errors)
        product = (find_product(org, barcode) if barcode else None) or (find_product(org, sku) if sku else None)
        if not sku and not barcode:
            errors.append("SKU or Barcode is needed")
        ident = (product.pk if product else None) or (barcode or sku).lower()
        if ident in seen:
            errors.append(f"same product as row {seen[ident]}")
        else:
            seen[ident] = r["_row"]
        new = product is None and not errors
        if new:
            if not can_create:
                errors.append("no product with this SKU/barcode (ask someone with catalog rights to add it)")
            else:
                if not _text(r.get("name")):
                    errors.append("new product: Name is needed")
                if price is None:
                    errors.append("new product: Price is needed")
                if not sku:
                    errors.append("new product: SKU is needed")
                if barcode and Product.objects.filter(organization=org, barcode=barcode).exists():
                    errors.append("barcode already used by another product")
        current = on_hand(branch, product) if product else ZERO
        if qty is not None and not errors:
            if mode == "add":
                after, change = current + qty, qty
            else:
                after, change = qty, qty - current
        else:
            after = change = None
        out.append({
            "row": r["_row"], "sku": sku or (product.sku if product else ""), "barcode": barcode,
            "name": product.name if product else _text(r.get("name")), "product": product.pk if product else None,
            "new_product": new and not errors, "current": str(current), "quantity": str(qty) if qty is not None else "",
            "after": str(after) if after is not None else "", "change": str(change) if change is not None else "",
            "cost": str(cost) if cost is not None else "", "price": str(price) if price is not None else "",
            "reorder": str(reorder) if reorder is not None else "", "category": _text(r.get("category")),
            "unit": _text(r.get("unit")), "errors": errors,
        })
    bad = [x for x in out if x["errors"]]
    summary = {"rows": len(out), "errors": len(bad), "new_products": sum(1 for x in out if x["new_product"]),
               "changes": sum(1 for x in out if not x["errors"] and x["change"] and Decimal(x["change"]) != 0)}
    return out, summary


@transaction.atomic
def apply(results, *, branch, mode, user, can_create, file_name=""):
    """Save a checked file. Every row must be valid (the caller checks); all or nothing."""
    from apps.accounting.services import acct, post, post_stock_adjustment
    org = branch.organization
    from apps.core.models import next_number
    from apps.catalog.models import TaxRate
    ref = next_number(f"stock-upload-{org.pk}", "UPL-")
    # New products get the tax rate most products already use (usually VAT); change it later if needed.
    from django.db.models import Count
    usual = (Product.objects.filter(organization=org, tax_rate__isnull=False).values("tax_rate")
             .annotate(n=Count("id")).order_by("-n").first())
    tax = TaxRate.objects.filter(pk=usual["tax_rate"]).first() if usual else None
    cats, created, opening_value, moved = {}, 0, ZERO, 0
    for x in results:
        product = Product.objects.filter(pk=x["product"]).first() if x["product"] else None
        if product is None:
            category, err = _category(org, x["category"], can_create, cats)
            product = Product.objects.create(
                organization=org, sku=x["sku"][:50], barcode=x["barcode"][:64], name=x["name"][:200], category=category,
                unit=(x["unit"] or "pcs")[:20], cost_price=Decimal(x["cost"] or "0"), sell_price=Decimal(x["price"]),
                reorder_level=Decimal(x["reorder"] or "0"), tax_rate=tax)
            created += 1
        elif x["reorder"]:
            product.reorder_level = Decimal(x["reorder"])
            product.save(update_fields=["reorder_level", "updated_at"])
        change = Decimal(x["change"] or "0")
        if change == 0:
            continue
        if mode == "add":
            unit_cost = Decimal(x["cost"]) if x["cost"] else current_cost(branch, product)
            move_stock(branch=branch, product=product, quantity=change, kind="opening", unit_cost=unit_cost, user=user,
                       reference=ref, note=f"Stock upload {file_name}"[:255])
            opening_value += (change * unit_cost).quantize(Decimal("0.01"))
        else:
            mv = move_stock(branch=branch, product=product, quantity=change, kind="adjustment", user=user, reference=ref,
                            note=f"Stock count upload {file_name}"[:255], allow_negative=True)
            post_stock_adjustment(mv)
        moved += 1
    if opening_value:
        post(organization=org, branch=branch, reference=ref, source="opening", user=user,
             memo=f"Stock upload {file_name}"[:200],
             lines=[(acct(org, "inventory"), opening_value, ZERO, "Stock uploaded"),
                    (acct(org, "equity"), ZERO, opening_value, "Stock uploaded")])
    audit("inventory.import", organization=org, branch=branch, actor=user, mode=mode, file=file_name, rows=len(results),
          products_created=created, items_changed=moved, value_added=str(opening_value))
    return {"rows": len(results), "products_created": created, "items_changed": moved, "value_added": str(opening_value),
            "reference": ref}


def template_workbook():
    """A ready-to-fill .xlsx: the Stock sheet with headers and two examples, plus instructions."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock"
    head = ["SKU", "Barcode", "Name", "Category", "Unit", "Cost", "Price", "Quantity", "Reorder level"]
    ws.append(head)
    ws.append(["SUG-2KG", "6001234567890", "Sugar 2kg", "Food/Groceries", "pcs", 4200, 5500, 24, 10])
    ws.append(["OIL-2L", "", "Cooking oil 2L", "Food/Groceries", "pcs", 10000, 12500, 12, 5])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0F766E")
    for col, width in zip("ABCDEFGHI", [14, 16, 30, 22, 8, 10, 10, 10, 13]):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for c in row:
            c.number_format = "@"  # keep barcodes as text (no 6.00E+12)
    info = wb.create_sheet("How to fill it")
    for line in [
        "Fill the Stock sheet: one row per product. Delete the two example rows.",
        "SKU or Barcode finds the product. Barcodes can be UPC, EAN-13 or GTIN-14.",
        "Quantity: with 'Add to stock' it is ADDED (goods in, opening stock); with 'Stock count' it REPLACES what the system has.",
        "Cost: the unit cost for stock being added (else the current average cost is used).",
        "New products (people with catalog rights): also give Name, Price and SKU; Category like Food/Meat is created if missing.",
        "Reorder level (optional) updates the product's reorder alert.",
        "Upload in the back office: Stock > Upload from Excel. You see a check of every row before anything is saved.",
    ]:
        info.append([line])
    info.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
