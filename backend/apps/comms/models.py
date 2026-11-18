from django.conf import settings
from django.db import models

from apps.core.models import Organization, TimeStamped


class StaffGroup(TimeStamped):
    """A named list of people to message together, e.g. "Weekend shift", "Store managers"."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="staff_groups")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="staff_groups")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        unique_together = [("organization", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Message(models.Model):
    """One message or announcement. Who it went to is frozen in MessageRecipient at send time, so later
    staff changes never alter who received what."""

    KIND = [("message", "Message"), ("announcement", "Announcement")]
    PRIORITY = [("normal", "Normal"), ("important", "Important"), ("urgent", "Urgent")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sent_messages")
    kind = models.CharField(max_length=12, choices=KIND, default="message")
    priority = models.CharField(max_length=10, choices=PRIORITY, default="normal")
    subject = models.CharField(max_length=160)
    body = models.TextField()
    requires_ack = models.BooleanField(default=False, help_text="Recipients must press 'Got it'.")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="replies")
    # What the sender picked, kept for display ("Lilongwe City Centre, Shop floor department").
    audience = models.JSONField(default=dict)
    audience_label = models.CharField(max_length=500)
    recipient_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject


class MessageRecipient(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inbox")
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        unique_together = [("message", "user")]
        indexes = [models.Index(fields=["user", "read_at"])]
