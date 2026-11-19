"""Stock-take API (phones + back office) and scan-to-look-up."""
from django.utils.dateparse import parse_date
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.catalog.models import Category, Product
from apps.core.api import active_branch, branches_with

from . import counts
from .models import StockCount, StockCountLine

COUNT_PERMS = ("inventory.count", "inventory.verify", "inventory.adjust")


def _name(u):
    return (u.get_full_name() or u.username) if u else ""


def _err(e: counts.CountError):
    if e.status == 403:
        raise PermissionDenied(str(e))
    raise ValidationError({"detail": str(e)})


def can_verify(user, branch):
    return user.has_branch_perm(branch, "inventory.verify")


class LineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sku = serializers.CharField(source="product.sku", read_only=True)
    barcode = serializers.CharField(source="product.barcode", read_only=True)
    unit = serializers.CharField(source="product.unit", read_only=True)
    counted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StockCountLine
        fields = ["id", "product", "product_name", "sku", "barcode", "unit", "counted_qty", "counted_by_name",
                  "counted_at", "expected_qty", "verified_qty"]

    def get_counted_by_name(self, l):
        return _name(l.counted_by)

    def to_representation(self, line):
        d = super().to_representation(line)
        # Blind counts: counters don't see the system quantity (so they count, not confirm).
        if self.context.get("hide_expected"):
            d["expected_qty"] = None
            d["variance"] = None
        else:
            d["final_qty"] = str(line.final_qty)
            d["variance"] = str(line.variance)
        return d


class CountSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()
    verified_by_name = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(source="lines.count", read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), required=False, allow_null=True)

    class Meta:
        model = StockCount
        fields = ["id", "branch", "branch_name", "number", "title", "category", "category_name", "blind", "status",
                  "status_label", "note", "created_by_name", "created_at", "submitted_by_name", "submitted_at",
                  "verified_by_name", "verified_at", "line_count"]
        read_only_fields = ["branch", "number", "status", "submitted_at", "verified_at"]

    def get_created_by_name(self, c):
        return _name(c.created_by)

    def get_submitted_by_name(self, c):
        return _name(c.submitted_by)

    def get_verified_by_name(self, c):
        return _name(c.verified_by)

    def validate_category(self, c):
        if c and c.organization_id != self.context["request"].user.organization_id:
            raise serializers.ValidationError("Unknown category.")
        return c


class StockCountViewSet(viewsets.ModelViewSet):
    """?status=, ?search=, ?from=/to= (created date), ?ordering=created_at|number|status"""

    serializer_class = CountSerializer
    http_method_names = ["get", "post"]
    search_fields = ["number", "title", "note"]
    ordering_fields = ["created_at", "number", "status", "title"]
    ordering = ["-created_at"]
    filterset_fields = ["status"]

    def branch_ids(self):
        u = self.request.user
        return {b.pk for code in COUNT_PERMS for b in branches_with(u, code)}

    def get_queryset(self):
        qs = StockCount.objects.filter(branch__in=self.branch_ids()).select_related(
            "branch", "category", "created_by", "submitted_by", "verified_by")
        selected = active_branch(self.request, required=False)
        if selected:
            qs = qs.filter(branch=selected)
        p = self.request.query_params
        if parse_date(p.get("from") or ""):
            qs = qs.filter(created_at__date__gte=parse_date(p["from"]))
        if parse_date(p.get("to") or ""):
            qs = qs.filter(created_at__date__lte=parse_date(p["to"]))
        return qs

    def _detail(self, c):
        u = self.request.user
        verifier = can_verify(u, c.branch)
        hide = c.blind and not verifier and c.status != "posted"
        lines = c.lines.select_related("product", "counted_by")
        d = CountSerializer(c, context={"request": self.request}).data
        d["lines"] = LineSerializer(lines, many=True, context={"hide_expected": hide}).data
        d["can_count"] = c.status == "counting" and any(u.has_branch_perm(c.branch, x) for x in COUNT_PERMS)
        d["can_verify"] = verifier and c.status == "submitted" and (
            not counts.counted_it(c, u) or u.has_org_perm("org.admin"))
        d["i_counted"] = counts.counted_it(c, u)
        d["is_verifier"] = verifier
        if not hide:
            d["summary"] = {"lines": len(d["lines"]),
                            "differences": sum(1 for l in lines if l.variance != 0),
                            "short": str(sum((l.variance for l in lines if l.variance < 0), 0)),
                            "over": str(sum((l.variance for l in lines if l.variance > 0), 0))}
        return d

    def retrieve(self, request, *args, **kwargs):
        return Response(self._detail(self.get_object()))

    def create(self, request, *args, **kwargs):
        branch = active_branch(request)
        u = request.user
        if not any(u.has_branch_perm(branch, x) for x in COUNT_PERMS):
            raise PermissionDenied("You can't start stock takes at this branch.")
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        c = counts.create(branch=branch, by=u, title=v.get("title", ""), category=v.get("category"),
                          blind=v.get("blind", True), note=v.get("note", ""))
        return Response(self._detail(c), status=201)

    def _count(self):
        c = self.get_object()
        if not any(self.request.user.has_branch_perm(c.branch, x) for x in COUNT_PERMS):
            raise PermissionDenied("No stock-take rights at this branch.")
        return c

    def _verifier(self, c):
        if not can_verify(self.request.user, c.branch):
            raise PermissionDenied("Only stock verifiers can do this.")

    @action(detail=True, methods=["post"])
    def scan(self, request, pk=None):
        """{code} or {product}, qty (default 1), mode add|set."""
        c = self._count()
        d = request.data
        if d.get("product"):
            p = Product.objects.filter(pk=d["product"], organization=c.branch.organization).first()
        else:
            p = counts.find_product(c.branch.organization, d.get("code", ""))
        if not p:
            raise NotFound(f"No product with code {d.get('code', '')!s}.")
        try:
            line = counts.record(c, product=p, qty=d.get("qty", 1), by=request.user, mode=d.get("mode", "add"))
        except counts.CountError as e:
            _err(e)
        hide = c.blind and not can_verify(request.user, c.branch)
        return Response({"line": LineSerializer(line, context={"hide_expected": hide}).data,
                         "lines": c.lines.count()}, status=201)

    @action(detail=True, methods=["post"], url_path=r"lines/(?P<line_id>\d+)/remove")
    def remove_line(self, request, pk=None, line_id=None):
        c = self._count()
        line = c.lines.filter(pk=line_id).first() or None
        if not line:
            raise NotFound("No such line.")
        try:
            counts.remove_line(c, line, request.user)
        except counts.CountError as e:
            _err(e)
        return Response(self._detail(c))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        c = self._count()
        try:
            counts.submit(c, request.user)
        except counts.CountError as e:
            _err(e)
        return Response(self._detail(c))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        c = self._count()
        self._verifier(c)
        try:
            counts.reopen(c, request.user)
        except counts.CountError as e:
            _err(e)
        return Response(self._detail(c))

    @action(detail=True, methods=["post"])
    def recount(self, request, pk=None):
        """{line, qty}: the verifier's own count for a line."""
        c = self._count()
        self._verifier(c)
        line = c.lines.filter(pk=request.data.get("line")).first()
        if not line:
            raise NotFound("No such line.")
        try:
            counts.recount(c, line, qty=request.data.get("qty"), by=request.user)
        except counts.CountError as e:
            _err(e)
        return Response(self._detail(c))

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        c = self._count()
        self._verifier(c)
        try:
            counts.post(c, request.user)
        except counts.CountError as e:
            _err(e)
        c.refresh_from_db()
        return Response(self._detail(c))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        c = self._count()
        if c.created_by_id != request.user.pk:
            self._verifier(c)
        try:
            counts.cancel(c, request.user)
        except counts.CountError as e:
            _err(e)
        return Response(self._detail(c))


