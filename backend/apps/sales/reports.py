"""Back-office dashboard numbers, scoped to what the caller may see.

Sales figures cover branches where the user has pos.view_all_sales or accounting.view.
Alert counts appear only for the areas the user is responsible for (stock, approvals,
expenses, leave), so a cashier-supervisor and a head-office accountant get different boards.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounting.models import Expense
from apps.core.api import branches_with
from apps.hr.api import hr_scope
from apps.hr.models import Employee, LeaveRequest
from apps.inventory.models import StockLevel
from apps.payments.models import Payment

from .models import OverrideApproval, Sale, SaleLine, TillSession

ZERO = Decimal("0")


def _ids(user, code, only=None):
    ids = {b.pk for b in branches_with(user, code)}
    return ids & {only} if only else ids


@api_view(["GET"])
def dashboard(request):
    u = request.user
    only = int(request.query_params["branch"]) if request.query_params.get("branch") else None
    days = max(1, min(int(request.query_params.get("days", 14)), 90))

    sales_ids = _ids(u, "pos.view_all_sales", only) | _ids(u, "accounting.view", only)
    stock_ids = _ids(u, "inventory.view", only)
    approve_ids = _ids(u, "pos.price_override", only)
    expense_ids = _ids(u, "accounting.reconcile", only)
    can_leave = u.has_org_perm("hr.approve_leave") or bool(branches_with(u, "hr.approve_leave"))
    if not (sales_ids or stock_ids or approve_ids or expense_ids or can_leave):
        raise PermissionDenied("Nothing on the dashboard for your role.")

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    out = {"date": today.isoformat(), "days": days, "sales": None, "alerts": {}}

    if sales_ids:
        done = Sale.objects.filter(branch__in=sales_ids, status="completed")
        period = done.filter(completed_at__date__gte=start)

        def totals(qs):
            a = qs.aggregate(total=Sum("total"), tax=Sum("tax_total"), count=Count("id"))
            return {"total": a["total"] or ZERO, "tax": a["tax"] or ZERO, "count": a["count"]}

        t_sales = totals(done.filter(kind="sale", completed_at__date=today))
        t_refunds = totals(done.filter(kind="refund", completed_at__date=today))
        y_sales = totals(done.filter(kind="sale", completed_at__date=today - timedelta(days=1)))

        by_day = {r["d"]: r for r in period.filter(kind="sale").annotate(d=TruncDate("completed_at"))
                  .values("d").annotate(total=Sum("total"), count=Count("id"))}
        refunds_by_day = {r["d"]: r["total"] for r in period.filter(kind="refund")
                          .annotate(d=TruncDate("completed_at")).values("d").annotate(total=Sum("total"))}
        trend = []
        for i in range(days):
            d = start + timedelta(days=i)
            r = by_day.get(d, {})
            trend.append({"date": d.isoformat(), "total": r.get("total") or ZERO, "count": r.get("count") or 0,
                          "refunds": refunds_by_day.get(d) or ZERO})

        # Same-length period just before, for the dashed comparison line.
        prev_start = start - timedelta(days=days)
        prev = {r["d"]: r["total"] for r in done.filter(kind="sale", completed_at__date__gte=prev_start,
                                                        completed_at__date__lt=start)
                .annotate(d=TruncDate("completed_at")).values("d").annotate(total=Sum("total"))}
        for i, t in enumerate(trend):
            t["prev_total"] = prev.get(prev_start + timedelta(days=i)) or ZERO

        # Busiest times: weekday (0=Mon) x hour, over the period, in the shop's time zone.
        heat = (period.filter(kind="sale").annotate(wd=ExtractIsoWeekDay("completed_at"), hr=ExtractHour("completed_at"))
                .values("wd", "hr").annotate(count=Count("id"), total=Sum("total")))
        heatmap = [{"weekday": r["wd"] - 1, "hour": r["hr"], "count": r["count"], "total": r["total"]} for r in heat]

        by_branch = list(done.filter(kind="sale", completed_at__date=today)
                         .values("branch_id", name=F("branch__name"))
                         .annotate(total=Sum("total"), count=Count("id")).order_by("-total"))
        seen = {r["branch_id"] for r in by_branch}
        from apps.core.models import Branch
        by_branch += [{"branch_id": b.pk, "name": b.name, "total": ZERO, "count": 0}
                      for b in Branch.objects.filter(pk__in=sales_ids - seen, is_active=True)]

        by_method = list(Payment.objects.filter(sale__in=done.filter(kind="sale", completed_at__date=today),
                                                status="confirmed")
                         .values(name=F("method__name")).annotate(total=Sum("amount")).order_by("-total"))
        top = list(SaleLine.objects.filter(sale__in=period.filter(kind="sale"))
                   .values(name=F("product__name")).annotate(qty=Sum("quantity"), total=Sum("line_total"))
                   .order_by("-total")[:8])

        out["sales"] = {
            "today": {**t_sales, "avg_basket": (t_sales["total"] / t_sales["count"]).quantize(Decimal("0.01"))
                      if t_sales["count"] else ZERO,
                      "refunds_total": t_refunds["total"], "refunds_count": t_refunds["count"],
                      "net": t_sales["total"] - t_refunds["total"]},
            "yesterday_total": y_sales["total"],
            "trend": trend, "heatmap": heatmap, "by_branch": by_branch, "by_method": by_method, "top_products": top,
            "period_total": sum((t["total"] for t in trend), ZERO),
            "prev_period_total": sum((t["prev_total"] for t in trend), ZERO),
        }
        out["alerts"]["needs_review"] = Sale.objects.filter(branch__in=sales_ids, needs_review=True).count()
        out["alerts"]["open_tills"] = TillSession.objects.filter(branch__in=sales_ids, status="open").count()
    if stock_ids:
        out["alerts"]["low_stock"] = StockLevel.objects.filter(
            branch__in=stock_ids, product__track_stock=True, quantity__lte=F("product__reorder_level")).count()
    if approve_ids:
        out["alerts"]["pending_overrides"] = OverrideApproval.objects.filter(branch__in=approve_ids,
                                                                             status="pending").count()
    if expense_ids:
        out["alerts"]["pending_expenses"] = Expense.objects.filter(branch__in=expense_ids, status="pending").count()
    if can_leave:
        visible = Employee.objects.filter(hr_scope(u, "hr.approve_leave")).values("pk")
        out["alerts"]["pending_leave"] = LeaveRequest.objects.filter(employee__in=visible, status="pending").count()
    return Response(out)
