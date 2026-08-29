# INTERVIEW_NOTES.md — bolo-backend-django

> Phase 14 of `ROADMAP.md`. Spoken answers — the way I'd actually say them out loud in a 3+ YOE
> interview, not doc prose. One "what I built" line per phase, then the Q&A.
> Practice these out loud. Depth lives in `changelog.md`; the deployment runbook is
> `docs/ops/deployment-django.md`.

## One-line pitch

I built a task-delegation SaaS backend end to end: Django + DRF, PostgreSQL, Redis, Celery, OTP→JWT
cookie auth, a global search feature with an OpenAI query-understanding layer, and an OpenAI
natural-language task-extraction endpoint — all Dockerized with a GitHub Actions CI pipeline and a
reference AWS ECS Fargate deploy path. It's a from-scratch re-implementation of an existing
Node/Express/Prisma backend, so the whole thing was built against a fixed API contract, which meant
every decision had to preserve wire compatibility with a React frontend I didn't control.

---

## Phase 0 — Bootstrap

**What I built:** venv + `requirements/{base,dev,test,prod}.txt`, `django-admin startproject` restructured
into `config/settings/{base,dev,prod,test}.py` with `django-environ`, a fresh local Postgres database,
and env-var validation that crashes at startup if a required variable is missing.

**Q: Why split settings per environment instead of one `settings.py` with `if DEBUG:` branches?**
Because `if DEBUG` branches make the dangerous case the implicit one — prod silently inherits whatever
the dev branch set unless someone remembered to write the `else`. With separate files, `prod.py`
starts from `base.py` and has to *opt into* every relaxation explicitly, so a dev-only convenience
like a permissive `ALLOWED_HOSTS` or the browsable API can't leak into production by accident. It also
makes "what is actually true in prod" a single file you can read top to bottom, instead of mentally
evaluating a dozen conditionals.

**Q: What does "crash early on missing config" buy you?**
`base.py` reads every required var through `django-environ` and raises at import time if one's absent.
In production that means a misconfigured container fails its health check and ECS never routes traffic
to it — you get a clean "this release didn't start" instead of a process that's up but 500ing on the
first request that touches the missing setting.

---

## Phase 1 — Domain models

**What I built:** every model from `docs/reference/schema.prisma.reference` ported into one Django app
per bounded context, UUID PKs, `created_at`/`updated_at`, and `Meta.db_table` set to the original
snake_case table names. Django owns migrations from scratch against its own fresh database.

**Q: Why keep the Node backend's table and column names when Django doesn't require it?**
Two reasons. First, contract parity — if we ever cut the React frontend over to this backend, the wire
responses are unaffected by internal renames, but keeping the *database* naming identical meant I
could port `domain-model.md` mechanically, field for field, instead of maintaining a translation
table in my head and introducing typos. Second, it keeps the door open to pointing this Django app at
a database the Node backend also touches during a migration window — same tables, same columns, no
view layer in between.

**Q: Any friction from that choice?**
Minor. Django's app label `auth` collides with `django.contrib.auth`, so the OTP app needed an
explicit `AppConfig.label = "bolo_auth"`. And a couple of composite primary keys from Prisma's
`@@id([...])` needed Django 6's `CompositePrimaryKey`, which the admin doesn't fully support yet — so
those models just aren't registered in admin. Neither is a real cost.

---

## Phase 2 — Auth: OTP + JWT (httpOnly cookie) + Redis-backed throttling

**What I built:** an `OtpCode` model and `AuthService` (6-digit code, 5-min expiry, hashed at rest),
a custom `CookieJWTAuthentication` class that reads the token from an httpOnly cookie instead of an
`Authorization` header, `tenant_id`/`role_level` as JWT claims decoded once per request, a
Redis-backed `ScopedRateThrottle` on the OTP-request endpoint, and `HasOrgRole`/`IsTenantMember`
permission classes. I also went beyond the original single long-lived cookie and added a 15-minute
access token plus a rotating opaque refresh token with reuse detection.

