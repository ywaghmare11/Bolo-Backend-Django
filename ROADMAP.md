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

## Phase 7 — Cross-entity search — SUPERSEDED, see `docs/api/api-spec.md` §13

> **Built 2026-08-12, to a different design than the plan below.** This section described the plan *before* `docs/` was re-synced from upstream on 2026-08-03; that sync brought in `api-spec.md` §13 and `docs/api/global-search-ai-contract.md`, verified directly against the real `bolo-backend` source — a materially different, already-shipped design (two endpoints, not one; Task+Sticky only, not four entity types; an OpenAI `gpt-4o-mini` query-understanding layer + plain `ILIKE`, not Postgres FTS/`pg_trgm`). Flagged as a real conflict rather than silently picked; the user chose "build to api-spec.md's contract, with real OpenAI" over this plan. Same kind of deliberate-deviation note as `docs/ops/security.md`'s auth section. Implemented in `apps/search/` — see `changelog.md`'s 2026-08-12 entry for the full breakdown. The bullets below are kept for reference/talking-point value only; they were **not** built.
>
> - ~~Add a `search_vector` (`SearchVectorField`) to `Task`, `StickyNote`, `Comment`, `BroadcastNotice`; populate via a `pre_save`/`post_save` signal or a Postgres trigger (`django.contrib.postgres.indexes.GinIndex`)~~
> - ~~Enable `pg_trgm` extension (migration: `TrigramSimilarity` for typo-tolerant partial matches, e.g. "meting" → "meeting")~~
> - ~~Single `GET /api/v1/search?q=...` endpoint: fan out across the four search-enabled models (tenant-scoped!), rank with `SearchRank`, merge + paginate results by type~~
> - ~~GIN index on each `search_vector` column~~
>
> **Talking point, still valid even though this exact plan wasn't built:** why Postgres FTS instead of Elasticsearch at this data volume (no second service to run/sync/monitor, ACID-consistent with the source data — no reindex lag — and `pg_trgm` covers the fuzzy-match case Elasticsearch would otherwise be reached for). The design that *was* built raises the adjacent talking point instead: why an LLM query-understanding layer in front of plain `ILIKE` rather than Postgres FTS/trigram ranking — cheaper to reach acceptable fuzzy-match quality without a `search_vector`/GIN-index migration, at the cost of a real external dependency (cost, latency, data leaving India for the OpenAI call) and non-deterministic behavior that the deterministic Levenshtein-fallback layer exists specifically to bound.

---

## Phase 8 — Notifications, Celery, Redis — complete, see `changelog.md` 2026-08-16

