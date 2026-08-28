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

## 6. CD pipeline to AWS ECS Fargate (`.github/workflows/deploy.yml`)

Committed as a **reference, disabled** workflow (`workflow_dispatch` only, guarded
by `if: vars.AWS_REGION != ''`) — it does nothing until the AWS side and the
secrets/vars exist. When enabled, a merge to `main` runs:

1. **Authenticate to AWS via OIDC.** `aws-actions/configure-aws-credentials`
   exchanges a short-lived GitHub OIDC token for temporary AWS credentials by
   assuming an IAM role. **No long-lived AWS access keys are stored in GitHub.**

2. **Build & push the image to ECR.** Tagged with the **commit SHA** (immutable,
   traceable) plus `latest`. `docker push` to the Amazon ECR repo.

3. **Run migrations as a one-off ECS task**, *before* the rolling deploy:
   `aws ecs run-task … --overrides '…command":["python","manage.py","migrate"]'`.
   Migrations run **once**, not per web container, and complete before any new
   code serves traffic. This only works if migrations are backward-compatible —
   see §7.

4. **Register a new task-definition revision** with the new image
   (`amazon-ecs-render-task-definition`).

5. **Update the ECS service** to that revision
   (`amazon-ecs-deploy-task-definition`, `wait-for-service-stability: true`). ECS
   does a **rolling replace**: start new tasks → wait for their ALB health checks
   to pass → shift traffic → drain and stop the old tasks. If the new tasks never
   go healthy, ECS's circuit breaker rolls back automatically.

Where the dependencies live: **RDS** Postgres (Multi-AZ), **ElastiCache** Redis,
**S3** buckets, **SES** — all reached over the VPC's private subnets; the ECS task
role carries the S3/SES IAM permissions so the app needs no access keys.

---

## 7. Zero-downtime deploys & database migrations

Zero downtime comes from the **rolling replace + health checks** in §6.5 — old
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

- **App code:** re-point the ECS service at the previous task-definition revision
  (`aws ecs update-service --task-definition <family>:<prev>`) — or just re-run the
  deploy workflow with an older `image_tag`. ECS rolls forward to the old image the
  same way it rolled to the new one.
- **Database:** there is no automatic down-migration in production. Because
  migrations are expand/contract and backward-compatible, rolling the *code* back
  is safe without touching the schema. Destructive schema changes only ship once
  the previous release is no longer a rollback target.
- **Automatic:** the ECS deployment circuit breaker rolls back a release whose new
  tasks never pass health checks, with no human action.

---

## 9. Interview cheat-sheet

**"How do you deploy this?"**
GitHub Actions on merge to `main`: build a Docker image tagged with the commit SHA,
push to ECR, run DB migrations as a one-off Fargate task, then update the ECS
service, which does a rolling replace behind an ALB with health checks. Rollback is
re-pointing the service at the previous task-definition revision.

**"Walk me through your CI/CD."**
CI (every PR): four parallel jobs — ruff lint, pytest against a real Postgres+Redis,
`pip-audit` for dependency CVEs, and a Docker build + `manage.py check --deploy`.
`makemigrations --check` fails the build if a model changed without a migration.
CD (merge to main): OIDC into AWS (no stored keys) → build/push to ECR → migrate →
rolling ECS deploy with automatic rollback on failed health checks.

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
