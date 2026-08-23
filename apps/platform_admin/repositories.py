from apps.common.exceptions import NotFoundError
from apps.platform_admin.models import PlatformAdmin, PlatformAdminOtpCode


class PlatformAdminRepository:
    @staticmethod
    def get_by_email(email: str) -> PlatformAdmin:
        try:
            return PlatformAdmin.objects.get(email=email)
        except PlatformAdmin.DoesNotExist:
            raise NotFoundError("PlatformAdmin", email) from None

    @staticmethod
    def get_by_id(admin_id) -> PlatformAdmin:
        try:
            return PlatformAdmin.objects.get(id=admin_id)
        except PlatformAdmin.DoesNotExist:
            raise NotFoundError("PlatformAdmin", admin_id) from None


class PlatformAdminOtpRepository:
    """Mirrors apps.auth.repositories.OtpRepository exactly, on
    PlatformAdminOtpCode instead of OtpCode -- deliberately duplicated, not
    shared, per the "fully parallel auth flow" design (docs/ops/security.md)."""

    @staticmethod
    def get_by_email(email: str) -> PlatformAdminOtpCode | None:
        return PlatformAdminOtpCode.objects.filter(email=email).first()

    @staticmethod
    def upsert(email: str, hashed_code: str, expires_at) -> PlatformAdminOtpCode:
        PlatformAdminOtpCode.objects.filter(email=email).delete()
        return PlatformAdminOtpCode.objects.create(
            email=email, hashed_code=hashed_code, expires_at=expires_at,
        )

    @staticmethod
    def delete_by_email(email: str) -> None:
        PlatformAdminOtpCode.objects.filter(email=email).delete()

    @staticmethod
    def increment_attempts(otp: PlatformAdminOtpCode) -> PlatformAdminOtpCode:
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return otp

    @staticmethod
    def lock(otp: PlatformAdminOtpCode, until) -> PlatformAdminOtpCode:
        otp.locked_until = until
        otp.save(update_fields=["locked_until"])
        return otp
