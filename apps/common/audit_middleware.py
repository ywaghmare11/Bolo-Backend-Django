import datetime
import uuid

from django.apps import apps as django_apps
from django.urls import Resolver404, resolve
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.common.audit_route_config import AUDIT_ROUTE_CONFIG
from apps.common.tasks import write_audit_log_task


def decode_access_cookie(request):
    """Independently reads + decodes the same httpOnly access-token cookie
    apps.auth.authentication.CookieJWTAuthentication uses. This middleware can't rely
    on request.tenant_id/request.user -- those are set on DRF's internal Request
    wrapper created inside APIView.dispatch(), not on the underlying HttpRequest this
    (plain Django) middleware holds a reference to, so they never propagate back here.
    Returns (user_id, tenant_id), both None if there's no valid token (e.g. request-otp,
    or verify-otp before the cookie it's about to set exists)."""
    from apps.auth.tokens import ACCESS_COOKIE_NAME

    raw = request.COOKIES.get(ACCESS_COOKIE_NAME)
    if not raw:
        return None, None
    try:
        token = AccessToken(raw)
    except TokenError:
        return None, None
    return token["userId"], token["tenantId"]


def _json_safe(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _fetch_state(config, entity_id):
    if entity_id is None:
        return None
    model = django_apps.get_model(config["model"])
    row = model.objects.filter(pk=entity_id).values(*config["tracked_fields"]).first()
    if row is None:
        return None
    return {key: _json_safe(value) for key, value in row.items()}


class AuditLogMiddleware:
    """Generic mutating-request observer -- CLAUDE.md Architecture Rules point 8.
    Route config: apps/common/audit_route_config.py. No service or view calls this
    directly; a new audited route means adding one config row there."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path_info.startswith("/api/v1/"):
            return self.get_response(request)

        try:
            match = resolve(request.path_info)
        except Resolver404:
            return self.get_response(request)

        config = AUDIT_ROUTE_CONFIG.get((request.method, match.url_name))
        if config is None:
            return self.get_response(request)

        actor_id, tenant_id = decode_access_cookie(request)

        entity_id = None
        before = None
        if "id_resolver" in config:
            entity_id = config["id_resolver"](request, match)
            before = _fetch_state(config, entity_id)

        response = self.get_response(request)

        if response.status_code >= 400:
            return response

        if entity_id is None and "id_resolver_post" in config:
            entity_id = config["id_resolver_post"](response)
        if entity_id is None:
            return response

        after = None if request.method == "DELETE" else _fetch_state(config, entity_id)

        action = config["action"]
        if callable(action):
            action = action(before, after)

        if config.get("actor_is_entity"):
            actor_id = str(entity_id)
        if "tenant_id_resolver" in config:
            tenant_id = config["tenant_id_resolver"](response) or tenant_id

        write_audit_log_task.delay(
            tenant_id=tenant_id,
            actor_id=actor_id,
            entity_type=config["entity_type"],
            entity_id=str(entity_id),
            action=action,
            before=before,
            after=after,
        )
        return response
