from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Branch, TimeStamped


class Vault(TimeStamped):
    """The branch's cash store. Tills open at zero and get their float from here; at closing all till
    cash comes back here. Its balance is the 'Vault cash' ledger account for the branch."""

    branch = models.OneToOneField(Branch, on_delete=models.PROTECT, related_name="vault")
    name = models.CharField(max_length=60, default="Main vault")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.branch.name} {self.name}"


class VaultCustody(TimeStamped):
    """Who holds a vault, and until when. The holder is the branch's authorizer (supervisor powers)
    for as long as they hold it. One active custody per vault."""

    vault = models.ForeignKey(Vault, on_delete=models.PROTECT, related_name="custodies")
    custodian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vault_custodies")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    starts_at = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(help_text="Custody lapses automatically at this time (default: end of day).")
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="+")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    @classmethod
    def active(cls):
        now = timezone.now()
        return cls.objects.filter(ended_at__isnull=True, starts_at__lte=now, valid_until__gt=now)

    @property
    def is_active(self):
        now = timezone.now()
        return self.ended_at is None and self.starts_at <= now < self.valid_until

    def __str__(self):
        return f"{self.custodian} holds {self.vault} until {self.valid_until:%Y-%m-%d %H:%M}"


class CashTransfer(TimeStamped):
    """Every movement of physical cash between the vault, tills, finance and the bank."""

    KIND = [
        ("float", "Float to till"),            # vault -> till
        ("pickup", "Pickup from till"),        # till -> vault (during the shift)
        ("close", "Till closing"),             # till -> vault (all cash at close; holder confirms)
        ("drop", "Cash drop from till"),       # till -> vault during the shift (cashier hands over; holder confirms)
        ("to_finance", "To finance"),          # vault -> accountant/finance
        ("from_finance", "From finance"),      # finance -> vault
        ("to_bank", "Bank deposit"),           # vault -> bank
        ("from_bank", "Bank withdrawal"),      # bank -> vault
        ("restock", "Restocking payment"),     # vault -> supplier (pays accounts payable)
    ]
    INTO_VAULT = {"pickup", "close", "drop", "from_finance", "from_bank"}
    # Cash a cashier hands over sits "in transit" until the vault holder counts and confirms it.
    NEEDS_CONFIRMATION = {"close", "drop"}
    STATUS = [("settled", "Settled"), ("pending", "Waiting for the vault holder")]
    vault = models.ForeignKey(Vault, on_delete=models.PROTECT, related_name="transfers")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="cash_transfers")
    kind = models.CharField(max_length=15, choices=KIND, db_index=True)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    till_session = models.ForeignKey("sales.TillSession", on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="cash_transfers")
    counterparty = models.CharField(max_length=120, blank=True, help_text="Bank, finance person or supplier.")
    reference = models.CharField(max_length=60, blank=True, help_text="Deposit slip, receipt or voucher number.")
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    vault_balance_after = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    journal_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="settled", db_index=True)
    received_amount = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True,
                                          help_text="What the vault holder counted on receipt.")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_note = models.CharField(max_length=255, blank=True)
    confirm_entry = models.OneToOneField("accounting.JournalEntry", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["branch", "created_at"])]

    @property
    def difference(self):
        return None if self.received_amount is None else self.received_amount - self.amount

    @property
    def direction(self):
        return "in" if self.kind in self.INTO_VAULT else "out"

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount}"


def active_custody(vault):
    return VaultCustody.active().filter(vault=vault).select_related("custodian").first()

