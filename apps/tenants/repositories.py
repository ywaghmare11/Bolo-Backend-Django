from apps.common.exceptions import NotFoundError
from apps.tenants.models import Department, Tenant, TenantMembership


class TenantRepository:
    @staticmethod
    def get_with_counts(tenant_id) -> Tenant:
        """For GET /tenant. Three simple queries rather than one annotated query --
        TenantMembership's composite PK (tenant, user) makes Count(..., distinct=True)
        raise when combined with a second to-many annotation in the same query, and
        this is a single-row admin lookup, not a list, so there's no N+1 to worry about."""
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise NotFoundError("Tenant", tenant_id) from None
        tenant.member_count_annotated = TenantMembership.objects.filter(tenant_id=tenant_id).count()
        tenant.dept_count_annotated = Department.objects.filter(tenant_id=tenant_id).count()
        return tenant


class MembershipRepository:
    @staticmethod
    def get_profile_for_user(user_id: str) -> TenantMembership:
        """Returns the TenantMembership row (with .tenant preloaded) for a user --
        the source of tenantId/tenantName/roleLevel/roleLabel/canBroadcast used
        both for the verify-otp response payload and the JWT claims."""
        try:
            return TenantMembership.objects.select_related("tenant").get(user_id=user_id)
        except TenantMembership.DoesNotExist:
            raise NotFoundError("TenantMembership", user_id) from None
