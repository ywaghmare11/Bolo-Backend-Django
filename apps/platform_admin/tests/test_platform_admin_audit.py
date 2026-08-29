"""Phase 15b -- AuditLog wiring for PlatformAdmin (cross-tenant) actions.

The generic audit middleware (apps/common/audit_middleware.py) previously only
resolved an actor from the tenant-user `token` cookie, so nothing under
/platform-admin/* was audited. These tests cover the second actor-resolution
path: the admin_token cookie -> actor_type=PLATFORM_ADMIN, actor_id=null,
operator identity in AuditLog.metadata.
"""
import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.common.enums import AuditActorType, OrgRoleLevel, Vertical
from apps.platform_admin.models import PlatformAdmin
from apps.platform_admin.tokens import issue_admin_access_token
from apps.tenants.factories import TenantFactory, TenantMembershipFactory
from apps.users.factories import UserFactory
from apps.users.models import User


@pytest.fixture
def admin():
    return PlatformAdmin.objects.create(name="Ops Admin", email="admin@bolo.internal")


@pytest.fixture
def client(admin):
    c = APIClient()
    c.cookies["admin_token"] = issue_admin_access_token(admin.id, admin.email, admin.role)
    return c


def _tenant_payload(**overrides):
    payload = {
        "tenantName": "ABC College",
        "urlSlug": "abc-college",
        "vertical": Vertical.EDUCATION,
        "adminName": "Dr. Kamal Sethi",
        "adminEmail": "dean@abc.edu",
        "roleLabel": "Dean",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestTenantCreatedAudit:
    def test_writes_tenant_created_row(self, client, admin):
        resp = client.post("/api/v1/platform-admin/tenants/", _tenant_payload(), format="json")
        assert resp.status_code == 201
        tenant_id = resp.data["data"]["tenantId"]

        log = AuditLog.objects.get(entity_type="TENANT", entity_id=tenant_id)
        assert log.action == "TENANT_CREATED"
        # a PlatformAdmin is not a User row
        assert log.actor_id is None
        assert log.actor_type == AuditActorType.PLATFORM_ADMIN
        # its identity is captured in metadata instead
        assert log.metadata == {
            "platformAdminId": str(admin.id),
            "platformAdminEmail": admin.email,
        }
        # tenant FK points at the tenant that was just created
        assert str(log.tenant_id) == str(tenant_id)
        assert log.before is None
        assert log.after == {"vertical": Vertical.EDUCATION, "url_slug": "abc-college"}

    def test_failed_create_writes_no_row(self, client):
        TenantFactory(name="Other", url_slug="abc-college")
        resp = client.post("/api/v1/platform-admin/tenants/", _tenant_payload(), format="json")
        assert resp.status_code == 400
        assert not AuditLog.objects.filter(action="TENANT_CREATED").exists()

    def test_unauthenticated_writes_no_row(self):
        resp = APIClient().post(
            "/api/v1/platform-admin/tenants/", _tenant_payload(), format="json",
        )
        assert resp.status_code == 401
        assert not AuditLog.objects.exists()


@pytest.mark.django_db
class TestMemberAddedAudit:
    def test_writes_member_added_row(self, client, admin):
        tenant = TenantFactory()
        resp = client.post(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/",
            {"name": "Prof. Asha Nair", "email": "asha@abc.edu", "roleLevel": OrgRoleLevel.MID},
            format="json",
        )
        assert resp.status_code == 201
        user_id = resp.data["data"]["userId"]

        log = AuditLog.objects.get(entity_type="USER", entity_id=user_id, action="MEMBER_ADDED")
        assert log.actor_id is None
        assert log.actor_type == AuditActorType.PLATFORM_ADMIN
        assert log.metadata["platformAdminEmail"] == admin.email
        # tenant FK comes from the URL path param, not a tenant-user JWT
        assert str(log.tenant_id) == str(tenant.id)
        assert log.before is None
        assert log.after == {"tenant_id": str(tenant.id), "preferred_lang": "EN"}


@pytest.mark.django_db
class TestMemberRemovedAudit:
    def test_writes_member_removed_row_with_null_after(self, client):
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        TenantMembershipFactory(tenant=tenant, user=user)

        resp = client.delete(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/{user.id}/",
        )
        assert resp.status_code == 200

        log = AuditLog.objects.get(entity_type="USER", entity_id=str(user.id), action="MEMBER_REMOVED")
        assert log.actor_type == AuditActorType.PLATFORM_ADMIN
        assert log.actor_id is None
        assert str(log.tenant_id) == str(tenant.id)
        # DELETE -> after is null by middleware convention; before is the pre-delete state
        assert log.after is None
        assert log.before == {"tenant_id": str(tenant.id), "preferred_lang": "EN"}
        # the User row itself survives (only the membership is deleted)
        assert User.objects.filter(id=user.id).exists()

    def test_failed_remove_writes_no_row(self, client):
        tenant = TenantFactory()
        user = UserFactory()  # no membership in this tenant
        resp = client.delete(
            f"/api/v1/platform-admin/tenants/{tenant.id}/members/{user.id}/",
        )
        assert resp.status_code == 404
        assert not AuditLog.objects.filter(action="MEMBER_REMOVED").exists()


@pytest.mark.django_db
class TestTenantUserAuditPathUnaffected:
    """Regression: the original USER/SYSTEM actor inference still applies when
    actor_type isn't passed (every non-platform-admin route)."""

    def test_tenant_user_task_create_still_user_actor(self):
        from apps.auth.tokens import issue_access_token

        tenant = TenantFactory()
        assigner = UserFactory(tenant=tenant)
        assignee = UserFactory(tenant=tenant)
        c = APIClient()
        c.cookies["token"] = issue_access_token(assigner.id, tenant.id, "MID")

        resp = c.post(
            "/api/v1/tasks/",
            {"title": "X", "assigneeId": str(assignee.id), "dueDate": "2026-08-01T00:00:00Z"},
            format="json",
        )
        log = AuditLog.objects.get(entity_type="TASK", entity_id=resp.data["data"]["id"])
        assert log.actor_type == AuditActorType.USER
        assert str(log.actor_id) == str(assigner.id)
        assert log.metadata is None
