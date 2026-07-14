# Product Changelog

Chronological log of significant product decisions made after the initial PRD was written.
Update this file whenever a requirement changes, a feature is descoped, or a rule is revised.
The PRD reflects the current state; this file explains how we got there.

---

## Format

```
### YYYY-MM-DD — Short title

**Changed:** What changed (and what it changed from).
**Reason:** Why the decision was made.
**Decided by:** Who made the call.
**Impact:** Which docs / features are affected.
```

---

## Log

### 2026-07-10 — AI Nudge backend built: W94 resolved, NudgeSkipCounter schema confirmed with tenantId+userId

**Changed:**
- `NudgeSkipCounter` built with `tenantId`+`userId` added to the originally-proposed `(entityType, entityId, nudgeKind)` key — `userId` isn't stylistic, it fixes a real bug: Broadcast has many recipients per entity, so without it every recipient of the same broadcast would share one skip count.
- `AI_NUDGE_PERIODIC` removed from the `NotificationType` enum entirely (not just deprecated in docs) — 6 stale test rows deleted first so the migration's enum-narrowing cast wouldn't fail.
- Cross-type dedup changed from entity-only to recipient+entity-scoped (W84 correction) — same underlying reason as the `userId` fix above.
- Task/Subtask Due-Proximity now correctly requires already-accepted — an unaccepted-but-overdue task surfaces via Follow-up condition (a) instead, not Due-Proximity.

