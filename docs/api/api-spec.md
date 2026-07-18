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
{ "success": false, "error": { "code": "DRAFT_MISSING_FIELDS", "message": "Audience scope (department + role level) is required to publish a broadcast" } }

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
    "roleLevel": "TOP",
    "roleLabel": "Dean",
    "canBroadcast": true,
    "preferredLang": "EN"
  },
  "message": "Login successful"
}

Set-Cookie: token=<jwt>; HttpOnly; SameSite=Strict; Path=/; (no Max-Age — session cookie)
```

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
| `view` | yes | `assigned` \| `delegated` \| `needs_attention` | — |
| `labelId` | no | UUID | — |
| `isArchived` | no | `true` \| `false` | `false` |
| `page` | no | integer ≥ 1 | `1` |
| `limit` | no | 1–100 | `20` |

**View → filter logic:**
- `assigned` — `assigneeId = me`; excludes `DRAFT`, `DONE_D`, `CANCELLED`, `isArchived=true`; sort: `OVERDUE` first → `dueDate ASC` → `createdAt DESC`
- `delegated` — `assignerId = me`; excludes `DONE_D`, `isArchived=true`; same sort
- `needs_attention` — tasks where action is required: `OPEN` (not yet accepted) + `OVERDUE` + `DONE_A` (awaiting assigner mark); scoped to me as assignee or assigner

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

Returns the count of tasks in each of the three task-tab views (`assigned`, `delegated`, `needs_attention`) for the calling user — used for sidebar/tab badge counts. Cheap COUNT query — no pagination, no body params. Uses the same filter logic as `GET /tasks?view=...` (see above), scoped to `tenantId` from JWT.

**Access:** `requireAuth` — scoped to `tenantId` + `userId` from JWT.

```json
Response 200:
{ "success": true, "data": { "assigned": 4, "delegated": 7, "needsAttention": 2 }, "message": "OK" }
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

> `voiceRecording` is `null` if the task was created via keyboard. `hasAudio: true` means an audio clip is stored in S3 — use `GET /tasks/:id/voice-recording/audio` to get a playback URL. The raw S3 key is never exposed.

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

**Access:** `requireAuth` + must be assigner or assignee. File URLs are pre-signed S3 read URLs (expire in 1 hour).

```json
Response 200:
{ "data": [ { "id": "uuid", "fileUrl": "https://...", "fileName": "...", "fileType": "PDF", "caption": "...", "uploaderName": "...", "createdAt": "..." } ] }
```

---

### DELETE /tasks/:id/evidence/:eid

**Access:** Caller must be the uploader (`uploaderId`) or the assigner. Deletes from S3 and DB.

```json
Response 200: { "data": null, "message": "Evidence removed" }
```

**Errors:** 401 · 403 · 404 · 500

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

### GET /tasks/:id/voice-recording/audio — get pre-signed playback URL

Generates a short-lived pre-signed S3 GET URL for audio playback. Only callable if `hasAudio: true`.

```json
Response 200:
{
  "data": {
    "playbackUrl": "https://s3.ap-south-1.amazonaws.com/bolo-voice/...",
    "expiresIn": 900
  }
}
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

**Implementation status (2026-07-12):** CRUD + publish + list + ack + ack-count are built (`bolo-backend/src/routes/broadcast-notices.routes.ts`). The two image endpoints below (`POST /upload/broadcast-image-presign`, `POST /broadcast-notices/:id/image`) are **not yet implemented** — this backend has no S3/presign client wired anywhere yet (same gap blocks task-evidence upload; see the commented-out `uploadRoutes` import in `routes/index.ts`). Contract stays documented here for when that infra lands. Server-side HTML re-sanitization uses a small in-repo safelist sanitizer (`utils/htmlSanitize.ts`), not a library — fine for TipTap's current tag set, revisit if the editor's allowed marks grow.

### Permissions recap:
- `canBroadcast` on `TenantMembership` gates creation — 403 if false.
- `audienceDeptId` + `audienceRoleLevel` are **both mandatory** at publish — 400 if either is null.
- Broadcasts live for **exactly 1 day** — `expiresAt = publishedAt + 24 hours` (set by server, not client).
- Stored as `messageJson` (TipTap AST — editor source) + `messageHtml` (sanitized HTML — feed rendering).
- One image attachment maximum.

### Image upload (broadcast) — same unconfirmed/ pattern as evidence

```
S3 paths:
  Upload →   bolo-broadcast/unconfirmed/{tenantId}/{broadcastId}/{filename}
  Confirmed → bolo-broadcast/{tenantId}/{broadcastId}/{filename}

