from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.comments.models import Comment
from apps.common.enums import AcceptanceStatus, NotificationType, Priority, TaskStatus
from apps.notifications.models import Notification, NudgeSkipCounter
from apps.notifications.tasks import ai_nudge_due_proximity_sweep, ai_nudge_followup_sweep
from apps.tasks.factories import TaskFactory
from apps.tasks.models import Task
from apps.tasks.services import TaskService
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
def assigner(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def assignee(tenant):
    return UserFactory(tenant=tenant)


def _due_today_task(tenant, assigner, assignee, priority=Priority.P3):
    return TaskFactory(
        tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
        acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now(), priority=priority,
    )


def _no_progress_task(tenant, assigner, assignee, priority=Priority.P3):
    return TaskFactory(
        tenant_id=tenant.id, assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
        acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(), priority=priority,
    )


def _priority_of(tenant, task_id):
    return Task.objects.get(id=task_id, tenant_id=tenant.id).priority


@pytest.mark.django_db
class TestNudgeFeed:
    def test_due_proximity_item_shape(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        assert resp.status_code == 200
        item = resp.data["data"][0]
        assert item["nudgeType"] == "DUE_PROXIMITY"
        assert item["entityType"] == "task"
        assert item["entityId"] == str(task.id)
        assert item["actions"] == ["ADD_COMMENT", "OPEN_TASK"]
        assert item["skipCap"] == 3
        assert item["escalation"] == {"toName": assigner.name}

    def test_followup_item_shape(self, tenant, assigner, assignee):
        _no_progress_task(tenant, assigner, assignee)
        ai_nudge_followup_sweep()

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        item = resp.data["data"][0]
        assert item["nudgeType"] == "FOLLOWUP"
        assert item["actions"] == ["ADD_COMMENT"]
        assert item["skipCap"] is None
        assert item["escalation"] is None

    def test_only_assignees_own_nudges_returned(self, tenant, assigner, assignee):
        other_assignee = UserFactory(tenant=tenant)
        _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()

        resp = _authed_client(other_assignee, tenant.id).get("/api/v1/nudges/")
        assert resp.data["data"] == []

    def test_due_proximity_fills_before_followup(self, tenant, assigner, assignee):
        _due_today_task(tenant, assigner, assignee)
        _no_progress_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()
        ai_nudge_followup_sweep()

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        types = [item["nudgeType"] for item in resp.data["data"]]
        assert types == ["DUE_PROXIMITY", "FOLLOWUP"]

    def test_feed_caps_at_five_ordered_by_priority(self, tenant, assigner, assignee):
        priorities = [Priority.P4, Priority.P1, Priority.P3, Priority.P2, Priority.P1, Priority.P4]
        for p in priorities:
            _due_today_task(tenant, assigner, assignee, priority=p)
        ai_nudge_due_proximity_sweep()

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        data = resp.data["data"]
        assert len(data) == 5
        returned_priorities = [
            _priority_of(tenant, item["entityId"]) for item in data
        ]
        assert returned_priorities == sorted(returned_priorities, key=lambda p: ["P1", "P2", "P3", "P4"].index(p))

    def test_stale_condition_auto_resolves_and_excludes(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()

        TaskService.mark_done_a(assignee, tenant.id, task.id)

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        assert resp.data["data"] == []
        notification = Notification.objects.get(
            type=NotificationType.AI_NUDGE_DUE_PROXIMITY, entity_id=str(task.id),
        )
        assert notification.is_read is True

    def test_comment_after_notification_resolves_due_proximity_for_cycle(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()
        notification = Notification.objects.get(type=NotificationType.AI_NUDGE_DUE_PROXIMITY)

        Comment.objects.create(task=task, author=assignee, text="in progress")
        c = Comment.objects.filter(task=task).latest("created_at")
        Comment.objects.filter(id=c.id).update(created_at=notification.created_at + timedelta(minutes=1))

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        assert resp.data["data"] == []

    def test_dedup_keeps_newest_marks_older_read(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        older = Notification.objects.create(
            tenant_id=tenant.id, recipient=assignee, type=NotificationType.AI_NUDGE_DUE_PROXIMITY,
            entity_type="task", entity_id=str(task.id), message="older",
        )
        Notification.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(hours=1))
        newer = Notification.objects.create(
            tenant_id=tenant.id, recipient=assignee, type=NotificationType.AI_NUDGE_DUE_PROXIMITY,
            entity_type="task", entity_id=str(task.id), message="newer",
        )

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        assert [item["id"] for item in resp.data["data"]] == [str(newer.id)]
        older.refresh_from_db()
        assert older.is_read is True

    def test_followup_rotation_prefers_oldest_last_shown(self, tenant, assigner, assignee):
        task_a = _no_progress_task(tenant, assigner, assignee)
        Comment.objects.create(task=task_a, author=assigner, text="x")
        task_b = _no_progress_task(tenant, assigner, assignee)
        Comment.objects.create(task=task_b, author=assigner, text="x")
        ai_nudge_followup_sweep()

        NudgeSkipCounter.objects.filter(entity_id=str(task_a.id)).update(
            last_shown_at=timezone.now() - timedelta(hours=1),
        )
        NudgeSkipCounter.objects.filter(entity_id=str(task_b.id)).update(
            last_shown_at=timezone.now(),
        )

        resp = _authed_client(assignee, tenant.id).get("/api/v1/nudges/")
        entity_ids = [item["entityId"] for item in resp.data["data"]]
        assert entity_ids.index(str(task_a.id)) < entity_ids.index(str(task_b.id))


@pytest.mark.django_db
class TestNudgeSkip:
    def test_skip_increments_counter_and_marks_read(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()
        notification = Notification.objects.get(entity_id=str(task.id))

        resp = _authed_client(assignee, tenant.id).post(f"/api/v1/nudges/{notification.id}/skip/")
        assert resp.status_code == 200
        assert resp.data["data"]["skipCount"] == 1
        notification.refresh_from_db()
        assert notification.is_read is True

    def test_skip_succeeds_even_past_cap(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        NudgeSkipCounter.objects.create(
            tenant_id=tenant.id, entity_type="task", entity_id=str(task.id),
            nudge_kind="due_proximity", skip_count=5,
        )
        ai_nudge_due_proximity_sweep()
        notification = Notification.objects.get(entity_id=str(task.id), recipient=assignee)

        resp = _authed_client(assignee, tenant.id).post(f"/api/v1/nudges/{notification.id}/skip/")
        assert resp.status_code == 200
        assert resp.data["data"]["skipCount"] == 6

    def test_cannot_skip_someone_elses_nudge(self, tenant, assigner, assignee):
        task = _due_today_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()
        notification = Notification.objects.get(entity_id=str(task.id))

        outsider = UserFactory(tenant=tenant)
        resp = _authed_client(outsider, tenant.id).post(f"/api/v1/nudges/{notification.id}/skip/")
        assert resp.status_code == 404

    def test_skip_all_skips_entire_current_feed(self, tenant, assigner, assignee):
        _due_today_task(tenant, assigner, assignee)
        _no_progress_task(tenant, assigner, assignee)
        ai_nudge_due_proximity_sweep()
        ai_nudge_followup_sweep()

        client = _authed_client(assignee, tenant.id)
        resp = client.post("/api/v1/nudges/skip-all/")
        assert resp.status_code == 200
        assert resp.data["data"]["skippedCount"] == 2

        follow_up = client.get("/api/v1/nudges/")
        assert follow_up.data["data"] == []
