from django.db import models

from apps.common.models import CreatedOnlyModel, TimestampedModel


class OtpCode(CreatedOnlyModel):
    # transient -- row deleted immediately after successful verify; no FK to User,
    # lookup is by email string (a 15-min cleanup job sweeps expired unlocked rows)
    email = models.EmailField(unique=True)
    hashed_code = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "otp_codes"

    def __str__(self):
        return self.email


class RefreshToken(TimestampedModel):
    """Opaque, DB-backed refresh token -- NOT a JWT. Rotated on every use
    (docs/ops/security.md Authentication section, added this phase -- a
    deliberate deviation from the original "no refresh tokens" decision).
    Stored hashed, same pattern as OtpCode.hashed_code."""

    user = models.ForeignKey(
        "users.User", on_delete=models.PROTECT, related_name="refresh_tokens",
    )
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refresh_tokens"
        indexes = [
            models.Index(fields=["token_hash"], name="idx_refresh_token_hash"),
        ]

    def __str__(self):
        return f"RefreshToken({self.id})"
