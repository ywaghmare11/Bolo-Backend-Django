from datetime import timedelta

import pytest
from django.utils import timezone

from apps.comments.models import Comment
from apps.common.enums import AcceptanceStatus, TaskStatus
from apps.notifications.nudge_rules import (
    FOLLOWUP_NO_PROGRESS,
    FOLLOWUP_UNANSWERED_COMMENT,
    classify_followup,
    due_proximity_bucket,
    resolved_by_comment_since,
)
from apps.tasks.factories import TaskFactory
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


@pytest.fixture
def tenant():
    return TenantFactory()


@pytest.fixture
def assigner(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def assignee(tenant):
    return UserFactory(tenant=tenant)


def _comment(task, author, when):
    c = Comment.objects.create(task=task, author=author, text="update")
    Comment.objects.filter(id=c.id).update(created_at=when)
    return c


@pytest.mark.django_db
class TestClassifyFollowup:
    def test_not_accepted_is_none(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            acceptance_status=AcceptanceStatus.PENDING,
        )
        assert classify_followup(task) is None

    def test_accepted_no_comments_is_no_progress(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(),
        )
        assert classify_followup(task) == FOLLOWUP_NO_PROGRESS

    def test_comment_before_acceptance_still_no_progress(self, assigner, assignee):
        now = timezone.now()
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=now,
        )
        _comment(task, assigner, now - timedelta(hours=1))
        assert classify_followup(task) == FOLLOWUP_NO_PROGRESS

    def test_assigner_posted_last_is_unanswered_comment(self, assigner, assignee):
        now = timezone.now()
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=now - timedelta(hours=2),
        )
        _comment(task, assigner, now)
        assert classify_followup(task) == FOLLOWUP_UNANSWERED_COMMENT

    def test_assignee_posted_last_is_none(self, assigner, assignee):
        now = timezone.now()
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=now - timedelta(hours=2),
        )
        _comment(task, assignee, now)
        assert classify_followup(task) is None

    def test_done_a_task_is_none(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.DONE_A,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(),
        )
        assert classify_followup(task) is None


@pytest.mark.django_db
class TestDueProximityBucket:
    def test_unaccepted_overdue_is_none(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.PENDING,
        )
        assert due_proximity_bucket(task) is None

    def test_accepted_overdue_is_overdue_bucket(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.ACCEPTED,
        )
        assert due_proximity_bucket(task) == "overdue"

    def test_accepted_due_today_is_due_today_bucket(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now(),
        )
        assert due_proximity_bucket(task) == "due_today"

    def test_accepted_due_next_week_is_none(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now() + timedelta(days=7),
        )
        assert due_proximity_bucket(task) is None

    def test_done_a_task_is_none(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.DONE_A,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now(),
        )
        assert due_proximity_bucket(task) is None


@pytest.mark.django_db
class TestResolvedByCommentSince:
    def test_comment_after_marker_resolves(self, assigner, assignee):
        marker = timezone.now()
        task = TaskFactory(assigner=assigner, assignee=assignee)
        _comment(task, assignee, marker + timedelta(minutes=5))
        assert resolved_by_comment_since(task, marker) is True

    def test_comment_before_marker_does_not_resolve(self, assigner, assignee):
        marker = timezone.now()
        task = TaskFactory(assigner=assigner, assignee=assignee)
        _comment(task, assignee, marker - timedelta(minutes=5))
        assert resolved_by_comment_since(task, marker) is False
