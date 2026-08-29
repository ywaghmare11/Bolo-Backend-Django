# BOLO — API Specification

> **Last updated:** 2026-06-20 — full rewrite for PRD v1.1 + schema V1.1. All 15 entities covered.
> **Status:** Authoritative contract. Open items: W64 (readiness indicators), W65 (routing approach).
> **Base URL:** `https://api.bolo.app/api/v1`

---

## Conventions

- REST over HTTPS
- **Auth:** httpOnly JWT cookie set on login — browser sends it automatically. No `Authorization` header.
- **Tenant scoping:** `tenantId` read exclusively from the JWT — never accepted in the request body.
- **Timestamps:** ISO 8601 IST, `+05:30` offset (`2026-06-20T15:30:00+05:30`) — **corrected 2026-07-12**, this previously said UTC (`Z`), but every repository (`TaskRepository` since inception, `StickyNoteRepository` as of 2026-07-12) actually stores wall-clock IST via `nowIST()`/serializes via `istLabel()`/`toIST()` (`src/utils/date.ts`), matching `TZ=Asia/Kolkata` and the India-first product. Doc was wrong, not the code.
- **IDs:** UUIDs
- **Pagination:** `?page=1&limit=20` — default limit 20, max 100
- **RBAC middleware** on every route — no exceptions.

### Response envelope

All responses produced by `successResponse()` / `failureResponse()` from `utils/response.ts` — never raw `res.json()`.

```json
// Success — single resource
{
  "success": true,
  "message": "Task created",
  "data": { ... }
}

// Success — list with pagination
{
  "success": true,
  "message": "OK",
  "data": [ ... ],
  "pagination": { "page": 1, "limit": 20, "total": 84 }
}

// Error — all 4xx and 5xx
{
  "success": false,
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task with id abc123 does not exist"
  }
}
```

> For brevity, inline examples in this spec omit the `success` wrapper field — it is **always** present. The `success: true/false` field is the primary flag clients should read; HTTP status code is secondary.

### Standard error response examples

```json
// 400 — validation
{ "success": false, "error": { "code": "VALIDATION_ERROR", "message": "dueDate is required" } }

// 400 — domain rule violation
{ "success": false, "error": { "code": "TITLE_IMMUTABLE", "message": "Task title cannot be changed after creation" } }
{ "success": false, "error": { "code": "SUBTASK_DUE_DATE_INVALID", "message": "Subtask due date must be earlier than parent task due date" } }
{ "success": false, "error": { "code": "REASSIGN_BLOCKED", "message": "Cannot reassign — this task has existing subtasks" } }
{ "success": false, "error": { "code": "SUBTASKS_INCOMPLETE", "message": "All subtasks must be DONE_D before the parent task can be completed" } }
{ "success": false, "error": { "code": "DRAFT_MISSING_FIELDS", "message": "Title, assignee, and due date are required to move a task out of Draft" } }

// 401 — not authenticated
{ "success": false, "error": { "code": "UNAUTHENTICATED", "message": "Authentication required" } }

// 403 — authenticated but not permitted
{ "success": false, "error": { "code": "FORBIDDEN", "message": "You are not the assigner of this task" } }
{ "success": false, "error": { "code": "BROADCAST_NOT_PERMITTED", "message": "Your account does not have broadcast permission" } }

// 404 — not found
{ "success": false, "error": { "code": "NOT_FOUND", "message": "Task not found" } }

// 409 — conflict
{ "success": false, "error": { "code": "ALREADY_ACKNOWLEDGED", "message": "You have already acknowledged this broadcast" } }
{ "success": false, "error": { "code": "TASK_TERMINAL", "message": "Task is in a terminal state (DONE_D or CANCELLED) and cannot be modified" } }
{ "success": false, "error": { "code": "LABEL_IN_USE", "message": "Cannot delete — 3 active tasks reference this label" } }

// 429 — rate limited
{ "success": false, "error": { "code": "RATE_LIMITED", "message": "Too many OTP requests. Try again in 60 seconds." } }

// 500 — unexpected
{ "success": false, "error": { "code": "SERVER_ERROR", "message": "An unexpected error occurred" } }
```

### Standard error codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Missing/invalid field |
| 400 | `TITLE_IMMUTABLE` | Attempt to PATCH title after creation |
| 400 | `DRAFT_MISSING_FIELDS` | Publish attempted without title+assignee+dueDate |
| 400 | `SUBTASK_DUE_DATE_INVALID` | Subtask dueDate ≥ parent dueDate |
| 400 | `ASSIGNMENT_LOOP` | Subtask assigned back to parent assigner |
| 401 | `UNAUTHENTICATED` | No or expired JWT |
| 403 | `FORBIDDEN` | Authenticated but wrong role/ownership |
| 403 | `BROADCAST_NOT_PERMITTED` | `canBroadcast = false` on membership |
| 404 | `NOT_FOUND` | Entity does not exist or not accessible |
| 409 | `REASSIGN_BLOCKED` | Task has subtasks — reassignment not allowed |
| 409 | `ALREADY_ACKNOWLEDGED` | User already acknowledged this broadcast |
| 409 | `TASK_TERMINAL` | Task is DONE_D or CANCELLED — no further transitions |
| 409 | `SUBTASKS_INCOMPLETE` | Parent cannot reach DONE_D until all subtasks are DONE_D |
| 409 | `LABEL_IN_USE` | Project label cannot be deleted — active tasks reference it |
| 409 | `ALREADY_PROMOTED` | Sticky note already promoted to a task |
| 409 | `HEAD_ALREADY_ASSIGNED` | User is already the head of another department |
| 422 | `BROADCAST_ALREADY_PUBLISHED` | Cannot edit or re-publish an already-published broadcast |
| 422 | `EMAIL_UNDELIVERABLE` | SMTP RCPT TO probe confirmed recipient mailbox does not exist |
| 429 | `RATE_LIMITED` | Too many requests (OTP: 1/60s; API: 100 req/min per user) |
| 500 | `SERVER_ERROR` | Unexpected server error |
| 502 | `EMAIL_DELIVERY_FAILED` | User exists in DB but the SES send failed (transient — retry) |

---

## 1. Auth

No role middleware — these routes are public (pre-auth).

### POST /auth/request-otp

Sends a 6-digit OTP to the user's email via AWS SES. Upserts the OTP row (one active OTP per email). OTP is SHA-256 hashed before storing. Expires in 10 minutes. Max 3 verify attempts before lockout.

A pre-send SMTP RCPT TO probe is run against the recipient's MX server — domains/mailboxes that reject at SMTP level return 422 immediately. Gmail and providers that accept-then-bounce are undetectable synchronously.

```json
Request:
{ "email": "dean@abc.edu" }

Response 200:
{ "data": null, "message": "OTP sent to dean@abc.edu" }
```

**Errors:** 400 `INVALID_EMAIL` · 404 `USER_NOT_FOUND` · 422 `EMAIL_UNDELIVERABLE` · 429 `RATE_LIMITED` · 502 `EMAIL_DELIVERY_FAILED`

---

### POST /auth/verify-otp

Verifies the OTP, issues JWT, sets httpOnly cookie. Deletes the OtpCode row immediately after success.

```json
Request:
{ "email": "dean@abc.edu", "otp": "482910" }

Response 200:
{
  "data": {
    "userId": "uuid",
    "name": "Dr. Kamal Sethi",
    "tenantId": "uuid",
    "tenantName": "ABC College",
    "tenantSlug": "abc-college",
    "roleLevel": "TOP",
    "roleLabel": "Dean",
    "canBroadcast": true,
    "preferredLang": "EN"
  },
  "message": "Login successful"
}

Set-Cookie: token=<jwt>; HttpOnly; SameSite=Strict; Path=/; (no Max-Age — session cookie)
```

**`tenantSlug`** (upstream added 2026-08-09; `Tenant.url_slug` + its `POST /platform-admin/tenants` assignment path both built here, 2026-08-22/23) — the tenant's `urlSlug`. Upstream's `bolo-web` uses it + a slugified first name to build a post-login URL path. Purely cosmetic/frontend routing — never an authorization signal. **Nullable in this project** (unlike upstream's required field) — any tenant predating this endpoint (`seed_dev_data`, factories) has no slug, so `tenantSlug` is `null` in that case.

**Errors:** 400 `INVALID_OTP` (includes `data.attemptsRemaining`) · 400 `OTP_EXPIRED` · 429 `RATE_LIMITED` (locked 15 min, `data.attemptsRemaining: 0`)

---

### POST /auth/logout

Clears the JWT cookie server-side.

```json
Response 200:
{ "data": null, "message": "Logged out" }
```

---

## 2. Tasks

**Access rules summary:**
- Any authenticated tenant member can create a task (becomes assigner).
- `tenantId` always from JWT.
- Assigner = creator (`assignerId`). Assignee = `assigneeId`.
- Service enforces task-level ownership — controller only parses HTTP, never checks ownership.

### GET /tasks — list tasks

```
GET /api/v1/tasks?view=assigned&status=all&page=1&limit=20
```

| Param | Required | Values | Default |
|---|---|---|---|
| `view` | yes | `assigned` \| `delegated` \| `needs_attention` \| `open` \| `overdue` \| `done_a` \| `by_label` \| `due_this_week` | — |
| `labelId` | no (required when `view=by_label`) | UUID | — |
| `isArchived` | no | `true` \| `false` | `false` |
| `page` | no | integer ≥ 1 | `1` |
| `limit` | no | 1–100 | `20` |

**View → filter logic:**
- `assigned` — `assigneeId = me`; excludes `DRAFT`, `DONE_D`, `CANCELLED`, `isArchived=true`; sort: `OVERDUE` first → `dueDate ASC` → `createdAt DESC`
- `delegated` — `assignerId = me`; excludes `DONE_D`, `isArchived=true`; same sort
- `needs_attention` — tasks where action is required: `OPEN` (not yet accepted) + `OVERDUE` + `DONE_A` (awaiting assigner mark); scoped to me as assignee or assigner
- `open` — `status = OPEN`; scoped to me as assignee or assigner
- `overdue` — `status = OVERDUE`; scoped to me as assignee or assigner
- `done_a` — `status = DONE_A`; scoped to me as assignee or assigner
- `by_label` — requires `labelId`; main-label tasks (as assigner, or as assignee without a personal label override) + personal-label tasks (as assignee), scoped to me
- `due_this_week` — `dueDate` falls within the current Monday–Sunday calendar week (server-local day boundaries, `TaskRepository._current_week_range`); excludes `DRAFT`, `DONE_D`, `CANCELLED`; scoped to me as assignee or assigner

**Access:** `requireAuth` — scoped to `tenantId` from JWT.

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "title": "Submit NAAC report",
      "status": "IN_PROGRESS",
      "acceptanceStatus": "ACCEPTED",
      "priority": "P1",
      "dueDate": "2026-06-30T17:00:00Z",
      "isArchived": false,
      "parentTaskId": null,
      "assignerId": "uuid",
      "assignerName": "Dr. Kamal Sethi",
      "assigneeId": "uuid",
      "assigneeName": "Prof. Asha Nair",
      "mainLabelId": "uuid",
      "projectLabelName": "NAAC",
      "subtaskCount": 3,
      "doneSubtaskCount": 1,
      "commentCount": 5,
      "latestComment": {
        "id": "uuid",
        "authorId": "uuid",
        "authorName": "Prof. Asha Nair",
        "text": "A1 data compiled. Working on B2.",
        "isEdited": false,
        "createdAt": "2026-06-20T11:00:00Z"
      },
      "createdAt": "2026-06-19T10:00:00Z",
      "updatedAt": "2026-06-20T08:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 12 }
}
```

> `latestComment` is the single most recent comment on the task (`null` if none) — a lightweight preview for list rows. Use `GET /tasks/:id/comments` or the `comments[]` array on `GET /tasks/:id` for the full thread.

**Errors:** 400 (invalid view/param) · 401 · 500

---

### GET /tasks/counts — dashboard tab counts

```
GET /api/v1/tasks/counts
```

Returns the count of tasks in each task-tab view (`assigned`, `delegated`, `needs_attention`, `open`, `overdue`, `done_a`/`doneA`, `due_this_week`/`dueThisWeek`) for the calling user — used for sidebar/tab badge counts. Cheap COUNT query — no pagination, no body params. Uses the same filter logic as `GET /tasks?view=...` (see above), scoped to `tenantId` from JWT. `by_label` has no count here since it requires a `labelId`.

**Access:** `requireAuth` — scoped to `tenantId` + `userId` from JWT.

```json
Response 200:
{ "success": true, "data": { "assigned": 4, "delegated": 7, "needsAttention": 2, "open": 3, "overdue": 1, "doneA": 2, "dueThisWeek": 5 }, "message": "OK" }
```

**Errors:** 401 · 500

---

### GET /tasks/:id — task detail

Returns the task with its subtasks, comments, evidence, and the calling user's personal labels.

**Access:** `requireAuth` — calling user must be assigner or assignee. Service checks; returns 403 otherwise.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "title": "Submit NAAC report",
    "status": "IN_PROGRESS",
    "acceptanceStatus": "ACCEPTED",
    "priority": "P1",
    "dueDate": "2026-06-30T17:00:00Z",
    "description": "Include sections A1 through C4.",
    "isArchived": false,
    "parentTaskId": null,
    "acceptedAt": "2026-06-20T09:00:00Z",
    "assignerId": "uuid",
    "assignerName": "Dr. Kamal Sethi",
    "assigneeId": "uuid",
    "assigneeName": "Prof. Asha Nair",
    "mainLabelId": "uuid",
    "projectLabelName": "NAAC",
    "myPersonalLabels": ["urgent", "admin"],
    "subtasks": [
      {
        "id": "uuid",
        "title": "Compile criterion A1 data",
        "status": "DONE_A",
        "assigneeId": "uuid",
        "assigneeName": "Rahul Sharma",
        "dueDate": "2026-06-25T17:00:00Z",
        "priority": "P2"
      }
    ],
    "comments": [
      {
        "id": "uuid",
        "authorId": "uuid",
        "authorName": "Prof. Asha Nair",
        "text": "A1 data compiled. Working on B2.",
        "isEdited": false,
        "createdAt": "2026-06-20T11:00:00Z"
      }
    ],
    "evidence": [
      {
        "id": "uuid",
        "fileUrl": "https://s3.../presigned...",
        "fileName": "criterion-a1.pdf",
        "fileSize": 204800,
        "fileType": "PDF",
        "caption": "Criterion A1 data pack",
        "uploaderId": "uuid",
        "uploaderName": "Prof. Asha Nair",
        "createdAt": "2026-06-20T10:30:00Z"
      }
    ],
    "voiceRecording": {
      "rawTranscript": "Rohit ko NAAC report submit karna hai next month tak",
      "language": "hi-en",
      "durationSecs": 12,
      "confidenceScore": 0.87,
      "hasAudio": true
    },
    "createdAt": "2026-06-19T10:00:00Z",
    "updatedAt": "2026-06-20T11:00:00Z"
  }
}
```