**Reason:** W94 (skip-counter schema) was the one item left unconfirmed from the 2026-07-06 redesign, explicitly flagged "propose, don't build yet." Building it surfaced a real correctness gap (Broadcast's shared-recipient problem) that wasn't visible at design time — caught in schema review, before the migration was written.

**Decided by:** Varun + Claude, working session 2026-07-10.

**Impact:** `docs/architecture/domain-model.md` (schema section, rows 8c/8d), `docs/architecture/system-design.md` §2.5, `docs/api/api-spec.md` §11 (new `/nudges` endpoints), `docs/product/open-questions-web-v1.md` (W94 now resolved). New reusable pattern recorded in `tech-playbook/patterns/polymorphic-recipient-scoped-counter.md`.

---

### 2026-07-04 — AI Nudge design complete: W80/W81/W82 resolved, zero opens remain

**Changed:**
- Periodic nudges batch into one notification per user (not per task).
- Follow-up's V1 trigger conditions are exactly the PRD's 2 stated examples — no more.
- "Due Tomorrow" tasks don't get recurring AI Nudges at all — only Due Today/Overdue do.

**Reason:** Final round of open questions on the AI Nudge feature — closing these out completes the design started 2026-07-03.

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `domain-model.md`, `prd.md` §5.7, `system-design.md` §2.5, `open-questions-web-v1.md`. **AI Nudge design (W72–W84) is fully resolved — ready for implementation with no outstanding design questions.**

---

### 2026-07-04 — AI Nudge W83/W84 resolved: StickyNote time-based ceiling, per-entity cross-type dedup

**Changed:**
- StickyNote due-proximity now stops nudging at the end of the calendar day it was due, rather than having no ceiling at all.
- Cross-type nudge collisions (e.g. Follow-up and Periodic both about the same task) are prevented via a dedup check keyed on the entity (`entityType`+`entityId`), not just the notification type.

**Reason:** Talked through 4 options for the cross-type collision problem (priority/suppression, merge-at-generation, do-nothing, generic per-entity cooldown) — the per-entity approach generalizes best since it doesn't hardcode a Periodic-vs-Follow-up-specific rule.

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `domain-model.md`, `prd.md` §5.7, `system-design.md` §2.5. W83/W84 closed. W80 (Periodic batching), W81 (Follow-up trigger list), W82 (Due Tomorrow cap bucket) still open — W84's fix is partly dependent on how W80 lands.

---

### 2026-07-04 — AI Nudge gap audit: 6 real gaps found, skip mechanic simplified

**Changed:**
- Re-examined the AI Nudge design after claiming it was "fully resolved" — it wasn't. Found 6 real gaps: Periodic batching unspecified, Follow-up trigger-condition list incomplete, "Due Tomorrow" doesn't fit the 2 defined skip-cap buckets, StickyNote due-proximity has no ceiling at all, dropping the daily cap silently reintroduced cross-type pile-up risk, and no API endpoint existed for the Skip action.
- **Skip mechanic simplified rather than the missing API being filled in:** skip is not a user action anymore — the counter auto-increments as a side effect of the sweep job firing an unresolved nudge, and escalation fires in that same operation if the cap is exceeded. Removes the gap instead of building an endpoint to close it.
- Periodic nudge scope confirmed as any active task status (`OPEN`/`IN_PROGRESS`/`OVERDUE`), not literal `OPEN` only.

**Reason:** Varun directly asked "are you sure there are no gaps" — re-deriving the design under that challenge, rather than just reassuring, surfaced real unresolved pieces that had been glossed over in the "fully resolved" claim.

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `domain-model.md`, `prd.md` §5.7, `system-design.md` §2.5, `open-questions-web-v1.md` (W76/W77/W79 revised, W80–W84 newly opened — batching, follow-up trigger list, due-tomorrow cap bucket, sticky cap, cross-type pile-up all still genuinely open).

---

### 2026-07-04 — AI Nudge scheduler architecture + remaining config values resolved

**Changed:**
- Scheduler architecture: one shared EventBridge sweep job (not 3 separate ones) evaluates all AI Nudge conditions each run.
- Frontend notification delivery confirmed decoupled from backend generation — one generic polling loop handles all notification types, including all 3 AI Nudge types.
- Dedup window, office hours, and skip cap numbers (W74/W75/W77) are hardcoded code constants, not admin-configurable DB settings, for the initial build.

**Reason:** Working through implementation mechanics surfaced that the scheduler didn't need per-type infrastructure, and that pinning exact numeric configs wasn't worth blocking on — code constants with sensible defaults get the feature built faster, config-table admin-UI can come later if actually needed.

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `system-design.md` §2.5 (rewritten — was stale), `domain-model.md` (schema plan simplified), `open-questions-web-v1.md` (W74/W75/W77 closed). AI Nudge feature design is complete and ready for implementation.

---

### 2026-07-04 — AI Nudge escalation delivery resolved: one-time in-app + email

**Changed:**
- Escalation-to-assigner (Task due-proximity, skip cap exhausted) delivers as a **one-time in-app + email** alert, not repeated on every subsequent cycle. Assignee's own nudge continues recurring in-app-only as before; the assigner is not notified again for that task.

**Reason:** Final open piece of the AI Nudge escalation design — needed to know whether the escalation moment warranted email (it does, being a one-shot "this needs attention now" signal) and whether it repeats (it doesn't, to avoid re-introducing the spam problem the whole nudge system is designed to avoid).

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `domain-model.md`, `prd.md` §5.7, `api-spec.md` §11, `open-questions-web-v1.md` W77. **AI Nudge design is now fully resolved** except exact numeric configs (W74 dedup window, W75 office hours, W77 skip cap values).

---

### 2026-07-04 — AI Nudge refinements: daily cap dropped, Screen A close button clarified, POC UI authorized

**Changed:**
- Daily nudge cap (from the previous session's entry) — descoped, not being built initially.
- Screen A's close button (Periodic/Follow-up/Sticky) — confirmed as a simple dismiss, no counter, no escalation; only Screen B's Skip button (Task due-proximity) is counted.
- Explicitly authorized building placeholder/POC screens for both nudge screens now, ahead of a real Figma design — swap later.

**Reason:** Scoping down for a faster first build — daily cap adds complexity without a proven need yet; POC screens let backend/schema work proceed without waiting on design.

**Decided by:** Varun + Claude, working session 2026-07-04.

**Impact:** `domain-model.md`, `prd.md` §5.7, `open-questions-web-v1.md` (W78, W79). Still open: exact escalation-to-assigner delivery mechanism.

---

### 2026-07-03 — AI Nudge escalation: skip cap, daily nudge cap, two-screen UI

**Changed:**
- `domain-model.md`, `prd.md` §5.7/§10 — added the due-proximity **skip mechanic**: explicit Skip button (Task only), lifetime cap per task, separate lower cap for overdue vs. due-today. Routine nudge cycle is assignee-only; assigner is pulled in only once the skip cap is exhausted (the actual escalation).
- Clarified **qualifying response** for every nudge type — opening the task via the notification link never counts on its own; only real progress/status/date changes (or explicit Skip) resolve a nudge.
- Added a **daily nudge cap** (tenant-configurable, per user, across all 3 nudge types combined) to prevent notification pile-up — separate mechanism from the per-task skip cap.
- Specified **two separate UI screens** needed: combined Periodic+Follow-up+Sticky nudges, and Task due-proximity specifically. Neither has a Figma reference yet.

**Reason:** Working through the AI Nudge build plan, Varun identified that (1) tasks need a way to acknowledge-without-fully-resolving a due nudge without it escalating immediately, (2) nudging all day across 3 independent trigger types would be exhausting without a global cap, (3) due-proximity nudges need different UI treatment than the simpler periodic/follow-up/sticky nudges.

**Decided by:** Varun + Claude, working session 2026-07-03.

**Impact:** `domain-model.md`, `prd.md`, `open-questions-web-v1.md` (W77–W79 opened, W76 resolved). New schema fields needed (not yet built): `Task.dueProximitySkipCount`, tenant-level `NudgeConfig` (skip caps, daily cap, re-fire interval, office hours).

---

### 2026-07-03 — AI Nudge design resolved: one-shot vs recurring, polymorphic due-proximity

**Changed:**
- `domain-model.md` Notification Events table, `prd.md` §5.7 + §10, `api-spec.md` §11 — resolved what looked like duplicate enum values (`AI_NUDGE_DUE_PROXIMITY` vs `TASK_DUE_TODAY`/`TOMORROW`/`OVERDUE` vs `REMINDER_FIRED`). They're two layers: the `TASK_DUE_*`/`REMINDER_FIRED` events are one-shot factual notices; `AI_NUDGE_DUE_PROXIMITY` is a recurring escalation nudge layered on top, re-firing until the user acts.
- **`AI_NUDGE_DUE_PROXIMITY` is polymorphic** — applies to both overdue Tasks and StickyNote reminders (`dueAt` passed), not tasks only as previously implied. `AI_NUDGE_PERIODIC`/`AI_NUDGE_FOLLOWUP` stay task-only.
- Corrected `api-spec.md`, which had wrongly listed `AI_NUDGE_DUE_PROXIMITY` as sending email — AI Nudge types are in-app only (only the one-shot `TASK_DUE_*`/`TASK_REMINDER` send email, per the W71 correction).

**Reason:** Working through a build plan for AI Nudge surfaced the ambiguity; Varun caught that due-proximity nudging needed to cover sticky note reminders too, not just tasks.

**Decided by:** Varun + Claude, working session 2026-07-03.

**Impact:** `domain-model.md`, `prd.md`, `api-spec.md`, `open-questions-web-v1.md` (W72–W73 resolved, W74–W76 opened — dedup window value, office-hours definition, per-type "response" semantics still need decisions before build).

---

### 2026-07-03 — Notification channel correction: reminder/due-date types also send email

**Changed:**
- `prd.md §10` and `§16 Out of Scope` — was "all notifications in-app only, email used only for OTP/greeting delivery, not a notification channel." Corrected: `TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE` also send email (same nodemailer/SMTP path as OTP). All other notification types (assigned, accepted, edited, commented, broadcasts, AI nudge periodic/follow-up, etc.) remain in-app only. WhatsApp stays fully out of scope for all types.
- Propagated to `CLAUDE.md`, `domain-model.md`, `system-design.md`, `security.md`, `deployment.md`, `api-spec.md` (added a Channel column to the notification-types table; noted `POST /tasks/:id/remind` sends email too).
- `open-questions-web-v1.md` — new **W71**, resolved (docs correction, not a fresh decision).

**Reason:** Docs were simply wrong — email-for-reminders was always the intent, "in-app only" language never got corrected across the doc set. Confirmed with Varun (2026-07-03): scope is reminder/due-date types only, not a blanket email-for-everything change.

**Decided by:** Varun (correction confirmed via chat) + Claude (doc propagation).

**Impact:** `CLAUDE.md`, `prd.md` (§10, §16), `domain-model.md` (Notification section), `system-design.md` (§13 Out of Scope), `security.md` (External integrations — DKIM/SPF now applies now, not post-MVP), `deployment.md` (alerting checklist), `api-spec.md` (§11 Notification types table + `POST /tasks/:id/remind`). **Implementation note:** `remindTaskService` is currently a validation-only stub — the actual `Notification` row write and email send are not yet built (flagged in `api-spec.md` and W71).

---

### 2026-06-27 — Voice data storage, evidence serving, and broadcast image serving added to PRD

**Changed:**
- **`prd.md §9.6` (new section) — Voice Data Storage** — rawTranscript always saved verbatim (multilingual, unfiltered), audio clip opt-in (W37), confidence score 0.0–1.0 from SDK stored, retention 6 months–1 year (W41), assigner+assignee access only (W38). Two-phase save: transcript atomic with task DB transaction, audio uploaded async post-201 — task creation never blocked by audio. Source of truth is the final edited task, not the audio/transcript (W39). Applies to main tasks and subtasks equally.
- **`prd.md §3.5` — Evidence storage & access rules added** — files go directly browser→S3 (never through API server). `fileUrl` in DB stores S3 object key, not a URL. Pre-signed GET URL with 15 min TTL generated on demand per access. Restricted to assigner and assignee only. Applies to main tasks and subtasks.
- **`prd.md §7` — Broadcast image serving rules added** — broadcast images render **inline in the feed** without user interaction (unlike evidence/audio which are click-to-open). Pre-signed GET URL with 25h TTL generated once at publish time and stored in `imageUrl`; returned directly in feed — no per-request URL generation. Access controlled at API level via audience filter (dept + role).

**Reason:** Design session (2026-06-27) finalised how all three types of binary data (voice audio, evidence files, broadcast images) are stored and served. Different serving patterns because broadcast images need zero-click inline rendering while evidence/audio are access-controlled per-request.

**Decided by:** Varun + Claude design session (2026-06-27).

**Impact:** `prd.md` (§3.5, §7, §9.6), `domain-model.md` (Evidence notes, BroadcastNotice.imageUrl, VoiceRecording entity), `api-spec.md` (§6 Voice Recording, §10 Broadcast image upload endpoints), `system-design.md` (§4.2 Evidence flow, §4.6 Voice flow, §4.7 Broadcast image flow — all with full positive+negative failure scenarios).

---

### 2026-06-23 — Create Task with Voice 3 built (all fields resolved state)

**Changed:**
- **`bolo-web/src/pages/ReviewConfirmTask.tsx`** — now covers all three voice states (V1/V2/V3). Badge switches between "AI Draft" (amber) and "Ready to create" (green `#E8F2E7`/`#689E69`). Footer and Create Task button reflect resolved vs unresolved state.
- **`bolo-web/src/components/VoiceComposer.tsx`** — `ready` and `timer` props added; transcript label turns green (`#6FA670`) and timer "00:23" appears when all fields resolved.
- **`createTask.mock.ts`** — `MOCK_VOICE_TASK_DRAFT_V3` added: Rohit Sharma confirmed (95% match), due date + time + priority + evidence all set.
- **`workspaceStore.ts`** — `assigneeMatchPercent?: number` added to `VoiceTaskDraft`.
- **`tailwind.config.js`** — 7 new tokens: `ready-badge-*`, `transcript-green`, `timer-green`, `btn-create-*`.
- **`docs/ux/design-system.md`** — `ReviewConfirmTask` entry updated with all three state variants documented.

**Reason:** Voice 3 Figma state (node `163:2432`) is the success state — all fields confirmed, Create Task button enabled.
**Decided by:** Design (Figma) + dev session.
**Impact:** `ReviewConfirmTask`, `VoiceComposer`, `tailwind.config.js`, `workspaceStore`.

### 2026-06-23 — Create Task with Voice 2 built (assignee picker state)

**Changed:**
- **`bolo-web/src/components/AssigneePicker.tsx`** — new inline component for resolving ambiguous assignees; shows AI-suggested matches with % badge color-coding (green ≥90%, blue 75–89%, purple <75%).
- **`bolo-web/src/components/TaskFieldRow.tsx`** — added `needs-attention` status (orange value text `#F89659`, amber "Needs attention" pill `#FDF1DF`/`#F8A05E`; chevron flips up when picker is open).
- **`bolo-web/src/pages/ReviewConfirmTask.tsx`** — stateful draft; picker auto-opens when `assigneeAmbiguous === true`; selecting a match resolves it and closes picker; Priority `P1` → "High" confirmed.
- **`tailwind.config.js`** — 22 new tokens for picker and needs-attention state.
- **`store/workspaceStore.ts`** — `AssigneeMatch` interface + `assigneeAmbiguous`/`assigneeMatches` on `VoiceTaskDraft`.
- **`docs/ux/design-system.md`** — `AssigneePicker` and `needs-attention` entries added.

**Reason:** Voice 2 Figma state (node `162:2108`) shows the assignee picker open when speech was ambiguous ("Rohit" matched 3 people).
**Decided by:** Design (Figma) + dev session.
**Impact:** `TaskFieldRow`, `ReviewConfirmTask`, `workspaceStore`, `tailwind.config.js`.

### 2026-06-23 — 4-week sprint plan locked + Create Task with Voice screen built

**Changed:**
- **Sprint plan `docs/product/sprint-plan-4w.md`** — 4-week plan confirmed: Week 1 Jun 23-29 (voice USP + end-to-end task creation), Week 2 Jun 30-Jul 6 (full task lifecycle), Week 3 Jul 7-13 (team features), Week 4 Jul 14-20 (production). Deadline extended to 20 July MVP.
- **`bolo-web/src/pages/ReviewConfirmTask.tsx`** — "Review & Confirm Task" screen built pixel-accurate from Figma node `162:1838`. Components: `TaskFieldRow`, `VoiceComposer`, mock data in `src/api/mocks/createTask.mock.ts`.
- **`tailwind.config.js`** — new colour tokens from Figma node `162:1838` (review-title, ai-draft-bg, field-optional-*, field-error-*, transcript-label, btn-disabled-*, etc.).
- **`store/workspaceStore.ts`** — added `review-confirm-task` state + `VoiceTaskDraft` type + `openReviewConfirmTask` action.
- **Two active tech conflicts to resolve (flagged, not yet decided):**
  1. Sprint plan specifies **MSW (Mock Service Worker)** for FE mocking; current implementation uses `VITE_USE_MOCKS` env toggle with `Promise.resolve()`. Both achieve the same goal — needs a call before building more screens.
  2. Sprint plan specifies **shared types in `shared/types/`** from `prisma generate`; current approach has `bolo-backend/src/types` + `bolo-web/src/types` kept in sync manually. Needs a decision before types diverge.
- **HTTPS required from Day 1** (browser mic `getUserMedia` requires HTTPS — confirmed, affects Week 1 infra setup).

**Reason:** Week 1 starts today (Jun 23). Voice task creation is the Week 1 demo deliverable.

**Decided by:** Varun (sprint plan), Claude (screen implementation).

**Impact:** `ReviewConfirmTask` ready for demo with mock data. Backend `/api` side not yet built — needs `/api` task create endpoint, then `/integrate` to connect.

---

### 2026-06-20 — API spec V1.1: missing endpoints added + cross-cutting standards

**Changed:**
- **`docs/api/api-spec.md`** — added 12 missing endpoints: `GET /notifications/unread-count`, `GET /tenant/org-chart`, `POST /tenant/onboard/import`, full Department CRUD (4 endpoints), Billing stubs (3 endpoints), AI Nudge Config (2 endpoints), `GET /health`. Route × Middleware Matrix updated for all new routes.
- **`docs/api/api-spec.md`** — Response envelope corrected to match `utils/response.ts` actual output: `{ success: true, message, data }` / `{ success: false, error: { code, message } }`. Added full standard error response examples section.
- **`docs/api/api-spec.md`** — Added missing error codes: `LABEL_IN_USE`, `ALREADY_PROMOTED`, `BROADCAST_ALREADY_PUBLISHED`, `RATE_LIMITED`. Added subtask label inheritance business rule (inherit parent's `projectLabelId` if not set).
- **`guidelines.md`** — Full rewrite: fixed `org_id → tenant_id`, removed stale "Audit log NOT in V1" rule (W63 resolved), added Error Handling section (AppError classes + global middleware), added Logging section (levels, PII exclusions, log format), added Audit Logging section (AuditService interface + complete action map), fixed response shape to match helpers, updated entity names to V1.1.
- **`bolo-backend/src/utils/response.ts`** — Updated `failureResponse` to accept optional `code` param; added `httpStatusToCode` fallback map for structured error codes.

**Reason:** Pre-build validation — every endpoint, error code, and cross-cutting concern must be documented before implementation starts.

**Decided by:** Varun + Claude session (2026-06-20).

**Impact:** All backend implementation must follow the updated guidelines.md error patterns. All MSW stubs in bolo-web must match the corrected response envelope.

---

### 2026-06-20 — API spec V1.0 complete

**Changed:**
- **`docs/api/api-spec.md`** — full rewrite from stubs to complete spec. All 15 entities covered: Auth, Tasks, Subtasks, Comments, Evidence, Personal Labels, Project Labels, Sticky Notes (incl. reminders via `dueAt`), Broadcast Notices, Notifications, Audit Log, Search, Voice AI dispatch, Users & Tenant, Analytics.
- Removed the stale `/reminders` section (W30 resolved — `StickyNote.dueAt` IS the reminder).
- Corrected subtask state endpoints from `/complete` → `/done-a` / `/done-d` (matching task state machine).
- Added missing endpoints: Comment PATCH/DELETE, Evidence presign flow, Personal Labels CRUD, Broadcast publish/ack flow, Notifications list + mark-read, Audit Log with filters, Voice dispatch.
- Added full Route × Middleware Matrix appendix.

**Reason:** Foundation doc needed before any endpoint can be built. Sprint plan references this as the source of truth for MSW stubs.

**Decided by:** Varun + Claude session (2026-06-20).

**Impact:** `docs/api/api-spec.md` (primary). Sprint plan and backend implementation should reference this for endpoint contracts.

---

### 2026-06-20 — Schema V1.1 locked + full docs cascade

**Changed:**
- **`bolo-backend/prisma/schema.prisma`** — V1.0 → V1.1 complete rewrite. Added 6 new tables: `OtpCode`, `TaskPersonalLabel`, `BroadcastAcknowledgement`, `Notification`, `AuditLog`. Renamed `Org`/`OrgMembership` → `Tenant`/`TenantMembership` (`org_id` → `tenant_id` throughout). Added `reportsToId` (org chart via self-ref FK on TenantMembership), `canBroadcast` boolean (binary broadcast gate, not role-derived), `dueDate` required for Draft→Open, `messageJson` + `messageHtml` on BroadcastNotice (TipTap AST + sanitized HTML), `ProjectLabel` + `TaskPersonalLabel` (two-tier label model). `prisma validate` passes clean.
- **`docs/architecture/domain-model.md`** — full rewrite to V1.1: all 15 entities, field tables, relations, scoping rules. Reminder removed (W30 resolved). `tenant_id` throughout.
- **`docs/product/prd-summary.md`** — updated to v1.1: two-tier labels, broadcast audience mandatory, AI Nudge three triggers, Audit Log section.
- **`CLAUDE.md`** — synced: `orgId` → `tenantId`, W1/W-C1/W-C3 resolved, two-tier labels, TipTap, httpOnly cookie, all 15 entities.
- **`tech-playbook/`** — updated `decisions/database.md` (7 BOLO schema patterns), `decisions/auth.md` (httpOnly cookie, OTP DB pattern), `patterns/multi-tenant-saas.md` (4 new patterns), `projects/registry.md` (BOLO entry fully updated), `ARCHITECT.md` (`org_id` → `tenant_id` in checklists).
- **All stale docs cascade** — `org_id`/`orgId` → `tenant_id`/`tenantId` in: `system-design.md`, `api-spec.md`, `ops/security.md`, `engineering/testing-strategy.md`. W63 marked resolved in all: `open-questions-web-v1.md`, `api-spec.md`, `system-design.md`, `security.md`, `testing-strategy.md`.

**Reason:** Schema design session finalized all 15 DB tables for the BOLO Web V1 backend before API implementation begins. Resolves W63 (audit log in V1 — CA/CS compliance), W-C3 (dueDate required at Draft→Open), confirms W1 (httpOnly cookie), W16 (two-tier label model).

**Decided by:** Integrate18 (Varun) — design session 2026-06-19/20.

**Impact:** Schema locked. All design docs current. Ready to start API implementation layer (routes → controllers → services → repositories).

---

### 2026-06-17 — Full PRD reconciliation + new client-facing summary doc

**Changed:** Rewrote `docs/product/prd.md` end to end to fold in every decision resolved across all four clarification rounds (Excel sheet/Rhushabh, `Bolo Workspace Architecture v1.pdf`, and two rounds of direct client text) — mandatory fields (Draft-only-needs-nothing, Title+Assignee+DueDate to publish), labels (Gmail-style private model), hierarchy (any-to-any assignment, binary broadcast permission, no enforced designation hierarchy), no escalation engine, platform (Responsive Web + desktop-scoped PWA, no offline), full voice CRUD/search/navigation scope with confirm-before-delete, evidence (25MB per-task aggregate, docs allowed, no count limit), reminders (auto from StickyNote due date), billing (per-seat module confirmed in V1), auth (Email OTP only, admin-portal invites), and the workspace-first navigation model (replacing the old routed three-panel framing). **Removed** §12 "Offline Mode (PWA Application)" and §16 "Boundary Conditions & Error Handling" entirely (no offline support in V1 made both moot) — per explicit client instruction, more removals to come. **Added** a new "Required Operational Services (V1)" section, sourced from `Doc/Fatafat_Development_Proposal.md` §4.1, filtered down to what the web-pivoted V1 actually needs (cut native app distribution, push/FCM, SMS OTP, WhatsApp Business API; kept cloud infra, transactional email, search, scheduler, git — added a payment/billing provider line item since billing is now confirmed in scope). Also created **`docs/product/prd-summary.md`** — a concise, client-shareable summary (tables/bullets only, no prose, no internal W-number references) with its own separate "Decisions Needed From You" section (billing UI, audit log scope, readiness-indicator data source).
**Reason:** Client is sharing a PRD-derived doc with the client side directly; needed both the comprehensive internal version locked to current decisions and a short external-facing version. Client gave explicit instruction to strip both the offline and boundary-conditions sections since neither applies anymore.
**Decided by:** Client (scope decisions, all four rounds); document structure and operational-services filtering by Integrate18.
**Impact:** `prd.md` (full rewrite), `prd-summary.md` (new). **Not yet done:** cascading the same decisions into `domain-model.md`, `system-design.md`, `api-spec.md`, `schema.prisma`, and `CLAUDE.md` — `prd.md` is current, those are not yet. Further section removals from both PRD docs are expected once the client sends the rest of the removal list.

---

### 2026-06-17 — Workspace-first frontend architecture (supersedes routed-page navigation)

**Changed:** Synced `Doc/Bolo Workspace Architecture v1.pdf` (new client architecture doc, read via markitdown). The frontend interaction model is now "Intent → Workspace," not "Navigation → Page": a single persistent workspace canvas, global voice commands that can switch context from anywhere regardless of current screen, a constant URL (no page routing for primary workflows), and sidebars reframed as context providers rather than navigation menus. Added `system-design.md` §0 as the authoritative model; annotated `prd.md` §13 and `design-system.md` to match. Added two new open questions: **W64** (what data backs the Top Bar "readiness indicators") and **W65** (is "constant URL" a hard zero-routing requirement, or is a thin shell route acceptable).
**Reason:** Client-provided architecture vision doc, dated after the original Web PRD — refines (does not replace) the three-panel layout, but changes the routing/navigation paradigm underneath it.
**Decided by:** Client (architecture doc). The actual technical implementation approach (zero-router vs thin shell route) is still open — flagged to Varun, not yet decided.
**Impact:** `system-design.md` (new §0 + Client Layer + diagram label), `prd.md` §13 (annotated), `design-system.md` (new Layout architecture section), `open-questions-web-v1.md` (new §13, W64/W65). **Not yet updated:** `CLAUDE.md` Architecture Rule #1 ("React Router for navigation") still contradicts this — pending explicit confirmation before editing project rules. `tech-playbook/` recording also pending the same confirmation (Q&A protocol).

---

### 2026-06-14 — Cleaned up remaining mobile-era rule docs

**Changed:** Reconciled `.cursorrules` (full rewrite: web/Vite, two-project layout, org-role RBAC, no `@fatafat/types`, web scope guard) and `docs/engineering/guidelines.md` (BOLO name, W-refs for audit/PII, no GPS, `bolo-backend`/`bolo-web` folder structure, org-scoped vs personal/child table scoping, archive-not-delete).
**Reason:** These two carried React Native/Expo/Turborepo/per-project-role guidance contradicting the synced web docs.
**Impact:** `.cursorrules`, `docs/engineering/guidelines.md`. Remaining known-stale: `docs/engineering/permissions-onboarding.md`, `docs/architecture/system-design-diagrams.html` (generated), minor name refs in `git-workflow.md` / `design-system.md`.

---

### 2026-06-14 — Code located + backend made coherent with the web model

**Changed:** The `bolo-backend` / `bolo-web` code was **never missing** — it lives at the project root (`Bolo/bolo-backend`, `Bolo/bolo-web`). An accidental double-nesting (`Bolo/Bolo/…`) had been flattened mid-session, and the first schema reconciliation was written into the leftover nested folder by mistake. Corrected:
- Moved the reconciled web schema to the real `bolo-backend/prisma/schema.prisma` (overwrote the old mobile schema).
- Reconciled `bolo-backend/src/types/index.ts` and `bolo-web/src/types/index.ts` to the Org/web model (+ `AuthTokenPayload`).
- Fixed broken imports: `@fatafat/types` (package no longer exists) → local `../types`.
- Rewrote `rbac.middleware.ts` from per-project `ProjectRole`/`projectMember` to org-level `requireOrgRole` over `OrgMembership`.
- Cosmetic: `index.ts` health/app name + route stubs → BOLO web entities.

**Reason:** Recover/clean up after the folder rename and make the existing backend compile against the new schema.
**Decided by:** Reconciliation per the Doc-sync rule; task-level (assigner/assignee) permission checks intended to live in services, not middleware.
**Impact:** `bolo-backend` (schema, types, both middleware, index), `bolo-web/src/types`. **Manual follow-up:** delete the stray `Bolo/Bolo/` folder (locked/in-use during this session). Hierarchy enforcement still open (W17–W20).

---

### 2026-06-14 — Reconciled downstream docs + schema to the Web PRD

**Changed:** Brought the remaining PRD-derived docs in line with the synced `prd.md` / `domain-model.md`:
- `docs/architecture/domain-model.md` — `dueDate` optional (W-C3), status enum = PRD §6, **subtask = self-referential Task** (`parentTaskId`), Evidence/Comment FK to Task only.
- `Bolo/bolo-backend/prisma/schema.prisma` — rewritten from the old mobile model to the Org/web model (Org/Department/OrgMembership, new `TaskStatus`, self-ref subtasks, GPS removed, no password — Email OTP, uuid IDs).
- `docs/architecture/system-design.md` — full rewrite: web-first, new state machine (no rejection), Moments removed, GPS removed, roles `top/mid/executor`, languages Hindi/English + cross-language viewing, web push.
- `docs/api/api-spec.md` — removed `/reject` (W-C1) and `/audit-log` (W63), split completion into `done-a`/`done-d`, dropped `requiresEvidence` + GPS, fixed broadcast roles + states.
- `docs/ops/security.md` — GPS PII dropped (web), audit log / voice encryption / DPDP / WhatsApp marked out-of-V1, Q→W refs.
- `docs/engineering/testing-strategy.md` — removed rejection/`requiresEvidence`/audit tests, added two-step completion + parent/subtask gate, web/PWA testing replaces native camera/GPS.
- `docs/ops/deployment.md` — S3 (no GPS), web push (native deferred), Prisma migrations, `bolo-backend`/`bolo-web` local setup.

**Reason:** Keep every PRD-derived doc and the backing schema consistent with the new Web PRD after the source-file re-sync above.
**Decided by:** Reconciliation per the Doc-sync rule; product decisions still pending are flagged inline (W-C1/W-C2/W-C3, W22, W29, W33).
**Impact:** Architecture + API + ops + testing docs and the Prisma schema. **Still mobile-era / not reconciled:** root `CLAUDE.md`, `docs/architecture/system-design-diagrams.html` (generated artifact), and the TS types in `bolo-backend`/`bolo-web` (currently missing from disk).

---

### 2026-06-14 — Re-synced PRD docs from updated client source files

**Changed:** Re-synced `docs/product/prd.md` from `Doc/BOLO_Web_PRD_v1.pdf` (PDF dated 2026-06-11, publisher AIBIGO Institute Pvt Ltd) and `docs/product/open-questions-web-v1.md` from `Doc/BOLO_Web_PRD_OpenQuestions.xlsx`. Notable deltas from the prior (2026-06-06) sync:
- Task **required fields** changed to **Title + Assignee** (due date moved to optional in §3.1).
- Added **§16 Boundary Conditions & Error Handling** (new section).
- Added §5.4 per-tab action lists (Delegated vs My Tasks), §9.6 cross-language task viewing, broadcast Notice Board + offline-draft behaviour (§7.2).
- Recorded **W-C3** — a new PRD-internal contradiction on mandatory task fields (§3.1/§6.2 say Title+Assignee; §5.1 says +Due Date).
- Added the open-questions status legend (CONTRADICTION / PENDING / NEED NEW ANSWER / RE-CONFIRM / CARRIED) + Priority + Owner from the sheet.

**Reason:** Client shipped an updated PRD PDF + open-questions sheet; `Doc/` is source of truth and the `.md` mirrors must follow.
**Decided by:** Client (PRD); sync performed per the Doc-sync rule in `CLAUDE.md`.
**Impact:** `prd.md`, `open-questions-web-v1.md`. **Downstream, not yet updated:** `docs/architecture/domain-model.md` and `backend` Prisma schema still mark due date / state values from the old model — must be reconciled (esp. W-C3 required-field change) before backend work.

---

_Add new entries above this line, newest first._
