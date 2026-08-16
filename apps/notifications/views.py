from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.notifications.services import NudgeService


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
