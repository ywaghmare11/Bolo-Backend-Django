# Fatafat — Git Workflow

---

## Branch strategy

```
main          ← production-ready; protected; only merged via PR
  └── staging ← pre-production; mirrors main after QA
        └── dev (or develop) ← integration branch for features

Feature branches cut from: dev
Hotfix branches cut from: main (then back-merged into dev)
```

### Branch naming

| Type | Format | Example |
|---|---|---|
| Feature | `feat/<short-description>` | `feat/task-acceptance-flow` |
| Bug fix | `fix/<short-description>` | `fix/broadcast-ack-not-saving` |
| Chore / tooling | `chore/<short-description>` | `chore/add-eslint-rules` |
| Docs | `docs/<short-description>` | `docs/update-domain-model` |
| Hotfix | `hotfix/<short-description>` | `hotfix/auth-token-expiry` |

---

## Commit messages

Format: `<type>(<scope>): <short description>`

```
feat(tasks): add task acceptance flow
fix(broadcast): ack not persisting on re-open
chore(deps): upgrade TypeScript to 5.5
docs(domain-model): add audit log entity
test(tasks): add integration test for re-assign guard
```

**Types:** `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`

Rules:
- Present tense: "add feature" not "added feature"
- No period at the end of the subject line
- Subject line max 72 characters
- Body is optional — use it for WHY, not WHAT

---

## Pull request process

1. Cut a branch from `dev`
2. Write code; commit often with meaningful messages
3. Open a PR against `dev`
4. PR must pass:
   - All CI checks (lint, type-check, tests)
   - At least 1 peer review approval
5. Squash-merge into `dev` (keeps history clean)
6. Delete the feature branch after merge

### PR description template

```markdown
## What
Brief description of the change.

## Why
Link to the user story / task this implements. What problem does it solve?

## How
Any non-obvious implementation detail worth flagging.

## Testing
How was this tested? (unit tests added? manual test steps?)

## Checklist
- [ ] No hardcoded UI strings
- [ ] DB queries scoped to tenantId
- [ ] Audit log updated if task/subtask fields changed
- [ ] PII fields encrypted if new PII column added
- [ ] Migration included if schema changed
- [ ] i18n keys added for any new UI strings
```

---

## Release flow

```
dev  →  (QA on staging)  →  main  →  production deploy
```

1. Merge `dev` into `staging` via PR
2. Run QA on the staging environment
3. If QA passes, merge `staging` into `main` via PR (no additional code changes)
4. Tag the release: `v1.0.0`, `v1.0.1`, etc. (semantic versioning)
5. CI/CD deploys `main` to production

---

## Hotfix flow

1. Cut `hotfix/<name>` from `main`
2. Fix the issue
3. PR into `main` → deploy to production
4. Back-merge `hotfix/<name>` into `dev` (avoid drift)

---

## Commit signing & hooks

- Commits should be signed (GPG or SSH) once the team is set up.
- Pre-commit hooks (via Husky or similar):
  - `lint-staged`: lint + format changed files only
  - `tsc --noEmit`: type-check
- Pre-push hooks:
  - Run unit tests for changed packages

---

## Protected branches

| Branch | Rules |
|---|---|
| `main` | No direct push; PR required; all CI must pass; 1 approval minimum |
| `staging` | No direct push; PR required; all CI must pass |
| `dev` | No force-push; PR required for external contributors |
