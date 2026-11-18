"""POS business rules: checkout, supervisor overrides, payments, void, refund and till sessions."""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.accounting import services as ledger
from apps.accounts.models import User
from apps.catalog.models import Product
from apps.core.models import audit, next_number
from apps.inventory.services import InsufficientStock, current_cost, move_stock
from apps.payments.models import Payment, PaymentMethod
from apps.payments.providers import ProviderError, get_provider

from .models import Customer, OverrideApproval, Sale, SaleLine, TillSession

ZERO = Decimal("0")
CENTS = Decimal("0.01")


class POSError(Exception):
    code = "pos_error"

    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


class OverrideRequired(POSError):
    code = "override_required"


class PermissionDenied(POSError):
    code = "permission_denied"


def q(x) -> Decimal:
    return Decimal(str(x)).quantize(CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------------------------
# Supervisor overrides
# ---------------------------------------------------------------------------------------------
KIND_PERMISSION = {"price": "pos.price_override", "discount": "pos.discount_override",
                   "void": "pos.void", "refund": "pos.refund"}


def authorize_override(*, kind, branch, user, auth, product=None, original=None, new=None, reason=""):
    """Return an approved OverrideApproval, or raise OverrideRequired.

    `auth` is one of:
      None                                   -> only works if `user` holds the permission
      {"approval_id": 12}                    -> a remote approval a supervisor already granted
      {"supervisor": "jdoe", "pin": "1234"}  -> supervisor PIN typed at the till
    """
    perm = KIND_PERMISSION[kind]
    auth = auth or {}
    common = dict(branch=branch, kind=kind, requested_by=user, product=product, original_value=original,
                  new_value=new, reason=reason or auth.get("reason", ""), decided_at=timezone.now())

    if user.has_branch_perm(branch, perm):
        return OverrideApproval.objects.create(status="used", method="self", approved_by=user, **common)

    if auth.get("approval_id"):
        appr = (OverrideApproval.objects.select_for_update()
                .filter(pk=auth["approval_id"], branch=branch, kind=kind, status="approved").first())
        if not appr:
            raise OverrideRequired("Approval not found, not approved, or already used.")
        if product is not None and appr.product_id != product.pk:
            raise OverrideRequired("Approval was granted for a different product.")
        if new is not None and appr.new_value is not None and q(new) != q(appr.new_value):
            raise OverrideRequired("Approved value does not match.")
        appr.status = "used"
        appr.save(update_fields=["status", "updated_at"])
        return appr

    if auth.get("supervisor") and auth.get("pin"):
        sup = User.objects.filter(username=auth["supervisor"], organization=branch.organization,
                                  is_active=True).first()
        if not sup or not sup.check_supervisor_pin(str(auth["pin"])) or not sup.has_branch_perm(branch, perm):
            audit("override.pin_failed", organization=branch.organization, branch=branch, actor=user,
                  kind=kind, supervisor=auth.get("supervisor"))
            raise OverrideRequired("Supervisor PIN invalid or supervisor lacks permission.")
        return OverrideApproval.objects.create(status="used", method="pin", approved_by=sup, **common)

    raise OverrideRequired(f"Supervisor approval needed: {dict(OverrideApproval.KIND)[kind]}.", kind=kind,
                           product=getattr(product, "pk", None), original=str(original), new=str(new))


def request_override(*, branch, user, kind, reason, product=None, original=None, new=None):
    appr = OverrideApproval.objects.create(branch=branch, kind=kind, requested_by=user, product=product,
                                           original_value=original, new_value=new, reason=reason,
                                           status="pending", method="remote")
    audit("override.requested", organization=branch.organization, branch=branch, actor=user, obj=appr)
    return appr


@transaction.atomic
def decide_override(approval, supervisor, approve: bool):
    approval = OverrideApproval.objects.select_for_update().get(pk=approval.pk)
    if approval.status != "pending":
        raise POSError("Request already decided.")
    if not supervisor.has_branch_perm(approval.branch, KIND_PERMISSION[approval.kind]):
        raise PermissionDenied("You cannot approve this kind of request.")
    if supervisor.pk == approval.requested_by_id:
        raise PermissionDenied("You cannot approve your own request.")
    approval.status = "approved" if approve else "rejected"
    approval.approved_by = supervisor
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "approved_by", "decided_at", "updated_at"])
    audit(f"override.{approval.status}", organization=approval.branch.organization, branch=approval.branch,
          actor=supervisor, obj=approval)
    return approval


