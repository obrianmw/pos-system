from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api import branches_with
from apps.core.models import Branch, audit

from .models import Membership, Role, User
from .permissions_catalog import PERMISSIONS


@api_view(["GET"])
def me(request):
    """Who am I, which branches can I use, and what may I do at each. The POS caches this offline."""
    u = request.user
    branches = Branch.objects.filter(pk__in=u.accessible_branch_ids(), is_active=True).select_related("organization")
    return Response({
        "id": u.pk, "username": u.username, "name": u.get_full_name() or u.username,
        "organization": u.organization_id,
        "organization_name": u.organization.name if u.organization_id else "",
        "branches": [{"id": b.pk, "name": b.name, "code": b.code,
                      "max_cashier_discount_pct": str(b.max_cashier_discount_pct),
                      "currency": b.organization.currency, "receipt_footer": b.receipt_footer,
                      "permissions": sorted(c for c in PERMISSIONS if u.has_branch_perm(b, c))}
                     for b in branches],
        "org_permissions": sorted(c for c in PERMISSIONS if u.has_org_perm(c)),
    })


@api_view(["GET"])
def permission_catalog(request):
    return Response(PERMISSIONS)


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "scope", "permissions", "is_active"]

    def validate_permissions(self, value):
        unknown = [p for p in value if p != "*" and p not in PERMISSIONS]
        if unknown:
            raise ValidationError(f"Unknown permission codes: {unknown}")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "role_name", "branch", "is_active"]

    def validate(self, attrs):
        role, branch = attrs.get("role"), attrs.get("branch")
        if role and role.scope == "org" and branch:
            raise ValidationError("Organization-wide roles are assigned without a branch.")
        if role and role.scope == "branch" and not branch:
            raise ValidationError("Branch roles need a branch.")
        return attrs


class UserSerializer(serializers.ModelSerializer):
    memberships = MembershipSerializer(many=True, read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    supervisor_pin = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "phone", "is_active",
                  "password", "supervisor_pin", "memberships"]

    def save(self, **kwargs):
        password = self.validated_data.pop("password", None)
        pin = self.validated_data.pop("supervisor_pin", None)
        user = super().save(**kwargs)
        if password:
            user.set_password(password)
        if pin:
            user.set_supervisor_pin(pin)
        if password or pin:
            user.save()
        return user


def _can_manage_users(user, branch=None):
    if user.has_org_perm("org.admin"):
        return True
    return branch is not None and user.has_branch_perm(branch, "branch.admin")


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer

    def get_queryset(self):
        return Role.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        if not self.request.user.has_org_perm("org.admin"):
            raise PermissionDenied("Only organization admins define roles.")
        serializer.save(organization=self.request.user.organization)

    perform_update = perform_create


class UserViewSet(viewsets.ModelViewSet):
    """Org admins manage everyone; branch admins manage users who belong to their branches."""

    serializer_class = UserSerializer
    search_fields = ["username", "first_name", "last_name", "phone"]

    def get_queryset(self):
        u = self.request.user
        qs = User.objects.filter(organization=u.organization).prefetch_related("memberships__role")
        if u.has_org_perm("org.admin"):
            return qs
        admin_branches = [b.pk for b in branches_with(u, "branch.admin")]
        return qs.filter(memberships__branch__in=admin_branches).distinct()

    def perform_create(self, serializer):
        if not (self.request.user.has_org_perm("org.admin") or branches_with(self.request.user, "branch.admin")):
            raise PermissionDenied("Not allowed to create users.")
        user = serializer.save(organization=self.request.user.organization)
        audit("user.created", organization=user.organization, actor=self.request.user, obj=user)

    @action(detail=True, methods=["post"])
    def assign_role(self, request, pk=None):
        target = self.get_object()
        s = MembershipSerializer(data={**request.data, "user": target.pk})
        s.is_valid(raise_exception=True)
        role, branch = s.validated_data["role"], s.validated_data.get("branch")
        if role.organization_id != request.user.organization_id:
            raise PermissionDenied("Role from another organization.")
        if role.scope == "org" or "*" in role.permissions or "org.admin" in role.permissions:
            if not request.user.has_org_perm("org.admin"):
                raise PermissionDenied("Only organization admins grant organization-wide roles.")
        elif not _can_manage_users(request.user, branch):
            raise PermissionDenied("You do not administer that branch.")
        m = s.save()
        audit("user.role_assigned", organization=role.organization, branch=branch, actor=request.user, obj=m,
              user=target.username, role=role.name)
        return Response(MembershipSerializer(m).data, status=201)

    @action(detail=True, methods=["post"])
    def revoke_role(self, request, pk=None):
        target = self.get_object()
        m = Membership.objects.filter(pk=request.data.get("membership_id"), user=target).first()
        if not m:
            raise ValidationError("Membership not found.")
        if not _can_manage_users(request.user, m.branch):
            raise PermissionDenied("You do not administer that branch.")
        m.is_active = False
        m.save(update_fields=["is_active", "updated_at"])
        audit("user.role_revoked", organization=m.role.organization, branch=m.branch, actor=request.user, obj=m)
        return Response(status=204)
