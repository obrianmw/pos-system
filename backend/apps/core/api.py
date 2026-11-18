"""Shared API plumbing: branch scoping and permission-code checks.

Every branch-owned viewset declares `perms = {"list": "inventory.view", "create": "...", ...}`
(with "*" as the fallback for any action). Users only ever see rows from branches where they
hold that code, and can only write to such branches. The active branch comes from the
`X-Branch-ID` header (or `?branch=`).
"""
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from .models import AuditLog, Branch, Organization, Till


def branches_with(user, code):
    cache = user.__dict__.setdefault("_branches_with", {})
    if code not in cache:
        cache[code] = [b for b in Branch.objects.filter(pk__in=user.accessible_branch_ids())
                       if user.has_branch_perm(b, code)]
    return cache[code]


def active_branch(request, required=True):
    raw = request.headers.get("X-Branch-ID") or request.query_params.get("branch")
    if not raw:
        if required:
            raise ValidationError({"branch": "Send the X-Branch-ID header."})
        return None
    branch = Branch.objects.filter(pk=raw, pk__in=request.user.accessible_branch_ids()).first()
    if branch is None:
        raise PermissionDenied("You have no access to that branch.")
    return branch


def require_perm(user, branch, code):
    if not user.has_branch_perm(branch, code):
        raise PermissionDenied(f"Missing permission '{code}' at {branch.name}.")


def require_org_or_any_branch_perm(user, code):
    if not (user.has_org_perm(code) or branches_with(user, code)):
        raise PermissionDenied(f"Missing permission '{code}'.")


class PermCodeMixin:
    perms: dict = {}

    def perm_for_action(self):
        action = self.action or ("list" if self.request.method == "GET" else "create")
        if action in self.perms:
            return self.perms[action]
        if action in ("retrieve",) and "list" in self.perms:
            return self.perms["list"]
        return self.perms.get("*")


class BranchScopedViewSet(PermCodeMixin, viewsets.ModelViewSet):
    """Rows owned by a branch (`branch_field`)."""

    branch_field = "branch"

    def get_queryset(self):
        qs = super().get_queryset()
        code = self.perm_for_action()
        allowed = [b.pk for b in branches_with(self.request.user, code)] if code else \
            self.request.user.accessible_branch_ids()
        qs = qs.filter(**{f"{self.branch_field}__in": allowed})
        selected = active_branch(self.request, required=False)  # 403 if the branch is not theirs
        if selected:
            qs = qs.filter(**{f"{self.branch_field}": selected})
        return qs if qs.ordered else qs.order_by("-pk")

    def perform_create(self, serializer):
        """Objects are created in the branch given in the body, else the active branch."""
        branch = serializer.validated_data.get("branch") or active_branch(self.request)
        code = self.perm_for_action()
        if code:
            require_perm(self.request.user, branch, code)
        serializer.save(branch=branch, **self.create_extra())

    def create_extra(self):
        return {}

    def perform_update(self, serializer):
        new_branch = serializer.validated_data.get("branch")
        if isinstance(new_branch, Branch):  # moving a row to another branch needs rights there too
            require_perm(self.request.user, new_branch, self.perm_for_action())
        serializer.save()


class OrgScopedViewSet(PermCodeMixin, viewsets.ModelViewSet):
    """Organization-wide master data (products, suppliers, accounts...). Reads need the `read` code if
    set (else any member); writes need `write` held org-wide or at any branch."""

    read_perm = None
    write_perm = None

    def get_queryset(self):
        qs = super().get_queryset().filter(organization=self.request.user.organization)
        qs = qs if qs.ordered else qs.order_by("pk")
        if self.request.method in permissions.SAFE_METHODS and self.read_perm:
            require_org_or_any_branch_perm(self.request.user, self.read_perm)
        return qs

    def check_write(self):
        if self.write_perm:
            require_org_or_any_branch_perm(self.request.user, self.write_perm)

    def perform_create(self, serializer):
        self.check_write()
        serializer.save(organization=self.request.user.organization)

    def perform_update(self, serializer):
        self.check_write()
        serializer.save()

    def perform_destroy(self, instance):
        self.check_write()
        instance.delete()


# ---- core endpoints ---------------------------------------------------------------------------
class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = "__all__"


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = "__all__"
        read_only_fields = ["organization"]


class TillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Till
        fields = "__all__"
        extra_kwargs = {"branch": {"required": False}}


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.get_full_name", read_only=True, default="")

    class Meta:
        model = AuditLog
        fields = "__all__"


class BranchViewSet(viewsets.ModelViewSet):
    serializer_class = BranchSerializer

    def get_queryset(self):
        return Branch.objects.filter(pk__in=self.request.user.accessible_branch_ids())

    def perform_create(self, serializer):
        if not self.request.user.has_org_perm("org.admin"):
            raise PermissionDenied("Only organization admins create branches.")
        serializer.save(organization=self.request.user.organization)

    def perform_update(self, serializer):
        branch = serializer.instance
        if not (self.request.user.has_org_perm("org.admin") or self.request.user.has_branch_perm(branch, "branch.admin")):
            raise PermissionDenied("Branch admin permission required.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        return Response({"detail": "Deactivate branches instead of deleting them."},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=False)
    def directory(self, request):
        """Names of every active branch in your organization (e.g. to pick a transfer destination).
        Only id/name/code - no figures or settings."""
        rows = Branch.objects.filter(organization=request.user.organization, is_active=True).order_by("name")
        return Response(list(rows.values("id", "name", "code")))


class TillViewSet(BranchScopedViewSet):
    queryset = Till.objects.select_related("branch")
    serializer_class = TillSerializer
    perms = {"list": "pos.sell", "create": "branch.admin", "update": "branch.admin",
             "partial_update": "branch.admin", "destroy": "branch.admin"}


class AuditLogViewSet(BranchScopedViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    http_method_names = ["get"]
    perms = {"*": "audit.view"}
    filterset_fields = ["action", "actor", "object_type"]
