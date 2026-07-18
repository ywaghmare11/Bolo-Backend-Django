from django.db import models

from apps.common.enums import BroadcastStatus, OrgRoleLevel
from apps.common.models import TimestampedModel


class BroadcastNotice(TimestampedModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="broadcasts",
    )
    sender = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="broadcasts_sent",
    )
    # TipTap AST -- restores editor state when re-opening a draft
    message_json = models.JSONField()
    # sanitized HTML -- rendered in the broadcast feed
    message_html = models.TextField()
    status = models.CharField(
        max_length=20, choices=BroadcastStatus.choices, default=BroadcastStatus.DRAFT,
    )
    # null = all departments
    audience_dept = models.ForeignKey(
        "tenants.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="broadcasts",
    )
    # null = all role levels
    audience_role_level = models.CharField(
        max_length=20, choices=OrgRoleLevel.choices, null=True, blank=True,
    )
    requires_acknowledgement = models.BooleanField(default=False)
    # single image only -- draft stores S3 key, publish overwrites with a pre-signed URL
    image_url = models.CharField(max_length=512, null=True, blank=True)
    # set to created_at + 1 day on publish -- not configurable (W54)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "broadcast_notices"
        indexes = [
            models.Index(fields=["expires_at"], name="idx_broadcast_expires_at"),
        ]

    def __str__(self):
        return f"BroadcastNotice({self.id})"


class BroadcastAcknowledgement(models.Model):
    """One row per user per broadcast. Sender sees COUNT(*) only -- no per-person breakdown."""

    pk = models.CompositePrimaryKey("broadcast", "user")
    # CASCADE -- corrected 2026-07-13 upstream: PROTECT 500'd DELETE on any broadcast
    # with acknowledgements; the one documented exception to the default PROTECT rule
    broadcast = models.ForeignKey(
        "broadcasts.BroadcastNotice",
        on_delete=models.CASCADE,
        related_name="acknowledgements",
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="broadcast_acknowledgements",
    )
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "broadcast_acknowledgements"

    def __str__(self):
        return f"{self.user_id}->{self.broadcast_id}"
