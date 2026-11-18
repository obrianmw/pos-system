from decimal import Decimal

from django.db import models

from apps.core.models import Branch, Organization, TimeStamped


class TaxRate(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="tax_rates")
    name = models.CharField(max_length=50)  # e.g. "VAT 16.5%", "Exempt"
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Percent, e.g. 16.50")
    inclusive = models.BooleanField(default=True, help_text="Shelf prices already include this tax.")

    def __str__(self):
        return self.name


class Category(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=100)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    image = models.ImageField(upload_to="categories/", blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = "categories"
        unique_together = [("organization", "parent", "name")]
        ordering = ["sort_order", "name"]

    def path(self):
        """"Food › Meat" - walks up the parents (trees are shallow)."""
        names, c, seen = [], self, set()
        while c is not None and c.pk not in seen:
            seen.add(c.pk)
            names.append(c.name)
            c = c.parent
        return " › ".join(reversed(names))

    def __str__(self):
        return self.name


class Product(TimeStamped):
    """Organization-wide product master. Branches can override the price via BranchPrice."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="products")
    sku = models.CharField(max_length=50)
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    image = models.ImageField(upload_to="products/", blank=True, help_text="Photo shown on the till and in lists.")
    unit = models.CharField(max_length=20, default="pcs")
    cost_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    sell_price = models.DecimalField(max_digits=14, decimal_places=2)
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.PROTECT, null=True, blank=True)
    track_stock = models.BooleanField(default=True)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0"))
    min_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                    help_text="Floor price; even supervisors cannot go below it.")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("organization", "sku")]
        indexes = [models.Index(fields=["organization", "name"])]

    def __str__(self):
        return f"{self.sku} {self.name}"

    def price_at(self, branch: Branch) -> Decimal:
        bp = self.branch_prices.filter(branch=branch).first()
        return bp.price if bp else self.sell_price


class BranchPrice(TimeStamped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="branch_prices")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="prices")
    price = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = [("product", "branch")]
