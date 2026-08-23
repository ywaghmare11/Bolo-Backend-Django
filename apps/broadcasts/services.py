from datetime import timedelta

import bleach
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags

from apps.broadcasts.repositories import BroadcastRepository
from apps.broadcasts.tasks import broadcast_fanout_task
from apps.common import storage
from apps.common.enums import BroadcastStatus
from apps.common.exceptions import AppError, ForbiddenError, NotFoundError, ValidationError
from apps.tenants.repositories import MembershipRepository

BROADCAST_TEXT_MAX_LENGTH = 200
PRESIGN_EXPIRES_IN_SECONDS = 900
# 5MB placeholder cap -- no dedicated PRD limit, same as profile pictures (api-spec.md §10).
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024

# TipTap's basic mark set -- mirrors upstream's own in-repo safelist sanitizer
# (utils/htmlSanitize.ts) in spirit, implemented with bleach per guidelines.md's
# Security section, which names bleach explicitly for this.
ALLOWED_HTML_TAGS = [
    "p", "br", "strong", "b", "em", "i", "u", "s",
    "ul", "ol", "li", "h1", "h2", "h3", "blockquote", "a",
]
ALLOWED_HTML_ATTRS = {"a": ["href"]}


def _sanitize_html(message_html: str) -> str:
    return bleach.clean(message_html, tags=ALLOWED_HTML_TAGS, attributes=ALLOWED_HTML_ATTRS, strip=True)


def _validate_text_length(message_html: str) -> None:
    visible_text = strip_tags(message_html).strip()
    if len(visible_text) > BROADCAST_TEXT_MAX_LENGTH:
        raise ValidationError(
            f"Message text exceeds the {BROADCAST_TEXT_MAX_LENGTH}-character limit",
        )


def _validate_dept_ids(tenant_id, dept_ids) -> None:
    if not BroadcastRepository.department_ids_belong_to_tenant(tenant_id, dept_ids):
        raise ValidationError(
            "One or more departments do not belong to your tenant", code="INVALID_DEPARTMENT",
        )


def _require_can_broadcast(user):
    membership = MembershipRepository.get_profile_for_user(user.id)
    if not membership.can_broadcast:
        raise AppError(
            "Your account does not have broadcast permission", 403, "BROADCAST_NOT_PERMITTED",
        )
    return membership


def _require_sender(broadcast, user):
    if broadcast.sender_id != user.id:
        raise ForbiddenError("You are not the sender of this broadcast")


def _is_expired(broadcast) -> bool:
    return broadcast.expires_at is not None and broadcast.expires_at <= timezone.now()


def _caller_matches_audience(broadcast, dept_id, role_level) -> bool:
    dept_ids = {d.department_id for d in broadcast.audience_depts.all()}
    role_levels = {r.role_level for r in broadcast.audience_role_levels.all()}
    dept_ok = not dept_ids or dept_id in dept_ids
    role_ok = not role_levels or role_level in role_levels
    return dept_ok and role_ok


