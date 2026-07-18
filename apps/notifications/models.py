from django.db import models

from apps.common.enums import NotificationType
from apps.common.models import CreatedOnlyModel, TimestampedModel


class Notification(CreatedOnlyModel):
    """In-app only for V1. entity_type + entity_id is a polymorphic reference."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="notifications",
    )
    recipient = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="notifications_received",
    )
    type = models.CharField(max_length=30, choices=NotificationType.choices)
    # "task" | "broadcast" | "sticky_note" -- always lowercase
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    message = models.CharField(max_length=500)
    # enriched display fields for the general Notification panel -- optional,
    # UI degrades gracefully to plain `message` text when absent
    actor_name = models.CharField(max_length=255, null=True, blank=True)
    entity_title = models.CharField(max_length=255, null=True, blank=True)
    entity_context = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications"
        indexes = [
            models.Index(fields=["recipient", "is_read"], name="idx_notif_recipient_read"),
            models.Index(fields=["entity_type", "entity_id"], name="idx_notif_entity"),
        ]

    def __str__(self):
        return f"Notification({self.id})"


class NudgeSkipCounter(TimestampedModel):
    """AI-nudge skip/escalation state. Scope narrowed 2026-07-13 to Task only
    (Broadcast/StickyNote/Subtask dropped) -- every remaining candidate has
    exactly one assignee, so keying is per-task, not per-user."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="nudge_skip_counters",
    )
    # "task" -- scope narrowed 2026-07-13
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    # "followup_no_progress" | "followup_unanswered_comment" | "due_proximity"
    nudge_kind = models.CharField(max_length=64)
    skip_count = models.PositiveIntegerField(default=0)
    # due-proximity only, one-time escalation-to-assigner guard
    escalated_at = models.DateTimeField(null=True, blank=True)
    # last time this candidate was actually included in a GET /nudges response --
    # drives Follow-up's oldest-shown-first rotation under the feed's 5-slot cap
    last_shown_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "nudge_skip_counters"
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_id", "nudge_kind"],
                name="uq_nudge_skip_counter",
            ),
        ]

    def __str__(self):
        return f"NudgeSkipCounter({self.id})"
