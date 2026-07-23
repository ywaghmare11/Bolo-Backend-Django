# BOLO Staging — AWS Setup Runbook

> Working log for the AWS staging environment setup. Updated after every step.
> Goal: anyone can replicate the full setup on a fresh AWS account using only this file.
> Region: **ap-south-1 (Mumbai)** for everything, no exceptions.

---

## Backend Handoff Checklist — status as of 2026-07-18

Compiled from the infra decisions made throughout this runbook. Kept current as items get picked up.

**Items 1–5 below committed 2026-07-18 on branch `chore/backend-handoff-ses-routing`** — `Bolo` (`70506e5`, docs only, still on the chore branch, not on `staging` — root repo has no deploy branch), `bolo-backend` (`1b141eb`, SES swap), `bolo-web` (`3fe44bd`, path-prefix routing). **`bolo-backend` and `bolo-web` are now also on `staging` (both local and `origin/staging` fast-forwarded to the same commit, confirmed 2026-07-18)** — the branch GHA's `workflow_dispatch` deploys from per `staging-setup.md` Step 10. So this work is positioned to actually go out whenever Step 10 is triggered, pending the still-open item 6 (GHA build-arg wiring) below.

### ✅ Done
- **S3 access pattern** — confirmed correct in the actual merged code (`bolo-backend` develop, `b05558c`, "Feature/voice evidence profile #36"): credentials via default AWS SDK provider chain (IAM role, no static keys), `S3_BUCKET`/`S3_PREFIX` resolution matches our SSM params exactly. No code change was needed — already matched the infra setup.
- **S3 CORS for local dev** — user added the local dev origin to the bucket's `AllowedOrigins` and confirmed evidence/voice/profile upload testing works locally.
- **`JWT_SECRET`, `SARVAM_API_KEY`, `OPENAI_API_KEY`, `NODE_ENV`, `PORT`** — same var names as local `.env`, already in Secrets Manager/SSM with real values, no code change expected.

### 🔲 Remaining backend backlog

1. **✅ Email — SMTP → SES (resolves W100) — done 2026-07-18.**
   - **Decision: AWS SDK (`@aws-sdk/client-ses`), not the SMTP interface** — IAM-role-only via the default provider chain, matches the S3 integration's pattern, no new secret to manage (`bolo-ec2-role` already has `AmazonSESFullAccess`).
   - `src/utils/email.ts` rewritten: all five send functions (`sendOtpEmail`, `sendInviteEmail`, `sendAiNudgeEscalationEmail`, `sendTaskReminderEmail`, `sendTaskDueDateEmail`) now go through a single shared `SESClient` + `SendEmailCommand` instead of per-call `nodemailer.createTransport()`. The pre-send RCPT-probe (`smtpRcptProbe`) is unchanged — it's a raw MX/port-25 handshake, unrelated to which transport actually sends the mail — except its `MAIL FROM` now uses `SES_FROM_EMAIL` instead of `SMTP_USER`.
   - Removed: `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` from `.env.example`, `docker-compose.yml`. Removed `nodemailer` + `@types/nodemailer` from `package.json`; added `@aws-sdk/client-ses`. `npm install` run, `tsc --noEmit` clean.
   - Added `SES_FROM_EMAIL` to `.env.example` (placeholder value — real staging value `bolosupport@aibigo.in` stays in SSM, not committed) and to `docker-compose.yml`'s backend service env block.

2. **✅ `DB_PASSWORD` grep check — done 2026-07-18, confirmed clean.** Grepped the full `bolo-backend` tree (code, not docs) for `DB_PASSWORD` — zero matches. Only references anywhere in the repo are in `docs/` (this runbook, `staging-setup.md`, `deployment.md`, `deployment-proposal-client.md`, `changelog.md`), all historical mentions of the already-resolved Secrets Manager dedup (Step 5 above). Confirmed: `DATABASE_URL` is the only DB credential env var actually read by the app.

3. **✅ `TZ` / `CORS_ORIGIN` runtime confirmation — done 2026-07-18.**
   - **`CORS_ORIGIN`: genuinely read at runtime.** `src/index.ts:35` — `const corsOrigin = process.env.CORS_ORIGIN || 'http://localhost:5173'`, passed into `cors({ origin: ... })`. Comma-split to support multiple origins. Correctly wired for the real staging value `https://staging-bolo.aibigo.in`.
   - **`TZ`: NOT read anywhere in the app.** `src/utils/date.ts` hardcodes `IST_OFFSET_MS = 5.5 * 60 * 60 * 1000` and does manual `Date` arithmetic (`nowIST()`, `toIST()`, `istLabel()`) instead of consulting `process.env.TZ` or any timezone library. Grepped for `dayjs`/`moment`/`Intl.DateTimeFormat`/`timeZone` usage — none found. The three background jobs (`otpCleanup`, `aiNudgeSweep`, `dueDateSweep`) use plain `setInterval`, not a TZ-aware scheduler like node-cron, so nothing else in the app consumes the var either.
   - **Verdict: functionally fine, not a real gap.** The hardcoded `+5:30` produces the same result `TZ=Asia/Kolkata` would, and IST has no DST to drift out of sync. But the env var itself is inert — SSM's `/bolo/staging/TZ` is a no-op today, not actually wired to anything. **Decision (2026-07-18): leave the code as-is, just document the gap here** — not worth the churn on a hardcoded-but-correct value this close to the 30 June-adjacent staging push. Worth revisiting if the app ever needs to run outside IST or the date logic gets consolidated into a real timezone library.

4. **✅ S3 prefix naming — cosmetic doc fix — done 2026-07-18.** `staging-setup.md` Step 6 corrected to say `staging/bolo-evidence/`, `staging/bolo-voice/`, `staging/bolo-profile-pics/` (matches `S3_EVIDENCE_BUCKET`/`S3_VOICE_BUCKET`/`S3_PROFILE_BUCKET` resolved through `resolveReal()` in `src/utils/s3.ts`), replacing the stale `staging/evidence/`/`staging/voice/` wording. No code change — code was already correct.

