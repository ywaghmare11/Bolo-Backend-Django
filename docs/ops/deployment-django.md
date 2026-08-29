# Deployment & CI/CD — bolo-backend-django

> This is **this project's own** runbook (Django/DRF + gunicorn + Celery). The other
> `docs/ops/*` files (`deployment.md`, `staging-runbook.md`, …) are the inherited
> Node/Express narrative — reference only. Everything here matches real committed
> files: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`,
> `.github/workflows/deploy.yml`.

Target production platform: **AWS ECS Fargate** (serverless containers) with
**RDS Postgres**, **ElastiCache Redis**, **S3** (evidence/broadcast/profile files)
and **SES** (reminder emails). The app is already written for this — it reads
`DATABASE_URL` / `REDIS_URL` from the environment and uses the default AWS
credential chain (IAM role) for S3/SES, no access keys.

---

## 1. What actually runs

The same image runs as **four process types**, differing only by the command:

| Process | Command | What it does | Scales on |
|---|---|---|---|
| **web** | `gunicorn config.wsgi:application` | Serves HTTP (the API, `/admin/`, `/api/v1/docs/`) | request volume |
| **worker** | `celery -A config worker` | Runs background jobs: notification fan-out, audit-log writes, AI calls | queue depth |
| **beat** | `celery -A config beat` | Fires scheduled jobs (due-date sweep, sticky-note retention, AI-nudge sweeps) | never — exactly **one** replica |
| **migrate** | `python manage.py migrate` | One-off, run once per release *before* web/worker roll | n/a |

Why split them: a slow email fan-out must never block an HTTP response, the
schedulers must be singletons, and each type scales on a different signal. One
image, four ECS services (well, three services + one-off task).

---

## 2. The Docker image (`Dockerfile`)

Two stages:

**Stage 1 — `builder`.** `python:3.12-slim`, creates a virtualenv at `/opt/venv`,
`pip install -r requirements/prod.txt` into it. Requirements are copied *before*
the app code so this layer is cached and only re-runs when a `requirements/*.txt`
file changes — not on every code edit.

**Stage 2 — `final`.** Fresh `python:3.12-slim`, copies **only** `/opt/venv` and
the app code from stage 1. The pip cache and any build tools stay behind in the
discarded builder stage, so the shipped image is smaller and has less attack
surface.

Other choices, and why:

- **Non-root user.** `groupadd app && useradd app`, `USER app` before `CMD`. If the
  process is ever compromised it isn't root inside the container.
- **`collectstatic` at build time**, with throwaway env vars. The admin CSS/JS and
  the Swagger/ReDoc assets are baked into the image, so the container is immutable
  and needs no build step at boot. The dummy `DJANGO_SECRET_KEY=build-only` etc.
  only satisfy settings validation for a command that touches neither DB nor
  network — the real secrets arrive at run time.
- **WhiteNoise** (`config/settings/prod.py`) serves those static files straight
  from gunicorn, so there's no nginx sidecar in the task.
- **`ENTRYPOINT` + `CMD`.** `docker/entrypoint.sh` blocks until Postgres is
  reachable, runs `migrate` **only if `RUN_MIGRATIONS=1`**, then `exec "$@"`. The
  `CMD` is the default (`gunicorn …`); the worker/beat services override it with
  `celery …` while reusing the same entrypoint.
- **`.dockerignore`** keeps `.git`, `.venv`, `docs/`, `.env*`, test caches out of
  the build context — smaller, faster, and no secrets in a layer.
- **`config.settings.prod`** is the image's default `DJANGO_SETTINGS_MODULE`
  (`DEBUG=False`, `ALLOWED_HOSTS` required, HSTS, `SECURE_SSL_REDIRECT`,
  `SECURE_PROXY_SSL_HEADER` so it trusts the ALB's `X-Forwarded-Proto`).

---

## 3. Local: `docker compose up`

```bash
cp .env.docker.example .env.docker
docker compose up --build
# API on http://localhost:8000 , docs on /api/v1/docs/
```

Five services in `docker-compose.yml`:

- **db** (`postgres:16-alpine`) — named volume `pgdata`, `pg_isready` healthcheck.
- **redis** (`redis:7-alpine`) — `redis-cli ping` healthcheck.
- **web / worker / beat** — the app image (built once, shared via a YAML anchor).
  All three `depends_on` db + redis **`condition: service_healthy`**, so they don't
  start until the datastores actually accept connections. Only **web** sets
  `RUN_MIGRATIONS=1` — worker and beat must not race it applying migrations.
  **beat** writes its "last run" cache to `--schedule /tmp/celerybeat-schedule`
  (a writable path; it's only a cache, and every sweep in this project is
  idempotent, so losing it just re-fires one tick early).

Verified end-to-end (`docker compose up --wait`): all five services reach
`healthy`, migrations apply once in web, gunicorn serves `/api/v1/docs/`,
`/api/v1/schema/`, `/api/v1/redoc/` and the admin (WhiteNoise static), the worker
connects to Redis, and beat starts clean.

Local compose uses `config.settings.dev` (plain HTTP, `DEBUG`). Production uses the
**same image** with `config.settings.prod` behind a TLS-terminating load balancer —
you can't run prod settings on plain-HTTP localhost because `SECURE_SSL_REDIRECT`
would loop.

---

## 4. Configuration & secrets (12-factor)

Every environment-specific value is an env var, never committed:

| Var | Local | Production source |
|---|---|---|
| `DJANGO_SECRET_KEY`, `JWT_SECRET` | `.env.docker` | AWS Secrets Manager → injected by ECS |
| `DATABASE_URL` | compose `db` service | RDS endpoint, in Secrets Manager |
| `REDIS_URL` | compose `redis` service | ElastiCache endpoint (SSM param) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | the ALB / domain name (SSM param) |
| `S3_BUCKET_NAME`, `SES_FROM_EMAIL` | blank (mocked/console) | SSM params; **no AWS keys** — the ECS task role grants S3/SES |
| `OPENAI_API_KEY` | blank (fallback path) | Secrets Manager |

`config/settings/base.py` reads these through `django-environ` and **crashes at
startup if a required one is missing** — a misconfigured task fails its health
check and ECS never routes traffic to it, instead of running half-broken.

Secrets live in **AWS Secrets Manager / SSM Parameter Store** and are referenced by
ARN in the ECS task definition's `secrets` block — ECS injects them as env vars at
container start. They are **not** baked into the image and **not** in GitHub.

---

## 5. CI pipeline (`.github/workflows/ci.yml`)

Runs on every pull request and every push to `main`. Four parallel jobs; branch
protection blocks merge unless all pass.

| Job | Step | Catches |
|---|---|---|
| **lint** | `ruff check .` | style/import/lint errors |
| **test** | `manage.py makemigrations --check --dry-run` | a model change committed **without** its migration |
| | `pytest -q` | any behavioural regression — 336 tests against a **real** Postgres + Redis (GitHub `services:` containers), not mocks |
| **security** | `pip-audit -r requirements/prod.txt --strict` | a pinned dependency with a known CVE |
| **docker** | `docker build` (+ GHA layer cache) | a broken Dockerfile |
| | `docker run … manage.py check --deploy` | prod-settings misconfiguration in the built image |

The `test` job passes `DJANGO_SECRET_KEY` / `DATABASE_URL` / `REDIS_URL` as job
`env:` because `config.settings.test` still imports `base.py`, which validates them
(the crash-early rule from §4).

**Reading a red X:**

| Failed job | Meaning | Fix |
|---|---|---|
| lint | formatting / unused import | `ruff check --fix .` |
| test → migration check | you changed a model, no migration file | `manage.py makemigrations`, commit it |
| test → pytest | a real regression | read the failing assertion |
| security | dependency CVE | bump the pin, or add an ignore with justification |
| docker | Dockerfile / prod settings broke | build locally to reproduce |

---

## 6. CD pipeline: staging → approval → production (`.github/workflows/deploy.yml`)

Still committed as a **reference, disabled** workflow — `workflow_dispatch` only,
with the `build` job guarded by `if: vars.AWS_REGION != ''` (a skipped `build`
skips its dependents too), so the whole thing is inert until the AWS stacks and
the GitHub Environments exist. When enabled (trigger flipped to
`push: branches: [main]`), a merge to `main` promotes **that one commit** through
two environments:

```
build (once)  ──►  deploy-staging (automatic)  ──►  deploy-production (manual gate)
```

### The three jobs

1. **`build`** — runs once. OIDC into AWS (no stored keys), `docker build`, push
   to the **one shared ECR repository** tagged with the **commit SHA**, and export
   that image URI as a job output. If the tag already exists (workflow re-run, or
   a `workflow_dispatch` with an explicit `image_tag`) it reuses it instead of
   rebuilding. No `environment:` — it touches nothing environment-specific.

2. **`deploy-staging`** — `needs: build`, `environment: staging`, **no required
   reviewers**, so it runs automatically. It (a) runs `migrate` as a one-off
   Fargate task against **staging's RDS**, then (b) renders a new task-definition
   revision pointing at `needs.build.outputs.image` and calls
   `aws ecs update-service` on **staging's cluster**, with
   `wait-for-service-stability`.

3. **`deploy-production`** — `needs: deploy-staging`, `environment: production`.
   The `production` GitHub Environment has **Required reviewers** configured, so
   the job starts, immediately **parks in a "waiting" state**, and a listed
   reviewer must click *Approve* on the run before it proceeds. It then does
   exactly what `deploy-staging` did — one-off `migrate`, then a rolling
   `update-service` — but against **production's** RDS and cluster, deploying
   **the same SHA-tagged image** staging just validated. Never a rebuild: what QA
   signed off on is byte-for-byte what ships.

### One set of steps, two environments — no branching

Every deploy step reads `vars.ECS_CLUSTER`, `vars.ECS_SERVICE`,
`vars.ECS_TASK_FAMILY`, `vars.PRIVATE_SUBNETS`, `vars.SERVICE_SG` and
`secrets.AWS_DEPLOY_ROLE_ARN`. These are defined **per GitHub Environment**
(Settings → Environments → *staging* / *production* → Secrets and Variables), so
the job declaring `environment: staging` resolves them to staging's values and the
one declaring `environment: production` resolves them to production's — with **no
`if`/matrix branching in the YAML**. Only `vars.AWS_REGION` and
`vars.ECR_REPOSITORY` live at repository scope (genuinely shared).

### What's duplicated per environment, what's shared

**Each of staging and production gets its own:** ECS cluster + web/worker/beat
services; RDS Postgres (staging smaller, production Multi-AZ); ElastiCache Redis;
ALB + target group + domain (`staging.` host vs the real host); `<family>-migrate`
task definition; OIDC deploy role (scoped to that environment's resources).

**Shared across both:** the **ECR repository** (one repo, images addressed by
commit-SHA tag), the app image itself, and the `config.settings.prod` settings
module. Staging is production's topology at a smaller size with its own data — a
deploy that's green on staging is high-confidence for production because
everything except scale and data is identical.

### Per-environment migrate, before each rolling deploy

Each deploy job runs `migrate` against **its own** RDS **before** rolling that
environment's service: staging's schema moves first and QA exercises it, then
production's moves at approval time. Migrations must be backward-compatible
(expand/contract — §7) because the still-running old tasks keep serving through
both the one-off migrate task and the rolling replace.

The dependencies (RDS, ElastiCache, S3, SES) are reached over each VPC's private
subnets; the ECS **task role** carries the S3/SES IAM permissions so the app
itself needs no access keys.

### Continuous delivery, not continuous deployment

Every green commit on `main` is **automatically deployed to staging** and is then
**one approval click from production** — the pipeline is always ready to ship, a
human decides when. That's *continuous delivery*. *Continuous deployment* would
delete the `deploy-production` approval gate and push every merge straight to
production; this project keeps the human in the loop for the prod step on purpose.

---

## 7. Zero-downtime deploys & database migrations

Zero downtime comes from the **rolling replace + health checks** in §6 — old
containers keep serving until new ones are proven healthy.

The catch is the database. During the rollout, **old and new code run at the same
time against the same schema**, so every migration must be **backward-compatible
with the currently-running code**. The safe pattern is **expand / contract**:

| Change | Wrong (one deploy) | Right (spread across deploys) |
|---|---|---|
| Rename a column | `RenameField` — old code 500s instantly | Deploy A: add new column + write to both. Deploy B: backfill + read new. Deploy C: drop old column. |
| Add a `NOT NULL` column | add `NOT NULL` with no default — old inserts fail | add nullable (or with default) → backfill → add the constraint later |
| Drop a column/table | drop it while old code still selects it | stop referencing it (deploy) → drop it (next deploy) |

This is why migrations run as a **separate step before** the code rollout, and why
`makemigrations --check` is a CI gate — a migration that's missing or unreviewed
is the most common way to break a deploy.

---

## 8. Rollback

- **App code:** re-point the affected environment's ECS service at the previous
  task-definition revision
  (`aws ecs update-service --cluster <env-cluster> --task-definition <family>:<prev>`)
  — or re-run `deploy.yml` via `workflow_dispatch` with an older `image_tag` (it
  promotes that existing ECR image, still through staging then the prod approval
  gate). ECS rolls forward to the old image the same way it rolled to the new one.
- **Database:** there is no automatic down-migration in production. Because
  migrations are expand/contract and backward-compatible, rolling the *code* back
  is safe without touching the schema. Destructive schema changes only ship once
  the previous release is no longer a rollback target.
- **Automatic:** the ECS deployment circuit breaker rolls back a release whose new
  tasks never pass health checks, with no human action.

---

## 9. Monitoring

Not provisioned yet — like the rest of the AWS side, the actual infra stays in the
roadmap's *"Future — Production Deployment on AWS"* bucket. This section documents
the intended design, not something running today.

### Health checks (ALB target group)

Each environment's ALB target group health-checks its web tasks on a lightweight
path. There's no dedicated endpoint in the code yet — the options are a tiny
no-DB, no-auth `/healthz` view, or reusing `/api/v1/schema/` (already unauthed and
cheap). A task must pass the check before the ALB routes traffic to it and before
ECS treats a rolling deploy as succeeded; a task that starts failing is pulled
from rotation and replaced. **`HealthyHostCount = 0`** is the single clearest
"the service is down" signal.

### Logs (CloudWatch Logs)

The container writes **`structlog` JSON to stdout** (Phase 10). The ECS task
definition uses the **`awslogs`** log driver, so every line lands in a per-service
CloudWatch Logs group (`/ecs/bolo-web`, `/ecs/bolo-worker`, `/ecs/bolo-beat`).
Because each line is JSON carrying `request_id` / `tenant_id` / `actor_id`,
**CloudWatch Logs Insights** can query them structurally — e.g. reconstruct one
request end to end:

```
fields @timestamp, event, path, status_code, duration_ms
| filter request_id = "abc123"
| sort @timestamp asc
```

That `request_id` is the same value returned in error responses / surfaced to the
client, so an incident report gives you a direct key into the logs.

### Metrics & alarms (CloudWatch → SNS)

ECS, ALB and RDS publish CloudWatch metrics with no extra code. The alarms worth
wiring — each notifying an **SNS** topic that fans out to email / Slack /
PagerDuty:

| Alarm | Condition (starting point) | Why it matters |
|---|---|---|
| **5xx rate** | ALB `HTTPCode_Target_5XX_Count` / request count > ~2% for 5 min | the app is erroring for real users |
| **No healthy tasks** | ALB `HealthyHostCount` = 0 for 1 min | service is fully down |
| **RDS CPU** | `CPUUtilization` > 80% for 10 min | a query regression or an undersized DB |
| **RDS connections** | `DatabaseConnections` approaching `max_connections` | a connection leak or bad pool config |
| **Redis memory / evictions** | ElastiCache `DatabaseMemoryUsagePercentage` high, or `Evictions` > 0 sustained | cache undersized and thrashing |
| **Worker backlog** | custom metric on the Celery/Redis queue length | background jobs falling behind |

### Automatic rollback (ECS deployment circuit breaker)

Each ECS service is configured with
`deploymentConfiguration.deploymentCircuitBreaker = { enable: true, rollback: true }`.
If a new deployment's tasks never reach a steady healthy state — crash loop,
failing health checks, a migration problem that only shows at boot — ECS
**aborts the deployment and rolls the service back** to the last known-good
task-definition revision, no human action. The workflow's
`wait-for-service-stability` step then fails, so the GitHub run goes red and the
rollback is visible rather than silent.

### Error tracking (Sentry — off by default)

Intended integration: `sentry-sdk` initialised in `config/settings/prod.py`
**only when a `SENTRY_DSN` env var is present**. Unset (the default, and the case
in this sandbox) means the SDK is never initialised — zero overhead, nothing to
opt out of. Set the DSN per environment via Secrets Manager to turn on exception
capture, with the Sentry `release` tagged to the deployed commit SHA so a new
error class ties back to the deploy that introduced it. Not in the code yet —
Phase 10 deferred `django-prometheus` / Sentry until real AWS infra exists.

---

## 10. Interview cheat-sheet

**"How do you deploy this?"**
GitHub Actions on merge to `main`: build one Docker image tagged with the commit
SHA and push it to a shared ECR repo, then promote that same image through two
environments — automatically to staging (migrate staging's RDS, rolling ECS
replace behind an ALB), then to production behind a manual approval gate (a GitHub
Environment with required reviewers). Each environment migrates its own RDS before
its own rolling deploy. Rollback is re-pointing that environment's ECS service at
the previous task-definition revision.

**"Walk me through your CI/CD."**
CI (every PR): four parallel jobs — ruff lint, pytest against a real Postgres+Redis,
`pip-audit` for dependency CVEs, and a Docker build + `manage.py check --deploy`.
`makemigrations --check` fails the build if a model changed without a migration.
CD (merge to main): OIDC into AWS (no stored keys) → build/push one SHA-tagged
image → `deploy-staging` runs itself (migrate + rolling ECS deploy) → QA validates
→ `deploy-production` waits on a required-reviewer approval, then does the same
against prod's stack with the *identical* image. Continuous delivery, not
continuous deployment — a human approves prod. Failed health checks trigger the
ECS deployment circuit breaker's automatic rollback either way.

**"How do you get zero-downtime deploys?"**
Rolling replacement: ECS starts new containers, waits for their load-balancer
health checks, shifts traffic, then drains the old ones. The app also recycles
gunicorn workers (`max_requests`) and reuses DB connections (`CONN_MAX_AGE`).

**"How do you handle database migrations in a deploy?"**
Migrations run once, as a dedicated step before the code rollout — never inside the
web container's startup where N containers would race. Every migration is
backward-compatible with the still-running old code (expand/contract): add-then-
backfill-then-switch-then-drop across multiple deploys, never a destructive change
in the same release that introduces its replacement.

**"Why Docker? Why multi-stage?"**
One artifact that runs identically on a laptop and in prod — no "works on my
machine". Multi-stage keeps build tooling and the pip cache out of the runtime
image: smaller, faster to pull, less to attack. The image also runs as a non-root
user and ships with static files pre-collected.

**"Why is Celery a separate container?"**
A background job (email fan-out, an OpenAI call) must not hold an HTTP worker
hostage, and it scales on queue depth, not request rate. `beat` is a third
container because the scheduler must be a singleton — two would double-fire every
cron job.
