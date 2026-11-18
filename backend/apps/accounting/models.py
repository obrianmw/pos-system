from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Branch, Organization, TimeStamped


class Account(TimeStamped):
    TYPES = [("asset", "Asset"), ("liability", "Liability"), ("equity", "Equity"),
             ("income", "Income"), ("expense", "Expense")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=TYPES)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    # Stable key used by automatic postings (e.g. "cash", "sales"). Blank for user-created accounts.
    system_key = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("organization", "code")]
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "system_key"], condition=~models.Q(system_key=""),
                                    name="uniq_account_system_key"),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def normal_debit(self):
        return self.type in ("asset", "expense")


class JournalEntry(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="journal_entries")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    date = models.DateField(db_index=True)
    reference = models.CharField(max_length=64, db_index=True)
    memo = models.CharField(max_length=255, blank=True)
    source = models.CharField(max_length=30, blank=True, help_text="sale, refund, expense, manual ...")
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    reverses = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="reversed_by")

    class Meta:
        ordering = ["-date", "-id"]
        verbose_name_plural = "journal entries"

    def __str__(self):
        return f"{self.date} {self.reference}"


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="lines")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True)
    debit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    credit = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [models.Index(fields=["account", "branch"])]

    def clean(self):
        if (self.debit and self.credit) or (not self.debit and not self.credit):
            raise ValidationError("A line has either a debit or a credit.")


class Expense(TimeStamped):
    STATUS = [("pending", "Pending approval"), ("approved", "Approved & posted"), ("rejected", "Rejected")]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="expenses")
    expense_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    paid_from = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+",
                                  help_text="Cash, bank or wallet account the money left.")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    description = models.CharField(max_length=255)
    receipt_number = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True)


class CashMovement(TimeStamped):
    """Money moved between cash/bank/wallet accounts: banking takings, float top-ups, HQ remittance."""

    from_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="+")
    to_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="+")
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField()
    reference = models.CharField(max_length=60, blank=True, help_text="Deposit slip / wallet txn id")
    description = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    journal_entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, null=True, blank=True)
