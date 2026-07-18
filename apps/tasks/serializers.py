from rest_framework import serializers

from apps.common.enums import Priority


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    assigneeId = serializers.UUIDField(source="assignee_id")
    dueDate = serializers.DateTimeField(source="due_date", required=False, allow_null=True, default=None)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False, default=Priority.P3)
    mainLabelId = serializers.UUIDField(source="main_label_id", required=False, allow_null=True, default=None)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class TaskUpdateSerializer(serializers.Serializer):
    """No `title` field at all -- deliberately. DRF would otherwise just
    silently drop an undeclared field instead of rejecting it, so the view
    checks raw request.data for a "title" key (-> 400 TITLE_IMMUTABLE)
    before this serializer ever runs."""

    assigneeId = serializers.UUIDField(source="assignee_id", required=False)
    dueDate = serializers.DateTimeField(source="due_date", required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=Priority.choices, required=False)
    mainLabelId = serializers.UUIDField(source="main_label_id", required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)


def serialize_task_created(task) -> dict:
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "assignerId": str(task.assigner_id),
        "assigneeId": str(task.assignee_id),
        "priority": task.priority,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "parentTaskId": str(task.parent_task_id) if task.parent_task_id else None,
        "createdAt": task.created_at.isoformat(),
    }


def serialize_comment(comment) -> dict:
    return {
        "id": str(comment.id),
        "authorId": str(comment.author_id),
        "authorName": comment.author.name,
        "text": comment.text,
        "isEdited": comment.is_edited,
        "createdAt": comment.created_at.isoformat(),
    }


def serialize_evidence(evidence) -> dict:
    return {
        "id": str(evidence.id),
        "fileUrl": evidence.file_url,
        "fileName": evidence.file_name,
        "fileSize": evidence.file_size,
        "fileType": evidence.file_type,
        "caption": evidence.caption,
        "uploaderId": str(evidence.uploader_id),
        "uploaderName": evidence.uploader.name,
        "createdAt": evidence.created_at.isoformat(),
    }


def serialize_subtask_summary(subtask) -> dict:
    return {
        "id": str(subtask.id),
        "title": subtask.title,
        "status": subtask.status,
        "assigneeId": str(subtask.assignee_id),
        "assigneeName": subtask.assignee.name,
        "dueDate": subtask.due_date.isoformat() if subtask.due_date else None,
        "priority": subtask.priority,
    }


def serialize_voice_recording(vr) -> dict | None:
    if vr is None:
        return None
    return {
        "rawTranscript": vr.raw_transcript,
        "language": vr.language,
        "durationSecs": vr.duration_secs,
        "confidenceScore": vr.confidence_score,
        "hasAudio": bool(vr.audio_url),
    }


class TaskListItemSerializer(serializers.Serializer):
    def to_representation(self, instance):
        latest_comment = getattr(instance, "latest_comment_obj", None)
        return {
            "id": str(instance.id),
            "title": instance.title,
            "status": instance.status,
            "acceptanceStatus": instance.acceptance_status,
            "priority": instance.priority,
            "dueDate": instance.due_date.isoformat() if instance.due_date else None,
            "isArchived": instance.is_archived,
            "parentTaskId": str(instance.parent_task_id) if instance.parent_task_id else None,
            "assignerId": str(instance.assigner_id),
            "assignerName": instance.assigner.name,
            "assigneeId": str(instance.assignee_id),
            "assigneeName": instance.assignee.name,
            "mainLabelId": str(instance.main_label_id) if instance.main_label_id else None,
            "projectLabelName": instance.main_label.name if instance.main_label_id else None,
            "subtaskCount": instance.subtask_count_annotated,
            "doneSubtaskCount": instance.done_subtask_count_annotated,
            "commentCount": instance.comment_count_annotated,
            "latestComment": serialize_comment(latest_comment) if latest_comment else None,
            "createdAt": instance.created_at.isoformat(),
            "updatedAt": instance.updated_at.isoformat(),
        }


class TaskDetailSerializer(serializers.Serializer):
    def to_representation(self, instance):
        task = instance["task"]
        my_personal_labels = instance["my_personal_labels"]
        return {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "acceptanceStatus": task.acceptance_status,
            "priority": task.priority,
            "dueDate": task.due_date.isoformat() if task.due_date else None,
            "description": task.description,
            "isArchived": task.is_archived,
            "parentTaskId": str(task.parent_task_id) if task.parent_task_id else None,
            "acceptedAt": task.accepted_at.isoformat() if task.accepted_at else None,
            "assignerId": str(task.assigner_id),
            "assignerName": task.assigner.name,
            "assigneeId": str(task.assignee_id),
            "assigneeName": task.assignee.name,
            "mainLabelId": str(task.main_label_id) if task.main_label_id else None,
            "projectLabelName": task.main_label.name if task.main_label_id else None,
            "myPersonalLabels": [label.name for label in my_personal_labels],
            "subtasks": [serialize_subtask_summary(s) for s in task.subtasks.select_related("assignee").all()],
            "comments": [serialize_comment(c) for c in task.comments.select_related("author").all()],
            "evidence": [serialize_evidence(e) for e in task.evidence.select_related("uploader").all()],
            "voiceRecording": serialize_voice_recording(getattr(task, "voice_recording", None)),
            "createdAt": task.created_at.isoformat(),
            "updatedAt": task.updated_at.isoformat(),
        }
