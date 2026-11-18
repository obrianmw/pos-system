"""Demo catalogue with categories, subcategories and pictures: `manage.py seed_catalog`.

Safe to run again: existing categories/products are reused, pictures are only added where missing.
Opening stock for new products is booked as owner's capital (Dr Inventory / Cr Equity).
"""
from collections import defaultdict
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.services import acct, post
from apps.catalog.demo_art import svg
from apps.catalog.models import Category, Product, TaxRate
from apps.core.models import Branch, Organization
from apps.inventory.services import move_stock

# top-level -> (sort, art for the tile, [(subcategory, art)])
TREE = {
    "Food": (1, "tomato", [("Meat & Poultry", "beef"), ("Vegetables", "cabbage"), ("Fruits", "banana"),
                           ("Bakery", "bread"), ("Staples", "maize")]),
    "Drinks": (2, "cola", [("Soft drinks", "cola"), ("Water", "water")]),
    "Household": (3, "soap", [("Toiletries", "tissue")]),
    "Services": (4, "airtime", [("Airtime", "airtime")]),
}
# Older demo categories folded into the tree: old name -> (parent, new name)
RENAMES = {"Groceries": ("Food", "Staples"), "Bakery": ("Food", "Bakery"), "Toiletries": ("Household", "Toiletries")}

EXISTING = {  # sku -> (subcategory, art)
    "SUG-2KG": ("Staples", "sugar"), "OIL-2L": ("Staples", "oil"), "RICE-5KG": ("Staples", "rice"),
    "MAIZE-10": ("Staples", "maize"), "PB-400": ("Staples", "peanut"), "BREAD": ("Bakery", "bread"),
    "SOAP-BAR": ("Toiletries", "soap"), "TP-4": ("Toiletries", "tissue"), "COKE-500": ("Soft drinks", "cola"),
    "WATER-1L": ("Water", "water"), "AIRTIME-1K": ("Airtime", "airtime"),
}
NEW = [  # sku, name, subcategory, art, unit, cost, price  (fresh food is VAT-exempt)
    ("BEEF-1KG", "Beef steak 1kg", "Meat & Poultry", "beef", "kg", 6500, 8500),
    ("CHICK-WHL", "Whole chicken", "Meat & Poultry", "chicken", "pcs", 7000, 9500),
    ("GOAT-1KG", "Goat meat 1kg", "Meat & Poultry", "goat", "kg", 7500, 9800),
    ("TOM-1KG", "Tomatoes 1kg", "Vegetables", "tomato", "kg", 1200, 1800),
    ("ONION-1KG", "Onions 1kg", "Vegetables", "onion", "kg", 1500, 2200),
    ("CABBAGE", "Cabbage (head)", "Vegetables", "cabbage", "pcs", 800, 1200),
    ("POT-5KG", "Irish potatoes 5kg", "Vegetables", "potato", "bag", 3500, 5000),
    ("BANANA-BN", "Bananas (bunch)", "Fruits", "banana", "bunch", 900, 1400),
    ("ORANGE-1KG", "Oranges 1kg", "Fruits", "orange", "kg", 1300, 2000),
]


class Command(BaseCommand):
    help = "Organise the demo catalogue into categories/subcategories and give every item a picture."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="demo")

    @transaction.atomic
    def handle(self, *args, org, **opts):
        o = Organization.objects.get(code=org)
        sub = {}
        for top, (order, art, children) in TREE.items():
            parent = Category.objects.filter(organization=o, name=top, parent=None).first() or \
                Category.objects.create(organization=o, name=top)
            parent.sort_order = order
            self._picture(parent, art, f"cat-{top}")
            parent.save()
            for i, (name, child_art) in enumerate(children):
                old = next((k for k, v in RENAMES.items() if v == (top, name)), None)
                c = (Category.objects.filter(organization=o, name=name, parent=parent).first()
                     or (Category.objects.filter(organization=o, name=old, parent=None).first() if old else None)
                     or Category(organization=o, name=name))
                c.name, c.parent, c.sort_order = name, parent, i
                self._picture(c, child_art, f"cat-{top}-{name}")
                c.save()
                sub[name] = c

        for sku, (name, art) in EXISTING.items():
            p = Product.objects.filter(organization=o, sku=sku).first()
            if p:
                p.category = sub[name]
                self._picture(p, art, sku)
                p.save()

        exempt = TaxRate.objects.filter(organization=o, rate=0).first()
        branches = list(Branch.objects.filter(organization=o, is_active=True))
        opening = defaultdict(Decimal)
        made = 0
        for sku, name, cat, art, unit, cost, price in NEW:
            p, created = Product.objects.get_or_create(organization=o, sku=sku, defaults={
                "name": name, "category": sub[cat], "unit": unit, "cost_price": cost, "sell_price": price,
                "tax_rate": exempt, "reorder_level": 10, "min_price": Decimal(cost)})
            self._picture(p, art, sku)
            p.save()
            if created:
                made += 1
                for b in branches:
                    move_stock(branch=b, product=p, quantity=60, kind="opening", unit_cost=cost,
                               reference="OPENING", note="Demo opening stock")
                    opening[b.pk] += Decimal(cost) * 60
        for b in branches:
            if opening[b.pk]:
                post(organization=o, branch=b, reference=f"OPENING-FRESH-{b.code}", source="opening",
                     memo="Opening stock (fresh food)",
                     lines=[(acct(o, "inventory"), opening[b.pk], 0, "Opening stock"),
                            (acct(o, "equity"), 0, opening[b.pk], "Opening stock")])
        # Empty old top-level categories left behind by earlier demo versions.
        for c in Category.objects.filter(organization=o, parent=None).exclude(name__in=TREE):
            if not c.children.exists() and not Product.objects.filter(category=c).exists():
                c.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Catalogue ready: {len(TREE)} departments, {len(sub)} subcategories, {made} new products with pictures."))

    @staticmethod
    def _picture(obj, art, stem):
        if not obj.image:
            obj.image.save(f"{stem.lower().replace(' ', '-').replace('&', 'and')}.svg",
                           ContentFile(svg(art).encode()), save=False)
