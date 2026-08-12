import re

from rest_framework import serializers

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_color_code(value):
    if not HEX_COLOR_RE.match(value):
        raise serializers.ValidationError("colorCode must be a hex color like #FEF3C7")
    return value


class StickyNoteCreateSerializer(serializers.Serializer):
    text = serializers.CharField()
    dueAt = serializers.DateTimeField(source="due_at", required=False, allow_null=True, default=None)
    isPinned = serializers.BooleanField(source="is_pinned", required=False, default=False)
    colorCode = serializers.CharField(
        source="color_code",
        max_length=7,
        required=False,
        default="#FEF3C7",
        validators=[_validate_color_code],
    )


class StickyNoteUpdateSerializer(serializers.Serializer):
    text = serializers.CharField(required=False)
    dueAt = serializers.DateTimeField(source="due_at", required=False, allow_null=True)
    isPinned = serializers.BooleanField(source="is_pinned", required=False)
    colorCode = serializers.CharField(
        source="color_code", max_length=7, required=False, validators=[_validate_color_code],
    )


class StickyNotePromoteSerializer(serializers.Serializer):
    assigneeId = serializers.UUIDField(source="assignee_id")
    dueDate = serializers.DateTimeField(source="due_date", required=False, allow_null=True, default=None)


def serialize_sticky_note(note) -> dict:
    return {
        "id": str(note.id),
        "text": note.text,
        "colorCode": note.color_code,
        "dueAt": note.due_at.isoformat() if note.due_at else None,
        "isPinned": note.is_pinned,
        "promotedToTaskId": str(note.promoted_to_task_id) if note.promoted_to_task_id else None,
        "createdAt": note.created_at.isoformat(),
        "updatedAt": note.updated_at.isoformat(),
    }
