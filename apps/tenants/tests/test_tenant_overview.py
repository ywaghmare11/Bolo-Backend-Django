import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
    return client


@pytest.mark.django_db
class TestTenantOverview:
    def test_top_role_can_view(self):
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        client = _authed_client(user, tenant.id, "TOP")

        resp = client.get("/api/v1/tenant/")

        assert resp.status_code == 200
        assert resp.data["data"]["id"] == str(tenant.id)
        assert resp.data["data"]["memberCount"] == 0
        assert resp.data["data"]["deptCount"] == 0

    @pytest.mark.parametrize("role_level", ["MID", "EXECUTOR"])
    def test_non_top_role_forbidden(self, role_level):
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        client = _authed_client(user, tenant.id, role_level)

        resp = client.get("/api/v1/tenant/")

        assert resp.status_code == 403

    def test_unauthenticated_rejected(self):
        client = APIClient()
        resp = client.get("/api/v1/tenant/")
        assert resp.status_code == 401
