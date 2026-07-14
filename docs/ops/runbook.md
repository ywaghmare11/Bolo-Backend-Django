# Operations Runbook

> **Last updated:** 2026-07-10 — observability stack live; replaced TBD stubs with real links.
> Every on-call developer should read this before their first shift.

---

## First principles for incidents

1. **Don't panic.** Open this document first.
2. **Communicate early.** Post in the incident channel as soon as you start investigating — even if you have no answer yet.
3. **Preserve evidence.** Copy logs and error messages before restarting services.
4. **Rollback is valid.** A fast rollback is better than a slow fix. Deploy the previous working version first; investigate root cause second.

---

## Where to look

| What to check | Where |
|---|---|
| Application logs (structured JSON) | Grafana → Loki — query `{service_name="bolo-backend"}` |
| API metrics (latency, error rate, throughput) | Grafana → BOLO Observability dashboard → Application Level section |
| Tenant-level usage (who's hitting what) | Grafana → BOLO Observability dashboard → Tenant Level section |
| Distributed traces (slow request deep-dive) | Grafana → Jaeger (dev/staging) or Grafana Cloud Traces (prod) |
| Error logs | `{service_name="bolo-backend", level="error"}` in Grafana Loki |
| DB health (connections, slow queries) | RDS CloudWatch metrics (prod) · `pg_stat_activity` directly (dev) |
| Recent deploys | GitHub Actions → `bolo-backend` / `bolo-web` workflows |
| Full observability setup + query reference | [`docs/ops/observability.md`](./observability.md) |

> **Prod Grafana:** Grafana Cloud account (credentials in AWS Secrets Manager).
> **Dev/Staging Grafana:** `http://localhost:3001` (Docker Compose) or OpenShift Route for `grafana`.

---

## Alert triage playbooks

### API 5xx error rate > 1% for 5 minutes

1. **Open Grafana → BOLO Observability → Error Rate by Route** — identify which routes are failing.
2. **Open Grafana Loki** — query `{service_name="bolo-backend", level="error"}` for the error message and stack trace.
3. Check if a deploy happened in the last 30 minutes → if yes, roll back (see [`deployment.md`](./deployment.md)) — rollback is ~60s via image tag swap.
4. If a specific route: open a trace for that route in Jaeger/Grafana Cloud Traces (click TraceID link from the Loki error log line).
5. Check third-party services (Sarvam STT, SMTP) — are they returning errors?
6. If DB is the issue: check `pg_stat_activity` for blocking queries.
7. No root cause found → escalate.

**Useful LogQL:**
```logql
{service_name="bolo-backend", level="error"} | json | line_format "{{.msg}} | route={{.route}} | err={{.err}}"
```

---

### High API latency (P95 > 500ms sustained)

1. **Open Grafana → p95 Latency by Route** — identify which specific route is slow.
2. Open a trace for that route in Jaeger — find where time is spent (DB query, external HTTP, serialization).
3. Check for N+1 queries: look for many repeated short DB spans in the trace waterfall.
4. Check DB CPU and I/O (RDS CloudWatch in prod, `pg_stat_activity` in dev).
5. Check evidence upload traffic — large files should use pre-signed S3 URLs and never pass through the backend.
6. Check if a new deploy changed the slow endpoint.

**Useful PromQL:**
```promql
histogram_quantile(0.95, sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))
```

---

### DB connection pool exhausted

1. Check `pg_stat_activity` for long-running queries (look for `state = 'active'` rows older than 30s).
2. Kill blocking queries if safe to do so.
3. Check for missing DB indexes on a recently-added feature — Prisma explain a slow query.
4. Temporarily increase pool size in `prisma.ts` as a stop-gap while investigating root cause.

---

### Notification delivery failing (in-app / email)

**In-app notifications:**
1. Check `{service_name="bolo-backend"} | json | msg=\`dispatch notification\`` in Loki — look for error fields.
2. Verify the `Notification` rows exist in DB (`SELECT * FROM "Notification" ORDER BY "createdAt" DESC LIMIT 20`).

**Email notifications (TASK_REMINDER, TASK_DUE_TODAY/TOMORROW, TASK_OVERDUE):**
1. Check Loki for SMTP errors: `{service_name="bolo-backend", level="error"} | json | msg=\`email send failed\``.
2. Verify SMTP credentials are set (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` in env).
3. Email failures are swallowed (logged, not thrown) — the task operation will have succeeded even if email failed.

---

### Evidence / voice file upload failures

1. Check S3 bucket availability and IAM role permissions.
2. Verify pre-signed URL expiry — default may be too short for slow mobile connections; increase if needed.
3. Check file size limits (per-file limit TBD — see `docs/product/open-questions-web-v1.md`).
4. Check `{service_name="bolo-backend", level="error"} | json | route=\`/evidence\`` in Loki.

---

## Escalation path

| Severity | Action |
|---|---|
| Can resolve alone | Fix and post update |
| Need help | Ping tech lead |
| Production down, cannot resolve | Call tech lead (TBD — add phone number) |

---

## Post-incident review template

After every significant incident, fill this in and store it in `docs/ops/incidents/YYYY-MM-DD-short-title.md`.

```markdown
## Incident: <title>
**Date:** YYYY-MM-DD
**Duration:** X hours Y minutes
**Severity:** P1 (production down) / P2 (degraded) / P3 (minor)
**On-call:** Name

### Timeline
- HH:MM — Alert fired
- HH:MM — Investigation started
- HH:MM — Root cause identified
- HH:MM — Fix deployed / rollback completed
- HH:MM — Resolved

### Root cause
...

### What went well
...

### What could be improved
...

### Action items
- [ ] Action 1 — Owner
- [ ] Action 2 — Owner
```