S3 lifecycle rule: prefix=unconfirmed/ | delete after 24h
```

**Image serving:** broadcast images render **inline in the feed** (not click-to-open like evidence). At publish time the server generates a pre-signed GET URL with **25h TTL** and stores it in `imageUrl`. The feed returns this URL directly — no per-request URL generation.

### POST /upload/broadcast-image-presign — request pre-signed image upload URL

**Access:** `requireAuth` + `canBroadcast = true` + must be sender of the broadcast.

```json
Request:
{
  "broadcastId": "uuid",
  "filename": "notice-banner.jpg",
  "contentType": "image/jpeg",
  "fileSize": 512000
}

Response 200:
{
  "data": {
    "uploadUrl": "https://s3.ap-south-1.amazonaws.com/bolo-broadcast/unconfirmed/...",
    "s3Key": "unconfirmed/{tenantId}/{broadcastId}/notice-banner.jpg",
    "expiresIn": 900
  }
}
```

---

### POST /broadcast-notices/:id/image — confirm image after S3 upload

Server does: CopyObject → DeleteObject → UPDATE `imageUrl` with confirmed S3 key (not the pre-signed URL yet — that is generated at publish).

```json
Request: { "s3Key": "unconfirmed/{tenantId}/{broadcastId}/notice-banner.jpg" }

Response 200:
{ "data": { "hasImage": true }, "message": "Image attached" }
```

**Errors:** 400 (broadcast already published · not image content type) · 401 · 403 · 404 · 500

---

### GET /broadcast-notices?view=received|sent — notices visible to me / sent by me

```
GET /api/v1/broadcast-notices?view=received&page=1&limit=20   (default — same as omitting ?view entirely)
GET /api/v1/broadcast-notices?view=sent&page=1&limit=20
```

| Param | Required | Values | Default |
|---|---|---|---|
| `view` | no | `received` \| `sent` | `received` |
| `page` | no | integer ≥ 1 | `1` |
| `limit` | no | 1–100 | `20` |

**View → filter logic** (added 2026-07-14, W97 — see `open-questions-web-v1.md` §21):
- `received` (default) — active (`PUBLISHED`, non-expired) broadcasts where the audience matches the calling user's own dept + roleLevel. **A sender does NOT automatically see their own broadcast here** unless they also happen to match their own audience scope (e.g. a Dean broadcasting to HoDs never sees it in `received`, since the Dean is `TOP` not `MID`).
- `sent` — everything `senderId = me` created, **any** status (`DRAFT` + `PUBLISHED`, including expired) — the sender's own management view, so they can see/edit drafts and check on what they've published regardless of whether they're in its audience. Rows omit `hasAcknowledged` (not meaningful for your own sent item) but still include `ackCount`.

**Access:** `requireAuth`. Invalid `view` value, or `page`/`limit` out of range → 400 `VALIDATION_ERROR`.

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
      "audienceDeptId": "uuid",
      "audienceDeptName": "CSE",
      "audienceRoleLevel": "EXECUTOR",
      "requiresAcknowledgement": true,
      "ackCount": 12,
      "hasAcknowledged": false,         // true if calling user has acknowledged
      "imageUrl": "https://...",
      "status": "PUBLISHED",
      "expiresAt": "2026-06-21T10:00:00Z",
      "createdAt": "2026-06-20T10:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 12 }
}
```

`view=sent` returns the same shape minus `hasAcknowledged`, and includes `DRAFT` rows (`expiresAt: null`) alongside `PUBLISHED` ones.

