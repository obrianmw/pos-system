from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.catalog.models import Product
from apps.core.api import BranchScopedViewSet, OrgScopedViewSet, active_branch, branches_with, require_perm
from apps.core.models import Till, audit
from apps.payments.models import Payment

from . import services
from .models import Customer, OverrideApproval, Sale, SaleLine, TillSession


def pos_error_response(e: services.POSError):
    code = status.HTTP_403_FORBIDDEN if isinstance(e, services.PermissionDenied) else \
        status.HTTP_409_CONFLICT if isinstance(e, services.OverrideRequired) else status.HTTP_400_BAD_REQUEST
    return Response({"detail": str(e), "code": e.code, **e.extra}, status=code)


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        exclude = ["organization"]


class PaymentSerializer(serializers.ModelSerializer):
    method_name = serializers.CharField(source="method.name", read_only=True)
    change = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "method", "method_name", "amount", "tendered", "change", "status", "provider_reference",
                  "payer_phone", "checkout_url", "message", "client_reference", "confirmed_at"]

    def get_change(self, p):
        return str(p.tendered - p.amount) if p.tendered is not None else None


class SaleLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SaleLine
        exclude = ["sale", "unit_cost"]


class SaleSerializer(serializers.ModelSerializer):
    lines = SaleLineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    cashier_name = serializers.CharField(source="cashier.get_full_name", read_only=True)

    class Meta:
        model = Sale
        fields = "__all__"


class TillSessionSerializer(serializers.ModelSerializer):
    till_name = serializers.CharField(source="till.name", read_only=True)

    class Meta:
        model = TillSession
        fields = "__all__"
        read_only_fields = ["branch", "cashier", "status", "closed_at", "closed_by", "expected_cash",
                            "counted_cash", "variance"]


class OverrideSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source="requested_by.get_full_name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True, default="")

    class Meta:
        model = OverrideApproval
        fields = "__all__"
        read_only_fields = ["status", "method", "requested_by", "approved_by", "sale", "decided_at", "branch"]


class CustomerViewSet(OrgScopedViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    search_fields = ["name", "phone", "email"]
    write_perm = "pos.sell"


class TillSessionViewSet(BranchScopedViewSet):
    queryset = TillSession.objects.select_related("till", "cashier")
    serializer_class = TillSessionSerializer
    http_method_names = ["get", "post"]
    perms = {"*": "pos.open_till", "list": "pos.open_till"}

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        # Cashiers see their own sessions; supervisors/accountants see the branch's.
        seeing_all = {b.pk for b in branches_with(u, "pos.view_all_sales")}
        from django.db.models import Q
        return qs.filter(Q(cashier=u) | Q(branch__in=seeing_all))

    def create(self, request, *args, **kwargs):
        """Open a till: {"till": id, "opening_float": "5000"}"""
        till = Till.objects.filter(pk=request.data.get("till"), branch__in=request.user.accessible_branch_ids(),
                                   is_active=True).first()
        if not till:
            raise ValidationError({"till": "Unknown till."})
        try:
            s = services.open_till(till=till, user=request.user, opening_float=request.data.get("opening_float", 0))
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(s).data, status=201)

    @action(detail=False)
    def current(self, request):
        s = TillSession.objects.filter(cashier=request.user, status="open").select_related("till").first()
        return Response(self.get_serializer(s).data if s else None)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        session = self.get_object()
        try:
            s = services.close_till(session, user=request.user, counted_cash=request.data["counted_cash"],
                                    notes=request.data.get("notes", ""))
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(s).data)

    @action(detail=True)
    def summary(self, request, pk=None):
        """X/Z report: totals per payment method for the session."""
        s = self.get_object()
        rows = (Payment.objects.filter(sale__till_session=s, status="confirmed", sale__status="completed")
                .values("sale__kind", "method__name").annotate(total=Sum("amount"), count=Count("id")))
        return Response({"session": self.get_serializer(s).data, "expected_cash": str(services.expected_cash(s)),
                         "by_method": list(rows)})


