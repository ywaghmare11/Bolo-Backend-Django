import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.auth.models import OtpCode, RefreshToken
from apps.tenants.factories import TenantMembershipFactory
from apps.users.factories import UserFactory


def _otp_code_from_outbox():
    body = mail.outbox[-1].body
    return "".join(filter(str.isdigit, body))[:6]


@pytest.mark.django_db
class TestOtpFlow:
    def test_request_otp_for_unknown_email_404(self):
        client = APIClient()
        resp = client.post("/api/v1/auth/request-otp/", {"email": "nobody@example.com"}, format="json")
        assert resp.status_code == 404
        assert resp.data["error"]["code"] == "USER_NOT_FOUND"

    def test_request_otp_success_creates_otp_and_sends_email(self):
        user = UserFactory(email="dean@abc.edu")
        client = APIClient()
        resp = client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        assert resp.status_code == 200
        assert OtpCode.objects.filter(email=user.email).exists()
        assert len(mail.outbox) == 1

    def test_request_otp_rate_limited_within_60s(self):
        user = UserFactory(email="dean@abc.edu")
        client = APIClient()
        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        resp = client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        assert resp.status_code == 429
        assert resp.data["error"]["code"] == "RATE_LIMITED"

    def test_request_otp_ip_throttled_across_distinct_emails(self):
        """The Redis-backed ScopedRateThrottle (otp_request, 5/min) is IP-keyed, so it
        catches someone cycling through many different emails from one IP -- a case
        AuthService's per-email 60s cooldown alone doesn't stop."""
        client = APIClient()
        for i in range(5):
            UserFactory(email=f"burst{i}@abc.edu")
            resp = client.post(
                "/api/v1/auth/request-otp/", {"email": f"burst{i}@abc.edu"}, format="json",
            )
            assert resp.status_code == 200

        UserFactory(email="burst-over@abc.edu")
        resp = client.post(
            "/api/v1/auth/request-otp/", {"email": "burst-over@abc.edu"}, format="json",
        )
        assert resp.status_code == 429
        assert resp.data["error"]["code"] == "RATE_LIMITED"

    def test_verify_otp_success_sets_cookies_and_updates_login(self):
        user = UserFactory(email="dean@abc.edu")
        TenantMembershipFactory(user=user, tenant=user.tenant)
        client = APIClient()
        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        code = _otp_code_from_outbox()

        resp = client.post("/api/v1/auth/verify-otp/", {"email": user.email, "otp": code}, format="json")
        assert resp.status_code == 200
        assert "token" in resp.cookies
        assert "refresh_token" in resp.cookies
        assert not OtpCode.objects.filter(email=user.email).exists()
        user.refresh_from_db()
        assert user.last_login_at is not None
        assert RefreshToken.objects.filter(user=user).exists()

    def test_verify_otp_wrong_code_three_times_locks(self):
        user = UserFactory(email="dean@abc.edu")
        TenantMembershipFactory(user=user, tenant=user.tenant)
        client = APIClient()
        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")

        resp = None
        for expected_remaining in (2, 1, 0):
            resp = client.post(
                "/api/v1/auth/verify-otp/", {"email": user.email, "otp": "000000"}, format="json",
            )
            assert resp.data["data"]["attemptsRemaining"] == expected_remaining

        assert resp.status_code == 429
        otp_row = OtpCode.objects.get(email=user.email)
        assert otp_row.locked_until is not None

    def test_no_cookie_request_401(self):
        client = APIClient()
        resp = client.post("/api/v1/auth/logout/")
        assert resp.status_code == 401


@pytest.mark.django_db
class TestRefreshFlow:
    def _login(self, client, user):
        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        code = _otp_code_from_outbox()
        return client.post("/api/v1/auth/verify-otp/", {"email": user.email, "otp": code}, format="json")

    def test_refresh_rotates_and_old_token_becomes_unusable(self):
        user = UserFactory(email="dean@abc.edu")
        TenantMembershipFactory(user=user, tenant=user.tenant)
        client = APIClient()
        self._login(client, user)

        old_refresh_cookie = client.cookies["refresh_token"].value
        resp = client.post("/api/v1/auth/refresh/")
        assert resp.status_code == 200
        new_refresh_cookie = client.cookies["refresh_token"].value
        assert new_refresh_cookie != old_refresh_cookie

        # replay the old, now-revoked token
        client2 = APIClient()
        client2.cookies["refresh_token"] = old_refresh_cookie
        resp2 = client2.post("/api/v1/auth/refresh/")
        assert resp2.status_code == 401

        # reuse-detection revoked *every* refresh token for the user, including the live one
        client3 = APIClient()
        client3.cookies["refresh_token"] = new_refresh_cookie
        resp3 = client3.post("/api/v1/auth/refresh/")
        assert resp3.status_code == 401

    def test_logout_revokes_refresh_token(self):
        user = UserFactory(email="dean@abc.edu")
        TenantMembershipFactory(user=user, tenant=user.tenant)
        client = APIClient()
        self._login(client, user)

        refresh_cookie = client.cookies["refresh_token"].value
        resp = client.post("/api/v1/auth/logout/")
        assert resp.status_code == 200
        user.refresh_from_db()
        assert user.last_logout_at is not None

        client2 = APIClient()
        client2.cookies["refresh_token"] = refresh_cookie
        resp2 = client2.post("/api/v1/auth/refresh/")
        assert resp2.status_code == 401
