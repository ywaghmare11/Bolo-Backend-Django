from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.common.exceptions import NotFoundError
from apps.platform_admin.repositories import PlatformAdminRepository
from apps.platform_admin.tokens import ADMIN_COOKIE_NAME


class PlatformAdminCookieJWTAuthentication(BaseAuthentication):
    """Reads the separate 'admin_token' cookie -- never the tenant-user
    'token' cookie apps.auth.authentication.CookieJWTAuthentication reads.
    Mirrors that class's shape, but a PlatformAdmin isn't a User row and the
    token payload carries no tenantId/roleLevel to inject onto the request."""

    def authenticate(self, request):
        raw = request.COOKIES.get(ADMIN_COOKIE_NAME)
        if not raw:
            return None  # anonymous -> IsAuthenticated denies -> 401

        try:
            token = AccessToken(raw)
        except TokenError as exc:
            raise exceptions.AuthenticationFailed("Invalid or expired token") from exc

        if not token.get("isPlatformAdmin"):
            raise exceptions.AuthenticationFailed("Not a platform-admin token")

        try:
            admin = PlatformAdminRepository.get_by_id(token["adminId"])
        except NotFoundError as exc:
            raise exceptions.AuthenticationFailed("Platform admin not found") from exc

        # RBAC tier for HasPlatformAdminRole -- mirrors how CookieJWTAuthentication
        # sets request.role_level for tenant users. Prefer the JWT claim (no extra
        # work); fall back to the just-loaded row for admin_token cookies minted
        # before the `role` claim existed (7-day lifetime, so they linger).
        request.platform_admin_role = token.get("role") or admin.role

        return (admin, token)

    def authenticate_header(self, request):
        return "Bearer"  # forces 401 (not 403) on IsAuthenticated denial
