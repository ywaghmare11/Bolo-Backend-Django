from .base import *  # noqa: F401,F403

DEBUG = False

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# locmem lets tests assert against django.core.mail.outbox
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Tests shouldn't depend on a running Redis -- locmem gives the same
# get/set/incr semantics ScopedRateThrottle needs, per-process, which is fine
# since pytest-django runs single-process.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
