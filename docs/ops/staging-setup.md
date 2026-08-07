# BOLO Staging — AWS Infra Setup

**Region:** ap-south-1 (Mumbai) for everything.
**Goal:** Get staging live before OpenShift sandbox expires (~Jul 26).

---

## Before you start — collect these first

Everything below must be in hand before touching AWS:

| What | Status | Notes |
|---|---|---|
| **Client's AWS account ID** | ✅ have it | `929123273547` |
| **Domain name** | ✅ have it (2026-07-16) | `aibigo.in` (client corrected from `.com` same day). Client's own words specified `bolo.aibigo.in/integrate18/varun/` for staging (path confirmed literal, 2026-07-16). **Dev-team addition, not client-specified:** prefixed with `staging.` → **`staging-bolo.aibigo.in/integrate18/varun/`**, to keep the environment name in the URL itself and leave `bolo.aibigo.in` free for a clean production URL later. Not run past the client — reasonable to loop them in if this URL gets shared externally. **✅ Path routing (`/integrate18/varun/`) decided + implemented 2026-07-18 — see `staging-runbook.md` backlog item 5.** Both frontend and backend API sit under the prefix; `bolo-web/nginx.conf` strips it before proxying to `bolo-backend`, no backend code change needed. |
| **Domain on Cloudflare** | confirm | Domain's nameservers must point to Cloudflare — check at registrar (GoDaddy / Namecheap etc.). If not yet done, update nameservers and wait for propagation (up to 24h). |
| **Cloudflare account** | ❌ needs creating (corrected 2026-07-17 — the "✅ have it" here was never actually verified, false positive) | No existing account for this project. Needs creating with a team/shared email, not a personal one — same reasoning as `bolosupport@aibigo.in` being a dedicated alias. |
| **GitHub repos access** | ✅ have it | `integrate18/bolo-backend` + `integrate18/bolo-web` |
| **SES domain/sender verification** | needs client's official sender email | AWS SES (decided 2026-07-16, W100) — needs the domain or a specific sender identity verified in SES before it can send OTP/reminder emails. Same pending-item as the domain used for Cloudflare. |
| **Sarvam API key** | confirm | From Sarvam dashboard — needed for Voice AI. |
| **Grafana Cloud account** | create before Step 11 | Free at grafana.com — can create anytime before Step 11 |

**Subdomains to create in Cloudflare (Step 8):**
- `staging-bolo.aibigo.in` → frontend + API (both on same EC2). Confirmed by client 2026-07-16 — not the generic `staging.<domain>` pattern; the app is further scoped to path `/integrate18/varun/` (app-layer routing, not a DNS concern).

**If domain is NOT yet on Cloudflare:**
1. Add domain to Cloudflare (free plan)
2. Cloudflare shows you 2 nameserver addresses
3. Log into your domain registrar → change nameservers to Cloudflare's
4. Wait for propagation — can take 10 minutes to 24 hours

---

## Order of creation

```
0. Client grants dev team AWS console access (one-time, done by client)
1. IAM (GHA user + EC2 role)
2. ECR
3. Security Groups
4. RDS
5. Secrets Manager + SSM
6. S3
7. EC2
8. Cloudflare
9. GitHub Secrets
10. First deploy (GHA)
11. Grafana Cloud
```

---

## Step 0 — Client grants dev team AWS console access

**Done by the client (root account holder) — one time only.**

The client logs into their AWS account as root and creates one IAM user for the dev team:

| Field | Value |
|---|---|
| Username | `bolo-dev` (or similar) |
| Access type | AWS Management Console access |
| Password | auto-generated, share securely (via 1Password / WhatsApp OTP / etc.) |
| Permissions | `AdministratorAccess` (simplest) OR custom policy covering EC2, RDS, S3, ECR, SSM, SecretsManager, IAM, **SES** (added 2026-07-17 — missed originally, written before the SES-vs-Gmail-SMTP decision (W100) was resolved) |
| MFA | Recommended — ask dev team to set up on first login |

