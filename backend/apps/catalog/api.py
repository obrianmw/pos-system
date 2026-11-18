import io
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db.models import Count
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api import OrgScopedViewSet, active_branch, require_perm
from apps.core.models import Branch, audit
from apps.inventory.models import StockLevel
from apps.payments.models import PaymentMethod

from .models import BranchPrice, Category, Product, TaxRate

MAX_UPLOAD = 5 * 1024 * 1024
MAX_SIDE = 800


def process_image(f, stem):
    """Accept a photo (JPEG/PNG/WebP), check it really is an image, strip metadata (incl. location),
    shrink to at most 800 px and store as WebP so tills load it quickly."""
    if f.size > MAX_UPLOAD:
        raise serializers.ValidationError("Photo is larger than 5 MB.")
    try:
        img = Image.open(f)
        img.verify()  # detects truncated/corrupt files
        f.seek(0)
        img = Image.open(f)
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise serializers.ValidationError("Use a JPEG, PNG or WebP photo.")
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise serializers.ValidationError("That file is not a readable image.")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82)
    return ContentFile(out.getvalue(), name=f"{stem}.webp")


def descendant_ids(org, root_id):
    """root and every category below it (one query; trees are small)."""
    children = {}
    for cid, parent in Category.objects.filter(organization=org).values_list("id", "parent_id"):
        children.setdefault(parent, []).append(cid)
    out, stack = set(), [int(root_id)]
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(children.get(c, []))
    return out


def image_url(field):
    return field.url if field else None


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        exclude = ["organization"]


