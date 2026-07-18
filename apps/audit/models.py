from django.db import models

from apps.common.enums import AuditAction, AuditActorType
from apps.common.models import CreatedOnlyModel


class AuditLog(CreatedOnlyModel):
    """Immutable -- never updated or deleted. Written from the service layer only."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="audit_logs",
    )
    # null for system-triggered actions (scheduler, EventBridge)
    actor = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_logs_actioned",
    )
    actor_type = models.CharField(
        max_length=14, choices=AuditActorType.choices, default=AuditActorType.USER,
    )
    action = models.CharField(max_length=64, choices=AuditAction.choices)
    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=64)
    # state before the change -- null for creates
    before = models.JSONField(null=True, blank=True)
    # state after the change -- null for deletes
    after = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="idx_audit_entity"),
            models.Index(fields=["tenant", "created_at"], name="idx_audit_tenant_created"),
        ]

    def __str__(self):
        return f"AuditLog({self.id})"
