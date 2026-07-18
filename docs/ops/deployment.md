# BOLO — Deployment & DevOps

> **Last updated:** 2026-07-10 — full AWS deployment architecture locked (all 7 groups decided).
> Status: Infrastructure locked (AWS). **Both Responsive Web and desktop-installable PWA ship in V1** (W29 resolved — PWA is desktop-screen-scoped, no offline). Native app store pipelines are out of scope for V1.

---

## Deployment pipeline (locked 2026-07-08)

**Sequential, staging-gated flow — never skip a stage:**

```
OpenShift dev (temp, expires ~Jul 26)
        │
        │  complete feature + integration testing
        ▼
AWS Staging (ap-south-1) ← target before Jul 26
        │
        │  full application testing — must be GREEN
        │  (no prod setup begins until staging is confirmed green)
        ▼
AWS Production (ap-south-1)
```

- **OpenShift → AWS Staging** is the immediate migration target. Staging must be live before sandbox expiry (~Jul 26).
- **Staging → Production** is gated on testing, not a date. No production infrastructure is provisioned until the staging environment passes full application testing.
- **Deployment pattern on all AWS environments:** Docker Compose on EC2 (locked 2026-07-08). ECS is the upgrade path at 500+ concurrent users — not needed for MVP.

---

## Environments

| Environment | Purpose | Branch | Platform | S3 bucket |
|---|---|---|---|---|
| `dev` | OpenShift sandbox — **temp until ~Jul 26** | any feature branch | OpenShift (US-East, test data only) | `bolo-staging` (shared — see note below) |
| `staging` | Pre-production QA + full application testing | `staging` branch | AWS EC2 ap-south-1 | `bolo-staging` |
| `production` | Live user traffic — provisioned only after staging green | `main` branch | AWS EC2 ap-south-1 | `bolo-production` |

> **S3 sharing — dev uses staging bucket (locked 2026-07-08):** The OpenShift dev environment points at the AWS `bolo-staging` S3 bucket directly. No separate dev S3 bucket is provisioned — the sandbox is temporary (~18 days remaining) and the overhead is not worth it. **Consequence:** evidence files and voice recordings uploaded from OpenShift land in the staging bucket. Use a key prefix (`dev/`) in the OpenShift env to distinguish dev uploads from staging app uploads if cleanup is needed later. DPDP note: files (not user PII) leave OpenShift US-East infra and land in AWS ap-south-1 — acceptable since S3 is the permanent store regardless.

> **DPDP constraint on OpenShift dev:** No real user data on the sandbox — test data only. Sandbox runs on US-East Red Hat infra, not India region. S3 files routed directly to ap-south-1 are fine.

### Dev environment — OpenShift Developer Sandbox (2026-06-26 to ~2026-07-26)

**Status: Approved for dev/test only. Test data only — no real user data (DPDP constraint: sandbox runs on US-East Red Hat infra, not India region).**

#### Status: LIVE (2026-06-26) — CI/CD fully configured

**GitHub Actions CI/CD (`github.com/integrate18/bolo-backend` → Actions → Deploy to OpenShift):**
- Trigger: manual `workflow_dispatch` only — pick branch from "Use workflow from" dropdown
- Auth: `github-actions` service account (`github-actions-sa-token` — non-expiring)
- Flow: `oc login` → `oc start-build --commit=<branch>` → `oc rollout status`
- Secrets required in GitHub repo: `OPENSHIFT_TOKEN`, `OPENSHIFT_SERVER`

#### Status: LIVE (2026-06-26)
- **Backend URL:** `http://bolo-backend-techbrutal1151-dev.apps.rm1.0a51.p1.openshiftapps.com` ⚠️ HTTP only — edge TLS not configured on route; HTTPS returns "Application not available"
- **Namespace:** `techbrutal1151-dev`
- **PostgreSQL:** `postgresql` service (PVC-backed, `1Gi`)
- **Backend pod:** `Running 1/1` — Prisma migrations run at startup, server on port 3000
- **Known issue:** Cookie is issued with `Secure` flag (`NODE_ENV=production`) but route is HTTP — Postman/browser will not send the cookie back automatically. Workaround: pass `Cookie: token=<value>` manually as a request header. Fix: enable edge TLS on the route (`oc patch route bolo-backend -p '{"spec":{"tls":{"termination":"edge"}}}'`) or add `COOKIE_SECURE` env var to decouple secure flag from NODE_ENV.

#### Required env vars on OpenShift (set via `oc set env`)

