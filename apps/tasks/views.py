from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import ValidationError
from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response
from apps.tasks.serializers import (
    TaskCreateSerializer,
    TaskDetailSerializer,
    TaskListItemSerializer,
    TaskUpdateSerializer,
    serialize_task_created,
)
from apps.tasks.services import TaskService


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
