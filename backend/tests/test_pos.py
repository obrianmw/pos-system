import uuid
from decimal import Decimal
from unittest import mock

import pytest

from apps.accounting.models import JournalLine
from apps.accounting.services import trial_balance
from apps.inventory.models import StockLevel
from apps.payments.providers import ProviderResult
from apps.payments.providers.mobile_money import AirtelMoneyProvider
from apps.sales.models import OverrideApproval, Sale

from .conftest import sale_body

pytestmark = pytest.mark.django_db


def stock(branch, product):
    return StockLevel.objects.get(branch=branch, product=product).quantity


def assert_books_balance(org):
    rows = trial_balance(org)
    assert sum(r["debit"] for r in rows) == sum(r["credit"] for r in rows)
    for entry_id in JournalLine.objects.values_list("entry", flat=True).distinct():
        lines = JournalLine.objects.filter(entry=entry_id)
        assert sum(l.debit for l in lines) == sum(l.credit for l in lines), entry_id


def test_me_reports_branch_permissions(demo, client_for):
    data = client_for("ll_cash1").get("/api/me/").data
    assert [b["code"] for b in data["branches"]] == ["ll"]
    assert "pos.sell" in data["branches"][0]["permissions"]
    assert "pos.price_override" not in data["branches"][0]["permissions"]
    owner = client_for("owner").get("/api/me/").data
    assert {b["code"] for b in owner["branches"]} == {"ll", "bt"}


def test_cash_sale_moves_stock_and_posts_balanced_journal(demo, open_session):
    c, sid = open_session()
    body = sale_body(demo, qty=2)
    body["payments"][0]["tendered"] = "20000"
    r = c.post("/api/sales/", body, format="json")
    assert r.status_code == 201, r.data
    assert r.data["status"] == "completed"
    assert r.data["total"] == "11000.00"
    assert r.data["payments"][0]["change"] == "9000.00"
    # VAT inclusive 16.5%: 11000 * 16.5 / 116.5
    assert r.data["tax_total"] == "1557.94"
    assert stock(demo["ll"], demo["sugar"]) == 98
    assert stock(demo["bt"], demo["sugar"]) == 100
    assert_books_balance(demo["ll"].organization)


def test_payments_must_cover_total_online(demo, open_session):
    c, _ = open_session()
    r = c.post("/api/sales/", sale_body(demo, qty=2, pay="5000"), format="json")
    assert r.status_code == 400
    assert stock(demo["ll"], demo["sugar"]) == 100  # rolled back


def test_cannot_oversell_online(demo, open_session):
    c, _ = open_session()
    r = c.post("/api/sales/", sale_body(demo, qty=101), format="json")
    assert r.status_code == 400
    assert "in stock" in r.data["detail"]


def test_price_override_needs_supervisor_pin(demo, open_session):
    c, _ = open_session()
    r = c.post("/api/sales/", sale_body(demo, qty=1, unit_price=5000), format="json")
    assert r.status_code == 409 and r.data["code"] == "override_required"

    bad = {"supervisor": "ll_super", "pin": "0000", "reason": "loyal customer"}
    assert c.post("/api/sales/", sale_body(demo, 1, 5000, override=bad), format="json").status_code == 409

    # A Blantyre supervisor has no authority in Lilongwe.
    other = {"supervisor": "bt_super", "pin": "2468", "reason": "x"}
    assert c.post("/api/sales/", sale_body(demo, 1, 5000, override=other), format="json").status_code == 409

    good = {"supervisor": "ll_super", "pin": "2468", "reason": "damaged packaging"}
    r = c.post("/api/sales/", sale_body(demo, 1, 5000, override=good), format="json")
    assert r.status_code == 201, r.data
    appr = OverrideApproval.objects.get(sale__number=r.data["number"])
    assert appr.method == "pin" and appr.approved_by.username == "ll_super" and appr.new_value == Decimal("5000")


def test_floor_price_blocks_even_supervisors(demo, open_session):
    c, _ = open_session("ll_super")
    r = c.post("/api/sales/", sale_body(demo, 1, 4000), format="json")  # cost/min price is 4200
    assert r.status_code == 400


