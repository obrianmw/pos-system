from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.services import trial_balance
from apps.accounts.models import User
from apps.cash import services as cash
from apps.cash.models import CashTransfer, VaultCustody
from apps.core.models import Till

from .conftest import sale_body

pytestmark = pytest.mark.django_db


def uid(n):
    return User.objects.get(username=n).pk


def vault_id(c, branch):
    return next(v["id"] for v in c.get("/api/cash/vaults/").data if v["branch"] == branch.pk)


def move(c, branch, **body):
    return c.post(f"/api/cash/vaults/{vault_id(c, branch)}/move/", body, format="json")


def move_confirm(c, branch, transfer, received, note=""):
    return c.post(f"/api/cash/vaults/{vault_id(c, branch)}/confirm/",
                  {"transfer": transfer, "received_amount": received, "note": note}, format="json")


def books_balance(org):
    tb = trial_balance(org)
    return sum(r["debit"] for r in tb) == sum(r["credit"] for r in tb)


# ------------------------------------------------------------------------------------------- tills
def test_till_opens_at_zero_for_assigned_users_only(demo, client_for):
    c = client_for("ll_cash1", demo["ll"])
    assert c.post("/api/till-sessions/", {"till": demo["till"].pk, "opening_float": "5000"},
                  format="json").status_code == 400
    lonely = Till.objects.create(branch=demo["ll"], name="Till 9", code="t9")
    r = c.post("/api/till-sessions/", {"till": lonely.pk}, format="json")
    assert r.status_code == 403 and "not assigned" in r.data["detail"]
    r = c.post("/api/till-sessions/", {"till": demo["till"].pk}, format="json")
    assert r.status_code == 201 and r.data["opening_float"] == "0.00"


def test_one_person_per_till_and_one_till_per_person(demo, client_for):
    cashier = client_for("ll_cash1", demo["ll"])
    t2 = demo["ll"].tills.get(code="t2")
    assert cashier.post("/api/till-sessions/", {"till": demo["till"].pk}, format="json").status_code == 201
    r = cashier.post("/api/till-sessions/", {"till": t2.pk}, format="json")
    assert r.status_code == 400 and "already have" in r.data["detail"]
    r = client_for("ll_super", demo["ll"]).post("/api/till-sessions/", {"till": demo["till"].pk}, format="json")
    assert r.status_code == 400 and "in use by" in r.data["detail"]
    tills = {t["code"]: t for t in cashier.get("/api/tills/").data["results"]}
    assert tills["t1"]["open_session"]["cashier_name"] == "Lilongwe Cashier"
    assert tills["t2"]["open_session"] is None and tills["t2"]["assigned_to_me"] is True


def test_only_admins_assign_till_users(demo, client_for):
    t2 = demo["ll"].tills.get(code="t2")
    assert client_for("ll_cash1", demo["ll"]).patch(f"/api/tills/{t2.pk}/", {"users": []},
                                                    format="json").status_code == 403
    admin = client_for("ll_admin", demo["ll"])
    # Blantyre staff can't be put on a Lilongwe till.
    assert admin.patch(f"/api/tills/{t2.pk}/", {"users": [uid("bt_cash1")]}, format="json").status_code == 400
    r = admin.patch(f"/api/tills/{t2.pk}/", {"users": [uid("ll_super")]}, format="json")
    assert r.status_code == 200 and [u["name"] for u in r.data["user_names"]] == ["Lilongwe Supervisor"]
    assert client_for("ll_cash1", demo["ll"]).post("/api/till-sessions/", {"till": t2.pk},
                                                   format="json").status_code == 403


