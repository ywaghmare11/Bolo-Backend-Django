from apps.common.exceptions import NotFoundError
from apps.tenants.models import TenantMembership


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
