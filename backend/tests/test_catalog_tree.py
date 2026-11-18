import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.models import Category, Product

pytestmark = pytest.mark.django_db


def cat(name):
    return Category.objects.get(name=name)


def png(w=1600, h=1200, fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 60, 40)).save(buf, fmt)
    return SimpleUploadedFile(f"photo.{fmt.lower()}", buf.getvalue(), content_type=f"image/{fmt.lower()}")


def test_tree_counts_and_paths(demo, client_for):
    rows = {r["path"]: r for r in client_for("owner").get("/api/categories/tree/").data}
    assert rows["Food"]["total_products"] == 14 and rows["Food"]["products"] == 0
    assert rows["Food › Meat & Poultry"]["products"] == 3
    assert all(r["image_url"] for r in rows.values())


def test_filter_by_category_includes_subcategories(demo, client_for):
    c = client_for("owner")
    food = c.get(f"/api/products/?category_tree={cat('Food').pk}&page_size=100").data
    assert food["count"] == 14
    meat = c.get(f"/api/products/?category_tree={cat('Meat & Poultry').pk}").data["results"]
    assert {p["sku"] for p in meat} == {"BEEF-1KG", "CHICK-WHL", "GOAT-1KG"}
    assert meat[0]["category_path"] == "Food › Meat & Poultry" and meat[0]["image_url"].startswith("/media/")
    # Stock page uses the same filter.
    store = client_for("ll_store", demo["ll"])
    veg = store.get(f"/api/stock-levels/?category_tree={cat('Vegetables').pk}").data
    assert veg["count"] == 4 and all(r["image_url"] for r in veg["results"])


def test_pos_catalog_has_categories_and_pictures(demo, client_for):
    data = client_for("ll_cash1", demo["ll"]).get("/api/pos/catalog/").data
    assert {c["name"] for c in data["categories"] if c["parent"] is None} == {"Food", "Drinks", "Household", "Services"}
    beef = next(p for p in data["products"] if p["sku"] == "BEEF-1KG")
    assert beef["category_path"] == "Food › Meat & Poultry" and beef["image_url"] and beef["stock"] == "60.000"


def test_photo_upload_is_resized_and_rejects_non_images(demo, client_for):
    c = client_for("owner")
    pid = Product.objects.get(sku="BEEF-1KG").pk
    r = c.patch(f"/api/products/{pid}/", {"image": png()}, format="multipart")
    assert r.status_code == 200, r.data
    p = Product.objects.get(pk=pid)
    assert p.image.name.endswith(".webp")
    with Image.open(p.image.path) as im:
        assert max(im.size) == 800  # 1600x1200 shrunk to fit 800
    bad = SimpleUploadedFile("evil.png", b"<svg onload=alert(1)>", content_type="image/png")
    assert c.patch(f"/api/products/{pid}/", {"image": bad}, format="multipart").status_code == 400
    r = c.patch(f"/api/products/{pid}/", {"clear_image": "true"}, format="multipart")
    assert r.status_code == 200 and r.data["image_url"] is None


def test_only_head_office_changes_categories(demo, client_for):
    assert client_for("ll_admin").post("/api/categories/", {"name": "Snacks", "parent": cat("Food").pk},
                                       format="json").status_code == 403
    r = client_for("owner").post("/api/categories/", {"name": "Snacks", "parent": cat("Food").pk}, format="json")
    assert r.status_code == 201 and r.data["path"] == "Food › Snacks"
    assert client_for("owner").post("/api/categories/", {"name": "snacks", "parent": cat("Food").pk},
                                    format="json").status_code == 400  # duplicate under same parent


def test_category_cycles_and_safe_delete(demo, client_for):
    c = client_for("owner")
    food, meat = cat("Food"), cat("Meat & Poultry")
    assert c.patch(f"/api/categories/{food.pk}/", {"parent": meat.pk}, format="json").status_code == 400
    assert c.patch(f"/api/categories/{food.pk}/", {"parent": food.pk}, format="json").status_code == 400
    assert c.delete(f"/api/categories/{food.pk}/").status_code == 400  # has subcategories
    assert c.delete(f"/api/categories/{meat.pk}/").status_code == 400  # has products
    empty = c.post("/api/categories/", {"name": "Frozen", "parent": food.pk}, format="json").data
    assert c.delete(f"/api/categories/{empty['id']}/").status_code == 204
