"""Every permission code the system checks. Roles hold a list of these codes ("*" = all).

Codes are data, so organizations can build their own roles in the admin without code changes.
"""

PERMISSIONS = {
    # POS / counter
    "pos.sell": "Ring up sales at a till",
    "pos.open_till": "Open and close own till session",
    "pos.price_override": "Change an item price at the counter (supervisor)",
    "pos.discount_override": "Give discounts above the branch cashier limit (supervisor)",
    "pos.void": "Void a sale (supervisor)",
    "pos.refund": "Process returns/refunds (supervisor)",
    "pos.view_all_sales": "See sales from all tills at the branch",
    # Catalog & inventory
    "catalog.manage": "Create/edit products, categories and prices",
    "inventory.view": "View stock levels and movements",
    "inventory.adjust": "Post stock adjustments / stock takes",
    "inventory.count": "Count stock in stock takes (scan on a phone)",
    "inventory.verify": "Verify other people's stock counts and post the differences",
    "inventory.receive": "Receive goods against purchase orders",
    "inventory.transfer": "Send/receive stock transfers between branches",
    "purchasing.manage": "Manage suppliers and purchase orders",
    # Accounting
    "accounting.view": "View ledgers and financial reports",
    "accounting.post": "Post manual journals, expenses and cash movements",
    "accounting.reconcile": "Reconcile till sessions, bank and wallet balances",
    # HR & admin
    "hr.view": "View staff records",
    "hr.manage": "Manage staff, attendance and leave",
    "hr.approve_leave": "Approve leave requests",
    "branch.admin": "Manage branch settings, tills and branch users",
    "org.admin": "Manage the whole organization",
    "payments.configure": "Configure payment methods and wallet integrations",
    "audit.view": "View the audit log",
    # Messages & announcements (everyone can read their own inbox and reply to what they received)
    "comms.send": "Send messages/announcements to people, departments, groups and roles in your branches",
    "comms.broadcast": "Send to all staff and to any branch in the organization",
    # Cash
    "vault.operate": "Move cash in and out of the branch vault (given automatically to today's vault holder)",
}

# Whoever holds a branch vault is that branch's authorizer for as long as they hold it.
CUSTODIAN_PERMISSIONS = {"vault.operate", "pos.price_override", "pos.discount_override", "pos.void",
                         "pos.refund", "pos.view_all_sales"}

# Permissions added after first release; a data migration grants them to the default roles that exist.
ADDED_PERMISSIONS = {
    "comms.send": ["Organization Accountant", "Organization HR", "Branch Admin", "Supervisor",
                   "Branch Accountant", "Branch HR"],
    "comms.broadcast": ["Organization HR"],
    "inventory.count": ["Branch Admin", "Supervisor", "Storekeeper"],
    "inventory.verify": ["Branch Admin", "Supervisor"],
}

# name -> (scope, permissions). "org" roles are assigned without a branch and apply to every branch.
DEFAULT_ROLES = {
    "Organization Admin": ("org", ["*"]),
    "Organization Accountant": ("org", ["accounting.view", "accounting.post", "accounting.reconcile",
                                        "inventory.view", "pos.view_all_sales", "audit.view", "comms.send"]),
    "Organization HR": ("org", ["hr.view", "hr.manage", "hr.approve_leave", "comms.send", "comms.broadcast"]),
    "Branch Admin": ("branch", ["branch.admin", "catalog.manage", "inventory.view", "inventory.adjust",
                                "inventory.count", "inventory.verify",
                                "inventory.receive", "inventory.transfer", "purchasing.manage",
                                "pos.view_all_sales", "hr.view", "audit.view", "payments.configure", "comms.send"]),
    "Supervisor": ("branch", ["pos.sell", "pos.open_till", "pos.price_override", "pos.discount_override",
                              "pos.void", "pos.refund", "pos.view_all_sales", "inventory.view", "comms.send",
                              "inventory.count", "inventory.verify"]),
    "Cashier": ("branch", ["pos.sell", "pos.open_till"]),
    "Storekeeper": ("branch", ["inventory.view", "inventory.adjust", "inventory.receive", "inventory.transfer",
                               "inventory.count"]),
    "Stock Taker": ("branch", ["inventory.view", "inventory.count"]),
    "Stock Verifier": ("branch", ["inventory.view", "inventory.count", "inventory.verify"]),
    "Branch Accountant": ("branch", ["accounting.view", "accounting.post", "accounting.reconcile",
                                     "pos.view_all_sales", "inventory.view", "comms.send"]),
    "Branch HR": ("branch", ["hr.view", "hr.manage", "hr.approve_leave", "comms.send"]),
}
