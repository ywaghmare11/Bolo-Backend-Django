from django.contrib import admin

from .models import PlatformAdmin, PlatformAdminOtpCode


@admin.register(PlatformAdmin)
class PlatformAdminAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "email", "created_at")
    search_fields = ("name", "email")


@admin.register(PlatformAdminOtpCode)
class PlatformAdminOtpCodeAdmin(admin.ModelAdmin):
    # hashed_code deliberately excluded -- never surface OTP material, even hashed
    list_display = ("id", "email", "expires_at", "attempts", "locked_until", "created_at")
    exclude = ("hashed_code",)
    search_fields = ("email",)
