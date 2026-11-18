from datetime import date

import pytest

from apps.accounts.models import Role, User
from apps.comms.models import Message, MessageRecipient
from apps.hr.models import Department, Employee

pytestmark = pytest.mark.django_db


def uid(name):
    return User.objects.get(username=name).pk


def send(c, **kw):
    body = {"subject": "Stock count Saturday", "body": "Please come in at 7am.", **kw}
    return c.post("/api/comms/compose/", body, format="json")


def test_cashier_cannot_send_but_can_read_and_reply(demo, client_for):
    cashier = client_for("ll_cash1")
    assert send(cashier, audience={"users": [uid("ll_super")]}).status_code == 403
    assert cashier.get("/api/comms/directory/").status_code == 403
    # Supervisor writes to the cashier; the cashier reads and replies.
    r = send(client_for("ll_super"), audience={"users": [uid("ll_cash1")]}, priority="urgent")
    assert r.status_code == 201 and r.data["recipient_count"] == 1
    s = cashier.get("/api/comms/inbox/summary/").data
    assert s["unread"] == 1 and s["pinned"][0]["priority"] == "urgent" and s["can_send"] is False
    item = cashier.get("/api/comms/inbox/").data["results"][0]
    assert cashier.post(f"/api/comms/inbox/{item['id']}/read/").data["read_at"]
    rep = cashier.post("/api/comms/compose/", {"parent": item["message_id"], "body": "OK, will be there"}, format="json")
    assert rep.status_code == 201, rep.data
    assert Message.objects.get(pk=rep.data["id"]).subject == "Re: Stock count Saturday"
    assert client_for("ll_super").get("/api/comms/inbox/").data["results"][0]["is_reply"] is True


def test_cannot_reply_to_someone_elses_message(demo, client_for):
    r = send(client_for("ll_super"), audience={"users": [uid("ll_cash1")]})
    assert client_for("ll_store").post("/api/comms/compose/", {"parent": r.data["id"], "body": "hi"},
                                       format="json").status_code == 403


def test_branch_scope(demo, client_for):
    sup = client_for("ll_super")
    # Blantyre people and the Blantyre branch are out of a Lilongwe supervisor's reach.
    assert send(sup, audience={"users": [uid("bt_cash1")]}).status_code == 403
    assert send(sup, audience={"branches": [demo["bt"].pk]}).status_code == 403
    assert send(sup, audience={"everyone": True}).status_code == 403
    # Directory only lists reachable people.
    names = {p["username"] for p in sup.get("/api/comms/directory/").data["people"]}
    assert "ll_cash1" in names and "bt_cash1" not in names and "ll_super" not in names
    # A role that exists in both branches is trimmed to Lilongwe, and says so.
    cashier_role = Role.objects.get(name="Cashier")
    r = send(sup, audience={"roles": [cashier_role.pk]})
    assert r.status_code == 201 and r.data["recipient_count"] == 1 and r.data["skipped"] == 1
    assert MessageRecipient.objects.get(message_id=r.data["id"]).user.username == "ll_cash1"


def test_branch_and_everyone_broadcast(demo, client_for):
    r = send(client_for("ll_admin"), audience={"branches": [demo["ll"].pk]}, kind="announcement")
    assert r.status_code == 201
    got = set(MessageRecipient.objects.filter(message_id=r.data["id"]).values_list("user__username", flat=True))
    assert got == {"ll_super", "ll_cash1", "ll_store"}  # Lilongwe staff, not the sender, not Blantyre
    # Organization HR may broadcast to everyone.
    r = send(client_for("hr"), audience={"everyone": True}, kind="announcement", requires_ack=True)
    assert r.status_code == 201
    active = User.objects.filter(is_active=True).count()
    assert r.data["recipient_count"] == active - 1  # everyone except HR themself
    assert r.data["audience_label"] == "All staff"


def test_departments_and_groups(demo, client_for):
    org = demo["ll"].organization
    shop = Department.objects.create(organization=org, name="Shop floor")
    for i, u in enumerate(["ll_cash1", "bt_cash1"]):
        Employee.objects.create(organization=org, branch=demo["ll"] if i == 0 else demo["bt"], user_id=uid(u),
                                department=shop, employee_number=f"E{i}", first_name=u, last_name="x",
                                hire_date=date(2025, 1, 1))
    hr = client_for("hr")
    r = send(hr, audience={"departments": [shop.pk]})
    assert r.data["recipient_count"] == 2 and "Shop floor department" in r.data["audience_label"]
    # A group made by the Lilongwe supervisor: only Lilongwe members allowed.
    sup = client_for("ll_super")
    assert sup.post("/api/comms/groups/", {"name": "Morning shift", "members": [uid("bt_cash1")]},
                    format="json").status_code == 400
    g = sup.post("/api/comms/groups/", {"name": "Morning shift", "members": [uid("ll_cash1"), uid("ll_store")]},
                 format="json")
    assert g.status_code == 201, g.data
    r = send(sup, audience={"groups": [g.data["id"]], "users": [uid("ll_cash1")]})  # overlap counted once
    assert r.data["recipient_count"] == 2
    # Someone else's group cannot be edited by a branch-level sender.
    assert client_for("ll_admin").patch(f"/api/comms/groups/{g.data['id']}/", {"name": "x"},
                                        format="json").status_code == 403


def test_read_receipts_and_ack(demo, client_for):
    sup = client_for("ll_super")
    r = send(sup, audience={"users": [uid("ll_cash1"), uid("ll_store")]}, requires_ack=True)
    cashier = client_for("ll_cash1")
    item = cashier.get("/api/comms/inbox/").data["results"][0]
    cashier.post(f"/api/comms/inbox/{item['id']}/ack/")
    sent = sup.get("/api/comms/sent/").data["results"][0]
    assert sent["recipient_count"] == 2 and sent["read_count"] == 1 and sent["ack_count"] == 1
    who = sup.get(f"/api/comms/sent/{r.data['id']}/recipients/").data
    assert {w["username"]: bool(w["acknowledged_at"]) for w in who} == {"ll_cash1": True, "ll_store": False}
    # Others cannot see this sent message's receipts.
    assert client_for("ll_admin").get(f"/api/comms/sent/{r.data['id']}/recipients/").status_code == 404
    # Archive moves it out of the inbox.
    cashier.post(f"/api/comms/inbox/{item['id']}/archive/")
    assert cashier.get("/api/comms/inbox/").data["count"] == 0
    assert cashier.get("/api/comms/inbox/?folder=archived").data["count"] == 1


def test_preview_and_validation(demo, client_for):
    sup = client_for("ll_super")
    p = sup.post("/api/comms/preview/", {"audience": {"branches": [demo["ll"].pk]}}, format="json").data
    assert p["count"] == 3
    assert send(sup, audience={}).status_code == 400
    assert send(sup, audience={"users": [uid("ll_cash1")]}, body="  ").status_code == 400
    assert send(sup, audience={"users": [999999]}).status_code == 400
