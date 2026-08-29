import pytest
from rest_framework.test import APIClient
from structlog.testing import capture_logs

from apps.auth.tokens import issue_access_token
from apps.common.request_identity import decode_access_cookie
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
def alice(tenant):
    return UserFactory(tenant=tenant)


@pytest.mark.django_db
class TestRequestFinishedLogging:
    def test_authenticated_request_logs_actor_and_tenant(self, tenant, alice):
        with capture_logs() as cap:
            resp = _authed_client(alice, tenant.id).get("/api/v1/tasks/?view=assigned")

        assert resp.status_code == 200
        [entry] = [e for e in cap if e["event"] == "request_finished"]
        assert entry["log_level"] == "info"
        assert entry["method"] == "GET"
        assert entry["path"] == "/api/v1/tasks/"
        assert entry["status_code"] == 200
        assert isinstance(entry["duration_ms"], float)
        assert entry["actor_id"] == str(alice.id)
        assert entry["tenant_id"] == str(tenant.id)

    def test_anonymous_request_logs_null_actor_and_tenant(self):
        with capture_logs() as cap:
            resp = APIClient().get("/api/v1/tasks/")

        assert resp.status_code == 401
        [entry] = [e for e in cap if e["event"] == "request_finished"]
        assert entry["status_code"] == 401
        assert entry["actor_id"] is None
        assert entry["tenant_id"] is None

    def test_status_code_reflects_error_responses(self, tenant, alice):
        with capture_logs() as cap:
            resp = _authed_client(alice, tenant.id).get("/api/v1/tasks/does-not-exist-route/")

        [entry] = [e for e in cap if e["event"] == "request_finished"]
        assert entry["status_code"] == resp.status_code
        assert resp.status_code == 404


@pytest.mark.django_db
class TestDecodeAccessCookieCrossAuthSpace:
    """Regression test: apps/common/logging_middleware.py calls decode_access_cookie
    on every single request (unlike apps/common/audit_middleware.py, which only
    calls it for routes present in AUDIT_ROUTE_CONFIG). That's what first exposed a
    latent bug -- decode_access_cookie indexed token["userId"]/token["tenantId"]
    unguarded, same class of issue apps/auth/authentication.py:CookieJWTAuthentication
    was already fixed for. A PlatformAdmin's admin_token (adminId/isPlatformAdmin,
    no userId/tenantId) presented as the tenant 'token' cookie used to crash this
    helper with an unhandled KeyError instead of returning (None, None)."""

    def test_admin_token_presented_as_tenant_cookie_returns_none_none(self):
        from apps.platform_admin.models import PlatformAdmin
        from apps.platform_admin.tokens import issue_admin_access_token

        admin = PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")
        admin_token = issue_admin_access_token(admin.id, admin.email, admin.role)

        class _FakeRequest:
            COOKIES = {"token": admin_token}

        assert decode_access_cookie(_FakeRequest()) == (None, None)

    def test_request_with_admin_token_as_tenant_cookie_does_not_500(self, tenant, alice):
        from apps.platform_admin.models import PlatformAdmin
        from apps.platform_admin.tokens import issue_admin_access_token

        admin = PlatformAdmin.objects.create(name="Ops Admin", email="admin2@bolo.internal")
        client = _authed_client(alice, tenant.id)
        client.cookies["token"] = issue_admin_access_token(admin.id, admin.email, admin.role)

        with capture_logs() as cap:
            resp = client.get("/api/v1/tasks/")

        assert resp.status_code == 401
        [entry] = [e for e in cap if e["event"] == "request_finished"]
        assert entry["actor_id"] is None
        assert entry["tenant_id"] is None
