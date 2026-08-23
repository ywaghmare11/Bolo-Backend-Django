import io

import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.tasks.models import VoiceRecording
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


@pytest.fixture(autouse=True)
def mock_storage(monkeypatch):
    calls = {"copied": [], "deleted": [], "put_presigned": 0, "streamed": []}

    def fake_presign_put(key, content_type, expires_in):
        calls["put_presigned"] += 1
        return f"https://s3.ap-south-1.amazonaws.com/bolo-voice/{key}?X-Amz-Signature=fake"

    def fake_copy(source_key, dest_key):
        calls["copied"].append((source_key, dest_key))

    def fake_delete(key):
        calls["deleted"].append(key)

    def fake_get_object_stream(key):
        calls["streamed"].append(key)
        return io.BytesIO(b"fake audio bytes"), "audio/webm"

    monkeypatch.setattr("apps.common.storage.generate_presigned_put_url", fake_presign_put)
    monkeypatch.setattr("apps.common.storage.copy_object", fake_copy)
    monkeypatch.setattr("apps.common.storage.delete_object", fake_delete)
    monkeypatch.setattr("apps.common.storage.get_object_stream", fake_get_object_stream)
    return calls


def _create_task(client, assignee_id, with_voice=False):
    body = {
        "title": "Submit NAAC report",
        "assigneeId": str(assignee_id),
        "dueDate": "2026-08-20T00:00:00Z",
    }
    if with_voice:
        body["voiceRecording"] = {
            "rawTranscript": "Rohit ko NAAC report submit karna hai next month tak",
            "language": "hi-en",
            "durationSecs": 12,
            "confidenceScore": 0.87,
        }
    return client.post("/api/v1/tasks/", body, format="json")


@pytest.mark.django_db
class TestVoiceRecordingCreate:
    def test_create_with_voice_recording_saved_atomically(self, tenant, assigner, assignee):
        resp = _create_task(_authed_client(assigner, tenant.id), assignee.id, with_voice=True)
        task_id = resp.data["data"]["id"]
        assert VoiceRecording.objects.filter(task_id=task_id).exists()

        detail = _authed_client(assigner, tenant.id).get(f"/api/v1/tasks/{task_id}/")
        vr = detail.data["data"]["voiceRecording"]
        assert vr["rawTranscript"] == "Rohit ko NAAC report submit karna hai next month tak"
        assert vr["language"] == "hi-en"
        assert vr["hasAudio"] is False
        assert vr["carryVoiceRecording"] is False

    def test_create_without_voice_recording_leaves_it_null(self, tenant, assigner, assignee):
        resp = _create_task(_authed_client(assigner, tenant.id), assignee.id, with_voice=False)
        task_id = resp.data["data"]["id"]
        assert not VoiceRecording.objects.filter(task_id=task_id).exists()

        detail = _authed_client(assigner, tenant.id).get(f"/api/v1/tasks/{task_id}/")
        assert detail.data["data"]["voiceRecording"] is None


@pytest.mark.django_db
class TestVoicePresign:
    def test_presign_returns_fixed_voice_webm_key(self, tenant, assigner, assignee, mock_storage):
        resp = _create_task(_authed_client(assigner, tenant.id), assignee.id, with_voice=True)
        task_id = resp.data["data"]["id"]

        client = _authed_client(assigner, tenant.id)
        presign_resp = client.post(
            "/api/v1/upload/voice-presign/",
            {"taskId": task_id, "filename": "voice.webm", "contentType": "audio/webm", "durationSecs": 12},
            format="json",
        )
        assert presign_resp.status_code == 200
        assert presign_resp.data["data"]["expiresIn"] == 900
        assert presign_resp.data["data"]["s3Key"] == f"unconfirmed/{tenant.id}/{task_id}/voice.webm"
        assert mock_storage["put_presigned"] == 1

    def test_presign_without_transcript_row_is_404(self, tenant, assigner, assignee):
        resp = _create_task(_authed_client(assigner, tenant.id), assignee.id, with_voice=False)
        task_id = resp.data["data"]["id"]

        presign_resp = _authed_client(assigner, tenant.id).post(
            "/api/v1/upload/voice-presign/",
            {"taskId": task_id, "filename": "voice.webm", "contentType": "audio/webm"},
            format="json",
        )
        assert presign_resp.status_code == 404

    def test_presign_by_outsider_forbidden(self, tenant, outsider, assigner, assignee):
        resp = _create_task(_authed_client(assigner, tenant.id), assignee.id, with_voice=True)
        task_id = resp.data["data"]["id"]

        presign_resp = _authed_client(outsider, tenant.id).post(
            "/api/v1/upload/voice-presign/",
            {"taskId": task_id, "filename": "voice.webm", "contentType": "audio/webm"},
            format="json",
        )
        assert presign_resp.status_code == 403