@api_view(["GET"])
def lookup(request):
    """GET /api/stock/lookup/?code=<barcode or SKU> -> product + stock per branch you can see."""
    u = request.user
    if not any(branches_with(u, x) for x in ("inventory.view", "pos.sell", "inventory.count")):
        raise PermissionDenied("You can't look up stock.")
    data = counts.lookup(u, request.query_params.get("code", ""))
    if not data:
        raise NotFound(f"No product with code {request.query_params.get('code', '')}.")
    return Response(data)


# ------------------------------------------------------------------------------------------ Excel upload
@api_view(["GET"])
def stock_import_template(request):
    """GET /api/stock/import/template/ -> stock-upload.xlsx to fill in."""
    from django.http import HttpResponse
    from . import importer
    r = HttpResponse(importer.template_workbook(),
                     content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = 'attachment; filename="stock-upload.xlsx"'
    return r


@api_view(["POST"])
def stock_import(request):
    """POST /api/stock/import/ (multipart): file, mode=add|set, apply=0|1.
    apply=0 checks every row and shows what would change; apply=1 saves it, only if no row has an error."""
    from rest_framework.parsers import MultiPartParser  # noqa: F401  (multipart is in the default parsers)
    from . import importer
    branch = active_branch(request)
    u = request.user
    mode = request.data.get("mode", "add")
    if mode not in ("add", "set"):
        raise ValidationError({"mode": "Choose add (goods in / opening stock) or set (stock count)."})
    needed = ["inventory.adjust"] if mode == "set" else ["inventory.adjust", "inventory.receive"]
    if not any(u.has_branch_perm(branch, p) for p in needed):
        raise PermissionDenied("You can't change stock at this branch.")
    f = request.FILES.get("file")
    if not f:
        raise ValidationError({"file": "Choose an Excel (.xlsx) or CSV file."})
    can_create = u.has_org_perm("catalog.manage") or u.has_branch_perm(branch, "catalog.manage")
    try:
        rows = importer.read_rows(f)
    except importer.ImportError_ as e:
        raise ValidationError({"file": str(e)})
    results, summary = importer.check(rows, branch=branch, mode=mode, can_create=can_create)
    out = {"summary": summary, "rows": results, "mode": mode, "branch": branch.name, "can_create": can_create}
    if str(request.data.get("apply", "0")).lower() in ("1", "true", "yes"):
        if summary["errors"]:
            raise ValidationError({"detail": f"{summary['errors']} row(s) have problems. Fix them and upload again.",
                                   **out})
        out["applied"] = importer.apply(results, branch=branch, mode=mode, user=u, can_create=can_create,
                                        file_name=f.name[:80])
    return Response(out)
