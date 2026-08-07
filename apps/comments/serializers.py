from rest_framework import serializers


class CommentCreateSerializer(serializers.Serializer):
    text = serializers.CharField()


class CommentUpdateSerializer(serializers.Serializer):
    text = serializers.CharField()


def serialize_comment(comment) -> dict:
    return {
        "id": str(comment.id),
        "authorId": str(comment.author_id),
        "authorName": comment.author.name,
        "text": comment.text,
        "isEdited": comment.is_edited,
        "createdAt": comment.created_at.isoformat(),
        "updatedAt": comment.updated_at.isoformat(),
    }