> `voiceRecording` is `null` if the task was created via keyboard. `hasAudio: true` means an audio clip is stored in S3 — point an `<audio>` tag's `src` directly at `GET /tasks/:id/voice-recording/audio` to stream it. The raw S3 key is never exposed.

**Errors:** 401 · 403 (not assigner or assignee) · 404 · 500

---

### POST /tasks — create a task

**Transaction boundary:** the `tasks` row and the `voice_recordings` row (transcript only) are saved in a **single DB transaction**. S3 audio upload happens after the response is returned — never inside the transaction.

```json
Request:
{
  "title": "Submit NAAC self-study report",   // required
  "assigneeId": "uuid",                        // required
  "dueDate": "2026-06-30T17:00:00Z",          // required for Open; optional while saving Draft
  "priority": "P1",                            // optional — default: P3
  "mainLabelId": "uuid",                    // optional — default: null
  "description": "Include sections A1–C4.",   // optional — default: ""

  "voiceRecording": {                          // optional — only for voice-created tasks
    "rawTranscript": "Rohit ko NAAC report submit karna hai next month tak",
    "language": "hi-en",
    "durationSecs": 12,
    "confidenceScore": 0.87
    // audioUrl is NOT included here — added separately after S3 upload via PATCH
  }
}

Response 201:
{
  "data": {
    "id": "uuid",
    "title": "Submit NAAC self-study report",
    "status": "OPEN",     // "DRAFT" if any required field is missing
    "acceptanceStatus": "PENDING",
    "assignerId": "uuid",
    "assigneeId": "uuid",
    "priority": "P3",
    "dueDate": "2026-06-30T17:00:00Z",
    "parentTaskId": null,
    "createdAt": "2026-06-20T12:00:00Z"
  },
  "message": "Task created"
}
```

**Business rules enforced:**
- If `title + assigneeId + dueDate` all present → status = `OPEN`; TASK_ASSIGNED notification fired to assignee.
- If any of the three is missing → status = `DRAFT`; assignee NOT notified.
- `assigneeId` must belong to the same tenant — 400 if not.
- Default `priority = P3` applied silently if omitted.
- If `voiceRecording` is present → `voice_recordings` row created in the same DB transaction (`audioUrl = null`). If `voiceRecording` is absent → no row created (keyboard-created task).

**Two-phase voice audio flow (frontend, after 201):**
1. `POST /upload/voice-presign { taskId }` → pre-signed S3 PUT URL
2. `PUT audioBlob → S3` directly (never through API)
3. `PATCH /tasks/:id/voice-recording/audio { s3Key }` → sets `audioUrl` on the voice_recordings row

If phase 2 fails for any reason: task + transcript are safe (saved in phase 1). `audioUrl` stays null, `hasAudio = false`. Acceptable — transcript is source of truth (W39).

**Errors:** 400 (validation) · 401 · 500

---

### PATCH /tasks/:id — update a task (assigner only)

```json
Request (any subset — all optional):
{
  "assigneeId": "uuid",                  // only allowed if NO subtasks exist
  "dueDate": "2026-07-15T17:00:00Z",
  "priority": "P2",
  "mainLabelId": "uuid",
  "description": "Updated scope."
}
// "title" is NOT patchable — returns 400 TITLE_IMMUTABLE if included
// "status" is NOT patchable — use action endpoints (accept, done-a, done-d, cancel)
```

```json
Response 200:
{ "data": { /* updated task fields */ }, "message": "Task updated" }
```

**Business rules enforced:**
- Caller must be `assignerId` — 403 otherwise.
- If `assigneeId` changed and subtasks exist → 409 REASSIGN_BLOCKED.
- If `dueDate` removed → task reverts to `DRAFT` status (loses Open/active state).
- Fires TASK_EDITED notification to assignee.

**Errors:** 400 (TITLE_IMMUTABLE · VALIDATION_ERROR) · 401 · 403 · 404 · 409 (REASSIGN_BLOCKED) · 500

---

### DELETE /tasks/:id — delete a task (assigner only)

Hard delete. Cascades to all subtasks, evidence, comments, personal labels.

**Access:** Caller must be `assignerId`. Cannot delete `DONE_D` tasks.

```json
Response 200:
{ "data": null, "message": "Task deleted" }
```

**Errors:** 400 (TASK_TERMINAL — already DONE_D) · 401 · 403 · 404 · 500

---

### POST /tasks/:id/accept — assignee accepts task

Transitions `OPEN → IN_PROGRESS`. Sets `acceptedAt`.

**Access:** Caller must be `assigneeId`. Task must be in `OPEN` state.

```json
Response 200:
{ "data": { "status": "IN_PROGRESS", "acceptedAt": "2026-06-20T09:00:00Z" }, "message": "Task accepted" }
```

**Errors:** 400 (task not in OPEN state) · 401 · 403 · 404 · 500

---

### POST /tasks/:id/done-a — assignee marks complete

Transitions `IN_PROGRESS | OVERDUE → DONE_A`. Notifies assigner.

**Access:** Caller must be `assigneeId`.

```json
Response 200:
{ "data": { "status": "DONE_A" }, "message": "Marked as complete — awaiting delegator confirmation" }
```

**Errors:** 400 (invalid state) · 401 · 403 · 404 · 500

---

### POST /tasks/:id/done-d — assigner marks complete

Transitions `IN_PROGRESS | OVERDUE | DONE_A → DONE_D`. Archives task (`isArchived = true`). Notifies assignee.

**Access:** Caller must be `assignerId`. All subtasks must be `DONE_D` — 409 SUBTASKS_INCOMPLETE otherwise.

```json
Response 200:
{ "data": { "status": "DONE_D", "isArchived": true }, "message": "Task completed and archived" }
```

**Errors:** 400 (invalid state) · 401 · 403 · 404 · 409 (SUBTASKS_INCOMPLETE) · 500

---

### POST /tasks/:id/cancel — assigner cancels task

Transitions any non-terminal state → `CANCELLED`. Cascades cancel to all non-DONE_D subtasks. Notifies assignee (unless task was in DRAFT).

**Access:** Caller must be `assignerId`. Cannot cancel `DONE_D` tasks.

```json
Response 200:
{ "data": { "status": "CANCELLED" }, "message": "Task cancelled" }
```

**Errors:** 400 (TASK_TERMINAL) · 401 · 403 · 404 · 500

---

### POST /tasks/:id/remind — send reminder to assignee (assigner only)