@pytest.mark.django_db
class TestVoiceAudioConfirmAndPlayback:
    def _create_and_presign(self, tenant, assigner, assignee):
        client = _authed_client(assigner, tenant.id)
        task_id = _create_task(client, assignee.id, with_voice=True).data["data"]["id"]
        s3_key = client.post(
            "/api/v1/upload/voice-presign/",
            {"taskId": task_id, "filename": "voice.webm", "contentType": "audio/webm"},
            format="json",
        ).data["data"]["s3Key"]
        return client, task_id, s3_key

    def test_confirm_sets_audio_url_and_is_idempotent(self, tenant, assigner, assignee, mock_storage):
        client, task_id, s3_key = self._create_and_presign(tenant, assigner, assignee)

        resp = client.patch(
            f"/api/v1/tasks/{task_id}/voice-recording/audio/", {"s3Key": s3_key}, format="json",
        )
        assert resp.status_code == 200
        assert resp.data["data"]["hasAudio"] is True
        assert len(mock_storage["copied"]) == 1
        assert len(mock_storage["deleted"]) == 1

        # Retrying the same confirm must not re-issue CopyObject/DeleteObject --
        # the source is already gone after the first call.
        resp2 = client.patch(
            f"/api/v1/tasks/{task_id}/voice-recording/audio/", {"s3Key": s3_key}, format="json",
        )
        assert resp2.status_code == 200
        assert len(mock_storage["copied"]) == 1
        assert len(mock_storage["deleted"]) == 1

    def test_confirm_with_mismatched_key_rejected(self, tenant, assigner, assignee):
        client, task_id, _ = self._create_and_presign(tenant, assigner, assignee)
        resp = client.patch(
            f"/api/v1/tasks/{task_id}/voice-recording/audio/",
            {"s3Key": "unconfirmed/someone-elses-key/voice.webm"},
            format="json",
        )
        assert resp.status_code == 400

    def test_audio_before_confirm_is_404(self, tenant, assigner, assignee):
        client, task_id, _ = self._create_and_presign(tenant, assigner, assignee)
        resp = client.get(f"/api/v1/tasks/{task_id}/voice-recording/audio/")
        assert resp.status_code == 404

    def test_audio_streams_bytes_after_confirm(self, tenant, assigner, assignee, mock_storage):
        client, task_id, s3_key = self._create_and_presign(tenant, assigner, assignee)
        client.patch(f"/api/v1/tasks/{task_id}/voice-recording/audio/", {"s3Key": s3_key}, format="json")

        resp = client.get(f"/api/v1/tasks/{task_id}/voice-recording/audio/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "audio/webm"
        assert b"".join(resp.streaming_content) == b"fake audio bytes"

    def test_audio_re_checks_access_on_every_request(self, tenant, assigner, assignee, outsider, mock_storage):
        """Never a pre-signed URL -- a non-participant is rejected fresh on this
        request, not just when the (nonexistent) URL was originally minted."""
        client, task_id, s3_key = self._create_and_presign(tenant, assigner, assignee)
        client.patch(f"/api/v1/tasks/{task_id}/voice-recording/audio/", {"s3Key": s3_key}, format="json")

        outsider_client = _authed_client(outsider, tenant.id)
        resp = outsider_client.get(f"/api/v1/tasks/{task_id}/voice-recording/audio/")
        assert resp.status_code == 403
        assert mock_storage["streamed"] == []


@pytest.mark.django_db
class TestVoiceRecordingTranscript:
    def test_get_transcript(self, tenant, assigner, assignee):
        task_id = _create_task(
            _authed_client(assigner, tenant.id), assignee.id, with_voice=True,
        ).data["data"]["id"]

        resp = _authed_client(assignee, tenant.id).get(f"/api/v1/tasks/{task_id}/voice-recording/")
        assert resp.status_code == 200
        assert resp.data["data"]["rawTranscript"] == "Rohit ko NAAC report submit karna hai next month tak"
        assert resp.data["data"]["confidenceScore"] == 0.87

    def test_get_transcript_missing_is_404(self, tenant, assigner, assignee):
        task_id = _create_task(
            _authed_client(assigner, tenant.id), assignee.id, with_voice=False,
        ).data["data"]["id"]

        resp = _authed_client(assigner, tenant.id).get(f"/api/v1/tasks/{task_id}/voice-recording/")
        assert resp.status_code == 404

    def test_outsider_cannot_get_transcript(self, tenant, outsider, assigner, assignee):
        task_id = _create_task(
            _authed_client(assigner, tenant.id), assignee.id, with_voice=True,
        ).data["data"]["id"]

        resp = _authed_client(outsider, tenant.id).get(f"/api/v1/tasks/{task_id}/voice-recording/")
        assert resp.status_code == 403
