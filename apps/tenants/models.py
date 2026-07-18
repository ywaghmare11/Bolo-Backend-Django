from django.db import models

from apps.common.enums import OrgRoleLevel, Vertical
from apps.common.models import TimestampedModel


class Tenant(TimestampedModel):
    name = models.CharField(max_length=255)
    vertical = models.CharField(max_length=20, choices=Vertical.choices)

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
