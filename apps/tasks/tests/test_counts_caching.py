"""Phase 12 -- cache-aside for GET /tasks/counts.

Tested at the service layer so query counts are unambiguous (no auth-middleware
user lookup in the way). `conftest.py` clears the cache between tests, so each
test starts cold.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.common import caching
from apps.common.enums import TaskStatus
from apps.tasks.factories import TaskFactory
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


@pytest.mark.django_db
class TestCountsCacheAside:
    def test_second_call_is_served_from_cache_with_no_queries(
        self, django_assert_num_queries, tenant, assigner, assignee,
    ):
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN)

        first = TaskService.get_counts(assigner, tenant.id)
        with django_assert_num_queries(0):
            second = TaskService.get_counts(assigner, tenant.id)
        assert second == first
        assert second["open"] == 1

    def test_counts_are_cached_per_user(self, tenant, assigner, assignee):
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN)

        assigner_counts = TaskService.get_counts(assigner, tenant.id)
        assignee_counts = TaskService.get_counts(assignee, tenant.id)
        # same task, different perspective -- the two cache entries must not collide
        assert assigner_counts["delegated"] == 1
        assert assigner_counts["assigned"] == 0
        assert assignee_counts["assigned"] == 1
        assert assignee_counts["delegated"] == 0


@pytest.mark.django_db
class TestCountsInvalidation:
    def _warm(self, *users_and_tenant):
        tenant_id = users_and_tenant[-1]
        for user in users_and_tenant[:-1]:
            TaskService.get_counts(user, tenant_id)

    def test_create_task_busts_both_participants(self, tenant, assigner, assignee):
        self._warm(assigner, assignee, tenant.id)

        TaskService.create_task(
            assigner, tenant.id, title="New", assignee_id=assignee.id,
            due_date=timezone.now() + timedelta(days=3), priority="P3",
            main_label_id=None, description="",
        )

        assert TaskService.get_counts(assigner, tenant.id)["delegated"] == 1
        assert TaskService.get_counts(assignee, tenant.id)["assigned"] == 1

    def test_reassignment_busts_old_and_new_assignee_and_assigner(self, tenant, assigner, assignee):
        new_assignee = UserFactory(tenant=tenant)
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() + timedelta(days=3),
        )
        self._warm(assigner, assignee, new_assignee, tenant.id)

        TaskService.update_task(assigner, tenant.id, task.id, {"assignee_id": new_assignee.id})

        assert TaskService.get_counts(assignee, tenant.id)["assigned"] == 0
        assert TaskService.get_counts(new_assignee, tenant.id)["assigned"] == 1
        assert TaskService.get_counts(assigner, tenant.id)["delegated"] == 1

    def test_status_transition_busts_counts(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() + timedelta(days=3),
        )
        assert TaskService.get_counts(assignee, tenant.id)["open"] == 1

        TaskService.accept_task(assignee, tenant.id, task.id)

        # OPEN -> IN_PROGRESS: drops out of the `open` and `needsAttention` tabs
        counts = TaskService.get_counts(assignee, tenant.id)
        assert counts["open"] == 0
        assert counts["needsAttention"] == 0

    def test_cancel_busts_counts(self, tenant, assigner, assignee):
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            due_date=timezone.now() + timedelta(days=3),
        )
        assert TaskService.get_counts(assignee, tenant.id)["assigned"] == 1

        TaskService.cancel_task(assigner, tenant.id, task.id)

        assert TaskService.get_counts(assignee, tenant.id)["assigned"] == 0

    def test_helper_ignores_none_and_dedups(self):
        # bust_task_counts is called with assigner/assignee/previous-assignee, any
        # of which can be None or equal -- must not raise or fan out redundantly.
        caching.bust_task_counts("tenant-x", None, "u1", "u1", None)
