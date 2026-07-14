# Documentation Guide — bolo-backend-django

This `docs/` folder is copied from the original **BOLO** repo (`bolo-web` + `bolo-backend`, Node/Express/Prisma) and is the **contract this Django project must implement**. It is *not* a fresh spec written for Django — it is the same product, same API shapes, same business rules, same domain model. Only the backend implementation language/framework changes.

## What's here (backend-relevant subset only)

| File | Why it's here |
|---|---|
| `product/prd.md` | Business rules, entities, MVP scope — unchanged by the language swap |
| `product/open-questions-web-v1.md` | Pending decisions (W15, W19, W64, doc size limit) — still open, still block the same areas |
| `product/changelog.md` | Product decision history — context for *why* rules are what they are |
| `architecture/domain-model.md` | Entity/field/relationship source of truth — **the model to port to Django `models.py`** |
| `architecture/system-design.md` | Component/infra map from the original stack — adapt, don't copy blindly (see CLAUDE.md tech stack table) |
| `architecture/adr/` | Architecture Decision Records — why past choices (Postgres, tenant model, etc.) were made |
| `api/api-spec.md` | **The binding contract.** Every endpoint, request/response shape, status/error code. `bolo-web` is coded against this exactly — do not change a response shape here without updating it in the original Bolo repo's copy too, and flagging the drift to whoever maintains `bolo-web`. |
| `ops/security.md` | Security checklist — tenant isolation, PII/DPDP rules, audit logging requirements |
| `ops/deployment.md` | Original deploy pipeline — reference only; this project's actual deploy setup will differ (Django/gunicorn vs Node) |
| `ops/observability.md` | Original logging/metrics setup — reference for parity, not a hard requirement |
| `ops/runbook.md` | Original incident playbook — adapt once this service actually runs somewhere |
| `engineering/testing-strategy.md` | Test pyramid + critical test case list — same cases apply, tooling translates to pytest-django |
| `engineering/git-workflow.md` | Branch/commit/PR conventions |
| `engineering/environments.md` | Original env var reference — **shape is right, values (`DATABASE_URL` etc.) point at Node tooling; see this project's own `README.md` for the Django equivalents** |
| `engineering/global-search.md` | Global search feature spec (backend-owned) |
| `reference/schema.prisma.reference` | The exact Prisma schema this project ports to Django `models.py`. Table/column names (snake_case, per `docs/engineering guidelines`) must match so the DB contract stays identical even though the ORM is different. **Not executable here — reference only.** |
| `reference/BOLO-API.postman_collection.json` | Working request/response examples — useful for writing DRF serializer tests against real payloads |

**Deliberately excluded:** `docs/ux/design-system.md` and `docs/design-session.md` (frontend/Figma-only — this is a backend-only project with no UI) and `docs/product/sprint-plan-4w.md` (PM scheduling, not implementation-relevant).

## Source of truth going forward

For everything in `api/api-spec.md` and `architecture/domain-model.md`: **this is a port, not a redesign.** If Django forces a genuinely different shape somewhere, note it in this project's own `changelog.md` as a `[BE]` entry and flag it back to the `bolo-web`/original-`bolo-backend` maintainer — those two repos need to agree on the contract even though they no longer share a codebase.