Fires a TASK_REMINDER notification to the assignee — **in-app + email** (email via the existing AWS SES setup used for OTP). Implemented 2026-07-03: `remindTaskService` validates (assigner check, task status check), writes the `Notification` row via `NotificationRepository`, then sends `sendTaskReminderEmail` best-effort (failure is logged and swallowed, doesn't fail the request).

**Access:** Caller must be `assignerId`. Task must be in `OPEN | IN_PROGRESS | OVERDUE` state.

```json
Response 200:
{ "data": null, "message": "Reminder sent to assignee" }
```

**Errors:** 400 (invalid state for reminder) · 401 · 403 · 404 · 500

---

## 3. Subtasks

A subtask is a `Task` with `parentTaskId` set. Uses the same state machine as a regular task. **The parent task's assignee acts as the subtask's assigner.**

### POST /tasks/:taskId/subtasks — create a subtask

**Access:** Caller must be the **assignee** of the parent task. Parent must be in `IN_PROGRESS` (accepted).

```json
Request:
{
  "title": "Compile criterion A1 data",         // required
  "assigneeId": "uuid",                          // required — cannot be parent task's assigner
  "dueDate": "2026-06-25T17:00:00Z",            // required — must be < parent.dueDate
  "priority": "P2",                              // optional — default P3
  "description": "..."                           // optional
}

Response 201:
{
  "data": {
    "id": "uuid",
    "parentTaskId": "uuid",
    "title": "Compile criterion A1 data",
    "status": "OPEN",
    "assignerId": "uuid",   // = parent's assigneeId (caller)
    "assigneeId": "uuid",
    "dueDate": "2026-06-25T17:00:00Z",
    "priority": "P2"
  },
  "message": "Subtask created"
}
```

**Business rules enforced:**
- If no `mainLabelId` is set on the subtask → server inherits parent task's `mainLabelId` silently.
- Notification `SUBTASK_CREATED` fired to sub-assignee on creation.

**Errors:** 400 (SUBTASK_DUE_DATE_INVALID · ASSIGNMENT_LOOP · VALIDATION_ERROR) · 401 · 403 · 404 · 500

---

### PATCH /tasks/:taskId/subtasks/:id

Same rules as PATCH /tasks/:id — assigner only, title immutable.

---

### DELETE /tasks/:taskId/subtasks/:id

Same rules as DELETE /tasks/:id — assigner (= parent's original assignee) only.

---

### POST /tasks/:taskId/subtasks/:id/accept
### POST /tasks/:taskId/subtasks/:id/done-a
### POST /tasks/:taskId/subtasks/:id/done-d
### POST /tasks/:taskId/subtasks/:id/cancel

Same rules as their parent-task equivalents. `done-d` on a subtask does NOT trigger parent archiving — parent archiving only happens when the assigner explicitly calls `POST /tasks/:id/done-d` and all subtasks are DONE_D.

---

## 4. Comments

Full CRUD. Both assigner and assignee can comment. Author can edit/delete their own comments only.

### GET /tasks/:id/comments

**Access:** `requireAuth` + must be assigner or assignee.

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "authorId": "uuid",
      "authorName": "Prof. Asha Nair",
      "text": "A1 data compiled. Working on B2.",
      "isEdited": false,
      "createdAt": "2026-06-20T11:00:00Z",
      "updatedAt": "2026-06-20T11:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 3 }
}
```

---

### POST /tasks/:id/comments

**Access:** `requireAuth` + must be assigner or assignee.

```json
Request:
{ "text": "A1 data compiled. Working on B2." }

Response 201:
{ "data": { "id": "uuid", "text": "...", "authorId": "uuid", "isEdited": false, "createdAt": "..." }, "message": "Comment added" }
```

Fires COMMENT_ADDED notification to the other party (assigner ↔ assignee).

**Errors:** 400 (empty text) · 401 · 403 · 404 · 500

---

### PATCH /tasks/:id/comments/:cid

**Access:** Caller must be `authorId`. Sets `isEdited = true`.

```json
Request: { "text": "Updated comment text." }
Response 200: { "data": { "id": "uuid", "text": "...", "isEdited": true, "updatedAt": "..." } }
```

**Errors:** 401 · 403 (not author) · 404 · 500

---

### DELETE /tasks/:id/comments/:cid

**Access:** Caller must be `authorId`.

```json
Response 200: { "data": null, "message": "Comment deleted" }
```

**Errors:** 401 · 403 · 404 · 500

---

## 5. Evidence

Evidence files go directly to S3 via pre-signed URL — **they never pass through the API server**.

**Orphan-safe pattern:** uploads land in an `unconfirmed/` S3 prefix first. `POST /tasks/:id/evidence` moves the file to the confirmed path and creates the DB row atomically. An S3 lifecycle rule deletes anything under `unconfirmed/` after 24h — S3 self-cleans without needing DB lookups.

```
S3 paths:
  Upload →   bolo-evidence/unconfirmed/{tenantId}/{taskId}/{evidenceId}/{filename}
  Confirmed → bolo-evidence/{tenantId}/{taskId}/{evidenceId}/{filename}

S3 lifecycle rule (set once):
  Prefix: unconfirmed/  |  Action: DELETE  |  After: 24h
```

### POST /upload/presign — request pre-signed upload URL

**Access:** `requireAuth` + must be assigner or assignee of the task.

```json
Request:
{
  "taskId": "uuid",
  "filename": "criterion-a1.pdf",
  "contentType": "application/pdf",
  "fileSize": 204800
}

Response 200:
{
  "data": {
    "uploadUrl": "https://s3.ap-south-1.amazonaws.com/bolo-evidence/unconfirmed/...",
    "evidenceId": "uuid",
    "expiresIn": 900
  }
}
```

Client uploads directly to `uploadUrl` (the `unconfirmed/` path) via HTTP PUT, then calls `POST /tasks/:id/evidence` to confirm.

**Allowed types:** image/jpeg · image/png · image/heic · application/pdf · application/vnd.openxmlformats-officedocument.wordprocessingml.document · application/vnd.openxmlformats-officedocument.spreadsheetml.sheet

**Errors:** 400 (unsupported type · file too large · missing fields) · 401 · 403 · 404 · 500

---

### POST /tasks/:id/evidence — confirm evidence after S3 upload

**Access:** `requireAuth` + must be assigner or assignee.

Server does three things in order:
1. `CopyObject`: `unconfirmed/...` → `bolo-evidence/{tenantId}/...`
2. `DeleteObject`: remove from `unconfirmed/`
3. `INSERT` Evidence row with confirmed S3 key

If step 3 fails after copy+delete: object is in confirmed path with no DB row (extremely rare — DB crash in a 50ms window). Weekly EventBridge reconciliation job handles this edge case.

```json
Request:
{
  "evidenceId": "uuid",
  "caption": "Criterion A1 data pack"   // optional
}

Response 201:
{
  "data": {
    "id": "uuid",
    "taskId": "uuid",
    "uploaderId": "uuid",
    "fileName": "criterion-a1.pdf",
    "fileSize": 204800,
    "fileType": "PDF",
    "caption": "Criterion A1 data pack",
    "createdAt": "2026-06-20T10:30:00Z"
  },
  "message": "Evidence attached"
}
```

Fires EVIDENCE_ATTACHED notification to the other party.

**Errors:** 400 (evidenceId not found / S3 upload not confirmed) · 401 · 403 · 404 · 500

---

### GET /tasks/:id/evidence — list evidence

**Access:** `requireAuth` + must be assigner or assignee.

> **Changed (bolo-backend-django sync 2026-08-03):** `fileUrl` is no longer a pre-signed S3 read URL. It's now an **app-relative path** to the streaming endpoint below (`/tasks/{id}/evidence/{eid}/file`) — a pre-signed URL is a bearer credential the moment it's put in a JSON response, valid for its full TTL for whoever holds it; the streaming endpoint re-checks access on every request instead.

```json
Response 200:
{ "data": [ { "id": "uuid", "fileUrl": "/tasks/{id}/evidence/{eid}/file", "fileName": "...", "fileType": "PDF", "caption": "...", "uploaderName": "...", "createdAt": "..." } ] }
```

---

### GET /tasks/:id/evidence/:eid/file — stream evidence file (new, bolo-backend-django sync 2026-08-03)

**Access:** `requireAuth` + must be assigner or assignee. Streams the S3 object server-side; re-checked on every request rather than baked into a signed URL.

**Errors:** 401 · 403 · 404 · 500

---

### DELETE /tasks/:id/evidence/:eid

**Access:** **Caller must be the uploader (`uploaderId`) only** — **narrowed (bolo-backend-django sync 2026-08-03)**, was previously uploader-or-assigner. Matches `Comment`'s existing author-only delete rule. Deletes from S3 and DB.

```json
Response 200: { "data": null, "message": "Evidence removed" }
```

**Errors:** 401 · 403 · 404 · 500

**Note:** `.xls` (legacy binary Excel) is now accepted alongside `.xlsx` for evidence uploads (bolo-backend-django sync 2026-08-03).

---

## 6. Voice Recording

**Two-phase design** — transcript is saved atomically with the task (inside `POST /tasks`); audio is uploaded to S3 and linked separately after the task exists. Same `unconfirmed/` prefix pattern as evidence — S3 lifecycle rule auto-cleans unconfirmed audio after 24h.

```
S3 paths:
  Upload →   bolo-voice/unconfirmed/{tenantId}/{taskId}/voice.webm
  Confirmed → bolo-voice/{tenantId}/{taskId}/voice.webm

S3 lifecycle rule (same bucket, separate prefix):
  Prefix: unconfirmed/  |  Action: DELETE  |  After: 24h
```

**Access on all routes:** `requireAuth` + caller must be assigner or assignee of the task.

### POST /upload/voice-presign — request pre-signed audio upload URL

Called after `POST /tasks` returns 201. Generates a short-lived S3 PUT URL for the audio blob.

```json
Request:
{
  "taskId": "uuid",
  "filename": "voice.webm",
  "contentType": "audio/webm",
  "durationSecs": 12
}

Response 200:
{
  "data": {
    "uploadUrl": "https://s3.ap-south-1.amazonaws.com/bolo-voice/unconfirmed/tenantId/taskId/voice.webm?...",
    "s3Key": "unconfirmed/tenantId/taskId/voice.webm",
    "expiresIn": 900
  }
}
```

Client uploads audio blob directly to `uploadUrl` (the `unconfirmed/` path) via HTTP PUT, then calls `PATCH /tasks/:id/voice-recording/audio`.

**Errors:** 400 (unsupported contentType · missing fields · no voice_recording row exists for this task) · 401 · 403 · 404 · 500

---

### PATCH /tasks/:id/voice-recording/audio — confirm audio after S3 upload

Called after the S3 PUT to `unconfirmed/` succeeds. Server moves the file to the confirmed path and sets `audioUrl` on the VoiceRecording row.

Server does in order:
1. `CopyObject`: `unconfirmed/...` → `bolo-voice/{tenantId}/{taskId}/voice.webm`
2. `DeleteObject`: remove from `unconfirmed/`
3. `UPDATE voice_recordings SET audio_url = confirmedKey WHERE task_id = ...`

```json
Request:
{ "s3Key": "unconfirmed/tenantId/taskId/voice.webm" }

Response 200:
{
  "data": { "hasAudio": true },
  "message": "Audio linked"
}
```

**Business rules enforced:**
- `VoiceRecording` row must already exist (created by `POST /tasks`) — 404 if not.
- `audioUrl` stored as confirmed S3 key — never returned raw in any response.
- Idempotent — safe to retry; CopyObject to same destination is a no-op if already done.

**Failure handling:** if this call never arrives (network failure, tab close), the task + transcript are intact; object sits in `unconfirmed/` and is auto-deleted by S3 lifecycle after 24h. `hasAudio` stays false — acceptable (W39: transcript is source of truth).

**Errors:** 401 · 403 · 404 (no voice recording for this task) · 500

---

### GET /tasks/:id/voice-recording — get transcript and metadata

Returns the transcript, language, confidence, and whether audio is available. Never returns the raw S3 key.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "rawTranscript": "Rohit ko NAAC report submit karna hai next month tak",
    "language": "hi-en",
    "durationSecs": 12,
    "confidenceScore": 0.87,
    "hasAudio": true,
    "createdAt": "2026-06-27T10:00:00Z"
  }
}
```

**Errors:** 401 · 403 · 404 (no voice recording for this task) · 500

---

### GET /tasks/:id/voice-recording/audio — stream audio playback

**Changed (built here 2026-08-23, matching upstream's 2026-07-25 change) — this endpoint used to return `{ playbackUrl, expiresIn }`, a pre-signed S3 GET URL.** Only callable if `hasAudio: true`. Streams the S3 object server-side (`VoiceRecordingService.get_audio_stream`) with `Content-Type` from the stored object metadata — a pre-signed URL's signature is its entire authorization, so returning one in JSON made it a copyable credential valid for anyone for its full TTL, session or not; this endpoint re-checks assigner/assignee on every request instead. Point an `<audio>` tag's `src` directly at this URL — cookies attach automatically for same-origin requests. Same pattern as Evidence (§5) and Broadcast image (§10).

```
Response 200: audio/webm bytes (or the object's stored Content-Type)
```

**Errors:** 401 · 403 · 404 (no audio stored) · 500

---

## 7. Labels

A single `ProjectLabel` table serves both main labels (set by assigner on task) and assignee personal labels (set by assignee on task). Each user sees only labels they created (`createdBy = req.userId`). Labels cannot be deleted while applied to any task (`onDelete: Restrict`).

### GET /labels/shared — assigner's label picker

Returns all labels created by the calling user. Used when the assigner sets or changes the main label on a task.

**Access:** `requireAuth`

```json
Response 200:
{ "data": [ { "id": "uuid", "name": "NAAC", "colorCode": "#6B7280", "createdAt": "..." } ] }
```

---

### GET /labels/mine — assignee's label picker

Returns all labels created by the calling user. Used when the assignee sets their personal label on a task.

**Access:** `requireAuth`

```json
Response 200:
{ "data": [ { "id": "uuid", "name": "urgent", "colorCode": "#6B7280", "createdAt": "..." } ] }
```

---

### POST /labels — create a label

**Access:** `requireAuth`. Label name must be unique per user (not per tenant).

```json
Request: { "name": "NAAC", "colorCode": "#6B7280" }
Response 201: { "data": { "id": "uuid", "name": "NAAC", "colorCode": "#6B7280" }, "message": "Label created" }
```

**Errors:** 400 (empty name · duplicate name for this user) · 401 · 500

---

### PATCH /labels/:id — rename a label

**Access:** Creator of the label only (`createdBy = req.userId`).

```json
Request: { "name": "NAAC Prep", "colorCode": "#3B82F6" }
Response 200: { "data": { "id": "uuid", "name": "NAAC Prep" }, "message": "Label updated" }
```

**Errors:** 400 (no fields provided · empty name · invalid `colorCode` format · duplicate name for this user) · 401 · 403 · 404 · 500

---

### DELETE /labels/:id

**Access:** Creator of the label only. **Fails if label is currently set as `mainLabelId` or `assigneeLabelId` on any task** — unset from the task first.

```json
Response 200: { "data": null, "message": "Label deleted" }
```

**Errors:** 400 (LABEL_IN_USE) · 401 · 403 · 404 · 500

---

## 9. Sticky Notes & Reminders

**A `StickyNote` with `dueAt` set IS the reminder** — there is no separate Reminder entity (W30 resolved). Notes with imminent/past `dueAt` float to the top in the UI with a red border.

### GET /sticky-notes

Returns all sticky notes for the calling user, sorted: pinned first → dueAt ascending (nulls last) → createdAt DESC.

**Access:** `requireAuth` — returns only `userId = me` rows.

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "text": "Prepare agenda for staff meeting",
      "dueAt": "2026-06-21T09:00:00Z",
      "isPinned": true,
      "promotedToTaskId": null,
      "createdAt": "2026-06-20T08:00:00Z",
      "updatedAt": "2026-06-20T08:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 5 }
}
```

---

### POST /sticky-notes

**Access:** `requireAuth`.

```json
Request:
{
  "text": "Prepare agenda for staff meeting",   // required
  "dueAt": "2026-06-21T09:00:00Z",             // optional — set to make it a reminder
  "isPinned": false                              // optional — default false
}

Response 201:
{ "data": { "id": "uuid", "text": "...", "dueAt": "...", "isPinned": false, "createdAt": "..." }, "message": "Sticky note created" }
```

---

### GET /sticky-notes/:id

**Access:** Owner only (`userId = me`); 404 if not found or not owned.

```json
Response 200:
{ "data": { "id": "uuid", "text": "...", "dueAt": "...", "isPinned": false, "promotedToTaskId": null, "createdAt": "...", "updatedAt": "..." } }
```

---

### PATCH /sticky-notes/:id

**Access:** Owner only (`userId = me`).

```json
Request (any subset):
{ "text": "Updated note", "dueAt": "2026-06-22T10:00:00Z", "isPinned": true }

Response 200:
{ "data": { "id": "uuid", "text": "...", "dueAt": "...", "isPinned": true, "updatedAt": "..." } }
```

---

### DELETE /sticky-notes/:id

**Access:** Owner only.

```json
Response 200: { "data": null, "message": "Sticky note deleted" }
```

---

### POST /sticky-notes/:id/promote — promote to task

Creates a new Task from the sticky note's text (as title). Sets `StickyNote.promotedToTaskId` to the new task ID. The original sticky note is retained (not deleted).

**Access:** Owner only.

```json
Request:
{
  "assigneeId": "uuid",               // required — see note below
  "dueDate": "2026-06-30T17:00:00Z"  // optional — leave blank to save as Draft
}

Response 201:
{
  "data": {
    "taskId": "uuid",
    "status": "OPEN"    // or "DRAFT" if dueDate missing
  },
  "message": "Promoted to task"
}
```

> **Corrected 2026-07-11:** this section previously documented `assigneeId` as optional ("leave blank to save as Draft"), matching W-C3's general rule that Drafts can omit any field. In practice `Task.assigneeId` is a required, non-nullable column (`schema.prisma`), and `createTask.service.ts` already enforces it as required for every task, not just at the Draft→Open transition — a pre-existing gap between the resolved PRD rule and the implementation, not introduced here. `promoteStickyNote.service.ts` follows that same existing constraint for consistency rather than diverging from it. See `open-questions-web-v1.md` for the flagged contradiction.

**Errors:** 400 (already promoted — `promotedToTaskId` not null) · 401 · 403 · 500

---

## 10. Broadcast Notices

**Implementation status:** CRUD + publish + list + ack + ack-count + both image endpoints below are all built (`apps/broadcasts/`, 2026-08-07). Server-side HTML re-sanitization uses `bleach`. The W110 "Entire Institution" stop-gap and the `sent`-view `audienceSize`/`from`/`to`/`updatedAt` additions were both built 2026-08-23. The "notify newly-added recipients on audience-widening edit" rule was built ahead of when it was added to this doc, 2026-08-07.

### Permissions recap:
- `canBroadcast` on `TenantMembership` gates creation — 403 if false.
- `audienceDeptIds[]` + `audienceRoleLevels[]` — both may be empty at publish (W110, below). Empty `audienceDeptIds[]` means "not department-restricted" (all departments); empty `audienceRoleLevels[]` means "not role-restricted" (all role levels). `audienceRoleLevels` is a `BroadcastNoticeAudienceRoleLevel` join table (matching upstream's 2026-07-30 change) — same shape as `audienceDeptIds`'s `BroadcastNoticeAudienceDept` join table (2026-07-17) — a notice can target several departments and several role levels at once (e.g. Computer Science + Civil Engineering, HoD + Faculty only).
- **W110 — "Entire Institution" (built here 2026-08-23, matching upstream's 2026-07-25 stop-gap — still pending client/product-owner confirmation upstream, `open-questions-web-v1.md` §23):** publishing with **both** `audienceDeptIds`/`audienceRoleLevels` empty is a valid, explicit "Entire Institution" scope — reaches every tenant member, including anyone with no department assigned. Previously there was no way to reach 100% of a tenant (one Role Level misses other roles; every Department excludes members with no department). `BroadcastService.publish` no longer rejects this combination; `resolve_audience_member_user_ids`/`_caller_matches_audience` already treated "no restriction on this dimension" as "everyone matches," so the publish-time gate was the only place still blocking it. Revert-worthy if the client says mandatory-scope should stand.
- Broadcasts live for **exactly 1 day** — `expiresAt = publishedAt + 24 hours` (set by server, not client).
- Stored as `messageJson` (TipTap AST — editor source) + `messageHtml` (sanitized HTML — feed rendering).
- One image attachment maximum.

### Image upload (broadcast) — built 2026-08-07, single-object-per-entity (mirrors profile-picture, not task evidence)

No separate attachment id and no filename in the S3 key — since exactly one image is allowed per
broadcast (never multiple), the key is derived purely from `(tenantId, broadcastId)`, same shape
as the profile-picture upload. Original filename is not preserved or shown anywhere client-side.

```
S3 paths:
  Upload →   bolo-broadcast/unconfirmed/{tenantId}/{broadcastId}
  Confirmed → bolo-broadcast/{tenantId}/{broadcastId}
```

**Image serving (bolo-backend-django, built 2026-08-07 — backend-streamed from day one, matching upstream's own later 2026-07-25 correction):** `imageUrl` in the feed is an **app-relative path** to `GET /broadcast-notices/:id/image` (below), not a pre-signed or raw S3 URL — the endpoint re-checks sender-or-audience-membership on every request rather than baking access into a copyable, time-limited signed URL. This project never built the earlier "25h pre-signed URL persisted on `imageUrl`" design upstream shipped and later walked back.

### POST /upload/broadcast-image-presign — request pre-signed image upload URL

**Access:** `requireAuth` + `canBroadcast = true` + must be sender of the broadcast. The broadcast must be **editable** — `DRAFT`, or `PUBLISHED` and not yet expired — 400 `CANNOT_EDIT_EXPIRED` otherwise (built here to match upstream's 2026-07-26 widening).

```json
Request:
{
  "broadcastId": "uuid",
  "filename": "notice-banner.jpg",  // used only for contentType inference client-side; not stored
  "contentType": "image/jpeg",      // image/jpeg | image/png | image/heic only — no PDF/DOC (PRD §7)
  "fileSize": 512000                // 5MB placeholder cap (no dedicated PRD limit, same as profile pics)
}

Response 200:
{
  "data": {
    "uploadUrl": "https://s3.ap-south-1.amazonaws.com/bolo-broadcast/unconfirmed/...",
    "expiresIn": 900
  }
}
```

---

### POST /broadcast-notices/:id/image — confirm image after S3 upload

No request body — the confirmed key is derived from `(tenantId, broadcastId)` alone. Server does:
HeadObject (verify the PUT landed) → CopyObject → DeleteObject → UPDATE `imageUrl` with the
confirmed S3 key (no pre-signed URL is ever generated — see streaming note above).

```json
Response 200:
{ "data": { "hasImage": true }, "message": "Image attached" }
```

**Errors:** 400 (`CANNOT_EDIT_EXPIRED`, or `UPLOAD_NOT_CONFIRMED` if the S3 PUT never landed) · 401 · 403 (`FORBIDDEN` — not the sender) · 404 · 500

---

### GET /broadcast-notices?view=received|sent — notices visible to me / sent by me

```
GET /api/v1/broadcast-notices?view=received&page=1&limit=20   (default — same as omitting ?view entirely)
GET /api/v1/broadcast-notices?view=sent&page=1&limit=20
```

| Param | Required | Values | Default |
|---|---|---|---|
| `view` | no | `received` \| `sent` | `received` |
| `from` | no | ISO date/datetime — `view=sent` only | — |
| `to` | no | ISO date/datetime — `view=sent` only | — |
| `page` | no | integer ≥ 1 | `1` |
| `limit` | no | 1–100 | `20` |

**View → filter logic** (added 2026-07-14, W97 — see `open-questions-web-v1.md` §21):
- `received` (default) — active (`PUBLISHED`, non-expired) broadcasts where the audience matches the calling user's own dept + roleLevel. **A sender does NOT automatically see their own broadcast here** unless they also happen to match their own audience scope (e.g. a Dean broadcasting to HoDs never sees it in `received`, since the Dean is `TOP` not `MID`).
- `sent` — everything `senderId = me` created, the sender's own management view — this project **excludes `DRAFT`** here (own correction, matches upstream's later 2026-07-26 "temporarily excludes DRAFT" change for the same reason: no resume/publish-a-draft action exists yet). Still includes expired `PUBLISHED` rows. Rows omit `hasAcknowledged` (not meaningful for your own sent item) but include `ackCount`. **Not yet built here:** `audienceSize` (a live count of members currently matching that row's audience scope, deliberately live not a publish-time snapshot) and optional `from`/`to` narrowing by `createdAt` — see CLAUDE.md.

**Access:** `requireAuth`. Invalid `view` value, `from`/`to` not a valid date, or `page`/`limit` out of range → 400 `VALIDATION_ERROR`.

**Pagination added 2026-07-14** — the endpoint previously ignored `page`/`limit` entirely and always returned every matching row unpaginated (the Postman collection had sent these params since before this feature existed, silently ignored). Now real, matching `GET /notifications`' `page`/`limit` convention exactly (`PaginatedResponse<T>` shape, max `limit` 100).

```json
Response 200 (view=received):
{
  "data": [
    {
      "id": "uuid",
      "senderId": "uuid",
      "senderName": "Dean Sethi",
      "messageHtml": "<p>All faculty...</p>",
      "audienceDeptIds": ["uuid"],
      "audienceDeptNames": ["CSE"],
      "audienceRoleLevels": ["EXECUTOR"],
      "requiresAcknowledgement": true,
      "ackCount": 12,
      "hasAcknowledged": false,         // true if calling user has acknowledged
      "imageUrl": "/broadcast-notices/uuid/image",
      "status": "PUBLISHED",
      "expiresAt": "2026-06-21T10:00:00Z",
      "createdAt": "2026-06-20T10:00:00Z",
      "updatedAt": "2026-06-20T10:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 12 }
}
```

`view=sent` returns the same shape minus `hasAcknowledged`, plus `audienceSize` (below) — this project excludes `DRAFT` there (see above), so `expiresAt` is always set.

**`updatedAt`** (upstream added 2026-07-26, built here 2026-08-23) — lets a recipient tell whether a notice was edited after it originally went out. Not a simple `updatedAt !== createdAt` check client-side: `publish()` itself bumps `updatedAt` too (DRAFT → PUBLISHED is itself a write), so that alone false-positives on every freshly-published notice. The correct check is `updatedAt` meaningfully later than `expiresAt` minus 24h (the original publish instant, with clock-jitter buffer).

**`audienceSize`** (built here 2026-08-23, `view=sent` only) — a **live** count of members currently matching that row's audience scope, not a publish-time snapshot: a member who joins the tenant after publish can still see and acknowledge an active notice, so the denominator has to be able to grow the same way (`BroadcastService.attach_audience_size`, called on the paginated page after fetching).

---

### POST /broadcast-notices — create a draft

**Access:** `requireAuth` + `canBroadcast = true` on membership.

```json
Request:
{
  "messageJson": { /* TipTap JSON AST */ },   // required
  "messageHtml": "<p>All faculty...</p>",     // required — sanitized by client before sending; server re-sanitizes
  "audienceDeptIds": ["uuid"],                // both may be empty at publish -- see W110 above; optional while DRAFT
  "audienceRoleLevels": ["EXECUTOR"],        // ditto
  "requiresAcknowledgement": true            // optional — default false
  // image is attached separately via POST /broadcast-notices/:id/image after S3 upload
}

Response 201:
{
  "data": {
    "id": "uuid",
    "status": "DRAFT",
    "senderId": "uuid",
    "createdAt": "2026-06-20T10:00:00Z"
  },
  "message": "Draft saved"
}
```

**Errors:** 400 (VALIDATION_ERROR — missing `messageJson`/`messageHtml`, text over the char limit, or an `audienceRoleLevels` entry outside `TOP`/`MID`/`EXECUTOR`; `INVALID_DEPARTMENT` — `audienceDeptIds` contains a department that doesn't exist in the caller's tenant, batch-checked via `_validate_dept_ids`) · 401 · 403 (BROADCAST_NOT_PERMITTED) · 500

---

### POST /broadcast-notices/:id/publish — publish a draft

Transitions `DRAFT → PUBLISHED`. Server does in order:
1. No audience validation gate — both `audienceDeptIds`/`audienceRoleLevels` may be empty ("Entire Institution", W110 above)
2. Sets `expiresAt = now + 24 hours`
3. Enqueues fan-out notification job (async — not inline)

**Access:** Sender only + `canBroadcast = true`.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "status": "PUBLISHED",
    "expiresAt": "2026-06-21T10:00:00Z",
    "imageUrl": "/broadcast-notices/uuid/image"
  },
  "message": "Broadcast published"
}
```

**Errors:** 401 · 403 · 404 · 500 (no `DRAFT_MISSING_FIELDS` — see the "Entire Institution" note in the Permissions recap above, W110)

---

### PATCH /broadcast-notices/:id — edit (sender only)

A `DRAFT` is always editable. A `PUBLISHED` notice is editable while still inside its 24h `expiresAt` window — 400 `CANNOT_EDIT_EXPIRED` once expired. Editing never changes `expiresAt` itself.

**Notifies newly-added audience members (built here, matching upstream's 2026-07-30 change):** editing an already-`PUBLISHED` notice's `audienceDeptIds`/`audienceRoleLevels` fires `BROADCAST_POSTED` to whoever is newly in scope as a result of the edit (set difference of old vs. new audience resolution). Members already matching before the edit are not re-notified; members removed by the edit get no notification.

```json
Request (any subset):
{
  "messageJson": { /* updated TipTap AST */ },
  "messageHtml": "<p>Updated text</p>",
  "audienceDeptIds": ["uuid"],
  "audienceRoleLevels": ["MID"],
  "requiresAcknowledgement": false,
  "imageUrl": null
}

Response 200:
{ "data": { "id": "uuid", "status": "DRAFT" }, "message": "Broadcast updated" }
```

**Errors:** 400 (`CANNOT_EDIT_EXPIRED` · `INVALID_DEPARTMENT` if `audienceDeptIds` contains a department that doesn't exist in the caller's tenant · `VALIDATION_ERROR` if `audienceRoleLevels` contains an invalid role level) · 401 · 403 · 404 · 500

---

### DELETE /broadcast-notices/:id

**Access:** Sender only.

```json
Response 200: { "data": null, "message": "Broadcast deleted" }
```

---

### POST /broadcast-notices/:id/ack — acknowledge a broadcast

Inserts a `BroadcastAcknowledgement` row. Composite PK `(broadcastId, userId)` prevents duplicates at DB level.

**Access:** `requireAuth`. Broadcast must be `PUBLISHED` and not expired. `requiresAcknowledgement` must be true. **Caller must be in the broadcast's audience** (own `dept`+`roleLevel` match `audienceDeptIds`/`audienceRoleLevels`, same match rule as `GET /broadcast-notices`) — 403 otherwise. This includes the sender: they can only ack their own broadcast if they'd also see it in their own feed.

```json
Response 200:
{ "data": { "ackCount": 13 }, "message": "Acknowledged" }
```

**Errors:** 400 (not a requiring-ack broadcast · expired) · 401 · 403 (`NOT_IN_AUDIENCE`) · 404 · 409 (ALREADY_ACKNOWLEDGED) · 500

---

### GET /broadcast-notices/:id/image — fetch the broadcast image content

**Access:** `requireAuth`. Sender may always fetch their own broadcast's image (any status). Anyone else must be in the audience: `status = PUBLISHED`, not expired, dept/roleLevel match — same rule as `POST /broadcast-notices/:id/ack`. Streams the S3 object server-side, `Content-Type` from the stored object metadata — no presigning.

**Errors:** 401 · 403 (`NOT_IN_AUDIENCE`) · 404 (broadcast not found, or has no image) · 500

---

### GET /broadcast-notices/:id/ack-count — sender reads count

**Access:** Sender only.

```json
Response 200:
{ "data": { "broadcastId": "uuid", "ackCount": 13 } }
```

**Errors:** 401 · 403 · 404 · 500

---

## 11. Notifications

All types write an in-app `Notification` row; client polls on a configurable interval (no WebSocket/SSE in V1). System-generated only — no user-created notifications. **Corrected 2026-07-03:** reminder/due-date types also send email (via the existing AWS SES setup used for OTP, transport decided 2026-07-18) — see Channel column below. Previously documented as in-app only across the board; that was wrong for these 2 types.

### Notification types

**Corrected 2026-07-03 to match `schema.prisma`'s `NotificationType` enum exactly** — this table previously listed `TASK_COMPLETED_DONE_A`/`TASK_COMPLETED_DONE_D`/`COMMENT_ADDED`/`EVIDENCE_ATTACHED`, none of which exist in the schema, and omitted several types that do. Schema is ground truth; this table was stale.

| Type | Trigger | Channel |
|---|---|---|
| `TASK_ASSIGNED` | Draft→Open; fires to assignee | In-app |
| `TASK_ACCEPTED` | Assignee accepts; fires to assigner | In-app |
| `TASK_REASSIGNED` | Assigner changes assigneeId; fires to both old and new assignee | In-app |
| `TASK_EDITED` | Assigner patches task; fires to assignee | In-app |
| `TASK_COMMENTED` | Comment posted; fires to other party | In-app |
| `TASK_DONE_A` | Assignee marks done-a; fires to assigner | In-app |
| `TASK_DONE_D` | Assigner marks done-d; fires to assignee | In-app |
| `TASK_CANCELLED` | Assigner cancels; fires to assignee | In-app |
| `TASK_REMINDER` | Assigner sends manual reminder (`POST /tasks/:id/remind`); fires to assignee | **In-app + Email** |
| `TASK_DUE_TODAY` | EventBridge: task due today; fires to assignee (one-shot) | **In-app + Email** |
| `TASK_DUE_TOMORROW` | EventBridge: task due tomorrow; fires to assignee (one-shot) | **In-app + Email** |
| `TASK_OVERDUE` | EventBridge: task became overdue; fires to assignee (one-shot) | **In-app + Email** |
| `SUBTASK_CREATED` | Subtask created; fires to assigner of parent | In-app |
| `SUBTASK_EDITED` | Subtask patched; fires to subtask assignee | In-app |
| `SUBTASK_DONE_A` | Subtask assignee marks done-a; fires to assigner | In-app |
| `SUBTASK_DONE_D` | Assigner marks subtask done-d; fires to assignee | In-app |
| `BROADCAST_POSTED` | Broadcast published; fires to audience | In-app |
| `REMINDER_FIRED` | EventBridge: StickyNote.dueAt reached; fires once to note owner (one-shot) | In-app |
| `AI_NUDGE_FOLLOWUP` | Sweep (every 6h, no office-hours gate). **Scope narrowed 2026-07-13 (client-directed):** 2 conditions only, both **assignee-only** — accepted-no-progress, and unanswered-comment (only when the assignee owes the reply; if the assignee posted last and is waiting on the assigner, no nudge fires — the assigner is out of scope entirely). The 3 conditions requiring Accept/Mark Complete actions were dropped, not just their buttons. No cap, no escalation — skip counter tracked for visibility + rotation only. | In-app |
| `AI_NUDGE_DUE_PROXIMITY` | Sweep (every 3h, no office-hours gate). **Task only** (Subtask/StickyNote/Broadcast dropped 2026-07-13 — a Subtask is no longer distinguished from Task). Already-accepted + due-today-or-overdue only; cap 3 due-today / 1 overdue; escalates once to assigner if cap reached and still not `DONE_A`. **No blocking** — Skip is never disabled at cap, panel is never forced closed; cap only drives the real one-time escalation, not any UI restriction. | In-app only, **except** the **one-time** escalation-to-assigner moment → **in-app + email**, never repeated (`NudgeSkipCounter.escalatedAt` guard) |

`AI_NUDGE_PERIODIC` was retired 2026-07-06 — merged into `AI_NUDGE_FOLLOWUP` once Follow-up gained per-condition action buttons and lost its own cap, leaving no structural difference between the two. Removed from the `NotificationType` enum entirely (not just deprecated) as of the Phase 1 backend build.

**AI Nudge vs. general Notification panel:** both are `Notification` rows, but AI Nudge is served by its own dedicated `/api/v1/nudges` endpoint (below) — not `GET /notifications?type=...` — because the nudge feed needs richer, freshly-computed fields (`actions[]`, `skipCount`, `skipCap`, `escalation`) that don't apply to the general panel. The AI Nudge panel auto-surfaces itself (system-generated, no bell/manual trigger — see `docs/ux/design-system.md`); the general Notification panel (`feature/notification-panel`, bolo-web — built) is user-opened via the bell icon and shows all types in the table above via `GET /notifications`.

---

### GET /nudges — my current AI Nudge feed

**Access:** `requireAuth` — only the caller's own pending nudges.

```
GET /api/v1/nudges
```

No query params. **Scope narrowed 2026-07-13:** returns **at most 5 items total**, not everything eligible — Due-Proximity fills first (ordered by `Task.priority`, P1 highest), then Follow-up fills any remaining slots (also priority-ordered, tiebroken by oldest-`lastShownAt`-first for fair rotation across candidates that don't all fit). Deduped by `(entityId, type)` — if the sweep left multiple unread notifications for the same task+type behind, only the newest counts toward a slot; older duplicates are silently marked read.

**Every row is re-validated against current entity state on every call — never trusts what was true when the notification originally fired.** If the underlying condition no longer holds (e.g. the task was accepted through Task Detail instead of the nudge panel), the notification is auto-marked-read server-side and silently excluded from the response — it won't linger as a stale row.

```json
Response 200:
{
  "data": [
    {
      "id": "NTF00045",
      "nudgeType": "DUE_PROXIMITY",
      "entityType": "task",
      "entityId": "uuid",
      "title": "Submit IQAC audit report",
      "subtitle": "Due today",
      "actions": ["ADD_COMMENT", "OPEN_TASK"],
      "skipCount": 1,
      "skipCap": 3,
      "escalation": { "toName": "Dr. Kamal Sethi" },
      "createdAt": "2026-07-10T14:11:26.040Z"
    }
  ]
}
```

`entityType` is always `"task"` now (Subtask/StickyNote/Broadcast dropped 2026-07-13 — a Subtask is no longer distinguished from Task at all). `skipCap: null` = uncapped (Follow-up) — `skipCount` still tracked, never enforced. `escalation` only ever present for Due-Proximity. `actions` is `["ADD_COMMENT"]` for Follow-up or `["ADD_COMMENT", "OPEN_TASK"]` for Due-Proximity — `ACCEPT_TASK`/`MARK_COMPLETE`/`VIEW_BROADCAST` are no longer emitted by anything.

---

### POST /nudges/:id/skip — skip one nudge

**Access:** `requireAuth` — only the caller's own nudge.

Increments the caller's skip counter for that `(entityType, entityId, nudgeKind)` and marks the notification read (resolved until the next sweep cycle re-fires it, if still applicable). **Always succeeds now (2026-07-13) — no cap rejection.** Skip is never blocked in the UI even past the Due-Proximity cap; the cap still drives the one-time escalation server-side (see `AI_NUDGE_DUE_PROXIMITY` above), it just no longer restricts what the user can click.

```json
Response 200: { "skipCount": 2 }
```

---

### POST /nudges/skip-all — bulk-skip everything currently shown

**Access:** `requireAuth` — only the caller's own feed.

**No last-chance rejection (2026-07-13)** — skips everything currently in the caller's feed in one pass, always succeeds. The earlier "reject the whole batch if anything is at last-chance" rule was tied to the blocking-panel behavior, which was removed along with it.

```json
Response 200: { "skippedCount": 4 }
```

---

### GET /notifications — list my notifications (general panel)

**Access:** `requireAuth` — only `recipientId = me`.

```
GET /api/v1/notifications?isRead=false&page=1&limit=20&type=TASK_ASSIGNED,BROADCAST_POSTED
```

**`type` param:** optional, comma-separated list of `NotificationType` values, for callers that want a subset (e.g. AI Nudge types are also valid here for read/mark-read purposes, but the nudge panel itself uses `GET /nudges` instead — see above).

**`entityType` is always lowercase** (`"task"` | `"subtask"` | `"broadcast"` | `"sticky_note"`) — this example previously showed uppercase (`"TASK"`), which was wrong and caused a real bug when a frontend branch was built against it (fixed 2026-07-05).

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "type": "TASK_ASSIGNED",
      "entityType": "task",
      "entityId": "uuid",
      "message": "Dr. Sethi assigned you a task",
      "actorName": "Dr. Sethi",
      "entityTitle": "Submit NAAC report",
      "entityContext": "IQAC",
      "isRead": false,
      "readAt": null,
      "createdAt": "2026-06-20T10:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 7 }
}
```

**`actorName`/`entityTitle`/`entityContext` (added 2026-07-05):** optional, populated only where the notification-creating call site has the data on hand — the general Notification panel (`feature/notification-panel`, bolo-web) renders them for a richer layout but falls back to plain `message` text when absent, so this is safe to consume defensively. **Coverage as of the Phase 1 backend build:** wired into `createTask`, `updateTask` (covers `TASK_ASSIGNED` Draft→Open promotion, `TASK_REASSIGNED`, `TASK_EDITED`/`SUBTASK_EDITED`), `acceptTask`, `cancelTask`, `createComment` (`TASK_COMMENTED`), `createSubtask`, `markDoneA`, `markDoneD`, and `remindTask` — 9 task services in total, plus both `AI_NUDGE_*` types. Broadcast due-proximity nudges don't set `entityTitle` (no natural short title for a broadcast message — the panel falls back to `message` text).

---

### PATCH /notifications/:id/read — mark as read

**Access:** `recipientId = me`.

```json
Response 200:
{ "data": { "id": "uuid", "isRead": true, "readAt": "2026-06-20T11:00:00Z" } }
```

---

### GET /notifications/unread-count — badge count

Used by the top bar notification icon. Cheap COUNT query — no pagination.

**Access:** `requireAuth`.

```json
Response 200:
{ "success": true, "data": { "count": 7 }, "message": "OK" }
```

---

### POST /notifications/mark-all-read

Marks all unread notifications for the calling user as read.

**Access:** `requireAuth`.

```json
Response 200:
{ "success": true, "data": { "updatedCount": 7 }, "message": "All notifications marked as read" }
```

---

### GET /nudges, POST /nudges/:id/skip, POST /nudges/skip-all — AI Nudge feed (2026-07-06 redesign)

**Added 2026-07-06, merged to `bolo-backend` `feature/ai-nudge` 2026-07-09.** Supersedes the "fetch `/notifications?type=AI_NUDGE_*` and split client-side into Screen A/B" approach described above (rows 1293-1295) — that plan predates this dedicated endpoint. The AI Nudge UI (`bolo-web`, one-at-a-time "Today's Check-in" carousel, no Figma reference — W79) is built against this feed, not `/notifications` directly.

**Access:** all three `requireAuth`, scoped to `recipientId = me`.

```
GET /api/v1/nudges
```
Re-validates each pending `AI_NUDGE_FOLLOWUP`/`AI_NUDGE_DUE_PROXIMITY` notification against **current** state (never trusts what was true when it originally fired) — auto-marks-read anything that no longer qualifies.

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "nudgeType": "FOLLOWUP",
      "entityType": "task",
      "entityId": "uuid",
      "title": "AQAR Draft Preparation",
      "subtitle": "accepted but no progress update since",
      "actions": ["ADD_COMMENT"],
      "skipCount": 0,
      "skipCap": null,
      "createdAt": "2026-07-09T10:00:00Z"
    }
  ]
}
```
- `entityType`: `"task" | "subtask" | "sticky_note" | "broadcast"`.
- `actions`: drives which buttons the client renders — `ACCEPT_TASK`, `ADD_COMMENT`, `MARK_COMPLETE`, `OPEN_TASK`, `VIEW_BROADCAST`. **Resolving a nudge is never a dedicated call** — the client performs the real underlying action via the existing Task/Comment endpoints (§ this doc), and the item naturally drops off the next `GET /nudges` poll.
- `skipCap: null` = uncapped (all Follow-up conditions, StickyNote due-proximity). Capped types: Task/Subtask due-proximity (3 due-today / 1 overdue), Broadcast due-proximity (3).
- `escalation: { toName }` present only for capped Task/Subtask items with an assigner.

```
POST /api/v1/nudges/:id/skip
```
**Reverses W77's original resolution** (`open-questions-web-v1.md`, see W85) — Skip is a real user action again, not purely a backend-sweep side effect. Increments the nudge's skip counter. Returns `409 SKIP_CAP_REACHED` if `skipCount >= skipCap - 1` already (client must hide the Skip button at that same threshold — see `isLastChanceNudge` in `bolo-web/src/types/nudge.ts`).
```json
Response 200: { "data": { "skipCount": 2 } }
```

```
POST /api/v1/nudges/skip-all
```
Skips every currently-pending nudge for the caller in one call. Rejects with `409 LAST_CHANCE_BLOCKING` if anything is at last-chance (mirrors the same client-side disable rule). **Not currently wired in `bolo-web`** — the one-at-a-time carousel UI has no bulk "Skip All" affordance (descoped 2026-07-11, see changelog.md).
```json
Response 200: { "data": { "skippedCount": 4 } }
```

---

## 12. Audit Log

Immutable append-only log. No UPDATE or DELETE on `audit_logs`. Used for compliance and traceability.

### GET /audit-log

**Access:** `requireOrgRole(['TOP'])` OR `assignerId` of the entity (checked in service). Scoped to `tenantId` from JWT. `entityType=TENANT`/`DOCUMENT` rows (platform-admin actions; evidence upload/delete, added 2026-07-18) are TOP-only for now — neither a Tenant nor an Evidence row has assigner resolution wired (`findEntityAssignerId()` only resolves TASK).

```
GET /api/v1/audit-log?entityType=TASK&entityId=uuid&page=1&limit=50
```

| Param | Required | Values |
|---|---|---|
| `entityType` | no | `TASK` \| `BROADCAST` \| `USER` \| `STICKY_NOTE` \| `PROJECT_LABEL` \| `TENANT` \| `DOCUMENT` |
| `entityId` | no | UUID |
| `actorId` | no | UUID |
| `from` | no | ISO 8601 date |
| `to` | no | ISO 8601 date |

```json
Response 200:
{
  "data": [
    {
      "id": "uuid",
      "actorId": "uuid",
      "actorName": "Dr. Kamal Sethi",
      "actorType": "USER",
      "action": "TASK_STATUS_CHANGED",
      "entityType": "TASK",
      "entityId": "uuid",
      "before": { "status": "IN_PROGRESS" },
      "after": { "status": "DONE_D" },
      "createdAt": "2026-06-20T14:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 50, "total": 23 }
}
```

`actorType` is `USER` \| `SYSTEM` \| `PLATFORM_ADMIN` (added 2026-07-17). For `PLATFORM_ADMIN` rows, `actorId`/`actorName` are always `null` — a `PlatformAdmin` isn't a `User` row, so there's no `AuditLog.actorId` FK target for one.

**Errors:** 401 · 403 · 500

---

## 13. Search

> **Rewritten 2026-08-03 sync — supersedes the previous 2026-07-23 revision of this section.** That revision (a single `GET /search` endpoint, described in `docs/api/global-search-ai-contract.md`) was itself already superseded in the original repo's actual code by **2026-08-01** (commit splitting Global Search into two paginated endpoints), but the upstream **doc** files (`bolo-backend`'s `docs/api/api-spec.md` and `global-search-ai-contract.md`) were never updated to match — they still describe the pre-split single-endpoint shape as of this sync. The contract below was verified directly against `bolo-backend`'s current source (`src/routes/search.routes.ts`, `src/controllers/search/{searchTasks,searchStickies}.controller.ts`, `src/services/search/globalSearch.service.ts`, `src/repositories/SearchRepository.ts`, `src/search/searchClassify.ts`), not against the (stale) upstream doc prose. Flag this drift back to whoever maintains `bolo-backend`'s docs — their own contract docs are behind their own code.

Scoped to exactly **two** result types — Task/Subtask and Sticky Note — not "every entity the user can access." A person's name in the query is a match field (surfaces tasks where that person is assigner/assignee), never a third result type. Powered by PostgreSQL + a standalone AI query-understanding layer (OpenAI `gpt-4o-mini`), not OpenSearch — see `docs/api/global-search-ai-contract.md` for the full design rationale.

### GET /search/tasks

**Access:** `requireAuth` — scoped to `tenantId` + (`assignerId = userId` OR `assigneeId = userId`), same visibility as the task list views. `Draft`/`Cancelled`/`Done_D` (archived) tasks **are** included by design — unlike the default Assigned/Delegated views, search does not hide them.

```
GET /api/v1/search/tasks?q=NAAC&source=typed&page=1&limit=10
```

| Param | Required | Values |
|---|---|---|
| `q` | yes | search string, 3–100 chars |
| `source` | no | `typed` \| `voice` — default `typed`; lets the AI layer apply voice-specific correction (e.g. transliterate a Devanagari mis-transcription back to Latin script before matching) |
| `page` | no | positive int, default 1 |
| `limit` | no | 1–50, default 10 |

```json
Response 200:
{
  "query": "NAAC",
  "interpretedQuery": "corrected term or null",
  "entityScope": "task",
  "data": [
    {
      "id": "uuid",
      "title": "Submit NAAC self-study report",
      "status": "IN_PROGRESS",
      "priority": "P2",
      "dueDate": "2026-06-30T17:00:00Z",
      "parentTaskId": null,
      "assigneeId": "uuid",
      "assigneeName": "Prof. Asha Nair",
      "assignerId": "uuid",
      "assignerName": "Dr. Kamal Sethi",
      "mainLabelId": "uuid",
      "mainLabelName": "NAAC Cycle 4",
      "assigneeLabelId": null,
      "assigneeLabelName": null,
      "latestComment": null
    }
  ],
  "pagination": { "page": 1, "limit": 10, "total": 1 }
}
```

- `interpretedQuery` is populated only when the AI/fuzzy layer meaningfully corrected the raw query (a typo, a mis-transcribed name); `null` when the raw query already matched. Powers a "Showing results for X" hint client-side.
- `assigneeLabelName` (private label) is privacy-scoped — only ever populated when the caller **is** that task's assignee, `null` otherwise; never leaks to the assigner.
- `latestComment` is `{id, authorId, authorName, text, isEdited, createdAt}` or `null` — the comment text itself is not searched (out of scope, see below), only surfaced on an already-matched row.

**Errors:** 400 `VALIDATION_ERROR` (`q` under 3 or over 100 chars, or missing; `limit` over 50) · 401 · 500

### GET /search/stickies

**Access:** `requireAuth` — scoped to `userId = caller` only. Strictly private, no tenant join.

```
GET /api/v1/search/stickies?q=agenda&source=typed&page=1&limit=10
```

Same query params as `/search/tasks`.

```json
Response 200:
{
  "query": "agenda",
  "interpretedQuery": null,
  "entityScope": "sticky",
  "data": [
    { "id": "uuid", "text": "Prepare NAAC agenda for staff meeting", "dueAt": "2026-06-21T09:00:00Z", "isPinned": false, "createdAt": "2026-06-18T10:00:00Z", "colorCode": "#FEF3C7" }
  ],
  "pagination": { "page": 1, "limit": 10, "total": 1 }
}
```

**Errors:** same as `/search/tasks`.

**How it works:** both endpoints run the query through a standalone AI module (`bolo-backend/src/search/searchClassify.ts` — deliberately independent of the voice-command classifier in `voice/intent.js`, so nothing here can regress that flow), cached per `(query, source, userId, tenantId)` so both endpoints agree on `interpretedQuery`/`entityScope` regardless of which is called first. It extracts typo-corrected keywords, resolves any person name against the real tenant roster (never invents one — ties widen to an OR across every tied candidate's **id**, never guessed), detects `status`/`priority`/`due` filters, and narrows to task-only or sticky-only if the query implies it. A deterministic Levenshtein-distance fallback catches name/label mis-hearings the LLM doesn't reliably self-correct. If the AI call fails or is unavailable, search falls back to a raw keyword match rather than erroring. Pagination is ordered with an `id` tiebreaker on top of the primary/secondary sort — load-bearing for stable pagination when rows tie on timestamp.

**Confirmed out of scope for V1:** `Comment.text` (as search-match text, not display), `Evidence.fileName`, `VoiceRecording.rawTranscript` — each has its own visibility rules to get right; deferred as a dedicated follow-up if ever needed, not silently expanded.

**Navigation on click (frontend):** Task/Subtask result → task detail view (a Subtask uses its own id — it's already a fully addressable Task row, no parent/highlight needed). Sticky result → Sticky Wall.

---

## 14. Voice AI

The client-provided Voice AI SDK handles transcription and intent extraction. Our backend receives the structured output and routes it to the correct REST endpoint.

### POST /voice/dispatch — route SDK intent to action

**Access:** `requireAuth`.

```json
Request:
{
  "intent": "CREATE_TASK",
  "entityType": "TASK",
  "operation": "CREATE",
  "jsonBody": {
    "title": "Submit NAAC report by month end",
    "assigneeId": "uuid",
    "dueDate": "2026-06-30T17:00:00Z",
    "priority": "P1"
  },
  "confirmed": true     // false = preview only (validate + return draft, don't persist)
}
```

**Dispatcher logic:** Maps `(entityType, operation)` → the corresponding REST endpoint and calls it internally. Enforces the **same RBAC/ownership checks** as direct REST calls.

**Destructive operations** (DELETE, CANCEL, DONE_D) require `confirmed: true` explicitly — return 400 if `confirmed: false` for these.

```json
Response 200 (confirmed: true — persisted):
{
  "data": {
    "action": "CREATE_TASK",
    "result": { /* same shape as POST /tasks response data */ }
  },
  "message": "Task created via voice"
}

Response 200 (confirmed: false — preview):
{
  "data": {
    "action": "CREATE_TASK",
    "preview": { /* validated fields, not persisted */ },
    "missingFields": ["assigneeId"]
  },
  "message": "Preview only — not saved"
}
```

**Errors:** 400 (unknown intent · destructive without confirmed=true · validation) · 401 · 403 · 500

---

## 15. Users & Tenant

### GET /me

**Access:** `requireAuth`.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "name": "Prof. Asha Nair",
    "email": "asha@abc.edu",
    "phone": "+919876543210",
    "profilePicUrl": "/users/uuid/profile-picture/file",
    "preferredLang": "EN",
    "tenantId": "uuid",
    "tenantName": "ABC College",
    "roleLevel": "MID",
    "roleLabel": "HoD",
    "departmentId": "uuid",
    "departmentName": "CSE",
    "reportsToId": "uuid",
    "reportsToName": "Dean Sethi",
    "canBroadcast": false
  }
}
```

---

### PATCH /me

**Access:** `requireAuth`. User can only update their own name and preferred language.

```json
Request: { "name": "Prof. Asha M. Nair", "preferredLang": "HI" }
Response 200: { "data": { "name": "Prof. Asha M. Nair", "preferredLang": "HI" } }
```

---

### POST /upload/profile-picture-presign — get an S3 upload URL for the profile picture

**Access:** `requireAuth`. Always targets the caller's own profile picture (no `userId` in the body).

Same presign → confirm flow as Evidence (`docs/api/api-spec.md §5`), but a single object per user — a re-upload overwrites the existing picture at the same confirmed S3 key.

```json
Request: { "contentType": "image/jpeg", "fileSize": 204800 }
Response 200:
{
  "data": {
    "uploadUrl": "https://s3.../presigned-put-url",
    "expiresIn": 900
  }
}
```

- `contentType` must be one of `image/jpeg`, `image/png`, `image/heic`.
- `fileSize` must be ≤ 5MB (placeholder — no dedicated PRD limit for avatars; revisit alongside the evidence per-file limit, PRD v1.1 §3.5).
- Client `PUT`s the file directly to `uploadUrl`, then calls `PATCH /me/profile-picture` to confirm.

---

### PATCH /me/profile-picture — confirm the upload

**Access:** `requireAuth`. No request body — confirms whatever was just PUT to the caller's presigned URL.

```json
Response 200: { "data": { "profilePicUrl": "/users/uuid/profile-picture/file" } }
Response 400: { "error": "S3 upload not confirmed" }  // client never PUT the file, or it expired
```

---

### DELETE /me/profile-picture — remove the profile picture

**Access:** `requireAuth`. Optional field — deleting when none is set returns 404.

```json
Response 200: { "data": null }
Response 404: { "error": "No profile picture set" }
```

---

### GET /users/:userId/profile-picture — get any tenant member's profile picture by ID

**Access:** `requireAuth` — any tenant member (e.g. task cards, comments, org chart, where only a `userId` is known). `userId` must belong to the caller's tenant — 404 if not.

```json
Response 200: { "data": { "userId": "uuid", "profilePicUrl": "/users/uuid/profile-picture/file-or-null" } }
Response 404: { "error": "User not found: uuid" }
```

---

### GET /users/:userId/profile-picture/file — fetch the profile picture content

**Access:** `requireAuth`, tenant-scoped only — no further per-viewer restriction, since profile pictures are already visible tenant-wide in member lists, task cards, comments, and the org chart. Streams the S3 object server-side, `Content-Type` from the stored object metadata — **never a pre-signed URL**, same pattern as Evidence/Broadcast image (§5, §10). `getPresignedGetUrl`-style URL generation should have no remaining callers anywhere once this ships.

**Errors:** 401 · 404 (user not found, or no picture set) · 500

---

### GET /tenant

**Access:** `requireOrgRole(['TOP'])`.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "name": "ABC College",
    "vertical": "EDUCATION",
    "memberCount": 87,
    "deptCount": 6,
    "createdAt": "2026-01-15T00:00:00Z"
  }
}
```

---

### GET /tenant/members — list all tenant members

**Access:** `requireAuth` — any tenant member (used for assignee picker).

```
GET /api/v1/tenant/members?deptId=uuid&roleLevel=MID&page=1&limit=50
```

```json
Response 200:
{
  "data": [
    {
      "userId": "uuid",
      "name": "Prof. Asha Nair",
      "email": "asha@abc.edu",
      "profilePicUrl": "/users/uuid/profile-picture/file-or-null",
      "roleLevel": "MID",
      "roleLabel": "HoD",
      "departmentId": "uuid",
      "departmentName": "CSE",
      "canBroadcast": false,
      "joinedAt": "2026-06-01T10:00:00+05:30"
    }
  ],
  "pagination": { "page": 1, "limit": 50, "total": 87 }
}
```

**`profilePicUrl`/`joinedAt`**: `profilePicUrl` is the streaming path from `GET /users/:userId/profile-picture/file` above, or `null`. `joinedAt` is the member's `TenantMembership.createdAt`. **Note:** this specific endpoint, `GET /tenant/members`, is not built here — only the profile-picture endpoints it would reference are; see CLAUDE.md. There is also no tenant self-service member CRUD in this project at all (`GET /tenant/members`, `GET /tenant/roles`, invite/remove) — a separate, larger gap from profile picture, out of scope for that slice.

---

### GET /tenant/roles — distinct role levels + labels in use for this tenant

**Access:** `requireAuth` — any tenant member. Used by the Broadcast composer's Role Level audience picker, so it shows the tenant's actual vertical-specific labels (Dean/HoD/Faculty for Education, Director/HoD/Employees for CA/CS, or whatever custom `roleLabel` values were set on invite/import) instead of a hardcoded mapping. Distinct `(roleLevel, roleLabel)` pairs from `TenantMembership`, sorted `TOP → MID → EXECUTOR`; rows with no `roleLabel` set are excluded (nothing meaningful to show in a label picker).

```json
Response 200:
{
  "success": true,
  "message": "OK",
  "data": [
    { "roleLevel": "TOP", "roleLabel": "Dean" },
    { "roleLevel": "MID", "roleLabel": "HoD" },
    { "roleLevel": "EXECUTOR", "roleLabel": "Faculty" }
  ]
}
```

**Errors:** 401 · 500

---

### POST /tenant/members/invite — invite a new member

**Access:** `requireOrgRole(['TOP'])`.

```json
Request:
{
  "name": "Dr. Ravi Kumar",
  "email": "ravi@abc.edu",
  "phone": "+919876543211",
  "roleLevel": "EXECUTOR",
  "roleLabel": "Faculty",
  "departmentId": "uuid",
  "reportsToId": "uuid",
  "canBroadcast": false
}

Response 201:
{ "data": { "userId": "uuid", "email": "ravi@abc.edu" }, "message": "Invitation sent — user will log in via Email OTP" }
```

Creates `User` + `TenantMembership` rows. Sends welcome email with login instructions (Email OTP flow).

**Errors:** 400 (email already in tenant · invalid dept · validation) · 401 · 403 · 500

---

### DELETE /tenant/members/:userId — remove a member

**Access:** `requireOrgRole(['TOP'])`. Cannot remove self.

```json
Response 200: { "success": true, "data": null, "message": "Member removed" }
```

> Active tasks assigned to/by this member are **not** cancelled automatically — they remain and must be reassigned or closed manually.

---

### GET /tenant/org-chart — reporting tree

Returns the full reports-to hierarchy as a flat list with `reportsToId` links — client builds the tree. Used by the analytics board for dept/firm view.

**Access:** `requireOrgRole(['TOP', 'MID'])`.

```json
Response 200:
{
  "success": true,
  "data": [
    {
      "userId": "uuid",
      "name": "Dr. Kamal Sethi",
      "roleLabel": "Dean",
      "departmentName": "Administration",
      "reportsToId": null
    },
    {
      "userId": "uuid",
      "name": "Prof. Asha Nair",
      "roleLabel": "HoD",
      "departmentName": "CSE",
      "reportsToId": "uuid"
    }
  ]
}
```

---

### POST /tenant/onboard/import — bulk Excel import (admin only)

Initial tenant setup. Accepts either a multipart Excel file (`.xlsx`/`.xls`, **max 50 MB**) or a JSON body. Idempotent — safe to re-run (upserts by email). Processes every row — bad rows are skipped and logged, upload never aborts mid-file.

**Access:** `requireOrgRole(['TOP'])`.

**Required columns (Excel):** `name`, `email`, `roleLevel` (`TOP`/`MID`/`EXECUTOR`). Optional: `roleLabel`, `departmentName`, `phone`, `canBroadcast` (`true`/`yes`/`1`).

**Deduplication:** If the same email appears more than once in the file, earlier rows are skipped and logged in `errors[]` — last occurrence wins.

```json
Request (multipart/form-data):
  file: <.xlsx or .xls binary, max 50 MB>

OR Request (application/json):
Initial tenant setup. Accepts either an Excel file upload (`.xlsx`) or a JSON body. Idempotent — safe to re-run (upserts by email).

**Access:** `requireOrgRole(['TOP'])`.

**Excel columns:** `name*` · `email*` · `roleLevel*` · `roleLabel` · `departmentName` · `phone` · `canBroadcast` · `isHead`

**`isHead` field rules:**
- Accepts: `TRUE` / `true` / `yes` / `1` (anything else = `false`)
- Only valid when `roleLevel = MID` — other values reject the row
- Max **one** `isHead=true` per `departmentName` — if two rows share the same dept and both have `isHead=true`, the **entire import is rejected before any DB write**
- Requires `departmentName` to be set — row is rejected if `isHead=true` with no dept
- When `isHead=true`: service sets `Department.headUserId` to this user after creating/updating their membership

```json
Request (multipart/form-data — Excel upload):
  file: <.xlsx file>

Request (JSON body — alternative):
{
  "members": [
    {
      "name": "Dr. Kamal Sethi",
      "email": "dean@abc.edu",
      "phone": "+919876543210",
      "roleLabel": "Dean",
      "roleLevel": "TOP",
      "departmentName": "Administration",
      "canBroadcast": true,
      "isHead": false
    },
    {
      "name": "Prof. Shivam",
      "email": "shivam@abc.edu",
      "roleLabel": "HoD",
      "roleLevel": "MID",
      "departmentName": "Computer Science",
      "canBroadcast": false,
      "isHead": true
    }
  ]
}

Response 200:
{
  "success": true,
  "data": {
    "created": 45,
    "updated": 3,
    "skipped": 2,
    "errors": [
      { "email": "bad-email", "reason": "Invalid email format" },
      { "email": "john@acme.com", "reason": "Duplicate in file — earlier row skipped, last row used" }
    ]
  },
  "message": "Import complete"
}
```

**Skip reasons:** `Missing or invalid email` · `Invalid email format` · `Missing name` · `roleLevel must be TOP, MID, or EXECUTOR` · `Duplicate in file — earlier row skipped, last row used` · `Failed to resolve or create department`

**Errors:** 400 (wrong file type / empty file / no body) · 401 · 403 · 500
**Per-row errors** (row skipped, rest of import continues):
- Missing/invalid email · Missing name · Invalid `roleLevel`
- `isHead=true` with `roleLevel` ≠ `MID`
- `isHead=true` with no `departmentName`

**Whole-import rejection before any DB write** (400):
- Two or more rows with `isHead=true` for the same `departmentName`
- Malformed / unreadable Excel file

**Errors:** 400 (validation failure or duplicate isHead) · 401 · 403 · 500

---

## 16. Analytics

### GET /analytics/members — task effectiveness per member

**Access:** `requireOrgRole(['TOP', 'MID'])`. TOP sees all depts; MID sees own dept only (service checks).

```
GET /api/v1/analytics/members?deptId=uuid&from=2026-06-01&to=2026-06-30
```

```json
Response 200:
{
  "data": [
    {
      "userId": "uuid",
      "name": "Prof. Asha Nair",
      "departmentName": "CSE",
      "roleLabel": "HoD",
      "totalTasks": 20,
      "onTime": 15,
      "beforeTime": 3,
      "overdue": 2,
      "effectivenessScore": 82.5
    }
  ],
  "meta": {
    "formula": "((onTime × 1 + beforeTime × 2 + overdue × −1) / total) × 100",
    "refreshedAt": "2026-06-20T00:00:00Z"
  }
}
```

> Analytics are refreshed **once daily** via EventBridge cron (not real-time). `refreshedAt` shows last compute time.

**Errors:** 401 · 403 · 500

---

## 17. Departments

> **No admin UI for department creation or deletion.** Departments are **created** exclusively via the Excel onboarding import (`POST /tenant/onboard/import`). The `departments` table exists for two reasons: (1) `BroadcastNoticeAudienceDept` join table for multi-department audience targeting (2026-07-17), (2) analytics scoping for HoD (MID role). POST and DELETE are not exposed — use re-import to create or remove departments. **PATCH is exposed** (`TOP` role only) to allow updating `name` and `headUserId` without a full re-import.

### GET /departments

**Access:** `requireAuth` — any tenant member. Used by the broadcast audience picker and analytics filter. Returns only the calling tenant's departments.

```json
Response 200:
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "id": "uuid",
      "name": "CSE",
      "headUserId": "uuid",
      "headName": "Prof. Asha Nair",
      "memberCount": 12
    }
  ]
}
```

**Errors:** 401 · 500

---

### GET /departments/:id

Returns a single department by ID. Tenant-scoped — returns 404 if the department belongs to a different tenant.

**Access:** `requireAuth` — any tenant member.

```json
Response 200:
{
  "success": true,
  "message": "OK",
  "data": {
    "id": "uuid",
    "name": "CSE",
    "headUserId": "uuid",
    "headName": "Prof. Asha Nair",
    "memberCount": 12
  }
}
```

**Errors:** 401 · 404 (`NOT_FOUND`) · 500

---

### PATCH /departments/:id

Updates a department's `name` and/or `headUserId`. At least one field must be provided. Tenant-scoped — returns 404 if the department belongs to a different tenant.

**Access:** `requireAuth` + `requireOrgRole(['TOP'])` — TOP admin only.

```json
Request (any subset — at least one required):
{
  "name": "Computer Science & Engineering",   // optional — new department name
  "headUserId": "uuid"                        // optional — assign a new head; null to clear
}

