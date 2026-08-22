from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response
from apps.notifications.serializers import serialize_notification
from apps.notifications.services import NotificationService, NudgeService


def _parse_is_read(value):
    if value is None:
        return None
    return value.lower() == "true"


class NotificationListView(APIView):
    def get(self, request):
        is_read = _parse_is_read(request.query_params.get("isRead"))
        type_param = request.query_params.get("type")
        types = [t.strip() for t in type_param.split(",")] if type_param else None

        qs = NotificationService.list_notifications(
            request.user, request.tenant_id, is_read=is_read, types=types,
        )
        paginator = BoloPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = [serialize_notification(n) for n in page]
        return Response(paginator.get_paginated_response(data))


class NotificationMarkReadView(APIView):
    def patch(self, request, notification_id):
        data = NotificationService.mark_read(request.user, request.tenant_id, notification_id)
        return success_response(data, "Notification marked as read")


class NotificationMarkAllReadView(APIView):
    def post(self, request):
        data = NotificationService.mark_all_read(request.user, request.tenant_id)
        return success_response(data, "All notifications marked as read")


class NotificationUnreadCountView(APIView):
    def get(self, request):
        data = NotificationService.unread_count(request.user, request.tenant_id)
        return success_response(data, "OK")


class NudgeFeedView(APIView):
    def get(self, request):
        data = NudgeService.get_feed(request.user, request.tenant_id)
        return success_response(data, "OK")


class NudgeSkipView(APIView):
    def post(self, request, notification_id):
        data = NudgeService.skip(request.user, request.tenant_id, notification_id)
        return success_response(data, "Nudge skipped")


class NudgeSkipAllView(APIView):
    def post(self, request):
        data = NudgeService.skip_all(request.user, request.tenant_id)
        return success_response(data, "All nudges skipped")
