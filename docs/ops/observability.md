# BOLO — Observability Runbook

> **Last updated:** 2026-07-10
> **Stack:** pino · prom-client · OpenTelemetry · Grafana Alloy · Prometheus · Loki · Jaeger · Grafana Cloud (prod)
> **Status:** Dev stack verified end-to-end. Prod target locked as Grafana Cloud free tier.

---

## 1. Architecture Overview

Three signal types — **logs, metrics, traces** — are emitted from the Express app, collected by a single Grafana Alloy sidecar, and shipped to per-signal backends. Grafana queries all three from one UI.

```
┌─────────────────────────────────────────────────────────────────┐
│                       Express Application                        │
│                                                                  │
│  ┌──────────────────┐  ┌─────────────────┐  ┌───────────────┐  │
│  │    pino-http     │  │   prom-client   │  │  OTel SDK     │  │
│  │  JSON log/req    │  │   GET /metrics  │  │  OTLP spans   │  │
│  └────────┬─────────┘  └────────┬────────┘  └───────┬───────┘  │
└───────────│────────────────────│───────────────────│────────────┘
         stdout              scrape :3000         HTTP :4318
       (k8s: pod logs)
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 ▼
                    ┌────────────────────────┐
                    │     Grafana Alloy      │
                    │  log tail  ·  scrape   │
                    │  OTLP recv ·  ship     │
                    └──────┬─────────┬───┬───┘
                    logs   │ metrics │   │ traces
                           │         │   │
                    ┌──────┘  ┌──────┘   └──────┐
                    ▼         ▼                  ▼
                 ┌──────┐ ┌──────────┐      ┌────────┐
                 │ Loki │ │Prometheus│      │ Jaeger │
                 └──┬───┘ └────┬─────┘      └───┬────┘
                    └──────────┴────────────────┘
                                    │
                                    ▼
                             ┌────────────┐
                             │  Grafana   │
                             └────────────┘
```

**Key principle: Alloy is the single collection boundary.**
No signal goes directly from the app to a backend. Swapping a backend (e.g. self-hosted Loki → Grafana Cloud Logs) requires only an Alloy config change — no app code change, no redeploy.

---

## 2. Component Reference

### 2.1 pino + pino-http — Structured Logger

**Files:** `src/observability/logger.ts` · `src/middleware/requestLogger.middleware.ts`

- Singleton `pino` instance exported as `logger`, used everywhere via `req.log.info(...)` or direct `logger.error(...)`.
- `pino-http` middleware writes **one JSON line per completed request** on `res.finish`, including: `method`, `url`, normalized `route`, `statusCode`, `responseTime`, plus `tenantId`/`userId`/`roleLevel` from `req.user` (populated by `requireAuth` before finish fires).
- If an OTel span is active, `trace_id` is injected into the log line — this is the Loki → Jaeger one-click link.
- **Redaction:** `req.headers.authorization`, `req.headers.cookie`, `*.password`, `*.otp` → `[REDACTED]`.

**Pretty-print rule:** Gated on `LOG_PRETTY=true`, **not** on `NODE_ENV`. Docker Compose sets `NODE_ENV=development`, which would break JSON parsing in Loki if we linked the two. Only set `LOG_PRETTY=true` for local `npm run dev` outside Docker.

---

### 2.2 prom-client — Metrics

**Files:** `src/observability/metrics.ts` · `src/middleware/metrics.middleware.ts`

Two custom metrics:

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `http_request_duration_seconds` | Histogram | method, route, status | p50/p95/p99 latency per route |
| `http_requests_total` | Counter | method, route, status | Request rate + error rate |

`collectDefaultMetrics()` adds Node.js process metrics automatically: CPU, RSS memory, heap, event loop lag, GC pause.

`GET /metrics` is **not behind `requireAuth`** — Alloy scrapes it as an infrastructure agent. It should be network-gated (internal network only) rather than token-gated.

---

### 2.3 OpenTelemetry — Distributed Tracing

**Files:** `src/instrument.ts` · `src/observability/tracing.ts`

