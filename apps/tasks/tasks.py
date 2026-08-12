from datetime import datetime, time, timedelta
from smtplib import SMTPException

from celery import shared_task
from django.utils import timezone

from apps.common.enums import NotificationType, TaskStatus
from apps.notifications.services import dispatch_notification
from apps.tasks.models import Task

ACTIVE_STATUSES = (TaskStatus.OPEN, TaskStatus.IN_PROGRESS)

# domain-model.md's Notification Events table, row 8: due-proximity notifications fire
# to BOTH the assignee and assigner (api-spec.md §11's older table says assignee only --
# the more recently reconciled domain-model.md table wins, same kind of call as the
# Subtasks slice's notification-target fix).
_DUE_PROXIMITY_LABELS = {
    NotificationType.TASK_DUE_TODAY: "is due today",
    NotificationType.TASK_DUE_TOMORROW: "is due tomorrow",
    NotificationType.TASK_OVERDUE: "is overdue",
}


def _notify_due_proximity(task: Task, type_: str) -> None:
    message = f'Task "{task.title}" {_DUE_PROXIMITY_LABELS[type_]}'
    for recipient in (task.assignee, task.assigner):
        dispatch_notification(
            tenant_id=task.tenant_id,
            recipient=recipient,
            type_=type_,
            entity_type="task",
            entity_id=task.id,
            message=message,
            entity_title=task.title,
            send_email=True,
            email_subject=message,
            email_body=message,
        )


@shared_task(
    name="apps.tasks.due_proximity_sweep",
    autoretry_for=(SMTPException,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def task_due_proximity_sweep():
    """Daily EventBridge-equivalent sweep for TASK_DUE_TODAY/TASK_DUE_TOMORROW/
    TASK_OVERDUE (docs/api/api-spec.md §11, row 8) -- one-shot per threshold crossing.

    Idempotent by design: due_today_notified_at/due_tomorrow_notified_at are only set
    after a successful dispatch, and the OVERDUE transition itself is TASK_OVERDUE's
    one-shot guard (a task already OVERDUE no longer matches ACTIVE_STATUSES) -- a
    retried run after a partial failure only reprocesses what didn't get marked,
    never double-sends what already succeeded.
    """
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    start_of_today = timezone.make_aware(datetime.combine(today, time.min))

    due_today = Task.objects.filter(
        status__in=ACTIVE_STATUSES, due_date__date=today, due_today_notified_at__isnull=True,
    ).select_related("assignee", "assigner")
    for task in due_today:
        _notify_due_proximity(task, NotificationType.TASK_DUE_TODAY)
        task.due_today_notified_at = timezone.now()
        task.save(update_fields=["due_today_notified_at"])

    due_tomorrow = Task.objects.filter(
        status__in=ACTIVE_STATUSES, due_date__date=tomorrow, due_tomorrow_notified_at__isnull=True,
    ).select_related("assignee", "assigner")
    for task in due_tomorrow:
        _notify_due_proximity(task, NotificationType.TASK_DUE_TOMORROW)
        task.due_tomorrow_notified_at = timezone.now()
        task.save(update_fields=["due_tomorrow_notified_at"])

    # Strictly before today -- a task due today isn't overdue yet, only from the day
    # after its due date onward.
    newly_overdue = Task.objects.filter(
        status__in=ACTIVE_STATUSES, due_date__lt=start_of_today,
    ).select_related("assignee", "assigner")
    for task in newly_overdue:
        task.status = TaskStatus.OVERDUE
        task.save(update_fields=["status"])
        _notify_due_proximity(task, NotificationType.TASK_OVERDUE)
