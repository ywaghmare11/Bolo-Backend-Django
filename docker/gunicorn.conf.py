"""Gunicorn config for the container. Values are overridable via GUNICORN_* env
vars so the same image can be tuned per environment (ECS task size, etc.)."""
import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# 2*CPU + 1 is the usual starting point for sync workers; pin explicitly in prod
# (GUNICORN_WORKERS) once the ECS task's CPU allocation is known.
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get("GUNICORN_THREADS", 1))

# Recycle workers periodically to cap the impact of any slow memory leak.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 1000))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", 100))

timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", 30))

# Log to stdout/stderr -- the container runtime (ECS awslogs driver) ships these
# to CloudWatch. structlog already renders app logs as JSON (see settings.base).
accesslog = "-"
errorlog = "-"
