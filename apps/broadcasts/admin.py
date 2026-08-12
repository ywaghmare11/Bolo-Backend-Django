from django.contrib import admin

from .models import BroadcastNotice

# BroadcastAcknowledgement, BroadcastNoticeAudienceDept, and
# BroadcastNoticeAudienceRoleLevel are not registered here -- Django admin cannot yet
# register a model with a composite primary key (see models.CompositePrimaryKey).


@admin.register(BroadcastNotice)
class BroadcastNoticeAdmin(admin.ModelAdmin):
    list_display = (
        "id", "tenant", "sender", "status",
        "requires_acknowledgement", "expires_at", "created_at",
    )
    list_filter = ("tenant", "status")
