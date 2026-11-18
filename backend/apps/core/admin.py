from django.contrib import admin

from .models import AuditLog, Branch, Organization, Sequence, Till


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "currency", "is_active"]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "code", "is_active", "allow_negative_stock"]
    list_filter = ["organization", "is_active"]


@admin.register(Till)
class TillAdmin(admin.ModelAdmin):
    list_display = ["name", "branch", "code", "is_active"]
    list_filter = ["branch"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "action", "actor", "branch", "object_type", "object_id"]
    list_filter = ["action", "branch"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