| Var | Value | Why |
|---|---|---|
| `DATABASE_URL` | `postgresql://bolo:<secret>@postgresql:5432/bolo` | Prisma DB connection |
| `JWT_SECRET` | `<secret>` | JWT signing |
| `COOKIE_SECURE` | `true` | Enables `Secure` flag on JWT cookie (HTTPS only). Without this the cookie is sent over HTTP but Secure is required when OpenShift route uses HTTPS termination. |

```bash
oc set env deployment/bolo-backend COOKIE_SECURE=true -n techbrutal1151-dev
```

#### Files committed — branch `chore/openshift-cicd` on `github.com/integrate18/bolo-backend`

| File | Purpose |
|---|---|
| `Dockerfile` | OpenShift S2I build + local Docker builds |
| `docker-compose.yml` | Local dev — runs postgres + backend together |
| `.dockerignore` | Excludes `node_modules`, `dist`, `.env`, logs from image |

#### Two-file strategy

**`docker-compose.yml` (bolo-backend repo root) — local dev only**
Defines both `postgres` and `backend` services. `docker-compose up` runs the full stack locally. Used by all developers; not deployed to OpenShift.

**OpenShift S2I + catalog — sandbox deployment**
OpenShift's Source-to-Image (S2I) feature builds and deploys the backend directly from the GitHub repo. PostgreSQL is provisioned from the OpenShift catalog (`postgresql-persistent` template). No separate manifest file required — OpenShift generates the `BuildConfig`, `DeploymentConfig`, `Service`, and `Route` automatically.

#### Pipeline (GitHub → OpenShift, automatic on every push)

```
git push → GitHub webhook → OpenShift BuildConfig (S2I Node.js)
                                      ↓
                            Builds Docker image from bolo-backend/
                                      ↓
                            Pushes to OpenShift internal registry
                                      ↓
                            Triggers DeploymentConfig rollout
                                      ↓
                            Init container: npx prisma migrate deploy
                                      ↓
                            Backend pod live on auto-provisioned HTTPS Route
```

#### Setup commands (run once after sandbox account is created)

```bash
# 1. Add PostgreSQL with persistent storage
oc new-app postgresql-persistent \
  -p POSTGRESQL_DATABASE=bolo \
  -p POSTGRESQL_USER=bolo \
  -p POSTGRESQL_PASSWORD=<secret>

# 2. Deploy backend from the OpenShift branch (# pins to the specific branch)
oc new-app https://github.com/integrate18/bolo-backend#chore/openshift-cicd \
  --name=bolo-backend \
  --strategy=docker

# 3. Inject secrets (never commit these)
oc set env deployment/bolo-backend \
  DATABASE_URL=postgresql://bolo:<secret>@postgresql:5432/bolo \
  JWT_SECRET=<secret>

# 4. Expose backend as public HTTPS URL
oc expose service/bolo-backend

# 5. Wire GitHub webhook: copy URL from OpenShift console → GitHub repo Settings → Webhooks
```

After step 5, every `git push` to the connected branch triggers a new build + deploy automatically.

#### Limits & expiry

- **Sandbox limits:** 7 GB RAM · 15 GB storage · 30-day account (extendable once)
- **PostgreSQL:** Always use `postgresql-persistent` (PVC-backed) — ephemeral template loses data on pod restart
- **Expiry:** ~2026-07-26. At expiry → migrate dev to local Docker Compose or provision AWS staging

**AWS ap-south-1 remains locked for staging + production.** This sandbox is a zero-cost shortcut during active development.

---

## AWS Architecture Decisions (locked 2026-07-10)

All 7 groups decided. Do not change without team discussion.

### Group 1 — Compute: Docker Compose on EC2

- **Pattern:** Docker Compose on EC2. Existing Dockerfiles used as-is.
- **Instances:** t3.small (staging) · 2× t3.medium (production)
- **Prod docker-compose services:** `bolo-backend` + `bolo-web` + `alloy` (3 containers only — no self-hosted observability stack)
- **Crash recovery:** `restart: unless-stopped` — auto-restarts within seconds on crash
- **Deployment downtime:** ~30 seconds (not zero-downtime — schedule deploys off-hours). Zero-downtime is ECS Fargate territory; upgrade trigger is 3,000–5,000 MAU.
- **Upgrade path:** Docker Compose → ECS Fargate when traffic justifies it. Dockerfiles don't change.

### Group 2 — Observability: Grafana Cloud free tier

