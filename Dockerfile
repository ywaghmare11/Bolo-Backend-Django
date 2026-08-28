# syntax=docker/dockerfile:1
#
# Multi-stage build. Stage 1 installs the Python dependencies into an isolated
# virtualenv; stage 2 is the lean runtime image that copies only that venv plus
# the application code. Nothing from the build toolchain (pip cache, compilers)
# ends up in the shipped image, and the container runs as a non-root user.
#
# Build:  docker build -t bolo-backend .
# Run:    docker run --env-file .env -p 8000:8000 bolo-backend

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dedicated venv so stage 2 can copy one self-contained directory.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements first -- this layer is cached and re-run only when a
# requirements file actually changes, not on every code edit.
COPY requirements/ requirements/
RUN pip install -r requirements/prod.txt

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# Unprivileged user -- the process never runs as root inside the container.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
# WORKDIR was created as root -- hand the whole tree (dir included) to the app
# user so the non-root process can write runtime files (e.g. celery beat's
# schedule cache) if it needs to.
RUN chown app:app /app

# Bake the collected static files (admin CSS/JS + Swagger/ReDoc assets) into the
# image so the container is immutable and starts without a build step. The real
# secrets are injected at run time; these build-only dummies just satisfy
# settings validation for a command that never touches the DB or network.
RUN DJANGO_SECRET_KEY=build-only \
    JWT_SECRET=build-only \
    DATABASE_URL=sqlite:// \
    REDIS_URL=redis://localhost:6379/0 \
    ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

USER app

EXPOSE 8000

# entrypoint waits for Postgres (and optionally runs migrations); the CMD is the
# process it then exec's -- overridden to `celery ...` for the worker/beat services.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "docker/gunicorn.conf.py"]
