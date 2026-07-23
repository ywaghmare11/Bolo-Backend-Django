# BOLO Web PRD v1.0 — Open Questions & Decisions Tracker

**Version:** 1.6
**Source PRD:** `Doc/BOLO_Web_PRD_v1.pdf` · **Source sheet:** `Doc/BOLO_Web_PRD_OpenQuestions.xlsx` + client Google Sheet (Rhushabh's answers, round 2) + client's direct V1 scope-down text (rounds 3 & 4)
**Created:** 2026-06-06 | **Last updated:** 2026-07-21 — §22 added: W102–W109, accepted voice-command scope limitations surfaced while building the voice command manual test plan (`docs/engineering/testing-strategy.md`). Previous update 2026-06-17 (round 4): resolved W66/W67/W68 (voice CRUD scope = all 5 entities, mandatory confirm-before-delete, flow diagrams built into `diagrams.html` §9–10); clarified W20 is dev discretion, not a contradiction; clarified W16 is "client needs to review Rhushabh's answer first," not a rejection of it.
**Status:** Almost all items resolved. Genuinely open: **W15** (task card fields — pull from Figma), **W43** (voice privacy — low priority), **W60** (billing UI/flow), **W64** (readiness indicators), **W65** (routing approach). See **🚩 Major Flags** and **Critical Gaps** near the end. **W63 resolved (2026-06-20):** Audit log is in V1 scope — full AuditLog table in schema V1.1. **W100 resolved (2026-07-16):** transactional email is AWS SES, client-confirmed.

> This file is specific to the Web MVP (v1.0).
> For mobile / V2 open questions, see `docs/product/open-questions.md`.
> `domain-model.md`, `system-design.md`, and `api-spec.md` have been updated to reflect all resolved decisions (2026-06-18). `schema.prisma` and `CLAUDE.md` still carry stale references — pending the full code cascade.

---

## Status Legend (from the open-questions sheet)

| Status | Meaning |
|---|---|
| **CONTRADICTION** | Direct conflict between an old confirmed answer and the new PRD. Resolve before any development. |
| **PENDING** | New question with no prior answer. |
| **NEED NEW ANSWER** | Had a previous answer but it is now outdated/invalid for the web context. |
| **RE-CONFIRM** | Had a previous answer — still likely valid but needs explicit re-confirmation for web v1. |
| **CARRIED** | Previous answer confirmed valid; no new answer needed. |

**Priority:** CRITICAL / HIGH / MEDIUM / LOW · **Owner:** Client / Both (Integrate18 + Client).

---

## 🚩 Major Flags — Round 3 (client's direct text, 2026-06-17, outranks rounds 1 & 2)

| # | Flag | What changed |
|---|---|---|
| **W29** | **Final, decided — not open for further discussion.** Reverses the same-day Excel answer ("Responsive Web only, no PWA"). Confirmed final by the client (2026-06-17): both Responsive Web and PWA ship in V1; PWA is desktop-screen-scoped; still no offline (separate decision unchanged) — so it's an installable shell, not an offline PWA. |
| **W16** | ✅ **Resolved by PRD v1.1 (2026-06-18).** Two-tier model: one shared **Main Label** (assigner sets via `Task.projectLabelId`, visible to both parties) + private **Personal Labels** (`TaskPersonalLabel` join table, one row per user per task, invisible to the other party). This supersedes the round-3 "undecided" flag and the round-2 Gmail-style fully-private model — PRD v1.1 is the authoritative answer. |
| **W20** | **Not a contradiction — confirmed dev discretion.** Client gave the dev team free hand on the hierarchy/reports-to tree; we're leaning toward building it, for analytics/org-structure only, never for assignment validation. Rhushabh's "no relationship used for delegation" stands exactly as stated. |
| **W8** | **Voice scope now concrete.** Was "open-ended, client will refine later." Now: full CRUD on Task/StickyNote/Broadcast + search + navigation, target 70–80% of all ops voice-driven. This is a much bigger voice-integration surface than originally scoped — flagging the size, not the content. |

---

## 🚩 Major Flags Surfaced by Rhushabh's Answers (2026-06-17, round 2)

These need your eyes before we cascade them into `domain-model.md` / `schema.prisma` / `system-design.md` — each is either a contradiction between two client-side answers (we used Rhushabh's per your instruction) or a bigger architectural change than previously assumed. **Note: W16, W20, and W29 above were further changed by round 3 — this section is kept for the original Excel-round context.**

| # | Flag | What changed |
|---|---|---|
| **W19** | **Org-role model likely collapses from 3 tiers to 2.** Rhushabh explicitly disagrees with Adarsh's answer (Owner/Manager/Executor). Rhushabh: there are only **two** permission tiers — "can send broadcast notice" and "cannot" — every other feature (task creation, assignment, etc.) is available to everyone regardless of level. A separate per-vertical "Profile" field (Education vs MSME/CA-CS) exists but doesn't gate features. | This **contradicts** the current `TenantMembership.roleLevel` (`top/mid/executor`) in `domain-model.md` and `schema.prisma`, and the Dean/HoD/Faculty hierarchy baked into `CLAUDE.md`. Big enough to need your explicit confirmation before we touch the schema. |
| **W23 / W48–W52** | **There is no escalation engine.** Rhushabh: "no escalation — just tasks due today, tomorrow, overdue. Overdues are escalations." The whole escalation chain (Manager/Owner routing, thresholds, "overloaded" definition, top-of-org fallback) goes away — replaced by the existing due-date notification events. This **simplifies** the build (less to do), but it removes Notification Event #9 ("Escalation Triggered") as a distinct thing. |
| **W35** | **Member invite needs an admin portal**, not just the Excel/CLI re-import we'd already recorded (D19). Rhushabh: new users come in via email link + OTP, and **"we would update new user through our admin portal for the backend."** That implies an admin UI for adding members, not only a bulk script. |
| **W55** | **Reversed from the previous carried answer.** Old answer: new members never see broadcasts posted before they joined. Rhushabh: **"Yes, if the broadcast is still active in its 1 day life"** — i.e. visibility is just "is this notice still in its 1-day window," not gated by join date at all. |
| **W60** | **Billing — resolved per Rhushabh's priority.** "Answer" column said "decide later, no billing module in V1"; Rhushabh's column says "Per seat in org. Billing module in V1." Per your instruction, Rhushabh (main client) outranks the other column — **billing module IS in scope for V1, per-seat pricing.** Flagging only because billing wasn't on the MVP build-order list in `CLAUDE.md` — worth a build-order/timeline gut-check given the 30 June deadline, not because the decision itself is in doubt. |
| **W63** | ✅ **Resolved (2026-06-20).** Audit log is in V1 scope. Full `AuditLog` table added to schema V1.1 — immutable rows, `actorType USER\|SYSTEM`, `before`/`after` JSONB snapshots, all critical actions logged (task CRUD, status changes, broadcast, evidence, user login/logout). CA/CS vertical requires this from day 1. |
| **W16** | ✅ **Resolved by PRD v1.1.** Two-tier model supersedes this round-2 fully-private model. See round-3 flag update above. |

---

## 🔴 PRD Contradictions — Resolve Before Any Development

| # | Contradiction | Old Answer (confirmed) | New PRD Says | Status |
|---|---|---|---|---|
| **W-C1** | Task rejection by assignee — still in scope? | Q16: YES — rejection with reason text box. Q19: Returns to Open | New PRD state machine has no rejection path | ✅ Resolved — **No rejection in V1. Assignee can only accept.** Reconfirmed by Rhushabh: "Assignee can not reject a task in V1." (2026-06-17) |
| **W-C2** | AI daily nudges — in or out? | Q23: NO (excluded from MVP) | PRD §5.7: AI nudges assignee daily | ✅ Resolved & refined — **Nudging is required, for every task in the "My Tasks" list, fired daily, on both web and app.** Trigger detail (W36): fires per office hours, and the nudge persists/recurs until the user responds to it. (2026-06-17) |
| **W-C3** | Mandatory task fields — Title+Assignee, or +Due Date? | n/a (PRD-internal inconsistency) | §3.1 optional vs §5.1 required | ✅ Resolved — **Title + Assignee + Due Date, required only at the Draft → Open transition.** A Draft can be saved missing any of these — confirmed directly by the client (2026-06-17). Final discussion still to come, but build against this now. |

---

## Section 1 — Auth & Session

| # | Question | Status |
|---|---|---|
| **W1** | Session timeout / refresh tokens? | ✅ Resolved — **One-time login for web. Session persists until the user explicitly logs out** (implementation detail — cookie/storage strategy — left to us). Matches our existing httpOnly-cookie decision. (2026-06-17) |
| **W2** | SSO / Google sign-in, or Email+OTP only? | ✅ Resolved (new) — **Email OTP only, for now.** No SSO in V1. (2026-06-17) |
| **W3** | Tenant onboarding via Excel sheet — confirmed? | ✅ Resolved — **Yes**, confirmed again. (2026-06-17) |
| **W35** | Member invite flow post-onboarding? | ✅ Resolved, **see 🚩 flag above** — **Email link + OTP login.** New users are added on our side **via an admin portal** ("we would update new user through our admin portal for the backend") — not purely the Excel/CLI re-import we'd previously assumed (D19). Login flow: user enters email → we check it exists in the tenant's DB → if yes, send OTP. (2026-06-17) |

---

## Section 2 — Voice AI & Transcription

| # | Question | Status |
|---|---|---|
| **W4** | Live transcription ownership — client's Voice AI module, or ours? | ✅ Resolved (2026-06-17) — **The client's SDK owns it.** Live on-screen transcription display, interpretation, and intent/field extraction are all the SDK's responsibility — not ours. We only receive the final `{ intent, entityType, operation, jsonBody }` once it's done. Flow diagrams for this contract are built — see **W68** / `diagrams.html` §9–10. |
| **W5** | Voice session model — cumulative or fresh per mic press? | ✅ Resolved — **Fresh/isolated.** Press mic to start recording, press again to stop. Pressing again after that starts a brand-new audio note (not appended). Low-confidence transcription gets flagged to the user. (2026-06-17) |
| **W6** | Retakes — additive or replacing? | ✅ Resolved — **Overrides.** Second input replaces the first (matches the fresh-session model in W5). (2026-06-17) |
| **W7** | Panel-wise mic restriction (subtask mic only creates subtasks, etc.)? | ✅ Resolved — **No restriction.** The mic is context-aware and "can create any entity from anywhere," regardless of which panel it was pressed in. (2026-06-17) |
| **W8** | Full list of supported voice commands beyond task creation? | ✅ Resolved (2026-06-17, client's direct text, supersedes the earlier "open-ended" answer) — Voice is the product's **USP**. In scope: **full CRUD on Task, StickyNote, and BroadcastNotice; search; and navigation** (switching the workspace view, per `system-design.md` §0). Target: **70–80% of all operations done via voice.** New follow-ups raised by this: see **W66** (does CRUD extend to Comments/Evidence/Labels/Reminders/Subtasks?) and **W67** (should destructive voice ops like delete require a confirm step?). |
| **W36** | AI nudge trigger conditions (if W-C2 confirmed in scope)? | ✅ Resolved — **Fires during office hours; the nudge persists/recurs until the user responds to it; applies on web too** (not just the app). (2026-06-17) |

### Voice Data Storage & Retention

| # | Question | Status |
|---|---|---|
| **W37** | Store the original voice audio clip after task creation? | ✅ Resolved + cascaded (2026-06-27) — **Yes, opt-in.** New `VoiceRecording` table (16th entity) stores: `rawTranscript` (always), `audioUrl` S3 key (opt-in), `language`, `durationSecs`, `confidenceScore` (from SDK). 1:1 with Task. Cascaded into `domain-model.md`, `api-spec.md §6`, `system-design.md`. |
| **W38** | Who can access stored audio? | ✅ Resolved — **Assigner and assignee only.** (2026-06-17) |
| **W39** | Source of truth — audio or final edited form? | ✅ Resolved — **Final edited form**, by client's own framing: "Does not matter to us. The user interprets the task in their way and performs it." (2026-06-17) |
| **W40** | Can the user replay/re-record before saving? | ✅ Resolved — **changed from the earlier "yes."** Rhushabh: **no replay needed** — since the voice has already been transcribed, the user can see what's going on from the transcript. If they don't want it, they cancel and re-record (new isolated session, per W5/W6) rather than replaying the old clip. (2026-06-17) |
| **W41** | Voice audio retention policy? | ✅ Resolved — **6 months to 1 year.** (Slightly tighter than the earlier "1 year then ask" — exact cutoff still to be pinned before the scheduler is built.) (2026-06-17) |
| **W42** | Low-confidence transcription handling? | ✅ Resolved — **Highlight the low-confidence word/field to the user**; they can figure out the rest. (2026-06-17) |
| **W43** | Privacy/legal concerns about storing voice recordings? | ⏳ **Unclear — not actually answered.** Rhushabh: "Will check." Treat as still open, low priority. |
| **W44** | Encryption at rest for voice audio? | ✅ Resolved — **Yes, if easily implementable; otherwise defer to V2.** (2026-06-17) |

---

## Section 3 — Task & Subtask Rules

| # | Question | Status |
|---|---|---|
| **W9** | Max subtask nesting depth? | ✅ Resolved — **No limit.** (2026-06-17) |
| **W10** | Can one task have multiple subtasks; is there a max count? | ⏳ **Max count still not actually answered** — client's answer addressed a different rule instead: **(1)** a subtask's due date must be earlier than the parent's (validate before creating it — ties into W11), **(2)** no assignment loops — **a subtask cannot be assigned back to the parent task's own delegator.** (2026-06-17) |
| **W11** | Due date propagation through the task tree? | ✅ Resolved — **(a)** No — a subtask cannot have a later due date than its parent; enforced at creation (see W10). **(b)** If a subtask isn't completed before the parent's due date, the parent **cannot be marked complete** and enters overdue mode. **(c)** System warns. (2026-06-17) |
| **W12** | Can a completed (DoneD) task be reopened? | ✅ Resolved — **No.** "We do not reopen old completed tasks." (Reconfirms D15 — DoneD is terminal.) (2026-06-17) |
| **W13** | Full cascade on Cancel/Reopen/Due-date-change/Reassignment? | ✅ Resolved — **No reopening of any task, ever.** A due-date change on the parent does **not** cascade to subtasks — each subtask's due date is managed independently by whoever delegated *that* subtask. (2026-06-17) |
| **W14** | Evidence/comments — isolated per task or aggregated from subtasks? | ✅ Resolved — **Isolated.** Task detail shows comments/evidence for that task only. The subtask **list** is visible (so you can see they exist), but not their full detail inline. (2026-06-17) |
| **W15** | Task card/detail fields (PRD §8.2 blank) — what fields/actions? | ⏳ **Still open / still blocking.** Client's answer: **"Refer screens."** This needs to come from the Figma designs, not a written spec — pull it from Figma directly rather than waiting on more PRD text. |
| **W45** | If rejection were in scope — return state / reason box? | ✅ Resolved — **Moot. No rejection at all** (reconfirms W-C1). (2026-06-17) |
| **W46** | Timeout for task acceptance? | ✅ Carried — **None.** Task sits in the assignee's list until acted on. |
| **W47** | What happens to tasks when a user is removed from the org? | ✅ Carried — **Not handled in V1.** |

---

## Section 4 — Labels

| # | Question | Status |
|---|---|---|
| **W16** | Per-person labels — same task, different label per person? | ✅ **Resolved by PRD v1.1 (2026-06-18) — two-tier model.** Tier 1: one shared **Main Label** per task (`Task.projectLabelId` FK → `ProjectLabel`; assigner sets it; both parties can see it on the task). Tier 2: **Personal Labels** (`TaskPersonalLabel` join table, `(taskId, userId, label text)`; private per user; assigner never sees assignee's and vice versa). The round-2 Gmail-style fully-private model (D35) is superseded — PRD v1.1 is the authority. |

---

## Section 5 — Hierarchy & Permissions

| # | Question | Status |
|---|---|---|
| **W17** | Hierarchy-enforced assignment, or any-to-any? | ✅ Resolved — **Any-to-any.** "Anyone can assign to anyone — it's on users to understand hierarchy." No system-enforced validation. (2026-06-17) |
| **W18** | Skip-level assignment allowed? | ✅ Resolved — **Yes.** (2026-06-17) |
| **W19** | Designation model — hardcoded per vertical, or configurable? | ✅ Resolved — **see 🚩 flag above (major).** Rhushabh overrides Adarsh's 3-tier (Owner/Manager/Executor) proposal: there are really only **two permission tiers — can send a broadcast notice, or cannot** — every other feature is available to everyone regardless of level (differentiation handled at the implementation level, not the role model). A separate per-vertical "Profile" section exists (Education vs MSME/CA-CS) for display/labelling, not for gating behaviour. (2026-06-17) |
| **W20** | Generic parent-child reporting-manager model for delegation? | ✅ Resolved — **not actually a contradiction.** Client gave the dev team **free hand** on whether to build a hierarchy/reports-to tree — it's our call, and we're leaning toward implementing it. It would be used for analytics/org-structure (ties into W21/W27), **never** to gate/validate assignment (any-to-any per W17/W18 still stands; Rhushabh's "no relationship used for delegation" holds exactly as stated). (2026-06-17) |
| **W21** | Does BOLO store org chart as a system of record? | ✅ Resolved — **Yes, but scoped.** Org structure is **not** used for task routing, but **is** preserved/used for: broadcasting a notice, and team analytics — and per W20 above, possibly a reports-to field per user for that same purpose. (2026-06-17) |
| **W22** | Executor-level broadcast permissions? | ✅ Resolved — **Governed by the W19 binary flag**, not by org-role level. Whether an Executor-tier user can broadcast depends purely on whether they hold the "can broadcast" permission. (2026-06-17) |
| **W23** | Escalation chain — who are "Manager" and "Owner"? | ✅ Resolved — **see 🚩 flag above.** There is **no escalation chain.** "Delegator gets informed of overdue tasks" — that's the entire mechanism. (2026-06-17) |

### Escalation Engine Detail — now moot, see W23

| # | Question | Status |
|---|---|---|
| **W48** | Exact action when escalation fires — notify only, or grant edit rights? | ✅ Resolved — **N/A, no escalation.** Edit rights already always sit with the delegator regardless (per standard task ownership rules). (2026-06-17) |
| **W49** | Who configures escalation thresholds? | ✅ Resolved — **N/A.** "No escalation — just tasks due today, tomorrow, overdue. Overdues are escalations." (2026-06-17) |
| **W50** | Time windows per priority level before escalation? | ✅ Resolved — **N/A**, same as W49. (2026-06-17) |
| **W51** | Definition of "overloaded" as an escalation trigger? | ✅ Resolved — **N/A**, same as W49. (2026-06-17) |
| **W52** | What happens when escalation reaches the top with no one higher? | ✅ Resolved — **N/A**, same as W49. (2026-06-17) |

---

## Section 6 — Search

| # | Question | Status |
|---|---|---|
| **W24** | Search scope — global full-text, or scoped fields? | ✅ Resolved — **Entire scope** — full-text across all data the user can access. (2026-06-17) |

---

## Section 7 — Evidence & Attachments

| # | Question | Status |
|---|---|---|
| **W25** | Max evidence file size? | ✅ Resolved, **superseded by W69 (2026-06-17): 25MB is a per-task aggregate cap**, not a per-file limit — see W69. |
| **W69** | Allowed MIME types? Per-task attachment count limit? Per-file or per-task size cap? | ✅ Fully resolved (2026-06-17) — **Images and documents both allowed** (not images-only). **No limit on the number of attachments per task.** **Size cap is a per-task aggregate: all evidence files on one task share a single 25MB total budget** — this supersedes the old per-file framing in W25 (each individual file is no longer separately capped at 25MB; what matters is the running total for the task). |

---

## Section 8 — Analytics

| # | Question | Status |
|---|---|---|
| **W26** | Definition/formula for "task completion effectiveness"? | ✅ Resolved (placeholder) — Final formula still TBD on the client's end, but they gave us a placeholder so dev isn't blocked: **`(( #OnTime×1 + #BeforeTime×2 + #Overdue×−1 ) / TotalTasks) × 100`**. (2026-06-17) |
| **W27** | Do Dean/Director and HoD see different analytics views? | ✅ Resolved — **Org chart drives this.** Team analytics are visible per the user's position in the org structure (exact view differences between top-level and HoD still implicit, not fully spelled out). (2026-06-17) |
| **W28** | Analytics refresh — real-time or periodic? | ✅ Resolved — **Periodic, once a day.** (2026-06-17) |

---

## Section 9 — Platform & Deployment

| # | Question | Status |
|---|---|---|
| **W29** | Platform — Responsive Web vs PWA vs Desktop? | ✅ **Resolved, final (2026-06-17).** Both Responsive Web and PWA ship in V1 — the PWA is scoped to **desktop screen sizes only** (not offered on mobile). No offline capability in the PWA (per the separate no-offline-in-V1 decision) — it's an installable app shell, not an offline-capable PWA. Confirmed final by the client — not open for further discussion. |
| **W53** | Uptime SLA — 99.9% or 99.5%? | ✅ Resolved — **99.5% for V1.** Rhushabh deferred to Adarsh's answer here rather than overriding it. (2026-06-17) |

---

## Section 10 — Notifications & Reminders

| # | Question | Status |
|---|---|---|
| **W30** | Is Reminder a standalone entity, or a StickyNote variant? | ✅ Resolved — **StickyNote variant, confirmed twice.** Task-level reminders are sent from the task owner/delegator to the assignee (an action on an existing task, not a new entity). A personal reminder is "a sticky note with time and date" — still a `StickyNote` row, and **the due date automatically makes it function as a reminder** — no separate opt-in, no standalone `Reminder` table. (2026-06-17) |
| **W31** | Broadcast character limit? | ✅ Resolved — **~200 words** (no real design impact either way). (2026-06-17) |
| **W54** | Broadcast expiry — configurable or fixed? | ✅ Resolved — **1 day, fixed, not configurable** for now. (2026-06-17) |
| **W55** | Do new members see old broadcasts from before they joined? | ✅ Resolved — **see 🚩 flag above (reversed).** **Yes** — if the broadcast is still inside its 1-day active window, a new member sees it. Visibility is purely "is this notice still active," not gated by join date. (2026-06-17) |

---

## Section 11 — UI / UX Clarity

| # | Question | Status |
|---|---|---|
| **W32** | Where do Draft tasks appear in the UI? | ✅ Resolved — **Yes, build a dedicated Drafts section/tab.** (2026-06-17) |
| **W33** | Broadcast acknowledgement UI — what does sender/recipient see? | ✅ Resolved — **Just a read count** for the sender (no names/timestamps breakdown). Reuse the existing App's acknowledgement screen design as the reference for web. (2026-06-17) |
| **W34** | Offline sync conflict resolution UI? | ⏳ **Parked, not resolved.** "Need better clarity or discussion. Park it for now." Likely moot anyway given D3 (no offline support in V1) — revisit only if that decision changes. |

---

## Section 12 — Data, Compliance & Billing

| # | Topic | Status |
|---|---|---|
| **W56** | Single user in multiple orgs simultaneously? | ✅ Carried — **No.** (Rhushabh left this blank — no override; "Answer" column confirms.) |
| **W57** | Account deletion / right to erasure? | ✅ Resolved (slightly changed) — **"Up to the reporting manager"** rather than pure self-service-on-request as previously carried. (2026-06-17) |
| **W58** | Data retention after org deletion? | ✅ Carried — unchanged: archive → provide to org → permanently delete. |
| **W59** | Data ownership — tasks vs personal data? | ✅ Carried — unchanged. |
| **W60** | Billing model? | ✅ Module + pricing resolved — per-seat, in scope for V1 (Rhushabh's priority). ⚠️ **But the billing UI/flow itself is still explicitly undecided** — the client flagged this directly: "we still need the decision on... billing UI." (2026-06-17) |
| **W61** | RPO/RTO requirements? | ✅ Carried — unchanged. |
| **W62** | DPDP Act compliance? | ✅ Carried — **Not in V1**, unchanged. |
| **W63** | Audit log required? | ✅ **Resolved (2026-06-20).** In scope for V1. Full `AuditLog` table in schema V1.1 — all critical actions logged, immutable rows. |

---

## Section 13 — Workspace Architecture (new, from `Doc/Bolo Workspace Architecture v1.pdf`)

| # | Question | Status |
|---|---|---|
| **W64** | What data backs the Top Bar "readiness indicators"? The workspace architecture doc shows them in the persistent top bar and gives a voice example ("Show NBA readiness"), implying a NAAC/NBA-style accreditation-readiness metric for the Education vertical — but no field, formula, or entity for it exists anywhere in `domain-model.md` or `prd.md`. | ⏳ **Pending — to be asked of the client directly.** Not yet sent. Blocks building the Top Bar fully. |
| **W65** | Is "constant URL" a hard requirement (zero client-side routing at all), or is a single shell route with in-memory/query-param workspace state acceptable (for refresh-safety, shareable links)? | ⏳ **Pending — internal dev-team decision**, not a client question. Also blocks the `CLAUDE.md` routing-rule update and the `tech-playbook` write. |
| **W66** | Voice CRUD scope (W8) is explicitly Task/StickyNote/Broadcast — does it also extend to Comments, Evidence attachments, Labels, Reminders, and Subtasks? | ✅ Resolved (2026-06-17) — **Yes: Comments, Labels, Reminders, Subtask, Task, StickyNote, Broadcast.** Note: **Evidence was not included** in the client's list — voice-attaching a file/photo isn't really speakable, so this is read as a deliberate omission, not a gap. Flag if Evidence *should* be voice-triggerable (e.g. "attach evidence" opens a file picker via voice). |
| **W67** | Should destructive voice operations (e.g. "delete task X") require a confirmation step before executing, given the system has no undo/reopen anywhere (W12, W13)? | ✅ Resolved (2026-06-17) — **Yes, confirmation required before every destructive voice op. No undo/redo anywhere in the system** — confirmed explicitly, this is the only safety net. |
| **W68** | Deliverable owed: voice-intent flow diagrams. | ✅ Built (2026-06-17) — `docs/architecture/diagrams.html` §9 "Voice Command → Intent Resolution" (SDK handoff: intent + JSON body) and §10 "Voice Intent → Action Dispatch" (single dispatcher covering create/read/update/delete/search/navigate across all 5 distinct entities — Task incl. Subtask, StickyNote incl. Reminder, BroadcastNotice, Comment, ProjectLabel). |

---

## Section 14 — Member Import (resolved 2026-06-28)

| # | Question | Status |
|---|---|---|
| **W69** | When a department has multiple MID-level users in the import sheet, which one becomes `Department.headUserId`? The schema allows only one head per dept (`headUserId @unique`). | ✅ **Resolved (2026-06-28)** — **Option A: add `isHead` column to the Excel template.** Only one row per dept may have `isHead=true`; that user is set as `headUserId`. Two `isHead=true` rows for the same dept = whole import rejected (nothing written to DB). `isHead=true` is only valid for `roleLevel=MID`; invalid on TOP/EXECUTOR. `isHead` is an import-time instruction only — no new DB column needed; the result is captured in `Department.headUserId`. |

---

## Section 15 — Observability (opened 2026-07-01)

| # | Question | Status |
|---|---|---|
| **W70** | Production observability backend — **single choice, one backend per environment** (confirmed 2026-07-01: dual-shipping to both AWS and Grafana was considered and rejected for simplicity — one place to look, less ops surface). Either stay on the already-locked CloudWatch + Sentry, or migrate prod to the Grafana stack (self-hosted on EC2/OpenShift, or Grafana Cloud managed). | ⏳ **Pending — internal dev-team decision, explicitly deferred ("later we can setup").** Not blocking: app-side instrumentation (pino/prom-client/OpenTelemetry) is backend-agnostic regardless of which single backend prod ends up on, so this can be decided after the producer + dev stack are built without any app code changes. **Dev is locked: self-hosted Grafana stack only.** See `docs/architecture/system-design.md` §10.1. |

---

## Section 16 — Notification Channel Correction (2026-07-03)

| # | Question | Status |
|---|---|---|
| **W71** | Multiple docs (`CLAUDE.md`, `prd.md`, `system-design.md`, `domain-model.md`, `security.md`, `deployment.md`, `api-spec.md`) stated "all notifications in-app only, WhatsApp/email fully out of scope for MVP." This was **wrong** — reminder/due-date notification types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`) were always meant to also send email (via the same nodemailer/SMTP path used for OTP), not just in-app. All other notification types remain in-app only; WhatsApp remains out of scope for all types. | ✅ **Resolved (2026-07-03) — docs corrected, not a new decision.** Every affected doc updated with a Channel column / inline correction. **Still open:** `remindTaskService` (`POST /tasks/:id/remind`) is currently a validation-only stub — doesn't write the `Notification` row or send email yet (`AI_NUDGE_DUE_PROXIMITY`, the automatic due-date nudge, is similarly unimplemented). Building the actual email-sending logic is a separate follow-up task. |

---

## Section 17 — AI Nudge Design (2026-07-03)

| # | Question | Status |
|---|---|---|
| **W72** | `AI_NUDGE_DUE_PROXIMITY` vs `TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE` (and vs `REMINDER_FIRED`) looked like duplicate/redundant enum values covering the same event. | ✅ **Resolved (2026-07-03).** Not duplicates — two layers: `TASK_DUE_*`/`REMINDER_FIRED` are **one-shot** factual notices; `AI_NUDGE_DUE_PROXIMITY` is a **recurring escalation** layered on top, re-firing until the user acts. This **is** the entire escalation mechanism (no separate escalation engine, per W23/W48–W52). |
| **W73** | Does `AI_NUDGE_DUE_PROXIMITY` apply to StickyNote reminders, or Tasks only? | ✅ **Resolved (2026-07-03).** **Polymorphic — both.** Applies to overdue/due-soon Tasks AND StickyNote reminders (`dueAt` passed), via `entityType`/`entityId` on the existing `Notification` model (already supports `"task" \| "broadcast" \| "sticky_note"` — no schema friction). `AI_NUDGE_PERIODIC` and `AI_NUDGE_FOLLOWUP` remain **task-only** — no equivalent "progress" or "acceptance" concept exists for a sticky note. |
| **W74** | Exact deduplication window for AI Nudge recurrence — PRD explicitly flags this as **"exact value TBD before scheduler is built."** | ✅ **Resolved by approach (2026-07-04).** Not an admin-configurable DB setting — a **hardcoded constant in the nudge-sweep job's code**, sensible default chosen at implementation time, changed in code if it needs adjusting. No longer blocks anything. |
| **W75** | "Office hours" — PRD says all AI Nudge types "fire during office hours" but never defines the window (fixed org-wide, e.g. 9am–6pm IST, vs per-tenant configurable). | ✅ **Resolved by approach (2026-07-04).** Same as W74 — hardcoded constant in code, not a schema field, not admin-configurable via UI for now. No longer blocks anything. |
| **W76** | "Persists/recurs until the user responds" — what counts as a qualifying "response" per nudge type? Not defined per-type anywhere. | ✅ **Resolved (2026-07-03, revised 2026-07-04).** **Opening/viewing the task via the notification link does NOT count as a response, for any type.** Per type: **Periodic** → assignee posts a progress comment on the task. **Follow-up** → the specific expected action happens (accept task, reply to comment, etc.). **Due-proximity (Task)** → only a real progress/status/date change resolves it — there is no longer a separate "skip" response type (revised 2026-07-04, see W77 — the skip counter auto-increments on every unresolved firing, it isn't a user action). **Due-proximity (StickyNote)** → `dueAt` cleared/changed, or note deleted/marked done. |
| **W77** | Due-proximity skip mechanic. | ✅ **Fully resolved (2026-07-04, revised from the 2026-07-03 version).** **Not a user action, no API endpoint, no button.** Every sweep firing that finds the task still unresolved auto-increments `Task.dueProximitySkipCount` as part of that same backend operation. Capped at N lifetime increments per task (hardcoded constants, separate lower cap for overdue vs. due-today, same code-constant approach as W74/W75). The same firing that pushes the count over the cap also notifies the assigner in that instant (one-time in-app + email, never repeated after). Counter resets only if the due date moves back into the future or the task completes/cancels — otherwise lifetime. |
| **W78** | Daily nudge cap. | ✅ **Descoped (2026-07-04).** Not being built in the initial version — considered and explicitly skipped for now, may revisit if nudge volume proves to be a real problem in practice. `dailyNudgeCapPerUser` removed from the planned schema. **See W84** — this has a consequence that was accepted, not separately re-confirmed. |
| **W79** | AI Nudge UI — two separate screens/panels needed: (1) combined Periodic + Follow-up + Sticky-reminder nudges (simple close button, no counter), (2) Task due-proximity nudges specifically (urgency state + escalation, **no functional button now that skip is automatic — revised 2026-07-04**, may still have a cosmetic dismiss). **No Figma reference exists for either screen.** | ✅ **Approach resolved (2026-07-04) — build a rough placeholder/POC screen for both now, swap for the real design once a Figma reference exists.** Explicitly authorized as a one-off exception to the usual Figma-first rule. Not blocking implementation; a real Figma node ID is still wanted eventually. |
| **W80** | Periodic nudge batching — one notification per user covering all their active tasks, or one notification per task? | ✅ **Resolved (2026-07-04) — one notification per user (batched).** Summarizes all active tasks in one row, not one per task. Means Periodic has no single `entityId` — see W84's caveat. "Qualifying response" (W76) for Periodic remains "posts a progress comment on the task" — resolving the batch notification itself (e.g. marking it read) doesn't require resolving every listed task; the batch just reflects whatever's still active at the next sweep. |
| **W81** | Follow-up trigger conditions — PRD only gives examples ("e.g. accepted but no progress update, comment left unanswered"), never an exhaustive V1 list. | ✅ **Resolved (2026-07-04) — exactly the PRD's 2 examples, as the exhaustive V1 list.** (1) Task accepted but no progress update since. (2) A comment posted with no reply from the other party within the window. No additional conditions for V1. |
| **W82** | Does "Due Tomorrow" get recurring `AI_NUDGE_DUE_PROXIMITY` nudges at all? Only two skip-cap buckets are defined (due-today, overdue) — "due tomorrow" doesn't have one. | ✅ **Resolved (2026-07-04) — no third bucket needed.** "Due Tomorrow" does not get row 8d's recurring nudge at all — it's covered by the ordinary Periodic/Follow-up nudges like any other open task. Only once it becomes Due Today (or Overdue) does it enter the recurring/skip-cap/escalation mechanic. Confirmed: only 2 cap buckets exist (today, overdue). |
| **W83** | StickyNote due-proximity has no cap or escalation at all (no assigner to escalate to) — could nudge the owner indefinitely if ignored forever. | ✅ **Resolved (2026-07-04).** Time-based ceiling, not count-based: nudges only for the remainder of the calendar day the reminder was due, stops entirely at midnight regardless of resolution. No status field to check against (unlike Task), so a date-boundary cutoff is the natural equivalent to a lifetime cap. |
| **W84** | Cross-type nudge pile-up — since the daily cap (W78) was dropped, a user can receive separate Periodic + Follow-up + Due-proximity notifications about the same/related task in one sweep cycle, with no throttling across types. | ✅ **Fully resolved (2026-07-04) — option 4 (generic per-entity cooldown) chosen** over 3 alternatives (priority/suppression rule, merge-at-generation, do-nothing). Dedup check keyed on `entityType`+`entityId`, not just `type` — before firing, check whether *any* AI Nudge type already fired for this same entity within the cooldown window. **Confirmed scope (W80 resolved):** only applies between Follow-up and Due-proximity — Periodic is batched per-user, has no single entity to key on, doesn't participate. Accepted as fine. |

**AI Nudge design was fully resolved at W72–W84 (2026-07-04) — since substantially redesigned, see Section 18 below (2026-07-06).**

---

## Section 18 — AI Nudge Redesign: Action Buttons, Broadcast, Periodic Merge (2026-07-06)

Prompted by designing the actual nudge panel UI and realizing several of the W72–W84 decisions didn't hold up once nudges needed per-item action buttons. Supersedes the relevant parts of Section 17 — this section is the current source of truth for AI Nudge.

| # | Question | Status |
|---|---|---|
| **W85** | Both AI Nudge and Notification were scoped to different entity sets (Nudge: Task+StickyNote; Notification: Task/Subtask/Broadcast/StickyNote) — should they match? | ✅ **Resolved — both cover the same 4 entities:** Task, Subtask, Broadcast, StickyNote. |
| **W86** | Nudge rows only had an "Open" link — should they carry contextual action buttons matching what's actually missing (accept, comment, mark complete)? | ✅ **Resolved — yes, per scenario:** not-accepted → `Accept Task`; no-progress/unanswered-comment → `Add Comment`; `DONE_A` awaiting `DONE_D` / subtasks-done-awaiting-close → `Mark Complete` (assigner-facing). Evidence-attach considered, explicitly deferred — evidence-required rules are still open elsewhere. |
| **W87** | Once Periodic gained the same action-button treatment as Follow-up, and neither had a skip cap, was there still a real difference between the two types? | ✅ **Resolved — no difference remained, Periodic is retired.** Merged into Follow-up entirely. Follow-up now fires every 6h (was Periodic's conceptual slot) covering all 5 named conditions, each producing its own per-task/per-condition row with its own action button — no more batched "you have N tasks" summary, since a batch can't carry a single action button sensibly. |
| **W88** | Do Follow-up's assignee-facing conditions (not-accepted, no-progress, unanswered-comment) get a skip cap + escalation like Due-proximity does? | ✅ **Resolved — no.** All 5 Follow-up conditions (including the 2 new assigner-facing ones) track a DB skip counter for visibility only. No cap, no escalation on any of them. |
| **W89** | Do the 2 new assigner-facing Follow-up conditions escalate further up an org hierarchy (assigner's own manager) if ignored? | ✅ **Resolved — no.** No org-level escalation. Plain repeating reminder, no cap, no consequence — there's nothing above the assigner to escalate to in this model. |
| **W90** | Office-hours gating (9am–6pm IST) was a single-institution business-hours assumption — does it generalize across BOLO's multiple verticals/timezones/login patterns? | ✅ **Resolved — no, removed entirely.** Sweep now runs continuously (24/7), cadence purely from each type's own elapsed-time gap (Follow-up 6h, Due-proximity 3h). **Accepted consequence:** Task due-proximity's caps (3 due-today/1 overdue), sized for ~3 fires within a 9h window, now exhaust same-day within a few hours at ~8 fires/24h. Matches "overdue is urgent," just faster. Time-of-day itself stays a hardcoded constant for now; true per-user configurable scheduling is a future feature-flag-service item. |
| **W91** | Should Broadcast get its own nudge trigger, given it now shares entity scope with Task/StickyNote (W85)? Which trigger type — Follow-up, Due-proximity, or its own? | ✅ **Resolved — Due-proximity only, no Periodic-equivalent, not a Follow-up condition either.** Broadcast's urgency is entirely "the window to acknowledge this is closing" (1-day expiry) — exactly what Due-proximity represents. Cap of 3, **enforcement only, no escalation** (no sender-escalation target — exceeding the cap just removes the Skip affordance, forcing acknowledgment). Self-limits at the broadcast's normal 1-day expiry regardless of cap. |
| **W92** | Task due-proximity's last-chance behavior (skip count == cap, one firing before escalation) — what does the UI actually do differently at that point, and does the assignee get threatened over something outside their control? | ✅ **Resolved.** At last-chance: `Skip` button disappears, replaced by a warning ("will be escalated to your assigner if not actioned"); only `Add Comment`/`Open` remain. Any comment resolves it — no separate "remind me later" needed, Add Comment already covers that case. **Escalation bar is `DONE_A`, never `DONE_D`** — the assignee is only ever held accountable for what they actually control (`DONE_A`); confirming a task to `DONE_D` is the assigner's job, so the assignee can't be threatened over it. If the task reaches `DONE_A` before the next sweep, it naturally drops out of the due-proximity query entirely (no longer `OPEN`/`IN_PROGRESS`/`OVERDUE`) — no escalation fires. |
| **W93** | Nudge panel UI structure — single list or split screens? Filter dimensions? Can the panel just be closed at any time? | ✅ **Resolved.** Single unified scrollable list, **not** split screens. Two independent, combinable filters: Type (All/Follow-up/Due-proximity) and Entity (All/Task/StickyNote/Broadcast). **Panel is blocking** while any Due-proximity item is unresolved (must skip or resolve each one) — Follow-up items never block closing. `Skip All` bulk-skips every currently-skippable item at once in one click; disabled if any single item is at last-chance (that one needs individual resolution first). |
| **W94** | Skip counters — with 5 Follow-up conditions plus Task/StickyNote/Broadcast Due-proximity all needing their own counter, does `Task.dueProximitySkipCount`/`dueProximityEscalatedAt` still scale? | ✅ **Resolved, built 2026-07-10.** Replaced with a generic polymorphic `NudgeSkipCounter` table — confirmed shape adds `tenantId` (RLS) and `userId` (correctness fix: without it, Broadcast's many-recipients-per-entity shape means every recipient shares one skip count) on top of the original `(entityType, entityId, nudgeKind)` proposal, keyed on `(userId, entityType, entityId, nudgeKind)`. See `domain-model.md` row 8c/8d for the exact shape and `docs/api/api-spec.md` §11 for the `GET /nudges`/`POST /nudges/:id/skip`/`POST /nudges/skip-all` endpoints built on top of it. `AI_NUDGE_PERIODIC` also removed from the `NotificationType` enum in the same migration. |

**Section 18 is fully resolved and built** — backend Phase 1 (schema, sweep rewrite, `/nudges` API) shipped 2026-07-10, live-tested against the real local DB. Frontend (`bolo-web`, `feature/ai-nudge`) still runs on mock data pending the switch to these real endpoints.

**Superseded 2026-07-13 — client scoped the feature down substantially** after reviewing the full build: Task-only (no Subtask/StickyNote/Broadcast), Follow-up cut to 2 assignee-only conditions (no Accept/Mark Complete anywhere), no blocking behavior (Skip never disabled, panel never forced closed), feed capped at 5 with priority-then-rotation ordering. See `domain-model.md` row 8c/8d and `changelog.md` 2026-07-13 for the full spec. Built on a new `feature/ai-nudge-scoped` branch (both repos) — `feature/ai-nudge` kept intact rather than modified in place, so the fuller original build is still there to pick from if any of this gets walked back. Backend-only so far; frontend not yet updated to match.

---

## Section 19 — Audit Log Middleware Build (2026-07-14)

| # | Question | Status |
|---|---|---|
| **W95** | `AuditLog.entityType` casing contradiction: `domain-model.md` documented lowercase (`"task"`, `"broadcast"`...), matching `Notification.entityType`; `api-spec.md` §12's `GET /audit-log` examples used UPPERCASE (`"TASK"`, `"BROADCAST"`...). Surfaced while planning the audit-log write path (dev-team question, not sent to client). | ✅ **Resolved (2026-07-14) — UPPERCASE is canonical.** `domain-model.md` corrected to match `api-spec.md`. `AuditLog.entityType` deliberately does **not** share a convention with `Notification.entityType` — two independent polymorphic-reference fields, no requirement they match. |
| **W96** | Should an `AuditLog` write failure ever block/roll back the business action it's recording? | ✅ **Resolved (2026-07-14) — fire-and-forget.** Mirrors `dispatchNotification.service.ts`: fault-isolated in a try/catch, logged on failure, never throws back to the caller. Chosen so audited business operations (task update, broadcast publish, etc.) never fail because the audit write failed — same rationale as the existing notification dispatcher, applied consistently rather than inventing a stricter rule for one cross-cutting concern and not the other. |
| **W97** | `api-spec.md` §12's `entityType` filter list includes `STICKY_NOTE` and `PROJECT_LABEL`, but neither `AuditAction` enum values nor `security.md`'s "critical actions" list cover StickyNote or ProjectLabel CRUD — those filter values currently have nothing to return. | ⏳ **Open — flagged during planning, not yet decided.** Either extend `AuditAction` with StickyNote/ProjectLabel actions and add them to the security.md critical-actions list, or drop those two values from the api-spec filter enum as aspirational/out-of-scope. Does not block Phase 1 (Task/Broadcast/User/Document) — resolve before building the `GET /audit-log` filter validation. |
| **W98** | Should `AuditLog` rows be written the same way as `Notification` — an explicit `dispatchAuditLog()` call added to every service that needs auditing — or captured generically without touching services? User explicitly asked for "the same as the logging [middleware] we have" (`requestLoggerMiddleware`/`metricsMiddleware` — registered once, applies to every request automatically) and "no need to touch the API/service directly." | ✅ **Resolved (2026-07-14) — generic middleware + static route-config table**, deliberately the *opposite* of the Notification dispatcher pattern. See `system-design.md` §2.6 for the full mechanics (before/after capture, action-resolution via response-body diffing for the one generic `PATCH /tasks/:id` catch-all). Rationale: unlike a `Notification`, an `AuditLog` row needs no hand-written business content — it's mechanically derivable from the request/response/DB-diff, which a generic layer can do; a `Notification`'s message text cannot. |
| **W99** | The generic middleware (W98) can only observe events that cause a DB write it can diff. `verifyOtpService` writes nothing to `User` on login; `logout.controller.ts` makes zero DB calls. How should `USER_LOGIN`/`USER_LOGOUT` be captured given this? | ✅ **Resolved (2026-07-14) — add `User.lastLoginAt`/`lastLogoutAt`.** Those two flows now write a real timestamp field (also independently useful for session tracking), which the generic middleware then picks up the same way it picks up every other field change — no special-cased audit call anywhere. Cost, confirmed accepted by the client-facing dev decision: `verifyOtp.service.ts` gets one added line; `logout.controller.ts` gains a real service/repository layer for the first time (was controller-only, no Prisma call, before this). See `domain-model.md` User entity and `system-design.md` §2.6. |
| **W101** | A separately-built platform-admin/superadmin feature (PR #33, cross-tenant tenant/member management, outside normal `req.user`/tenantId auth) landed 4 services calling a nonexistent `AuditLogRepository.log()` method — broke `develop`'s build. Should platform-admin actions get a second explicit-call exception alongside login/logout (W98/W99), or be brought into the generic-middleware-only model some other way? User explicit: "We have to use the middleware only no log method." | ✅ **Resolved (2026-07-17) — extended the generic middleware with a second actor source**, not a second exception. `AuditRouteRule` gained `actorSource: 'platformAdmin'` (reads `req.platformAdmin` instead of `req.user`; `actorId` always `null` since `PlatformAdmin` isn't a `User` row, FK has no target), `tenantIdParam` (platform admins have no tenant of their own — resolved from the target tenant via path param or, for tenant-creation, the response body), and `entityIdResponseField` (their controllers return `{tenantId}`/`{userId}`, not `{id}`). All 4 manual `.log()` calls removed. `AuditActorType.PLATFORM_ADMIN` and the 4 new `AuditAction` values already existed in schema from PR #33 — no migration needed. `AuditLog.entityType` gained a `TENANT` value; `GET /audit-log`'s `entityType` filter enum and `actorType` documentation updated to match (`api-spec.md` §12, `swagger.ts`, `getAuditLog.service.ts`'s `VALID_ENTITY_TYPES` — the last one was a real validation gap, not just a doc gap: without it, filtering `?entityType=TENANT` would have 400'd despite those rows existing). See `system-design.md` §2.6. |

---

## Section 20 — AWS Staging Setup (2026-07-15/16)

| # | Question | Status |
|---|---|---|
| **W100** | **CONTRADICTION — transactional email provider.** Surfaced mid-`staging-setup.md` Step 5 (Secrets Manager), while storing SMTP-related secrets/params. `prd.md`, `security.md`, `api-spec.md`, and `sprint-plan-4w.md` all specify **AWS SES** for OTP/transactional email. `CLAUDE.md` and the infra docs (`staging-setup.md`, `deployment.md`, `deployment-proposal-client.md`) all specify **Gmail SMTP via nodemailer** instead — no SES anywhere in the infra plan or cost breakdown. Checked the actual codebase for `nodemailer` or an AWS SES SDK call to settle it empirically — **neither exists yet**; the email-sending logic hasn't been built, so there's no code-level ground truth either. | ✅ **Resolved (2026-07-16) — AWS SES, client confirmed.** Asked the client directly; answer: "SES is approved." `CLAUDE.md`, `deployment.md`, `staging-setup.md` updated to match `prd.md`/`security.md`/`api-spec.md`/`sprint-plan-4w.md` — SES is now the single documented provider everywhere. **Still blocked on the pending official sender email/domain** (same blocker as before, now SES-shaped specifically: SES requires a verified domain or sender identity before it can send anything) — this part doesn't unblock until the client's domain arrives. **Sub-item resolved (2026-07-18):** transport mechanism — went with the AWS SDK (`@aws-sdk/client-ses`, `ses:SendEmail` via the EC2 IAM role, no static credentials), not SES's SMTP interface, for consistency with this project's existing IAM-role-over-static-keys pattern for S3/ECR. `bolo-backend/src/utils/email.ts` rewritten accordingly — `nodemailer` and all `SMTP_*` env vars removed. Email template content unchanged, only the transport layer. Committed on `chore/backend-handoff-ses-routing` (not yet merged). `bolo-ec2-role`'s `ses:SendEmail`/`ses:SendRawEmail` permission (granted earlier, no-regret either way) now actually in use. |

---

## Section 19 — Sticky Note Promote: `assigneeId` Required vs. Optional (found 2026-07-11)

Building the full Sticky Note CRUD API (`GET/PATCH/DELETE /sticky-notes`, `POST /sticky-notes/:id/promote`) surfaced a pre-existing contradiction, not introduced by this work.

| # | Question | Status |
|---|---|---|
| **W95** | `docs/api/api-spec.md` §9's promote endpoint documented `assigneeId` as optional ("leave blank to save as Draft"), consistent with W-C3's general rule that any field can be omitted on a Draft. But `Task.assigneeId` is a required, non-nullable column in `schema.prisma`, and `createTask.service.ts` already enforces it as required for every task (not only at Draft→Open) — this gap predates the sticky-note work. Should promote match the doc (requires a nullable `assigneeId` column + relaxing `createTask` too) or the existing enforced behavior? | ✅ **Resolved for now — matches existing enforced behavior.** `promoteStickyNote.service.ts` requires `assigneeId` (400 if missing), same as `createTask.service.ts`. `api-spec.md` §9 corrected to say "required." Making `assigneeId` truly optional (Drafts with no assignee) is a bigger schema change (nullable FK + `createTask` relaxation) that should be scoped as its own task rather than decided implicitly here — revisit if the client confirms Drafts genuinely need to support "no assignee yet." |

---

## Section 20 — Broadcast Notice: Who Can Acknowledge? (found 2026-07-13)

Manually testing the Broadcast Notice API end-to-end surfaced a real gap: `docs/api/api-spec.md` §10's original `POST /broadcast-notices/:id/ack` access rule ("`requireAuth`. Broadcast must be `PUBLISHED` and not expired. `requiresAcknowledgement` must be true.") never restricted *who* could acknowledge — any tenant member could ack any broadcast by ID, including the sender acknowledging their own notice, even though `GET /broadcast-notices` (the list/feed) already restricts *visibility* to audience members only (`audienceDeptId`+`audienceRoleLevel` matching the caller). Net effect: the broadcast's own creator could acknowledge a notice they could never actually see in their own feed.

| # | Question | Status |
|---|---|---|
| **W96** | Should acknowledging a broadcast require being in its audience (same dept+roleLevel match as the list feed), or is any tenant member acknowledging by ID acceptable? | ✅ **Resolved — restrict to audience members.** `acknowledgeBroadcastNoticeService` now applies the identical audience-match check used by `findActiveForAudience` (list): 403 `NOT_IN_AUDIENCE` if the caller's dept/roleLevel don't match. This applies to the sender too — they can only ack their own broadcast if they'd also see it in their own feed (no special-case exclusion beyond the match itself). `api-spec.md` §10 updated. |

---

## Section 21 — Broadcast Notice: How Does a Sender See Their Own Broadcast? (found 2026-07-14)

Direct follow-on from W96: once acknowledging was correctly restricted to audience members, the same underlying asymmetry showed up one layer higher — a sender who broadcasts *outside* their own role/dept (the common case: Dean → HoDs, HoD → Faculty) never matches their own audience, so they had **no way to see anything they'd sent** via any endpoint — not even their own `DRAFT`s, since `GET /broadcast-notices` only ever returned audience-matched, `PUBLISHED` rows.

| # | Question | Status |
|---|---|---|
| **W97** | Should there be a separate endpoint for "broadcasts I sent," or should the existing list endpoint grow a mode switch? | ✅ **Resolved — extended the existing endpoint, no new route.** Mirrors the precedent already set by `GET /tasks?view=assigned\|delegated\|needs_attention` (same "same list, different perspective" shape). `GET /broadcast-notices?view=received\|sent` — `received` (default, unchanged, backward compatible) is today's audience-feed behavior; `sent` (new) returns everything `senderId = me` created, any status (`DRAFT` + `PUBLISHED` + expired), for the sender's own management view. `api-spec.md` §10 updated. |

---

## Section 22 — Voice Command Known Limitations (found 2026-07-21)

Building the full voice command manual test plan (`docs/engineering/testing-strategy.md`) surfaced several accepted, non-blocking scope limitations — recorded here rather than left as tribal knowledge, since none of them are bugs but all of them are worth a future developer knowing about before "fixing" them.

| # | Question | Status |
|---|---|---|
| **W102** | `deterministicFallback()` (used when `OPENAI_API_KEY` is missing/down) doesn't recognize any of the newer intents added past the original 10. Should it be kept in parity with the GPT prompt? | ✅ **Accepted — not kept in parity.** Only matters if the API key is missing/down; the GPT path covers everything in the test plan. Revisit only if outages become frequent enough to matter. |
| **W103** | The ambiguous-assignee picker (e.g. two users both named "Priya") shows the full org directory rather than a pre-filtered shortlist of just the colliding names. Worth narrowing? | ✅ **Accepted as-is.** Still never guesses wrong between homonyms — just more scrolling than an ideal pre-filtered list. Low priority polish item. |
| **W104** | Compound ambiguity — a `task_update` command with both an ambiguous task title *and* an ambiguous label in the same sentence — silently drops the label change after the task is picked. Fix now or accept? | ✅ **Accepted — rare compound edge case.** Not expected to come up often enough to justify the added disambiguation-flow complexity right now. |
| **W105** | "Assign it to myself, due today" spoken with zero surrounding context doesn't reliably resolve to `create_task` — the model reads "it" as referring to an already-open task. Needs a fix? | ✅ **Accepted — genuinely ambiguous in isolation, safely handled.** Caught by the `task_action` action-enum guard (changelog 2026-07-21 (4)) rather than misfiring. Real usage almost always has a preceding "create a task..." utterance establishing "it," so this hasn't been observed as a real-world problem. |
| **W106** | Voice-deleting the task/comment/sticky/label currently on screen leaves that page in an error state (with retry) instead of auto-navigating away, even though the query cache is correctly invalidated. Should pages auto-redirect? | 🟡 **Open, low priority.** Not a crash, just a rough edge — no page currently reacts to "the thing I'm viewing no longer exists" by redirecting. Candidate for a future UX pass, not blocking. |
| **W107** | "Search for X" (voice `filter_tasks` keyword) only matches task title + label, not description. Full-text-across-everything was the implied ask — worth a backend change? | ✅ **Accepted, scope note added to test plan.** The list endpoints (`AssignedToMe`/`DelegatedTasksPage`, both list-based, not detail-based) don't return `description` at all — searching it would need a backend response-shape change. Out of scope for the frontend-side filter fix that shipped; revisit if a backend change to the list endpoints happens for another reason. |
| **W108** | "Cancel this task" always shows the subtask-cascade warning in the confirm dialog, even for tasks with zero subtasks. Should the dialog be made conditional? | ✅ **Accepted — truthful, just occasionally unneeded caution.** No subtask-count is threaded through voice context today (only id/title/due date are). Not incorrect, just occasionally more cautious than strictly necessary. |
| **W109** | Two voice commands ("what's the weather"; "go to sticky wall") don't classify exactly as expected by category (`out_of_scope` instead of `unknown`; `filter_reminders` instead of `navigate`) despite two rounds of prompt tightening. Keep chasing, or accept? | ✅ **Accepted — no observable user-facing difference.** Both pairs produce an equally graceful outcome (a non-crashing decline message; the same `StickyWall` page) regardless of which of the two intents fires. Not chasing further. |

---

## Critical Gaps (Still Blocking or Needing a Follow-up Conversation)

| Priority | Gap | Why it's still open |
|---|---|---|
| 🔴 | **W16** — Labels | Reopened 2026-06-17 — client says still needs a decision despite a detailed Excel answer; do not build against the Excel model yet. |
| 🔴 | **W15** — Task card/detail fields | Client says "refer screens" — needs a Figma pull, not more PRD text. |
| 🟡 | **W60** — Billing UI/flow | Module + pricing confirmed (per-seat, in V1); the UI/flow itself is explicitly still undecided per the client. |
| ✅ | **W63** — Audit log scope | **Resolved (2026-06-20).** In scope for V1. Full AuditLog table in schema V1.1. |
| 🟡 | **W19** — Org-role/permission model | Resolved per Rhushabh, but it's a big enough architecture change (3-tier → 2-tier) that it's worth a sentence of explicit confirmation before we touch `schema.prisma`. |
| 🟢 | **W34** — Offline conflict resolution UI | Parked by client, and moot since V1 has no offline mode anyway. |
| 🟢 | **W43** — Voice recording privacy/legal concerns | "Will check" — not an actual answer, low priority. |
| 🟢 | **W10** — Max subtask count per parent | Still technically unanswered (client answered a different, related rule instead). |
| 🟢 | **W106** — Voice-deleted entity leaves an error state on screen | Not a crash, cache invalidation works — just no page auto-redirects when the thing it's viewing no longer exists. Low priority UX polish. |

---

*Last updated: 2026-07-21 — §22 (voice command known limitations, W102–W109) added. Previous: 2026-06-17 (Rhushabh's answers from the client Google Sheet, round 2) | Next: incorporate the user's verbal PRD update notes, then update `docs/product/prd.md` and propagate confirmed changes into `domain-model.md` / `system-design.md` / `api-spec.md` / `schema.prisma` / `design-session.md`.*
