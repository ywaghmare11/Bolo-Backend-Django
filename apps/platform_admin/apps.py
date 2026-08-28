from django.apps import AppConfig


class PlatformAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.platform_admin'

    def ready(self):
        # Registers the drf-spectacular auth extension (side-effect import).
        from apps.platform_admin import schema  # noqa: F401
