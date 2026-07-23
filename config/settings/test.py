from .base import *  # noqa: F401,F403

DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# locmem lets tests assert against django.core.mail.outbox
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tests shouldn't depend on a running Redis -- locmem gives the same
# get/set/incr semantics ScopedRateThrottle needs, per-process, which is fine
# since pytest-django runs single-process.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Run Celery tasks (the audit-log write) synchronously and in-process -- no worker
# needed for tests, and failures raise immediately instead of vanishing into a queue.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
