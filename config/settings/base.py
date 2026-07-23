"""
Base settings shared by every environment.
See https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.common",
    "apps.platform_admin",
    "apps.tenants",
    "apps.users",
    "apps.auth",
    "apps.tasks",
    "apps.labels",
    "apps.evidence",
    "apps.comments",
    "apps.sticky_notes",
    "apps.broadcasts",
    "apps.notifications",
    "apps.audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Last -- generic audit-log observer (CLAUDE.md Architecture Rules point 8). Does
    # its own URL resolution against apps.common.audit_route_config.AUDIT_ROUTE_CONFIG
    # rather than reading DRF-specific request attributes (request.tenant_id/request.user
    # are set on DRF's internal Request wrapper inside APIView.dispatch(), not on the
    # underlying HttpRequest this middleware sees -- they never propagate back out here).
    "apps.common.audit_middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": env.db("DATABASE_URL"),
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.auth.authentication.CookieJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.BoloPageNumberPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "config.exception_handler.bolo_exception_handler",
    # Only apply throttling where a view opts in via throttle_classes/throttle_scope --
    # not a DEFAULT_THROTTLE_CLASSES global, since only the OTP-request endpoint needs it today.
    "DEFAULT_THROTTLE_RATES": {
        # Per-IP burst guard, layered on top of AuthService.request_otp's existing
        # per-email 60s resend cooldown (a DB timestamp check -- see apps/auth/services.py).
        # That check alone doesn't stop someone cycling through many emails from one IP;
        # this rate is enforced in Redis so it holds across multiple gunicorn workers/processes,
        # unlike DRF's in-memory cache which is per-process and useless beyond one worker.
        "otp_request": "5/min",
    },
}

# Redis-backed cache -- DRF's ScopedRateThrottle reads/writes through Django's default
# cache alias (django.core.cache.cache), so pointing "default" at Redis here is what
# makes the throttle actually shared across processes. Also the shared cache-aside
# backend for future read-heavy endpoints (Phase 12).
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    },
}

# Celery -- shares the same Redis instance as CACHES above (broker + result backend).
# Used today for the fire-and-forget audit-log write (apps/common/audit_middleware.py);
# CELERY_TASK_ALWAYS_EAGER lets config/settings/test.py run tasks synchronously so tests
# don't need a running worker.
CELERY_BROKER_URL = env("REDIS_URL")
CELERY_RESULT_BACKEND = env("REDIS_URL")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "SIGNING_KEY": env("JWT_SECRET"),
    "ALGORITHM": "HS256",
}

# Refresh tokens are opaque, DB-backed (apps.auth.models.RefreshToken), not JWTs --
# see docs/ops/security.md Authentication section for the access+refresh design.
REFRESH_TOKEN_LIFETIME_DAYS = 7

COOKIE_SECURE = env.bool("COOKIE_SECURE", default=False)

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# SES_FROM_EMAIL is present-but-empty in .env.example (SES not wired up yet) --
# `or` guards against that in addition to the truly-unset case.
DEFAULT_FROM_EMAIL = env("SES_FROM_EMAIL", default="") or "noreply@bolo.local"
