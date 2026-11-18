from datetime import date

import pytest

from apps.accounting.models import Account
from apps.hr.models import Employee
from apps.inventory.models import StockLevel

from .conftest import sale_body

pytestmark = pytest.mark.django_db


def test_cashier_is_confined_to_own_branch(demo, client_for):
    c = client_for("ll_cash1")
    assert c.get("/api/stock-levels/", HTTP_X_BRANCH_ID=str(demo["bt"].pk)).status_code == 403
    bt_till = demo["bt"].tills.first()
    assert c.post("/api/till-sessions/", {"till": bt_till.pk}, format="json").status_code == 400
    # No inventory.view for cashiers
    assert c.get("/api/stock-levels/", HTTP_X_BRANCH_ID=str(demo["ll"].pk)).data["count"] == 0


def test_cashier_sees_only_own_sales_supervisor_sees_branch(demo, open_session, client_for):
    c, _ = open_session("ll_cash1")
    c.post("/api/sales/", sale_body(demo, 1), format="json")
    c2, _ = open_session("ll_super", till=demo["ll"].tills.get(code="t2"))
    c2.post("/api/sales/", sale_body(demo, 1), format="json")
    assert c.get("/api/sales/").data["count"] == 1
    assert c2.get("/api/sales/").data["count"] == 2
    assert client_for("bt_super").get("/api/sales/").data["count"] == 0
    assert client_for("owner").get("/api/sales/").data["count"] == 2


def test_branch_admin_cannot_grant_org_roles(demo, client_for):
    from apps.accounts.models import Role, User
    c = client_for("ll_admin")
    target = User.objects.get(username="ll_cash1")
    org_admin = Role.objects.get(name="Organization Admin")
    r = c.post(f"/api/users/{target.pk}/assign_role/", {"role": org_admin.pk}, format="json")
    assert r.status_code == 403
    sup = Role.objects.get(name="Supervisor")
    assert c.post(f"/api/users/{target.pk}/assign_role/", {"role": sup.pk, "branch": demo["bt"].pk},
                  format="json").status_code == 403
    assert c.post(f"/api/users/{target.pk}/assign_role/", {"role": sup.pk, "branch": demo["ll"].pk},
                  format="json").status_code == 201


def test_stock_transfer_between_branches(demo, client_for):
    store = client_for("ll_store", demo["ll"])
    r = store.post("/api/transfers/", {"from_branch": demo["ll"].pk, "to_branch": demo["bt"].pk,
                                       "lines": [{"product": demo["oil"].pk, "quantity": "10"}]}, format="json")
    assert r.status_code == 201, r.data
    tid = r.data["id"]
    assert store.post(f"/api/transfers/{tid}/send/").status_code == 200
    assert store.post(f"/api/transfers/{tid}/receive/").status_code == 403  # only Blantyre can receive
    assert client_for("bt_admin").post(f"/api/transfers/{tid}/receive/").status_code == 200
    assert StockLevel.objects.get(branch=demo["ll"], product=demo["oil"]).quantity == 90
    assert StockLevel.objects.get(branch=demo["bt"], product=demo["oil"]).quantity == 110


def test_purchase_order_receive_updates_avg_cost(demo, client_for):
    from apps.inventory.models import Supplier
    sup = Supplier.objects.create(organization=demo["ll"].organization, name="Wholesaler")
    c = client_for("ll_admin", demo["ll"])
    r = c.post("/api/purchase-orders/", {"supplier": sup.pk, "lines": [
        {"product": demo["sugar"].pk, "quantity": "100", "unit_cost": "4600"}]}, format="json")
    assert r.status_code == 201, r.data
    line_id = r.data["lines"][0]["id"]
    r = c.post(f"/api/purchase-orders/{r.data['id']}/receive/", {"lines": {str(line_id): "100"}}, format="json")
    assert r.status_code == 200 and r.data["status"] == "received"
    lvl = StockLevel.objects.get(branch=demo["ll"], product=demo["sugar"])
    assert lvl.quantity == 200 and lvl.avg_cost == 4400


def test_stock_adjustment_requires_reason_and_permission(demo, client_for):
    cashier = client_for("ll_cash1", demo["ll"])
    assert cashier.post("/api/inventory/adjust/", {"product": demo["oil"].pk, "counted_quantity": "95",
                                                   "reason": "count"}, format="json").status_code == 403
    store = client_for("ll_store", demo["ll"])
    r = store.post("/api/inventory/adjust/", {"product": demo["oil"].pk, "counted_quantity": "95",
                                              "reason": "breakage"}, format="json")
    assert r.status_code == 200 and r.data["quantity"] == "-5.000"


def test_trial_balance_scopes(demo, open_session, client_for):
    c, _ = open_session()
    c.post("/api/sales/", sale_body(demo, 2), format="json")
    org_tb = client_for("accounts").get("/api/reports/trial-balance/").data
    assert org_tb["total_debit"] == org_tb["total_credit"]
    assert client_for("ll_cash1").get("/api/reports/trial-balance/").status_code == 403
    assert client_for("ll_admin").get("/api/reports/trial-balance/").status_code == 403


def test_expense_needs_a_second_person(demo, client_for):
    org = demo["ll"].organization
    rent = Account.objects.get(organization=org, code="6200")
    cash = Account.objects.get(organization=org, system_key="cash")
    acc = client_for("accounts", demo["ll"])
    r = acc.post("/api/accounting/expenses/", {"expense_account": rent.pk, "paid_from": cash.pk, "amount": "250000",
                                               "date": "2026-11-18", "description": "November rent"}, format="json")
    assert r.status_code == 201, r.data
    assert acc.post(f"/api/accounting/expenses/{r.data['id']}/approve/").status_code == 403
    owner = client_for("owner", demo["ll"])
    assert owner.post(f"/api/accounting/expenses/{r.data['id']}/approve/").data["status"] == "approved"


def test_leave_flow(demo, client_for):
    from apps.accounts.models import User
    cashier = User.objects.get(username="ll_cash1")
    emp = Employee.objects.create(organization=demo["ll"].organization, branch=demo["ll"], user=cashier,
                                  employee_number="E001", first_name="L", last_name="C", hire_date=date(2025, 1, 6))
    c = client_for("ll_cash1")
    r = c.post("/api/hr/leave/", {"employee": emp.pk, "leave_type": "annual", "start_date": "2026-12-01",
                                  "end_date": "2026-12-05", "days": "5"}, format="json")
    assert r.status_code == 201, r.data
    assert c.post(f"/api/hr/leave/{r.data['id']}/approve/").status_code == 403
    assert client_for("hr").post(f"/api/hr/leave/{r.data['id']}/approve/").data["status"] == "approved"


def test_payment_method_config_rejects_secrets(demo, client_for):
    c = client_for("owner")
    r = c.post("/api/payment-methods/", {"name": "X", "kind": "mobile_money", "provider": "airtel_money",
                                         "config": {"client_secret": "abc"}}, format="json")
    assert r.status_code == 400


def test_pos_catalog_for_offline_use(demo, client_for):
    data = client_for("ll_cash1", demo["ll"]).get("/api/pos/catalog/").data
    sugar = next(p for p in data["products"] if p["sku"] == "SUG-2KG")
    assert sugar["price"] == "5500.00" and sugar["stock"] == "100.000"
    assert any(m["name"] == "Cash" and m["allowed_offline"] for m in data["payment_methods"])