**Console login URL format:**
```
https://<client-aws-account-id>.signin.aws.amazon.com/console
```

The client shares:
- Account ID (12-digit number)
- Username: `bolo-dev`
- Temporary password

Dev team logs in, changes password on first login, and then handles all of Steps 1–11.

> **Note:** `AdministratorAccess` gives full account access. If the client is uncomfortable with that, a custom policy scoped to just the services BOLO uses is possible — but takes more setup time. For a time-bound staging setup, `AdministratorAccess` with MFA is the practical choice.

---

## Step 1 — IAM

Two things to create:

**A. IAM User `bolo-gha`** (for GitHub Actions)
- Permissions: `AmazonEC2ContainerRegistryFullAccess` + `AmazonSSMFullAccess`
- Generate access keys → save for Step 9

**B. IAM Role `bolo-ec2-role`** (for the EC2 instance)
- Trusted entity: EC2
- Permissions: `AmazonSSMManagedInstanceCore` + `AmazonS3FullAccess` + `AmazonEC2ContainerRegistryReadOnly` + `SecretsManagerReadWrite`
- This role lets EC2 pull images from ECR, read S3, fetch secrets, and accept SSM commands — no static credentials needed on the server

---

## Step 2 — ECR

Prerequisites: Step 1 done.

Create two private repositories in ap-south-1:
- `bolo-backend`
- `bolo-web`

Lifecycle policy on each: keep last 4 images (untagged images expire after 1 day).

Note the registry URL: `<account-id>.dkr.ecr.ap-south-1.amazonaws.com`

---

## Step 3 — Security Groups

Prerequisites: nothing (use default VPC).

**SG: `bolo-ec2-sg`**
| Direction | Port | Source |
|---|---|---|
| Inbound | 80 | 0.0.0.0/0 |
| Inbound | 443 | 0.0.0.0/0 |
| Outbound | all | 0.0.0.0/0 |

No port 22 — SSH is closed. SSM is used instead.

**SG: `bolo-rds-sg`**
| Direction | Port | Source |
|---|---|---|
| Inbound | 5432 | `bolo-ec2-sg` only |
| Outbound | all | 0.0.0.0/0 |

---

## Step 4 — RDS PostgreSQL

Prerequisites: Step 3 (need `bolo-rds-sg`).

- Engine: PostgreSQL 16
- Instance: db.t3.small
- Storage: 20 GB gp3
- Availability: Single-AZ (staging)
- VPC: default · Subnet: private · SG: `bolo-rds-sg`
- DB name: `bolo` · Username: `bolo` · Password: generate and save for Step 5
- Public access: **No**

Note the endpoint URL after creation — needed in Step 5.

---

## Step 5 — Secrets Manager + SSM Parameter Store

Prerequisites: Step 4 (need RDS endpoint + password).

**Secrets Manager** — one secret per sensitive value (~₹165/mo total):

| Secret name | Value |
|---|---|
| `bolo/staging/DATABASE_URL` | `postgresql://bolo:<password>@<rds-endpoint>:5432/bolo` — full connection string, password embedded (not a separate `DB_PASSWORD` secret — decided 2026-07-16, see `deployment.md` Group 5) |
| `bolo/staging/JWT_SECRET` | generate a random 64-char string |
| `bolo/staging/SARVAM_API_KEY` | from Sarvam dashboard |
| `bolo/staging/OPENAI_API_KEY` | from OpenAI dashboard |

**SSM Parameter Store** (free, Standard tier) — non-sensitive config:

