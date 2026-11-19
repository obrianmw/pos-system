from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.api import branches_with
from apps.sales.models import TillSession

from . import services
from .models import CashTransfer, Vault, active_custody


def _name(u):
    return (u.get_full_name() or u.username) if u else ""


def can_see_vault(user, branch):
    return any(user.has_branch_perm(branch, p) for p in ("branch.admin", "vault.operate", "accounting.view"))


class TransferSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    direction = serializers.CharField(read_only=True)
    till_name = serializers.CharField(source="till_session.till.name", read_only=True, default="")
    created_by_name = serializers.SerializerMethodField()

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    confirmed_by_name = serializers.SerializerMethodField()
    difference = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = CashTransfer
        fields = ["id", "branch", "kind", "kind_label", "direction", "amount", "till_session", "till_name",
                  "counterparty", "reference", "note", "created_by_name", "vault_balance_after", "created_at",
                  "status", "status_label", "received_amount", "difference", "confirmed_by_name", "confirmed_at",
                  "confirm_note"]

    def get_confirmed_by_name(self, t):
        return _name(t.confirmed_by)

    def get_created_by_name(self, t):
        return _name(t.created_by)


def _err(e: services.CashError):
    if e.status == 403:
        raise PermissionDenied(str(e))
    raise ValidationError({"detail": str(e)})


class VaultViewSet(viewsets.ReadOnlyModelViewSet):
    """One vault per branch: balance, today's holder, open tills and the actions on it."""

    def get_queryset(self):
        u = self.request.user
        ids = [b.pk for b in branches_with(u, "branch.admin")] + [b.pk for b in branches_with(u, "vault.operate")] \
            + [b.pk for b in branches_with(u, "accounting.view")]
        for b in set(ids):
            from apps.core.models import Branch
            services.vault_for(Branch.objects.get(pk=b))
        qs = Vault.objects.filter(branch__in=set(ids)).select_related("branch")
        if self.request.headers.get("X-Branch-ID"):
            qs = qs.filter(branch=self.request.headers["X-Branch-ID"])
        return qs.order_by("branch__name")

    def _data(self, v):
        u = self.request.user
        c = active_custody(v)
        sessions = TillSession.objects.filter(branch=v.branch, status="open").select_related("till", "cashier")
        return {
            "id": v.pk, "branch": v.branch_id, "branch_name": v.branch.name, "name": v.name,
            "balance": str(services.vault_balance(v.branch)),
            "custodian": {"id": c.custodian_id, "name": _name(c.custodian), "until": c.valid_until,
                          "since": c.starts_at} if c else None,
            "i_hold_it": bool(c and c.custodian_id == u.pk),
            "can_operate": u.has_branch_perm(v.branch, "vault.operate"),
            "can_assign": u.has_org_perm("org.admin") or u.has_branch_perm(v.branch, "branch.admin"),
            "open_tills": [{"session": s.pk, "till": s.till.name, "cashier": _name(s.cashier), "opened_at": s.opened_at,
                            "balance": str(services.till_balance(s))} for s in sessions],
            "in_transit": str(services.pending_total(v.branch)),
            "pending": TransferSerializer(CashTransfer.objects.filter(branch=v.branch, status="pending")
                                          .select_related("till_session__till", "created_by").order_by("created_at"),
                                          many=True).data,
        }

    def list(self, request, *args, **kwargs):
        return Response([self._data(v) for v in self.get_queryset()])

    def retrieve(self, request, *args, **kwargs):
        return Response(self._data(self.get_object()))

    @action(detail=True, methods=["get"])
    def candidates(self, request, pk=None):
        """People who can be given the vault: active staff of this branch."""
        v = self.get_object()
        users = User.objects.filter(organization=v.branch.organization, is_active=True,
                                    memberships__is_active=True, memberships__branch=v.branch).distinct()
        return Response([{"id": x.pk, "name": _name(x), "username": x.username} for x in users.order_by("first_name")])

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """{"custodian": user id, "until": ISO datetime (optional, default end of today), "note"}"""
        v = self.get_object()
        target = User.objects.filter(pk=request.data.get("custodian"), organization=request.user.organization).first()
        if not target:
            raise ValidationError({"custodian": "Choose who holds the vault."})
        until = parse_datetime(request.data["until"]) if request.data.get("until") else None
        if until and timezone.is_naive(until):
            until = timezone.make_aware(until)
        try:
            services.assign_custody(v, custodian=target, by=request.user, until=until, note=request.data.get("note", ""))
        except services.CashError as e:
            _err(e)
        return Response(self._data(v))

    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        v = self.get_object()
        try:
            services.release_custody(v, by=request.user)
        except services.CashError as e:
            _err(e)
        return Response(self._data(v))

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """{"kind", "amount", "till_session"?, "reference"?, "counterparty"?, "note"?}"""
        v = self.get_object()
        d = request.data
        session = None
        if d.get("till_session"):
            session = TillSession.objects.filter(pk=d["till_session"], branch=v.branch).select_related("till").first()
        try:
            t = services.move(branch=v.branch, kind=d.get("kind", ""), amount=d.get("amount"), by=request.user,
                              session=session, reference=d.get("reference", ""), counterparty=d.get("counterparty", ""),
                              note=d.get("note", ""))
        except services.CashError as e:
            _err(e)
        return Response({"transfer": TransferSerializer(t).data, "vault": self._data(v)}, status=201)


    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """{"transfer": id, "received_amount": "...", "note": "..."} - the holder confirms a till handover."""
        v = self.get_object()
        t = CashTransfer.objects.filter(pk=request.data.get("transfer"), branch=v.branch).first()
        if not t:
            raise ValidationError({"transfer": "Choose a handover at this branch."})
        try:
            services.confirm(t, received=request.data.get("received_amount"), by=request.user,
                             note=request.data.get("note", ""))
        except services.CashError as e:
            _err(e)
        return Response(self._data(v))


class TransferViewSet(viewsets.ReadOnlyModelViewSet):
    """Cash movement history. Filters: kind, till_session, created_at range (?from=&to=), search, ordering."""

    serializer_class = TransferSerializer
    filterset_fields = ["kind", "till_session", "status"]
    search_fields = ["reference", "counterparty", "note", "till_session__till__name"]
    ordering_fields = ["created_at", "amount", "kind"]
    ordering = ["-created_at"]

    def get_queryset(self):
        u = self.request.user
        from apps.core.models import Branch
        ids = [b.pk for b in Branch.objects.filter(pk__in=u.accessible_branch_ids()) if can_see_vault(u, b)]
        qs = CashTransfer.objects.filter(branch__in=ids).select_related("created_by", "till_session__till")
        if self.request.headers.get("X-Branch-ID"):
            qs = qs.filter(branch=self.request.headers["X-Branch-ID"])
        p = self.request.query_params
        if p.get("from"):
            qs = qs.filter(created_at__date__gte=p["from"])
        if p.get("to"):
            qs = qs.filter(created_at__date__lte=p["to"])
        return qs