- `src/instrument.ts` is the app entry point when running with tracing. Runs `dotenv.config()` first, then imports `tracing.ts`, then imports `index.ts`. **Order is critical** — OTel auto-instrumentation patches `http` and `express` at module-load time; if `index.ts` loads first, no spans are captured.
- `tracing.ts` initializes NodeSDK with `getNodeAutoInstrumentations()`. `fs` instrumentation disabled (`enabled: false`) — generates too many spans for file reads.
- Exports via OTLP HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT` (Alloy in Docker/OpenShift, or `localhost:4318` for direct local dev).

> **⚠️ Prisma spans unavailable:** `@prisma/instrumentation` pins `sdk-trace-base@^1.22`, incompatible with current OTel SDK (`sdk-trace-base@^2.x`). Runtime crash: `getActiveSpanProcessor is not a function`. Excluded until Prisma updates their package. Express + HTTP-level spans work fully.

---

### 2.4 Grafana Alloy — Collector / Shipper

**Config:** `observability/alloy-config.alloy` (local Docker) · ConfigMap `alloy-config` (OpenShift)

Handles all three signal types in one binary:

| Signal | Source | Destination |
|---|---|---|
| Logs | Docker stdout (local) / k8s pod logs (OpenShift) | Loki push endpoint |
| Metrics | Scrapes `bolo-backend:3000/metrics` every 15s | Prometheus `remote_write` |
| Traces | OTLP receiver on `:4317` (gRPC) and `:4318` (HTTP) | Jaeger via OTLP gRPC |

Only the `discovery.*` component differs between Docker and Kubernetes. The entire processing pipeline — JSON label promotion, Loki write, Prometheus remote_write, OTLP forward — is identical.

**Label promotion (low-cardinality only):** `service_name`, `level`, `method`, `status`, `pod` (OpenShift). High-cardinality fields (`tenantId`, `userId`, `trace_id`, `url`) stay in the JSON body and are parsed at query time with `| json`. Never promote high-cardinality fields to Loki labels.

---

### 2.5 Loki — Log Store

Queryable via LogQL. Low-cardinality Loki labels only (see §2.4). `tenantId` and `userId` are JSON fields, not labels — see §7 (Decisions) for why.

---

### 2.6 Prometheus — Metrics Store

Run with `--web.enable-remote-write-receiver` (not the default). Alloy does the scraping; Prometheus is metrics storage only. In local dev, data is lost on container restart (Docker named volume, not persistent EBS).

---

### 2.7 Jaeger — Trace Store

All-in-one image (collector + UI + in-memory store). **In-memory only** — traces are lost on restart. Acceptable for dev and OpenShift. For production, Grafana Cloud Traces (Tempo) provides persistent storage; only the Alloy OTLP exporter target URL changes.

---

### 2.8 Grafana — Dashboard UI

Datasources auto-provisioned from `observability/grafana-datasources.yml`:
- Prometheus (default datasource)
- Loki — with a `trace_id` derived field: parses `trace_id` from JSON and renders a "View Trace" link to jump directly to Jaeger.
- Jaeger

Dashboard auto-provisioned from `observability/dashboards/bolo-observability.json` (UID: `bolo-observability`). Two sections:

- **Application Level** — request rate, error rate, p95 latency by route, process CPU, process memory (RSS), event loop lag, total requests (1h).
- **Tenant Level** (derived from Loki LogQL metric queries) — authenticated requests per tenant, distinct active tenants, API hits by tenant × route × status, failed requests by tenant, top tenants by volume, p95 response time by tenant.

> **⚠️ Anonymous auth enabled in dev/OpenShift:** `GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin`. Never deploy with this outside a private network. Grafana Cloud (prod) uses proper authentication.

---

## 3. Local Dev Setup

### Start the full stack

```bash
# From bolo-backend/
docker-compose up
# Starts: postgres + backend + alloy + prometheus + loki + jaeger + grafana
```

### Ports

| Service | Port | Notes |
|---|---|---|
| Backend API | `3000` | Express; Swagger at `/api/docs`, metrics at `/metrics` |
| Grafana | `3001` | BOLO dashboard auto-loads; anonymous auth |
| Prometheus | `9090` | Raw PromQL explorer |
| Loki | `3100` | API only — query via Grafana Explore |
| Jaeger UI | `16686` | Trace search + waterfall |
| Alloy OTLP HTTP | `4318` | OTel SDK target when running in Docker |
| Alloy OTLP gRPC | `4317` | Alternative OTLP transport |

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `LOG_LEVEL` | `info` | pino level: `trace` / `debug` / `info` / `warn` / `error` |
| `LOG_PRETTY` | unset | Set `true` only for local non-Docker dev. Breaks Loki parsing inside Docker. |
| `OTEL_SERVICE_NAME` | `bolo-backend` | Service name label on traces in Jaeger / Grafana Cloud |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | Set to `http://alloy:4318` in Docker Compose or OpenShift |

