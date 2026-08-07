from rest_framework.views import APIView

from apps.common.permissions import HasOrgRole, IsTenantMember
from apps.common.responses import success_response
from apps.tenants.serializers import serialize_tenant_overview
from apps.tenants.services import TenantService


class TenantOverviewView(APIView):
    """GET /tenant -- docs/api/api-spec.md: `requireOrgRole(['TOP'])`."""

    permission_classes = [IsTenantMember, HasOrgRole(["TOP"])]

    def get(self, request):
        tenant = TenantService.get_overview(request.tenant_id)
        return success_response(serialize_tenant_overview(tenant), "OK")
