from django.contrib import admin

from .models import Payment, PaymentCallbackLog, PaymentMethod


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "provider", "organization", "is_active", "allowed_offline"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["sale", "method", "amount", "status", "provider_reference", "created_at"]
    list_filter = ["status", "method"]
    search_fields = ["provider_reference", "sale__number"]


@admin.register(PaymentCallbackLog)
class PaymentCallbackLogAdmin(admin.ModelAdmin):
    list_display = ["received_at", "provider", "payment", "processed", "error"]
