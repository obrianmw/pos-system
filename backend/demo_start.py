"""Starts the public demo: database, demo shop and users, then the web server.

Run from backend/ with `python demo_start.py` (Render's start command). The SQLite database lives on the
instance's temporary disk, so each restart begins again from the demo shop. The built till and back office
(frontend/dist) are served from the same address as the API. Local check on Windows:
`python demo_start.py --runserver`.
"""
import os
import sys

host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
defaults = {
    "DJANGO_SETTINGS_MODULE": "config.settings",
    "DEMO_MODE": "1",
    "DJANGO_DEBUG": "0",
    "CELERY_EAGER": "1",                      # no Redis on the demo: run background jobs straight away
    "DJANGO_ALLOWED_HOSTS": host or "localhost,127.0.0.1",
    "TRUSTED_PROXY_COUNT": "1" if host else "0",
    "PUBLIC_BASE_URL": f"https://{host}" if host else "http://localhost:8100",
    "FRONTEND_URL": f"https://{host}/" if host else "http://localhost:8100/",
    "WEB_APP_URL": f"https://{host}/" if host else "http://localhost:8100/",
}
for key, value in defaults.items():
    os.environ.setdefault(key, value)
if not os.environ.get("DJANGO_SECRET_KEY") and not host:
    os.environ["DJANGO_SECRET_KEY"] = "local-demo-only-not-secret-" + "x" * 20  # local check only

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402


def prepare() -> None:
    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    print("Loading the demo shop...", flush=True)
    call_command("seed_demo")
    print("Demo ready.", flush=True)


def main() -> None:
    prepare()
    port = os.environ.get("PORT", "8100")
    if "--runserver" in sys.argv:
        call_command("runserver", f"127.0.0.1:{port}", use_reloader=False)
        return
    os.execvp("gunicorn", ["gunicorn", "config.wsgi:application", "--bind", f"0.0.0.0:{port}",
                           "--workers", "2", "--timeout", "120"])


if __name__ == "__main__":
    main()
