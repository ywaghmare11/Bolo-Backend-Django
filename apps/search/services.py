from apps.search.ai_classify import classify_search_query
from apps.search.repositories import SearchRepository, resolve_due_range
from apps.search.serializers import serialize_sticky_search_result, serialize_task_search_result
from apps.tasks.repositories import TaskRepository


def _person_ids(resolved_assignee) -> list:
    if not resolved_assignee:
        return []
    if resolved_assignee.get("ambiguous"):
        return resolved_assignee.get("candidates") or []
    return [resolved_assignee["id"]] if resolved_assignee.get("id") else []


class SearchService:
    @staticmethod
    def search_tasks(user, tenant_id, q, source, page, limit):
        classification = classify_search_query(q, source, tenant_id, user.id, user)
        due_range = resolve_due_range(classification["filters"]["due"])

        results, total = SearchRepository.search_tasks(
            tenant_id,
            user,
            classification["resolved_keywords"],
            _person_ids(classification["resolved_assignee"]),
            classification["filters"]["status"],
            classification["filters"]["priority"],
            due_range,
            page,
            limit,
        )
        results = TaskRepository.attach_latest_comments(results)

        return {
            "success": True,
            "message": "",
            "query": q,
            "interpretedQuery": classification["interpreted_query"],
            "entityScope": classification["entity_scope"],
            "data": [serialize_task_search_result(t, user.id) for t in results],
            "pagination": {"page": page, "limit": limit, "total": total},
        }

    @staticmethod
    def search_stickies(user, tenant_id, q, source, page, limit):
        classification = classify_search_query(q, source, tenant_id, user.id, user)
        due_range = resolve_due_range(classification["filters"]["due"])

        results, total = SearchRepository.search_stickies(
            user, classification["resolved_keywords"], due_range, page, limit,
        )

        return {
            "success": True,
            "message": "",
            "query": q,
            "interpretedQuery": classification["interpreted_query"],
            "entityScope": classification["entity_scope"],
            "data": [serialize_sticky_search_result(n) for n in results],
            "pagination": {"page": page, "limit": limit, "total": total},
        }
