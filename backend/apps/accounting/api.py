from decimal import Decimal

from django.db import transaction
from rest_framework import serializers
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api import BranchScopedViewSet, OrgScopedViewSet, active_branch, require_perm
from apps.core.models import Branch, audit

from . import services
from .models import Account, CashMovement, Expense, JournalEntry, JournalLine


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        exclude = ["organization"]
        read_only_fields = ["system_key"]


class JournalLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalLine
        fields = ["id", "account", "account_name", "branch", "debit", "credit", "description"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True)

    class Meta:
        model = JournalEntry
        fields = "__all__"
        read_only_fields = ["organization", "posted_by", "source", "reverses"]
        extra_kwargs = {"branch": {"required": False}}


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = "__all__"
        read_only_fields = ["status", "requested_by", "approved_by", "journal_entry"]
        extra_kwargs = {"branch": {"required": False}}


class CashMovementSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashMovement
        fields = "__all__"
        read_only_fields = ["created_by", "journal_entry"]


class AccountViewSet(OrgScopedViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    read_perm = "accounting.view"
    write_perm = "accounting.post"

    def perform_destroy(self, instance):
        raise PermissionDenied("Deactivate accounts instead of deleting them.")


class JournalEntryViewSet(BranchScopedViewSet):
    queryset = JournalEntry.objects.prefetch_related("lines__account")
    serializer_class = JournalEntrySerializer
    http_method_names = ["get", "post"]
    perms = {"*": "accounting.post", "list": "accounting.view"}
    filterset_fields = ["source", "date", "reference"]

    def create(self, request, *args, **kwargs):
        """Manual journal: {"date", "reference", "memo", "lines": [{"account", "debit", "credit", "description"}]}"""
        branch = active_branch(request)
        require_perm(request.user, branch, "accounting.post")
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        org = branch.organization
        lines = []
        for l in s.validated_data["lines"]:
            if l["account"].organization_id != org.pk:
                raise ValidationError("Account from another organization.")
            lines.append((l["account"], l.get("debit") or Decimal(0), l.get("credit") or Decimal(0),
                          l.get("description", "")))
        try:
            entry = services.post(organization=org, branch=branch, reference=s.validated_data["reference"],
                                  memo=s.validated_data.get("memo", ""), source="manual", user=request.user,
                                  date=s.validated_data["date"], lines=lines)
        except services.UnbalancedEntry as e:
            raise ValidationError(str(e))
        audit("journal.manual", organization=org, branch=branch, actor=request.user, obj=entry)
        return Response(self.get_serializer(entry).data, status=201)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        entry = self.get_object()
        require_perm(request.user, entry.branch, "accounting.post")
        if hasattr(entry, "reversed_by"):
            raise ValidationError("Already reversed.")
        rev = services.reverse_entry(entry, request.user, request.data.get("memo", ""))
        audit("journal.reversed", organization=entry.organization, branch=entry.branch, actor=request.user, obj=entry)
        return Response(self.get_serializer(rev).data, status=201)


class ExpenseViewSet(BranchScopedViewSet):
    """Anyone with accounting.post can record; approval (which posts it) needs accounting.reconcile."""

    queryset = Expense.objects.select_related("expense_account", "paid_from")
    serializer_class = ExpenseSerializer
    perms = {"*": "accounting.post", "list": "accounting.view", "approve": "accounting.reconcile",
             "reject": "accounting.reconcile"}
    filterset_fields = ["status"]
    search_fields = ["description", "receipt_number"]
    ordering_fields = ["date", "amount", "status", "created_at"]

    def create_extra(self):
        return {"requested_by": self.request.user}

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        exp = self.get_object()
        if exp.requested_by_id == request.user.pk and not request.user.has_org_perm("org.admin"):
            raise PermissionDenied("Someone else must approve your expense.")
        try:
            services.approve_expense(exp, request.user)
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(self.get_serializer(exp).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        exp = self.get_object()
        if exp.status != "pending":
            raise ValidationError("Already decided.")
        exp.status, exp.approved_by = "rejected", request.user
        exp.save(update_fields=["status", "approved_by", "updated_at"])
        return Response(self.get_serializer(exp).data)


class CashMovementViewSet(BranchScopedViewSet):
    queryset = CashMovement.objects.all()
    serializer_class = CashMovementSerializer
    http_method_names = ["get", "post"]
    branch_field = "from_branch"
    perms = {"*": "accounting.post", "list": "accounting.view"}

    def perform_create(self, serializer):
        d = serializer.validated_data
        require_perm(self.request.user, d["from_branch"], "accounting.post")
        org = d["from_branch"].organization
        if d["to_branch"].organization_id != org.pk or d["from_account"].organization_id != org.pk \
                or d["to_account"].organization_id != org.pk:
            raise ValidationError("All branches and accounts must belong to your organization.")
        with transaction.atomic():
            cm = serializer.save(created_by=self.request.user)
            services.post_cash_movement(cm)
        audit("cash.movement", organization=org, branch=cm.from_branch, actor=self.request.user, obj=cm,
              amount=str(cm.amount))


@api_view(["GET"])
def trial_balance(request):
    """?branch=<id> for one branch (needs accounting.view there), omit for the whole organization
    (needs accounting.view org-wide). ?date_to=YYYY-MM-DD optional."""
    u = request.user
    branch = None
    if request.query_params.get("branch") or request.headers.get("X-Branch-ID"):
        branch = active_branch(request)
        require_perm(u, branch, "accounting.view")
    elif not u.has_org_perm("accounting.view"):
        raise PermissionDenied("Organization-wide reports need an organization role.")
    rows = services.trial_balance(u.organization, branch, request.query_params.get("date_to"))
    return Response({"branch": branch.pk if branch else None, "rows": rows,
                     "total_debit": sum(r["debit"] for r in rows), "total_credit": sum(r["credit"] for r in rows)})
