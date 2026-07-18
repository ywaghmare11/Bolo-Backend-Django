from django.utils import timezone

from apps.common.exceptions import NotFoundError
from apps.users.models import User


class UserRepository:
    @staticmethod
    def get_by_email(email: str) -> User:
        try:
            return User.objects.get(email=email)
        except User.DoesNotExist:
            raise NotFoundError("User", email) from None

    @staticmethod
    def get_by_id(user_id: str) -> User:
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise NotFoundError("User", user_id) from None

    @staticmethod
    def update_last_login(user: User) -> None:
        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at", "updated_at"])

    @staticmethod
    def update_last_logout(user: User) -> None:
        user.last_logout_at = timezone.now()
        user.save(update_fields=["last_logout_at", "updated_at"])