Response 200:
{
  "success": true,
  "message": "Department updated",
  "data": {
    "id": "uuid",
    "name": "Computer Science & Engineering",
    "headUserId": "uuid",
    "headName": "Prof. Asha Nair",
    "memberCount": 12
  }
}
```

**Business rules enforced:**
- `headUserId` must belong to the same tenant — 400 if not.
- `headUserId` is `@unique` — one user can head at most one department. If the user is already heading another department → 409 `HEAD_ALREADY_ASSIGNED`.
- Setting `headUserId: null` clears the current head.
- `name` must be non-empty if provided.

**Errors:** 400 (`VALIDATION_ERROR`) · 401 · 403 (`FORBIDDEN` — not TOP role) · 404 (`NOT_FOUND`) · 409 (`HEAD_ALREADY_ASSIGNED`) · 500

---

## 18. Billing

> **W60:** Billing module is confirmed in scope (per-seat pricing). Payment provider TBD (Razorpay vs Stripe — W60 open). These stubs define the contract; implementation waits on provider selection.

### GET /billing/subscription — current plan

**Access:** `requireOrgRole(['TOP'])`.

```json
Response 200:
{
  "success": true,
  "data": {
    "planId": "per-seat-v1",
    "status": "ACTIVE",           // ACTIVE | TRIAL | PAST_DUE | CANCELLED
    "seatCount": 87,
    "billedSeats": 90,            // rounded up to billing unit
    "nextBillingDate": "2026-07-01",
    "provider": "razorpay",
    "externalSubscriptionId": "sub_xxx"
  }
}
```

---

### POST /billing/subscribe — start or update subscription

**Access:** `requireOrgRole(['TOP'])`.

```json
Request:
{
  "planId": "per-seat-v1",
  "paymentMethodToken": "tok_xxx"    // provider-specific token from client-side SDK
}

