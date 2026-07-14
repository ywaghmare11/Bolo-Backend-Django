# BOLO — Product Requirements Document (PRD)

> **Source of truth:** `Doc/BOLO_Web_PRD_v1.pdf`, reconciled against four follow-up rounds of clarification (a Q&A sheet, an architecture reference doc, and direct scope-down updates) — all tracked in `docs/product/open-questions-web-v1.md` and `docs/design-session.md`.
> **Last synced:** 2026-06-18 — formal PRD update: default values, dual-label model (Main + Personal), document-level attachment limits, audience scope mandatory, AI Nudge follow-up trigger, comprehensive audit log.
> **Document:** Version 1.1 — MVP Scope · Product type: Lightweight Task & Delegation App (not a project-management tool) · Platform: Web-browser based (Responsive Web + a desktop-scoped PWA).
> **Previous PRD (mobile):** archived — superseded by this document.
> ⚠️ Still genuinely open — see `docs/product/open-questions-web-v1.md` (billing UI, readiness indicators, routing approach). Audit log scope is now resolved and added as §16.

---

## 0. Design Principles

These principles govern every feature, entity, and interaction. Read before designing or implementing anything.

- **Task-first.** The task is the hero. Projects are optional containers — a user never needs to create a project to use the app.
- **Minimal mandatory fields.** Creating any entity should take seconds. A task only needs **Title + Assignee + Due Date** to be published; everything else is optional, and even those three are only required to publish (see §5.1).
- **Fast capture over completeness.** Optimised for jotting things down quickly, not for exhaustive planning.
- **Voice-first.** Voice is the product's core differentiator (USP) — target 70–80% of all operations done via voice, not just task creation (see §9).
- **One continuous workspace, not pages.** The app is a single persistent workspace, not a set of routed pages — see §12.

Applies to every entity:

- Task (optional attachment)
- Subtask (optional attachment)
- Sticky Note
- Broadcast Notice (optional attachment)

---

## 1. Product Overview

BOLO is a lightweight, multi-vertical task and delegation app. The core is a fast, minimal task manager; the differentiated value comes from self-labelled project templates per vertical — e.g., NAAC Accreditation for Education, or statutory annual filing for CA/CS firms.

The same UI serves every domain — only templates and role labels change. The backend voice AI algorithm is customised per domain.

BOLO scales from a single individual jotting personal tasks all the way up to a team or firm running structured, compliance-heavy work — in their own language.

### 1.1 Launch Verticals

- **Education** — colleges, departments, NAAC/NBA accreditation workflows.
- **CA/CS Firms** — Chartered Accountant and Company Secretary practices, statutory filing compliance.

---

## 2. Target Users

- **Teams / Firms** — e.g., a college department, a CA/CS practice with multiple staff.
- **Individuals (optional)** — solo use; personal tasks and sticky notes; no project required.

---

## 3. Domain Model & Core Concepts

Mandatory fields are marked **(required)** — everything else is optional by design.

### 3.1 Entity Definitions

| Entity | Required (to publish) | Optional / Notes |
|---|---|---|
| **User** | Account | Has a preferred language in addition to system defaults (Hindi + English); login via Email OTP only (no SSO) |
| **Task** | Title, Assignee, Due Date | A **Draft** can be saved missing any of these — they are only required to transition Draft → Open. Optional fields have **predefined defaults** (see §3.4) — users are never required to manually populate them. Optional: priority, main label, description, attachments, evidence, subtasks, progress comments. |
| **Subtask** | Title, Assignee, Due Date | Child of a Task; same publish rule as Task; optional fields carry the same predefined defaults (§3.4); can **only** be created by the parent task's assignee; due date must be earlier than the parent's due date; cannot be assigned back to the parent task's own delegator (no assignment loops) |
| **Evidence** | File / photo | Proof attached to a task. Images and documents both allowed. **No task-level aggregate size limit** — document constraints (file size, file type) are managed at the document level only (see §3.5). |
| **Project Label** | Name | Two-tier label model (see §3.3): **Main Label** (set by assigner, visible to all users on the task) + **Personal Labels** (private per user, for individual filtering only) |
| **Sticky Note** | Text | Due date/time optional; personal — always private to the user regardless of role; can optionally be promoted into a task. **A Sticky Note with a due date automatically functions as a personal reminder** — there is no separate Reminder entity. |
| **Broadcast Notice** | Message text | One-to-many message posted to the Notice Board. Optional: audience scope, acknowledgement-required flag, attachment (doc or image). Character limit ~200 words. Expires after a fixed 1 day (not configurable). |

### 3.2 Roles

Roles are defined **per task, not org-wide**. The same user can hold different roles across different tasks. There are only two task-level roles:

