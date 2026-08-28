"""drf-spectacular extension so the generated OpenAPI schema describes this API's
actual auth: the short-lived access JWT in the httpOnly `token` cookie, not an
Authorization header. Without this, spectacular emits an "unable to resolve
authenticator" warning for every view and the docs show no security scheme.

Imported for its side effect (registration) from apps/auth/apps.py:AuthConfig.ready.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from apps.auth.tokens import ACCESS_COOKIE_NAME


class CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.auth.authentication.CookieJWTAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": ACCESS_COOKIE_NAME,
            "description": (
                "Short-lived access JWT set as an httpOnly cookie by "
                "POST /auth/verify-otp and refreshed by POST /auth/refresh."
            ),
        }
