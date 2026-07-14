# bolo-backend-django

A standalone **Django + Django REST Framework** re-implementation of the BOLO backend (originally Node/Express/Prisma — see the sibling `Bolo/` repo). Same product, same API contract, same domain model, same business rules — different implementation language.

This project does **not** depend on the original repo at runtime. It is a separate deployable service, with its own PostgreSQL database. The React frontend (`bolo-web`, in the original repo) can point at either backend — whichever is running — by setting `VITE_API_URL`.

## Status

Scaffold stage only — `docs/`, `CLAUDE.md`, `guidelines.md` are in place. No Django project/apps have been created yet. See `CLAUDE.md` → "Current Build Status" for the punch list.

## What's in this repo

```
bolo-backend-django/
├── CLAUDE.md          ← AI assistant instructions — read this first
├── guidelines.md      ← Coding standards (Python/Django port of the original)
├── README.md          ← This file
├── changelog.md       ← Engineering log for this project ([BE] [STD] [INFRA])
└── docs/              ← Copied contract from the original repo — see docs/README.md
```

## Local setup (once code exists)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env             # fill in DATABASE_URL, JWT_SECRET, etc.
python manage.py migrate
python manage.py runserver
```

(This section will be filled in with real, tested commands once the project is actually scaffolded with `django-admin startproject`.)

## Key docs

- [`CLAUDE.md`](CLAUDE.md) — project overview, tech stack, architecture rules, business rules
- [`ROADMAP.md`](ROADMAP.md) — phased build plan (this is an interview portfolio project — see the roadmap for why each phase is built the way it is)
- [`guidelines.md`](guidelines.md) — coding standards
- [`docs/api/api-spec.md`](docs/api/api-spec.md) — the API contract this project implements
- [`docs/architecture/domain-model.md`](docs/architecture/domain-model.md) — entities to port to `models.py`
- [`docs/reference/schema.prisma.reference`](docs/reference/schema.prisma.reference) — the exact original schema to port field-for-field
