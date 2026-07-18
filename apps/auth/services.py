import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from apps.auth.repositories import OtpRepository, RefreshTokenRepository
from apps.auth.tokens import hash_refresh_token, issue_access_token, issue_refresh_token
from apps.common.email import EmailService
from apps.common.exceptions import AppError, NotFoundError
from apps.tenants.repositories import MembershipRepository
from apps.users.repositories import UserRepository

OTP_EXPIRY_MINUTES = 10
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 3
OTP_LOCKOUT_MINUTES = 15


class AuthService:
    @staticmethod
    def request_otp(email: str) -> None:
        try:
            UserRepository.get_by_email(email)
        except NotFoundError:
            raise AppError(f"No account found for {email}", 404, "USER_NOT_FOUND") from None

        existing = OtpRepository.get_by_email(email)
        resend_cutoff = timezone.now() - timedelta(seconds=OTP_RESEND_SECONDS)
        if existing and existing.created_at > resend_cutoff:
            raise AppError(
                "Too many OTP requests. Try again in 60 seconds.", 429, "RATE_LIMITED",
            )

        code = f"{secrets.randbelow(1_000_000):06d}"
        hashed_code = hashlib.sha256(code.encode()).hexdigest()
        expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)
        OtpRepository.upsert(email, hashed_code, expires_at)
        EmailService.send_otp_email(email, code)

    @staticmethod
    def verify_otp(email: str, otp: str) -> dict:
        """Returns {"user", "membership", "access_token", "refresh_token"}."""
        otp_row = OtpRepository.get_by_email(email)
        if not otp_row:
            raise AppError("OTP expired or not found", 400, "OTP_EXPIRED")

        if otp_row.locked_until and otp_row.locked_until > timezone.now():
            raise AppError(
                "Too many failed attempts. Try again later.",
                429, "RATE_LIMITED", data={"attemptsRemaining": 0},
            )

        if otp_row.expires_at < timezone.now():
            OtpRepository.delete_by_email(email)
            raise AppError("OTP expired", 400, "OTP_EXPIRED")

        hashed_code = hashlib.sha256(otp.encode()).hexdigest()
        if hashed_code != otp_row.hashed_code:
            otp_row = OtpRepository.increment_attempts(otp_row)
            if otp_row.attempts >= OTP_MAX_ATTEMPTS:
                OtpRepository.lock(
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

        user = UserRepository.get_by_email(email)
        membership = MembershipRepository.get_profile_for_user(user.id)

        OtpRepository.delete_by_email(email)
        UserRepository.update_last_login(user)

        access_token = issue_access_token(user.id, membership.tenant_id, membership.role_level)
        raw_refresh, refresh_hash, refresh_expires_at = issue_refresh_token()
        RefreshTokenRepository.create(user, refresh_hash, refresh_expires_at)

        return {
            "user": user,
            "membership": membership,
            "access_token": access_token,
            "refresh_token": raw_refresh,
        }

    @staticmethod
    def refresh(raw_refresh_token: str) -> dict:
        """Validates + rotates a refresh token. Reuse of an already-revoked
        token is treated as a theft signal and revokes every refresh token
        for that user, forcing full re-login."""
        token_hash = hash_refresh_token(raw_refresh_token)
        existing = RefreshTokenRepository.get_by_hash(token_hash)
        if not existing:
            raise AppError("Invalid refresh token", 401, "UNAUTHENTICATED")

        if existing.revoked_at is not None:
            RefreshTokenRepository.revoke_all_for_user(existing.user)
            raise AppError("Refresh token already used", 401, "UNAUTHENTICATED")

        if existing.expires_at < timezone.now():
            raise AppError("Refresh token expired", 401, "UNAUTHENTICATED")

        RefreshTokenRepository.revoke(existing)

        user = existing.user
        membership = MembershipRepository.get_profile_for_user(user.id)
        access_token = issue_access_token(user.id, membership.tenant_id, membership.role_level)
        raw_refresh, refresh_hash, refresh_expires_at = issue_refresh_token()
        RefreshTokenRepository.create(user, refresh_hash, refresh_expires_at)

        return {"access_token": access_token, "refresh_token": raw_refresh}

    @staticmethod
    def logout(user, raw_refresh_token: str | None) -> None:
        UserRepository.update_last_logout(user)
        if raw_refresh_token:
            token_hash = hash_refresh_token(raw_refresh_token)
            existing = RefreshTokenRepository.get_by_hash(token_hash)
            if existing and existing.revoked_at is None:
                RefreshTokenRepository.revoke(existing)
