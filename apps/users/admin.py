from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "email", "tenant", "preferred_lang", "created_at")
    search_fields = ("name", "email")
    list_filter = ("tenant", "preferred_lang")
