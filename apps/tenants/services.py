from apps.tenants.repositories import TenantRepository


class TenantService:
    @staticmethod
    def get_overview(tenant_id):
        return TenantRepository.get_with_counts(tenant_id)
