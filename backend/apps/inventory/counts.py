"""Stock takes: count (scan on phones), submit, verify by someone else, post the differences."""
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.models import audit, next_number

from .models import StockCount, StockCountLine, StockLevel
from .services import move_stock


class CountError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def dec(x, what="quantity") -> Decimal:
    try:
        d = Decimal(str(x))
    except (InvalidOperation, TypeError, ValueError):
        raise CountError(f"Enter a valid {what}.")
    if d < 0:
        raise CountError("Quantities can't be negative.")
    return d.quantize(Decimal("0.001"))


AIM = re.compile(r"^\][A-Za-z][0-9A-Za-z]")
GS1 = re.compile(r"^(?:\(01\)|01)(\d{14})")
GS = chr(29)  # GS1 group separator
DIGITAL_LINK = re.compile(r"/01/(\d{8,14})")


def normalize_code(raw: str) -> str:
    """Same clean-up as the web app: AIM prefix, GS1 GTIN, links inside QR codes."""
    s = re.sub(r"[\r\n\t]+", "", raw or "").strip()
    s = AIM.sub("", s).lstrip(GS)
    m = GS1.match(s)
    if m and (len(s) == 16 or s.startswith("(") or not s[2:].isdigit() or len(s) > 16):
        return m.group(1)
    if s.lower().startswith(("http://", "https://")):
        from urllib.parse import parse_qs, urlparse
        u = urlparse(s)
        dl = DIGITAL_LINK.search(u.path)
        if dl:
            return dl.group(1)
        q = parse_qs(u.query)
        for k in ("code", "c", "sku"):
            if q.get(k):
                return q[k][0].strip()
    return s


def find_product(org, code: str):
    """Barcode (any GTIN length: UPC-A, EAN-13, GTIN-14 match each other) or SKU."""
    code = normalize_code(code)
    if not code:
        return None
    qs = Product.objects.filter(organization=org)
    p = qs.filter(barcode=code).first() or qs.filter(sku__iexact=code).first()
    if p or not code.isdigit():
        return p
    key = code.lstrip("0")
    if not key:
        return None
    for cand in qs.filter(barcode__endswith=key):
        if cand.barcode.isdigit() and cand.barcode.lstrip("0") == key:
            return cand
    return None


def on_hand(branch, product) -> Decimal:
    lvl = StockLevel.objects.filter(branch=branch, product=product).first()
    return lvl.quantity if lvl else Decimal("0")


def in_scope(count, product) -> bool:
    if not count.category_id:
        return True
    from apps.catalog.api import descendant_ids
    return product.category_id in set(descendant_ids(count.branch.organization, count.category_id))


@transaction.atomic
def create(*, branch, by, title="", category=None, blind=True, note=""):
    c = StockCount.objects.create(branch=branch, number=next_number(f"count-{branch.organization_id}", "ST-"),
                                  title=title or f"Stock take {timezone.localdate():%d %b %Y}", category=category,
                                  blind=blind, note=note, created_by=by)
    audit("stockcount.created", organization=branch.organization, branch=branch, actor=by, obj=c)
    return c


def _open(count):
    if count.status != "counting":
        raise CountError(f"{count.number} is {count.get_status_display().lower()}; counting is closed.")


@transaction.atomic
def record(count, *, product, qty, by, mode="add"):
    """mode "add": each scan adds qty (default 1). mode "set": the shelf total for this product."""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    _open(count)
    if not in_scope(count, product):
        raise CountError(f"{product.name} isn't in this stock take's category.")
    qty = dec(qty)
    line = StockCountLine.objects.filter(count=count, product=product).first()
    if line is None:
        line = StockCountLine(count=count, product=product, expected_qty=on_hand(count.branch, product),
                              counted_qty=Decimal("0"), counted_by=by)
    line.counted_qty = line.counted_qty + qty if mode == "add" else qty
    line.counted_by = by
    line.save()
    return line


