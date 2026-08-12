"""Global Search's standalone query-understanding layer.

Deliberately its own module rather than reusing/extending the voice-command
classifier (apps/tasks' voice intent handling) -- docs/api/global-search-ai-contract.md
§2: "kept deliberately independent so nothing in search can regress the voice-command
flow, and vice versa."

classify_search_query() is the only entry point apps/search/services.py calls. Its
result is cached per (query, source, userId, tenantId) so GET /search/tasks and
GET /search/stickies agree on the same interpretedQuery/entityScope regardless of
which is called first.
"""
import hashlib
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

from apps.common.enums import Priority, TaskStatus
from apps.labels.models import ProjectLabel
from apps.tasks.models import Task
from apps.tenants.models import TenantMembership

logger = logging.getLogger("bolo")

CACHE_TTL_SECONDS = 300
LEVENSHTEIN_THRESHOLD = 2
ROSTER_PROMPT_CAP = 200
AI_TIMEOUT_SECONDS = 8

# GPT is prompted for human-friendly values ("high", "open") -- these must be mapped
# to the real enum values before ever reaching a query filter. A real crash was found
# and fixed upstream when this normalization was missing (unrecognized value passed
# straight to the ORM); a value that isn't in the target enum is dropped (treated as
# no filter) rather than raised, per the same defense-in-depth fix.
PRIORITY_ALIASES = {
    "p1": Priority.P1, "urgent": Priority.P1, "critical": Priority.P1, "highest": Priority.P1,
    "high": Priority.P1,
    "p2": Priority.P2, "medium": Priority.P2, "med": Priority.P2,
    "p3": Priority.P3, "normal": Priority.P3, "low": Priority.P3,
    "p4": Priority.P4, "lowest": Priority.P4,
}
STATUS_ALIASES = {
    "draft": TaskStatus.DRAFT,
    "open": TaskStatus.OPEN,
    "in_progress": TaskStatus.IN_PROGRESS, "in progress": TaskStatus.IN_PROGRESS,
    "inprogress": TaskStatus.IN_PROGRESS, "progress": TaskStatus.IN_PROGRESS,
    "overdue": TaskStatus.OVERDUE, "late": TaskStatus.OVERDUE,
    "done_a": TaskStatus.DONE_A, "done a": TaskStatus.DONE_A,
    "done_d": TaskStatus.DONE_D, "done d": TaskStatus.DONE_D,
    "done": TaskStatus.DONE_D, "complete": TaskStatus.DONE_D, "completed": TaskStatus.DONE_D,
    "cancelled": TaskStatus.CANCELLED, "canceled": TaskStatus.CANCELLED,
}

SYSTEM_PROMPT = """You are the query-understanding layer for a task-management app's \
search box. Given a user's raw search text, extract structured intent to help a \
downstream SQL search.

Rules:
- Always output keywords and any person name in Latin/English script, even if the \
input was typed or transcribed in a different script (e.g. Devanagari, Tamil) -- \
transliterate before responding. The underlying data is stored in Latin script.
- Only ever name a person from the roster you are given below. Never invent a person \
who is not on that list. If the query text could plausibly be a known label name \
instead of a person's name, do not treat it as a person.
- entityScope is "task", "sticky", or "both" -- default to "both" unless the query \
clearly implies only one (e.g. "sticky about the vendor call" implies "sticky").
- filters.status/.priority should be your best human-friendly guess at intent \
("high", "open", "done", etc.) -- a downstream layer normalizes these to the real \
enum values, so do not worry about exact casing/spelling.
- filters.due is one of "today", "tomorrow", "this_week", or null.
- interpretedQuery is the corrected/cleaned form of the query, populated ONLY when \
you meaningfully corrected a typo or mis-transcription -- null if the raw query was \
already fine as-is.

Respond with strict JSON, no prose, matching exactly this shape:
{"resolvedKeywords": ["..."], "resolvedAssigneeName": "name or null", \
"entityScope": "task|sticky|both", \
"filters": {"status": "..."|null, "priority": "..."|null, "due": "..."|null}, \
"detectedLanguage": "...", "interpretedQuery": "corrected term or null"}"""


def _cache_key(query, source, user_id, tenant_id) -> str:
    # Hashed rather than embedding the raw query -- keeps the key length bounded
    # (queries run up to 100 chars) and avoids spaces/unicode that trip a
    # memcached-unsafe-character warning (harmless on this project's actual Redis
    # backend, but cheap to just not have).
    query_hash = hashlib.sha256(query.strip().lower().encode()).hexdigest()
    return f"search_classify:{tenant_id}:{user_id}:{source}:{query_hash}"


def _default_classification(query: str) -> dict:
    """The documented AI-unavailable fallback shape -- also doubles as the "no
    correction needed" baseline that a real AI response gets merged over."""
    return {
        "resolved_keywords": [query],
        "resolved_assignee": None,
        "entity_scope": "both",
        "filters": {"status": None, "priority": None, "due": None},
        "detected_language": None,
        "interpreted_query": None,
    }


def _tenant_roster(tenant_id) -> list[tuple[str, str]]:
    return list(
        TenantMembership.objects.filter(tenant_id=tenant_id)
        .select_related("user")
        .values_list("user_id", "user__name"),
    )


