"""Service-layer unit tests for Task business rules (ROADMAP.md Phase 11:
"Service-layer unit tests for every business rule ... cascade cancel, etc.").

These call TaskService directly rather than going through the HTTP layer -- the
rules here are enforced in the service, and a few of them (cancel-cascade,
assignee_label clearing on reassignment) were previously only exercised
indirectly, or not at all, by the API-level tests in test_tasks.py /
test_subtasks.py. The rules that already have a direct service-layer test
elsewhere (OVERDUE reverse-transition in test_due_proximity_sweep.py) are not
duplicated here.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.common.enums import TaskStatus
from apps.common.exceptions import ConflictError
from apps.labels.models import ProjectLabel
from apps.tasks.factories import TaskFactory
from apps.tasks.models import Task
from apps.tasks.services import TaskService
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


def _subtask(tenant, parent, assigner, assignee, status=TaskStatus.OPEN):
    return Task.objects.create(
        tenant_id=tenant.id, title="Subtask", assigner=assigner, assignee=assignee,
        status=status, due_date=timezone.now() + timedelta(days=1), parent_task=parent,
    )


@pytest.mark.django_db
class TestCancelCascade:
    def test_cancelling_parent_cancels_non_terminal_subtasks_only(self, tenant, assigner, assignee):
        parent = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.IN_PROGRESS, due_date=timezone.now() + timedelta(days=10),
        )
        open_sub = _subtask(tenant, parent, assignee, assigner, status=TaskStatus.OPEN)
        in_progress_sub = _subtask(tenant, parent, assignee, assigner, status=TaskStatus.IN_PROGRESS)
        done_sub = _subtask(tenant, parent, assignee, assigner, status=TaskStatus.DONE_D)

        TaskService.cancel_task(assigner, tenant.id, parent.id)

        for obj in (parent, open_sub, in_progress_sub, done_sub):
            obj.refresh_from_db()
        assert parent.status == TaskStatus.CANCELLED
        assert open_sub.status == TaskStatus.CANCELLED
        assert in_progress_sub.status == TaskStatus.CANCELLED
        # A subtask that already reached DONE_D is terminal -- the cascade leaves it be.
        assert done_sub.status == TaskStatus.DONE_D

    def test_cancelling_an_already_done_d_task_is_a_conflict(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.DONE_D, is_archived=True,
        )
        with pytest.raises(ConflictError) as exc:
            TaskService.cancel_task(assigner, tenant.id, task.id)
        assert exc.value.code == "TASK_TERMINAL"


@pytest.mark.django_db
class TestReassignment:
    def test_reassigning_a_task_clears_the_assignee_private_label(self, tenant, assigner, assignee):
        personal_label = ProjectLabel.objects.create(
            tenant_id=tenant.id, created_by=assignee, name="follow-up",
        )
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() + timedelta(days=5), assignee_label=personal_label,
        )
        new_assignee = UserFactory(tenant=tenant)

        TaskService.update_task(assigner, tenant.id, task.id, {"assignee_id": new_assignee.id})

        task.refresh_from_db()
        assert task.assignee_id == new_assignee.id
        assert task.assignee_label_id is None

    def test_reassignment_is_blocked_once_any_subtask_exists(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.IN_PROGRESS, due_date=timezone.now() + timedelta(days=5),
        )
        _subtask(tenant, task, assignee, assigner)
        new_assignee = UserFactory(tenant=tenant)

        with pytest.raises(ConflictError) as exc:
            TaskService.update_task(assigner, tenant.id, task.id, {"assignee_id": new_assignee.id})
        assert exc.value.code == "REASSIGN_BLOCKED"
        task.refresh_from_db()
        assert task.assignee_id == assignee.id
