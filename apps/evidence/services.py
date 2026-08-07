import os
import uuid

from django.core.cache import cache

from apps.common import storage
from apps.common.enums import NotificationType
from apps.common.exceptions import ForbiddenError, ValidationError
from apps.evidence.repositories import EvidenceRepository
from apps.evidence.serializers import ALLOWED_CONTENT_TYPES
from apps.notifications.services import dispatch_notification
from apps.tasks.repositories import TaskRepository

# Matches the S3 lifecycle rule that deletes anything under unconfirmed/ after 24h
# (docs/api/api-spec.md §5) -- an abandoned presign shouldn't be confirmable forever.
UNCONFIRMED_TTL_SECONDS = 60 * 60 * 24
PRESIGN_EXPIRES_IN_SECONDS = 900


def _cache_key(evidence_id) -> str:
    return f"evidence_presign:{evidence_id}"


def _unconfirmed_key(tenant_id, task_id, evidence_id, filename) -> str:
    return f"unconfirmed/{tenant_id}/{task_id}/{evidence_id}/{filename}"


def _confirmed_key(tenant_id, task_id, evidence_id, filename) -> str:
    return f"{tenant_id}/{task_id}/{evidence_id}/{filename}"


def _get_accessible_task(tenant_id, task_id, user):
    task = TaskRepository.get_by_id(task_id, tenant_id)
    if user.id not in (task.assigner_id, task.assignee_id):
        raise ForbiddenError("You do not have access to this task")
    return task


class EvidenceService:
    @staticmethod
    def presign_upload(user, tenant_id, task_id, filename, content_type, file_size):
        _get_accessible_task(tenant_id, task_id, user)
        # Strip any directory components -- the filename becomes part of the S3 key
        # below, so a value like "../../other-tenant/x" must not be able to escape
        # the intended prefix.
        filename = os.path.basename(filename)

        evidence_id = uuid.uuid4()
        unconfirmed_key = _unconfirmed_key(tenant_id, task_id, evidence_id, filename)
        upload_url = storage.generate_presigned_put_url(
            unconfirmed_key, content_type, PRESIGN_EXPIRES_IN_SECONDS,
        )

        # No DB row yet -- api-spec.md §5 documents the Evidence row as created only
        # at confirm time. This cache entry is the only record of the pending upload
        # between presign and confirm; its own TTL doubles as the "evidenceId not
        # found / S3 upload not confirmed" error condition below once it expires.
        cache.set(
            _cache_key(evidence_id),
            {
                "task_id": str(task_id),
                "tenant_id": str(tenant_id),
                "filename": filename,
                "content_type": content_type,
                "file_size": file_size,
                "unconfirmed_key": unconfirmed_key,
            },
            timeout=UNCONFIRMED_TTL_SECONDS,
        )
        return {
            "uploadUrl": upload_url,
            "evidenceId": str(evidence_id),
            "expiresIn": PRESIGN_EXPIRES_IN_SECONDS,
        }

    @staticmethod
    def confirm_evidence(user, tenant_id, task_id, evidence_id, caption):
        task = _get_accessible_task(tenant_id, task_id, user)

        pending = cache.get(_cache_key(evidence_id))
        if (
            pending is None
            or pending["task_id"] != str(task_id)
            or pending["tenant_id"] != str(tenant_id)
        ):
            raise ValidationError(
                "evidenceId not found or S3 upload not confirmed", code="EVIDENCE_NOT_PENDING",
            )

        confirmed_key = _confirmed_key(tenant_id, task_id, evidence_id, pending["filename"])
        storage.copy_object(pending["unconfirmed_key"], confirmed_key)
        storage.delete_object(pending["unconfirmed_key"])

        evidence = EvidenceRepository.create(
            id=evidence_id,
            task_id=task_id,
            uploader=user,
            file_url=confirmed_key,
            file_name=pending["filename"],
            file_size=pending["file_size"],
            file_type=ALLOWED_CONTENT_TYPES[pending["content_type"]],
            caption=caption or None,
        )
        cache.delete(_cache_key(evidence_id))

        other_party = task.assignee if user.id == task.assigner_id else task.assigner
        dispatch_notification(
            tenant_id=tenant_id,
            recipient=other_party,
            type_=NotificationType.EVIDENCE_ATTACHED,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} attached evidence to: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        return evidence

    @staticmethod
    def list_evidence(user, tenant_id, task_id):
        _get_accessible_task(tenant_id, task_id, user)
        return EvidenceRepository.list_for_task(task_id)

    @staticmethod
    def get_evidence_file(user, tenant_id, task_id, evidence_id):
        _get_accessible_task(tenant_id, task_id, user)
        evidence = EvidenceRepository.get_by_id(evidence_id, task_id)
        body, content_type = storage.get_object_stream(evidence.file_url)
        return body, content_type or "application/octet-stream", evidence.file_name

    @staticmethod
    def delete_evidence(user, tenant_id, task_id, evidence_id):
        _get_accessible_task(tenant_id, task_id, user)
        evidence = EvidenceRepository.get_by_id(evidence_id, task_id)
        if evidence.uploader_id != user.id:
            raise ForbiddenError("You are not the uploader of this evidence")
        storage.delete_object(evidence.file_url)
        EvidenceRepository.delete(evidence)
