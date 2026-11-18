"""Demo sales history so dashboards have something to show: `manage.py seed_sales --days 30`.

Goes through the real checkout service (stock, ledger, audit all stay consistent), then back-dates
each sale and its journal entry. Demo use only.
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounting.models import JournalEntry
from apps.accounting.services import acct, post
from apps.accounts.models import User
from apps.catalog.models import Product
from apps.core.models import Branch
from apps.inventory.services import move_stock
from apps.payments.models import PaymentMethod
from apps.sales import services
from apps.sales.models import Sale, TillSession


class Command(BaseCommand):
    help = "Generate back-dated demo sales for the demo organization."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--seed", type=int, default=7)

    def handle(self, *args, days, seed, **opts):
        rnd = random.Random(seed)
        cash = PaymentMethod.objects.get(organization__code="demo", name="Cash")
        card = PaymentMethod.objects.get(organization__code="demo", name="Card (own terminal)")
        products = list(Product.objects.filter(organization__code="demo", is_active=True))
        made = 0
        for branch, cashier_name, busy in [("ll", "ll_cash1", 1.0), ("bt", "bt_cash1", 0.7)]:
            b = Branch.objects.get(organization__code="demo", code=branch)
            cashier = User.objects.get(username=cashier_name)
            till = b.tills.get(code="t3")
            topup = Decimal("0")
            for p in products:  # top up so history doesn't run the shelves dry
                if p.track_stock:
                    move_stock(branch=b, product=p, quantity=400, kind="purchase", unit_cost=p.cost_price,
                               reference="DEMO-TOPUP")
                    topup += p.cost_price * 400
            org = b.organization  # extra stock is owner's capital in the demo: Dr Inventory / Cr Equity
            post(organization=org, branch=b, reference=f"DEMO-TOPUP-{b.code}", source="opening",
                 memo="Demo stock top-up", date=timezone.localdate() - timedelta(days=days),
                 lines=[(acct(org, "inventory"), topup, 0, "Stock top-up"), (acct(org, "equity"), 0, topup, "Stock top-up")])
            session = TillSession.objects.filter(till=till, status="open").first() or \
                services.open_till(till=till, user=User.objects.get(username="owner"), opening_float=0)
            for d in range(days, 0, -1):
                day = timezone.localdate() - timedelta(days=d)
                weekend = day.weekday() >= 5
                n = int(rnd.randint(8, 16) * busy * (1.4 if weekend else 1))
                for _ in range(n):
                    lines = [{"product_id": p.pk, "quantity": str(rnd.choice([1, 1, 1, 2, 3]))}
                             for p in rnd.sample(products, rnd.randint(1, 4))]
                    sale, _ = services.checkout(user=User.objects.get(username="owner"), session=session,
                                                data={"lines": lines, "payments": []} | {"offline": True})
                    method = card if rnd.random() < 0.3 else cash
                    sale.payments.create(method=method, amount=sale.total, status="confirmed",
                                         confirmed_at=timezone.now(), received_by=cashier)
                    when = timezone.make_aware(datetime.combine(day, time(rnd.randint(8, 19), rnd.randint(0, 59))))
                    Sale.objects.filter(pk=sale.pk).update(
                        cashier=cashier, created_offline=False, needs_review=False, review_reason="",
                        created_at=when, completed_at=when)
                    entry = JournalEntry.objects.filter(reference=sale.number, source="sale").first()
                    if entry:  # re-post with the payment now attached, dated on the sale day
                        entry.delete()
                    from apps.accounting.services import post_sale
                    e = post_sale(Sale.objects.get(pk=sale.pk))
                    JournalEntry.objects.filter(pk=e.pk).update(date=day)
                    made += 1
            services.close_till(session, user=User.objects.get(username="owner"),
                                counted_cash=services.expected_cash(session))
        self.stdout.write(self.style.SUCCESS(f"Created {made} demo sales over {days} days."))
