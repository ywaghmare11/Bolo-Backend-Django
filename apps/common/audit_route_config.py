"""Static {method, view_name} -> config table for apps/common/audit_middleware.py.

A route not listed here is never audited -- auditing a new mutating endpoint means
adding one row, not editing the view (CLAUDE.md Architecture Rules point 8).

Each row:
  entity_type      UPPERCASE string stored on AuditLog.
  model            "app_label.ModelName" dotted string (resolved lazily via
                    django.apps.apps.get_model to avoid import-order issues).
  tracked_fields    allowlist of structural/status fields read into before/after --
                    never message text, names, descriptions (see guidelines.md).
  id_resolver       (request, url_match) -> pk, called BEFORE the view runs. Present
                    when the entity's pk is already in the URL (detail/action routes).
  id_resolver_post  (response) -> pk, called AFTER the view runs. Used when the pk is
                    only known from the response body (creates; login, whose actor
                    doesn't exist as an authenticated identity until the view resolves it).
                    When only this is present, `before` is always null (undiscoverable
                    pre-dispatch) -- the same convention the schema already uses for creates.
  action            AuditAction value, or resolve_action(before, after) -> AuditAction
                    for routes where a single method can mean several things.
  actor_is_entity   True for the two routes where the actor performing the action *is*
                    the entity being changed (login/logout) -- there's no separate actor.
  tenant_id_resolver (response) -> tenant_id, only needed for verify-otp: at request time
                    there's no session/JWT yet to decode a tenant_id out of (that's what
                    this request is creating), so it comes from the response body instead.
"""
from apps.common.enums import AuditAction

TASK_TRACKED_FIELDS = ["status", "priority", "due_date", "assignee_id", "main_label_id", "is_archived"]
USER_TRACKED_FIELDS = ["last_login_at", "last_logout_at"]


def _url_kwarg(name):
    def resolver(request, match):
        return match.kwargs.get(name)
    return resolver


def _response_data_field(key):
    def resolver(response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data")
        return inner.get(key) if isinstance(inner, dict) else None
    return resolver


def _logout_actor_id(request, match):
    from apps.common.audit_middleware import decode_access_cookie

    actor_id, _tenant_id = decode_access_cookie(request)
    return actor_id


def resolve_task_update_action(before, after):
    """Same mutually-exclusive priority-order branching as TaskService.update_task's
    own field handling -- reassignment takes precedence over label/due-date/priority
    since it's the most structurally significant change a PATCH can make."""
    if before is None or after is None:
        return AuditAction.TASK_UPDATED
    if before.get("assignee_id") != after.get("assignee_id"):
        return AuditAction.TASK_REASSIGNED
    if before.get("main_label_id") != after.get("main_label_id"):
        return AuditAction.TASK_LABEL_CHANGED
    if before.get("due_date") != after.get("due_date"):
        return AuditAction.TASK_DUE_DATE_CHANGED
    if before.get("priority") != after.get("priority"):
        return AuditAction.TASK_PRIORITY_CHANGED
    return AuditAction.TASK_UPDATED


_TASK_ROW = {
    "entity_type": "TASK",
    "model": "tasks.Task",
    "tracked_fields": TASK_TRACKED_FIELDS,
}

AUDIT_ROUTE_CONFIG = {
    ("POST", "task-list-create"): {
        **_TASK_ROW,
        "id_resolver_post": _response_data_field("id"),
        "action": AuditAction.TASK_CREATED,
    },
    ("PATCH", "task-detail"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": resolve_task_update_action,
    },
    ("DELETE", "task-detail"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": AuditAction.TASK_DELETED,
    },
    ("POST", "task-accept"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": AuditAction.TASK_STATUS_CHANGED,
    },
    ("POST", "task-done-a"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": AuditAction.TASK_STATUS_CHANGED,
    },
    ("POST", "task-done-d"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": AuditAction.TASK_STATUS_CHANGED,
    },
    ("POST", "task-cancel"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("task_id"),
        "action": AuditAction.TASK_STATUS_CHANGED,
    },
    # task-remind: excluded -- doesn't mutate any persisted entity, nothing to observe.
    # apps/labels routes: excluded -- no AuditAction values exist for label events yet
    # (CLAUDE.md's Notifications rule says "add the event type before wiring the call
    # site"; the same principle applies here rather than inventing an enum value).
    ("POST", "auth-verify-otp"): {
        "entity_type": "USER",
        "model": "users.User",
        "tracked_fields": USER_TRACKED_FIELDS,
        "id_resolver_post": _response_data_field("userId"),
        "tenant_id_resolver": _response_data_field("tenantId"),
        "action": AuditAction.USER_LOGIN,
        "actor_is_entity": True,
    },
    ("POST", "auth-logout"): {
        "entity_type": "USER",
        "model": "users.User",
        "tracked_fields": USER_TRACKED_FIELDS,
        "id_resolver": _logout_actor_id,
        "action": AuditAction.USER_LOGOUT,
        "actor_is_entity": True,
    },
}