- [x] `Notification` model + `dispatch_notification()` service — the only write path, called from every task/broadcast state-changing service (built in Phase 2/3)
- [x] Celery + Redis as broker (built in `feature/roadmap-hardening`, 2026-07-23)
- [x] `TASK_REMINDER` (manual, `POST /tasks/:id/remind`) — built in Phase 3
- [x] Celery beat: daily cron scanning tasks for `TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE` → in-app notification + email — `apps/tasks/tasks.py:task_due_proximity_sweep`, built 2026-08-12. Also closes a related latent gap found while building it: the `OVERDUE`→`OPEN`/`IN_PROGRESS` auto-revert-on-due-date-edit business rule had no implementation until this session, since nothing had ever set `OVERDUE` before.
- [x] `apps/sticky_notes/tasks.py:sticky_note_reminder_sweep` — `REMINDER_FIRED` for `StickyNote.dueAt`, same session (not originally itemized in this phase, but the same "due-proximity sweep" shape, and `REMINDER_FIRED` had been sitting unbuilt since the Sticky Notes slice)
- [x] Task retry policy: `autoretry_for=(SMTPException,)`, exponential backoff, max retries — and idempotency via persisted one-shot DB guards (`Task.due_today_notified_at`/`due_tomorrow_notified_at`, `StickyNote.reminder_fired`), not a cache/TTL — don't double-send if a retry fires after a partial success
- [x] `AI_NUDGE_FOLLOWUP`/`AI_NUDGE_DUE_PROXIMITY` — the recurring skip-cap/escalation nudge feed (`GET /nudges`, `POST /nudges/:id/skip`, `POST /nudges/skip-all`, `NudgeSkipCounter`) — built 2026-08-16, `apps/notifications` (`nudge_rules.py`, `services.py:NudgeService`, `tasks.py`'s two Celery beat sweeps). Not built: the "first-login-of-the-day fast-track" interval-gate bypass from `domain-model.md` — designed for the original Node backend's single continuous-tick sweep, doesn't map onto this project's fixed-crontab-per-sweep-type shape; see `changelog.md` 2026-08-16.
- [x] **General Notification panel** (`GET /notifications`, `PATCH /notifications/:id/read`, `POST /notifications/mark-all-read`, `GET /notifications/unread-count`) — this phase's own bullets above never itemized it, but it's been in `docs/api/api-spec.md` §11 since Phase 1 and had zero views/urls until this session found the gap during a 2026-08-22 docs re-sync. Built 2026-08-22, `apps/notifications` (`NotificationService`, mounted at `/api/v1/notifications/` alongside the `/api/v1/nudges/` mount already there). `dispatch_notification()` — the write side — needed no changes; this only added the read API on top of it.

**Talking point:** idempotent task design — a Celery task can and will run more than once (worker crash after side-effect but before ack); design the notification-send to be safe to repeat (dedupe key, or check-then-act guarded by a unique constraint) rather than assuming exactly-once delivery. What was actually built: persisted per-row "already notified" flags, set only after a successful dispatch — a retry after a mid-sweep failure only reprocesses rows that never got marked, which is naturally idempotent without needing a separate dedupe-key table.

---

## Phase 9 — OpenAI: natural-language task extraction — complete, see `changelog.md` 2026-08-24 (2), branch `feature/openai-task-extraction` (not yet merged/pushed — held per user request pending walkthrough)

- [x] `POST /api/v1/tasks/extract` — raw text (voice transcript or typed input) in, `{title, assigneeHint, dueDate, priority}` suggestion out for a create-task form to pre-fill; never persists a task itself. `apps/tasks/ai_extract.py` (new), `docs/api/api-spec.md` §23 (new — no upstream equivalent to port).
- [x] **Documented choice: synchronous call with a tight timeout (`AI_TIMEOUT_SECONDS = 8`), not a Celery job the frontend polls.** This phase's own two bullets below presented both as options; Celery's job-id/poll shape would need a second endpoint (`GET /tasks/extract/:jobId`) this project's contract doesn't have, purely to work around a call that already degrades in-process. Matches `apps/search/ai_classify.py`'s existing precedent (same synchronous-plus-timeout shape, already proven in this codebase for Search).
- [x] Fallback: `OPENAI_API_KEY` unset (this dev sandbox's actual state), an AI timeout/error, or malformed/non-dict AI JSON all resolve to the same all-`null` response — always `200`, never blocks or errors task creation. One mockable boundary, `call_openai_extract()`, isolates the real `openai` package call, mirroring `apps/search/ai_classify.py:call_openai_classify`.
- [x] `assigneeHint` is the extracted name as-is, **not** resolved against the tenant roster (deliberately simpler than Search's Levenshtein/roster-grounded `resolve_person` — the frontend's own assignee picker does that lookup; a wrong hint here just means picking a different dropdown entry, never a silently wrong assignment).
- [ ] Redis prompt caching — left as the documented optional talking point this phase itself flagged as optional; not built. **Deferred to real AWS production deployment** (see "Future — Production Deployment on AWS" below) — Redis already exists in this project (Celery broker + `django-redis` cache backend), so wiring this in later is a small, self-contained addition once there's real production traffic/cost to justify caching against, not a missing dependency.

**Talking point:** graceful degradation — the core product (create a task) must work with OpenAI completely down. This is the difference between "I called an API" and "I designed a resilient integration."

---

## Phase 10 — Audit logging + observability — complete, see `changelog.md` 2026-08-25, branch `feature/structured-logging-observability` (not yet merged/pushed)

- [x] **Audit logging half was already built** — back in `feature/roadmap-hardening` (2026-07-23), as a generic `AuditLogMiddleware` + static route-config table (`apps/common/audit_middleware.py`/`audit_route_config.py`), not `AuditService.log()` calls from the service layer as this bullet originally described. Deliberately the opposite shape, matching upstream's own 2026-07-14 W98/W99 redesign — see CLAUDE.md Architecture Rules point 8. Nothing rebuilt here; this session's own investigation confirmed it was already the real gap-free implementation, not a stale doc claim.
- [x] **Structured logging (`structlog`) with request-id/tenant-id/actor-id correlation** — the actual gap (there was a literal `# TODO(structlog): swap once structlog lands` comment sitting in `config/exception_handler.py`, and no `LOGGING` dict existed in settings at all). New `apps/common/logging_middleware.py:RequestLoggingMiddleware`, genuinely first in `MIDDLEWARE`, binds `request_id`/`method`/`path`/`actor_id`/`tenant_id` to `structlog.contextvars` for the whole request and logs one `request_finished` summary line per request matching `guidelines.md`'s documented JSON shape exactly. Both `structlog.get_logger()` calls (this project's own code) and plain stdlib `logging.getLogger()` calls (Django/Celery/third-party internals) render through the same JSON formatter and pick up the same contextvars — verified live: even Django's own internal error log line came out carrying `tenant_id`/`actor_id`/`request_id`.
- [x] **Celery task start/finished/failed logging** — via `task_prerun`/`task_postrun`/`task_failure` signal handlers in `config/celery.py`, not hand-added log calls inside each of the ~6 existing `@shared_task` functions across `apps/{tasks,notifications,broadcasts,sticky_notes,common}/tasks.py`. Same "generic observer, hook in once" shape as the audit middleware.
- [x] **Real bug found and fixed while building this**: `decode_access_cookie()` (the helper both middlewares use to read caller identity outside DRF's request wrapper, moved to new `apps/common/request_identity.py`) indexed `token["userId"]`/`token["tenantId"]` unguarded — the exact same class of bug already fixed once in `apps.auth.authentication.CookieJWTAuthentication` (2026-08-23, `PlatformAdmin`'s `admin_token` presented as the tenant cookie). It was latent in `audit_middleware.py` since July because that middleware only decodes the cookie for routes present in `AUDIT_ROUTE_CONFIG`; the new logging middleware calls it on *every* request, immediately exposing it via a real test failure. Fixed with the same claim-presence guard, caught by a new cross-auth-space regression test rather than a bug report.
- [ ] `django-prometheus` metrics, Sentry — scoped out this pass, user's explicit call: both need a real external account (metrics scraper / Sentry DSN) this dev sandbox doesn't have, so they'd be inert config with nothing to verify against, unlike `structlog` which is fully self-contained and demoable today. **Deferred to real AWS production deployment**, not dropped — see "Future — Production Deployment on AWS" below for the concrete plan (real Sentry DSN vs. `django-prometheus`+Grafana vs. AWS-native CloudWatch/X-Ray, decided against real infra, not guessed now).

**Talking point:** audit log is written via a Celery task (`write_audit_log_task.delay(...)`), fire-and-forget, **not** the same DB transaction as the business change it records — documented in `guidelines.md`'s Audit Logging section as the deliberate trade-off (Django has no equivalent of Express's post-response hook, so a queued Celery task after the response is formed is the idiomatic substitute for "never blocks or rolls back the parent request"). Know this was a documented choice, not an oversight, when asked about it.

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

