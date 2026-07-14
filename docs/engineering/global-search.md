# BOLO — Global Search: Full Implementation Plan

> **Created:** 2026-07-01
> **Author:** sarang
> **Status:** Approved for implementation — MVP scope
> **Search strategy:** PostgreSQL `ILIKE` (MVP). Upgrade path to FTS + GIN index documented in §8.
> **Deadline:** 30 July 2026 MVP

---

## 1. Overview

Global search lets any authenticated user find Tasks, Users, Departments, Labels, Sticky Notes, and Broadcast Notices across their tenant from a single search bar in the Top Bar.

Search is a **Workspace State** (`WORKSPACE.SEARCH_RESULTS`) — results render in the main workspace canvas, not in a dropdown overlay. Clicking any result transitions to the appropriate workspace state for that entity.

---

## 2. What Is Searchable

| Entity | Fields Searched | Visibility Rule |
|---|---|---|
| **Tasks** (incl. subtasks) | `title`, `description` | Only tasks where `assignerId = userId` OR `assigneeId = userId` |
| **Users** | `name`, `email` | All users in the same tenant |
| **Departments** | `name` | All departments in the same tenant |
| **ProjectLabels** | `name` | All labels in the same tenant |
| **StickyNotes** | `title`, `content` | Only notes where `userId = currentUser.id` (strictly private) |
| **BroadcastNotices** | `messageHtml` (plain-text strip) | Only notices scoped to the user's dept + role level |

**Excluded from MVP:** Comments, Evidence filenames, VoiceRecording transcripts. Add in a later phase.

---

## 3. API Design

### Endpoint

```
GET /api/v1/search?q=<query>&types=<csv>&limit=<n>
```

### Query Parameters

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `q` | string | ✅ | — | Min 2 chars; max 100 chars |
| `types` | CSV string | ❌ | all | `tasks,users,departments,labels,stickies,broadcasts` |
| `limit` | number | ❌ | `5` | Per-category cap; max `20` |

### Auth & Scoping

- Requires `requireAuth` middleware — `401` if no valid JWT.
- `tenantId` read from JWT only — never from request body.
- Per-entity visibility rules enforced in the repository layer (see §5.3).

### Success Response

```json
{
  "success": true,
  "message": "OK",
  "data": {
    "query": "rohit",
    "results": {
      "tasks": [
        {
          "id": "uuid",
          "title": "Submit Q1 report",
          "status": "OPEN",
          "priority": "P2",
          "assigneeId": "uuid",
          "assigneeName": "Rohit Sharma",
          "dueDate": "2026-07-15T00:00:00Z"
        }
      ],
      "users": [
        {
          "id": "uuid",
          "name": "Rohit Sharma",
          "email": "rohit@abc.edu",
          "orgRoleLevel": "EXECUTOR"
        }
      ],
      "departments": [],
      "labels": [],
      "stickies": [],
      "broadcasts": []
    },
    "totals": {
      "tasks": 1,
      "users": 1,
      "departments": 0,
      "labels": 0,
      "stickies": 0,
      "broadcasts": 0
    }
  }
}
```

### Error Responses

| HTTP | Code | Trigger |
|---|---|---|
| `400` | `VALIDATION_ERROR` | `q` missing, under 2 chars, or over 100 chars |
| `401` | `UNAUTHENTICATED` | No or expired JWT |
| `500` | `SERVER_ERROR` | Unexpected DB error |

---

## 4. Backend — File Map

```
bolo-backend/src/
├── routes/
│   └── search.routes.ts          ← registers GET /search
├── controllers/
│   └── search.controller.ts      ← validates q param, calls service
├── services/
│   └── search.service.ts         ← orchestrates parallel repo calls
└── repositories/
    └── search.repository.ts      ← all ILIKE queries (one method per entity)
```

---

## 5. Backend — Implementation Detail

### 5.1 Route (`search.routes.ts`)

```
GET /search   →  requireAuth  →  searchController.search
```

No `requireOrgRole` — any authenticated tenant member can search.

### 5.2 Controller (`search.controller.ts`)

Responsibilities (HTTP layer only):
1. Read `q`, `types`, `limit` from `req.query`.
2. Validate: `q` must be a non-empty string, 2–100 chars. Return `400 VALIDATION_ERROR` if not.
3. Parse `types` CSV into an array; default to all types if absent.
4. Clamp `limit` to `[1, 20]`; default `5`.
5. Call `searchService.search({ q, types, limit, tenantId, userId })`.
6. Return `successResponse(res, data, 'OK')`.

### 5.3 Service (`search.service.ts`)

Responsibilities (business logic only):
1. Receive validated `{ q, types, limit, tenantId, userId }`.
2. Build `searchTerm = %${q}%` (single place — never built in the repository).
3. Run only the requested entity queries — skip others.
4. Run all active queries **in parallel** (`Promise.all`).
5. Return a grouped results object.