**Q: Why put the JWT in an httpOnly cookie instead of `localStorage`?**
`localStorage` is readable by any JavaScript on the page, so one XSS bug — in your code or in a
dependency — and the attacker walks away with the token. An httpOnly cookie can't be read from JS at
all; the browser attaches it automatically and the token never touches the page's scripting context.
The tradeoff is CSRF exposure, which you cover with `SameSite` and the usual CSRF token on unsafe
methods — a well-understood problem with a standard fix, unlike "some npm package exfiltrated our
tokens."

**Q: Why does the rate limiter need Redis? Why not just an in-memory counter?**
Because in-memory state is per-process, and in production you're running multiple gunicorn workers,
probably across multiple containers. An in-memory "5 requests per minute" limit actually becomes
"5 per minute per worker" — so with eight workers an attacker gets 40, and it's not even
deterministic which worker they hit. Redis is the shared counter every worker reads and writes, so
the limit is a real global limit. Same reason DRF's throttling is documented to need a shared cache
backend.

**Q: You added refresh-token rotation — why, and what's reuse detection?**
The original contract was one long-lived cookie; I wanted a shorter blast radius if a token leaks. So
the access token lives 15 minutes and the refresh token is opaque, hashed at rest like the OTP, and
rotated on every use. Reuse detection means: if a refresh token that's already been rotated away gets
replayed, that's a signal it was stolen, so I revoke every token for that user and force a fresh
login. It's the standard OAuth refresh-rotation pattern.

---

## Phase 3 — Tasks: the hero CRUD + query optimization + indexing

**What I built:** the full task lifecycle — `TaskViewSet` → `TaskService` → `TaskRepository` — with
the business rules enforced in the service layer (title immutable, two-step DoneA→DoneD completion,
no reassignment once a subtask exists, cascade-cancel, no rejection state). Plus a composite index on
`(tenant_id, status)`, single-column indexes on `assignee_id` and `due_date`, a partial index on
`is_archived = false`, and `select_related` in the repository so the list endpoint doesn't N+1.

**Q: Walk me through a slow query before and after the composite index.**
The task list endpoint filters `WHERE tenant_id = ? AND status = ?` and orders by a sort key. Before
the index, `EXPLAIN ANALYZE` shows a `Seq Scan on tasks` — Postgres reads every row in the table,
"Rows Removed by Filter" is basically the whole table minus one tenant's slice, and on a table with
tens of thousands of rows that's tens of milliseconds per call plus a sort node on top. After adding
a composite index on `(tenant_id, status)`, the same plan becomes an `Index Scan using
idx_tasks_tenant_status`, it walks straight to the matching rows, "Rows Removed by Filter" drops to
zero, and you're at a fraction of a millisecond. The key detail is *composite and column order*: the
index is on `(tenant_id, status)` in that order because every query filters `tenant_id` for equality
first, so it's the leading column; a query that filtered status alone couldn't use it, which is fine
because we never do that.

**Q: Why the partial index on `is_archived = false`?**
The default list views only ever show non-archived tasks, and archived rows accumulate forever. A
partial index `WHERE is_archived = false` only indexes the rows we actually query, so it stays small
and cache-friendly as the archive grows. Each `AddIndex` in the migration has a comment naming the
exact query it serves, so nobody later wonders whether an index is still earning its keep.

**Q: How do you know the list endpoint doesn't N+1?**
There's a `django_assert_num_queries` regression test — more on that in Phase 11. When I built this I
actually found there was no N+1 to fix: `select_related` on the FKs plus `annotate(Count(...))` for
the child counts already kept it flat. The test locks that in.

---

## Phase 4 — Pagination

**What I built:** `PageNumberPagination` (size 20, max 100) as the default to match the original
contract, and `CursorPagination` for the infinite-scroll feeds, keyed on a stable `(created_at, id)`
ordering.

**Q: Page-number vs offset vs cursor — how do you choose?**
Page and offset pagination both compute "skip N rows" at query time, so if rows are inserted or
deleted between requests, page 2 either repeats a row from page 1 or skips one — the window shifts
under you. Cursor pagination says "give me the next 20 rows *after this key*," so concurrent writes
don't corrupt the sequence. The cost is you can't jump to "page 47" — there's no page number, only
next and previous. So I use cursor for the feeds where people scroll continuously and correctness
under concurrent writes matters, and page-number for admin-style lists where jumping around is the
point and the data's not changing every second. It's a per-endpoint decision, not a global one.

