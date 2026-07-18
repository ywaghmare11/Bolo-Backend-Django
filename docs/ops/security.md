# BOLO — Security Requirements & Controls

> Applies to all environments. Treat this as a checklist — check off items as they are implemented.
> **Last updated:** 2026-06-20 — audit log added to V1 (W63 resolved). Web PRD v1.1. **Web platform: no device GPS in V1.** Controls deferred: voice encryption (W44), DPDP (W62).

---

## Authentication & sessions

> **Decisions locked (W1, W2 resolved):** Email OTP only — no SSO, no passwords.
> **bolo-backend-django deviation (2026-07-19):** the Django port replaces the original's single session-length cookie with a short-lived access token + rotating refresh token (below). This is a deliberate divergence from the original Node backend's contract, made for this port only — see `apps/auth/` (`models.RefreshToken`, `tokens.py`, `services.py::AuthService.refresh`). The original Node backend and `docs/api/api-spec.md` (which has no `/auth/refresh` endpoint) are unchanged by this note.

- [x] Auth method: **Email OTP → JWT access token in httpOnly cookie**, backed by a rotating refresh token in a second httpOnly cookie. No Authorization header.
- [x] **Cookie settings (2026-06-30, unchanged by the refresh-token addition):**
  - `SameSite=Lax` (not Strict) — Strict blocks XHR/fetch from SPAs; Lax allows same-site API calls while still blocking cross-site CSRF.
  - `Secure` flag controlled by `COOKIE_SECURE=true` env var (not `NODE_ENV`) — off on HTTP dev, on for HTTPS prod.
- [x] **Two cookies (bolo-backend-django, 2026-07-19):**
  - `token` — JWT access token, `Max-Age=900` (15 min). Payload: `{ userId, tenantId, roleLevel }`, `tenantId`/`roleLevel` never trusted from the request body. This is what every authenticated request is validated against.
  - `refresh_token` — opaque random token (not a JWT), SHA-256-hashed at rest in a new `refresh_tokens` table, `Max-Age=604800` (7 days). Used only to mint a new access+refresh pair via `POST /auth/refresh`; never accepted as a request-authentication credential itself.
- [x] **Refresh rotation:** every `POST /auth/refresh` call revokes the presented refresh token and issues a brand-new access+refresh pair (fresh 7-day window) — this is what "stays logged in until logout" now means in practice, since each rotation slides the window forward. **Reuse detection:** presenting an already-revoked (but not yet expired) refresh token revokes every refresh token for that user, forcing full re-login — this is the theft-detection signal a stolen-but-still-valid cookie would trip.
- [x] JWT access token now carries a real `exp` claim (15 min, `SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]`) — closes the original's open "JWT itself has no `expiresIn`" gap by construction, since the access token is short-lived by design rather than relying on an unenforced claim.
- [x] Logout revokes the current refresh token row (not just clearing cookies) — closes most of the original's "existing JWT remains valid until logout, no revocation list" V1 limitation: a stolen access token still only has a 15-minute window, and a stolen refresh token stops working the moment either side calls `/auth/refresh` or `/auth/logout`.
- [x] OTP: SHA-256 hashed before storage in `otp_codes` table. Plain OTP never stored or logged.
- [x] OTP delivery: AWS SES via `@aws-sdk/client-ses` (decided 2026-07-18 — was Gmail SMTP in dev, swap-to-SES-in-prod; now SES in every environment, IAM-role-only, same pattern as S3 — no SMS, no WhatsApp). Rate limit: 1 OTP per 60 s per email. Pre-send SMTP RCPT TO probe (a raw MX/port-25 handshake, independent of the SES send path) catches dead domains/mailboxes before sending — returns `422 EMAIL_UNDELIVERABLE`. SES send failure returns `502 EMAIL_DELIVERY_FAILED`. OTP row rolled back on any delivery failure so user can retry immediately.
- [x] Failed OTP attempts: lockout after **3 wrong attempts** (tracked in `otp_codes.attempts` + `otp_codes.lockedUntil`). Lockout window: 15 min. Response includes `data.attemptsRemaining` on each wrong attempt. 15-min server-side cleanup job (`src/jobs/otpCleanup.job.ts`) sweeps expired/abandoned OTP rows — replace with EventBridge/pg_cron in production.
- [x] On logout: both cookies cleared server-side (`Set-Cookie: token=; Max-Age=0` / `refresh_token=; Max-Age=0`); the current refresh token row is also revoked (bolo-backend-django). OTP row already deleted at verify time — nothing extra to clean up there.
- [ ] On account removal: `TenantMembership` row deleted; an already-issued access token remains valid until it expires (max 15 min, bolo-backend-django) or the original Node backend's cookie expiry (7 days, unchanged there). Revoking all refresh tokens for the removed user (`RefreshTokenRepository.revoke_all_for_user`) on this path is not yet wired up — worth doing before this matters in practice.

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
> **Write path resolved 2026-07-14 (W98/W99):** captured by a **generic Express middleware + static route-config table** (`src/middleware/auditLog.middleware.ts` + `src/config/auditRouteConfig.ts`), not by manual audit calls inside each service — see `system-design.md` §2.6. The one exception is login/logout, which route through `User.lastLoginAt`/`lastLogoutAt` field writes (W99) rather than a direct audit call.

