"""Demo cash setup: `manage.py seed_cash`. Safe to run again.

For every branch: create the vault, assign the branch's cashiers/supervisors to its tills, fund an
empty vault with a demo bank withdrawal, and give today's vault custody to the branch supervisor.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Membership, User
from apps.cash import services as cash
from apps.cash.models import active_custody
from apps.core.models import Branch

OPENING = 300_000


class Command(BaseCommand):
    help = "Create vaults, assign tills and give each branch supervisor today's vault (demo data)."

    def add_arguments(self, parser):
        parser.add_argument("--org", default="demo")

    @transaction.atomic
    def handle(self, *args, org, **opts):
        owner = User.objects.filter(organization__code=org, is_superuser=True).first() or \
            User.objects.filter(organization__code=org).first()
        for b in Branch.objects.filter(organization__code=org, is_active=True):
            vault = cash.vault_for(b)
            sellers = User.objects.filter(memberships__branch=b, memberships__is_active=True,
                                          memberships__role__permissions__icontains="pos.open_till").distinct()
            for till in b.tills.filter(is_active=True):
                till.users.add(*sellers)
            if cash.vault_balance(b) <= 0:
                cash.move(branch=b, kind="from_bank", amount=OPENING, by=owner, reference="DEMO-OPENING",
                          note="Demo opening cash for the vault", system=True)
            if not active_custody(vault):
                sup = User.objects.filter(memberships__branch=b, memberships__is_active=True,
                                          memberships__role__name="Supervisor").first()
                if sup:
                    cash.assign_custody(vault, custodian=sup, by=owner, note="Demo: supervisor holds the vault today")
            self.stdout.write(f"{b.name}: {sellers.count()} people assigned to {b.tills.count()} tills; "
                              f"vault {cash.vault_balance(b):,.2f}; held by "
                              f"{(active_custody(vault).custodian.username if active_custody(vault) else 'nobody')}")
        # Demo payment-QR details (an admin replaces these with the shop's real merchant/bank numbers).
        from apps.payments.models import PaymentMethod
        demo_qr = {"Airtel Money": {"qr_merchant": "DEMO-0880000"}, "MTN MoMo": {"qr_merchant": "DEMO-0990000"},
                   "Bank transfer": {"qr_bank": "Demo Bank", "qr_account": "000000000000", "qr_account_name": "Aden Shop"}}
        for m in PaymentMethod.objects.filter(organization__code=org, name__in=demo_qr):
            if not any(k.startswith("qr_") for k in m.config or {}):
                m.config = {**(m.config or {}), **demo_qr[m.name]}
                m.save(update_fields=["config", "updated_at"])
        self.stdout.write(self.style.SUCCESS("Cash setup ready."))