**Q: Why does the cursor need `(created_at, id)` and not just `created_at`?**
Because `created_at` isn't unique — two rows can share a timestamp, and then the cursor boundary is
ambiguous and you can drop or duplicate rows right at the page edge. Adding `id` as a tiebreaker
makes the ordering key total, so the boundary is always unambiguous.

---

## Phase 5 — Supporting entities (Evidence, Comments, Sticky Notes, Labels)

**What I built:** `Comment` CRUD with author-only edit/delete; `Evidence` upload via an S3
presign→confirm flow with server-side MIME/extension validation; `StickyNote` as a private
per-user entity where setting `due_at` *is* the reminder; and full `ProjectLabel` CRUD with delete
blocked while a label is in use.

**Q: Why do evidence uploads use pre-signed URLs instead of the file going through Django?**
If the file streams through your app server, every large upload ties up a gunicorn worker for the
whole transfer — that worker can't serve anything else while a 50 MB file crawls in over someone's
hotel wifi. With a pre-signed URL, the client PUTs the bytes straight to S3 and your app only handles
two tiny JSON calls: one to mint the URL, one to confirm the upload landed. Your request/response
cycle never touches the file payload, so upload size and client bandwidth stop being your app
server's problem.

**Q: The confirm step creates the DB row — why not create it at presign time?**
Because a presign that's never followed by an upload would leave an orphan row. So presign just
stashes the pending metadata in Redis with a 24-hour TTL that matches the S3 lifecycle rule on the
`unconfirmed/` prefix, and the `Evidence` row is only created at confirm, after the object is
verified in place. An expired or unknown `evidenceId` at confirm time is genuinely indistinguishable
from "upload never happened," which is exactly the error case the contract already describes.

**Q: Serving the file back — pre-signed GET URL, or stream it?**
Stream it through the backend, re-checking access on every request. A pre-signed URL is a bearer
credential the moment it's in a JSON response — anyone who has it can fetch the file until it
expires, regardless of session state or whether they still have permission. For evidence, broadcast
images, and profile pictures, access rules can change, so the endpoint re-checks authorization per
request and streams the S3 object. Voice recordings were the one place the original contract kept the
pre-signed URL and I matched that, then later moved it to streaming too during a docs re-sync.

---

## Phase 6 — Broadcast Notices

**What I built:** `can_broadcast`-gated publishing, a mandatory audience scope (departments and
role-levels, both many-to-many), `message_json` + `bleach`-sanitized `message_html`, a single image
served through a re-checking streamed endpoint, acknowledgement as a count-only signal to the sender,
and a Celery beat job that expires notices exactly one day after publish. Fan-out to recipients is a
Celery task, never inline.

**Q: Why a scheduled job for the 1-day expiry instead of a `WHERE published_at > now() - interval '1 day'` filter?**
Because the filter approach means every single read path — the list, the detail, the image endpoint,
the ack endpoint — has to remember to include that clause, and the day one forgets, an expired notice
leaks. A scheduled job that flips a status field gives you one source of truth for "is this visible,"
it's trivial to test in isolation (run the job, assert the status changed), and if the client later
wants a configurable TTL it's a one-line change in one place instead of a find-and-replace across
every query.

**Q: Why is the fan-out a Celery task?**
A broadcast can go to hundreds of people, each needing a notification row and possibly an email. If
that runs inline, the publisher's HTTP request hangs for however long the slowest email takes, and a
timeout mid-loop leaves it half-sent. As a queued task it returns instantly, retries independently,
and scales on queue depth instead of blocking a web worker.

---

## Phase 7 — Global Search

**What I built:** `GET /search/tasks` and `GET /search/stickies` — tenant- and participant-scoped
`ILIKE` matching over titles, descriptions, and label names, with an OpenAI `gpt-4o-mini` layer that
turns a natural-language query into structured filters (person, status, priority, due-range), plus a
deterministic Levenshtein fallback for mis-heard names and an alias table for status/priority values.
No API key configured means the whole thing degrades to raw keyword matching.

