import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.platform_admin.models import PlatformAdmin, PlatformAdminOtpCode


def _otp_code_from_outbox():
    body = mail.outbox[-1].body
    return "".join(filter(str.isdigit, body))[:6]


@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


@pytest.mark.django_db
class TestPlatformAdminOtpFlow:
    def test_request_otp_for_unknown_email_404(self):
        client = APIClient()
        resp = client.post(
            "/api/v1/platform-admin/auth/request-otp/", {"email": "nobody@bolo.internal"}, format="json",
        )
        assert resp.status_code == 404
        assert resp.data["error"]["code"] == "ADMIN_NOT_FOUND"

    def test_request_otp_success_creates_otp_and_sends_email(self, admin):
        client = APIClient()
        resp = client.post(
            "/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json",
        )
        assert resp.status_code == 200
        assert PlatformAdminOtpCode.objects.filter(email=admin.email).exists()
        assert len(mail.outbox) == 1

    def test_request_otp_rate_limited_within_60s(self, admin):
        client = APIClient()
        client.post("/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json")
        resp = client.post(
            "/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json",
        )
        assert resp.status_code == 429
        assert resp.data["error"]["code"] == "RATE_LIMITED"

    def test_verify_otp_success_sets_admin_cookie_only(self, admin):
        client = APIClient()
        client.post("/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json")
        code = _otp_code_from_outbox()

        resp = client.post(
            "/api/v1/platform-admin/auth/verify-otp/", {"email": admin.email, "otp": code}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["adminId"] == str(admin.id)
        assert "admin_token" in resp.cookies
        # Never the tenant-user cookies -- fully parallel auth, no shared session.
        assert "token" not in resp.cookies
        assert "refresh_token" not in resp.cookies
        assert not PlatformAdminOtpCode.objects.filter(email=admin.email).exists()

    def test_verify_otp_wrong_code_three_times_locks(self, admin):
        client = APIClient()
        client.post("/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json")

        resp = None
        for expected_remaining in (2, 1, 0):
            resp = client.post(
                "/api/v1/platform-admin/auth/verify-otp/",
                {"email": admin.email, "otp": "000000"}, format="json",
            )
            assert resp.data["data"]["attemptsRemaining"] == expected_remaining

        assert resp.status_code == 429
        otp_row = PlatformAdminOtpCode.objects.get(email=admin.email)
        assert otp_row.locked_until is not None

    def test_no_cookie_request_401(self):
        client = APIClient()
        resp = client.post("/api/v1/platform-admin/auth/logout/")
        assert resp.status_code == 401

    def test_tenant_user_cookie_does_not_authenticate_platform_admin_routes(self, admin):
        """A stolen/leaked tenant-user 'token' cookie must never grant
        platform-admin access -- the two auth spaces are fully parallel."""
        client = APIClient()
        client.post("/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json")
        code = _otp_code_from_outbox()
        client.post(
            "/api/v1/platform-admin/auth/verify-otp/", {"email": admin.email, "otp": code}, format="json",
        )
        admin_token = client.cookies["admin_token"].value

        # Present it as the tenant-user cookie against a tenant-scoped route instead.
        other_client = APIClient()
        other_client.cookies["token"] = admin_token
        resp = other_client.get("/api/v1/tasks/")
        assert resp.status_code == 401


@pytest.mark.django_db
class TestPlatformAdminLogout:
    def _login(self, client, admin):
        client.post("/api/v1/platform-admin/auth/request-otp/", {"email": admin.email}, format="json")
        code = _otp_code_from_outbox()
        return client.post(
            "/api/v1/platform-admin/auth/verify-otp/", {"email": admin.email, "otp": code}, format="json",
        )

    def test_logout_clears_cookie(self, admin):
        client = APIClient()
        self._login(client, admin)

        resp = client.post("/api/v1/platform-admin/auth/logout/")
        assert resp.status_code == 200
        assert client.cookies["admin_token"].value == ""
