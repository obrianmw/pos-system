import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_sees_everything_branch_admin_only_their_branch(demo, client_for):
    from rest_framework.test import APIClient
    APIClient().post("/api/auth/token/", {"username": "ll_cash1", "password": "wrong-one"}, format="json")
    owner = client_for("owner")
    d = owner.get("/api/system/overview/").data
    assert d["scope"]["full"] and d["health"]["database"]["ok"] and "broker" in d["health"]
    assert len(d["parameters"]["branches"]) == 2 and d["parameters"]["organization"]["currency"] == "MWK"
    assert len(d["events"]["per_day"]) == 14
    assert d["operations"]["failed_sign_ins_24h"] == 1
    one = owner.get(f"/api/system/overview/?branch={demo['bt'].pk}").data
    assert one["scope"]["branch_name"] == demo["bt"].name and len(one["parameters"]["branches"]) == 1

    ll_admin = client_for("ll_admin")
    d = ll_admin.get("/api/system/overview/").data
    assert not d["scope"]["full"] and "server" not in d["health"] and "organization" not in d["parameters"]
    assert [b["code"] for b in d["parameters"]["branches"]] == ["ll"]
    assert ll_admin.get(f"/api/system/overview/?branch={demo['bt'].pk}").status_code == 403
    assert client_for("ll_cash1").get("/api/system/overview/").status_code == 403


def test_every_list_filters_by_date_and_sorts(demo, client_for, open_session):
    from datetime import date, timedelta
    from .conftest import sale_body
    c, _ = open_session()
    c.post("/api/sales/", sale_body(demo, 1), format="json")
    c.post("/api/sales/", sale_body(demo, 3), format="json")
    sup = client_for("ll_super", demo["ll"])
    today, past = date.today().isoformat(), (date.today() - timedelta(days=30)).isoformat()
    assert sup.get(f"/api/sales/?from={today}").data["count"] == 2
    assert sup.get(f"/api/sales/?to={past}").data["count"] == 0
    totals = [s["total"] for s in sup.get("/api/sales/?ordering=-total").data["results"]]
    assert totals == sorted(totals, key=float, reverse=True)
    assert sup.get(f"/api/audit-logs/?from={today}&search=sale").status_code in (200, 403)
