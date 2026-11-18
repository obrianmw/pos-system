import uuid

from django.conf import settings
from django.db import models

from apps.core.models import Branch, Organization, TimeStamped


class PaymentMethod(TimeStamped):
    """A way customers can pay, e.g. "Cash", "Airtel Money", "TNM Mpamba", "Visa (PayChangu)".

    `provider` picks the integration in apps.payments.providers. Each method posts to its own ledger
    account so every wallet/bank can be reconciled separately.
    """

    KINDS = [("cash", "Cash"), ("bank_transfer", "Bank transfer"), ("card_terminal", "Card (own terminal)"),
             ("mobile_money", "Mobile money wallet"), ("card_gateway", "Card via online gateway"),
             ("store_credit", "Store credit / account")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="payment_methods")
    name = models.CharField(max_length=60)
    kind = models.CharField(max_length=20, choices=KINDS)
    provider = models.CharField(max_length=30, default="manual",
                                help_text="manual, airtel_money, tnm_mpamba, mpesa, mtn_momo, paychangu")
    branches = models.ManyToManyField(Branch, blank=True, help_text="Empty = available at every branch.")
    ledger_account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT, null=True, blank=True,
                                       related_name="+")
    # Non-secret settings (shortcode, country...). Secrets belong in env vars; see .env.example.
    config = models.JSONField(default=dict, blank=True)
    requires_reference = models.BooleanField(default=False, help_text="Cashier must type a txn/slip number.")
    allowed_offline = models.BooleanField(default=False, help_text="Can be taken while the till is offline.")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name

    def available_at(self, branch) -> bool:
        return self.is_active and (not self.branches.exists() or self.branches.filter(pk=branch.pk).exists())


class Payment(TimeStamped):
    STATUS = [("pending", "Pending"), ("confirmed", "Confirmed"), ("failed", "Failed"),
              ("cancelled", "Cancelled"), ("refunded", "Refunded")]
    sale = models.ForeignKey("sales.Sale", on_delete=models.PROTECT, related_name="payments")
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    tendered = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True,
                                   help_text="Cash handed over (change = tendered - amount).")
    status = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    # Our id sent to the provider; also the idempotency key for offline sync.
    client_reference = models.UUIDField(default=uuid.uuid4, unique=True)
    provider_reference = models.CharField(max_length=100, blank=True, db_index=True)
    payer_phone = models.CharField(max_length=30, blank=True)
    checkout_url = models.URLField(blank=True, max_length=500)
    message = models.CharField(max_length=255, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                    related_name="+")

    def __str__(self):
        return f"{self.method} {self.amount} [{self.status}]"


class PaymentCallbackLog(models.Model):
    """Raw provider callbacks, kept for reconciliation and dispute handling."""

    provider = models.CharField(max_length=30)
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.JSONField(default=dict)
    headers = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    error = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
