import pytest
from structlog.testing import capture_logs

from apps.common.tasks import write_audit_log_task


@pytest.mark.django_db
class TestCeleryTaskLogging:
    """config/celery.py's task_prerun/task_postrun/task_failure signal handlers --
    a generic observer (same shape as apps/common/audit_middleware.py) rather than
    hand-written start/finish log calls inside every @shared_task. CELERY_TASK_ALWAYS_EAGER
    (config/settings/test.py) runs tasks synchronously in-process, but Celery still
    fires these signals for eager tasks the same as it would for a real worker."""

    def test_successful_task_logs_started_and_finished(self, tenant):
        with capture_logs() as cap:
            write_audit_log_task.delay(
                tenant_id=tenant.id, actor_id=None, entity_type="TASK", entity_id="fake-id",
                action="TASK_CREATED", before=None, after=None,
            )

        started = [e for e in cap if e["event"] == "celery_task_started"]
        finished = [e for e in cap if e["event"] == "celery_task_finished"]
        assert len(started) == 1
        assert len(finished) == 1
        assert started[0]["task_name"] == "apps.common.write_audit_log"
        assert finished[0]["task_name"] == "apps.common.write_audit_log"
        assert finished[0]["state"] == "SUCCESS"

    def test_failing_task_logs_failure(self, settings):
        # CELERY_TASK_EAGER_PROPAGATES (config/settings/test.py) makes .delay() itself
        # re-raise the task's exception synchronously -- real Celery's own failure
        # machinery (what actually sends task_failure) never runs on that path, only
        # on a real worker's request lifecycle. Turning propagation off for just this
        # test is what lets the real signal-firing codepath run under eager execution;
        # every other test in this project relies on propagate=True precisely so a
        # task's exception surfaces immediately instead of vanishing into a queue.
        settings.CELERY_TASK_EAGER_PROPAGATES = False
        from celery import shared_task

        @shared_task(name="apps.common.tests._always_fails")
        def _always_fails():
            raise ValueError("boom")

        with capture_logs() as cap:
            _always_fails.delay()

        failures = [e for e in cap if e["event"] == "celery_task_failed"]
        assert len(failures) == 1
        assert failures[0]["log_level"] == "error"
        assert "boom" in failures[0]["error"]


@pytest.fixture
def tenant():
    from apps.tenants.factories import TenantFactory

    return TenantFactory()
