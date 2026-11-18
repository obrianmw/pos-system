from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.catalog.models import Product
from apps.core.models import Branch, Organization, TimeStamped


class StockLevel(models.Model):
    """Current on-hand quantity per branch. Only changed through inventory.services.move_stock."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="stock_levels")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_levels")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    avg_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("branch", "product")]

    def __str__(self):
        return f"{self.product} @ {self.branch}: {self.quantity}"


class StockMovement(models.Model):
    """Append-only stock ledger. StockLevel.quantity == sum(quantity) for a branch/product."""

    KIND_CHOICES = [
        ("sale", "Sale"),
        ("refund", "Customer return"),
        ("void", "Sale void"),
        ("purchase", "Goods received"),
        ("adjustment", "Adjustment"),
        ("transfer_out", "Transfer out"),
        ("transfer_in", "Transfer in"),
        ("opening", "Opening balance"),
    ]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="stock_movements")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_movements")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, help_text="+ in, - out")
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    balance_after = models.DecimalField(max_digits=14, decimal_places=3)
    reference = models.CharField(max_length=64, blank=True, db_index=True)
    note = models.CharField(max_length=255, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["branch", "product", "created_at"])]


class Supplier(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PurchaseOrder(TimeStamped):
    STATUS = [("draft", "Draft"), ("ordered", "Ordered"), ("partial", "Partially received"),
              ("received", "Received"), ("cancelled", "Cancelled")]
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="purchase_orders")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    number = models.CharField(max_length=30, unique=True)
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    expected_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    note = models.TextField(blank=True)

    def __str__(self):
        return self.number


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))


class StockTransfer(TimeStamped):
    STATUS = [("draft", "Draft"), ("sent", "In transit"), ("received", "Received"), ("cancelled", "Cancelled")]
    number = models.CharField(max_length=30, unique=True)
    from_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_out")
    to_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="transfers_in")
    status = models.CharField(max_length=10, choices=STATUS, default="draft")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True,
                                    blank=True, related_name="+")
    note = models.TextField(blank=True)


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
