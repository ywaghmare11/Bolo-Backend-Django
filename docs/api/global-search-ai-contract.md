# BOLO — Global Search: AI ↔ Search Contract

> **Status:** Locked and implemented — this is no longer the draft proposal it was on 2026-07-20. Rewritten 2026-08-03 to match the actual shipped design, verified directly against `bolo-backend`'s current source (the upstream doc files themselves — this file's previous revision included — describe an earlier, superseded design; see the note at the top of `docs/api/api-spec.md` §13). **One material change from the original proposal below (§2):** the AI layer was built as its own standalone module, `bolo-backend/src/search/searchClassify.ts`, rather than reusing/extending `/classify` (`voice/intent.js`) as originally proposed — kept deliberately independent so nothing in search can regress the voice-command flow, and vice versa.
> **Owners:** Search (AI classify + Postgres execution + API) — backend, single owner, not split across two flows as originally planned.

---

## 1. What this is

Global search lets a user type (3+ characters) or speak a query and get back matching **Tasks/Subtasks** and **Sticky Notes** — nothing else, across two separate paginated endpoints (`GET /search/tasks`, `GET /search/stickies` — see `docs/api/api-spec.md` §13 for the full request/response contract). This doc covers the AI query-understanding layer that both endpoints share.

---

## 2. Why a standalone module instead of reusing `/classify`

The original proposal (2026-07-20) suggested extending the existing voice-command classifier (`voice/intent.js`, `classify.controller.ts`) since it already had roster-grounded name resolution and jargon glossary logic. **This was not what got built.** `searchClassify.ts` is its own module with its own OpenAI call, deliberately decoupled from `/classify` — a bug or schema change in search classification can't regress voice commands, and vice versa. It does still follow the same non-hallucination pattern (never invent a person who isn't a real tenant member; ties widen to an OR across every tied candidate, never guessed).

---

## 3. Scope

**In scope (the only two result types, ever):**
- Task (including Subtask — a Subtask is a `Task` row with `parentTaskId` set, same schema, same query)
- Sticky Note

**Explicitly out of scope, confirmed 2026-07-23 (not just an unimplemented gap):** Users, Departments, Labels, Broadcasts as standalone result types; `Comment.text`, `Evidence.fileName`, `VoiceRecording.rawTranscript` as match fields. A person's name (e.g. "Yash") is a **match field**, not a result type — searching "Yash" surfaces Tasks where Yash is assigner or assignee, never a "User" card.

---

## 4. Trigger rules

- Minimum **3 characters**, maximum **100**, or the API 400s with `VALIDATION_ERROR`.
- **Typed input:** client debounces before firing (~250–300ms after the user pauses) — the AI call is not cheap/instant enough for per-keystroke firing. Not enforced server-side; a client-side convention.
- **Voice input:** fires once on the finalized transcript from the Voice AI SDK, `source=voice` — this tells the classifier to apply transliteration (see §6) more aggressively, since STT mis-hearings are the dominant error mode there.

---

## 5. Input contract (API → AI layer)

```json
{ "query": "MBA", "source": "typed" }
```

`tenantId` and `userId` are never sent by the client — injected server-side from the JWT, same rule as every other endpoint. `classifySearchQuery()` is cached per `(query, source, userId, tenantId)` (`classifyCache.service.ts`) so both `/search/tasks` and `/search/stickies` agree on the same classification when a client calls both for one query.

---

## 6. Output contract (AI layer → search execution layer)

```json
{
  "resolvedKeywords": ["MBA"],
  "resolvedAssignee": { "id": "uuid-or-null", "name": "Yash Patil", "ambiguous": false, "candidates": null },
  "entityScope": "both",
  "filters": { "status": null, "priority": null, "due": null },
  "detectedLanguage": "hi",
  "interpretedQuery": "corrected term or null"
}
```

