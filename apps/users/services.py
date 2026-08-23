from apps.common import storage
from apps.common.exceptions import NotFoundError, ValidationError
from apps.tenants.repositories import MembershipRepository
from apps.users.repositories import UserRepository

PRESIGN_EXPIRES_IN_SECONDS = 900
# 5MB placeholder cap -- no dedicated PRD limit for avatars, same as Broadcast image.
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024


def _unconfirmed_key(user_id) -> str:
    return f"bolo-profile-pics/unconfirmed/{user_id}"


def _confirmed_key(user_id) -> str:
    return f"bolo-profile-pics/{user_id}"


class UserService:
    @staticmethod
    def get_me(user):
        membership = MembershipRepository.get_profile_for_user(user.id)
        return user, membership

    @staticmethod
    def update_me(user, fields: dict):
        return UserRepository.update(user, **fields)


class ProfilePictureService:
    """Single object per user -- a re-upload overwrites the existing picture
    at the same confirmed S3 key, same shape as BroadcastImageService."""

    @staticmethod
    def presign_upload(user, content_type, file_size):
        if file_size > MAX_IMAGE_SIZE_BYTES:
            raise ValidationError("Image exceeds the maximum allowed size")

        key = _unconfirmed_key(user.id)
        upload_url = storage.generate_presigned_put_url(key, content_type, PRESIGN_EXPIRES_IN_SECONDS)
        return {"uploadUrl": upload_url, "expiresIn": PRESIGN_EXPIRES_IN_SECONDS}

    @staticmethod
    def confirm_upload(user):
        unconfirmed_key = _unconfirmed_key(user.id)
        confirmed_key = _confirmed_key(user.id)
        storage.copy_object(unconfirmed_key, confirmed_key)
        storage.delete_object(unconfirmed_key)
        return UserRepository.update(user, profile_pic_url=confirmed_key)

    @staticmethod
    def delete(user):
        if not user.profile_pic_url:
            raise NotFoundError("Profile picture", user.id)
        storage.delete_object(user.profile_pic_url)
        UserRepository.update(user, profile_pic_url=None)

    @staticmethod
    def get_metadata(tenant_id, user_id):
        return UserRepository.get_by_id_in_tenant(user_id, tenant_id)

    @staticmethod
    def get_stream(tenant_id, user_id):
        """Streams the object server-side -- never a pre-signed URL, same
        pattern as Evidence/Broadcast image/Voice recording. Tenant-scoped
        only, no further per-viewer restriction: profile pictures are already
        visible tenant-wide in member lists, task cards, comments, and the
        org chart."""
        target = UserRepository.get_by_id_in_tenant(user_id, tenant_id)
        if not target.profile_pic_url:
            raise NotFoundError("Profile picture", user_id)

        body, content_type = storage.get_object_stream(target.profile_pic_url)
        return body, content_type or "application/octet-stream"
