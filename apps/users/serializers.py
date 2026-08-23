from rest_framework import serializers

from apps.common.enums import Language

ALLOWED_IMAGE_CONTENT_TYPES = ["image/jpeg", "image/png", "image/heic"]


def profile_picture_path(user) -> str | None:
    # App-relative path to the streaming endpoint, never a pre-signed S3 URL --
    # same pattern as Evidence/Broadcast image/Voice recording.
    return f"/users/{user.id}/profile-picture/file" if user.profile_pic_url else None


class MeUpdateSerializer(serializers.Serializer):
    """Only name and preferredLang -- api-spec.md's PATCH /me is explicit that
    a user can only update their own name and preferred language."""

    name = serializers.CharField(max_length=255, required=False)
    preferredLang = serializers.ChoiceField(
        source="preferred_lang", choices=Language.choices, required=False,
    )


class ProfilePicturePresignSerializer(serializers.Serializer):
    contentType = serializers.ChoiceField(source="content_type", choices=ALLOWED_IMAGE_CONTENT_TYPES)
    fileSize = serializers.IntegerField(source="file_size", min_value=1)


def serialize_me(user, membership) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "profilePicUrl": profile_picture_path(user),
        "preferredLang": user.preferred_lang,
        "tenantId": str(membership.tenant_id),
        "tenantName": membership.tenant.name,
        "roleLevel": membership.role_level,
        "roleLabel": membership.role_label,
        "departmentId": str(membership.department_id) if membership.department_id else None,
        "departmentName": membership.department.name if membership.department_id else None,
        "reportsToId": str(membership.reports_to_id) if membership.reports_to_id else None,
        "reportsToName": membership.reports_to.name if membership.reports_to_id else None,
        "canBroadcast": membership.can_broadcast,
    }
