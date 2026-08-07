from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.common.exceptions import ConflictError, NotFoundError
from apps.labels.models import ProjectLabel


class LabelRepository:
    @staticmethod
    def create(tenant_id, created_by, name, color_code, description) -> ProjectLabel:
        try:
            return ProjectLabel.objects.create(
                tenant_id=tenant_id,
                created_by=created_by,
                name=name,
                color_code=color_code,
                description=description,
            )
        except IntegrityError:
            raise ConflictError(
                f"You already have a label named '{name}'", code="LABEL_NAME_TAKEN",
            ) from None

    @staticmethod
    def list_by_creator(created_by, tenant_id):
        return ProjectLabel.objects.filter(
            created_by=created_by, tenant_id=tenant_id,
        ).order_by("name")

    @staticmethod
    def get_owned_by(label_id, user, tenant_id) -> ProjectLabel | None:
        """None if the label doesn't exist, isn't owned by this user, or is
        in a different tenant -- callers treat all three the same way."""
        return ProjectLabel.objects.filter(
            id=label_id, created_by=user, tenant_id=tenant_id,
        ).first()

    @staticmethod
    def get_owned_by_or_404(label_id, user, tenant_id) -> ProjectLabel:
        label = LabelRepository.get_owned_by(label_id, user, tenant_id)
        if label is None:
            raise NotFoundError("Label", label_id)
        return label

    @staticmethod
    def update(label: ProjectLabel, **fields) -> ProjectLabel:
        for key, value in fields.items():
            setattr(label, key, value)
        try:
            label.save()
        except IntegrityError:
            raise ConflictError(
                f"You already have a label named '{label.name}'", code="LABEL_NAME_TAKEN",
            ) from None
        return label

    @staticmethod
    def delete(label: ProjectLabel) -> None:
        try:
            label.delete()
        except ProtectedError:
            raise ConflictError(
                "This label is currently applied to a task -- remove it from the task first",
                code="LABEL_IN_USE",
            ) from None
