from rest_framework.response import Response
from rest_framework.views import APIView

from apps.comments.serializers import (
    CommentCreateSerializer,
    CommentUpdateSerializer,
    serialize_comment,
)
from apps.comments.services import CommentService
from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response


class CommentListCreateView(APIView):
    def get(self, request, task_id):
        qs = CommentService.list_comments(request.user, request.tenant_id, task_id)

        paginator = BoloPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = [serialize_comment(c) for c in page]
        return Response(paginator.get_paginated_response(data))

    def post(self, request, task_id):
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = CommentService.create_comment(
            request.user, request.tenant_id, task_id, serializer.validated_data["text"],
        )
        return success_response(serialize_comment(comment), "Comment added", status=201)


class CommentDetailView(APIView):
    def patch(self, request, task_id, comment_id):
        serializer = CommentUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = CommentService.update_comment(
            request.user, request.tenant_id, task_id, comment_id, serializer.validated_data["text"],
        )
        return success_response(serialize_comment(comment), "Comment updated")

    def delete(self, request, task_id, comment_id):
        CommentService.delete_comment(request.user, request.tenant_id, task_id, comment_id)
        return success_response(None, "Comment deleted")
