import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import EvidenceType
from apps.evidence.models import Evidence
from apps.notifications.models import Notification
from apps.tasks.models import Task
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


@pytest.fixture
def sub_assignee(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def in_progress_task(tenant, assigner, assignee):
    """A parent task accepted by its assignee -- the only state subtasks can be
    created under."""
    assigner_client = _authed_client(assigner, tenant.id)
    assignee_client = _authed_client(assignee, tenant.id)
    resp = assigner_client.post(
        "/api/v1/tasks/",
        {"title": "Prepare NAAC report", "assigneeId": str(assignee.id), "dueDate": "2026-08-20T00:00:00Z"},
        format="json",
    )
    task_id = resp.data["data"]["id"]
    assignee_client.post(f"/api/v1/tasks/{task_id}/accept/")
    return Task.objects.get(id=task_id)


@pytest.mark.django_db
class TestSubtaskCreate:
    def test_create_by_parent_assignee_succeeds_and_notifies_parent_assigner(
        self, tenant, assigner, assignee, sub_assignee, in_progress_task,
    ):
        client = _authed_client(assignee, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/",
            {
                "title": "Compile criterion A1 data",
                "assigneeId": str(sub_assignee.id),
                "dueDate": "2026-08-10T00:00:00Z",
            },
            format="json",
        )
        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["status"] == "OPEN"
        assert data["assignerId"] == str(assignee.id)
        assert data["assigneeId"] == str(sub_assignee.id)
        assert data["parentTaskId"] == str(in_progress_task.id)

        # SUBTASK_CREATED notifies the *parent's* assigner, not the new sub-assignee
        # (api-spec.md §11's notification-types table).
        assert Notification.objects.filter(
            type="SUBTASK_CREATED", recipient=assigner, entity_id=data["id"],
        ).exists()
        assert not Notification.objects.filter(type="SUBTASK_CREATED", recipient=sub_assignee).exists()

    def test_create_by_non_assignee_forbidden(self, tenant, assigner, sub_assignee, in_progress_task):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/",
            {"title": "X", "assigneeId": str(sub_assignee.id), "dueDate": "2026-08-10T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 403

    def test_create_before_parent_accepted_rejected(self, tenant, assigner, assignee, sub_assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/",
            {"title": "Draft parent", "assigneeId": str(assignee.id), "dueDate": "2026-08-20T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]

        resp = _authed_client(assignee, tenant.id).post(
            f"/api/v1/tasks/{task_id}/subtasks/",
            {"title": "X", "assigneeId": str(sub_assignee.id), "dueDate": "2026-08-10T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 400

    def test_create_assigned_to_parent_assigner_rejected(self, tenant, assigner, assignee, in_progress_task):
        client = _authed_client(assignee, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/",
            {"title": "X", "assigneeId": str(assigner.id), "dueDate": "2026-08-10T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "ASSIGNMENT_LOOP"

    def test_create_due_date_not_before_parent_rejected(
        self, tenant, assignee, sub_assignee, in_progress_task,
    ):
        client = _authed_client(assignee, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/",
            # in_progress_task is due 2026-08-20
            {"title": "X", "assigneeId": str(sub_assignee.id), "dueDate": "2026-08-20T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "SUBTASK_DUE_DATE_INVALID"

    def test_create_inherits_parent_main_label_when_not_given(
        self, tenant, assignee, sub_assignee, in_progress_task,
    ):
        from apps.labels.models import ProjectLabel

        label = ProjectLabel.objects.create(
            tenant_id=tenant.id, created_by=in_progress_task.assigner, name="NAAC Cycle 4",
        )
        in_progress_task.main_label = label
        in_progress_task.save()

        client = _authed_client(assignee, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/",
            {"title": "X", "assigneeId": str(sub_assignee.id), "dueDate": "2026-08-10T00:00:00Z"},
            format="json",
        )
        assert resp.status_code == 201
        subtask = Task.objects.get(id=resp.data["data"]["id"])
        assert subtask.main_label_id == label.id


@pytest.mark.django_db
class TestSubtaskLifecycle:
    def _create_subtask(self, tenant, assignee, sub_assignee, parent):
        client = _authed_client(assignee, tenant.id)
        resp = client.post(
            f"/api/v1/tasks/{parent.id}/subtasks/",
            {"title": "Compile data", "assigneeId": str(sub_assignee.id), "dueDate": "2026-08-10T00:00:00Z"},
            format="json",
        )
        return resp.data["data"]["id"]

    def test_wrong_parent_in_url_is_404(self, tenant, assignee, sub_assignee, in_progress_task):
        subtask_id = self._create_subtask(tenant, assignee, sub_assignee, in_progress_task)
        wrong_parent_id = "00000000-0000-0000-0000-000000000000"
        resp = _authed_client(sub_assignee, tenant.id).post(
            f"/api/v1/tasks/{wrong_parent_id}/subtasks/{subtask_id}/accept/",
        )
        assert resp.status_code == 404

    def test_done_d_on_subtask_does_not_archive_and_fires_subtask_type(
        self, tenant, assignee, sub_assignee, in_progress_task,
    ):
        subtask_id = self._create_subtask(tenant, assignee, sub_assignee, in_progress_task)
        sub_client = _authed_client(sub_assignee, tenant.id)
        parent_assignee_client = _authed_client(assignee, tenant.id)

        sub_client.post(f"/api/v1/tasks/{in_progress_task.id}/subtasks/{subtask_id}/accept/")
        sub_client.post(f"/api/v1/tasks/{in_progress_task.id}/subtasks/{subtask_id}/done-a/")
        resp = parent_assignee_client.post(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/{subtask_id}/done-d/",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "DONE_D"
        assert resp.data["data"]["isArchived"] is False
        assert Task.objects.get(id=subtask_id).is_archived is False
        assert Notification.objects.filter(type="SUBTASK_DONE_D", recipient=sub_assignee).exists()

    def test_parent_done_d_blocked_while_subtask_incomplete_but_allowed_once_cancelled(
        self, tenant, assigner, assignee, sub_assignee, in_progress_task,
    ):
        subtask_id = self._create_subtask(tenant, assignee, sub_assignee, in_progress_task)
        assignee_client = _authed_client(assignee, tenant.id)
        assigner_client = _authed_client(assigner, tenant.id)

        assignee_client.post(f"/api/v1/tasks/{in_progress_task.id}/done-a/")
        resp = assigner_client.post(f"/api/v1/tasks/{in_progress_task.id}/done-d/")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "SUBTASKS_INCOMPLETE"

        # Cancelling the subtask (instead of completing it) must also unblock the
        # parent -- a cancelled subtask can never reach DONE_D on its own.
        assignee_client.post(f"/api/v1/tasks/{in_progress_task.id}/subtasks/{subtask_id}/cancel/")
        resp = assigner_client.post(f"/api/v1/tasks/{in_progress_task.id}/done-d/")
        assert resp.status_code == 200
        assert resp.data["data"]["isArchived"] is True

    def test_reassign_blocked_once_subtask_exists(
        self, tenant, assigner, assignee, sub_assignee, in_progress_task,
    ):
        self._create_subtask(tenant, assignee, sub_assignee, in_progress_task)
        other = UserFactory(tenant=tenant)
        resp = _authed_client(assigner, tenant.id).patch(
            f"/api/v1/tasks/{in_progress_task.id}/", {"assigneeId": str(other.id)}, format="json",
        )
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "REASSIGN_BLOCKED"

    def test_patch_subtask_title_rejected(self, tenant, assignee, sub_assignee, in_progress_task):
        subtask_id = self._create_subtask(tenant, assignee, sub_assignee, in_progress_task)
        resp = _authed_client(assignee, tenant.id).patch(
            f"/api/v1/tasks/{in_progress_task.id}/subtasks/{subtask_id}/",
            {"title": "New title"},
            format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "TITLE_IMMUTABLE"


@pytest.mark.django_db
class TestEvidenceRequiredGate:
    def test_done_a_blocked_without_evidence_then_allowed_once_uploaded(
        self, tenant, assigner, assignee,
    ):
        assigner_client = _authed_client(assigner, tenant.id)
        assignee_client = _authed_client(assignee, tenant.id)
        resp = assigner_client.post(
            "/api/v1/tasks/",
            {
                "title": "Submit evidence",
                "assigneeId": str(assignee.id),
                "dueDate": "2026-08-20T00:00:00Z",
                "evidenceRequired": True,
            },
            format="json",
        )
        assert resp.data["data"]["evidenceRequired"] is True
        task_id = resp.data["data"]["id"]
        assignee_client.post(f"/api/v1/tasks/{task_id}/accept/")

        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/done-a/")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "EVIDENCE_REQUIRED"

        Evidence.objects.create(
            task_id=task_id,
            uploader=assignee,
            file_url="tenant/task/evidence/report.pdf",
            file_name="report.pdf",
            file_size=1024,
            file_type=EvidenceType.PDF,
        )
        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/done-a/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "DONE_A"
