import hashlib
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

ACCESS_COOKIE_NAME = "token"
REFRESH_COOKIE_NAME = "refresh_token"


def issue_access_token(user_id: str, tenant_id: str, role_level: str) -> str:
    token = AccessToken()
    token["userId"] = str(user_id)
    token["tenantId"] = str(tenant_id)
    token["roleLevel"] = role_level
    return str(token)


def issue_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at). The raw token is what goes
    in the cookie; only the hash is ever stored (same pattern as OtpCode)."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = timezone.now() + timedelta(days=settings.REFRESH_TOKEN_LIFETIME_DAYS)
    return raw_token, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_LIFETIME_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )


def clear_auth_cookies(response) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )
