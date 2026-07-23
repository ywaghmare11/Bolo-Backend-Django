# BOLO — Testing Strategy

> **Last updated:** 2026-06-20 — audit log added to V1 scope (W63 resolved). Web-first; native mobile testing deferred with the Mobile PRD. No rejection / `requiresEvidence` tests (W-C1 resolved).

---

## Philosophy

- Test behaviour, not implementation.
- Prefer integration tests over unit tests for business logic (the DB layer is part of the logic).
- Unit tests for pure functions and complex algorithms.
- No mocking the database in integration tests — use a real test DB.
- Tests must run in CI on every PR.

---

## Test pyramid

```
         ┌───────────┐
         │  E2E / UI │  ← few; test critical user flows only
         ├───────────┤
         │Integration│  ← most business logic tests live here
         ├───────────┤
         │   Unit    │  ← pure functions, utils, complex algorithms
         └───────────┘
```

---

## Unit tests

**What to unit test:**
- Pure utility functions (date formatting, string transforms)
- Complex domain logic isolated from I/O (e.g., state machine transition validator)
- i18n key resolution helpers

**What NOT to unit test:**
- Functions that are just DB queries with no logic
- React components in isolation (prefer integration/E2E for UI)
- Anything that requires mocking more than one dependency

**Framework:** Jest (Node) / Vitest (web)
**Location:** `tests/unit/` next to source or co-located as `*.test.ts`

---

## Integration tests (API / backend)

**What to test:**
- Every API endpoint: happy path + key error cases
- Tenant isolation — a request with org A's token must never return org B's data
- Business rules: task re-assignment guard (any subtask exists), task title immutability, two-step completion (assignee done_a → assigner done_d), parent cannot be done_d until all subtasks complete, parent cancel cascades to subtasks
- Auth middleware: unauthenticated requests rejected, expired tokens rejected
- Role-based access: only the assigner can change task status / reassign / delete

**Setup:**
- Use a dedicated test PostgreSQL database (not mock)
- Seed minimal data per test using factory helpers
- Reset (truncate) between test files
- Run migrations before the test suite

**Framework:** Jest + Supertest (or equivalent for the chosen backend framework)
**Location:** `tests/integration/`

---

## Critical test cases (must exist before shipping)

| Feature | Test case |
|---|---|
| Task creation | Draft saves with any fields; **title + assigneeId + dueDate required at Draft → Open** (W-C3 resolved) |
| Draft → Open | Task becomes visible to assignee only once it reaches `open` |
| Task assignment | Assignee receives notification #1 on Draft → Open |
| Task acceptance | Task moves to `in_progress` only after assignee accepts |
| Two-step completion | Assignee `done_a` notifies assigner; assigner `done_d` archives the main task |
| Parent/subtask gate | Parent cannot reach `done_d` until all subtasks complete; cancelling parent cancels subtasks |
| Task re-assign guard | Returns 409 if any subtask exists |
| Task title immutable | PATCH on title field returns 400 (task and subtask) |
| Tenant isolation | Tenant A cannot read/write Tenant B data (every entity) |
| Broadcast scoping | Gated by binary "can broadcast" flag — not by org-role level. HoD / Dean audience targeting per PRD §7.1 (W22 resolved) |
| Sticky note privacy | Sticky notes not visible to other users via any endpoint |
| Reminder privacy | Reminders not visible to other users via any endpoint |

> Removed for V1: *Task rejection* (no rejection state — W-C1), *Evidence required* (`requiresEvidence` field dropped). **Audit log added back in V1 (W63 resolved 2026-06-20)** — integration tests must cover: AuditLog rows written on task create/update/delete/status-change; assigner/admin can read audit-log endpoint; non-admin cannot.

---

## Voice Command Manual Test Plan

> One row per spoken command. Columns: the **intent** it should classify as (`bolo-backend/src/voice/intent.js`), the **title/key value** it should produce (for creation intents) or the key resolved param (for action intents), the **frontend effect** (`bolo-web` dispatch), the **page/component** that renders it, any **filters/sorting** applied, whether a **confirm dialog** is required (no undo), and notes on RBAC/edge cases.
>
> **Prerequisite:** `OPENAI_API_KEY` must be set in `bolo-backend/.env` — without it everything falls back to `deterministicFallback()`, which only recognizes the original 10 intents (see Known Limitation, `open-questions-web-v1.md` §22). All rows below assume the GPT path is live.
>
> **Legend:** 🔴 Confirm required (destructive, no undo) · 🟡 Needs disambiguation/attention · 🟢 Fires directly · ⚪ Not a real intent (mic mechanic / graceful decline)
>
> All ~70 example commands below were executed against the real classifier (not assumed) with realistic context per row, repeated until stable — stable pass rate 68/70, with the remaining 2 documented as benign in the Known Limitations tracker rather than bugs. The defects found and fixed while producing this table are logged in `changelog.md` (root) under the 2026-07-21 entries, not repeated here — this table is the living regression reference, the changelog is the historical record of what was wrong before it passed.

### 1. Global mechanics

| # | Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|---|
| G1 | *(press mic, speak, press again)* | ⚪ n/a | — | Start → stop capture → classify fires | `VoiceComposer` | — | 🟢 No | Standard toggle |
| G1b | *(press mic, speak, pause mid-sentence, keep talking, press again once)* | ⚪ n/a | — | Classify fires exactly once, after the second press | `useVoice.ts` | — | 🟢 No | Silence/pause no longer auto-fires classify — gated behind an explicit `stopRequested` flag set only by pressing mic/SPACE again |
| G2 | *(press mic mid-command, release, press again, speak something new)* | ⚪ n/a | — | Second session is a clean slate | `useVoice.ts` | — | 🟢 No | First transcript never merges into the second |
| G3 | *(disconnect network)* | ⚪ n/a | — | Mic disabled, "Voice unavailable offline" | `VoiceComposer` | — | 🟢 No | SPACE + click both no-op |
| G4 | "Create a task for Rohit" *(spoken while on Sticky Wall)* | `create_task` | *(as spoken)* | Opens task review — not a sticky | `ReviewConfirmTask` | — | 🟢 No | Mic is context-aware, not panel-restricted |
| G5 | "Create a task for Vedanttt" *(mangled name)* | `create_task` | *(as spoken)* | Assignee field → 🟡 needs-attention, match-% badge | `ReviewConfirmTask` | — | 🟢 No | Create disabled until resolved |
| G6 | "Create a task" *(nothing else)* | `create_task` | `""` (empty) | Empty form opens | `ReviewConfirmTask` | — | 🟢 No | Saves as **Draft** on confirm |
| G7 | *(open a review form via voice, click Back without confirming)* | ⚪ n/a | — | Draft discarded, no API call | any review form | — | 🟢 No | — |
| G8 | "Mark complete" *(backend down)* | `task_action` | `action: complete` | Red Toast reports failure | current page | — | 🔴 Yes | Confirm dialog still shows; the POST after confirm fails and surfaces a Toast |
| G9 | "Delete this" *(task outside your RBAC scope)* | `task_delete` | — | 403 Toast, same as UI | current page | — | 🔴 Yes | Never reveals whether the task exists |
| G10 | "Show whiteboards" / "open evidence vault" / "escalate this" / "send this on whatsapp" / "show NBA readiness" | `out_of_scope` | `feature: <name>` | Toast: "*Feature* isn't available in BOLO yet." | current page | — | 🟢 No | Deterministic catch — never depends on GPT guessing right |
| G11 | "Mark this done" *(nothing open)* | `task_action` | — | AMBIGUOUS: "Which task? Open it first or say its title." | floating prompt | — | 🟢 No | Suggestion chips shown |
| G11b | "Mark this done" *(on Task Detail for task X)* | `task_action` | `action: complete` | Resolves to X directly | `TaskDetail` | — | 🔴 Yes | `context.current_task_id` used, no prompt |
| G12 | "Delete the NAAC report task" *(2 tasks share that title)* | `task_delete` | — | `DISAMBIGUATE` list (title + assignee + due) | `EntityDisambiguationList` | — | 🔴 Yes *(after pick)* | Disambiguates **before** any confirm dialog |
| G13 | *(any delete/cancel command)* | `task_delete` / `task_cancel` / `delete_*` | — | `ConfirmDialog` always shown first | `ConfirmDialog` | — | 🔴 Yes | The only safety net — no undo anywhere |
| G14 | "निकमसाठी AGM minutes तयार करा उद्या पर्यंत" *(Marathi)* | `create_task` | `Prepare AGM minutes` | Task created; view later in English UI | `ReviewConfirmTask` | — | 🟢 No | Devanagari renders correctly; cross-language viewing supported |
| G15 | "Assign Priya to file MGT-7" *(2 users named Priya)* | `create_task` | `File MGT-7` | Assignee field opens **full directory** picker, 🟡 needs-attention | `ReviewConfirmTask` → `AssigneePicker` | — | 🟢 No | Never guesses between homonyms |
| G16 | *(silence, or off-topic speech)* | `unknown` | — | Neutral "couldn't understand" + suggestion chips | floating prompt | — | 🟢 No | Never an error screen |

