from django.core.cache import cache

from apps.common import caching
from apps.common.exceptions import ValidationError
from apps.labels.repositories import LabelRepository


class LabelService:
    @staticmethod
    def create_label(user, tenant_id, name, color_code, description):
        label = LabelRepository.create(
            tenant_id=tenant_id,
            created_by=user,
            name=name,
            color_code=color_code,
            description=description,
        )
        caching.bust_label_list(user.id)
        return label

    @staticmethod
    def list_my_labels(user, tenant_id):
        """Backs both GET /labels/shared and GET /labels/mine -- both are
        documented as the identical created_by=request.user query, just
        surfaced for different UI purposes (main-label picker vs personal-
        label picker). Also read once per task-detail load for
        `myPersonalLabels`. Cache-aside (ROADMAP.md Phase 12): busted by
        create/update/delete_label below, TTL is only a backstop."""
        key = caching.label_list_key(user.id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        labels = list(LabelRepository.list_by_creator(created_by=user, tenant_id=tenant_id))
        cache.set(key, labels, caching.LABEL_LIST_TTL)
        return labels

    @staticmethod
    def update_label(user, tenant_id, label_id, fields: dict):
        if not fields:
            raise ValidationError("At least one field must be provided")
        label = LabelRepository.get_owned_by_or_404(label_id, user, tenant_id)
        label = LabelRepository.update(label, **fields)
        caching.bust_label_list(user.id)
        return label

    @staticmethod
    def delete_label(user, tenant_id, label_id):
        label = LabelRepository.get_owned_by_or_404(label_id, user, tenant_id)
        LabelRepository.delete(label)
        caching.bust_label_list(user.id)
