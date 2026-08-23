from urllib.parse import quote

from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.broadcasts.serializers import (
    BroadcastCreateSerializer,
    BroadcastImagePresignSerializer,
    BroadcastUpdateSerializer,
    broadcast_image_path,
    serialize_broadcast_list_item,
)
from apps.broadcasts.services import BroadcastImageService, BroadcastService
from apps.common.exceptions import ValidationError
from apps.common.pagination import BoloPageNumberPagination
from apps.common.responses import success_response


def _parse_date_param(raw, param_name):
    if not raw:
        return None
    # Accept a bare date ("2026-08-01") by treating it as midnight that day --
    # parse_datetime alone rejects a date-only string.
    parsed = parse_datetime(raw) or parse_datetime(f"{raw}T00:00:00")
    if parsed is None:
        raise ValidationError(f"{param_name} is not a valid ISO date/datetime")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


class BroadcastListCreateView(APIView):
    def get(self, request):
        view = request.query_params.get("view")
        from_date = _parse_date_param(request.query_params.get("from"), "from")
        to_date = _parse_date_param(request.query_params.get("to"), "to")
        qs, include_has_acknowledged = BroadcastService.list_broadcasts(
            request.user, request.tenant_id, view, from_date=from_date, to_date=to_date,
        )

        paginator = BoloPageNumberPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if view == "sent":
            page = BroadcastService.attach_audience_size(request.tenant_id, page)
        data = [
            serialize_broadcast_list_item(b, include_has_acknowledged=include_has_acknowledged)
            for b in page
        ]
        return Response(paginator.get_paginated_response(data))

    def post(self, request):
        serializer = BroadcastCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        broadcast = BroadcastService.create_draft(
            request.user, request.tenant_id, **serializer.validated_data,
        )
        data = {
            "id": str(broadcast.id),
            "status": broadcast.status,
            "senderId": str(broadcast.sender_id),
            "createdAt": broadcast.created_at.isoformat(),
        }
        return success_response(data, "Draft saved", status=201)


class BroadcastDetailView(APIView):
    def patch(self, request, broadcast_id):
        serializer = BroadcastUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        broadcast = BroadcastService.update_broadcast(
            request.user, request.tenant_id, broadcast_id, serializer.validated_data,
        )
        data = {"id": str(broadcast.id), "status": broadcast.status}
        return success_response(data, "Broadcast updated")

    def delete(self, request, broadcast_id):
        BroadcastService.delete_broadcast(request.user, request.tenant_id, broadcast_id)
        return success_response(None, "Broadcast deleted")


class BroadcastPublishView(APIView):
    def post(self, request, broadcast_id):
        broadcast = BroadcastService.publish(request.user, request.tenant_id, broadcast_id)
        data = {
            "id": str(broadcast.id),
            "status": broadcast.status,
            "expiresAt": broadcast.expires_at.isoformat(),
            "imageUrl": broadcast_image_path(broadcast),
        }
        return success_response(data, "Broadcast published")


class BroadcastAckView(APIView):
    def post(self, request, broadcast_id):
        ack_count = BroadcastService.acknowledge(request.user, request.tenant_id, broadcast_id)
        return success_response({"ackCount": ack_count}, "Acknowledged")


class BroadcastAckCountView(APIView):
    def get(self, request, broadcast_id):
        ack_count = BroadcastService.get_ack_count(request.user, request.tenant_id, broadcast_id)
        return success_response({"broadcastId": str(broadcast_id), "ackCount": ack_count}, "OK")


class BroadcastImagePresignView(APIView):
    def post(self, request):
        serializer = BroadcastImagePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = BroadcastImageService.presign_upload(
            request.user, request.tenant_id, **serializer.validated_data,
        )
        return success_response(data, "Upload URL generated")


class BroadcastImageView(APIView):
    def post(self, request, broadcast_id):
        BroadcastImageService.confirm_image(request.user, request.tenant_id, broadcast_id)
        return success_response({"hasImage": True}, "Image attached")

    def get(self, request, broadcast_id):
        body, content_type = BroadcastImageService.get_image_stream(
            request.user, request.tenant_id, broadcast_id,
        )
        response = StreamingHttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(str(broadcast_id))}"
        return response
