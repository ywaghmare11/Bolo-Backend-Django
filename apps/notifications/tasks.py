from smtplib import SMTPException

from celery import shared_task
from django.utils import timezone

from apps.common.enums import AcceptanceStatus, NotificationType, TenantStatus
from apps.notifications.models import Notification, NudgeSkipCounter
from apps.notifications.nudge_rules import (
    ACTIVE_STATUSES,
    DUE_PROXIMITY,
    DUE_PROXIMITY_CAPS,
    classify_followup,
    due_proximity_bucket,
)
from apps.notifications.services import dispatch_notification
from apps.tasks.models import Task

_AI_NUDGE_TYPES = (NotificationType.AI_NUDGE_FOLLOWUP, NotificationType.AI_NUDGE_DUE_PROXIMITY)

_FOLLOWUP_MESSAGES = {
    "followup_no_progress": 'No progress update on "{title}" since it was accepted',
    "followup_unanswered_comment": 'You owe a reply on "{title}"',
}


def _accepted_active_tasks():
    return Task.objects.filter(
        status__in=ACTIVE_STATUSES, acceptance_status=AcceptanceStatus.ACCEPTED,
        tenant__status=TenantStatus.ACTIVE,  # no AI nudges for a suspended tenant (Phase 15e)
    ).select_related("assignee", "assigner")


def _has_pending_ai_nudge(recipient, task) -> bool:
    """Cross-type dedup (domain-model.md W84): don't pile a second AI Nudge
    notification onto the same recipient+entity while an earlier one is
    still unread -- the earlier one is itself the cooldown, resolved as soon
    as the user sees/skips/resolves it (W74: no fixed dedup window is
    specified upstream beyond "sensible default chosen at implementation
    time")."""
    return Notification.objects.filter(
        recipient=recipient, entity_type="task", entity_id=str(task.id),
        type__in=_AI_NUDGE_TYPES, is_read=False,
    ).exists()


@shared_task(name="apps.notifications.ai_nudge_followup_sweep")
def ai_nudge_followup_sweep():
    """AI_NUDGE_FOLLOWUP -- every 6h, no office-hours gate (domain-model.md
    row 8c). 2 assignee-only conditions, no cap, no escalation."""
    for task in _accepted_active_tasks():
        kind = classify_followup(task)
        if kind is None:
            continue
        NudgeSkipCounter.objects.get_or_create(
            entity_type="task", entity_id=str(task.id), nudge_kind=kind,
            defaults={"tenant_id": task.tenant_id},
        )
        if _has_pending_ai_nudge(task.assignee, task):
            continue
        dispatch_notification(
            tenant_id=task.tenant_id,
            recipient=task.assignee,
            type_=NotificationType.AI_NUDGE_FOLLOWUP,
            entity_type="task",
            entity_id=task.id,
            message=_FOLLOWUP_MESSAGES[kind].format(title=task.title),
            entity_title=task.title,
        )


@shared_task(
    name="apps.notifications.ai_nudge_due_proximity_sweep",
    autoretry_for=(SMTPException,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def ai_nudge_due_proximity_sweep():
    """AI_NUDGE_DUE_PROXIMITY -- every 3h, no office-hours gate (domain-model.md
    row 8d). Escalation is checked every tick independent of whether a fresh
    routine notification fires this cycle, guarded by
    NudgeSkipCounter.escalated_at so it never repeats."""
    for task in _accepted_active_tasks():
        bucket = due_proximity_bucket(task)
        if bucket is None:
            continue

        counter, _created = NudgeSkipCounter.objects.get_or_create(
            entity_type="task", entity_id=str(task.id), nudge_kind=DUE_PROXIMITY,
            defaults={"tenant_id": task.tenant_id},
        )

        cap = DUE_PROXIMITY_CAPS[bucket]
        if counter.skip_count >= cap and counter.escalated_at is None:
            dispatch_notification(
                tenant_id=task.tenant_id,
                recipient=task.assigner,
                type_=NotificationType.AI_NUDGE_DUE_PROXIMITY,
                entity_type="task",
                entity_id=task.id,
                message=f'"{task.title}" has been skipped past its reminder limit and needs your attention',
                entity_title=task.title,
                send_email=True,
                email_subject=f'Escalation: "{task.title}" needs your attention',
                email_body=(
                    f'{task.assignee.name} has repeatedly skipped due-date reminders '
                    f'for "{task.title}", which is now {bucket.replace("_", " ")}.'
                ),
            )
            counter.escalated_at = timezone.now()
            counter.save(update_fields=["escalated_at"])

        if _has_pending_ai_nudge(task.assignee, task):
            continue
        dispatch_notification(
            tenant_id=task.tenant_id,
            recipient=task.assignee,
            type_=NotificationType.AI_NUDGE_DUE_PROXIMITY,
            entity_type="task",
            entity_id=task.id,
            message=f'"{task.title}" is {"overdue" if bucket == "overdue" else "due today"}',
            entity_title=task.title,
        )
