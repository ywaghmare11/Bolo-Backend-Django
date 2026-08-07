from apps.common.exceptions import ValidationError
from apps.labels.repositories import LabelRepository


class LabelService:
    @staticmethod
    def create_label(user, tenant_id, name, color_code, description):
        return LabelRepository.create(
            tenant_id=tenant_id,
            created_by=user,
            name=name,
            color_code=color_code,
            description=description,
        )

    @staticmethod
    def list_my_labels(user, tenant_id):
        """Backs both GET /labels/shared and GET /labels/mine -- both are
        documented as the identical created_by=request.user query, just
        surfaced for different UI purposes (main-label picker vs personal-
        label picker)."""
        return LabelRepository.list_by_creator(created_by=user, tenant_id=tenant_id)

    @staticmethod
    def update_label(user, tenant_id, label_id, fields: dict):
        if not fields:
            raise ValidationError("At least one field must be provided")
        label = LabelRepository.get_owned_by_or_404(label_id, user, tenant_id)
        return LabelRepository.update(label, **fields)

    @staticmethod
    def delete_label(user, tenant_id, label_id):
        label = LabelRepository.get_owned_by_or_404(label_id, user, tenant_id)
        LabelRepository.delete(label)
