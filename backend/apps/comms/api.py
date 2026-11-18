from django.db.models import Count, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.models import Membership, Role, User
from apps.core.models import Branch
from apps.hr.models import Department, Employee

from . import services
from .models import Message, MessageRecipient, StaffGroup


def _name(u):
    return u.get_full_name() or u.username


class InboxSerializer(serializers.ModelSerializer):
    message_id = serializers.IntegerField(source="message.id")
    subject = serializers.CharField(source="message.subject")
    body = serializers.CharField(source="message.body")
    kind = serializers.CharField(source="message.kind")
    priority = serializers.CharField(source="message.priority")
    requires_ack = serializers.BooleanField(source="message.requires_ack")
    sent_at = serializers.DateTimeField(source="message.created_at")
    sender_name = serializers.SerializerMethodField()
    audience_label = serializers.CharField(source="message.audience_label")
    is_reply = serializers.SerializerMethodField()

    class Meta:
        model = MessageRecipient
        fields = ["id", "message_id", "subject", "body", "kind", "priority", "requires_ack", "sent_at", "sender_name",
                  "audience_label", "read_at", "acknowledged_at", "archived", "is_reply"]

    def get_sender_name(self, r):
        return _name(r.message.sender)

    def get_is_reply(self, r):
        return r.message.parent_id is not None


class SentSerializer(serializers.ModelSerializer):
    read_count = serializers.IntegerField(read_only=True)
    ack_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "subject", "body", "kind", "priority", "requires_ack", "audience_label", "recipient_count",
                  "read_count", "ack_count", "created_at", "parent"]


class InboxViewSet(viewsets.ReadOnlyModelViewSet):
    """Your own messages. ?folder=inbox (default) | archived ; ?unread=1 ; ?kind=announcement"""

    serializer_class = InboxSerializer
    search_fields = ["message__subject", "message__body"]

    def get_queryset(self):
        qs = (MessageRecipient.objects.filter(user=self.request.user)
              .select_related("message__sender").order_by("-message__created_at"))
        p = self.request.query_params
        qs = qs.filter(archived=p.get("folder") == "archived")
        if p.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        if p.get("kind") in ("message", "announcement"):
            qs = qs.filter(message__kind=p["kind"])
        return qs

    def _act(self, **kw):
        r = services.mark(self.get_object(), **kw)
        return Response(self.get_serializer(r).data)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        return self._act(read=True)

    @action(detail=True, methods=["post"])
    def ack(self, request, pk=None):
        return self._act(ack=True)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        r = MessageRecipient.objects.get(pk=pk, user=request.user)
        r.archived = request.data.get("archived", True) is not False
        r.save(update_fields=["archived"])
        return Response(self.get_serializer(r).data)

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        from django.utils import timezone
        n = MessageRecipient.objects.filter(user=request.user, read_at__isnull=True, archived=False,
                                            message__requires_ack=False).update(read_at=timezone.now())
        return Response({"marked": n})

    @action(detail=False)
    def summary(self, request):
        """For the bell icon and the urgent banner (polled every 30 s)."""
        mine = MessageRecipient.objects.filter(user=request.user, archived=False)
        unread = mine.filter(read_at__isnull=True)
        pinned = (mine.filter(Q(message__priority="urgent", read_at__isnull=True) |
                              Q(message__requires_ack=True, acknowledged_at__isnull=True))
                  .select_related("message__sender").order_by("-message__created_at")[:3])
        return Response({"unread": unread.count(), "can_send": services.can_send(request.user),
                         "can_broadcast": request.user.has_org_perm("comms.broadcast"),
                         "pinned": InboxSerializer(pinned, many=True).data})


class SentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SentSerializer

    def get_queryset(self):
        return (Message.objects.filter(sender=self.request.user)
                .annotate(read_count=Count("recipients", filter=Q(recipients__read_at__isnull=False)),
                          ack_count=Count("recipients", filter=Q(recipients__acknowledged_at__isnull=False)))
                .order_by("-created_at"))

    @action(detail=True)
    def recipients(self, request, pk=None):
        """Who has read / acknowledged it."""
        msg = self.get_object()
        rows = msg.recipients.select_related("user").order_by("read_at", "user__first_name")
        return Response([{"name": _name(r.user), "username": r.user.username, "read_at": r.read_at,
                          "acknowledged_at": r.acknowledged_at} for r in rows])


def _err(e: services.AudienceError):
    if e.status == 403:
        raise PermissionDenied(str(e))
    raise ValidationError({"detail": str(e)})


