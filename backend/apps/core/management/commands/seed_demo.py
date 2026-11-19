from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from collections import defaultdict

from apps.accounting.services import acct, post
from apps.accounts.models import Membership, Role, User
from apps.catalog.models import Category, Product, TaxRate
from apps.core.models import Branch, Organization, Till
from apps.core.setup import setup_organization
from apps.inventory.services import move_stock
from apps.payments.models import PaymentMethod

DEMO_PASSWORD = "demo-pass-2026"
DEMO_PIN = "2468"

PRODUCTS = [
    # sku, name, category, cost, price, barcode
    ("SUG-2KG", "Sugar 2kg", "Groceries", 4200, 5500, "6009801234561"),
    ("OIL-2L", "Cooking oil 2L", "Groceries", 9800, 12500, "6009801234578"),
    ("RICE-5KG", "Rice 5kg (Kilombero)", "Groceries", 11000, 14500, "6009801234585"),
    ("MAIZE-10", "Maize flour 10kg", "Groceries", 9000, 11000, "6009801234592"),
    ("SOAP-BAR", "Bathing soap", "Toiletries", 650, 950, "6009801234608"),
    ("TP-4", "Toilet paper 4-pack", "Toiletries", 2100, 2900, "6009801234615"),
    ("COKE-500", "Coca-Cola 500ml", "Drinks", 600, 900, "5449000000996"),
    ("WATER-1L", "Mineral water 1L", "Drinks", 450, 700, "6009801234622"),
    ("BREAD", "Bread loaf", "Bakery", 1300, 1700, "6009801234639"),
    ("AIRTIME-1K", "Airtime voucher 1000", "Services", 950, 1000, ""),
]

USERS = [
    # username, first, last, role, branch_code (None = org-wide), pin?
    ("owner", "Org", "Admin", "Organization Admin", None, True),
    ("accounts", "Head", "Accountant", "Organization Accountant", None, False),
    ("hr", "Head", "HR", "Organization HR", None, False),
    ("ll_admin", "Lilongwe", "Admin", "Branch Admin", "ll", False),
    ("ll_super", "Lilongwe", "Supervisor", "Supervisor", "ll", True),
    ("ll_cash1", "Lilongwe", "Cashier", "Cashier", "ll", False),
    ("ll_store", "Lilongwe", "Storekeeper", "Storekeeper", "ll", False),
    ("ll_count", "Lilongwe", "Stock Taker", "Stock Taker", "ll", False),
    ("ll_verify", "Lilongwe", "Stock Verifier", "Stock Verifier", "ll", False),
    ("bt_admin", "Blantyre", "Admin", "Branch Admin", "bt", False),
    ("bt_super", "Blantyre", "Supervisor", "Supervisor", "bt", True),
    ("bt_cash1", "Blantyre", "Cashier", "Cashier", "bt", False),
]


