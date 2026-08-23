from rest_framework import serializers

from apps.common.enums import OrgRoleLevel

ALLOWED_IMAGE_CONTENT_TYPES = ["image/jpeg", "image/png", "image/heic"]


def broadcast_image_path(broadcast) -> str | None:
    # App-relative path to the streaming endpoint, not a pre-signed S3 URL --
    # see CLAUDE.md's Broadcast Notice business rules for why.
    return f"/broadcast-notices/{broadcast.id}/image" if broadcast.image_url else None


class BroadcastImagePresignSerializer(serializers.Serializer):
    broadcastId = serializers.UUIDField(source="broadcast_id")
    filename = serializers.CharField(max_length=255)
    contentType = serializers.ChoiceField(
        source="content_type", choices=ALLOWED_IMAGE_CONTENT_TYPES,
    )
    fileSize = serializers.IntegerField(source="file_size", min_value=1)


class BroadcastCreateSerializer(serializers.Serializer):
    messageJson = serializers.JSONField(source="message_json")
    messageHtml = serializers.CharField(source="message_html")
    audienceDeptIds = serializers.ListField(
        child=serializers.UUIDField(), source="audience_dept_ids", required=False, default=list,
    )
    audienceRoleLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=OrgRoleLevel.choices),
        source="audience_role_levels",
        required=False,
        default=list,
    )
    requiresAcknowledgement = serializers.BooleanField(
        source="requires_acknowledgement", required=False, default=False,
    )


class BroadcastUpdateSerializer(serializers.Serializer):
    messageJson = serializers.JSONField(source="message_json", required=False)
    messageHtml = serializers.CharField(source="message_html", required=False)
    audienceDeptIds = serializers.ListField(
        child=serializers.UUIDField(), source="audience_dept_ids", required=False,
    )
    audienceRoleLevels = serializers.ListField(
        child=serializers.ChoiceField(choices=OrgRoleLevel.choices),
        source="audience_role_levels",
        required=False,
    )
    requiresAcknowledgement = serializers.BooleanField(
        source="requires_acknowledgement", required=False,
    )
    # The only meaningful client-supplied value is null (detach the current image) --
    # the field stores an S3 object key server-side, never something a client can
    # legitimately construct, so a non-null value is rejected in the service.
    imageUrl = serializers.JSONField(source="image_url", required=False, allow_null=True)


def serialize_broadcast_list_item(broadcast, *, include_has_acknowledged: bool) -> dict:
    data = {
        "id": str(broadcast.id),
        "senderId": str(broadcast.sender_id),
        "senderName": broadcast.sender.name,
        "messageHtml": broadcast.message_html,
        "audienceDeptIds": [str(d.department_id) for d in broadcast.audience_depts.all()],
        "audienceDeptNames": [d.department.name for d in broadcast.audience_depts.all()],
        "audienceRoleLevels": [r.role_level for r in broadcast.audience_role_levels.all()],
        "requiresAcknowledgement": broadcast.requires_acknowledgement,
        "ackCount": broadcast.ack_count_annotated,
        "imageUrl": broadcast_image_path(broadcast),
        "status": broadcast.status,
        "expiresAt": broadcast.expires_at.isoformat() if broadcast.expires_at else None,
        "createdAt": broadcast.created_at.isoformat(),
        "updatedAt": broadcast.updated_at.isoformat(),
    }
    if include_has_acknowledged:
        data["hasAcknowledged"] = bool(broadcast.has_acknowledged_annotated)
    # Only present on view=sent rows, where BroadcastService.attach_audience_size
    # was called on the page first -- a live count of members currently matching
    # this row's audience scope (api-spec.md's GET /broadcast-notices?view=sent).
    audience_size = getattr(broadcast, "audience_size_annotated", None)
    if audience_size is not None:
        data["audienceSize"] = audience_size
    return data
