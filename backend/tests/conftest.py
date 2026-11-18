import uuid
from decimal import Decimal

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.core.models import Branch, Till
from apps.payments.models import PaymentMethod


@pytest.fixture(autouse=True)
def _media_in_tmp(settings, tmp_path):
    """Uploaded/demo pictures go to a throwaway folder, never the real media directory."""
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def demo(db):
    call_command("seed_demo", stdout=open("nul" if __import__("os").name == "nt" else "/dev/null", "w"))
    ll = Branch.objects.get(code="ll")
    bt = Branch.objects.get(code="bt")
    return {
        "ll": ll, "bt": bt,
        "sugar": Product.objects.get(sku="SUG-2KG"),
        "oil": Product.objects.get(sku="OIL-2L"),
        "cash": PaymentMethod.objects.get(name="Cash"),
        "airtel": PaymentMethod.objects.get(name="Airtel Money"),
        "till": Till.objects.get(branch=ll, code="t1"),
    }


@pytest.fixture
def client_for():
    def make(username, branch=None):
        c = APIClient()
        c.force_authenticate(User.objects.get(username=username))
        if branch is not None:
            c.credentials(HTTP_X_BRANCH_ID=str(branch.pk))
        return c
    return make


@pytest.fixture
def open_session(demo, client_for):
    def make(username="ll_cash1", till=None, opening_float="10000"):
        c = client_for(username, demo["ll"])
        r = c.post("/api/till-sessions/", {"till": (till or demo["till"]).pk, "opening_float": opening_float},
                   format="json")
        assert r.status_code == 201, r.data
        return c, r.data["id"]
    return make


def sale_body(demo, qty=2, unit_price=None, discount=None, override=None, pay=None, method=None, **extra):
    line = {"product_id": demo["sugar"].pk, "quantity": str(qty)}
    if unit_price is not None:
        line["unit_price"] = str(unit_price)
    if discount is not None:
        line["discount_amount"] = str(discount)
    if override:
        line["override"] = override
    price = Decimal(unit_price if unit_price is not None else 5500)
    total = price * qty - Decimal(discount or 0)
    return {"client_uuid": str(uuid.uuid4()), "lines": [line],
            "payments": [{"method_id": (method or demo["cash"]).pk, "amount": str(pay or total),
                          "tendered": str(pay or total)}], **extra}
