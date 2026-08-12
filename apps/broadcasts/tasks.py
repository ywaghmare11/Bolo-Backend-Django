from celery import shared_task
from django.utils.html import strip_tags

from apps.broadcasts.models import BroadcastNotice
from apps.common.enums import NotificationType
from apps.notifications.services import dispatch_notification
from apps.users.models import User

ENTITY_TITLE_MAX_LENGTH = 100


@shared_task(name="apps.broadcasts.fanout_notifications")
def broadcast_fanout_task(broadcast_id, recipient_user_ids):
    """Fire-and-forget BROADCAST_POSTED fan-out -- dispatched from
    BroadcastService.publish/update_broadcast rather than run inline, per
    guidelines.md's Performance section ('Notification fan-out for broadcasts:
    enqueue a Celery task, never inline in the request/response cycle')."""
    if not recipient_user_ids:
        return

    try:
        broadcast = BroadcastNotice.objects.select_related("sender").get(id=broadcast_id)
    except BroadcastNotice.DoesNotExist:
        return

    entity_title = strip_tags(broadcast.message_html).strip()[:ENTITY_TITLE_MAX_LENGTH]
    for recipient in User.objects.filter(id__in=recipient_user_ids):
        dispatch_notification(
            tenant_id=broadcast.tenant_id,
            recipient=recipient,
            type_=NotificationType.BROADCAST_POSTED,
            entity_type="broadcast",
            entity_id=broadcast.id,
            message=f"{broadcast.sender.name} posted a broadcast",
            actor_name=broadcast.sender.name,
            entity_title=entity_title,
        )
