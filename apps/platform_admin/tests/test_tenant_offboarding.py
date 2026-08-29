"""Phase 15e -- operator tenant offboarding (suspend / reactivate).

Covers the PATCH /platform-admin/tenants/:id endpoint, its audit rows, and the
enforcement: a SUSPENDED tenant's users can't request/verify an OTP or refresh a
session, its Celery sweeps don't fire, and no members can be added to it.
"""
import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.common.enums import AuditActorType, OrgRoleLevel, TenantStatus
from apps.platform_admin.models import PlatformAdmin
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.factories import TenantFactory, TenantMembershipFactory
from apps.users.factories import UserFactory


@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


@pytest.fixture
def client(admin):
    c = APIClient()
    c.cookies["admin_token"] = issue_admin_access_token(admin.id, admin.email, admin.role)
    return c


def _patch(client, tenant_id, **body):
    return client.patch(
        f"/api/v1/platform-admin/tenants/{tenant_id}/", body, format="json",
    )


def _otp_from_outbox():
    return "".join(filter(str.isdigit, mail.outbox[-1].body))[:6]


def _login(email):
    """Full tenant-user OTP login; returns the APIClient with session cookies."""
    c = APIClient()
    c.post("/api/v1/auth/request-otp/", {"email": email}, format="json")
    otp = _otp_from_outbox()
    resp = c.post("/api/v1/auth/verify-otp/", {"email": email, "otp": otp}, format="json")
    assert resp.status_code == 200
    return c


@pytest.mark.django_db
class TestPatchEndpoint:
    def test_suspend_sets_status_reason_and_timestamp(self, client):
        tenant = TenantFactory()
        resp = _patch(client, tenant.id, status="SUSPENDED", reason="non-payment")

        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "SUSPENDED"
        assert resp.data["data"]["suspensionReason"] == "non-payment"
        assert resp.data["data"]["suspendedAt"] is not None
        tenant.refresh_from_db()
        assert tenant.status == TenantStatus.SUSPENDED
        assert tenant.suspended_at is not None

    def test_reactivate_clears_suspension(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED, suspension_reason="x")
        resp = _patch(client, tenant.id, status="ACTIVE")

        assert resp.status_code == 200
        tenant.refresh_from_db()
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.suspended_at is None
        assert tenant.suspension_reason is None

    def test_suspend_already_suspended_is_409(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED)
        resp = _patch(client, tenant.id, status="SUSPENDED")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "TENANT_STATUS_UNCHANGED"

    def test_reactivate_already_active_is_409(self, client):
        tenant = TenantFactory()
        resp = _patch(client, tenant.id, status="ACTIVE")
        assert resp.status_code == 409

    def test_unknown_tenant_is_404(self, client):
        resp = _patch(client, "00000000-0000-0000-0000-000000000000", status="SUSPENDED")
        assert resp.status_code == 404

    def test_invalid_status_is_400(self, client):
        tenant = TenantFactory()
        resp = _patch(client, tenant.id, status="DELETED")
        assert resp.status_code == 400

    def test_requires_super_admin_role(self, admin):
        from rest_framework_simplejwt.tokens import AccessToken

        tok = AccessToken()
        tok["adminId"] = str(admin.id)
        tok["email"] = admin.email
        tok["isPlatformAdmin"] = True
        tok["role"] = "VIEWER"
        c = APIClient()
        c.cookies["admin_token"] = str(tok)
        resp = _patch(c, TenantFactory().id, status="SUSPENDED")
        assert resp.status_code == 403

    def test_unauthenticated_is_401(self):
        resp = _patch(APIClient(), TenantFactory().id, status="SUSPENDED")
        assert resp.status_code == 401

    def test_tenant_list_shows_status(self, client):
        TenantFactory(name="Active Co")
        TenantFactory(name="Gone Co", status=TenantStatus.SUSPENDED)
        resp = client.get("/api/v1/platform-admin/tenants/")
        by_name = {r["name"]: r["status"] for r in resp.data["data"]}
        assert by_name == {"Active Co": "ACTIVE", "Gone Co": "SUSPENDED"}


