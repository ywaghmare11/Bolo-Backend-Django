from .base import *  # noqa: F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE, env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# HTTPS hardening. Secure-by-default -- the defaults ARE the production values --
# but each is overridable from the environment so the same image can run behind a
# plain-HTTP load balancer during bring-up or in a no-TLS/no-domain demo. Leave
# all three unset in any real deployment. See docs/ops/aws-deploy-from-scratch.md §12b.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = env.bool("COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("COOKIE_SECURE", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# Behind an AWS ALB (or CloudFront) that terminates TLS -- trust the forwarded
# proto header so Django knows the original request was HTTPS (otherwise
# SECURE_SSL_REDIRECT loops). The header NAME is configurable because a
# CloudFront-in-front-of-ALB topology must forward it as a custom header the ALB
# won't rewrite (e.g. X-Client-Proto); a single ALB with an HTTPS listener uses
# the standard X-Forwarded-Proto default.
SECURE_PROXY_SSL_HEADER = (
    env("SECURE_PROXY_SSL_HEADER_NAME", default="HTTP_X_FORWARDED_PROTO"),
    "https",
)

# CORS -- only needed when a browser SPA is served from a different origin than
# this API (e.g. the admin console on its own CloudFront domain). Inert until
# CORS_ALLOWED_ORIGINS is populated from the environment; dev.py keeps its own
# localhost list. CorsMiddleware must sit above SecurityMiddleware / WhiteNoise /
# CommonMiddleware, so it's spliced in just before SecurityMiddleware below.
INSTALLED_APPS = [*INSTALLED_APPS, "corsheaders"]
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# Reuse each DB connection for up to 60s instead of opening one per request --
# meaningful under gunicorn with many short requests against RDS.
CONN_MAX_AGE = env.int("CONN_MAX_AGE", default=60)

# WhiteNoise serves collected static files straight from gunicorn (Django admin +
# the Swagger/ReDoc assets) -- no nginx sidecar needed in the container. Must sit
# directly after SecurityMiddleware. CorsMiddleware goes just before it, so the
# order becomes: ... -> CorsMiddleware -> SecurityMiddleware -> WhiteNoise -> ...
_security = MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
MIDDLEWARE = (
    MIDDLEWARE[:_security]
    + ["corsheaders.middleware.CorsMiddleware"]
    + [MIDDLEWARE[_security]]
    + ["whitenoise.middleware.WhiteNoiseMiddleware"]
    + MIDDLEWARE[_security + 1 :]
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
