from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.labels.serializers import LabelCreateSerializer, LabelListItemSerializer
from apps.labels.services import LabelService


class LabelCreateView(APIView):
    def post(self, request):
        serializer = LabelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        label = LabelService.create_label(
            user=request.user,
            tenant_id=request.tenant_id,
            **serializer.validated_data,
        )
        data = LabelListItemSerializer(label).data
        return success_response(data, "Label created", status=201)


class SharedLabelsView(APIView):
    def get(self, request):
        labels = LabelService.list_my_labels(request.user, request.tenant_id)
        data = LabelListItemSerializer(labels, many=True).data
        return success_response(data, "OK")


class MyLabelsView(APIView):
    def get(self, request):
        labels = LabelService.list_my_labels(request.user, request.tenant_id)
        data = LabelListItemSerializer(labels, many=True).data
        return success_response(data, "OK")
