import io

import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.common.enums import Language, OrgRoleLevel
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
def dept(tenant):
    return DepartmentFactory(tenant=tenant)


@pytest.fixture
def dean(tenant):
    return UserFactory(tenant=tenant, name="Dr. Kamal Sethi")


@pytest.fixture
def me(tenant, dept, dean):
    user = UserFactory(tenant=tenant, name="Prof. Asha Nair")
    TenantMembershipFactory(
        tenant=tenant, user=user, department=dept, role_level=OrgRoleLevel.MID,
        role_label="HoD", reports_to=dean, can_broadcast=False,
    )
    return user


@pytest.fixture(autouse=True)
def mock_storage(monkeypatch):
    calls = {"copied": [], "deleted": [], "presigned": []}

    def fake_presign(key, content_type, expires_in):
        calls["presigned"].append((key, content_type, expires_in))
        return f"https://s3.ap-south-1.amazonaws.com/bolo-profile-pics/{key}?X-Amz-Signature=fake"

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


@pytest.mark.django_db
class TestMe:
    def test_get_me(self, tenant, dept, dean, me):
        client = _authed_client(me, tenant.id)
        resp = client.get("/api/v1/me/")
        assert resp.status_code == 200
        data = resp.data["data"]
        assert data["id"] == str(me.id)
        assert data["name"] == "Prof. Asha Nair"
        assert data["tenantName"] == tenant.name
        assert data["roleLevel"] == OrgRoleLevel.MID
        assert data["roleLabel"] == "HoD"
        assert data["departmentId"] == str(dept.id)
        assert data["departmentName"] == dept.name
        assert data["reportsToId"] == str(dean.id)
        assert data["reportsToName"] == "Dr. Kamal Sethi"
        assert data["canBroadcast"] is False
        assert data["profilePicUrl"] is None

    def test_patch_me_updates_name_and_language(self, tenant, me):
        client = _authed_client(me, tenant.id)
        resp = client.patch(
            "/api/v1/me/", {"name": "Prof. Asha M. Nair", "preferredLang": "HI"}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"] == {"name": "Prof. Asha M. Nair", "preferredLang": "HI"}
        me.refresh_from_db()
        assert me.name == "Prof. Asha M. Nair"
        assert me.preferred_lang == Language.HI

    def test_patch_me_partial_update(self, tenant, me):
        client = _authed_client(me, tenant.id)
        resp = client.patch("/api/v1/me/", {"name": "Renamed"}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"] == {"name": "Renamed"}
        me.refresh_from_db()
        assert me.name == "Renamed"
        assert me.preferred_lang == Language.EN  # untouched


@pytest.mark.django_db
class TestProfilePictureUploadFlow:
    def test_presign_returns_upload_url(self, tenant, me, mock_storage):
        client = _authed_client(me, tenant.id)
        resp = client.post(
            "/api/v1/upload/profile-picture-presign/",
            {"contentType": "image/jpeg", "fileSize": 204800},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["uploadUrl"].startswith("https://")
        key, content_type, _ = mock_storage["presigned"][0]
        assert key == f"bolo-profile-pics/unconfirmed/{me.id}"
        assert content_type == "image/jpeg"

    def test_presign_rejects_oversized_file(self, tenant, me):
        client = _authed_client(me, tenant.id)
        resp = client.post(
            "/api/v1/upload/profile-picture-presign/",
            {"contentType": "image/jpeg", "fileSize": 6 * 1024 * 1024},
            format="json",
        )
        assert resp.status_code == 400

    def test_presign_rejects_bad_content_type(self, tenant, me):
        client = _authed_client(me, tenant.id)
        resp = client.post(
            "/api/v1/upload/profile-picture-presign/",
            {"contentType": "application/pdf", "fileSize": 1024},
            format="json",
        )
        assert resp.status_code == 400

    def test_confirm_sets_profile_pic_and_streaming_path(self, tenant, me, mock_storage):
        client = _authed_client(me, tenant.id)
        resp = client.patch("/api/v1/me/profile-picture/")
        assert resp.status_code == 200
        assert resp.data["data"]["profilePicUrl"] == f"/users/{me.id}/profile-picture/file"
        me.refresh_from_db()
        assert me.profile_pic_url == f"bolo-profile-pics/{me.id}"
        assert mock_storage["copied"] == [
            (f"bolo-profile-pics/unconfirmed/{me.id}", f"bolo-profile-pics/{me.id}"),
        ]
        assert mock_storage["deleted"] == [f"bolo-profile-pics/unconfirmed/{me.id}"]

    def test_reupload_overwrites_same_confirmed_key(self, tenant, me, mock_storage):
        client = _authed_client(me, tenant.id)
        client.patch("/api/v1/me/profile-picture/")
        client.patch("/api/v1/me/profile-picture/")
        me.refresh_from_db()
        assert me.profile_pic_url == f"bolo-profile-pics/{me.id}"
        assert len(mock_storage["copied"]) == 2

    def test_delete_removes_picture(self, tenant, me, mock_storage):
        client = _authed_client(me, tenant.id)
        client.patch("/api/v1/me/profile-picture/")

        resp = client.delete("/api/v1/me/profile-picture/")
        assert resp.status_code == 200
        me.refresh_from_db()
        assert me.profile_pic_url is None
        assert mock_storage["deleted"][-1] == f"bolo-profile-pics/{me.id}"

    def test_delete_without_picture_set_is_404(self, tenant, me):
        client = _authed_client(me, tenant.id)
        resp = client.delete("/api/v1/me/profile-picture/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestAnyMemberProfilePicture:
    def test_metadata_for_tenant_member(self, tenant, me):
        other = UserFactory(tenant=tenant)
        client = _authed_client(other, tenant.id)
        resp = client.get(f"/api/v1/users/{me.id}/profile-picture/")
        assert resp.status_code == 200
        assert resp.data["data"] == {"userId": str(me.id), "profilePicUrl": None}

    def test_metadata_404_for_cross_tenant_user(self, tenant, me):
        other_tenant_user = UserFactory()
        client = _authed_client(other_tenant_user, other_tenant_user.tenant_id)
        resp = client.get(f"/api/v1/users/{me.id}/profile-picture/")
        assert resp.status_code == 404

    def test_streams_file_content(self, tenant, me, mock_storage):
        client = _authed_client(me, tenant.id)
        client.patch("/api/v1/me/profile-picture/")

        other = UserFactory(tenant=tenant)
        other_client = _authed_client(other, tenant.id)
        resp = other_client.get(f"/api/v1/users/{me.id}/profile-picture/file/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "image/jpeg"
        assert b"".join(resp.streaming_content) == b"fake image bytes"

    def test_file_404_when_no_picture_set(self, tenant, me):
        other = UserFactory(tenant=tenant)
        client = _authed_client(other, tenant.id)
        resp = client.get(f"/api/v1/users/{me.id}/profile-picture/file/")
        assert resp.status_code == 404