def test_discount_limit(demo, open_session):
    c, _ = open_session()
    # 5% of 11000 = 550 is within the cashier limit
    assert c.post("/api/sales/", sale_body(demo, 2, discount=550), format="json").status_code == 201
    assert c.post("/api/sales/", sale_body(demo, 2, discount=1000), format="json").status_code == 409


def test_remote_override_approval_is_single_use(demo, open_session, client_for):
    c, _ = open_session()
    r = c.post("/api/overrides/", {"kind": "price", "product": demo["sugar"].pk, "original_value": "5500",
                                   "new_value": "5000", "reason": "price match"}, format="json")
    assert r.status_code == 201, r.data
    aid = r.data["id"]
    # The requester cannot approve; a cashier cannot approve.
    assert c.post(f"/api/overrides/{aid}/approve/").status_code in (403, 404)
    sup = client_for("ll_super", demo["ll"])
    assert sup.post(f"/api/overrides/{aid}/approve/").status_code == 200

    body = sale_body(demo, 1, 5000, override={"approval_id": aid})
    assert c.post("/api/sales/", body, format="json").status_code == 201
    body2 = sale_body(demo, 1, 5000, override={"approval_id": aid})
    assert c.post("/api/sales/", body2, format="json").status_code == 409


def test_offline_sync_is_idempotent_and_flags_unverified(demo, open_session):
    c, sid = open_session()
    good = sale_body(demo, 1, till_session=sid, client_created_at="2026-11-18T09:00:00+02:00")
    bad_override = sale_body(demo, 1, 4500, override={"supervisor": "ll_super", "pin": "9999"}, till_session=sid)
    r = c.post("/api/sales/sync/", {"sales": [good, bad_override]}, format="json")
    assert all(x["ok"] for x in r.data["results"]), r.data
    assert r.data["results"][1]["needs_review"] is True
    # Resend (till never got the response): no duplicates.
    r2 = c.post("/api/sales/sync/", {"sales": [good, bad_override]}, format="json")
    assert all(x["duplicate"] for x in r2.data["results"])
    assert Sale.objects.filter(created_offline=True).count() == 2
    assert stock(demo["ll"], demo["sugar"]) == 98
    assert_books_balance(demo["ll"].organization)


def test_offline_number_collision_is_renumbered(demo, open_session):
    c, sid = open_session()
    a = sale_body(demo, 1, till_session=sid, number="LL-T1-OFF00001")
    b = sale_body(demo, 1, till_session=sid, number="LL-T1-OFF00001")
    r = c.post("/api/sales/sync/", {"sales": [a, b]}, format="json")
    assert all(x["ok"] for x in r.data["results"]), r.data
    assert r.data["results"][1]["needs_review"] and r.data["results"][1]["number"] != "LL-T1-OFF00001"


def test_offline_sale_can_go_negative_stock(demo, open_session):
    c, sid = open_session()
    r = c.post("/api/sales/sync/", {"sales": [sale_body(demo, 105, till_session=sid)]}, format="json")
    assert r.data["results"][0]["ok"]
    assert stock(demo["ll"], demo["sugar"]) == -5


def test_refund_requires_supervisor_and_limits_quantity(demo, open_session):
    c, _ = open_session()
    sale = c.post("/api/sales/", sale_body(demo, 3), format="json").data
    line_id = sale["lines"][0]["id"]
    body = {"lines": [{"line_id": line_id, "quantity": "2"}], "method_id": demo["cash"].pk, "reason": "expired"}
    assert c.post(f"/api/sales/{sale['id']}/refund/", body, format="json").status_code == 409
    body["override"] = {"supervisor": "ll_super", "pin": "2468"}
    r = c.post(f"/api/sales/{sale['id']}/refund/", body, format="json")
    assert r.status_code == 201, r.data
    assert r.data["total"] == "11000.00"
    assert stock(demo["ll"], demo["sugar"]) == 99
    # Only 1 left to return
    r = c.post(f"/api/sales/{sale['id']}/refund/", body, format="json")
    assert r.status_code == 400
    assert_books_balance(demo["ll"].organization)


