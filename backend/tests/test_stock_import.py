import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook

from apps.accounting.services import trial_balance
from apps.catalog.models import Product
from apps.inventory.counts import on_hand

pytestmark = pytest.mark.django_db


def xlsx(rows, header=("SKU", "Barcode", "Name", "Category", "Cost", "Price", "Qty")):
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock"
    ws.append(["Aden Trifo Shop stock list"])  # a title row above the header is fine
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("stock.xlsx", buf.getvalue())


def upload(c, f, mode="add", apply=False):
    return c.post("/api/stock/import/", {"file": f, "mode": mode, "apply": "1" if apply else "0"}, format="multipart")


def balanced(org):
    tb = trial_balance(org)
    return sum(r["debit"] for r in tb) == sum(r["credit"] for r in tb)


def test_template_downloads_as_a_real_workbook(demo, client_for):
    r = client_for("ll_store", demo["ll"]).get("/api/stock/import/template/")
    assert r.status_code == 200 and r["Content-Disposition"].endswith('stock-upload.xlsx"')
    wb = load_workbook(io.BytesIO(r.content))
    assert wb["Stock"]["A1"].value == "SKU" and "How to fill it" in wb.sheetnames


def test_add_stock_checks_first_then_saves_and_books_it(demo, client_for):
    ll, sugar = demo["ll"], demo["sugar"]
    before = on_hand(ll, sugar)
    c = client_for("ll_store", ll)
    rows = [(sugar.sku, "", "", "", 4000, "", 10),
            ("NEW-1", "", "Mango juice 1L", "Drinks/Juice", 1500, 2200, 30)]  # storekeeper can't create products
    r = upload(c, xlsx(rows))
    assert r.status_code == 200 and r.data["summary"]["errors"] == 1
    assert "catalog rights" in r.data["rows"][1]["errors"][0]
    assert upload(c, xlsx(rows), apply=True).status_code == 400  # nothing saved while a row is wrong
    assert on_hand(ll, sugar) == before

    admin = client_for("ll_admin", ll)  # branch admin: catalog rights, so the new product is created
    r = upload(admin, xlsx(rows), apply=True)
    assert r.status_code == 200, r.data
    assert r.data["applied"]["products_created"] == 1 and r.data["applied"]["items_changed"] == 2
    assert on_hand(ll, sugar) == before + 10
    mango = Product.objects.get(sku="NEW-1")
    assert on_hand(ll, mango) == 30 and mango.category.name == "Juice" and mango.category.parent.name == "Drinks"
    assert Decimal(r.data["applied"]["value_added"]) == Decimal(10 * 4000 + 30 * 1500)
    assert balanced(ll.organization)


def test_stock_count_mode_sets_quantities(demo, client_for):
    ll, sugar, oil = demo["ll"], demo["sugar"], demo["oil"]
    c = client_for("ll_store", ll)
    r = upload(c, xlsx([(sugar.sku, "", "", "", "", "", 7), (oil.sku, "", "", "", "", "", "")], ), mode="set")
    assert r.data["rows"][1]["errors"] == ["Quantity is missing"]
    r = upload(c, xlsx([(sugar.sku, "", "", "", "", "", 7), (oil.sku, "", "", "", "", "", on_hand(ll, oil))]),
               mode="set", apply=True)
    assert r.status_code == 200 and r.data["applied"]["items_changed"] == 1  # oil already right
    assert on_hand(ll, sugar) == 7
    assert balanced(ll.organization)


def test_barcodes_csv_and_bad_files(demo, client_for):
    ll, sugar = demo["ll"], demo["sugar"]
    sugar.barcode = "012345678905"
    sugar.save(update_fields=["barcode"])
    c = client_for("ll_store", ll)
    csv_file = SimpleUploadedFile("count.csv", b"Barcode,Quantity\n0012345678905,3\n")  # EAN-13 form of the UPC
    r = upload(c, csv_file, mode="set")
    assert r.status_code == 200 and r.data["rows"][0]["product"] == sugar.pk and r.data["rows"][0]["after"] == "3"
    assert upload(c, SimpleUploadedFile("old.xls", b"x")).status_code == 400
    assert upload(c, SimpleUploadedFile("x.xlsx", b"not a workbook")).status_code == 400
    assert upload(c, xlsx([("A", 1)], header=("Name", "Price"))).status_code == 400  # no SKU/Qty columns
    assert upload(client_for("ll_cash1", ll), xlsx([(sugar.sku, "", "", "", "", "", 1)])).status_code == 403
