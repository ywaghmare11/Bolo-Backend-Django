"""Phase 15a -- RBAC on PlatformAdmin.

Covers the HasPlatformAdminRole([...]) factory in isolation, the `role` claim
riding in the admin_token JWT, the authentication class exposing
request.platform_admin_role (with a DB fallback for pre-migration tokens), and
the three tenant-management endpoints actually enforcing it.
"""
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.common.enums import OrgRoleLevel, PlatformAdminRole, Vertical
from apps.common.permissions import HasPlatformAdminRole
from apps.platform_admin.models import PlatformAdmin
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.factories import TenantFactory

_ABSENT = object()


class _FakeRequest:
    def __init__(self, role=_ABSENT):
        if role is not _ABSENT:
            self.platform_admin_role = role


class TestHasPlatformAdminRoleFactory:
    """Structurally identical to HasOrgRole -- pure attribute check, no DB, no view."""

    def _perm(self):
        return HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])()

    def test_allows_matching_role(self):
        assert self._perm().has_permission(_FakeRequest(PlatformAdminRole.SUPER_ADMIN), None) is True

    def test_denies_non_matching_role(self):
        assert self._perm().has_permission(_FakeRequest("SUPPORT_ADMIN"), None) is False

    def test_denies_when_role_is_none(self):
        assert self._perm().has_permission(_FakeRequest(None), None) is False

    def test_denies_when_attribute_absent(self):
        # A request that never went through PlatformAdminCookieJWTAuthentication.
        assert self._perm().has_permission(_FakeRequest(), None) is False

    def test_multi_role_allow_list(self):
        perm = HasPlatformAdminRole(["SUPPORT_ADMIN", PlatformAdminRole.SUPER_ADMIN])()
        assert perm.has_permission(_FakeRequest(PlatformAdminRole.SUPER_ADMIN), None) is True
        assert perm.has_permission(_FakeRequest("VIEWER"), None) is False


@pytest.mark.django_db
class TestRoleModelAndToken:
    def test_role_defaults_to_super_admin(self):
        admin = PlatformAdmin.objects.create(name="Ops", email="ops@bolo.internal")
        assert admin.role == PlatformAdminRole.SUPER_ADMIN

    def test_issued_token_carries_role_claim(self):
        admin = PlatformAdmin.objects.create(name="Ops", email="ops@bolo.internal")
        raw = issue_admin_access_token(admin.id, admin.email, admin.role)
        assert AccessToken(raw)["role"] == PlatformAdminRole.SUPER_ADMIN
        # still no tenant-user claims -- the two token shapes stay disjoint
        decoded = AccessToken(raw)
        assert "tenantId" not in decoded and "roleLevel" not in decoded


@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


def _legacy_token(admin):
    """An admin_token minted before the `role` claim existed (7-day lifetime,
    so real ones linger across a deploy)."""
    token = AccessToken()
    token["adminId"] = str(admin.id)
    token["email"] = admin.email
    token["isPlatformAdmin"] = True
    return str(token)


def _token_with_role(admin, role):
    token = AccessToken()
    token["adminId"] = str(admin.id)
    token["email"] = admin.email
    token["isPlatformAdmin"] = True
    token["role"] = role
    return str(token)


@pytest.mark.django_db
class TestEndpointEnforcement:
    def _client(self, raw_token):
        client = APIClient()
        client.cookies["admin_token"] = raw_token
        return client

    def test_super_admin_can_list_tenants(self, admin):
        TenantFactory(name="ABC College")
        resp = self._client(issue_admin_access_token(admin.id, admin.email, admin.role)).get(
            "/api/v1/platform-admin/tenants/",
        )
        assert resp.status_code == 200

    def test_super_admin_can_create_tenant(self, admin):
        resp = self._client(issue_admin_access_token(admin.id, admin.email, admin.role)).post(
            "/api/v1/platform-admin/tenants/",
            {
                "tenantName": "XYZ Firm", "urlSlug": "xyz-firm", "vertical": Vertical.CA_CS,
                "adminName": "CA Rao", "adminEmail": "rao@xyz.in",
            },
            format="json",
        )
        assert resp.status_code == 201

    def test_token_with_unknown_role_is_forbidden_not_unauthorized(self, admin):
        # Validly signed, right auth space, but a role outside the allow-list ->
        # 403 (authenticated, not permitted), never 401.
        resp = self._client(_token_with_role(admin, "VIEWER")).get(
            "/api/v1/platform-admin/tenants/",
        )
        assert resp.status_code == 403

    def test_unknown_role_blocked_on_every_management_endpoint(self, admin):
        client = self._client(_token_with_role(admin, "VIEWER"))
        tenant = TenantFactory()
        assert client.post(
            "/api/v1/platform-admin/tenants/",
            {"tenantName": "N", "urlSlug": "n-co", "vertical": Vertical.CA_CS,
             "adminName": "A", "adminEmail": "a@n.in"}, format="json",
        ).status_code == 403
        assert client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {"name": "P", "email": "p@n.in", "roleLevel": OrgRoleLevel.MID}, format="json",
        ).status_code == 403
        assert client.delete(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/"
            "00000000-0000-0000-0000-000000000000/",
        ).status_code == 403

    def test_legacy_token_without_role_claim_falls_back_to_db_role(self, admin):
        # admin.role is SUPER_ADMIN in the DB -> the fallback in
        # PlatformAdminCookieJWTAuthentication lets it through.
        resp = self._client(_legacy_token(admin)).get("/api/v1/platform-admin/tenants/")
        assert resp.status_code == 200

    def test_logout_is_not_role_gated(self, admin):
        # Any authenticated admin can end their own session regardless of role.
        resp = self._client(_token_with_role(admin, "VIEWER")).post(
            "/api/v1/platform-admin/auth/logout/",
        )
        assert resp.status_code == 200

    def test_still_401_without_any_token(self):
        assert APIClient().get("/api/v1/platform-admin/tenants/").status_code == 401