**Q: The roadmap said Postgres full-text search — why not Elasticsearch?**
At this data volume Elasticsearch is a second datastore to run, sync, and monitor, and it's
eventually consistent with your source of truth so you get reindex lag and "I just created this and
search can't find it" bugs. Postgres FTS with a `tsvector` column and a GIN index is ACID-consistent
with the row it indexes — no lag, no separate service — and `pg_trgm` covers the fuzzy-match case
that's usually the reason people reach for Elasticsearch in the first place.

**Q: But you didn't build Postgres FTS either — you built an LLM layer in front of `ILIKE`. Why?**
That was a deliberate call after a docs re-sync showed the real upstream design had already shipped
differently. The LLM query-understanding layer gets you acceptable fuzzy quality and "understands"
things like "high priority tasks for Raj due this week" without a `search_vector` migration or a GIN
index to maintain. The cost is a real external dependency — latency, money, and data leaving the
country for the OpenAI call — and non-deterministic behavior. That's exactly why there's a
deterministic Levenshtein layer for name resolution and an allow-list on the filter values: an
unrecognized status from the model gets dropped, never passed to the ORM. And if the key's missing or
the call fails, it falls back to plain keyword matching rather than erroring.

---

## Phase 8 — Notifications, Celery, Redis

**What I built:** a `Notification` model with `dispatch_notification()` as the single write path,
Celery + Redis for all async work, the manual `TASK_REMINDER`, daily due-proximity sweeps
(`TASK_DUE_TODAY`/`_TOMORROW`/`_OVERDUE` plus the real `OPEN→OVERDUE` status transition), sticky-note
reminder sweeps, and the AI-nudge skip-cap/escalation feed. Idempotency is enforced by persisted
per-row "already notified" flags, not a TTL.

**Q: How do you make a Celery task safe to run more than once?**
You start from the assumption that it *will* run more than once — a worker can do the side effect,
then crash before it acks the message, and the broker redelivers. So the send has to be
check-then-act guarded by durable state. Here, each task row has a `due_today_notified_at` timestamp
that's only set *after* a successful dispatch. A retry after a mid-sweep failure re-scans, sees that
column is still null only for the rows that never got sent, and processes just those. No separate
dedupe table, no "exactly once" assumption — the guard is a column, and it survives a worker restart.

**Q: Why a persisted DB column and not a Redis key with a TTL?**
Because "did we already tell this person their task is due" is a durable business fact, not a
short-lived coordination detail. I want it to survive a Redis flush and a worker restart, and I want
to be able to see it in the database when debugging. Redis with a TTL would risk re-sending after the
key expired.

---

## Phase 9 — OpenAI: natural-language task extraction

**What I built:** `POST /tasks/extract` — raw text in (a rough voice transcript or typed note), a
`{title, assigneeHint, dueDate, priority}` suggestion out to pre-fill the create-task form. It never
persists anything. One mockable `call_openai_extract()` boundary, an 8-second timeout, and a
documented all-null fallback when the key is missing or the call fails.

**Q: Design decisions worth defending here?**
Two. First, synchronous with a tight timeout, not a Celery job the frontend polls — the poll shape
would need a job-status endpoint the contract doesn't have, purely to work around a call that already
degrades cleanly in-process in under eight seconds. Second, graceful degradation is the whole point:
if `OPENAI_API_KEY` is unset, or the call times out, or the model returns malformed JSON, every one
of those collapses to the same `200` response with all fields null. Creating a task never breaks
because an AI feature is down. That's the difference between "I called an API" and "I designed a
resilient integration."

**Q: Why isn't `assigneeHint` resolved to a real user?**
Deliberately not. It's just the extracted name text. The frontend's assignee picker does the actual
roster lookup, so a wrong hint costs one extra dropdown click — whereas if I resolved it server-side
and got it wrong, you'd get a silently misassigned task. Keep the fuzzy step where a human is already
in the loop.

---

## Phase 10 — Audit logging + observability

**What I built:** the audit half was already done in an earlier hardening pass as generic middleware
plus a route-config table. This phase added `structlog` JSON logging with `request_id` / `tenant_id`
/ `actor_id` bound to context for the whole request, so every log line — including Django's own
internal ones — carries the correlation IDs. Plus Celery task start/finish/fail logging via signal
handlers, one hook instead of edits in every task function.

