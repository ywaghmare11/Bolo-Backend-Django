from urllib.parse import quote

from django.http import StreamingHttpResponse
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.evidence.serializers import (
    EvidenceConfirmSerializer,
    EvidencePresignSerializer,
    serialize_evidence,
)
from apps.evidence.services import EvidenceService


class EvidencePresignView(APIView):
    def post(self, request):
        serializer = EvidencePresignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = EvidenceService.presign_upload(
            request.user, request.tenant_id, **serializer.validated_data,
        )
        return success_response(data, "Upload URL generated")


class EvidenceListCreateView(APIView):
    def get(self, request, task_id):
        qs = EvidenceService.list_evidence(request.user, request.tenant_id, task_id)
        return success_response([serialize_evidence(e) for e in qs], "OK")

    def post(self, request, task_id):
        serializer = EvidenceConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        evidence = EvidenceService.confirm_evidence(
            request.user, request.tenant_id, task_id, **serializer.validated_data,
        )
        return success_response(serialize_evidence(evidence), "Evidence attached", status=201)


class EvidenceFileView(APIView):
    def get(self, request, task_id, evidence_id):
        body, content_type, file_name = EvidenceService.get_evidence_file(
            request.user, request.tenant_id, task_id, evidence_id,
        )
        response = StreamingHttpResponse(body, content_type=content_type)
        response["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(file_name)}"
        return response


class EvidenceDetailView(APIView):
    def delete(self, request, task_id, evidence_id):
        EvidenceService.delete_evidence(request.user, request.tenant_id, task_id, evidence_id)
        return success_response(None, "Evidence removed")
