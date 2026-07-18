from rest_framework.permissions import AllowAny, IsAuthenticated

__all__ = ["IsAuthenticated", "AllowAny"]

# No custom tenant-scoping or ownership permission classes exist yet.
# Tenant scope is enforced by every repository method requiring tenant_id
# (from request.tenant_id, set by CookieJWTAuthentication) as a filter
# argument -- never by a permission class. Resource-ownership checks
# (assigner-only / assignee-only) are service-layer, raising ForbiddenError.
# This module exists as a single import surface for app code so a future
# HasOrgRole or ownership permission class can be added without touching
# call sites.