class CategorySerializer(serializers.ModelSerializer):
    image = serializers.ImageField(write_only=True, required=False)
    image_url = serializers.SerializerMethodField()
    path = serializers.SerializerMethodField()

    class Meta:
        model = Category
        exclude = ["organization"]

    def get_image_url(self, c):
        return image_url(c.image)

    def get_path(self, c):
        return c.path()

    def validate_image(self, f):
        return process_image(f, "category")

    def validate(self, attrs):
        org = self.context["request"].user.organization
        parent = attrs.get("parent")
        if parent is not None:
            if parent.organization_id != org.pk:
                raise serializers.ValidationError({"parent": "Not found."})
            if self.instance and parent.pk in descendant_ids(org, self.instance.pk):
                raise serializers.ValidationError({"parent": "A category cannot sit inside itself or its own subcategory."})
        name = attrs.get("name", getattr(self.instance, "name", "")).strip()
        qs = Category.objects.filter(organization=org, parent=parent if "parent" in attrs else getattr(self.instance, "parent", None),
                                     name__iexact=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": "This category already exists here."})
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    category_path = serializers.SerializerMethodField()
    tax_name = serializers.CharField(source="tax_rate.name", read_only=True, default="")
    image = serializers.ImageField(write_only=True, required=False)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        exclude = ["organization"]

    def _org(self):
        return self.context["request"].user.organization

    def get_category_path(self, p):
        return p.category.path() if p.category_id else ""

    def get_image_url(self, p):
        return image_url(p.image)

    def validate_image(self, f):
        sku = self.initial_data.get("sku") or getattr(self.instance, "sku", "") or "product"
        return process_image(f, "".join(ch for ch in str(sku).lower() if ch.isalnum() or ch in "-_") or "product")

    def validate_sku(self, value):
        value = value.strip().upper()
        qs = Product.objects.filter(organization=self._org(), sku__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another product already uses this SKU.")
        return value

    def validate_barcode(self, value):
        value = value.strip()
        if value:
            qs = Product.objects.filter(organization=self._org(), barcode=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(f"Barcode already used by {qs.first().name}.")
        return value

    def validate(self, attrs):
        org = self._org()
        for f in ("category", "tax_rate"):
            if attrs.get(f) and attrs[f].organization_id != org.pk:
                raise serializers.ValidationError({f: "Not found."})

        def get(k):
            return attrs.get(k, getattr(self.instance, k, None))

        sell, cost, floor = get("sell_price"), get("cost_price"), get("min_price")
        if sell is not None and sell <= 0:
            raise serializers.ValidationError({"sell_price": "Must be more than zero."})
        if cost is not None and cost < 0:
            raise serializers.ValidationError({"cost_price": "Cannot be negative."})
        if floor is not None and sell is not None and floor > sell:
            raise serializers.ValidationError({"min_price": "Floor price cannot be above the selling price."})
        return attrs


class BranchPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchPrice
        fields = "__all__"


class TaxRateViewSet(OrgScopedViewSet):
    queryset = TaxRate.objects.all()
    serializer_class = TaxRateSerializer
    write_perm = "catalog.manage"


class CategoryViewSet(OrgScopedViewSet):
    queryset = Category.objects.select_related("parent")
    serializer_class = CategorySerializer
    write_perm = "catalog.manage"
    filterset_fields = ["parent"]

    def check_write(self):
        if not self.request.user.has_org_perm("catalog.manage"):
            raise PermissionDenied("Only head-office catalog managers change categories.")

    def perform_update(self, serializer):
        self.check_write()
        if self.request.data.get("clear_image") in ("1", "true", True):
            serializer.instance.image.delete(save=False)
            serializer.save(image="")
        else:
            serializer.save()

    def perform_destroy(self, instance):
        self.check_write()
        if instance.children.exists():
            raise ValidationError({"detail": "Move or delete its subcategories first."})
        if Product.objects.filter(category=instance).exists():
            raise ValidationError({"detail": "Move its products to another category first."})
        instance.delete()

    @action(detail=False)
    def tree(self, request):
        """All categories with direct and total (incl. subcategories) active product counts."""
        org = request.user.organization
        cats = list(Category.objects.filter(organization=org).select_related("parent"))
        direct = dict(Product.objects.filter(organization=org, is_active=True, category__isnull=False)
                      .values_list("category").annotate(n=Count("id")))
        kids = {}
        for c in cats:
            kids.setdefault(c.parent_id, []).append(c)

        def total(c, seen=()):
            if c.pk in seen:
                return 0
            return direct.get(c.pk, 0) + sum(total(k, seen + (c.pk,)) for k in kids.get(c.pk, []))

        return Response([{"id": c.pk, "name": c.name, "parent": c.parent_id, "path": c.path(),
                          "image_url": image_url(c.image), "sort_order": c.sort_order,
                          "products": direct.get(c.pk, 0), "total_products": total(c)} for c in cats])


class ProductViewSet(OrgScopedViewSet):
    """The product master is shared by every branch, so writing it needs catalog.manage org-wide.
    Branch admins (catalog.manage at one branch) set that branch's price via branch_prices.
    ?category_tree=<id> lists products in that category and every subcategory below it."""

    queryset = Product.objects.select_related("category__parent", "tax_rate")
    serializer_class = ProductSerializer
    search_fields = ["name", "sku", "barcode"]
    filterset_fields = ["category", "is_active", "barcode", "sku"]

    def get_queryset(self):
        qs = super().get_queryset()
        tree = self.request.query_params.get("category_tree")
        if tree:
            qs = qs.filter(category__in=descendant_ids(self.request.user.organization, tree))
        return qs

    def check_write(self):
        if not self.request.user.has_org_perm("catalog.manage"):
            raise PermissionDenied("Only head-office catalog managers edit products. "
                                   "Set your branch price under Branch prices instead.")

    def perform_update(self, serializer):
        self.check_write()
        fields = ("sell_price", "cost_price", "min_price", "is_active")
        before = {f: str(getattr(serializer.instance, f)) for f in fields}
        if self.request.data.get("clear_image") in ("1", "true", True):
            serializer.instance.image.delete(save=False)
            p = serializer.save(image="")
        else:
            p = serializer.save()
        changed = {f: [before[f], str(getattr(p, f))] for f in fields if before[f] != str(getattr(p, f))}
        if changed:
            audit("product.updated", organization=p.organization, actor=self.request.user, obj=p,
                  sku=p.sku, **changed)

    def perform_destroy(self, instance):
        raise PermissionDenied("Products with history cannot be deleted; untick Active instead.")

    @action(detail=True, methods=["get", "post"])
    def branch_prices(self, request, pk=None):
        """GET: the price at each branch you can see. POST {"branch", "price"}: set it; an empty
        price removes the override so the branch sells at the base price."""
        product = self.get_object()
        if request.method == "POST":
            branch = Branch.objects.filter(pk=request.data.get("branch"), organization=product.organization).first()
            if not branch:
                raise ValidationError({"branch": "Unknown branch."})
            require_perm(request.user, branch, "catalog.manage")
            price = request.data.get("price")
            if price in (None, ""):
                BranchPrice.objects.filter(product=product, branch=branch).delete()
            else:
                price = Decimal(str(price))
                if price <= 0 or (product.min_price is not None and price < product.min_price):
                    raise ValidationError({"price": f"Must be above zero and not below the floor price {product.min_price}."})
                BranchPrice.objects.update_or_create(product=product, branch=branch, defaults={"price": price})
            audit("product.branch_price", organization=product.organization, branch=branch, actor=request.user,
                  obj=product, sku=product.sku, price=str(price))
        prices = dict(BranchPrice.objects.filter(product=product).values_list("branch_id", "price"))
        return Response([
            {"branch": b.pk, "name": b.name, "price": str(prices[b.pk]) if b.pk in prices else None,
             "base_price": str(product.sell_price), "can_edit": request.user.has_branch_perm(b, "catalog.manage")}
            for b in Branch.objects.filter(pk__in=request.user.accessible_branch_ids(), is_active=True)])


@api_view(["GET"])
def pos_catalog(request):
    """Everything a till needs to keep selling offline: products with this branch's prices, stock,
    photos and categories, plus the payment methods allowed here. The POS stores it in IndexedDB."""
    branch = active_branch(request)
    require_perm(request.user, branch, "pos.sell")
    org = branch.organization
    prices = dict(BranchPrice.objects.filter(branch=branch).values_list("product_id", "price"))
    stock = dict(StockLevel.objects.filter(branch=branch).values_list("product_id", "quantity"))
    products = Product.objects.filter(organization=org, is_active=True).select_related("tax_rate", "category__parent")
    methods = [m for m in PaymentMethod.objects.filter(organization=org, is_active=True) if m.available_at(branch)]
    cats = Category.objects.filter(organization=org).select_related("parent")
    return Response({
        "branch": {"id": branch.pk, "name": branch.name, "code": branch.code, "currency": org.currency,
                   "max_cashier_discount_pct": str(branch.max_cashier_discount_pct),
                   "receipt_footer": branch.receipt_footer, "organization": org.name},
        "categories": [{"id": c.pk, "name": c.name, "parent": c.parent_id, "path": c.path(),
                        "image_url": image_url(c.image), "sort_order": c.sort_order} for c in cats],
        "products": [{
            "id": p.pk, "sku": p.sku, "barcode": p.barcode, "name": p.name, "unit": p.unit,
            "category": p.category.name if p.category else "", "category_id": p.category_id,
            "category_path": p.category.path() if p.category_id else "", "image_url": image_url(p.image),
            "price": str(prices.get(p.pk, p.sell_price)),
            "min_price": str(p.min_price) if p.min_price is not None else None,
            "tax_rate": str(p.tax_rate.rate) if p.tax_rate else "0",
            "tax_inclusive": p.tax_rate.inclusive if p.tax_rate else True,
            "track_stock": p.track_stock, "stock": str(stock.get(p.pk, 0)), "reorder_level": str(p.reorder_level),
        } for p in products],
        "payment_methods": [{"id": m.pk, "name": m.name, "kind": m.kind, "provider": m.provider,
                             "requires_reference": m.requires_reference, "allowed_offline": m.allowed_offline}
                            for m in methods],
    })
