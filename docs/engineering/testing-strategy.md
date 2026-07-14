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
