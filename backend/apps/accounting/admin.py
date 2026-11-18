from django.contrib import admin

from .models import Account, CashMovement, Expense, JournalEntry, JournalLine


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "type", "system_key", "organization"]
    list_filter = ["organization", "type"]


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "reference", "source", "branch", "memo"]
    list_filter = ["source", "branch"]
    inlines = [type("Lines", (admin.TabularInline,), {"model": JournalLine, "extra": 0, "can_delete": False})]

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "branch", "description", "amount", "status"]
    list_filter = ["status", "branch"]


@admin.register(CashMovement)
class CashMovementAdmin(admin.ModelAdmin):
    list_display = ["date", "from_branch", "to_branch", "amount", "reference"]
