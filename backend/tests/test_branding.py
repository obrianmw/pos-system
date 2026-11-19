import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.core.models import Branding

pytestmark = pytest.mark.django_db


def png(w=1200, h=600, alpha=True):
    buf = io.BytesIO()
    Image.new("RGBA" if alpha else "RGB", (w, h), (15, 118, 110, 128) if alpha else (15, 118, 110)).save(buf, "PNG")
    return SimpleUploadedFile("logo.png", buf.getvalue(), content_type="image/png")


# ---- personal theme ---------------------------------------------------------------------------
def test_theme_preference_is_saved_per_user(demo, client_for):
    c = client_for("ll_cash1")
    assert c.get("/api/me/").data["ui_theme"] == "system"
    assert c.patch("/api/me/preferences/", {"ui_theme": "dark"}, format="json").status_code == 200
    assert User.objects.get(username="ll_cash1").ui_theme == "dark"
    assert c.get("/api/me/").data["ui_theme"] == "dark"
    assert client_for("ll_super").get("/api/me/").data["ui_theme"] == "system"  # others unaffected
    assert c.patch("/api/me/preferences/", {"ui_theme": "purple"}, format="json").status_code == 400


# ---- branding ---------------------------------------------------------------------------------
def test_public_branding_needs_no_login(demo):
    r = Client().get("/api/branding/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Aden Trifo Shop" and body["primary_color"].startswith("#")
    assert "doc_tax_number" not in body and "invoice_terms" not in body  # document settings stay private


def test_settings_readable_by_staff_editable_by_org_admin_only(demo, client_for):
    assert client_for("ll_cash1").get("/api/branding/settings/").data["receipt_paper"] == "80mm"
    r = client_for("ll_admin").patch("/api/branding/settings/", {"primary_color": "#ff0000"}, format="json")
    assert r.status_code == 403
    r = client_for("owner").patch("/api/branding/settings/", {"primary_color": "#FACC15", "tagline": "Fresh daily",
                                                              "invoice_prefix": "AS-INV-"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["primary_color"] == "#facc15" and r.data["invoice_prefix"] == "AS-INV-"
    assert Client().get("/api/branding/").json()["tagline"] == "Fresh daily"
    from apps.core.models import AuditLog
    assert AuditLog.objects.filter(action="branding.updated").exists()


@pytest.mark.parametrize("field, value", [
    ("primary_color", "red"), ("accent_color", "#12345"), ("primary_color", "#gggggg"),
    ("invoice_prefix", "X" * 11), ("proforma_validity_days", 0), ("receipt_paper", "A4"),
])
def test_settings_validation(demo, client_for, field, value):
    r = client_for("owner").patch("/api/branding/settings/", {field: value}, format="json")
    assert r.status_code == 400 and field in r.data


def test_logo_upload_keeps_transparency_and_rejects_non_images(demo, client_for):
    c = client_for("owner")
    r = c.patch("/api/branding/settings/", {"logo": png()}, format="multipart")
    assert r.status_code == 200, r.data
    b = Branding.objects.get(organization__code="demo")
    assert b.logo.name.endswith(".webp")
    with Image.open(b.logo.path) as im:
        assert max(im.size) == 512 and im.mode == "RGBA"
    assert Client().get("/api/branding/").json()["logo_url"].startswith("/media/branding/")
    bad = SimpleUploadedFile("logo.png", b"<svg onload=alert(1)>", content_type="image/png")
    assert c.patch("/api/branding/settings/", {"logo": bad}, format="multipart").status_code == 400
    r = c.patch("/api/branding/settings/", {"clear_logo": "true"}, format="multipart")
    assert r.status_code == 200 and r.data["logo_url"] is None


# ---- proformas --------------------------------------------------------------------------------
def body(demo, **line):
    return {"customer_name": "Kondwani Phiri", "customer_phone": "0999000111",
            "lines": [{"product_id": demo["sugar"].pk, "quantity": "3", **line},
                      {"product_id": demo["oil"].pk, "quantity": "1"}]}


def test_proforma_priced_numbered_and_dated(demo, client_for):
    c = client_for("ll_cash1", demo["ll"])
    r = c.post("/api/proformas/", body(demo), format="json")
    assert r.status_code == 201, r.data
    assert r.data["number"] == "PF-000001"
    assert Decimal(r.data["total"]) == Decimal("29000.00")  # 3 x 5,500 + 12,500, VAT inclusive
    assert Decimal(r.data["tax_total"]) > 0
    assert r.data["valid_until"] == str(timezone.localdate() + timedelta(days=14))
    assert r.data["lines"][0]["name"] == "Sugar 2kg"
    # Prefix and validity come from the branding settings.
    client_for("owner").patch("/api/branding/settings/", {"proforma_prefix": "Q-", "proforma_validity_days": 7}, format="json")
    r2 = c.post("/api/proformas/", body(demo), format="json")
    assert r2.data["number"] == "Q-000002" and r2.data["valid_until"] == str(timezone.localdate() + timedelta(days=7))


def test_proforma_has_no_stock_or_ledger_effect(demo, client_for):
    from apps.accounting.models import JournalEntry
    from apps.inventory.models import StockLevel
    before = (StockLevel.objects.get(branch=demo["ll"], product=demo["sugar"]).quantity, JournalEntry.objects.count())
    client_for("ll_cash1", demo["ll"]).post("/api/proformas/", body(demo), format="json")
    after = (StockLevel.objects.get(branch=demo["ll"], product=demo["sugar"]).quantity, JournalEntry.objects.count())
    assert before == after


def test_proforma_price_change_needs_supervisor_and_respects_floor(demo, client_for):
    assert client_for("ll_cash1", demo["ll"]).post("/api/proformas/", body(demo, unit_price="5000"),
                                                   format="json").status_code == 403
    sup = client_for("ll_super", demo["ll"])
    r = sup.post("/api/proformas/", body(demo, unit_price="5000"), format="json")
    assert r.status_code == 201 and r.data["lines"][0]["unit_price"] == "5000.00"
    assert sup.post("/api/proformas/", body(demo, unit_price="100"), format="json").status_code == 400  # below floor


def test_proformas_are_branch_scoped(demo, client_for):
    client_for("ll_cash1", demo["ll"]).post("/api/proformas/", body(demo), format="json")
    assert client_for("ll_cash1").get("/api/proformas/").data["count"] == 1
    assert client_for("bt_cash1").get("/api/proformas/").data["count"] == 0
    assert client_for("ll_cash1", demo["ll"]).post("/api/proformas/", {"lines": []}, format="json").status_code == 400
