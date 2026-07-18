from django.db import models

from apps.common.enums import AcceptanceStatus, Priority, TaskStatus
from apps.common.models import CreatedOnlyModel, TimestampedModel


class Task(TimestampedModel):
    """A Task row with parent_task set IS a subtask -- same fields, relations, and rules."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="tasks",
    )
    # immutable after creation -- enforced in the service layer, not here
    title = models.CharField(max_length=255)
    assigner = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="tasks_delegated",
    )
    assignee = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="tasks_assigned",
    )
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.DRAFT,
    )
    acceptance_status = models.CharField(
        max_length=20,
        choices=AcceptanceStatus.choices,
        default=AcceptanceStatus.PENDING,
    )
    priority = models.CharField(
        max_length=2, choices=Priority.choices, default=Priority.P3,
    )
    # optional while Draft; required at Draft -> Open transition (service-enforced)
    due_date = models.DateTimeField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    # assigner sets; visible to all who can see the task
    main_label = models.ForeignKey(
        "labels.ProjectLabel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="main_label_tasks",
    )
    # assignee sets; private -- never returned to non-assignees; cleared on reassignment
    assignee_label = models.ForeignKey(
        "labels.ProjectLabel",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assignee_label_tasks",
    )
    # true only when assigner marks DONE_D on a main task (parent_task IS NULL)
    is_archived = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)
    parent_task = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="subtasks",
    )

    class Meta:
        db_table = "tasks"
        indexes = [
            models.Index(fields=["status"], name="idx_tasks_status"),
        ]

    def __str__(self):
        return self.title


class VoiceRecording(CreatedOnlyModel):
    """1:1 with Task (incl. subtasks). rawTranscript always stored; audioUrl is opt-in (W37)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="voice_recordings",
    )
    # deleted together with its task -- documented cascade (schema.prisma.reference)
    task = models.OneToOneField(
        "tasks.Task", on_delete=models.CASCADE, related_name="voice_recording",
    )
    raw_transcript = models.TextField()
    language = models.CharField(max_length=16, null=True, blank=True)
    duration_secs = models.FloatField(null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    # S3 object key, not a URL -- pre-signed GET URL generated on demand
    audio_url = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "voice_recordings"

    def __str__(self):
        return str(self.task_id)
