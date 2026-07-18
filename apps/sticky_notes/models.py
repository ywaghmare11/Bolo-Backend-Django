from django.db import models

from apps.common.models import TimestampedModel


class StickyNote(TimestampedModel):
    """Always private. A StickyNote with due_at set IS the reminder -- no separate entity."""

    user = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="sticky_notes",
    )
    text = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    is_pinned = models.BooleanField(default=False)
    # set when this note is converted to a task -- one note, one task
    promoted_to_task = models.OneToOneField(
        "tasks.Task",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="promoted_from_note",
    )

    class Meta:
        db_table = "sticky_notes"
        indexes = [
            models.Index(fields=["due_at"], name="idx_sticky_notes_due_at"),
        ]

    def __str__(self):
        return f"StickyNote({self.id})"
