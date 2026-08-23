import io
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.auth.tokens import issue_access_token
from apps.broadcasts.models import BroadcastNotice
from apps.common.enums import OrgRoleLevel
from apps.notifications.models import Notification
from apps.tenants.factories import DepartmentFactory, TenantFactory, TenantMembershipFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level="MID"):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
    return client


@pytest.fixture
def tenant():
    return TenantFactory()


@pytest.fixture
def dept_cs(tenant):
    return DepartmentFactory(tenant=tenant)


@pytest.fixture
def dept_civil(tenant):
    return DepartmentFactory(tenant=tenant)


@pytest.fixture
def sender(tenant, dept_cs):
    user = UserFactory(tenant=tenant)
    TenantMembershipFactory(
        tenant=tenant, user=user, department=dept_cs, role_level=OrgRoleLevel.TOP, can_broadcast=True,
    )
    return user


@pytest.fixture
def non_broadcaster(tenant, dept_cs):
    user = UserFactory(tenant=tenant)
    TenantMembershipFactory(
        tenant=tenant, user=user, department=dept_cs, role_level=OrgRoleLevel.TOP, can_broadcast=False,
    )
    return user


@pytest.fixture
def cs_faculty(tenant, dept_cs):
    user = UserFactory(tenant=tenant)
    TenantMembershipFactory(
        tenant=tenant, user=user, department=dept_cs, role_level=OrgRoleLevel.EXECUTOR,
    )
    return user


@pytest.fixture
def civil_faculty(tenant, dept_civil):
    user = UserFactory(tenant=tenant)
    TenantMembershipFactory(
        tenant=tenant, user=user, department=dept_civil, role_level=OrgRoleLevel.EXECUTOR,
    )
    return user


@pytest.fixture(autouse=True)
def mock_storage(monkeypatch):
    calls = {"copied": [], "deleted": [], "presigned": []}

    def fake_presign(key, content_type, expires_in):
        calls["presigned"].append((key, content_type, expires_in))
        return f"https://s3.ap-south-1.amazonaws.com/bolo-broadcast/{key}?X-Amz-Signature=fake"

    def fake_copy(source_key, dest_key):
        calls["copied"].append((source_key, dest_key))

    def fake_delete(key):
        calls["deleted"].append(key)

    def fake_get_object_stream(key):
        return io.BytesIO(b"fake image bytes"), "image/jpeg"

    monkeypatch.setattr("apps.common.storage.generate_presigned_put_url", fake_presign)
    monkeypatch.setattr("apps.common.storage.copy_object", fake_copy)
    monkeypatch.setattr("apps.common.storage.delete_object", fake_delete)
    monkeypatch.setattr("apps.common.storage.get_object_stream", fake_get_object_stream)
    return calls


def _create_draft(client, **overrides):
    body = {
        "messageJson": {"type": "doc"},
        "messageHtml": "<p>All faculty please submit reports</p>",
        "audienceDeptIds": [],
        "audienceRoleLevels": [],
        "requiresAcknowledgement": False,
    }
    body.update(overrides)
    return client.post("/api/v1/broadcast-notices/", body, format="json")


