"""Structured request-lifecycle logging (ROADMAP.md Phase 10).

Binds request_id/method/path/actor_id/tenant_id to structlog's contextvars for the
whole request -- every log line emitted anywhere below this middleware (views,
services, the exception handler) automatically carries the same correlation ids,
without any of that code having to pass them explicitly. Genuinely first in
MIDDLEWARE so its timing window covers the entire request/response cycle, including
every other middleware.

Reuses apps.common.request_identity.decode_access_cookie -- the same technique
apps.common.audit_middleware already uses to read the caller's identity from plain
Django middleware, where request.user/request.tenant_id (set by DRF inside
APIView.dispatch()) aren't available yet.
"""
import time
import uuid

import structlog

from apps.common.request_identity import decode_access_cookie

logger = structlog.get_logger("bolo")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        structlog.contextvars.clear_contextvars()
        request_id = str(uuid.uuid4())
        actor_id, tenant_id = decode_access_cookie(request)
        actor_id = str(actor_id) if actor_id else None
        tenant_id = str(tenant_id) if tenant_id else None

        # Bound to contextvars so any *other* log line emitted anywhere during this
        # request (a service's own logger.warning, the exception handler) picks up
        # the same correlation ids automatically. The summary line below repeats
        # them as explicit kwargs anyway, so it's self-contained and matches
        # guidelines.md's documented shape on its own, regardless of contextvar
        # propagation -- not relying on it is what keeps this line simple to test.
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.path,
            actor_id=actor_id, tenant_id=tenant_id,
        )

        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "request_finished",
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            actor_id=actor_id,
            tenant_id=tenant_id,
        )
        return response
