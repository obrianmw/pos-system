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
    """A counter / POS terminal at a branch. Admins assign the people allowed to open it; only one of
    them can have it open at a time (see sales.TillSession)."""

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="tills")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=30)
    is_active = models.BooleanField(default=True)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="assigned_tills",
                                   help_text="People allowed to open this till.")

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


HEX = r"^#[0-9a-fA-F]{6}$"


class Branding(TimeStamped):
    """How the system and its printed documents look for one organization. Edited by org admins on the
    Branding page. Colors are the brand's own; the app derives readable light/dark variants from them."""

    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="branding")
    # Look & feel
    display_name = models.CharField(max_length=80, blank=True, help_text="Shown in the app; defaults to the organization name.")
    tagline = models.CharField(max_length=120, blank=True)
    logo = models.ImageField(upload_to="branding/", blank=True)
    primary_color = models.CharField(max_length=7, default="#0f766e")
    accent_color = models.CharField(max_length=7, default="#4f46e5")
    # Shared on every document
    doc_business_name = models.CharField(max_length=120, blank=True)
    doc_address = models.TextField(blank=True)
    doc_phone = models.CharField(max_length=60, blank=True)
    doc_email = models.CharField(max_length=120, blank=True)
    doc_tax_number = models.CharField(max_length=40, blank=True, help_text="TPIN / VAT number printed on documents.")
    doc_show_logo = models.BooleanField(default=True)
    # Receipt (till)
    receipt_header = models.TextField(blank=True)
    receipt_footer = models.TextField(blank=True, default="Thank you for shopping with us!")
    receipt_paper = models.CharField(max_length=5, choices=[("58mm", "58 mm"), ("80mm", "80 mm")], default="80mm")
    receipt_show_vat = models.BooleanField(default=True)
    receipt_show_cashier = models.BooleanField(default=True)
    receipt_show_barcode_sku = models.BooleanField(default=False)
    # Invoice (A4, from a sale)
    invoice_prefix = models.CharField(max_length=10, default="INV-")
    invoice_title = models.CharField(max_length=40, default="Tax invoice")
    invoice_terms = models.TextField(blank=True, default="Payment due on receipt.")
    invoice_payment_details = models.TextField(blank=True, help_text="Bank / mobile money details for payment.")
    invoice_footer = models.TextField(blank=True)
    # Proforma (A4 quotation before a sale)
    proforma_prefix = models.CharField(max_length=10, default="PF-")
    proforma_title = models.CharField(max_length=40, default="Proforma invoice")
    proforma_validity_days = models.PositiveSmallIntegerField(default=14)
    proforma_terms = models.TextField(blank=True, default="Prices valid for the period shown. Stock not reserved.")
    proforma_footer = models.TextField(blank=True)

    def __str__(self):
        return f"Branding for {self.organization}"

    @classmethod
    def for_org(cls, org):
        b, _ = cls.objects.get_or_create(organization=org)
        return b
