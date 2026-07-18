from django.contrib import admin

from .models import StickyNote


@admin.register(StickyNote)
class StickyNoteAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "due_at", "is_pinned", "promoted_to_task", "created_at")
    list_filter = ("is_pinned",)
