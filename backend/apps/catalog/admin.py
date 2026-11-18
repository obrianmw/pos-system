from django.contrib import admin

from .models import BranchPrice, Category, Product, TaxRate


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ["name", "rate", "inclusive", "organization"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "parent", "organization"]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "sell_price", "cost_price", "category", "is_active"]
    search_fields = ["sku", "name", "barcode"]
    list_filter = ["organization", "category", "is_active"]


@admin.register(BranchPrice)
class BranchPriceAdmin(admin.ModelAdmin):
    list_display = ["product", "branch", "price"]
