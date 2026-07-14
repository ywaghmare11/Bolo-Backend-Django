# BOLO — Security Requirements & Controls

> Applies to all environments. Treat this as a checklist — check off items as they are implemented.
> **Last updated:** 2026-06-20 — audit log added to V1 (W63 resolved). Web PRD v1.1. **Web platform: no device GPS in V1.** Controls deferred: voice encryption (W44), DPDP (W62).

---

## Authentication & sessions

> **Decisions locked (W1, W2 resolved):** Email OTP only — no SSO, no passwords. Session-length httpOnly cookie — no refresh tokens.

- [x] Auth method: **Email OTP → JWT in httpOnly cookie** (`Set-Cookie: token=<jwt>; HttpOnly; SameSite=Lax; Max-Age=604800`). No Authorization header.
- [x] **Cookie settings (2026-06-30):**
  - `SameSite=Lax` (not Strict) — Strict blocks XHR/fetch from SPAs; Lax allows same-site API calls while still blocking cross-site CSRF.
  - `Secure` flag controlled by `COOKIE_SECURE=true` env var (not `NODE_ENV`) — off on HTTP dev, on for HTTPS prod.
  - `maxAge: 7 days` (604,800 s) — persistent cookie; survives browser close. Previously a session cookie (no maxAge) which caused token to disappear on tab/browser close.
- [x] JWT payload: `{ userId, tenantId, roleLevel }` — `tenantId` and `roleLevel` injected by `requireAuth` middleware; never trusted from request body.
- [x] **No refresh tokens** (W1 resolved) — session persists until explicit logout or cookie expiry (7 days). Single active session per user.
- [ ] **JWT itself has no `expiresIn`** — token never expires server-side; only the cookie expiry (7 days) limits session length. Add `expiresIn: '7d'` to `jwt.sign()` before production launch.
- [x] OTP: SHA-256 hashed before storage in `otp_codes` table. Plain OTP never stored or logged.
- [x] OTP delivery: SMTP (Gmail in dev; swap to SES in prod — no SMS, no WhatsApp). Rate limit: 1 OTP per 60 s per email. Pre-send SMTP RCPT TO probe catches dead domains/mailboxes before sending — returns `422 EMAIL_UNDELIVERABLE`. SMTP send failure returns `502 EMAIL_DELIVERY_FAILED`. OTP row rolled back on any delivery failure so user can retry immediately.
- [x] Failed OTP attempts: lockout after **3 wrong attempts** (tracked in `otp_codes.attempts` + `otp_codes.lockedUntil`). Lockout window: 15 min. Response includes `data.attemptsRemaining` on each wrong attempt. 15-min server-side cleanup job (`src/jobs/otpCleanup.job.ts`) sweeps expired/abandoned OTP rows — replace with EventBridge/pg_cron in production.
- [x] On logout: cookie cleared server-side (`Set-Cookie: token=; Max-Age=0`). OTP row already deleted at verify time — nothing extra to clean up.
- [ ] On account removal: `TenantMembership` row deleted; existing JWT remains valid until logout. (Acceptable for V1 — no token revocation list needed given single-session model.)

---

## Authorisation & tenant isolation

> **RBAC model (V1 — deliberately minimal per PRD §3.2):**
> Designations ("Dean", "Director", "HoD") are **display-only** (`TenantMembership.roleLabel`). They differ per tenant vertical but carry **zero permission logic**. All API gates use only:
> 1. **`roleLevel`** — universal 3-value enum (`TOP | MID | EXECUTOR`), same meaning across all tenants. Embedded in JWT. Checked by `requireOrgRole()` middleware.
> 2. **`canBroadcast`** — binary boolean on `TenantMembership`. The only permission NOT derived from roleLevel. Checked in `BroadcastService`, not middleware.
> 3. **Task-level ownership** — assigner vs assignee, derived from the Task row in the service. No roleLevel involved.
>
> No per-tenant permission customisation is needed or planned for V1.

| Gate | Checked by | Used for |
|---|---|---|
| `requireAuth` | `auth.middleware.ts` | Every route — validates JWT cookie, injects `req.user` |
| `requireOrgRole(['TOP'])` | `rbac.middleware.ts` | Member invite/remove, tenant admin ops |
| `requireOrgRole(['TOP','MID'])` | `rbac.middleware.ts` | Analytics, org chart |
| `canBroadcast` | `BroadcastService` | Creating/publishing broadcast notices |
| Assigner check | Service layer | Task edit, done-d, cancel, remind |
| Assignee check | Service layer | Task accept, done-a, subtask create |
| Owner check | Service layer | Sticky notes, personal labels, comments (author-only) |

- [x] `tenantId` always sourced from JWT, never from request payload
- [x] `roleLevel` embedded in JWT — `requireOrgRole()` is a pure in-memory check, zero extra DB round-trips
- [ ] Row-Level Security on `tenant_id` enforced at DB layer (PostgreSQL RLS policy)
- [ ] Integration tests assert cross-tenant data access is blocked for every entity type
- [ ] `canBroadcast` checked in BroadcastService before any create/publish operation

