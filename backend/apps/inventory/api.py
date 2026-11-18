from decimal import Decimal

from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.api import BranchScopedViewSet, OrgScopedViewSet, active_branch, branches_with, require_perm
from apps.core.models import audit, next_number

from . import services
from .models import (PurchaseOrder, PurchaseOrderLine, StockLevel, StockMovement, StockTransfer,
                     StockTransferLine, Supplier)


class StockLevelSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    reorder_level = serializers.DecimalField(source="product.reorder_level", max_digits=14, decimal_places=3,
                                             read_only=True)
    category_path = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = StockLevel
        fields = ["id", "branch", "product", "product_name", "sku", "quantity", "avg_cost", "reorder_level",
                  "category_path", "image_url", "updated_at"]

    def get_category_path(self, s):
        return s.product.category.path() if s.product.category_id else ""

    def get_image_url(self, s):
        return s.product.image.url if s.product.image else None


class StockMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMovement
        fields = "__all__"


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        exclude = ["organization"]


class POLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        exclude = ["order"]
        read_only_fields = ["received_quantity"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = POLineSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ["number", "status", "created_by"]
        extra_kwargs = {"branch": {"required": False}}

    def get_total(self, o):
        return str(sum((l.quantity * l.unit_cost for l in o.lines.all()), Decimal("0")).quantize(Decimal("0.01")))

    def validate(self, attrs):
        org = self.context["request"].user.organization
        if attrs["supplier"].organization_id != org.pk or not attrs["supplier"].is_active:
            raise serializers.ValidationError({"supplier": "Unknown or inactive supplier."})
        lines = attrs.get("lines") or []
        if not lines:
            raise serializers.ValidationError({"lines": "Add at least one item."})
        seen = set()
        for l in lines:
            prod = l["product"]
            if prod.organization_id != org.pk:
                raise serializers.ValidationError({"lines": "Unknown product."})
            if not prod.track_stock:
                raise serializers.ValidationError({"lines": f"{prod.name} is not a stocked item."})
            if prod.pk in seen:
                raise serializers.ValidationError({"lines": f"{prod.name} is listed twice."})
            seen.add(prod.pk)
            if l["quantity"] <= 0 or l["unit_cost"] < 0:
                raise serializers.ValidationError({"lines": f"{prod.name}: quantity must be positive and cost not negative."})
        return attrs

    def create(self, data):
        lines = data.pop("lines")
        order = PurchaseOrder.objects.create(**data)
        PurchaseOrderLine.objects.bulk_create([PurchaseOrderLine(order=order, **l) for l in lines])
        return order


class TransferLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockTransferLine
        fields = ["id", "product", "product_name", "sku", "quantity", "unit_cost"]
        read_only_fields = ["unit_cost"]


class TransferSerializer(serializers.ModelSerializer):
    lines = TransferLineSerializer(many=True)
    from_branch_name = serializers.CharField(source="from_branch.name", read_only=True)
    to_branch_name = serializers.CharField(source="to_branch.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    received_by_name = serializers.CharField(source="received_by.get_full_name", read_only=True, default="")
    value = serializers.SerializerMethodField()

    class Meta:
        model = StockTransfer
        fields = "__all__"
        read_only_fields = ["number", "status", "created_by", "received_by"]

    def get_value(self, t):
        """Cost value; known once sent (unit cost is fixed at the sender's average cost then)."""
        return str(sum((l.quantity * l.unit_cost for l in t.lines.all()), Decimal("0")).quantize(Decimal("0.01")))

    def validate(self, attrs):
        org = self.context["request"].user.organization
        src, dst = attrs["from_branch"], attrs["to_branch"]
        if src.organization_id != org.pk or dst.organization_id != org.pk:
            raise serializers.ValidationError({"to_branch": "Unknown branch."})
        if src == dst:
            raise serializers.ValidationError({"to_branch": "Pick a different branch from the sender."})
        if not dst.is_active:
            raise serializers.ValidationError({"to_branch": "That branch is closed."})
        lines = attrs.get("lines") or []
        if not lines:
            raise serializers.ValidationError({"lines": "Add at least one item."})
        seen = set()
        for l in lines:
            prod = l["product"]
            if prod.organization_id != org.pk:
                raise serializers.ValidationError({"lines": "Unknown product."})
            if not prod.track_stock:
                raise serializers.ValidationError({"lines": f"{prod.name} is not a stocked item."})
            if prod.pk in seen:
                raise serializers.ValidationError({"lines": f"{prod.name} is listed twice."})
            seen.add(prod.pk)
            if l["quantity"] <= 0:
                raise serializers.ValidationError({"lines": f"{prod.name}: quantity must be positive."})
        return attrs


class StockLevelViewSet(BranchScopedViewSet):
    """?category_tree=<id> limits to a category and all its subcategories."""

    queryset = StockLevel.objects.select_related("product__category__parent")
    serializer_class = StockLevelSerializer
    http_method_names = ["get"]
    perms = {"*": "inventory.view"}
    search_fields = ["product__name", "product__sku", "product__barcode"]

    def get_queryset(self):
        qs = super().get_queryset()
        tree = self.request.query_params.get("category_tree")
        if tree:
            from apps.catalog.api import descendant_ids
            qs = qs.filter(product__category__in=descendant_ids(self.request.user.organization, tree))
        return qs

    @action(detail=False)
    def low(self, request):
        """Items at or below their reorder level."""
        from django.db.models import F
        qs = self.get_queryset().filter(quantity__lte=F("product__reorder_level"))
        return Response(self.get_serializer(qs[:500], many=True).data)


class StockMovementViewSet(BranchScopedViewSet):
    queryset = StockMovement.objects.select_related("product")
    serializer_class = StockMovementSerializer
    http_method_names = ["get"]
    perms = {"*": "inventory.view"}
    filterset_fields = ["product", "kind", "reference"]


@api_view(["POST"])
def adjust(request):
    """Stock take: {"product": id, "counted_quantity": "12", "reason": "..."}"""
    branch = active_branch(request)
    require_perm(request.user, branch, "inventory.adjust")
    product = Product.objects.get(pk=request.data["product"], organization=branch.organization)
    if not request.data.get("reason"):
        raise ValidationError({"reason": "Give a reason for the adjustment."})
    mv = services.adjust_stock(branch=branch, product=product, counted_quantity=request.data["counted_quantity"],
                               user=request.user, reason=request.data["reason"])
    return Response(StockMovementSerializer(mv).data if mv else {"detail": "No change"})


class SupplierViewSet(OrgScopedViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    write_perm = "purchasing.manage"
    search_fields = ["name", "phone"]


class PurchaseOrderViewSet(BranchScopedViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier", "created_by").prefetch_related("lines__product")
    serializer_class = PurchaseOrderSerializer
    http_method_names = ["get", "post"]  # orders are not edited once placed; cancel and re-order instead
    perms = {"*": "purchasing.manage", "list": "inventory.view", "retrieve": "inventory.view",
             "receive": "inventory.view", "cancel": "inventory.view"}  # actions check their own permission
    filterset_fields = ["status", "supplier"]
    search_fields = ["number", "supplier__name"]

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        require_perm(request.user, order.branch, "purchasing.manage")
        if order.status not in ("draft", "ordered"):
            raise ValidationError("Only orders with nothing received can be cancelled.")
        order.status = "cancelled"
        order.save(update_fields=["status", "updated_at"])
        audit("purchase.cancelled", organization=order.branch.organization, branch=order.branch,
              actor=request.user, obj=order, reason=request.data.get("reason", ""))
        return Response(self.get_serializer(order).data)

    def perform_create(self, serializer):
        branch = serializer.validated_data.get("branch") or active_branch(self.request)
        require_perm(self.request.user, branch, "purchasing.manage")
        with transaction.atomic():
            serializer.save(branch=branch, created_by=self.request.user,
                            number=next_number(f"po:{branch.organization_id}", "PO-", 6), status="ordered")

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """{"lines": {"<line_id>": "<qty received now>"}}"""
        order = self.get_object()
        require_perm(request.user, order.branch, "inventory.receive")
        if order.status not in ("ordered", "partial"):
            raise ValidationError("Order is not open for receiving.")
        try:
            services.receive_purchase(order, request.user, request.data.get("lines", {}))
        except ValueError as e:
            raise ValidationError(str(e))
        order.refresh_from_db()
        return Response(self.get_serializer(order).data)


class TransferViewSet(BranchScopedViewSet):
    """Visible to both the sending and the receiving branch."""

    queryset = StockTransfer.objects.select_related("from_branch", "to_branch").prefetch_related("lines")
    serializer_class = TransferSerializer
    http_method_names = ["get", "post"]  # not edited once created; cancel a draft and start again
    perms = {"*": "inventory.transfer"}
    filterset_fields = ["status", "from_branch", "to_branch"]
    search_fields = ["number"]

    def get_queryset(self):
        from django.db.models import Q
        allowed = [b.pk for b in branches_with(self.request.user, "inventory.transfer")]
        qs = StockTransfer.objects.filter(Q(from_branch__in=allowed) | Q(to_branch__in=allowed))
        selected = self.request.headers.get("X-Branch-ID")
        if selected:  # "this branch" = anything going out of it or coming into it
            qs = qs.filter(Q(from_branch=selected) | Q(to_branch=selected))
        return (qs.select_related("from_branch", "to_branch", "created_by", "received_by")
                .prefetch_related("lines__product").order_by("-created_at"))

    def perform_create(self, serializer):
        src = serializer.validated_data["from_branch"]
        require_perm(self.request.user, src, "inventory.transfer")
        lines = serializer.validated_data.pop("lines")
        with transaction.atomic():
            t = serializer.save(created_by=self.request.user,
                                number=next_number(f"trf:{src.organization_id}", "TRF-", 6))
            StockTransferLine.objects.bulk_create([StockTransferLine(transfer=t, **l) for l in lines])

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        t = self.get_object()
        require_perm(request.user, t.from_branch, "inventory.transfer")
        try:
            services.send_transfer(t, request.user)
        except (ValueError, services.InsufficientStock) as e:
            raise ValidationError(str(e))
        return Response(self.get_serializer(self.get_queryset().get(pk=t.pk)).data)  # fresh lines

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        t = self.get_object()
        require_perm(request.user, t.from_branch, "inventory.transfer")
        if t.status != "draft":
            raise ValidationError("Only drafts can be cancelled; goods already sent must be received.")
        t.status = "cancelled"
        t.save(update_fields=["status", "updated_at"])
        audit("transfer.cancelled", organization=t.from_branch.organization, branch=t.from_branch,
              actor=request.user, obj=t)
        return Response(self.get_serializer(self.get_queryset().get(pk=t.pk)).data)  # fresh lines

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        t = self.get_object()
        if not request.user.has_branch_perm(t.to_branch, "inventory.transfer"):
            raise PermissionDenied("Only the receiving branch can receive this transfer.")
        try:
            services.receive_transfer(t, request.user)
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(self.get_serializer(self.get_queryset().get(pk=t.pk)).data)  # fresh lines