---

### POST /broadcast-notices — create a draft

**Access:** `requireAuth` + `canBroadcast = true` on membership.

```json
Request:
{
  "messageJson": { /* TipTap JSON AST */ },   // required
  "messageHtml": "<p>All faculty...</p>",     // required — sanitized by client before sending; server re-sanitizes
  "audienceDeptId": "uuid",                  // required at publish; optional while DRAFT
  "audienceRoleLevel": "EXECUTOR",           // required at publish; optional while DRAFT
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

**Errors:** 400 (VALIDATION_ERROR — missing `messageJson`/`messageHtml`, or text over the char limit; `INVALID_DEPARTMENT` — `audienceDeptId` doesn't exist in the caller's tenant, corrected 2026-07-13, found via manual API testing: the server previously passed it straight to Prisma and a bad value threw an unhandled 500 instead of a clean 400) · 401 · 403 (BROADCAST_NOT_PERMITTED) · 500

---

### POST /broadcast-notices/:id/publish — publish a draft

Transitions `DRAFT → PUBLISHED`. Server does in order:
1. Validates `audienceDeptId` + `audienceRoleLevel` both set
2. Sets `expiresAt = now + 24 hours`
3. If image attached: generates **pre-signed GET URL with 25h TTL** from the stored S3 key → overwrites `imageUrl` with this URL (feed returns it directly — no per-request generation)
4. Enqueues fan-out notification job (async — not inline)

**Access:** Sender only + `canBroadcast = true`.

```json
Response 200:
{
  "data": {
    "id": "uuid",
    "status": "PUBLISHED",
    "expiresAt": "2026-06-21T10:00:00Z",
    "imageUrl": "https://s3.ap-south-1.amazonaws.com/bolo-broadcast/tenantId/broadcastId/...?X-Amz-Expires=90000&..."
  },
  "message": "Broadcast published"
}
```

**Errors:** 400 (DRAFT_MISSING_FIELDS — audience not set) · 401 · 403 · 404 · 500

---

### PATCH /broadcast-notices/:id — edit (sender only, DRAFT status only)

```json
Request (any subset):
{
  "messageJson": { /* updated TipTap AST */ },
  "messageHtml": "<p>Updated text</p>",
  "audienceDeptId": "uuid",
  "audienceRoleLevel": "MID",
  "requiresAcknowledgement": false,
  "imageUrl": null
}

Response 200:
{ "data": { "id": "uuid", "status": "DRAFT" }, "message": "Draft updated" }
```

**Errors:** 400 (CANNOT_EDIT_PUBLISHED · `INVALID_DEPARTMENT` if `audienceDeptId` doesn't exist in the caller's tenant, same check/fix as create above) · 401 · 403 · 404 · 500

---

### DELETE /broadcast-notices/:id

**Access:** Sender only.

```json
Response 200: { "data": null, "message": "Broadcast deleted" }
```

---

### POST /broadcast-notices/:id/ack — acknowledge a broadcast

Inserts a `BroadcastAcknowledgement` row. Composite PK `(broadcastId, userId)` prevents duplicates at DB level.

**Access:** `requireAuth`. Broadcast must be `PUBLISHED` and not expired. `requiresAcknowledgement` must be true. **Caller must be in the broadcast's audience** (own `dept`+`roleLevel` match `audienceDeptId`/`audienceRoleLevel`, same match rule as `GET /broadcast-notices` — corrected 2026-07-13, W96) — 403 otherwise. This includes the sender: they can only ack their own broadcast if they'd also see it in their own feed.

```json
Response 200:
{ "data": { "ackCount": 13 }, "message": "Acknowledged" }
```

**Errors:** 400 (not a requiring-ack broadcast · expired) · 401 · 403 (`NOT_IN_AUDIENCE`) · 404 · 409 (ALREADY_ACKNOWLEDGED) · 500

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

Full-text across all entities the user can access, powered by OpenSearch.

### GET /search

**Access:** `requireAuth` — results scoped to `tenantId` + entities the user is permitted to see.

```
GET /api/v1/search?q=NAAC&type=task&page=1&limit=20
```

| Param | Required | Values |
|---|---|---|
| `q` | yes | search string (min 2 chars) |
| `type` | no | `task` \| `sticky_note` \| `broadcast` \| `comment` — omit to search all |

```json
Response 200:
{
  "data": [
    {
      "entityType": "TASK",
      "id": "uuid",
      "title": "Submit NAAC self-study report",
      "snippet": "...include sections A1 through <mark>NAAC</mark> criteria...",
      "status": "IN_PROGRESS",
      "dueDate": "2026-06-30T17:00:00Z"
    },
    {
      "entityType": "STICKY_NOTE",
      "id": "uuid",
      "snippet": "Prepare <mark>NAAC</mark> agenda for staff meeting",
      "dueAt": "2026-06-21T09:00:00Z"
    }
  ],
  "pagination": { "page": 1, "limit": 20, "total": 4 }
}
```

**Errors:** 400 (q too short) · 401 · 500

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
    "profilePicUrl": "https://s3.../presigned-get-url",
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
Response 200: { "data": { "profilePicUrl": "https://s3.../presigned-get-url" } }
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
      "roleLevel": "MID",
      "roleLabel": "HoD",
      "departmentId": "uuid",
      "departmentName": "CSE",
      "canBroadcast": false
    }
  ],
  "pagination": { "page": 1, "limit": 50, "total": 87 }
}
```

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

