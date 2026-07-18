from django.contrib import admin

from .models import OtpCode, RefreshToken


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    # hashed_code deliberately excluded -- never surface OTP material, even hashed
    list_display = ("id", "email", "expires_at", "attempts", "locked_until", "created_at")
    exclude = ("hashed_code",)
    search_fields = ("email",)


@admin.register(RefreshToken)
class RefreshTokenAdmin(admin.ModelAdmin):
    # token_hash deliberately excluded -- never surface token material, even hashed
    list_display = ("id", "user", "expires_at", "revoked_at", "created_at")
    exclude = ("token_hash",)
    search_fields = ("user__email",)