| Role | Who |
|---|---|
| Delegator | The user who creates and assigns the task |
| Assignee | The user responsible for completing the task |

**Org-level standing:** at onboarding, each user gets a vertical-specific **profile/designation label** (Dean/HoD/Faculty for Education, Director/HoD/Employees for CA/CS) — this is for **display and analytics only**. The only **enforced** permission distinction at the org level is binary: **can send a broadcast notice, or cannot.** There is no hierarchy enforcement anywhere else:

- **Any user can assign a task to any other user**, regardless of designation — there is no "higher → lower only" validation. Skip-level assignment is explicitly allowed.
- Whether to maintain an internal reports-to / hierarchy tree (for analytics and org-structure views only, never for assignment validation) is an **engineering discretion** call, not a hard requirement either way.

### 3.3 Labels — Two-Tier Model

> ⚠️ **This supersedes D35 (2026-06-17 decision).** D35 established a fully-private Gmail-style model where every user's label was invisible to everyone else. The formal PRD update (2026-06-18) introduces a two-tier model: one shared Main Label plus private Personal Labels.

**Tier 1 — Main Label (shared)**
- Set by the **task assigner (Delegator)** only.
- Visible to **all users with access to the task** (assigner, assignee, and any org members who can view the task).
- Used for task organisation at the org/project level (e.g. "NAAC – Section 3", "GST Filing – Q2").
- One main label per task; can be updated by the assigner.

**Tier 2 — Personal Labels (private)**
- Each user (assigner or assignee) can maintain their **own private labels** on any task, independently of the Main Label.
- **Visible only to the user who created them** — never visible to anyone else.
- Used exclusively for **individual task segregation and filtering** (e.g. "Follow up", "Waiting on client").
- A user can have multiple personal labels on the same task.

**Subtask label inheritance:**
- A subtask gets its own independent Main Label (set by whoever created the subtask).
- If unset, the subtask inherits the parent task's Main Label.
- Personal Labels operate independently at every nesting level.

### 3.4 Default Values for Optional Fields

All optional fields in Tasks and Subtasks have **predefined system defaults** — users are never required to manually set them:

| Field | Default value |
|---|---|
| priority | `p3` (medium) |
| Main Label | None (blank) |
| description | Empty |
| attachments / evidence | None |
| Personal Labels | None |

Subtasks inherit the same defaults. Defaults are applied silently — no prompt shown unless the user explicitly edits the field.

### 3.5 Document-Level Attachment Constraints

Attachment limits are enforced **per document**, not aggregated across a task:

- **Allowed file types:** Images (JPG, PNG, HEIC) and documents (PDF, DOCX, XLSX).
- **Per-file size limit:** TBD — to be defined before the evidence upload feature is built. *(Previously a 25MB per-task aggregate was in place; this is removed per the 2026-06-18 PRD update. Exact per-file cap needs to be confirmed.)*
- **No task-level aggregate cap** — tasks and subtasks inherit document-level restrictions only.
- No limit on the number of attachments per task.

**Evidence storage & access (engineering):**
- Files are uploaded directly from the browser to S3 — they never pass through the API server.
- `fileUrl` in the DB stores the S3 object key, not a URL. A **pre-signed GET URL (15 min TTL)** is generated on demand whenever the file is accessed.
- Access is restricted to the task's assigner and assignee only — no other user can retrieve the file.
- Applies identically to main tasks and subtasks (a subtask is a Task row — same flow).

---

## 4. Roles & Permissions Matrix

Capabilities are scoped to a Task. A user can be a Delegator on one task and an Assignee on another. The permission logic is detailed in Section 5. The only org-level (non-task) permission gate in V1 is broadcast eligibility (§3.2, §7).

---

## 5. Task Rules & Business Logic

### 5.1 Creation & Assignment
- A **Draft** can be saved with any subset of fields filled in.
- Publishing (Draft → Open) requires **Title + Assignee + Due Date**. All other fields remain optional.
- A task becomes visible to the assignee **only after** it transitions to Open state.
- A task or subtask must be **accepted** by the assignee before work begins. There is no rejection path — the assignee can only accept.

### 5.2 Task Editing Rules

**The assigner (Delegator) can edit any field except the task title:**
- Assignee, due date, priority, label (their own only), description
- Write comments
- Attach attachment
- Send reminder to assignee
- Mark task as complete
- **Cannot** create subtasks

> The assignee is notified of any change made by the assigner.

**The assignee can:**
- Write progress comments
- Attach attachment
- Mark the task as complete from their end
- Create subtasks
- Apply their own private label (§3.3)

> The assigner is notified of any change made by the assignee.