### Config file map

| File | Purpose |
|---|---|
| `docker-compose.yml` | Full stack. `SES_FROM_EMAIL`/OpenAI/Sarvam keys read from `.env` via Compose substitution (updated 2026-07-18 — was `SMTP_*`). |
| `observability/alloy-config.alloy` | Alloy pipeline: Docker log discovery → label promotion → Loki; /metrics scrape → Prometheus; OTLP → Jaeger. |
| `observability/prometheus.yml` | Minimal Prometheus config — no scrape_configs (Alloy does scraping, Prometheus is remote_write target only). |
| `observability/grafana-datasources.yml` | Provisions Prometheus, Loki, Jaeger datasources. Loki datasource includes trace_id derived field. |
| `observability/grafana-dashboards-provider.yml` | Tells Grafana to auto-load JSON dashboards from `observability/dashboards/`. |
| `observability/dashboards/bolo-observability.json` | Pre-built BOLO dashboard. |

---

## 4. OpenShift Dev Environment

> **Sandbox expires ~Jul 26.** Migrate to AWS staging before expiry.

### Deploy

```bash
# Apply RBAC + Alloy + Prometheus + Loki + Jaeger + Grafana + Routes — all in one file
oc apply -f openshift/observability.yaml -n techbrutal1151-dev

# Get external URLs for Grafana and Jaeger UIs
oc get routes -n techbrutal1151-dev
```

### Differences from Docker Compose

| Aspect | Docker Compose | OpenShift |
|---|---|---|
| Log discovery | `discovery.docker` via Docker socket | `discovery.kubernetes` via Kubernetes API |
| Auth for log access | None — Docker socket | ServiceAccount + Role (get/list/watch pods, pods/log, endpoints, services) |
| Config delivery | Bind-mounted `.alloy` / `.yml` files | ConfigMaps |
| External access | Localhost port bindings | OpenShift Routes (TLS edge, auto HTTP→HTTPS redirect) |
| Storage | Docker named volumes | `emptyDir` — data lost on pod restart |

### RBAC

`observability.yaml` includes a `ServiceAccount` named `alloy`, a `Role` with `get/list/watch` on `pods`, `pods/log`, `endpoints`, `services`, and a `RoleBinding`. The `oc apply` user needs RBAC create permissions (sandbox admin has this by default).

### Pod label for log discovery

The backend pod from OpenShift's BuildConfig uses `deployment=bolo-backend`, not `app=bolo-backend`. The Alloy config has a fallback relabel rule that tries `app` first, then `deployment` — both cases are covered and the `service_name` label in Loki will read `bolo-backend` regardless.

---

## 5. Production — Grafana Cloud

**Decision (locked 2026-07-10):** Grafana Cloud free tier for all prod signal backends.

Free tier capacity: 50 GB logs/month · 10K active metric series · 50 GB traces · 14-day log retention · 13-month metric retention. Sufficient for MVP.

### What runs on prod EC2

Only: `bolo-backend` · `bolo-web` · `alloy`. Prometheus, Loki, Jaeger, and Grafana containers are **removed** from the prod Docker Compose file — saves ~1–2 GB RAM.

### What changes from dev to prod

