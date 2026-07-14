# Environments & Local Setup

> Status: **Stub** — fill in when the tech stack is confirmed (Q63) and the repo has source code.

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Node.js | 20+ (LTS) | https://nodejs.org |
| Docker Desktop | Latest | https://docker.com |
| Git | 2.40+ | https://git-scm.com |
| (Others TBD) | | |

---

## Local setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd <project-name>

# 2. Start backing services (DB, etc.)
docker-compose up -d

# 3. Install dependencies
npm install

# 4. Configure environment variables
cp .env.example .env.dev
# Open .env.dev and fill in values (see table below)

# 5. Run database migrations
npm run db:migrate

# 6. Start API dev server
npm run dev --workspace=apps/api

# 7. Start web dev server (separate terminal)
npm run dev --workspace=apps/web
```

---

## Environment variable reference

| Variable | Required | Description | Example / Notes |
|---|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string | `postgres://user:pass@localhost:5432/dbname` |
| `JWT_SECRET` | ✅ | Secret for signing access tokens | Generate: `openssl rand -hex 32` |
| `JWT_REFRESH_SECRET` | ✅ | Secret for signing refresh tokens | Generate: `openssl rand -hex 32` |
| `S3_BUCKET_NAME` | ✅ | Evidence file storage bucket | `project-evidence-dev` |
| `S3_REGION` | ✅ | AWS region | `ap-south-1` |
| `AWS_ACCESS_KEY_ID` | ✅ | AWS credentials | Use dev IAM user |
| `AWS_SECRET_ACCESS_KEY` | ✅ | AWS credentials | Use dev IAM user |
| `VOICE_API_KEY` | — | Voice AI provider API key | Only needed for voice feature dev |
| `WHATSAPP_API_KEY` | — | WhatsApp Business API key | Only needed for notification dev |
| `PORT` | — | API server port | Default: `3000` |

---

## Environments

| Environment | Purpose | URL | Branch |
|---|---|---|---|
| Local | Development | `localhost:3000` | Any feature branch |
| Staging | Pre-production QA | TBD | `staging` |
| Production | Live users | TBD | `main` |

---

## Running tests

```bash
# Unit tests
npm run test:unit

# Integration tests (requires local DB running)
npm run test:integration

# All tests
npm test
```

---

## Common setup issues

| Problem | Fix |
|---|---|
| DB connection refused | Run `docker-compose up -d` and wait 5 seconds |
| Migrations fail | Check `DATABASE_URL` in `.env.dev` is correct |
| Port already in use | Change `PORT` in `.env.dev` or kill the process using it |
| (Add more as they are discovered) | |
