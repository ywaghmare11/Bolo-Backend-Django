"""Shared helper for reading caller identity outside DRF's request wrapper.

Used by both apps/common/audit_middleware.py and apps/common/logging_middleware.py --
extracted here rather than one middleware importing from the other. Plain Django
middleware only ever sees the raw HttpRequest; request.tenant_id/request.user are
set on DRF's internal Request wrapper created inside APIView.dispatch(), so they
never propagate back out to middleware. Both middlewares therefore decode the same
httpOnly access-token cookie independently, using the same logic
apps.auth.authentication.CookieJWTAuthentication uses for the real request.
"""
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


def decode_access_cookie(request):
    """Returns (user_id, tenant_id), both None if there's no valid token (e.g.
    request-otp, or verify-otp before the cookie it's about to set exists) --
    or if the token is well-formed but shaped for a different auth space (e.g.
    PlatformAdmin's admin_token, which carries adminId/isPlatformAdmin, never
    userId/tenantId -- both JWTs are signed with the same SIMPLE_JWT key, so
    AccessToken() alone can't tell them apart). Same guard as
    apps.auth.authentication.CookieJWTAuthentication's own claim check --
    this caller just wants best-effort identity for logging/audit, never a
    reason to 401 or crash, so a mismatched shape is treated the same as no
    token at all rather than raising."""
    from apps.auth.tokens import ACCESS_COOKIE_NAME

    raw = request.COOKIES.get(ACCESS_COOKIE_NAME)
    if not raw:
        return None, None
    try:
        token = AccessToken(raw)
    except TokenError:
        return None, None
    if "userId" not in token or "tenantId" not in token:
        return None, None
    return token["userId"], token["tenantId"]


def decode_admin_cookie(request):
    """Returns (admin_id, email) for a valid PlatformAdmin `admin_token` cookie,
    or (None, None) for no / malformed / wrong-shaped token -- the mirror of
    decode_access_cookie for the second, cross-tenant auth space, with the same
    best-effort, never-raise contract. A PlatformAdmin is not a User row, so the
    audit middleware uses this only to attribute an audit row's metadata and
    actor_type, never AuditLog.actor_id (which stays null for PLATFORM_ADMIN
    actions -- see docs/api/api-spec.md and AuditActorType.PLATFORM_ADMIN)."""
    from apps.platform_admin.tokens import ADMIN_COOKIE_NAME

    raw = request.COOKIES.get(ADMIN_COOKIE_NAME)
    if not raw:
        return None, None
    try:
        token = AccessToken(raw)
    except TokenError:
        return None, None
    if not token.get("isPlatformAdmin") or "adminId" not in token:
        return None, None
    return token["adminId"], token.get("email")
