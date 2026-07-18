from django.db import models

from apps.common.enums import EvidenceType
from apps.common.models import CreatedOnlyModel


class Evidence(CreatedOnlyModel):
    task = models.ForeignKey(
        "tasks.Task", on_delete=models.PROTECT, related_name="evidence",
    )
    uploader = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="evidence_uploaded",
    )
    # S3 object key -- pre-signed URL generated per request, never the raw key
    file_url = models.CharField(max_length=512)
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    file_type = models.CharField(max_length=10, choices=EvidenceType.choices)
    caption = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "evidence"

    def __str__(self):
        return self.file_name
