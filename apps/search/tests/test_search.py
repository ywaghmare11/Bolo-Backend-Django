import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import Priority, TaskStatus
from apps.labels.models import ProjectLabel
from apps.search import ai_classify
from apps.sticky_notes.models import StickyNote
from apps.tasks.factories import TaskFactory
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
def other_tenant():
    return TenantFactory()


@pytest.fixture
def alice(tenant):
    return UserFactory(tenant=tenant, name="Alice Rao")


@pytest.fixture
def bob(tenant):
    return UserFactory(tenant=tenant, name="Bob Iyer")


@pytest.fixture
def outsider(tenant):
    return UserFactory(tenant=tenant, name="Outsider Person")


@pytest.mark.django_db
class TestSearchValidation:
    def test_query_too_short_rejected(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get("/api/v1/search/tasks/?q=ab")
        # Plain serializer-level field validation (min_length) surfaces as a raw DRF
        # 400, not the AppError envelope -- same convention as every other view's
        # basic field checks in this codebase (e.g. apps/labels/tests/test_labels.py).
        assert resp.status_code == 400

    def test_query_too_long_rejected(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get(f"/api/v1/search/tasks/?q={'x' * 101}")
        assert resp.status_code == 400

    def test_query_missing_rejected(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get("/api/v1/search/tasks/")
        assert resp.status_code == 400

    def test_limit_over_max_rejected(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get("/api/v1/search/tasks/?q=report&limit=51")
        assert resp.status_code == 400

    def test_invalid_source_rejected(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get("/api/v1/search/tasks/?q=report&source=telepathy")
        assert resp.status_code == 400

    def test_defaults_applied(self, tenant, alice):
        client = _authed_client(alice, tenant.id)
        resp = client.get("/api/v1/search/tasks/?q=report")
        assert resp.status_code == 200
        assert resp.data["pagination"] == {"page": 1, "limit": 10, "total": 0}
        assert resp.data["query"] == "report"
        assert resp.data["interpretedQuery"] is None
        assert resp.data["entityScope"] == "both"


@pytest.mark.django_db
class TestTaskSearchMatching:
    def test_matches_title(self, tenant, alice, bob):
        TaskFactory(title="Submit NAAC report", assigner=alice, assignee=bob)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_matches_description_not_just_title(self, tenant, alice, bob):
        TaskFactory(
            title="Quarterly review", description="mentions MBA program details",
            assigner=alice, assignee=bob,
        )
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=MBA")
        assert len(resp.data["data"]) == 1

    def test_multiword_keyword_matches_hyphenated_title(self, tenant, alice, bob):
        TaskFactory(title="Submit self-study report", assigner=alice, assignee=bob)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=self study report")
        assert len(resp.data["data"]) == 1

    def test_main_label_name_match(self, tenant, alice, bob):
        label = ProjectLabel.objects.create(tenant=tenant, name="NAAC", created_by=alice)
        TaskFactory(
            title="Prepare accreditation checklist", assigner=alice, assignee=bob, main_label=label,
        )
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["mainLabelName"] == "NAAC"

    def test_assignee_label_privacy_scoped(self, tenant, alice, bob):
        private_label = ProjectLabel.objects.create(tenant=tenant, name="NAAC-Docs", created_by=bob)
        TaskFactory(
            title="Compile evaluation notes", assigner=alice, assignee=bob, assignee_label=private_label,
        )
        # Bob (the assignee) can find it via the private label name, and sees the label.
        bob_resp = _authed_client(bob, tenant.id).get("/api/v1/search/tasks/?q=NAAC-Docs")
        assert len(bob_resp.data["data"]) == 1
        assert bob_resp.data["data"][0]["assigneeLabelName"] == "NAAC-Docs"

        # Alice (the assigner) can see the task (she's on it) but never the private label name/id,
        # and the private label name alone must not surface it via a match she isn't privy to.
        alice_resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC-Docs")
        assert len(alice_resp.data["data"]) == 0

    def test_excludes_task_caller_has_no_access_to(self, tenant, alice, bob, outsider):
        TaskFactory(title="MBA convocation prep", assigner=bob, assignee=outsider)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=MBA")
        assert len(resp.data["data"]) == 0

    def test_tenant_isolation(self, tenant, other_tenant, alice):
        other_user = UserFactory(tenant=other_tenant)
        other_assignee = UserFactory(tenant=other_tenant)
        TaskFactory(title="MBA program launch", assigner=other_user, assignee=other_assignee)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=MBA")
        assert len(resp.data["data"]) == 0

    def test_includes_draft_cancelled_done_d_by_design(self, tenant, alice, bob):
        TaskFactory(title="Workshop planning draft", assigner=alice, assignee=bob, status=TaskStatus.DRAFT)
        TaskFactory(
            title="Workshop planning cancelled", assigner=alice, assignee=bob,
            status=TaskStatus.CANCELLED,
        )
        TaskFactory(
            title="Workshop planning archived", assigner=alice, assignee=bob,
            status=TaskStatus.DONE_D, is_archived=True,
        )
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Workshop planning")
        assert len(resp.data["data"]) == 3

    def test_latest_comment_attached(self, tenant, alice, bob):
        from apps.comments.models import Comment

        task = TaskFactory(title="Submit NAAC report", assigner=alice, assignee=bob)
        Comment.objects.create(task=task, author=bob, text="Working on it")
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert resp.data["data"][0]["latestComment"]["text"] == "Working on it"

    def test_id_tiebreaker_keeps_pagination_stable(self, tenant, alice, bob):
        tasks = [TaskFactory(title=f"Report {i}", assigner=alice, assignee=bob) for i in range(3)]
        from apps.tasks.models import Task

        same_time = tasks[0].created_at
        Task.objects.filter(id__in=[t.id for t in tasks]).update(created_at=same_time)

        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Report&limit=2")
        page1_ids = [row["id"] for row in resp.data["data"]]
        resp2 = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Report&limit=2&page=2")
        page2_ids = [row["id"] for row in resp2.data["data"]]
        assert set(page1_ids).isdisjoint(page2_ids)
        assert len(page1_ids) + len(page2_ids) == 3


@pytest.mark.django_db
class TestTaskSearchFilters:
    def test_status_and_priority_filters_applied(self, tenant, alice, bob, monkeypatch):
        TaskFactory(title="Report A", assigner=alice, assignee=bob, status=TaskStatus.OPEN, priority=Priority.P1)
        TaskFactory(title="Report B", assigner=alice, assignee=bob, status=TaskStatus.DRAFT, priority=Priority.P3)

        monkeypatch.setattr("apps.search.services.classify_search_query", lambda *a, **k: {
            "resolved_keywords": ["Report"],
            "resolved_assignee": None,
            "entity_scope": "task",
            "filters": {"status": "OPEN", "priority": "P1", "due": None},
            "detected_language": None,
            "interpreted_query": None,
        })
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Report")
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["title"] == "Report A"

    def test_due_today_filter(self, tenant, alice, bob, monkeypatch):
        from django.utils import timezone

        today_task = TaskFactory(
            title="Report due today", assigner=alice, assignee=bob, due_date=timezone.now(),
        )
        TaskFactory(
            title="Report due later", assigner=alice, assignee=bob,
            due_date=timezone.now() + timezone.timedelta(days=10),
        )

        monkeypatch.setattr("apps.search.services.classify_search_query", lambda *a, **k: {
            "resolved_keywords": ["Report"],
            "resolved_assignee": None,
            "entity_scope": "task",
            "filters": {"status": None, "priority": None, "due": "today"},
            "detected_language": None,
            "interpreted_query": None,
        })
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Report")
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["id"] == str(today_task.id)


@pytest.mark.django_db
class TestPersonNameMatching:
    def test_resolved_assignee_surfaces_tasks_without_keyword_match(self, tenant, alice, bob, monkeypatch):
        TaskFactory(title="Prepare slides", assigner=alice, assignee=bob)

        monkeypatch.setattr("apps.search.services.classify_search_query", lambda *a, **k: {
            "resolved_keywords": ["Bob"],
            "resolved_assignee": {"id": str(bob.id), "name": bob.name, "ambiguous": False, "candidates": None},
            "entity_scope": "task",
            "filters": {"status": None, "priority": None, "due": None},
            "detected_language": None,
            "interpreted_query": None,
        })
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Bob")
        assert len(resp.data["data"]) == 1

    def test_ambiguous_name_widens_to_or_across_candidates(self, tenant, alice, bob, outsider, monkeypatch):
        priya1 = UserFactory(tenant=tenant, name="Priya Sharma")
        priya2 = UserFactory(tenant=tenant, name="Priya Iyer")
        TaskFactory(title="Task for priya one", assigner=alice, assignee=priya1)
        TaskFactory(title="Task for priya two", assigner=alice, assignee=priya2)

        monkeypatch.setattr("apps.search.services.classify_search_query", lambda *a, **k: {
            "resolved_keywords": ["Priya"],
            "resolved_assignee": {
                "id": None, "name": None, "ambiguous": True,
                "candidates": [str(priya1.id), str(priya2.id)],
            },
            "entity_scope": "task",
            "filters": {"status": None, "priority": None, "due": None},
            "detected_language": None,
            "interpreted_query": None,
        })
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=Priya")
        assert len(resp.data["data"]) == 2


class TestResolvePersonUnit:
    """Deterministic, no-AI-required tests for the Levenshtein fallback and exact
    matching -- the parts of classification that ARE fully regression-testable."""

    def test_exact_match(self):
        roster = [("id-1", "Sarang Patil"), ("id-2", "Bob Iyer")]
        result = ai_classify.resolve_person("Sarang Patil", roster)
        assert result == {"id": "id-1", "name": "Sarang Patil", "ambiguous": False, "candidates": None}

    def test_levenshtein_catches_one_character_typo(self):
        roster = [("id-1", "Sarang"), ("id-2", "Bob")]
        result = ai_classify.resolve_person("Tarang", roster)
        assert result["id"] == "id-1"
        assert result["ambiguous"] is False

    def test_no_match_beyond_threshold(self):
        roster = [("id-1", "Sarang"), ("id-2", "Bob")]
        result = ai_classify.resolve_person("Completely Different Name", roster)
        assert result is None

    def test_tied_distance_widens_to_ambiguous(self):
        # "Ann" is edit-distance 1 from both "Ana" and "Ani" -- a genuine tie.
        roster = [("id-1", "Ana"), ("id-2", "Ani")]
        result = ai_classify.resolve_person("Ann", roster)
        assert result["ambiguous"] is True
        assert set(result["candidates"]) == {"id-1", "id-2"}

    def test_empty_name_returns_none(self):
        assert ai_classify.resolve_person("", [("id-1", "Bob")]) is None
        assert ai_classify.resolve_person(None, [("id-1", "Bob")]) is None


@pytest.mark.django_db
class TestAiUnavailableFallback:
    def test_no_api_key_configured_uses_raw_keyword_fallback(self, tenant, alice, bob, settings):
        settings.OPENAI_API_KEY = ""
        TaskFactory(title="Submit NAAC report", assigner=alice, assignee=bob)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert resp.status_code == 200
        assert resp.data["interpretedQuery"] is None
        assert resp.data["entityScope"] == "both"
        assert len(resp.data["data"]) == 1

    def test_ai_call_raising_falls_back_without_erroring(self, tenant, alice, bob, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated network failure")

        monkeypatch.setattr(ai_classify, "call_openai_classify", _boom)
        TaskFactory(title="Submit NAAC report", assigner=alice, assignee=bob)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_invalid_status_priority_from_ai_are_dropped_not_crashed(
        self, tenant, alice, bob, settings, monkeypatch,
    ):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_classify, "call_openai_classify",
            lambda *a, **k: {
                "resolvedKeywords": ["NAAC"],
                "resolvedAssigneeName": None,
                "entityScope": "task",
                "filters": {"status": "some_nonsense", "priority": "ultra-mega", "due": None},
                "detectedLanguage": "en",
                "interpretedQuery": None,
            },
        )
        TaskFactory(title="Submit NAAC report", assigner=alice, assignee=bob)
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=NAAC")
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1

    def test_classify_cached_across_both_endpoints(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        calls = {"count": 0}

        def _fake_call(*args, **kwargs):
            calls["count"] += 1
            return {
                "resolvedKeywords": ["NAAC"],
                "resolvedAssigneeName": None,
                "entityScope": "both",
                "filters": {"status": None, "priority": None, "due": None},
                "detectedLanguage": "en",
                "interpretedQuery": None,
            }

        monkeypatch.setattr(ai_classify, "call_openai_classify", _fake_call)
        client = _authed_client(alice, tenant.id)
        client.get("/api/v1/search/tasks/?q=NAAC")
        client.get("/api/v1/search/stickies/?q=NAAC")
        assert calls["count"] == 1

    def test_interpreted_query_surfaced_when_ai_corrects_typo(self, tenant, alice, settings, monkeypatch):
        settings.OPENAI_API_KEY = "sk-fake-for-test"
        monkeypatch.setattr(
            ai_classify, "call_openai_classify",
            lambda *a, **k: {
                "resolvedKeywords": ["report"],
                "resolvedAssigneeName": None,
                "entityScope": "both",
                "filters": {"status": None, "priority": None, "due": None},
                "detectedLanguage": "en",
                "interpretedQuery": "report",
            },
        )
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/tasks/?q=repot")
        assert resp.data["interpretedQuery"] == "report"


@pytest.mark.django_db
class TestStickySearch:
    def test_matches_own_sticky_text(self, tenant, alice):
        StickyNote.objects.create(user=alice, text="Prepare NAAC agenda for staff meeting")
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/stickies/?q=agenda")
        assert resp.status_code == 200
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["colorCode"] == "#FEF3C7"

    def test_never_sees_other_users_sticky(self, tenant, alice, bob):
        StickyNote.objects.create(user=bob, text="Alice must never see this MBA note")
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/stickies/?q=MBA")
        assert len(resp.data["data"]) == 0

    def test_cross_tenant_sticky_never_matched(self, tenant, other_tenant, alice):
        other_user = UserFactory(tenant=other_tenant)
        StickyNote.objects.create(user=other_user, text="MBA program notes")
        resp = _authed_client(alice, tenant.id).get("/api/v1/search/stickies/?q=MBA")
        assert len(resp.data["data"]) == 0
