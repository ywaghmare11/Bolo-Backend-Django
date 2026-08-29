import datetime
import uuid

from django.apps import apps as django_apps
from django.urls import Resolver404, resolve

from apps.common.audit_route_config import AUDIT_ROUTE_CONFIG
from apps.common.enums import AuditActorType
from apps.common.request_identity import decode_access_cookie, decode_admin_cookie
from apps.common.tasks import write_audit_log_task


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

        actor_type = None
        metadata = None
        if config.get("actor") == "platform_admin":
            # Second actor-resolution path: the cross-tenant admin_token cookie,
            # never the tenant-user `token` cookie. A PlatformAdmin isn't a User
            # row, so actor_id stays null and its identity is captured in
            # metadata instead (docs/api/api-spec.md §22, AuditActorType).
            admin_id, admin_email = decode_admin_cookie(request)
            actor_id, tenant_id = None, None
            actor_type = AuditActorType.PLATFORM_ADMIN
            metadata = {"platformAdminId": admin_id, "platformAdminEmail": admin_email}
        else:
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
        if "tenant_id_kwarg" in config:
            kwarg_val = match.kwargs.get(config["tenant_id_kwarg"])
            if kwarg_val is not None:
                tenant_id = str(kwarg_val)
        if "tenant_id_resolver" in config:
            tenant_id = config["tenant_id_resolver"](response) or tenant_id

        write_audit_log_task.delay(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            entity_type=config["entity_type"],
            entity_id=str(entity_id),
            action=action,
            before=before,
            after=after,
            metadata=metadata,
        )
        return response
