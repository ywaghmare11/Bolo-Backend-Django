import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.comments.models import Comment
from apps.notifications.models import Notification
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


@pytest.fixture
def outsider(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def task(tenant, assigner, assignee):
    client = _authed_client(assigner, tenant.id)
    resp = client.post(
        "/api/v1/tasks/",
        {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-20T00:00:00Z"},
        format="json",
    )
    return resp.data["data"]["id"]


@pytest.mark.django_db
class TestCommentCreate:
    def test_assigner_comments_notifies_assignee(self, tenant, assigner, assignee, task):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(f"/api/v1/tasks/{task}/comments/", {"text": "A1 data compiled."}, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["authorId"] == str(assigner.id)
        assert resp.data["data"]["isEdited"] is False
        assert Notification.objects.filter(type="TASK_COMMENTED", recipient=assignee).exists()

    def test_assignee_comments_notifies_assigner(self, tenant, assigner, assignee, task):
        client = _authed_client(assignee, tenant.id)
        resp = client.post(f"/api/v1/tasks/{task}/comments/", {"text": "Working on B2."}, format="json")
        assert resp.status_code == 201
        assert Notification.objects.filter(type="TASK_COMMENTED", recipient=assigner).exists()

    def test_outsider_cannot_comment(self, tenant, outsider, task):
        client = _authed_client(outsider, tenant.id)
        resp = client.post(f"/api/v1/tasks/{task}/comments/", {"text": "Hi"}, format="json")
        assert resp.status_code == 403

    def test_empty_text_rejected(self, tenant, assigner, task):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(f"/api/v1/tasks/{task}/comments/", {"text": "   "}, format="json")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestCommentList:
    def test_lists_in_chronological_order_paginated(self, tenant, assigner, assignee, task):
        client = _authed_client(assigner, tenant.id)
        client.post(f"/api/v1/tasks/{task}/comments/", {"text": "First"}, format="json")
        client.post(f"/api/v1/tasks/{task}/comments/", {"text": "Second"}, format="json")

        resp = client.get(f"/api/v1/tasks/{task}/comments/")
        assert resp.status_code == 200
        assert [c["text"] for c in resp.data["data"]] == ["First", "Second"]
        assert resp.data["pagination"]["total"] == 2

    def test_outsider_cannot_list(self, tenant, outsider, task):
        client = _authed_client(outsider, tenant.id)
        resp = client.get(f"/api/v1/tasks/{task}/comments/")
        assert resp.status_code == 403


@pytest.mark.django_db
class TestCommentEditDelete:
    def _create(self, tenant, author, task, text="Original text"):
        resp = _authed_client(author, tenant.id).post(
            f"/api/v1/tasks/{task}/comments/", {"text": text}, format="json",
        )
        return resp.data["data"]["id"]

    def test_author_can_edit(self, tenant, assigner, task):
        comment_id = self._create(tenant, assigner, task)
        resp = _authed_client(assigner, tenant.id).patch(
            f"/api/v1/tasks/{task}/comments/{comment_id}/", {"text": "Edited text"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["isEdited"] is True
        assert resp.data["data"]["text"] == "Edited text"

    def test_non_author_cannot_edit(self, tenant, assigner, assignee, task):
        comment_id = self._create(tenant, assigner, task)
        resp = _authed_client(assignee, tenant.id).patch(
            f"/api/v1/tasks/{task}/comments/{comment_id}/", {"text": "Hijacked"}, format="json",
        )
        assert resp.status_code == 403

    def test_author_can_delete(self, tenant, assigner, task):
        comment_id = self._create(tenant, assigner, task)
        resp = _authed_client(assigner, tenant.id).delete(f"/api/v1/tasks/{task}/comments/{comment_id}/")
        assert resp.status_code == 200
        assert not Comment.objects.filter(id=comment_id).exists()

    def test_non_author_cannot_delete(self, tenant, assigner, assignee, task):
        comment_id = self._create(tenant, assigner, task)
        resp = _authed_client(assignee, tenant.id).delete(f"/api/v1/tasks/{task}/comments/{comment_id}/")
        assert resp.status_code == 403
        assert Comment.objects.filter(id=comment_id).exists()


@pytest.mark.django_db
class TestCommentTenantIsolation:
    """docs/engineering/testing-strategy.md critical case: "Tenant A cannot
    read/write Tenant B data (every entity)". The outsider tests above cover a
    same-tenant non-participant (-> 403); a caller from a *different* tenant is
    denied one step earlier by the tenant-scoped task lookup (-> 404, never
    revealing that the task exists)."""

    def test_caller_from_another_tenant_cannot_read_or_write_comments(
        self, tenant, assigner, task,
    ):
        Comment.objects.create(task_id=task, author=assigner, text="internal note")

        other_tenant = TenantFactory()
        intruder = UserFactory(tenant=other_tenant)
        client = _authed_client(intruder, other_tenant.id)

        assert client.get(f"/api/v1/tasks/{task}/comments/").status_code == 404
        assert (
            client.post(
                f"/api/v1/tasks/{task}/comments/", {"text": "injected"}, format="json",
            ).status_code
            == 404
        )
        assert Comment.objects.filter(task_id=task).count() == 1
