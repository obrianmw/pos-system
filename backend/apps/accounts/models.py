from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Branch, Organization, TimeStamped

from .permissions_catalog import PERMISSIONS


class User(AbstractUser):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="users")
    phone = models.CharField(max_length=30, blank=True)
    # Short numeric PIN supervisors type at the counter to approve overrides. Stored hashed.
    supervisor_pin = models.CharField(max_length=128, blank=True)
    THEMES = [("system", "Follow device"), ("light", "Light"), ("dark", "Dark")]
    ui_theme = models.CharField(max_length=10, choices=THEMES, default="system")

    def set_supervisor_pin(self, pin: str):
        if not (pin.isdigit() and 4 <= len(pin) <= 8):
            raise ValidationError("PIN must be 4-8 digits.")
        self.supervisor_pin = make_password(pin)

    def check_supervisor_pin(self, pin: str) -> bool:
        return bool(self.supervisor_pin) and check_password(pin, self.supervisor_pin)

    # ---- permission helpers -------------------------------------------------------------
    def _memberships(self):
        if not hasattr(self, "_membership_cache"):
            self._membership_cache = list(
                self.memberships.filter(is_active=True, role__is_active=True).select_related("role")
            )
        return self._membership_cache

    def custody_branch_ids(self):
        """Branches whose vault this user holds right now (cached for the request)."""
        if not hasattr(self, "_custody_cache"):
            from apps.cash.models import VaultCustody
            self._custody_cache = set(VaultCustody.active().filter(custodian=self)
                                      .values_list("vault__branch_id", flat=True))
        return self._custody_cache

    def has_branch_perm(self, branch, code: str) -> bool:
        """True if the user holds `code` at `branch`, through a branch or an org-wide membership, or
        because they hold that branch's vault today (vault holders are the branch's authorizers)."""
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        if not isinstance(branch, Branch):
            branch = Branch.objects.filter(pk=branch).first()
            if branch is None:
                return False
        from .permissions_catalog import CUSTODIAN_PERMISSIONS
        if code in CUSTODIAN_PERMISSIONS and branch.pk in self.custody_branch_ids():
            return True
        for m in self._memberships():
            if m.branch_id is None:
                if m.role.organization_id != branch.organization_id:
                    continue
            elif m.branch_id != branch.pk:
                continue
            if "*" in m.role.permissions or code in m.role.permissions:
                return True
        return False

    def has_org_perm(self, code: str) -> bool:
        if self.is_superuser:
            return True
        return any(m.branch_id is None and ("*" in m.role.permissions or code in m.role.permissions)
                   for m in self._memberships())

    def accessible_branch_ids(self):
        if self.is_superuser:
            return list(Branch.objects.values_list("id", flat=True))
        ids = set()
        for m in self._memberships():
            if m.branch_id is None:
                ids.update(Branch.objects.filter(organization_id=m.role.organization_id)
                           .values_list("id", flat=True))
            else:
                ids.add(m.branch_id)
        return sorted(ids)


class Role(TimeStamped):
    SCOPE_CHOICES = [("org", "Organization-wide"), ("branch", "Branch")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=80)
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default="branch")
    permissions = models.JSONField(default=list, help_text="List of permission codes, or ['*'].")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("organization", "name")]

    def clean(self):
        unknown = [p for p in self.permissions if p != "*" and p not in PERMISSIONS]
        if unknown:
            raise ValidationError({"permissions": f"Unknown permission codes: {unknown}"})

    def __str__(self):
        return f"{self.name} ({self.organization.code})"


class Membership(TimeStamped):
    """Gives a user a role at one branch, or at every branch when `branch` is empty."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "role", "branch")]

    def clean(self):
        if self.role.scope == "org" and self.branch_id:
            raise ValidationError("Organization-wide roles are assigned without a branch.")
        if self.role.scope == "branch" and not self.branch_id:
            raise ValidationError("Branch roles need a branch.")
        if self.branch_id and self.branch.organization_id != self.role.organization_id:
            raise ValidationError("Branch and role belong to different organizations.")

    def __str__(self):
        return f"{self.user} - {self.role.name} @ {self.branch or 'all branches'}"
