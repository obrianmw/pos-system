"""Makes the database admin site (/admin/) look and behave like the POS: the shop's name, logo and brand
colours (made readable in light and dark), the person's own light/dark choice, links back to the till and
back office, and a sign-in hand-off so organization admins coming from the POS don't sign in twice."""
import colorsys
import secrets

from django.conf import settings
from django.contrib.auth import login
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import Branding, Organization, audit
from .security import admin_site_permission

# Same surfaces as the web app (styles.css) so contrast is judged against what is really behind the colour.
LIGHT = {"bg": "#f4f6f8", "card": "#ffffff", "text": "#111827", "muted": "#6b7280", "line": "#e5e7eb", "card2": "#f8fafb"}
DARK = {"bg": "#0b0f14", "card": "#131920", "text": "#e6e9ee", "muted": "#94a0b0", "line": "#243040", "card2": "#182029"}


# ------------------------------------------------------------------------------------------ colour
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, v)) * 255):02x}" for v in rgb)


def luminance(h):
    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    x, y = sorted((luminance(a), luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _reach(h, surface, target, direction):
    """Change lightness (keeping the hue) until `h` reaches `target` contrast against `surface`."""
    hh, ll, ss = colorsys.rgb_to_hls(*_rgb(h))
    out = h
    for _ in range(60):
        if contrast(out, surface) >= target:
            break
        ll = max(0, min(1, ll + 0.015 * direction))
        out = _hex(colorsys.hls_to_rgb(hh, ll, ss))
    return out


def readable(brand, mode):
    """Text/link colour for this brand on the theme's cards (4.5:1), and a button fill + its text colour."""
    s = LIGHT if mode == "light" else DARK
    ink = _reach(brand, s["card"], 4.5, -1 if mode == "light" else 1)
    text_on = "#ffffff" if contrast(brand, "#ffffff") >= contrast(brand, "#0b0f14") else "#0b0f14"
    fill = brand
    if contrast(fill, text_on) < 4.5:
        fill = _reach(brand, text_on, 4.5, -1 if text_on == "#ffffff" else 1)
    return {"ink": ink, "fill": fill, "on_fill": text_on}


# ------------------------------------------------------------------------------------------ context
def _org(request):
    u = getattr(request, "user", None)
    if u is not None and u.is_authenticated and u.organization_id:
        return u.organization
    qs = Organization.objects.filter(is_active=True)
    return qs.first() if qs.count() == 1 else None


def web_url(path=""):
    return settings.FRONTEND_URL.rstrip("/") + "/" + path.lstrip("/")


def brand_context(request):
    """Template context for the admin site (and the friendly error pages)."""
    org = _org(request)
    b = Branding.for_org(org) if org else None
    primary = (b.primary_color if b else None) or "#0f766e"
    u = getattr(request, "user", None)
    theme = getattr(u, "ui_theme", "") if u is not None and u.is_authenticated else ""
    return {
        "name": (b.display_name or org.name) if b else "POS System",
        "tagline": b.tagline if b else "",
        "logo_url": b.logo.url if b and b.logo else "",
        "initial": ((b.display_name or org.name) if b else "P")[:1].upper(),
        "light": readable(primary, "light"), "dark": readable(primary, "dark"),
        "LIGHT": LIGHT, "DARK": DARK,
        # The admin site's own theme switch uses auto/light/dark.
        "theme": {"system": "auto", "light": "light", "dark": "dark"}.get(theme or "", ""),
        "tabs": [("Till", web_url("#/pos")), ("Back office", web_url("#/office/dashboard")), ("Stock", web_url("#/count"))],
    }


def admin_brand(request):
    """Context processor: only the admin site pays for the lookup."""
    if not request.path.startswith("/" + getattr(settings, "ADMIN_URL", "admin/").lstrip("/")):
        return {}
    return {"brand": brand_context(request)}


# ------------------------------------------------------------------------------------------ hand-off
SALT = "admin-handoff"
TTL = 60  # seconds


@api_view(["POST"])
def admin_handoff(request):
    """POST /api/admin-handoff/ (signed in to the POS) -> a one-time link that opens the admin site
    already signed in. Only for organization admins; the link works once, for one minute, and the
    admin-network rule still applies when it is opened."""
    if not admin_site_permission(request):
        raise PermissionDenied("Only organization admins can use the database admin site.")
    nonce = secrets.token_urlsafe(16)
    cache.set(f"{SALT}:{nonce}", request.user.pk, TTL)
    token = signing.dumps({"u": request.user.pk, "n": nonce}, salt=SALT)
    return Response({"path": f"/admin/handoff/?t={token}", "port": settings.API_PORT, "expires_in": TTL})


def admin_handoff_open(request):
    """GET /admin/handoff/?t=... - signs the person in to the admin site and goes to its home page."""
    from apps.accounts.models import User
    nxt = request.GET.get("next") or "/admin/"
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = "/admin/"
    try:
        data = signing.loads(request.GET.get("t", ""), salt=SALT, max_age=TTL)
    except signing.BadSignature:
        return HttpResponseRedirect("/admin/login/?expired=1")
    key = f"{SALT}:{data.get('n')}"
    if cache.get(key) != data.get("u"):  # already used, or never issued here
        return HttpResponseRedirect("/admin/login/?expired=1")
    cache.delete(key)
    user = User.objects.filter(pk=data["u"], is_active=True).first()
    if user is None or not admin_site_permission(type("R", (), {"user": user})()):
        return HttpResponseRedirect("/admin/login/?expired=1")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    audit("admin.signed_in", organization=user.organization, actor=user, via="POS hand-off")
    return HttpResponseRedirect(nxt)