@pytest.mark.django_db
class TestAuditTrail:
    def test_suspend_writes_tenant_suspended_row(self, client, admin):
        tenant = TenantFactory()
        _patch(client, tenant.id, status="SUSPENDED", reason="customer offboarded")

        log = AuditLog.objects.get(action="TENANT_SUSPENDED", entity_id=str(tenant.id))
        assert log.entity_type == "TENANT"
        assert log.actor_id is None
        assert log.actor_type == AuditActorType.PLATFORM_ADMIN
        assert str(log.tenant_id) == str(tenant.id)
        assert log.before == {"status": "ACTIVE", "suspension_reason": None}
        assert log.after == {"status": "SUSPENDED", "suspension_reason": "customer offboarded"}
        assert log.metadata == {
            "platformAdminId": str(admin.id), "platformAdminEmail": admin.email,
        }

    def test_reactivate_writes_tenant_reactivated_row(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED, suspension_reason="x")
        _patch(client, tenant.id, status="ACTIVE")

        log = AuditLog.objects.get(action="TENANT_REACTIVATED", entity_id=str(tenant.id))
        assert log.before["status"] == "SUSPENDED"
        assert log.after["status"] == "ACTIVE"

    def test_failed_patch_writes_no_audit_row(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED)
        _patch(client, tenant.id, status="SUSPENDED")  # 409
        assert not AuditLog.objects.filter(entity_id=str(tenant.id)).exists()


@pytest.mark.django_db
class TestLoginEnforcement:
    def _member(self, tenant, email):
        user = UserFactory(tenant=tenant, email=email)
        TenantMembershipFactory(tenant=tenant, user=user, role_level=OrgRoleLevel.MID)
        return user

    def test_suspended_tenant_cannot_request_otp(self, client):
        tenant = TenantFactory()
        self._member(tenant, "u@abc.edu")
        _patch(client, tenant.id, status="SUSPENDED")

        c = APIClient()
        resp = c.post("/api/v1/auth/request-otp/", {"email": "u@abc.edu"}, format="json")
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "TENANT_SUSPENDED"
        assert mail.outbox == []  # no OTP email sent

    def test_suspended_tenant_cannot_verify_otp(self, client):
        tenant = TenantFactory()
        self._member(tenant, "u@abc.edu")
        c = APIClient()
        c.post("/api/v1/auth/request-otp/", {"email": "u@abc.edu"}, format="json")
        otp = _otp_from_outbox()
        _patch(client, tenant.id, status="SUSPENDED")  # suspend after OTP issued

        resp = c.post(
            "/api/v1/auth/verify-otp/", {"email": "u@abc.edu", "otp": otp}, format="json",
        )
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "TENANT_SUSPENDED"

    def test_suspended_tenant_refresh_rejected(self, client):
        tenant = TenantFactory()
        self._member(tenant, "u@abc.edu")
        session = _login("u@abc.edu")

        _patch(client, tenant.id, status="SUSPENDED")
        resp = session.post("/api/v1/auth/refresh/")
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "TENANT_SUSPENDED"

    def test_reactivated_tenant_can_log_in_again(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED)
        self._member(tenant, "u@abc.edu")
        _patch(client, tenant.id, status="ACTIVE")

        session = _login("u@abc.edu")  # asserts 200 internally
        assert session is not None


@pytest.mark.django_db
class TestMemberOpsBlocked:
    def test_add_member_to_suspended_tenant_is_409(self, client):
        tenant = TenantFactory(status=TenantStatus.SUSPENDED)
        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {"name": "X", "email": "x@abc.edu", "roleLevel": OrgRoleLevel.MID},
            format="json",
        )
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "TENANT_SUSPENDED"

    def test_bulk_import_to_suspended_tenant_is_409(self, client):
        from django.core.files.uploadedfile import SimpleUploadedFile

        tenant = TenantFactory(status=TenantStatus.SUSPENDED)
        f = SimpleUploadedFile("m.csv", b"name,email,role\nA,a@abc.edu,MID\n")
        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/import/",
            {"file": f}, format="multipart",
        )
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "TENANT_SUSPENDED"


@pytest.mark.django_db
class TestSweepEnforcement:
    def test_due_proximity_sweep_skips_suspended_tenant(self, client):
        from django.utils import timezone

        from apps.tasks.factories import TaskFactory
        from apps.tasks.tasks import task_due_proximity_sweep

        tenant = TenantFactory()
        assigner = UserFactory(tenant=tenant)
        assignee = UserFactory(tenant=tenant)
        task = TaskFactory(
            tenant_id=tenant.id, assigner=assigner, assignee=assignee,
            status="OPEN", due_date=timezone.now(),
        )
        _patch(client, tenant.id, status="SUSPENDED")

        mail.outbox.clear()
        task_due_proximity_sweep()

        task.refresh_from_db()
        assert task.due_today_notified_at is None       # not notified
        assert task.status == "OPEN"                     # not transitioned to OVERDUE
        assert mail.outbox == []
