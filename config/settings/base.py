"""
Base settings shared by every environment.
See https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab

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
    "apps.search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # First -- normalizes bolo-web's no-trailing-slash requests (the actual
    # api-spec.md contract) before URL resolution. See apps/common/middleware.py.
    "apps.common.middleware.NormalizeApiTrailingSlashMiddleware",
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

# Celery beat -- periodic jobs. Django's built-in settings-based scheduler (no
# django_celery_beat app installed) is enough for the jobs that exist so far.
CELERY_BEAT_SCHEDULE = {
    "sticky-note-retention-sweep": {
        "task": "apps.sticky_notes.retention_sweep",
        # Natural port of upstream's 24h setInterval (docs/architecture/domain-model.md
        # StickyNote section) -- once daily is enough since the retention window is 3 days.
        "schedule": crontab(hour=2, minute=0),
    },
    "sticky-note-reminder-sweep": {
        "task": "apps.sticky_notes.reminder_sweep",
        # REMINDER_FIRED needs to fire close to the note's own dueAt (any time of day),
        # not once a day like the retention sweep above -- every 15 minutes is prompt
        # enough without being wasteful (a judgment call; no SLA is documented upstream).
        "schedule": crontab(minute="*/15"),
    },
    "task-due-proximity-sweep": {
        "task": "apps.tasks.due_proximity_sweep",
        # ROADMAP.md Phase 8: "daily cron scanning tasks for TASK_DUE_TODAY/
        # TASK_DUE_TOMORROW/TASK_OVERDUE" -- once daily, early morning before most
        # users start their day (a judgment call; no specific time is documented).
        "schedule": crontab(hour=7, minute=0),
    },
    "ai-nudge-followup-sweep": {
        "task": "apps.notifications.ai_nudge_followup_sweep",
        # domain-model.md row 8c: "Fires every 6h, no office-hours gate."
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "ai-nudge-due-proximity-sweep": {
        "task": "apps.notifications.ai_nudge_due_proximity_sweep",
        # domain-model.md row 8d: "Fires every 3h, no office-hours gate."
        "schedule": crontab(minute=0, hour="*/3"),
    },
}

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

# SMTP settings -- only read when EMAIL_BACKEND is the smtp backend. Local-dev-only
# stand-in for real transactional email (Gmail app-password SMTP, e.g.) so OTP mails
# actually land in an inbox during frontend testing, ahead of the real AWS SES wiring
# CLAUDE.md's tech stack table calls for in prod. Never used unless EMAIL_BACKEND is
# switched away from its console/SES defaults above.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)

# Evidence file storage -- IAM-role-only via the default boto3 credential provider
# chain (see apps/common/storage.py), no separate access-key secret to manage, same
# pattern as SES above.
AWS_S3_BUCKET_NAME = env("S3_BUCKET_NAME", default="")
AWS_S3_REGION = env("AWS_S3_REGION", default="ap-south-1")

# Global Search's query-understanding layer (docs/api/global-search-ai-contract.md).
# Deliberately optional, not crash-on-missing like most required settings -- an empty
# key is the documented "AI unavailable" condition (apps/search/ai_classify.py falls
# back to a raw keyword classification, never a hard failure), not a misconfiguration.
OPENAI_API_KEY = env("OPENAI_API_KEY", default="")
OPENAI_SEARCH_MODEL = env("OPENAI_SEARCH_MODEL", default="gpt-4o-mini")