| Parameter name | Value |
|---|---|
| `/bolo/staging/NODE_ENV` | `production` |
| `/bolo/staging/PORT` | `3000` |
| `/bolo/staging/TZ` | `Asia/Kolkata` |
| `/bolo/staging/CORS_ORIGIN` | `https://staging-bolo.aibigo.in` — **create at Step 8, not here** (avoids a placeholder value sitting in SSM that could get read by an early deploy). Backend Express CORS — distinct from the S3 bucket CORS policy below, which is a different concern despite the shared name. |
| `/bolo/staging/S3_BUCKET` | `bolo-staging` |
| `/bolo/staging/S3_PREFIX` | `staging/` |
| `/bolo/staging/AWS_REGION` | `ap-south-1` |

**Not stored in AWS — goes directly in `docker-compose.yml` (Step 7), since these are fixed/environment-invariant, not secrets or per-deploy config:** `LOG_LEVEL=info`, `OTEL_SERVICE_NAME=bolo-backend`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318` (Alloy's Docker Compose service name, not an AWS value). `LOG_PRETTY` stays unset — `observability.md` explicitly says never set it in Docker.

**⚠️ Unaddressed gap, still needs resolving before Step 9/10 — GHA build-arg wiring, not a value/routing question anymore:** `bolo-web`'s `VITE_API_URL`/`VITE_AUTH_URL`/`VITE_BASE_PATH` are baked into the JS bundle at **Docker build time**, not fetched at container runtime — Secrets Manager/SSM can't help here. The *values* and the path-routing design are now decided (2026-07-18, see `staging-runbook.md` backlog item 5): `VITE_API_URL=https://staging-bolo.aibigo.in/integrate18/varun` (no trailing slash), `VITE_AUTH_URL` same value for now (single backend), `VITE_BASE_PATH=/integrate18/varun/`. What's still missing is purely mechanical: nothing in the GitHub Actions workflow yet passes these three as `--build-arg` when building the `bolo-web` image.

