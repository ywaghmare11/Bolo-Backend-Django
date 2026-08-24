import os

import structlog
from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("bolo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = structlog.get_logger("bolo")


# Generic observer via Celery's own signals, same "hook in once, not per-task-function"
# shape as apps/common/audit_middleware.py -- guidelines.md's Logging section asks for
# "Celery task start/complete" at info level; wiring every individual @shared_task in
# apps/{tasks,notifications,broadcasts,sticky_notes,common}/tasks.py by hand would mean
# editing five files (and every future one) instead of hooking in here once. No shared
# mutable state between prerun/postrun (e.g. a dict keyed by task_id) to compute a
# duration -- a worker pool can run tasks concurrently in one process (eventlet/gevent),
# which would make that racy; each line's own structlog timestamp is enough to derive
# duration from the logs without that risk.
@task_prerun.connect
def _log_task_prerun(task_id, task, **kwargs):
    logger.info("celery_task_started", task_name=task.name, task_id=task_id)


@task_postrun.connect
def _log_task_postrun(task_id, task, state, **kwargs):
    logger.info("celery_task_finished", task_name=task.name, task_id=task_id, state=state)


@task_failure.connect
def _log_task_failure(task_id, exception, sender, **kwargs):
    logger.error(
        "celery_task_failed",
        task_name=sender.name if sender else None,
        task_id=task_id,
        error=str(exception),
    )