# ---------------------------------------------------------------------------------------------
# Till sessions
# ---------------------------------------------------------------------------------------------
def open_till(*, till, user, opening_float):
    if not user.has_branch_perm(till.branch, "pos.open_till"):
        raise PermissionDenied("You cannot open a till at this branch.")
    try:
        with transaction.atomic():
            session = TillSession.objects.create(till=till, branch=till.branch, cashier=user,
                                                 opening_float=q(opening_float))
    except IntegrityError:
        raise POSError("This till already has an open session.")
    audit("till.open", organization=till.branch.organization, branch=till.branch, actor=user, obj=session,
          opening_float=str(session.opening_float))
    return session


def expected_cash(session) -> Decimal:
    def cash_sum(kind):
        return (Payment.objects.filter(sale__till_session=session, sale__kind=kind, status="confirmed",
                                       method__kind="cash", sale__status="completed")
                .aggregate(s=Sum("amount"))["s"] or ZERO)
    return session.opening_float + cash_sum("sale") - cash_sum("refund")


@transaction.atomic
def close_till(session, *, user, counted_cash, notes=""):
    session = TillSession.objects.select_for_update().get(pk=session.pk)
    if session.status != "open":
        raise POSError("Session already closed.")
    if session.cashier_id != user.pk and not user.has_branch_perm(session.branch, "accounting.reconcile") \
            and not user.has_branch_perm(session.branch, "pos.view_all_sales"):
        raise PermissionDenied("Only the cashier or a supervisor/accountant can close this till.")
    if session.sales.filter(status="pending_payment").exists():
        raise POSError("Finish or cancel sales awaiting payment before closing.")
    session.expected_cash = expected_cash(session)
    session.counted_cash = q(counted_cash)
    session.variance = session.counted_cash - session.expected_cash
    session.status, session.closed_at, session.closed_by, session.notes = "closed", timezone.now(), user, notes
    session.save()
    ledger.post_till_variance(session, user)
    audit("till.close", organization=session.branch.organization, branch=session.branch, actor=user,
          obj=session, expected=str(session.expected_cash), counted=str(session.counted_cash),
          variance=str(session.variance))
    return session


# ---------------------------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------------------------
def _price_line(line, product, tax_rate, tax_inclusive):
    gross = q(line.quantity * line.unit_price) - line.discount_amount
    if tax_inclusive:
        tax = q(gross * tax_rate / (100 + tax_rate)) if tax_rate else ZERO
        total = gross
    else:
        tax = q(gross * tax_rate / 100)
        total = gross + tax
    line.tax_amount, line.line_total = tax, total


