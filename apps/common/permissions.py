from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated

__all__ = ["IsAuthenticated", "AllowAny", "IsTenantMember", "HasOrgRole"]


class IsTenantMember(BasePermission):
    """Explicit tenant-scope guard -- request.tenant_id is set by
    CookieJWTAuthentication whenever a request authenticates at all, so this
    is largely a documented marker rather than a new check, but it makes the
    'every view is tenant-scoped' rule (CLAUDE.md Architecture Rules point 5)
    visible in permission_classes instead of only implicit in repository
    filters. Repository methods still always filter by tenant_id themselves
    -- this doesn't replace that, it's defense in depth."""

    def has_permission(self, request, view):
        return bool(getattr(request, "tenant_id", None))


def HasOrgRole(allowed_role_levels):
    """DRF permission-class factory -- equivalent of the original Node
    backend's `requireOrgRole(['TOP'])` middleware. request.role_level is
    decoded straight from the JWT by CookieJWTAuthentication.

    Usage: permission_classes = [IsTenantMember, HasOrgRole(["TOP"])]
    """

    class _HasOrgRole(BasePermission):
        def has_permission(self, request, view):
            return getattr(request, "role_level", None) in allowed_role_levels

    return _HasOrgRole
