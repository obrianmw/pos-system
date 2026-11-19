"""Network and deployment safeguards.

1. The Django admin site (/admin/) edits database tables directly, so it is reachable only from the admin
   networks in ADMIN_ALLOWED_NETWORKS and only by organization admins. Everyone else uses the POS and
   back office, which go through the API's role checks and audit log.
2. In production (DJANGO_DEBUG=0) the server refuses to start with unsafe settings, including database
   credentials that are missing, weak, or the same as an app login's.
"""
import ipaddress
import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

log = logging.getLogger("security")

WEAK_DB_PASSWORDS = {"", "shop", "postgres", "password", "admin", "pos", "changeme", "change-me", "demo-pass-2026"}


def parse_networks(raw):
    nets = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                raise ImproperlyConfigured(f"ADMIN_ALLOWED_NETWORKS: '{part}' is not an IP network (e.g. 10.0.5.0/24).")
    return nets


def client_ip(request):
    """REMOTE_ADDR, or the address the trusted reverse proxy saw when TRUSTED_PROXY_COUNT > 0."""
    hops = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if hops:
        chain = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(chain) >= hops:
            return chain[-hops]
    return request.META.get("REMOTE_ADDR", "")


def ip_allowed(ip, networks):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in n for n in networks if n.version == addr.version)


class AdminNetworkMiddleware:
    """Blocks the admin site for anyone outside the admin networks, before login is even shown."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = parse_networks(getattr(settings, "ADMIN_ALLOWED_NETWORKS", "127.0.0.1/32,::1/128"))
        self.prefix = "/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/")

    def __call__(self, request):
        if request.path.startswith(self.prefix):
            ip = client_ip(request)
            if not ip_allowed(ip, self.networks):
                log.warning("Admin site refused for %s (not on an admin network): %s", ip, request.path)
                from .views import error_response
                return error_response(request, 403, "Admin network only",
                                      "The database admin site can only be used from the shop's admin network. "
                                      "Use the back office for day-to-day work.")
        return self.get_response(request)


def admin_site_permission(request):
    """Admin site = direct table editing: organization admins only (not branch admins or other staff)."""
    u = request.user
    return bool(u.is_active and u.is_staff and u.has_org_perm("org.admin"))


def validate_production(s):
    """Called from settings when DEBUG is off. Raises ImproperlyConfigured listing every problem."""
    problems = []
    if s["SECRET_KEY"].startswith("dev-") or len(s["SECRET_KEY"]) < 40:
        problems.append("DJANGO_SECRET_KEY must be set to a random value of 40+ characters.")
    db = s["DATABASES"]["default"]
    if s.get("DEMO_MODE"):
        pass  # public demo: a throwaway SQLite database on the host's temporary disk, reset on restart
    elif db["ENGINE"].endswith("sqlite3"):
        problems.append("DATABASE_URL must point at PostgreSQL in production (SQLite has no credentials).")
    else:
        pw, user = db.get("PASSWORD") or "", db.get("USER") or ""
        if len(pw) < 16 or pw.lower() in WEAK_DB_PASSWORDS:
            problems.append("The database password must be 16+ characters and not a common word.")
        if user in ("postgres", "root", "admin"):
            problems.append("The app must connect with its own limited database role, not a superuser.")
        if s.get("DATABASE_OWNER_USER") and s["DATABASE_OWNER_USER"] == user:
            problems.append("The app must use its limited database role (DB_APP_USER), not the owner role.")
    if not s["ALLOWED_HOSTS"] or "*" in s["ALLOWED_HOSTS"]:
        problems.append("DJANGO_ALLOWED_HOSTS must list the real host names.")
    if problems:
        raise ImproperlyConfigured("Unsafe production settings:\n - " + "\n - ".join(problems))


def check_db_password_not_an_app_password():
    """Startup check: the database password must not also unlock an app account (separate credentials)."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.hashers import check_password
    pw = settings.DATABASES["default"].get("PASSWORD") or ""
    if not pw:
        return []
    User = get_user_model()
    clashes = [u.username for u in User.objects.filter(is_active=True).only("username", "password")
               if check_password(pw, u.password)]
    return clashes