### 5.3 Reassignment Rules
- A task can be reassigned by the **assigner (original creator) only**.
- The assigner can reassign to a new assignee and remove the old one.
- A task **cannot be reassigned** once subtasks have been created.

### 5.4 Completion & Cancellation
- A main task can only be marked complete when **all its subtasks (if any) are complete**. If a subtask isn't completed before the parent's due date, the parent cannot be completed and enters Overdue.
- If a main task is cancelled, all its subtasks are also cancelled.
- Task status (Open / Cancelled / Complete) can be changed **only by the assigner**.
- Task progress can be updated by **both** the assigner and the assignee.
- A task **cannot be cancelled** once it is Completed, and **cannot be reopened once Completed (DoneD) — this is permanent and terminal**, including all of its subtasks.
- A task can be **deleted only by the assigner**.
- **Both** assignee and assigner mark the task complete (DoneA → DoneD).
- Assigner is notified when the assignee marks complete (DoneA).
- The task is **archived** when the assigner marks complete (DoneD). Archiving is **not** applicable to subtasks.
- A due-date change on a parent task does **not** cascade to its subtasks — each subtask's due date is managed independently by whoever delegated that specific subtask.
- **Status indicators:** On Time, Overdue, Due Today, Due Tomorrow, Days Since Started.
- **Tasks Delegated** — per-task options: send reminders, add comments, attach evidence, mark as complete.
- **My Tasks / Tasks Assigned** — options: write comments, attach evidence.

### 5.5 Subtask Rules
- Subtasks follow the same rules as tasks, with the **parent task's assignee acting as the subtask's assigner**.
- Can only be created by the assignee of the parent task.
- A subtask's due date must be **earlier than the parent task's due date** — enforced at creation.
- A subtask **cannot be assigned back to the parent task's own delegator** (no assignment loops).
- **Subtask title cannot be edited** once set.
- Sub-assignee can edit due date, comments, attachments, and description.
- No hard limit on subtask nesting depth. Maximum subtask count per parent is not yet defined.

### 5.6 Sticky Notes & Self-Tasks
- Created, edited, and deleted **only by the creator (self)**.
- Every field of a self-task can be changed.
- Upcoming sticky reminders with imminent due times appear at the top with a **red border**.
- A Sticky Note with a due date **automatically** acts as a personal reminder — no separate opt-in, no standalone Reminder entity.

### 5.7 AI Behaviour
- **AI Nudge** (implemented as scheduled cron triggers, not ML) has **two trigger types (redesigned 2026-07-06, backend built 2026-07-10 — Periodic removed/merged into Follow-up), covering Task, Subtask, StickyNote, and Broadcast:**
  1. **Follow-up** — fires every 6h, continuously (no office-hours gate — see below). 5 conditions, each with its own action button, none capped/escalating:
     - (a) Task not yet accepted → assignee → `Accept Task`
     - (b) Task accepted, no progress update since → assignee → `Add Comment`
     - (c) Comment posted, no reply from the other party → whoever didn't reply → `Add Comment`
     - (d) Assignee marked `DONE_A`, assigner hasn't confirmed `DONE_D` → assigner → `Mark Complete`
     - (e) All subtasks `DONE_D` but parent still open → assigner → `Mark Complete`
     - All 5 track a lifetime skip counter in DB for visibility, but enforce **no cap and no escalation** — (d)/(e) explicitly have no org-hierarchy escalation either, since there's nothing above the assigner in this model.
  2. **Due-date proximity** — fires every 3h, continuously. The **only** type with a real skip cap + escalation, and now polymorphic across **Task, StickyNote, and Broadcast** (Broadcast added 2026-07-06):
     - **Task** (already-accepted, `IN_PROGRESS`/`OVERDUE` only): `Add Comment` + `Skip` + `Open`. **Skip is a user-clicked button** (`POST /nudges/:id/skip`), not something the sweep increments automatically. Cap: 3 for due-today, 1 for overdue — in practice an overdue task starts at last-chance immediately (zero grace skips). **Last-chance state** (skip count == cap): `Skip` disappears, replaced by a warning that this will escalate if not actioned; only `Add Comment`/`Open` remain — any comment resolves it (no separate "remind me later," Add Comment already covers that). **Escalation**: next sweep, if the task still hasn't reached at least `DONE_A` → one-time in-app + email to the **assigner**, never repeats. If it reached `DONE_A`, it naturally drops out of the sweep (no longer `OPEN`/`IN_PROGRESS`/`OVERDUE`) — no escalation. The assignee is only ever held to `DONE_A`; `DONE_D` is the assigner's responsibility, not something the assignee is threatened over.
     - **StickyNote**: `Skip` only, no cap — self-limits once the due date's calendar day ends.
     - **Broadcast**: acknowledge/`Skip`, cap of **3, enforcement only, no escalation** (no sender-escalation target — exceeding the cap just removes Skip, forcing acknowledgment). Self-limits at the broadcast's normal 1-day expiry regardless.
