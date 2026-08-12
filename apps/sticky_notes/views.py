from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response
from apps.sticky_notes.serializers import (
    StickyNoteCreateSerializer,
    StickyNotePromoteSerializer,
    StickyNoteUpdateSerializer,
    serialize_sticky_note,
)
from apps.sticky_notes.services import StickyNoteService


class StickyNoteListCreateView(APIView):
    def get(self, request):
        qs = StickyNoteService.list_notes(request.user)

        paginator = BoloPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = [serialize_sticky_note(n) for n in page]
        return Response(paginator.get_paginated_response(data))

    def post(self, request):
        serializer = StickyNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        note = StickyNoteService.create_note(request.user, **serializer.validated_data)
        return success_response(serialize_sticky_note(note), "Sticky note created", status=201)


class StickyNoteDetailView(APIView):
    def get(self, request, note_id):
        note = StickyNoteService.get_note(request.user, note_id)
        return success_response(serialize_sticky_note(note), "OK")

    def patch(self, request, note_id):
        serializer = StickyNoteUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        note = StickyNoteService.update_note(request.user, note_id, serializer.validated_data)
        return success_response(serialize_sticky_note(note), "Sticky note updated")

    def delete(self, request, note_id):
        StickyNoteService.delete_note(request.user, note_id)
        return success_response(None, "Sticky note deleted")


class StickyNotePromoteView(APIView):
    def post(self, request, note_id):
        serializer = StickyNotePromoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = StickyNoteService.promote_to_task(
            request.user, request.tenant_id, note_id, **serializer.validated_data,
        )
        data = {"taskId": str(task.id), "status": task.status}
        return success_response(data, "Promoted to task", status=201)
