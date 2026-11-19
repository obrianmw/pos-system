"""Admin system dashboard: health, parameters, live operations and events - for the whole organization or
one branch. Org admins see everything; branch admins see operations and events for their own branches
(server health, security and settings are org-admin only)."""
import os
import platform
import shutil
import socket
import time
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse

import django
from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.db import connection
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.dispatch import receiver
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from .models import AuditLog, Branch

STARTED = time.time()
ZERO = Decimal("0")

# Grouping of audit actions for the charts.
CATEGORIES = [
    ("Sales", ("sale.", "proforma.", "till.")),
    ("Cash", ("cash.", "vault.", "journal.")),
    ("Stock", ("inventory.", "stockcount.", "transfer.", "purchase.", "product.")),
    ("People & access", ("user.", "auth.", "override.", "hr.")),
    ("System", ("system.", "branding.", "comms.")),
]
NOTABLE = ("auth.login_failed", "override.pin_failed", "system.error", "sale.voided", "sale.refund", "user.",
           "vault.", "journal.manual", "journal.reversed", "inventory.adjust", "stockcount.posted", "till.updated",
           "branding.updated")


def category(action):
    for name, prefixes in CATEGORIES:
        if action.startswith(prefixes):
            return name
    return "Other"


# ------------------------------------------------------------------------------------------ recording
@receiver(user_login_failed)
def _login_failed(sender, credentials, request=None, **kw):
    """Wrong password for a real account -> event (unknown usernames can't be tied to an organization)."""
    from apps.accounts.models import User
    u = User.objects.filter(username=(credentials or {}).get("username", "")).select_related("organization").first()
    if u and u.organization_id:
        AuditLog.objects.create(organization=u.organization, action="auth.login_failed", object_type="User",
                                object_id=str(u.pk), data={"username": u.username},
                                ip_address=(request.META.get("REMOTE_ADDR") if request else None))


def record_server_error(request, ref):
    try:
        u = getattr(request, "user", None)
        if u is not None and u.is_authenticated and u.organization_id:
            AuditLog.objects.create(organization=u.organization, actor=u, action="system.error",
                                    data={"path": request.path[:200], "method": request.method, "reference": ref})
    except Exception:  # never let error reporting cause a second error
        pass


# ------------------------------------------------------------------------------------------ checks
def _db():
    t = time.perf_counter()
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        ok = True
    except Exception as e:  # pragma: no cover - only when the DB is down
        return {"ok": False, "detail": str(e)[:200]}
    ms = round((time.perf_counter() - t) * 1000, 1)
    size = None
    try:
        if connection.vendor == "sqlite":
            size = os.path.getsize(settings.DATABASES["default"]["NAME"])
        elif connection.vendor == "postgresql":
            with connection.cursor() as c:
                c.execute("SELECT pg_database_size(current_database())")
                size = c.fetchone()[0]
    except Exception:
        pass
    from django.db.migrations.executor import MigrationExecutor
    try:
        ex = MigrationExecutor(connection)
        pending = len(ex.migration_plan(ex.loader.graph.leaf_nodes()))
    except Exception:
        pending = None
    return {"ok": ok, "engine": connection.vendor, "latency_ms": ms, "size_bytes": size, "pending_migrations": pending}


def _broker():
    url = getattr(settings, "CELERY_BROKER_URL", "") or ""
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return {"ok": True, "detail": "Background jobs run inline (development)."}
    p = urlparse(url)
    if not p.hostname:
        return {"ok": None, "detail": "Not configured."}
    try:
        with socket.create_connection((p.hostname, p.port or 6379), timeout=0.4):
            return {"ok": True, "detail": f"{p.hostname}:{p.port or 6379} reachable"}
    except OSError:
        return {"ok": False, "detail": f"{p.hostname}:{p.port or 6379} not reachable - receipts by email and "
                                       "payment status checks in the background are paused."}


