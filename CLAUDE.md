# BOLO-BACKEND-DJANGO — CLAUDE.md

> Read this file completely at the start of every Claude Code session.
> This is the single source of truth for **this project only**.
> **This is a standalone Django + DRF re-implementation of the BOLO backend** (originally Node/Express/Prisma, in the sibling `Bolo/` repo). It is a **port, not a redesign** — same API contract, same domain model, same business rules. `bolo-web` (React, in the original `Bolo/` repo) is a completely separate project and only talks to whichever backend is running over HTTP, via `VITE_API_URL`. Nothing in `bolo-web` needs to change for this project to work, as long as the contract in `docs/api/api-spec.md` is honored exactly.
> **Last updated:** 2026-08-16 — **AI Nudges** (`apps/notifications`), closing ROADMAP.md Phase 8's last remaining piece, explicitly flagged as out of scope in the two immediately preceding sessions: `GET /nudges`, `POST /nudges/:id/skip`, `POST /nudges/skip-all` (`docs/api/api-spec.md` §11) plus two recurring Celery beat sweeps, `AI_NUDGE_FOLLOWUP` (every 6h) and `AI_NUDGE_DUE_PROXIMITY` (every 3h). Built against `domain-model.md` rows 8c/8d and `open-questions-web-v1.md` Section 18's 2026-07-13 narrowing (Task-only, Follow-up cut to 2 assignee-only conditions, no blocking, feed capped at 5) — **found api-spec.md §11 itself still carries two contradictory `GET`/`POST /nudges` sections**, an older one (~line 1487, "2026-07-06 redesign") with the pre-narrowing Subtask/StickyNote/Broadcast scope and `409` cap-rejection responses, superseded by the section just above it (~line 1351) that actually matches the current narrowed spec; built against the latter, flagged the doc contradiction since section *order* in this file doesn't track recency here unlike every other doc-staleness call so far in this project. `apps/notifications/nudge_rules.py` (new) is the single source of truth for nudge eligibility — `classify_followup()`/`due_proximity_bucket()` — shared by the sweeps (fire a fresh notification) and `NudgeService.get_feed()` (re-validate an existing unread one against current state on every call, auto-resolving anything stale); re-running `classify_followup` fresh is what makes "Add Comment resolves the Follow-up nudge" work with zero special-casing, while Due-Proximity needed a separate `resolved_by_comment_since()` check since its own eligibility function never looks at comments. `NudgeSkipCounter`'s model/migrations already existed untouched since the Phase 1 scaffold — this session is the first to build service/repository/view/sweep logic on top of it, no new migration needed. Due-Proximity's cap (3 due-today / 1 overdue) lives on one counter row keyed by `nudge_kind` regardless of which bucket is currently active, so a task that's already been skipped twice while due-today re-evaluates against the stricter overdue cap the moment it rolls over. Escalation (one-time in-app+email to the assigner once `skip_count >= cap`) is checked every Due-Proximity sweep tick independent of whether a routine notification also fires that cycle, guarded by `NudgeSkipCounter.escalated_at`. Cross-type dedup (W84's "cooldown window," never given an exact value upstream per W74) implemented as "don't fire a new AI Nudge while an earlier unread one for the same recipient+entity still exists" rather than a fixed elapsed-time window — a documented judgment call, same class as this project's other W74/W75-style resolutions. **Explicitly not built:** `domain-model.md`'s "first-login-of-the-day fast-track" interval-gate bypass — designed for the original Node backend's single continuous 15-min-tick sweep with internal per-user elapsed-time gating, which doesn't map onto this project's already-established one-fixed-crontab-per-sweep-type shape (`task_due_proximity_sweep`, `sticky_note_reminder_sweep`). Not audited (no `NUDGE_*` `AuditAction` values exist). 37 new tests, 231 total, all green; `ruff check` clean. Full breakdown in `changelog.md`'s 2026-08-16 entry. Previously: 2026-08-12 (2) — **Due-date reminder sweep**, closing a gap flagged (but explicitly not built) in the two immediately preceding sessions: `TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE` (`docs/api/api-spec.md` §11 row 8) and `StickyNote`'s `REMINDER_FIRED` were never dispatched — only the sticky-note retention-delete job existed. ROADMAP.md Phase 8's remaining piece. New daily Celery beat job `apps/tasks/tasks.py:task_due_proximity_sweep` (`crontab(hour=7, minute=0)`) notifies **both assignee and assigner** (in-app + email) for tasks due today/tomorrow, and transitions `OPEN`/`IN_PROGRESS` → `OVERDUE` (+ notifies) once a due date fully passes — `domain-model.md`'s notification-events table (both parties) taken over `api-spec.md` §11's older per-type table (assignee only), same kind of correction call as prior sessions. **Found and fixed a latent bug while building this**: `OVERDUE` was a real `TaskStatus` value nothing ever actually set, so the documented "an `OVERDUE` task auto-reverts to `OPEN`/`IN_PROGRESS` if its due date is edited forward" business rule had no implementation at all — added to `TaskService.update_task` in the same pass (reverts to `IN_PROGRESS` if already accepted, else `OPEN`). One-shot guards are real persisted DB fields, not a cache/TTL — new `Task.due_today_notified_at`/`due_tomorrow_notified_at` (migration `0007`) and `StickyNote.reminder_fired` (migration `0005`); `TASK_OVERDUE` needs no field since the status transition itself is the guard. Both new sweep tasks (`task_due_proximity_sweep`, `apps/sticky_notes/tasks.py`'s new `sticky_note_reminder_sweep`) declare `autoretry_for=(SMTPException,)` per `ROADMAP.md` Phase 8's explicit ask, safe because of the idempotent-by-design guards. `REMINDER_FIRED` swept every 15 minutes (not daily) since a sticky note's `dueAt` can land any time of day. **Explicitly not built:** the recurring `AI_NUDGE_FOLLOWUP`/`AI_NUDGE_DUE_PROXIMITY` skip-cap/escalation system (`GET /nudges`, `NudgeSkipCounter`) — a separate, much larger feature; this session only covers the one-shot due-proximity/reminder notifications. 17 new tests, 194 total, all green; `ruff check` clean. Full breakdown in `changelog.md`'s 2026-08-12 (2) entry. Previously: 2026-08-12 — **Global Search** (`apps/search`, new app, no new DB tables — pure read-layer over `Task`/`StickyNote`): `GET /search/tasks` + `GET /search/stickies` per `docs/api/api-spec.md` §13 / `docs/api/global-search-ai-contract.md`. Resolved a real design conflict flagged before building anything — `ROADMAP.md`'s Phase 7 plan (Postgres FTS + `pg_trgm`, one endpoint, four entity types) predates the 2026-08-03 docs re-sync and was superseded by it (two endpoints, Task+Sticky only, OpenAI `gpt-4o-mini` query-understanding + plain `ILIKE`, verified against real upstream source). **User explicitly chose "build to api-spec.md's contract, with real OpenAI"** over the ROADMAP.md plan; `ROADMAP.md`'s Phase 7 section rewritten to point here rather than left contradicting the code. `apps/search/ai_classify.py` is its own standalone module (not bolted onto voice-command classification), with the actual OpenAI call isolated to one mockable function boundary (`call_openai_classify`, same pattern as `apps/common/storage.py`'s boto3 wrapper) — `OPENAI_API_KEY` is a new, deliberately optional setting; empty means the documented AI-unavailable fallback runs (raw keyword match, never a hard failure), which is what happens by default in this dev sandbox (no key configured, same as no AWS credentials for S3). Deterministic, fully-unit-testable pieces built alongside the AI layer: Levenshtein-distance person-name resolution (exact match → ambiguous-widen-to-OR on ties → edit-distance-≤2 fallback for typos the LLM doesn't self-correct), a status/priority alias table with a defense-in-depth allow-list check (an unrecognized AI-returned value is dropped, never reaches the ORM), self-contained today/tomorrow/this_week due-range resolution, and multi-word keyword matching that tolerates punctuation differences within a field (so a corrected "self study report" still matches a stored "self-study" hyphenation). Task search stays tenant+assigner-or-assignee scoped like the task list endpoints but **includes Draft/Cancelled/DoneD by design** (search doesn't hide them); `assigneeLabel` matches stay privacy-scoped to the assignee, never leaking to the assigner. Not audited (GET-only, same reason `BROADCAST_VIEWED`/`DOCUMENT_ACCESSED` stay unused). **Explicitly not built:** the AI contract doc's `closestFuzzyLabel` fuzzy label-name correction, and jargon-glossary grounding (the doc's own §9 already lists the latter as an unconfirmed residual gap upstream, not a settled requirement). 33 new tests, 177 total, all green; `ruff check` clean. Full breakdown in `changelog.md`'s 2026-08-12 entry. Previously: 2026-08-07 (2) — second and final "supporting entity" vertical slice, **Broadcast Notices** (`apps/broadcasts`): full create-draft/publish/list/edit/delete/ack/ack-count/image flow, not a one-shot publish-and-forget slice. Built the upstream-discovered corrections in from day one: `BroadcastNoticeAudienceRoleLevel` join table (mirrors the already-correct `BroadcastNoticeAudienceDept`, migration `0005`, API key `audienceRoleLevels` plural — api-spec.md §10's JSON examples still show the old singular form, `domain-model.md`'s field table is the more recently reconciled source); image access fully backend-streamed (`GET /broadcast-notices/:id/image`, re-checks access every request, sender always allowed / everyone else needs `PUBLISHED`+not-expired+audience-match) rather than a persisted 25h pre-signed URL; edit window widened to DRAFT-or-published-and-not-expired (`400 CANNOT_EDIT_EXPIRED`, correcting api-spec.md's older DRAFT-only text) with only newly-added recipients notified when a published broadcast's audience changes; `GET ?view=sent` excludes DRAFT rows (also a `domain-model.md` correction over api-spec.md's older prose). Notification fan-out is a real Celery task (`apps/broadcasts/tasks.py`), never inline, per guidelines.md's Performance section. `bleach` added as a new dependency for server-side `messageHtml` sanitization (guidelines.md names it explicitly). Audited: all 5 `BROADCAST_*` `AuditAction` values wired (they already existed from Phase 1, unlike Comments' case). 28 new tests, 144 total, all green; `ruff check` clean. Full breakdown in `changelog.md`'s 2026-08-07 (2) entry. **Both supporting-entity slices (Sticky Notes, Broadcast Notices) are now complete** — see `changelog.md`'s 2026-08-07 (1)/(2) entries. Nothing from this session is committed to git yet. Previously: 2026-08-07 (1) — first of the two slices, **Sticky Notes / Reminders** (`apps/sticky_notes`): full `GET`/`POST /sticky-notes`, `GET`/`PATCH`/`DELETE /sticky-notes/:id`, `POST /sticky-notes/:id/promote`, always scoped to `userId = caller` only (no tenant join, matching the model's existing design). Built the two upstream-discovered corrections in from day one rather than as a follow-up: added `StickyNote.color_code` (hex, default `#FEF3C7` — **not** `#6B7280`, that's `ProjectLabel`'s default on an unrelated model, migration `0004`), and a Celery beat periodic task (`apps/sticky_notes/tasks.py:sticky_note_retention_sweep`, first periodic job in this project, `CELERY_BEAT_SCHEDULE` added to `config/settings/base.py`) that hard-deletes notes whose `dueAt` is more than 3 days in the past. `POST /sticky-notes/:id/promote` reuses `TaskService.create_task` directly rather than duplicating its Draft-vs-Open/notification logic; `ALREADY_PROMOTED` resolved as `409` per the standard error-codes table (api-spec.md §9's inline prose says 400, but the table is the more recently reconciled source — same kind of call as the Subtasks slice's notification-target fix). Not audited (no `STICKY_NOTE_*`/`REMINDER_*` `AuditAction` values exist). **Explicitly not built this slice:** `REMINDER_FIRED` notification dispatch (a separate sweep, only the hard-delete retention job was asked for) — flagged so it isn't mistaken for done. 18 new tests, 116 total, all green; `ruff check` clean. Full breakdown in `changelog.md`'s 2026-08-07 (1) entry. Previously: 2026-08-03 (6) — fifth and final Phase 3 vertical slice, **full Label CRUD** (`apps/labels`): added `PATCH`/`DELETE /labels/:id` (creator-only rename/recolor, hex-format `colorCode` validation applied to create too) on top of Phase 2's existing create+list. `DELETE`'s "blocked while applied to a task" rule came essentially for free — `Task.main_label`/`assignee_label` were already `on_delete=PROTECT` from the Phase 1 model port, so Django's own `ProtectedError` just needed catching and translating to `409 LABEL_IN_USE`. Not audited (no `LABEL_*` `AuditAction` values exist, consistent with every other unaudited route here). 10 new tests, 98 total, all green. **Phase 3 is now complete** — Subtasks, Comments, Evidence, Voice Recording, and full Label CRUD are all built and tested; see `changelog.md`'s five 2026-08-03 entries ((2) through (6)) for the full breakdown of each slice. Nothing from this session is committed to git yet. Previously: 2026-08-03 (5) — fourth Phase 3 vertical slice, **Voice Recording** (`apps/tasks`): transcript saved atomically with the task in one DB transaction when `POST /tasks` gets a nested `voiceRecording` object; audio linked via the same presign→confirm S3 pattern as Evidence, but keeping the original pre-signed-playback-URL design (no confirmed upstream migration to streaming for this one, unlike Evidence/Broadcast image/Profile picture). Two real fixes along the way: `confirm_audio` never trusts the client-supplied `s3Key` as the literal copy source (same class of issue as Evidence's path-traversal fix) and retried confirms are now truly idempotent at the service layer rather than relying on `CopyObject`'s (false) natural idempotency. Also closed a real gap — `serialize_voice_recording` was missing `id`/`createdAt`/`carryVoiceRecording` (the last of which didn't even exist as a model field yet; added via migration `0006`). 12 new tests, 88 total, all green. Full breakdown in `changelog.md`'s 2026-08-03 (5) entry. Previously: 2026-08-03 (4) — third Phase 3 vertical slice, **Evidence** (`apps/evidence`): presign→confirm upload flow (`POST /upload/presign/` + `POST /tasks/:id/evidence/`), built to the documented orphan-safe design with pending-upload metadata cached in Redis (keyed by `evidenceId`, 24h TTL matching the S3 lifecycle rule) rather than a DB row created early; file access streamed through the backend from day one (`GET /tasks/:id/evidence/:eid/file/`), not a persisted pre-signed URL; delete narrowed to uploader-only; `.xls` accepted alongside `.xlsx`. First real cloud-infra code in this project — new `apps/common/storage.py` boto3 wrapper, `boto3` dependency added, no AWS credentials in this dev sandbox so all 14 new tests mock the storage layer. Also fixed a path-traversal gap in the presigned S3 key construction (client-supplied filename now run through `os.path.basename()`) — caught while building, not asked for. 76 tests total, all green. Full breakdown in `changelog.md`'s 2026-08-03 (4) entry. Previously: 2026-08-03 (3) — second Phase 3 vertical slice, **Comments** (`apps/comments`, its own app, mounted at the shared `/api/v1/tasks/` prefix): full CRUD, author-only edit/delete, `TASK_COMMENTED` notification (not `COMMENT_ADDED` — that type doesn't exist in the schema, same kind of stale-inline-prose-vs-corrected-table call as the Subtasks entry below), new `COMMENT_CREATED`/`COMMENT_UPDATED`/`COMMENT_DELETED` audit actions with comment text explicitly excluded from tracked fields, and a `serialize_comment` dedup that fixed a real missing-`updatedAt` gap. 10 new tests + 3 audit-trail tests, 62 total, all green. Full breakdown in `changelog.md`'s 2026-08-03 (3) entry. Previously: 2026-08-03 (2) — first Phase 3 vertical slice, **Subtasks** (`apps/tasks`), built against the freshly re-synced docs rather than the pre-sync design: full CRUD + lifecycle (`create/patch/delete/accept/done-a/done-d/cancel`) nested under `/tasks/:taskId/subtasks/`, plus `Task.evidence_required` + a DoneA gate, and two latent bugs fixed that were only reachable once subtasks could exist for the first time — `mark_done_d` no longer archives a subtask (only a main task), and a `CANCELLED` subtask now also unblocks the parent's `done-d` (was only `DONE_D`). Also resolved a real contradiction found in the just-synced `api-spec.md`: `SUBTASK_CREATED` notifies the **parent's original assigner** (per §11's notification-types table, the more recently reconciled source), not the new sub-assignee as §3's inline prose said. 12 new tests, 49 total, all green. Full breakdown in `changelog.md`'s 2026-08-03 (2) entry. Previously: 2026-08-03 — re-synced `docs/` from the original repo after the user pulled a large batch of upstream changes (`Bolo` monorepo docs, `bolo-backend` `develop` 491ef8b→518ab79, `bolo-web` `develop`). **Important finding: the original repo's own changelog.md stopped being updated on 2026-07-24 while its code kept moving through 2026-08-03** — several features below (Jargon Words, Global Search's final split-endpoint shape, member reactivation, evidence-required, comment audit actions, sticky retention sweep) exist only in upstream code, not in its changelog; verified directly against `bolo-backend` source, not doc prose. Docs-only sync, no Django code touched yet. Updated: `api/api-spec.md` §13 and `api/global-search-ai-contract.md` fully rewritten (Search moved to two paginated endpoints, `/search/tasks`/`/search/stickies`, superseding even the 2026-07-23 revision — upstream's own docs never caught up to this); `reference/schema.prisma.reference` gained `JargonWord` model, `BroadcastNoticeAudienceRoleLevel` join table (replacing the old single-FK `audienceRoleLevel`), `Task.evidenceRequired`, `StickyNote.colorCode`, and `AuditAction.MEMBER_REACTIVATED`/`COMMENT_CREATED`/`COMMENT_UPDATED`/`COMMENT_DELETED`; `architecture/domain-model.md` and this file's Business Rules corrected for the cancelled-subtask-counts-toward-parent-DoneD fix, evidence/broadcast-image/profile-picture pre-signed-URL→backend-streamed pattern, and the narrowed evidence-delete-to-uploader-only rule; `ops/staging-setup.md` added (new upstream doc); `reference/BOLO-API.postman_collection.json` refreshed. `docs/ops/security.md` again deliberately left untouched (own access+refresh-token deviation, unaffected by this sync). None of these upstream features are implemented in Django code yet — this pass is docs/contract only; a follow-up pass will plan and build them (Global Search, Jargon Words, Broadcast updates, Member Reactivation, Profile Picture streaming, Sticky Note color+sweep — see `changelog.md` for the full punch list). Previously: 2026-07-23 — `feature/roadmap-hardening` closed all five items ROADMAP.md's own Phase 2/3 checklists called for that were deliberately deferred on 2026-07-19 (not oversights): Redis-backed OTP-request throttle (`ScopedRateThrottle`, `CACHES` on Redis), `HasOrgRole`/`IsTenantMember` real permission classes (wired into a real endpoint, `GET /tenant`), `Task` indexing (composite `(tenant_id, status)`, `assignee_id`, `due_date`, partial `is_archived=False`), a `django_assert_num_queries` regression test locking in the task-list endpoint's existing query-count (turned out there was no N+1 to fix — `select_related`+`annotate(Count(...))` already covered it), and generic audit logging (Architecture Rules point 8: `apps/common/audit_middleware.py` + `apps/common/audit_route_config.py`, Celery+Redis stood up for the fire-and-forget write). Full breakdown, including a `redis`-vs-`kombu` RESP2/RESP3 compatibility snag worth knowing about, in `changelog.md`'s 2026-07-23 (2)/(3) entries. Before that: 2026-07-22 — re-synced `docs/` again from the original repo (docs-only, no code touched): `ops/deployment.md`'s rollback narrative moved to new `ops/staging-runbook.md`, new `api/global-search-ai-contract.md` added (draft, Phase 7-relevant), broadcast image confirm now needs an explicit `s3Key` in the request body. Multi-department broadcast audience scope and `GET /tenant/roles` are present in both this project's docs and upstream `main` — an initial pass of this sync incorrectly reported them as reverted/missing (stale read, corrected same day, see `changelog.md`). `docs/ops/security.md` was deliberately left untouched (still carries this project's own access+refresh-token deviation). Before that: 2026-07-19 — Phase 2 complete: `common` app foundation (response envelope, exception handler, pagination, permissions), OTP→JWT auth (`apps/auth`), and a core Task lifecycle vertical slice (`apps/tasks` + minimal `apps/labels`), see `changelog.md` for the full breakdown. **Deliberate deviation from `docs/ops/security.md`'s locked W1 decision:** the user asked for real access+refresh token handling beyond the original's single long-lived cookie — implemented as a 15-min JWT access token + rotating opaque refresh token with reuse-detection; `docs/ops/security.md`'s Authentication section was rewritten to match, so it no longer contradicts the code. Subtasks, comments, evidence, voice recording, and full label CRUD are still Phase 3. Before that: 2026-07-18 — re-synced `docs/` from the original repo and reworked Phase 1 models to match the drift found (label model redesign, new `platform_admin` app, `User`/`NudgeSkipCounter` field changes, new enum values); Phase 1 (domain models) complete before that.

---

## What Is This App?

**BOLO** (internal/legacy name: Fatafat) is a lightweight, web-based task & delegation app for Indian teams. Full product context, entities, and business rules are in `docs/` (copied from the original repo — see `docs/README.md` for what's here and why).

- **NOT** a project management tool — no Gantt, no resource planning, no time tracking
- Task is the hero — create one in seconds with just **title + assignee**
- Two verticals: **Education** (Dean/HoD/Faculty) and **CA/CS / Industry** (Director/HoD/Employees)
- India-first: multilingual, voice-first task creation (voice transcription happens client-side in `bolo-web`; this backend only stores/serves what it's given)
- All notifications are **in-app only**, except reminder/due-date types (`TASK_REMINDER`, `TASK_DUE_TODAY`, `TASK_DUE_TOMORROW`, `TASK_OVERDUE`), which also send **email**.

**Client:** AIBIGO Institute Pvt Ltd.

---

## Relationship to the Original Repo

| | Original (`Bolo/`) | This project (`bolo-django/bolo-backend-django/`) |
|---|---|---|
| Backend | `bolo-backend` — Node + Express + Prisma | Django + DRF (this repo) |
| Frontend | `bolo-web` — React + Vite | none — pure API, consumed by `bolo-web` over HTTP |
| Database | Shared Postgres instance (Prisma-owned migrations) | **Its own fresh Postgres database** — Django owns migrations from scratch, schema mirrors `docs/reference/schema.prisma.reference` table-for-table (same table/column names, so the wire contract stays identical) |
| Docs | `docs/` (git-ignored, local source of truth) | `docs/` copied in at scaffold time — treat as the binding contract for API shape and business rules; **not** a place to invent new rules |

**Do not assume this project reads or writes to the original repo's database.** They are two fully independent deployments of the same product spec. If you need current business-rule context beyond what's in this repo's `docs/`, the original repo lives at `/home/test/Desktop/Python_Project/BOLO/Bolo` (its Node backend at `.../BOLO/Bolo/bolo-backend`) — read its `CLAUDE.md`/`docs/` for extra background, but this repo's copies are what govern implementation here. **Note (2026-07-18):** the sibling repo is reachable again at the path above (moved since the 2026-07-14 Windows→Linux migration, when it was not present) — `docs/` was re-synced from it on this date; re-check for drift periodically rather than assuming this repo's copy stays current on its own.

---

## Task Protocol — Every Session, Every Task

### Before starting any task
State in 2–3 sentences: what the task is, what you're going to do, and what the expected outcome is, before the first tool call.

### After completing any task
State in 1–2 sentences: what was done and what files changed.

---

## Mandatory Doc Lookup — Before Any Implementation

| Task type | Must read first |
|---|---|
| Any feature | `docs/product/prd.md` → `docs/architecture/domain-model.md` |
| Any code (always) | + `guidelines.md` (repo root) — naming, DB rules, response shapes, app/folder structure |
| Endpoint / serializer work | + `docs/api/api-spec.md` (exact request/response shape — do not deviate) |
| Model / migration | + `docs/architecture/domain-model.md` + `docs/reference/schema.prisma.reference` (port field-for-field) |
| Auth / security | + `docs/ops/security.md` |
| Notifications | + `docs/api/api-spec.md` §11 (notification-types table) |
| Deployment / infra | + `docs/ops/deployment.md` (reference only — this project's actual pipeline will differ) |
| Testing | + `docs/engineering/testing-strategy.md` |
| Git / branching / PRs | + `docs/engineering/git-workflow.md` |

**Never assume** — if a field, rule, or constraint seems wrong or missing, check `docs/product/open-questions-web-v1.md` first.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | Django + Django REST Framework | REST API only, no server-rendered templates |
| Database | PostgreSQL | Own fresh instance/DB — not shared with the original `bolo-backend` |
| ORM / migrations | Django ORM + Django migrations | Models mirror `schema.prisma.reference` field-for-field |
| Auth | Email OTP → JWT | Custom `CookieJWTAuthentication` (DRF's `SimpleJWT` defaults to header auth — this app needs httpOnly cookie, matching the original contract). No passwords stored. |
| Async / background jobs | Celery + Redis | Notification dispatch, broadcast fan-out, reminder/due-date cron, daily analytics pre-compute |
| API docs | drf-spectacular | OpenAPI schema generated from code — keep in sync with `docs/api/api-spec.md`, don't let them drift |
| Object storage | S3-compatible via `boto3` | Evidence files via pre-signed URLs, same as original |
| Transactional email | AWS SES via `boto3` | Reminder/due-date types only (see Business Rules). Matches the original's 2026-07-18 decision (was SMTP/nodemailer) — IAM-role-only via the default credential provider chain, same pattern as S3, no separate SMTP secret to manage |
| Env config | `django-environ` | `.env` per environment, validated at startup — crash early if a required var is missing |
| Testing | `pytest-django` + `factory_boy` | Real Postgres test DB, no mocking the database |
| Serialization | DRF serializers | One serializer per direction where request/response shapes differ (see api-spec.md) |

---

## Architecture Rules (NEVER break)

This project keeps the **same strict layering discipline** as the original Node backend, even though it's not Django's default idiom ("fat models" / views calling the ORM directly). This is a deliberate choice for consistency and testability — don't relax it because "Django doesn't normally do this."

### Controller → Service → Repository (STRICT — same as original)

1. **View** (`views.py` / DRF `APIView` or `ViewSet`): HTTP only — parse the request, call the service, return the response via the shared envelope helper. No business logic. No ORM calls.
2. **Service** (`services.py` or `services/`): business logic only. No `request`/`response` objects. No direct Django ORM calls — calls the repository. **Services never call an audit-log function directly** — see the Audit Logging rule below (point 8), which is the opposite pattern from Notifications (point 7).
3. **Repository** (`repositories.py` or `repositories/`): the only place `Model.objects....` / QuerySets are touched. No business logic — just queries, always filtered by `tenant_id` where applicable.
4. Always return via the shared response helper — never a raw DRF `Response({...})` built ad hoc in a view.
5. Permission classes (DRF `permissions.py`) on every view — no exceptions. Tenant scope is the universal guard; org-role checks use a custom `HasOrgRole` permission; task-level (assigner/assignee) checks live in the service layer.
6. `tenant_id` always comes from the decoded JWT (via the custom authentication class, exposed as `request.tenant_id`) — **never** from the request body or query params.
7. **Every service that changes task, subtask, or broadcast state — check `docs/api/api-spec.md` §11 for whether a `Notification` should fire.** Wire it through a `dispatch_notification()` service call — never a raw `NotificationRepository.create()` and never inline email logic. If the event type isn't in the table yet, add it there before wiring the call site.
8. **Audit logging is generic, not dispatched.** Matches the original's 2026-07-14 redesign (W98/W99) — deliberately the *opposite* pattern from point 7's Notifications. A DRF middleware (`apps/common/audit_middleware.py`, planned) paired with a static route-config table (`apps/common/audit_route_config.py`, planned — one row per `{method, resolver_match.view_name}` → `{entity_type, model, action | resolve_action(before, after)}`) observes every mutating request generically: reads before-state via the configured model before the view runs, captures after-state from the response body, and writes the `AuditLog` row only if the response succeeded (`status_code < 400`) — queued as a Celery task so the write never blocks the response (Django has no direct equivalent of Express's post-response hook; a fire-and-forget Celery task is the idiomatic substitute). **No service or view ever calls an audit-log function directly** — a new mutating route gets audited by adding one row to the config table, not by editing the handler. **The one documented exception:** login/logout has no entity mutation for the middleware to observe, so `User.last_login_at`/`last_logout_at` are written directly by the auth service for their own legitimate session-tracking purpose, and the middleware picks up `USER_LOGIN`/`USER_LOGOUT` off of *that* write the same generic way as everything else.

Response helpers (always — never a raw `Response({...})`):
```python
return success_response(data, "Task created")               # 200
return success_response(data, "Created", status=201)         # 201
return failure_response("Not found", status=404, code="TASK_NOT_FOUND")  # 4xx
```

---

## Business Rules (encode these exactly — ported from the Web PRD v1.1, unchanged)

### Task Rules
- Task needs only **title + assignee** to create (saves as Draft). **Due date is required to transition Draft → Open.**
- **Assigner (Delegator)** can: edit assignee, due date, priority, main label, description; comment; attach evidence; send reminder; mark complete (DoneD); cancel; delete; reassign. **Cannot** create subtasks. **Cannot** edit title.
- **Assignee** can: write progress comments, attach evidence, mark complete (DoneA), create subtasks, set their own private label.
- **Label model (redesigned — no separate personal-label table):** a single `ProjectLabel` pool per creator, referenced by two FKs on `Task` — `main_label` (assigner sets, visible to everyone who can see the task) and `assignee_label` (assignee sets, private, never returned to non-assignees, cleared on reassignment). Each user sees only labels they created (`created_by = request.user`). Deleting a label in use is blocked (`on_delete=PROTECT`).
- **Two-step completion:** assignee marks **DoneA** → assigner marks **DoneD** (archives the task). A main task reaches DoneD only when all subtasks are `DONE_D` **or `CANCELLED`** (corrected 2026-08-03 sync — a cancelled subtask can never itself reach `DONE_D` and would otherwise block the parent forever; upstream `TaskRepository.allSubtasksDoneD` uses `notIn: ['DONE_D','CANCELLED']`).
- Task **cannot be reassigned** once any subtask exists.
- Every task/subtask must be **accepted by the assignee** before work starts. **There is no rejection state.**
- **Title is immutable** after creation — reject any PATCH on title at the serializer/service level.
- Cancelling a parent cascades to all non-`DONE_D` subtasks. A task cannot be cancelled once `DONE_D`.
- Defaults: priority → P3, main label → none, description → empty.
- **`evidence_required`** (assigner-editable, default `false`, added upstream 2026-07-30): when set, blocks the assignee's DoneA transition until at least one `Evidence` row exists (`EVIDENCE_REQUIRED` error otherwise). Not yet built here — Evidence is Phase 3.
- An `OVERDUE` task auto-transitions back to `OPEN`/`IN_PROGRESS` if its due date is edited to today-or-later.

### Role Rules
- Tenant roles (`TOP/MID/EXECUTOR`) set at onboarding per vertical. Task roles (Delegator/Assignee) are per task, derived from `assigner_id`/`assignee_id` — never stored as separate fields.
- Always scope queries by `tenant_id` — never return unscoped data. `tenant_id` from the JWT only, never the body.
- Any user can assign to any other user — no hierarchy restriction enforced (W19 — pending confirmation before enforcing).

### Personal Items (Sticky Notes / Reminders)
- Always private — never shared, never visible to others.
- A `StickyNote` with `due_at` set **is** the reminder — no separate entity.
- `color_code` (hex, default `#FEF3C7` per upstream — **not** `#6B7280`, that default belongs to `ProjectLabel`). A retention job hard-deletes sticky notes once `due_at` is more than 3 days in the past (Celery beat periodic task is the natural port of upstream's interval-based job).

### Broadcast Notice
- `can_broadcast` flag on `TenantMembership` gates who can post — binary permission, not derived from role level.
- Audience scope (`audience_dept_ids` **and** `audience_role_levels` — both many-to-many via join tables as of the 2026-07-30 upstream redesign, not single nullable FKs) is **mandatory at publish** (empty on both = reject).
- Visible for **exactly 1 day** from publish — not configurable.
- **~200 character limit** on visible text; stored as `message_json` (rich text AST) + `message_html` (sanitized).
- **Single image** attachment only. Serve it via a backend-streamed endpoint that re-checks audience membership on every request, not a pre-signed S3 URL persisted in the DB — a signed URL is a bearer credential once handed to a client, so baking access control into a long-lived one defeats the audience/expiry rules it's supposed to respect. The same "stream through the backend, re-check access per request" pattern applies to Evidence and profile pictures.
- Acknowledge increments read count; sender sees COUNT only — no per-person breakdown.
- Edit (sender-only, blocked once expired) and delete (sender-only) are expected alongside create/publish — not just a one-shot publish-and-forget flow.

---

## Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Django apps | snake_case, plural, one per domain area | `tasks`, `broadcasts`, `sticky_notes` |
| Models | PascalCase | `Task`, `BroadcastNotice` |
| Model fields | snake_case | `tenant_id`, `due_at`, `assignee_id` |
| DB tables | snake_case, plural (`Meta.db_table`) | `tasks`, `broadcast_notices` |
| Views/ViewSets | PascalCase + `View`/`ViewSet` | `TaskDetailView`, `TaskViewSet` |
| Services | snake_case module, PascalCase class | `services.py` → `TaskService` |
| Repositories | snake_case module, PascalCase class | `repositories.py` → `TaskRepository` |
| Serializers | PascalCase + `Serializer` | `TaskCreateSerializer`, `TaskResponseSerializer` |
| URLs | kebab-case, plural, versioned | `/api/v1/broadcast-notices/` |
| Files | snake_case | `task_service.py`, `task_repository.py` |
| Env variables | SCREAMING_SNAKE_CASE | `DATABASE_URL` |

---

## Proposed Project Structure

```
bolo-backend-django/
├── manage.py
├── requirements/               # base.txt, dev.txt, prod.txt
├── config/                     # Django project package
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── prod.py
│   │   └── test.py
│   ├── urls.py                 # mounts each app's urls.py under /api/v1/
│   ├── celery.py
│   ├── wsgi.py / asgi.py
│   └── exception_handler.py    # DRF custom exception handler -> failure_response shape
├── apps/
│   ├── common/                 # response helpers, base permissions, pagination, error classes, audit middleware + route-config table
│   ├── platform_admin/         # PlatformAdmin, PlatformAdminOtpCode (cross-tenant superadmin, outside RLS/tenant scoping)
│   ├── tenants/                # Tenant, Department, TenantMembership
│   ├── users/                  # User (incl. last_login_at/last_logout_at/profile_pic_url)
│   ├── auth/                   # OtpCode, JWT issuance/verification, CookieJWTAuthentication
│   ├── tasks/                  # Task (dual-FK main_label/assignee_label), VoiceRecording
│   ├── labels/                 # ProjectLabel (single pool, dual-purpose via Task's FKs)
│   ├── evidence/                # Evidence (S3 pre-signed)
│   ├── comments/                # Comment
│   ├── sticky_notes/             # StickyNote
│   ├── broadcasts/              # BroadcastNotice, BroadcastAcknowledgement
│   ├── notifications/           # Notification, dispatch_notification service, NudgeSkipCounter
│   ├── audit/                    # AuditLog (written only by the generic middleware, see Architecture Rules point 8)
│   └── search/                    # No models -- read-only query layer over Task/StickyNote; ai_classify.py isolates the OpenAI call
│       # each app:
│       #   models.py
│       #   serializers.py
│       #   views.py            (or viewsets.py)  <- controller layer, thin
│       #   services.py         <- business logic
│       #   repositories.py     <- the only place ORM is used
│       #   permissions.py
│       #   urls.py
│       #   tests/
└── docs/                       # copied contract — see docs/README.md
```

---

## Environment Variables (planned)

```bash
DATABASE_URL=postgresql://...          # own DB, not shared with the Node bolo-backend
JWT_SECRET=...
DJANGO_SECRET_KEY=...
REDIS_URL=redis://...                  # Celery broker
S3_BUCKET_NAME=...
SES_FROM_EMAIL=...                     # reminder/due-date emails via AWS SES (boto3, IAM-role-only — no SMTP_* vars)
OPENAI_API_KEY=...                     # Global Search query classification -- optional, empty = documented AI-unavailable fallback
```

---

## Current Build Status

- [x] `bolo-backend-django/` folder scaffolded
- [x] `docs/` copied in from the original repo (backend-relevant subset — see `docs/README.md`)
- [x] `CLAUDE.md`, `guidelines.md`, `README.md`, `changelog.md` written
- [x] `django-admin startproject` / app scaffolding (`config/` restructured, empty `apps/` package created)
- [x] `requirements` files + virtualenv (Python 3.12.0)
- [x] Django settings (base/dev/prod/test) + env validation (`django-environ`, fresh local `bolo_django` Postgres DB)
- [x] Models ported from `docs/reference/schema.prisma.reference`
- [x] Initial migration against a fresh local Postgres DB
- [x] Custom `CookieJWTAuthentication` + OTP flow (plus access+refresh token rotation — a deliberate deviation from `docs/ops/security.md`'s original W1 decision, see `docs/ops/security.md` and `changelog.md` 2026-07-19)
- [x] `common` app: response helpers, exception handler, base permissions (`IsTenantMember`, `HasOrgRole` — real, wired into `GET /tenant`), pagination
- [x] First vertical slice (Auth → Tasks) end-to-end against `docs/api/api-spec.md` — core lifecycle only (create/list/detail/edit/delete/accept/done-a/done-d/cancel/remind + minimal labels); subtasks, comments, evidence, voice recording, and full label CRUD were Phase 3 — see the five Phase 3 slices below, all now complete
- [x] Redis-backed OTP-request throttle, `Task` indexing (composite + partial), a query-count regression test on the task-list endpoint, and generic audit logging (Celery + Redis, `apps/common/audit_middleware.py` — Task lifecycle routes + `USER_LOGIN`/`USER_LOGOUT`) — `feature/roadmap-hardening`, see `changelog.md` 2026-07-23
- [x] Phase 3, slice 1: **Subtasks** (`apps/tasks`) — full CRUD + lifecycle, `Task.evidence_required` + DoneA gate, audited — see `changelog.md` 2026-08-03 (2)
- [x] Phase 3, slice 2: **Comments** (`apps/comments`) — full CRUD, author-only edit/delete, audited (text excluded) — see `changelog.md` 2026-08-03 (3)
- [x] Phase 3, slice 3: **Evidence** (`apps/evidence`) — presign/confirm upload, backend-streamed file access, uploader-only delete, audited — see `changelog.md` 2026-08-03 (4)
- [x] Phase 3, slice 4: **Voice Recording** (`apps/tasks`) — transcript atomic with task creation, presign/confirm audio (pre-signed playback URL, not streamed), idempotent confirm — see `changelog.md` 2026-08-03 (5)
- [x] Phase 3, slice 5: **full Label CRUD** (`apps/labels`) — creator-only rename/recolor, delete blocked while applied to a task (`LABEL_IN_USE`) — see `changelog.md` 2026-08-03 (6). **Phase 3 complete.**
- [x] Supporting-entity slice 1: **Sticky Notes / Reminders** (`apps/sticky_notes`) — full CRUD + promote-to-task, `color_code`, Celery beat retention sweep — see `changelog.md` 2026-08-07 (1)
- [x] Supporting-entity slice 2: **Broadcast Notices** (`apps/broadcasts`) — full create/publish/list/edit/delete/ack flow, `BroadcastNoticeAudienceRoleLevel` join table, backend-streamed image, Celery fan-out, audited — see `changelog.md` 2026-08-07 (2). **Both supporting-entity slices complete.**
- [x] **Global Search** (`apps/search`) — `GET /search/tasks` + `GET /search/stickies`, OpenAI-backed query classification (`ai_classify.py`) with deterministic Levenshtein/normalization/fallback layers, per `docs/api/api-spec.md` §13 — built over `ROADMAP.md`'s superseded Postgres-FTS Phase 7 plan (user's explicit choice) — see `changelog.md` 2026-08-12
- [x] **Due-date reminder sweep** (`apps/tasks/tasks.py`, `apps/sticky_notes/tasks.py`) — `TASK_DUE_TODAY`/`TASK_DUE_TOMORROW`/`TASK_OVERDUE` (+ real `OVERDUE` status transition, both directions) and `StickyNote.REMINDER_FIRED`, both one-shot via persisted DB guards, `autoretry_for=(SMTPException,)`. See `changelog.md` 2026-08-12 (2)
- [x] **AI Nudges** (`apps/notifications`) — `GET /nudges`, `POST /nudges/:id/skip`, `POST /nudges/skip-all` + the recurring `AI_NUDGE_FOLLOWUP` (6h)/`AI_NUDGE_DUE_PROXIMITY` (3h) Celery beat sweeps, skip-cap + one-time assigner escalation on Due-Proximity. **ROADMAP.md Phase 8 is now complete.** Not built: the "first-login-of-the-day fast-track" interval-gate bypass (doesn't map onto this project's fixed-crontab sweep shape). See `changelog.md` 2026-08-16

---

## Git Conventions

- Branches: `feature/`, `fix/`, `chore/`
- Commits: `feat:`, `fix:`, `chore:`, `refactor:`
- Never commit directly to `main`
- Log every significant change in this project's own `changelog.md` (tags `[BE]` `[STD]` `[INFRA]` — no `[FE]`/`[PRD]` here, this is backend-only)
