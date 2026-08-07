import logging

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler

from apps.common.exceptions import AppError
from apps.common.responses import failure_response

logger = logging.getLogger("bolo")  # TODO(structlog): swap once structlog lands


def bolo_exception_handler(exc, context):
    if isinstance(exc, AppError):
        logger.warning("app_error", extra={"code": exc.code, "path": context["request"].path})
        return failure_response(exc.message, exc.status_code, exc.code, data=exc.data)

    if isinstance(exc, Throttled):
        # DRF's default Throttled response is {"detail": "..."} -- not the app's
        # {success, error:{code, message}} envelope. Same RATE_LIMITED code the
        # OTP resend/lockout checks in AuthService already use for 429s.
        return failure_response("Too many requests. Try again later.", 429, "RATE_LIMITED")

    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    logger.exception("unhandled_error", extra={"path": context["request"].path})
    return failure_response("An unexpected error occurred", 500, "SERVER_ERROR")