- **Single Grafana Cloud account** covers both staging and production
- Alloy is the only observability container that runs on EC2 — ships data to Grafana Cloud
- Prometheus, Loki, Jaeger, Grafana do NOT run on EC2 in production (replaced by Grafana Cloud managed versions)
- Environments separated by `env` label in Alloy relabel config (`env=staging` / `env=production`)
- **Free tier covers MVP:** 10K metric series + 50GB logs/month (BOLO uses ~5% of limits)
- **Note:** Observability data (logs/metrics/traces — not user PII) routes to Grafana Cloud's US/EU servers. Client approval obtained (see `deployment-proposal-client.md` item 4).

### Group 3 — Networking

- **Domain:** Team owns domain. Subdomains: `staging.<domain>` and `app.<domain>` (or `api.<domain>`)
- **TLS/SSL:** Cloudflare free tier — Full SSL mode with Cloudflare Origin Certificate (free, 15-year validity). No Certbot/Let's Encrypt on EC2. Unlimited bandwidth on Cloudflare free tier.
- **VPC:** Default AWS VPC. Security groups only — no custom VPC needed at MVP scale.
- **Security groups:**
  - EC2: inbound 80 + 443 from `0.0.0.0/0` (Cloudflare proxy) · inbound 22 from team IPs only
  - RDS: inbound 5432 from EC2 security group only — NOT from internet

### Group 4 — CI/CD: GHA + AWS ECR + SSM Run Command (locked 2026-07-10)

- **Trigger:** `workflow_dispatch` (manual) for both staging and production. No auto-deploy on push.
- **Deploy method:** GHA uses `aws ssm send-command` to run the deploy script on EC2 via AWS Systems Manager. **No SSH, port 22 closed on EC2.**
- **Image registry:** AWS ECR (ap-south-1). Pull from same-region EC2 = free data transfer.
- **Image tagging:** `:latest` + commit SHA tag (e.g. `:abc1234`) on every build
- **Retention:** ECR lifecycle policy keeps last 4 images per repo. Older images auto-deleted.
- **Rollback:** Change image tag in `docker-compose.yml` on EC2 → trigger deploy workflow (~60 seconds)
- **Audit trail:** Every deploy command logged in AWS CloudTrail automatically.
- **GHA secrets required:** `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` · `EC2_INSTANCE_ID`
  - ~~`EC2_SSH_PRIVATE_KEY`~~ — removed. No SSH key anywhere.
- **IAM permissions needed on the GHA IAM user:** `ecr:*` (already needed for image push) + `ssm:SendCommand` + `ssm:GetCommandInvocation` + `ec2:DescribeInstances`
- **EC2 requirement:** SSM agent pre-installed (comes standard on Amazon Linux 2023). EC2 instance profile must have `AmazonSSMManagedInstanceCore` policy attached.
- **Cost:** SSM Run Command is free for EC2 instances.

**Full deploy flow:**
```
GHA workflow_dispatch
  1. docker build bolo-backend  → tag :latest + :<commit-sha>
  2. aws ecr get-login-password | docker login ECR
  3. docker push to ECR (ap-south-1)
  4. docker build bolo-web      → tag :latest + :<commit-sha>
  5. docker push to ECR
  6. aws ssm send-command → EC2 runs:
       cd /app && docker compose pull && docker compose up -d
  7. aws ssm get-command-invocation → poll until SUCCESS/FAILED
  8. GHA marks deploy success or fail (no SSH involved at any step)
```

### Group 5 — Secrets: 3-Way Split

Secrets are split by who needs them and when:

