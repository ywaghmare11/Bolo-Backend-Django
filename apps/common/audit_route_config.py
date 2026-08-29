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
  tenant_id_kwarg   name of a URL kwarg holding the tenant id -- for the PlatformAdmin
                    member routes, where the tenant is in the path (/tenants/:tenantId/...)
                    and there's no tenant-user JWT to read it from.
  actor             "platform_admin" on the cross-tenant PlatformAdmin routes: the
                    middleware then resolves the actor from the admin_token cookie
                    (actor_type=PLATFORM_ADMIN, actor_id=null, identity in metadata)
                    instead of the tenant-user `token` cookie.
  metadata_response_fields  list of keys to copy from response.data["data"] into
                    AuditLog.metadata alongside the actor identity -- used by the
                    bulk-import route so the run's {created, updated, skipped}
                    counts are on the audit row, not only in the HTTP response.
"""
from apps.common.enums import AuditAction

TASK_TRACKED_FIELDS = ["status", "priority", "due_date", "assignee_id", "main_label_id", "is_archived"]
USER_TRACKED_FIELDS = ["last_login_at", "last_logout_at"]
# "text" deliberately excluded -- guidelines.md bans comment text from before/after.
COMMENT_TRACKED_FIELDS = ["is_edited"]
# "file_name"/"caption" deliberately excluded -- same structural-fields-only principle.
EVIDENCE_TRACKED_FIELDS = ["file_type"]
# "message_json"/"message_html" deliberately excluded -- same structural-fields-only
# principle as Comment's "text" exclusion.
BROADCAST_TRACKED_FIELDS = ["status", "requires_acknowledgement"]
# PlatformAdmin cross-tenant routes. "name" excluded (free text, same principle);
# role_level lives on TenantMembership, not User, so it isn't reachable from the
# single-model _fetch_state -- tenant_id is the useful structural fact captured here.
TENANT_TRACKED_FIELDS = ["vertical", "url_slug"]
MEMBER_TRACKED_FIELDS = ["tenant_id", "preferred_lang"]


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
    from apps.common.request_identity import decode_access_cookie

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

_COMMENT_ROW = {
    "entity_type": "COMMENT",
    "model": "comments.Comment",
    "tracked_fields": COMMENT_TRACKED_FIELDS,
}

_EVIDENCE_ROW = {
    "entity_type": "DOCUMENT",
    "model": "evidence.Evidence",
    "tracked_fields": EVIDENCE_TRACKED_FIELDS,
}

_BROADCAST_ROW = {
    "entity_type": "BROADCAST",
    "model": "broadcasts.BroadcastNotice",
    "tracked_fields": BROADCAST_TRACKED_FIELDS,
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
    ("POST", "subtask-create"): {
        **_TASK_ROW,
        "id_resolver_post": _response_data_field("id"),
        "action": AuditAction.SUBTASK_CREATED,
    },
    ("PATCH", "subtask-detail"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_UPDATED,
    },
    ("DELETE", "subtask-detail"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_DELETED,
    },
    # accept/done-a/done-d/cancel all map to SUBTASK_UPDATED -- unlike Task, the
    # schema has no granular SUBTASK_STATUS_CHANGED action, matching upstream.
    ("POST", "subtask-accept"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_UPDATED,
    },
    ("POST", "subtask-done-a"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_UPDATED,
    },
    ("POST", "subtask-done-d"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_UPDATED,
    },
    ("POST", "subtask-cancel"): {
        **_TASK_ROW,
        "id_resolver": _url_kwarg("subtask_id"),
        "action": AuditAction.SUBTASK_UPDATED,
    },
    # Unlike the original Node route (a single generic `:id` param shared by the
    # task-detail and comment-detail routes, requiring an explicit override), this
    # app's nested comment routes use a distinctly-named `comment_id` kwarg, so
    # `_url_kwarg` already resolves the right id with no override needed.
    ("POST", "comment-list-create"): {
        **_COMMENT_ROW,
        "id_resolver_post": _response_data_field("id"),
        "action": AuditAction.COMMENT_CREATED,
    },
    ("PATCH", "comment-detail"): {
        **_COMMENT_ROW,
        "id_resolver": _url_kwarg("comment_id"),
        "action": AuditAction.COMMENT_UPDATED,
    },
    ("DELETE", "comment-detail"): {
        **_COMMENT_ROW,
        "id_resolver": _url_kwarg("comment_id"),
        "action": AuditAction.COMMENT_DELETED,
    },
    # Distinctly-named `evidence_id` kwarg (not a shared generic `:id`) means no
    # idParam override is needed here, unlike the original Node route.
    ("POST", "evidence-list-create"): {
        **_EVIDENCE_ROW,
        "id_resolver_post": _response_data_field("id"),
        "action": AuditAction.DOCUMENT_UPLOADED,
    },
    ("DELETE", "evidence-detail"): {
        **_EVIDENCE_ROW,
        "id_resolver": _url_kwarg("evidence_id"),
        "action": AuditAction.DOCUMENT_DELETED,
    },
    ("POST", "broadcast-list-create"): {
        **_BROADCAST_ROW,
        "id_resolver_post": _response_data_field("id"),
        "action": AuditAction.BROADCAST_CREATED,
    },
    ("PATCH", "broadcast-detail"): {
        **_BROADCAST_ROW,
        "id_resolver": _url_kwarg("broadcast_id"),
        "action": AuditAction.BROADCAST_UPDATED,
    },
    ("DELETE", "broadcast-detail"): {
        **_BROADCAST_ROW,
        "id_resolver": _url_kwarg("broadcast_id"),
        "action": AuditAction.BROADCAST_DELETED,
    },
    ("POST", "broadcast-publish"): {
        **_BROADCAST_ROW,
        "id_resolver": _url_kwarg("broadcast_id"),
        "action": AuditAction.BROADCAST_PUBLISHED,
    },
    ("POST", "broadcast-ack"): {
        **_BROADCAST_ROW,
        "id_resolver": _url_kwarg("broadcast_id"),
        "action": AuditAction.BROADCAST_ACKNOWLEDGED,
    },
    # broadcast-image-presign / broadcast-image (confirm): excluded -- neither mutates
    # a field this route config tracks in a way distinct from BROADCAST_UPDATED, and
    # api-spec.md doesn't call out a dedicated audit event for image attach (same
    # "don't invent a mapping speculatively" call as evidence's DOCUMENT_ACCESSED).
    # BROADCAST_VIEWED: unused -- would require auditing GET requests, which the
    # middleware doesn't support (only POST/PATCH/DELETE), same as DOCUMENT_ACCESSED.
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
    # PlatformAdmin (cross-tenant / superadmin) -- actor resolved from the
    # admin_token cookie, not the tenant-user `token` cookie. TENANT_CREATED/
    # MEMBER_ADDED/MEMBER_REMOVED already exist in AuditAction (Phase 1);
    # docs/api/api-spec.md §22 specifies entityType "Tenant"/"User".
    ("POST", "platform-admin-tenants"): {
        "entity_type": "TENANT",
        "model": "tenants.Tenant",
        "tracked_fields": TENANT_TRACKED_FIELDS,
        "id_resolver_post": _response_data_field("tenantId"),
        "tenant_id_resolver": _response_data_field("tenantId"),
        "action": AuditAction.TENANT_CREATED,
        "actor": "platform_admin",
    },
    ("POST", "platform-admin-tenant-members"): {
        "entity_type": "USER",
        "model": "users.User",
        "tracked_fields": MEMBER_TRACKED_FIELDS,
        "id_resolver_post": _response_data_field("userId"),
        "tenant_id_kwarg": "tenant_id",
        "action": AuditAction.MEMBER_ADDED,
        "actor": "platform_admin",
    },
    ("DELETE", "platform-admin-tenant-member-detail"): {
        "entity_type": "USER",
        "model": "users.User",
        "tracked_fields": MEMBER_TRACKED_FIELDS,
        "id_resolver": _url_kwarg("user_id"),
        "tenant_id_kwarg": "tenant_id",
        "action": AuditAction.MEMBER_REMOVED,
        "actor": "platform_admin",
    },
    # Bulk import (Phase 15c) -- one row per call, entity is the target tenant
    # (api-spec.md §22). before == after (the import doesn't mutate the Tenant
    # row itself); the run's scale is folded into metadata via
    # metadata_response_fields so "who imported how much into which tenant" is
    # answerable from the audit trail alone.
    ("POST", "platform-admin-tenant-member-import"): {
        "entity_type": "TENANT",
        "model": "tenants.Tenant",
        "tracked_fields": TENANT_TRACKED_FIELDS,
        "id_resolver": _url_kwarg("tenant_id"),
        "tenant_id_kwarg": "tenant_id",
        "action": AuditAction.MEMBERS_BULK_IMPORTED,
        "actor": "platform_admin",
        "metadata_response_fields": ["created", "updated", "skipped"],
    },
}
