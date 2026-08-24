"""Natural-language task field extraction (ROADMAP.md Phase 9).

Deliberately its own module, same shape as apps/search/ai_classify.py: the only
place the openai package is imported/used for this feature, isolated behind
call_openai_extract() so tests can monkeypatch it instead of hitting a real API.

Called synchronously inside the request, with a tight timeout, rather than as a
Celery job the frontend polls for -- documented choice, not an oversight. The
caller needs this result before it can render the create-task form; Celery's
job-id/poll shape would need a second endpoint this project's contract doesn't
have, purely to work around a call that already degrades cleanly in-process.
AI_TIMEOUT_SECONDS plus the try/except fallback below is what actually satisfies
Phase 9's requirement -- "must keep working if OpenAI is down, slow, or
unconfigured" -- Celery retries would only help a background job, not a request
still waiting on its response.
"""
import json
import logging
from datetime import date

from django.conf import settings
from django.utils import timezone

from apps.common.enums import Priority

logger = logging.getLogger("bolo")

AI_TIMEOUT_SECONDS = 8
TEXT_MIN_LENGTH = 3
TEXT_MAX_LENGTH = 2000

# Same alias table shape as apps/search/ai_classify.py's PRIORITY_ALIASES --
# GPT is prompted for a human-friendly urgency word, never the raw enum value,
# so an unrecognized value must be dropped (treated as "no suggestion") rather
# than reaching the create-task form as an invalid priority.
PRIORITY_ALIASES = {
    "p1": Priority.P1, "urgent": Priority.P1, "critical": Priority.P1, "highest": Priority.P1,
    "high": Priority.P1,
    "p2": Priority.P2, "medium": Priority.P2, "med": Priority.P2,
    "p3": Priority.P3, "normal": Priority.P3, "low": Priority.P3,
    "p4": Priority.P4, "lowest": Priority.P4,
}

SYSTEM_PROMPT_TEMPLATE = """You are the task-creation extraction layer for a task-management app. Given a user's raw text (typed, or transcribed from voice), extract structured fields to pre-fill a "create task" form. The user still reviews and edits every field before anything is saved -- you are drafting a suggestion, never creating a task.

Today's date is {today}.

Rules:
- Always output title and personName in Latin/English script, even if the input was typed or transcribed in a different script (e.g. Devanagari, Tamil) -- transliterate before responding. The underlying app data is stored in Latin script.
- title is a short imperative summary of the task, not a verbatim copy of the whole input.
- personName is who the task should be assigned to, exactly as stated in the text, or null if no assignee is mentioned. Never invent a name that isn't stated.
- dueDate is an absolute ISO 8601 date (YYYY-MM-DD), resolved from any relative reference ("tomorrow", "by Friday", "next week") against today's date above. null if no due date is mentioned or implied.
- priority is your best human-friendly guess at urgency ("high", "urgent", "low", etc.) only if stated or clearly implied by the text, otherwise null -- a downstream layer normalizes this to the app's real priority values, so do not worry about exact casing/spelling.

Respond with strict JSON, no prose, matching exactly this shape:
{{"title": "... or null", "personName": "... or null", "dueDate": "YYYY-MM-DD or null", "priority": "... or null"}}"""


def _default_extraction() -> dict:
    """The documented AI-unavailable fallback -- every field null, so the
    frontend renders an empty create-task form for the user to fill by hand
    rather than blocking on, or erroring out of, task creation."""
    return {"title": None, "assignee_hint": None, "due_date": None, "priority": None}


def call_openai_extract(text: str) -> dict:
    """The single external-call boundary. Tests monkeypatch this function
    directly rather than hitting a real API, same pattern as
    apps.search.ai_classify.call_openai_classify."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(today=timezone.now().date().isoformat())
    response = client.chat.completions.create(
        model=settings.OPENAI_EXTRACT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        timeout=AI_TIMEOUT_SECONDS,
    )
    return json.loads(response.choices[0].message.content)


def _normalize_text(value, max_length=255) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:max_length]


def _normalize_priority(value) -> str | None:
    if not value:
        return None
    normalized = PRIORITY_ALIASES.get(str(value).strip().lower())
    return normalized if normalized in Priority.values else None


def _normalize_due_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _normalize_extraction(raw: dict) -> dict:
    return {
        "title": _normalize_text(raw.get("title")),
        "assignee_hint": _normalize_text(raw.get("personName")),
        "due_date": _normalize_due_date(raw.get("dueDate")),
        "priority": _normalize_priority(raw.get("priority")),
    }


def extract_fields(text: str) -> dict:
    if not settings.OPENAI_API_KEY:
        return _default_extraction()

    try:
        raw = call_openai_extract(text)
    except Exception:
        # Never a hard failure -- covers timeout, network error, and malformed
        # (non-JSON) AI output, all of which json.loads() inside
        # call_openai_extract would otherwise raise on. api-spec.md §23:
        # "if the AI call errors, times out, or is unavailable, the endpoint
        # still returns 200 with every field null."
        logger.warning("task_extract_ai_unavailable", exc_info=True)
        return _default_extraction()

    if not isinstance(raw, dict):
        return _default_extraction()

    return _normalize_extraction(raw)
