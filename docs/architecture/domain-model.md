# BOLO — Domain Model

> **Last synced:** 2026-06-27 — added `VoiceRecording` entity (W37 cascaded): stores raw SDK transcript, audio S3 key, language, duration, and AI confidence score per task.
> **Platform:** Web-based (V1). Mobile PRD is a future phase — architecture must remain mobile-compatible.
> **Backing schema:** `bolo-backend/prisma/schema.prisma` is kept in lockstep with this file.
> ⚠️ Genuinely open items: **W15** (task card/detail fields — pull from Figma), **W19** (org-role permission model — confirm before touching role-enforcement logic), **W64** (readiness indicators data). All others resolved — see `docs/product/open-questions-web-v1.md`.

---

## Entity Overview

```
Tenant                            ← a college, a CA/CS firm, etc.
 ├── Users[] (with TenantMembership — role + dept + reporting chain)
 ├── Departments[]
 ├── ProjectLabels[]               ← Main Labels (Tier 1 — shared)
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

### Tenant

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| name | string | ✅ | e.g., "ABC College", "Sharma & Associates" |
| vertical | enum | ✅ | `EDUCATION` \| `CA_CS` |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

Tenant isolation: **Row-Level Security on `tenant_id`** — every query scoped to the current tenant. JWT carries `tenantId`; API middleware injects it. Never trust `tenantId` from the request body.

---

### User

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| tenantId | UUID | ✅ | FK → Tenant; single tenant per user (W56) |
| name | string | ✅ | |
| email | string | ✅ | Primary identifier; login via Email OTP; `@unique` |
| phone | string | — | Collected during Excel onboarding; future notification channels |
| profilePicUrl | string | — | S3 object key (not a URL) — pre-signed GET URL generated per request, same pattern as `Evidence.fileUrl`; optional, add/update/delete via `POST /upload/profile-picture-presign` → `PATCH /me/profile-picture` → `DELETE /me/profile-picture` |
| preferredLang | enum | ✅ | `EN` \| `HI`; default `EN` |
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
| name | string | ✅ | `@@unique([tenantId, name])` — no duplicate names within a tenant |
| colorCode | string | ✅ | 6-digit hex (`#RRGGBB`); default `#6B7280` if not provided at create |
| description | string | — | Optional free text; default `null` |
| createdBy | UUID | ✅ | FK → User |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> Set by the task assigner; visible to all users with task access. Personal labels (Tier 2) live in `TaskPersonalLabel`.

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
| projectLabelId | UUID | — | FK → ProjectLabel (Main Label — assigner sets; everyone sees) |
| isArchived | boolean | ✅ | `true` when assigner marks DONE_D on a main task; default `false` |
| acceptedAt | timestamp | — | When assignee accepted |
| parentTaskId | UUID | — | FK → Task (self-reference). When set, this Task **is** a subtask |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

**Ownership rules:**
- `title` — immutable after creation
- `dueDate`, `assigneeId`, `priority`, `projectLabelId`, `description` — editable by assigner only
- `status` — assigner controls (except `DONE_A` which assignee sets)
- Subtask creation — assignee only
- Delete — assigner only
- Reassign — blocked once any subtask exists

**State machine:** `DRAFT → OPEN → IN_PROGRESS → DONE_A → DONE_D`; `OVERDUE` auto-set by scheduler; `CANCELLED` by assigner any time before `DONE_D`.

**Status propagation rules (service layer):**
- Parent `CANCELLED` → all non-`DONE_D` subtasks cascade to `CANCELLED`
- Parent cannot reach `DONE_D` until all subtasks are `DONE_D` (gate, not auto-propagation)
- Subtask `OVERDUE` / `CANCELLED` does NOT affect parent status

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

### TaskPersonalLabel *(Personal Labels — Tier 2)*

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| taskId | UUID | ✅ | FK → Task |
| userId | UUID | ✅ | FK → User (the person who added this label) |
| label | string | ✅ | Free text; `@@unique([taskId, userId, label])` |
| colorCode | string | ✅ | 6-digit hex (`#RRGGBB`); default `#6B7280` if not provided at create |
| description | string | — | Optional free text; default `null` |
| createdAt | timestamp | ✅ | |

> Private to the user who added it — never visible to others. Both assigner and assignee can add personal labels. Autocomplete via `SELECT DISTINCT label WHERE userId`.
> ⚠️ `colorCode` and `description` are decided but **not yet in `schema.prisma`** — migration needed on `feature/project-label` branch.

---

### Evidence

| Field | Type | Required | Notes |
|---|---|---|---|
| id | UUID | ✅ | |
| taskId | UUID | ✅ | FK → Task (covers subtasks — a subtask IS a Task) |
| uploaderId | UUID | ✅ | FK → User |
| fileUrl | string | ✅ | S3 object key — pre-signed URL generated per request |
| fileName | string | ✅ | Original filename for UI display |
| fileSize | integer | ✅ | Bytes — for per-file limit enforcement when confirmed (PRD v1.1 §3.5) |
| fileType | enum | ✅ | `IMAGE` \| `PDF` \| `DOC` \| `OTHER` |
| caption | string | — | |
| createdAt | timestamp | ✅ | |