5. **✅ `/integrate18/varun/` path routing — decided + implemented 2026-07-18.**
   - **Decision: yes, the backend API sits under the same prefix as the frontend** — one origin, one path scope for both, matching the client's literal wording (`bolo.aibigo.in/integrate18/varun/`, a single URL, not two) and the health-check URL `staging-setup.md` Step 10 already assumed (`.../integrate18/varun/api/v1/health`).
   - **`bolo-backend` needs zero code changes.** Express keeps mounting routes at `/api/v1` exactly as it does today (`src/index.ts`) — `bolo-web`'s nginx container, the single front door on the EC2 instance, strips the `/integrate18/varun` prefix when reverse-proxying to `bolo-backend:3000` (Docker Compose service-name DNS). `api-spec.md`'s documented paths stay accurate with no routing footnote needed.
   - **`bolo-web/nginx.conf` rewritten:** `location /integrate18/varun/api/ { proxy_pass http://bolo-backend:3000/api/; ... }` (prefix stripped — nginx's standard trailing-slash-on-both-sides substitution); static SPA files served via `alias` under `/integrate18/varun/` with a regex location for hashed-asset cache headers and an exact-match no-cache override for `index.html`; bare-root and no-trailing-slash convenience redirects added.
   - **`/ws` (Sarvam STT WebSocket proxy) deliberately left unprefixed**, bare `/ws` at domain root — `src/hooks/useVoice.ts:117` connects to `${proto}://${location.host}/ws`, relative to the domain root rather than the page's own base path. Left as-is rather than touching voice-feature code as part of an infra routing decision; nginx proxies bare `/ws` → `bolo-backend:3000/ws` alongside the prefixed API location, no conflict.
   - **`bolo-web/vite.config.ts`:** `base` now reads `process.env.VITE_BASE_PATH`, defaulting to `/` — local `npm run dev` is unaffected, only the Docker build sets it. VitePWA's `start_url`/`scope` (previously hardcoded to `/`, which would have mismatched a non-root `base`) now derive from the same variable.
   - **`bolo-web/Dockerfile`:** added `ARG VITE_BASE_PATH=/`, alongside the existing `VITE_API_URL`/`VITE_AUTH_URL`/`VITE_USE_MOCKS` build args.
   - **Verified:** `npm run build` with `VITE_BASE_PATH=/integrate18/varun/` set — built `dist/index.html` correctly emits `/integrate18/varun/assets/...` for JS/CSS/manifest links, PWA build succeeds. Not verified end-to-end against a running nginx + backend (no docker-compose.yml or live EC2 deploy yet to test against) — recommend a smoke test at Step 10 once both containers are actually up.
   - **⚠️ Follow-up, not resolved here:** VitePWA's service-worker *scope* behavior under a non-root path hasn't been tested in a real browser (only the manifest values were mechanically corrected to match `base`). Service workers have stricter same-directory-or-below scope rules than a manifest field alone guarantees — verify PWA install/offline behavior actually works under `/integrate18/varun/` once there's a live deploy to test against, before relying on it.
   - **Implied value for item 6 below:** `VITE_API_URL=https://staging-bolo.aibigo.in/integrate18/varun` (no trailing slash — `apiServices.ts` appends call paths like `/api/v1/...` directly onto this). `VITE_AUTH_URL` not yet a distinct concern — same single backend, would point at the same value for now.

6. **✅ `VITE_API_URL`/`VITE_AUTH_URL` build-arg strategy — done 2026-07-19.** Built the entire remaining Step 10 pipeline, not just the build-args — turned out nothing existed yet (only the OpenShift `deploy.yml` workflows were present in either repo).

   **Where the files actually live (corrected 2026-07-19 — first pass wrongly put 3 of these under `docs/ops/`, a docs repo, instead of the app repos that actually deploy them):**

   `bolo-web` (branch `staging`, commit `5e5ea47`):
   - `nginx.staging.conf` — separate from `nginx.conf`. Adds a `listen 8443 ssl` server block using the Cloudflare origin certificate (`/etc/ssl/bolo/bolo-origin.crt`/`.key`) — **real gap found and fixed**: Cloudflare's SSL mode is Full (strict), which requires the origin to serve valid HTTPS, but `nginx.conf` was HTTP-only on 8080. Kept a duplicate plain-8080 block for container-internal healthchecks only (not published to the host).
   - `Dockerfile.staging` — separate from `Dockerfile`. Copies `nginx.staging.conf`, exposes 8080 + 8443.
   - `.github/workflows/deploy-aws.yml` — builds from `Dockerfile.staging` with the 4 `--build-arg`s baked in (`VITE_API_URL`/`VITE_AUTH_URL` = `https://staging-bolo.aibigo.in/integrate18/varun`, `VITE_USE_MOCKS=false`, `VITE_BASE_PATH=/integrate18/varun/` — Secrets Manager/SSM can't help here, Vite bakes these into the JS bundle at build time).

   `bolo-backend` (branch `staging`, commit `5790958`):
   - `Dockerfile.staging` — currently identical to `Dockerfile`, kept separate so it can diverge later without touching OpenShift's build (mirrors `bolo-web`'s split, added for consistency even though nothing in it actually needs to differ yet).
   - `docker-compose.staging.yml` — 3 services only (`bolo-backend`, `bolo-web`, `alloy` — no Prometheus/Loki/Jaeger, per `deployment.md`'s locked prod compose design). Hardcoded ECR registry + `LOG_LEVEL`/`OTEL_SERVICE_NAME`/`OTEL_EXPORTER_OTLP_ENDPOINT` (environment-invariant, not AWS-fetched, per the Step 5 decision). Healthchecks on both app containers. **Auto-synced to `/app/docker-compose.yml` on every deploy** (see below — no manual placement).
   - `observability/alloy-config-prod.alloy` — Grafana Cloud version of the existing dev `observability/alloy-config.alloy`, per `observability.md` §5's documented endpoint swaps. **Placeholder Grafana Cloud hostnames (`logs-prod-xxx` etc.)** — still need real values from Step 11's Connection Details page; `alloy` won't start cleanly until then. Auto-synced to `/app/observability/alloy-config-prod.alloy`.
   - `fetch-secrets.sh` — pulls the 4 Secrets Manager secrets + 8 SSM params, writes `/app/.env`. Commented-out lines ready for the 4 Grafana Cloud secrets once Step 11 creates them. Auto-synced + `chmod +x`'d on every deploy.
   - `.github/workflows/deploy-aws.yml` — see the full redesign below (item 3) for current behavior.

   **Both `deploy-aws.yml` files also committed to `develop`** (via `chore/add-aws-deploy-workflow` branches in both repos — user merged both), alongside (not replacing) each repo's existing OpenShift `deploy.yml`. Needed for GitHub's `workflow_dispatch` UI-visibility requirement (a workflow must exist on the default branch to show up in the Actions tab at all, even if you intend to actually dispatch it against a different branch — `staging` is where it's meant to run, since that's where `Dockerfile.staging`/`docker-compose.staging.yml`/etc. actually exist). **✅ Follow-up fix merged (2026-07-19)** for `bolo-backend` (`fix/deploy-aws-dockerfile-ref`): `develop`'s copy now also references `Dockerfile.staging`. **Note: `develop`'s copies now also lag behind the item 3 redesign below** (still the older single-tag-scheme version) — same reasoning as before, harmless since nobody dispatches against `develop` directly, but worth a sync PR at some point.

   **Deploy-automation + rollback plan, implemented 2026-07-19** — user correctly pushed back on manual EC2 file placement (drift-prone, contradicts this pipeline's "no manual server surgery" design), which led to a full re-check that also surfaced a real missing piece:
   1. **✅ S3-sync automation, fully done (2026-07-19).** `bolo-backend`'s workflow uploads the 3 files to `s3://bolo-staging/deploy-config/` on every deploy run (not rollback — nothing new to upload). Both repos' SSM commands sync `s3://bolo-staging/deploy-config/ → /app/` before anything else — works for the very first deploy too. **IAM added:** scoped inline policy `bolo-gha-deploy-config-upload` on `bolo-gha` — `s3:PutObject` on `arn:aws:s3:::bolo-staging/deploy-config/*` only. `bolo-ec2-role` already had `AmazonS3FullAccess` for the download/sync side, no change needed there.
   2. **✅ ECR login on EC2** *(real gap caught 2026-07-19, was missing entirely)* — added `aws ecr get-login-password | docker login` to both SSM commands, before `docker compose pull`. Without this the first real deploy would have failed on a pull auth error — `bolo-ec2-role`'s IAM permission alone isn't enough, Docker needs an explicit login with a fresh token (ECR tokens expire every 12h).
   3. **✅ Redesigned 2026-07-19 (second pass, per user request) — explicit `action` input, single tag scheme, no-rebuild rollback.** Both `deploy-aws.yml` workflows now take two `workflow_dispatch` inputs: **`action`** (`deploy` or `rollback` — explicit choice dropdown, replacing the old "select a tag vs branch" implicit trick) and **`rollback_version`** (optional, e.g. `v1.2.3` — only used when `action: rollback`; if left empty, rolls back to the version immediately before the current one).
      - **`action: deploy`** — computes the next semver patch version (`v1.2.3` → `v1.2.4`, or `v0.1.0` if none exist) *before* building, uses it as the **only** Docker tag (dropped `:latest`/`:<commit-sha>` entirely — single consistent tag scheme now, per explicit request), builds, pushes, deploys via SSM (exporting `BACKEND_IMAGE_TAG`/`WEB_IMAGE_TAG` — see below), then **only after the SSM deploy confirms success**, creates and pushes the git tag. (Deliberate ordering: the version *string* is computed and used as the Docker tag before the build, but the actual git tag ref isn't pushed until the deploy is confirmed working — avoids a git tag existing for a build that never went live.) `bolo-backend`/`bolo-web` version independently — unrelated `v*` sequences, two separate artifacts.
      - **`action: rollback`** — **skips the build entirely.** Resolves the target version (either `rollback_version` if given, or the second-most-recent `v*` tag), then deploys that image via SSM — `docker compose pull`/`up -d`, no rebuild, no new tag created. This only works if that version's image still exists in ECR (see item 4 below — the ECR lifecycle exemption is what keeps old versions pullable).
      - **Real fix this surfaced:** `docker-compose.staging.yml`'s single shared `IMAGE_TAG` variable was a genuine bug once rollback started explicitly pinning a specific version — rolling back `bolo-backend` would have also repointed `bolo-web` at a meaningless tag (or vice versa), since they share unrelated version sequences. Split into **`BACKEND_IMAGE_TAG`** and **`WEB_IMAGE_TAG`**, each service reads only its own.
      - **SSM commands now scoped per-service** (`docker compose pull bolo-backend alloy && up -d bolo-backend alloy` for the backend workflow, `docker compose pull bolo-web && up -d bolo-web` for the web workflow) — not the whole compose file — so deploying/rolling back one service never touches the other's container. `bolo-backend`'s run also brings up `alloy` (untagged, not part of either app's release cycle) since that workflow owns the shared config sync.
      - Branch-based deploys (selecting `staging`, `action: deploy`) remain the everyday/primary mechanism — nothing about this changes that. Rollback is additive, occasional.
   5. **✅ Docs corrected** — `deployment.md`'s rollback bullet and full "Rollback procedure" section now describe this real mechanism instead of the original vague "change tag in docker-compose.yml on EC2" note.

   **✅ Item 4 resolved (2026-07-19) — no ECR change needed for staging.** Considered raising retention beyond the original Step 2 "keep last 4" (since `action: rollback` now depends on the target version's image still existing in ECR, no rebuild fallback) — **decided against it.** Staging is disposable, actively-changing state, not something needing weeks of rollback history the way a real production system would; "how many to keep" is a PROD-specific decision to revisit when that environment gets built. Leaving the original Step 2 policy exactly as-is. **Known, accepted consequence:** `action: rollback` in staging can only reach back 4 deploys — a version older than that has no image left to redeploy and no rebuild fallback in this design. Acceptable tradeoff for staging's actual use.

   **✅ IAM done (2026-07-19).** Only item 4 (ECR lifecycle policy, above) remains before a first real `action: deploy` attempt is likely to succeed end-to-end.

   **⚠️ Also still open:** Grafana Cloud placeholder endpoints in `alloy-config-prod.alloy` (Step 11 not done) — the `alloy` container will fail to start until real values + the 4 secrets exist. Won't block `bolo-backend`/`bolo-web` from deploying successfully (compose brings up all 3 independently), but `docker compose ps` won't show all-green until Step 11 is finished.

   **✅ First `bolo-backend` deploy succeeded (2026-07-19), verified end-to-end.** GHA completed, files landed via S3 sync, and manually confirmed on EC2:
   - `docker compose ps`: `bolo-backend` → `Up (healthy)`, running `929123273547.dkr.ecr.ap-south-1.amazonaws.com/bolo-backend:v0.1.0` — auto-tagging confirmed working correctly, first deploy correctly tagged `v0.1.0`
   - Health check (from inside the container): `{"success":true,"message":"OK","data":{"status":"ok","version":"1.0.0",...}}` — confirms Prisma migration ran, RDS connection works, app serving requests correctly
   - `alloy`: `Restarting (1)` — expected, not a new problem (Grafana Cloud placeholders, Step 11 not done)

   **Whole pipeline validated in one shot:** S3 config sync, ECR auth on EC2, `fetch-secrets.sh`, `docker compose` scoped to `bolo-backend`+`alloy`, healthcheck, and auto-tagging all worked correctly on the very first real attempt.
   **⚠️ Real gotcha found during manual verification — always `sudo` for interactive troubleshooting.** `docker compose ps` failed with `open /app/.env: permission denied` when run from a manually-opened SSM session. Root cause: the automated deploy runs as **`root`** (via `aws ssm send-command`), so `fetch-secrets.sh`'s `chmod 600` locks `/app/.env` to root-only. An interactive SSM Session Manager session runs as **`ssm-user`** instead — a different, less-privileged user that can't read a root-owned `600` file (also not in the `docker` group — only `ec2-user` was added to that in Step 7). **Fix: prefix every command with `sudo`** during manual troubleshooting — `sudo docker compose ps`, `sudo docker compose logs <service>`, `sudo docker compose exec <service> ...`. Not a bug to fix, just a gotcha to remember.

   **✅ Compose file split, bolo-web out of the shared file (2026-07-19).** While debugging why a manual `docker compose pull bolo-web` grabbed `:latest` instead of the real tag (env-var scoping issue, unrelated), a real structural gap surfaced: `bolo-web`'s workflow could only ever *download* `docker-compose.staging.yml` from S3 — only `bolo-backend`'s workflow had the upload step, since the file physically lived in `bolo-backend`'s repo. First patched with an explicit failure message if the file was missing; then, on request, fixed at the root — **user's call, driver was independent blast radius** (a bad edit/deploy on one side should never be able to reach the other's containers or network, not just "usually doesn't"):
   - `docker-compose.staging.yml` split into two files: `bolo-backend`'s (now `bolo-backend` + `alloy` only, unchanged filename) and a new one in `bolo-web`'s own repo (`bolo-web` service only).
   - S3 keys renamed accordingly — `docker-compose.backend.yml` and `docker-compose.web.yml` (the old `docker-compose.yml` key is now orphaned in S3, harmless but nothing references it anymore; fine to delete on a future cleanup pass).
   - `bolo-web`'s workflow gained its own "Sync deploy config to S3" step (mirrors `bolo-backend`'s) — it's now fully self-sufficient, no cross-repo deploy-order dependency at all (the earlier explicit-failure guard was removed, no longer needed).
   - Every `docker compose` call on the host now passes explicit `-f <file> -p <project-name>` (`bolo-backend`/`bolo-web`) — required since neither file uses the Compose-default filename anymore, and the project-name pin guarantees the two stacks can never share Compose's own bookkeeping (networks, labels) even if both ever ran from the same `/app` working directory.
   - **Known, accepted tradeoff:** `bolo-web`'s new standalone file drops the `depends_on: bolo-backend` ordering that Compose provided for free in the shared file. Accepted for now — `bolo-web` is a static SPA with `VITE_API_URL` baked in as a public HTTPS URL at build time, not an internal Docker network hostname, so it doesn't actually need `bolo-backend` up first to start serving. **Flagged to revisit** if this ever causes a real startup-ordering issue (e.g. add a healthcheck-retry loop to `bolo-web`'s own file).
   - `alloy` stays bundled with `bolo-backend`'s file, not split out further — it isn't part of either app's release cycle, and `bolo-backend`'s workflow already owns the shared secrets/observability config sync.
   - Recorded in `tech-playbook/decisions/cloud.md` (Group 1/Group 4) and `docs/ops/deployment.md` Group 4.

   **✅ Migration cleanup + first split deploy verified (2026-07-19).** Before the first deploy under the new split, manually cleaned up the pre-split state on EC2 (required, one-time only — not part of the ongoing workflow): deleted the orphaned `s3://bolo-staging/deploy-config/docker-compose.yml` object and its `/app/docker-compose.yml` copy (stale, unreferenced by either new `-f` flag, but a footgun for anyone running a bare `docker compose` command later — Compose would've silently fallen back to it), and `sudo docker rm -f bolo-backend alloy` on EC2 (the containers from before the split were tracked under Compose's old default project name, derived from cwd — the new `-p bolo-backend` project wouldn't recognize them as its own, and the fixed `container_name:` values would have collided as create-time conflicts). First `bolo-backend` deploy after cleanup succeeded cleanly: `bolo-backend:v0.1.1` → `Up (healthy)`, `alloy` up, health check returns `{"success":true,"status":"ok",...}`. **`bolo-web`'s first deploy under its own split file also succeeded** — no cleanup needed on that side (it had never gotten past the pull step before, so no orphaned container to collide with). Both apps confirmed running via `docker compose ps` — but that turned out to be premature, see the very next entry.

   **🔴 Real regression found immediately after, via the first actual public URL test (2026-07-19).** `docker compose ps` showing both containers up was never actually verified against the live site until now — `curl https://staging-bolo.aibigo.in/integrate18/varun/api/v1/health` returned Cloudflare `521` (origin unreachable). Root cause: `bolo-web`'s container was crash-looping (`Restarting (1)`) — `docker compose -f docker-compose.web.yml -p bolo-web logs bolo-web` showed `nginx: [emerg] host not found in upstream "bolo-backend"`. `nginx.staging.conf`'s `proxy_pass http://bolo-backend:3000/...` (`/api/`, `/ws`) is a static, non-variable upstream reference — nginx resolves it once at startup, and failure to resolve doesn't just disable that route, it crashes the entire nginx process. **This invalidates the split's original "no network dependency" reasoning** (both `docs/ops/deployment.md` and this file previously claimed `bolo-web` didn't need `bolo-backend` reachable internally, based on `VITE_API_URL` being a public URL baked at build time — true for the browser's own requests, but wrong for nginx's server-side reverse-proxying of those same public paths back to `bolo-backend:3000`). Splitting into separate Compose projects gave each its own default network, breaking that DNS resolution.
   - **Fix:** both compose files now join one shared **external** Docker network, `bolo-net`, instead of each project's own implicit default network. Created once, out-of-band: `sudo docker network create bolo-net` — must exist before either file's `up` runs (`external: true` in Compose means "expect this to exist," not "create it").
   - Container *lifecycle* (pull/up/down, per-project isolation) stays exactly as designed in the original split — only the network is deliberately shared back.
   - **No true startup-ordering guarantee restored** — `depends_on` can't cross a Compose project boundary (`bolo-backend` isn't defined in `bolo-web`'s file). `restart: unless-stopped` covers it in practice: if `bolo-web` ever starts before `bolo-backend`'s container exists on `bolo-net`, nginx crash-loops and Docker keeps retrying until the hostname resolves, then stabilizes. A self-heal, not a real guarantee — flagged to revisit if it's ever too slow/flaky in practice.
   - **Redeploy sequence required:** create `bolo-net` on EC2 → redeploy `bolo-backend` (picks up its new `networks:` block, joins `bolo-net`) → redeploy `bolo-web` (same) → re-verify the public URL + `/api/v1/health` through Cloudflare, not just `docker compose ps`.
   - `docs/ops/deployment.md` Group 4 updated to match.

   **✅ `bolo-net` fix confirmed (2026-07-19) — but redeploying `bolo-web` surfaced a second, unrelated bug: cert key permissions.** After `sudo docker network create bolo-net` + redeploying `bolo-backend` then `bolo-web`, the `host not found in upstream` error was gone (network fix worked), but `bolo-web` was still crash-looping — `nginx: [emerg] cannot load certificate key "/etc/ssl/bolo/bolo-origin.key": ... Permission denied`. Root cause: `Dockerfile.staging` uses `nginxinc/nginx-unprivileged:alpine`, which deliberately runs nginx as **UID 101**, not root (`bolo-web`'s own Dockerfile comment: "same restricted-privilege pattern as the OpenShift Dockerfile"). `bolo-origin.key` on the host was `rw------- root root` (600, from Step 8) — root-only, unreadable by UID 101. Genuinely pre-existing, unrelated to today's compose work — Step 8 placed the cert back on 2026-07-17, but nothing had ever actually exercised nginx booting with it until `bolo-web` got this far for the first time today (every earlier attempt crashed before reaching cert load: first the ECR pull, then the `bolo-backend` DNS issue).
   - **Fix (host-side only, no code/compose change):** `sudo chown root:101 /etc/ssl/bolo/bolo-origin.key && sudo chmod 640 /etc/ssl/bolo/bolo-origin.key` — scoped to GID 101 (`nginx-unprivileged`'s own group) rather than world-readable (`644`), keeping the private key readable only by root and that specific service user. `restart: unless-stopped` picked it up on the next auto-restart, no redeploy needed.
   - **Fully verified end-to-end after this fix** — not just `docker compose ps`, the actual public paths through Cloudflare: `curl https://staging-bolo.aibigo.in/integrate18/varun/` → `200 OK`; `curl https://staging-bolo.aibigo.in/integrate18/varun/api/v1/health` → `200 OK`, real response from `bolo-backend` through nginx's proxy (`{"success":true,"status":"ok",...}`). Both apps, the network split, and the compose-project isolation are all confirmed working together on live infra.
   - **Lesson for this whole saga:** `docker compose ps` / container "healthy" status is not sufficient evidence of a working deploy for `bolo-web` specifically, since its healthcheck only hits the internal static-file path (`:8080`), never the SSL listener (`:8443`) or the `bolo-backend` proxy path that real users actually hit. Every verification from here on should include the public-URL curl checks, not just container status.
   - **Made durable (2026-07-19):** the manual `chown`/`chmod` above fixed *this* instance, but nothing enforced it — a future cert rotation or EC2 rebuild would silently reintroduce the exact same crash, since Step 8's cert placement has no reason to know about `bolo-web`'s specific UID-101 requirement. Added the same `chown root:101` + `chmod 640` as an idempotent step directly in `bolo-web`'s SSM command (runs on every deploy) — harmless if already correct, self-heals if a future re-placement gets it wrong again.

   **Consolidated issue log for the whole "split → verify → fix" arc (2026-07-19), for anyone skimming instead of reading the full narrative above:**
   1. **Structural gap:** `bolo-web`'s deploy workflow could only ever download the shared compose file from S3, never push its own changes; depended on `bolo-backend` deploying first. → Split into two independently-owned compose files, one per repo.
   2. **Container-name collision (migration-only, one-time):** pre-split containers were tracked under Compose's old default project name; the new `-p bolo-backend`/`-p bolo-web` projects didn't recognize them, and the fixed `container_name:` values would have collided on create. → Manually cleaned up once (`docker rm -f`) before the first post-split deploy; not a recurring concern.
   3. **Orphaned S3/EC2 file:** the old `docker-compose.yml` key/file was never deleted by the rename (`aws s3 sync` doesn't remove stale files) — a footgun for any future bare `docker compose` command. → Manually deleted from both S3 and EC2.
   4. **Network regression (real bug, self-introduced by the split):** separate Compose projects meant separate default networks; `bolo-web`'s nginx does a static `proxy_pass http://bolo-backend:3000/...`, which nginx resolves once at startup — failure crashes the whole process, not just that route. Surfaced as a live Cloudflare `521`. → Both files now join one shared external network, `bolo-net`.
   5. **Cert key permissions (real bug, pre-existing, unrelated to the split):** `bolo-origin.key` was root-only `600` from Step 8; `bolo-web` runs nginx as UID 101 (`nginx-unprivileged`), can't read it. Never surfaced before because `bolo-web` never survived long enough to reach cert loading until this session's fixes cleared everything before it. → `chown root:101` + `chmod 640`, now automated as a self-healing step in the SSM command (this entry).
   6. **Manual `docker compose` commands need explicit flags now:** neither split file uses Compose's default filename anymore, so bare `docker compose ps`/`logs`/`exec` fail with "no configuration file provided" — need `-f docker-compose.<backend|web>.yml -p bolo-<backend|web>` on every manual command going forward.
   - End state: both apps deployed, both verified against the real public URL through Cloudflare (not just container status), both structural gaps (#1) and both real bugs (#4, #5) fixed at the root and made durable, not just patched around for one deploy.

   **⚠️ New gotcha from the split — bare `docker compose` commands no longer work for manual troubleshooting.** `sudo docker compose ps` (no flags) now fails with `no configuration file provided: not found` — expected, not a bug. Before the split, the shared file used Compose's default name (`docker-compose.yml`), so a bare command found it automatically. Now that both files are explicitly renamed (`docker-compose.backend.yml` / `docker-compose.web.yml`) and neither is the default name, every manual command needs the same `-f`/`-p` flags the GHA workflow uses:
   ```
   sudo docker compose -f docker-compose.backend.yml -p bolo-backend ps
   sudo docker compose -f docker-compose.backend.yml -p bolo-backend logs bolo-backend
   sudo docker compose -f docker-compose.backend.yml -p bolo-backend exec bolo-backend wget -qO- http://localhost:3000/api/v1/health
   ```
   (swap `backend`→`web` for `bolo-web`). Plain `sudo docker ps` / `sudo docker exec <container> ...` (no `compose`) still work unflagged, since those operate on containers directly rather than through a compose file.

---
> Source of truth for the plan: `docs/ops/staging-setup.md` + `docs/ops/deployment.md`.

---

## Progress Summary (as of 2026-07-18)

| Step | Status |
|---|---|
| 0 — Client grants AWS console access | ✅ Done |
| 1 — IAM (`bolo-gha` user + `bolo-ec2-role`) | ✅ Done |
| 2 — ECR (`bolo-backend`, `bolo-web` repos) | ✅ Done |
| 3 — Security Groups (`bolo-ec2-sg`, `bolo-rds-sg`) | ✅ Done |
| 4 — RDS PostgreSQL (`bolo-staging`) | ✅ Done — restarted after the 2026-07-16 overnight stop |
| 5 — Secrets Manager + SSM | ✅ Done |
| 6 — S3 (`bolo-staging` bucket) | ✅ Done — CORS covers staging + OpenShift dev + local dev origins |
| 7 — EC2 (`bolo-staging` instance, Docker bootstrapped) | ✅ Done — Elastic IP `13.232.26.36`, restarted after the overnight stop |
| 8 — Cloudflare (DNS + SSL) | ✅ Done (2026-07-17) |
| 9 — GitHub Secrets | ✅ Done — both repos |
| **Backend Handoff** (app-layer, not AWS console work) | ✅ Done (2026-07-18) — SMTP→SES swap, path-prefix routing, `TZ`/`CORS_ORIGIN`/`DB_PASSWORD` checks, S3 prefix doc fix. See checklist at top of this file. Code on `staging` branch, both `bolo-backend` (`1b141eb`) and `bolo-web` (`3fe44bd`) — this is what actually matters for Step 10, since GHA's `workflow_dispatch` deploys from whichever branch is picked directly (same pattern as the OpenShift pipeline), not from `main`. Docs-only commits on `Bolo` sit on `chore/backend-handoff-ses-routing`, **not blocking** — planned to merge to `main` within the week, unrelated to deploy readiness. |
| 10 — First deploy | ✅ Done (2026-07-19) — both `bolo-backend` and `bolo-web` deployed and verified end-to-end against the real public URL (not just `docker compose ps`): `https://staging-bolo.aibigo.in/integrate18/varun/` → `200`, `/api/v1/health` (proxied through nginx to `bolo-backend`) → `200`. Took a same-day compose-file split + two follow-up fixes (shared `bolo-net` network, cert key permissions) to get here — full narrative above. `alloy` still restarting (Step 11 placeholders), doesn't block either app. |
| 11 — Grafana Cloud | 🟡 Account created, OTP done — full setup still needs Step 10 (EC2 running the app + Alloy container) to actually connect anything |

**✅ SES production access granted (2026-07-19).** Request submitted and approved same-day (Transactional mail type, `bolosupport@aibigo.in` as additional contact) — found via a real `502` on the platform-admin OTP endpoint during Step 10 verification: `bolo-backend` logs showed `Email address is not verified. The following identities failed the check in region AP-SOUTH-1` for a test recipient (`sarangjadhav661@gmail.com`), confirming the account was still sandboxed even though the sender domain/DKIM had been verified since Step 8. Sandbox mode requires every individual recipient to be pre-verified in the SES console — completely unworkable for real users. Now resolved: any recipient can receive OTP/reminder emails without pre-verification. This also explains a subtlety worth remembering — Cloudflare substitutes its own generic error page for 5xx responses by default, so a `502` through the public URL doesn't always mean "origin unreachable"; here it was the app's own deliberate `EmailDeliveryFailedError` response, visible only by checking the actual backend logs.

**Open items (not blocking Step 10, but need answers eventually):**
- PWA service-worker scope under `/integrate18/varun/` — mechanically correct, not yet verified in a real browser against a live deploy
- PROD-only items flagged along the way: OIDC federation for `bolo-gha` (vs static keys), ECR tag immutability + scan-on-push, RDS deletion protection

---

### Step 0 — Client grants dev team AWS console access
**Status:** Done
**Date:** 2026-07-15
**What was done:** Client created IAM user `bolo-dev` (account ID `929123273547`) with 7 AWS managed policies attached (see below) and shared temporary console credentials. Dev team logged in and completed the forced password reset.
**Values to save:**
- AWS Account ID: `929123273547`
- Console login URL: `https://929123273547.signin.aws.amazon.com/console`
- IAM user: `bolo-dev`
- Attached policies: `IAMFullAccess`, `AmazonEC2FullAccess`, `AmazonRDSFullAccess`, `AmazonS3FullAccess`, `AmazonEC2ContainerRegistryFullAccess`, `AmazonSSMFullAccess`, `AWSSecretsManagerFullAccess`
**Errors encountered:** First login triggered forced password reset; initial reset attempt was rejected by AWS with "You may not be authorized to perform this action, or the new password does not comply with the account password policy set by your administrator."
**Fix applied:** Root cause was the new password not meeting the account's password complexity policy (not a permissions issue — `bolo-dev` has `IAMFullAccess`). A stronger password on retry succeeded.
**GitHub notes:** None yet.
**Notes:** `bolo-dev`'s policy set is broader than what `staging-setup.md` Step 0 suggests as a minimum, but it covers every service Steps 1–7 touch (IAM, EC2, RDS, S3, ECR, SSM, Secrets Manager) — no gaps expected for the rest of this setup.

---

### Step 1 — IAM
**Status:** Done
**Date:** 2026-07-15
**What was done:** 1A — created IAM user `bolo-gha` (programmatic access only, no console login), attached `AmazonEC2ContainerRegistryFullAccess` + `AmazonSSMFullAccess`, generated access key (use case: Third-party service). 1B — created IAM role `bolo-ec2-role` (trusted entity: EC2), attached `AmazonSSMManagedInstanceCore` + `AmazonS3FullAccess` + `AmazonEC2ContainerRegistryReadOnly` + `SecretsManagerReadWrite`.

Earlier blocker (for reference): Attempted 1A first, before the fix — console denied `iam:ListPolicies` when trying to attach a policy, then denied `iam:ListUsers` on the IAM Users list page itself. Error context both times: "no identity-based policy allows the action" — i.e. no attached policy grants any `iam:*` read/write action at all, not an explicit Deny override.
**Values to save:** `bolo-gha` Access Key ID + Secret Access Key generated — **intentionally not recorded in this file** (secret credential; don't paste into chat or plaintext docs even though `docs/` is gitignored). Keep it in a password manager — needed again only once, for Step 9 (GitHub Secrets). `bolo-ec2-role` created — role ARN visible in IAM → Roles if needed later, no secret involved (roles use temporary credentials automatically, nothing to store).
**Isolation test:** EC2 and S3 console dashboards load fine for `bolo-dev` — confirms 6 of the 7 stated managed policies (`AmazonEC2FullAccess`, `AmazonRDSFullAccess`, `AmazonS3FullAccess`, `AmazonEC2ContainerRegistryFullAccess`, `AmazonSSMFullAccess`, `AWSSecretsManagerFullAccess`) are genuinely attached and working. **`IAMFullAccess` alone is the odd one out — not functioning despite being reported as attached.**
**Errors encountered:** `Access denied to iam:ListPolicies` (Create user → Set permissions step) and `Access denied to iam:ListUsers` (IAM → Users list page), both for `arn:aws:iam::929123273547:user/bolo-dev`.
**Fix applied:** Client re-attached/fixed `IAMFullAccess` on `bolo-dev` — confirmed access restored 2026-07-15, faster than the ~2hr ETA given. Root cause on client's side not confirmed in detail (likely the attach-didn't-save theory), but resolved.
**⚠️ PROD open item (not yet decided):** `bolo-gha` access key creation triggered AWS's own recommendation to use OIDC federation (GitHub Actions assumes an IAM role directly, no static long-lived keys) instead of static access keys. Going with static keys for staging per `staging-setup.md` — simpler, matches deadline. Worth revisiting for prod: eliminates key leakage/rotation risk entirely. Not implemented, just flagged.
**GitHub notes:** None yet.
**Notes:** Step 1 (create `bolo-gha` IAM user + `bolo-ec2-role`) cannot proceed until `IAMFullAccess` is confirmed working on `bolo-dev`. All other steps that don't touch IAM (Step 2 ECR, Step 3 SGs, Step 4 RDS, Step 6 S3) are technically unblocked and could be done out of order if needed to make progress while this is resolved — but Steps 7 and 9 need Step 1's outputs (`bolo-ec2-role`, `bolo-gha` keys), so IAM will need fixing before the full path completes.

**Decision:** Client fix ETA ~2 hours. Rather than wait, reordering to do Step 2 (ECR) → Step 3 (Security Groups) → Step 4 (RDS) now — none of these need IAM, only the policies already confirmed working (`AmazonEC2ContainerRegistryFullAccess`, EC2/VPC access, RDS access). Will return to Step 1 as soon as the client confirms the fix, then resume the documented order (Step 5 onward needs Step 1 + Step 4 done).

---

### Step 2 — ECR
**Status:** Done
**Date:** 2026-07-15
**What was done:** Created `bolo-backend` and `bolo-web` private repos in ap-south-1. Staging settings used: tag immutability = mutable (default), encryption = AES-256 (default), image scanning = off/default (deprecated setting, left as-is). Lifecycle policy added to both repos — 2 rules each: (1) priority 1, tagged/wildcard `*`, expire when image count > 4; (2) priority 2, untagged, expire after 1 day since image created.
**⚠️ PROD open item (not yet decided, no doc backs this):** recommend flipping **tag immutability ON** and **scan-on-push ON** for the production ECR repos specifically — neither is needed for staging. Reasoning: (1) the client-approved rollback promise in `deployment-proposal-client.md` ("revert to any of last 4 versions within ~60 seconds") only holds if tags can't be silently overwritten — mutable tags break that guarantee; (2) scan-on-push is free and catches known CVEs before an image reaches EC2. Needs a real decision (not just this note) before PROD ECR repos are created — add to `deployment.md` Group 4 (CI/CD) once confirmed.
**Values to save:** Registry URL: `929123273547.dkr.ecr.ap-south-1.amazonaws.com` (repos: `.../bolo-backend`, `.../bolo-web`)
**Errors encountered:** None.
**Fix applied:** N/A.
**GitHub notes:** None yet.
**Notes:** Confirms `bolo-dev`'s ECR access (`AmazonEC2ContainerRegistryFullAccess`) works — consistent with the EC2/S3 isolation test from Step 1.

---

### Step 3 — Security Groups
**Status:** Done
**Date:** 2026-07-15
**What was done:** Created `bolo-ec2-sg` (inbound 80/443 from `0.0.0.0/0`, no port 22) and `bolo-rds-sg` (inbound 5432 from `bolo-ec2-sg` only) in the default VPC.
**✅ Done (2026-07-17).** Removed the two `0.0.0.0/0` rules on 80/443, replaced with ~30 rules (one per Cloudflare IPv4 CIDR range × 2 ports) pulled live from cloudflare.com/ips. Only Cloudflare's network can now reach `bolo-staging` directly on 80/443.
**Notes:** `0.0.0.0/0` on 80/443 is intentional, not a gap — public web traffic needs to reach these ports from anywhere. Real hardening is SSH being fully closed (no rule at all, SSM used instead) and RDS only reachable from `bolo-ec2-sg`, never the internet.

---

### Step 4 — RDS PostgreSQL
**Status:** Done
**Date:** 2026-07-15
**What was done:** Created `bolo-staging` RDS instance — PostgreSQL 18.3 engine (Full configuration, Dev/Test template, Single-AZ DB instance deployment), master username `bolo`, initial DB name `bolo`, storage gp3/20GiB, VPC SG `bolo-rds-sg` only, public access No.
**Errors encountered:** Instance class came out as `db.t3.micro` (2 vCPU/1GB RAM) instead of the planned `db.t3.small` (2 vCPU/2GB RAM) — Dev/Test template likely auto-suggested its free-tier-friendly default and it wasn't overridden during creation.
**Fix applied:** Fixed via Modify → Instance configuration → `db.t3.small` → Apply immediately. Confirmed post-fix: Status Available, Class db.t3.small (2 vCPU/2GB RAM).
**Values to save:** ARN: `arn:aws:rds:ap-south-1:929123273547:db:bolo-staging` · Resource ID: `db-CVJKGMFWKLSVXNJ3AKUNBXRPUA` · Endpoint: `bolo-staging.ctg0o6kueqo2.ap-south-1.rds.amazonaws.com` · Port: `5432` · DB name: `bolo` · Master username: `bolo`. Master password: generated and saved by user outside this file (not recorded here — secret credential). Full connection string for Step 5: `postgresql://bolo:<password>@bolo-staging.ctg0o6kueqo2.ap-south-1.rds.amazonaws.com:5432/bolo`
**GitHub notes:** None yet.
**Notes:** Deletion protection is Disabled (fine for staging, reconsider for prod). IAM DB authentication not enabled — using password auth as planned, matches `staging-setup.md`.
**⚠️ 2026-07-16 end of day — stopped temporarily.** No snapshot taken (not needed, data isn't at risk from a temporary stop). AWS auto-restarts it 2026-07-23 if not manually restarted first. Endpoint hostname stays identical after restart — no reconfiguration needed next session. **Action needed next session:** RDS → Actions → Start, before resuming any work that touches the database.

---

### Step 5 — Secrets Manager + SSM Parameter Store
**Status:** Done
**Date:** 2026-07-15
**What was done:** Attempted to create `bolo/staging/DB_PASSWORD` via Secrets Manager → Other type of secret → Plaintext.
**Errors encountered:** `Failed to create secret. User: arn:aws:iam::929123273547:user/bolo-dev is not authorized to perform: secretsmanager:CreateSecret on resource: bolo/staging/DB_PASSWORD because no identity-based policy allows the secretsmanager:CreateSecret action.` Same failure signature as the Step 1 IAM blocker — `AWSSecretsManagerFullAccess` is reported attached but not actually functioning.
**Fix applied:** Root cause found — checked `bolo-dev`'s actual Permissions policies list (9 total) and the client had attached **`AWSSecretsManagerClientReadOnlyAccess`** (read-only: GetSecretValue/DescribeSecret/ListSecrets), not `AWSSecretsManagerFullAccess` as reported — a similarly-named but far more limited policy, genuinely a wrong-policy-picked mistake, not a "didn't save" issue like the Step 1 theory assumed. Since `IAMFullAccess` is now confirmed attached (fixed from Step 1's blocker), `bolo-dev` self-remediated: added `AWSSecretsManagerFullAccess` directly via IAM → Users → bolo-dev → Add permissions, no client round-trip needed this time.
**Notes:** Full list of `bolo-dev`'s actual attached policies as of this check: `AmazonEC2ContainerRegistryFullAccess`, `AmazonEC2FullAccess`, `AmazonRDSFullAccess`, `AmazonS3FullAccess`, `AmazonSSMFullAccess`, `AWSSecretsManagerClientReadOnlyAccess` (now supplemented with `SecretsManagerReadWrite` — note: `AWSSecretsManagerFullAccess` is not a real AWS managed policy name, corrected mid-session), `ec2write` (customer inline, purpose not yet investigated), `IAMFullAccess`, `IAMUserChangePassword` — 9 total, more than the 7 originally reported. **Key learning:** now that `bolo-dev` has working `IAMFullAccess`, future policy gaps can likely be self-fixed here instead of needing another client round-trip — check this list first before messaging the client again.
**Doc gap found + fixed:** `staging-setup.md`'s Step 5 Secrets Manager table was missing `bolo/staging/OPENAI_API_KEY`, even though `deployment.md` (line ~333) explicitly lists `OPENAI_API_KEY` as one of the env vars `docker-compose.yml`'s backend service expects via `${VAR}` interpolation. Added the missing row to `staging-setup.md`. 4th secret created: `bolo/staging/OPENAI_API_KEY` (value from OpenAI dashboard, available from session start).

**✅ RESOLVED (2026-07-16) — W100 closed.** Asked the client directly which provider; answer: "SES is approved." Updated `CLAUDE.md`, `deployment.md`, `staging-setup.md`, `open-questions-web-v1.md` to consistently say AWS SES (matches what `prd.md`/`security.md`/`api-spec.md`/`sprint-plan-4w.md` said all along — confirms it was doc drift, not a real open design question). No more Gmail SMTP anywhere in the docs.
**Still blocked, same underlying pending item as before:** SES needs a verified domain or sender identity before it can send anything — same pending-client-domain blocker that was already holding up Cloudflare (Step 8) and CORS (Step 6). Not a new blocker, just now correctly SES-shaped instead of ambiguous.
**`/bolo/staging/CORS_ORIGIN` created (2026-07-17)** — String, `https://staging-bolo.aibigo.in`.
**Domain-level SES verification started (2026-07-17)** — created domain identity for `aibigo.in` (Easy DKIM, RSA_2048_BIT). Added all 3 DKIM CNAME records to Cloudflare DNS (DNS only, not proxied) — confirmed correct in console. Waiting on SES to auto-detect (usually minutes with Cloudflare, AWS states up to 72h max).
**✅ Verified (2026-07-17, same session) — fast, thanks to Cloudflare's quick DNS propagation.** SES domain identity status: Verified. DKIM configuration: Successful. Unblocks the production access request — retry it now.
**Infra action needed:** grant `bolo-ec2-role` (Step 1) the `ses:SendEmail` + `ses:SendRawEmail` permissions — no-regret action regardless of which transport mechanism the backend ends up using.
**Open sub-item (not blocking, for the backend dev building the email code):** AWS SDK (IAM-role-only, no secrets, matches how this project accesses S3/ECR) vs. SES's SMTP interface (keeps `nodemailer`, needs separately-generated SES SMTP credentials). Left undecided intentionally — outside this session's scope (infra only, no code).
**Secrets Manager: 4 secrets, unaffected by this change** (`DATABASE_URL`, `JWT_SECRET`, `SARVAM_API_KEY`, `OPENAI_API_KEY`) — no `SMTP_PASSWORD` needed regardless of transport choice above (SDK needs none; SMTP-interface would need `SES_SMTP_PASSWORD`, a new SES-generated value, not reused from anything Gmail-related).
**SSM: 5 non-email params done** (`NODE_ENV`, `PORT`, `S3_BUCKET`, `S3_PREFIX`, `AWS_REGION`). **Still pending client:** `/bolo/staging/SES_FROM_EMAIL` — the verified sender address, needed regardless of transport mechanism.

**Gaps found comparing against the real local `.env` files (both repos) — user pasted them, caught several things missing from this plan:**
- **`TZ` (`Asia/Kolkata`)** — genuinely absent from every doc until now. Added to `staging-setup.md`'s SSM table. **Action needed:** create `/bolo/staging/TZ`.
- **`CORS_ORIGIN`** — backend Express CORS (which frontend origin can call the API), distinct from the S3 bucket CORS policy already planned for Step 6 — same word, two different concerns, and the backend one was never actually planned. Added to `staging-setup.md`. **Decision: skip creating it now** — defer to Step 8 (once the real domain is known) rather than create it with a placeholder value now, which risked an early deploy silently reading a wrong/empty value.
- **`LOG_LEVEL`/`OTEL_SERVICE_NAME`/`OTEL_EXPORTER_OTLP_ENDPOINT`** — real and documented in `observability.md`, but fixed/environment-invariant values, not secrets — belong hardcoded directly in `docker-compose.yml`'s environment block at Step 7, not fetched from AWS. `LOG_PRETTY` correctly stays unset (Docker rule in `observability.md`).
- **⚠️ `VITE_API_URL`/`VITE_AUTH_URL` (frontend) — real unaddressed gap, not just a missing param.** These are baked into the `bolo-web` JS bundle at Docker **build time**, not fetched at container runtime — Secrets Manager/SSM doesn't apply. Nothing in `staging-setup.md`/`deployment.md` currently tells the GitHub Actions workflow how to pass `VITE_API_URL=https://staging.<domain>` as a build-arg when building the frontend image. **Needs a design decision before Step 9/10** (GitHub Secrets / first deploy) — not resolved yet.

### Design fix — `DATABASE_URL` duplication removed (decided 2026-07-16): Caught during setup that we were about to store the RDS password twice — once as `bolo/staging/DB_PASSWORD` (Secrets Manager) and again embedded inside `/bolo/staging/DATABASE_URL` (SSM). Traced this to `deployment.md` originally specifying `DB_PASSWORD` **or** `DATABASE_URL` (either/or) — `staging-setup.md`'s Step 5 table had drifted into listing both. Fixed: both docs now specify **`DATABASE_URL` only, stored in Secrets Manager** (sensitive value, belongs there, not in SSM's non-sensitive tier). No standalone `DB_PASSWORD` — nothing in the documented app design consumes it separately from the assembled `DATABASE_URL`. `bolo/staging/DB_PASSWORD` was deleted from Secrets Manager; `bolo/staging/DATABASE_URL` created in its place.

**Final tally:** Secrets Manager — 4 secrets (`DATABASE_URL`, `JWT_SECRET`, `SARVAM_API_KEY`, `OPENAI_API_KEY`). SSM — 6 params (`NODE_ENV`, `PORT`, `TZ`, `S3_BUCKET`, `S3_PREFIX`, `AWS_REGION`). Deferred to Step 8: `CORS_ORIGIN`, `SES_FROM_EMAIL`, and SES SMTP credentials if that transport is chosen.

---

### Step 6 — S3
**Status:** Done
**Date:** 2026-07-16
**What was done:** Created `bolo-staging` bucket in ap-south-1. General purpose, Global namespace, ACLs disabled, Block all public access on, Versioning disabled, SSE-S3 encryption, Bucket Key enabled, Object Lock disabled.
**Notes:** CORS policy intentionally skipped — needs the real staging domain in `AllowedOrigins`, deferred to Step 8 alongside `CORS_ORIGIN` (SSM) and `SES_FROM_EMAIL`. No folders created manually — app writes by prefix (`staging/evidence/`, `staging/voice/`) dynamically.
**2026-07-17 — S3 CORS policy updated again** after the `staging.bolo.aibigo.in` → `staging-bolo.aibigo.in` rename (Cloudflare free-SSL fix) — `AllowedOrigins` now correctly uses the hyphenated hostname.
**2026-07-17 — CORS policy applied, corrected to include OpenShift dev origin too.** User caught that `bolo-staging` is a shared bucket for both OpenShift dev (`bolo-staging/dev/`) and AWS staging (`bolo-staging/staging/`) per `deployment-proposal-client.md`'s prefix design — my first pass at the CORS policy only allowed `staging-bolo.aibigo.in`, which would have CORS-blocked the still-running OpenShift dev frontend from uploading. Corrected: `AllowedOrigins` now includes both `https://staging-bolo.aibigo.in` and `https://bolo-web-techbrutal1151-dev.apps.rm1.0a51.p1.openshiftapps.com`. `staging-setup.md` updated to match.

---

### Domain confirmed by client (2026-07-16)

Client email (Adarsh Jain, Jul 15 8:34 PM, corrected Jul 15 10:19 PM): domain is **`aibigo.in`** (not `.com` — correction). Client's own wording: staging at `bolo.aibigo.in/integrate18/varun/`, path confirmed literal (not just an annotation) via direct follow-up. **Dev-team decision, not client-specified:** added a `staging` marker → **`staging-bolo.aibigo.in/integrate18/varun/`** — keeps the environment marked in the URL, leaves `bolo.aibigo.in` free for a clean production URL later. Not yet run past the client; worth confirming with them if this exact URL gets shared externally. Official sender email: **`bolosupport@aibigo.in`**.
**2026-07-17 — naming revised from `staging.bolo.aibigo.in` to `staging-bolo.aibigo.in` (hyphen, not dot).** Original dotted version is a 2-level-deep subdomain, which Cloudflare's free Universal SSL doesn't cover (only covers the apex domain + one wildcard level) — would have required the paid Advanced Certificate Manager add-on (~$10/mo, not in the original budget). Hyphenated version is a single-level subdomain, covered for free by the existing `*.aibigo.in` origin certificate — no cert changes needed, no added cost. Confirmed via Cloudflare's DNS records page: the dotted version showed a "not covered by a certificate" warning; switching to the hyphenated form resolved it.

**Updated throughout `staging-setup.md`** — all `staging.<domain>` placeholders replaced with `staging-bolo.aibigo.in` (Cloudflare DNS record, CORS_ORIGIN value, S3 CORS AllowedOrigins, health-check URLs).

**⚠️ Real open item, not resolved in this session:** the `/integrate18/varun/` path prefix is an app-layer routing concern — nginx (in the `bolo-web` container) needs a rewrite rule and/or the Vite build needs its `base` path configured to serve correctly under this prefix instead of domain root. This is code/build work, not infra, and this session is infra-only — flagged for whoever builds the `bolo-web` nginx/Docker config, likely at or before Step 8.

**2026-07-17 — domain vs. email confirmed separately:** asked the client explicitly (domain existence was never actually verified, only assumed from the earlier email). **Domain `aibigo.in` confirmed to exist** — DNS record work in Step 8 can proceed. **`bolosupport@aibigo.in` does NOT exist yet** — client will confirm once created. This blocks only the SES sender-identity verification sub-step (Step 8 item 8) and the SSM `SES_FROM_EMAIL` param's real-world usability — everything else in Step 8 (DNS record, SSL/TLS, origin cert, CORS, SG tightening) is unaffected and can proceed now.
**2026-07-16, 7:47 PM — email confirmed live.** Client (Adarsh, WhatsApp): "mail exist now — bolosupport@aibigo.in". Unblocks the SES sender-identity verification step. **Action needed:** create `/bolo/staging/SES_FROM_EMAIL` (SSM, String) = `bolosupport@aibigo.in`, then start SES identity verification — someone with access to that inbox needs to click the confirmation link SES sends.

**2026-07-17 — Cloudflare account doesn't exist either, doc corrected.** `staging-setup.md`'s "Before you start" table had "Cloudflare account ✅ have it" — this was never actually verified, a false positive. Corrected the doc. **No Cloudflare account exists for this project yet** — needs creating before Step 8 can proceed at all. Recommend a team/shared email for the signup, not a personal one (same reasoning as the dedicated `bolosupport@aibigo.in` alias) — **which email to use is pending user input.**
**Decided (2026-07-17):** client confirmed — use `bolosupport@aibigo.in` for the Cloudflare account signup (same address as the SES sender identity). Matches the "shared/dedicated alias, not personal" recommendation.
**Values to save:** Domain: `aibigo.in` · Staging URL: `staging-bolo.aibigo.in/integrate18/varun/` · Sender email: `bolosupport@aibigo.in`

---

### Step 9 — GitHub Secrets
**Status:** Done
**Date:** 2026-07-17
**What was done:** Added `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (both from the `bolo-gha` IAM user, saved by the user from Step 1A), and `EC2_INSTANCE_ID` (`i-04528d8123c208780`) as repository secrets on both `integrate18/bolo-backend` and `integrate18/bolo-web`.
**GitHub notes:** These 3 secrets will need re-adding after the repos transfer to the client's GitHub org (per the session's PROD-migration note) — same secret names, same values, just re-entered under the new org. No workflow files reference the org name directly (per the original session brief's instruction to use `${{ github.repository_owner }}` — worth double-checking this is actually followed once the GHA workflow files are written, not yet built in this session).
**Notes:** No dependency on Cloudflare/domain — this step is fully independent of Step 8, done in parallel while waiting on the Cloudflare account email decision.

---

### SES setup (2026-07-17)
**Status:** In Progress
**What was done:** Created `/bolo/staging/SES_FROM_EMAIL` (SSM, String) = `bolosupport@aibigo.in`. Hit `Access denied to ses:GetAccount` opening the SES console — `bolo-dev` never had any SES permission at all (unlike earlier blockers, not a wrong-policy mixup — SES was genuinely never in the original Step 0 permission list, written before W100/SES was decided). Self-fixed: attached `AmazonSESFullAccess` to `bolo-dev` directly (self-serviceable now that `IAMFullAccess` works, no client round-trip needed). `staging-setup.md` Step 0 permissions list corrected to include SES.
**Notes:** `bolosupport@aibigo.in` identity created as **email address** type (not domain) — AWS flagged this may cause quarantine/rejection on receiving providers that check DMARC, since only the address is verified, not the domain. Acceptable for now (unblocks testing), but flagged to switch to **domain-level verification** once Cloudflare DNS is set up for `aibigo.in` (Step 8) — adds DKIM CNAME records, removes the DMARC risk, better deliverability.
**False alarm, corrected:** the SES "Get set up" dashboard card only spotlighted one identity as an example, which briefly looked like a mix-up. Checked the full **Identities** list instead — the account actually has **2** identities, both genuinely Verified: `aibigosupport@gmail.com` (pre-existing, unrelated to this project, nothing to do about it) and **`bolosupport@aibigo.in`** (ours, correctly created and verified 2026-07-17). No error after all — SES setup for the email identity is complete.

**2026-07-17 — Cloudflare account + DNS import done, nameserver switch pending (no registrar access on our end).** Created Cloudflare account with `bolosupport@aibigo.in`, added `aibigo.in` as a site (Free plan), DNS auto-import completed and reviewed (Google Workspace MX/SPF/DMARC records + root/`www` A/CNAME all correctly picked up). Cloudflare identified the registrar as **GoDaddy** and assigned nameservers: **`coleman.ns.cloudflare.com`** and **`lilyana.ns.cloudflare.com`** (replacing GoDaddy's default `ns33`/`ns34.domaincontrol.com`). **We don't have GoDaddy registrar access** — this needs the client (or whoever holds that login) to make the nameserver change. Discussed reversibility with the user beforehand: switching back is possible anytime (old records stay intact at GoDaddy, not deleted by the switch), main risk is DNS propagation lag (up to 24h either direction) and the small chance the auto-import missed an obscure record (e.g. a verification TXT). Recommended checking with the client whether `aibigo.in` uses anything beyond Google Workspace email + the main website before they flip the switch.
**✅ Nameservers updated by client (2026-07-17)** — confirmed via GoDaddy screenshot, showing `coleman.ns.cloudflare.com` + `lilyana.ns.cloudflare.com` correctly set. Now waiting on DNS propagation (up to 24h, often faster) before the Cloudflare zone shows Active. **Action needed next:** check Cloudflare dashboard for `aibigo.in` — once status flips from "Pending Nameserver Update" to "Active," continue with the DNS record, SSL/TLS mode, and origin certificate steps.
**Confirmed in progress (2026-07-17):** Cloudflare shows "Waiting for your registrar to propagate your new nameservers" — typically 1-2 hours, up to 24h max. **Values to save:** Zone ID: `7459caaf774c9f5248bc06e67a4f301e` · Account ID: `b5857b96fcc213357b3ab6d243d300c7`.
**✅ Active (2026-07-17, same day) — propagated faster than expected.** Cloudflare dashboard confirms "Your domain is now protected by Cloudflare." Continuing with the DNS A record, SSL/TLS mode, and origin certificate.
**Grafana Cloud account — paused, not abandoned.** Started signup with `bolosupport@aibigo.in`, blocked on an OTP the client needs to check their inbox for. Picking Step 8 back up first since it's now actually unblocked; will return to Grafana once the client is available.
**SSL/TLS mode set to Full (strict)** (2026-07-17) — confirmed saved.
**Origin certificate created + installed on EC2** (2026-07-17) — wildcard `*.aibigo.in` + root `aibigo.in`, expires Jul 13, 2041. Saved to `/etc/ssl/bolo/bolo-origin.crt` + `.key` on `bolo-staging`.
**Still needs confirming:** the `staging.bolo` DNS A record (`13.232.26.36`, Proxied) — not yet explicitly confirmed done, check before considering Step 8 complete.

**2026-07-17 — DMARC risk confirmed real, not theoretical.** Adding `aibigo.in` to Cloudflare surfaced its existing DNS records on import: confirmed a `_dmarc` TXT record genuinely exists (`v=DMARC1; p=...`), alongside Google Workspace MX/SPF records (domain's email runs on Google Workspace). Validates the earlier flag that SES's email-address-only verification for `bolosupport@aibigo.in` risks quarantine/rejection — domain-level SES verification (adds DKIM CNAMEs via Cloudflare once DNS access exists) is a real priority, not just theoretical hardening.

**Production access — deferred to Step 8, hard requirement not just a nice-to-have.** Attempted "Request production access" — button is greyed out with "Domain verification needed" shown directly under it. AWS requires domain-level SES verification (SPF/DKIM DNS records) before allowing a production access request at all, not just email-address verification. This means the "switch to domain verification for better deliverability" note above is actually a **blocking prerequisite**, not optional. Since domain verification needs DNS record access to `aibigo.in`, this naturally happens once Cloudflare is set up (Step 8) — deferring the production access request until then rather than working around sandbox mode now. **Cost clarified:** sandbox vs. production doesn't change SES pricing — pure pay-per-email either way, with a permanent 62,000 emails/month free allowance when sending from EC2 (not a 12-month trial). Sandbox only restricts *who* you can send to (verified addresses only) and imposes lower rate/volume caps (200/day, 1/sec) — not a cost difference.

---

---

### S3 Dev Handoff — OpenShift + Local Testing (2026-07-16)
**Status:** Done
**What was done:** Handed off S3 config to the dev team so they can test real object storage (instead of local file storage) on both local machines and OpenShift dev environment.

**Key decisions:**
- S3 credentials go on **backend only** — frontend never needs them. Flow is: frontend requests a pre-signed URL from backend → backend signs it using AWS SDK → frontend uploads directly to S3 using that URL.
- Rather than creating a new IAM user, added `AmazonS3FullAccess` to the existing `bolo-gha` IAM user — same credentials already in GitHub secrets, no new user needed.
- OpenShift dev uses prefix `dev/` → files land in `bolo-staging/dev/` (isolated from AWS staging which uses `bolo-staging/staging/`).

**Local `.env` setup (bolo-backend only):**
```
AWS_ACCESS_KEY_ID=<bolo-gha access key>
AWS_SECRET_ACCESS_KEY=<bolo-gha secret key>
S3_BUCKET=bolo-staging
S3_PREFIX=dev/
AWS_REGION=ap-south-1
```

**OpenShift setup:**
```bash
# 2 sensitive creds as an OpenShift secret
oc create secret generic bolo-s3-creds \
  --from-literal=AWS_ACCESS_KEY_ID=<bolo-gha access key> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<bolo-gha secret key>

# Mount secret into the backend deployment
oc set env deployment/bolo-backend --from=secret/bolo-s3-creds

# 3 non-sensitive config vars as plain env vars
oc set env deployment/bolo-backend \
  S3_BUCKET=bolo-staging \
  S3_PREFIX=dev/ \
  AWS_REGION=ap-south-1
```
Pod restarts automatically and picks up all 5 vars.

**PROD note:** For production, the EC2 instance uses `bolo-ec2-role` (IAM role) — no static credentials needed at all. The `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` pattern is only for local + OpenShift (environments without an IAM role attached).

---

### Step 7 — EC2
**Status:** Done
**Date:** 2026-07-16
**What was done:** Launched `bolo-staging` instance. Amazon Linux 2023 (64-bit x86), t3.small, `bolo-ec2-sg`, `bolo-ec2-role` IAM instance profile, 20GB gp3 root volume **encrypted** (default `aws/ebs` KMS key, fixed from an initial "Not encrypted" default), no key pair (SSM-only access), auto-assign public IP enabled. SSM connectivity confirmed via Session Manager. Bootstrapped Docker 25.0.14 + Docker Compose v5.3.1 via SSM session, `/app` directory created (owned by `ec2-user`). RDS connectivity check passed — `nc -zv` to the RDS endpoint on 5432 succeeded (connected to `172.31.17.140:5432`, RDS's private VPC IP), confirming `bolo-ec2-sg` → `bolo-rds-sg` works end-to-end, not just on paper.
**Values to save:** Instance ID: `i-04528d8123c208780` · **Elastic IP (static, permanent): `13.232.26.36`** (allocated + associated 2026-07-16, replaces the original auto-assigned `13.206.237.242` — this one survives stop/restart cycles)
**Errors encountered:** Key pair initially left on unset "Select" placeholder — fixed before launch. Root volume initially showed "Not encrypted" — fixed via Advanced storage settings before launch.
**Notes:** `docker-compose.yml` itself not placed in `/app/` yet — that's part of the actual app deployment (Step 10), out of scope for infra setup.

**✅ Elastic IP allocated + associated (2026-07-16).** `13.232.26.36` is now permanently reserved and attached to `bolo-staging` — survives stop/restart, safe to stop EC2 overnight too now without any DNS-record complications later. This is the IP to use for the Step 8 Cloudflare DNS record, not the old `13.206.237.242`.
**⚠️ 2026-07-16 end of day — stopped for the night** (graceful stop, OS shutdown not skipped). Elastic IP stays reserved/attached while stopped. **Action needed next session:** EC2 → Instance state → Start, before resuming Step 8.

---
