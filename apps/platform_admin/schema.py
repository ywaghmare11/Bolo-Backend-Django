"""drf-spectacular extension: describe the PlatformAdmin auth (the separate
`admin_token` httpOnly cookie) in the generated OpenAPI schema. Registered as a
side-effect import from apps/platform_admin/apps.py:PlatformAdminConfig.ready.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension

from apps.platform_admin.tokens import ADMIN_COOKIE_NAME


class PlatformAdminCookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.platform_admin.authentication.PlatformAdminCookieJWTAuthentication"
    name = "platformAdminCookieAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": ADMIN_COOKIE_NAME,
            "description": (
                "Platform-admin session JWT, set as an httpOnly cookie by "
                "POST /platform-admin/auth/verify-otp. Separate from the "
                "tenant-user `token` cookie."
            ),
        }
