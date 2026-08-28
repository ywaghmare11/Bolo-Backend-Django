from .base import *  # noqa: F401,F403
from .base import MIDDLEWARE, env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# Behind an AWS ALB that terminates TLS -- trust its X-Forwarded-Proto header so
# Django knows the original request was HTTPS (otherwise SECURE_SSL_REDIRECT loops).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Reuse each DB connection for up to 60s instead of opening one per request --
# meaningful under gunicorn with many short requests against RDS.
CONN_MAX_AGE = env.int("CONN_MAX_AGE", default=60)

# WhiteNoise serves collected static files straight from gunicorn (Django admin +
# the Swagger/ReDoc assets) -- no nginx sidecar needed in the container. Must sit
# directly after SecurityMiddleware.
_security = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
MIDDLEWARE = (
    MIDDLEWARE[: _security + 1]
    + ["whitenoise.middleware.WhiteNoiseMiddleware"]
    + MIDDLEWARE[_security + 1 :]
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
