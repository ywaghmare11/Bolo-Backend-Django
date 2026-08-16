from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.comments.models import Comment
from apps.common.enums import AcceptanceStatus, NotificationType, TaskStatus
from apps.notifications.models import Notification, NudgeSkipCounter
from apps.notifications.tasks import ai_nudge_due_proximity_sweep, ai_nudge_followup_sweep
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


@pytest.mark.django_db
class TestFollowupSweep:
    def test_no_progress_since_acceptance_notifies_assignee(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(),
        )
        ai_nudge_followup_sweep()

        assert Notification.objects.filter(
            type=NotificationType.AI_NUDGE_FOLLOWUP, recipient=assignee, entity_id=str(task.id),
        ).exists()
        assert not Notification.objects.filter(recipient=assigner).exists()
        assert len(mail.outbox) == 0

    def test_assigner_owed_reply_notifies_assignee(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now() - timedelta(hours=1),
        )
        Comment.objects.create(task=task, author=assigner, text="any update?")
        ai_nudge_followup_sweep()
        assert Notification.objects.filter(
            type=NotificationType.AI_NUDGE_FOLLOWUP, recipient=assignee,
        ).exists()

    def test_assignee_answered_no_nudge(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now() - timedelta(hours=1),
        )
        Comment.objects.create(task=task, author=assignee, text="working on it")
        ai_nudge_followup_sweep()
        assert not Notification.objects.filter(type=NotificationType.AI_NUDGE_FOLLOWUP).exists()

    def test_does_not_pile_up_while_unread_nudge_pending(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(),
        )
        ai_nudge_followup_sweep()
        ai_nudge_followup_sweep()
        assert Notification.objects.filter(type=NotificationType.AI_NUDGE_FOLLOWUP, entity_id=str(task.id)).count() == 1

    def test_not_accepted_no_nudge(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OPEN,
            acceptance_status=AcceptanceStatus.PENDING,
        )
        ai_nudge_followup_sweep()
        assert not Notification.objects.filter(type=NotificationType.AI_NUDGE_FOLLOWUP).exists()


@pytest.mark.django_db
class TestDueProximitySweep:
    def test_due_today_notifies_assignee_in_app_only(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now(),
        )
        ai_nudge_due_proximity_sweep()

        assert Notification.objects.filter(
            type=NotificationType.AI_NUDGE_DUE_PROXIMITY, recipient=assignee, entity_id=str(task.id),
        ).exists()
        assert len(mail.outbox) == 0

    def test_not_accepted_overdue_no_nudge(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.PENDING,
        )
        ai_nudge_due_proximity_sweep()
        assert not Notification.objects.filter(type=NotificationType.AI_NUDGE_DUE_PROXIMITY).exists()

    def test_escalates_once_when_cap_reached_and_not_yet_escalated(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.ACCEPTED,
        )
        NudgeSkipCounter.objects.create(
            tenant_id=task.tenant_id, entity_type="task", entity_id=str(task.id),
            nudge_kind="due_proximity", skip_count=1,  # overdue cap is 1
        )
        ai_nudge_due_proximity_sweep()

        assert Notification.objects.filter(
            type=NotificationType.AI_NUDGE_DUE_PROXIMITY, recipient=assigner, entity_id=str(task.id),
        ).exists()
        assert len(mail.outbox) == 1
        counter = NudgeSkipCounter.objects.get(entity_id=str(task.id), nudge_kind="due_proximity")
        assert counter.escalated_at is not None

    def test_escalation_never_repeats(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.OVERDUE,
            acceptance_status=AcceptanceStatus.ACCEPTED,
        )
        NudgeSkipCounter.objects.create(
            tenant_id=task.tenant_id, entity_type="task", entity_id=str(task.id),
            nudge_kind="due_proximity", skip_count=1, escalated_at=timezone.now(),
        )
        ai_nudge_due_proximity_sweep()
        assert not Notification.objects.filter(
            type=NotificationType.AI_NUDGE_DUE_PROXIMITY, recipient=assigner,
        ).exists()

    def test_below_cap_no_escalation(self, assigner, assignee):
        task = TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, due_date=timezone.now(),
        )
        NudgeSkipCounter.objects.create(
            tenant_id=task.tenant_id, entity_type="task", entity_id=str(task.id),
            nudge_kind="due_proximity", skip_count=1,  # due-today cap is 3
        )
        ai_nudge_due_proximity_sweep()
        assert not Notification.objects.filter(
            type=NotificationType.AI_NUDGE_DUE_PROXIMITY, recipient=assigner,
        ).exists()

    def test_cross_type_dedup_suppresses_followup_while_due_proximity_pending(self, assigner, assignee):
        TaskFactory(
            assigner=assigner, assignee=assignee, status=TaskStatus.IN_PROGRESS,
            acceptance_status=AcceptanceStatus.ACCEPTED, accepted_at=timezone.now(),
            due_date=timezone.now(),
        )
        ai_nudge_due_proximity_sweep()
        assert Notification.objects.filter(type=NotificationType.AI_NUDGE_DUE_PROXIMITY).exists()

        ai_nudge_followup_sweep()
        assert not Notification.objects.filter(type=NotificationType.AI_NUDGE_FOLLOWUP).exists()
