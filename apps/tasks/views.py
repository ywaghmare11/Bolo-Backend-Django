from django.http import StreamingHttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationError
from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response
from apps.tasks.serializers import (
    SubtaskCreateSerializer,
    TaskCreateSerializer,
    TaskDetailSerializer,
    TaskExtractSerializer,
    TaskListItemSerializer,
    TaskUpdateSerializer,
    VoiceAudioConfirmSerializer,
    VoicePresignSerializer,
    serialize_extraction,
    serialize_task_created,
    serialize_voice_recording,
)
from apps.tasks.services import TaskService
from apps.tasks.voice_recording_service import VoiceRecordingService


def _parse_bool(value, default=False):
    if value is None:
        return default
    return value.lower() == "true"


class TaskListCreateView(APIView):
    def get(self, request):
        view = request.query_params.get("view")
        label_id = request.query_params.get("labelId") or None
        is_archived = _parse_bool(request.query_params.get("isArchived"), default=False)

        qs = TaskService.list_tasks(
            request.user, request.tenant_id, view, label_id=label_id, is_archived=is_archived,
        )

        paginator = BoloPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        page = TaskService.attach_latest_comments(page)
        data = TaskListItemSerializer(page, many=True).data
        return Response(paginator.get_paginated_response(data))

    def post(self, request):
        serializer = TaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        task = TaskService.create_task(
            request.user, request.tenant_id, **serializer.validated_data,
        )
        return success_response(serialize_task_created(task), "Task created", status=201)


class TaskCountsView(APIView):
    def get(self, request):
        counts = TaskService.get_counts(request.user, request.tenant_id)
        return success_response(counts, "OK")


class TaskExtractView(APIView):
    def post(self, request):
        serializer = TaskExtractSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = TaskService.extract_task_fields(serializer.validated_data["text"])
        return success_response(serialize_extraction(result), "OK")


class TaskDetailView(APIView):
    def get(self, request, task_id):
        result = TaskService.get_task_detail(request.user, request.tenant_id, task_id)
        return success_response(TaskDetailSerializer(result).data, "OK")

    def patch(self, request, task_id):
        if "title" in request.data:
            raise ValidationError("Task title cannot be changed after creation", code="TITLE_IMMUTABLE")

        serializer = TaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        task = TaskService.update_task(
            request.user, request.tenant_id, task_id, serializer.validated_data,
        )
        return success_response(serialize_task_created(task), "Task updated")

    def delete(self, request, task_id):
        TaskService.delete_task(request.user, request.tenant_id, task_id)
        return success_response(None, "Task deleted")


class TaskAcceptView(APIView):
    def post(self, request, task_id):
        task = TaskService.accept_task(request.user, request.tenant_id, task_id)
        return success_response(
            {"status": task.status, "acceptedAt": task.accepted_at.isoformat()},
            "Task accepted",
        )


class TaskDoneAView(APIView):
    def post(self, request, task_id):
        task = TaskService.mark_done_a(request.user, request.tenant_id, task_id)
        return success_response(
            {"status": task.status}, "Marked as complete -- awaiting delegator confirmation",
        )


class TaskDoneDView(APIView):
    def post(self, request, task_id):
        task = TaskService.mark_done_d(request.user, request.tenant_id, task_id)
        return success_response(
            {"status": task.status, "isArchived": task.is_archived}, "Task completed and archived",
        )


class TaskCancelView(APIView):
    def post(self, request, task_id):
        task = TaskService.cancel_task(request.user, request.tenant_id, task_id)
        return success_response({"status": task.status}, "Task cancelled")


class TaskRemindView(APIView):
    def post(self, request, task_id):
        TaskService.remind_task(request.user, request.tenant_id, task_id)
        return success_response(None, "Reminder sent to assignee")


class SubtaskListCreateView(APIView):
    def post(self, request, task_id):
        serializer = SubtaskCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        subtask = TaskService.create_subtask(
            request.user, request.tenant_id, task_id, **serializer.validated_data,
        )
        return success_response(serialize_task_created(subtask), "Subtask created", status=201)


class SubtaskDetailView(APIView):
    def patch(self, request, task_id, subtask_id):
        if "title" in request.data:
            raise ValidationError("Task title cannot be changed after creation", code="TITLE_IMMUTABLE")

        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        serializer = TaskUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        subtask = TaskService.update_task(
            request.user, request.tenant_id, subtask_id, serializer.validated_data,
        )
        return success_response(serialize_task_created(subtask), "Subtask updated")

    def delete(self, request, task_id, subtask_id):
        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        TaskService.delete_task(request.user, request.tenant_id, subtask_id)
        return success_response(None, "Subtask deleted")


class SubtaskAcceptView(APIView):
    def post(self, request, task_id, subtask_id):
        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        subtask = TaskService.accept_task(request.user, request.tenant_id, subtask_id)
        return success_response(
            {"status": subtask.status, "acceptedAt": subtask.accepted_at.isoformat()},
            "Subtask accepted",
        )


class SubtaskDoneAView(APIView):
    def post(self, request, task_id, subtask_id):
        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        subtask = TaskService.mark_done_a(request.user, request.tenant_id, subtask_id)
        return success_response(
            {"status": subtask.status}, "Marked as complete -- awaiting delegator confirmation",
        )


class SubtaskDoneDView(APIView):
    def post(self, request, task_id, subtask_id):
        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        subtask = TaskService.mark_done_d(request.user, request.tenant_id, subtask_id)
        return success_response(
            {"status": subtask.status, "isArchived": subtask.is_archived}, "Subtask completed",
        )


class SubtaskCancelView(APIView):
    def post(self, request, task_id, subtask_id):
        TaskService.get_subtask_or_404(request.tenant_id, task_id, subtask_id)
        subtask = TaskService.cancel_task(request.user, request.tenant_id, subtask_id)
        return success_response({"status": subtask.status}, "Subtask cancelled")


class VoicePresignView(APIView):
    def post(self, request):
        serializer = VoicePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = VoiceRecordingService.presign_audio_upload(
            request.user, request.tenant_id, **serializer.validated_data,
        )
        return success_response(data, "Upload URL generated")


class VoiceRecordingDetailView(APIView):
    def get(self, request, task_id):
        voice_recording = VoiceRecordingService.get_transcript(request.user, request.tenant_id, task_id)
        return success_response(serialize_voice_recording(voice_recording), "OK")


class VoiceRecordingAudioView(APIView):
    def get(self, request, task_id):
        body, content_type = VoiceRecordingService.get_audio_stream(
            request.user, request.tenant_id, task_id,
        )
        return StreamingHttpResponse(body, content_type=content_type)

    def patch(self, request, task_id):
        serializer = VoiceAudioConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        voice_recording = VoiceRecordingService.confirm_audio(
            request.user, request.tenant_id, task_id, **serializer.validated_data,
        )
        return success_response({"hasAudio": bool(voice_recording.audio_url)}, "Audio linked")