> **No admin UI for department creation or deletion.** Departments are **created** exclusively via the Excel onboarding import (`POST /tenant/onboard/import`). The `departments` table exists for two reasons: (1) `BroadcastNotice.audienceDeptId` FK for audience targeting, (2) analytics scoping for HoD (MID role). POST and DELETE are not exposed — use re-import to create or remove departments. **PATCH is exposed** (`TOP` role only) to allow updating `name` and `headUserId` without a full re-import.

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

## Appendix — Route × Middleware Matrix

| Route | Auth | Role guard | Ownership check |
|---|---|---|---|
| POST /auth/\* | none | none | none |
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
| DELETE /tasks/:id/evidence/:eid | requireAuth | none | service: uploaderId or assignerId |
| GET/POST/PATCH/DELETE /labels | requireAuth | none | POST: any; PATCH/DELETE: creatorId |
| GET/POST/PATCH /sticky-notes | requireAuth | none | service: userId = me |
| POST /sticky-notes/:id/promote | requireAuth | none | service: userId = me |
| GET /broadcast-notices | requireAuth | none | audience match in service |
| POST /broadcast-notices | requireAuth | none | service: canBroadcast = true |
| POST /broadcast-notices/:id/publish | requireAuth | none | service: senderId + canBroadcast |
| POST /broadcast-notices/:id/ack | requireAuth | none | service: audience member |
| GET /broadcast-notices/:id/ack-count | requireAuth | none | service: senderId |
| GET /notifications | requireAuth | none | service: recipientId = me |
| PATCH /notifications/:id/read | requireAuth | none | service: recipientId = me |
| POST /notifications/mark-all-read | requireAuth | none | service: recipientId = me |
| GET /audit-log | requireAuth | requireOrgRole(['TOP']) | service: or assignerId of entity |
| GET /search | requireAuth | none | OpenSearch filtered by tenantId + visibility |
| POST /voice/dispatch | requireAuth | none | service: same as target endpoint |
| GET /me, PATCH /me | requireAuth | none | JWT userId |
| POST /upload/profile-picture-presign, PATCH/DELETE /me/profile-picture | requireAuth | none | JWT userId; always targets caller's own picture |
| GET /tenant | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| GET /tenant/members | requireAuth | none | tenantId from JWT |
| POST /tenant/members/invite | requireAuth | requireOrgRole(['TOP']) | tenantId from JWT |
| DELETE /tenant/members/:userId | requireAuth | requireOrgRole(['TOP']) | cannot remove self |
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
| GET /health | none | none | none |
