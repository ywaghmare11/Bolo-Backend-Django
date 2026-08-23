import pytest
from rest_framework.test import APIClient

from apps.common.enums import OrgRoleLevel, Vertical
from apps.platform_admin.models import PlatformAdmin
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.factories import TenantFactory, TenantMembershipFactory
from apps.tenants.models import Tenant, TenantMembership
from apps.users.factories import UserFactory
from apps.users.models import User


@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


def _authed_client(admin):
    client = APIClient()
    client.cookies["admin_token"] = issue_admin_access_token(admin.id, admin.email)
    return client


@pytest.mark.django_db
class TestCreateTenant:
    def _payload(self, **overrides):
        payload = {
            "tenantName": "ABC College",
            "urlSlug": "abc-college",
            "vertical": Vertical.EDUCATION,
            "adminName": "Dr. Kamal Sethi",
            "adminEmail": "dean@abc.edu",
            "roleLabel": "Dean",
        }
        payload.update(overrides)
        return payload

    def test_requires_platform_admin_auth(self):
        client = APIClient()
        resp = client.post("/api/v1/platform-admin/tenants/", self._payload(), format="json")
        assert resp.status_code == 401

    def test_creates_tenant_and_first_top_user(self, admin):
        client = _authed_client(admin)
        resp = client.post("/api/v1/platform-admin/tenants/", self._payload(), format="json")

        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["tenantName"] == "ABC College"
        assert data["urlSlug"] == "abc-college"
        assert data["vertical"] == Vertical.EDUCATION
        assert data["admin"]["email"] == "dean@abc.edu"
        assert data["admin"]["roleLevel"] == OrgRoleLevel.TOP

        tenant = Tenant.objects.get(name="ABC College")
        assert tenant.url_slug == "abc-college"
        admin_user = User.objects.get(email="dean@abc.edu")
        membership = TenantMembership.objects.get(tenant=tenant, user=admin_user)
        assert membership.role_level == OrgRoleLevel.TOP
        assert membership.can_broadcast is True

    def test_rejects_malformed_url_slug(self, admin):
        client = _authed_client(admin)
        resp = client.post(
            "/api/v1/platform-admin/tenants/", self._payload(urlSlug="Not Valid!"), format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "INVALID_URL_SLUG"

    def test_rejects_duplicate_tenant_name(self, admin):
        TenantFactory(name="ABC College")
        client = _authed_client(admin)
        resp = client.post("/api/v1/platform-admin/tenants/", self._payload(), format="json")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "TENANT_NAME_TAKEN"

    def test_rejects_duplicate_url_slug(self, admin):
        TenantFactory(name="Other College", url_slug="abc-college")
        client = _authed_client(admin)
        resp = client.post("/api/v1/platform-admin/tenants/", self._payload(), format="json")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "URL_SLUG_TAKEN"

    def test_rejects_duplicate_admin_email(self, admin):
        UserFactory(email="dean@abc.edu")
        client = _authed_client(admin)
        resp = client.post("/api/v1/platform-admin/tenants/", self._payload(), format="json")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "EMAIL_TAKEN"


@pytest.mark.django_db
class TestListTenants:
    def test_requires_platform_admin_auth(self):
        client = APIClient()
        resp = client.get("/api/v1/platform-admin/tenants/")
        assert resp.status_code == 401

    def test_lists_all_tenants_with_counts(self, admin):
        tenant = TenantFactory(name="ABC College")
        TenantMembershipFactory(tenant=tenant, user=UserFactory(tenant=tenant))
        TenantMembershipFactory(tenant=tenant, user=UserFactory(tenant=tenant))
        TenantFactory(name="XYZ Firm")

        client = _authed_client(admin)
        resp = client.get("/api/v1/platform-admin/tenants/")

        assert resp.status_code == 200
        by_name = {row["name"]: row for row in resp.data["data"]}
        assert by_name["ABC College"]["memberCount"] == 2
        assert by_name["XYZ Firm"]["memberCount"] == 0


@pytest.mark.django_db
class TestAddMember:
    def test_requires_platform_admin_auth(self):
        tenant = TenantFactory()
        client = APIClient()
        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {"name": "Prof. Nair", "email": "nair@abc.edu", "roleLevel": OrgRoleLevel.MID},
            format="json",
        )
        assert resp.status_code == 401

    def test_adds_member_to_any_tenant(self, admin):
        tenant = TenantFactory()
        client = _authed_client(admin)

        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {
                "name": "Prof. Asha Nair", "email": "asha@abc.edu",
                "roleLevel": OrgRoleLevel.MID, "roleLabel": "HoD",
            },
            format="json",
        )

        assert resp.status_code == 201
        assert resp.data["data"]["email"] == "asha@abc.edu"
        user = User.objects.get(email="asha@abc.edu")
        assert user.tenant_id == tenant.id
        membership = TenantMembership.objects.get(tenant=tenant, user=user)
        assert membership.role_level == OrgRoleLevel.MID
        assert membership.role_label == "HoD"

    def test_rejects_email_already_in_use(self, admin):
        tenant = TenantFactory()
        UserFactory(email="asha@abc.edu")
        client = _authed_client(admin)

        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {"name": "Prof. Nair", "email": "asha@abc.edu", "roleLevel": OrgRoleLevel.MID},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "EMAIL_ALREADY_IN_TENANT"

    def test_404_for_unknown_tenant(self, admin):
        client = _authed_client(admin)
        resp = client.post(
            "/api/v1/platform-admin/tenants/00000000-0000-0000-0000-000000000000/members/",
            {"name": "Prof. Nair", "email": "nair@abc.edu", "roleLevel": OrgRoleLevel.MID},
            format="json",
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestRemoveMember:
    def test_removes_membership_but_keeps_user_row(self, admin):
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        TenantMembershipFactory(tenant=tenant, user=user)
        client = _authed_client(admin)

        resp = client.delete(f"/api/v1/platform-admin/tenants/{tenant.id}/members/{user.id}/")

        assert resp.status_code == 200
        assert not TenantMembership.objects.filter(tenant=tenant, user=user).exists()
        assert User.objects.filter(id=user.id).exists()

    def test_404_for_nonexistent_membership(self, admin):
        tenant = TenantFactory()
        user = UserFactory()
        client = _authed_client(admin)

        resp = client.delete(f"/api/v1/platform-admin/tenants/{tenant.id}/members/{user.id}/")
        assert resp.status_code == 404
