from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.models import audit

from .models import StockLevel, StockMovement, StockTransfer


class InsufficientStock(Exception):
    def __init__(self, product, available, requested):
        self.product, self.available, self.requested = product, available, requested
        super().__init__(f"Only {available} of {product.name} in stock; {requested} requested.")


def move_stock(*, branch, product, quantity, kind, user=None, unit_cost=None, reference="", note="",
               allow_negative=None) -> StockMovement:
    """The only way stock changes. Locks the StockLevel row so concurrent tills cannot oversell.

    Must be called inside transaction.atomic().
    """
    quantity = Decimal(quantity)
    level, _ = StockLevel.objects.get_or_create(branch=branch, product=product,
                                                defaults={"avg_cost": product.cost_price})
    level = StockLevel.objects.select_for_update().get(pk=level.pk)
    new_qty = level.quantity + quantity
    if allow_negative is None:
        allow_negative = branch.allow_negative_stock
    if quantity < 0 and new_qty < 0 and not allow_negative:
        raise InsufficientStock(product, level.quantity, -quantity)

    if quantity > 0 and unit_cost is not None and kind in ("purchase", "transfer_in", "opening"):
        # Weighted average cost, only on stock coming in at a known cost.
        on_hand = max(level.quantity, Decimal("0"))
        total = on_hand * level.avg_cost + quantity * Decimal(unit_cost)
        level.avg_cost = (total / (on_hand + quantity)).quantize(Decimal("0.0001"))

    level.quantity = new_qty
    level.save(update_fields=["quantity", "avg_cost", "updated_at"])
    return StockMovement.objects.create(
        branch=branch, product=product, kind=kind, quantity=quantity,
        unit_cost=unit_cost if unit_cost is not None else level.avg_cost,
        balance_after=new_qty, reference=reference, note=note, user=user,
    )


def current_cost(branch, product) -> Decimal:
    level = StockLevel.objects.filter(branch=branch, product=product).first()
    return level.avg_cost if level and level.avg_cost else product.cost_price


@transaction.atomic
def adjust_stock(*, branch, product, counted_quantity, user, reason):
    """Stock take: set the on-hand quantity to what was physically counted."""
    level, _ = StockLevel.objects.get_or_create(branch=branch, product=product)
    diff = Decimal(counted_quantity) - level.quantity
    if diff == 0:
        return None
    mv = move_stock(branch=branch, product=product, quantity=diff, kind="adjustment", user=user,
                    note=reason, allow_negative=True)
    audit("inventory.adjust", organization=branch.organization, branch=branch, actor=user, obj=mv,
          product=product.sku, difference=str(diff), reason=reason)
    from apps.accounting.services import post_stock_adjustment
    post_stock_adjustment(mv)
    return mv


@transaction.atomic
def send_transfer(transfer: StockTransfer, user):
    if transfer.status != "draft":
        raise ValueError("Only draft transfers can be sent.")
    for line in transfer.lines.select_related("product"):
        line.unit_cost = current_cost(transfer.from_branch, line.product)
        line.save(update_fields=["unit_cost"])
        move_stock(branch=transfer.from_branch, product=line.product, quantity=-line.quantity,
                   kind="transfer_out", user=user, reference=transfer.number)
    transfer.status = "sent"
    transfer.save(update_fields=["status", "updated_at"])


@transaction.atomic
def receive_transfer(transfer: StockTransfer, user):
    if transfer.status != "sent":
        raise ValueError("Only transfers in transit can be received.")
    for line in transfer.lines.select_related("product"):
        move_stock(branch=transfer.to_branch, product=line.product, quantity=line.quantity,
                   kind="transfer_in", user=user, unit_cost=line.unit_cost, reference=transfer.number)
    transfer.status = "received"
    transfer.received_by = user
    transfer.save(update_fields=["status", "received_by", "updated_at"])


@transaction.atomic
def receive_purchase(order, user, quantities: dict):
    """quantities: {line_id: qty_received_now}."""
    from apps.accounting.services import post_goods_received

    total_cost = Decimal("0")
    for line in order.lines.model.objects.filter(order=order).select_related("product").select_for_update():
        qty = Decimal(str(quantities.get(line.id, quantities.get(str(line.id), 0))))
        if qty <= 0:
            continue
        if line.received_quantity + qty > line.quantity:
            raise ValueError(f"Receiving more {line.product.name} than ordered.")
        move_stock(branch=order.branch, product=line.product, quantity=qty, kind="purchase", user=user,
                   unit_cost=line.unit_cost, reference=order.number)
        line.received_quantity += qty
        line.save(update_fields=["received_quantity"])
        total_cost += qty * line.unit_cost
    lines = list(order.lines.model.objects.filter(order=order))  # not order.lines: may be a stale prefetch
    order.status = "received" if all(l.received_quantity >= l.quantity for l in lines) else "partial"
    order.save(update_fields=["status", "updated_at"])
    if total_cost:
        post_goods_received(order, total_cost, user, timezone.now())
    return total_cost