def checkout(*, user, session, data):
    """Create (or, for a re-sent offline sale, return) a sale.

    data = {
      "client_uuid": "...", "number": optional, "customer_id": optional, "offline": bool,
      "client_created_at": iso, "note": "",
      "lines": [{"product_id", "quantity", "unit_price"?, "discount_amount"?, "override"?}],
      "payments": [{"method_id", "amount", "tendered"?, "reference"?, "phone"?}],
    }
    Returns (sale, created: bool).

    Online, rule violations raise. Offline (sale already happened at the counter) the sale is kept and
    flagged needs_review instead, so stock and money still reconcile.
    """
    if data.get("client_uuid"):
        existing = Sale.objects.filter(client_uuid=data["client_uuid"]).first()
        if existing:
            return existing, False

    branch = session.branch
    offline = bool(data.get("offline"))
    if session.status != "open" and not offline:
        raise POSError("Till session is closed.")
    if not user.has_branch_perm(branch, "pos.sell"):
        raise PermissionDenied("You cannot sell at this branch.")
    if not data.get("lines"):
        raise POSError("A sale needs at least one line.")

    review = []
    electronic = []
    with transaction.atomic():
        number = data.get("number")
        if number and Sale.objects.filter(number=number).exists():
            # A till whose local counter was reset re-used a receipt number; keep the sale, renumber it.
            review.append(f"Offline receipt number {number} already used; renumbered")
            number = None
        number = number or next_number(f"sale:{branch.pk}", f"{branch.code.upper()}-", 7)
        sale = Sale.objects.create(
            organization=branch.organization, branch=branch, till_session=session, cashier=user,
            customer=Customer.objects.filter(pk=data.get("customer_id"), organization=branch.organization).first()
            if data.get("customer_id") else None,
            number=number, client_uuid=data.get("client_uuid") or uuid.uuid4(),
            currency=branch.organization.currency, created_offline=offline, note=data.get("note", "")[:255],
            client_created_at=parse_datetime(data["client_created_at"]) if data.get("client_created_at") else None,
        )

        for raw in data["lines"]:
            product = Product.objects.filter(pk=raw["product_id"], organization=branch.organization,
                                             is_active=True).select_related("tax_rate").first()
            if not product:
                raise POSError(f"Unknown product {raw['product_id']}")
            qty = Decimal(str(raw["quantity"]))
            if qty <= 0:
                raise POSError("Quantity must be positive.")
            list_price = product.price_at(branch)
            unit_price = q(raw.get("unit_price", list_price))
            discount = q(raw.get("discount_amount", 0))
            line = SaleLine(sale=sale, product=product, description=product.name, quantity=qty,
                            list_price=list_price, unit_price=unit_price, discount_amount=discount,
                            tax_rate=product.tax_rate.rate if product.tax_rate else ZERO,
                            tax_inclusive=product.tax_rate.inclusive if product.tax_rate else True,
                            unit_cost=current_cost(branch, product))

            if product.min_price is not None and unit_price < product.min_price:
                if not offline:
                    raise POSError(f"{product.name}: price below the floor price {product.min_price}.")
                review.append(f"{product.name} sold below floor price")

            gross = q(qty * unit_price)
            discount_pct = (discount / gross * 100) if gross else ZERO
            needs = []
            if unit_price != list_price:
                needs.append(("price", list_price, unit_price))
            if discount and discount_pct > branch.max_cashier_discount_pct:
                needs.append(("discount", ZERO, discount))
            for kind, orig, new in needs:
                try:
                    line.override = authorize_override(kind=kind, branch=branch, user=user, product=product,
                                                       original=orig, new=new, auth=raw.get("override"))
                except OverrideRequired:
                    if not offline:
                        raise
                    review.append(f"{product.name}: {kind} override not verified")

            _price_line(line, product, line.tax_rate, line.tax_inclusive)
            line.save()
            if line.override_id:
                OverrideApproval.objects.filter(pk=line.override_id).update(sale=sale)
            if product.track_stock:
                try:
                    move_stock(branch=branch, product=product, quantity=-qty, kind="sale", user=user,
                               reference=sale.number, unit_cost=line.unit_cost,
                               allow_negative=True if offline else None)
                except InsufficientStock as e:
                    raise POSError(str(e))

        lines = list(sale.lines.all())
        sale.subtotal = sum((q(l.quantity * l.unit_price) for l in lines), ZERO)
        sale.discount_total = sum((l.discount_amount for l in lines), ZERO)
        sale.tax_total = sum((l.tax_amount for l in lines), ZERO)
        sale.total = sum((l.line_total for l in lines), ZERO)

        pay_total = ZERO
        for raw in data.get("payments", []):
            method = PaymentMethod.objects.filter(pk=raw["method_id"], organization=branch.organization).first()
            if not method or not method.available_at(branch):
                raise POSError("Payment method not available at this branch.")
            amount = q(raw["amount"])
            if amount <= 0:
                raise POSError("Payment amounts must be positive.")
            if method.requires_reference and not raw.get("reference"):
                raise POSError(f"{method.name} needs a transaction/slip reference.")
            tendered = q(raw["tendered"]) if raw.get("tendered") not in (None, "") else None
            if tendered is not None and tendered < amount:
                raise POSError("Cash tendered is less than the amount.")
            p = Payment.objects.create(sale=sale, method=method, amount=amount, tendered=tendered,
                                       provider_reference=raw.get("reference", ""), received_by=user,
                                       payer_phone=raw.get("phone", ""))
            pay_total += amount
            if method.provider == "manual":
                p.status, p.confirmed_at = "confirmed", timezone.now()
                p.save(update_fields=["status", "confirmed_at", "updated_at"])
            elif offline:
                p.status = "confirmed"
                p.save(update_fields=["status", "updated_at"])
                review.append(f"{method.name} payment taken offline; verify with provider statement")
            else:
                electronic.append(p)

        if pay_total != sale.total:
            if not offline:
                raise POSError(f"Payments ({pay_total}) must equal the sale total ({sale.total}).",
                               total=str(sale.total))
            review.append(f"Payments {pay_total} != total {sale.total}")

        if review:
            sale.needs_review, sale.review_reason = True, "\n".join(review)
        sale.save()
        audit("sale.created", organization=branch.organization, branch=branch, actor=user, obj=sale,
              total=str(sale.total), offline=offline, needs_review=sale.needs_review)

    # Talk to wallets/gateways only after the stock + sale rows are committed and unlocked.
    for p in electronic:
        start_payment(p)
    try_finalize(sale, user)
    sale.refresh_from_db()
    return sale, True