class BroadcastService:
    @staticmethod
    def create_draft(
        user, tenant_id, message_json, message_html,
        audience_dept_ids, audience_role_levels, requires_acknowledgement,
    ):
        _require_can_broadcast(user)
        message_html = _sanitize_html(message_html)
        _validate_text_length(message_html)
        _validate_dept_ids(tenant_id, audience_dept_ids)

        with transaction.atomic():
            broadcast = BroadcastRepository.create(
                tenant_id=tenant_id,
                sender=user,
                message_json=message_json,
                message_html=message_html,
                requires_acknowledgement=requires_acknowledgement,
            )
            BroadcastRepository.set_audience(broadcast, audience_dept_ids, audience_role_levels)
        return broadcast

    @staticmethod
    def list_broadcasts(user, tenant_id, view, from_date=None, to_date=None):
        if view not in (None, "received", "sent"):
            raise ValidationError("view must be 'received' or 'sent'")
        if view == "sent":
            return BroadcastRepository.list_sent(tenant_id, user.id, from_date, to_date), False

        membership = MembershipRepository.get_profile_for_user(user.id)
        qs = BroadcastRepository.list_received(
            tenant_id, user.id, membership.department_id, membership.role_level,
        )
        return qs, True

    @staticmethod
    def attach_audience_size(tenant_id, broadcasts):
        return BroadcastRepository.attach_audience_size(tenant_id, broadcasts)

    @staticmethod
    def publish(user, tenant_id, broadcast_id):
        _require_can_broadcast(user)
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)

        dept_ids = [d.department_id for d in broadcast.audience_depts.all()]
        role_levels = [r.role_level for r in broadcast.audience_role_levels.all()]
        # W110 (2026-08-23): both empty is now a valid, explicit "Entire Institution"
        # audience, not a rejected DRAFT_MISSING_FIELDS -- there was previously no way
        # to reach 100% of a tenant (one role level misses other roles, every
        # department excludes members with none assigned). resolve_audience_member_user_ids
        # and _caller_matches_audience already treat "no restriction on this dimension"
        # as "everyone matches" with no filter -- this publish-time gate was the only
        # place still blocking it.

        broadcast.status = BroadcastStatus.PUBLISHED
        broadcast.expires_at = timezone.now() + timedelta(hours=24)
        broadcast.save(update_fields=["status", "expires_at", "updated_at"])

        recipient_ids = BroadcastRepository.resolve_audience_member_user_ids(
            tenant_id, dept_ids, role_levels,
        )
        broadcast_fanout_task.delay(str(broadcast.id), [str(i) for i in recipient_ids])
        return broadcast

    @staticmethod
    def update_broadcast(user, tenant_id, broadcast_id, fields: dict):
        if not fields:
            raise ValidationError("At least one field must be provided")
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)

        was_published = broadcast.status == BroadcastStatus.PUBLISHED
        if was_published and _is_expired(broadcast):
            raise ValidationError("Cannot edit an expired broadcast", code="CANNOT_EDIT_EXPIRED")

        old_dept_ids = {d.department_id for d in broadcast.audience_depts.all()}
        old_role_levels = {r.role_level for r in broadcast.audience_role_levels.all()}

        dept_ids = fields.pop("audience_dept_ids", None)
        role_levels = fields.pop("audience_role_levels", None)

        if "image_url" in fields:
            if fields["image_url"] is not None:
                raise ValidationError("imageUrl can only be cleared by sending null")
            if broadcast.image_url:
                storage.delete_object(broadcast.image_url)

        if "message_html" in fields:
            fields["message_html"] = _sanitize_html(fields["message_html"])
            _validate_text_length(fields["message_html"])

        if dept_ids is not None:
            _validate_dept_ids(tenant_id, dept_ids)

        with transaction.atomic():
            BroadcastRepository.update(broadcast, **fields)
            if dept_ids is not None or role_levels is not None:
                BroadcastRepository.set_audience(
                    broadcast,
                    dept_ids if dept_ids is not None else list(old_dept_ids),
                    role_levels if role_levels is not None else list(old_role_levels),
                )

        if was_published and (dept_ids is not None or role_levels is not None):
            new_dept_ids = dept_ids if dept_ids is not None else list(old_dept_ids)
            new_role_levels = role_levels if role_levels is not None else list(old_role_levels)
            old_recipients = BroadcastRepository.resolve_audience_member_user_ids(
                tenant_id, list(old_dept_ids), list(old_role_levels),
            )
            new_recipients = BroadcastRepository.resolve_audience_member_user_ids(
                tenant_id, new_dept_ids, new_role_levels,
            )
            newly_added = new_recipients - old_recipients
            if newly_added:
                broadcast_fanout_task.delay(str(broadcast.id), [str(i) for i in newly_added])

        return broadcast

    @staticmethod
    def delete_broadcast(user, tenant_id, broadcast_id):
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)
        if broadcast.image_url:
            storage.delete_object(broadcast.image_url)
        BroadcastRepository.delete(broadcast)

    @staticmethod
    def acknowledge(user, tenant_id, broadcast_id):
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        if broadcast.status != BroadcastStatus.PUBLISHED or _is_expired(broadcast):
            raise ValidationError("This broadcast is not open for acknowledgement")
        if not broadcast.requires_acknowledgement:
            raise ValidationError("This broadcast does not require acknowledgement")

        membership = MembershipRepository.get_profile_for_user(user.id)
        if not _caller_matches_audience(broadcast, membership.department_id, membership.role_level):
            raise AppError("You are not in this broadcast's audience", 403, "NOT_IN_AUDIENCE")

        BroadcastRepository.create_acknowledgement(broadcast.id, user.id)
        return BroadcastRepository.ack_count(broadcast.id)

    @staticmethod
    def get_ack_count(user, tenant_id, broadcast_id):
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)
        return BroadcastRepository.ack_count(broadcast.id)


def _unconfirmed_image_key(tenant_id, broadcast_id) -> str:
    return f"bolo-broadcast/unconfirmed/{tenant_id}/{broadcast_id}"


def _confirmed_image_key(tenant_id, broadcast_id) -> str:
    return f"bolo-broadcast/{tenant_id}/{broadcast_id}"


class BroadcastImageService:
    @staticmethod
    def presign_upload(user, tenant_id, broadcast_id, filename, content_type, file_size):
        _require_can_broadcast(user)
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)
        if broadcast.status != BroadcastStatus.DRAFT:
            raise ValidationError(
                "Cannot attach an image to a published broadcast", code="CANNOT_EDIT_PUBLISHED",
            )
        if file_size > MAX_IMAGE_SIZE_BYTES:
            raise ValidationError("Image exceeds the maximum allowed size")

        key = _unconfirmed_image_key(tenant_id, broadcast_id)
        upload_url = storage.generate_presigned_put_url(key, content_type, PRESIGN_EXPIRES_IN_SECONDS)
        return {"uploadUrl": upload_url, "expiresIn": PRESIGN_EXPIRES_IN_SECONDS}

    @staticmethod
    def confirm_image(user, tenant_id, broadcast_id):
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)
        _require_sender(broadcast, user)
        if broadcast.status != BroadcastStatus.DRAFT:
            raise ValidationError(
                "Cannot attach an image to a published broadcast", code="CANNOT_EDIT_PUBLISHED",
            )

        unconfirmed_key = _unconfirmed_image_key(tenant_id, broadcast_id)
        confirmed_key = _confirmed_image_key(tenant_id, broadcast_id)
        storage.copy_object(unconfirmed_key, confirmed_key)
        storage.delete_object(unconfirmed_key)

        BroadcastRepository.update(broadcast, image_url=confirmed_key)

    @staticmethod
    def get_image_stream(user, tenant_id, broadcast_id):
        broadcast = BroadcastRepository.get_by_id_or_404(broadcast_id, tenant_id)

        if broadcast.sender_id != user.id:
            if broadcast.status != BroadcastStatus.PUBLISHED or _is_expired(broadcast):
                raise AppError("You are not in this broadcast's audience", 403, "NOT_IN_AUDIENCE")
            membership = MembershipRepository.get_profile_for_user(user.id)
            if not _caller_matches_audience(broadcast, membership.department_id, membership.role_level):
                raise AppError("You are not in this broadcast's audience", 403, "NOT_IN_AUDIENCE")

        if not broadcast.image_url:
            raise NotFoundError("Broadcast image", broadcast_id)

        body, content_type = storage.get_object_stream(broadcast.image_url)
        return body, content_type or "application/octet-stream"
