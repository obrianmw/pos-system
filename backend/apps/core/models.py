from django.conf import settings
from django.db import models


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStamped):
    """The institution that owns all shops/branches."""

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=30, unique=True)
    currency = models.CharField(max_length=3, default="MWK")
    tax_number = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Branch(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="branches")
    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=30)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    # Branch-level policy switches managed by the branch admin.
    allow_negative_stock = models.BooleanField(default=False)
    max_cashier_discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Discount % a cashier may give without supervisor approval.",
    )
    receipt_footer = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("organization", "code")]
        ordering = ["organization", "name"]

    def __str__(self):
        return f"{self.organization.code}/{self.name}"


class Till(TimeStamped):
    """A counter / POS terminal at a branch."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="tills")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("branch", "code")]

    def __str__(self):
        return f"{self.branch} - {self.name}"


class AuditLog(models.Model):
    """Append-only record of sensitive actions (overrides, voids, price changes, settings)."""

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


def audit(action, *, organization, actor=None, branch=None, obj=None, request=None, **data):
    return AuditLog.objects.create(
        organization=organization,
        branch=branch,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(obj.pk) if obj is not None else "",
        data=data,
        ip_address=(request.META.get("REMOTE_ADDR") if request else None),
    )


class Sequence(models.Model):
    """Gap-tolerant document counters (sale numbers, PO numbers ...), locked row per key."""

    key = models.CharField(max_length=80, unique=True)
    value = models.PositiveBigIntegerField(default=0)


def next_number(key: str, prefix: str, width: int = 6) -> str:
    """Must be called inside transaction.atomic()."""
    seq, _ = Sequence.objects.get_or_create(key=key)
    seq = Sequence.objects.select_for_update().get(pk=seq.pk)
    seq.value += 1
    seq.save(update_fields=["value"])
    return f"{prefix}{seq.value:0{width}d}"