@pytest.mark.django_db
class TestBroadcastCreate:
    def test_create_draft(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = _create_draft(client)
        assert resp.status_code == 201
        assert resp.data["data"]["status"] == "DRAFT"
        assert resp.data["data"]["senderId"] == str(sender.id)

    def test_create_without_can_broadcast_is_forbidden(self, tenant, non_broadcaster):
        client = _authed_client(non_broadcaster, tenant.id)
        resp = _create_draft(client)
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "BROADCAST_NOT_PERMITTED"

    def test_create_over_char_limit_rejected(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = _create_draft(client, messageHtml=f"<p>{'x' * 201}</p>")
        assert resp.status_code == 400

    def test_create_sanitizes_html(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = _create_draft(client, messageHtml="<p>Hi<script>alert(1)</script></p>")
        assert resp.status_code == 201
        broadcast = BroadcastNotice.objects.get(id=resp.data["data"]["id"])
        assert "<script>" not in broadcast.message_html

    def test_create_with_invalid_department_rejected(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = _create_draft(client, audienceDeptIds=["00000000-0000-0000-0000-000000000000"])
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "INVALID_DEPARTMENT"

    def test_create_audited(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = _create_draft(client)
        broadcast_id = resp.data["data"]["id"]
        assert AuditLog.objects.filter(action="BROADCAST_CREATED", entity_id=broadcast_id).exists()


@pytest.mark.django_db
class TestBroadcastPublish:
    def test_publish_without_audience_is_entire_institution(
        self, tenant, sender, cs_faculty, civil_faculty,
    ):
        """W110 (2026-08-23): empty audienceDeptIds + empty audienceRoleLevels is
        now a valid, explicit "Entire Institution" scope -- publishable, and
        reaches every tenant member, not rejected as DRAFT_MISSING_FIELDS."""
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")
        assert resp.status_code == 200

        recipient_ids = set(
            Notification.objects.filter(
                type="BROADCAST_POSTED", entity_id=str(draft["id"]),
            ).values_list("recipient_id", flat=True),
        )
        assert {cs_faculty.id, civil_faculty.id} <= recipient_ids

    def test_entire_institution_reaches_member_with_no_department(self, tenant, sender):
        """A Director/Dean-level member with no department assigned (departmentId
        optional per domain-model.md) must still be reachable by "Entire
        Institution" -- the exact gap W110 exists to close."""
        deptless_member = UserFactory(tenant=tenant)
        TenantMembershipFactory(
            tenant=tenant, user=deptless_member, department=None, role_level=OrgRoleLevel.TOP,
        )
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        assert Notification.objects.filter(
            type="BROADCAST_POSTED", entity_id=str(draft["id"]), recipient_id=deptless_member.id,
        ).exists()

    def test_publish_sets_expiry_and_notifies_audience(self, tenant, sender, dept_cs, cs_faculty, civil_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        resp = client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "PUBLISHED"
        assert resp.data["data"]["expiresAt"] is not None

        broadcast = BroadcastNotice.objects.get(id=draft["id"])
        assert broadcast.expires_at - broadcast.created_at < timezone.timedelta(hours=25)

        assert Notification.objects.filter(type="BROADCAST_POSTED", recipient=cs_faculty).exists()
        assert not Notification.objects.filter(type="BROADCAST_POSTED", recipient=civil_faculty).exists()

    def test_publish_by_non_sender_forbidden(self, tenant, sender, non_broadcaster, dept_cs):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        resp = _authed_client(non_broadcaster, tenant.id).post(
            f"/api/v1/broadcast-notices/{draft['id']}/publish/",
        )
        assert resp.status_code == 403


@pytest.mark.django_db
class TestBroadcastUpdateDelete:
    def test_patch_draft_updates_text(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = client.patch(
            f"/api/v1/broadcast-notices/{draft['id']}/",
            {"messageHtml": "<p>Updated</p>"},
            format="json",
        )
        assert resp.status_code == 200
        broadcast = BroadcastNotice.objects.get(id=draft["id"])
        assert "Updated" in broadcast.message_html

    def test_patch_by_non_sender_forbidden(self, tenant, sender, non_broadcaster):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = _authed_client(non_broadcaster, tenant.id).patch(
            f"/api/v1/broadcast-notices/{draft['id']}/", {"messageHtml": "<p>x</p>"}, format="json",
        )
        assert resp.status_code == 403

    def test_patch_expired_broadcast_rejected(self, tenant, sender, dept_cs):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")
        broadcast = BroadcastNotice.objects.get(id=draft["id"])
        broadcast.expires_at = timezone.now() - timezone.timedelta(hours=1)
        broadcast.save(update_fields=["expires_at"])

        resp = client.patch(
            f"/api/v1/broadcast-notices/{draft['id']}/", {"messageHtml": "<p>x</p>"}, format="json",
        )
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "CANNOT_EDIT_EXPIRED"

    def test_patch_published_notifies_only_newly_added_recipients(
        self, tenant, sender, dept_cs, dept_civil, cs_faculty, civil_faculty,
    ):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")
        assert Notification.objects.filter(type="BROADCAST_POSTED", recipient=cs_faculty).count() == 1

        resp = client.patch(
            f"/api/v1/broadcast-notices/{draft['id']}/",
            {"audienceDeptIds": [str(dept_cs.id), str(dept_civil.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert Notification.objects.filter(type="BROADCAST_POSTED", recipient=civil_faculty).exists()
        # cs_faculty was already notified at publish time -- not notified again.
        assert Notification.objects.filter(type="BROADCAST_POSTED", recipient=cs_faculty).count() == 1

    def test_delete_by_sender(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = client.delete(f"/api/v1/broadcast-notices/{draft['id']}/")
        assert resp.status_code == 200
        assert not BroadcastNotice.objects.filter(id=draft["id"]).exists()

    def test_delete_by_non_sender_forbidden(self, tenant, sender, non_broadcaster):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = _authed_client(non_broadcaster, tenant.id).delete(
            f"/api/v1/broadcast-notices/{draft['id']}/",
        )
        assert resp.status_code == 403
        assert BroadcastNotice.objects.filter(id=draft["id"]).exists()


@pytest.mark.django_db
class TestBroadcastList:
    def test_received_only_shows_audience_matches(
        self, tenant, sender, dept_cs, dept_civil, cs_faculty, civil_faculty,
    ):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        cs_resp = _authed_client(cs_faculty, tenant.id).get("/api/v1/broadcast-notices/?view=received")
        assert len(cs_resp.data["data"]) == 1

        civil_resp = _authed_client(civil_faculty, tenant.id).get("/api/v1/broadcast-notices/?view=received")
        assert len(civil_resp.data["data"]) == 0

    def test_received_excludes_own_broadcast_unless_in_audience(self, tenant, sender, dept_civil):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_civil.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        resp = client.get("/api/v1/broadcast-notices/?view=received")
        assert len(resp.data["data"]) == 0

    def test_sent_excludes_drafts(self, tenant, sender, dept_cs):
        client = _authed_client(sender, tenant.id)
        _create_draft(client)
        published = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{published['id']}/publish/")

        resp = client.get("/api/v1/broadcast-notices/?view=sent")
        assert len(resp.data["data"]) == 1
        assert resp.data["data"][0]["id"] == published["id"]
        assert "hasAcknowledged" not in resp.data["data"][0]

    def test_sent_includes_updated_at_and_live_audience_size(
        self, tenant, sender, dept_cs, cs_faculty,
    ):
        client = _authed_client(sender, tenant.id)
        published = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{published['id']}/publish/")

        resp = client.get("/api/v1/broadcast-notices/?view=sent")
        row = resp.data["data"][0]
        assert "updatedAt" in row
        # dept_cs has the sender himself plus cs_faculty
        assert row["audienceSize"] == 2

        # audienceSize is live, not a publish-time snapshot -- a member added to
        # the tenant afterwards still counts.
        new_member = UserFactory(tenant=tenant)
        TenantMembershipFactory(tenant=tenant, user=new_member, department=dept_cs, role_level=OrgRoleLevel.EXECUTOR)
        resp2 = client.get("/api/v1/broadcast-notices/?view=sent")
        assert resp2.data["data"][0]["audienceSize"] == 3

    def test_received_view_has_no_audience_size(self, tenant, sender, dept_cs, cs_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        resp = _authed_client(cs_faculty, tenant.id).get("/api/v1/broadcast-notices/?view=received")
        assert "audienceSize" not in resp.data["data"][0]

    def test_sent_filters_by_from_to(self, tenant, sender, dept_cs):
        client = _authed_client(sender, tenant.id)
        published = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{published['id']}/publish/")

        future_from = (timezone.now() + timedelta(days=1)).date().isoformat()
        resp = client.get(f"/api/v1/broadcast-notices/?view=sent&from={future_from}")
        assert len(resp.data["data"]) == 0

        past_from = (timezone.now() - timedelta(days=1)).date().isoformat()
        resp2 = client.get(f"/api/v1/broadcast-notices/?view=sent&from={past_from}")
        assert len(resp2.data["data"]) == 1

    def test_sent_invalid_from_is_400(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        resp = client.get("/api/v1/broadcast-notices/?view=sent&from=not-a-date")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestBroadcastAck:
    def test_ack_by_audience_member_increments_count(self, tenant, sender, dept_cs, cs_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(
            client, audienceDeptIds=[str(dept_cs.id)], requiresAcknowledgement=True,
        ).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        resp = _authed_client(cs_faculty, tenant.id).post(f"/api/v1/broadcast-notices/{draft['id']}/ack/")
        assert resp.status_code == 200
        assert resp.data["data"]["ackCount"] == 1

    def test_ack_by_non_audience_forbidden(self, tenant, sender, dept_cs, civil_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(
            client, audienceDeptIds=[str(dept_cs.id)], requiresAcknowledgement=True,
        ).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        resp = _authed_client(civil_faculty, tenant.id).post(
            f"/api/v1/broadcast-notices/{draft['id']}/ack/",
        )
        assert resp.status_code == 403
        assert resp.data["error"]["code"] == "NOT_IN_AUDIENCE"

    def test_double_ack_conflict(self, tenant, sender, dept_cs, cs_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(
            client, audienceDeptIds=[str(dept_cs.id)], requiresAcknowledgement=True,
        ).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        faculty_client = _authed_client(cs_faculty, tenant.id)
        faculty_client.post(f"/api/v1/broadcast-notices/{draft['id']}/ack/")
        resp = faculty_client.post(f"/api/v1/broadcast-notices/{draft['id']}/ack/")
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "ALREADY_ACKNOWLEDGED"

    def test_ack_count_sender_only(self, tenant, sender, dept_cs, cs_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(
            client, audienceDeptIds=[str(dept_cs.id)], requiresAcknowledgement=True,
        ).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")
        _authed_client(cs_faculty, tenant.id).post(f"/api/v1/broadcast-notices/{draft['id']}/ack/")

        resp = client.get(f"/api/v1/broadcast-notices/{draft['id']}/ack-count/")
        assert resp.status_code == 200
        assert resp.data["data"]["ackCount"] == 1

        forbidden = _authed_client(cs_faculty, tenant.id).get(
            f"/api/v1/broadcast-notices/{draft['id']}/ack-count/",
        )
        assert forbidden.status_code == 403


@pytest.mark.django_db
class TestBroadcastImage:
    def _presign(self, client, broadcast_id, content_type="image/jpeg"):
        return client.post(
            "/api/v1/upload/broadcast-image-presign/",
            {
                "broadcastId": broadcast_id,
                "filename": "banner.jpg",
                "contentType": content_type,
                "fileSize": 1024,
            },
            format="json",
        )

    def test_presign_and_confirm(self, tenant, sender, mock_storage):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]

        presign_resp = self._presign(client, draft["id"])
        assert presign_resp.status_code == 200
        assert presign_resp.data["data"]["expiresIn"] == 900

        confirm_resp = client.post(f"/api/v1/broadcast-notices/{draft['id']}/image/")
        assert confirm_resp.status_code == 200
        assert confirm_resp.data["data"]["hasImage"] is True
        assert len(mock_storage["copied"]) == 1

        broadcast = BroadcastNotice.objects.get(id=draft["id"])
        assert broadcast.image_url is not None

    def test_presign_by_non_sender_forbidden(self, tenant, sender, non_broadcaster):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = self._presign(_authed_client(non_broadcaster, tenant.id), draft["id"])
        assert resp.status_code == 403

    def test_confirm_on_published_broadcast_rejected(self, tenant, sender, dept_cs):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        resp = client.post(f"/api/v1/broadcast-notices/{draft['id']}/image/")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "CANNOT_EDIT_PUBLISHED"

    def test_image_stream_sender_always_allowed(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        self._presign(client, draft["id"])
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/image/")

        resp = client.get(f"/api/v1/broadcast-notices/{draft['id']}/image/")
        assert resp.status_code == 200

    def test_image_stream_requires_audience_match(self, tenant, sender, dept_cs, dept_civil, cs_faculty, civil_faculty):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client, audienceDeptIds=[str(dept_cs.id)]).data["data"]
        self._presign(client, draft["id"])
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/image/")
        client.post(f"/api/v1/broadcast-notices/{draft['id']}/publish/")

        allowed = _authed_client(cs_faculty, tenant.id).get(
            f"/api/v1/broadcast-notices/{draft['id']}/image/",
        )
        assert allowed.status_code == 200

        denied = _authed_client(civil_faculty, tenant.id).get(
            f"/api/v1/broadcast-notices/{draft['id']}/image/",
        )
        assert denied.status_code == 403

    def test_image_stream_404_when_no_image(self, tenant, sender):
        client = _authed_client(sender, tenant.id)
        draft = _create_draft(client).data["data"]
        resp = client.get(f"/api/v1/broadcast-notices/{draft['id']}/image/")
        assert resp.status_code == 404
