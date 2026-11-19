from decimal import Decimal

import pytest

from apps.accounting.services import trial_balance
from apps.inventory.counts import on_hand
from apps.inventory.models import StockMovement

pytestmark = pytest.mark.django_db


def start(c, **body):
    r = c.post("/api/stock-counts/", {"title": "Shelf A", **body}, format="json")
    assert r.status_code == 201, r.data
    return r.data["id"]


def test_lookup_by_barcode_or_sku(demo, client_for):
    c = client_for("ll_count", demo["ll"])
    sugar = demo["sugar"]
    r = c.get(f"/api/stock/lookup/?code={sugar.sku.lower()}")
    assert r.status_code == 200 and r.data["name"] == sugar.name
    assert [b["name"] for b in r.data["branches"]] == ["Lilongwe City Centre"]  # only branches they work at
    if sugar.barcode:
        assert c.get(f"/api/stock/lookup/?code={sugar.barcode}").data["id"] == sugar.pk
    assert c.get("/api/stock/lookup/?code=NOPE-404").status_code == 404


def test_blind_count_scan_submit_verify_post(demo, client_for):
    ll, sugar, oil = demo["ll"], demo["sugar"], demo["oil"]
    before_sugar, before_oil = on_hand(ll, sugar), on_hand(ll, oil)
    counter = client_for("ll_count", ll)
    cid = start(counter)
    # Scanning adds one each time; typing a total sets it.
    for _ in range(3):
        r = counter.post(f"/api/stock-counts/{cid}/scan/", {"code": sugar.sku}, format="json")
        assert r.status_code == 201
    assert r.data["line"]["counted_qty"] == "3.000" and r.data["line"]["expected_qty"] is None  # blind
    counter.post(f"/api/stock-counts/{cid}/scan/", {"product": oil.pk, "qty": str(before_oil), "mode": "set"}, format="json")
    assert counter.post(f"/api/stock-counts/{cid}/scan/", {"code": "nope"}, format="json").status_code == 404
    d = counter.get(f"/api/stock-counts/{cid}/").data
    assert d["can_verify"] is False and all(l["variance"] is None for l in d["lines"])
    assert counter.post(f"/api/stock-counts/{cid}/approve/").status_code == 403  # counters can't verify
    assert counter.post(f"/api/stock-counts/{cid}/submit/").data["status"] == "submitted"
    assert counter.post(f"/api/stock-counts/{cid}/scan/", {"code": sugar.sku}, format="json").status_code == 400

    verifier = client_for("ll_verify", ll)
    d = verifier.get(f"/api/stock-counts/{cid}/").data
    assert d["can_verify"] is True and d["summary"]["differences"] >= 1
    sugar_line = next(l for l in d["lines"] if l["product"] == sugar.pk)
    assert Decimal(sugar_line["expected_qty"]) == before_sugar
    # Verifier recounts sugar: actually 4 on the shelf.
    verifier.post(f"/api/stock-counts/{cid}/recount/", {"line": sugar_line["id"], "qty": "4"}, format="json")
    r = verifier.post(f"/api/stock-counts/{cid}/approve/")
    assert r.status_code == 200 and r.data["status"] == "posted"
    assert on_hand(ll, sugar) == Decimal("4") and on_hand(ll, oil) == before_oil
    mv = StockMovement.objects.get(reference=r.data["number"], product=sugar)
    assert mv.kind == "adjustment" and mv.quantity == Decimal("4") - before_sugar
    tb = trial_balance(ll.organization)
    assert sum(x["debit"] for x in tb) == sum(x["credit"] for x in tb)


def test_counter_cannot_verify_own_count_and_sales_during_count(demo, client_for, open_session):
    ll, sugar = demo["ll"], demo["sugar"]
    sup = client_for("ll_super", ll)  # supervisors can both count and verify...
    cid = start(sup)
    sup.post(f"/api/stock-counts/{cid}/scan/", {"code": sugar.sku, "qty": "10", "mode": "set"}, format="json")
    expected = on_hand(ll, sugar)
    # A sale happens after sugar was counted: the adjustment uses the difference, so it stays right.
    from .conftest import sale_body
    c, _ = open_session()
    assert c.post("/api/sales/", sale_body(demo, 2), format="json").status_code == 201
    sup.post(f"/api/stock-counts/{cid}/submit/")
    r = sup.post(f"/api/stock-counts/{cid}/approve/")
    assert r.status_code == 403 and "didn't count" in r.data["detail"]  # ...but not their own
    assert client_for("ll_verify", ll).post(f"/api/stock-counts/{cid}/approve/").status_code == 200
    assert on_hand(ll, sugar) == Decimal("10") - 2  # counted 10, minus the 2 sold since
    assert expected - 2 + (Decimal("10") - expected) == on_hand(ll, sugar)


def test_cashiers_have_no_stock_take_and_lists_filter(demo, client_for):
    assert client_for("ll_cash1", demo["ll"]).post("/api/stock-counts/", {}, format="json").status_code == 403
    c = client_for("ll_count", demo["ll"])
    a, b = start(c, title="Fridges"), start(c, title="Dry goods")
    c.post(f"/api/stock-counts/{a}/cancel/")
    res = c.get("/api/stock-counts/?status=counting&search=dry").data["results"]
    assert [x["id"] for x in res] == [b]
    assert client_for("bt_admin", demo["bt"]).get(f"/api/stock-counts/{b}/").status_code == 404


def test_any_scanner_format_finds_the_product(demo, client_for):
    sugar = demo["sugar"]
    sugar.barcode = "012345678905"  # UPC-A on the product record
    sugar.save(update_fields=["barcode"])
    c = client_for("ll_store", demo["ll"])
    for scanned in ["012345678905", "0012345678905", "]E00012345678905", "(01)00012345678905(10)LOT7",
                    "0100012345678905", "https://id.gs1.org/01/00012345678905", "]Q1" + sugar.sku]:
        r = c.get("/api/stock/lookup/", {"code": scanned})
        assert r.status_code == 200 and r.data["id"] == sugar.pk, scanned