> No GPS / geotag fields — web platform, no device location API in V1.
> No task-level aggregate cap (PRD v1.1 removed it). Per-file size limit TBD.
> Files never pass through the backend — client uploads directly to S3 via pre-signed PUT URL.
> `fileUrl` stores the **S3 object key** (not a URL). A pre-signed GET URL with **15 min TTL** is generated on demand when the file is accessed. Raw S3 keys are never returned in API responses.
> Access: assigner and assignee only — enforced in the service layer via task ownership check.
> Upload safety: files land in `bolo-evidence/unconfirmed/` first; `POST /tasks/:id/evidence` moves to confirmed path + creates DB row. S3 lifecycle deletes `unconfirmed/` objects after 24h.

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
| dueAt | timestamp | — | When set → acts as reminder; shown red when imminent/past |
| isPinned | boolean | ✅ | Drives Pinned / Unpinned sub-tab; default `false` |
| promotedToTaskId | UUID | — | FK → Task; `@unique` — one note → one task |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> **W30 resolved** — no separate Reminder entity. A `StickyNote` with `dueAt` set IS the reminder. EventBridge fires `REMINDER_FIRED` notification for notes where `dueAt <= NOW()`.

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
| audienceDeptId | UUID | — | FK → Department; null = all departments |
| audienceRoleLevel | enum | — | `TOP` \| `MID` \| `EXECUTOR`; null = all role levels |
| requiresAcknowledgement | boolean | ✅ | Default `false` |
| imageUrl | string | — | Single image only. During DRAFT: stores S3 object key. At publish: server overwrites with a **pre-signed GET URL (25h TTL)**. Returned directly in feed — no per-request URL generation. |
| expiresAt | timestamp | — | Set to `createdAt + 1 day` on publish — not configurable (W54 resolved) |
| createdAt | timestamp | ✅ | |
| updatedAt | timestamp | ✅ | |

> **Audience scope is mandatory at publish** — service rejects publish if both `audienceDeptId` and `audienceRoleLevel` are null (PRD v1.1).
> `messageJson` is stored for the editor; `messageHtml` is pre-rendered on publish for fast feed rendering. Server sanitizes HTML with `sanitize-html` before storing.

---

### BroadcastAcknowledgement

| Field | Type | Required | Notes |
|---|---|---|---|
| broadcastId | UUID | ✅ | PK (composite with userId); FK → BroadcastNotice |
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
| actorId | UUID | — | FK → User; null for system-triggered actions |
| actorType | enum | ✅ | `USER` \| `SYSTEM`; default `USER` |
| action | enum | ✅ | See AuditAction enum below |
| entityType | string | ✅ | `"task"` \| `"broadcast"` \| `"user"` \| `"document"` |
| entityId | string | ✅ | ID of the affected entity |
| before | JSON | — | State before the change — null for creates |
| after | JSON | — | State after the change — null for deletes |
| metadata | JSON | — | IP address, user agent, session context |
| createdAt | timestamp | ✅ | |

> **Immutable** — never updated or deleted. CA/CS vertical requires longer retention for compliance (exact period TBD before first CA/CS onboarding). W63 resolved — audit log is in scope for V1.