**Q: Your audit log is written from a fire-and-forget Celery task, not the same transaction as the change. Isn't that a correctness risk?**
It's a documented tradeoff, not an oversight. If the audit write were in the same transaction as the
business change, an audit-table problem could roll back a legitimate task update, and the write would
add latency to every mutating request. Express has a post-response hook for this; Django doesn't, so
the idiomatic substitute is a Celery task queued after the response is formed. It only enqueues when
the response succeeded — status under 400 — and it reads before-state ahead of the view and
after-state from the response body. The accepted risk is that a broker outage could drop an audit
row; for this product that's the right side of the tradeoff versus coupling every write to the audit
system's availability.

**Q: Why structured logging and not just log strings?**
Because the first thing you do in an incident is filter. JSON logs with a `request_id` on every line
mean you can pull every log entry for one failing request across middleware, view, service, and even
Django's internal error logger, in one query. Free-text logs make you grep and guess. Binding the IDs
to `structlog.contextvars` in the first middleware means code deep in a service doesn't have to
thread a request object through just to log with context.

---

## Phase 11 — Testing

**What I built:** `pytest-django` + `factory_boy` against a real Postgres test database, no DB
mocking. Service-layer tests for every business rule, DRF-client tests for contract shape, and
`django_assert_num_queries` regression tests on both the task list and task detail endpoints. This
phase was investigate-first — the suite was already strong, so I added only the real gaps.

**Q: Why is a query-count regression test worth more than it looks?**
Because it converts a one-time achievement into a permanent guarantee. "I optimized this query once"
is worthless six months later when someone adds an inline serializer field that reintroduces an N+1 —
nothing fails, the page just gets slow in production. `django_assert_num_queries` pins the count: the
test creates one subtask, one comment, one evidence row and records the query count, then adds four
more of each and asserts the count is *identical*. If a change makes queries scale with row count,
CI goes red on that PR, not in an incident. It's the cheapest possible insurance against silent
performance regressions.

**Q: Why no database mocking?**
Because the bugs I care about — a wrong `select_related`, a missing tenant filter, an index that
doesn't get used, an `on_delete` that cascades when it shouldn't — only exist against a real
Postgres. A mocked DB tests that my code calls the ORM the way I expected, which is circular.
`factory_boy` plus a real test database is fast enough and tests the thing that actually breaks.

---

## Phase 12 — Caching

**What I built:** Redis cache-aside on two read-heavy, write-light endpoints. `GET /tasks/counts` is
cached per `(tenant, user)` with a 5-minute TTL; the per-creator label list is cached with a
10-minute TTL and one entry serves `/labels/mine`, `/labels/shared`, and the task-detail
`myPersonalLabels` list. Key builders and `bust_*` helpers live in `apps/common/caching.py`.

**Q: Walk me through your cache invalidation. Which write paths bust what, and why isn't the TTL enough?**
The TTL is only a backstop — the correctness mechanism is an explicit bust on every write path. For
the task counts, that's every mutating method in `TaskService` — `create`, `update`, `delete`,
`accept`, `done_a`, `done_d`, `cancel`, `create_subtask` — plus the `OPEN→OVERDUE` transition in the
due-proximity sweep, because that moves a task between the "open" and "overdue" tab counts. `update`
is the subtle one: on a reassignment I capture the previous assignee's ID *before* the write, so I
can bust the old assignee, the new assignee, and the assigner. Cancel and delete also bust every
cascaded subtask's participants. For labels, it's create, rename, recolor, and delete, all
creator-scoped so it's a single key.

Why the TTL isn't correctness: if I relied on a 5-minute TTL alone, a user who just created a task
would see a stale badge count for up to five minutes — a visible, reproducible bug. The per-write
bust makes the value right immediately. The TTL exists only to catch a bust I forgot to wire, or a
cross-process race where two requests interleave. It bounds staleness; it doesn't produce
correctness.

**Q: Why cache-aside and not write-through?**
Cache-aside keeps the caching logic out of the write path's critical section — the write just
invalidates, and the next read repopulates. It also fails safe: if Redis is down, reads fall through
to the database and writes still succeed. Write-through would couple every write to a successful
cache write.

