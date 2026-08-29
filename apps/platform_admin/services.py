import hashlib
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.email import EmailService
from apps.common.enums import OrgRoleLevel
from apps.common.exceptions import AppError, NotFoundError, ValidationError
from apps.platform_admin.repositories import PlatformAdminOtpRepository, PlatformAdminRepository
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.repositories import MembershipRepository, TenantRepository
from apps.users.repositories import UserRepository

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

OTP_EXPIRY_MINUTES = 10
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 3
OTP_LOCKOUT_MINUTES = 15


class PlatformAdminAuthService:
    """Mirrors apps.auth.services.AuthService's OTP flow -- deliberately
    duplicated on PlatformAdminOtpCode/PlatformAdmin rather than shared, so
    a platform-admin OTP request can never collide with a tenant user's
    in-flight OTP on the same email (docs/ops/security.md)."""

    @staticmethod
    def request_otp(email: str) -> None:
        try:
            PlatformAdminRepository.get_by_email(email)
        except NotFoundError:
            raise AppError(f"No platform admin found for {email}", 404, "ADMIN_NOT_FOUND") from None

        existing = PlatformAdminOtpRepository.get_by_email(email)
        resend_cutoff = timezone.now() - timedelta(seconds=OTP_RESEND_SECONDS)
        if existing and existing.created_at > resend_cutoff:
            raise AppError(
                "Too many OTP requests. Try again in 60 seconds.", 429, "RATE_LIMITED",
            )

        code = f"{secrets.randbelow(1_000_000):06d}"
        hashed_code = hashlib.sha256(code.encode()).hexdigest()
        expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        PlatformAdminOtpRepository.upsert(email, hashed_code, expires_at)
        EmailService.send_otp_email(email, code)

    @staticmethod
    def verify_otp(email: str, otp: str) -> dict:
        """Returns {"admin", "access_token"}."""
        otp_row = PlatformAdminOtpRepository.get_by_email(email)
        if not otp_row:
            raise AppError("OTP expired or not found", 400, "OTP_EXPIRED")

        if otp_row.locked_until and otp_row.locked_until > timezone.now():
            raise AppError(
                "Too many failed attempts. Try again later.",
                429, "RATE_LIMITED", data={"attemptsRemaining": 0},
            )

        if otp_row.expires_at < timezone.now():
            PlatformAdminOtpRepository.delete_by_email(email)
            raise AppError("OTP expired", 400, "OTP_EXPIRED")

        hashed_code = hashlib.sha256(otp.encode()).hexdigest()
        if hashed_code != otp_row.hashed_code:
            otp_row = PlatformAdminOtpRepository.increment_attempts(otp_row)
            if otp_row.attempts >= OTP_MAX_ATTEMPTS:
                PlatformAdminOtpRepository.lock(
                    otp_row, timezone.now() + timedelta(minutes=OTP_LOCKOUT_MINUTES),
                )
                raise AppError(
                    "Too many failed attempts. Try again in 15 minutes.",
                    429, "RATE_LIMITED", data={"attemptsRemaining": 0},
                )
            attempts_remaining = max(OTP_MAX_ATTEMPTS - otp_row.attempts, 0)
            raise AppError(
                "Incorrect OTP", 400, "INVALID_OTP",
                data={"attemptsRemaining": attempts_remaining},
            )

        admin = PlatformAdminRepository.get_by_email(email)
        PlatformAdminOtpRepository.delete_by_email(email)
        access_token = issue_admin_access_token(admin.id, admin.email, admin.role)
        return {"admin": admin, "access_token": access_token}


def _validate_url_slug(url_slug: str) -> None:
    if not url_slug or not (2 <= len(url_slug) <= 40) or not _SLUG_RE.match(url_slug):
        raise ValidationError(
            "urlSlug must be lowercase letters/numbers/hyphens only, 2-40 chars",
            code="INVALID_URL_SLUG",
        )


class PlatformAdminTenantService:
    @staticmethod
    def create_tenant(
        tenant_name, url_slug, vertical, admin_name, admin_email,
        admin_phone=None, role_label=None, preferred_lang="EN",
    ) -> dict:
        _validate_url_slug(url_slug)

        if not tenant_name:
            raise ValidationError("tenantName is required")
        if TenantRepository.name_exists(tenant_name):
            raise ValidationError("Tenant name already taken", code="TENANT_NAME_TAKEN")
        if TenantRepository.url_slug_exists(url_slug):
            raise ValidationError("URL slug already taken", code="URL_SLUG_TAKEN")
        if UserRepository.email_exists(admin_email):
            raise ValidationError("Email already in use", code="EMAIL_TAKEN")

        with transaction.atomic():
            tenant = TenantRepository.create(name=tenant_name, url_slug=url_slug, vertical=vertical)
            admin_user = UserRepository.create(
                tenant=tenant, name=admin_name, email=admin_email,
                phone=admin_phone, preferred_lang=preferred_lang,
            )
            MembershipRepository.create(
                tenant=tenant, user=admin_user, role_level=OrgRoleLevel.TOP,
                role_label=role_label, can_broadcast=True,
            )

        return {"tenant": tenant, "admin_user": admin_user, "role_label": role_label}

    @staticmethod
    def list_tenants():
        return TenantRepository.list_with_counts()

    @staticmethod
    def add_member(tenant_id, name, email, role_level, role_label=None, department_id=None, phone=None):
        tenant = TenantRepository.get_by_id(tenant_id)

        if UserRepository.email_exists(email):
            raise ValidationError("Email already in use", code="EMAIL_ALREADY_IN_TENANT")

        with transaction.atomic():
            user = UserRepository.create(tenant=tenant, name=name, email=email, phone=phone)
            MembershipRepository.create(
                tenant=tenant, user=user, role_level=role_level,
                role_label=role_label, department_id=department_id,
            )
        return user

    @staticmethod
    def remove_member(tenant_id, user_id) -> None:
        membership = MembershipRepository.get_by_tenant_and_user(tenant_id, user_id)
        MembershipRepository.delete(membership)
