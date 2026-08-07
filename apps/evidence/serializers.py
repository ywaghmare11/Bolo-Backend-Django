from rest_framework import serializers

from apps.common.enums import EvidenceType

# .xls (legacy binary Excel) accepted alongside .xlsx, per the 2026-08-03 upstream sync.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": EvidenceType.IMAGE,
    "image/png": EvidenceType.IMAGE,
    "image/heic": EvidenceType.IMAGE,
    "application/pdf": EvidenceType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": EvidenceType.DOC,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": EvidenceType.DOC,
    "application/vnd.ms-excel": EvidenceType.DOC,
}


class EvidencePresignSerializer(serializers.Serializer):
    taskId = serializers.UUIDField(source="task_id")
    filename = serializers.CharField(max_length=255)
    contentType = serializers.ChoiceField(source="content_type", choices=list(ALLOWED_CONTENT_TYPES))
    fileSize = serializers.IntegerField(source="file_size", min_value=1)


class EvidenceConfirmSerializer(serializers.Serializer):
    evidenceId = serializers.UUIDField(source="evidence_id")
    caption = serializers.CharField(required=False, allow_blank=True, default="")


def serialize_evidence(evidence) -> dict:
    return {
        "id": str(evidence.id),
        "taskId": str(evidence.task_id),
        "uploaderId": str(evidence.uploader_id),
        "uploaderName": evidence.uploader.name,
        # App-relative path to the streaming endpoint, not a pre-signed S3 URL --
        # see docs/api/api-spec.md §5's 2026-08-03 note on why.
        "fileUrl": f"/tasks/{evidence.task_id}/evidence/{evidence.id}/file",
        "fileName": evidence.file_name,
        "fileSize": evidence.file_size,
        "fileType": evidence.file_type,
        "caption": evidence.caption,
        "createdAt": evidence.created_at.isoformat(),
    }
