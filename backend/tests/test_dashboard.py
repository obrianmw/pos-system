import pytest

from .conftest import sale_body

pytestmark = pytest.mark.django_db


def test_owner_sees_all_branches_and_today_totals(demo, open_session, client_for):
    c, _ = open_session()
    c.post("/api/sales/", sale_body(demo, 2), format="json")
    d = client_for("owner").get("/api/reports/dashboard/?days=7").data
    assert d["sales"]["today"]["total"] == 11000 and d["sales"]["today"]["count"] == 1
    assert len(d["sales"]["trend"]) == 7 and d["sales"]["trend"][-1]["total"] == 11000
    assert {b["name"] for b in d["sales"]["by_branch"]} == {"Lilongwe City Centre", "Blantyre Limbe"}
    assert d["sales"]["by_method"][0]["name"] == "Cash"
    assert {"needs_review", "low_stock", "pending_overrides", "pending_expenses", "pending_leave"} <= set(d["alerts"])


def test_branch_scoping(demo, open_session, client_for):
    c, _ = open_session()
    c.post("/api/sales/", sale_body(demo, 2), format="json")
    bt = client_for("bt_super").get("/api/reports/dashboard/").data
    assert bt["sales"]["today"]["count"] == 0
    assert [b["name"] for b in bt["sales"]["by_branch"]] == ["Blantyre Limbe"]
    # Store keeper: stock alerts only, no money.
    store = client_for("ll_store").get("/api/reports/dashboard/").data
    assert store["sales"] is None and "low_stock" in store["alerts"]
    # HR sees leave only.
    hr = client_for("hr").get("/api/reports/dashboard/").data
    assert hr["sales"] is None and set(hr["alerts"]) == {"pending_leave"}


def test_cashier_has_no_dashboard(demo, client_for):
    assert client_for("ll_cash1").get("/api/reports/dashboard/").status_code == 403


def test_mark_reviewed(demo, open_session, client_for):
    c, sid = open_session()
    body = sale_body(demo, 1, 4500, override={"supervisor": "ll_super", "pin": "9999"}, till_session=sid)
    c.post("/api/sales/sync/", {"sales": [body]}, format="json")
    from apps.sales.models import Sale
    sale = Sale.objects.get(needs_review=True)
    assert c.post(f"/api/sales/{sale.pk}/mark_reviewed/", {"note": "ok"}, format="json").status_code == 403
    sup = client_for("ll_super")
    assert sup.post(f"/api/sales/{sale.pk}/mark_reviewed/", {}, format="json").status_code == 400
    r = sup.post(f"/api/sales/{sale.pk}/mark_reviewed/", {"note": "manager confirmed price"}, format="json")
    assert r.status_code == 200 and r.data["needs_review"] is False


def test_trend_comparison_and_heatmap(demo, open_session, client_for):
    c, _ = open_session()
    c.post("/api/sales/", sale_body(demo, 2), format="json")
    d = client_for("owner").get("/api/reports/dashboard/?days=7").data["sales"]
    assert all("prev_total" in t for t in d["trend"])
    assert d["period_total"] == 11000 and d["prev_period_total"] == 0
    assert len(d["heatmap"]) == 1 and d["heatmap"][0]["count"] == 1
    assert 0 <= d["heatmap"][0]["weekday"] <= 6 and 0 <= d["heatmap"][0]["hour"] <= 23
