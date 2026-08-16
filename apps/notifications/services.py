from datetime import datetime, timezone as dt_timezone

from apps.common.email import EmailService
from apps.common.enums import NotificationType, Priority
from apps.common.exceptions import NotFoundError
from apps.notifications.nudge_rules import (
    DUE_PROXIMITY,
    classify_followup,
    due_proximity_bucket,
    resolved_by_comment_since,
)
from apps.notifications.repositories import NotificationRepository, NudgeSkipCounterRepository
from apps.notifications.serializers import serialize_due_proximity_nudge, serialize_followup_nudge
from apps.tasks.repositories import TaskRepository

_PRIORITY_RANK = {Priority.P1: 0, Priority.P2: 1, Priority.P3: 2, Priority.P4: 3}

_MAX_FEED_ITEMS = 5

# Sorts never-shown Follow-up candidates first (oldest/never-shown-first rotation,
# domain-model.md's Feed composition note).
_NEVER_SHOWN = datetime.min.replace(tzinfo=dt_timezone.utc)


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


class NudgeService:
    """GET /nudges, POST /nudges/:id/skip, POST /nudges/skip-all
    (docs/api/api-spec.md §11). Every row is re-validated against current
    entity state on every call -- see apps.notifications.nudge_rules."""

    @staticmethod
    def get_feed(user, tenant_id) -> list[dict]:
        notifications = NotificationRepository.list_unread_ai_nudges(user, tenant_id)

        # Dedup by (entityId, type): only the newest unread notification per
        # pair counts toward a slot -- older duplicates are silently resolved
        # (api-spec.md §11's GET /nudges).
        seen_keys = set()
        deduped = []
        for notification in notifications:
            key = (notification.entity_id, notification.type)
            if key in seen_keys:
                NotificationRepository.mark_read(notification)
                continue
            seen_keys.add(key)
            deduped.append(notification)

        due_candidates = []
        followup_candidates = []
        for notification in deduped:
            try:
                task = TaskRepository.get_by_id(notification.entity_id, tenant_id)
            except NotFoundError:
                NotificationRepository.mark_read(notification)
                continue
            if task.assignee_id != user.id:
                NotificationRepository.mark_read(notification)
                continue

            if notification.type == NotificationType.AI_NUDGE_FOLLOWUP:
                kind = classify_followup(task)
                if kind is None:
                    NotificationRepository.mark_read(notification)
                    continue
                counter = NudgeSkipCounterRepository.get_or_create(tenant_id, "task", task.id, kind)
                item = serialize_followup_nudge(notification, task, kind, counter)
                followup_candidates.append((task, counter, item))
            else:
                bucket = due_proximity_bucket(task)
                if bucket is None or resolved_by_comment_since(task, notification.created_at):
                    NotificationRepository.mark_read(notification)
                    continue
                counter = NudgeSkipCounterRepository.get_or_create(
                    tenant_id, "task", task.id, DUE_PROXIMITY,
                )
                item = serialize_due_proximity_nudge(notification, task, bucket, counter)
                due_candidates.append((task, counter, item))

        # Feed composition (domain-model.md, "Feed composition (added 2026-07-13)"):
        # Due-Proximity fills first by priority, Follow-up fills remaining slots by
        # priority then oldest-lastShownAt-first for rotation.
        due_candidates.sort(key=lambda c: _PRIORITY_RANK[c[0].priority])
        due_slots = due_candidates[:_MAX_FEED_ITEMS]

        remaining = _MAX_FEED_ITEMS - len(due_slots)
        followup_candidates.sort(
            key=lambda c: (
                _PRIORITY_RANK[c[0].priority],
                c[1].last_shown_at or _NEVER_SHOWN,
            ),
        )
        followup_slots = followup_candidates[:remaining] if remaining > 0 else []

        for _task, counter, _item in followup_slots:
            NudgeSkipCounterRepository.touch_last_shown(counter)

        return [item for _task, _counter, item in due_slots] + [
            item for _task, _counter, item in followup_slots
        ]

    @staticmethod
    def skip(user, tenant_id, notification_id) -> dict:
        notification = NotificationRepository.get_own_ai_nudge(notification_id, user, tenant_id)
        try:
            task = TaskRepository.get_by_id(notification.entity_id, tenant_id)
        except NotFoundError:
            NotificationRepository.mark_read(notification)
            return {"skipCount": 0}

        if notification.type == NotificationType.AI_NUDGE_FOLLOWUP:
            kind = classify_followup(task)
        else:
            kind = DUE_PROXIMITY if due_proximity_bucket(task) is not None else None

        NotificationRepository.mark_read(notification)

        if kind is None:
            return {"skipCount": 0}

        counter = NudgeSkipCounterRepository.increment(tenant_id, "task", task.id, kind)
        return {"skipCount": counter.skip_count}

    @staticmethod
    def skip_all(user, tenant_id) -> dict:
        feed = NudgeService.get_feed(user, tenant_id)
        for item in feed:
            NudgeService.skip(user, tenant_id, item["id"])
        return {"skippedCount": len(feed)}