def _disk():
    u = shutil.disk_usage(settings.BASE_DIR)
    return {"ok": u.free / u.total > 0.1, "free_bytes": u.free, "total_bytes": u.total}


def _production_problems():
    if settings.DEBUG:
        return ["Running in development mode (DJANGO_DEBUG=1). Use production settings for the live shop."]
    return []


def health(full):
    db = _db()
    out = {"database": db, "checked_at": timezone.now()}
    if full:
        root = os.path.dirname(settings.BASE_DIR)
        out.update({
            "broker": _broker(), "disk": _disk(),
            "server": {"uptime_seconds": int(time.time() - STARTED), "python": platform.python_version(),
                       "django": django.get_version(), "os": f"{platform.system()} {platform.release()}",
                       "debug": settings.DEBUG, "time_zone": settings.TIME_ZONE,
                       "phones_on": os.path.exists(os.path.join(root, ".run", "lan-mode"))},
            "security": {"admin_networks": getattr(settings, "ADMIN_ALLOWED_NETWORKS", ""),
                         "allowed_hosts": settings.ALLOWED_HOSTS, "problems": _production_problems()},
        })
    return out


# ------------------------------------------------------------------------------------------ sections
def parameters(org, branches, full):
    from apps.catalog.models import TaxRate
    from apps.payments.models import PaymentMethod
    from apps.accounts.models import Role, User
    from apps.cash.services import vault_for
    from apps.cash.models import active_custody
    data = {
        "branches": [{
            "id": b.pk, "name": b.name, "code": b.code, "active": b.is_active,
            "allow_negative_stock": b.allow_negative_stock,
            "max_cashier_discount_pct": str(b.max_cashier_discount_pct),
            "tills": b.tills.filter(is_active=True).count(),
            "tills_unassigned": b.tills.filter(is_active=True, users__isnull=True).count(),
            "vault_holder": (lambda c: (c.custodian.get_full_name() or c.custodian.username) if c else None)(
                active_custody(vault_for(b))),
        } for b in branches],
    }
    if full:
        jwt = getattr(settings, "SIMPLE_JWT", {})
        data["organization"] = {
            "name": org.name, "currency": org.currency, "time_zone": settings.TIME_ZONE,
            "sign_in_hours": round(jwt["ACCESS_TOKEN_LIFETIME"].total_seconds() / 3600, 1) if jwt.get("ACCESS_TOKEN_LIFETIME") else None,
            "tax_rates": [{"name": t.name, "rate": str(t.rate), "inclusive": t.inclusive} for t in TaxRate.objects.filter(organization=org)],
            "payment_methods": [{"name": m.name, "kind": m.get_kind_display(), "provider": m.provider,
                                 "offline": m.allowed_offline, "qr": any(k.startswith("qr_") for k in m.config or {})}
                                for m in PaymentMethod.objects.filter(organization=org, is_active=True)],
            "roles": Role.objects.filter(organization=org, is_active=True).count(),
            "users": User.objects.filter(organization=org, is_active=True).count(),
        }
    return data


