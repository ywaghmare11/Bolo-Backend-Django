from django.db import IntegrityError

from apps.common.exceptions import ConflictError
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
