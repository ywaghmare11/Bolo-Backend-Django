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

        try:
            user = UserRepository.get_by_id(token["userId"])
        except NotFoundError as exc:
            raise exceptions.AuthenticationFailed("User not found") from exc

        request.tenant_id = token["tenantId"]
        request.role_level = token["roleLevel"]
        return (user, token)

    def authenticate_header(self, request):
        return "Bearer"  # forces 401 (not 403) on IsAuthenticated denial