---

## Phase 13 — Dockerization, CI, API docs

**What I built:** a multi-stage `Dockerfile` (venv-build stage → slim runtime, non-root user,
`collectstatic` baked in) and a `docker-compose.yml` with web/worker/beat/db/redis, verified end to
end on a real daemon. A GitHub Actions CI workflow with four parallel jobs — ruff, pytest +
`makemigrations --check` against real Postgres/Redis, `pip-audit`, and a Docker build with
`check --deploy`. A committed-but-disabled reference CD workflow for AWS ECS Fargate.
`drf-spectacular` serving Swagger and ReDoc. And `docs/ops/deployment-django.md` as the runbook.

**Q: Why is `makemigrations --check` in CI valuable?**
It's a one-line job that catches the single most common way to break a Django deploy: you change a
model field, run your tests locally against your already-migrated dev database so everything passes,
and forget to commit the migration file. It merges, the deploy's migrate step runs, and there's
nothing new to apply — so production is now running new code against an old schema, and you find out
via 500s. `makemigrations --check --dry-run` fails the build if the models and the migration files
disagree. Cheap gate, expensive incident avoided.

**Q: `pip-audit` — did it actually catch anything?**
Yes, immediately — it flagged the pinned `Django==6.0.7` for a CVE, so I bumped to `6.0.8` and
re-ran the suite. That's the job paying for itself on the first run: a known-vulnerable dependency
caught in CI instead of in a pen test.

---

## Cross-cutting: architecture decisions

**Q: You use a strict Controller → Service → Repository layering. That's not idiomatic Django — why keep it?**
Django's default idiom is fat models and views that call the ORM directly, and for a small app that's
fine. I kept the stricter layering for three reasons. One, this is a port of a Node backend that's
already structured this way, so matching it made the port mechanical and makes the two codebases
reviewable side by side. Two, testability: the service layer has no `request` or `response` objects
and no ORM calls, so business-rule tests call a plain function with plain arguments — no HTTP client,
no fixtures beyond the data. Three, it forces every ORM query into the repository, which is where the
tenant-scoping filter lives, so "did we scope this by tenant" has exactly one place to audit instead
of being sprinkled across views. The rule is: views do HTTP only, services do business logic and
never touch the ORM, repositories are the only place `Model.objects` appears.

**Q: Audit logging is generic middleware, but notifications are an explicit `dispatch_notification()` call. Why opposite patterns?**
Because they're solving opposite problems. Notifications are *business logic* — which event notifies
whom is a product decision that varies per transition, and the service that changes the state is the
only thing that knows the context. So it's an explicit call at the site, and if the event type isn't
in the notification-types table yet, you add it there first. Audit logging is *cross-cutting
bookkeeping* — every mutating request should produce an audit row, uniformly, and you never want a
developer to be able to add a new mutating endpoint and forget to audit it. So it's a middleware plus
a static route-config table: observe every request generically, read before-state via the configured
model, capture after-state from the response, write the row only if the response succeeded. A new
audited route is one row in a config table, not a line in a handler. Explicit where context matters,
generic where uniformity matters.

---

## Deployment & CI/CD (expanded)

The runbook is `docs/ops/deployment-django.md`; these are the spoken versions.

**Q: Local vs staging vs production — what actually differs?**
Same Docker image everywhere; what changes is the settings module and where config comes from.
*Local* is `docker compose up` with `config.settings.dev` — plain HTTP, `DEBUG` on, Postgres and
Redis as compose services, secrets in a gitignored `.env.docker`, S3/SES mocked or consoled. *Staging
and production* run the identical image with `config.settings.prod` — `DEBUG` off, `ALLOWED_HOSTS`
required, HSTS and SSL redirect on, behind a TLS-terminating load balancer, with `DATABASE_URL`
pointing at RDS, `REDIS_URL` at ElastiCache, and every secret injected by the platform from AWS
Secrets Manager / SSM by ARN. Staging is just production with smaller instances and separate data —
same topology, so a deploy that works in staging works in prod. You can't run prod settings on
localhost because `SECURE_SSL_REDIRECT` would infinite-loop on plain HTTP.