| Item | Dev / OpenShift | Prod |
|---|---|---|
| Alloy log endpoint | `http://loki:3100/loki/api/v1/push` | Grafana Cloud Loki URL + basic auth |
| Alloy metrics endpoint | `http://prometheus:9090/api/v1/write` | Grafana Cloud Prometheus remote_write URL + basic auth |
| Alloy trace endpoint | `jaeger:4317` (no auth) | Grafana Cloud Tempo OTLP endpoint + basic auth |
| Loki/Prometheus/Jaeger/Grafana | Running in Compose / OpenShift pods | Not present — Grafana Cloud only |
| Grafana auth | Anonymous (no login) | Grafana Cloud account login |
| Data retention | Lost on restart | 14 days logs · 13 months metrics |
| Env separation | Separate Docker networks | Single Grafana Cloud stack — `env=staging` / `env=prod` label separates at query time |

### Alloy config changes for prod (changed blocks only)

```hcl
// Logs → Grafana Cloud Loki
loki.write "default" {
  endpoint {
    url = "https://logs-prod-xxx.grafana.net/loki/api/v1/push"
    basic_auth {
      username = env("GRAFANA_CLOUD_LOKI_USER_ID")
      password = env("GRAFANA_CLOUD_API_KEY")
    }
  }
}

// Metrics → Grafana Cloud Prometheus
prometheus.remote_write "default" {
  endpoint {
    url = "https://prometheus-prod-xxx.grafana.net/api/prom/remote/write"
    basic_auth {
      username = env("GRAFANA_CLOUD_PROM_USER_ID")
      password = env("GRAFANA_CLOUD_API_KEY")
    }
  }
}

// Traces → Grafana Cloud Tempo
otelcol.auth.basic "gc" {
  username = env("GRAFANA_CLOUD_TEMPO_USER_ID")
  password = env("GRAFANA_CLOUD_API_KEY")
}
otelcol.exporter.otlp "grafana_cloud" {
  client {
    endpoint = "tempo-prod-xxx.grafana.net:443"
    auth     = otelcol.auth.basic.gc.handler
    tls { insecure = false }
  }
}
```

> The actual hostnames come from your Grafana Cloud stack's **Connection details** page (different host per signal type, same API key for all three). Store user IDs and API key in AWS Secrets Manager — fetched by the EC2 IAM role at startup, written to `/app/.env`.

---

## 6. Key Queries

### LogQL — Loki

```logql
# All backend logs
{service_name="bolo-backend"}

# Errors only
{service_name="bolo-backend", level="error"}

# All completed requests for a specific tenant
{service_name="bolo-backend"} | json | msg=`request completed` | tenantId="<uuid>"

# Failed requests (4xx/5xx) by tenant
{service_name="bolo-backend"} | json | msg=`request completed`
  | tenantId != `` | res_statusCode >= 400

# Find a specific trace from a log line
# (click the TraceID derived field in Grafana to jump directly to Jaeger)
{service_name="bolo-backend"} | json | trace_id="<id>"

# Request rate per tenant (for a time-series panel)
sum by (tenantId) (
  count_over_time(
    {service_name="bolo-backend"} | json | msg=`request authenticated` [$__interval]
  )
)

# Top tenants by volume (instant query for a table panel)
sum by (tenantId) (
  count_over_time(
    {service_name="bolo-backend"} | json | msg=`request completed` | tenantId != `` [$__range]
  )
)
```

### PromQL — Prometheus

```promql
# Request rate by route
sum by (route, method) (rate(http_requests_total[1m]))

# Error rate — 4xx and 5xx
sum by (route, status) (rate(http_requests_total{status=~"4..|5.."}[1m]))

# p95 latency by route
histogram_quantile(0.95,
  sum by (le, route) (rate(http_request_duration_seconds_bucket[5m]))
)

# Event loop lag
nodejs_eventloop_lag_seconds{job="prometheus.scrape.backend"}

# Process memory (RSS)
process_resident_memory_bytes{job="prometheus.scrape.backend"}
```

---

## 7. Decision Log

### Why pino, not winston

Fastest Node.js logger by a wide margin (3–5× lower overhead than winston in benchmarks). Outputs NDJSON natively — no formatter plugin. `pino-http` auto-attaches request context to one log line per request with no boilerplate in each controller. `req.log` child logger scopes structured fields to a single request automatically.

Winston was ruled out: defaults to unstructured text (requires a JSON transport plugin), higher CPU overhead, no built-in per-request scope.

### Why prom-client, not a vendor APM

