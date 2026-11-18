"""Who receives a message, and who may send to whom.

Audience = any mix of {"users", "departments", "groups", "branches", "roles"} id lists, or "everyone".

Scope rules
- comms.broadcast (org-wide): anyone in the organization, including "everyone".
- comms.send held org-wide: anyone in the organization, but not "everyone" in one click.
- comms.send at some branches: only people who work at those branches. Naming an individual outside
  that is refused; a department/group/role that also covers other branches is trimmed to your branches
  and the response says how many were left out.
- Replies: anyone may reply to a message they received; the reply goes only to its sender.
"""
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Membership, Role, User
from apps.core.api import branches_with
from apps.core.models import Branch, audit
from apps.hr.models import Department, Employee

from .models import Message, MessageRecipient, StaffGroup

KEYS = ("users", "departments", "groups", "branches", "roles")


class AudienceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def can_send(user):
    return user.has_org_perm("comms.send") or user.has_org_perm("comms.broadcast") or bool(branches_with(user, "comms.send"))


def scope_user_ids(sender):
    """None = whole organization; otherwise the set of user ids the sender may reach."""
    if sender.has_org_perm("comms.broadcast") or sender.has_org_perm("comms.send"):
        return None
    branch_ids = [b.pk for b in branches_with(sender, "comms.send")]
    return set(Membership.objects.filter(branch__in=branch_ids, is_active=True).values_list("user_id", flat=True))


def scope_branch_ids(sender):
    if sender.has_org_perm("comms.broadcast") or sender.has_org_perm("comms.send"):
        return set(Branch.objects.filter(organization=sender.organization).values_list("pk", flat=True))
    return {b.pk for b in branches_with(sender, "comms.send")}


def _ids(audience, key):
    raw = audience.get(key) or []
    try:
        return [int(x) for x in raw]
    except (TypeError, ValueError):
        raise AudienceError(f"'{key}' must be a list of ids.")


def resolve(sender, audience):
    """-> (recipient user ids, skipped_count, label). Raises AudienceError."""
    org = sender.organization
    if not can_send(sender):
        raise AudienceError("Your role cannot send messages.", 403)
    active = User.objects.filter(organization=org, is_active=True)
    scope = scope_user_ids(sender)
    branches_ok = scope_branch_ids(sender)
    picked, broad, parts = set(), set(), []

    if audience.get("everyone"):
        if not sender.has_org_perm("comms.broadcast"):
            raise AudienceError("Sending to all staff needs the broadcast permission.", 403)
        broad |= set(active.values_list("pk", flat=True))
        parts.append("All staff")

    users = _ids(audience, "users")
    if users:
        found = list(active.filter(pk__in=users))
        if len(found) != len(set(users)):
            raise AudienceError("Some people were not found or no longer have a login.")
        outside = [u for u in found if scope is not None and u.pk not in scope]
        if outside:
            names = ", ".join(u.get_full_name() or u.username for u in outside[:3])
            raise AudienceError(f"You can only message people in your branches (not: {names}).", 403)
        picked |= {u.pk for u in found}
        parts.append(", ".join(u.get_full_name() or u.username for u in found[:3]) +
                     (f" +{len(found) - 3} more" if len(found) > 3 else ""))

    deps = list(Department.objects.filter(organization=org, pk__in=_ids(audience, "departments")))
    if len(deps) != len(set(_ids(audience, "departments"))):
        raise AudienceError("Unknown department.")
    if deps:
        broad |= set(Employee.objects.filter(organization=org, department__in=deps, status="active",
                                             user__is_active=True).values_list("user_id", flat=True))
        parts += [f"{d.name} department" for d in deps]

    groups = list(StaffGroup.objects.filter(organization=org, pk__in=_ids(audience, "groups")))
    if len(groups) != len(set(_ids(audience, "groups"))):
        raise AudienceError("Unknown group.")
    for g in groups:
        broad |= set(g.members.filter(is_active=True).values_list("pk", flat=True))
        parts.append(f"{g.name} group")

    br = list(Branch.objects.filter(organization=org, pk__in=_ids(audience, "branches")))
    if len(br) != len(set(_ids(audience, "branches"))):
        raise AudienceError("Unknown branch.")
    if any(b.pk not in branches_ok for b in br):
        raise AudienceError("You can only message branches you manage.", 403)
    if br:
        broad |= set(Membership.objects.filter(branch__in=br, is_active=True, user__is_active=True)
                     .values_list("user_id", flat=True))
        parts += [f"{b.name} (all staff)" for b in br]

    roles = list(Role.objects.filter(organization=org, pk__in=_ids(audience, "roles")))
    if len(roles) != len(set(_ids(audience, "roles"))):
        raise AudienceError("Unknown role.")
    if roles:
        broad |= set(Membership.objects.filter(role__in=roles, is_active=True, user__is_active=True)
                     .values_list("user_id", flat=True))
        parts += [f"All {r.name}s" for r in roles]

    skipped = 0
    if scope is not None:
        before = len(broad - picked)
        broad &= scope
        skipped = before - len(broad - picked)
    ids = (picked | broad) - {sender.pk}
    if not parts:
        raise AudienceError("Choose who should receive it.")
    return ids, skipped, "; ".join(parts)


@transaction.atomic
def send(sender, *, subject, body, audience, kind="message", priority="normal", requires_ack=False, parent=None,
         request=None):
    subject, body = (subject or "").strip(), (body or "").strip()
    if not body:
        raise AudienceError("Write a message.")
    if kind == "announcement" and not can_send(sender):
        raise AudienceError("Your role cannot post announcements.", 403)
    if parent is not None:
        # Reply: only to the sender of a message you received.
        if not MessageRecipient.objects.filter(message=parent, user=sender).exists():
            raise AudienceError("You can only reply to messages you received.", 403)
        ids, skipped = {parent.sender_id} - {sender.pk}, 0
        label = parent.sender.get_full_name() or parent.sender.username
        subject = subject or (parent.subject if parent.subject.startswith("Re: ") else f"Re: {parent.subject}")
        kind, audience = "message", {"users": [parent.sender_id]}
    else:
        if not subject:
            raise AudienceError("Add a subject.")
        ids, skipped, label = resolve(sender, audience)
    if not ids:
        raise AudienceError("Nobody to send to: the people you picked have no active login in your scope.")
    msg = Message.objects.create(
        organization=sender.organization, sender=sender, kind=kind, priority=priority, subject=subject[:160],
        body=body, requires_ack=requires_ack, parent=parent, audience=audience, audience_label=label[:500],
        recipient_count=len(ids))
    MessageRecipient.objects.bulk_create([MessageRecipient(message=msg, user_id=i) for i in ids])
    audit("comms.sent", organization=sender.organization, actor=sender, obj=msg, kind=kind, priority=priority,
          recipients=len(ids), audience=label[:200], request=request)
    return msg, skipped


def mark(recipient, *, read=False, ack=False):
    now = timezone.now()
    fields = []
    if (read or ack) and not recipient.read_at:
        recipient.read_at = now
        fields.append("read_at")
    if ack and not recipient.acknowledged_at:
        recipient.acknowledged_at = now
        fields.append("acknowledged_at")
    if fields:
        recipient.save(update_fields=fields)
    return recipient