class SaleViewSet(BranchScopedViewSet):
    queryset = Sale.objects.select_related("cashier", "customer").prefetch_related("lines", "payments__method")
    serializer_class = SaleSerializer
    http_method_names = ["get", "post"]
    perms = {"*": "pos.sell"}
    filterset_fields = ["status", "kind", "till_session", "needs_review", "cashier"]
    search_fields = ["number", "customer__name", "customer__phone"]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        seeing_all = {b.pk for b in branches_with(u, "pos.view_all_sales")}
        from django.db.models import Q
        return qs.filter(Q(cashier=u) | Q(branch__in=seeing_all))

    def _session(self, request, session_id=None):
        sid = session_id or request.data.get("till_session")
        s = TillSession.objects.filter(pk=sid).select_related("branch").first() if sid else \
            TillSession.objects.filter(cashier=request.user, status="open").select_related("branch").first()
        if not s:
            raise ValidationError({"till_session": "Open a till first."})
        if s.cashier_id != request.user.pk and not request.user.has_branch_perm(s.branch, "pos.view_all_sales"):
            raise PermissionDenied("That till session belongs to someone else.")
        return s

    def create(self, request, *args, **kwargs):
        """Checkout. See services.checkout for the body. 409 + code=override_required means: ask a
        supervisor (PIN or remote approval) and resend with the line's "override" filled in."""
        try:
            sale, created = services.checkout(user=request.user, session=self._session(request), data=request.data)
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(sale).data, status=201 if created else 200)

    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Upload sales made while offline: {"sales": [<checkout body with offline=true>...]}.
        Each result says ok / error, so the till can drop synced ones from its queue."""
        results = []
        for body in request.data.get("sales", []):
            body = {**body, "offline": True}
            try:
                sale, created = services.checkout(user=request.user,
                                                  session=self._session(request, body.get("till_session")),
                                                  data=body)
                results.append({"client_uuid": str(sale.client_uuid), "ok": True, "number": sale.number,
                                "duplicate": not created, "needs_review": sale.needs_review})
            except (services.POSError, ValidationError, PermissionDenied, KeyError, Product.DoesNotExist) as e:
                results.append({"client_uuid": body.get("client_uuid"), "ok": False, "error": str(e)})
        return Response({"results": results})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        try:
            s = services.void_sale(self.get_object(), user=request.user, reason=request.data.get("reason", ""),
                                   auth=request.data.get("override"))
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        """{"lines": [{"line_id", "quantity"}], "method_id", "reason", "override"?}"""
        if not request.data.get("reason"):
            raise ValidationError({"reason": "Reason required."})
        try:
            r = services.refund(self.get_object(), user=request.user, session=self._session(request),
                                lines=request.data.get("lines", []), method_id=request.data.get("method_id"),
                                reason=request.data["reason"], auth=request.data.get("override"))
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(r).data, status=201)

    @action(detail=True, methods=["post"])
    def mark_reviewed(self, request, pk=None):
        """Clear the needs_review flag on an offline sale after checking it: {"note": "..."}."""
        sale = self.get_object()
        u = request.user
        if not (u.has_branch_perm(sale.branch, "accounting.reconcile") or u.has_branch_perm(sale.branch, "pos.void")):
            raise PermissionDenied("Needs a supervisor or accountant.")
        note = (request.data.get("note") or "").strip()
        if not note:
            raise ValidationError({"note": "Say what you checked."})
        sale.needs_review = False
        sale.review_reason = f"{sale.review_reason}\nReviewed by {u.username}: {note}".strip()
        sale.save(update_fields=["needs_review", "review_reason", "updated_at"])
        audit("sale.reviewed", organization=sale.organization, branch=sale.branch, actor=u, obj=sale, note=note)
        return Response(self.get_serializer(sale).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        try:
            s = services.cancel_pending_sale(self.get_object(), request.user, request.data.get("reason", ""))
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(s).data)

    @action(detail=True, methods=["post"])
    def add_payment(self, request, pk=None):
        sale = self.get_object()
        try:
            services.add_payment(sale, user=request.user, method_id=request.data.get("method_id"),
                                 amount=request.data.get("amount"), phone=request.data.get("phone", ""),
                                 reference=request.data.get("reference", ""), tendered=request.data.get("tendered"))
        except services.POSError as e:
            return pos_error_response(e)
        sale.refresh_from_db()
        return Response(self.get_serializer(sale).data)

    @action(detail=True, methods=["post"], url_path="payments/(?P<payment_id>[0-9]+)/refresh")
    def refresh_payment(self, request, pk=None, payment_id=None):
        """POS polls this while the customer approves on their phone."""
        sale = self.get_object()
        p = sale.payments.get(pk=payment_id)
        services.refresh_payment(p, request.user)
        sale.refresh_from_db()
        return Response(self.get_serializer(sale).data)


class OverrideViewSet(BranchScopedViewSet):
    """Remote approval: cashier POSTs a request; supervisors see pending ones and approve/reject."""

    queryset = OverrideApproval.objects.select_related("requested_by", "product")
    serializer_class = OverrideSerializer
    http_method_names = ["get", "post"]
    perms = {"*": "pos.sell"}
    filterset_fields = ["status", "kind"]

    def perform_create(self, serializer):
        branch = active_branch(self.request)
        require_perm(self.request.user, branch, "pos.sell")
        d = serializer.validated_data
        if d.get("product") and d["product"].organization_id != branch.organization_id:
            raise ValidationError("Unknown product.")
        serializer.instance = services.request_override(
            branch=branch, user=self.request.user, kind=d["kind"], reason=d.get("reason", ""),
            product=d.get("product"), original=d.get("original_value"), new=d.get("new_value"))

    def _decide(self, request, approve):
        try:
            a = services.decide_override(self.get_object(), request.user, approve)
        except services.POSError as e:
            return pos_error_response(e)
        return Response(self.get_serializer(a).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, False)


@api_view(["GET"])
def sales_summary(request):
    """Daily dashboard numbers for a branch: ?branch=&date=YYYY-MM-DD (defaults to today)."""
    branch = active_branch(request)
    if not (request.user.has_branch_perm(branch, "pos.view_all_sales")
            or request.user.has_branch_perm(branch, "accounting.view")):
        raise PermissionDenied("Not allowed.")
    day = request.query_params.get("date") or timezone.localdate().isoformat()
    sales = Sale.objects.filter(branch=branch, status="completed", completed_at__date=day)
    agg = lambda kind: sales.filter(kind=kind).aggregate(total=Sum("total"), tax=Sum("tax_total"),
                                                         discount=Sum("discount_total"), count=Count("id"))
    by_method = (Payment.objects.filter(sale__in=sales, status="confirmed")
                 .values("sale__kind", "method__name").annotate(total=Sum("amount")))
    top = (SaleLine.objects.filter(sale__in=sales.filter(kind="sale"))
           .values("product__name").annotate(qty=Sum("quantity"), total=Sum("line_total")).order_by("-total")[:10])
    return Response({"date": day, "sales": agg("sale"), "refunds": agg("refund"), "by_method": list(by_method),
                     "top_products": list(top),
                     "needs_review": Sale.objects.filter(branch=branch, needs_review=True).count(),
                     "pending_overrides": OverrideApproval.objects.filter(branch=branch, status="pending").count()})
