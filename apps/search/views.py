from rest_framework.response import Response
from rest_framework.views import APIView

from apps.search.serializers import SearchQuerySerializer
from apps.search.services import SearchService


class SearchTasksView(APIView):
    def get(self, request):
        serializer = SearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        result = SearchService.search_tasks(request.user, request.tenant_id, **serializer.validated_data)
        return Response(result)


class SearchStickiesView(APIView):
    def get(self, request):
        serializer = SearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        result = SearchService.search_stickies(request.user, request.tenant_id, **serializer.validated_data)
        return Response(result)