class Command(BaseCommand):
    help = "Create a demo organization with two branches, users for every role, products and stock."

    @transaction.atomic
    def handle(self, *args, **opts):
        org, _ = Organization.objects.get_or_create(code="demo", defaults={"name": "Aden Trifo Shop", "currency": "MWK"})
        setup_organization(org)
        from apps.core.models import Branding
        Branding.objects.get_or_create(organization=org, defaults={
            "display_name": "Aden Trifo Shop", "tagline": "Groceries, fresh food and more",
            "doc_business_name": "Aden Trifo Shop", "doc_phone": "+265 1 000 000", "doc_email": "hello@adentrifoshop.example",
            "doc_address": "City Centre, Lilongwe, Malawi"})
        branches = {}
        for code, name in [("ll", "Lilongwe City Centre"), ("bt", "Blantyre Limbe")]:
            b, _ = Branch.objects.get_or_create(organization=org, code=code, defaults={
                "name": name, "max_cashier_discount_pct": Decimal("5"),
                "receipt_footer": "Thank you for shopping with us!"})
            branches[code] = b
            for i in (1, 2, 3):
                Till.objects.get_or_create(branch=b, code=f"t{i}", defaults={"name": f"Till {i}"})

        vat, _ = TaxRate.objects.get_or_create(organization=org, name="VAT 16.5%",
                                               defaults={"rate": Decimal("16.50"), "inclusive": True})
        exempt, _ = TaxRate.objects.get_or_create(organization=org, name="Exempt",
                                                  defaults={"rate": Decimal("0"), "inclusive": True})
        opening_value = defaultdict(Decimal)
        for sku, name, cat, cost, price, barcode in PRODUCTS:
            c, _ = Category.objects.get_or_create(organization=org, name=cat, parent=None)
            p, created = Product.objects.get_or_create(organization=org, sku=sku, defaults={
                "name": name, "category": c, "cost_price": cost, "sell_price": price, "barcode": barcode,
                "tax_rate": exempt if cat in ("Services",) else vat, "reorder_level": 10,
                "min_price": Decimal(cost), "track_stock": cat != "Services"})
            if created and p.track_stock:
                for b in branches.values():
                    move_stock(branch=b, product=p, quantity=100, kind="opening", unit_cost=cost,
                               reference="OPENING", note="Demo opening stock")
                    opening_value[b.code] += Decimal(cost) * 100

        for code, value in opening_value.items():
            if value:  # opening stock is owner's capital: Dr Inventory / Cr Equity
                post(organization=org, branch=branches[code], reference=f"OPENING-{code}", source="opening",
                     memo="Opening stock", lines=[(acct(org, "inventory"), value, 0, "Opening stock"),
                                                  (acct(org, "equity"), 0, value, "Opening stock")])

        methods = [
            ("Cash", "cash", "manual", {}, False, True),
            ("Bank transfer", "bank_transfer", "manual", {}, True, False),
            ("Card (own terminal)", "card_terminal", "manual", {}, True, True),
            ("Airtel Money", "mobile_money", "airtel_money", {"country": "MW", "dial_code": "265"}, False, False),
            ("TNM Mpamba / Card (PayChangu)", "card_gateway", "paychangu", {}, False, False),
            ("M-Pesa", "mobile_money", "mpesa", {}, False, False),
            ("MTN MoMo", "mobile_money", "mtn_momo", {}, False, False),
            ("Store credit", "store_credit", "manual", {}, False, False),
        ]
        for i, (name, kind, provider, config, needs_ref, offline) in enumerate(methods):
            PaymentMethod.objects.get_or_create(organization=org, name=name, defaults={
                "kind": kind, "provider": provider, "config": config, "requires_reference": needs_ref,
                "allowed_offline": offline, "sort_order": i})
        # Give each wallet its own ledger account so it can be reconciled against its statement.
        for m in PaymentMethod.objects.filter(organization=org, kind="mobile_money", ledger_account=None):
            parent = acct(org, "mobile_money")
            a, _ = parent.__class__.objects.get_or_create(
                organization=org, code=f"1020-{m.pk}", defaults={"name": f"{m.name} wallet", "type": "asset",
                                                                  "parent": parent})
            m.ledger_account = a
            m.save(update_fields=["ledger_account"])

        for username, first, last, role_name, bcode, pin in USERS:
            u, created = User.objects.get_or_create(username=username, defaults={
                "first_name": first, "last_name": last, "organization": org})
            if created:
                u.set_password(DEMO_PASSWORD)
                if pin:
                    u.set_supervisor_pin(DEMO_PIN)
                u.is_staff = bcode is None and role_name == "Organization Admin"
                u.is_superuser = u.is_staff
                u.save()
            Membership.objects.get_or_create(user=u, role=Role.objects.get(organization=org, name=role_name),
                                             branch=branches[bcode] if bcode else None)

        from django.core.management import call_command
        call_command("seed_catalog", org=org.code, stdout=self.stdout)
        call_command("seed_cash", org=org.code, stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready. Users: {', '.join(u[0] for u in USERS)}\n"
            f"Password for all: {DEMO_PASSWORD}   Supervisor PIN (owner, ll_super, bt_super): {DEMO_PIN}"))