## Future — Production Deployment on AWS (tracked, not yet a phase — added 2026-08-25)

Not scheduled with a phase number yet — this is a holding area for the pieces that were deliberately deferred during Phases 1-13 specifically because they need **real infrastructure/accounts** to mean anything, rather than being missing effort. Per user direction: build these for real once this backend actually gets deployed to AWS, not guessed at now against nothing. Consolidated here so they aren't scattered/lost across individual phase notes:

- **Error tracking**: either a real Sentry account (`sentry_sdk.init(dsn=SENTRY_DSN)`, gated exactly like `OPENAI_API_KEY` — empty by default, flips on with zero code change once a real DSN exists) or AWS-native (CloudWatch alarms off structured log patterns, since every log line is already JSON with a `level` field — see Phase 10). Decide once real AWS account/budget constraints are known, not before.
- **Metrics/dashboards**: `django-prometheus` + self-hosted Grafana (if running on ECS/EKS/EC2) vs. AWS-native CloudWatch Metrics + a Grafana-on-AWS-Managed-Grafana dashboard. Same "decide against real infra" reasoning as above — the two options have different operational costs that only matter once there's a real AWS account to weigh them against.
- **Log shipping/aggregation**: right now (Phase 10) every log line is structured JSON written to stdout/stderr with nowhere for it to go — that's correct and complete for local dev, but on AWS this becomes close to free: ECS/Fargate's container log driver ships stdout straight to CloudWatch Logs with no application code change at all, since the JSON format was chosen specifically so this step costs nothing later (see the Phase 10 walkthrough in `changelog.md` 2026-08-25 for the full reasoning).
- **Redis prompt caching** (Phase 9's optional talking point) — small, self-contained addition once there's real production request volume/OpenAI cost to justify caching against; Redis already exists in this project for Celery + `django-redis`, so this isn't a new dependency, just deferred tuning.
- Also relevant when this becomes real: `docs/ops/deployment.md` is explicitly reference-only (an AWS/OpenShift narrative inherited from the original Node backend's docs, per CLAUDE.md) — this project's actual AWS pipeline will need its own real runbook written against whatever this Django app's real deployment target turns out to be (ECS vs. EKS vs. EC2+gunicorn, RDS Postgres, ElastiCache Redis, S3/SES already IAM-role-ready per `CLAUDE.md`'s env var table), not assumed from that inherited doc.

---

## Phase 15 — Platform Admin Console: 3-tier RBAC, audit trail, multi-format onboarding (added 2026-08-23)

Not in the original roadmap — this phase exists because `PlatformAdmin`'s real purpose only became clear once the actual business model was spelled out (see `changelog.md` 2026-08-23 (2) and (3) for the full narrative). Worth stating precisely, because it's the single best "how did you think about multi-tenancy" interview answer this project has:

> **Integrate18** (the vendor/dev shop building BOLO) delivers the product to **AIBIGO Institute Pvt Ltd** (the client). AIBIGO is not a `Tenant` — AIBIGO *operates* BOLO as a business, onboarding their own customers (colleges, CA/CS firms) as `Tenant` rows. This is a standard **B2B2C / operator-reseller** SaaS shape (same pattern as Shopify Plus + agencies, or a white-label LMS vendor whose client resells seats to individual schools) — three distinct access tiers, not two:

| Tier | Who | Mechanism | Status |
|---|---|---|---|
| 1. Vendor/infra | Integrate18 engineers | Django's built-in `/admin/` (`is_staff`/`is_superuser`) | Already exists, free from Django |
| 2. Operator/superadmin | AIBIGO's own ops team | `PlatformAdmin` (`admin_token`, `apps/platform_admin`) | Core CRUD built 2026-08-23 — see below for what's left |
| 3. Tenant-internal | Each college/firm's own staff | `TenantMembership.role_level` (`TOP`/`MID`/`EXECUTOR`) | Built since Phase 1 |

### 15a — RBAC on `PlatformAdmin` itself

- `PlatformAdmin.role` field. **Scope decision (2026-08-23): implement `SUPER_ADMIN` only for now** — AIBIGO's first ops person is the only real actor today; add `SUPPORT_ADMIN`/`VIEWER` later if/when AIBIGO actually needs to split access within their own team, not speculatively.
- Carried in the JWT payload (`{adminId, email, isPlatformAdmin, role}`) — no extra DB hit per request, same pattern as tenant-user `roleLevel`.
- A `HasPlatformAdminRole([...])` permission-class factory, structurally identical to the existing `HasOrgRole([...])` factory (`apps/common/permissions.py`) — same shape, one tier up. Even with only one role today, build the factory now so adding a second role later is a one-line change at each protected view, not a refactor.

### 15b — Un-defer: `AuditLog` for `PlatformAdmin` actions

Deferred on 2026-08-23's initial build as out of scope; **re-scoped in per the corrected business model** — once AIBIGO's own team (not Integrate18) is the one creating tenants and adding/removing members, "who at AIBIGO did what, when" is a real accountability requirement, not a nice-to-have. Requires extending the generic audit middleware (`apps/common/audit_middleware.py`) to resolve a **second actor source** — it currently only decodes the tenant-user `token` cookie to find `actorId`/`tenantId`; it needs an equivalent path for `admin_token` → `actorType: PLATFORM_ADMIN`, `actorId: null` (a `PlatformAdmin` isn't a `User` row), with the admin's identity captured in the audit row's `metadata` instead. `AuditAction.TENANT_CREATED`/`MEMBER_ADDED`/`MEMBER_REMOVED` already exist in the enum (confirmed present since Phase 1) — this is config-table wiring, not new schema.

### 15c — Multi-format bulk import (Excel `.xlsx` + CSV + JSON) — a small ETL pipeline

This is deliberately framed as **ETL (Extract → Transform → Load)**, not "file upload handling" — it's the same shape as a real data-engineering pipeline, just small-scale, and that's the correct term to use for it (resume/interview value: "built a multi-format data ingestion pipeline" is a stronger, more precise claim than "added CSV import").

```
EXTRACT              TRANSFORM                                    LOAD
────────             ─────────────────────────────────            ────
.xlsx ──┐            1. Normalize headers                         Validated,
.csv  ──┼─► DataFrame 2. Clean/coerce types                   ──►  deduped rows
.json ──┘            3. Validate (vectorized where possible)       → Django ORM
                      4. Dedup within file                           upsert
                      5. Neutralize formula-injection risk
```

**Extract** — one shared output shape regardless of source format:
- Excel: `pd.read_excel(file, engine="openpyxl")`. Real gotchas to handle, not just the happy path: multiple sheets (which one is the data?), a title row above the real header row, merged cells producing `NaN` in the cells beneath them.
- CSV: `pd.read_csv(file, encoding="utf-8-sig")` — the `-sig` variant eats a UTF-8 BOM automatically (the most common "why did my first header get mangled" bug from Excel-exported CSVs); fall back to `latin-1` on `UnicodeDecodeError`.
- JSON: plain `json.loads()` + a DRF serializer, not pandas — JSON is already structured, so pandas' value-add (handling messy tabular data) doesn't apply here. Worth being explicit about this choice rather than reaching for pandas everywhere by default.
- New dependency: `pandas` (+ `openpyxl`, already implied by the Excel engine above).

**Transform** — the substantive part:
```python
# Header normalization -- map every messy real-world variant to one canonical name
df.columns = df.columns.str.strip().str.lower()
df = df.rename(columns={"e-mail": "email", "email address": "email", "role": "role_level", ...})

# Type coercion -- a "boolean" column from Excel/CSV is never actually a bool
BOOL_MAP = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}
df["can_broadcast"] = df["can_broadcast"].astype(str).str.lower().map(BOOL_MAP).fillna(False)

# Vectorized validation -- fast because it's not a per-row Python loop
df["email_valid"] = df["email"].str.match(EMAIL_REGEX, na=False)
df["role_valid"] = df["role_level"].isin(["TOP", "MID", "EXECUTOR"])  # unknown value -> reject
                                                                        # that row only, never
                                                                        # let it reach the ORM
                                                                        # (same defense-in-depth
                                                                        # principle Global Search's
                                                                        # status/priority handling
                                                                        # already uses)

# Dedup within the file -- last occurrence wins, earlier ones reported as skipped
dupes = df.duplicated(subset=["email"], keep="last")

# CSV/Excel formula injection (a real, under-known security issue): a cell starting with
# =/+/-/@ can execute as a formula if this data is ever re-exported and reopened in Excel
# by another admin -- neutralize on ingest, defense-in-depth even with no re-export feature yet
RISKY_PREFIXES = ("=", "+", "-", "@")
df["name"] = df["name"].apply(
    lambda v: f"'{v}" if isinstance(v, str) and v.startswith(RISKY_PREFIXES) else v
)
```

**Load** — idempotent upsert, chunked, one DB transaction per chunk (not the whole file) so a mid-import crash leaves a clean, known boundary rather than an ambiguous partial state:
```python
for _, row in valid_rows.iterrows():
    User.objects.update_or_create(email=row["email"], defaults={"name": row["name"], ...})
```

**Response shape** — structured reporting, not a boolean success/fail:
```json
{ "created": 12, "updated": 3, "skipped": 1, "errors": [{"row": 5, "field": "roleLevel", "reason": "must be TOP, MID, or EXECUTOR"}] }
```

**Talking point:** the difference between "I used pandas to read a file" and "I designed an ETL pipeline" is entirely in the Transform stage above — vectorized validation (not naive row-by-row loops, which shows you understand *why* pandas is fast, not just that it's a library that reads Excel), defensive type coercion against real-world messy input, and the formula-injection handling, which most engineers doing a "quick CSV import" have never even heard of.

### 15d — Platform Admin Console: standalone React app

**Decision (2026-08-24, reconsidered from an earlier "build inside `bolo-web`" instinct):** a **separate, standalone React app** — its own repo, own `Vite` scaffold, own deploy, talking to this Django backend purely over `/api/v1/platform-admin/*`. Chosen deliberately over the `bolo-web`-embedded option for two reasons: (1) it's a self-contained artifact — demoable end-to-end without touching `bolo-web` at all, a cleaner standalone portfolio piece than "routes added to an existing app"; (2) the real security boundary (a valid `admin_token`, checked server-side on every request) is identical either way, so embedding it in `bolo-web` bought little beyond reusing its design system — a cost worth paying here for a cleaner, independent build.

- **New repo/project**: `npm create vite@latest bolo-admin-console -- --template react-ts`. TanStack Query for data-fetching (same convention `bolo-web` already uses, kept for consistency even though this is a separate codebase). A thin `fetch`/`axios` API client pointed at this backend's `/api/v1/platform-admin/*`, always `credentials: "include"` so the httpOnly `admin_token` cookie rides along automatically — the app itself never reads or stores the token.
- **New backend endpoint needed**: `GET /platform-admin/auth/me` — doesn't exist yet. Lets the SPA ask "am I still logged in, as who" once on page load, without hitting a real data endpoint first. Belongs with 15a/15b as backend prep before the frontend needs it.
- **Pages**: `/login` (email → "Send OTP") → `/otp` (6-digit code, resend-in-60s countdown matching the backend's real cooldown) → `/dashboard` (tenant list: name, vertical, member/department counts) → `/tenants/new` (create-tenant form, debounced live `urlSlug` availability check before submit) → `/tenants/:id` (member table + "Add Member" modal + "Bulk Import" modal).
- **Auth flow**: a top-level route guard calls `GET /platform-admin/auth/me` on load — `401` redirects to `/login`, `200` renders the app and caches the admin's identity in the query cache. A global fetch/axios response interceptor handles `401` from any call the same way, so the redirect logic lives in one place.
- **Bulk-import UI** (the component worth the most polish — best interview talking point of the frontend half): drag-and-drop (or plain file input) accepting `.xlsx`/`.csv`/`.json` → upload immediately, no client-side parsing (the backend's ETL pipeline in 15c does all of it) → a **results table**, one row per import row, `[Row #, Status, Detail]`, green check for created/updated rows, red X with the specific reason for errors → a "Download failed rows" button that serializes the response's `errors[]` array back into a downloadable CSV client-side, so the admin can fix just those rows and re-upload.

**Talking point:** the corrected business model (Integrate18 → AIBIGO → their tenants, §Phase 15 intro above) is the strongest thing to lead with here — it demonstrates reasoning about *who the actual actors in a system are*, not just implementing whatever a spec says. Pair it with the ETL formula-injection handling (15c) as your "I thought about the edge case nobody asks about" answer, and the standalone-app decision itself as a "here's a tradeoff I made deliberately, and here's why" answer.

---

## Suggested order to actually build in

Phases 0-3 first (bootstrap → models → auth → tasks) get you a working, demoable core. Phases 4-9 (pagination, supporting entities, broadcasts, search, notifications, OpenAI) are the "impressive feature" layer — build in whatever order keeps you motivated, they're mostly independent of each other once Phase 3 exists. Phases 10-14 (audit/observability, testing, caching, docker/CI, cheat-sheet) should be woven in continuously, not left to the end — "I wrote tests as I went" is a better interview answer than "I added tests at the end."

**Phase 15 (Platform Admin Console) is deliberately sequenced *after* Phases 9-14 (2026-08-24 decision)** — the leftover core-backend phases (OpenAI extraction, observability/`structlog`, caching, Docker/CI, the interview cheat-sheet) finish the main `bolo-backend-django` story before starting a second, separate frontend project. Within Phase 15 itself, once its turn comes: 15a (RBAC) and 15b (audit trail) are small and worth doing before 15c/15d grow the surface area; 15c (the ETL import pipeline, backend) and 15d (the standalone React app, frontend) are independent of each other and can build in either order once 15a/15b land.
