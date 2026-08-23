from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Local cross-origin dev only -- bolo-web (vite, localhost:5173) calls this API
# directly at localhost:8000 instead of through a same-origin nginx proxy like prod,
# so the browser needs an explicit CORS allow + credentials for the auth cookies to
# round-trip. Not in base.py/prod.py -- prod is same-origin, no CORS needed there.
INSTALLED_APPS = [*INSTALLED_APPS, "corsheaders"]  # noqa: F405
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", *MIDDLEWARE]  # noqa: F405

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CORS_ALLOW_CREDENTIALS = True
