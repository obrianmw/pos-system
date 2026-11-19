import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

from apps.accounts.models import User
from apps.core.security import validate_production

pytestmark = pytest.mark.django_db


def admin_client(ip, username=None, **extra):
    c = Client(REMOTE_ADDR=ip, **extra)
    if username:
        c.force_login(User.objects.get(username=username))
    return c


def test_admin_site_only_from_admin_network(demo):
    assert admin_client("127.0.0.1").get("/admin/login/").status_code == 200
    assert admin_client("::1").get("/admin/login/").status_code == 200
    r = admin_client("10.0.0.9").get("/admin/login/")
    assert r.status_code == 403 and b"Admin network only" in r.content
    # Even a logged-in org admin is refused from the shop floor network.
    assert admin_client("192.168.1.40", "owner").get("/admin/").status_code == 403
    # The POS/back-office API is not affected by the admin-network rule.
    assert admin_client("192.168.1.40").get("/api/me/").status_code in (401, 403)  # needs login, not blocked
    assert b"Admin network only" not in admin_client("192.168.1.40").get("/api/me/").content


def test_whitelisted_admin_network(demo, settings):
    settings.ADMIN_ALLOWED_NETWORKS = "127.0.0.1/32,10.20.0.0/24"
    assert admin_client("10.20.0.15", "owner").get("/admin/").status_code == 200
    assert admin_client("10.20.1.15", "owner").get("/admin/").status_code == 403


def test_forwarded_for_only_trusted_behind_proxy(demo, settings):
    settings.ADMIN_ALLOWED_NETWORKS = "10.20.0.0/24"
    # Without a trusted proxy, a client cannot claim an admin address via the header.
    spoof = admin_client("203.0.113.5", HTTP_X_FORWARDED_FOR="10.20.0.15")
    assert spoof.get("/admin/login/").status_code == 403
    settings.TRUSTED_PROXY_COUNT = 1
    via_proxy = admin_client("127.0.0.1", HTTP_X_FORWARDED_FOR="10.20.0.15")
    assert via_proxy.get("/admin/login/").status_code == 200


def test_only_org_admins_can_use_admin_site(demo):
    branch_admin = User.objects.get(username="ll_admin")
    branch_admin.is_staff = True  # staff flag alone is not enough
    branch_admin.save()
    r = admin_client("127.0.0.1", "ll_admin").get("/admin/")
    assert r.status_code == 302 and "/admin/login/" in r["Location"]
    assert admin_client("127.0.0.1", "owner").get("/admin/").status_code == 200


def _prod(**over):
    base = {"SECRET_KEY": "k" * 50, "ALLOWED_HOSTS": ["pos.adentrifoshop.example"], "DATABASE_OWNER_USER": "pos_owner",
            "DATABASES": {"default": {"ENGINE": "django.db.backends.postgresql", "USER": "pos_app",
                                      "PASSWORD": "Zx9-long-random-db-pass"}}}
    base.update(over)
    return base


def test_production_settings_accepts_safe_config():
    validate_production(_prod())


@pytest.mark.parametrize("over, problem", [
    ({"SECRET_KEY": "dev-insecure-key-change-me"}, "DJANGO_SECRET_KEY"),
    ({"DATABASES": {"default": {"ENGINE": "django.db.backends.sqlite3"}}}, "PostgreSQL"),
    ({"DATABASES": {"default": {"ENGINE": "django.db.backends.postgresql", "USER": "pos_app", "PASSWORD": "shop"}}}, "16+"),
    ({"DATABASES": {"default": {"ENGINE": "django.db.backends.postgresql", "USER": "postgres",
                                "PASSWORD": "Zx9-long-random-db-pass"}}}, "superuser"),
    ({"DATABASES": {"default": {"ENGINE": "django.db.backends.postgresql", "USER": "pos_owner",
                                "PASSWORD": "Zx9-long-random-db-pass"}}}, "limited database role"),
    ({"ALLOWED_HOSTS": ["*"]}, "ALLOWED_HOSTS"),
])
def test_production_settings_refuses_unsafe(over, problem):
    with pytest.raises(ImproperlyConfigured, match=problem):
        validate_production(_prod(**over))
