from apps.notifications.nudge_rules import DUE_PROXIMITY_CAPS

_FOLLOWUP_SUBTITLES = {
    "followup_no_progress": "Accepted but no progress update since",
    "followup_unanswered_comment": "You owe a reply on this task",
}


def serialize_followup_nudge(notification, task, kind, counter) -> dict:
    return {
        "id": str(notification.id),
        "nudgeType": "FOLLOWUP",
        "entityType": "task",
        "entityId": str(task.id),
        "title": task.title,
        "subtitle": _FOLLOWUP_SUBTITLES[kind],
        "actions": ["ADD_COMMENT"],
        "skipCount": counter.skip_count,
        "skipCap": None,
        "escalation": None,
        "createdAt": notification.created_at.isoformat(),
    }


def serialize_due_proximity_nudge(notification, task, bucket, counter) -> dict:
    return {
        "id": str(notification.id),
        "nudgeType": "DUE_PROXIMITY",
        "entityType": "task",
        "entityId": str(task.id),
        "title": task.title,
        "subtitle": "Due today" if bucket == "due_today" else "Overdue",
        "actions": ["ADD_COMMENT", "OPEN_TASK"],
        "skipCount": counter.skip_count,
        "skipCap": DUE_PROXIMITY_CAPS[bucket],
        "escalation": {"toName": task.assigner.name},
        "createdAt": notification.created_at.isoformat(),
    }
