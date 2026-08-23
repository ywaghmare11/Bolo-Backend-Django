from django.urls import path

from apps.users.views import (
    MeProfilePictureView,
    MeView,
    UserProfilePictureFileView,
    UserProfilePictureView,
)

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/profile-picture/", MeProfilePictureView.as_view(), name="me-profile-picture"),
    path(
        "users/<uuid:user_id>/profile-picture/",
        UserProfilePictureView.as_view(),
        name="user-profile-picture",
    ),
    path(
        "users/<uuid:user_id>/profile-picture/file/",
        UserProfilePictureFileView.as_view(),
        name="user-profile-picture-file",
    ),
]