```typescript
// Pseudocode — parallel execution
const [tasks, users, depts, labels, stickies, broadcasts] = await Promise.all([
  types.includes('tasks')      ? searchRepo.searchTasks(...)      : [],
  types.includes('users')      ? searchRepo.searchUsers(...)      : [],
  types.includes('departments')? searchRepo.searchDepartments(...): [],
  types.includes('labels')     ? searchRepo.searchLabels(...)     : [],
  types.includes('stickies')   ? searchRepo.searchStickies(...)   : [],
  types.includes('broadcasts') ? searchRepo.searchBroadcasts(...) : [],
]);
```

### 5.4 Repository (`search.repository.ts`)

All Prisma calls live here. Each method uses `ILIKE` via Prisma's `contains` + `mode: 'insensitive'`.

**Tasks:**
```
WHERE tenantId = :tenantId
  AND (assignerId = :userId OR assigneeId = :userId)
  AND (title ILIKE :term OR description ILIKE :term)
LIMIT :limit
```
Return: `id, title, status, priority, dueDate, assigneeId + assignee.name`

**Users:**
```
WHERE TenantMembership.tenantId = :tenantId
  AND (name ILIKE :term OR email ILIKE :term)
LIMIT :limit
```
Return: `id, name, email, orgRoleLevel`

**Departments:**
```
WHERE tenantId = :tenantId
  AND name ILIKE :term
LIMIT :limit
```
Return: `id, name, headUserId + headUser.name`

**ProjectLabels:**
```
WHERE tenantId = :tenantId
  AND name ILIKE :term
LIMIT :limit
```
Return: `id, name, color`

**StickyNotes:**
```
WHERE userId = :userId                ← private; NO tenantId needed (user is already scoped)
  AND (title ILIKE :term OR content ILIKE :term)
LIMIT :limit
```
Return: `id, title, content, dueAt, isPinned`

**BroadcastNotices (published, not expired, audience-matched):**
```
WHERE tenantId = :tenantId
  AND status = 'PUBLISHED'
  AND publishedAt > NOW() - INTERVAL '1 day'
  AND (audienceDeptId = :userDeptId OR audienceDeptId IS NULL)
  AND (audienceRoleLevel = :userOrgRole OR audienceRoleLevel IS NULL)
  AND messageHtml ILIKE :term
LIMIT :limit
```
Return: `id, title, messageHtml (truncated to 120 chars), publishedAt`

> ⚠️ `messageHtml` contains HTML tags — strip them before returning to the frontend or before matching. Use a helper `stripHtml(html)` in the service layer before building the search term match display text.

---

## 6. Frontend — File Map

```
bolo-web/src/
├── pages/
│   └── SearchResults/
│       ├── index.tsx             ← workspace canvas for WORKSPACE.SEARCH_RESULTS
│       ├── style.scss            ← page-scoped styles
│       └── hooks.ts              ← useSearchResults (reads query from Zustand)
├── components/
│   ├── GlobalSearchBar/
│   │   ├── index.tsx             ← input in TopBar; triggers setWorkspace + sets query
│   │   └── style.scss
│   └── SearchResultGroup/
│       ├── index.tsx             ← reusable grouped result section (Tasks / Users / etc.)
│       └── style.scss
├── hooks/
│   └── useSearch.ts              ← useFetch wrapper for GET /search
├── api/
│   └── search.api.ts             ← getService('/search', { q, types, limit })
└── store/
    └── searchStore.ts            ← Zustand: { query, activeTypes } (UI state only)
```

---

## 7. Frontend — Implementation Detail

### 7.1 Zustand Store (`searchStore.ts`)

Holds UI state only — NOT the results (those live in TanStack Query cache).

```typescript
interface SearchStore {
  query: string;
  activeTypes: string[];
  setQuery: (q: string) => void;
  setActiveTypes: (types: string[]) => void;
  clearSearch: () => void;
}
```

### 7.2 GlobalSearchBar Component

- Rendered in `TopBar` — always visible.
- On input change: update `searchStore.query` (debounced — 300ms).
- On first keystroke (or focus with existing query): call `setWorkspace(WORKSPACE.SEARCH_RESULTS)`.
- On `Escape` or blur with empty input: `clearSearch()` + revert to previous workspace state.
- Keyboard shortcut: `Ctrl+K` / `Cmd+K` focuses the input from anywhere.
- Min 2 chars before the API call fires (enforce in `useSearch` hook, not in the component).

### 7.3 useSearch Hook (`useSearch.ts`)

```typescript
// Uses useFetch (never raw useQuery)
// Enabled only when query.length >= 2
// staleTime: 30s — search results don't need to be hyper-fresh
// Key: ['search', query, activeTypes, limit]
```

### 7.4 Search API Function (`search.api.ts`)

