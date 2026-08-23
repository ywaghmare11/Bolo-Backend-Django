from urllib.parse import quote

from django.http import StreamingHttpResponse
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.users.serializers import (
    MeUpdateSerializer,
    ProfilePicturePresignSerializer,
    profile_picture_path,
    serialize_me,
)
from apps.users.services import ProfilePictureService, UserService


class MeView(APIView):
    def get(self, request):
        user, membership = UserService.get_me(request.user)
        return success_response(serialize_me(user, membership), "OK")

    def patch(self, request):
        serializer = MeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = UserService.update_me(request.user, serializer.validated_data)

        data = {}
        if "name" in serializer.validated_data:
            data["name"] = user.name
        if "preferred_lang" in serializer.validated_data:
            data["preferredLang"] = user.preferred_lang
        return success_response(data, "OK")


class ProfilePicturePresignView(APIView):
    def post(self, request):
        serializer = ProfilePicturePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = ProfilePictureService.presign_upload(request.user, **serializer.validated_data)
        return success_response(data, "Upload URL generated")


class MeProfilePictureView(APIView):
    def patch(self, request):
        user = ProfilePictureService.confirm_upload(request.user)
        return success_response({"profilePicUrl": profile_picture_path(user)}, "OK")

    def delete(self, request):
        ProfilePictureService.delete(request.user)
        return success_response(None, "OK")


class UserProfilePictureView(APIView):
    def get(self, request, user_id):
        target = ProfilePictureService.get_metadata(request.tenant_id, user_id)
        data = {"userId": str(target.id), "profilePicUrl": profile_picture_path(target)}
        return success_response(data, "OK")


class UserProfilePictureFileView(APIView):
    def get(self, request, user_id):
        body, content_type = ProfilePictureService.get_stream(request.tenant_id, user_id)
        response = StreamingHttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(str(user_id))}"
        return response