# ------------------------------------------------------------------------------------------- vault
def test_float_sale_close_returns_everything_to_vault(demo, client_for, open_session):
    start = cash.vault_balance(demo["ll"])
    c, sid = open_session(float_amount="10000")
    assert cash.vault_balance(demo["ll"]) == start - 10000
    c.post("/api/sales/", sale_body(demo, 2), format="json")  # +11,000 cash
    r = c.post(f"/api/till-sessions/{sid}/close/", {"counted_cash": "20500"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["expected_cash"] == "21000.00" and r.data["variance"] == "-500.00"
    closing = CashTransfer.objects.get(kind="close", till_session=sid)
    assert closing.amount == Decimal("20500") and closing.status == "pending"
    # Not in the vault until the holder counts and confirms it.
    assert cash.vault_balance(demo["ll"]) == start - 10000
    sup = client_for("ll_super", demo["ll"])
    vault = sup.get("/api/cash/vaults/").data[0]
    assert vault["in_transit"] == "20500.00" and vault["pending"][0]["id"] == closing.pk
    r = move_confirm(sup, demo["ll"], closing.pk, "20500")
    assert r.status_code == 200 and r.data["pending"] == [] and r.data["in_transit"] == "0.00"
    assert cash.vault_balance(demo["ll"]) == start - 10000 + Decimal("20500")
    from apps.sales.models import TillSession
    assert cash.till_balance(TillSession.objects.get(pk=sid)) == 0  # closed with zero balance
    assert books_balance(demo["ll"].organization)


def test_only_the_vault_holder_moves_cash(demo, client_for, open_session):
    c, sid = open_session(float_amount=None)
    cashier = client_for("ll_cash1", demo["ll"])
    assert cashier.get("/api/cash/vaults/").data == []  # cashiers don't see the vault
    admin = client_for("ll_admin", demo["ll"])  # can see and assign, but doesn't hold it
    assert move(admin, demo["ll"], kind="float", amount="5000", till_session=sid).status_code == 403
    sup = client_for("ll_super", demo["ll"])
    assert move(sup, demo["ll"], kind="float", amount="999999999", till_session=sid).status_code == 400
    r = move(sup, demo["ll"], kind="float", amount="5000", till_session=sid)
    assert r.status_code == 201 and r.data["vault"]["open_tills"][0]["balance"] == "5000.00"
    # Pickup can't take more than the drawer holds.
    assert move(sup, demo["ll"], kind="pickup", amount="6000", till_session=sid).status_code == 400
    assert move(sup, demo["ll"], kind="pickup", amount="2000", till_session=sid).status_code == 201


def test_vault_to_finance_bank_and_restocking(demo, client_for):
    sup = client_for("ll_super", demo["ll"])
    assert move(sup, demo["ll"], kind="to_bank", amount="50000").status_code == 400  # needs deposit slip
    assert move(sup, demo["ll"], kind="to_bank", amount="50000", reference="NBM-1234").status_code == 201
    assert move(sup, demo["ll"], kind="to_finance", amount="20000").status_code == 400  # who received it?
    assert move(sup, demo["ll"], kind="to_finance", amount="20000", counterparty="Head Accountant").status_code == 201
    r = move(sup, demo["ll"], kind="restock", amount="30000", counterparty="Demo Wholesale", reference="INV-77")
    assert r.status_code == 201 and r.data["vault"]["balance"] == "200000.00"
    hist = sup.get("/api/cash/transfers/?kind=to_bank").data["results"]
    assert len(hist) == 1 and hist[0]["reference"] == "NBM-1234" and hist[0]["direction"] == "out"
    assert books_balance(demo["ll"].organization)


def test_holder_gets_supervisor_powers_only_while_holding(demo, client_for):
    # A fresh client per check = a fresh user per request, exactly like real token/session logins.
    perms = lambda: next(b["permissions"] for b in client_for("ll_store").get("/api/me/").data["branches"]
                         if b["code"] == "ll")
    assert "pos.void" not in perms()
    admin = client_for("ll_admin", demo["ll"])
    vid = vault_id(admin, demo["ll"])
    r = admin.post(f"/api/cash/vaults/{vid}/assign/", {"custodian": uid("ll_store")}, format="json")
    assert r.status_code == 200 and r.data["custodian"]["name"] == "Lilongwe Storekeeper"
    assert {"pos.void", "pos.refund", "pos.price_override", "vault.operate"} <= set(perms())
    # The previous holder (the supervisor) no longer has vault powers; their role still gives the rest.
    sup_perms = next(b["permissions"] for b in client_for("ll_super").get("/api/me/").data["branches"])
    assert "vault.operate" not in sup_perms and "pos.void" in sup_perms
    # Custody lapses on its own at the end of the period.
    VaultCustody.objects.filter(custodian__username="ll_store").update(valid_until=timezone.now() - timedelta(minutes=1))
    assert "pos.void" not in perms()


def test_custody_rules(demo, client_for):
    admin = client_for("ll_admin", demo["ll"])
    vid = vault_id(admin, demo["ll"])
    assert admin.post(f"/api/cash/vaults/{vid}/assign/", {"custodian": uid("bt_cash1")},
                      format="json").status_code == 400  # doesn't work at Lilongwe
    assert client_for("ll_cash1", demo["ll"]).post(f"/api/cash/vaults/{vid}/assign/", {"custodian": uid("ll_cash1")},
                                                   format="json").status_code in (403, 404)
    sup = client_for("ll_super", demo["ll"])
    assert sup.post(f"/api/cash/vaults/{vid}/release/").status_code == 200  # holder can hand it back
    sup = client_for("ll_super", demo["ll"])  # next request: no longer the holder, so not even visible
    r = sup.post(f"/api/cash/vaults/{vid}/move/", {"kind": "to_bank", "amount": "10", "reference": "x"}, format="json")
    assert r.status_code in (403, 404)


# ------------------------------------------------------------------------------- handover confirmation
def test_cash_drop_waits_for_the_vault_holder_and_books_a_shortfall(demo, client_for, open_session):
    start = cash.vault_balance(demo["ll"])
    c, sid = open_session(float_amount="10000")
    r = c.post(f"/api/till-sessions/{sid}/drop/", {"amount": "8000"}, format="json")
    assert r.status_code == 201 and r.data["status"] == "pending" and r.data["till_balance"] == "2000.00"
    assert c.post(f"/api/till-sessions/{sid}/drop/", {"amount": "9000"}, format="json").status_code == 400  # more than the drawer
    # Another cashier can't drop from this till.
    assert client_for("ll_super", demo["ll"]).post(f"/api/till-sessions/{sid}/drop/", {"amount": "1"},
                                                   format="json").status_code in (403, 404)
    drop = CashTransfer.objects.get(kind="drop", till_session=sid)
    assert cash.vault_balance(demo["ll"]) == start - 10000  # not settled yet
    sup = client_for("ll_super", demo["ll"])
    # Holder counts only 7,900: a note is required, then the 100 is booked short.
    r = move_confirm(sup, demo["ll"], drop.pk, "7900")
    assert r.status_code == 400 and "note" in r.data["detail"]
    assert move_confirm(sup, demo["ll"], drop.pk, "7900", "One 100 note missing").status_code == 200
    drop.refresh_from_db()
    assert drop.status == "settled" and drop.difference == Decimal("-100") and drop.confirmed_by.username == "ll_super"
    assert cash.vault_balance(demo["ll"]) == start - 10000 + 7900
    assert move_confirm(sup, demo["ll"], drop.pk, "7900", "again").status_code == 400  # only once
    assert books_balance(demo["ll"].organization)


def test_only_the_holder_confirms_and_not_their_own_handover(demo, client_for, open_session):
    # The supervisor holds the vault AND runs a till: their own closing must be confirmed by someone else.
    sup_c, sid = open_session(username="ll_super", float_amount=None)
    sup_c.post(f"/api/till-sessions/{sid}/close/", {"counted_cash": "0"}, format="json")
    c, sid2 = open_session(till=demo["ll"].tills.get(code="t2"), float_amount="3000")
    c.post(f"/api/till-sessions/{sid2}/drop/", {"amount": "3000"}, format="json")
    drop = CashTransfer.objects.get(kind="drop", till_session=sid2)
    admin = client_for("ll_admin", demo["ll"])  # sees the vault but doesn't hold it
    assert move_confirm(admin, demo["ll"], drop.pk, "3000").status_code == 403
    sup = client_for("ll_super", demo["ll"])
    sup_drop_sid = open_session(username="ll_super", till=demo["ll"].tills.get(code="t3"), float_amount="500")[1]
    sup.post(f"/api/till-sessions/{sup_drop_sid}/drop/", {"amount": "500"}, format="json")
    own = CashTransfer.objects.get(kind="drop", till_session=sup_drop_sid)
    r = move_confirm(sup, demo["ll"], own.pk, "500")
    assert r.status_code == 403 and "someone else" in r.data["detail"]
    assert move_confirm(sup, demo["ll"], drop.pk, "3000").status_code == 200
