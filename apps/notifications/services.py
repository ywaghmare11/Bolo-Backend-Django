from apps.common.email import EmailService
from apps.notifications.repositories import NotificationRepository


def dispatch_notification(
    tenant_id,
    recipient,
    type_,
    entity_type,
    entity_id,
    message,
    actor_name=None,
    entity_title=None,
    entity_context=None,
    send_email=False,
    email_subject=None,
    email_body=None,
):
    """The only place Notification rows get written and the only place the
    email channel gets triggered for task/subtask events -- callers (e.g.
    apps.tasks.services) never touch NotificationRepository or EmailService
    directly, per architecture rule 7."""
    NotificationRepository.create(
        tenant_id=tenant_id,
        recipient=recipient,
        type=type_,
        entity_type=entity_type,
        entity_id=str(entity_id),
        message=message,
        actor_name=actor_name,
        entity_title=entity_title,
        entity_context=entity_context,
    )

    if send_email:
        EmailService.send_task_reminder_email(
            recipient.email, email_subject or entity_title or "", email_body or message,
        )