@api_view(["POST"])
def compose(request):
    """{subject, body, kind, priority, requires_ack, audience:{users,departments,groups,branches,roles,everyone}}
    or {body, parent: <message id>} for a reply."""
    d = request.data
    parent = None
    if d.get("parent"):
        parent = Message.objects.filter(pk=d["parent"], organization=request.user.organization).first()
        if not parent:
            raise ValidationError({"parent": "Message not found."})
    kind = d.get("kind", "message")
    priority = d.get("priority", "normal")
    if kind not in dict(Message.KIND) or priority not in dict(Message.PRIORITY):
        raise ValidationError({"detail": "Unknown kind or priority."})
    try:
        msg, skipped = services.send(request.user, subject=d.get("subject", ""), body=d.get("body", ""),
                                     audience=d.get("audience") or {}, kind=kind, priority=priority,
                                     requires_ack=bool(d.get("requires_ack")), parent=parent, request=request)
    except services.AudienceError as e:
        _err(e)
    return Response({"id": msg.id, "recipient_count": msg.recipient_count, "skipped": skipped,
                     "audience_label": msg.audience_label}, status=201)


@api_view(["POST"])
def preview(request):
    """How many people would get it - shown live in the compose form."""
    try:
        ids, skipped, label = services.resolve(request.user, request.data.get("audience") or {})
    except services.AudienceError as e:
        return Response({"count": 0, "skipped": 0, "label": "", "error": str(e)})
    return Response({"count": len(ids), "skipped": skipped, "label": label})


@api_view(["GET"])
def directory(request):
    """Everything the compose form can target, limited to the sender's reach."""
    u = request.user
    if not services.can_send(u):
        raise PermissionDenied("Your role cannot send messages.")
    org = u.organization
    scope = services.scope_user_ids(u)
    people = User.objects.filter(organization=org, is_active=True).exclude(pk=u.pk)
    if scope is not None:
        people = people.filter(pk__in=scope)
    emp = {e.user_id: e for e in Employee.objects.filter(organization=org, user__isnull=False).select_related("department")}
    member_branches = {}
    for m in Membership.objects.filter(user__in=people, is_active=True).select_related("branch", "role"):
        member_branches.setdefault(m.user_id, []).append({"branch": m.branch.name if m.branch else "All branches",
                                                          "role": m.role.name})
    branch_ids = services.scope_branch_ids(u)
    return Response({
        "people": [{"id": p.pk, "name": _name(p), "username": p.username,
                    "department": emp[p.pk].department.name if p.pk in emp and emp[p.pk].department else "",
                    "roles": member_branches.get(p.pk, [])} for p in people.order_by("first_name", "username")],
        "departments": list(Department.objects.filter(organization=org).order_by("name").values("id", "name")),
        "groups": [{"id": g.pk, "name": g.name, "size": g.size}
                   for g in StaffGroup.objects.filter(organization=org).annotate(size=Count("members"))],
        "branches": list(Branch.objects.filter(pk__in=branch_ids, is_active=True).order_by("name").values("id", "name")),
        "roles": list(Role.objects.filter(organization=org, is_active=True).order_by("name").values("id", "name")),
        "can_broadcast": u.has_org_perm("comms.broadcast"),
    })


class GroupSerializer(serializers.ModelSerializer):
    member_names = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = StaffGroup
        fields = ["id", "name", "description", "members", "member_names", "created_by", "created_by_name"]
        read_only_fields = ["created_by"]

    def get_member_names(self, g):
        return [_name(m) for m in g.members.all()]

    def get_created_by_name(self, g):
        return _name(g.created_by)

    def validate_members(self, members):
        u = self.context["request"].user
        scope = services.scope_user_ids(u)
        for m in members:
            if m.organization_id != u.organization_id or (scope is not None and m.pk not in scope):
                raise serializers.ValidationError(f"{_name(m)} is outside your branches.")
        return members

    def validate_name(self, name):
        qs = StaffGroup.objects.filter(organization=self.context["request"].user.organization, name__iexact=name.strip())
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A group with this name exists.")
        return name.strip()


class GroupViewSet(viewsets.ModelViewSet):
    """Anyone who can send may create groups; only the creator (or an org-wide sender) edits/deletes them."""

    serializer_class = GroupSerializer

    def get_queryset(self):
        return StaffGroup.objects.filter(organization=self.request.user.organization).prefetch_related("members")

    def _require_send(self):
        if not services.can_send(self.request.user):
            raise PermissionDenied("Your role cannot manage groups.")

    def _require_owner(self, g):
        u = self.request.user
        if g.created_by_id != u.pk and not (u.has_org_perm("comms.send") or u.has_org_perm("comms.broadcast")):
            raise PermissionDenied("Only the person who made this group can change it.")

    def perform_create(self, serializer):
        self._require_send()
        serializer.save(organization=self.request.user.organization, created_by=self.request.user)

    def perform_update(self, serializer):
        self._require_send()
        self._require_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._require_owner(instance)
        instance.delete()
