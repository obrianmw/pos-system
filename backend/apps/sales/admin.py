from django.contrib import admin

from .models import Customer, OverrideApproval, Sale, SaleLine, TillSession


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "phone", "organization"]
    search_fields = ["name", "phone"]


@admin.register(TillSession)
class TillSessionAdmin(admin.ModelAdmin):
    list_display = ["till", "cashier", "status", "opened_at", "expected_cash", "counted_cash", "variance"]
    list_filter = ["status", "branch"]


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["number", "branch", "kind", "status", "total", "cashier", "needs_review", "created_at"]
    list_filter = ["branch", "status", "kind", "needs_review", "created_offline"]
    search_fields = ["number"]
    inlines = [type("Lines", (admin.TabularInline,), {"model": SaleLine, "extra": 0, "fk_name": "sale"})]


@admin.register(OverrideApproval)
class OverrideApprovalAdmin(admin.ModelAdmin):
    list_display = ["created_at", "branch", "kind", "status", "method", "requested_by", "approved_by", "original_value", "new_value"]
    list_filter = ["kind", "status", "method", "branch"]
