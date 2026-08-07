from apps.common.exceptions import NotFoundError
from apps.evidence.models import Evidence


class EvidenceRepository:
    @staticmethod
    def list_for_task(task_id):
        return Evidence.objects.filter(task_id=task_id).select_related("uploader").order_by("created_at")

    @staticmethod
    def create(**fields) -> Evidence:
        return Evidence.objects.create(**fields)

    @staticmethod
    def get_by_id(evidence_id, task_id) -> Evidence:
        try:
            return Evidence.objects.select_related("uploader").get(id=evidence_id, task_id=task_id)
        except Evidence.DoesNotExist:
            raise NotFoundError("Evidence", evidence_id) from None

    @staticmethod
    def delete(evidence: Evidence) -> None:
        evidence.delete()
