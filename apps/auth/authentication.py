from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.auth.tokens import ACCESS_COOKIE_NAME
from apps.common.exceptions import NotFoundError
from apps.users.repositories import UserRepository


class CookieJWTAuthentication(BaseAuthentication):
    """Reads the short-lived access token from the httpOnly 'token' cookie --
    never an Authorization header. Refresh tokens are never used here; they
    only mint new access tokens via POST /auth/refresh."""

    def authenticate(self, request):
        raw = request.COOKIES.get(ACCESS_COOKIE_NAME)
        if not raw:
            return None  # anonymous -> IsAuthenticated denies -> 401

        try:
            token = AccessToken(raw)
        except TokenError as exc:
            raise exceptions.AuthenticationFailed("Invalid or expired token") from exc

        # A well-formed, unexpired JWT signed with this project's key but shaped
        # for a different auth space (e.g. PlatformAdmin's admin_token, which
        # carries adminId/isPlatformAdmin, never userId/tenantId) passes
        # AccessToken() above -- both are minted from the same SIMPLE_JWT
        # signing key -- but has no userId claim to index into. Reject that
        # cleanly as 401 rather than letting an uncaught KeyError 500.
        if "userId" not in token or "tenantId" not in token or "roleLevel" not in token:
            raise exceptions.AuthenticationFailed("Not a tenant-user token")

        try:
            user = UserRepository.get_by_id(token["userId"])
        except NotFoundError as exc:
            raise exceptions.AuthenticationFailed("User not found") from exc

        request.tenant_id = token["tenantId"]
        request.role_level = token["roleLevel"]
        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"  # forces 401 (not 403) on IsAuthenticated denial
