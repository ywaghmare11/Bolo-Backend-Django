# BOLO — Global Search: AI ↔ Search Contract

> **Status:** Draft — for review by the dev who built the `/classify` voice-AI flow. Not yet synced into `api-spec.md` §13 (which still documents the old, stale OpenSearch-based design) — will be folded in once this contract is confirmed workable.
> **Created:** 2026-07-20
> **Owners:** AI/classify flow — [voice-flow dev]. Search execution (Postgres + API) — backend.

---

## 1. What this is

Global search lets a user type (3+ characters) or speak a query and get back matching **Tasks/Subtasks** and **Sticky Notes** — nothing else. This doc defines the handoff contract between:

- **The AI layer** (owned by the dev who built `/classify`) — takes the raw query, returns a clean structured object. No hallucinated names/labels — grounded against the real tenant roster, same pattern already used for voice commands.
- **The search execution layer** (Postgres query + API response) — consumes that structured object with zero further interpretation and returns results in exactly two buckets.

**This is a design proposal, not yet a locked decision.** It needs sign-off from the AI-flow dev that molding `/classify` this way is workable before it gets written into `docs/api/api-spec.md` as the authoritative spec.

---

## 2. Why reuse `/classify` instead of building a new AI layer

The existing voice-command flow already does most of what search needs:

| File | What it already provides |
|---|---|
| `bolo-backend/src/voice/intent.js` | `buildJargonGlossary(users)` — per-tenant jargon + name glossary, built from the real user roster, refreshed every 5 min. `resolveAssigneeCandidates(name, users)` — scores a spoken/typed name against real tenant users; ties are surfaced as candidates, **never silently guessed**. `filter_tasks` intent already extracts `assignee`, `keyword`, `status`, `priority`, `due` from free text. |
| `bolo-backend/src/controllers/voice/classify.controller.ts` | `getCachedUsers(tenantId)` — 60s-TTL cached tenant roster, fed into every classify call. `taskRepo.searchByKeyword(tenantId, userId, spoken)` — keyword search on Task **already exists**, built for voice command resolution. `resolveStickyReference` — keyword search on sticky text already exists too, currently only used to disambiguate a spoken reference for update/delete/promote. |
| `bolo-backend/src/routes/voice.routes.ts` | `POST /api/voice/classify` — the live endpoint, `requireAuth` gated. |

**Gaps to close for search specifically** (see §8):
- Sticky search today only disambiguates a *known* reference — it isn't exposed as a first-class free-text search.
- No single intent returns both Task and Sticky matches together — `filter_tasks` and `filter_reminders` are separate today.
- Response shape is action-oriented (`OPEN_FORM` / `EXECUTE_DIRECT` / `APPLY_FILTERS`) — search needs a results-oriented shape instead (see §6).

---

## 3. Scope

**In scope (the only two result types, ever):**
- Task (including Subtask — a Subtask is a `Task` row with `parentTaskId` set, same schema, same query)
- Sticky Note

**Explicitly out of scope:** Users, Departments, Labels, Broadcasts as standalone result types. A person's name (e.g. "Yash") is a **match field**, not a result type — searching "Yash" surfaces Tasks where Yash is assigner or assignee, never a "User" card.

---

## 4. Trigger rules

- Minimum **3 characters** before any search call fires.
- **Typed input:** debounce ~250–300ms after the user pauses typing. **Never fire per keystroke** — the AI call is not cheap or instant enough for that.
- **Voice input:** fires once on the finalized transcript from the Voice AI SDK (per the existing voice contract — SDK owns transcription, we only receive final text).

---

## 5. Input contract (client/API → AI layer)

```json
{
  "query": "MBA",
  "source": "typed"
}
```

| Field | Type | Notes |
|---|---|---|
| `query` | string | Raw text, already past the 3-char + debounce gate. Required. |
| `source` | `"typed"` \| `"voice"` | Lets the AI apply the STT-correction glossary (§7 of `intent.js`) only when relevant. |

