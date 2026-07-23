import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.auth.tokens import issue_access_token
from apps.tasks.factories import TaskFactory
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level="MID"):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
    return client


def _otp_code_from_outbox():
    body = mail.outbox[-1].body
    return "".join(filter(str.isdigit, body))[:6]


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
class TestTaskAuditTrail:
    def test_create_writes_task_created(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        resp = client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]

        log = AuditLog.objects.get(entity_type="TASK", entity_id=task_id)
        assert log.action == "TASK_CREATED"
        assert str(log.tenant_id) == str(tenant.id)
        assert str(log.actor_id) == str(assigner.id)
        assert log.before is None
        assert log.after["status"] == "OPEN"

    def test_reassign_writes_task_reassigned(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        new_assignee = UserFactory(tenant=tenant)
        task = TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee)

        AuditLog.objects.all().delete()
        resp = client.patch(
            f"/api/v1/tasks/{task.id}/", {"assigneeId": str(new_assignee.id)}, format="json",
        )
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="TASK", entity_id=str(task.id))
        assert log.action == "TASK_REASSIGNED"
        assert log.before["assignee_id"] == str(assignee.id)
        assert log.after["assignee_id"] == str(new_assignee.id)

    def test_due_date_only_change_writes_task_due_date_changed(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        task = TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee)

        AuditLog.objects.all().delete()
        resp = client.patch(
            f"/api/v1/tasks/{task.id}/", {"dueDate": "2026-09-01T00:00:00Z"}, format="json",
        )
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="TASK", entity_id=str(task.id))
        assert log.action == "TASK_DUE_DATE_CHANGED"

    def test_delete_writes_task_deleted_with_null_after(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        task = TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee)

        AuditLog.objects.all().delete()
        resp = client.delete(f"/api/v1/tasks/{task.id}/")
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="TASK", entity_id=str(task.id))
        assert log.action == "TASK_DELETED"
        assert log.after is None
        assert log.before["status"] is not None

    def test_accept_writes_task_status_changed(self, tenant, assigner, assignee):
        assigner_client = _authed_client(assigner, tenant.id)
        assignee_client = _authed_client(assignee, tenant.id)
        resp = assigner_client.post(
            "/api/v1/tasks/",
            {"title": "Ship report", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        task_id = resp.data["data"]["id"]

        AuditLog.objects.all().delete()
        resp = assignee_client.post(f"/api/v1/tasks/{task_id}/accept/")
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="TASK", entity_id=task_id)
        assert log.action == "TASK_STATUS_CHANGED"
        assert log.after["status"] == "IN_PROGRESS"

    def test_forbidden_request_does_not_write_audit_log(self, tenant, assigner, assignee):
        """assignee (not the assigner) tries to PATCH -- 403, no mutation, no audit row."""
        assignee_client = _authed_client(assignee, tenant.id)
        task = TaskFactory(tenant_id=tenant.id, assigner=assigner, assignee=assignee)

        AuditLog.objects.all().delete()
        resp = assignee_client.patch(
            f"/api/v1/tasks/{task.id}/", {"priority": "P1"}, format="json",
        )
        assert resp.status_code == 403
        assert not AuditLog.objects.filter(entity_type="TASK", entity_id=str(task.id)).exists()

    def test_label_create_is_not_audited(self, tenant, assigner):
        """No AuditAction values exist for label events yet -- deliberately excluded
        from AUDIT_ROUTE_CONFIG rather than inventing one."""
        client = _authed_client(assigner, tenant.id)
        AuditLog.objects.all().delete()
        resp = client.post(
            "/api/v1/labels/", {"name": "Urgent", "colorCode": "#FF0000", "description": ""}, format="json",
        )
        assert resp.status_code == 201
        assert not AuditLog.objects.filter(entity_type="LABEL").exists()


@pytest.mark.django_db
class TestAuthAuditTrail:
    def test_login_writes_user_login(self, tenant):
        user = UserFactory(tenant=tenant, email="dean@abc.edu")
        from apps.tenants.factories import TenantMembershipFactory

        TenantMembershipFactory(user=user, tenant=tenant)
        client = APIClient()

        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        otp = _otp_code_from_outbox()
        resp = client.post(
            "/api/v1/auth/verify-otp/", {"email": user.email, "otp": otp}, format="json",
        )
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="USER", action="USER_LOGIN", entity_id=str(user.id))
        assert str(log.actor_id) == str(user.id)
        assert str(log.tenant_id) == str(tenant.id)
        assert log.before is None
        assert log.after["last_login_at"] is not None

    def test_logout_writes_user_logout(self, tenant):
        user = UserFactory(tenant=tenant, email="dean@abc.edu")
        from apps.tenants.factories import TenantMembershipFactory

        TenantMembershipFactory(user=user, tenant=tenant)
        client = APIClient()
        client.post("/api/v1/auth/request-otp/", {"email": user.email}, format="json")
        otp = _otp_code_from_outbox()
        client.post("/api/v1/auth/verify-otp/", {"email": user.email, "otp": otp}, format="json")

        AuditLog.objects.all().delete()
        resp = client.post("/api/v1/auth/logout/")
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="USER", action="USER_LOGOUT", entity_id=str(user.id))
        assert str(log.actor_id) == str(user.id)
        assert log.after["last_logout_at"] is not None
