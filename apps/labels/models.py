from django.db import models

from apps.common.models import TimestampedModel


class ProjectLabel(TimestampedModel):
    """Single label pool, serving two purposes via a dual FK on Task:
    main_label (assigner sets, visible to all who can see the task) and
    assignee_label (assignee sets, private). Each user sees only labels
    they created. No separate personal-label table (TaskPersonalLabel
    removed -- see V1.2 label model redesign)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="project_labels",
    )
    name = models.CharField(max_length=100)
    color_code = models.CharField(max_length=7, default="#6B7280")
    description = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="project_labels_created",
    )

    class Meta:
        db_table = "project_labels"
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "name"], name="uq_project_label_created_by_name",
            ),
        ]

    def __str__(self):
        return self.name