- **Office-hours gating removed entirely (2026-07-06).** Was 9am–6pm IST; dropped since it assumed one institution's business hours, which doesn't generalize across verticals, timezones, or individual login patterns. The sweep now runs continuously — cadence comes purely from each type's own gap (Follow-up 6h/~4 fires per day, Due-proximity 3h/~8 fires per day). Times themselves stay fixed in code for now; a per-user configurable schedule is a future feature-flag-service item, not built yet.
- **Consequence of removing office hours, accepted as intentional:** Task due-proximity's caps (3 due-today / 1 overdue) were sized assuming ~3 fires/day; at 8 fires/day the cap now exhausts same-day, within hours. Matches "overdue is urgent," just faster than originally modeled.
- **Nudge configuration rules:**
  - Nudge rules are configurable and extensible by an admin/configurator (future feature-flag service — not built yet, intervals/caps are hardcoded constants for V1).
  - Multiple nudge types can be active for the same task simultaneously.
  - **Cross-type duplicate suppression (W84, corrected 2026-07-10):** dedup keyed on `recipientId`+`entityType`+`entityId`, not just `entityType`+`entityId`. Recipient-scoped because Broadcast has many recipients per entity — an entity-only check would let one recipient's nudge suppress the notification for everyone else acknowledging the same broadcast (caught during the backend build, before shipping). Applies uniformly to both remaining types.
  - **Daily nudge cap — still descoped.** Not being built.
  - **Panel behavior (redesigned 2026-07-06, backend built 2026-07-10):** single unified nudge list, not split screens — two independent filters (Type: All/Follow-up/Due-proximity; Entity: All/Task/Subtask/StickyNote/Broadcast), combinable. **Blocking**: the panel cannot be closed while any Due-proximity item is unresolved (skip it if not at last-chance, or resolve it if at last-chance) — Follow-up items never block closing. **Skip All** bulk-skips every currently-skippable item at once; disabled if any single item is at last-chance — enforced both client-side and server-side (`POST /nudges/skip-all` rejects with 409 rather than trusting the client-side disable alone).
- AI assists in parsing voice commands and populating task fields intelligently.
- AI algorithm is customised per vertical (Education vs CA/CS).

---

## 6. Task State Machine

### 6.1 States

| State | Meaning | Terminal? | Notes |
|---|---|---|---|
| Draft | Missing one or more of title/assignee/due date | No | Never visible to the assignee; creator can delete directly |
| Open | Fully defined, assignee notified, work not yet started | No | Entry point after Draft resolves |
| In Progress | Assignee has explicitly started work | No | System triggers: Due Today / Due Tomorrow / Overdue |
| Overdue | Due date passed without completion | No | System-only entry; notifies the delegator; task remains actionable |
| DoneA (Soft Complete) | Assignee self-reported complete | No | Delegator notified; can still be cancelled |
| DoneD (Complete) | Assigner marked complete | Hard ✅ | Task archived and removed from the list — **permanent, cannot be reopened** |
| Cancelled | Creator terminated the task | Hard ✅ | No transitions out; assignee notified if task was Open / In Progress / Overdue |

There is **no rejection state** — the assignee can only accept, never reject.

### 6.2 Transition Table

| From | To | Who | Condition / Guard |
|---|---|---|---|
| — | Draft | Anyone in tenant | Voice or UI — any subset of fields, even none |
| Draft | Open | Anyone in tenant | Title + Assignee + Due Date all present; task becomes visible to assignee |
| Open | In Progress | Assignee | Assignee accepts the task and explicitly starts work |
| In Progress | Open | Assignee | Task is reassigned |
| In Progress | DoneA | Assignee | Assignee self-reports complete; no approval required; assigner notified |
| In Progress | DoneD | Assigner | Assigner self-reports complete; no approval required; assignee notified |
| Open | Overdue | System | Due date passes, task not accepted / started; notifies assignee + delegator |
| In Progress | Due Today | System | Due date is today while in progress; notifies assignee + delegator |
| In Progress | Due Tomorrow | System | Due date is tomorrow while in progress; notifies assignee + delegator |
| In Progress | Overdue | System | Due date passes while in progress; notifies assignee + delegator |
| Overdue | DoneA | Assignee | Assignee completes after deadline; overdue flag cleared; assigner notified |
| Overdue | DoneD | Assigner | Assigner self-reports complete after deadline; assignee notified |
| Overdue | In Progress | Assigner | Reset after due date extended or reassigned; assignee notified |
| Done | Archive | Original Creator | Task is archived — terminal, no reopen |
| Draft / Open / In Progress / Overdue | Cancelled | Assigner | Assigner terminates task; assignee notified unless task was in Draft |