### 2. Task & Subtask

**Create**

| Command | Intent | Title Generated | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Create a task for Priya — submit the NAAC report by Friday" | `create_task` | `Submit NAAC report` | Form pre-filled, "Ready to activate" | `ReviewConfirmTask` | — | 🟢 No | title/assignee/due all present |
| "Create a task" | `create_task` | `""` | Empty form, Draft-eligible | `ReviewConfirmTask` | — | 🟢 No | — |
| "Remind Rohit to submit fee receipts tomorrow" | `create_task` *or* `create_reminder` | `Submit fee receipts` | SDK resolves Task vs. own Sticky | `ReviewConfirmTask` / `CreateStickyNote` | — | 🟢 No | Ambiguous by design — no voice "undo" if it resolves wrong |
| "Assign it to myself, due today" | `create_task` | *(as spoken)* | Self-assignment allowed | `ReviewConfirmTask` | — | 🟢 No | Any-to-any, no hierarchy check |
| "…due yesterday" *(past date)* | `create_task` | *(as spoken)* | Due-date field → 🟡 error | `ReviewConfirmTask` | — | 🟢 No | Due date must be present/future |
| "Assign Xyzabc to…" *(no such user)* | `create_task` | *(as spoken)* | Toast: "no such user in your organization" | `ReviewConfirmTask` | — | 🟢 No | Never auto-creates or fuzzy-guesses |
| "Assign a task to Priya to complete NBA certification" *(assignee mid-sentence)* | `create_task` | `Complete NBA certification` | Form pre-filled, title clean | `ReviewConfirmTask` | — | 🟢 No | Title no longer keeps "Priya to" stuck to the front |
| "Create a task to complete NBA submission and assign it to Rohit" *(assignee trailing)* | `create_task` | `Complete NBA submission` | Form pre-filled, title clean | `ReviewConfirmTask` | — | 🟢 No | Title no longer the entire sentence verbatim |
| Same two patterns, spoken in Hindi/Marathi/Gujarati (e.g. "...task banao aur Rohit ko assign karo") | `create_task` | `Complete NBA submission` | Form pre-filled, title clean | `ReviewConfirmTask` | — | 🟢 No | GPT path already handled these; degraded-mode `deterministicFallback` extended to match |

**Subtask** *(must be on Task Detail for the parent)*

| Command | Intent | Title Generated | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Add a subtask — verify signatures, due Wednesday, for Vedant" *(spoken by parent's assignee)* | `create_subtask` | `Verify signatures` | `ReviewConfirmSubtask` opens under correct parent | `ReviewConfirmSubtask` | — | 🟢 No | Parent from `context.current_task_id` |
| *Same, spoken by the parent's assigner* | `create_subtask` | — | 403 → Toast: "Only the parent task assignee can create subtasks" | `ReviewConfirmSubtask` | — | 🟢 No | `createSubtask.service.ts` rejects |
| *Subtask due date ≥ parent's due date* | `create_subtask` | *(as spoken)* | Due-date field → 🟡 "must be before parent's due date" | `ReviewConfirmSubtask` | — | 🟢 No | Create button disabled client-side + server rejects |
| *Subtask assignee = parent's own delegator* | `create_subtask` | *(as spoken)* | Server rejects (`ASSIGNMENT_LOOP`) | `ReviewConfirmSubtask` | — | 🟢 No | No assignment loops |
| "Add a subtask under the NAAC report" *(nothing open)* | `create_subtask` | — | AMBIGUOUS: "Which task should this subtask go under?" | floating prompt | — | 🟢 No | — |

**Read / Filter**