@transaction.atomic
def remove_line(count, line, by):
    _open(count)
    line.delete()


@transaction.atomic
def submit(count, by):
    _open(count)
    if not count.lines.exists():
        raise CountError("Nothing has been counted yet.")
    count.status, count.submitted_by, count.submitted_at = "submitted", by, timezone.now()
    count.save(update_fields=["status", "submitted_by", "submitted_at", "updated_at"])
    audit("stockcount.submitted", organization=count.branch.organization, branch=count.branch, actor=by, obj=count,
          lines=count.lines.count())
    return count


@transaction.atomic
def reopen(count, by):
    if count.status != "submitted":
        raise CountError("Only a submitted stock take can be sent back for recounting.")
    count.status = "counting"
    count.save(update_fields=["status", "updated_at"])
    audit("stockcount.reopened", organization=count.branch.organization, branch=count.branch, actor=by, obj=count)
    return count


def counted_it(count, user) -> bool:
    return count.lines.filter(counted_by=user).exists() or count.submitted_by_id == user.pk


def _require_verifier(count, user):
    if count.status != "submitted":
        raise CountError("Submit the stock take before verifying it.")
    if counted_it(count, user) and not user.has_org_perm("org.admin"):
        raise CountError("Someone who didn't count this stock take has to verify it.", 403)


@transaction.atomic
def recount(count, line, *, qty, by):
    _require_verifier(count, by)
    line.verified_qty = dec(qty)
    line.save(update_fields=["verified_qty"])
    return line


@transaction.atomic
def post(count, by):
    """Approve: book each line's difference (counted - system qty when it was counted) as an adjustment.
    Using the difference, not the absolute count, keeps sales made during the count correct."""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    _require_verifier(count, by)
    from apps.accounting.services import post_stock_adjustment
    changed = 0
    for line in count.lines.select_related("product"):
        diff = line.variance
        if diff == 0:
            continue
        mv = move_stock(branch=count.branch, product=line.product, quantity=diff, kind="adjustment", user=by,
                        reference=count.number, note=f"Stock take {count.number}", allow_negative=True)
        post_stock_adjustment(mv)
        line.movement = mv
        line.save(update_fields=["movement"])
        changed += 1
    count.status, count.verified_by, count.verified_at = "posted", by, timezone.now()
    count.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
    audit("stockcount.posted", organization=count.branch.organization, branch=count.branch, actor=by, obj=count,
          adjusted=changed)
    return count


@transaction.atomic
def cancel(count, by):
    if count.status == "posted":
        raise CountError("A posted stock take can't be cancelled.")
    count.status = "cancelled"
    count.save(update_fields=["status", "updated_at"])
    audit("stockcount.cancelled", organization=count.branch.organization, branch=count.branch, actor=by, obj=count)
    return count


def lookup(user, code):
    """Scan-to-look-up: the product and its stock at every branch the user can see stock for."""
    from apps.core.api import branches_with
    p = find_product(user.organization, code)
    if not p:
        return None
    branches = {b.pk: b for b in [*branches_with(user, "inventory.view"), *branches_with(user, "pos.sell"),
                                  *branches_with(user, "inventory.count")]}
    levels = {l.branch_id: l.quantity for l in StockLevel.objects.filter(product=p, branch__in=branches)}
    from apps.catalog.models import BranchPrice
    prices = {bp.branch_id: bp.price for bp in BranchPrice.objects.filter(product=p, branch__in=branches)}
    return {"id": p.pk, "name": p.name, "sku": p.sku, "barcode": p.barcode, "unit": p.unit,
            "category": p.category.path() if p.category_id else "", "reorder_level": str(p.reorder_level),
            "is_active": p.is_active,
            "branches": [{"id": b.pk, "name": b.name, "quantity": str(levels.get(b.pk, Decimal("0"))),
                          "price": str(prices.get(b.pk, p.sell_price))} for b in sorted(branches.values(), key=lambda b: b.name)]}