---

## 7. Broadcast Notice Rules

- Created, edited, and deleted by the **sender only**.
- Appears prominently on the landing page (Notice Board) for **1 day, fixed, not configurable**.
- **Character limit: ~200 words.**
- **Audience Scope is mandatory** — a broadcast cannot be published without a defined audience (Department + Role level). There is no "send to everyone" without explicitly selecting the scope.
- A new member who joins **after** a broadcast was posted **still sees it**, as long as it's still inside its 1-day active window.
- **Single image attachment allowed** — only one image per broadcast notice; multiple images are not permitted. Optional doc or image attachment.
- **Acknowledgement:** when a recipient clicks the Acknowledge button, the read/acknowledgement count is incremented. The sender sees only the **aggregate read count** (no per-recipient breakdown of names or timestamps). The acknowledge counter accurately reflects the number of users who have acknowledged.
- Broadcasts require an active internet connection to publish (no offline support — see §13).

**Broadcast image storage & serving (engineering):**
- Image uploads follow the same S3 flow as evidence (browser → S3 directly, never through API server).
- **Image is rendered inline in the notice feed — the user does not click to open it.** This is different from evidence/audio which are click-to-open.
- At publish time the server generates a **pre-signed GET URL with 25h TTL** (1h buffer beyond the 1-day broadcast lifetime) and stores it in `BroadcastNotice.imageUrl`. The feed returns this URL directly — no per-request URL generation needed.
- Access is controlled at the API level (audience dept + role filter) — not at the S3 URL level.

### 7.1 Broadcast Permissions
- Eligibility to send a broadcast is the **one enforced org-level permission** in V1 (binary: can or cannot) — see §3.2.
- Audience targeting is by **Department + Role level** — this field is **mandatory** at publish time.

---

## 8. Dashboard & Task Views

### 8.1 Five Task Tabs

Per the workspace-first interaction model (§12), these are **workspace shortcuts that change the active workspace state** — not routed pages.

| Tab | Description | Sub-tabs |
|---|---|---|
| Tasks Delegated | Tasks the logged-in user has assigned to others | Needs Attention / All Tasks |
| Assigned to Me (My Tasks) | Tasks assigned to the logged-in user | Needs Attention / All Tasks |
| Needs Attention | Cross-view of tasks requiring action | Delegated / Assigned |
| By Label / Archive | Tasks grouped by the viewing user's own private label (§3.3) | Project Labels |
| Stickies & Reminders | Personal sticky notes and self-reminders | Pinned / Unpinned |

### 8.2 Task Information

> ⚠️ **Still open — W15.** No fields/actions for the task card or detail panel have been specified in writing. Direction so far is to refer to the Figma screens — this needs a Figma pull, not more PRD text.

### 8.3 Analytics Board
- Dean / Director / HoD: can view all faculty/employees in their department/firm and their **task completion effectiveness**, driven by the org chart/structure.
- Placeholder formula (final formula still TBD, but this unblocks development):
  `(( #OnTime × 1 + #BeforeTime × 2 + #Overdue × −1 ) / TotalTasks) × 100`
- Refresh: **periodic, once a day** — not real-time.

---

## 9. Voice Input — The Product's USP

### 9.1 Availability
Available globally — voice is not tied to whatever workspace state is currently showing. A command can switch the workspace to a completely different view regardless of current context (e.g. viewing Assigned Tasks, user says "Show overdue tasks" → workspace switches).

