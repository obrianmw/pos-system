from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api import branches_with
from apps.core.models import Branch, audit
from apps.core.security import admin_site_permission

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
        "ui_theme": u.ui_theme,
        # The database admin site lives on the API's own port (never proxied to the shop network).
        "admin_site": {"port": settings.API_PORT, "path": "/admin/"} if admin_site_permission(request) else None,
    })


@api_view(["PATCH"])
def preferences(request):
    """Personal settings that follow the user to any till or PC: {"ui_theme": "system"|"light"|"dark"}."""
    theme = request.data.get("ui_theme")
    if theme not in dict(User.THEMES):
        raise ValidationError({"ui_theme": "Choose system, light or dark."})
    request.user.ui_theme = theme
    request.user.save(update_fields=["ui_theme"])
    return Response({"ui_theme": theme})


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
        validators = []  # assign_role switches a previously removed role back on instead of failing

    def validate(self, attrs):
        role, branch = attrs.get("role"), attrs.get("branch")
        if role and role.scope == "org" and branch:
            raise ValidationError("Organization-wide roles are assigned without a branch.")
        if role and role.scope == "branch" and not branch:
            raise ValidationError("Branch roles need a branch.")
        return attrs


class UserSerializer(serializers.ModelSerializer):
    memberships = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    supervisor_pin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_supervisor_pin = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    last_login = serializers.DateTimeField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "phone", "is_active", "last_login",
                  "password", "supervisor_pin", "has_supervisor_pin", "memberships", "can_edit"]

    def get_memberships(self, u):
        return MembershipSerializer([m for m in u.memberships.all() if m.is_active], many=True).data

    def get_has_supervisor_pin(self, u):
        return bool(u.supervisor_pin)

    def get_can_edit(self, u):
        return can_edit_user(self.context["request"].user, u)

    def validate_username(self, value):
        value = value.strip()
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This username is taken.")
        return value

    def validate_supervisor_pin(self, value):
        if value and not (value.isdigit() and 4 <= len(value) <= 8):
            raise ValidationError("PIN must be 4-8 digits.")
        return value

    def validate(self, attrs):
        pw = attrs.get("password")
        if pw:
            probe = self.instance or User(username=attrs.get("username", ""), first_name=attrs.get("first_name", ""),
                                          last_name=attrs.get("last_name", ""), email=attrs.get("email", ""))
            try:
                validate_password(pw, probe)
            except DjangoValidationError as e:
                raise ValidationError({"password": list(e.messages)})
        elif not self.instance:
            raise ValidationError({"password": "Set a starting password."})
        return attrs

    def save(self, **kwargs):
        password = self.validated_data.pop("password", None)
        pin = self.validated_data.pop("supervisor_pin", None)
        user = super().save(**kwargs)
        if password:
            user.set_password(password)
        if pin is not None:
            if pin:
                user.set_supervisor_pin(pin)
            else:
                user.supervisor_pin = ""  # empty string clears the PIN
        if password or pin is not None:
            user.save()
        return user


def _can_manage_users(user, branch=None):
    if user.has_org_perm("org.admin"):
        return True
    return branch is not None and user.has_branch_perm(branch, "branch.admin")


def _is_powerful(target):
    """Holds an org-wide role or org admin rights - only org admins may touch such accounts."""
    if target.is_superuser or target.is_staff:
        return True
    for m in target.memberships.filter(is_active=True).select_related("role"):
        if m.branch_id is None or "*" in m.role.permissions or "org.admin" in m.role.permissions:
            return True
    return False


