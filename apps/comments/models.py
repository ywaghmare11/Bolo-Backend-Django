from django.db import models

from apps.common.models import TimestampedModel


class Comment(TimestampedModel):
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.PROTECT, related_name="comments",
    )
    author = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="comments",
    )
    text = models.TextField()
    is_edited = models.BooleanField(default=False)

    class Meta:
        db_table = "comments"

    def __str__(self):
        return f"Comment({self.id})"
