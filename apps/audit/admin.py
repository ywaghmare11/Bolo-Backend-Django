from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "tenant", "actor", "actor_type", "action", "entity_type",
        "entity_id", "created_at",
    )
    list_filter = ("tenant", "actor_type", "action")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