De facto standard for Node.js Prometheus metrics. Exposes a `/metrics` endpoint that any Prometheus-compatible scraper can consume — no vendor lock-in. Today it lands in self-hosted Prometheus; moving to Grafana Cloud Metrics or VictoriaMetrics is an Alloy config change only. Histogram primitives give proper p95/p99 latency.

Datadog APM / New Relic were ruled out: paid, vendor-locked, proprietary agents with significantly higher overhead. More than MVP requires.

### Why OpenTelemetry, not a vendor tracing SDK

Vendor-neutral CNCF standard. The backend (Jaeger → Grafana Cloud Tempo) is a config change in Alloy, not a code change in the app. Auto-instrumentation covers Express and HTTP with zero manual span code. OTLP is a stable wire protocol — any modern backend speaks it.

Vendor SDKs tie the app code to a specific backend; switching later requires touching every instrumented service.

### Why Grafana Alloy, not separate agents

Alloy handles logs, metrics, and traces in a single binary with one config syntax. The alternative — Fluent Bit for logs + Prometheus agent for metrics + OTel Collector for traces — means three agents to run, configure, monitor, and upgrade independently.

Only the `discovery.*` component differs between Docker Compose (Docker socket) and OpenShift (Kubernetes API). The rest of the pipeline is identical — one config maintained for both environments.

### Why Grafana Cloud for prod, not self-hosted on EC2

Free tier covers MVP scale (50 GB logs/month, 10K series, 50 GB traces). Removes Loki + Prometheus + Jaeger + Grafana containers from prod Docker Compose — frees ~1–2 GB RAM on the production instance. No EBS volumes to manage for Loki/Prometheus data, no backup strategy needed.

Self-hosted works fine in dev (free Docker images), but adds operational burden in prod that is not justified for MVP.

**Upgrade path:** Grafana Cloud free → paid if volume exceeds limits. Or deploy the exact self-hosted dev stack to a dedicated EC2/ECS service with EBS volumes if the team prefers on-prem.

### Why tenantId tracking in Loki, not Prometheus

Prometheus label cardinality: each unique label value combination creates a new time series. At scale (1,000 tenants × 50 routes × 3 status classes), `tenantId` as a Prometheus label = 150,000 series — well above the free-tier limit (10K).

Instead, `tenantId` is a JSON field in the pino-http log line. Alloy promotes only low-cardinality fields to Loki labels. Tenant breakdown happens at query time with `| json | tenantId="..."` — Loki does the filter, no new streams are created.

---

## 8. Known Limitations

| Limitation | Status | Notes |
|---|---|---|
| No per-query Prisma spans | **Blocked** | `@prisma/instrumentation` incompatible with current OTel SDK. Unblock by upgrading Prisma past the pnpm/Node 24 conflict (currently pinned at 5.22.0), then re-test. HTTP spans work fully. |
| Grafana anonymous auth | Dev only | Never deploy `GF_AUTH_ANONYMOUS_ENABLED=true` outside a private network. Grafana Cloud (prod) has proper auth. |
| Observability data lost on restart | Dev only | Docker volumes and OpenShift `emptyDir` are ephemeral. Dev data regenerates immediately. Grafana Cloud (prod) persists 14 days (logs) / 13 months (metrics). |
| No alerting configured | Deferred | No Grafana alert rules or notification channels yet. Error rate and latency panels exist in the BOLO dashboard — add alert thresholds in Grafana Cloud once prod is live and baseline traffic is observed. |
| Prisma pinned at v5.22.0 | Pending | v7.x crashes on npm + Node 24 (expects pnpm layout, missing `.wasm` file). Pinned until pnpm/Node conflict resolved. Also blocks Prisma instrumentation availability. |
| LOG_PRETTY in Docker | Resolved | Fixed: pretty-print gated on `LOG_PRETTY=true` env var, not `NODE_ENV`. Docker Compose never sets this var, so structured JSON always emits inside containers. |
| `allowJs: true` in tsconfig | Resolved | Removed from `bolo-backend/tsconfig.json` — caused RangeError stack overflow when tsc traversed Prisma's recursive types. Voice JS files are now copied post-tsc by the build script instead. |
