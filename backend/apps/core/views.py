"""Friendly error pages that never reveal how the server is built (no URL lists, tracebacks, file paths
or module names) - in production and in development mode alike.

Every HTML error response (400, 403, 404, 405, 500, CSRF failures ...) is replaced by one plain card.
API addresses (/api/...) get a short JSON body instead. Server errors (500) get a reference code that is
written to the server log together with the full traceback, so staff can quote it and IT can find it.
"""
import logging
import secrets

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils.html import escape

log = logging.getLogger("errors")

MESSAGES = {
    400: ("Bad request", "The request could not be understood. Please go back and try again."),
    401: ("Sign in needed", "Please sign in and try again."),
    403: ("Access denied", "You don't have permission to open this page."),
    404: ("Page not found", "The page {path} does not exist or has moved."),
    405: ("Action not allowed", "This action isn't available on this page."),
    413: ("Too large", "What you sent is too large. Try a smaller file."),
    429: ("Too many requests", "Please wait a moment and try again."),
    500: ("Something went wrong", "We couldn't finish that. The problem has been logged; please try again in a moment."),
    503: ("Temporarily unavailable", "The system is busy or being updated. Please try again shortly."),
}
# Short messages for programs calling the API (/api/...).
API_MESSAGES = {400: "Bad request.", 401: "Authentication required.", 403: "Access denied.", 404: "Not found.",
                405: "Method not allowed.", 413: "Request too large.", 429: "Too many requests.",
                500: "Server error.", 503: "Service unavailable."}
CSRF = ("Session expired", "This form was open too long or your session changed. Reload the page and try again.")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · POS System</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f4f6f8; --card:#fff; --text:#111827; --muted:#6b7280; --line:#e5e7eb; --primary:{pl}; --on:{onl}; --accent:{accent}; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0b0f14; --card:#131920; --text:#e6e9ee; --muted:#94a0b0; --line:#243040; --primary:{pd}; --on:{ond}; }} }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--text);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif; padding:16px; box-sizing:border-box; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:32px; max-width:440px; text-align:center;
          box-shadow:0 20px 40px -12px rgb(16 24 40 / .18); }}
  .code {{ font-size:3.5rem; font-weight:800; letter-spacing:-.04em; color:var(--accent); margin:0; }}
  h1 {{ font-size:1.3rem; margin:.25rem 0 .5rem; }}
  p {{ color:var(--muted); margin:0 0 1.25rem; line-height:1.5; }}
  .ref {{ font-family: ui-monospace, Consolas, monospace; font-size:.85rem; background:var(--bg); border:1px solid var(--line);
         border-radius:6px; padding:6px 10px; display:inline-block; margin:-.25rem 0 1.25rem; color:var(--text); }}
  .actions {{ display:flex; gap:10px; justify-content:center; flex-wrap:wrap; }}
  a, button {{ font:inherit; background:var(--primary); color:var(--on); text-decoration:none; padding:10px 18px; border-radius:8px;
              font-weight:600; border:0; cursor:pointer; }}
  .ghost {{ background:transparent; color:var(--text); border:1px solid var(--line); }}
</style></head>
<body><main class="card" role="alert">
  <p class="code">{status}</p>
  <h1>{title}</h1>
  <p>{message}</p>
  {ref}
  <div class="actions">
    <button class="ghost" onclick="history.length > 1 ? history.back() : location.assign('{home}')">Go back</button>
    <a href="{home}">Go to the POS</a>
  </div>
</main></body></html>"""


def error_response(request, status, title=None, message=None, ref=None):
    """One place that builds every error the server shows a person (HTML) or a program (JSON)."""
    default_title, default_message = MESSAGES.get(status, ("Request not completed", "Please go back and try again."))
    title, message = title or default_title, message or default_message
    if request.path.startswith("/api/"):
        body = {"detail": API_MESSAGES.get(status, "Request failed.") if message == default_message else message}
        if ref:
            body["reference"] = ref
        response = JsonResponse(body, status=status)
    else:
        message_html = escape(message).replace("{path}", f"<b>{escape(request.path[:120])}</b>")
        home = escape(getattr(settings, "FRONTEND_URL", "/"))
        accent = "#d03b3b" if status >= 500 else "var(--primary)"
        ref_html = f'<div class="ref">Reference: {escape(ref)}</div>' if ref else ""
        try:  # the shop's own colours, readable in light and dark
            from .admin_theme import brand_context
            b = brand_context(request)
            colours = {"pl": b["light"]["fill"], "onl": b["light"]["on_fill"], "pd": b["dark"]["fill"], "ond": b["dark"]["on_fill"]}
        except Exception:
            colours = {"pl": "#0f766e", "onl": "#ffffff", "pd": "#14b8a6", "ond": "#0b0f14"}
        response = HttpResponse(PAGE.format(status=status, title=escape(title), message=message_html, home=home,
                                            ref=ref_html, accent=accent, **colours), status=status)
    response._friendly_error = True
    return response


# ---- handlers Django uses in production (DEBUG off) -----------------------------------------------
def bad_request(request, exception=None):
    return error_response(request, 400)


def permission_denied(request, exception=None):
    return error_response(request, 403)


def not_found(request, exception=None):
    return error_response(request, 404)


def server_error(request):
    return error_response(request, 500, ref=getattr(request, "_error_ref", None) or new_ref())


def csrf_failure(request, reason=""):
    return error_response(request, 403, *CSRF)


def new_ref():
    return "ERR-" + secrets.token_hex(3).upper()


class FriendlyErrorMiddleware:
    """Replaces Django's error pages - including the development-mode debug pages with tracebacks and
    URL lists - with the friendly card. JSON errors from the API are left alone (they carry field
    messages the app shows), except server errors, which get the reference code.
    Sits above CommonMiddleware so "add a trailing slash" redirects still happen first."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code < 400 or getattr(response, "_friendly_error", False):
            return response
        is_html = response.get("Content-Type", "").startswith("text/html")
        if response.status_code >= 500:
            ref = getattr(request, "_error_ref", None) or new_ref()
            return error_response(request, response.status_code if response.status_code in MESSAGES else 500, ref=ref)
        if is_html:
            if getattr(response, "csrf_failure", False) or b"CSRF verification failed" in (response.content or b"")[:4000]:
                return error_response(request, 403, *CSRF)
            return error_response(request, response.status_code)
        return response

    def process_exception(self, request, exception):
        """Give the crash a reference and log it with the full traceback (never shown to the user)."""
        from django.core.exceptions import PermissionDenied, SuspiciousOperation
        from django.http import Http404
        if isinstance(exception, (Http404, PermissionDenied, SuspiciousOperation)):
            return None  # normal 4xx handling
        request._error_ref = new_ref()
        from .system import record_server_error
        record_server_error(request, request._error_ref)
        log.error("%s %s %s failed (reference %s)", request.method, request.path,
                  getattr(request.user, "username", "-") if hasattr(request, "user") else "-",
                  request._error_ref, exc_info=exception)
        return None
