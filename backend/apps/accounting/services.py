"""Double-entry postings. Every money-moving event in the system ends up here."""
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Account, JournalEntry, JournalLine

ZERO = Decimal("0")
CENTS = Decimal("0.01")

DEFAULT_CHART = [
    # code, name, type, system_key
    ("1000", "Cash on hand", "asset", "cash"),
    ("1010", "Bank", "asset", "bank"),
    ("1020", "Mobile money wallets", "asset", "mobile_money"),
    ("1030", "Card settlements receivable", "asset", "card_clearing"),
    ("1100", "Accounts receivable", "asset", "accounts_receivable"),
    ("1200", "Inventory", "asset", "inventory"),
    ("2000", "Accounts payable", "liability", "accounts_payable"),
    ("2100", "VAT output", "liability", "vat_output"),
    ("2200", "Salaries payable", "liability", "salaries_payable"),
    ("3000", "Owner's equity", "equity", "equity"),
    ("4000", "Sales", "income", "sales"),
    ("4010", "Sales returns", "income", "sales_returns"),
    ("5000", "Cost of goods sold", "expense", "cogs"),
    ("5100", "Inventory shrinkage / adjustments", "expense", "shrinkage"),
    ("5200", "Cash over / short", "expense", "cash_over_short"),
    ("6000", "General expenses", "expense", "general_expense"),
    ("6100", "Salaries & wages", "expense", "salaries"),
    ("6200", "Rent", "expense", ""),
    ("6300", "Utilities", "expense", ""),
    ("6400", "Transport", "expense", ""),
]

METHOD_KIND_ACCOUNT = {"cash": "cash", "bank_transfer": "bank", "card_terminal": "card_clearing",
                       "card_gateway": "card_clearing", "mobile_money": "mobile_money",
                       "store_credit": "accounts_receivable"}


class UnbalancedEntry(Exception):
    pass


def ensure_chart(organization):
    for code, name, typ, key in DEFAULT_CHART:
        Account.objects.get_or_create(organization=organization, code=code,
                                      defaults={"name": name, "type": typ, "system_key": key})


def acct(organization, key) -> Account:
    try:
        return Account.objects.get(organization=organization, system_key=key)
    except Account.DoesNotExist:
        ensure_chart(organization)
        return Account.objects.get(organization=organization, system_key=key)


def payment_account(method) -> Account:
    return method.ledger_account or acct(method.organization, METHOD_KIND_ACCOUNT[method.kind])


@transaction.atomic
def post(*, organization, branch, reference, lines, memo="", source="", user=None, date=None, reverses=None):
    """lines: iterable of (account, debit, credit, description). Zero lines are dropped."""
    lines = [(a, Decimal(d).quantize(CENTS), Decimal(c).quantize(CENTS), desc) for a, d, c, desc in lines]
    lines = [l for l in lines if l[1] or l[2]]
    dr = sum(l[1] for l in lines)
    cr = sum(l[2] for l in lines)
    if dr != cr:
        raise UnbalancedEntry(f"{reference}: debits {dr} != credits {cr}")
    if not lines:
        return None
    entry = JournalEntry.objects.create(organization=organization, branch=branch, reference=reference,
                                        memo=memo, source=source, posted_by=user, reverses=reverses,
                                        date=date or timezone.localdate())
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=a, branch=branch, debit=d, credit=c, description=desc[:255])
        for a, d, c, desc in lines
    ])
    return entry


def _sale_lines(sale, revenue_key):
    org = sale.organization
    net = sum((l.net_amount for l in sale.lines.all()), ZERO)
    tax = sum((l.tax_amount for l in sale.lines.all()), ZERO)
    cost = sum(((l.quantity * l.unit_cost).quantize(CENTS) for l in sale.lines.all() if l.product.track_stock), ZERO)
    by_account = defaultdict(lambda: ZERO)
    for p in sale.payments.filter(status="confirmed").select_related("method"):
        by_account[payment_account(p.method)] += p.amount
    return org, net, tax, cost, by_account


def post_sale(sale, user=None):
    org, net, tax, cost, by_account = _sale_lines(sale, "sales")
    lines = [(a, amt, ZERO, f"Receipt {sale.number}") for a, amt in by_account.items()]
    # Offline sales flagged for review can be under/over-paid; park the gap so the books still balance.
    gap = sale.total - sum(by_account.values(), ZERO)
    if gap > 0:
        lines.append((acct(org, "accounts_receivable"), gap, ZERO, f"Unpaid, under review {sale.number}"))
    elif gap < 0:
        lines.append((acct(org, "cash_over_short"), ZERO, -gap, f"Overpaid, under review {sale.number}"))
    lines += [(acct(org, "sales"), ZERO, net, "Sales"), (acct(org, "vat_output"), ZERO, tax, "VAT")]
    lines += [(acct(org, "cogs"), cost, ZERO, "COGS"), (acct(org, "inventory"), ZERO, cost, "Inventory out")]
    return post(organization=org, branch=sale.branch, reference=sale.number, lines=lines, source="sale",
                user=user, memo=f"POS sale {sale.number}")