**Email (AWS SES, decided 2026-07-16, W100) — still blocked on client's official sender email/domain:**
- `/bolo/staging/SES_FROM_EMAIL` (SSM, non-sensitive) — the verified sender address, needed regardless of transport mechanism below. Pending client.
- Beyond that, what else is needed depends on an implementation decision not yet made by whoever builds the email-sending code:
  - **If AWS SDK** (recommended — matches this project's IAM-role-over-static-keys pattern elsewhere): no secrets/params needed beyond `SES_FROM_EMAIL` — just the `ses:SendEmail`/`ses:SendRawEmail` IAM permission already granted to `bolo-ec2-role`.
  - **If SES's SMTP interface** (keeps `nodemailer` as the code library): needs `bolo/staging/SES_SMTP_PASSWORD` (Secrets Manager) + `/bolo/staging/SES_SMTP_HOST` (`email-smtp.ap-south-1.amazonaws.com`) + `/bolo/staging/SES_SMTP_PORT` (`587`) + `/bolo/staging/SES_SMTP_USER` — all SES-generated, not reused from Gmail.

---

## Step 6 — S3

Prerequisites: Step 1B (IAM role must exist to attach bucket policy).

Create bucket `bolo-staging` in ap-south-1:
- Block all public access: **On**
- Versioning: off (staging)
- Folder structure is by prefix in code — actual runtime key prefixes are `staging/bolo-evidence/`, `staging/bolo-voice/`, `staging/bolo-profile-pics/` (from `S3_EVIDENCE_BUCKET`/`S3_VOICE_BUCKET`/`S3_PROFILE_BUCKET` logical bucket names resolved against `S3_PREFIX` in `src/utils/s3.ts`'s `resolveReal()`), not `staging/evidence/`/`staging/voice/` — no folders to create manually either way

CORS policy (needed for browser uploads) — **includes the OpenShift dev frontend origin too, not just staging** (bucket is shared between dev + staging per `deployment-proposal-client.md`'s prefix design — `bolo-staging/dev/` and `bolo-staging/staging/` in the same bucket, missed on the first pass of this doc, corrected 2026-07-17):
```json
[{
  "AllowedHeaders": ["*"],
  "AllowedMethods": ["GET","PUT","POST","DELETE"],
  "AllowedOrigins": ["https://staging-bolo.aibigo.in", "https://bolo-web-techbrutal1151-dev.apps.rm1.0a51.p1.openshiftapps.com"],
  "ExposeHeaders": ["ETag"]
}]
```

---

## Step 7 — EC2

Prerequisites: Steps 1B (role), 3 (SG), 5 (secrets exist), 6 (S3 exists).

- AMI: Amazon Linux 2023
- Instance type: t3.small
- IAM instance profile: `bolo-ec2-role` (from Step 1B)
- SG: `bolo-ec2-sg`
- Storage: 20 GB gp3
- No key pair needed (SSM access only)

**After launch — SSH in once via SSM console to set up:**

```bash
# Install Docker
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Create app directory
sudo mkdir -p /app
sudo chown ec2-user:ec2-user /app
```

Then place `docker-compose.yml` in `/app/` (bolo-backend + bolo-web + alloy).

**Verify SSM is working:**
From AWS Console → Systems Manager → Fleet Manager → confirm instance appears.

---

## Step 8 — Cloudflare

Prerequisites: Step 7 (need EC2 public IP).

1. Add DNS record: `staging-bolo.aibigo.in` → EC2 public IP, **Proxied** (orange cloud on)
2. SSL/TLS → Full (strict)
3. SSL/TLS → Origin Server → Create certificate → copy certificate + key
4. On EC2: save as `/etc/ssl/bolo-origin.crt` and `/etc/ssl/bolo-origin.key`
5. Nginx config in the `bolo-web` container references these files

---

## Step 9 — GitHub Secrets

Prerequisites: Step 1A (IAM user keys), Step 7 (EC2 instance ID).

Add to GitHub repo secrets (both `bolo-backend` and `bolo-web` repos):

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | from `bolo-gha` IAM user |
| `AWS_SECRET_ACCESS_KEY` | from `bolo-gha` IAM user |
| `EC2_INSTANCE_ID` | e.g. `i-0abc123def456` |

---

## Step 10 — First Deploy (GHA)

Prerequisites: All above steps done.

1. Trigger GHA `workflow_dispatch` from `staging` branch on both repos
2. Watch build logs — images push to ECR, SSM command triggers on EC2
3. On EC2, verify: `docker compose ps` → all 3 containers running
4. Run DB migration manually on first deploy:
   ```bash
   # Via SSM session on EC2
   cd /app && docker compose exec bolo-backend npx prisma migrate deploy
   ```
5. Hit `https://staging-bolo.aibigo.in/integrate18/varun/api/v1/health` → should return `{ status: "ok" }`
6. Hit `https://staging-bolo.aibigo.in/integrate18/varun/` → frontend loads

---

## Step 11 — Grafana Cloud

Prerequisites: Step 10 (EC2 running with Alloy container).

1. Create free account at grafana.com
2. Go to Connections → Add new connection → Grafana Alloy
3. Copy the Alloy config snippet (includes Loki + Prometheus + Tempo endpoints + API keys)
4. Update `alloy.config` in the repo with the staging credentials
5. Redeploy → verify logs/metrics appear in Grafana dashboards with `env=staging` label

---

## Checklist

- [ ] Step 0 — Client creates `bolo-dev` IAM user + shares console login
- [ ] Step 1 — IAM GHA user + EC2 role
- [ ] Step 2 — ECR repos
- [ ] Step 3 — Security groups
- [ ] Step 4 — RDS
- [ ] Step 5 — Secrets Manager + SSM params
- [ ] Step 6 — S3 bucket + CORS
- [ ] Step 7 — EC2 + Docker setup
- [ ] Step 8 — Cloudflare DNS + SSL
- [ ] Step 9 — GitHub Secrets
- [ ] Step 10 — First deploy + health check green
- [x] Step 11 — Grafana Cloud connected (done 2026-07-23, see staging-runbook.md)
