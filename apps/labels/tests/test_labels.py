import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.labels.models import ProjectLabel
from apps.tasks.factories import TaskFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level="MID"):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
    return client


@pytest.mark.django_db
class TestLabels:
    def test_create_label(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        resp = client.post("/api/v1/labels/", {"name": "Urgent"}, format="json")
        assert resp.status_code == 201
        assert resp.data["data"]["name"] == "Urgent"
        assert ProjectLabel.objects.filter(created_by=user, name="Urgent").exists()

    def test_duplicate_label_name_conflict(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        client.post("/api/v1/labels/", {"name": "Urgent"}, format="json")
        resp = client.post("/api/v1/labels/", {"name": "Urgent"}, format="json")
        assert resp.status_code == 409

    def test_mine_and_shared_scoped_to_creator(self):
        user = UserFactory()
        other = UserFactory(tenant=user.tenant)
        client = _authed_client(user, user.tenant_id)
        other_client = _authed_client(other, other.tenant_id)

        client.post("/api/v1/labels/", {"name": "Mine"}, format="json")
        other_client.post("/api/v1/labels/", {"name": "Theirs"}, format="json")

        resp = client.get("/api/v1/labels/mine/")
        assert [label["name"] for label in resp.data["data"]] == ["Mine"]

        resp = client.get("/api/v1/labels/shared/")
        assert [label["name"] for label in resp.data["data"]] == ["Mine"]

    def test_create_invalid_color_code_rejected(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        resp = client.post(
            "/api/v1/labels/", {"name": "Urgent", "colorCode": "blue"}, format="json",
        )
        assert resp.status_code == 400


@pytest.mark.django_db
class TestLabelUpdate:
    def test_creator_can_rename(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = client.patch(
            f"/api/v1/labels/{label_id}/", {"name": "NAAC Prep", "colorCode": "#3B82F6"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["name"] == "NAAC Prep"
        assert ProjectLabel.objects.get(id=label_id).color_code == "#3B82F6"

    def test_non_creator_cannot_update(self):
        user = UserFactory()
        other = UserFactory(tenant=user.tenant)
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = _authed_client(other, other.tenant_id).patch(
            f"/api/v1/labels/{label_id}/", {"name": "Hijacked"}, format="json",
        )
        assert resp.status_code == 404

    def test_update_with_no_fields_rejected(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = client.patch(f"/api/v1/labels/{label_id}/", {}, format="json")
        assert resp.status_code == 400

    def test_update_invalid_color_code_rejected(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = client.patch(f"/api/v1/labels/{label_id}/", {"colorCode": "red"}, format="json")
        assert resp.status_code == 400

    def test_update_to_duplicate_name_conflict(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        client.post("/api/v1/labels/", {"name": "Existing"}, format="json")
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = client.patch(f"/api/v1/labels/{label_id}/", {"name": "Existing"}, format="json")
        assert resp.status_code == 409


@pytest.mark.django_db
class TestLabelDelete:
    def test_creator_can_delete_unused_label(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = client.delete(f"/api/v1/labels/{label_id}/")
        assert resp.status_code == 200
        assert not ProjectLabel.objects.filter(id=label_id).exists()

    def test_non_creator_cannot_delete(self):
        user = UserFactory()
        other = UserFactory(tenant=user.tenant)
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]

        resp = _authed_client(other, other.tenant_id).delete(f"/api/v1/labels/{label_id}/")
        assert resp.status_code == 404
        assert ProjectLabel.objects.filter(id=label_id).exists()

    def test_delete_blocked_while_set_as_main_label(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "NAAC"}, format="json").data["data"]["id"]
        label = ProjectLabel.objects.get(id=label_id)
        TaskFactory(tenant_id=user.tenant_id, assigner=user, main_label=label)

        resp = client.delete(f"/api/v1/labels/{label_id}/")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "LABEL_IN_USE"
        assert ProjectLabel.objects.filter(id=label_id).exists()

    def test_delete_blocked_while_set_as_assignee_label(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)
        label_id = client.post("/api/v1/labels/", {"name": "urgent"}, format="json").data["data"]["id"]
        label = ProjectLabel.objects.get(id=label_id)
        TaskFactory(tenant_id=user.tenant_id, assignee=user, assignee_label=label)

        resp = client.delete(f"/api/v1/labels/{label_id}/")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "LABEL_IN_USE"
