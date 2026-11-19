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


def test_admin_pages_wear_the_shop_brand(demo, client_for):
    from apps.core.models import Branding
    b = Branding.objects.get(organization__code="demo")
    b.primary_color = "#ffd400"  # a pale yellow: must be made readable, not used raw for links
    b.save()
    r = Client().get("/admin/login/")
    html = r.content.decode()
    assert r.status_code == 200 and "Aden Shop" in html and "Sign in to the database admin" in html
    c, _ = login("owner")
    page = c.get("/admin/").content.decode()
    assert "Database admin" in page and "Back office" in page and "#ffd400" in page  # button fill keeps the brand
    from apps.core.admin_theme import contrast, readable
    assert contrast(readable("#ffd400", "light")["ink"], "#ffffff") >= 4.5
    assert contrast(readable("#0f766e", "dark")["ink"], "#131920") >= 4.5


def test_signed_in_from_the_pos_without_a_second_password(demo, client_for):
    api = client_for("owner")
    r = api.post("/api/admin-handoff/")
    assert r.status_code == 200 and r.data["path"].startswith("/admin/handoff/?t=")
    browser = Client()
    resp = browser.get(r.data["path"])
    assert resp.status_code == 302 and resp["Location"] == "/admin/"
    assert browser.get("/admin/").status_code == 200
    # One use only.
    assert "expired" in Client().get(r.data["path"])["Location"]
    # Not for branch admins or cashiers.
    assert client_for("ll_admin").post("/api/admin-handoff/").status_code == 403
    assert client_for("ll_cash1").post("/api/admin-handoff/").status_code == 403
