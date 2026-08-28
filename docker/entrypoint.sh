#!/bin/sh
# Container entrypoint. Blocks until Postgres accepts connections, optionally runs
# migrations (only where RUN_MIGRATIONS=1 -- the web service, never worker/beat),
# then hands off to the CMD (gunicorn, or celery for the worker/beat services).
set -e

python - <<'PY'
import os, sys, time
import psycopg
from urllib.parse import urlparse

url = urlparse(os.environ["DATABASE_URL"])
dsn = f"host={url.hostname} port={url.port or 5432} dbname={url.path.lstrip('/')} user={url.username} password={url.password}"
for attempt in range(1, 61):
    try:
        psycopg.connect(dsn, connect_timeout=3).close()
        print("postgres is ready")
        break
    except Exception as exc:  # noqa: BLE001
        print(f"waiting for postgres ({attempt}/60): {exc}")
        time.sleep(1)
else:
    sys.exit("postgres did not become ready in time")
PY

if [ "$RUN_MIGRATIONS" = "1" ]; then
    echo "running migrations"
    python manage.py migrate --noinput
fi

exec "$@"
