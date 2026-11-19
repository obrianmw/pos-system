"""Proformas (quotations): priced like a sale at the branch's prices, numbered, reprintable.
No stock moves and nothing is posted to the books."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.api import BranchScopedViewSet, active_branch, require_perm
from apps.core.models import Branding, audit, next_number

from .models import Proforma
from .services import _price_line, q

ZERO = Decimal("0")


class ProformaSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source="branch.name", read_only=True)

    class Meta:
        model = Proforma
        fields = "__all__"

    def get_created_by_name(self, p):
        return p.created_by.get_full_name() or p.created_by.username


class ProformaViewSet(BranchScopedViewSet):
    queryset = Proforma.objects.select_related("branch", "created_by")
    serializer_class = ProformaSerializer
    http_method_names = ["get", "post"]
    perms = {"*": "pos.sell"}
    search_fields = ["number", "customer_name", "customer_phone"]

    def create(self, request, *args, **kwargs):
        """{"lines": [{"product_id", "quantity", "unit_price"?}], "customer_name", "customer_phone", "note"}"""
        branch = active_branch(request)
        require_perm(request.user, branch, "pos.sell")
        org = branch.organization
        raw_lines = request.data.get("lines") or []
        if not raw_lines:
            raise ValidationError({"lines": "Add at least one item."})
        can_override = request.user.has_branch_perm(branch, "pos.price_override")
        lines, subtotal, tax_total, total = [], ZERO, ZERO, ZERO
        for raw in raw_lines:
            p = Product.objects.filter(pk=raw.get("product_id"), organization=org, is_active=True).select_related("tax_rate").first()
            if not p:
                raise ValidationError({"lines": "Unknown product."})
            try:
                qty = Decimal(str(raw.get("quantity", 1)))
            except Exception:
                raise ValidationError({"lines": "Quantity must be a number."})
            if qty <= 0:
                raise ValidationError({"lines": f"{p.name}: quantity must be positive."})
            list_price = p.price_at(branch)
            price = q(raw["unit_price"]) if raw.get("unit_price") not in (None, "") else list_price
            if price != list_price and not can_override:
                raise PermissionDenied(f"{p.name}: changing the price on a proforma needs a supervisor.")
            if p.min_price is not None and price < p.min_price:
                raise ValidationError({"lines": f"{p.name}: price is below the floor price {p.min_price}."})
            rate = p.tax_rate.rate if p.tax_rate else ZERO
            inclusive = p.tax_rate.inclusive if p.tax_rate else True
            line = SimpleNamespace(quantity=qty, unit_price=price, discount_amount=ZERO)
            _price_line(line, p, rate, inclusive)
            lines.append({"product_id": p.pk, "sku": p.sku, "name": p.name, "unit": p.unit, "quantity": str(qty),
                          "unit_price": str(price), "list_price": str(list_price), "tax_rate": str(rate),
                          "tax_inclusive": inclusive, "tax_amount": str(line.tax_amount), "line_total": str(line.line_total)})
            subtotal += q(qty * price)
            tax_total += line.tax_amount
            total += line.line_total
        b = Branding.for_org(org)
        with transaction.atomic():
            pf = Proforma.objects.create(
                organization=org, branch=branch, created_by=request.user,
                number=b.proforma_prefix + next_number(f"pf:{org.pk}", "", 6),
                customer_name=(request.data.get("customer_name") or "")[:200],
                customer_phone=(request.data.get("customer_phone") or "")[:30],
                note=(request.data.get("note") or "")[:255], lines=lines,
                subtotal=subtotal, tax_total=tax_total, total=total,
                valid_until=timezone.localdate() + timedelta(days=b.proforma_validity_days))
        audit("proforma.created", organization=org, branch=branch, actor=request.user, obj=pf, total=str(total))
        return Response(self.get_serializer(pf).data, status=201)
