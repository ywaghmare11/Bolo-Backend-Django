import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.labels.models import ProjectLabel
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
