from rest_framework import serializers

from apps.comments.serializers import serialize_comment


class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=3, max_length=100, trim_whitespace=True)
    source = serializers.ChoiceField(choices=["typed", "voice"], required=False, default="typed")
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=10)


def serialize_task_search_result(task, caller_id) -> dict:
    latest_comment = getattr(task, "latest_comment_obj", None)
    # assigneeLabel is private -- only ever populated when the caller IS that task's
    # assignee, same privacy rule as the task detail/list endpoints.
    is_assignee = str(task.assignee_id) == str(caller_id)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "parentTaskId": str(task.parent_task_id) if task.parent_task_id else None,
        "assigneeId": str(task.assignee_id),
        "assigneeName": task.assignee.name,
        "assignerId": str(task.assigner_id),
        "assignerName": task.assigner.name,
        "mainLabelId": str(task.main_label_id) if task.main_label_id else None,
        "mainLabelName": task.main_label.name if task.main_label_id else None,
        "assigneeLabelId": str(task.assignee_label_id) if is_assignee and task.assignee_label_id else None,
        "assigneeLabelName": task.assignee_label.name if is_assignee and task.assignee_label_id else None,
        "latestComment": serialize_comment(latest_comment) if latest_comment else None,
    }


def serialize_sticky_search_result(note) -> dict:
    return {
        "id": str(note.id),
        "text": note.text,
        "dueAt": note.due_at.isoformat() if note.due_at else None,
        "isPinned": note.is_pinned,
        "createdAt": note.created_at.isoformat(),
        "colorCode": note.color_code,
    }
