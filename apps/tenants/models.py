from django.db import models

from apps.common.enums import OrgRoleLevel, TenantStatus, Vertical
from apps.common.models import TimestampedModel


class Tenant(TimestampedModel):
    name = models.CharField(max_length=255)
    vertical = models.CharField(max_length=20, choices=Vertical.choices)
    # Cosmetic post-login routing only (domain-model.md) -- drives bolo-web's
    # /{urlSlug}/{firstName} path, never used for tenant scoping/authorization
    # (that stays keyed on `id` from the JWT everywhere else). Nullable because
    # tenants predating POST /platform-admin/tenants (fixtures, seed_dev_data)
    # have no slug; existing tenants are backfilled via migration.
    url_slug = models.CharField(max_length=40, unique=True, null=True, blank=True)

    # Operator offboarding lifecycle (ROADMAP.md Phase 15e). SUSPENDED cuts all
    # login/refresh for this tenant's users and stops its Celery sweeps, with
    # every row retained and the transition fully reversible. Set only via
    # PATCH /platform-admin/tenants/:id (SUPER_ADMIN).
    status = models.CharField(
        max_length=16, choices=TenantStatus.choices, default=TenantStatus.ACTIVE,
    )
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "tenants"

    def __str__(self):
        return self.name


class Department(TimestampedModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="departments",
    )
    name = models.CharField(max_length=255)
    # null until a head is assigned; one user heads at most one department
    head = models.OneToOneField(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="department_headed",
    )

    class Meta:
        db_table = "departments"

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    pk = models.CompositePrimaryKey("tenant", "user")
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="memberships",
    )
    # unique=True -- single tenant per user (W56); also completes the composite PK
    user = models.OneToOneField(
        "users.User", on_delete=models.PROTECT, related_name="membership",
    )
    department = models.ForeignKey(
        "tenants.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships",
    )
    role_level = models.CharField(max_length=20, choices=OrgRoleLevel.choices)
    role_label = models.CharField(max_length=100, null=True, blank=True)
    # null = root of the org tree; org chart is built from this chain, not role_label
    reports_to = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="direct_reports",
    )
    # binary permission flag, not derived from role_level (W22)
    can_broadcast = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenant_memberships"

    def __str__(self):
        return f"{self.user_id}@{self.tenant_id}"
