from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import TaskStatus
from apps.labels.models import ProjectLabel
from apps.tasks.factories import TaskFactory
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, "MID")
    return client


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
class TestStatusViews:
    def test_open_view_scoped_to_status_and_participant(self, tenant, assigner, assignee):
        open_task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.OPEN, due_date=timezone.now() + timedelta(days=3),
        )
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.IN_PROGRESS, due_date=timezone.now() + timedelta(days=3),
        )
        outsider = UserFactory(tenant=tenant)

        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/?view=open")
        assert resp.status_code == 200
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(open_task.id)]

        outsider_resp = _authed_client(outsider, tenant.id).get("/api/v1/tasks/?view=open")
        assert outsider_resp.data["data"] == []

    def test_overdue_view(self, tenant, assigner, assignee):
        overdue_task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
        )
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN)

        client = _authed_client(assignee, tenant.id)
        resp = client.get("/api/v1/tasks/?view=overdue")
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(overdue_task.id)]

    def test_done_a_view(self, tenant, assigner, assignee):
        done_a_task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.DONE_A,
        )
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.DONE_D)

        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/?view=done_a")
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(done_a_task.id)]


@pytest.mark.django_db
class TestByLabelView:
    def test_requires_label_id(self, tenant, assigner):
        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/?view=by_label")
        assert resp.status_code == 400

    def test_includes_main_label_tasks_as_assigner(self, tenant, assigner, assignee):
        label = ProjectLabel.objects.create(tenant=tenant, name="NAAC", created_by=assigner)
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, main_label=label,
        )
        client = _authed_client(assigner, tenant.id)
        resp = client.get(f"/api/v1/tasks/?view=by_label&labelId={label.id}")
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(task.id)]

    def test_excludes_main_label_task_for_assignee_with_personal_override(
        self, tenant, assigner, assignee,
    ):
        main_label = ProjectLabel.objects.create(tenant=tenant, name="NAAC", created_by=assigner)
        personal_label = ProjectLabel.objects.create(tenant=tenant, name="Urgent", created_by=assignee)
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            main_label=main_label, assignee_label=personal_label,
        )

        client = _authed_client(assignee, tenant.id)
        main_label_resp = client.get(f"/api/v1/tasks/?view=by_label&labelId={main_label.id}")
        assert main_label_resp.data["data"] == []

        personal_label_resp = client.get(f"/api/v1/tasks/?view=by_label&labelId={personal_label.id}")
        ids = [row["id"] for row in personal_label_resp.data["data"]]
        assert ids == [str(task.id)]

    def test_includes_main_label_task_for_assignee_without_override(self, tenant, assigner, assignee):
        main_label = ProjectLabel.objects.create(tenant=tenant, name="NAAC", created_by=assigner)
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee, main_label=main_label,
        )
        client = _authed_client(assignee, tenant.id)
        resp = client.get(f"/api/v1/tasks/?view=by_label&labelId={main_label.id}")
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(task.id)]


@pytest.mark.django_db
class TestDueThisWeekView:
    def test_includes_task_due_within_current_week_excludes_outside(self, tenant, assigner, assignee):
        today = timezone.localdate()
        this_week_task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.OPEN, due_date=timezone.now(),
        )
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.OPEN, due_date=timezone.now() + timedelta(days=30),
        )
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.DRAFT, due_date=None,
        )

        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/?view=due_this_week")
        ids = [row["id"] for row in resp.data["data"]]
        assert ids == [str(this_week_task.id)]
        assert today.isoformat()  # sanity: fixture ran under a real localdate

    def test_excludes_cancelled_and_done_d(self, tenant, assigner, assignee):
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.CANCELLED, due_date=timezone.now(),
        )
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.DONE_D, due_date=timezone.now(),
        )
        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/?view=due_this_week")
        assert resp.data["data"] == []


@pytest.mark.django_db
class TestTaskCounts:
    def test_counts_include_new_view_fields(self, tenant, assigner, assignee):
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OPEN)
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE)
        TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.DONE_A)
        TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status=TaskStatus.OPEN, due_date=timezone.now(),
        )

        client = _authed_client(assigner, tenant.id)
        resp = client.get("/api/v1/tasks/counts/")
        data = resp.data["data"]
        assert data["open"] == 2
        assert data["overdue"] == 1
        assert data["doneA"] == 1
        assert data["dueThisWeek"] == 1