def post_refund(refund_sale, user=None):
    org, net, tax, cost, by_account = _sale_lines(refund_sale, "sales_returns")
    lines = [(acct(org, "sales_returns"), net, ZERO, "Returns"), (acct(org, "vat_output"), tax, ZERO, "VAT reversal")]
    lines += [(a, ZERO, amt, f"Refund {refund_sale.number}") for a, amt in by_account.items()]
    lines += [(acct(org, "inventory"), cost, ZERO, "Inventory back"), (acct(org, "cogs"), ZERO, cost, "COGS reversal")]
    return post(organization=org, branch=refund_sale.branch, reference=refund_sale.number, lines=lines,
                source="refund", user=user, memo=f"Refund of {refund_sale.original_sale}")


@transaction.atomic
def reverse_entry(entry, user=None, memo=""):
    lines = [(l.account, l.credit, l.debit, f"Reversal: {l.description}") for l in entry.lines.all()]
    return post(organization=entry.organization, branch=entry.branch, reference=f"REV-{entry.reference}",
                lines=lines, source="reversal", user=user, memo=memo or f"Reversal of {entry.reference}",
                reverses=entry)


def post_goods_received(order, total_cost, user, when):
    org = order.branch.organization
    return post(organization=org, branch=order.branch, reference=order.number, source="purchase", user=user,
                memo=f"Goods received from {order.supplier}",
                lines=[(acct(org, "inventory"), total_cost, ZERO, "Goods received"),
                       (acct(org, "accounts_payable"), ZERO, total_cost, str(order.supplier))])


def post_stock_adjustment(movement):
    org = movement.branch.organization
    value = (abs(movement.quantity) * movement.unit_cost).quantize(CENTS)
    inv, shrink = acct(org, "inventory"), acct(org, "shrinkage")
    lines = ([(shrink, value, ZERO, movement.note), (inv, ZERO, value, movement.note)] if movement.quantity < 0
             else [(inv, value, ZERO, movement.note), (shrink, ZERO, value, movement.note)])
    return post(organization=org, branch=movement.branch, reference=f"ADJ-{movement.pk}", lines=lines,
                source="adjustment", user=movement.user, memo=f"Stock adjustment {movement.product}")


def post_till_variance(session, user):
    if not session.variance:
        return None
    org = session.branch.organization
    v = abs(session.variance)
    cash, over_short = acct(org, "cash"), acct(org, "cash_over_short")
    lines = ([(cash, v, ZERO, "Cash over"), (over_short, ZERO, v, "Cash over")] if session.variance > 0
             else [(over_short, v, ZERO, "Cash short"), (cash, ZERO, v, "Cash short")])
    return post(organization=org, branch=session.branch, reference=f"TILL-{session.pk}", lines=lines,
                source="till_close", user=user, memo=f"Till variance {session.till}")


@transaction.atomic
def approve_expense(expense, user):
    if expense.status != "pending":
        raise ValueError("Expense already decided.")
    org = expense.branch.organization
    expense.journal_entry = post(
        organization=org, branch=expense.branch, reference=f"EXP-{expense.pk}", source="expense", user=user,
        date=expense.date, memo=expense.description,
        lines=[(expense.expense_account, expense.amount, ZERO, expense.description),
               (expense.paid_from, ZERO, expense.amount, expense.description)])
    expense.status, expense.approved_by = "approved", user
    expense.save(update_fields=["journal_entry", "status", "approved_by", "updated_at"])
    return expense


@transaction.atomic
def post_cash_movement(cm):
    org = cm.from_branch.organization
    entry = JournalEntry.objects.create(organization=org, branch=cm.from_branch, date=cm.date,
                                        reference=f"CM-{cm.pk}", source="cash_movement", posted_by=cm.created_by,
                                        memo=cm.description or "Cash movement")
    JournalLine.objects.bulk_create([
        JournalLine(entry=entry, account=cm.to_account, branch=cm.to_branch, debit=cm.amount,
                    description=cm.reference),
        JournalLine(entry=entry, account=cm.from_account, branch=cm.from_branch, credit=cm.amount,
                    description=cm.reference),
    ])
    cm.journal_entry = entry
    cm.save(update_fields=["journal_entry", "updated_at"])
    return entry


def trial_balance(organization, branch=None, date_to=None):
    qs = JournalLine.objects.filter(entry__organization=organization)
    if branch is not None:
        qs = qs.filter(branch=branch)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    rows = (qs.values("account__code", "account__name", "account__type")
            .annotate(debit=Sum("debit"), credit=Sum("credit")).order_by("account__code"))
    out = []
    for r in rows:
        bal = (r["debit"] or ZERO) - (r["credit"] or ZERO)
        out.append({"code": r["account__code"], "name": r["account__name"], "type": r["account__type"],
                    "debit": bal if bal > 0 else ZERO, "credit": -bal if bal < 0 else ZERO})
    return out