| Field | Type | Semantics |
|---|---|---|
| `resolvedKeywords` | `string[]` | Cleaned/typo-corrected/STT-corrected search terms, filler words stripped. Always at least `[query]` as a fallback. |
| `resolvedAssignee` | object \| `null` | `null` if no person name detected. Otherwise resolved **only against that tenant's real user list**, grounded with the caller's visible labels too (own-created ∪ labels used as `mainLabel` on any task the caller is assigner/assignee of — fixed 2026-07-24 after labels not grounding correctly for non-creator callers). Never invents a person. |
| `resolvedAssignee.ambiguous` | boolean | `true` if 2+ tenant users tie on the name match — widens the query to an OR across every tied candidate's **id**. |
| `entityScope` | `"task"` \| `"sticky"` \| `"both"` | Defaults to `"both"`. Only narrows if the query explicitly implies a scope. |
| `filters.status`/`.priority` | enum \| `null` | Normalized from GPT's human-friendly output (`"high"` → `P1`, `"open"` → `OPEN`) to real Prisma enum values via `normalizePriority`/`normalizeStatus` — a real crash was found and fixed here (2026-07-24) when this normalization was missing. |
| `filters.due` | enum \| `null` | `today\|tomorrow\|this_week`. |
| `detectedLanguage` | string | **Open-ended, not a fixed 5-value enum** (corrected 2026-07-24 from the original proposal's `en\|hi\|mr\|gu\|mixed`) — explicitly extended to Tamil/Telugu/Kannada/Bengali/Punjabi/Malayalam/Odia/Assamese/Urdu, not just Hindi/Marathi/Gujarati. |
| `interpretedQuery` | string \| `null` | Populated only when the classifier meaningfully corrected the raw query; surfaced to the frontend as a "Showing results for X" hint. |

**Latin-script output is required regardless of input script** (fixed 2026-07-24 — a real bug: voice input "Shivam" transcribed as Devanagari "शिवम" matched 0 results because nothing told GPT to transliterate its output back to Latin before matching against Latin-stored names). A deterministic Levenshtein-distance fallback (`scoreAssigneeCandidates`, `closestFuzzyLabel`) additionally catches name/label mis-hearings the LLM doesn't reliably self-correct (e.g. "Sarang" heard as "Tarang" — itself a plausible real name, so an ungrounded LLM won't always self-correct it).

**Failure fallback:** if the AI call errors, times out, or is unavailable, search falls back to a raw keyword match against `resolvedKeywords: [query]` — never a hard failure.

---

## 7. Search criteria — what actually gets matched, per bucket

### Task/Subtask bucket (`SearchRepository.ts`)

Scope: `tenantId = JWT` **AND** (`assignerId = userId` OR `assigneeId = userId`) — same visibility rule as the existing task list endpoints, not all-tenant. `Draft`/`Cancelled`/`Done_D` (archived) tasks **are** included by design (confirmed 2026-07-23) — search doesn't hide them like the default Assigned/Delegated views do.

Matched on ANY of: `title`, `description`, assignee/assigner name match (only if `resolvedAssignee` non-null), `mainLabel.name`. Multi-word keyword matching requires each word present regardless of separator (fixed 2026-08-01 — "self study report" now matches stored "self-study" hyphenation). `assigneeLabel` (private label) match is scoped `AND assigneeId = userId` in the same clause — cannot leak to the assigner. Then narrowed by `status`/`priority`/due-window filters, only when non-null.

A Subtask result opens its own Task Detail view directly (resolved — no longer an open question) — it's already a fully addressable Task row, no parent/highlight mechanism needed.

### Sticky bucket

Scope: `userId = calling user` only — strictly private, no `tenantId` join. Matched on `text ILIKE`. `filters.status`/`.priority` don't apply. `colorCode` is now selected and returned (a real bug found 2026-08-01: search results showed the wrong sticky color because this field was never selected in the query).

Pagination uses `orderBy: [primary, secondary, {id: 'asc'}]` on both buckets — the `id` tiebreaker is load-bearing, added 2026-08-01 after tied-timestamp rows caused skip/duplicate results across pages on bulk-seeded data.

---

## 8. Corner cases

| Case | Handling |
|---|---|
| Proper noun / name typo | Roster-grounded resolution + Levenshtein fallback |
| Two tenant users share a name | `ambiguous: true` → OR across every tied candidate's id, never guessed |
| Non-Latin-script voice transcription of a Latin-stored name | Classifier required to transliterate output to Latin (fixed 2026-07-24) |
| AI call fails/times out | Deterministic fallback — raw keyword search still runs, never a hard failure |
| Query matches both a task and a sticky | Both endpoints return results independently; frontend calls both |
| Tied-timestamp rows across a page boundary | `id` tiebreaker in `orderBy` (fixed 2026-08-01) |

---

## 9. Known residual gaps (as of 2026-08-03)

- Education-vertical jargon glossary equivalent — not confirmed either way in the latest sync; treat as still open until re-verified.
- Fully deterministic regression testing isn't possible (LLM-based classification) — see `docs/engineering/testing-strategy.md` "Global Search — Automated Test Catalog" for the test approach taken instead (deterministic fallback paths + fixture-based fuzzy-match assertions).
- Data residency: queries go to OpenAI, outside India — same caveat as the existing voice flow, not new to this feature.
