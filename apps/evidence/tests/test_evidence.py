import io

import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.auth.tokens import issue_access_token
from apps.evidence.models import Evidence
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
def assigner(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def assignee(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def outsider(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def task(tenant, assigner, assignee):
    client = _authed_client(assigner, tenant.id)
    resp = client.post(
        "/api/v1/tasks/",
        {"title": "Submit NAAC report", "assigneeId": str(assignee.id), "dueDate": "2026-08-20T00:00:00Z"},
        format="json",
    )
    return resp.data["data"]["id"]


@pytest.fixture(autouse=True)
def mock_storage(monkeypatch):
    """No real S3 in this dev environment -- every test mocks the thin wrapper in
    apps.common.storage rather than hitting AWS."""
    calls = {"copied": [], "deleted": [], "presigned": []}

    def fake_presign(key, content_type, expires_in):
        calls["presigned"].append((key, content_type, expires_in))
        return f"https://s3.ap-south-1.amazonaws.com/bolo-evidence/{key}?X-Amz-Signature=fake"

    def fake_copy(source_key, dest_key):
        calls["copied"].append((source_key, dest_key))

    def fake_delete(key):
        calls["deleted"].append(key)

    def fake_get_object_stream(key):
        return io.BytesIO(b"fake file bytes"), "application/pdf"

    monkeypatch.setattr("apps.common.storage.generate_presigned_put_url", fake_presign)
    monkeypatch.setattr("apps.common.storage.copy_object", fake_copy)
    monkeypatch.setattr("apps.common.storage.delete_object", fake_delete)
    monkeypatch.setattr("apps.common.storage.get_object_stream", fake_get_object_stream)
    return calls


def _presign(client, task_id, filename="report.pdf", content_type="application/pdf", file_size=1024):
    return client.post(
        "/api/v1/upload/presign/",
        {"taskId": task_id, "filename": filename, "contentType": content_type, "fileSize": file_size},
        format="json",
    )


def _confirm(client, task_id, evidence_id, caption=""):
    return client.post(
        f"/api/v1/tasks/{task_id}/evidence/", {"evidenceId": evidence_id, "caption": caption}, format="json",
    )


@pytest.mark.django_db
class TestEvidencePresign:
    def test_presign_by_assignee_returns_upload_url(self, tenant, assignee, task, mock_storage):
        client = _authed_client(assignee, tenant.id)
        resp = _presign(client, task)
        assert resp.status_code == 200
        assert resp.data["data"]["expiresIn"] == 900
        assert "evidenceId" in resp.data["data"]
        assert resp.data["data"]["uploadUrl"].startswith("https://")

    def test_presign_by_outsider_forbidden(self, tenant, outsider, task):
        resp = _presign(_authed_client(outsider, tenant.id), task)
        assert resp.status_code == 403

    def test_presign_disallowed_content_type_rejected(self, tenant, assigner, task):
        resp = _presign(_authed_client(assigner, tenant.id), task, content_type="application/zip")
        assert resp.status_code == 400

    def test_presign_sanitizes_path_traversal_in_filename(self, tenant, assigner, task, mock_storage):
        _presign(_authed_client(assigner, tenant.id), task, filename="../../etc/passwd")
        key, _, _ = mock_storage["presigned"][0]
        assert ".." not in key
        assert key.endswith("/passwd")


@pytest.mark.django_db
class TestEvidenceConfirm:
    def test_confirm_creates_row_copies_and_deletes_unconfirmed(
        self, tenant, assigner, assignee, task, mock_storage,
    ):
        assigner_client = _authed_client(assigner, tenant.id)
        presign_resp = _presign(assigner_client, task)
        evidence_id = presign_resp.data["data"]["evidenceId"]

        resp = _confirm(assigner_client, task, evidence_id, caption="Criterion A1 data")
        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["id"] == evidence_id
        assert data["fileType"] == "PDF"
        assert data["fileUrl"] == f"/tasks/{task}/evidence/{evidence_id}/file"
        assert Evidence.objects.filter(id=evidence_id).exists()
        assert len(mock_storage["copied"]) == 1
        assert len(mock_storage["deleted"]) == 1
        assert Notification.objects.filter(type="EVIDENCE_ATTACHED", recipient=assignee).exists()

    def test_confirm_unknown_evidence_id_rejected(self, tenant, assigner, task):
        client = _authed_client(assigner, tenant.id)
        resp = _confirm(client, task, "00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "EVIDENCE_NOT_PENDING"

    def test_confirm_under_wrong_task_rejected(self, tenant, assigner, assignee, task):
        other_task_resp = _authed_client(assigner, tenant.id).post(
            "/api/v1/tasks/",
            {"title": "Other task", "assigneeId": str(assignee.id), "dueDate": "2026-08-21T00:00:00Z"},
            format="json",
        )
        other_task_id = other_task_resp.data["data"]["id"]

        client = _authed_client(assigner, tenant.id)
        presign_resp = _presign(client, task)
        evidence_id = presign_resp.data["data"]["evidenceId"]

        resp = _confirm(client, other_task_id, evidence_id)
        assert resp.status_code == 400
        assert resp.data["error"]["code"] == "EVIDENCE_NOT_PENDING"


@pytest.mark.django_db
class TestEvidenceListFileDelete:
    def _upload(self, tenant, uploader, task):
        client = _authed_client(uploader, tenant.id)
        evidence_id = _presign(client, task).data["data"]["evidenceId"]
        _confirm(client, task, evidence_id)
        return evidence_id

    def test_list_returns_app_relative_file_url(self, tenant, assigner, assignee, task):
        evidence_id = self._upload(tenant, assigner, task)
        resp = _authed_client(assignee, tenant.id).get(f"/api/v1/tasks/{task}/evidence/")
        assert resp.status_code == 200
        assert resp.data["data"][0]["fileUrl"] == f"/tasks/{task}/evidence/{evidence_id}/file"

    def test_outsider_cannot_list(self, tenant, outsider, assigner, task):
        self._upload(tenant, assigner, task)
        resp = _authed_client(outsider, tenant.id).get(f"/api/v1/tasks/{task}/evidence/")
        assert resp.status_code == 403

    def test_file_endpoint_streams_bytes(self, tenant, assigner, assignee, task):
        evidence_id = self._upload(tenant, assigner, task)
        resp = _authed_client(assignee, tenant.id).get(f"/api/v1/tasks/{task}/evidence/{evidence_id}/file/")
        assert resp.status_code == 200
        assert b"".join(resp.streaming_content) == b"fake file bytes"

    def test_uploader_can_delete(self, tenant, assigner, task, mock_storage):
        evidence_id = self._upload(tenant, assigner, task)
        deletes_before = len(mock_storage["deleted"])  # confirm already deleted the unconfirmed object

        resp = _authed_client(assigner, tenant.id).delete(f"/api/v1/tasks/{task}/evidence/{evidence_id}/")
        assert resp.status_code == 200
        assert not Evidence.objects.filter(id=evidence_id).exists()
        assert len(mock_storage["deleted"]) == deletes_before + 1

    def test_non_uploader_cannot_delete(self, tenant, assigner, assignee, task):
        """assignee is a party to the task but not the uploader -- narrowed
        upstream 2026-08-03 from uploader-or-assigner to uploader-only."""
        evidence_id = self._upload(tenant, assigner, task)
        resp = _authed_client(assignee, tenant.id).delete(f"/api/v1/tasks/{task}/evidence/{evidence_id}/")
        assert resp.status_code == 403
        assert Evidence.objects.filter(id=evidence_id).exists()


@pytest.mark.django_db
class TestEvidenceAuditTrail:
    def test_confirm_writes_document_uploaded_without_file_name(self, tenant, assigner, task):
        client = _authed_client(assigner, tenant.id)
        evidence_id = _presign(client, task).data["data"]["evidenceId"]
        _confirm(client, task, evidence_id, caption="Criterion A1 data")

        log = AuditLog.objects.get(entity_type="DOCUMENT", entity_id=evidence_id)
        assert log.action == "DOCUMENT_UPLOADED"
        assert log.after == {"file_type": "PDF"}

    def test_delete_writes_document_deleted(self, tenant, assigner, task):
        client = _authed_client(assigner, tenant.id)
        evidence_id = _presign(client, task).data["data"]["evidenceId"]
        _confirm(client, task, evidence_id)

        client.delete(f"/api/v1/tasks/{task}/evidence/{evidence_id}/")

        log = AuditLog.objects.get(entity_type="DOCUMENT", entity_id=evidence_id, action="DOCUMENT_DELETED")
        assert log.after is None