**AuditAction enum covers:**
- Task & Subtask: `TASK_CREATED`, `TASK_UPDATED`, `TASK_DELETED`, `TASK_ASSIGNED`, `TASK_REASSIGNED`, `TASK_STATUS_CHANGED`, `TASK_PRIORITY_CHANGED`, `TASK_DUE_DATE_CHANGED`, `TASK_LABEL_CHANGED`, `TASK_ARCHIVED`, `SUBTASK_CREATED`, `SUBTASK_UPDATED`, `SUBTASK_DELETED`
- Documents: `DOCUMENT_UPLOADED`, `DOCUMENT_DELETED`, `DOCUMENT_DOWNLOADED`, `DOCUMENT_ACCESSED`
- Broadcast: `BROADCAST_CREATED`, `BROADCAST_UPDATED`, `BROADCAST_DELETED`, `BROADCAST_PUBLISHED`, `BROADCAST_ACKNOWLEDGED`, `BROADCAST_VIEWED`
- Audience Scope: `AUDIENCE_SCOPE_CREATED`, `AUDIENCE_SCOPE_MODIFIED`, `AUDIENCE_SCOPE_ASSIGNMENT_CHANGED`
- User Activity: `USER_LOGIN`, `USER_LOGOUT`, `USER_PROFILE_UPDATED`, `USER_ROLE_CHANGED`, `USER_PERMISSION_CHANGED`

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
| 8c | `AI_NUDGE_FOLLOWUP` | AI Nudge — Follow-up. **Redesigned 2026-07-06, built 2026-07-10 — 5 conditions on Task/Subtask, own action button each, no cap/escalation on any of them:** (a) not yet accepted → assignee, `Accept Task`; (b) accepted, no progress since → assignee, `Add Comment`; (c) comment posted, no reply from the other party → whoever didn't reply, `Add Comment`; (d) assignee marked `DONE_A`, assigner hasn't confirmed `DONE_D` → assigner, `Mark Complete`; (e) all subtasks `DONE_D` but parent still open → assigner, `Mark Complete`. All 5 also get a lifetime skip counter tracked in `NudgeSkipCounter` (below) **for visibility only** — no cap enforced, no escalation (assigner-facing (d)/(e) explicitly have no org-hierarchy escalation either — nothing above the assigner in this model). Broadcast is **not** a Follow-up condition — it's due-proximity only (see 8d). Fires every 6h, no office-hours gate. One condition fires per task per sweep tick (first match wins, priority order a→e) even if a task technically matches more than one. | Per-condition, see above |
| 8d | `AI_NUDGE_DUE_PROXIMITY` | AI Nudge — Due Date Proximity. **Polymorphic across Task/Subtask, StickyNote, and Broadcast (redesigned 2026-07-06, built 2026-07-10 — Broadcast added).** The only type with a real skip cap + escalation. Fires every 3h, no office-hours gate. Per-entity behavior: <br>**Task/Subtask** (already-accepted only — an unaccepted-but-overdue task is Follow-up condition (a)'s territory, not this one's; `IN_PROGRESS`/`OVERDUE` or due-today only): `Add Comment` + `Skip` + `Open`. **Skip is a user-clicked button** (`POST /nudges/:id/skip`) — it does not auto-increment on sweep fire; the counter only moves when the user actually clicks it. Cap: 3 for due-today, 1 for overdue (overdue stricter — more urgent; in practice this means overdue tasks start at last-chance immediately, zero grace skips). **Last-chance state** (`skipCount >= skipCap - 1`): `Skip` button disappears, replaced by a warning ("will be escalated to your assigner if not actioned") — only `Add Comment`/`Open` remain. Any comment left counts as resolving it (no separate "remind me later" — Add Comment already serves that purpose). **Escalation**: sweep-side check, independent of whether the routine nudge itself re-fires that tick — if `skipCount >= cap` and not yet escalated and the task still hasn't reached at least `DONE_A` → one-time in-app+email to the **assigner**, never repeats (`NudgeSkipCounter.escalatedAt` guard). If the task reached `DONE_A` in the meantime, it naturally drops out of the sweep query (not `OPEN`/`IN_PROGRESS`/`OVERDUE` anymore) — no escalation. **The assignee is only ever held to `DONE_A`, never `DONE_D` — that's the assigner's responsibility, not something the assignee can be threatened over.** <br>**StickyNote**: `Skip` only, no cap, no escalation — self-limits once the due date's calendar day ends. <br>**Broadcast**: `Skip`/acknowledge, **cap = 3, enforcement only — no escalation** (no sender-escalation target; exceeding the cap just removes Skip, forcing acknowledgment, nothing further happens). One row per (broadcast, un-acknowledged audience member) — dedup and skip counters are per-recipient, not per-broadcast, since one broadcast has many recipients. Self-limits at the broadcast's normal 1-day expiry regardless. | Task/Subtask: assignee (routine) + assigner (one-time escalation only). StickyNote: owner only. Broadcast: each un-acknowledged audience member, no escalation. |
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

**Schema — built 2026-07-10 (W94 resolved):** `Task.dueProximitySkipCount`/`dueProximityEscalatedAt` are gone (dropped in migration `20260709182552_nudge_skip_counter_and_periodic_retirement`), replaced by a generic polymorphic `NudgeSkipCounter` table. Built shape differs from the original proposal in two ways, both confirmed before implementing: added `tenantId` (every tenant-scoped table needs it for RLS — the original proposal omitted it) and added `userId` (**a correctness fix, not just style** — Broadcast has many recipients per entity, so an entity-only key would make every recipient of the same broadcast share one skip count; one person skipping would push it to last-chance for everyone):
```prisma
model NudgeSkipCounter {
  id          String    @id
  tenantId    String
  userId      String
  entityType  String    // "task" | "subtask" | "sticky_note" | "broadcast"
  entityId    String
  nudgeKind   String    // "followup_not_accepted" | "followup_no_progress" | "followup_unanswered_comment" |
                         // "followup_done_a_pending" | "followup_subtasks_done_pending" | "due_proximity"
  skipCount   Int       @default(0)
  escalatedAt DateTime? // only ever set for Task/Subtask due-proximity
  createdAt   DateTime  @default(now())
  updatedAt   DateTime  @updatedAt

  tenant Tenant @relation(fields: [tenantId], references: [id])
  user   User   @relation(fields: [userId], references: [id])

  @@unique([userId, entityType, entityId, nudgeKind])
  @@index([tenantId])
  @@map("nudge_skip_counters")
}
```
`AI_NUDGE_PERIODIC` was removed from the `NotificationType` enum in the same migration (6 stale test rows using it were deleted first, with sign-off, so the enum-narrowing cast wouldn't fail — no other notification types or rows were touched; verified 95→95 unrelated rows intact before/after).

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
