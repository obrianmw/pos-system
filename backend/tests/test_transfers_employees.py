from datetime import date

import pytest

from apps.accounts.models import Role, User
from apps.catalog.models import Product
from apps.core.models import AuditLog
from apps.hr.models import Employee
from apps.inventory.models import StockLevel

pytestmark = pytest.mark.django_db


def _trf(demo, **over):
    return {"from_branch": demo["ll"].pk, "to_branch": demo["bt"].pk,
            "lines": [{"product": demo["oil"].pk, "quantity": "10"}], **over}


def test_transfer_validation(demo, client_for):
    c = client_for("ll_store")
    assert c.post("/api/transfers/", _trf(demo, to_branch=demo["ll"].pk), format="json").status_code == 400
    assert c.post("/api/transfers/", _trf(demo, lines=[]), format="json").status_code == 400
    airtime = Product.objects.get(sku="AIRTIME-1K")
    assert c.post("/api/transfers/", _trf(demo, lines=[{"product": airtime.pk, "quantity": "1"}]),
                  format="json").status_code == 400
    # Lilongwe storekeeper cannot send from Blantyre
    assert c.post("/api/transfers/", _trf(demo, from_branch=demo["bt"].pk, to_branch=demo["ll"].pk),
                  format="json").status_code == 403
    r = c.post("/api/transfers/", _trf(demo), format="json")
    assert r.status_code == 201 and r.data["lines"][0]["product_name"] == "Cooking oil 2L"
    assert c.patch(f"/api/transfers/{r.data['id']}/", {"note": "x"}, format="json").status_code == 405


def test_send_more_than_in_stock_is_refused(demo, client_for):
    c = client_for("ll_store")
    t = c.post("/api/transfers/", _trf(demo, lines=[{"product": demo["oil"].pk, "quantity": "500"}]), format="json").data
    r = c.post(f"/api/transfers/{t['id']}/send/")
    assert r.status_code == 400 and "in stock" in str(r.data)
    assert StockLevel.objects.get(branch=demo["ll"], product=demo["oil"]).quantity == 100


def test_value_fixed_at_send_and_cancel_rules(demo, client_for):
    c = client_for("ll_store")
    t = c.post("/api/transfers/", _trf(demo), format="json").data
    assert t["value"] == "0.00"  # cost known only once sent
    sent = c.post(f"/api/transfers/{t['id']}/send/").data
    assert sent["value"] == "98000.00"  # 10 x 9800 average cost
    assert c.post(f"/api/transfers/{t['id']}/cancel/").status_code == 400  # in transit
    t2 = c.post("/api/transfers/", _trf(demo), format="json").data
    assert client_for("bt_admin").post(f"/api/transfers/{t2['id']}/cancel/").status_code == 403  # receiver can't
    assert c.post(f"/api/transfers/{t2['id']}/cancel/").data["status"] == "cancelled"
    assert AuditLog.objects.filter(action="transfer.cancelled").count() == 1


def test_branch_filter_shows_in_and_out(demo, client_for):
    c = client_for("ll_store")
    c.post("/api/transfers/", _trf(demo), format="json")
    owner = client_for("owner")
    assert owner.get("/api/transfers/", HTTP_X_BRANCH_ID=str(demo["bt"].pk)).data["count"] == 1  # incoming
    assert owner.get("/api/transfers/", HTTP_X_BRANCH_ID=str(demo["ll"].pk)).data["count"] == 1  # outgoing


# ---------------------------------------------------------------------------------------- employees
EMP = {"first_name": "Chikondi", "last_name": "Banda", "hire_date": "2025-03-01", "job_title": "Cashier",
       "basic_salary": "250000", "bank_account": "1234567", "national_id": "AB12CD34"}


def _give_branch_hr(username, branch):
    from apps.accounts.models import Membership
    role = Role.objects.get(name="Branch HR")
    Membership.objects.create(user=User.objects.get(username=username), role=role, branch=branch)


def test_auto_number_and_duplicate_number(demo, client_for):
    hr = client_for("hr")
    a = hr.post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk}, format="json")
    assert a.status_code == 201, a.data
    assert a.data["employee_number"] == "E0001"
    b = hr.post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk, "employee_number": "e0001"}, format="json")
    assert b.status_code == 400 and "Chikondi" in str(b.data)


def test_salary_hidden_from_branch_admin(demo, client_for):
    client_for("hr").post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk}, format="json")
    row = client_for("ll_admin").get("/api/hr/employees/").data["results"][0]
    assert row["first_name"] == "Chikondi" and row["can_manage"] is False
    assert "basic_salary" not in row and "bank_account" not in row and "national_id" not in row
    full = client_for("hr").get("/api/hr/employees/").data["results"][0]
    assert full["basic_salary"] == "250000.00" and full["can_manage"] is True


def test_branch_hr_scope(demo, client_for):
    _give_branch_hr("ll_admin", demo["ll"])
    c = client_for("ll_admin")
    assert c.post("/api/hr/employees/", {**EMP, "branch": demo["bt"].pk}, format="json").status_code == 403
    assert c.post("/api/hr/employees/", {**EMP}, format="json").status_code == 403  # head office
    assert c.post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk}, format="json").status_code == 201


def test_link_login_and_terminate_disables_it(demo, client_for):
    from rest_framework.test import APIClient
    hr = client_for("hr")
    cashier = User.objects.get(username="ll_cash1")
    # The cashier is logged in at a till with a real token before HR terminates them.
    till = APIClient()
    token = till.post("/api/auth/token/", {"username": "ll_cash1", "password": "demo-pass-2026"}, format="json").data["access"]
    till.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert till.get("/api/me/").status_code == 200
    ids = [u["id"] for u in hr.get("/api/hr/employees/linkable_users/").data]
    assert cashier.pk in ids
    e = hr.post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk, "user": cashier.pk}, format="json").data
    assert e["username"] == "ll_cash1"
    assert cashier.pk not in [u["id"] for u in hr.get("/api/hr/employees/linkable_users/").data]
    dup = hr.post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk, "user": cashier.pk}, format="json")
    assert dup.status_code == 400
    assert hr.patch(f"/api/hr/employees/{e['id']}/", {"status": "terminated"}, format="json").status_code == 400
    r = hr.patch(f"/api/hr/employees/{e['id']}/", {"status": "terminated", "end_date": "2026-11-30"}, format="json")
    assert r.status_code == 200 and r.data["login_active"] is False
    cashier.refresh_from_db()
    assert cashier.is_active is False
    assert AuditLog.objects.filter(action="user.deactivated").exists()
    assert till.get("/api/me/").status_code == 401  # existing session stops working at once
    assert APIClient().post("/api/auth/token/", {"username": "ll_cash1", "password": "demo-pass-2026"},
                            format="json").status_code == 401  # and no new logins


def test_end_date_before_hire_rejected(demo, client_for):
    r = client_for("hr").post("/api/hr/employees/", {**EMP, "branch": demo["ll"].pk, "end_date": "2024-01-01"},
                              format="json")
    assert r.status_code == 400
    assert Employee.objects.count() == 0
    assert date(2025, 3, 1)  # keeps the import honest


def test_branch_directory_lists_all_org_branches(demo, client_for):
    names = [b["name"] for b in client_for("ll_store").get("/api/branches/directory/").data]
    assert names == ["Blantyre Limbe", "Lilongwe City Centre"]
    assert client_for("ll_store").get("/api/branches/").data["count"] == 1  # full records stay scoped