def _visible_label_names(user, tenant_id) -> list[str]:
    """Own-created labels union labels used as mainLabel on any task the caller is
    assigner/assignee of -- matches the documented 2026-07-24 grounding fix (labels
    weren't grounding correctly for non-creator callers before that)."""
    my_task_ids = Task.objects.filter(tenant_id=tenant_id).filter(
        Q(assigner=user) | Q(assignee=user),
    )
    return list(
        ProjectLabel.objects.filter(tenant_id=tenant_id)
        .filter(Q(created_by=user) | Q(main_label_tasks__in=my_task_ids))
        .values_list("name", flat=True)
        .distinct(),
    )


def call_openai_classify(query: str, source: str, roster: list, label_names: list) -> dict:
    """The single external-call boundary -- the only place the openai package is
    imported/used. Tests monkeypatch this function directly rather than hitting a
    real API, same pattern as apps/common/storage.py's boto3 calls."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    user_payload = json.dumps({
        "query": query,
        "source": source,
        "roster": [name for _, name in roster][:ROSTER_PROMPT_CAP],
        "knownLabels": label_names[:ROSTER_PROMPT_CAP],
    })
    response = client.chat.completions.create(
        model=settings.OPENAI_SEARCH_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        response_format={"type": "json_object"},
        timeout=AI_TIMEOUT_SECONDS,
    )
    return json.loads(response.choices[0].message.content)


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current_row[j] = min(
                current_row[j - 1] + 1,
                previous_row[j] + 1,
                previous_row[j - 1] + cost,
            )
        previous_row = current_row
    return previous_row[-1]


def _build_resolution(matches: list[tuple[str, str]]) -> dict:
    if len(matches) == 1:
        user_id, name = matches[0]
        return {"id": str(user_id), "name": name, "ambiguous": False, "candidates": None}
    return {
        "id": None,
        "name": None,
        "ambiguous": True,
        "candidates": [str(user_id) for user_id, _ in matches],
    }


def resolve_person(name: str, roster: list[tuple[str, str]]) -> dict | None:
    """Resolves an AI-proposed person name against the real tenant roster.

    Exact case-insensitive match first (2+ ties widen to an OR across every tied
    candidate's id -- never guessed). Falls back to a deterministic Levenshtein-distance
    check ("off by 1-2 characters, and nothing else in the roster is closer") to catch
    a name the AI didn't reliably self-correct (docs/engineering/testing-strategy.md's
    "Sarang" heard as "Tarang" bug) -- a code-level check, not a probabilistic one.
    """
    search_term = (name or "").strip().lower()
    if not search_term or not roster:
        return None

    exact_matches = [(uid, uname) for uid, uname in roster if uname.lower() == search_term]
    if exact_matches:
        return _build_resolution(exact_matches)

    scored = [
        (_levenshtein_distance(search_term, uname.lower()), uid, uname)
        for uid, uname in roster
    ]
    scored = [item for item in scored if item[0] <= LEVENSHTEIN_THRESHOLD]
    if not scored:
        return None

    scored.sort(key=lambda item: item[0])
    best_distance = scored[0][0]
    tied = [(uid, uname) for distance, uid, uname in scored if distance == best_distance]
    return _build_resolution(tied)


def _normalize_status(value) -> str | None:
    if not value:
        return None
    normalized = STATUS_ALIASES.get(str(value).strip().lower())
    return normalized if normalized in TaskStatus.values else None


def _normalize_priority(value) -> str | None:
    if not value:
        return None
    normalized = PRIORITY_ALIASES.get(str(value).strip().lower())
    return normalized if normalized in Priority.values else None


def _normalize_ai_output(raw: dict, query: str, roster: list[tuple[str, str]]) -> dict:
    keywords = raw.get("resolvedKeywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = [query]

    ai_name = raw.get("resolvedAssigneeName")
    resolved_assignee = resolve_person(ai_name, roster) if ai_name else None

    entity_scope = raw.get("entityScope")
    if entity_scope not in ("task", "sticky", "both"):
        entity_scope = "both"

    filters_raw = raw.get("filters") or {}
    due = filters_raw.get("due")
    if due not in ("today", "tomorrow", "this_week"):
        due = None

    interpreted_query = raw.get("interpretedQuery")
    if not interpreted_query or interpreted_query.strip().lower() == query.strip().lower():
        interpreted_query = None

    return {
        "resolved_keywords": keywords,
        "resolved_assignee": resolved_assignee,
        "entity_scope": entity_scope,
        "filters": {
            "status": _normalize_status(filters_raw.get("status")),
            "priority": _normalize_priority(filters_raw.get("priority")),
            "due": due,
        },
        "detected_language": raw.get("detectedLanguage"),
        "interpreted_query": interpreted_query,
    }


def classify_search_query(query: str, source: str, tenant_id, user_id, user) -> dict:
    cache_key = _cache_key(query, source, user_id, tenant_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    roster = _tenant_roster(tenant_id)

    raw = None
    if settings.OPENAI_API_KEY:
        try:
            label_names = _visible_label_names(user, tenant_id)
            raw = call_openai_classify(query, source, roster, label_names)
        except Exception:
            # Never a hard failure -- docs/api/global-search-ai-contract.md §6:
            # "if the AI call errors, times out, or is unavailable, search falls
            # back to a raw keyword match against resolvedKeywords: [query]."
            logger.warning("search_classify_ai_unavailable", exc_info=True)
            raw = None

    result = _normalize_ai_output(raw, query, roster) if raw is not None else _default_classification(query)
    cache.set(cache_key, result, timeout=CACHE_TTL_SECONDS)
    return result