| Command | Intent | Title Generated | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Show my tasks" | `navigate` | — | Navigate | `AssignedToMe` | `target: assigned` | 🟢 No | — |
| "Show tasks I delegated" | `navigate` | — | Navigate | `DelegatedTasksPage` | `target: delegated` | 🟢 No | — |
| "Show overdue tasks" | `navigate` | — | Navigate + badge | `AssignedToMe` | `overdue: true` | 🟢 No | — |
| "What's due today" | `filter_tasks` | — | Filtered list | `AssignedToMe` | `dueToday: true` | 🟢 No | — |
| "Show tasks under MCA Filings" | `filter_tasks` | — | Filtered list | `AssignedToMe` | `label: "MCA Filings"` | 🟢 No | — |
| "Search for GST filing" | `filter_tasks` | — | Full-text filter | `AssignedToMe` | `keyword: "GST filing"` | 🟢 No | Tenant-scoped |
| "Show tasks assigned to Vedant on 27th June" | `filter_tasks` | — | Multi-filter list | `DelegatedTasksPage` | `assigneeId, dueDate: "2026-06-27"` | 🟢 No | box inferred → delegated |
| "Show high priority tasks for Nikam" *(zero matches)* | `filter_tasks` | — | Empty state | `AssignedToMe` | `assigneeId, priority: high` | 🟢 No | Not an error |
| "उशीर झालेली कामे दाखवा" *(Marathi: overdue)* | `filter_tasks` | — | Filtered list | `AssignedToMe` | `overdue: true` | 🟢 No | Cross-language filter |

