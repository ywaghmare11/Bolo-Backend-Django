from django.db.models import F
from django.utils import timezone

from apps.common.enums import NotificationType
from apps.common.exceptions import NotFoundError
from apps.notifications.models import Notification, NudgeSkipCounter

AI_NUDGE_TYPES = (NotificationType.AI_NUDGE_FOLLOWUP, NotificationType.AI_NUDGE_DUE_PROXIMITY)


class NotificationRepository:
    @staticmethod
    def create(**fields) -> Notification:
        return Notification.objects.create(**fields)

    @staticmethod
    def list_unread_ai_nudges(recipient, tenant_id):
        return Notification.objects.filter(
            recipient=recipient, tenant_id=tenant_id, type__in=AI_NUDGE_TYPES, is_read=False,
        ).order_by("-created_at")

    @staticmethod
    def has_unread_ai_nudge(recipient, entity_type, entity_id) -> bool:
        return Notification.objects.filter(
            recipient=recipient, entity_type=entity_type, entity_id=str(entity_id),
            type__in=AI_NUDGE_TYPES, is_read=False,
        ).exists()

    @staticmethod
    def get_own_ai_nudge(notification_id, recipient, tenant_id) -> Notification:
        try:
            return Notification.objects.get(
                id=notification_id, recipient=recipient, tenant_id=tenant_id, type__in=AI_NUDGE_TYPES,
            )
        except Notification.DoesNotExist:
            raise NotFoundError("Notification", notification_id) from None

    @staticmethod
    def mark_read(notification: Notification) -> None:
        if notification.is_read:
            return
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])


class NudgeSkipCounterRepository:
    @staticmethod
    def get_or_create(tenant_id, entity_type, entity_id, nudge_kind) -> NudgeSkipCounter:
        counter, _ = NudgeSkipCounter.objects.get_or_create(
            entity_type=entity_type, entity_id=str(entity_id), nudge_kind=nudge_kind,
            defaults={"tenant_id": tenant_id},
        )
        return counter

    @staticmethod
    def increment(tenant_id, entity_type, entity_id, nudge_kind) -> NudgeSkipCounter:
        counter = NudgeSkipCounterRepository.get_or_create(tenant_id, entity_type, entity_id, nudge_kind)
        counter.skip_count = F("skip_count") + 1
        counter.save(update_fields=["skip_count"])
        counter.refresh_from_db()
        return counter

    @staticmethod
    def touch_last_shown(counter: NudgeSkipCounter) -> None:
        counter.last_shown_at = timezone.now()
        counter.save(update_fields=["last_shown_at"])