**GitHub Secrets** — CI/CD pipeline credentials only (free):
- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` — GHA pushes images to ECR and sends SSM commands
- `EC2_INSTANCE_ID` — target EC2 instance for SSM Run Command
- ~~`EC2_SSH_PRIVATE_KEY`~~ — removed (SSM, not SSH)
- ~~`EC2_HOST`~~ — removed (SSM targets by instance ID, not IP)

**AWS Secrets Manager** — sensitive runtime secrets the app needs (₹165–200/month for 4–5 secrets):
- `DATABASE_URL` (full connection string, password embedded — not a separate `DB_PASSWORD` secret; Prisma needs one assembled string, storing both duplicates the password across two stores with no consumer for the standalone value — decided 2026-07-16)
- `JWT_SECRET`
- Third-party API keys (Voice AI SDK, OpenAI, etc.)
- ~~`SMTP_PASSWORD`~~ — removed 2026-07-16, see below (SES decided, W100)

**AWS SSM Parameter Store standard tier** — non-sensitive config (free):
- `NODE_ENV`, `PORT`
- `S3_BUCKET_NAME`, `AWS_REGION`
- ~~`SMTP_HOST`, `SMTP_FROM`~~ — removed 2026-07-16, see below

**Transactional email — AWS SES (decided 2026-07-16, client-confirmed, resolves W100):** was previously documented as Gmail SMTP via nodemailer; client confirmed SES instead, matching `prd.md`/`security.md`/`api-spec.md`/`sprint-plan-4w.md` (those docs had SES all along — this was a stale-doc drift, not a new decision). Domain-verified in SES as of 2026-07-17 (Step 8). `bolo-ec2-role` granted `ses:SendEmail` + `ses:SendRawEmail`. **Transport decided 2026-07-18: AWS SDK (`@aws-sdk/client-ses`), not the SMTP interface** — IAM-role-only via the default provider chain, consistent with how this project accesses S3/ECR, no new secret to manage. `src/utils/email.ts` implemented accordingly; `nodemailer` removed from `bolo-backend`.

- EC2 IAM role grants read access to both Secrets Manager and SSM — no static credentials in `.env` for these
- Startup script fetches from Secrets Manager + SSM → writes to `/app/.env` → `docker compose up -d` reads it
- **Never commit secrets to Git. Never hardcode in `docker-compose.yml`.**
- Security boundary: if GHA is compromised, attacker gets deploy credentials only — DB password and JWT_SECRET are unreachable (AWS IAM role, runtime only)

### Group 6 — Database: Fresh RDS, no migration

- **Fresh RDS PostgreSQL** instance for staging. No data migrated from OpenShift sandbox (test data only — not worth migrating).
- Run `npx prisma migrate deploy` against new RDS on first deploy — creates all tables from migration files.
- **Staging:** db.t3.small, Single-AZ, 20GB gp3
- **Production:** db.t3.medium, Multi-AZ, 50GB gp3 (same fresh start — prod is set up after staging is green)
- RDS in private subnet (security group blocks all internet access, only EC2 security group allowed on 5432)

### Group 7 — S3

- **Bucket naming:** `bolo-staging` (shared between OpenShift dev + AWS staging) · `bolo-production`
- **Folder structure inside `bolo-staging`:**
  ```
  bolo-staging/
  ├── dev/          ← OpenShift dev environment (S3_PREFIX=dev/)
  │   ├── evidence/
  │   └── voice/
  └── staging/      ← AWS staging environment (S3_PREFIX=staging/)
      ├── evidence/
      └── voice/
  
  bolo-production/  ← separate bucket entirely
  ├── evidence/
  └── voice/
  ```
- OpenShift dev env var: `S3_PREFIX=dev/` — all uploads prepend this prefix. AWS staging env var: `S3_PREFIX=staging/`. Production has no prefix (or `S3_PREFIX=` empty).
- **Auth:** IAM role on EC2 (not IAM user with access keys). EC2 instance profile grants S3 read/write to the appropriate bucket. No `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` needed in `.env` for S3.
- **ECR pull auth:** Same IAM role also grants `ecr:GetAuthorizationToken` + `ecr:BatchGetImage` for image pulls.

---

## CI/CD pipeline (GitHub Actions — planned)

### On every PR to `dev`:
1. Install dependencies
2. Lint (`eslint --max-warnings 0`)
3. Type check (`tsc --noEmit`)
4. Run unit tests
5. Run integration tests (against ephemeral test DB)
6. Security audit (`npm audit --audit-level=high`)
7. Build (fail if build errors)

### On `workflow_dispatch` → staging or production:
1. Build Docker images (bolo-backend + bolo-web)
2. Push to AWS ECR (tagged `:latest` + `:<commit-sha>`)
3. SSH into EC2
4. `docker compose pull && docker compose up -d`
5. Health check: `curl /api/v1/health`

---

## Infrastructure (Locked)

| Component | Choice | Status |
|---|---|---|
| Cloud provider | **AWS ap-south-1 (Mumbai)** | ✓ Locked (2026-05-30) |
| Compute | **EC2 (t3 family)** | ✓ Locked |
| DB | **RDS PostgreSQL, Multi-AZ production** | ✓ Locked (2026-05-30) |
| Object storage | **S3 (evidence; optional voice audio)** | ✓ Locked — no GPS on web |
| CDN | CloudFront (optional — see below) | Optional |
| Search | **AWS OpenSearch Service** (t3.small dev, t3.medium prod) | ✓ Locked (2026-06-04); search scope W24 |
| Scheduler | **AWS EventBridge Scheduler + Lambda** (reminders + due-date) | ✓ Locked (2026-06-04) |
| Push notifications | Web push (Web Push API / FCM-web) | Desktop PWA confirmed (W29) — in scope V1; native FCM/APNs deferred with mobile |
| Monitoring | **CloudWatch** (free tier) | ✓ Locked (2026-06-04) |
| Error tracking | **Sentry** (free tier, 5K events/month) | ✓ Locked (2026-06-04) |
| Log aggregation | **CloudWatch Logs** (5 GB free/month) | ✓ Locked (2026-06-04) |
| App logging library | **pino** (structured JSON, via `pino-http` for request/correlation IDs) | ✅ **Implemented (2026-07-01)** — replaces ad-hoc `console.log`; see `tech-playbook/decisions/backend.md` |
| Metrics | **prom-client** (`GET /metrics`, Prometheus exposition format) | ✅ **Implemented (2026-07-01)** |
| Tracing | **OpenTelemetry SDK** (auto-instrumented Express/HTTP, OTLP export) | ✅ **Implemented (2026-07-01)** — Express/HTTP spans only. **Prisma child spans dropped**: `@prisma/instrumentation@5.22.0` (matching the pinned Prisma version) requires `@opentelemetry/sdk-trace-base@^1.22`, incompatible with the current `@opentelemetry/sdk-node@^0.219` (`sdk-trace-base@^2.x`) — crashes at runtime (`parentTracer.getActiveSpanProcessor is not a function`). Not fixable by re-pinning; would require downgrading the whole OTel stack ~2 years. Revisit if/when Prisma is upgraded past the npm/pnpm-layout issue blocking v6/v7 (see 2026-07-01 "Auth, build fixes" entry in `changelog.md`). |
| Prisma query logging (partial substitute) | Prisma's native `log: [{level:'query', emit:'event'}]`, routed through `pino` (`config/prisma.ts`) | ✅ **Implemented (2026-07-01)**, but **not trace-correlated** — verified via `trace.getActiveSpan()` that the OTel active-span context does not survive into the `$on('query')` callback (Prisma's query engine response arrives outside the original request's async chain). Gives SQL + duration for every query, readable in log order, but cannot be filtered by `trace_id`. True trace-correlated DB spans still require `@prisma/instrumentation` (blocked, see row above). |
| Observability agent | **Grafana Alloy** (single collector — ships logs/metrics/traces to their backend) | ✅ **Verified end-to-end (2026-07-01)** — `docker compose up`, confirmed logs/metrics/traces all flow through Alloy to their respective backends |
| Dev observability backend | **Prometheus + Loki + Jaeger + Grafana**, self-hosted via `docker-compose` | ✅ **Verified end-to-end (2026-07-01)** — see verification note below |
| Prod observability backend | TBD — stay on CloudWatch+Sentry, migrate to self-hosted Grafana stack, or Grafana Cloud | ⏳ **Open — W70**, deferred. Producer code is identical regardless of the answer; only Alloy's prod config changes. |

> **Note (2026-07-01):** CloudWatch Logs / Sentry were locked as destinations, but `bolo-backend` had no structured producer feeding them — only scattered, unstructured `console.log`/`console.error` calls (no levels, no request correlation, no PII redaction). The new producer stack (pino + prom-client + OpenTelemetry) closes this gap and is backend-agnostic — it can ship to CloudWatch or Grafana, decided per environment by Alloy's config alone, single backend per env (not dual-ship — see W70).
>
> **Verified end-to-end (2026-07-01):** `npm run type-check` and `npm run build` both pass; `dist/instrument.js` boots correctly (production build path). Tested against a real local Postgres instance — `GET /health`, `GET /metrics` (default Node metrics + custom `http_requests_total`/`http_request_duration_seconds`), and a full `POST /api/tasks` call all work. Confirmed: every log line for one request shares the same `trace_id` (5 lines for one `createTask` call — request received → validating assignee → assignee verified → row created → request completed — all one `trace_id`, auto-injected by OTel's pino auto-instrumentation, no custom correlation code needed). Full architecture + sample flow: `docs/architecture/system-design.md` §10.1.
>
> **Logging depth convention going forward:** two tiers. **Tier 1 (automatic, zero per-endpoint code):** 4 lifecycle log lines from shared middleware, applying to every current and future endpoint with no per-controller change — `request received` (`index.ts`) → `request authenticated` (`auth.middleware.ts`, fires on any `requireAuth` route — userId/tenantId/roleLevel) → `role check passed` (`rbac.middleware.ts`, fires only on routes that also use `requireOrgRole`) → `request completed` (`pino-http`, status + duration) — plus one error log line on any unhandled exception. Non-role-gated authenticated routes get 3 of the 4 (no role-check stage); public routes (health, login) get 2 (received + completed) since there's no auth step to log. **Verified (2026-07-01):** `GET /api/tenant` (role-gated) produced exactly these 4 lines, all sharing one `trace_id`. **Tier 2 (manual, developer's judgment):** business-event log lines inside a service at meaningful checkpoints (e.g., `createTask.service.ts` logs at validation, assignee-verified, row-created) — added selectively, same judgment call as deciding an `AuditLog` write, not blanket-applied to every line of every service.

### Local dev observability stack

Added to `bolo-backend/docker-compose.yml` alongside the existing `postgres` + `backend` services:

| Service | Image | Purpose |
|---|---|---|
| `prometheus` | `prom/prometheus` | Receives metrics via remote-write from Alloy (`--web.enable-remote-write-receiver`) |
| `loki` | `grafana/loki` | Receives log lines forwarded by Alloy |
| `jaeger` | `jaegertracing/all-in-one` | Receives OTLP trace spans forwarded by Alloy |
| `alloy` | `grafana/alloy` | Single agent — tails `backend` container stdout (via Docker socket) → Loki; scrapes `/metrics` → Prometheus; receives OTLP on 4317/4318 → Jaeger |
| `grafana` | `grafana/grafana` (host port `3001`, `3000` is taken by `backend`) | Dashboards; pre-provisioned datasources for Prometheus, Loki, Jaeger via `observability/grafana-datasources.yml` |

Config files: `bolo-backend/observability/prometheus.yml`, `alloy-config.alloy`, `grafana-datasources.yml`. All free/OSS, runs entirely on a dev machine via `docker-compose up`, no AWS cost.

**Everything is per-machine, not shared (2026-07-02):** `docker compose up` starts all 7 containers (`postgres`, `backend`, `prometheus`, `loki`, `jaeger`, `alloy`, `grafana`) on whichever machine runs it, fully isolated. Two developers each running the stack get two separate Postgres instances, two separate Loki/Prometheus/Jaeger datasets — nothing is centralized between team members. This is intentional for local dev; a shared/production backend is a separate, later decision (W70, still open).

**Running the backend without Docker (`npm run dev`):** works fine, but only the logging tier is meaningfully useful on its own — pino writes structured JSON straight to your terminal (`LOG_PRETTY=true` locally for readability), no Alloy needed. `GET /metrics` still serves real data but nothing scrapes it unless Prometheus/Alloy is pointed at it. OpenTelemetry still generates spans but the OTLP export silently fails if nothing's listening on `OTEL_EXPORTER_OTLP_ENDPOINT` (`localhost:4318`) — no crash, just no captured traces. **Hybrid option** (native backend + full Grafana visibility): run everything except `backend` via Compose (`docker compose up -d postgres prometheus loki jaeger alloy grafana`) and run the backend natively — works for logs/metrics/traces since Alloy's ports are host-published, but `alloy-config.alloy`'s `prometheus.scrape "backend"` target (`backend:3000`, a Docker-internal name) would need to become `host.docker.internal:3000` for Alloy to reach the natively-running process. Not yet implemented — a documented option, not the default flow.

**Verified end-to-end (2026-07-01)** via `docker compose up` — 5 real bugs found and fixed along the way (only surfaced by actually running the stack, not by type-check/build):
1. Host port `5432` conflicted with a local Postgres instance — compose's own `postgres` remapped to host port `5433` (internal container-to-container connection on `5432` unaffected).
2. `Dockerfile`'s `CMD` still hardcoded `node dist/index.js`, bypassing the `instrument.ts`/`.js` entry point entirely — tracing would have silently never initialized in the container. Fixed to `node dist/instrument.js`.
3. `prometheus.yml` had its own `scrape_configs` job for the backend, duplicating what Alloy's `prometheus.scrape` + remote-write already does — removed; Prometheus now only needs `--web.enable-remote-write-receiver`.
4. Alloy's `discovery.docker` finds every container on the host (postgres, loki, prometheus, itself, ...) with no relabeling, so all logs landed under one generic `unknown_service` label in Loki — added a `discovery.relabel` step mapping `__meta_docker_container_name` → `service_name`.
5. `pino-pretty` was tied to `NODE_ENV=development` (which `docker-compose.yml` sets for the backend), fragmenting every structured JSON log line into ~10 unparseable multi-line entries once ingested by Loki. Decoupled via a new `LOG_PRETTY` env var (opt-in, for local `npm run dev` only — never set in `docker-compose.yml`).

**Secrets handling (2026-07-01, updated 2026-07-18 — SMTP_* → SES_FROM_EMAIL):** `docker-compose.yml`'s `backend.environment` block references `SES_FROM_EMAIL`/`OPENAI_API_KEY`/`SARVAM_API_KEY` via `${VAR}` interpolation — real values live only in `bolo-backend/.env` (gitignored), which Compose automatically substitutes from since it sits in the same directory as `docker-compose.yml`. Never hardcode real secrets directly into `docker-compose.yml` — it's a tracked file in the `bolo-backend` repo. Verified via `docker compose config`.

**Confirmed working after fixes:** a real request's structured logs are queryable in Loki via LogQL (`{service_name="bolo-backend-backend-1"} | json | msg="request completed"`); metrics appear in Prometheus under `job="prometheus.scrape.backend"`; **a full multi-span trace** appears in Jaeger — Express auto-instrumentation breaks down every middleware (cors, jsonParser, cookieParser, metricsMiddleware, the route handler) as its own child span, richer than the single-root-span originally assumed; Grafana auto-provisions all 3 datasources (Prometheus, Loki, Jaeger) via `grafana-datasources.yml`.

**Loki label promotion (2026-07-01):** `alloy-config.alloy` adds a `loki.process` stage promoting `level`/`method`/`status` to real Loki labels (visible in Grafana's "Label filters" UI builder). Deliberately did **not** promote `trace_id` or raw `url` — both are effectively unique per request; doing so would create a new indexed Loki stream per request (documented "cardinality explosion" anti-pattern). Filter those via `| json` + a field match instead.

**Grafana dashboard, auto-provisioned (2026-07-01):** `observability/dashboards/bolo-observability.json` + `observability/grafana-dashboards-provider.yml`, mounted into the Grafana container — loads automatically on start into a "BOLO" folder, no manual import. Two rows:
- **Application Level** (Prometheus): request rate/error rate/p95 latency by route, plus process-level OS-adjacent stats (CPU, memory RSS, event-loop lag — no cAdvisor needed, see below).
- **Tenant Level** (Loki, not Prometheus — cardinality): requests per tenant, distinct active tenants, **API hits by tenant × route × status** (table), **failed requests by tenant × route** (table), top tenants by volume, p95 latency by tenant. Powered by enriching the `request completed` log line with `tenantId`/`route` via `requestLogger.middleware.ts`'s `customProps` — see `docs/architecture/system-design.md` §10.1.

**cAdvisor tried and removed (2026-07-01):** added for true container-level (OS/cgroup) CPU/memory/network metrics, but its container-name labeling didn't work cleanly on this Docker Desktop/WSL2 setup (only raw cgroup ID hashes, no readable names) — plus it needs `privileged: true` and host filesystem mounts, meaningful complexity for local dev. Dropped; the app's own process metrics already cover practical OS-adjacent visibility for local dev. Revisit cAdvisor (or the production equivalent — Kubernetes' built-in kubelet cAdvisor, AWS Container Insights) if/when this actually deploys to shared infra where per-container breakdown matters.

### Locked: Compute (EC2)

| Stage | Instance | Annual cost |
|---|---|---|
| Dev + Staging | 1 × t3.small (~6 weeks) | ₹1,250/mo |
| Production | 2 × t3.medium (500+ users) | ₹5,000/mo; Year 1 total ₹51,875 |

**Scaling by active users:**
- Up to 500: 2×t3.medium (₹5,000/mo)
- 500–1,500: 2×t3.large (₹9,960/mo)
- 1,500–3,000: 3×t3.large (₹14,940/mo)
- 3,000–6,000: 4×t3.xlarge (₹39,760/mo)

### Locked: Database (RDS PostgreSQL)

| Stage | Instance | HA | Monthly | Notes |
|---|---|---|---|---|
| Dev + Staging | db.t3.small | Single-AZ | ₹2,850 | 6 weeks, 20 GB gp3 |
| Production | db.t3.medium | **Multi-AZ** | ₹11,075 | 50 GB gp3, auto-failover ~60–120s |

**Scaling by active users (production Multi-AZ):**
- Up to 500: db.t3.medium (₹11,075/mo)
- 500–1,500: db.t3.large (₹21,075/mo)
- 1,500–3,000: db.r6g.large (₹28,000/mo)
- 3,000–6,000: db.r6g.xlarge (₹54,000/mo)

**Year 1 total: ₹114,740** (6 weeks dev at ₹2,850 + 10 months production at ₹11,075)

### Locked: Object Storage (S3)

- Voice recordings (audio from voice-to-task, ~500 KB per 60-sec clip) — storage is opt-in (W37); encryption at rest not in V1 (W44)
- Evidence files (photos, documents). No GPS metadata on web; DPDP-driven encryption deferred to V2 (W62)
- Estimated Year 1 usage: 25 MB/user/month (light usage assumption) × 500 users = ~12.5 TB
- Cost (Section 2.3 of ops cost estimate): TBD — to be calculated after we finalize retention policy

### Locked: Single-region deployment (MVP)

- **Region:** AWS ap-south-1 (Mumbai) — primary and only region for Year 1
- **No cross-region replication** for backup snapshots (RDS automated backups stay in ap-south-1)
- **No custom domain** — use internal Route 53 records for service discovery (api.internal, etc.)
- **Rationale:** Minimize complexity for MVP. If disaster recovery or global failover needed, add in Year 2 after product validation

### Pending: CDN (CloudFront) — OPTIONAL

**Decision:** S3-only for MVP (no CDN in baseline). If client requires sub-100ms latency or usage grows 2x, add CloudFront later (~₹1,800/year).
**Rationale:** S3 ap-south-1 meets latency SLAs for India. CDN is easy to add retroactively (no app code changes).

---

## Local development setup (to be written when code exists)

```bash
# Prerequisites: Node.js 20+, Docker, PostgreSQL
# Projects are separate (not a single workspace): bolo-backend (Express+Prisma) and bolo-web (React+Vite).

