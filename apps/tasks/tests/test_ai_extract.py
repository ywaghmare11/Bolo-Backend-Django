import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.tasks import ai_extract
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
    return UserFactory(tenant=tenant, name="Alice Rao")


@pytest.mark.django_db
class TestTaskExtractValidation:
    def test_text_missing_rejected(self, tenant, alice):
        resp = _authed_client(alice, tenant.id).post("/api/v1/tasks/extract/", {}, format="json")
        assert resp.status_code == 400

    def test_text_too_short_rejected(self, tenant, alice):
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "hi"}, format="json",
        )
        assert resp.status_code == 400

    def test_text_too_long_rejected(self, tenant, alice):
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "x" * 2001}, format="json",
        )
        assert resp.status_code == 400

    def test_unauthenticated_rejected(self, tenant):
        resp = APIClient().post("/api/v1/tasks/extract/", {"text": "remind Bob tomorrow"}, format="json")
        assert resp.status_code == 401


@pytest.mark.django_db
class TestTaskExtractAiUnavailableFallback:
    def test_no_api_key_configured_returns_all_null(self, tenant, alice, settings):
        settings.OPENAI_API_KEY = ""
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "ask Bob to submit the report by Friday"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": None, "assigneeHint": None, "dueDate": None, "priority": None,
        }

    def test_ai_timeout_falls_back_without_erroring(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"

        def _timeout(*args, **kwargs):
            raise TimeoutError("simulated timeout")

        monkeypatch.setattr(ai_extract, "call_openai_extract", _timeout)
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "ask Bob to submit the report by Friday"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": None, "assigneeHint": None, "dueDate": None, "priority": None,
        }

    def test_ai_call_raising_falls_back_without_erroring(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated network failure")

        monkeypatch.setattr(ai_extract, "call_openai_extract", _boom)
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "ask Bob to submit the report by Friday"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["title"] is None

    def test_malformed_non_dict_ai_output_falls_back(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(ai_extract, "call_openai_extract", lambda text: ["not", "a", "dict"])
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "ask Bob to submit the report by Friday"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": None, "assigneeHint": None, "dueDate": None, "priority": None,
        }


@pytest.mark.django_db
class TestTaskExtractSuccessfulExtraction:
    def test_full_extraction_returned(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_extract, "call_openai_extract",
            lambda text: {
                "title": "Submit the self-study report",
                "personName": "Bob Iyer",
                "dueDate": "2026-08-28",
                "priority": "urgent",
            },
        )
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/",
            {"text": "ask Bob Iyer to submit the self-study report by Friday, urgent"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": "Submit the self-study report",
            "assigneeHint": "Bob Iyer",
            "dueDate": "2026-08-28",
            "priority": "P1",
        }

    def test_no_assignee_or_due_date_mentioned_returns_nulls_for_those_fields(
        self, tenant, alice, settings, monkeypatch,
    ):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_extract, "call_openai_extract",
            lambda text: {
                "title": "Buy printer paper",
                "personName": None,
                "dueDate": None,
                "priority": None,
            },
        )
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "need to buy printer paper"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": "Buy printer paper", "assigneeHint": None, "dueDate": None, "priority": None,
        }


@pytest.mark.django_db
class TestTaskExtractPartialOrInvalidAiOutput:
    def test_missing_keys_in_ai_response_default_to_null(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(ai_extract, "call_openai_extract", lambda text: {"title": "Call the vendor"})
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "call the vendor"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {
            "title": "Call the vendor", "assigneeHint": None, "dueDate": None, "priority": None,
        }

    def test_unparseable_due_date_dropped_not_crashed(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_extract, "call_openai_extract",
            lambda text: {
                "title": "Follow up", "personName": None, "dueDate": "next Friday-ish", "priority": None,
            },
        )
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "follow up next Friday-ish"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["dueDate"] is None

    def test_unrecognized_priority_dropped_not_crashed(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_extract, "call_openai_extract",
            lambda text: {
                "title": "Do the thing", "personName": None, "dueDate": None, "priority": "ultra-mega",
            },
        )
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "do the thing"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["priority"] is None

    def test_wrong_type_title_dropped_not_crashed(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_extract, "call_openai_extract",
            lambda text: {"title": 12345, "personName": None, "dueDate": None, "priority": None},
        )
        resp = _authed_client(alice, tenant.id).post(
            "/api/v1/tasks/extract/", {"text": "some text"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["title"] is None
