from django.utils import timezone

from apps.common.enums import TenantStatus
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

    @staticmethod
    def get_by_id(tenant_id) -> Tenant:
        try:
            return Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise NotFoundError("Tenant", tenant_id) from None

    @staticmethod
    def name_exists(name: str) -> bool:
        return Tenant.objects.filter(name=name).exists()

    @staticmethod
    def url_slug_exists(url_slug: str) -> bool:
        return Tenant.objects.filter(url_slug=url_slug).exists()

    @staticmethod
    def create(name: str, url_slug: str, vertical: str) -> Tenant:
        return Tenant.objects.create(name=name, url_slug=url_slug, vertical=vertical)

    @staticmethod
    def set_status(tenant: Tenant, status: str, reason: str | None = None) -> Tenant:
        """Operator offboarding (ROADMAP.md Phase 15e). Suspending stamps
        suspended_at + reason; reactivating clears both."""
        tenant.status = status
        if status == TenantStatus.SUSPENDED:
            tenant.suspended_at = timezone.now()
            tenant.suspension_reason = reason or None
        else:
            tenant.suspended_at = None
            tenant.suspension_reason = None
        tenant.save(update_fields=["status", "suspended_at", "suspension_reason", "updated_at"])
        return tenant

    @staticmethod
    def list_with_counts() -> list[Tenant]:
        """For GET /platform-admin/tenants -- an ops-only, expected-tiny list
        (dozens of tenants, not thousands), so the same per-row two-query
        approach as get_with_counts is fine here even looped; the composite-PK
        annotation issue documented there rules out one combined query anyway."""
        tenants = list(Tenant.objects.all().order_by("-created_at"))
        for tenant in tenants:
            tenant.member_count_annotated = TenantMembership.objects.filter(tenant_id=tenant.id).count()
            tenant.dept_count_annotated = Department.objects.filter(tenant_id=tenant.id).count()
        return tenants


class MembershipRepository:
    @staticmethod
    def get_profile_for_user(user_id: str) -> TenantMembership:
        """Returns the TenantMembership row (with .tenant/.department/.reports_to
        preloaded) for a user -- the source of tenantId/tenantName/roleLevel/
        roleLabel/canBroadcast used for the verify-otp response payload and the
        JWT claims, and of departmentName/reportsToName for GET /me."""
        try:
            return TenantMembership.objects.select_related(
                "tenant", "department", "reports_to",
            ).get(user_id=user_id)
        except TenantMembership.DoesNotExist:
            raise NotFoundError("TenantMembership", user_id) from None

    @staticmethod
    def create(
        tenant, user, role_level: str, role_label: str | None = None,
        department_id=None, can_broadcast: bool = False,
    ) -> TenantMembership:
        return TenantMembership.objects.create(
            tenant=tenant, user=user, role_level=role_level, role_label=role_label,
            department_id=department_id, can_broadcast=can_broadcast,
        )

    @staticmethod
    def get_by_tenant_and_user(tenant_id, user_id) -> TenantMembership:
        try:
            return TenantMembership.objects.get(tenant_id=tenant_id, user_id=user_id)
        except TenantMembership.DoesNotExist:
            raise NotFoundError("TenantMembership", user_id) from None

    @staticmethod
    def upsert(tenant, user, role_level: str, role_label=None, can_broadcast: bool = False):
        """For the bulk-import Load step -- (tenant, user) is the composite PK, so
        a re-import of the same member just refreshes their role fields rather
        than erroring. Returns (membership, created)."""
        return TenantMembership.objects.update_or_create(
            tenant=tenant, user=user,
            defaults={
                "role_level": role_level,
                "role_label": role_label,
                "can_broadcast": can_broadcast,
            },
        )

    @staticmethod
    def delete(membership: TenantMembership) -> None:
        membership.delete()