def operations(org, branches):
    from apps.cash.models import CashTransfer
    from apps.cash.services import vault_balance
    from apps.inventory.models import StockCount, StockLevel
    from apps.sales.models import Sale, TillSession
    from apps.accounts.models import User
    today = timezone.localdate()
    since = timezone.now() - timedelta(hours=24)
    ids = [b.pk for b in branches]
    sales = Sale.objects.filter(branch__in=ids, kind="sale", status="completed", created_at__date=today)
    agg = sales.aggregate(n=Count("id"), total=Sum("total"))
    logs = AuditLog.objects.filter(organization=org, created_at__gte=since).filter(Q(branch__in=ids) | Q(branch__isnull=True))
    return {
        "sales_today": {"count": agg["n"] or 0, "total": str(agg["total"] or ZERO)},
        "open_tills": TillSession.objects.filter(branch__in=ids, status="open").count(),
        "pending_handovers": {"count": CashTransfer.objects.filter(branch__in=ids, status="pending").count(),
                              "total": str(CashTransfer.objects.filter(branch__in=ids, status="pending")
                                           .aggregate(s=Sum("amount"))["s"] or ZERO)},
        "vault_total": str(sum((vault_balance(b) for b in branches), ZERO)),
        "awaiting_payment": Sale.objects.filter(branch__in=ids, status="pending_payment").count(),
        "stock_takes_to_verify": StockCount.objects.filter(branch__in=ids, status="submitted").count(),
        "stock_takes_counting": StockCount.objects.filter(branch__in=ids, status="counting").count(),
        "low_stock": StockLevel.objects.filter(branch__in=ids, product__is_active=True, product__track_stock=True,
                                               quantity__lte=F("product__reorder_level")).count(),
        "users_signed_in_today": User.objects.filter(organization=org, last_login__date=today, is_active=True)
            .filter(Q(memberships__branch__in=ids) | Q(memberships__branch__isnull=True)).distinct().count(),
        "failed_sign_ins_24h": logs.filter(action="auth.login_failed").count(),
        "failed_pins_24h": logs.filter(action="override.pin_failed").count(),
        "server_errors_24h": logs.filter(action="system.error").count(),
    }


def events(org, branches, days=14):
    ids = [b.pk for b in branches]
    start = timezone.now() - timedelta(days=days - 1)
    qs = AuditLog.objects.filter(organization=org, created_at__gte=start.replace(hour=0, minute=0, second=0)) \
        .filter(Q(branch__in=ids) | Q(branch__isnull=True))
    per_day = {}
    for row in qs.annotate(d=TruncDate("created_at", tzinfo=timezone.get_current_timezone())).values("d", "action") \
            .annotate(n=Count("id")):
        day = per_day.setdefault(row["d"].isoformat(), Counter())
        day[category(row["action"])] += row["n"]
    days_list = [(timezone.localdate() - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    cats = [c for c, _ in CATEGORIES] + ["Other"]
    week = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
    notable = qs.filter(Q(*[Q(action__startswith=p) for p in NOTABLE], _connector=Q.OR)).select_related("actor", "branch")[:25]
    return {
        "categories": cats,
        "per_day": [{"day": d, **{c: per_day.get(d, {}).get(c, 0) for c in cats}} for d in days_list],
        "top_actions": [{"action": r["action"], "count": r["n"]} for r in
                        week.values("action").annotate(n=Count("id")).order_by("-n")[:10]],
        "notable": [{"id": e.pk, "at": e.created_at, "action": e.action, "category": category(e.action),
                     "branch": e.branch.name if e.branch else "", "actor": (e.actor.get_full_name() or e.actor.username) if e.actor else "",
                     "data": e.data} for e in notable],
    }


@api_view(["GET"])
def overview(request):
    """GET /api/system/overview/?branch=<id> (omit for the whole organization)."""
    u = request.user
    full = u.has_org_perm("org.admin")
    allowed = Branch.objects.filter(organization=u.organization, is_active=True)
    if not full:
        from .api import branches_with
        allowed = allowed.filter(pk__in=[b.pk for b in branches_with(u, "branch.admin")])
        if not allowed.exists():
            raise PermissionDenied("The system dashboard is for admins.")
    raw = request.query_params.get("branch") or request.headers.get("X-Branch-ID")
    branches = list(allowed.order_by("name"))
    if raw:
        branches = [b for b in branches if str(b.pk) == str(raw)]
        if not branches:
            raise PermissionDenied("That branch isn't yours.")
    org = u.organization
    return Response({
        "scope": {"branch": branches[0].pk if raw else None, "branch_name": branches[0].name if raw else "All branches",
                  "full": full},
        "health": health(full),
        "operations": operations(org, branches),
        "parameters": parameters(org, branches, full),
        "events": events(org, branches),
    })
