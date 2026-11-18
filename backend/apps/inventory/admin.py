from django.contrib import admin

from .models import PurchaseOrder, StockLevel, StockMovement, StockTransfer, Supplier


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ["product", "branch", "quantity", "avg_cost"]
    list_filter = ["branch"]
    search_fields = ["product__name", "product__sku"]
    readonly_fields = ["quantity", "avg_cost"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "branch", "product", "kind", "quantity", "balance_after", "reference"]
    list_filter = ["branch", "kind"]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "organization"]


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "branch", "supplier", "status"]


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = ["number", "from_branch", "to_branch", "status"]
