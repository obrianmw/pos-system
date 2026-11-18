import pytest

from apps.catalog.models import Category, Product
from apps.core.models import Organization
from apps.inventory.models import PurchaseOrder, Supplier

pytestmark = pytest.mark.django_db

NEW = {"sku": "jam-400", "name": "Jam 400g", "sell_price": "3200", "cost_price": "2400", "unit": "jar"}


def test_only_head_office_edits_products(demo, client_for):
    assert client_for("ll_cash1").post("/api/products/", NEW, format="json").status_code == 403
    assert client_for("ll_admin").post("/api/products/", NEW, format="json").status_code == 403
    r = client_for("owner").post("/api/products/", NEW, format="json")
    assert r.status_code == 201, r.data
    assert r.data["sku"] == "JAM-400"  # normalised


def test_product_validation(demo, client_for):
    c = client_for("owner")
    assert c.post("/api/products/", {**NEW, "sku": "sug-2kg"}, format="json").status_code == 400  # dup, any case
    r = c.post("/api/products/", {**NEW, "barcode": demo["sugar"].barcode}, format="json")
    assert r.status_code == 400 and "Sugar" in str(r.data["barcode"])
    assert c.post("/api/products/", {**NEW, "sell_price": "0"}, format="json").status_code == 400
    assert c.post("/api/products/", {**NEW, "min_price": "5000"}, format="json").status_code == 400
    other = Organization.objects.create(name="Other", code="other")
    foreign = Category.objects.create(organization=other, name="X")
    assert c.post("/api/products/", {**NEW, "category": foreign.pk}, format="json").status_code == 400


def test_price_change_is_audited_and_delete_blocked(demo, client_for):
    c = client_for("owner")
    pid = demo["sugar"].pk
    assert c.patch(f"/api/products/{pid}/", {"sell_price": "5800"}, format="json").status_code == 200
    from apps.core.models import AuditLog
    log = AuditLog.objects.get(action="product.updated")
    assert log.data["sell_price"] == ["5500.00", "5800.00"]
    assert c.delete(f"/api/products/{pid}/").status_code == 403


def test_branch_admin_sets_own_branch_price_only(demo, client_for):
    c = client_for("ll_admin")
    pid = demo["sugar"].pk
    r = c.post(f"/api/products/{pid}/branch_prices/", {"branch": demo["ll"].pk, "price": "5900"}, format="json")
    assert r.status_code == 200, r.data
    assert next(x for x in r.data if x["branch"] == demo["ll"].pk)["price"] == "5900.00"
    assert c.post(f"/api/products/{pid}/branch_prices/", {"branch": demo["bt"].pk, "price": "5900"},
                  format="json").status_code == 403
    assert c.post(f"/api/products/{pid}/branch_prices/", {"branch": demo["ll"].pk, "price": "100"},
                  format="json").status_code == 400  # below floor
    # The till now sells at the branch price, Blantyre still at base.
    cat = client_for("ll_cash1", demo["ll"]).get("/api/pos/catalog/").data
    assert next(p for p in cat["products"] if p["id"] == pid)["price"] == "5900.00"
    assert Product.objects.get(pk=pid).price_at(demo["bt"]) == 5500
    # Clearing returns to the base price
    c.post(f"/api/products/{pid}/branch_prices/", {"branch": demo["ll"].pk, "price": ""}, format="json")
    assert Product.objects.get(pk=pid).price_at(demo["ll"]) == 5500


def _po(demo, **over):
    sup = Supplier.objects.get_or_create(organization=demo["ll"].organization, name="Wholesaler")[0]
    return {"supplier": sup.pk, "lines": [{"product": demo["sugar"].pk, "quantity": "50", "unit_cost": "4300"},
                                          {"product": demo["oil"].pk, "quantity": "20", "unit_cost": "9500"}], **over}


def test_purchase_order_validation(demo, client_for):
    c = client_for("ll_admin", demo["ll"])
    assert c.post("/api/purchase-orders/", _po(demo, lines=[]), format="json").status_code == 400
    dup = _po(demo)
    dup["lines"].append(dup["lines"][0])
    assert c.post("/api/purchase-orders/", dup, format="json").status_code == 400
    airtime = Product.objects.get(sku="AIRTIME-1K")  # not stocked
    bad = _po(demo, lines=[{"product": airtime.pk, "quantity": "5", "unit_cost": "900"}])
    assert c.post("/api/purchase-orders/", bad, format="json").status_code == 400
    r = c.post("/api/purchase-orders/", _po(demo), format="json")
    assert r.status_code == 201 and r.data["total"] == "405000.00", r.data
    assert r.data["supplier_name"] == "Wholesaler"
    # Orders are not edited after creation
    assert c.patch(f"/api/purchase-orders/{r.data['id']}/", {"note": "x"}, format="json").status_code == 405


def test_storekeeper_receives_but_cannot_order(demo, client_for):
    admin = client_for("ll_admin", demo["ll"])
    po = admin.post("/api/purchase-orders/", _po(demo), format="json").data
    store = client_for("ll_store", demo["ll"])
    assert store.post("/api/purchase-orders/", _po(demo), format="json").status_code == 403
    assert store.get(f"/api/purchase-orders/{po['id']}/").status_code == 200
    lines = {str(l["id"]): "10" for l in po["lines"]}
    r = store.post(f"/api/purchase-orders/{po['id']}/receive/", {"lines": lines}, format="json")
    assert r.status_code == 200 and r.data["status"] == "partial"
    # Partially received orders cannot be cancelled
    assert admin.post(f"/api/purchase-orders/{po['id']}/cancel/").status_code == 400


def test_cancel_open_order(demo, client_for):
    admin = client_for("ll_admin", demo["ll"])
    po = admin.post("/api/purchase-orders/", _po(demo), format="json").data
    assert client_for("ll_store", demo["ll"]).post(f"/api/purchase-orders/{po['id']}/cancel/").status_code == 403
    r = admin.post(f"/api/purchase-orders/{po['id']}/cancel/", {"reason": "supplier out of stock"}, format="json")
    assert r.data["status"] == "cancelled"
    assert PurchaseOrder.objects.get(pk=po["id"]).status == "cancelled"