Response 200:
{
  "success": true,
  "data": { "status": "ACTIVE", "nextBillingDate": "2026-07-01" },
  "message": "Subscription activated"
}
```

**Errors:** 400 (invalid token · plan not found) · 402 (payment failed) · 401 · 403 · 500

---

### POST /billing/cancel

**Access:** `requireOrgRole(['TOP'])`.

```json
Response 200:
{ "success": true, "data": { "status": "CANCELLED" }, "message": "Subscription cancelled" }
```

---

## 19. AI Nudge Config (Admin)

The AI Nudge scheduler behaviour is admin-configurable per PRD §5.7. These settings are per-tenant.

### GET /settings/nudge-config

**Access:** `requireOrgRole(['TOP'])`.

```json
Response 200:
{
  "success": true,
  "data": {
    "periodicNudge": {
      "enabled": true,
      "intervalHours": 24,          // how often the periodic nudge fires
      "officeHoursStart": "09:00",  // IST
      "officeHoursEnd": "18:00"
    },
    "followupNudge": {
      "enabled": true,
      "triggerAfterHours": 48,      // fire if no progress update after N hours
      "deduplicationWindowHours": 24
    },
    "dueDateNudge": {
      "enabled": true,
      "fireDaysBefore": [1, 0]      // fire 1 day before + on due date
    }
  }
}
```

---

### PATCH /settings/nudge-config

**Access:** `requireOrgRole(['TOP'])`.

```json
Request (any subset of the GET response body):
{
  "periodicNudge": { "intervalHours": 48 },
  "followupNudge": { "deduplicationWindowHours": 12 }
}

