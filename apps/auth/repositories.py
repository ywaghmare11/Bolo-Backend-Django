from django.utils import timezone

from apps.auth.models import OtpCode, RefreshToken


class OtpRepository:
    @staticmethod
    def get_by_email(email: str) -> OtpCode | None:
        return OtpCode.objects.filter(email=email).first()

    @staticmethod
    def upsert(email: str, hashed_code: str, expires_at) -> OtpCode:
        """Delete-then-create rather than update -- resets created_at (auto_now_add)
        so the 60s resend-rate-limit check has an accurate 'last sent' timestamp."""
        OtpCode.objects.filter(email=email).delete()
        return OtpCode.objects.create(
            email=email, hashed_code=hashed_code, expires_at=expires_at,
        )

    @staticmethod
    def delete_by_email(email: str) -> None:
        OtpCode.objects.filter(email=email).delete()

    @staticmethod
    def increment_attempts(otp: OtpCode) -> OtpCode:
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return otp

    @staticmethod
    def lock(otp: OtpCode, until) -> OtpCode:
        otp.locked_until = until
        otp.save(update_fields=["locked_until"])
        return otp


class RefreshTokenRepository:
    @staticmethod
    def create(user, token_hash: str, expires_at) -> RefreshToken:
        return RefreshToken.objects.create(
            user=user, token_hash=token_hash, expires_at=expires_at,
        )

    @staticmethod
    def get_valid_by_hash(token_hash: str) -> RefreshToken | None:
        return RefreshToken.objects.filter(
            token_hash=token_hash, revoked_at__isnull=True, expires_at__gt=timezone.now(),
        ).select_related("user").first()

    @staticmethod
    def get_by_hash(token_hash: str) -> RefreshToken | None:
        """Includes revoked/expired rows -- used to detect reuse of an
        already-revoked token as a theft signal."""
        return RefreshToken.objects.filter(token_hash=token_hash).select_related("user").first()

    @staticmethod
    def revoke(refresh_token: RefreshToken) -> None:
        refresh_token.revoked_at = timezone.now()
        refresh_token.save(update_fields=["revoked_at", "updated_at"])

    @staticmethod
    def revoke_all_for_user(user) -> None:
        RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
            revoked_at=timezone.now(),
        )
