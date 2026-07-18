import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import TaskStatus
from apps.notifications.models import Notification
from apps.tasks.models import Task
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level="MID"):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
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
class TestTaskLifecycle:
    def test_create_with_due_date_is_open_and_notifies(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["data"]["status"] == "OPEN"
        task_id = resp.data["data"]["id"]
        assert Notification.objects.filter(
            type="TASK_ASSIGNED", recipient=assignee, entity_id=task_id,
        ).exists()

    def test_create_without_due_date_is_draft_no_notification(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/", {"title": "Draft task", "assigneeId": str(assignee.id)}, format="json",
        )
        assert resp.status_code == 201
        assert resp.data["data"]["status"] == "DRAFT"
        assert not Notification.objects.filter(type="TASK_ASSIGNED").exists()

    def test_full_lifecycle_chain(self, tenant, assigner, assignee):
        assigner_client = _authed_client(assigner, tenant.id)
        assignee_client = _authed_client(assignee, tenant.id)

        resp = assigner_client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]

        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/accept/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "IN_PROGRESS"
        assert Notification.objects.filter(type="TASK_ACCEPTED", recipient=assigner).exists()

        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/done-a/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "DONE_A"
        assert Notification.objects.filter(type="TASK_DONE_A", recipient=assigner).exists()

        resp = assigner_client.post(f"/api/v1/tasks/{task_id}/done-d/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "DONE_D"
        assert resp.data["data"]["isArchived"] is True
        assert Notification.objects.filter(type="TASK_DONE_D", recipient=assignee).exists()

    def test_patch_clearing_due_date_reverts_to_draft(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]
        resp = client.patch(f"/api/v1/tasks/{task_id}/", {"dueDate": None}, format="json")
        assert resp.status_code == 200
        assert Task.objects.get(id=task_id).status == TaskStatus.DRAFT

    def test_patch_with_title_rejected(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/", {"title": "Ship report", "assigneeId": str(assignee.id)}, format="json",
        )
        task_id = resp.data["data"]["id"]
        resp = client.patch(f"/api/v1/tasks/{task_id}/", {"title": "New title"}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "TITLE_IMMUTABLE"

    def test_delete_done_d_task_rejected(self, tenant, assigner, assignee):
        assigner_client = _authed_client(assigner, tenant.id)
        assignee_client = _authed_client(assignee, tenant.id)
        resp = assigner_client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]
        assignee_client.post(f"/api/v1/tasks/{task_id}/accept/")
        assignee_client.post(f"/api/v1/tasks/{task_id}/done-a/")
        assigner_client.post(f"/api/v1/tasks/{task_id}/done-d/")

        resp = assigner_client.delete(f"/api/v1/tasks/{task_id}/")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "TASK_TERMINAL"

    def test_delete_non_terminal_task_succeeds(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/", {"title": "Ship report", "assigneeId": str(assignee.id)}, format="json",
        )
        task_id = resp.data["data"]["id"]
        resp = client.delete(f"/api/v1/tasks/{task_id}/")
        assert resp.status_code == 200
        assert not Task.objects.filter(id=task_id).exists()

    def test_remind_sends_notification_and_email(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]
        mail.outbox.clear()
        resp = client.post(f"/api/v1/tasks/{task_id}/remind/")
        assert resp.status_code == 200
        assert Notification.objects.filter(type="TASK_REMINDER", recipient=assignee).exists()
        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestTaskPermissions:
    def test_non_assignee_cannot_accept(self, tenant, assigner, assignee):
        other = UserFactory(tenant=tenant)
        assigner_client = _authed_client(assigner, tenant.id)
        resp = assigner_client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]

        other_client = _authed_client(other, tenant.id)
        resp = other_client.post(f"/api/v1/tasks/{task_id}/accept/")
        assert resp.status_code == 403

    def test_non_assigner_cannot_cancel(self, tenant, assigner, assignee):
        assigner_client = _authed_client(assigner, tenant.id)
        assignee_client = _authed_client(assignee, tenant.id)
        resp = assigner_client.post(
            "/api/v1/tasks/", {"title": "Ship report", "assigneeId": str(assignee.id)}, format="json",
        )
        task_id = resp.data["data"]["id"]

        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/cancel/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestTenantScoping:
    def test_cross_tenant_task_detail_is_404(self, tenant, assigner, assignee):
        client_a = _authed_client(assigner, tenant.id)

        other_tenant = TenantFactory()
        other_assigner = UserFactory(tenant=other_tenant)
        other_assignee = UserFactory(tenant=other_tenant)
        other_client = _authed_client(other_assigner, other_tenant.id)
        resp = other_client.post(
            "/api/v1/tasks/",
            {"title": "Other tenant task", "assigneeId": str(other_assignee.id)},
            format="json",
        )
        other_task_id = resp.data["data"]["id"]

        resp = client_a.get(f"/api/v1/tasks/{other_task_id}/")
        assert resp.status_code == 404