**Q: Walk me through the whole flow from `git push` to running in production.**
I push a branch and open a PR. That triggers the CI workflow — four parallel jobs: ruff lint, pytest
against real Postgres and Redis service containers with `makemigrations --check` in front of it,
`pip-audit` for dependency CVEs, and a Docker build that runs `manage.py check --deploy` on the
finished image. Branch protection blocks the merge button until all four are green and someone's
reviewed it. On merge to `main`, the CD workflow runs: authenticate to AWS via OIDC, build the image
and push it to ECR tagged with the commit SHA, run database migrations as a *one-off* ECS task,
register a new task-definition revision pointing at the new image, and update the ECS service to that
revision. ECS then does a rolling replace behind the load balancer — start new tasks, wait for their
health checks, shift traffic, drain the old ones. If the new tasks never go healthy, ECS's deployment
circuit breaker rolls it back automatically.

**Q: How does GitHub Actions know to run those?**
Each workflow file in `.github/workflows/` has an `on:` block declaring its triggers. `ci.yml` is
`on: [pull_request, push: branches: [main]]`, so it runs for every PR and every merge. `deploy.yml`
is `on: workflow_dispatch` plus a guard `if: vars.AWS_REGION != ''` — so it's committed as a
reference that does nothing until the AWS side actually exists, at which point you'd switch it to
`on: push: branches: [main]`. GitHub watches the repo events and dispatches the matching workflows;
there's no external scheduler.