def can_edit_user(actor, target):
    """Who may change whose account:
    - superusers only by superusers;
    - org admins: anyone in their organization;
    - branch admins: only people whose every role is at branches they administer, and who hold no
      org-wide or admin-of-everything role."""
    if target.organization_id != actor.organization_id and not actor.is_superuser:
        return False
    if target.is_superuser and not actor.is_superuser:
        return False
    if actor.has_org_perm("org.admin"):
        return True
    if _is_powerful(target):
        return False
    admin_branches = {b.pk for b in branches_with(actor, "branch.admin")}
    branches = {m.branch_id for m in target.memberships.filter(is_active=True)}
    return bool(admin_branches) and branches <= admin_branches and bool(branches)


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
    """Org admins manage everyone; branch admins manage people who only work at their branches.
    Accounts are never deleted (sales, audit and HR history point at them) - deactivate instead."""

    serializer_class = UserSerializer
    http_method_names = ["get", "post", "patch"]
    search_fields = ["username", "first_name", "last_name", "phone", "email"]
    filterset_fields = ["is_active"]

    def get_queryset(self):
        u = self.request.user
        qs = (User.objects.filter(organization=u.organization)
              .prefetch_related("memberships__role", "memberships__branch").order_by("first_name", "username"))
        if not u.has_org_perm("org.admin"):
            admin_branches = [b.pk for b in branches_with(u, "branch.admin")]
            qs = qs.filter(memberships__branch__in=admin_branches, memberships__is_active=True).distinct()
        p = self.request.query_params
        if p.get("branch"):
            qs = qs.filter(memberships__branch=p["branch"], memberships__is_active=True).distinct()
        if p.get("role"):
            qs = qs.filter(memberships__role=p["role"], memberships__is_active=True).distinct()
        return qs

    def _require_edit(self, target):
        if not can_edit_user(self.request.user, target):
            raise PermissionDenied("You can't change this account. It belongs to someone with organization-wide "
                                   "access or staff at a branch you don't administer.")

    def create(self, request, *args, **kwargs):
        """New user. Branch admins must give them a role at one of their branches in the same request:
        {"username", "first_name", "last_name", "email", "phone", "password", "role": id, "branch": id}"""
        actor = request.user
        role = Role.objects.filter(pk=request.data.get("role"), organization=actor.organization).first() \
            if request.data.get("role") else None
        branch = Branch.objects.filter(pk=request.data.get("branch"), organization=actor.organization).first() \
            if request.data.get("branch") else None
        if not actor.has_org_perm("org.admin") and not branches_with(actor, "branch.admin"):
            raise PermissionDenied("Not allowed to create users.")
        if role:
            self._check_grant(role, branch)  # permission first, so "not allowed" wins over "missing branch"
        if not actor.has_org_perm("org.admin") and (not role or not branch):
            raise ValidationError({"role": "Choose the role and branch this person will work at."})
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            user = s.save(organization=actor.organization)
            if role:
                Membership.objects.create(user=user, role=role, branch=branch if role.scope == "branch" else None)
        audit("user.created", organization=user.organization, branch=branch, actor=actor, obj=user,
              user=user.username, role=role.name if role else "")
        return Response(self.get_serializer(User.objects.get(pk=user.pk)).data, status=201)

    def perform_update(self, serializer):
        target = serializer.instance
        actor = self.request.user
        self._require_edit(target)
        d = serializer.validated_data
        if target.pk == actor.pk and d.get("is_active") is False:
            raise ValidationError({"is_active": "You can't deactivate your own account."})
        tracked = ("username", "first_name", "last_name", "email", "phone", "is_active")
        changed = {f: [str(getattr(target, f)), str(d[f])] for f in tracked if f in d and getattr(target, f) != d[f]}
        password_reset = bool(d.get("password"))  # read before save(), which consumes it
        user = serializer.save()
        if changed:
            audit("user.updated", organization=user.organization, actor=actor, obj=user, user=user.username, **changed)
        if password_reset:
            audit("user.password_reset", organization=user.organization, actor=actor, obj=user, user=user.username)
        if "supervisor_pin" in self.request.data:
            audit("user.pin_changed", organization=user.organization, actor=actor, obj=user, user=user.username,
                  cleared=not self.request.data.get("supervisor_pin"))

    def _check_grant(self, role, branch):
        actor = self.request.user
        if role.organization_id != actor.organization_id:
            raise PermissionDenied("Role from another organization.")
        if role.scope == "org" or "*" in role.permissions or "org.admin" in role.permissions:
            if not actor.has_org_perm("org.admin"):
                raise PermissionDenied("Only organization admins grant organization-wide roles.")
        elif not _can_manage_users(actor, branch):
            raise PermissionDenied("You do not administer that branch.")

    @action(detail=True, methods=["post"])
    def assign_role(self, request, pk=None):
        target = self.get_object()
        s = MembershipSerializer(data={**request.data, "user": target.pk})
        s.is_valid(raise_exception=True)
        role, branch = s.validated_data["role"], s.validated_data.get("branch")
        self._check_grant(role, branch)
        if not request.user.has_org_perm("org.admin") and _is_powerful(target):
            raise PermissionDenied("Only organization admins change this account's roles.")
        m, created = Membership.objects.get_or_create(user=target, role=role, branch=branch,
                                                      defaults={"is_active": True})
        if not created:
            if m.is_active:
                raise ValidationError({"detail": f"{target.username} already has {role.name} there."})
            m.is_active = True  # previously removed; switch it back on
            m.save(update_fields=["is_active", "updated_at"])
        audit("user.role_assigned", organization=role.organization, branch=branch, actor=request.user, obj=m,
              user=target.username, role=role.name)
        return Response(MembershipSerializer(m).data, status=201)

    @action(detail=True, methods=["post"])
    def revoke_role(self, request, pk=None):
        target = self.get_object()
        m = Membership.objects.filter(pk=request.data.get("membership_id"), user=target, is_active=True) \
            .select_related("role").first()
        if not m:
            raise ValidationError({"detail": "Role not found."})
        if not _can_manage_users(request.user, m.branch):
            raise PermissionDenied("You do not administer that branch.")
        if target.pk == request.user.pk and ("*" in m.role.permissions or "org.admin" in m.role.permissions
                                             or "branch.admin" in m.role.permissions):
            raise ValidationError({"detail": "You can't remove your own admin role. Ask another admin."})
        m.is_active = False
        m.save(update_fields=["is_active", "updated_at"])
        audit("user.role_revoked", organization=m.role.organization, branch=m.branch, actor=request.user, obj=m,
              user=target.username, role=m.role.name)
        return Response(status=204)
