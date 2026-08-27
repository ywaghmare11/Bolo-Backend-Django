"""Cache-aside helpers for the read-heavy / write-light endpoints (ROADMAP.md
Phase 12): the dashboard tab counts (`GET /tasks/counts`) and the per-user label
picker list (`GET /labels/mine` + `/labels/shared`, identical query).

Both are read on nearly every page load and change only on a handful of explicit
write paths, so they're cached with a short TTL *and* busted from those write
paths by hand -- the TTL alone is not enough for correctness (a user who just
created a task would see a stale badge count for up to the whole TTL). The TTL is
only a backstop for a bust we forgot to wire or a cross-process race; the
`bust_*` calls are what actually keep the cached value right.

Key shapes (all under Django's single "default" alias, which points at Redis in
prod / LocMem in tests):

    tasks:counts:<tenant_id>:<user_id>   -> dict of int, TASK_COUNTS_TTL
    labels:list:<user_id>                -> list[dict], LABEL_LIST_TTL
"""
from django.core.cache import cache

# 5 minutes: counts move often (every task create / status change), so a short
# window keeps the blast radius of any missed bust small.
TASK_COUNTS_TTL = 60 * 5

# 10 minutes: labels change rarely (a user edits their own small label pool by
# hand), so a longer window is safe and cuts more repeat queries.
LABEL_LIST_TTL = 60 * 10


def task_counts_key(tenant_id, user_id) -> str:
    return f"tasks:counts:{tenant_id}:{user_id}"


def label_list_key(user_id) -> str:
    return f"labels:list:{user_id}"


def bust_task_counts(tenant_id, *user_ids) -> None:
    """Invalidate the cached tab counts for every user whose totals a write just
    changed -- typically the task's assigner and assignee (and, on reassignment,
    the previous assignee too). `None`/duplicate ids are ignored."""
    keys = {task_counts_key(tenant_id, uid) for uid in user_ids if uid}
    if keys:
        cache.delete_many(list(keys))


def bust_label_list(user_id) -> None:
    """Invalidate a user's cached label list after they create / rename / recolor
    / delete one of their own labels."""
    cache.delete(label_list_key(user_id))
