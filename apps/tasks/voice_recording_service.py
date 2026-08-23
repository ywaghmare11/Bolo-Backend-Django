from apps.common import storage
from apps.common.exceptions import ForbiddenError, NotFoundError, ValidationError
from apps.tasks.repositories import TaskRepository, VoiceRecordingRepository

PRESIGN_EXPIRES_IN_SECONDS = 900


def _unconfirmed_key(tenant_id, task_id) -> str:
    return f"unconfirmed/{tenant_id}/{task_id}/voice.webm"


def _confirmed_key(tenant_id, task_id) -> str:
    return f"{tenant_id}/{task_id}/voice.webm"


def _get_accessible_task(tenant_id, task_id, user):
    task = TaskRepository.get_by_id(task_id, tenant_id)
    if user.id not in (task.assigner_id, task.assignee_id):
        raise ForbiddenError("You do not have access to this task")
    return task


class VoiceRecordingService:
    @staticmethod
    def presign_audio_upload(user, tenant_id, task_id, filename, content_type, duration_secs):
        """`filename`/`duration_secs` are accepted per the documented request shape but
        not used to build the key -- the S3 object is always named voice.webm (one
        recording per task), matching api-spec.md §6's literal S3 path examples."""
        _get_accessible_task(tenant_id, task_id, user)
        # 400s if POST /tasks never created a transcript row for this task.
        VoiceRecordingRepository.get_by_task_id(task_id, tenant_id)

        unconfirmed_key = _unconfirmed_key(tenant_id, task_id)
        upload_url = storage.generate_presigned_put_url(
            unconfirmed_key, content_type, PRESIGN_EXPIRES_IN_SECONDS,
        )
        return {
            "uploadUrl": upload_url,
            "s3Key": unconfirmed_key,
            "expiresIn": PRESIGN_EXPIRES_IN_SECONDS,
        }

    @staticmethod
    def confirm_audio(user, tenant_id, task_id, s3_key):
        _get_accessible_task(tenant_id, task_id, user)
        voice_recording = VoiceRecordingRepository.get_by_task_id(task_id, tenant_id)

        # Never trust the client-supplied key as the literal S3 source -- recompute
        # the expected pending-upload key server-side and reject a mismatch, rather
        # than blindly copying from whatever key the caller names (the same class of
        # issue as the path-traversal fix in apps/evidence/services.py).
        expected_key = _unconfirmed_key(tenant_id, task_id)
        if s3_key != expected_key:
            raise ValidationError("s3Key does not match the pending upload for this task")

        confirmed_key = _confirmed_key(tenant_id, task_id)
        # Idempotent: a retried confirm is a pure no-op once audio_url is already
        # set, rather than re-issuing CopyObject against a source S3 already deleted
        # on the first call (api-spec.md §6's documented "safe to retry" guarantee).
        if voice_recording.audio_url != confirmed_key:
            storage.copy_object(expected_key, confirmed_key)
            storage.delete_object(expected_key)
            voice_recording = VoiceRecordingRepository.update_audio_url(voice_recording, confirmed_key)
        return voice_recording

    @staticmethod
    def get_transcript(user, tenant_id, task_id):
        _get_accessible_task(tenant_id, task_id, user)
        return VoiceRecordingRepository.get_by_task_id(task_id, tenant_id)

    @staticmethod
    def get_audio_stream(user, tenant_id, task_id):
        """Streams the object server-side instead of minting a pre-signed URL --
        a pre-signed URL's signature is its entire authorization, so returning
        one in JSON makes it a copyable credential valid for anyone for its
        full TTL, session or not. Re-checks assigner/assignee access on every
        request instead. Same pattern as Evidence/Broadcast image."""
        _get_accessible_task(tenant_id, task_id, user)
        voice_recording = VoiceRecordingRepository.get_by_task_id(task_id, tenant_id)
        if not voice_recording.audio_url:
            raise NotFoundError("Audio", task_id)

        body, content_type = storage.get_object_stream(voice_recording.audio_url)
        return body, content_type or "audio/webm"
