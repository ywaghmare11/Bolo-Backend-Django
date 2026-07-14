# Changelog — bolo-backend-django

> Engineering log for this project. Tags: `[BE]` `[STD]` `[INFRA]`. Newest first.
> For product-level decisions/history, see `docs/product/changelog.md` (copied from the original repo).

---

## 2026-07-14 (3)

- `[INFRA]` Project moved from a Windows dev machine to Linux for the actual build — folder was zipped/copied over, no longer under `C:\Users\yogesh\Projects\bolo-django\`. Updated the sibling-repo path in `CLAUDE.md` (was `C:\Users\yogesh\Projects\Bolo\`, now `~/Projects/Bolo/`, flagged as not present on this machine) — `ROADMAP.md` and `guidelines.md` had no OS-specific paths to change. Sibling `Bolo/` repo isn't available locally on Linux, so this repo's own `docs/` is now the sole source of truth going forward rather than a fallback to the original repo.

## 2026-07-14 (2)

- `[INFRA]` Clarified project intent: this is an interview portfolio project (Django dev, 3+ YOE interviews), not just a faithful port. Wrote `ROADMAP.md` — 14 phases from bootstrap through models/auth/tasks/pagination/supporting entities/broadcasts/search/notifications/OpenAI/audit/testing/caching/docker-CI/interview cheat-sheet. Locked two decisions: search = Postgres full-text + `pg_trgm` (no Elasticsearch), OpenAI use case = natural-language → structured task extraction, called async via Celery with timeout/fallback.

## 2026-07-14

- `[INFRA]` Project scaffolded: `bolo-backend-django/` created under `C:\Users\yogesh\Projects\bolo-django\` as a standalone Django + DRF re-implementation of the BOLO backend (original is Node/Express/Prisma, in `C:\Users\yogesh\Projects\Bolo\`). Copied backend-relevant `docs/` (domain model, api-spec, security, deployment, observability, runbook, prd, open-questions, testing-strategy, git-workflow, environments, global-search), the Prisma schema, and the Postman collection as reference material. Wrote `CLAUDE.md` and `guidelines.md` translating the original's architecture rules (Controller→Service→Repository, tenant scoping, audit logging, response envelope) into Django/DRF equivalents. No Django code written yet — next step is `django-admin startproject` + app scaffolding.
