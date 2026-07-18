from django.contrib import admin

from .models import Notification, NudgeSkipCounter


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id", "tenant", "recipient", "type", "entity_type", "entity_id",
        "is_read", "created_at",
    )
    list_filter = ("tenant", "type", "is_read")


@admin.register(NudgeSkipCounter)
class NudgeSkipCounterAdmin(admin.ModelAdmin):
    list_display = (
        "id", "tenant", "entity_type", "entity_id", "nudge_kind",
        "skip_count", "escalated_at", "last_shown_at",
    )
    list_filter = ("tenant", "nudge_kind")
