from rest_framework.pagination import PageNumberPagination


class BoloPageNumberPagination(PageNumberPagination):
    """Matches the api-spec.md envelope: {success, message, data, pagination}.

    The returned dict is already envelope-shaped -- views return it as-is via
    Response(...), they don't pass it through success_response() again.
    """

    page_query_param = "page"
    page_size_query_param = "limit"
    page_size = 20
    max_page_size = 100

    def get_paginated_response(self, data):
        return {
            "success": True,
            "message": "",
            "data": data,
            "pagination": {
                "page": self.page.number,
                "limit": self.get_page_size(self.request),
                "total": self.page.paginator.count,
            },
        }
