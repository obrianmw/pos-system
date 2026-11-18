from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Membership, Role, User


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (("Shop", {"fields": ("organization", "phone")}),)
    list_display = ["username", "first_name", "last_name", "organization", "is_active"]
    list_filter = ["organization", "is_active"]
    inlines = [MembershipInline]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "scope", "is_active"]
    list_filter = ["organization", "scope"]