def test_void_restores_stock_and_reverses_books(demo, open_session):
    c, _ = open_session()
    sale = c.post("/api/sales/", sale_body(demo, 4), format="json").data
    r = c.post(f"/api/sales/{sale['id']}/void/", {"reason": "rang wrong item",
                                                   "override": {"supervisor": "ll_super", "pin": "2468"}},
               format="json")
    assert r.status_code == 200 and r.data["status"] == "voided"
    assert stock(demo["ll"], demo["sugar"]) == 100
    sales_acct = [x for x in trial_balance(demo["ll"].organization, demo["ll"]) if x["code"] == "4000"]
    assert not sales_acct or (sales_acct[0]["debit"] == sales_acct[0]["credit"] == 0)


def test_till_close_computes_variance(demo, open_session):
    c, sid = open_session(float_amount="10000")  # float handed over from the vault
    c.post("/api/sales/", sale_body(demo, 2), format="json")  # +11000 cash
    r = c.post(f"/api/till-sessions/{sid}/close/", {"counted_cash": "20500"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["expected_cash"] == "21000.00"
    assert r.data["variance"] == "-500.00"
    assert_books_balance(demo["ll"].organization)
    # Till can be opened again by the next shift.
    assert c.post("/api/till-sessions/", {"till": demo["till"].pk}, format="json").status_code == 201


def test_one_open_session_per_till(demo, open_session, client_for):
    open_session()
    c = client_for("ll_super", demo["ll"])
    r = c.post("/api/till-sessions/", {"till": demo["till"].pk}, format="json")
    assert r.status_code == 400


def test_mobile_money_pending_then_confirmed_via_callback(demo, open_session):
    c, _ = open_session()
    body = sale_body(demo, 1, method=demo["airtel"])
    body["payments"][0].pop("tendered")
    body["payments"][0]["phone"] = "0991234567"
    with mock.patch.object(AirtelMoneyProvider, "initiate", return_value=ProviderResult("pending", "", "approve")):
        r = c.post("/api/sales/", body, format="json")
    assert r.status_code == 201 and r.data["status"] == "pending_payment"
    payment = r.data["payments"][0]

    # A forged callback cannot complete the sale: we ask the provider, which says still pending.
    cb = {"transaction": {"id": payment["client_reference"], "status_code": "TS"}}
    with mock.patch.object(AirtelMoneyProvider, "check_status", return_value=ProviderResult("pending")):
        c.post("/api/payments/callback/airtel_money/", cb, format="json")
    assert Sale.objects.get(pk=r.data["id"]).status == "pending_payment"

    with mock.patch.object(AirtelMoneyProvider, "check_status",
                           return_value=ProviderResult("confirmed", "AM123", "ok")):
        anon = __import__("rest_framework.test", fromlist=["APIClient"]).APIClient()
        assert anon.post("/api/payments/callback/airtel_money/", cb, format="json").status_code == 200
    sale = Sale.objects.get(pk=r.data["id"])
    assert sale.status == "completed"
    assert sale.payments.get().provider_reference == "AM123"
    assert_books_balance(demo["ll"].organization)


def test_failed_wallet_payment_can_be_replaced_with_cash(demo, open_session):
    c, _ = open_session()
    body = sale_body(demo, 1, method=demo["airtel"])
    body["payments"][0].pop("tendered")
    with mock.patch.object(AirtelMoneyProvider, "initiate", return_value=ProviderResult("failed", message="no funds")):
        sale = c.post("/api/sales/", body, format="json").data
    assert sale["status"] == "pending_payment"
    r = c.post(f"/api/sales/{sale['id']}/add_payment/", {"method_id": demo["cash"].pk, "amount": "5500"},
               format="json")
    assert r.status_code == 200 and r.data["status"] == "completed", r.data


def test_cancel_pending_sale_returns_stock(demo, open_session):
    c, _ = open_session()
    body = sale_body(demo, 3, method=demo["airtel"])
    with mock.patch.object(AirtelMoneyProvider, "initiate", return_value=ProviderResult("pending")):
        sale = c.post("/api/sales/", body, format="json").data
    assert stock(demo["ll"], demo["sugar"]) == 97
    r = c.post(f"/api/sales/{sale['id']}/cancel/", {"reason": "customer left"}, format="json")
    assert r.data["status"] == "cancelled"
    assert stock(demo["ll"], demo["sugar"]) == 100
