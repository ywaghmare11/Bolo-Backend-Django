from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.sticky_notes.models import StickyNote
from apps.tasks.models import Task


def resolve_due_range(due_filter):
    """Day-boundary resolution for filters.due ("today"/"tomorrow"/"this_week").
    No existing due-today/due-tomorrow sweep exists yet in this project to reuse
    (REMINDER_FIRED/TASK_DUE_TODAY dispatch isn't built -- see changelog.md's
    2026-08-07 (1) entry), so this is self-contained rather than borrowed."""
    if due_filter not in ("today", "tomorrow", "this_week"):
        return None

    today = timezone.localdate()
    if due_filter == "today":
        start_date = end_date = today
    elif due_filter == "tomorrow":
        start_date = end_date = today + timedelta(days=1)
    else:  # this_week -- today through the end of the current Mon-Sun week
        start_date = today
        end_date = today + timedelta(days=6 - today.weekday())

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_date, time.min), tz)
    end = timezone.make_aware(datetime.combine(end_date, time.max), tz)
    return (start, end)


def _field_phrase_q(field_lookup: str, words: list[str]) -> Q:
    """AND's every word of a phrase against the SAME field via icontains -- tolerant
    of punctuation/separator differences (docs/engineering/testing-strategy.md #8:
    corrected "self study report" now matches stored "self-study" hyphenation)."""
    q = Q()
    for word in words:
        q &= Q(**{f"{field_lookup}__icontains": word})
    return q


def _task_keyword_q(keywords: list[str], caller_id) -> Q:
    combined = Q()
    matched_anything = False
    for phrase in keywords:
        words = [w for w in phrase.split() if w]
        if not words:
            continue
        matched_anything = True
        combined |= (
            _field_phrase_q("title", words)
            | _field_phrase_q("description", words)
            | _field_phrase_q("main_label__name", words)
            # Private label -- scoped AND assignee=caller in the same clause so it
            # can never leak a match to the assigner (docs/engineering/testing-strategy.md #3).
            | (_field_phrase_q("assignee_label__name", words) & Q(assignee_id=caller_id))
        )
    return combined if matched_anything else Q()


def _sticky_keyword_q(keywords: list[str]) -> Q:
    combined = Q()
    matched_anything = False
    for phrase in keywords:
        words = [w for w in phrase.split() if w]
        if not words:
            continue
        matched_anything = True
        combined |= _field_phrase_q("text", words)
    return combined if matched_anything else Q()


class SearchRepository:
    @staticmethod
    def search_tasks(tenant_id, caller, keywords, person_ids, status, priority, due_range, page, limit):
        # Same visibility rule as the task list endpoints -- not all-tenant. Draft/
        # Cancelled/Done_D (archived) tasks are included by design (search doesn't
        # hide them like the default Assigned/Delegated views do).
        qs = Task.objects.filter(tenant_id=tenant_id).filter(
            Q(assigner_id=caller.id) | Q(assignee_id=caller.id),
        )

        match_q = _task_keyword_q(keywords, caller.id)
        if person_ids:
            match_q |= Q(assigner_id__in=person_ids) | Q(assignee_id__in=person_ids)
        qs = qs.filter(match_q)

        if status:
            qs = qs.filter(status=status)
        if priority:
            qs = qs.filter(priority=priority)
        if due_range:
            qs = qs.filter(due_date__range=due_range)

        qs = qs.select_related("assigner", "assignee", "main_label", "assignee_label")
        # id tiebreaker is load-bearing for stable pagination across tied created_at rows.
        qs = qs.order_by("-created_at", "id")

        total = qs.count()
        offset = (page - 1) * limit
        return list(qs[offset:offset + limit]), total

    @staticmethod
    def search_stickies(caller, keywords, due_range, page, limit):
        # Strictly private -- no tenant join, userId = caller only.
        qs = StickyNote.objects.filter(user_id=caller.id)

        match_q = _sticky_keyword_q(keywords)
        qs = qs.filter(match_q)

        if due_range:
            qs = qs.filter(due_at__range=due_range)

        qs = qs.order_by("-created_at", "id")

        total = qs.count()
        offset = (page - 1) * limit
        return list(qs[offset:offset + limit]), total
