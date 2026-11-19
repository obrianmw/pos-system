"""Cash flow between the vault, tills, finance and the bank. Every movement is a CashTransfer with a
balanced journal entry, so the vault and till balances always come straight from the ledger."""
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.accounting import services as ledger
from apps.accounting.models import JournalLine
from apps.accounts.models import Membership
from apps.core.models import audit

from .models import CashTransfer, Vault, VaultCustody, active_custody

ZERO = Decimal("0")


class CashError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def q(x) -> Decimal:
    try:
        return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        raise CashError("Enter an amount.")


def vault_for(branch) -> Vault:
    v, _ = Vault.objects.get_or_create(branch=branch)
    return v


def vault_balance(branch) -> Decimal:
    org = branch.organization
    agg = JournalLine.objects.filter(account=ledger.acct(org, "vault"), branch=branch) \
        .aggregate(d=Sum("debit"), c=Sum("credit"))
    return q((agg["d"] or ZERO) - (agg["c"] or ZERO))


def till_balance(session) -> Decimal:
    """What should be in the drawer right now."""
    floats = session.cash_transfers.filter(kind="float").aggregate(s=Sum("amount"))["s"] or ZERO
    out = session.cash_transfers.filter(kind__in=["pickup", "close", "drop"]).aggregate(s=Sum("amount"))["s"] or ZERO
    from apps.payments.models import Payment

    def cash(kind):
        return (Payment.objects.filter(sale__till_session=session, sale__kind=kind, status="confirmed",
                                       method__kind="cash", sale__status="completed")
                .aggregate(s=Sum("amount"))["s"] or ZERO)
    # Once closed, the counted shortage/surplus has been booked to "cash over/short", so a closed till is 0.
    booked = session.variance if session.status == "closed" and session.variance is not None else ZERO
    return q(session.opening_float + floats - out + cash("sale") - cash("refund") + booked)


def end_of_today():
    return timezone.make_aware(datetime.combine(timezone.localdate(), time(23, 59, 59)))


def _require_admin(user, branch):
    if not (user.has_org_perm("org.admin") or user.has_branch_perm(branch, "branch.admin")):
        raise CashError("Only branch or organization admins assign the vault.", 403)


def _require_holder(user, branch):
    if not user.has_branch_perm(branch, "vault.operate"):
        raise CashError("Only the person holding the vault today can move vault cash.", 403)


def works_at(user, branch):
    return user.is_active and Membership.objects.filter(
        Q(branch=branch) | Q(branch__isnull=True, role__organization=branch.organization),
        user=user, is_active=True).exists()


@transaction.atomic
def assign_custody(vault, *, custodian, by, until=None, note=""):
    """Hand the vault to someone (default: until the end of today). They become the branch's
    authorizer until then. Any current holder is released."""
    _require_admin(by, vault.branch)
    if not works_at(custodian, vault.branch):
        raise CashError(f"{custodian.get_full_name() or custodian.username} doesn't work at {vault.branch.name}.")
    until = until or end_of_today()
    if until <= timezone.now():
        raise CashError("Pick a time in the future.")
    now = timezone.now()
    for c in VaultCustody.active().select_for_update().filter(vault=vault):
        c.ended_at, c.ended_by = now, by
        c.save(update_fields=["ended_at", "ended_by", "updated_at"])
    c = VaultCustody.objects.create(vault=vault, custodian=custodian, assigned_by=by, valid_until=until, note=note)
    audit("vault.assigned", organization=vault.branch.organization, branch=vault.branch, actor=by, obj=c,
          custodian=custodian.username, until=until.isoformat())
    return c


@transaction.atomic
def release_custody(vault, *, by):
    c = active_custody(vault)
    if not c:
        raise CashError("Nobody holds this vault right now.")
    if c.custodian_id != by.pk:
        _require_admin(by, vault.branch)
    c.ended_at, c.ended_by = timezone.now(), by
    c.save(update_fields=["ended_at", "ended_by", "updated_at"])
    audit("vault.released", organization=vault.branch.organization, branch=vault.branch, actor=by, obj=c,
          custodian=c.custodian.username)
    return c


# (debit account key, credit account key) for each kind
POSTINGS = {
    "float": ("cash", "vault"), "pickup": ("vault", "cash"),
    # Handed over by the cashier: in transit until the vault holder confirms (see confirm()).
    "close": ("cash_in_transit", "cash"), "drop": ("cash_in_transit", "cash"),
    "to_finance": ("cash_with_finance", "vault"), "from_finance": ("vault", "cash_with_finance"),
    "to_bank": ("bank", "vault"), "from_bank": ("vault", "bank"),
    "restock": ("accounts_payable", "vault"),
}
NEEDS_REFERENCE = {"to_bank", "from_bank", "restock"}
NEEDS_COUNTERPARTY = {"to_finance", "from_finance", "restock"}


