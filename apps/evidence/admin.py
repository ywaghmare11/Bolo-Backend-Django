from django.contrib import admin

from .models import Evidence


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ("id", "task", "uploader", "file_name", "file_type", "file_size", "created_at")
    search_fields = ("file_name",)
    list_filter = ("file_type",)
