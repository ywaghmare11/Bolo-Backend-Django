"""Shared AI Nudge eligibility rules -- used by both the Celery sweeps
(apps/notifications/tasks.py, deciding whether to fire a fresh notification)
and NudgeService (apps/notifications/services.py, re-validating an existing
one on every GET /nudges call against current entity state). One source of
truth keeps the two call sites from silently drifting apart.

Scope narrowed 2026-07-13 (docs/architecture/domain-model.md rows 8c/8d,
docs/product/open-questions-web-v1.md Section 18's superseding note): Task
only, Follow-up down to 2 assignee-only conditions.
"""
from django.utils import timezone

from apps.common.enums import AcceptanceStatus, TaskStatus

FOLLOWUP_NO_PROGRESS = "followup_no_progress"
FOLLOWUP_UNANSWERED_COMMENT = "followup_unanswered_comment"
DUE_PROXIMITY = "due_proximity"

# domain-model.md row 8d: "Cap: 3 for due-today, 1 for overdue."
DUE_PROXIMITY_CAPS = {"due_today": 3, "overdue": 1}

ACTIVE_STATUSES = (TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE)


def classify_followup(task) -> str | None:
    """Returns the Follow-up nudge_kind still eligible for this task's
    assignee, or None if neither condition holds.

    Re-running this against current comment state is also what makes "Add
    Comment resolves the nudge" work for Follow-up without any special
    casing: once the assignee's own comment becomes the latest one, this
    naturally returns None.
    """
    if task.status not in ACTIVE_STATUSES or task.acceptance_status != AcceptanceStatus.ACCEPTED:
        return None

    last_comment = task.comments.order_by("-created_at").first()
    if last_comment is None or (task.accepted_at and last_comment.created_at <= task.accepted_at):
        return FOLLOWUP_NO_PROGRESS
    if last_comment.author_id == task.assigner_id:
        return FOLLOWUP_UNANSWERED_COMMENT
    # Assignee posted last -- they've already responded, and the assigner is
    # out of scope for Follow-up entirely (domain-model.md row 8c).
    return None


def due_proximity_bucket(task, now=None) -> str | None:
    """"due_today" | "overdue" | None. Already-accepted only -- an
    unaccepted-but-overdue task gets no nudge at all (row 8d)."""
    if task.acceptance_status != AcceptanceStatus.ACCEPTED:
        return None
    if task.status == TaskStatus.OVERDUE:
        return "overdue"
    if task.status == TaskStatus.IN_PROGRESS and task.due_date:
        now = now or timezone.now()
        if task.due_date.date() == timezone.localtime(now).date():
            return "due_today"
    return None


def resolved_by_comment_since(task, since) -> bool:
    """Due-Proximity's "Add Comment resolves the nudge for this cycle" fix
    (domain-model.md row 8d) -- unlike Follow-up, due_proximity_bucket()
    doesn't look at comments at all, so re-validation needs this as a
    separate check."""
    return task.comments.filter(created_at__gt=since).exists()
