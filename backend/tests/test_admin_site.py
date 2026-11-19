import pytest
from django.test import Client

from apps.accounts.models import Membership, Role, User

pytestmark = pytest.mark.django_db
PASSWORD = "demo-pass-2026"


def login(username):
    c = Client()
    return c, c.post("/admin/login/?next=/admin/", {"username": username, "password": PASSWORD})


def test_root_of_the_api_port_opens_the_admin_sign_in(demo):
    r = Client().get("/")
    assert r.status_code == 302 and r["Location"] == "/admin/"


def test_org_admin_given_in_the_app_can_sign_in_and_loses_it_with_the_role(demo):
    u = User.objects.get(username="ll_admin")
    _, r = login("ll_admin")  # branch admin: not for the database admin site
    assert r.status_code == 200 and b"Only organization admins" in r.content
    role = Role.objects.get(organization=u.organization, name="Organization Admin")
    m = Membership.objects.create(user=u, role=role, branch=None)
    u.refresh_from_db()
    assert u.is_staff and u.is_superuser
    c, r = login("ll_admin")
    assert r.status_code == 302 and c.get("/admin/").status_code == 200
    m.is_active = False
    m.save()
    u.refresh_from_db()
    assert not u.is_staff and not u.is_superuser
    _, r = login("ll_admin")
    assert b"Only organization admins" in r.content


def test_wrong_password_is_said_plainly(demo):
    c = Client()
    r = c.post("/admin/login/", {"username": "owner", "password": "nope"})
    assert b"Wrong username or password" in r.content