**Update** *(assigner-only unless noted; on Task Detail)*

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Change the due date to Monday" | `task_update` | `due: "Monday"` | `PATCH /tasks/:id` fires directly | `TaskDetail` | — | 🟢 No | Not destructive — no confirm |
| *Same, spoken by the assignee* | `task_update` | — | 403 → Toast: "You are not the assigner" | `TaskDetail` | — | 🟢 No | — |
| "Mark this high priority" | `task_update` | `priority: P1` | PATCH fires directly | `TaskDetail` | — | 🟢 No | — |
| "Reassign this task to Priya" *(task has subtasks)* | `task_update` | `reassign_to: Priya` | 403 → Toast (`REASSIGN_BLOCKED`) | `TaskDetail` | — | 🟢 No | Blocked once subtasks exist |
| "Reassign this task to Priya" *(2 Priyas)* | `task_update` | — | `DISAMBIGUATE` (user) → pick → PATCH fires | `AssigneePicker` | — | 🟢 No | — |
| "Add the label GST-Q2 to this task" *(label doesn't exist)* | `task_update` | `label: "GST-Q2"` | Toast: "No such label — create it first" | `TaskDetail` | — | 🟢 No | Never auto-creates |
| "Add my personal label follow-up to this task" | `task_update` | `personal_label: "follow-up"` | `PATCH /tasks/:id/assignee-label` | `TaskDetail` | — | 🟢 No | Invisible to the other party |
| "Change the title to Annual Filing" | `task_update` | — | Always rejected | `TaskDetail` | — | 🟢 No | Title immutable in every state |
| "Accept this task" *(assignee)* | `task_action` | `action: accept` | Fires directly, Open → In Progress | `TaskDetail` | — | 🟢 No | — |
| "Mark this done" *(assignee)* | `task_action` | `action: complete` | DoneA (soft complete) | `TaskDetail` | — | 🔴 Yes | Self-reported |
| "Mark this done" *(assigner)* | `task_action` | `action: complete` | DoneD (terminal) | `TaskDetail` | — | 🔴 Yes | Same verb, resolved by speaker's role |
| *Assigner marks done while subtasks open* | `task_action` | — | Server rejects DoneD | `TaskDetail` | — | 🔴 Yes | All subtasks must be DoneA first |
| "Reopen this task" / "reject this task" | `unknown` | — | Neutral fallback prompt | floating prompt | — | 🟢 No | No such state exists — never guessed |
| *Assignee tries "change priority" / "reassign"* | `task_update` | — | 403 on all | `TaskDetail` | — | 🟢 No | Assignee's surface: comments/evidence/complete/subtasks/personal-labels only |

**Delete / Cancel** *(assigner-only, confirm required)*

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Delete this task" *(assigner)* | `task_delete` | — | `ConfirmDialog` → `DELETE /tasks/:id` | `TaskDetail` | — | 🔴 Yes | — |
| *Same, spoken by assignee* | `task_delete` | — | 403 Toast, no dialog shown | `TaskDetail` | — | 🔴 Yes *(blocked before firing)* | — |
| "Cancel this task" *(has open subtasks)* | `task_cancel` | — | Dialog warns of cascade | `TaskDetail` | — | 🔴 Yes | Cascades to all non-terminal subtasks |
| "Delete this task" *(already DoneD)* | `task_delete` | — | Server rejects — terminal | `TaskDetail` | — | 🔴 Yes | — |
| "Delete the NAAC report task" *(2 matches)* | `task_delete` | — | Disambiguate first, **then** confirm | `EntityDisambiguationList` → `ConfirmDialog` | — | 🔴 Yes | Never confirm-then-disambiguate |

### 3. Sticky Note / Reminder

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Add a sticky note — call the vendor" | `create_reminder` | `Call the vendor` | Form pre-filled, no `dueAt` | `CreateStickyNote` | — | 🟢 No | Plain sticky |
| "Remind me to submit the report tomorrow at 5" | `create_reminder` | `Submit the report` | `dueDate`/`dueTime` pre-filled | `CreateStickyNote` | — | 🟢 No | Setting `dueAt` **is** the reminder |
| "Show my stickies" | `filter_reminders` | — | Navigate, all notes | `StickyWall` | `filter: all` | 🟢 No | — |
| "Show my reminders" | `filter_reminders` | — | Navigate, `dueAt`-only notes | `StickyWall` | `remindersOnly: true` | 🟢 No | Not every sticky — only ones with `dueAt` set |
| "Show my reminders due today" | `filter_reminders` | — | Further filtered | `StickyWall` | `remindersOnly: true, dueToday: true` | 🟢 No | — |
| "Pin this sticky note" | `update_sticky` | `action: pin` | PATCH fires directly | `StickyWall` | — | 🟢 No | — |
| "Move my reminder to Friday" | `update_sticky` | `action: move, due: Friday` | PATCH `dueAt` only | `StickyWall` | — | 🟢 No | Same entity, no new note created |
| "Turn this sticky note into a task" *(assignee + due already spoken)* | `promote_sticky` | *(sticky's first line)* | Promotes directly | `StickyWall` | — | 🟢 No | — |
| *Same, assignee/due missing* | `promote_sticky` | *(sticky's first line)* | Falls back to task review form | `ReviewConfirmTask` | — | 🟢 No | Draft-task behavior |
| "Delete the sticky about the vendor call" | `delete_sticky` | — | Confirm required | `StickyWall` | — | 🔴 Yes | Disambiguates first if 2+ match |
| "Delete this sticky" *(no distinguishing text, nothing in view)* | `delete_sticky` | — | AMBIGUOUS: "Say a word or two from the note" | floating prompt | — | 🔴 Yes *(after resolving)* | — |

### 4. Broadcast Notice — **stubbed per current scope**

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Post a notice to all faculty — office closed Friday" | `broadcast_notice` | — | Toast: "not available yet — still being built" | current page | — | 🟢 No | No partial state |
| "Send a broadcast to HoDs in Commerce" | `broadcast_notice` | — | Same graceful decline | current page | — | 🟢 No | — |
| "Edit the notice I just posted" / "delete my notice" | `broadcast_notice` | — | Same graceful decline | current page | — | 🟢 No | — |

*Full BroadcastNotice CRUD (routes/services/frontend page) is deliberately out of scope for this pass — the Prisma model exists (`schema.prisma:398`) for whenever that's picked up.*

### 5. Comment

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Add a comment — client confirmed the extension" | `add_comment` | `body: "client confirmed…"` | Posts directly | `TaskDetail` | — | 🟢 No | — |
| *Same, nothing open* | `add_comment` | — | AMBIGUOUS: "Which task should this go on?" | floating prompt | — | 🟢 No | — |
| *Third party (not assigner/assignee) comments* | `add_comment` | — | 403 — same as UI | `TaskDetail` | — | 🟢 No | — |
| "Edit my last comment to say filed with ROC" | `edit_comment` | `body: "filed with ROC"` | PATCHes your own latest comment | `TaskDetail` | — | 🟢 No | Author-only, enforced server-side |
| *Same, nothing open, title matches 2 tasks* | `edit_comment` | — | Disambiguate by task, **then** resolve latest comment server-side | `EntityDisambiguationList` | — | 🟢 No | `RECLASSIFY` round-trip |
| "Edit my last comment" *(never commented on that task)* | `edit_comment` | — | Toast: "You haven't commented on this task yet" | `TaskDetail` | — | 🟢 No | — |
| "Delete my comment" | `delete_comment` | — | Confirm required | `TaskDetail` | — | 🔴 Yes | Author-only |
| "Delete Rohit's comment" | `delete_comment` | — | Explicit permission denial | `TaskDetail` | — | 🔴 Yes *(blocked before firing)* | Not a silent no-op |

### 6. Project Label

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Create a label called GST Filing Q2" | `create_label` | `name: "GST Filing Q2"` | POST fires directly | `LabelPage` | — | 🟢 No | — |
| "Rename the label GST Filing Q2 to GST Filing Q3" *(as creator)* | `update_label` | `new_name: "GST Filing Q3"` | PATCH fires directly | `LabelPage` | — | 🟢 No | — |
| *Same, as non-creator* | `update_label` | — | 403 — creator-only | `LabelPage` | — | 🟢 No | — |
| "Delete the label GST Filing Q2" | `delete_label` | — | Confirm required | `LabelPage` | — | 🔴 Yes | Server rejects if still applied to any task |
| *Spoken label name matches 2 labels* | `update_label` / `delete_label` | — | Disambiguate first | `EntityDisambiguationList` | — | 🔴 Yes *(delete only)* | — |
| "Add the label GST-Q2 to this task" *(main)* vs. "add my personal label follow-up" | `task_update` | `label` vs. `personal_label` | Routed to different endpoints | `TaskDetail` | — | 🟢 No | `mainLabelId` (assigner-only) vs. `assigneeLabelId` (either party, private) |
| *Subtask created with no label spoken* | `create_subtask` | — | Inherits parent's main label | `ReviewConfirmSubtask` | — | 🟢 No | Server-side default, not prompted |

### 7. Navigation

| Command | Intent | Title / Key Value | Frontend Effect | Page / Component | Filters / Sorting | Confirm? | Notes |
|---|---|---|---|---|---|---|---|
| "Show overdue tasks" | `navigate` | — | Navigate | `AssignedToMe` | `overdue: true` | 🟢 No | — |
| "Go to sticky wall" | `navigate` | — | Navigate | `StickyWall` | — | 🟢 No | — |
| "Show delegated tasks" | `navigate` | — | Navigate | `DelegatedTasksPage` | — | 🟢 No | — |
| "Open settings" | `navigate` | — | Navigate | `ProfileSettings` | — | 🟢 No | — |
| "Show NBA readiness" | `out_of_scope` | `feature: "NBA readiness"` | Graceful decline | current page | — | 🟢 No | Flagged W64 — intentionally undefined |
| "Show whiteboards" / "open evidence vault" | `out_of_scope` | `feature: <name>` | Graceful decline | current page | — | 🟢 No | — |
| "Show delegated tasks" *(backend killed mid-navigation)* | `navigate` | — | Error Toast, no stale view | current page | — | 🟢 No | — |

Known limitations carried over from this test plan (not silently dropped) are tracked in `docs/product/open-questions-web-v1.md` §22.

---

## End-to-end (E2E) tests

**What to test:**
- Core user journey: register → create task → assign → accept → add evidence → complete
- Broadcast notice posted and visible to recipient
- Voice-to-task flow: audio in → draft task shown → confirmed → task saved

**Framework:** Playwright (web + mobile-web browsers). Native-mobile E2E (Detox) deferred with the Mobile PRD.
**When to run:** Nightly on `staging`; on-demand before a release
**Location:** `tests/e2e/`

---

## Web / PWA-specific testing

- Cross-browser happy-path flows (Chrome, Safari, Firefox; desktop + mobile-web viewports).
- Browser microphone permission + voice flow (graceful fallback to keyboard when denied/offline).
- Offline → back-online sync: create/update while offline → Pending Sync → auto-sync on reconnect; surface Conflict state (W34).
- PWA install + service-worker cache behaviour (desktop PWA confirmed — W29).

---

## Performance testing

- Load test task list endpoint and task creation before each major release
- Target: task list P95 < 300ms at expected concurrent load (TBD Q65)
- Tool: k6 or Artillery
- Run against `staging`, never against `production`

---

## CI requirements (every PR must pass)

- [ ] Lint (`eslint --max-warnings 0`)
- [ ] Type check (`tsc --noEmit`)
- [ ] Unit tests (all pass)
- [ ] Integration tests (all pass)
- [ ] No new critical/high CVEs (`npm audit --audit-level=high`)
- [ ] Bundle size check (web — alert if bundle increases > 10%)