def start_payment(payment):
    try:
        result = get_provider(payment.method).initiate(payment)
    except Exception as e:  # ProviderError, network errors ... the sale stays payable by other means
        Payment.objects.filter(pk=payment.pk).update(status="failed", message=str(e)[:255])
        return
    _apply_result(payment, result)


def _apply_result(payment, result):
    payment.status = result.status if result.status in ("pending", "confirmed", "failed") else "pending"
    payment.provider_reference = result.provider_reference or payment.provider_reference
    payment.message = (result.message or "")[:255]
    payment.checkout_url = result.checkout_url or payment.checkout_url
    payment.raw_response = result.raw or payment.raw_response
    if payment.status == "confirmed":
        payment.confirmed_at = timezone.now()
    payment.save()


def refresh_payment(payment, user=None):
    """Ask the provider for the real status (used by callbacks and the POS 'check' button)."""
    if payment.status != "pending":
        return payment
    try:
        result = get_provider(payment.method).check_status(payment)
    except ProviderError as e:
        payment.message = str(e)[:255]
        payment.save(update_fields=["message", "updated_at"])
        return payment
    _apply_result(payment, result)
    try_finalize(payment.sale, user)
    return payment


@transaction.atomic
def try_finalize(sale, user=None):
    """Complete the sale once confirmed payments cover the total. Safe to call repeatedly."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != "pending_payment":
        return sale
    if sale.paid_total < sale.total and not sale.needs_review:
        return sale
    sale.status, sale.completed_at = "completed", timezone.now()
    sale.save(update_fields=["status", "completed_at", "updated_at"])
    if sale.kind == "sale":
        ledger.post_sale(sale, user)
    else:
        ledger.post_refund(sale, user)
    return sale


@transaction.atomic
def add_payment(sale, *, user, method_id, amount, phone="", reference="", tendered=None):
    """Replace a failed wallet payment with another method on a sale still awaiting payment."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != "pending_payment":
        raise POSError("Sale is not awaiting payment.")
    outstanding = sale.total - sum((p.amount for p in sale.payments.filter(status__in=["pending", "confirmed"])), ZERO)
    amount = q(amount)
    if amount <= 0 or amount > outstanding:
        raise POSError(f"Amount must be between 0 and the outstanding {outstanding}.")
    method = PaymentMethod.objects.get(pk=method_id, organization=sale.organization)
    p = Payment.objects.create(sale=sale, method=method, amount=amount, payer_phone=phone,
                               provider_reference=reference, received_by=user,
                               tendered=q(tendered) if tendered else None)
    if method.provider == "manual":
        p.status, p.confirmed_at = "confirmed", timezone.now()
        p.save()
        try_finalize(sale, user)
    else:
        transaction.on_commit(lambda: (start_payment(p), try_finalize(sale, user)))
    return p


@transaction.atomic
def cancel_pending_sale(sale, user, reason=""):
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != "pending_payment":
        raise POSError("Only sales awaiting payment can be cancelled.")
    if sale.payments.filter(status="confirmed").exclude(method__provider="manual").exists():
        raise POSError("A wallet/card payment already succeeded; refund it instead.")
    for line in sale.lines.select_related("product"):
        if line.product.track_stock:
            move_stock(branch=sale.branch, product=line.product, quantity=line.quantity, kind="void",
                       user=user, reference=sale.number, unit_cost=line.unit_cost, note="cancelled")
    sale.payments.filter(status="pending").update(status="cancelled")
    sale.status = "cancelled"
    sale.save(update_fields=["status", "updated_at"])
    audit("sale.cancelled", organization=sale.organization, branch=sale.branch, actor=user, obj=sale, reason=reason)
    return sale


