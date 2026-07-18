# BOLO-BACKEND-DJANGO — Engineering Guidelines

> **How code must be written in this repo.** Read alongside `CLAUDE.md`.
> This is a Python/Django port of the original Node/Express/Prisma `bolo-backend` guidelines. Principles are unchanged; syntax and tooling are translated.
> **Last updated:** 2026-07-18 — Audit Logging section rewritten to match the original's generic middleware + route-config pattern (was manual `AuditService.log()` calls); `on_delete` exceptions updated to include `BroadcastAcknowledgement.broadcast`. Previously: initial scaffold (2026-07-14).

---

## Changelog rule

Every change — standards update, new pattern, significant refactor — must be logged in this project's `changelog.md` (root) before the PR is merged. Tags: `[BE]` `[STD]` `[INFRA]`. Newest first.

---

## Core rules (non-negotiable)

1. **Every query is tenant-scoped.** Tenant-owned tables carry `tenant_id`; repository queries always filter `tenant_id=...`. Child rows (StickyNote, Comment, Evidence, TaskPersonalLabel) are scoped via their owner/parent. `tenant_id` always comes from the decoded JWT (`request.tenant_id`), never the request body or query params.
2. **Audit log is required, and it is generic, not dispatched.** No service, view, or repository ever calls an audit-log function directly — see the "Audit Logging" section below for the middleware + route-config pattern (matches the original's 2026-07-14 W98/W99 redesign). `AuditLog` rows are immutable — no update/delete.
3. **PII encryption: not required yet** (matches original W62/DPDP decision). No GPS fields — this is web-only. Don't add encryption complexity speculatively.
4. **Validate at system boundaries.** Trust internal code; validate serializer input and external API responses. No defensive checks inside services/repositories.
5. **View → Service → Repository — strictly enforced.** No Django ORM in views. No `request`/`response` objects in services. No business logic in repositories.

---

## Django App Structure

One app per domain area (see `CLAUDE.md` → Proposed Project Structure). Each app:

```
apps/tasks/
  models.py          # Task, VoiceRecording, TaskPersonalLabel
  serializers.py      # TaskCreateSerializer, TaskResponseSerializer, ...
  views.py             # thin — parse request, call service, return response
  services.py          # TaskService — business logic, calls repositories.py
  repositories.py       # TaskRepository — the only place Task.objects.* is called
  permissions.py         # app-specific DRF permission classes
  urls.py
  tests/
    test_services.py
    test_views.py
```

### Data flow (must follow — no exceptions)

```
URL (urls.py)
  → View / ViewSet (views.py)        ← HTTP only, no business logic, no ORM
  → Service (services.py)             ← business logic, calls repository, calls AuditService
  → Repository (repositories.py)      ← the only place Model.objects.* / QuerySets are used
  → Django ORM → PostgreSQL
```

### Banned patterns

```python
# ❌ ORM call in a view
class TaskDetailView(APIView):
    def get(self, request, pk):
        task = Task.objects.get(pk=pk)   # NO — belongs in repositories.py

# ❌ business logic in a repository
class TaskRepository:
    def mark_done(self, task):
        if task.status != "DONE_A":       # NO — this is a business rule, belongs in services.py
            raise ValueError(...)

# ❌ raw DRF Response instead of the shared envelope
return Response({"data": task_data})      # NO — use success_response(...)
```

---

## Response Envelope (`apps/common/responses.py`)

Every endpoint returns this shape — never a raw `Response({...})`.

```python
def success_response(data, message="", status=200):
    return Response({"success": True, "message": message, "data": data}, status=status)

def failure_response(message, status=400, code="ERROR"):
    return Response({"success": False, "error": {"code": code, "message": message}}, status=status)
```

```json
// Success
{ "success": true, "message": "Task created", "data": { ... } }
// Error
{ "success": false, "error": { "code": "TASK_NOT_FOUND", "message": "..." } }
```

Never return `200` with an error body. Status codes: `200`, `201`, `400`, `401`, `403`, `404`, `409`, `422`, `429`, `500` — same set as the original API.

### REST conventions

- `GET` for reads (no side effects), `POST` for creates/actions, `PATCH` for partial updates (not `PUT`), `DELETE` for deletes.
- Route naming: plural nouns, kebab-case, versioned. `/api/v1/tasks/`, `/api/v1/broadcast-notices/`.
- DRF permission classes on every view — no exceptions.

---

## Error Handling

### Custom error classes (`apps/common/exceptions.py`)

```python
class AppError(Exception):
    def __init__(self, message: str, status_code: int, code: str):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)

class NotFoundError(AppError):
    def __init__(self, entity: str, id: str):
        super().__init__(f"{entity} not found: {id}", 404, "NOT_FOUND")

class ForbiddenError(AppError):
    def __init__(self, message="Access denied"):
        super().__init__(message, 403, "FORBIDDEN")

class ValidationError(AppError):
    def __init__(self, message: str, code="VALIDATION_ERROR"):
        super().__init__(message, 400, code)

class ConflictError(AppError):
    def __init__(self, message: str, code="CONFLICT"):
        super().__init__(message, 409, code)
```

Use the domain-specific codes from `docs/api/api-spec.md` (e.g. `TITLE_IMMUTABLE`, `REASSIGN_BLOCKED`) as the `code` argument.

### Global exception handler (`config/exception_handler.py`)

Register via DRF's `EXCEPTION_HANDLER` setting:

```python
def bolo_exception_handler(exc, context):
    if isinstance(exc, AppError):
        logger.warning("app_error", code=exc.code, path=context["request"].path)
        return failure_response(exc.message, exc.status_code, exc.code)
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response
    logger.error("unhandled_error", path=context["request"].path, exc_info=exc)
    return failure_response("An unexpected error occurred", 500, "SERVER_ERROR")
```

Services raise; views never catch. Let the exception handler do it.

### Service layer pattern

```python
class TaskService:
    def __init__(self, task_repo: TaskRepository):
        self.task_repo = task_repo

    def get_by_id(self, task_id: str, caller_id: str, tenant_id: str) -> Task:
        task = self.task_repo.find_by_id(task_id, tenant_id)
        if task is None:
            raise NotFoundError("Task", task_id)
        if task.assigner_id != caller_id and task.assignee_id != caller_id:
            raise ForbiddenError("You do not have access to this task")
        return task
```

---

## Logging

Use `structlog` (structured logging) — never bare `print()` in application code.

| Level | When to use |
|---|---|
| `error` | Unhandled exceptions, failed external calls (SES/SMTP, S3, DB) — always with stack trace |
| `warning` | Expected business errors (`AppError` subclasses), rate limit hits, auth failures |
| `info` | Request lifecycle, Celery task start/complete |
| `debug` | Detailed dev trace — never enabled in production |

**Always log:** request path/method/status/duration, error code + message, actor_id + tenant_id on mutating actions.

**Never log (PII):** emails, phone numbers, names, task titles/descriptions/comment text, OTP codes, S3 pre-signed URLs, JWTs/cookie values, voice transcripts.

```json
{"level": "info", "method": "POST", "path": "/api/v1/tasks", "status_code": 201, "duration_ms": 43, "actor_id": "uuid", "tenant_id": "uuid"}
```

---

## Audit Logging

**Generic middleware + static route-config table — not manual per-service calls.** This is deliberately the *opposite* pattern from Notifications (`dispatch_notification()`, called explicitly at every relevant call site) — matches the original's 2026-07-14 redesign (W98/W99). Rationale carried over unchanged: a `Notification` needs hand-written, context-specific `message`/`actor_name`/`entity_title` content only the business service has on hand; an `AuditLog` row needs none of that — it's a mechanical `{who, what route, before-state, after-state}` capture fully derivable from the HTTP request/response and a DB read, which is exactly what a generic layer is good at.

**Mechanics (Django/DRF equivalent of the original's Express middleware + config table):**

1. **Route config table** (`apps/common/audit_route_config.py`, one static dict) — one entry per `{method, resolver_match.view_name}` → `{entity_type (UPPERCASE), model, action | resolve_action(before, after)}`. A route not in this table is never audited — adding a new mutating endpoint means adding one config row, not editing a view. `resolver_match.view_name` is the Django-idiomatic substitute for the original's raw route-string matching.
2. **Before-state**: for update/delete-shaped routes, the middleware does a generic `model.objects.get(pk=...)` before calling `get_response(request)`. Naturally `None` for create routes (`before` stays null, matching the schema's existing convention).
3. **After-state**: the middleware inspects the response body's `data` field (every view already responds via `success_response()` → `{success, message, data}`, so this needs no per-view change). Only writes when `response.status_code < 400`.
4. **Action resolution**: most routes are single-purpose and just need a static `action` in the config row. Generic multi-purpose routes (e.g. `PATCH /tasks/:id`) need a `resolve_action(before, after)` diff function — same mutually-exclusive priority-order branching as the service's own update logic, reimplemented as a field-diff rule table.
5. **Write**: dispatched as a Celery task from the middleware after the response is fully formed (fire-and-forget — Django has no direct equivalent of Express's post-response hook, so queuing a Celery task at that point is the idiomatic substitute for "never blocks the response"). Logged on failure, never rolls back or blocks the parent request.

**The one documented exception — login/logout:** the OTP-verify and logout flows make no entity mutation the generic middleware can observe. Resolved the same way as upstream: `User.last_login_at`/`last_logout_at` are written directly by the auth service for their own legitimate session-tracking purpose (see `apps/users/models.py`), and the middleware picks up `USER_LOGIN`/`USER_LOGOUT` off of *that* field write the same generic way as everything else. No manual audit call is added anywhere for this — it's a schema/business-field change, not an audit-specific code path.

Same event → action mapping as the original backend (`TaskService.create()` → `TASK_CREATED`, `.accept()`/`.done_a()`/`.done_d()`/`.cancel()` → `TASK_STATUS_CHANGED`, `.reassign()` → `TASK_REASSIGNED`, evidence/broadcast/auth/tenant events, plus the newer platform-admin events `TENANT_CREATED`/`MEMBER_ADDED`/`MEMBER_REMOVED`/`MEMBERS_BULK_IMPORTED` — see `docs/architecture/domain-model.md`'s `AuditAction` enum table for the full current list).

`AuditLog.entity_type` is **UPPERCASE** (`"TASK"`, `"BROADCAST"`, `"USER"`, `"DOCUMENT"`, `"TENANT"`) — deliberately diverges from `Notification.entity_type`, which stays lowercase. `actor_id` is null for `SYSTEM` **and** `PLATFORM_ADMIN` actions (`PlatformAdmin` is a separate model from `User`, so there's no valid FK target either way) — `actor_type` distinguishes which.

**Never put in `before`/`after`:** message text, comment text, task descriptions, names, email — structural/status fields only.

---

## Database

- Migrations only (`python manage.py makemigrations` / `migrate`) — no manual schema changes in any environment.
- Every model: `id` (UUID, `default=uuid.uuid4`, `editable=False`), `created_at`, `updated_at` (`auto_now_add`/`auto_now`).
- Tenant-scoped tables carry `tenant_id` (UUID, `db_index=True`, not null). Child tables scoped via owner/parent FK.
- Foreign keys declared on the model (`on_delete=models.PROTECT` unless cascade is the documented rule — e.g. cancelling a parent task cascades to subtasks, but that's app-level logic in the service, not a DB `CASCADE`). Two documented DB-level exceptions exist: `VoiceRecording.task` and `BroadcastAcknowledgement.broadcast` are both `CASCADE` — the latter corrected 2026-07-13 upstream after `PROTECT` 500'd `DELETE /broadcast-notices/:id` for any broadcast with acknowledgements.
- Completed main tasks are **archived** via `is_archived=True` (set on DoneD), never deleted.
- No raw SQL / stored procedures that bypass the application auth layer.
- Avoid N+1 queries — use `select_related` / `prefetch_related` in repositories.
- `Meta.db_table` set explicitly to match `docs/reference/schema.prisma.reference`'s mapped table name (snake_case, plural) — the DB contract must stay identical even though the ORM differs.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Variables, functions | snake_case | `task_assignee_id` |
| Classes | PascalCase | `TaskService`, `EvidenceRepository` |
| DB tables | snake_case, plural | `tasks`, `broadcast_notices` |
| DB columns | snake_case | `tenant_id`, `created_at` |
| API routes | kebab-case, plural | `/broadcast-notices/` |
| Files | snake_case | `task_service.py`, `task_repository.py` |
| Django apps | snake_case, plural | `sticky_notes`, `broadcasts` |
| Env variables | SCREAMING_SNAKE_CASE | `DATABASE_URL` |

---

## Environment Variables

- All config via `django-environ`, no secrets in source code.
- `.env.example` with all required keys (empty values), never commit `.env`.
- Validate required env vars at Django startup (`config/settings/base.py`) — crash early (`environ.Env` with required=True, or explicit checks) if missing.
- Separate settings modules per environment (`base.py` / `dev.py` / `prod.py` / `test.py`) — never one giant `if DEBUG` branch file.

---

## Security

- Never trust `tenant_id` from the request body — always read from `request.tenant_id` (set by the custom JWT authentication class).
- Sanitize user input at the serializer boundary (title, description, broadcast HTML via `bleach`).
- File uploads: validate MIME type + extension server-side; never trust client-provided `Content-Type`.
- Signed URLs for evidence access — never expose raw S3 bucket keys.
- Never log PII (see Logging).
- Dependency scanning: `pip-audit` (or `safety`) in CI, block deploys on critical CVEs.

---

## Performance

- Evidence uploads: S3 pre-signed PUT URLs — bypass the API server entirely.
- Paginate all list endpoints via DRF pagination classes. Default page size 20, max 100 — never unbounded lists.
- Indexed columns in `WHERE` clauses — `tenant_id` always indexed.
- Avoid N+1 — `select_related`/`prefetch_related` in repositories.
- Notification fan-out for broadcasts: enqueue a Celery task, never inline in the request/response cycle.
- Analytics pre-computed via Celery beat cron — never computed on-the-fly per request.

---

## Comments

Write **no comments** by default. Add one only when the WHY is non-obvious: a hidden constraint, a workaround for a specific bug, an invariant that would surprise a reader. Don't document WHAT the code does — well-named identifiers do that.

---

## Testing

- `pytest-django` + `factory_boy`. Real Postgres test DB — no mocking the database.
- See `docs/engineering/testing-strategy.md` for the critical test case list (ported unchanged from the original — the business rules didn't change).