Response 200:
{ "success": true, "data": { /* full updated config */ }, "message": "Nudge config updated" }
```

---

## 20. Health Check

Public — no auth.

### GET /health

```json
Response 200:
{ "success": true, "data": { "status": "ok", "version": "1.0.0", "timestamp": "2026-06-20T10:00:00Z" } }
```

---

## 21. Jargon Words *(new, bolo-backend-django sync 2026-08-03)*

Grounds the voice-recognition and Global Search query-understanding layers against vertical-specific jargon (e.g. "NAAC", "MGT-7") a general-purpose model wouldn't otherwise get right. **Not tenant-scoped** — one shared dictionary per `Vertical` (`EDUCATION`/`CA_CS`). Gated by an email allow-list (`JARGON_ADMIN_EMAILS` equivalent), **not** `PlatformAdmin` and **not** `OrgRoleLevel` — a distinct admin concept from either. Deliberately **not audit-logged** (no route-config row upstream, by design).

### GET /jargon-words — list

```
GET /api/v1/jargon-words?vertical=EDUCATION&search=&isActive=&page=&limit=
```

`limit` capped at 200 (default 50). `search` matches `term` (case-insensitive contains) or exact `variants` array-contains.

```json
Response 200:
{ "data": [ { "id": "uuid", "vertical": "EDUCATION", "term": "NAAC", "variants": ["nack"], "isActive": true, "createdBy": "uuid", "createdAt": "...", "updatedAt": "..." } ], "pagination": { "page": 1, "limit": 50, "total": 1 } }
```

### POST /jargon-words — create

```json
Request: { "vertical": "EDUCATION", "term": "NAAC", "variants": ["nack"], "isActive": true }
Response 201: { "data": { ... }, "message": "Jargon word created" }
```

`term` max 100 chars. Case-insensitive duplicate check on `(vertical, term)` — app-level pre-check plus a DB unique-constraint catch, `409 DUPLICATE_JARGON_TERM`.

### PATCH /jargon-words/:id — partial update

Re-checks the duplicate constraint only if `term` actually changes.

### DELETE /jargon-words/:id

```json
Response 200: { "data": null, "message": "Jargon word deleted" }
```

### GET /jargon-words/template?vertical=EDUCATION — download Excel template

Returns an `.xlsx` file (`Content-Disposition: attachment`), filename varies by vertical (e.g. `education-institute-jargon-template.xlsx` / `ca-firm-jargon-template.xlsx`).

### POST /jargon-words/bulk-import?vertical=EDUCATION — bulk import

Accepts **either** `multipart/form-data` file upload (`.xlsx`/`.xls`, field `file`) **or** a JSON body `{ "words": [...] }`.

```json
Response 200: { "data": { "created": 12, "updated": 3, "skipped": 1, "errors": [ { "term": "...", "reason": "..." } ] } }
```

Dedup within the file is case-insensitive (last row wins; earlier duplicate rows reported as skipped/errors); upserts by `(vertical, term)`.

**Errors (all endpoints):** 400 `VALIDATION_ERROR` · 401 · 403 (not on the admin allow-list) · 404 · 409 `DUPLICATE_JARGON_TERM` · 500

---

## 22. Platform Admin (Superadmin) *(upstream built 2026-07-15, W35/W98 resolved — core CRUD built here 2026-08-23: OTP auth, create/list tenant, add/remove member. RBAC (`PlatformAdmin.role` + `HasPlatformAdminRole`) built 2026-08-29 (Phase 15a); `AuditLog` wiring for `TENANT_CREATED`/`MEMBER_ADDED`/`MEMBER_REMOVED` built 2026-08-29 (Phase 15b); `.xlsx`/`.csv`/`.json` member bulk-import ETL + `MEMBERS_BULK_IMPORTED` audit built 2026-08-29 (Phase 15c); tenant suspend/reactivate offboarding (`PATCH .../tenants/:id`, `TENANT_SUSPENDED`/`TENANT_REACTIVATED`) built 2026-08-29 (Phase 15e); `GET /platform-admin/auth/me` for the SPA session check built 2026-08-29 (Phase 15d backend prep). **Deferred:** the standalone admin console SPA itself (Phase 15d, separate `bolo-admin-console` repo), and a hard tenant purge (export-first, W58) — see CLAUDE.md)*

A `PlatformAdmin` is a cross-tenant actor, outside `Tenant`/RLS scoping entirely — not a `User`, not a `TenantMembership` role. It registers new tenants and can add/remove users in **any** tenant. No self-registration: rows are provisioned only via an ops-run seed script. See `docs/architecture/domain-model.md`'s "PlatformAdmin" section for the model shape.

Auth mirrors `/auth/*` (Email+OTP, same OTP/email infra) but is fully parallel: separate `PlatformAdminOtpCode` table (not `OtpCode` — avoids colliding with a tenant user's in-flight OTP on the same email), separate `admin_token` cookie (not `token`), separate JWT payload (`{ adminId, email, isPlatformAdmin: true, role }` — no `tenantId`/`roleLevel`, so a tenant session and a platform-admin session can never be mistaken for or coexist-confused with each other).

> **`role` claim (bolo-backend-django addition, ROADMAP.md Phase 15a — not in upstream):** the `admin_token` JWT also carries `role`, a `PlatformAdminRole` value (`SUPER_ADMIN` only today). The four management endpoints below enforce it via a `HasPlatformAdminRole(["SUPER_ADMIN"])` permission-class factory (structural twin of `HasOrgRole`) *in addition to* `requirePlatformAdmin` — an authenticated admin whose role is outside the allow-list gets `403`, not `401`. `/platform-admin/auth/logout` is deliberately **not** role-gated (any authenticated admin can end their own session). Tokens minted before this claim existed fall back to the `PlatformAdmin.role` column.

**Note:** upstream also has an in-flight, *unmerged* "Admin Console" feature (`/api/v1/admin-console/tenants/...`, `bug/voice-post-deploy-issues` branch as of this sync) that is a **different, third surface** — gated by the jargon-admin email allow-list, not `PlatformAdmin` auth, reached from an "Admin Tools" panel rather than a superadmin login. It is explicitly documented upstream as NOT the `PlatformAdmin` surface. It is not on upstream's `develop` branch yet — do not build against it; track it for a future sync once it merges.

### POST /platform-admin/auth/request-otp

Same behavior as `POST /auth/request-otp`, looked up against `PlatformAdmin` instead of `User`.

```json
Request: { "email": "admin@bolo.internal" }
Response 200: { "data": null, "message": "OTP sent to admin@bolo.internal" }
```

**Errors:** 400 `INVALID_EMAIL` · 404 `ADMIN_NOT_FOUND` · 429 `RATE_LIMITED` · 502 `EMAIL_DELIVERY_FAILED`

---

### POST /platform-admin/auth/verify-otp

```json
Request: { "email": "admin@bolo.internal", "otp": "482910" }

Response 200:
{
  "data": { "adminId": "PAD00001", "name": "Ops Admin", "email": "admin@bolo.internal", "role": "SUPER_ADMIN" },
  "message": "Login successful"
}

Set-Cookie: admin_token=<jwt>; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800
```

(`role` added to the response 2026-08-29, Phase 15d — `PlatformAdminRole`, `SUPER_ADMIN` only today.)

**Errors:** 400 `INVALID_OTP` (includes `data.attemptsRemaining`) · 400 `OTP_EXPIRED` · 429 (locked 15 min)

---

### GET /platform-admin/auth/me *(built here 2026-08-29, ROADMAP.md Phase 15d — no upstream equivalent)*

Session check for the standalone admin console SPA: its top-level route guard calls this once on load — `200` renders the app, `401` redirects to `/login`. Reads the `admin_token` cookie; not role-gated (any authenticated admin can read their own identity).

```json
Response 200:
{ "data": { "adminId": "PAD00001", "name": "Ops Admin", "email": "admin@bolo.internal", "role": "SUPER_ADMIN" }, "message": "OK" }
```

**Errors:** 401 (no / invalid / wrong-auth-space cookie)

---

### POST /platform-admin/auth/logout

Clears the `admin_token` cookie server-side. **Access (4 endpoints below):** `requirePlatformAdmin` — a distinct middleware; none of them accept or trust a tenant-scoped `token` cookie.

---

### POST /platform-admin/tenants — create Tenant + first TOP user

Replaces what would otherwise be a public, unauthenticated tenant-registration endpoint — this project has never had one (Phase 1 tenant creation had always gone through fixtures/seed data until this endpoint, so there's no equivalent public-endpoint-removal gap to close here, unlike upstream's removed `POST /onboard/register`).

```json
Request:
{
  "tenantName": "ABC College",
  "urlSlug": "abc-college",
  "vertical": "EDUCATION",
  "adminName": "Dr. Kamal Sethi",
  "adminEmail": "dean@abc.edu",
  "adminPhone": "+919876543210",
  "roleLabel": "Dean",
  "preferredLang": "EN"
}

Response 201:
{
  "data": {
    "tenantId": "uuid",
    "tenantName": "ABC College",
    "urlSlug": "abc-college",
    "vertical": "EDUCATION",
    "createdAt": "2026-07-15T10:00:00+05:30",
    "admin": { "userId": "uuid", "name": "Dr. Kamal Sethi", "email": "dean@abc.edu", "roleLevel": "TOP", "roleLabel": "Dean" }
  },
  "message": "Tenant registered"
}
```

**`urlSlug`** — required, `^[a-z0-9]+(-[a-z0-9]+)*$`, 2-40 chars. **Rejected, not auto-transformed** if malformed (`400 INVALID_URL_SLUG`). Must be unique across all tenants.

**Audit (built 2026-08-29, Phase 15b):** writes an `AuditLog` row — `action: TENANT_CREATED`, `actorType: PLATFORM_ADMIN`, `actorId: null` (a `PlatformAdmin` isn't a `User` row), `entityType: "TENANT"`, `entityId` + `tenant` = the new tenant, `before: null`, `after: { vertical, url_slug }`, `metadata: { platformAdminId, platformAdminEmail }`. The generic audit middleware grew a second actor-resolution path that reads the `admin_token` cookie instead of the tenant-user `token` cookie. Same shape on `MEMBER_ADDED`/`MEMBER_REMOVED` below.

**Errors:** 400 `VALIDATION_ERROR` · 400 `INVALID_URL_SLUG` · 400 `TENANT_NAME_TAKEN` · 400 `URL_SLUG_TAKEN` · 400 `EMAIL_TAKEN` · 401

---

### GET /platform-admin/tenants — list all tenants

```json
Response 200:
{ "data": [ { "tenantId": "uuid", "name": "ABC College", "vertical": "EDUCATION", "status": "ACTIVE", "createdAt": "...", "memberCount": 42, "departmentCount": 5 } ] }
```

`status` is `ACTIVE` | `SUSPENDED` (Phase 15e).

---

### PATCH /platform-admin/tenants/:tenantId — suspend / reactivate a tenant *(built here 2026-08-29, ROADMAP.md Phase 15e — no upstream equivalent)*

Operator **offboarding**: cut a whole tenant's access when a customer leaves BOLO or stops paying, and restore it later. All tenant data is retained either way. There is **no `DELETE`** — a hard purge is a separate, export-first step (`W58`), not built.

```json
Request:  { "status": "SUSPENDED", "reason": "customer offboarded" }   // reason optional
Response 200:
{ "data": { "tenantId": "uuid", "name": "ABC College", "vertical": "EDUCATION", "urlSlug": "abc-college",
            "status": "SUSPENDED", "suspendedAt": "...", "suspensionReason": "customer offboarded", "createdAt": "..." } }
```

- `status` — `ACTIVE` | `SUSPENDED` (required). Only the lifecycle status is mutable here; name/vertical/slug are set once at creation.
- **While `SUSPENDED`:** this tenant's users get `403 TENANT_SUSPENDED` on `POST /auth/request-otp`, `POST /auth/verify-otp`, and `POST /auth/refresh` — so any live session dies within the 15-minute access-token lifetime. Its due-date and AI-nudge Celery sweeps don't fire. `POST .../members` and `POST .../members/import` return `409 TENANT_SUSPENDED`.
- Reactivating (`status: "ACTIVE"`) clears `suspendedAt` / `suspensionReason` and restores all of the above.

Writes one `AuditLog` row: `action: TENANT_SUSPENDED` or `TENANT_REACTIVATED`, `actorType: PLATFORM_ADMIN`, `actorId: null`, `entityType: "TENANT"`, `before`/`after` = `{ status, suspension_reason }`, `metadata: { platformAdminId, platformAdminEmail }`.

**Errors:** 400 `VALIDATION_ERROR` (unknown `status`) · 404 `NOT_FOUND` · 409 `TENANT_STATUS_UNCHANGED` (already in that status) · 401

---

### POST /platform-admin/tenants/:tenantId/members — add a user to any tenant

This project has no tenant self-service member-add endpoint to mirror (never built — see CLAUDE.md's contract-gaps list), so this is its own standalone implementation: creates the `User` row (`tenant_id` from the URL param) + a `TenantMembership` in one transaction.

```json
Request:
{ "name": "Prof. Asha Nair", "email": "asha@abc.edu", "roleLevel": "MID", "roleLabel": "HoD", "departmentId": "uuid" }

Response 201:
{ "data": { "userId": "uuid", "email": "asha@abc.edu" }, "message": "Member added" }
```

**Audit (built 2026-08-29, Phase 15b):** `AuditLog` row — `action: MEMBER_ADDED`, `actorType: PLATFORM_ADMIN`, `actorId: null`, `entityType: "USER"`, `entityId` = the new user, `tenant` = the path `:tenantId`, `after: { tenant_id, preferred_lang }`, `metadata: { platformAdminId, platformAdminEmail }`. See the note on `POST /platform-admin/tenants` above.

**Errors:** 400 `VALIDATION_ERROR` · 400 `EMAIL_ALREADY_IN_TENANT` · 404 `NOT_FOUND` (tenant) · 409 `TENANT_SUSPENDED` (tenant is suspended — reactivate it first) · 401

---

### DELETE /platform-admin/tenants/:tenantId/members/:userId — remove a user from any tenant

Hard-deletes the `TenantMembership` row only — `User` row is left intact. Active tasks are **not** cancelled automatically.

```json
Response 200: { "data": null, "message": "Member removed" }
```

**Audit (built 2026-08-29, Phase 15b):** `AuditLog` row — `action: MEMBER_REMOVED`, `actorType: PLATFORM_ADMIN`, `actorId: null`, `entityType: "USER"`, `entityId` = the removed user, `tenant` = the path `:tenantId`, `before: { tenant_id, preferred_lang }`, `after: null` (DELETE convention), `metadata: { platformAdminId, platformAdminEmail }`. The `User` row itself is not deleted — only the `TenantMembership`.

**Errors:** 404 `NOT_FOUND` · 401

---

### POST /platform-admin/tenants/:tenantId/members/import — bulk member import into any tenant *(built here 2026-08-29, ROADMAP.md Phase 15c — a small ETL pipeline)*

**Access:** `requirePlatformAdmin` + `HasPlatformAdminRole(["SUPER_ADMIN"])`. `tenantId` from the URL, so an operator can import into **any** tenant.

**Request:** `multipart/form-data`, one field `file` — a `.xlsx`, `.csv`, **or** `.json` file (CSV and JSON are a bolo-backend-django extension of upstream's Excel-only contract, per direct request). Max 5 MB / 5000 data rows.

**Columns** (header names are case-insensitive and alias-normalised — `E-mail`/`Email Address`/`mail` → `email`, `Role`/`Role Level` → `roleLevel`, `Full Name` → `name`, `Designation`/`Title` → `roleLabel`, `Can Broadcast` → `canBroadcast`, `Language` → `preferredLang`):

| column | required | notes |
|---|---|---|
| `name` | ✅ | |
| `email` | ✅ | lower-cased; globally unique — an email already in a *different* tenant is skipped with an error |
| `roleLevel` | ✅ | `TOP` \| `MID` \| `EXECUTOR` (case-insensitive); anything else rejects that row |
| `roleLabel` | — | free-text designation |
| `phone` | — | |
| `canBroadcast` | — | `true/yes/1` → true, else false; default false |
| `preferredLang` | — | `EN` \| `HI`; unrecognised → `EN` |

Department assignment is **not** supported by import (single-add's `departmentId` only). JSON input may be a bare array or `{ "members": [...] }`.

**Behaviour:** Extract (one DataFrame regardless of format; CSV tries `utf-8-sig` then falls back to `latin-1`) → Transform (header normalisation, type coercion, **vectorised** per-row validation, within-file dedup by email keeping the **last** occurrence, CSV/Excel **formula-injection** neutralisation — a cell starting `= + - @` is prefixed with `'`) → Load (idempotent `update_or_create` by email, 100 rows per transaction). A member already in this tenant is **updated**, not duplicated. One bad row never fails the batch — it becomes an `errors[]` entry and is counted in `skipped`.

```json
Response 200:
{ "success": true, "message": "Import complete",
  "data": { "created": 5, "updated": 1, "skipped": 2,
            "errors": [ { "row": 4, "field": "roleLevel", "reason": "must be one of EXECUTOR, MID, TOP" },
                        { "row": 7, "field": "email", "reason": "not a valid email address" } ] } }
```

`row` is 1-based and counts the header as row 1 (i.e. it matches the spreadsheet line); for JSON input, `row` 2 is the first array element.

Writes one `AuditLog` row: `action: MEMBERS_BULK_IMPORTED`, `actorType: PLATFORM_ADMIN`, `actorId: null`, `entityType: "TENANT"`, `entityId` + `tenant` = the target tenant, `metadata: { platformAdminId, platformAdminEmail, created, updated, skipped }` (the run's scale is on the audit row, not only the HTTP response).

**Errors:** 400 `INVALID_FILE` (missing/oversized file, unsupported extension, unparseable content, missing a required column, empty, over the row cap) · 404 `NOT_FOUND` (tenant) · 409 `TENANT_SUSPENDED` · 401

---

## 23. Task Extraction (AI) *(new, bolo-backend-django ROADMAP.md Phase 9, no equivalent in the original bolo-backend contract)*

Not a port — this endpoint doesn't exist upstream. Voice transcription and §14's Voice AI SDK dispatch already handle *fully structured* voice commands client-side; this endpoint is for the opposite case — raw, unstructured text (a rough voice transcript or something typed free-form) that the user wants turned into a **draft** to review, not an action to execute. It never creates a task and is never in the create-task critical path: every field it returns is optional and user-editable before `POST /tasks` is ever called, and the endpoint itself degrades to an all-null response — never an error — if the AI provider is unavailable. See `CLAUDE.md`'s Phase 9 changelog entry for why this is a synchronous call with a tight timeout rather than a Celery job the frontend polls.

### POST /tasks/extract

**Access:** `requireAuth`.

```json
Request: { "text": "ask Bob Iyer to submit the self-study report by Friday, urgent" }

Response 200:
{
  "data": {
    "title": "Submit the self-study report",
    "assigneeHint": "Bob Iyer",
    "dueDate": "2026-08-28",
    "priority": "P1"
  },
  "message": "OK"
}
```

- `text` — required, 3–2000 chars.
- `assigneeHint` is the **name as extracted from the text**, not a resolved `userId` — this endpoint never queries the tenant roster or Global Search's person-resolution layer (`apps/search/ai_classify.py:resolve_person`); the frontend runs its own assignee picker/autocomplete against the hint, same as a user would type a name into that picker manually. Deliberately simpler than Search's roster-grounded resolution, since a wrong hint here just means the user picks a different name from a dropdown — it never silently assigns a task to the wrong person the way a mis-resolved search filter silently would.
- `dueDate` is an absolute `YYYY-MM-DD`, resolved from any relative phrase ("tomorrow", "by Friday") against the server's current date at request time.
- `priority` is normalized to a real `Priority` enum value (`P1`–`P4`) server-side; an AI-returned value that doesn't map to a known alias is dropped (`null`), never passed through unvalidated.
- Every field is `null` when: no `OPENAI_API_KEY` is configured (this project's dev sandbox default), the AI call times out or errors, or the AI's own response is malformed/unparseable JSON. All three are the same documented fallback — the response is still `200`, never a `5xx`, and the frontend just renders an empty form.
- Not cached (unlike `/search/*`'s per-`(query, source, userId, tenantId)` cache) — deliberately deferred as optional, see `CLAUDE.md`'s Phase 9 changelog entry; each call re-hits OpenAI when a key is configured.

**Errors:** 400 `VALIDATION_ERROR` (`text` under 3 or over 2000 chars, or missing) · 401

---

## Appendix — Route × Middleware Matrix

| Route | Auth | Role guard | Ownership check |
|---|---|---|---|
| POST /auth/\* | none | none | none |
| GET /tasks?view=open\|overdue\|done_a\|by_label\|due_this_week | requireAuth | none | tenantId scope |
| GET /tasks | requireAuth | none | tenantId scope |
| GET /tasks/counts | requireAuth | none | service: userId + tenantId = me |
| POST /tasks | requireAuth | none | caller becomes assigner |
| PATCH /tasks/:id | requireAuth | none | service: must be assignerId |
| DELETE /tasks/:id | requireAuth | none | service: must be assignerId |
| POST /tasks/:id/accept | requireAuth | none | service: must be assigneeId |
| POST /tasks/:id/done-a | requireAuth | none | service: must be assigneeId |
| POST /tasks/:id/done-d | requireAuth | none | service: must be assignerId |
| POST /tasks/:id/cancel | requireAuth | none | service: must be assignerId |
| POST /tasks/:taskId/subtasks | requireAuth | none | service: must be parent assigneeId |
| GET /tasks/:id/comments | requireAuth | none | service: assigner or assignee |
| POST /tasks/:id/comments | requireAuth | none | service: assigner or assignee |
| PATCH /tasks/:id/comments/:cid | requireAuth | none | service: must be authorId |
| DELETE /tasks/:id/comments/:cid | requireAuth | none | service: must be authorId |
| POST /upload/presign | requireAuth | none | service: assigner or assignee |
| POST /tasks/:id/evidence | requireAuth | none | service: assigner or assignee |
| GET /tasks/:id/evidence/:eid/file | requireAuth | none | service: assigner or assignee (backend-streamed, not pre-signed URL) |
| DELETE /tasks/:id/evidence/:eid | requireAuth | none | service: uploaderId only (narrowed — was uploaderId or assignerId) |
| GET/POST/PATCH/DELETE /labels | requireAuth | none | POST: any; PATCH/DELETE: creatorId |
| GET/POST/PATCH /sticky-notes | requireAuth | none | service: userId = me |
| POST /sticky-notes/:id/promote | requireAuth | none | service: userId = me |
| GET /broadcast-notices?view=received\|sent | requireAuth | none | audience match (received) or senderId (sent, excludes DRAFT) in service |
| POST /broadcast-notices | requireAuth | none | service: canBroadcast = true |
| PATCH /broadcast-notices/:id | requireAuth | none | service: senderId only; blocked once expired |
| DELETE /broadcast-notices/:id | requireAuth | none | service: senderId only |
| POST /broadcast-notices/:id/publish | requireAuth | none | service: senderId + canBroadcast |
| GET /broadcast-notices/:id/image | requireAuth | none | service: sender (any status) or active audience member (backend-streamed, not pre-signed URL) |
| POST /broadcast-notices/:id/ack | requireAuth | none | service: audience member |
| GET /broadcast-notices/:id/ack-count | requireAuth | none | service: senderId |
| GET /notifications | requireAuth | none | service: recipientId = me |
| PATCH /notifications/:id/read | requireAuth | none | service: recipientId = me |
| POST /notifications/mark-all-read | requireAuth | none | service: recipientId = me |
| GET /audit-log | requireAuth | requireOrgRole(['TOP']) | service: or assignerId of entity |
| GET /search/tasks, GET /search/stickies | requireAuth | none | PostgreSQL + AI query-understanding layer, scoped per-bucket (§13) — not OpenSearch |
| POST /tasks/extract | requireAuth | none | none — draft-only, never persists (§23) |
| POST /voice/dispatch | requireAuth | none | service: same as target endpoint |
| GET /me, PATCH /me | requireAuth | none | JWT userId |
| POST /upload/profile-picture-presign, PATCH/DELETE /me/profile-picture | requireAuth | none | JWT userId; always targets caller's own picture |
| GET /users/:userId/profile-picture | requireAuth | none | any tenant member; 404 if userId belongs to a different tenant |
| GET /users/:userId/profile-picture/file | requireAuth | none | any tenant member (backend-streamed, not pre-signed URL) |
| GET /tenant | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| GET /tenant/members | requireAuth | none | tenantId from JWT |
| GET /tenant/roles | requireAuth | none | tenantId from JWT |
| POST /tenant/members/invite | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| DELETE /tenant/members/:userId | requireAuth | requireOrgRole(['TOP']) | cannot remove self |
| POST /tenant/members/:userId/reactivate | requireAuth | requireOrgRole(['TOP']) | service: user must belong to tenant, no existing active membership |
| POST /platform-admin/tenants/:tenantId/members/:userId/reactivate | platformAdmin auth | none | cross-tenant variant, same validation |
| GET/POST/PATCH/DELETE /jargon-words, GET /jargon-words/template, POST /jargon-words/bulk-import | requireAuth | requireJargonAdmin (email allow-list, not OrgRoleLevel) | not tenant-scoped — one dictionary per Vertical |
| GET /analytics/members | requireAuth | requireOrgRole(['TOP','MID']) | service: MID scoped to own dept |
| GET /departments | requireAuth | none | tenantId from JWT |
| GET /departments/:id | requireAuth | none | service: tenantId match (404 if foreign tenant) |
| PATCH /departments/:id | requireAuth | requireOrgRole(['TOP']) | service: tenantId match; headUserId in same tenant |
| GET /tenant/org-chart | requireAuth | requireOrgRole(['TOP','MID']) | tenantId from JWT |
| POST /tenant/onboard/import | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| GET /notifications/unread-count | requireAuth | none | service: recipientId = me |
| GET /billing/subscription | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| POST /billing/subscribe | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| POST /billing/cancel | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| GET /settings/nudge-config | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| PATCH /settings/nudge-config | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| POST /platform-admin/auth/\* | none | none | none — parallel to /auth/\*, admin_token cookie |
| POST /platform-admin/tenants | requirePlatformAdmin | none | none — cross-tenant by design |
| GET /platform-admin/tenants | requirePlatformAdmin | none | none — cross-tenant by design |
| POST /platform-admin/tenants/:tenantId/members | requirePlatformAdmin | none | none — cross-tenant by design |
| DELETE /platform-admin/tenants/:tenantId/members/:userId | requirePlatformAdmin | none | none — cross-tenant by design |
| POST /platform-admin/tenants/:tenantId/members/import | requirePlatformAdmin + SUPER_ADMIN | none | none — cross-tenant by design; built 2026-08-29 (Phase 15c), `.xlsx`/`.csv`/`.json` ETL, see §22 |
| GET /health | none | none | none |