---

## Data protection — PII

PII in scope (web V1): phone numbers, email addresses, voice recordings, voice transcripts.
**GPS latitude/longitude is NOT collected in V1** — no device location API on web. (Returns with the Mobile PRD.)

- [ ] Voice recordings encrypted at rest — **deferred: not in V1 (W44)**; compress and store for now
- [ ] No PII logged to application logs or error tracking services
- [ ] PII transmitted only over HTTPS (TLS 1.2+)
- [ ] DPDP Act consent management — **deferred to V2 (W62)**
- [ ] Right to erasure: account deletion removes/anonymises personal data (reminders, audio); org data (tasks) is org-owned (W57)
- [ ] Data retention policies: voice audio kept 1 year then ask user (W41); org data after org deletion = archive → provide → delete (W58)

---

## Audit logging

> **In V1 (W63 resolved 2026-06-20).** `AuditLog` table in schema V1.1 — immutable, append-only rows covering all critical actions.

- [ ] Every critical action writes an `audit_log` record: task CRUD, status transitions, reassign, broadcast lifecycle, evidence upload/delete, user login/logout/profile change, role change
- [ ] Audit log is append-only — DB-level: no UPDATE or DELETE on `audit_logs` table
- [ ] Fields: `tenantId`, `actorId` (nullable for system events), `actorType` (USER | SYSTEM), `action` (enum), `entityType`, `entityId`, `before` (JSON snapshot), `after` (JSON snapshot), `createdAt`
- [ ] `GET /audit-log?entityType=&entityId=` — paginated; assigner/admin only
- [ ] CA/CS vertical requires longer retention — exact period TBD before first CA/CS firm onboarding

---

## File uploads (evidence)

- [ ] Files uploaded via pre-signed S3 URLs — do not pass through API server
- [ ] MIME type validated server-side (not just client-provided `Content-Type`)
- [ ] File extension whitelist enforced (jpg, png, heic, pdf, docx, xlsx — re-confirm W25)
- [ ] Max file size enforced (25 MB — re-confirm W25)
- [ ] Virus/malware scanning on upload (ClamAV or cloud-native scan — TBD)
- [ ] Signed URLs for evidence access (never expose raw S3 URLs)
- [ ] Evidence files scoped to tenant: S3 key includes `tenantId/...`

---

## API security

- [ ] Input validation on all user-provided fields (title, description, message)
- [ ] Character limits enforced server-side (broadcast notice limit TBD — W31)
- [ ] Rate limiting per user and per org on all endpoints
- [ ] Rate limiting stricter on auth endpoints (OTP request, verify)
- [ ] SQL injection: use parameterised queries only; no string interpolation in SQL
- [ ] CORS configured to allow only known frontend origins
- [ ] Security headers: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`

---

## Dependency security

- [ ] `npm audit --audit-level=high` runs in CI; blocks deploy on critical/high CVEs
- [ ] Dependabot or Renovate configured for automated dependency updates
- [ ] No dev dependencies in production Docker images

---

## Infrastructure security

- [ ] All services run in a private network; only API gateway exposed publicly
- [ ] DB not publicly accessible; API connects via private network
- [ ] S3 bucket not publicly readable; access only via signed URLs
- [ ] Least-privilege IAM roles for all services
- [ ] Secrets stored in secrets manager; not in environment variable files
- [ ] DB credentials rotated quarterly

---

## External integrations

> WhatsApp notifications are **out of scope for the MVP** (in-app only). **Corrected 2026-07-03:** email notifications are NOT fully out of scope — reminder/due-date types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`) send email now, via the same nodemailer/SMTP setup already used for OTP (PRD §10). All other notification types remain in-app only.

- [ ] API keys for all third-party services stored as secrets (not in code) — applies now (OTP provider, Voice AI, storage)
- [ ] Voice AI module endpoint called over HTTPS with documented contract; secrets stored in secrets manager
- [ ] (Post-MVP) WhatsApp Business API webhooks verified with HMAC signature validation
- [ ] **Email provider DKIM/SPF records configured** — applies now, not post-MVP, since reminder emails are live (same SMTP/FROM address as OTP — verify the sending domain's DKIM/SPF, not just OTP-specific)

---

## Compliance checklist

| Requirement | Status | Notes |
|---|---|---|
| DPDP Act (India, 2023) | Deferred to V2 — W62 | Voice = PII; consent + erasure required when in scope (no GPS on web) |
| ICAI guidelines (CA/CS vertical) | TBD — W71 (build Education first) | Client financial data handling |
| Audit log | ✅ In V1 (W63 resolved 2026-06-20) | All critical actions; CA/CS retention period TBD |
| Tenant data isolation | Row-level security on `tenant_id` | Enforced at DB layer + middleware |
