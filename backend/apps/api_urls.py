from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounting import api as accounting
from apps.accounts import api as accounts
from apps.catalog import api as catalog
from apps.comms import api as comms
from apps.cash import api as cash
from apps.core import api as core
from apps.hr import api as hr
from apps.inventory import api as inventory
from apps.inventory import counts_api
from apps.core import admin_theme, system
from apps.payments import api as payments
from apps.sales import api as sales
from apps.sales import reports
from apps.sales import proformas
from apps.core import branding

r = DefaultRouter()
# organization & users
r.register("branches", core.BranchViewSet, basename="branch")
r.register("tills", core.TillViewSet, basename="till")
r.register("audit-logs", core.AuditLogViewSet, basename="auditlog")
r.register("users", accounts.UserViewSet, basename="user")
r.register("roles", accounts.RoleViewSet, basename="role")
# catalog & inventory
r.register("tax-rates", catalog.TaxRateViewSet, basename="taxrate")
r.register("categories", catalog.CategoryViewSet, basename="category")
r.register("products", catalog.ProductViewSet, basename="product")
r.register("stock-levels", inventory.StockLevelViewSet, basename="stocklevel")
r.register("stock-movements", inventory.StockMovementViewSet, basename="stockmovement")
r.register("suppliers", inventory.SupplierViewSet, basename="supplier")
r.register("purchase-orders", inventory.PurchaseOrderViewSet, basename="purchaseorder")
r.register("transfers", inventory.TransferViewSet, basename="transfer")
r.register("stock-counts", counts_api.StockCountViewSet, basename="stockcount")
# POS
r.register("customers", sales.CustomerViewSet, basename="customer")
r.register("till-sessions", sales.TillSessionViewSet, basename="tillsession")
r.register("sales", sales.SaleViewSet, basename="sale")
r.register("overrides", sales.OverrideViewSet, basename="override")
r.register("proformas", proformas.ProformaViewSet, basename="proforma")
r.register("payment-methods", payments.PaymentMethodViewSet, basename="paymentmethod")
# accounting
r.register("accounting/accounts", accounting.AccountViewSet, basename="account")
r.register("accounting/journal-entries", accounting.JournalEntryViewSet, basename="journalentry")
r.register("accounting/expenses", accounting.ExpenseViewSet, basename="expense")
r.register("accounting/cash-movements", accounting.CashMovementViewSet, basename="cashmovement")
# cash: vaults and cash movements
r.register("cash/vaults", cash.VaultViewSet, basename="vault")
r.register("cash/transfers", cash.TransferViewSet, basename="cashtransfer")
# messages
r.register("comms/inbox", comms.InboxViewSet, basename="inbox")
r.register("comms/sent", comms.SentViewSet, basename="sent")
r.register("comms/groups", comms.GroupViewSet, basename="staffgroup")
# HR
r.register("hr/departments", hr.DepartmentViewSet, basename="department")
r.register("hr/employees", hr.EmployeeViewSet, basename="employee")
r.register("hr/attendance", hr.AttendanceViewSet, basename="attendance")
r.register("hr/leave", hr.LeaveViewSet, basename="leave")
r.register("hr/shifts", hr.ShiftViewSet, basename="shift")

urlpatterns = [
    path("me/", accounts.me),
    path("me/preferences/", accounts.preferences),
    path("branding/", branding.public_branding),
    path("branding/settings/", branding.branding_settings),
    path("permissions/", accounts.permission_catalog),
    path("pos/catalog/", catalog.pos_catalog),
    path("inventory/adjust/", inventory.adjust),
    path("stock/lookup/", counts_api.lookup),
    path("stock/import/", counts_api.stock_import),
    path("stock/import/template/", counts_api.stock_import_template),
    path("system/overview/", system.overview),
    path("admin-handoff/", admin_theme.admin_handoff),
    path("reports/sales-summary/", sales.sales_summary),
    path("reports/dashboard/", reports.dashboard),
    path("reports/trial-balance/", accounting.trial_balance),
    path("payments/callback/<slug:provider>/", payments.provider_callback),
    path("comms/compose/", comms.compose),
    path("comms/preview/", comms.preview),
    path("comms/directory/", comms.directory),
    path("", include(r.urls)),
]