@transaction.atomic
def move(*, branch, kind, amount, by, session=None, reference="", counterparty="", note="", system=False):
    """The single way cash moves. `system=True` is used by till closing (no holder check)."""
    if kind not in POSTINGS:
        raise CashError("Unknown kind of cash movement.")
    amount = q(amount)
    if amount <= 0:
        raise CashError("Amount must be more than zero.")
    if kind == "drop":
        if session is None or (session.cashier_id != by.pk and not system):
            raise CashError("Only the cashier on this till can hand over a cash drop.", 403)
    elif not system:
        _require_holder(by, branch)
    if kind in NEEDS_REFERENCE and not reference.strip():
        raise CashError("Enter the slip, receipt or voucher number.")
    if kind in NEEDS_COUNTERPARTY and not counterparty.strip():
        raise CashError("Say who the cash goes to or comes from.")
    vault = Vault.objects.select_for_update().get(pk=vault_for(branch).pk)
    if kind in ("float", "pickup", "close", "drop"):
        if session is None or session.branch_id != branch.pk:
            raise CashError("Choose a till at this branch.")
        if session.status != "open":
            raise CashError("That till is closed.")
    balance = vault_balance(branch)
    if kind not in CashTransfer.INTO_VAULT and amount > balance:
        raise CashError(f"The vault only has {balance:,.2f}.")
    if kind in ("pickup", "drop") and amount > till_balance(session):
        raise CashError(f"The till only holds {till_balance(session):,.2f}.")
    org = branch.organization
    dr, cr = POSTINGS[kind]
    label = dict(CashTransfer.KIND)[kind]
    t = CashTransfer.objects.create(vault=vault, branch=branch, kind=kind, amount=amount, till_session=session,
                                    reference=reference.strip(), counterparty=counterparty.strip(), note=note[:255],
                                    created_by=by,
                                    status="pending" if kind in CashTransfer.NEEDS_CONFIRMATION else "settled")
    t.journal_entry = ledger.post(
        organization=org, branch=branch, reference=f"CASH-{t.pk}", source="cash", user=by,
        memo=f"{label}{f' · {session.till.name}' if session else ''}{f' · {counterparty}' if counterparty else ''}",
        lines=[(ledger.acct(org, dr), amount, ZERO, label), (ledger.acct(org, cr), ZERO, amount, label)])
    t.vault_balance_after = vault_balance(branch)
    t.save(update_fields=["journal_entry", "vault_balance_after", "updated_at"])
    audit(f"cash.{kind}", organization=org, branch=branch, actor=by, obj=t, amount=str(amount),
          till=session.till.name if session else "", reference=reference, counterparty=counterparty)
    return t


def pending_total(branch) -> Decimal:
    return q(CashTransfer.objects.filter(branch=branch, status="pending").aggregate(s=Sum("amount"))["s"] or ZERO)


@transaction.atomic
def confirm(transfer, *, received, by, note=""):
    """The vault holder counts cash handed over from a till and confirms it. Only now does it settle in the
    vault; any difference from what the cashier declared goes to cash over/short."""
    t = CashTransfer.objects.select_for_update().select_related("branch", "till_session__till").get(pk=transfer.pk)
    if t.status != "pending":
        raise CashError("This handover has already been confirmed.")
    _require_holder(by, t.branch)
    handed_by_me = t.created_by_id == by.pk or (t.till_session and t.till_session.cashier_id == by.pk)
    if handed_by_me and not by.has_org_perm("org.admin"):
        raise CashError("You handed this cash over, so someone else has to confirm it.", 403)
    received = q(received)
    if received < 0:
        raise CashError("The amount received can't be negative.")
    note = (note or "").strip()
    diff = received - t.amount
    if diff != 0 and not note:
        raise CashError(f"The count differs by {diff:,.2f} from what was handed over. Add a note saying why.")
    org = t.branch.organization
    till = t.till_session.till.name if t.till_session else ""
    lines = [(ledger.acct(org, "cash_in_transit"), ZERO, t.amount, "Handover received")]
    if received:
        lines.append((ledger.acct(org, "vault"), received, ZERO, "Into the vault"))
    if diff < 0:
        lines.append((ledger.acct(org, "cash_over_short"), -diff, ZERO, "Short on receipt"))
    elif diff > 0:
        lines.append((ledger.acct(org, "cash_over_short"), ZERO, diff, "Over on receipt"))
    t.confirm_entry = ledger.post(organization=org, branch=t.branch, reference=f"CASH-{t.pk}-OK", source="cash",
                                  user=by, memo=f"Vault confirmed {t.get_kind_display().lower()}{f' · {till}' if till else ''}",
                                  lines=lines)
    t.status, t.received_amount, t.confirmed_by, t.confirmed_at, t.confirm_note = \
        "settled", received, by, timezone.now(), note[:255]
    t.vault_balance_after = vault_balance(t.branch)
    t.save(update_fields=["status", "received_amount", "confirmed_by", "confirmed_at", "confirm_note",
                          "confirm_entry", "vault_balance_after", "updated_at"])
    audit("cash.confirmed", organization=org, branch=t.branch, actor=by, obj=t, declared=str(t.amount),
          received=str(received), difference=str(diff), till=till, note=note)
    return t
