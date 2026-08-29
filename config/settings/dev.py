from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Local cross-origin dev only -- the two Vite frontends (bolo-web on :5173,
# bolo-admin-console on :5174, ROADMAP.md Phase 15d) call this API directly at
# localhost:8000 instead of through a same-origin proxy like prod, so the browser
# needs an explicit CORS allow + credentials for the auth cookies (`token` /
# `admin_token`) to round-trip. SameSite=Lax is fine here -- localhost:5174 and
# localhost:8000 are the same site (same registrable domain), just different
# ports. Not in base.py/prod.py -- prod is same-origin, no CORS needed there.
INSTALLED_APPS = [*INSTALLED_APPS, "corsheaders"]  # noqa: F405
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware", *MIDDLEWARE]  # noqa: F405

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
CORS_ALLOW_CREDENTIALS = True