`tenantId` and `userId` are **never sent by the client** — injected server-side from the JWT before this reaches the AI layer, same rule as every other endpoint in `api-spec.md`. The AI layer receives the tenant's user roster the same way `classify.controller.ts` already does via `getCachedUsers(tenantId)`.

---

## 6. Output contract (AI layer → search execution layer)

This is the exact object the AI layer must return. No other shape, no extra required interpretation on the search side.

```json
{
  "resolvedKeywords": ["MBA"],
  "resolvedAssignee": {
    "id": "uuid-or-null",
    "name": "Yash Patil",
    "ambiguous": false,
    "candidates": null
  },
  "entityScope": "both",
  "filters": {
    "status": null,
    "priority": null,
    "due": null
  },
  "detectedLanguage": "en",
  "confidence": 0.9
}
```

| Field | Type | Semantics |
|---|---|---|
| `resolvedKeywords` | `string[]` | Cleaned/typo-corrected/STT-corrected search terms, filler words stripped. Always at least `[query]` as a fallback. |
| `resolvedAssignee` | object \| `null` | `null` if no person name detected. Otherwise resolved **only against that tenant's real user list** — same `resolveAssigneeCandidates` logic already in `intent.js`. Never invents a person. |
| `resolvedAssignee.ambiguous` | boolean | `true` if 2+ tenant users tied on the name match. |
| `resolvedAssignee.candidates` | array \| `null` | Populated only when `ambiguous: true` — `{id, name}` pairs for a disambiguation chip. |
| `entityScope` | `"task"` \| `"sticky"` \| `"both"` | Defaults to `"both"`. Only narrows if the query explicitly names a scope (e.g. "my reminders about X" → `"sticky"`). |
| `filters.status` | enum \| `null` | One of `open\|in_progress\|overdue\|done_a\|done_d\|cancelled`, only if clearly implied. |
| `filters.priority` | enum \| `null` | `P1\|P2\|P3\|P4`. |
| `filters.due` | enum \| `null` | `today\|tomorrow\|this_week`. |
| `detectedLanguage` | enum | `en\|hi\|mr\|gu\|mixed` — matches the languages `intent.js` already supports. **Note:** `tech-playbook/decisions/database.md` recorded Tamil as a 4th language; the actual glossary supports Gujarati instead. Flagging for reconciliation, not blocking this contract. |
| `confidence` | number 0–1 | **Informational only.** Search always runs best-effort regardless of confidence — unlike an action-executing intent, a search with no results is harmless and visible, so there's nothing to gate on a threshold. |

**Hard invariant:** `resolvedAssignee` must never be a name that doesn't exist in that tenant's roster. If the AI is unsure, it returns `ambiguous: true` with candidates — it does not guess.

**Failure fallback:** if the AI call errors or times out, the search layer proceeds with `resolvedKeywords: [query]`, `resolvedAssignee: null`, `entityScope: "both"`, all filters `null` — same principle as `deterministicFallback()` in `intent.js`. Search must never hard-fail just because the AI call failed.

---

## 7. Search criteria — what actually gets matched, per output bucket

### Task/Subtask bucket

Scope: `tenantId = JWT` **AND** (`assignerId = userId` OR `assigneeId = userId`) — same visibility rule as the existing task list endpoints, not all-tenant.

Matched on ANY of:
- `title ILIKE %keyword%`
- `description ILIKE %keyword%`
- `assignee.name = resolvedAssignee.name` OR `assigner.name = resolvedAssignee.name` (only if `resolvedAssignee` is non-null)
- `mainLabel.name ILIKE %keyword%`

Then narrowed further by `AND status = filters.status` / `AND priority = filters.priority` / due-window check — only applied when that filter is non-null.

Subtasks need no special query — they're `Task` rows with `parentTaskId` set, same WHERE clause covers both.

> **Open question for the AI-flow dev + product:** a Subtask result — does it open its own detail view, or the parent Task Detail with the subtask highlighted? Nothing in `docs/product/prd.md` or `api-spec.md` defines a standalone subtask route today. Needs an answer before the navigation contract (§9) is final.

### Sticky bucket

Scope: `userId = calling user` only — strictly private, no `tenantId` join needed (matches existing Sticky Note privacy rule).