```typescript
// Calls getService from apiServices.ts
// Builds query string: ?q=...&types=...&limit=5
// Returns SearchResponse shape
```

### 7.5 SearchResults Page (`SearchResults/index.tsx`)

- Reads `query` from `searchStore`.
- Calls `useSearch(query)`.
- Renders one `<SearchResultGroup>` per entity type that has results.
- Groups with zero results are hidden (not shown as "0 results").
- If ALL groups are empty → show a single "No results for `{query}`" state.
- Loading state: skeleton rows inside each group.
- Error state: "Search unavailable — try again."

### 7.6 SearchResultGroup Component

Receives: `title` (e.g. "Tasks"), `items[]`, `onItemClick`.

Each item row shows:
- **Tasks:** title + assignee name + status badge + due date
- **Users:** name + email + role label
- **Departments:** name + head name
- **Labels:** color dot + name
- **Stickies:** title + content snippet (60 chars) + due date if set
- **Broadcasts:** title + content snippet (120 chars, HTML stripped) + published date

### 7.7 Navigation on Click

Each result click calls `setWorkspace` with the appropriate workspace state:

| Entity | Action |
|---|---|
| Task | `setWorkspace(WORKSPACE.TASK_DETAIL, { taskId })` |
| User | `setWorkspace(WORKSPACE.USER_PROFILE, { userId })` |
| Department | `setWorkspace(WORKSPACE.DEPARTMENT_DETAIL, { deptId })` |
| Label | `setWorkspace(WORKSPACE.TASKS_BY_LABEL, { labelId })` |
| Sticky Note | `setWorkspace(WORKSPACE.STICKY_DETAIL, { noteId })` |
| Broadcast | `setWorkspace(WORKSPACE.BROADCAST_DETAIL, { noticeId })` |

> Use whatever `WORKSPACE.*` constants already exist — add new ones if the state doesn't exist yet, following the existing `routeConstants.ts` pattern.

---

## 8. Not in MVP — Upgrade Path

These are explicitly deferred. The API contract above is designed to accommodate them without breaking changes.

| Feature | Notes |
|---|---|
| **PostgreSQL FTS** | Replace `ILIKE` with `to_tsvector` + `plainto_tsquery` + GIN index. Change only `search.repository.ts`. API unchanged. |
| **Hindi / multilingual** | Use `pg_catalog.simple` dictionary in FTS. |
| **Result ranking** | Add `ts_rank` scoring in FTS; sort results by rank within each group. |
| **Search Comments** | Add `Comment.body ILIKE :term` in `searchTasks` join or a separate `searchComments` method. |
| **Search Evidence filenames** | `Evidence.fileName ILIKE :term`, scoped to task visibility. |
| **Voice-triggered search** | Voice AI calls `setWorkspace(WORKSPACE.SEARCH_RESULTS)` + sets query in `searchStore`. No new backend needed. |
| **Search history** | Store last 10 queries in `localStorage` — purely frontend, zero backend. |
| **Cmd+K command palette** | Extend `GlobalSearchBar` to show recent searches + quick actions when query is empty. |

---

## 9. Build Sequence

Build in this order — each step is independently testable:

1. **Backend repository** — write all 6 ILIKE query methods with mock data to verify SQL shapes.
2. **Backend service + controller + route** — wire up, test with Postman / REST client.
3. **Frontend API function + useSearch hook** — verify data shape against response.
4. **GlobalSearchBar component** — input, debounce, Zustand write, workspace switch.
5. **SearchResultGroup component** — static with mock data first.
6. **SearchResults page** — compose groups, wire to `useSearch`, handle loading/empty/error.
7. **Navigation on click** — verify each entity type navigates correctly.
8. **Keyboard shortcut** — `Ctrl+K` / `Cmd+K` focus.

---

## 10. Security Checklist

- [ ] `tenantId` sourced from JWT only — never from `req.query` or `req.body`
- [ ] Sticky Notes query filters by `userId`, not just `tenantId` — private results cannot leak
- [ ] Broadcast audience filter enforced in repository — users outside the audience cannot see results
- [ ] Min query length (2 chars) enforced server-side — prevents full-table scan on empty string
- [ ] Max query length (100 chars) enforced — prevents oversized ILIKE patterns
- [ ] `messageHtml` HTML is stripped before sending to client — no raw HTML in search snippets
- [ ] RBAC middleware (`requireAuth`) on the route — unauthenticated calls return `401`
- [ ] No raw `res.json()` — all responses via `successResponse` / `failureResponse`

---

## 11. Open Questions

None blocking MVP. Log any new ones in `docs/product/open-questions-web-v1.md`.

Potential future question: should search results from Broadcast Notices older than 24 h (expired) still be findable? Currently excluded by the `publishedAt > NOW() - INTERVAL '1 day'` filter — consistent with the 1-day visibility rule (W54 resolved).
