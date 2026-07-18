from django.core.management.base import BaseCommand

from apps.common.enums import OrgRoleLevel, Vertical
from apps.tenants.models import Tenant, TenantMembership
from apps.users.models import User

# Fixed IDs (not random uuid4) so the Postman collection can bake in default
# variable values that just work, instead of requiring copy-paste per run.
TENANT_ID = "11111111-1111-1111-1111-111111111111"
ASSIGNER_ID = "22222222-2222-2222-2222-222222222222"
ASSIGNEE_ID = "33333333-3333-3333-3333-333333333333"


class Command(BaseCommand):
    help = (
        "Seeds a fixed tenant + two users (assigner/assignee) for manual API "
        "testing via curl or the Postman collection. Idempotent -- safe to re-run."
    )

    def handle(self, *args, **options):
        tenant, _ = Tenant.objects.get_or_create(
            id=TENANT_ID, defaults={"name": "ABC College", "vertical": Vertical.EDUCATION},
        )
        assigner, _ = User.objects.get_or_create(
            id=ASSIGNER_ID,
            defaults={"tenant": tenant, "name": "Dr. Kamal Sethi", "email": "assigner@example.com"},
        )
        assignee, _ = User.objects.get_or_create(
            id=ASSIGNEE_ID,
            defaults={"tenant": tenant, "name": "Prof. Asha Nair", "email": "assignee@example.com"},
        )
        TenantMembership.objects.get_or_create(
            tenant=tenant, user=assigner,
            defaults={"role_level": OrgRoleLevel.TOP, "role_label": "Dean", "can_broadcast": True},
        )
        TenantMembership.objects.get_or_create(
            tenant=tenant, user=assignee,
            defaults={"role_level": OrgRoleLevel.MID, "role_label": "HoD", "can_broadcast": False},
        )

        self.stdout.write(self.style.SUCCESS("Seed data ready:"))
        self.stdout.write(f"  tenant:   {tenant.id} ({tenant.name})")
        self.stdout.write(f"  assigner: {assigner.id} <{assigner.email}> -- request-otp with this email")
        self.stdout.write(f"  assignee: {assignee.id} <{assignee.email}> -- request-otp with this email")
        self.stdout.write("These IDs are already baked into the Postman collection's default variables.")
