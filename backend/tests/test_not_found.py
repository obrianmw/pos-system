"""Friendly error pages: same card for every error, nothing about the server's insides on show."""
import logging

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db

LEAKS = [b"URLconf", b"api/auth/token", b"Django tried", b"Raised by", b"DEBUG", b"Traceback",
         b"hunter2", b"RuntimeError", b"site-packages", b"settings.py"]


def no_leaks(content):
    for leak in LEAKS:
        assert leak not in content, leak


@pytest.fixture
def debug(settings):
    settings.DEBUG = True  # development mode is where Django's technical pages used to appear
    return settings


@pytest.mark.parametrize("path", ["/nothing-here", "/media/products/missing.png"])  # "/" opens the admin sign-in
def test_404_page(debug, path):
    r = Client(REMOTE_ADDR="127.0.0.1").get(path)
    assert r.status_code == 404
    assert b"Page not found" in r.content and b"Go to the POS" in r.content and b"Go back" in r.content
    no_leaks(r.content)


def test_unknown_admin_page_for_logged_in_admin(debug, demo):
    from apps.accounts.models import User
    c = Client(REMOTE_ADDR="127.0.0.1")
    c.force_login(User.objects.get(username="owner"))
    r = c.get("/admin/no-such-page/")
    assert r.status_code == 404 and b"Page not found" in r.content
    no_leaks(r.content)


def test_api_404_is_short_json(debug):
    r = Client().get("/api/no-such-endpoint/")
    assert r.status_code == 404 and r.json() == {"detail": "Not found."}


def test_500_has_reference_and_no_traceback(debug, caplog):
    debug.ROOT_URLCONF = "tests.crash_urls"
    c = Client(raise_request_exception=False)
    with caplog.at_level(logging.ERROR, logger="errors"):
        r = c.get("/boom/")
    assert r.status_code == 500 and b"Something went wrong" in r.content and b"Reference: ERR-" in r.content
    no_leaks(r.content)
    ref = r.content.split(b"Reference: ")[1][:10].decode()
    # The full story is in the server log under the same reference, for IT.
    record = next(rec for rec in caplog.records if ref in rec.getMessage())
    assert record.exc_info and "hunter2" in str(record.exc_info[1])


def test_api_500_is_json_with_reference(debug):
    debug.ROOT_URLCONF = "tests.crash_urls"
    r = Client(raise_request_exception=False).get("/api/boom/")
    body = r.json()
    assert r.status_code == 500 and body["detail"] == "Server error." and body["reference"].startswith("ERR-")
    assert "hunter2" not in r.content.decode()


def test_405_page(debug, demo):
    from apps.accounts.models import User
    c = Client(REMOTE_ADDR="127.0.0.1")
    c.force_login(User.objects.get(username="owner"))
    r = c.get("/admin/logout/")  # logout only accepts POST
    assert r.status_code == 405 and b"Action not allowed" in r.content
    no_leaks(r.content)


def test_csrf_failure_page(debug, demo):
    c = Client(REMOTE_ADDR="127.0.0.1", enforce_csrf_checks=True)
    r = c.post("/admin/login/", {"username": "owner", "password": "x"})
    assert r.status_code == 403 and b"Session expired" in r.content
    no_leaks(r.content)


def test_admin_network_refusal_uses_same_card(demo):
    r = Client(REMOTE_ADDR="10.9.9.9").get("/admin/")
    assert r.status_code == 403 and b"Admin network only" in r.content and b"Go to the POS" in r.content


def test_api_field_errors_are_kept(demo, client_for):
    # The app relies on DRF's per-field messages; the error middleware must not replace them.
    r = client_for("owner").post("/api/products/", {"sku": "", "name": ""}, format="json")
    assert r.status_code == 400 and "sell_price" in r.json()


def test_trailing_slash_redirect_still_works():
    r = Client(REMOTE_ADDR="127.0.0.1").get("/admin")
    assert r.status_code == 301 and r["Location"] == "/admin/"


def test_path_is_escaped():
    r = Client().get("/<script>alert(1)</script>")
    assert r.status_code == 404 and b"<script>alert" not in r.content
