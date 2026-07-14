# bolo-backend-django — Build Roadmap

> This project's real purpose: an interview-ready portfolio piece. "I built a task-delegation SaaS backend — React frontend, Django/DRF backend, Postgres, Redis, Celery, JWT auth, full-text search, and an OpenAI-powered feature." Every phase below is written so you can explain the **why**, not just ship the **what** — that's what gets tested in a 3+ YOE interview.
>
> Decisions locked in for this build:
> - **Search:** Postgres full-text search (`SearchVector`/`SearchRank`) + `pg_trgm` for fuzzy matching — no Elasticsearch. Zero extra infra, still a legitimate senior-level answer.
> - **OpenAI:** Natural-language → structured task extraction ("remind Raj to submit the fee report by Friday" → `{title, assignee_hint, due_date, priority}`), called async via Celery so it never blocks a request, with a timeout + fallback to manual entry if the API fails or times out.

Each phase ends with a **"talking points"** line — memorize these, they're the actual interview answer, not the code.

---

## Phase 0 — Bootstrap

- `python -m venv .venv` + activate, `pip install django djangorestframework psycopg[binary] django-environ`
- `django-admin startproject config .` then restructure into `config/` (settings/urls/celery) + `apps/` per `CLAUDE.md`
- `requirements/base.txt`, `dev.txt`, `prod.txt`, `test.txt`
- `.env.example` + `django-environ` wired into `config/settings/base.py`, split `dev.py`/`prod.py`/`test.py`
- Git init, `.gitignore` (`.venv`, `.env`, `__pycache__`, `*.pyc`)
- Local Postgres: create a **fresh** `bolo_django` database (not the Node backend's DB)

**Talking point:** why settings are split per environment instead of one file with `if DEBUG` branches (explicit is better than implicit, prevents prod accidentally inheriting a dev-only setting).

---

## Phase 1 — Domain models (port from `docs/reference/schema.prisma.reference`)

- One Django app per bounded context: `tenants`, `users`, `auth`, `tasks`, `labels`, `evidence`, `comments`, `sticky_notes`, `broadcasts`, `notifications`, `audit`, `common`
- Every model: UUID PK, `created_at`/`updated_at`, `Meta.db_table` matching the original snake_case table name
- FKs per `docs/architecture/domain-model.md`; self-referencing `Task.parent_task` for subtasks
- `makemigrations` per app, `migrate` against the fresh DB
- Register everything in Django admin (fast way to eyeball data before any API exists)

**Talking point:** why you kept the Node backend's table/column naming even though Django doesn't require it (contract parity — if you ever needed to cut over `bolo-web` to this backend, response shapes are unaffected by internal renames, but keeping DB naming consistent made porting `domain-model.md` mechanical instead of error-prone).

---

## Phase 2 — Auth: OTP + JWT (httpOnly cookie) + Redis-backed throttling

- `OtpCode` model + `AuthService`: generate 6-digit OTP, expiry (5 min), store, email via console backend in dev / SMTP in prod
- `djangorestframework-simplejwt` for token issuance, **custom `CookieJWTAuthentication`** class (simplejwt defaults to `Authorization: Bearer` header — you need httpOnly cookie to match the product's actual security model)
- JWT custom claims: `tenant_id`, `org_role_level` — decoded once per request, exposed as `request.tenant_id`
- Redis-backed DRF throttle (`ScopedRateThrottle` with `CACHES` pointed at Redis) on the OTP-request endpoint — stops OTP-spam abuse
- `HasOrgRole` and `IsTenantMember` custom permission classes

**Talking point:** why JWT lives in an httpOnly cookie instead of `localStorage` (XSS can't read it), and why the rate limiter needs a shared backend like Redis instead of in-memory (in-memory throttling is per-process — useless the moment you run more than one gunicorn worker).

---

## Phase 3 — Tasks: the hero CRUD + query optimization + indexing

- `TaskViewSet` (or generic APIViews) → `TaskService` → `TaskRepository`
- Business rules enforced in the service layer: title immutable, two-step completion (DoneA→DoneD), no reassignment once subtasks exist, cascade-cancel to non-DoneD subtasks, no rejection state
- **Indexes:** composite index on `(tenant_id, status)` (every list view filters both), index on `assignee_id` and `due_at` (dashboard "due this week" query), partial index on `is_archived=False` if Postgres version supports it — document *why* each index exists as a migration comment
- **Query optimization:** `select_related('assigner', 'assignee', 'main_label')` + `prefetch_related('subtasks', 'evidence', 'comments')` in the repository — write a `pytest` test using `django_assert_num_queries` that fails if someone reintroduces an N+1
- Wire `AuditService.log()` for every state transition (create/update/status-change/reassign)

**Talking point:** walk through one query with `EXPLAIN ANALYZE` before/after adding the composite index — this is the single most common senior-Django interview question ("tell me about a time you fixed a slow query").

---

## Phase 4 — Pagination

- Default `PageNumberPagination` (page size 20, max 100) to match the original API contract for most list endpoints
- `CursorPagination` for the infinite-scroll feeds (mirrors `bolo-web`'s `useInfiniteFetch`) — stable ordering key (`created_at`, `id`) required for cursor pagination to be correct under concurrent writes

**Talking point:** page-number vs cursor vs offset pagination trade-offs — page/offset break under concurrent inserts (skipped/duplicated rows), cursor doesn't, but cursor can't jump to "page 5" directly. Pick per endpoint, not globally.

---

## Phase 5 — Supporting entities

- `ProjectLabel` (main labels) + `TaskPersonalLabel` (private, both assigner/assignee can add)
- `Comment` (full CRUD, author-only edit/delete)
- `Evidence` — S3 pre-signed PUT/GET via `boto3`, MIME/extension validated server-side, files never proxied through Django
- `StickyNote` — private, `due_at` set = acts as reminder, no separate reminder entity

**Talking point:** why evidence upload uses pre-signed URLs instead of proxying the file through Django (keeps large uploads off your app server's request/response cycle entirely).

---

## Phase 6 — Broadcast Notices

- `canBroadcast`-gated publish, mandatory audience scope, `message_json` + `message_html` (sanitize with `bleach`)
- Celery beat task: hides/expires notices exactly 1 day after publish (don't rely on a `WHERE published_at > now() - interval '1 day'` filter everywhere — a scheduled job that flips a status is easier to reason about and test)
- `BroadcastAcknowledgement` — COUNT only exposed to sender

**Talking point:** why an actual scheduled job instead of a query-time filter for the 1-day expiry (single source of truth for "is this visible," testable in isolation, and cheap to change to a configurable TTL later).

---

## Phase 7 — Cross-entity search (Postgres FTS + trigram)

- Add a `search_vector` (`SearchVectorField`) to `Task`, `StickyNote`, `Comment`, `BroadcastNotice`; populate via a `pre_save`/`post_save` signal or a Postgres trigger (`django.contrib.postgres.indexes.GinIndex`)
- Enable `pg_trgm` extension (migration: `TrigramSimilarity` for typo-tolerant partial matches, e.g. "meting" → "meeting")
- Single `GET /api/v1/search?q=...` endpoint: fan out across the four search-enabled models (tenant-scoped!), rank with `SearchRank`, merge + paginate results by type
- GIN index on each `search_vector` column

**Talking point:** why Postgres FTS instead of Elasticsearch at this data volume (no second service to run/sync/monitor, ACID-consistent with the source data — no reindex lag — and `pg_trgm` covers the fuzzy-match case Elasticsearch would otherwise be reached for). Know the migration path if scale demanded it later (CDC into ES, or Postgres logical replication).

---

## Phase 8 — Notifications, Celery, Redis

- `Notification` model + `dispatch_notification()` service — the only write path, called from every task/broadcast state-changing service
- Celery + Redis as broker (and result backend for anything you need to poll)
- Celery beat: daily cron scanning tasks for `TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE`/`TASK_REMINDER` → in-app notification + email (SMTP) for those four types only
- Task retry policy: `autoretry_for=(SMTPException,)`, exponential backoff, max retries — and idempotency (don't double-send if a retry fires after a partial success)

**Talking point:** idempotent task design — a Celery task can and will run more than once (worker crash after side-effect but before ack); design the notification-send to be safe to repeat (dedupe key, or check-then-act guarded by a unique constraint) rather than assuming exactly-once delivery.

---

## Phase 9 — OpenAI: natural-language task extraction

- Endpoint accepts raw text (from `bolo-web`'s voice transcript or typed input): `POST /api/v1/tasks/extract`
- Service calls OpenAI (structured output / function-calling to get back `{title, assignee_hint, due_date, priority}`) **inside a Celery task**, not inline in the request — return a job id immediately, frontend polls or the endpoint is synchronous with a tight timeout and Celery is used for retry/backoff instead
- Wrap the call: timeout, retry on transient failure, and a **fallback** — if OpenAI errors or times out, return what was parsed so far (or nothing) so the user can still fill the form manually. Never let an AI-provider outage block task creation.
- Cache identical prompts briefly in Redis if you want to show caching-for-cost-control as a talking point (optional)

**Talking point:** graceful degradation — the core product (create a task) must work with OpenAI completely down. This is the difference between "I called an API" and "I designed a resilient integration."

---

## Phase 10 — Audit logging + observability

- `AuditService.log()` from the service layer only, immutable `AuditLog` rows, structured logging (`structlog`) with request-id/tenant-id/actor-id correlation
- Optional polish: `django-prometheus` metrics, Sentry for exception tracking

**Talking point:** audit log is written in the same DB transaction as the business change it records (or explicitly documented as best-effort if it isn't) — know which one you built and why.

---

## Phase 11 — Testing

- `pytest-django` + `factory_boy`, real Postgres test DB (no DB mocking)
- Service-layer unit tests for every business rule (title immutable, reassignment blocked, cascade cancel, etc.)
- API tests via DRF test client for contract shape
- `django_assert_num_queries` tests on the Task list/detail endpoints — this is your proof-of-work for Phase 3's optimization claims

**Talking point:** a query-count regression test is more valuable than most people realize — it turns "I optimized this once" into "this can't silently regress."

---

## Phase 12 — Caching

- Redis cache-aside for read-heavy, write-light endpoints (dashboard counts, label lists) — explicit `cache.get`/`cache.set` with a documented TTL and invalidation on the relevant write path (not a blanket cache-everything approach)

**Talking point:** cache invalidation strategy — explain exactly which write paths call `cache.delete()`/`cache.set()` and why a TTL alone isn't enough for correctness here.

---

## Phase 13 — Dockerization, CI, API docs

- `docker-compose.yml`: `web` (gunicorn), `worker` (celery), `beat` (celery beat), `redis`, `postgres`
- GitHub Actions: lint (`ruff`), test (`pytest`), `makemigrations --check --dry-run` (catches missing migrations in CI)
- `drf-spectacular` for OpenAPI schema + Swagger UI — keep in sync with `docs/api/api-spec.md`

**Talking point:** `makemigrations --check` in CI — a cheap gate that catches "forgot to commit a migration" before it becomes a production incident.

---

## Phase 14 — Interview cheat-sheet

Once the above is built, write a one-page `INTERVIEW_NOTES.md`: for each starred talking point above, a 2-3 sentence spoken answer. Practice saying them out loud, not just reading them — this is the actual deliverable of this whole roadmap.

---

## Suggested order to actually build in

Phases 0-3 first (bootstrap → models → auth → tasks) get you a working, demoable core. Phases 4-9 (pagination, supporting entities, broadcasts, search, notifications, OpenAI) are the "impressive feature" layer — build in whatever order keeps you motivated, they're mostly independent of each other once Phase 3 exists. Phases 10-14 (audit/observability, testing, caching, docker/CI, cheat-sheet) should be woven in continuously, not left to the end — "I wrote tests as I went" is a better interview answer than "I added tests at the end."
