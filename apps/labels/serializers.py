import re

from rest_framework import serializers

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_color_code(value):
    if not HEX_COLOR_RE.match(value):
        raise serializers.ValidationError("colorCode must be a hex color like #3B82F6")
    return value


class LabelCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    colorCode = serializers.CharField(
        source="color_code",
        max_length=7,
        required=False,
        default="#6B7280",
        validators=[_validate_color_code],
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")


class LabelUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    colorCode = serializers.CharField(
        source="color_code", max_length=7, required=False, validators=[_validate_color_code],
    )
    description = serializers.CharField(required=False, allow_blank=True)


class LabelListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    colorCode = serializers.CharField(source="color_code")
    createdAt = serializers.DateTimeField(source="created_at")