@transaction.atomic
def void_sale(sale, *, user, reason, auth=None):
    """Reverse a completed sale completely (wrong items rung up, same-day mistakes)."""
    sale = Sale.objects.select_for_update().get(pk=sale.pk)
    if sale.status != "completed" or sale.kind != "sale":
        raise POSError("Only completed sales can be voided.")
    if sale.refunds.exists():
        raise POSError("Sale has refunds; refund the remaining items instead.")
    appr = authorize_override(kind="void", branch=sale.branch, user=user, auth=auth, original=sale.total,
                              new=ZERO, reason=reason)
    appr.sale = sale
    appr.save(update_fields=["sale"])
    for line in sale.lines.select_related("product"):
        if line.product.track_stock:
            move_stock(branch=sale.branch, product=line.product, quantity=line.quantity, kind="void",
                       user=user, reference=sale.number, unit_cost=line.unit_cost, note=reason)
    entry = sale.branch.organization.journal_entries.filter(reference=sale.number, source="sale").first()
    if entry:
        ledger.reverse_entry(entry, user, memo=f"Void {sale.number}: {reason}")
    sale.payments.filter(status="confirmed").update(status="refunded")
    sale.status = "voided"
    sale.save(update_fields=["status", "updated_at"])
    audit("sale.voided", organization=sale.organization, branch=sale.branch, actor=user, obj=sale,
          reason=reason, approved_by=appr.approved_by_id)
    return sale


def refund(original, *, user, session, lines, method_id, reason, auth=None):
    """Customer return. lines: [{"line_id", "quantity"}]. Money goes back via a manual method."""
    if original.status != "completed" or original.kind != "sale":
        raise POSError("Only completed sales can be refunded.")
    with transaction.atomic():
        appr = authorize_override(kind="refund", branch=session.branch, user=user, auth=auth, reason=reason)
        method = PaymentMethod.objects.get(pk=method_id, organization=original.organization)
        if method.provider != "manual":
            raise POSError("Refund wallet/card payments through the provider, then record them as manual.")
        r = Sale.objects.create(
            organization=original.organization, branch=session.branch, till_session=session, cashier=user,
            customer=original.customer, kind="refund", original_sale=original, currency=original.currency,
            number=next_number(f"refund:{session.branch.pk}", f"{session.branch.code.upper()}-R", 6),
            note=reason[:255])
        appr.sale = r
        appr.save(update_fields=["sale"])
        for raw in lines:
            ol = original.lines.select_related("product").get(pk=raw["line_id"])
            qty = Decimal(str(raw["quantity"]))
            already = sum((l.quantity for l in ol.refund_lines.filter(sale__status="completed")), ZERO)
            if qty <= 0 or already + qty > ol.quantity:
                raise POSError(f"Cannot return {qty} of {ol.description}; {ol.quantity - already} returnable.")
            ratio = qty / ol.quantity
            line = SaleLine.objects.create(
                sale=r, product=ol.product, description=ol.description, quantity=qty, list_price=ol.list_price,
                unit_price=ol.unit_price, discount_amount=q(ol.discount_amount * ratio), tax_rate=ol.tax_rate,
                tax_inclusive=ol.tax_inclusive, tax_amount=q(ol.tax_amount * ratio),
                line_total=q(ol.line_total * ratio), unit_cost=ol.unit_cost, original_line=ol, override=appr)
            if ol.product.track_stock:
                move_stock(branch=session.branch, product=ol.product, quantity=qty, kind="refund", user=user,
                           reference=r.number, unit_cost=ol.unit_cost)
        rl = list(r.lines.all())
        r.subtotal = sum((q(l.quantity * l.unit_price) for l in rl), ZERO)
        r.discount_total = sum((l.discount_amount for l in rl), ZERO)
        r.tax_total = sum((l.tax_amount for l in rl), ZERO)
        r.total = sum((l.line_total for l in rl), ZERO)
        r.save()
        Payment.objects.create(sale=r, method=method, amount=r.total, status="confirmed",
                               confirmed_at=timezone.now(), received_by=user)
        audit("sale.refund", organization=r.organization, branch=r.branch, actor=user, obj=r,
              original=original.number, total=str(r.total), approved_by=appr.approved_by_id)
        try_finalize(r, user)
    r.refresh_from_db()
    return r
