from django.db import models

from apps.common.models import CreatedOnlyModel, TimestampedModel


class PlatformAdmin(TimestampedModel):
    """Superadmin identity -- cross-tenant, entirely outside RLS/tenant scoping.
    Not a User row, so AuditLog.actor_id stays null for actions it takes
    (see AuditActorType.PLATFORM_ADMIN)."""

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)

    class Meta:
        db_table = "platform_admins"

    def __str__(self):
        return self.email


class PlatformAdminOtpCode(CreatedOnlyModel):
    """Separate OTP flow from the tenant-scoped OtpCode -- same shape, different
    identity space. No FK to PlatformAdmin, lookup is by email string."""

    email = models.EmailField(unique=True)
    hashed_code = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "platform_admin_otp_codes"

    def __str__(self):
        return self.email
