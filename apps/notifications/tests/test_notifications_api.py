import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import NotificationType
from apps.notifications.models import Notification
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
def me(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def other_user(tenant):
    return UserFactory(tenant=tenant)


def _make_notification(tenant, recipient, type_=NotificationType.TASK_ASSIGNED, is_read=False, **extra):
    return Notification.objects.create(
        tenant_id=tenant.id,
        recipient=recipient,
        type=type_,
        entity_type="task",
        entity_id="some-task-id",
        message="Dr. Sethi assigned you a task",
        is_read=is_read,
        **extra,
    )


@pytest.mark.django_db
def test_list_notifications_scoped_to_recipient(tenant, me, other_user):
    mine = _make_notification(tenant, me)
    _make_notification(tenant, other_user)

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/")

    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data["data"]]
    assert ids == [str(mine.id)]


@pytest.mark.django_db
def test_list_notifications_filters_by_is_read(tenant, me):
    unread = _make_notification(tenant, me, is_read=False)
    _make_notification(tenant, me, is_read=True)

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/?isRead=false")

    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data["data"]]
    assert ids == [str(unread.id)]


@pytest.mark.django_db
def test_list_notifications_filters_by_type(tenant, me):
    task_notif = _make_notification(tenant, me, type_=NotificationType.TASK_ASSIGNED)
    _make_notification(tenant, me, type_=NotificationType.BROADCAST_POSTED)

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/?type=TASK_ASSIGNED")

    assert resp.status_code == 200
    ids = [row["id"] for row in resp.data["data"]]
    assert ids == [str(task_notif.id)]


@pytest.mark.django_db
def test_list_notifications_shape(tenant, me):
    _make_notification(
        tenant, me, actor_name="Dr. Sethi", entity_title="Submit NAAC report", entity_context="IQAC",
    )

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/")

    row = resp.data["data"][0]
    assert row["type"] == NotificationType.TASK_ASSIGNED
    assert row["entityType"] == "task"
    assert row["actorName"] == "Dr. Sethi"
    assert row["entityTitle"] == "Submit NAAC report"
    assert row["entityContext"] == "IQAC"
    assert row["isRead"] is False
    assert row["readAt"] is None
    assert "createdAt" in row
    assert resp.data["pagination"]["total"] == 1


@pytest.mark.django_db
def test_mark_read(tenant, me):
    notification = _make_notification(tenant, me)

    client = _authed_client(me, tenant.id)
    resp = client.patch(f"/api/v1/notifications/{notification.id}/read/")

    assert resp.status_code == 200
    assert resp.data["data"]["isRead"] is True
    assert resp.data["data"]["readAt"] is not None
    notification.refresh_from_db()
    assert notification.is_read is True
    assert notification.read_at is not None


@pytest.mark.django_db
def test_mark_read_is_idempotent(tenant, me):
    notification = _make_notification(tenant, me)
    client = _authed_client(me, tenant.id)

    first = client.patch(f"/api/v1/notifications/{notification.id}/read/")
    second = client.patch(f"/api/v1/notifications/{notification.id}/read/")

    assert first.data["data"]["readAt"] == second.data["data"]["readAt"]


@pytest.mark.django_db
def test_mark_read_404_for_someone_elses_notification(tenant, me, other_user):
    theirs = _make_notification(tenant, other_user)

    client = _authed_client(me, tenant.id)
    resp = client.patch(f"/api/v1/notifications/{theirs.id}/read/")

    assert resp.status_code == 404


@pytest.mark.django_db
def test_mark_all_read(tenant, me):
    _make_notification(tenant, me, is_read=False)
    _make_notification(tenant, me, is_read=False)
    already_read = _make_notification(tenant, me, is_read=True)

    client = _authed_client(me, tenant.id)
    resp = client.post("/api/v1/notifications/mark-all-read/")

    assert resp.status_code == 200
    assert resp.data["data"]["updatedCount"] == 2
    assert Notification.objects.filter(recipient=me, is_read=False).count() == 0
    already_read.refresh_from_db()
    assert already_read.is_read is True


@pytest.mark.django_db
def test_mark_all_read_does_not_touch_other_users(tenant, me, other_user):
    _make_notification(tenant, me, is_read=False)
    theirs = _make_notification(tenant, other_user, is_read=False)

    client = _authed_client(me, tenant.id)
    client.post("/api/v1/notifications/mark-all-read/")

    theirs.refresh_from_db()
    assert theirs.is_read is False


@pytest.mark.django_db
def test_unread_count(tenant, me):
    _make_notification(tenant, me, is_read=False)
    _make_notification(tenant, me, is_read=False)
    _make_notification(tenant, me, is_read=True)

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/unread-count/")

    assert resp.status_code == 200
    assert resp.data["data"]["count"] == 2


@pytest.mark.django_db
def test_unread_count_scoped_to_recipient(tenant, me, other_user):
    _make_notification(tenant, other_user, is_read=False)

    client = _authed_client(me, tenant.id)
    resp = client.get("/api/v1/notifications/unread-count/")

    assert resp.data["data"]["count"] == 0
