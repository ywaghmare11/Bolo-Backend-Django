# BOLO — Domain Model

> **Last synced:** 2026-08-22 (bolo-backend-django) — re-synced from upstream through its 2026-08-18 state (`PlatformAdmin`/`Tenant.urlSlug`/`User.lastActiveAt`, all new to this project and not yet built here — see this project's `CLAUDE.md` for the punch list). Re-applied the Django-only findings below that upstream's own docs still don't carry (verified against upstream *source*, not doc prose, same discipline as the 2026-08-03 sync): `JargonWord` entity, `Task.evidenceRequired`, member reactivation, Evidence delete-access narrowing. Previously (2026-07-15 upstream): added `PlatformAdmin` + `PlatformAdminOtpCode` (superadmin, W35 resolved). Previously (2026-06-27): added `VoiceRecording` entity (W37 cascaded): stores raw SDK transcript, audio S3 key, language, duration, and AI confidence score per task.
> **Platform:** Web-based (V1). Mobile PRD is a future phase — architecture must remain mobile-compatible.
> **Backing schema:** `bolo-backend/prisma/schema.prisma` is kept in lockstep with this file.
> ⚠️ Genuinely open items: **W15** (task card/detail fields — pull from Figma), **W19** (org-role permission model — confirm before touching role-enforcement logic), **W64** (readiness indicators data). All others resolved — see `docs/product/open-questions-web-v1.md`.

---

## Entity Overview

```
PlatformAdmin                     ← superadmin; NOT part of any Tenant, outside RLS/tenant scoping
 └── (registers Tenants, adds/removes Users in any Tenant — see "PlatformAdmin" below)

Tenant                            ← a college, a CA/CS firm, etc.
 ├── Users[] (with TenantMembership — role + dept + reporting chain)
 ├── Departments[]
 ├── ProjectLabels[]               ← Label pool (each user sees only their own; dual FK on Task for main + personal)
 ├── Tasks[]
 ├── BroadcastNotices[]
 ├── Notifications[]
 └── AuditLogs[]

Task
 ├── Assigner (Delegator — User)
 ├── Assignee (User)
 ├── Subtasks[]                    ← self-referential; parentTaskId IS NOT NULL
 ├── Evidence[]
 ├── Comments[]
 ├── TaskPersonalLabels[]          ← Personal Labels (Tier 2 — private per user)
 └── VoiceRecording?               ← optional; only present if task was created via voice

User (personal)
 ├── StickyNotes[]                 ← a StickyNote with dueAt set IS the reminder (W30 resolved)
 ├── OtpCodes[]                    ← transient; deleted after use
 └── (assigned/delegated Tasks, personalLabels, broadcastAcknowledgements, notifications)

BroadcastNotice → sent to (Dept + RoleLevel) group
 └── BroadcastAcknowledgements[]  ← one row per user who acknowledged
```

---

## Entities & Fields

### PlatformAdmin (superadmin — W35 resolved)

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| name | string | ✅ | |
| email | string | ✅ | Login identifier via Email OTP; `@unique`. No self-registration — rows are provisioned only via `scripts/seedPlatformAdmin.ts` (ops-only). |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> **Not a `User` row and not a `TenantMembership` role** — `User.tenantId` is required/non-nullable (single tenant per user, W56), so a cross-tenant actor cannot be modeled as a `User`. A `PlatformAdmin` has no `tenantId` anywhere and sits entirely outside Row-Level Security.
> Capabilities: create a `Tenant` + its first `TOP` user (`POST /platform-admin/tenants` — this replaced the old undocumented public `POST /onboard/register`, which is now removed and gated behind platform-admin auth), list all tenants, add/remove a `User` in **any** tenant (`POST` / `DELETE /platform-admin/tenants/:tenantId/members[/:userId]`), and bulk Excel/JSON import members into **any** tenant (`POST /platform-admin/tenants/:tenantId/members/import` — same underlying import logic as the tenant self-service path). Every such action writes an `AuditLog` row with `actorType = PLATFORM_ADMIN`.
> Auth: separate Email+OTP flow (own `PlatformAdminOtpCode` table, own `admin_token` cookie, own JWT payload shape with no `tenantId`/`roleLevel` — see `docs/ops/security.md`). Reuses the same OTP/email infra as tenant-user login, just fully parallel so the two session types never collide.

---

### PlatformAdminOtpCode

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| email | string | ✅ | Lookup key; `@unique` — one active OTP per email |
| hashedCode | string | ✅ | SHA-256 hash — never store plain OTP |
| expiresAt | timestamp | ✅ | `createdAt + 10 min` |
| attempts | integer | ✅ | Wrong attempt counter; lock after 3; default 0 |
| lockedUntil | timestamp | — | Set to `now + 15 min` after 3 wrong attempts; null = not locked |
| createdAt | timestamp | ✅ | |

> Deliberately a separate table from `OtpCode` — `OtpCode.email` is globally unique with no discriminator column, so a platform-admin OTP request on an address that also happens to be a tenant `User.email` would otherwise silently collide with/invalidate that user's in-flight OTP.

---

### Tenant

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| name | string | ✅ | e.g., "ABC College", "Sharma & Associates" |
| urlSlug | string | ✅ | Unique. Client-chosen at tenant creation (`POST /platform-admin/tenants`), URL-safe (`^[a-z0-9]+(-[a-z0-9]+)*$`, 2-40 chars) — drives the post-login URL path `/{urlSlug}/{firstName}` (system-design.md §4.3). **Cosmetic only** — never used for tenant scoping/authorization, which stays keyed on `id` from the JWT everywhere else. Added 2026-08-09. |
| vertical | enum | ✅ | `EDUCATION` \| `CA_CS` |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

Tenant isolation: **Row-Level Security on `tenant_id`** — every query scoped to the current tenant. JWT carries `tenantId`; API middleware injects it. Never trust `tenantId` from the request body. **`urlSlug` is not part of this boundary** — it's a display/routing convenience, validated for uniqueness but never checked for authorization.

---

### User

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant; single tenant per user (W56) |
| name | string | ✅ | |
| email | string | ✅ | Primary identifier; login via Email OTP; `@unique` |
| phone | string | — | Collected during Excel onboarding; future notification channels |
| profilePicUrl | string | — | S3 object key (not a URL) — served via `GET /users/:userId/profile-picture/file`, which streams the object server-side instead of minting a pre-signed URL (changed 2026-07-25). Optional, add/update/delete via `POST /upload/profile-picture-presign` → `PATCH /me/profile-picture` → `DELETE /me/profile-picture` |
| preferredLang | enum | ✅ | `EN` \| `HI`; default `EN` |
| lastLoginAt | timestamp | — | Added 2026-07-14 (W99) — set on successful OTP verify. Session-tracking field that doubles as the DB mutation the generic `AuditLog` middleware keys `USER_LOGIN` off of — see §2.6 in `system-design.md`. **No longer used to drive AI Nudge fast-track (see `lastActiveAt` below, 2026-08-18)** — it still exists purely for its original login-event/audit purpose. |
| lastLogoutAt | timestamp | — | Added 2026-07-14 (W99) — set on logout. Same purpose as `lastLoginAt`, and gives `logout` its first real service/repository layer (was controller-only, no DB call, before this). |
| lastActiveAt | timestamp | — | Added 2026-08-18. Touched (throttled to once per 10 min per user) on **any authenticated request** via `requireAuth` — not tied to login/logout events. Added because `lastLoginAt` only updates on real OTP login, but the PWA keeps the JWT cookie (and session) alive for up to 7 days — a user who logs in once and keeps using the app never triggers another "login," so `lastLoginAt`-based logic goes stale after day one. This is what AI Nudge's first-eligible-nudge-of-the-day fast-track reads (row 8c/8d below) — not `lastLoginAt`. |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> No password field — Email OTP only (PRD §11).

---

### Department

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| name | string | ✅ | e.g., "CSE", "Finance" |
| headUserId | UUID | — | FK → User; `@unique` — one user heads at most one dept; null until assigned |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

---

### TenantMembership

| Field | Type | Required | Notes |
|---|---|---|---|
| userId | UUID | ✅ | PK (composite with tenantId); `@unique` — single tenant per user |
| tenantId | UUID | ✅ | PK (composite with userId); FK → Tenant |
| departmentId | UUID | — | FK → Department |
| roleLevel | enum | ✅ | `TOP` \| `MID` \| `EXECUTOR` |
| roleLabel | string | — | "Dean" \| "HoD" \| "Faculty" etc. — display only; from Excel onboarding |
| reportsToId | UUID | — | FK → User; null = root of the org tree; builds the org chart via `reportsToId` chain |

> **Member reactivation (bolo-backend-django finding, still absent from upstream's own docs):** `removeMember` only ever deletes this `TenantMembership` row — the `User` row itself survives. A `reactivateMember` flow (tenant-scoped `POST /tenant/members/:userId/reactivate`, `TOP`-only, plus a cross-tenant `POST /platform-admin/tenants/:tenantId/members/:userId/reactivate` variant once PlatformAdmin exists) re-creates a fresh membership for that same still-existing user, taking the same field set as this table. Rejects if the user already has an active membership (`409` "This member is already active"); `isHead=true` only valid when `roleLevel = MID` and a department is given. `AuditAction.MEMBER_REACTIVATED` fires on this path.
| canBroadcast | boolean | ✅ | Binary broadcast permission flag; default false (W22 resolved) |
| joinedAt | timestamp | ✅ | |

> **Task-level roles (Delegator / Assignee) are not stored here** — derived from `assignerId` / `assigneeId` on the Task.
> **Org chart tree** is built from `reportsToId` — the designation (`roleLabel`) is display-only and does not control the tree shape.

---

### OtpCode

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| email | string | ✅ | Lookup key; `@unique` — one active OTP per email |
| hashedCode | string | ✅ | SHA-256 hash — never store plain OTP |
| expiresAt | timestamp | ✅ | `createdAt + 10 min` |
| attempts | integer | ✅ | Wrong attempt counter; lock after 3; default 0 |
| lockedUntil | timestamp | — | Set to `now + 15 min` after 3 wrong attempts; null = not locked |
| createdAt | timestamp | ✅ | |

> Transient table — row deleted immediately after successful verify. A 15-min server-side cleanup job (`src/jobs/otpCleanup.job.ts`) sweeps expired, unlocked rows for rows that were requested but never verified. No FK to User — lookup is by email string.

---

### ProjectLabel *(Main Label — Tier 1)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| name | string | ✅ | `@@unique([createdBy, name])` — no duplicate label names per user |
| colorCode | string | ✅ | Hex color; default `#6B7280` — added 2026-07-02 |
| description | string | — | Optional label description — added 2026-07-02 |
| createdBy | UUID | ✅ | FK → User |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> Serves dual purpose via two FKs on Task: `mainLabelId` (assigner sets; visible to all who can see the task) and `assigneeLabelId` (assignee sets; private — API never returns this to non-assignees). Each user sees only labels they created (`createdBy = req.userId`). `onDelete: Restrict` — cannot delete a label while it is applied to any task.

---

### JargonWord *(bolo-backend-django finding, added 2026-07-31 upstream, still absent from upstream's own docs)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| vertical | enum | ✅ | `EDUCATION` \| `CA_CS` — **not tenant-scoped**; one shared dictionary per vertical, not per tenant |
| term | string | ✅ | Max 100 chars. `@@unique([vertical, term])` |
| variants | string[] | ✅ | Alternate spellings/mis-hearings that should resolve to the same term; default `[]` |
| isActive | boolean | ✅ | Default `true` |
| createdBy | UUID | ✅ | FK → User |
| createdAt / updatedAt | timestamp | ✅ | |

> Grounds the voice-recognition and Global Search query-understanding layers against vertical-specific jargon (e.g. "NAAC", "MGT-7") that a general-purpose model wouldn't otherwise get right. Managed via CRUD + Excel bulk-import/template endpoints, gated by an email allow-list (`JARGON_ADMIN_EMAILS`) — **not** `PlatformAdmin` and **not** `OrgRoleLevel`, a distinct admin concept. Deliberately **not audit-logged** (no route-config row upstream, by design). See `docs/api/api-spec.md` for the full CRUD + bulk-import contract.

---

### Task

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | From JWT, never from body |
| title | string | ✅ | **Immutable after creation** — service rejects PATCH on title |
| assignerId | UUID | ✅ | FK → User (the Delegator) |
| assigneeId | UUID | ✅ | FK → User |
| status | enum | ✅ | `DRAFT` \| `OPEN` \| `IN_PROGRESS` \| `OVERDUE` \| `DONE_A` \| `DONE_D` \| `CANCELLED`; default `DRAFT` |
| acceptanceStatus | enum | ✅ | `PENDING` \| `ACCEPTED`; default `PENDING` |
| priority | enum | — | `P1` \| `P2` \| `P3` \| `P4`; **default `P3`** (PRD v1.1) |
| dueDate | timestamp | — | Optional while Draft. **Required at Draft → Open transition** (W-C3 resolved) |
| description | text | — | |
| mainLabelId | UUID | — | FK → ProjectLabel (Main Label — assigner sets; visible to all) |
| assigneeLabelId | UUID | — | FK → ProjectLabel (Assignee personal label — assignee sets; private; cleared on reassignment) |
| isArchived | boolean | ✅ | `true` when assigner marks DONE_D on a main task; default `false` |
| acceptedAt | timestamp | — | When assignee accepted |
| parentTaskId | UUID | — | FK → Task (self-reference). When set, this Task **is** a subtask |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |
| evidenceRequired | boolean | ✅ | **bolo-backend-django sync, added 2026-07-30 upstream, still absent from upstream's own docs.** Assigner-editable (create + edit, same rule as `priority`/`mainLabelId`); default `false`. When `true`, blocks the assignee's DoneA transition until at least one `Evidence` row exists for the task (`400 EVIDENCE_REQUIRED` otherwise). |

**Ownership rules:**
- `title` — immutable after creation
- `dueDate`, `assigneeId`, `priority`, `mainLabelId`, `description` — editable by assigner only
- `assigneeLabelId` — editable by assignee only; service clears this field when `assigneeId` changes
- `status` — assigner controls (except `DONE_A` which assignee sets)
- Subtask creation — assignee only
- Delete — assigner only
- Reassign — blocked once any subtask exists

**State machine:** `DRAFT → OPEN → IN_PROGRESS → DONE_A → DONE_D`; `OVERDUE` auto-set by scheduler, auto-reverted to `OPEN`/`IN_PROGRESS` by a due-date edit (W100); `CANCELLED` by assigner any time before `DONE_D`.

**Status propagation rules (service layer):**
- Parent `CANCELLED` → all non-`DONE_D` subtasks cascade to `CANCELLED`
- Parent cannot reach `DONE_D` until every subtask is `DONE_D` **or** `CANCELLED` (gate, not auto-propagation) — a cancelled subtask counts as resolved since it can never reach `DONE_D` (W99, resolved 2026-07-22)
- Subtask `OVERDUE` / `CANCELLED` does NOT affect parent status
- `OVERDUE → OPEN`/`IN_PROGRESS`: editing `dueDate` on an `OVERDUE` task to today-or-later reverts status — `IN_PROGRESS` if `acceptanceStatus = ACCEPTED`, else `OPEN` (W100, resolved 2026-07-22). `updateTaskService` is the only place that reverts `OVERDUE`; `runOverdue` (`dueDateSweep.service.ts`) is the only place that sets it.

---

### Subtask *(modeled as a self-referential Task)*

A subtask is a **`Task` row with `parentTaskId` set** — shares every field, relation, and rule. Distinctions:

- **Subtask assigner = parent task's assignee** (auto-set on create)
- Created **only by the assignee of the parent task**
- **No archiving** — `isArchived` only set when `parentTaskId IS NULL`
- Subtask `dueDate` must be earlier than parent's `dueDate` — service validates
- Cannot be assigned back to the parent task's assigner
- Nesting is unbounded — self-reference handles arbitrary depth

---

### Evidence

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| taskId | UUID | ✅ | FK → Task (covers subtasks — a subtask IS a Task) |
| uploaderId | UUID | ✅ | FK → User |
| fileUrl | string | ✅ | S3 object key. **bolo-backend-django, built 2026-08-03:** served via a backend-streamed endpoint (`GET /tasks/:id/evidence/:eid/file`), not a pre-signed URL — the app returns an app-relative path and the backend re-checks assigner-or-assignee access on every request. Same pattern later confirmed upstream (2026-07-25) for broadcast images, voice recording, and profile pictures too — see `api-spec.md`. |
| fileName | string | ✅ | Original filename for UI display |
| fileSize | integer | ✅ | Bytes — for per-file limit enforcement when confirmed (PRD v1.1 §3.5) |
| fileType | enum | ✅ | `IMAGE` \| `PDF` \| `DOC` \| `OTHER` |
| caption | string | — | |
| createdAt | timestamp | ✅ | |

> No GPS / geotag fields — web platform, no device location API in V1.
> No task-level aggregate cap (PRD v1.1 removed it). Per-file size limit TBD.
> Files never pass through the backend — client uploads directly to S3 via pre-signed PUT URL.
> `fileUrl` stores the **S3 object key** (not a URL). Raw S3 keys are never returned in API responses.
> Access: assigner and assignee only — enforced in the service layer via task ownership check. **Delete access narrowed (bolo-backend-django, built 2026-08-03):** `DELETE /tasks/:id/evidence/:eid` is **uploader-only** (not uploader-or-assigner) — matches `Comment`'s existing author-only delete rule. Real behavior change, not a refactor; upstream's own docs still say uploader-or-assigner.
> Upload safety: files land in `bolo-evidence/unconfirmed/` first; `POST /tasks/:id/evidence` moves to confirmed path + creates DB row. S3 lifecycle deletes `unconfirmed/` objects after 24h. `.xls` (legacy binary Excel) is accepted alongside `.xlsx`.

---

### VoiceRecording

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| taskId | UUID | ✅ | FK → Task; `@unique` — one recording per task/subtask |
| audioUrl | string | — | S3 object key; null if user did not opt to store audio (W37 — opt-in) |
| rawTranscript | string | ✅ | Verbatim multilingual text returned by the Voice AI SDK — unfiltered, not LLM-processed |
| language | string | — | Detected language code e.g. `"hi"`, `"en"`, `"hi-en"` (Hinglish) |
| durationSecs | integer | — | Audio duration in seconds |
| confidenceScore | float | — | Overall extraction confidence 0.0–1.0 from SDK; used for analytics |
| createdAt | timestamp | ✅ | |

> Created immediately after task creation if the task was voice-initiated.
> `audioUrl` stores the S3 object key only — a pre-signed GET URL is generated on demand (`GET /tasks/:id/voice-recording/audio`) and never stored.
> Access: assigner and assignee only (W38) — enforced via task ownership check in the service layer.
> Retention: 6 months to 1 year (W41) — EventBridge cron job nulls `audioUrl` + deletes S3 object at cutoff; row itself kept for transcript.
> Encryption at rest: implement if easily achievable; otherwise defer to V2 (W44).
> `onDelete: Cascade` — deleted with the parent task.

---

### Comment

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| taskId | UUID | ✅ | FK → Task (covers subtasks) |
| authorId | UUID | ✅ | FK → User (assigner or assignee) |
| text | text | ✅ | |
| isEdited | boolean | ✅ | `true` when comment is edited; default `false` |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> Full CRUD — author can edit and delete their own comments. No threaded comments in V1.

---

### StickyNote

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| userId | UUID | ✅ | Owner — private to creator always |
| text | text | ✅ | |
| colorCode | string | ✅ | 6-digit hex (`#RRGGBB`); default `#FEF3C7` (design-system.md `color-sticky-bg`) if not provided at create |
| dueAt | timestamp | — | When set → acts as reminder; shown red when imminent/past |
| isPinned | boolean | ✅ | Drives Pinned / Unpinned sub-tab; default `false` |
| promotedToTaskId | UUID | — | FK → Task; `@unique` — one note → one task |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> **W30 resolved** — no separate Reminder entity. A `StickyNote` with `dueAt` set IS the reminder. EventBridge fires `REMINDER_FIRED` notification for notes where `dueAt <= NOW()`.

> **Retention (added 2026-07-23):** a `StickyNote` with `dueAt` set is hard-deleted once `dueAt + 3 days <= NOW()` — enforced by a daily EventBridge + Lambda sweep (`stickyNoteRetentionSweep.job.ts`), sharing the scheduler infra already used for `aiNudgeSweep.job.ts` (see `system-design.md` §Scheduler). Notes with `dueAt` null are unaffected. Hard delete, no soft-delete/archive step — no undo anywhere in the system (W67).

---

### BroadcastNotice

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| senderId | UUID | ✅ | FK → User |
| messageJson | JSON | ✅ | TipTap AST — restores editor state when re-opening a draft |
| messageHtml | string | ✅ | Sanitized HTML — rendered in the broadcast feed |
| status | enum | ✅ | `DRAFT` \| `PUBLISHED`; default `DRAFT` |
| audienceDeptIds | UUID[] | — | Via `BroadcastNoticeAudienceDept` join table (broadcastId, deptId — composite PK); can target multiple departments (e.g. Computer Science + Civil Engineering only); empty = all departments. Was a single nullable `audienceDeptId` FK before 2026-07-17. |
| audienceRoleLevels | enum[] | — | `TOP` \| `MID` \| `EXECUTOR`, via `BroadcastNoticeAudienceRoleLevel` join table; empty = all role levels. Was a single nullable `audienceRoleLevel` FK before 2026-07-30. |
| requiresAcknowledgement | boolean | ✅ | Default `false` |
| imageUrl | string | — | Single image only. Always stores the S3 object key — publish no longer overwrites it with a pre-signed URL (changed 2026-07-25). The feed (`GET /broadcast-notices`) returns an app-relative path to `GET /broadcast-notices/:id/image` instead, which streams the object server-side and re-checks sender-or-audience-membership on every request. |
| expiresAt | timestamp | — | Set to `createdAt + 1 day` on publish — not configurable (W54 resolved) |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> **Audience scope is mandatory at publish** — service rejects publish if both `audienceDeptIds` and `audienceRoleLevels` are empty (PRD v1.1). Stop-gap relaxation pending W110 (see `open-questions-web-v1.md` §23) makes "both empty" a valid explicit "Entire Institution" audience rather than a hard reject.
> `messageJson` is stored for the editor; `messageHtml` is pre-rendered on publish for fast feed rendering. Server sanitizes HTML with `sanitize-html` before storing.

---

### BroadcastAcknowledgement

| Field | Type | Required | Notes |
|---|---|---|---|
| broadcastId | UUID | ✅ | PK (composite with userId); FK → BroadcastNotice, **`ON DELETE CASCADE`** (corrected 2026-07-13 — was RESTRICT, which 500'd `DELETE /broadcast-notices/:id` for any broadcast with acknowledgements; found via manual API testing) |
| userId | UUID | ✅ | PK (composite with broadcastId); FK → User |
| acknowledgedAt | timestamp | ✅ | |

> Composite PK `(broadcastId, userId)` prevents double-counting. Sender sees `COUNT(*)` only — no per-person breakdown (PRD v1.1).

---

### Notification

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| recipientId | UUID | ✅ | FK → User |
| type | enum | ✅ | See Notification Events below |
| entityType | string | ✅ | `"task"` \| `"broadcast"` \| `"sticky_note"` — polymorphic reference, **always lowercase**. (`"user"` batched-Periodic value is retired — Periodic itself is gone, see AI Nudge redesign below.) |
| entityId | string | ✅ | ID of the related entity |
| message | string | ✅ | Pre-rendered text e.g. "Mehta assigned you a task" |
| actorName | string | — | Added 2026-07-05 — person who triggered the event, for the general Notification panel to bold. Optional; populated only where the creating call site has it on hand. |
| entityTitle | string | — | Added 2026-07-05 — e.g. task title, shown below `message` in the general Notification panel. |
| entityContext | string | — | Added 2026-07-05 — e.g. project label name, shown below `entityTitle`. |
| isRead | boolean | ✅ | Default `false` |
| readAt | timestamp | — | Set when user reads it |
| createdAt | timestamp | ✅ | |

> In-app only for V1. `entityType + entityId` is a polymorphic reference — avoids 10+ nullable FK columns per entity type.

---

### AuditLog

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant |
| actorId | UUID | — | FK → User; null for system-triggered actions and `PLATFORM_ADMIN` actions (a `PlatformAdmin` isn't a `User` row, so its identity is only in `metadata`, not `actorId`) |
| actorId | UUID | — | FK → User; null for system-triggered actions **and for `PLATFORM_ADMIN` actions** (added 2026-07-17) — `PlatformAdmin` is a separate model, not a `User` row, so there's no valid FK target |
| actorType | enum | ✅ | `USER` \| `SYSTEM` \| `PLATFORM_ADMIN`; default `USER` |
| action | enum | ✅ | See AuditAction enum below |
| entityType | string | ✅ | `"TASK"` \| `"BROADCAST"` \| `"USER"` \| `"DOCUMENT"` \| `"TENANT"` (added 2026-07-17, platform-admin actions) — **UPPERCASE**, matching `api-spec.md` §12. Deliberately diverges from `Notification.entityType` (lowercase) — AuditLog is a distinct polymorphic-reference convention, not required to match Notification's. |
| entityId | string | ✅ | ID of the affected entity |
| before | JSON | — | State before the change — null for creates |
| after | JSON | — | State after the change — null for deletes |
| metadata | JSON | — | IP address, user agent, session context |
| createdAt | timestamp | ✅ | |

> **Immutable** — never updated or deleted. CA/CS vertical requires longer retention for compliance (exact period TBD before first CA/CS onboarding). W63 resolved — audit log is in scope for V1.
> **W95 resolved (2026-07-14):** `entityType` casing contradiction between this file (was lowercase) and `api-spec.md` §12 (UPPERCASE) — UPPERCASE is canonical for `AuditLog`. Writers must uppercase the entity name at the call site.
> **W98 resolved (2026-07-14):** rows are written by a **generic Express middleware + static route-config table**, not by explicit `dispatchAuditLog()` calls scattered across services (deliberately the opposite of the `Notification` dispatcher pattern in §2.5 of `system-design.md`) — see `system-design.md` §2.6 for the full design and the one documented exception (login/logout, W99).

**AuditAction enum covers:**
- Task & Subtask: `TASK_CREATED`, `TASK_UPDATED`, `TASK_DELETED`, `TASK_ASSIGNED`, `TASK_REASSIGNED`, `TASK_STATUS_CHANGED`, `TASK_PRIORITY_CHANGED`, `TASK_DUE_DATE_CHANGED`, `TASK_LABEL_CHANGED`, `TASK_ARCHIVED`, `SUBTASK_CREATED`, `SUBTASK_UPDATED`, `SUBTASK_DELETED`
- Comments: `COMMENT_CREATED`, `COMMENT_UPDATED`, `COMMENT_DELETED` (added + wired 2026-07-25, `entityType: 'COMMENT'` — new `AuditAction` values, unlike `DOCUMENT`/`TENANT` which arrived pre-added by other PRs)
- Documents: `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED` (wired 2026-07-18 — Evidence upload/delete, PR #36, `entityType: 'DOCUMENT'`); `DOCUMENT_DOWNLOADED`, `DOCUMENT_ACCESSED` unused — no config rows, would require auditing `GET` requests, which the middleware doesn't support (only POST/PATCH/DELETE)
- Broadcast: `BROADCAST_CREATED`, `BROADCAST_UPDATED`, `BROADCAST_DELETED`, `BROADCAST_PUBLISHED`, `BROADCAST_ACKNOWLEDGED`, `BROADCAST_VIEWED`
- Audience Scope: `AUDIENCE_SCOPE_CREATED`, `AUDIENCE_SCOPE_MODIFIED`, `AUDIENCE_SCOPE_ASSIGNMENT_CHANGED`
- User Activity: `USER_LOGIN`, `USER_LOGOUT`, `USER_PROFILE_UPDATED`, `USER_ROLE_CHANGED`, `USER_PERMISSION_CHANGED`
- Platform Admin (cross-tenant, `actorType = PLATFORM_ADMIN`): `TENANT_CREATED`, `MEMBER_ADDED`, `MEMBER_REMOVED`, `MEMBERS_BULK_IMPORTED`
- User Activity: `USER_LOGIN`, `USER_LOGOUT`, `USER_PROFILE_UPDATED` (wired 2026-07-18 for `PATCH`/`DELETE /me/profile-picture`; `PATCH /me` name/language edits not yet wired), `USER_ROLE_CHANGED`, `USER_PERMISSION_CHANGED`
- Platform Admin (added 2026-07-17, cross-tenant/superadmin — `system-design.md` §2.6): `TENANT_CREATED`, `MEMBER_ADDED`, `MEMBER_REMOVED`, `MEMBERS_BULK_IMPORTED`

---

## Notification Events

| # | Type | Event | Notified |
|---|---|---|---|
| 1 | `TASK_ASSIGNED` | Task Assigned | Assignee |
| 1a | `TASK_ACCEPTED` | Task Accepted | Assigner |
| 2 | `TASK_REASSIGNED` | Task Reassigned | New assignee + previous assignee |
| 3 | `TASK_EDITED` | Task Edited by Assigner | Assignee |
| 3a | `TASK_EDITED` | Task Edited by Assignee | Assigner |
| 3b | `SUBTASK_CREATED` | Subtask Created | Sub-assignee |
| 3c | `SUBTASK_EDITED` | Subtask Edited by Subtask Assigner | Sub-task assignee |
| 3d | `SUBTASK_EDITED` | Subtask Edited by Subtask Assignee | Sub-task assigner |
| 4 | `TASK_COMMENTED` | Task Commented | The other party (no self-notification) |
| 5 | `TASK_DONE_A` | Task Marked DoneA | Assigner |
| 6 | `TASK_DONE_D` | Task Marked DoneD | Assignee |
| 7 | `TASK_CANCELLED` | Task Cancelled | Assignee + sub-assignee (only if Open/In Progress/Overdue) |
| 8 | `TASK_DUE_TODAY` / `TASK_DUE_TOMORROW` / `TASK_OVERDUE` | Due date proximity — **one-shot**, fires once per threshold crossing | Assignee + Assigner |
| — | (`TASK_DUE_TOMORROW` window — resolved 2026-07-04, W82) | A task due tomorrow does **not** get row 8d's recurring `AI_NUDGE_DUE_PROXIMITY` treatment — no third skip-cap bucket needed. It's covered by the ordinary Periodic/Follow-up nudges like any other open task. Only once it actually becomes Due Today (or Overdue) does it "land in" row 8d's recurring/skip-cap/escalation mechanic. Only 2 cap buckets exist: due-today, overdue. | — |
| 8b | ~~`AI_NUDGE_PERIODIC`~~ | **Removed 2026-07-06.** Was a batched "you have N open tasks" summary. Once Follow-up gained per-task action buttons (below) and lost its skip-cap, there was no remaining structural difference between the two — Follow-up's named conditions already comprehensively cover the space Periodic vaguely summarized. Merged away entirely; do not reintroduce. | — |
| 8c | `AI_NUDGE_FOLLOWUP` | AI Nudge — Follow-up. **Scope narrowed 2026-07-13 (client-directed):** down to 2 conditions, both assignee-only — (b) accepted, no progress since → assignee, `Add Comment`; (c) comment posted and the **assignee** owes the reply (assigner posted last) → assignee, `Add Comment`. Conditions (a) not-yet-accepted/`Accept Task`, (d) `DONE_A`-awaiting-`DONE_D`/`Mark Complete`, (e) subtasks-done/`Mark Complete` are **removed entirely, not just their buttons** — those are irreversible actions the user should take deliberately from the task itself, not one-click from a nudge, and they're already covered by the general Notification panel. The **assigner is out of scope for Follow-up entirely** — if the assignee posted the last comment and is waiting on the assigner, no nudge fires (there's no one left in scope to notify). No Subtask/Broadcast/StickyNote — Task only, and Subtask is no longer distinguished from Task (`entityType` is always `"task"`; a subtask is just another task from the assignee's point of view). Skip counter tracked for visibility only, no cap, no escalation. Fires every 6h, no office-hours gate. **First-login-of-the-day fast-track (added 2026-07-16, corrected 2026-08-18):** a recipient's first eligible Follow-up nudge of the day bypasses the 6h gate and fires on the next 15-min sweep tick instead of waiting — otherwise the day's first nudge can land hours late purely by interval-timing coincidence. Eligibility is computed once per sweep tick (`NudgeRepository.findFirstNudgeFastTrackRecipients`) from `User.lastActiveAt >= startOfToday` minus anyone already nudged today — **reads `lastActiveAt`, not `lastLoginAt`** (corrected 2026-08-18; see `lastActiveAt` in the User table above for why). | Assignee only |
| 8d | `AI_NUDGE_DUE_PROXIMITY` | AI Nudge — Due Date Proximity. **Scope narrowed 2026-07-13: Task only** (Subtask/StickyNote/Broadcast all dropped). Fires every 3h, no office-hours gate. Already-accepted only (`IN_PROGRESS`/`OVERDUE` or due-today) — an unaccepted-but-overdue task gets no nudge at all now (Follow-up's "not accepted" condition was removed, not replaced). Actions: `Add Comment` + `Open Task` + `Skip`. **Skip is a user-clicked button**, never auto-incremented by the sweep. **Add Comment resolves the nudge for this cycle** (fixed 2026-07-13 — was previously a no-op for Due-Proximity specifically, since its eligibility check never looked at comments; the fix re-validates against comments posted after the notification fired, whether via the nudge panel or the task directly). Cap: 3 for due-today, 1 for overdue. **No blocking behavior (removed 2026-07-13):** Skip is **never** disabled or hidden at cap, and the panel is never forced closed/blocked — at cap the card just shows a plain warning ("skip this and it'll be escalated to your assigner"); the user can keep skipping past it if they choose. **Escalation is still real**, independent of the UI: sweep-side check each tick — if `skipCount >= cap`, not yet escalated, and the task hasn't reached at least `DONE_A` → one-time in-app+email to the **assigner**, guarded by `NudgeSkipCounter.escalatedAt` so it never repeats. Reaching `DONE_A` drops the task out of the sweep query entirely (no longer `OPEN`/`IN_PROGRESS`/`OVERDUE`) — no escalation. **The assignee is only ever held to `DONE_A`, never `DONE_D`.** **Same first-login-of-the-day fast-track as row 8c** applies here too (shared `fastTrackRecipients` set, computed once per sweep tick and passed to both) — bypasses the 3h gate for a recipient's first eligible Due-Proximity nudge of the day. | Assignee (routine) + assigner (one-time escalation only) |
| — | **Feed composition (added 2026-07-13):** `GET /nudges` returns **max 5 items total**, not everything eligible. Due-Proximity fills first (ordered by `Task.priority`, P1 highest), up to 5. If fewer than 5 Due-Proximity items exist, Follow-up fills the remaining slots — also ordered by `Task.priority` first, then by `NudgeSkipCounter.lastShownAt` ascending (oldest-shown-first, nulls/never-shown first) as the rotation tiebreaker within the same priority. `lastShownAt` is updated on every Follow-up item that actually appears in a response — this is what makes the rotation self-correcting: as the user resolves what's currently shown, the next-oldest-unshown candidate surfaces on the next fetch, rather than the same few items camping the feed forever. | — |
| — | **First-login-of-the-day fast-track (added 2026-07-16):** the 3h/6h interval gate has no notion of whether the user was ever online — a user with short, irregular sessions could go a full day without a session ever overlapping the exact moment the interval elapsed. Fix: users who logged in today (`User.lastLoginAt`) but haven't received any AI Nudge notification yet today bypass the interval gate once, on the very next sweep tick — everything currently eligible for them fires at once. Self-limiting: the moment it fires, their own new notification is "today," so the next sweep computation naturally excludes them and normal gating resumes for the rest of the day. No new schema — computed from existing `lastLoginAt`/`Notification.createdAt`. | — |
| 10 | `SUBTASK_DONE_A` | Subtask Marked DoneA | Sub-task assigner |
| 11 | `SUBTASK_DONE_D` | Subtask Marked DoneD | Sub-task assignee |
| 12 | `BROADCAST_POSTED` | Broadcast Posted | All tenant members in audience scope |
| 13 | `REMINDER_FIRED` | Reminder Fired (StickyNote dueAt) — **one-shot**, fires once when `dueAt` is reached | Note owner only |

**Resolved (2026-07-03, updated 2026-07-06):** rows 8 and 8d, and rows 13 and 8d, are NOT redundant — 8/13 are one-shot factual notices, 8d is the recurring "AI Nudge" escalation layered on top, generalized across Task, StickyNote, **and Broadcast** (as of the 2026-07-06 redesign) via `entityType`/`entityId`.

**Channels — in-app for all types**, except: row 8 (`TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE`) and the manual assigner-triggered `TASK_REMINDER` (via `POST /tasks/:id/remind`) **also send email**. AI Nudge types stay in-app only for routine recurring cycles — a recurring nudge shouldn't spam email every time. **One exception:** row 8d's one-time Task escalation-to-assigner moment sends in-app + email. Broadcast's cap-exhaustion (2026-07-06) does **not** email anyone — enforcement only, no escalation target. WhatsApp remains out of scope for all types.

**Cross-type duplicate suppression (W84, corrected 2026-07-10):** the sweep's dedup check is keyed on `recipientId`+`entityType`+`entityId`, not just `type`/`entityId` — before creating a new AI Nudge notification, check whether *any* AI Nudge type already fired for this same recipient+entity within the cooldown window. **Recipient-scoped, not just entity-scoped**, because Broadcast has many recipients per entity — an entity-only check would let one recipient's nudge suppress everyone else's for the same broadcast (a real bug caught during the Phase 1 build, fixed before shipping). Now only 2 types exist (Follow-up, Due-Proximity — Periodic is gone), both always reference exactly one entity, so this check applies uniformly to both with no batching exception needed anymore.

**Office-hours gating — removed entirely (2026-07-06).** Originally 9am–6pm IST; dropped because it assumed a single institution's business hours, which doesn't generalize across BOLO's multiple verticals (Education/CA-CS), timezones, or individual login patterns. The sweep now runs continuously (still on a 15-min tick), governed purely by each type's own elapsed-time gap: Follow-up every 6h (~4×/day), Due-Proximity every 3h (~8×/day). **Consequence to be aware of:** Task due-proximity's caps (3 due-today / 1 overdue) were originally sized assuming ~3 fires/day; at 8 fires/day the cap exhausts same-day, within hours, not over a full day. Accepted as intentional — matches "overdue is urgent" reasoning, just faster.

**Daily nudge cap — still descoped (2026-07-04):** not being built. No `dailyNudgeCapPerUser` field.

**Skip counters — universal but not universally enforced (2026-07-06):** every Follow-up condition (a–e) and every Due-Proximity entity (Task/StickyNote/Broadcast) gets a lifetime skip counter persisted in DB. Only **Task due-proximity** (cap 3/1, escalates) and **Broadcast due-proximity** (cap 3, enforcement only) actually enforce a cap. Follow-up's 5 conditions and StickyNote due-proximity track the counter for visibility/analytics only — no cap, no consequence.

**Schema — built 2026-07-10 (W94 resolved), simplified again 2026-07-13:** `Task.dueProximitySkipCount`/`dueProximityEscalatedAt` are gone (dropped in migration `20260709182552_nudge_skip_counter_and_periodic_retirement`), replaced by a generic `NudgeSkipCounter` table. The 2026-07-10 build added `userId` to the key as a correctness fix for Broadcast's many-recipients-per-entity problem — now that Broadcast (and StickyNote, and the Task/Subtask distinction) are out of scope entirely, every remaining candidate has exactly one assignee, so `userId` was **dropped again** (migration `20260712200810_nudge_scope_task_only`) back to simple per-task keying. That same migration added `lastShownAt`, which didn't exist before — it drives the Follow-up rotation (see row 8c/8d above), and is distinct from "when did this last fire" (`createdAt`/the sweep's own re-fire interval) — it specifically means "when did this last actually appear in a `GET /nudges` response," which can lag behind eligibility if the feed's 5-slot cap keeps bumping a candidate out:
```prisma
model NudgeSkipCounter {
  id          String    @id
  tenantId    String
  entityType  String    // "task" — scope narrowed 2026-07-13
  entityId    String
  nudgeKind   String    // "followup_no_progress" | "followup_unanswered_comment" | "due_proximity"
  skipCount   Int       @default(0)
  escalatedAt DateTime? // due-proximity only, one-time escalation-to-assigner guard
  lastShownAt DateTime? // Follow-up rotation — last time shown in a GET /nudges response
  createdAt   DateTime  @default(now())
  updatedAt   DateTime  @updatedAt

  tenant Tenant @relation(fields: [tenantId], references: [id])

  @@unique([entityType, entityId, nudgeKind])
  @@index([tenantId])
  @@map("nudge_skip_counters")
}
```
`AI_NUDGE_PERIODIC` was removed from the `NotificationType` enum on 2026-07-10 (6 stale test rows using it were deleted first, with sign-off, so the enum-narrowing cast wouldn't fail — no other notification types or rows were touched; verified 95→95 unrelated rows intact before/after).

**Backend API — built 2026-07-10:** `GET /api/v1/nudges`, `POST /api/v1/nudges/:id/skip`, `POST /api/v1/nudges/skip-all` — see `docs/api/api-spec.md` §11 for request/response shapes. The feed endpoint re-validates every row against current entity state on every call (never trusts what was true when the notification fired) and auto-resolves (marks read) anything whose condition no longer holds.

**UI — redesigned 2026-07-06:** single unified, scrollable nudge list (no more Screen A/Screen B split) with **two independent filter dimensions**: Type (All / Follow-up / Due-Proximity) and Entity (All / Task / StickyNote / Broadcast), combinable. Each row shows a contextual action button (`Accept Task` / `Add Comment` / `Mark Complete` / acknowledge) plus `Skip` plus `Open`/redirect, per the table above. **The panel is blocking while unresolved Due-Proximity items exist** — cannot be closed until every Due-Proximity item is either skipped (if not at last-chance) or resolved via its action (if at last-chance — no skip available then). Follow-up items never block closing. A **Skip All** button bulk-skips every currently-skippable item at once; disabled if any single item is at last-chance (that one must be resolved individually first). No separate "remind me later" — `Add Comment` (any content) already serves that purpose at last-chance. Still no Figma reference (W79 exception stands) — build from this spec, swap for real design later.

---

## Tenant Isolation

Every tenant-scoped entity carries `tenantId`. All queries must be scoped: `WHERE tenant_id = :currentTenantId`.

**Model:** Single shared PostgreSQL database — Row-Level Security on `tenant_id`. No per-tenant databases.

**Rule:** `tenantId` comes from the JWT only — API middleware injects it into every request. Never trust `tenantId` from the request body.

**Entities NOT directly tenant-scoped** (scoped through their parent):
- `Evidence`, `Comment`, `TaskPersonalLabel`, `VoiceRecording` — scoped through `taskId → task.tenantId`
- `StickyNote`, `OtpCode`, `BroadcastAcknowledgement` — scoped through `userId → user.tenantId`
- `TenantMembership` — carries `tenantId` directly
