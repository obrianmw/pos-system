import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership, Role, User
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db

STRONG = "Kalulu-Lake-2026!"


def uid(name):
    return User.objects.get(username=name).pk


def role(name):
    return Role.objects.get(name=name).pk


def test_branch_admin_edits_own_staff(demo, client_for):
    c = client_for("ll_admin")
    r = c.patch(f"/api/users/{uid('ll_cash1')}/", {"first_name": "Chisomo", "phone": "0991000111"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["first_name"] == "Chisomo" and r.data["can_edit"] is True
    log = AuditLog.objects.get(action="user.updated")
    assert log.data["first_name"] == ["Lilongwe", "Chisomo"]


def test_branch_admin_cannot_touch_powerful_or_other_branch_accounts(demo, client_for):
    c = client_for("ll_admin")
    # The org admin is not in a branch admin's list at all; Blantyre staff neither.
    assert c.patch(f"/api/users/{uid('owner')}/", {"password": STRONG}, format="json").status_code in (403, 404)
    assert c.patch(f"/api/users/{uid('bt_cash1')}/", {"first_name": "x"}, format="json").status_code == 404
    # Someone who also works in Blantyre is visible but not editable by the Lilongwe admin.
    Membership.objects.create(user_id=uid("ll_super"), role_id=role("Cashier"), branch=demo["bt"])
    row = next(u for u in c.get("/api/users/").data["results"] if u["username"] == "ll_super")
    assert row["can_edit"] is False
    assert c.patch(f"/api/users/{uid('ll_super')}/", {"first_name": "x"}, format="json").status_code == 403


def test_password_reset_uses_strength_rules(demo, client_for):
    c = client_for("ll_admin")
    weak = c.patch(f"/api/users/{uid('ll_cash1')}/", {"password": "password1"}, format="json")
    assert weak.status_code == 400 and "password" in weak.data
    assert c.patch(f"/api/users/{uid('ll_cash1')}/", {"password": STRONG}, format="json").status_code == 200
    login = APIClient().post("/api/auth/token/", {"username": "ll_cash1", "password": STRONG}, format="json")
    assert login.status_code == 200
    assert AuditLog.objects.filter(action="user.password_reset").exists()
    assert "password" not in str(AuditLog.objects.get(action="user.password_reset").data).lower().replace("user", "")


def test_supervisor_pin_set_and_clear(demo, client_for):
    c = client_for("owner")
    pid = uid("ll_cash1")
    assert c.patch(f"/api/users/{pid}/", {"supervisor_pin": "12"}, format="json").status_code == 400
    assert c.patch(f"/api/users/{pid}/", {"supervisor_pin": "5791"}, format="json").data["has_supervisor_pin"] is True
    assert User.objects.get(pk=pid).check_supervisor_pin("5791")
    assert c.patch(f"/api/users/{pid}/", {"supervisor_pin": ""}, format="json").data["has_supervisor_pin"] is False


def test_deactivate_blocks_login_and_no_self_lockout(demo, client_for):
    owner = client_for("owner")
    r = owner.patch(f"/api/users/{uid('ll_cash1')}/", {"is_active": False}, format="json")
    assert r.status_code == 200 and r.data["is_active"] is False
    assert APIClient().post("/api/auth/token/", {"username": "ll_cash1", "password": "demo-pass-2026"},
                            format="json").status_code == 401
    assert owner.patch(f"/api/users/{uid('owner')}/", {"is_active": False}, format="json").status_code == 400


def test_users_are_never_deleted(demo, client_for):
    assert client_for("owner").delete(f"/api/users/{uid('ll_cash1')}/").status_code == 405


def test_create_user_rules(demo, client_for):
    c = client_for("ll_admin")
    base = {"username": "ll_cash2", "first_name": "New", "last_name": "Cashier", "password": STRONG}
    assert c.post("/api/users/", base, format="json").status_code == 400  # branch admin must give a role
    assert c.post("/api/users/", {**base, "role": role("Cashier"), "branch": demo["bt"].pk},
                  format="json").status_code == 403
    assert c.post("/api/users/", {**base, "role": role("Organization Admin")}, format="json").status_code == 403
    r = c.post("/api/users/", {**base, "role": role("Cashier"), "branch": demo["ll"].pk}, format="json")
    assert r.status_code == 201, r.data
    assert [m["role_name"] for m in r.data["memberships"]] == ["Cashier"]
    dup = c.post("/api/users/", {**base, "role": role("Cashier"), "branch": demo["ll"].pk}, format="json")
    assert dup.status_code == 400 and "already exists" in str(dup.data["username"])
    # Org admins may create without a role (e.g. head-office staff set up later).
    assert client_for("owner").post("/api/users/", {**base, "username": "hq_clerk"}, format="json").status_code == 201


def test_change_branch_and_reassign_removed_role(demo, client_for):
    c = client_for("owner")
    pid = uid("ll_cash1")
    m = Membership.objects.get(user_id=pid, branch=demo["ll"])
    assert c.post(f"/api/users/{pid}/revoke_role/", {"membership_id": m.pk}, format="json").status_code == 204
    assert c.post(f"/api/users/{pid}/assign_role/", {"role": role("Cashier"), "branch": demo["bt"].pk},
                  format="json").status_code == 201
    # Giving back a role that was removed earlier used to crash; it is switched back on instead.
    r = c.post(f"/api/users/{pid}/assign_role/", {"role": role("Cashier"), "branch": demo["ll"].pk}, format="json")
    assert r.status_code == 201
    assert Membership.objects.filter(user_id=pid, is_active=True).count() == 2
    dup = c.post(f"/api/users/{pid}/assign_role/", {"role": role("Cashier"), "branch": demo["ll"].pk}, format="json")
    assert dup.status_code == 400


def test_admin_cannot_remove_own_admin_role(demo, client_for):
    m = Membership.objects.get(user_id=uid("ll_admin"))
    r = client_for("ll_admin").post(f"/api/users/{uid('ll_admin')}/revoke_role/", {"membership_id": m.pk}, format="json")
    assert r.status_code == 400 and Membership.objects.get(pk=m.pk).is_active