# 1. Clone repo
git clone <repo-url>
cd Bolo

# 2. Start backing services (DB, etc.)
docker-compose up -d

# --- Backend (bolo-backend) ---
cd bolo-backend
npm install
cp .env.example .env            # set DATABASE_URL, JWT_SECRET, PORT
npx prisma migrate dev          # apply Prisma migrations
npm run dev                     # start API

# --- Web (bolo-web) ---
cd ../bolo-web
npm install
cp .env.example .env            # set VITE_API_URL
npm run dev                     # start web dev server
```

---

## Backend build notes

### Prisma version
**Pinned to `5.22.0`** — both `prisma` CLI and `@prisma/client` must be on the same major version. v7.x was briefly installed and caused a missing `.wasm` file error on npm + Node.js 24 because v7 expects a pnpm directory structure. If either package is upgraded, upgrade both together.

```bash
npm install prisma@5.22.0 @prisma/client@5.22.0
```

### Voice JS modules in dist
`src/voice/intent.js` and `src/voice/voiceAdapter.js` are plain JS files — `tsc` does not copy them automatically. The build script handles this:

```json
"build": "tsc && node -e \"const fs=require('fs');...copy src/voice → dist/voice\""
```

**Do not add `allowJs: true` to `tsconfig.json`** — it causes a `RangeError: Maximum call stack size exceeded` in the TypeScript type checker due to recursive type resolution with Prisma-generated types.

---

## Database migrations

- Migrations are Prisma migration files in `bolo-backend/prisma/migrations/`
- Apply with: `npx prisma migrate deploy` (CI/prod) / `npx prisma migrate dev` (local)
- **Never edit a migration file after it has been applied to any shared environment.** Create a new migration instead.
- Always test on `staging` before applying a migration to `production`.

---

## Secrets management

- Production secrets: stored in cloud provider's secrets manager (AWS Secrets Manager / GCP Secret Manager)
- Never commit secrets to Git
- Rotate database credentials quarterly (minimum)
- API keys for third-party services (WhatsApp, voice AI) stored as secrets — not in environment variable files committed to Git

---

## Rollback procedure

1. Identify the failing deployment (check error tracking / logs)
2. Revert: redeploy the previous Docker image tag (no code change needed)
3. If a DB migration was applied: run rollback migration (tested on staging first)
4. Document incident in the ops runbook

---

## Monitoring checklist (to be configured)

- [ ] API error rate alert (> 1% 5xx errors over 5 min)
- [ ] API P95 latency alert (> 500ms for task list endpoint)
- [ ] DB connection pool exhaustion alert
- [ ] Voice AI service error rate alert
- [ ] Notification delivery failure alert (in-app; web push if enabled; **email for reminder/due-date types — in scope, corrected 2026-07-03**; WhatsApp out of scope for MVP)
- [ ] Evidence upload failure rate alert
- [ ] Disk/storage usage alert (S3 bucket approaching limit)