### 9.2 How Voice Works
- System microphone is used (browser mic permission required).
- User presses the mic button **or** presses **SPACE** to begin speaking; presses again to stop.
- **The provided Voice AI SDK owns the entire interpretation pipeline** — live on-screen transcription display, transcription, and intent/field extraction are all the SDK's responsibility, not ours.
- Each mic press is a **fresh, isolated session** — never cumulative. A second press starts a brand-new audio note; it does not append to or merge with the previous one (retakes **override**, they don't merge).
- Low-confidence words/fields are highlighted to the user so they can fix the rest.
- The mic is **context-aware, not panel-restricted** — it can create or act on any entity type regardless of which panel/screen it was pressed from.
- Our system receives a structured handoff from the SDK: `{ intent, entityType, operation, jsonBody }`. We map `intent` → the corresponding REST API call. See `docs/architecture/diagrams.html` §9–10 for the full flow.

### 9.3 Voice Command Scope
Voice covers **full CRUD, search, and navigation** — not just task creation:

- **Create / Read / Update / Delete** on: Task (incl. Subtask), Sticky Note (incl. Reminder), Broadcast Notice, Comment, and Project Label.
- **Search** — full-text, across everything the user can access.
- **Navigation** — switching the active workspace state (§12), e.g. "show me overdue tasks."
- **Target: 70–80% of all operations** in the product done via voice.
- **Every destructive voice operation (e.g. "delete task X") requires a confirmation step before executing.** There is no undo/redo anywhere in the system — this confirm step is the only safety net.
- Voice commands enforce the **exact same RBAC/ownership checks as the UI** — e.g. a user cannot voice-delete a task they don't own. Enforced at the API layer, same as every other path in.

### 9.4 Voice-Assisted Task Creation
- If 'Create Task' is the command but required fields are missing, the user can press the mic again to add information verbally, or fill fields via keyboard.
- AI assists in completing form fields based on spoken input.
- On successful input, user clicks 'Create Task'; a success confirmation is displayed.

### 9.5 Multilingual Support
- Default languages: **Hindi and English** (Hinglish mixed supported).
- Users can set a preferred language in their profile.
- **Cross-language task viewing is supported.**

### 9.6 Voice Data Storage

Every voice-initiated task creation produces a `VoiceRecording` record. This is separate from the task fields the SDK extracted — it stores the raw session data for audit, replay, and analytics.

| Data | Stored | Notes |
|---|---|---|
| Raw transcript | ✅ Always | Verbatim multilingual text from SDK — unfiltered, not LLM-processed |
| Detected language | ✅ Always | e.g. `"hi"`, `"en"`, `"hi-en"` (Hinglish) |
| AI confidence score | ✅ Always | Overall extraction confidence 0.0–1.0 from SDK |
| Audio clip | ⚙️ Opt-in (W37) | Stored in S3 if user opts in; null otherwise |
| Audio retention | — | 6 months to 1 year (W41) — EventBridge cleanup |
| Encryption at rest | — | If easily achievable; otherwise V2 (W44) |

**Access:** assigner and assignee of the task only (W38).
**Source of truth:** the final edited task fields — not the audio or transcript (W39). If audio is lost, the task is unaffected.
**Two-phase save:** transcript is saved atomically with the task creation DB transaction. Audio upload to S3 is async and non-blocking — task creation is never delayed waiting for audio.
**Applies to:** main tasks and subtasks equally (a subtask is a Task row — same VoiceRecording table).

---

## 10. Notifications

All notifications are delivered **in-app**, via polling (no WebSocket/SSE — client polls on a configurable interval). **Reminder/due-date types** (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`) **also send email** via the existing nodemailer/SMTP setup (2026-07-03, corrected — was previously documented as in-app only). All other types remain in-app only. WhatsApp is out of scope for all types.

| # | Event | Trigger | Who is Notified | Notes |
|---|---|---|---|---|
| 1 | Task Assigned | Assigner | Assignee | Fires on Draft → Open; assigner not notified |
| 1a | Task Accepted | Assignee | Assigner | When assignee presses the acceptance button |
| 2 | Task Reassigned | Assigner | New assignee, previous assignee, creator | Previous assignee informed of removal; new assignee informed of task |
| 3 | Task Edited (by assigner) | Assigner | Assignee | Due date, label, priority, assignee, attachment, description. Not fired for Draft tasks |
| 3a | Task Edited (by assignee) | Assignee | Assigner | Assignee adds comments or attaches evidence |
| 3b | Subtask Created | Assignee (parent) | Sub-assignee | Parent task assignee creates the subtask |
| 3c | Subtask Edited (by subtask assigner) | Sub-task assigner | Sub-task assignee | Due date, label, priority, assignee, attachment, description |
| 3d | Subtask Edited (by subtask assignee) | Sub-task assignee | Sub-task assigner | Sub-task assignee adds comments / attaches evidence |
| 4 | Task Commented | Assignee + Assigner | The other party | Commenters do not self-notify |
| 5 | Task Marked DoneA | Assignee | Assigner | No self-notification for assignee |
| 6 | Task Marked DoneD | Assigner | Assignee | No self-notification for assigner |
| 7 | Task Cancelled | Assigner | Assignee + sub-assignee (if any) | Only if Open / In Progress / Overdue; no notification for Draft cancellation |
| 8 | Due Date Proximity (one-shot) | System | Assignee + Assigner | Fires **once** when a task becomes Due Today / Due Tomorrow / Overdue (`TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE`). |
| 8a | ~~AI Nudge — Periodic~~ | — | — | **Removed 2026-07-06** — merged into Follow-up once Follow-up gained per-task action buttons and lost its cap; no structural difference remained. |
| 8b | **AI Nudge — Follow-up** | System | Per-condition — assignee (not-accepted, no-progress, unanswered-comment) or assigner (`DONE_A` awaiting `DONE_D`, subtasks done awaiting parent close) | **Redesigned 2026-07-06 — 5 conditions**, each with its own action button (`Accept Task`/`Add Comment`/`Mark Complete`), covering Task + Subtask. Fires every 6h, continuously (no office hours). Skip counter tracked in DB for all 5, but **no cap, no escalation** on any of them. |
| 8c | **AI Nudge — Due Date Proximity** (`AI_NUDGE_DUE_PROXIMITY`) | System | Task: **assignee** routinely, **+ assigner once cap exhausted** (escalation, one-time). StickyNote: owner only, no escalation. Broadcast: audience member only, no escalation | **Polymorphic — Task, StickyNote, and Broadcast** (Broadcast added 2026-07-06). Fires every 3h, continuously (no office hours). The only type with a real skip cap: Task (3 due-today / 1 overdue, escalates to assigner if not at least `DONE_A` by next window), Broadcast (3, enforcement only, no escalation), StickyNote (no cap, self-limits at day-end). Last-chance state (Task only) removes the Skip button in favor of a warning + `Add Comment`/`Open`. |
| 9 | ~~Escalation Triggered~~ | — | — | **Removed — there is no escalation engine in V1.** Folded into event #8c (AI Nudge — Due Date Proximity). |
| 10 | Subtask Marked DoneA | Sub-task assignee | Sub-task assigner | No self-notification |
| 11 | Subtask Marked DoneD | Sub-task assigner | Sub-task assignee | No self-notification |
| 12 | Broadcast Posted | User | All tenant members in scope | Poster does not self-notify |
| 13 | Reminder Fired (one-shot) | System | Reminder owner only | Fires **once** from the StickyNote's due date — personal, not linked to task state. See row 8c for the recurring AI Nudge layered on top of this. |

---

## 11. Authentication & Settings

- **Login:** Email + OTP only — **no SSO, no "Sign in with Google."**
- **Session:** one-time login — stays logged in until the user explicitly logs out. No idle timeout, no refresh-token rotation.
- **Onboarding:** tenant sends an Excel sheet (name, email, phone, designation, dept, role); we load it into the DB. Post-onboarding member additions go through an **admin portal** plus an email-link + OTP login (not purely a re-run of the Excel import).
- **Settings sections:** Profile (editable), Display (Light / Dark / System theme), Help & Support (submit a support issue), About (version & info), Logout (with confirmation + session clearance).

---

## 12. Navigation & UI — Workspace-First, Not Page-Routed

> Source: `Doc/Bolo Workspace Architecture v1.pdf`. Full technical model in `docs/architecture/system-design.md` §0.

BOLO is **one persistent workspace**, not a set of pages the user clicks between. The model is **Intent → Workspace**, not **Navigation → Page**:

- Every interaction (view tasks, create a task, view notices, search, view reports) renders inside one center **Workspace Canvas**. The user never "leaves" the workspace.
- **Voice is global** — a command can switch the workspace to a different view from anywhere, regardless of current screen.
- **The URL stays constant** for primary workflows — the feel is "I am inside Bolo," not "I am inside the Tasks page."
- **Left and right panels are static for the whole session** — they only ever provide context, shortcuts, filters, and notifications. Clicking an item in them updates the Workspace Canvas in place; it does **not** navigate to a new page.

**Layout:**

| Region | Contents |
|---|---|
| Top Bar | Logo, search, readiness indicators *(scope TBD — W64)*, notifications, user profile |
| Left Panel (static) | Assigned tasks, delegated tasks, labels, workspace shortcuts |
| Workspace Canvas (dynamic) | The only region that changes — renders the active workspace state |
| Right Panel (static) | Sticky notes, notices, AI suggestions, contextual information |
| Bottom Composer | Voice input, text input, live transcription — always visible |

The exact routing implementation (zero client-side routing vs. a thin single shell route for refresh-safety) is an internal engineering decision, still pending.

---

## 13. Platform

**Decided, final:** both **Responsive Web** and a **desktop-scoped PWA** ship in V1.

- **Responsive Web** — runs in the browser on desktop and mobile, one codebase.
- **PWA** — installable on **desktop screens only** (not offered on mobile). This is an installable app **shell** — it does **not** provide offline functionality (see below); its purpose is installability/desktop-app feel only.
- **No offline support in V1** — an active internet connection is required for every action, voice or otherwise. This may be revisited in V2.
- **Mic note:** system mic access is required for voice; browser apps require an explicit mic permission prompt.
- **Desktop shortcut:** app will offer an option to create a desktop shortcut; opens in a full-screen browser tab/PWA window.

---

## 14. Required Operational Services (V1)

> Source: filtered from `Doc/Fatafat_Development_Proposal.md` §4.1 ("Typical Operational Service Categories") down to what the **current web-based V1** actually needs. All of these are **client-owned costs** — setup/configuration assistance only, not absorbed into development cost.

### Needed for V1

| Category | Service | Why |
|---|---|---|
| Cloud account | AWS (or equivalent) | Hosts all V1 infrastructure |
| Compute | EC2 (or equivalent) | Runs the backend API |
| Managed database | RDS PostgreSQL (or equivalent) | Primary relational datastore, RLS-enabled |
| Object storage | S3 (or equivalent) | Evidence files + optional voice audio, via pre-signed URLs |
| Load balancer | ALB (or equivalent) | HTTPS termination, traffic distribution |
| Networking | DNS, NAT Gateway, data transfer | Outbound connectivity and routing |
| Search service | OpenSearch (or Postgres `tsvector` fallback if scale is small) | Full-text/voice search across task data (§9.3) |
| Scheduler | EventBridge + Lambda (or equivalent) | Reminders, due-date triggers, AI Nudge (§5.7) |
| Monitoring & logging | CloudWatch + Sentry (or equivalent) | Error tracking, infra metrics |
| Transactional email | SES (or equivalent) | OTP delivery (§11), onboarding greeting emails |
| Git / source control | GitHub (or equivalent) | Source code + CI/CD |
| CDN *(optional)* | CloudFront (or equivalent) | Only if performance testing demands it |
| Payment / billing provider | TBD (e.g. Razorpay, Stripe) | Per-seat billing module is confirmed in scope (§ — see open-questions W60); provider not yet selected |

### Not needed for V1

| Category | Why it's excluded |
|---|---|
| App Distribution (Google Play Console, Apple Developer Program) | No native mobile app in V1 — separate Mobile PRD, future phase |
| Push notification service (FCM / APNs) | All notifications are in-app only, delivered via polling (§10) |
| SMS OTP provider | Login is Email OTP only — no phone-based auth |
| WhatsApp Business API | WhatsApp notifications are explicitly out of scope for V1 |

---

## 15. Audit Log & Activity Tracking

> **W63 resolved (2026-06-18).** Comprehensive audit logging is in scope for V1. Objective: traceability, accountability, compliance, and historical tracking of all critical user and system actions.

The system must capture audit records for the following activities:

### Task Management
- Task Created · Task Updated · Task Deleted
- Task Assigned / Reassigned
- Task Status Changed · Task Priority Changed · Task Due Date Modified
- Task Archived / Restored
- Main Label Added / Updated / Removed

### Subtask Management
- Subtask Created · Subtask Updated · Subtask Deleted
- Subtask Status Changed · Subtask Assignment Changed

### Document / Evidence Management
- Document Uploaded · Document Updated · Document Deleted
- Document Downloaded · Document Accessed / Viewed

### Broadcast Notice
- Broadcast Created · Updated · Deleted · Published
- Broadcast Acknowledged
- Broadcast Read / View Event

### Audience Scope
- Audience Scope Created · Modified
- Audience Scope Assignment Changed

### User Activity
- Login · Logout
- Profile Updated
- Role Changed · Permission Changed

### Audit Log Rules
- Every audit record captures: `actor (userId)`, `action`, `entityType`, `entityId`, `tenantId`, `timestamp`, `before/after snapshot (where applicable)`.
- Audit records are **immutable** — cannot be edited or deleted by any user.
- Scope for CA/CS vertical may require longer retention for compliance; exact retention period TBD before first CA/CS firm onboarding.

---

## 16. Out of Scope (MVP)

- Mobile apps — iOS and Android (separate Mobile PRD)
- Moments
- Template marketplace / third-party template authors
- Third-party integrations (ERP / LMS / accounting tools)
- Public project links and member re-sharing
- Heavy PM features: Gantt charts, resource planning, time tracking
- Predefined project templates (V2.0 only)
- WhatsApp notifications (out of scope for all types). **Correction (2026-07-03):** email IS a notification channel for reminder/due-date types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`) — not OTP/greeting-only as previously stated here. All other notification types remain in-app only.
- Whiteboards, Evidence Vault, Academic Calendar
- Escalation engine — there is no escalation logic beyond the AI Nudge triggers (§10)
- Offline support — no offline mode anywhere in V1, including in the PWA (§13)
- Task rejection — assignee can only accept, never reject
- Per-recipient audit/breakdown of broadcast acknowledgements (sender sees count only)

---

*End of PRD — Version 1.1 · last updated 2026-06-18 · reconciled through five rounds of clarification.*
