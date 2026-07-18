from django.contrib import admin

from .models import Task, VoiceRecording


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "tenant", "assigner", "assignee", "status",
        "acceptance_status", "priority", "due_date", "main_label",
        "assignee_label", "is_archived", "parent_task",
    )
    search_fields = ("title",)
    list_filter = ("tenant", "status", "priority", "is_archived")


@admin.register(VoiceRecording)
class VoiceRecordingAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "tenant", "language", "duration_secs", "confidence_score", "created_at")
    list_filter = ("tenant", "language")
