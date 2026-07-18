from django.contrib import admin

from .models import ProjectLabel


@admin.register(ProjectLabel)
class ProjectLabelAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "tenant", "color_code", "created_by", "created_at")
    search_fields = ("name",)
    list_filter = ("tenant",)
