from datetime import timedelta

from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken

ADMIN_COOKIE_NAME = "admin_token"

# A single 7-day session JWT, no refresh/rotation -- deliberately simpler than
# the tenant-user access+refresh design (apps/auth/tokens.py). PlatformAdmin
# is an ops-only, human-operated, low-volume surface (no self-registration,
# provisioned only via a management command), so the extra reuse-detection
# machinery built for the main product's session model isn't warranted here.
# Matches upstream's own single-cookie design for this specific auth flow.
ADMIN_TOKEN_LIFETIME_DAYS = 7


def issue_admin_access_token(admin_id: str, email: str) -> str:
    token = AccessToken()
    token.set_exp(lifetime=timedelta(days=ADMIN_TOKEN_LIFETIME_DAYS))
    token["adminId"] = str(admin_id)
    token["email"] = email
    # No tenantId/roleLevel at all -- so a tenant-user token can never be
    # mistaken for (or pass validation as) an admin token, and vice versa.
    token["isPlatformAdmin"] = True
    return str(token)


def set_admin_auth_cookie(response, access_token: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        access_token,
        max_age=ADMIN_TOKEN_LIFETIME_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )


def clear_admin_auth_cookie(response) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Lax",
        secure=settings.COOKIE_SECURE,
    )