Matched on:
- `text ILIKE %keyword%`

`filters.status`/`filters.priority` don't apply (stickies don't have those fields). `filters.due` could optionally match against `dueAt` if present — worth confirming whether that's wanted for V1 or deferred.

Each bucket capped at a fixed limit (e.g. top 10 — same pattern as the original per-category cap idea).

---

## 8. API response shape (search execution layer → frontend)

```json
{
  "success": true,
  "message": "OK",
  "data": {
    "query": "MBA",
    "entityScope": "both",
    "results": {
      "tasks": [
        {
          "id": "uuid",
          "title": "Prepare MBA accreditation report",
          "status": "IN_PROGRESS",
          "priority": "P2",
          "dueDate": "2026-07-30T17:00:00Z",
          "parentTaskId": null,
          "assigneeName": "Yash Patil",
          "assignerName": "Dr. Kamal Sethi"
        }
      ],
      "stickies": [
        { "id": "uuid", "text": "Check MBA intake numbers", "dueAt": null, "isPinned": false }
      ]
    },
    "totals": { "tasks": 1, "stickies": 1 }
  }
}
```

Always via `successResponse()` — never raw `res.json()` (see §10 note on existing debt).

---

## 9. Navigation on result click

Reuses existing `WORKSPACE.*` constants — no new navigation mechanism:

| Result type | Action |
|---|---|
| Task/Subtask | `setWorkspace(WORKSPACE.TASK_DETAIL, { taskId })` — shown in the main workspace, not a popup |
| Sticky | `setWorkspace(WORKSPACE.STICKY_WALL, { highlightNoteId })` — navigates to the Sticky Wall with that note highlighted |

---

## 10. Known existing debt in `classify.controller.ts` (flagging, not fixing here)

Since this contract extends that file's pattern, worth knowing before building on top of it:
- Controller calls `prisma` directly for label/sticky lookups (lines ~64, ~104, ~151) — bypasses the Repository layer `CLAUDE.md` requires.
- Success responses use raw `res.json()` (line ~214) instead of `successResponse()`.

Not blocking for this feature, but if the AI-flow dev is extending this same file, decide together whether to fix these in passing or leave as tracked debt.

---

## 11. Corner cases

| Case | Handling |
|---|---|
| Proper noun / name typo | Solved by `resolveAssigneeCandidates` grounding against the real roster |
| Two tenant users share a name | Surfaced via `ambiguous: true` + `candidates`, never guessed |
| CS/MCA jargon ("MGT-7", "DIN") | Already covered by the existing glossary in `intent.js` |
| Education-vertical jargon | **Not yet covered** — glossary is currently CS/MCA-only; needs an equivalent for Dean/HoD/Faculty terms if this ships for both verticals |
| AI call fails/times out | Deterministic fallback — raw keyword search still runs, never a hard failure |
| Query matches both a task and a sticky | Both buckets populated, both shown |
| Very common keyword (e.g. "task") | No special handling — normal ILIKE match, capped by per-bucket limit |

---

## 12. Test cases

**Can handle:**
- Typo'd/STT-garbled names via the correction glossary
- CS/MCA jargon search
- Person-name search surfacing tasks where that person is assigner or assignee
- Query matching both buckets simultaneously

**Cannot handle yet / needs more work:**
- Education-vertical jargon (no glossary built)
- Subtask-specific navigation target (open question, §7)
- Guaranteed data-residency compliance for AI calls (queries go to OpenAI, outside India — same caveat as the existing voice flow, not new to this feature)
- Fully deterministic regression testing (LLM-based classification, not pure logic)

---

## 13. Questions for the AI-flow dev before this is locked

1. Is molding `/classify` (or a sibling endpoint sharing its glossary/resolution helpers) workable for this, or does search need a fully separate code path?
2. Subtask navigation — own detail view or parent Task Detail highlighted?
3. Is `entityScope` narrowing (query implying "just stickies") in scope for V1, or should V1 always search both and skip that inference?
4. Fixed per-bucket result cap — same number for both, or different?
