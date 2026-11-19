"""Public demo mode (DEMO_MODE=1): stops visitors breaking the shared demo for everyone else.

Refuses, with a clear message, the changes that would lock other visitors out or deface the demo:
editing the shared demo users (password, PIN, roles, deactivation), ending a demo user's employment
in HR (which disables their login), changing role permissions, saving branding, and Django's /admin.
Selling, stock, purchasing, transfers, accounting, messages and new users all work as normal, and
the demo resets to its sample data whenever it restarts.
"""
import json
import re

from django.conf import settings
from django.http import HttpResponse

MESSAGE = ("This is a shared public demo, so that change is switched off. Everything else works, "
           "and the demo resets to its sample data whenever it restarts.")

WRITE = {"POST", "PUT", "PATCH", "DELETE"}
ADMIN = re.compile(r"^/admin(/|$)")
USER = re.compile(r"^/api/users/(\d+)/")
EMPLOYEE = re.compile(r"^/api/hr/employees/(\d+)/")
EMPLOYEES = re.compile(r"^/api/hr/employees/$")
ROLES = re.compile(r"^/api/roles/")
BRANDING = re.compile(r"^/api/branding/settings/$")


def demo_usernames():
    from apps.core.management.commands.seed_demo import USERS
    return {u[0] for u in USERS}


def demo_accounts():
    """For the sign-in page: who to sign in as, and the shared password and supervisor PIN."""
    from apps.core.management.commands.seed_demo import DEMO_PASSWORD, DEMO_PIN, USERS
    return {
        "password": DEMO_PASSWORD,
        "pin": DEMO_PIN,
        "accounts": [{"username": u, "role": role, "branch": {"ll": "Lilongwe", "bt": "Blantyre"}.get(b, "All branches"),
                      "has_pin": pin} for u, _first, _last, role, b, pin in USERS],
    }


def _refuse():
    return HttpResponse(json.dumps({"detail": MESSAGE}), status=403, content_type="application/json")


class DemoGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, "DEMO_MODE", False) and self._blocked(request):
            return _refuse()
        return self.get_response(request)

    @staticmethod
    def _blocked(request) -> bool:
        path = request.path
        if ADMIN.match(path):
            return True
        if request.method not in WRITE:
            return False
        if ROLES.match(path) or BRANDING.match(path):
            return True
        m = USER.match(path)
        if m:
            from django.contrib.auth import get_user_model
            target = get_user_model().objects.filter(pk=int(m.group(1))).only("username").first()
            return target is not None and target.username in demo_usernames()
        m = EMPLOYEE.match(path)
        if m:
            from apps.hr.models import Employee
            emp = Employee.objects.filter(pk=int(m.group(1))).select_related("user").first()
            if emp and emp.user_id and emp.user.username in demo_usernames():
                return True
        if (m or EMPLOYEES.match(path)) and _links_demo_user(request):
            return True  # a staff record pointing at a shared demo login (ending it would disable that login)
        return False


def _links_demo_user(request) -> bool:
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return False
    user_id = body.get("user") if isinstance(body, dict) else None
    if not user_id:
        return False
    from django.contrib.auth import get_user_model
    target = get_user_model().objects.filter(pk=user_id).only("username").first()
    return target is not None and target.username in demo_usernames()
