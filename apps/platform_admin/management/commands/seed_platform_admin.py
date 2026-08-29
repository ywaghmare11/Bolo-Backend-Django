from django.core.management.base import BaseCommand, CommandError

from apps.common.enums import PlatformAdminRole
from apps.platform_admin.models import PlatformAdmin


class Command(BaseCommand):
    help = (
        "Provisions a PlatformAdmin (superadmin) row. Deliberately the only way "
        "one is created -- there is no self-registration API endpoint, so nobody "
        "can grant themselves cross-tenant access over the network. Idempotent: "
        "re-running with the same --email updates the name rather than erroring."
    )

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Display name, e.g. \"Ops Admin\"")
        parser.add_argument("--email", required=True, help="Login identifier, Email+OTP")
        parser.add_argument(
            "--role",
            default=PlatformAdminRole.SUPER_ADMIN,
            choices=PlatformAdminRole.values,
            help="RBAC tier (only SUPER_ADMIN exists today; default)",
        )

    def handle(self, *args, **options):
        name = options["name"]
        email = options["email"]
        role = options["role"]

        if not email or "@" not in email:
            raise CommandError(f"Not a valid email: {email!r}")

        admin, created = PlatformAdmin.objects.update_or_create(
            email=email, defaults={"name": name, "role": role},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} PlatformAdmin: {admin.name} <{admin.email}>"))
