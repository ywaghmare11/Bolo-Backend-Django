from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.common.enums import AcceptanceStatus, TaskStatus
from apps.notifications.models import Notification
from apps.tasks.factories import TaskFactory
from apps.tasks.models import Task
from apps.tasks.tasks import task_due_proximity_sweep
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


@pytest.fixture
def tenant():
    return TenantFactory()


@pytest.fixture
def assigner(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def assignee(tenant):
    return UserFactory(tenant=tenant)


@pytest.mark.django_db
class TestDueTodaySweep:
    def test_notifies_assignee_and_assigner_once(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN, due_date=timezone.now(),
        )
        task_due_proximity_sweep()

        task.refresh_from_db()
        assert task.due_today_notified_at is not None
        assert Notification.objects.filter(
            type="TASK_DUE_TODAY", recipient=assignee, entity_id=str(task.id),
        ).exists()
        assert Notification.objects.filter(
            type="TASK_DUE_TODAY", recipient=assigner, entity_id=str(task.id),
        ).exists()
        assert len(mail.outbox) == 2

    def test_does_not_refire_on_second_run(self, assigner, assignee):
        TaskFactory(assigner=assigner, assignee=assignee, status=TaskStatus.OPEN, due_date=timezone.now())
        task_due_proximity_sweep()
        task_due_proximity_sweep()

        assert Notification.objects.filter(type="TASK_DUE_TODAY").count() == 2

    def test_draft_task_not_included(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.DRAFT, due_date=timezone.now(),
        )
        task_due_proximity_sweep()
        assert not Notification.objects.filter(type="TASK_DUE_TODAY").exists()

    def test_done_d_task_not_included(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.DONE_D,
            due_date=timezone.now(), is_archived=True,
        )
        task_due_proximity_sweep()
        assert not Notification.objects.filter(type="TASK_DUE_TODAY").exists()


@pytest.mark.django_db
class TestDueTomorrowSweep:
    def test_notifies_for_task_due_tomorrow(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            due_date=timezone.now() + timedelta(days=1),
        )
        task_due_proximity_sweep()

        task.refresh_from_db()
        assert task.due_tomorrow_notified_at is not None
        assert Notification.objects.filter(type="TASK_DUE_TOMORROW", entity_id=str(task.id)).count() == 2

    def test_task_due_in_a_week_not_included(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() + timedelta(days=7),
        )
        task_due_proximity_sweep()
        assert not Notification.objects.filter(type="TASK_DUE_TOMORROW").exists()


@pytest.mark.django_db
class TestOverdueSweep:
    def test_transitions_status_and_notifies_once(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            due_date=timezone.now() - timedelta(days=2),
        )
        task_due_proximity_sweep()

        task.refresh_from_db()
        assert task.status == TaskStatus.OVERDUE
        assert Notification.objects.filter(type="TASK_OVERDUE", entity_id=str(task.id)).count() == 2

    def test_due_today_is_not_yet_overdue(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN, due_date=timezone.now(),
        )
        task_due_proximity_sweep()

        task.refresh_from_db()
        assert task.status == TaskStatus.OPEN
        assert not Notification.objects.filter(type="TASK_OVERDUE").exists()

    def test_second_run_does_not_refire_overdue(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() - timedelta(days=2),
        )
        task_due_proximity_sweep()
        task_due_proximity_sweep()

        assert Notification.objects.filter(type="TASK_OVERDUE").count() == 2


@pytest.mark.django_db
class TestOverdueReverseTransition:
    def test_editing_due_date_forward_reopens_in_progress_task(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now() - timedelta(days=2),
        )
        from apps.tasks.services import TaskService

        TaskService.update_task(
            assigner, tenant.id, task.id, {"due_date": timezone.now() + timedelta(days=3)},
        )
        task.refresh_from_db()
        assert task.status == TaskStatus.IN_PROGRESS

    def test_editing_due_date_forward_reopens_unaccepted_task_to_open(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.PENDING, due_date=timezone.now() - timedelta(days=2),
        )
        from apps.tasks.services import TaskService

        TaskService.update_task(
            assigner, tenant.id, task.id, {"due_date": timezone.now() + timedelta(days=3)},
        )
        task.refresh_from_db()
        assert task.status == TaskStatus.OPEN

    def test_due_date_change_resets_notified_flags(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now(),
        )
        task_due_proximity_sweep()
        task.refresh_from_db()
        assert task.due_today_notified_at is not None

        from apps.tasks.services import TaskService

        TaskService.update_task(
            assigner, tenant.id, task.id, {"due_date": timezone.now() + timedelta(days=10)},
        )
        task.refresh_from_db()
        assert task.due_today_notified_at is None


@pytest.mark.django_db
class TestSubtasksIncluded:
    def test_subtask_due_today_is_swept_like_any_task(self, tenant, assigner, assignee):
        parent = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            due_date=timezone.now() + timedelta(days=5),
        )
        subtask = Task.objects.create(
            tenant_id=tenant.id, title="Subtask", assigner=assigner, assignee=assignee,
            status=TaskStatus.IN_PROGRESS, due_date=timezone.now(), parent_task=parent,
        )
        task_due_proximity_sweep()
        subtask.refresh_from_db()
        assert subtask.due_today_notified_at is not None