- [x] Every critical action writes an `audit_log` record, captured automatically by the generic middleware for any route present in `auditRouteConfig.ts`: task CRUD, status transitions, reassign, broadcast lifecycle, **evidence upload/delete (`DOCUMENT_UPLOADED`/`DOCUMENT_DELETED`, wired 2026-07-18)**, user login/logout (via `lastLoginAt`/`lastLogoutAt`, W99), **profile change (`USER_PROFILE_UPDATED`, wired 2026-07-18 — profile picture set/clear; `PATCH /me` name/language edits not yet wired)**, role change (platform-admin member add/remove, W101)
- [ ] **Do not add manual `dispatchAuditLog()`-style calls in services/controllers** — a new mutating route gets audited by adding one row to `auditRouteConfig.ts`, not by editing the handler. (Matches the standing rule in root `CLAUDE.md`.)
- [ ] Audit log is append-only — DB-level: no UPDATE or DELETE on `audit_logs` table; `AuditLogRepository` exposes `create()` only, no update/delete methods at all
- [ ] Fields: `tenantId`, `actorId` (nullable for system events **and platform-admin actions** — `PlatformAdmin` isn't a `User` row, added 2026-07-17), `actorType` (USER | SYSTEM | PLATFORM_ADMIN), `action` (enum), `entityType` (**UPPERCASE**, W95; includes `TENANT` since 2026-07-17, `DOCUMENT` since 2026-07-18), `entityId`, `before` (JSON snapshot), `after` (JSON snapshot), `createdAt`
- [ ] `GET /audit-log?entityType=&entityId=` — paginated; assigner/admin only
- [ ] CA/CS vertical requires longer retention — exact period TBD before first CA/CS firm onboarding
- [ ] **Known gap (W97):** `STICKY_NOTE`/`PROJECT_LABEL` are listed as valid `entityType` filter values in `api-spec.md` §12 but have no `AuditAction` coverage or config rows yet — resolve before shipping filter validation

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

> WhatsApp notifications are **out of scope for the MVP** (in-app only). **Corrected 2026-07-03:** email notifications are NOT fully out of scope — reminder/due-date types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`) send email now, via the same AWS SES setup already used for OTP (PRD §10, transport decided 2026-07-18 — was nodemailer/SMTP). All other notification types remain in-app only.

- [ ] API keys for all third-party services stored as secrets (not in code) — applies now (OTP provider, Voice AI, storage)
- [ ] Voice AI module endpoint called over HTTPS with documented contract; secrets stored in secrets manager
- [ ] (Post-MVP) WhatsApp Business API webhooks verified with HMAC signature validation
- [ ] **Email provider DKIM/SPF records configured** — applies now, not post-MVP, since reminder emails are live (same SES sender identity/`SES_FROM_EMAIL` as OTP — verify the sending domain's DKIM/SPF, not just OTP-specific). Done for staging (`aibigo.in` domain-verified in SES 2026-07-17).

---

## Compliance checklist

| Requirement | Status | Notes |
|---|---|---|
| DPDP Act (India, 2023) | Deferred to V2 — W62 | Voice = PII; consent + erasure required when in scope (no GPS on web) |
| ICAI guidelines (CA/CS vertical) | TBD — W71 (build Education first) | Client financial data handling |
| Audit log | ✅ In V1 (W63 resolved 2026-06-20) | All critical actions; CA/CS retention period TBD |
| Tenant data isolation | Row-level security on `tenant_id` | Enforced at DB layer + middleware |
