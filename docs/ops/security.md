# BOLO — Security Requirements & Controls

> Applies to all environments. Treat this as a checklist — check off items as they are implemented.
> **Last updated (bolo-backend-django):** 2026-08-23 — Platform Admin (superadmin) auth core built (see below). Previously 2026-08-22: re-synced through upstream's 2026-07-15 state (PlatformAdmin/superadmin auth, W35 resolved). Previously (upstream 2026-06-20): audit log added to V1 (W63 resolved). Web PRD v1.1. **Web platform: no device GPS in V1.** Controls deferred: voice encryption (W44), DPDP (W62).

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

### Platform Admin (superadmin) auth — W35 resolved *(core built here 2026-08-23 — OTP auth + create/list tenant + add/remove member. Deferred: Excel/JSON bulk-import, `AuditLog` wiring for these actions — see CLAUDE.md. One deliberate deviation: a single 7-day `admin_token` JWT with no refresh/rotation, simpler than the tenant-user access+refresh design below — PlatformAdmin is ops-only/low-volume, provisioned by a management command, not the main product's session model this project's refresh-token deviation was built for.)*

> A `PlatformAdmin` is a cross-tenant actor, entirely outside `Tenant`/RLS scoping — not a `User`, not a `TenantMembership` role. Registers new tenants and can add/remove users in any tenant. Full design in `docs/architecture/domain-model.md` ("PlatformAdmin" section) and `docs/api/api-spec.md` §22 (this project's numbering — §20 upstream).

- [x] Fully parallel auth flow to tenant users, same OTP/SMTP infra, deliberately kept separate everywhere it matters:
  - Separate table: `PlatformAdminOtpCode`, not `OtpCode` — `OtpCode.email` is globally unique with no discriminator, so sharing it risks a platform-admin OTP request silently invalidating a tenant user's in-flight OTP on the same address.
  - Separate cookie: `Set-Cookie: admin_token=<jwt>; HttpOnly; SameSite=Lax; Max-Age=604800` — never `token`, so a tenant session and a platform-admin session can coexist in the same browser without collision.
  - Separate JWT payload shape: `{ adminId, email, isPlatformAdmin: true, role }` — no `tenantId`/`roleLevel` at all, so a tenant token can never be mistaken for (or pass validation as) an admin token, and vice versa. (`role` is a bolo-backend-django addition — see next bullet.)
  - Separate middleware: `requirePlatformAdmin` (`platformAdminAuth.middleware.ts`) checks `isPlatformAdmin === true` on top of the standard JWT verify.
- [x] **RBAC on `PlatformAdmin` itself (bolo-backend-django addition, ROADMAP.md Phase 15a — no upstream equivalent):** a `PlatformAdmin.role` enum (`PlatformAdminRole`, `SUPER_ADMIN` only today), carried in the `admin_token` JWT and enforced on the four `/platform-admin/tenants*` management endpoints by a `HasPlatformAdminRole(["SUPER_ADMIN"])` permission-class factory — a structural twin of `HasOrgRole`, one auth tier up and on its own axis (`request.platform_admin_role`, never `request.role_level`). Authenticated-but-wrong-role → `403`. `/platform-admin/auth/logout` is not role-gated. `admin_token`s issued before the claim existed fall back to the DB column (no per-request extra query — the row is already loaded by the auth class). Second admin role = a one-line change per protected view; `SUPPORT_ADMIN`/`VIEWER` deliberately not built until the operator team needs the split.
- [x] **No self-registration** — there is no `POST` equivalent to create a `PlatformAdmin` via the API. The only way a row is created is `scripts/seedPlatformAdmin.ts`, run manually by ops. This is a deliberate gap, not an oversight: nobody should be able to grant themselves platform-admin access over the network.
- [x] `POST /onboard/register` (the old public, no-auth tenant-registration endpoint) is **removed** — tenant creation now requires `requirePlatformAdmin`, closing what had been "the only public write endpoint in the system."
- [x] Every platform-admin action (tenant creation, member add, member remove) writes an `AuditLog` row (`actorType: PLATFORM_ADMIN`, `actorId: null` — a `PlatformAdmin` isn't a `User` row, so its identity lives in `metadata` instead).
  - **bolo-backend-django (Phase 15b, 2026-08-29):** built. `apps/common/audit_middleware.py` grew a second actor-resolution path — a route with `actor: "platform_admin"` in `AUDIT_ROUTE_CONFIG` is attributed from the `admin_token` cookie (`decode_admin_cookie`), not the tenant-user `token` cookie: `actor_type = PLATFORM_ADMIN`, `actor_id = None`, `metadata = { platformAdminId, platformAdminEmail }`. `AuditLog.tenant` (required) is resolved from the target tenant — the `:tenantId` path kwarg for member add/remove, the response body for create-tenant. `TENANT_CREATED` / `MEMBER_ADDED` / `MEMBER_REMOVED` wired; `MEMBERS_BULK_IMPORTED` waits on Phase 15c. No service/view calls the audit layer — the generic-observer discipline holds.

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
| `requireAuth` | `auth.middleware.ts` | Every tenant-scoped route — validates JWT cookie, injects `req.user` |
| `requirePlatformAdmin` | `platformAdminAuth.middleware.ts` | Platform-admin routes only — validates separate `admin_token` cookie, injects `req.platformAdmin`; never accepts a tenant `token` |
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

- [x] Every critical action writes an `audit_log` record, captured automatically by the generic middleware for any route present in `auditRouteConfig.ts`: task CRUD, status transitions, reassign, broadcast lifecycle, **evidence upload/delete (`DOCUMENT_UPLOADED`/`DOCUMENT_DELETED`, wired 2026-07-18)**, **comment create/update/delete (`COMMENT_CREATED`/`COMMENT_UPDATED`/`COMMENT_DELETED`, wired 2026-07-25 — live-verified full success path)**, user login/logout (via `lastLoginAt`/`lastLogoutAt`, W99), **profile change (`USER_PROFILE_UPDATED`, wired 2026-07-18 — profile picture set/clear; `PATCH /me` name/language edits not yet wired)**, role change (platform-admin member add/remove, W101)
- [ ] **Do not add manual `dispatchAuditLog()`-style calls in services/controllers** — a new mutating route gets audited by adding one row to `auditRouteConfig.ts`, not by editing the handler. (Matches the standing rule in root `CLAUDE.md`.)
- [ ] Audit log is append-only — DB-level: no UPDATE or DELETE on `audit_logs` table; `AuditLogRepository` exposes `create()` only, no update/delete methods at all
- [ ] Fields: `tenantId`, `actorId` (nullable for system events **and platform-admin actions** — `PlatformAdmin` isn't a `User` row, added 2026-07-17), `actorType` (USER | SYSTEM | PLATFORM_ADMIN), `action` (enum), `entityType` (**UPPERCASE**, W95; includes `TENANT` since 2026-07-17, `DOCUMENT` since 2026-07-18, `COMMENT` since 2026-07-25), `entityId`, `before` (JSON snapshot), `after` (JSON snapshot), `createdAt`
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
- [x] Evidence **retrieval** proxied through the API (`GET /tasks/:id/evidence/:eid/file`) instead of a pre-signed URL — a pre-signed URL's signature is its entire authorization, so once it's in a JSON response it's a copyable credential valid for its full TTL regardless of session state. The API re-checks assigner/assignee on every request and streams the S3 object server-side (own IAM role, no presigning). Upload still uses pre-signed PUT URLs (client → S3 direct); only the read path changed.
- [x] Broadcast notice image **retrieval** proxied the same way (`GET /broadcast-notices/:id/image`) — this one was worse than evidence: `publishBroadcastNoticeService` used to mint a single pre-signed URL with a **25h TTL** and persist it on `imageUrl`, so the identical string was handed to every audience member's feed for the full 25h. Now `imageUrl` always stores the S3 key; the feed returns an app-relative path, and the endpoint re-checks sender-or-audience-membership on every request.
- [x] Voice recording playback (`GET /tasks/:id/voice-recording/audio`) proxied the same way, built 2026-08-23 (`VoiceRecordingService.get_audio_stream`) — previously returned `{ playbackUrl }`, a pre-signed URL with a 15-min TTL. Now streams the object server-side, re-checking assigner/assignee on every request.
- [x] Profile picture retrieval proxied the same way, built 2026-08-23 (`apps/users`) — `GET /me`, `PATCH /me`, `POST /upload/profile-picture-presign`, `PATCH`/`DELETE /me/profile-picture`, `GET /users/:userId/profile-picture[/file]`. `getPresignedGetUrl`-style URL generation has no callers left in `apps/users`. **Not built:** `GET /tenant/members` itself (and tenant self-service member CRUD generally) — a separate, larger gap; this slice only covers profile pictures.
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
