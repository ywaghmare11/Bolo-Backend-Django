from django.apps import AppConfig


class AuthConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.auth'
    # django.contrib.auth already owns the app_label "auth" -- must not collide with it.
    label = 'bolo_auth'
