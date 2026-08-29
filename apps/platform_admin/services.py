import hashlib
import re
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.common.email import EmailService
from apps.common.enums import OrgRoleLevel, TenantStatus
from apps.common.exceptions import AppError, ConflictError, NotFoundError, ValidationError
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
    def set_tenant_status(tenant_id, status: str, reason: str | None = None):
        """Operator offboarding (ROADMAP.md Phase 15e) -- suspend cuts login for
        this tenant's users and its Celery sweeps; reactivate restores both. All
        data is retained either way. Idempotent-guarded so a no-op PATCH doesn't
        re-stamp suspended_at or write a spurious audit row."""
        tenant = TenantRepository.get_by_id(tenant_id)
        if tenant.status == status:
            raise ConflictError(
                f"Tenant is already {status}.", code="TENANT_STATUS_UNCHANGED",
            )
        return TenantRepository.set_status(tenant, status, reason)

    @staticmethod
    def _assert_active(tenant) -> None:
        if tenant.status == TenantStatus.SUSPENDED:
            raise ConflictError(
                "This tenant is suspended; reactivate it before adding members.",
                code="TENANT_SUSPENDED",
            )

    @staticmethod
    def add_member(tenant_id, name, email, role_level, role_label=None, department_id=None, phone=None):
        tenant = TenantRepository.get_by_id(tenant_id)
        PlatformAdminTenantService._assert_active(tenant)

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
    def list_members(tenant_id):
        """QuerySet of a tenant's members for the console table (Phase 15d).
        404s before returning if the tenant doesn't exist."""
        TenantRepository.get_by_id(tenant_id)
        return MembershipRepository.list_for_tenant(tenant_id)

    @staticmethod
    def remove_member(tenant_id, user_id) -> None:
        membership = MembershipRepository.get_by_tenant_and_user(tenant_id, user_id)
        MembershipRepository.delete(membership)

    # -- bulk import (ROADMAP.md Phase 15c) -----------------------------------

    IMPORT_CHUNK_SIZE = 100

    @staticmethod
    def bulk_import_members(tenant_id, file_bytes: bytes, filename: str) -> dict:
        """Extract -> Transform (apps/platform_admin/etl.py) -> Load. Idempotent:
        a member already in this tenant is updated, not re-created. Returns
        {created, updated, skipped, errors:[{row, field, reason}]}."""
        from apps.platform_admin import etl

        tenant = TenantRepository.get_by_id(tenant_id)  # 404 before touching the file
        PlatformAdminTenantService._assert_active(tenant)

        df = etl.extract(file_bytes, filename)
        valid_records, errors = etl.transform(df)

        created = updated = 0
        skipped = len(errors)

        chunk_size = PlatformAdminTenantService.IMPORT_CHUNK_SIZE
        for start in range(0, len(valid_records), chunk_size):
            chunk = valid_records[start:start + chunk_size]
            # One transaction per chunk -- a mid-import failure leaves a clean,
            # known boundary (whole chunks committed or not) rather than a
            # half-written row.
            with transaction.atomic():
                for rec in chunk:
                    outcome = PlatformAdminTenantService._load_one(tenant, rec, errors)
                    if outcome == "created":
                        created += 1
                    elif outcome == "updated":
                        updated += 1
                    else:
                        skipped += 1

        return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}

    @staticmethod
    def _load_one(tenant, rec: dict, errors: list) -> str:
        existing = UserRepository.get_by_email_or_none(rec["email"])
        if existing is not None and str(existing.tenant_id) != str(tenant.id):
            errors.append({
                "row": rec["_row"], "field": "email",
                "reason": "this email already belongs to a different tenant",
            })
            return "skipped"

        if existing is not None:
            UserRepository.update(
                existing,
                name=rec["name"],
                phone=rec["phone"] if rec["phone"] is not None else existing.phone,
                preferred_lang=rec["preferred_lang"],
            )
            MembershipRepository.upsert(
                tenant, existing, rec["role_level"], rec["role_label"], rec["can_broadcast"],
            )
            return "updated"

        user = UserRepository.create(
            tenant=tenant, name=rec["name"], email=rec["email"],
            phone=rec["phone"], preferred_lang=rec["preferred_lang"],
        )
        MembershipRepository.create(
            tenant=tenant, user=user, role_level=rec["role_level"],
            role_label=rec["role_label"], can_broadcast=rec["can_broadcast"],
        )
        return "created"