**Q: ECR vs ECS vs Fargate vs EC2 — untangle those.**
ECR is the container *registry* — a private Docker Hub, where the built image lives. ECS is the
*orchestrator* — it reads a task definition ("run this image with this CPU/memory, these env vars,
this port") and keeps the desired number of copies running, replacing unhealthy ones. Fargate vs EC2
is the *compute mode* underneath ECS: with EC2 you manage a fleet of virtual machines that the
containers pack onto — you patch them, you scale them; with Fargate AWS runs each task on capacity it
manages and you just declare CPU and memory per task, no servers to see. I chose Fargate because for
this workload the operational savings outweigh the per-unit cost premium. So the pipeline is: build
image → push to **ECR** → **ECS** launches it as tasks on **Fargate**.

**Q: Where does the ALB fit, and how does ECS keep it in sync?**
The Application Load Balancer is the public entry point — it terminates TLS and forwards HTTP to the
web tasks. It routes to a *target group*, which is just a list of IP:port endpoints plus a health
check. The integration is that the ECS service is *registered with* that target group: when ECS
starts a new task it adds that task's IP to the target group, waits for the ALB's health check to
pass before sending it real traffic, and when it stops a task it deregisters the IP first and lets
in-flight requests drain. So scaling out, rolling deploys, and replacing a crashed task all keep the
load balancer's backend list correct automatically — you never touch the target group by hand.

**Q: Expand/contract migrations — what and why?**
During a rolling deploy, old and new code run at the same time against the same database, so every
migration has to be backward-compatible with the code that's still running. Expand/contract means you
never do a breaking schema change in one step. To rename a column: deploy A adds the new column and
writes to both; deploy B backfills and switches reads to the new one; deploy C drops the old column —
by which point no running code references it. To add a `NOT NULL` column: add it nullable or with a
default first, backfill, add the constraint in a later migration. The migration runs as its own step
*before* the code rollout, once, not inside each web container's startup where N containers would
race.

**Q: Why is rolling the code back safe but rolling the database back not?**
Because if every migration is expand/contract, the previous release's code still works against the
current schema — nothing was destructively removed while it was still a rollback target. So rollback
is just re-pointing the ECS service at the previous task-definition revision; the schema is left
alone. There is no automatic down-migration in production — reversing a migration that dropped a
column means restoring data that's gone. The discipline is: a destructive schema change only ships
once the release that needs the old shape is no longer something you'd roll back to.

**Q: Why WhiteNoise and an ALB instead of nginx?**
The classic setup puts nginx in front of the app to terminate TLS and serve static files. In this
deployment the ALB already terminates TLS, and WhiteNoise — a WSGI middleware — serves the collected
static files (admin CSS/JS, the Swagger assets) straight from gunicorn with cache headers and
compression. Those static files are baked into the image at build time by `collectstatic`. So there's
no per-task nginx sidecar to configure, ship, and patch; the task is just gunicorn. At this scale
that's simpler with no real downside — if static traffic ever justified it you'd put CloudFront in
front, not nginx back in.

**Q: Walk me through a production incident.**
*Detect* — an alert fires: error rate on the web service spikes, or health checks start failing after
a deploy. First look is the structured logs filtered to the spike window, and the deploy timeline —
did this start right after a release? *Mitigate first, diagnose second* — if it correlates with a
deploy, roll back immediately by re-pointing the ECS service at the previous task-definition
revision; that's a couple of minutes and it stops the bleeding. If it's not deploy-related, mitigate
whatever's proximate — scale out, disable a feature flag, shed load. *Diagnose* — now that users
aren't hurting, find root cause from the logs and metrics, reproduce it locally against the same
image if you can. *Hotfix through the normal pipeline* — the fix goes through a PR, CI, review, and
the same CD path as any other change. You do not SSH into a container and hand-edit anything; that
container is immutable and the next deploy would erase it anyway, and now prod doesn't match `main`.
The one exception is a config/secret change, which goes through Secrets Manager and a task restart.
*Blameless postmortem* — written up within a few days: timeline, what broke, why our tooling let it
through, and concrete follow-ups — a missing test, a missing alert, a CI gate that should have caught
it. The output is system changes, not blame; people are honest about what happened when it's not
about fault.

---

## The hardest bug I fixed: a cross-auth-space JWT crash

**The setup.** This backend has two separate authentication spaces. Tenant users get a `token` cookie
whose JWT carries `userId`, `tenantId`, and `roleLevel`. Platform admins — a cross-tenant operator
role — get an `admin_token` cookie whose JWT has a completely different claim shape: `adminId`,
`email`, `isPlatformAdmin`, and deliberately *no* `tenantId` or `roleLevel`. Both are signed with the
same secret, because they're issued by the same service.

**The bug.** `CookieJWTAuthentication`, the class that authenticates tenant users, verified the JWT
signature and then immediately did `token["userId"]` — it never checked the claim was actually
present. So if you took a perfectly valid `admin_token` and presented it as the `token` cookie, the
signature check passed, and then the code indexed into a claim that wasn't there and threw a
`KeyError`. DRF turns an unhandled exception into a `500`. It should have been a clean `401` — this
is just a token that isn't valid *for this endpoint*.

**Why it was hard to catch.** It sat latent for over a month. The only way to hit it was to cross the
two auth spaces — present one space's token to the other's endpoint — which no normal client and no
existing test did. Then a second copy of the same unguarded pattern turned up in
`decode_access_cookie()`, a helper the audit middleware used. That one was even better hidden: the
audit middleware only decoded the cookie for routes in its config table, so most requests never
exercised it. When I added request-logging middleware in Phase 10 that decodes caller identity on
*every* request, an existing negative-path test — one that deliberately presents a tenant cookie to a
platform-admin route — suddenly flipped from passing to `500`. That test failure is what surfaced the
second instance.

**The fix.** An explicit claim-presence guard: if the required claims aren't all in the decoded
token, treat it as no valid token and return `401`, don't index. I pulled the shared identity-decode
logic into `apps/common/request_identity.py` so both middlewares call one hardened implementation
instead of each carrying their own unguarded copy. Plus regression tests at both the unit level and
the full-request level for the cross-auth-space case.

**What I'd do to harden it further.** The root cause is that two token types are structurally
interchangeable — same signing key, distinguishable only by inspecting claims. The real fix is to
make them non-interchangeable: a separate signing key per auth space, or an `aud` (audience) claim
that each authenticator verifies, so a token minted for the admin space is *cryptographically*
rejected by the tenant authenticator before anyone reads a single claim. That's tracked as
follow-up.

**Why I tell this story.** It's a good one because the bug itself is a one-line fix, but everything
around it is the interesting part: latent for a month, a second hidden instance, found by an
unrelated feature's test rather than a bug report, and a proper root-cause fix that's different from
the proximate fix.
