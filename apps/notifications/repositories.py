from apps.notifications.models import Notification


class NotificationRepository:
    @staticmethod
    def create(**fields) -> Notification:
        return Notification.objects.create(**fields)
