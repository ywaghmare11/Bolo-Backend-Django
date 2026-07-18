from rest_framework import serializers


class LabelCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    colorCode = serializers.CharField(
        source="color_code", max_length=7, required=False, default="#6B7280",
    )
    description = serializers.CharField(required=False, allow_blank=True, default="")


class LabelListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    colorCode = serializers.CharField(source="color_code")
    createdAt = serializers.DateTimeField(source="created_at")
