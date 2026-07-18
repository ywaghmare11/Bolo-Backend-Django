import logging

from rest_framework.views import exception_handler as drf_exception_handler

from apps.common.exceptions import AppError
from apps.common.responses import failure_response

logger = logging.getLogger("bolo")  # TODO(structlog): swap once structlog lands


def bolo_exception_handler(exc, context):
    if isinstance(exc, AppError):
        logger.warning("app_error", extra={"code": exc.code, "path": context["request"].path})
        return failure_response(exc.message, exc.status_code, exc.code, data=exc.data)

    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    logger.exception("unhandled_error", extra={"path": context["request"].path})
    return failure_response("An unexpected error occurred", 500, "SERVER_ERROR")
