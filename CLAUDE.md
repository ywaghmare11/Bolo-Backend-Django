# BOLO-BACKEND-DJANGO — CLAUDE.md

> Read this file completely at the start of every Claude Code session.
> This is the single source of truth for **this project only**.
> **This is a standalone Django + DRF re-implementation of the BOLO backend** (originally Node/Express/Prisma, in the sibling `Bolo/` repo). It is a **port, not a redesign** — same API contract, same domain model, same business rules. `bolo-web` (React, in the original `Bolo/` repo) is a completely separate project and only talks to whichever backend is running over HTTP, via `VITE_API_URL`. Nothing in `bolo-web` needs to change for this project to work, as long as the contract in `docs/api/api-spec.md` is honored exactly.
> **Last updated:** 2026-07-22 — re-synced `docs/` again from the original repo (docs-only, no code touched): `ops/deployment.md`'s rollback narrative moved to new `ops/staging-runbook.md`, new `api/global-search-ai-contract.md` added (draft, Phase 7-relevant), broadcast image confirm now needs an explicit `s3Key` in the request body. Multi-department broadcast audience scope and `GET /tenant/roles` are present in both this project's docs and upstream `main` — an initial pass of this sync incorrectly reported them as reverted/missing (stale read, corrected same day, see `changelog.md`). `docs/ops/security.md` was deliberately left untouched (still carries this project's own access+refresh-token deviation). Previously: 2026-07-19 — Phase 2 complete: `common` app foundation (response envelope, exception handler, pagination, permissions), OTP→JWT auth (`apps/auth`), and a core Task lifecycle vertical slice (`apps/tasks` + minimal `apps/labels`), see `changelog.md` for the full breakdown. **Deliberate deviation from `docs/ops/security.md`'s locked W1 decision:** the user asked for real access+refresh token handling beyond the original's single long-lived cookie — implemented as a 15-min JWT access token + rotating opaque refresh token with reuse-detection; `docs/ops/security.md`'s Authentication section was rewritten to match, so it no longer contradicts the code. Audit logging (Architecture Rules point 8) is still deferred — not built this phase. Subtasks, comments, evidence, voice recording, and full label CRUD are Phase 3. Before that: 2026-07-18 — re-synced `docs/` from the original repo and reworked Phase 1 models to match the drift found (label model redesign, new `platform_admin` app, `User`/`NudgeSkipCounter` field changes, new enum values); Phase 1 (domain models) complete before that.

---

## What Is This App?

**BOLO** (internal/legacy name: Fatafat) is a lightweight, web-based task & delegation app for Indian teams. Full product context, entities, and business rules are in `docs/` (copied from the original repo — see `docs/README.md` for what's here and why).

- **NOT** a project management tool — no Gantt, no resource planning, no time tracking
- Task is the hero — create one in seconds with just **title + assignee**
- Two verticals: **Education** (Dean/HoD/Faculty) and **CA/CS / Industry** (Director/HoD/Employees)
- India-first: multilingual, voice-first task creation (voice transcription happens client-side in `bolo-web`; this backend only stores/serves what it's given)
- All notifications are **in-app only**, except reminder/due-date types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`), which also send **email**.

**Client:** AIBIGO Institute Pvt Ltd.

---

## Relationship to the Original Repo

| | Original (`Bolo/`) | This project (`bolo-django/bolo-backend-django/`) |
|---|---|---|
| Backend | `bolo-backend` — Node + Express + Prisma | Django + DRF (this repo) |
| Frontend | `bolo-web` — React + Vite | none — pure API, consumed by `bolo-web` over HTTP |
| Database | Shared Postgres instance (Prisma-owned migrations) | **Its own fresh Postgres database** — Django owns migrations from scratch, schema mirrors `docs/reference/schema.prisma.reference` table-for-table (same table/column names, so the wire contract stays identical) |
| Docs | `docs/` (git-ignored, local source of truth) | `docs/` copied in at scaffold time — treat as the binding contract for API shape and business rules; **not** a place to invent new rules |

**Do not assume this project reads or writes to the original repo's database.** They are two fully independent deployments of the same product spec. If you need current business-rule context beyond what's in this repo's `docs/`, the original repo lives at `/home/test/Desktop/Python_Project/BOLO/Bolo` (its Node backend at `.../BOLO/Bolo/bolo-backend`) — read its `CLAUDE.md`/`docs/` for extra background, but this repo's copies are what govern implementation here. **Note (2026-07-18):** the sibling repo is reachable again at the path above (moved since the 2026-07-14 Windows→Linux migration, when it was not present) — `docs/` was re-synced from it on this date; re-check for drift periodically rather than assuming this repo's copy stays current on its own.

---

## Task Protocol — Every Session, Every Task

### Before starting any task
State in 2–3 sentences: what the task is, what you're going to do, and what the expected outcome is, before the first tool call.

### After completing any task
State in 1–2 sentences: what was done and what files changed.

---

## Mandatory Doc Lookup — Before Any Implementation

| Task type | Must read first |
|---|---|
| Any feature | `docs/product/prd.md` → `docs/architecture/domain-model.md` |
| Any code (always) | + `guidelines.md` (repo root) — naming, DB rules, response shapes, app/folder structure |
| Endpoint / serializer work | + `docs/api/api-spec.md` (exact request/response shape — do not deviate) |
| Model / migration | + `docs/architecture/domain-model.md` + `docs/reference/schema.prisma.reference` (port field-for-field) |
| Auth / security | + `docs/ops/security.md` |
| Notifications | + `docs/api/api-spec.md` §11 (notification-types table) |
| Deployment / infra | + `docs/ops/deployment.md` (reference only — this project's actual pipeline will differ) |
| Testing | + `docs/engineering/testing-strategy.md` |
| Git / branching / PRs | + `docs/engineering/git-workflow.md` |

**Never assume** — if a field, rule, or constraint seems wrong or missing, check `docs/product/open-questions-web-v1.md` first.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | Django + Django REST Framework | REST API only, no server-rendered templates |
| Database | PostgreSQL | Own fresh instance/DB — not shared with the original `bolo-backend` |
| ORM / migrations | Django ORM + Django migrations | Models mirror `schema.prisma.reference` field-for-field |
| Auth | Email OTP → JWT | Custom `CookieJWTAuthentication` (DRF's `SimpleJWT` defaults to header auth — this app needs httpOnly cookie, matching the original contract). No passwords stored. |
| Async / background jobs | Celery + Redis | Notification dispatch, broadcast fan-out, reminder/due-date cron, daily analytics pre-compute |
| API docs | drf-spectacular | OpenAPI schema generated from code — keep in sync with `docs/api/api-spec.md`, don't let them drift |
| Object storage | S3-compatible via `boto3` | Evidence files via pre-signed URLs, same as original |
| Transactional email | AWS SES via `boto3` | Reminder/due-date types only (see Business Rules). Matches the original's 2026-07-18 decision (was SMTP/nodemailer) — IAM-role-only via the default credential provider chain, same pattern as S3, no separate SMTP secret to manage |
| Env config | `django-environ` | `.env` per environment, validated at startup — crash early if a required var is missing |
| Testing | `pytest-django` + `factory_boy` | Real Postgres test DB, no mocking the database |
| Serialization | DRF serializers | One serializer per direction where request/response shapes differ (see api-spec.md) |

---

## Architecture Rules (NEVER break)

This project keeps the **same strict layering discipline** as the original Node backend, even though it's not Django's default idiom ("fat models" / views calling the ORM directly). This is a deliberate choice for consistency and testability — don't relax it because "Django doesn't normally do this."

### Controller → Service → Repository (STRICT — same as original)

1. **View** (`views.py` / DRF `APIView` or `ViewSet`): HTTP only — parse the request, call the service, return the response via the shared envelope helper. No business logic. No ORM calls.
2. **Service** (`services.py` or `services/`): business logic only. No `request`/`response` objects. No direct Django ORM calls — calls the repository. **Services never call an audit-log function directly** — see the Audit Logging rule below (point 8), which is the opposite pattern from Notifications (point 7).
3. **Repository** (`repositories.py` or `repositories/`): the only place `Model.objects....` / QuerySets are touched. No business logic — just queries, always filtered by `tenant_id` where applicable.
4. Always return via the shared response helper — never a raw DRF `Response({...})` built ad hoc in a view.
5. Permission classes (DRF `permissions.py`) on every view — no exceptions. Tenant scope is the universal guard; org-role checks use a custom `HasOrgRole` permission; task-level (assigner/assignee) checks live in the service layer.
6. `tenant_id` always comes from the decoded JWT (via the custom authentication class, exposed as `request.tenant_id`) — **never** from the request body or query params.
7. **Every service that changes task, subtask, or broadcast state — check `docs/api/api-spec.md` §11 for whether a `Notification` should fire.** Wire it through a `dispatch_notification()` service call — never a raw `NotificationRepository.create()` and never inline email logic. If the event type isn't in the table yet, add it there before wiring the call site.
8. **Audit logging is generic, not dispatched.** Matches the original's 2026-07-14 redesign (W98/W99) — deliberately the *opposite* pattern from point 7's Notifications. A DRF middleware (`apps/common/audit_middleware.py`, planned) paired with a static route-config table (`apps/common/audit_route_config.py`, planned — one row per `{method, resolver_match.view_name}` → `{entity_type, model, action | resolve_action(before, after)}`) observes every mutating request generically: reads before-state via the configured model before the view runs, captures after-state from the response body, and writes the `AuditLog` row only if the response succeeded (`status_code < 400`) — queued as a Celery task so the write never blocks the response (Django has no direct equivalent of Express's post-response hook; a fire-and-forget Celery task is the idiomatic substitute). **No service or view ever calls an audit-log function directly** — a new mutating route gets audited by adding one row to the config table, not by editing the handler. **The one documented exception:** login/logout has no entity mutation for the middleware to observe, so `User.last_login_at`/`last_logout_at` are written directly by the auth service for their own legitimate session-tracking purpose, and the middleware picks up `USER_LOGIN`/`USER_LOGOUT` off of *that* write the same generic way as everything else.

Response helpers (always — never a raw `Response({...})`):
```python
return success_response(data, "Task created")               # 200
return success_response(data, "Created", status=201)         # 201
return failure_response("Not found", status=404, code="TASK_NOT_FOUND")  # 4xx
```

---

## Business Rules (encode these exactly — ported from the Web PRD v1.1, unchanged)

### Task Rules
- Task needs only **title + assignee** to create (saves as Draft). **Due date is required to transition Draft → Open.**
- **Assigner (Delegator)** can: edit assignee, due date, priority, main label, description; comment; attach evidence; send reminder; mark complete (DoneD); cancel; delete; reassign. **Cannot** create subtasks. **Cannot** edit title.
- **Assignee** can: write progress comments, attach evidence, mark complete (DoneA), create subtasks, set their own private label.
- **Label model (redesigned — no separate personal-label table):** a single `ProjectLabel` pool per creator, referenced by two FKs on `Task` — `main_label` (assigner sets, visible to everyone who can see the task) and `assignee_label` (assignee sets, private, never returned to non-assignees, cleared on reassignment). Each user sees only labels they created (`created_by = request.user`). Deleting a label in use is blocked (`on_delete=PROTECT`).
- **Two-step completion:** assignee marks **DoneA** → assigner marks **DoneD** (archives the task). A main task reaches DoneD only when all subtasks are `DONE_D`.
- Task **cannot be reassigned** once any subtask exists.
- Every task/subtask must be **accepted by the assignee** before work starts. **There is no rejection state.**
- **Title is immutable** after creation — reject any PATCH on title at the serializer/service level.
- Cancelling a parent cascades to all non-`DONE_D` subtasks. A task cannot be cancelled once `DONE_D`.
- Defaults: priority → P3, main label → none, description → empty.

### Role Rules
- Tenant roles (`TOP/MID/EXECUTOR`) set at onboarding per vertical. Task roles (Delegator/Assignee) are per task, derived from `assigner_id`/`assignee_id` — never stored as separate fields.
- Always scope queries by `tenant_id` — never return unscoped data. `tenant_id` from the JWT only, never the body.
- Any user can assign to any other user — no hierarchy restriction enforced (W19 — pending confirmation before enforcing).

### Personal Items (Sticky Notes / Reminders)
- Always private — never shared, never visible to others.
- A `StickyNote` with `due_at` set **is** the reminder — no separate entity.

### Broadcast Notice
- `can_broadcast` flag on `TenantMembership` gates who can post — binary permission, not derived from role level.
- Audience scope (`audience_dept_id` + `audience_role_level`) is **mandatory at publish**.
- Visible for **exactly 1 day** from publish — not configurable.
- **~200 character limit** on visible text; stored as `message_json` (rich text AST) + `message_html` (sanitized).
- **Single image** attachment only.
- Acknowledge increments read count; sender sees COUNT only — no per-person breakdown.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Django apps | snake_case, plural, one per domain area | `tasks`, `broadcasts`, `sticky_notes` |
| Models | PascalCase | `Task`, `BroadcastNotice` |
| Model fields | snake_case | `tenant_id`, `due_at`, `assignee_id` |
| DB tables | snake_case, plural (`Meta.db_table`) | `tasks`, `broadcast_notices` |
| Views/ViewSets | PascalCase + `View`/`ViewSet` | `TaskDetailView`, `TaskViewSet` |
| Services | snake_case module, PascalCase class | `services.py` → `TaskService` |
| Repositories | snake_case module, PascalCase class | `repositories.py` → `TaskRepository` |
| Serializers | PascalCase + `Serializer` | `TaskCreateSerializer`, `TaskResponseSerializer` |
| URLs | kebab-case, plural, versioned | `/api/v1/broadcast-notices/` |
| Files | snake_case | `task_service.py`, `task_repository.py` |
| Env variables | SCREAMING_SNAKE_CASE | `DATABASE_URL` |

---

## Proposed Project Structure

```
bolo-backend-django/
├── manage.py
├── requirements/               # base.txt, dev.txt, prod.txt
├── config/                     # Django project package
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── prod.py
│   │   └── test.py
│   ├── urls.py                 # mounts each app's urls.py under /api/v1/
│   ├── celery.py
│   ├── wsgi.py / asgi.py
│   └── exception_handler.py    # DRF custom exception handler -> failure_response shape
├── apps/
│   ├── common/                 # response helpers, base permissions, pagination, error classes, audit middleware + route-config table
│   ├── platform_admin/         # PlatformAdmin, PlatformAdminOtpCode (cross-tenant superadmin, outside RLS/tenant scoping)
│   ├── tenants/                # Tenant, Department, TenantMembership
│   ├── users/                  # User (incl. last_login_at/last_logout_at/profile_pic_url)
│   ├── auth/                   # OtpCode, JWT issuance/verification, CookieJWTAuthentication
│   ├── tasks/                  # Task (dual-FK main_label/assignee_label), VoiceRecording
│   ├── labels/                 # ProjectLabel (single pool, dual-purpose via Task's FKs)
│   ├── evidence/                # Evidence (S3 pre-signed)
│   ├── comments/                # Comment
│   ├── sticky_notes/             # StickyNote
│   ├── broadcasts/              # BroadcastNotice, BroadcastAcknowledgement
│   ├── notifications/           # Notification, dispatch_notification service, NudgeSkipCounter
│   └── audit/                    # AuditLog (written only by the generic middleware, see Architecture Rules point 8)
│       # each app:
│       #   models.py
│       #   serializers.py
│       #   views.py            (or viewsets.py)  <- controller layer, thin
│       #   services.py         <- business logic
│       #   repositories.py     <- the only place ORM is used
│       #   permissions.py
│       #   urls.py
│       #   tests/
└── docs/                       # copied contract — see docs/README.md
```

---

## Environment Variables (planned)

```bash
DATABASE_URL=postgresql://...          # own DB, not shared with the Node bolo-backend
JWT_SECRET=...
DJANGO_SECRET_KEY=...
REDIS_URL=redis://...                  # Celery broker
S3_BUCKET_NAME=...
SES_FROM_EMAIL=...                     # reminder/due-date emails via AWS SES (boto3, IAM-role-only — no SMTP_* vars)
```

---

## Current Build Status

- [x] `bolo-backend-django/` folder scaffolded
- [x] `docs/` copied in from the original repo (backend-relevant subset — see `docs/README.md`)
- [x] `CLAUDE.md`, `guidelines.md`, `README.md`, `changelog.md` written
- [x] `django-admin startproject` / app scaffolding (`config/` restructured, empty `apps/` package created)
- [x] `requirements` files + virtualenv (Python 3.12.0)
- [x] Django settings (base/dev/prod/test) + env validation (`django-environ`, fresh local `bolo_django` Postgres DB)
- [x] Models ported from `docs/reference/schema.prisma.reference`
- [x] Initial migration against a fresh local Postgres DB
- [x] Custom `CookieJWTAuthentication` + OTP flow (plus access+refresh token rotation — a deliberate deviation from `docs/ops/security.md`'s original W1 decision, see `docs/ops/security.md` and `changelog.md` 2026-07-19)
- [x] `common` app: response helpers, exception handler, base permissions, pagination (audit logging still deferred — see Architecture Rules point 8, not yet built)
- [x] First vertical slice (Auth → Tasks) end-to-end against `docs/api/api-spec.md` — core lifecycle only (create/list/detail/edit/delete/accept/done-a/done-d/cancel/remind + minimal labels); subtasks, comments, evidence, voice recording, full label CRUD, and audit logging are Phase 3

---

## Git Conventions

- Branches: `feature/`, `fix/`, `chore/`
- Commits: `feat:`, `fix:`, `chore:`, `refactor:`
- Never commit directly to `main`
- Log every significant change in this project's own `changelog.md` (tags `[BE]` `[STD]` `[INFRA]` — no `[FE]`/`[PRD]` here, this is backend-only)
