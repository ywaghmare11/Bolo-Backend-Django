# Architecture Decision Records (ADRs)

An ADR captures a significant technical decision: what was chosen, what alternatives were considered, and why.

## Why ADRs

Six months into a project, the question "why did we use X instead of Y?" either has a documented answer or requires finding the person who made the decision. ADRs make the answer findable.

## When to write one

Write an ADR when:
- Choosing a database, framework, or cloud service
- Deciding between two valid architectural approaches
- Making a decision that would be costly to reverse
- Any decision a future developer might question

Do NOT write an ADR for: library version bumps, minor config changes, coding style decisions (those go in `guidelines.md`).

## Format

File name: `NNN-short-title.md` (e.g., `001-database-choice.md`)

```markdown
# ADR NNN — Title

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR NNN
**Date:** YYYY-MM-DD
**Decided by:** Name(s)

## Context
Why does this decision need to be made? What is the situation?

## Options considered

### Option A — Name
Pros: ...
Cons: ...

### Option B — Name
Pros: ...
Cons: ...

## Decision
We chose Option A because ...

## Consequences
- What this means for development going forward
- Any follow-up actions or constraints introduced
```

## Never delete an ADR
If a decision is reversed, mark the ADR as `Superseded by ADR NNN` and write a new ADR for the new decision.

---

## Index

| # | Title | Status | Date |
|---|---|---|---|
| — | No ADRs yet | — | — |
