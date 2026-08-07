from django.urls import path

from apps.comments.views import CommentDetailView, CommentListCreateView

urlpatterns = [
    path("<uuid:task_id>/comments/", CommentListCreateView.as_view(), name="comment-list-create"),
    path(
        "<uuid:task_id>/comments/<uuid:comment_id>/",
        CommentDetailView.as_view(),
        name="comment-detail",
    ),
]
