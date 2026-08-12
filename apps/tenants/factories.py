import factory

from apps.common.enums import OrgRoleLevel, Vertical
from apps.tenants.models import Department, Tenant, TenantMembership


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Tenant {n}")
    vertical = Vertical.EDUCATION


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department

    tenant = factory.SubFactory(TenantFactory)
    name = factory.Sequence(lambda n: f"Department {n}")


class TenantMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TenantMembership

    tenant = factory.SubFactory(TenantFactory)
    user = factory.SubFactory("apps.users.factories.UserFactory")
    role_level = OrgRoleLevel.MID
    can_broadcast = False
