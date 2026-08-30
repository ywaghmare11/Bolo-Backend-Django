# AWS deploy from scratch — a hands-on, free-tier runbook

> **Who this is for:** someone who has never opened the AWS console and wants to
> take `bolo-backend-django` (Django + DRF + Celery) and the `bolo-admin-console`
> (React/Vite SPA) from "runs on my laptop" to "running on AWS, deployed
> automatically by GitHub Actions", spending **≈ $0** by staying inside the free
> tier / signup credits and tearing things down between sessions.
>
> **Scope choices baked in (your call, 2026-08-30):**
> - **No NAT Gateway** — the single biggest surprise bill. Alternative below.
> - **No Route 53, no custom domain** — reach the API by its load-balancer
>   DNS name (an AWS-provided hostname) or a CloudFront URL. No `$` for DNS.
> - **One environment**, not staging + production. The existing
>   `.github/workflows/deploy.yml` (two-env promotion) is the "next step up";
>   this runbook uses a simpler single-env workflow you can graduate from.
>
> The companion file `docs/ops/deployment-django.md` is the *reference
> architecture* (what a real production setup looks like). **This** file is the
> *tutorial* (exact clicks and commands, cheapest possible).

---

## 0. Map of the whole thing

```
                         Internet
                            │
        ┌───────────────────┴────────────────────┐
        │                                        │
  CloudFront distribution                  Application Load Balancer  (port 80)
  (bolo-admin-console)                     sg: inbound 80 from 0.0.0.0/0
        │                                        │
   S3 bucket (private,                     Target group  (type: ip, port 8000,
   reached only via CloudFront OAC)        health check: /healthz)
        │                                        │
   React build output (dist/)             ECS service  "bolo-web"
                                          Fargate Spot · 1 task · public subnet
                                          sg: inbound 8000 from the ALB sg only
                                          assignPublicIp = ENABLED
                                                 │  (egress via Internet Gateway)
                        ┌────────────────────────┼─────────────────────────┐
                        │                        │                         │
                RDS PostgreSQL          ElastiCache Redis          outbound to:
                sg: 5432 from           sg: 6379 from              ECR, SSM Parameter
                the ECS sg only         the ECS sg only            Store, CloudWatch
                (not publicly           (not publicly              Logs, SES, S3,
                 accessible)             accessible)               api.openai.com

                ECS service  "bolo-worker"   (Fargate Spot · 1 task · same subnet/sg · no ALB)
                command:  celery -A config worker --beat        (worker + scheduler in one)
```

**Why this shape avoids NAT:** a NAT Gateway exists so containers in a *private*
subnet can make *outbound* calls (pull the image from ECR, read secrets, ship
logs). We instead put the ECS tasks in a **public subnet with a public IP**
(`assignPublicIp = ENABLED`), so their outbound traffic goes straight out the
(free) Internet Gateway. **Inbound is still fully locked down** — the task's
security group only accepts port 8000 from the load balancer's security group,
nothing from the internet. The datastores (RDS, Redis) stay unreachable from
outside entirely (`Publicly accessible = No` + tight security groups).

Trade-off, stated plainly for interviews: the task has an outbound public IP,
which is a slightly larger surface than a private subnet + NAT. For a real
production system with a budget you'd use private subnets + a NAT Gateway (or
VPC endpoints). For learning and for keeping the bill at zero, public subnet +
strict security groups is the standard cheap pattern.

---

## Order of operations (the whole runbook at a glance)

| # | Step | AWS service | ~time |
|---|---|---|---|
| 1 | Create + secure the AWS account, set a $0 budget alarm | Billing, IAM | 20 min |
| 2 | Install & configure the AWS CLI locally | — | 10 min |
| 3 | Learn the 12 nouns (glossary) | — | read once |
| 4 | Pick a region, note the default VPC + subnets | VPC | 5 min |
| 5 | Create 4 security groups | VPC | 10 min |
| 6 | Create the ECR repository (+ lifecycle policy) | ECR | 5 min |
| 7 | Put secrets in SSM Parameter Store | SSM | 10 min |
| 8 | Create the RDS PostgreSQL instance | RDS | 15 min (wait) |
| 9 | Create the ElastiCache Redis node | ElastiCache | 15 min (wait) |
| 10 | Create 3 IAM roles (execution, task, GitHub-OIDC-deploy) | IAM | 20 min |
| 11 | Create CloudWatch log groups | CloudWatch | 5 min |
| 12 | Small code changes: `/healthz`, HTTP-only settings toggles | this repo | 10 min |
| 13 | Register task definitions (web, worker, migrate) | ECS | 15 min |
| 14 | Create the ALB + target group + listener | EC2 / ELBv2 | 15 min |
| 15 | Create the ECS cluster + 2 services | ECS | 15 min |
| 16 | First manual deploy + smoke test | — | 10 min |
| 17 | Register the GitHub OIDC provider, set repo secret | IAM, GitHub | 10 min |
| 18 | Fill in `deploy-simple.yml`'s `env:` block, push, watch it run | GitHub Actions | 15 min |
| 19 | Test it: change code, push, verify the rollout, practise a rollback | — | 15 min |
| 20 | Deploy the React admin console (S3 + CloudFront + its own workflow) | S3, CloudFront | 40 min |
| 21 | Wire the two together (CORS, `VITE_API_URL`, HTTPS note) | both | 20 min |
| 22 | **Tear down** to stop all spend | everything | 15 min |

Set these once in your shell and reuse them in every command below:

```bash
export AWS_REGION=ap-south-1               # Mumbai. Pick the one nearest you.
export AWS_ACCOUNT_ID=111122223333         # fill after step 1 (aws sts get-caller-identity)
export P=bolo                              # name prefix for everything
export GH_BACKEND_REPO=ywaghmare/bolo-backend-django
export GH_CONSOLE_REPO=ywaghmare/bolo-admin-console
```

---

## 1. Create and secure the AWS account

1. Go to <https://aws.amazon.com/> → **Create an AWS Account**. You need an
   email, a phone number, and a **credit/debit card** (a small temporary
   authorisation, refunded). This is unavoidable even for free usage.
2. During signup you'll be offered a **plan**:
   - **Free plan** (newer accounts): you get **$100 in credits now**, up to
     **$100 more** by completing activities, valid **6 months or until credits
     run out**. When credits hit zero the account is *paused*, not billed. Good
     for "I want to poke at this for a few weeks."
   - **Paid plan**: same credits, **plus** the classic *12-month free tier*
     allowances (750 hrs/month of small RDS, Redis, ALB, etc.) **plus** the
     perpetual "always free" tiers (CloudFront 1 TB/month). Overages bill to
     your card. Choose this if you want the account to last a year — and rely on
     the budget alarm in the next step.
   Either way, the services in this runbook are covered.
3. **Sign in as the root user** (the email you just used). Immediately:
   - **IAM** → your security credentials → **Enable MFA** on the root user
     (authenticator app is fine).
   - Do **not** create access keys for root. Do not use root day-to-day.
4. Create an admin IAM user for yourself:
   - **IAM** → **Users** → **Create user** → name `admin`.
   - "Provide user access to the AWS Management Console" — yes, autogenerated
     password, uncheck "must change".
   - Permissions → **Attach policies directly** → `AdministratorAccess`.
   - Create. **Save the console sign-in URL** (`https://<account-id>.signin.aws.amazon.com/console`).
   - Open the new user → **Security credentials** → **Create access key** →
     use case "Command Line Interface (CLI)" → save the **Access key ID** and
     **Secret access key** (shown once).
   - Enable MFA on this user too.
   - From now on, sign in and run the CLI as `admin`, never root.
   > A more "correct" setup uses **IAM Identity Center** (SSO) instead of a
   > long-lived IAM user access key. For a single solo learner the IAM user is
   > simpler; mention Identity Center in interviews as the thing you'd use on a
   > team.
5. **Set a zero-spend budget alarm right now** (this is your seatbelt):
   - **Billing and Cost Management** → **Budgets** → **Create budget** →
     template **"Zero spend budget"** → enter your email → Create.
   - Also **Budgets → Create budget → "Monthly cost budget"**, amount `$5`,
     alerts at 50% / 80% / 100% actual. Belt and braces.
   - **Billing → Billing preferences** → enable **"Receive Free Tier usage
     alerts"** and **"Receive CloudWatch billing alerts"**.
6. Confirm the CLI identity later with `aws sts get-caller-identity` — the
   `Account` field is your `AWS_ACCOUNT_ID`.

---

## 2. Install and configure the AWS CLI

```bash
# Linux (x86_64)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
aws --version            # aws-cli/2.x

aws configure
#   AWS Access Key ID     : <the admin user's key>
#   AWS Secret Access Key : <the admin user's secret>
#   Default region name   : ap-south-1
#   Default output format : json

aws sts get-caller-identity     # should show arn .../admin and your account id
```

Also make sure the **GitHub CLI** is handy for watching workflow runs:
`gh auth login` (optional but convenient).

---

## 3. Glossary — the nouns you're about to use

Learn these; they're exactly the words an interviewer will use.

| Term | One-line meaning |
|---|---|
| **Region** | A geographic AWS location (`ap-south-1` = Mumbai). Everything below lives in one region. |
| **Availability Zone (AZ)** | An isolated datacentre within a region. You spread across ≥2 for redundancy. |
| **VPC** | Your private network in the cloud. New accounts get a **default VPC** per region, already wired to the internet. |
| **Subnet** | An IP range inside a VPC, pinned to one AZ. **Public** = has a route to an Internet Gateway; **private** = doesn't. Default-VPC subnets are public. |
| **Internet Gateway (IGW)** | The VPC's door to the internet. Free. Already attached to the default VPC. |
| **NAT Gateway** | Lets *private* subnets make *outbound* calls. **~$32/mo — we do NOT use one.** |
| **Security Group (SG)** | A stateful firewall attached to a resource (ENI). Rules are "allow" only; default inbound = deny all. |
| **ECR** | Elastic Container **Registry** — where your Docker images are stored (like a private Docker Hub). |
| **ECS** | Elastic Container **Service** — runs your containers. **Cluster** → **Services** → **Tasks**. A **Task Definition** is the "recipe" (image, CPU, env, secrets, ports). |
| **Fargate** | "Serverless" compute for ECS — you don't manage EC2 VMs. **Fargate Spot** = same thing up to ~70% cheaper, can be interrupted. |
| **ALB** | Application Load Balancer — L7 (HTTP) load balancer. Terminates connections from the internet and forwards to your tasks via a **Target Group**. |
| **Target Group** | The pool of things an ALB forwards to (here: task IPs on port 8000) + the health check that decides which are "in". |
| **RDS** | Managed relational database (managed PostgreSQL here). |
| **ElastiCache** | Managed Redis. |
| **SSM Parameter Store** | Key/value config + secrets store. `SecureString` params are KMS-encrypted. **Free** for standard params (we use this instead of Secrets Manager, which costs $0.40/secret/mo). |
| **IAM Role** | A set of permissions that a *service* or an *external identity* assumes — no password, temporary credentials. |
| **OIDC (for GitHub Actions)** | Lets a GitHub Actions run prove "I am workflow X in repo Y" to AWS and assume a role, with **no stored AWS keys** in GitHub. |
| **CloudWatch Logs** | Where container stdout/stderr goes (via the `awslogs` log driver). |
| **CloudFront** | AWS's CDN. Perpetual free tier: 1 TB out + 10M requests/month. Gives you free HTTPS and a free `*.cloudfront.net` hostname. |

---

## 4. Region + default VPC

Pick a region (set `AWS_REGION` above). Then find the default VPC and its
subnets — **you will paste these IDs into many later commands**.

```bash
# Default VPC id
export VPC_ID=$(aws ec2 describe-vpcs --region $AWS_REGION \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
echo "VPC_ID=$VPC_ID"

# Two default (public) subnets, in two different AZs
aws ec2 describe-subnets --region $AWS_REGION \
  --filters Name=vpc-id,Values=$VPC_ID Name=default-for-az,Values=true \
  --query 'Subnets[].{Subnet:SubnetId,AZ:AvailabilityZone}' --output table

# Grab the first two subnet ids into vars (edit if you want specific AZs)
export SUBNET_A=$(aws ec2 describe-subnets --region $AWS_REGION \
  --filters Name=vpc-id,Values=$VPC_ID Name=default-for-az,Values=true \
  --query 'Subnets[0].SubnetId' --output text)
export SUBNET_B=$(aws ec2 describe-subnets --region $AWS_REGION \
  --filters Name=vpc-id,Values=$VPC_ID Name=default-for-az,Values=true \
  --query 'Subnets[1].SubnetId' --output text)
echo "SUBNET_A=$SUBNET_A  SUBNET_B=$SUBNET_B"
```

> Production note: you would create a **purpose-built VPC** with separate public
> (ALB only) and private (tasks + data) subnet tiers. The default VPC is used
> here to skip ~15 resources and because it's genuinely fine for this exercise.

---

## 5. Security groups (the firewall)

Four SGs. Create them, then add rules that reference *each other* (not IP ranges)
wherever possible — "the DB accepts traffic from the app tier" is expressed as
"from the app's SG".

```bash
mk_sg () {  # name  description  ->  echoes the sg id
  aws ec2 create-security-group --region $AWS_REGION \
    --group-name "$1" --description "$2" --vpc-id $VPC_ID \
    --query 'GroupId' --output text
}

export SG_ALB=$(mk_sg  $P-alb-sg   "ALB: public HTTP in")
export SG_ECS=$(mk_sg  $P-ecs-sg   "ECS tasks: 8000 from ALB only")
export SG_RDS=$(mk_sg  $P-rds-sg   "RDS: 5432 from ECS only")
export SG_REDIS=$(mk_sg $P-redis-sg "Redis: 6379 from ECS only")
echo "SG_ALB=$SG_ALB SG_ECS=$SG_ECS SG_RDS=$SG_RDS SG_REDIS=$SG_REDIS"

# ALB: allow HTTP from anywhere (add 443 later if you put a cert on the ALB)
aws ec2 authorize-security-group-ingress --region $AWS_REGION --group-id $SG_ALB \
  --protocol tcp --port 80 --cidr 0.0.0.0/0

# ECS tasks: allow 8000 ONLY from the ALB's SG
aws ec2 authorize-security-group-ingress --region $AWS_REGION --group-id $SG_ECS \
  --protocol tcp --port 8000 --source-group $SG_ALB

# RDS: allow 5432 ONLY from the ECS SG
aws ec2 authorize-security-group-ingress --region $AWS_REGION --group-id $SG_RDS \
  --protocol tcp --port 5432 --source-group $SG_ECS

# Redis: allow 6379 ONLY from the ECS SG
aws ec2 authorize-security-group-ingress --region $AWS_REGION --group-id $SG_REDIS \
  --protocol tcp --port 6379 --source-group $SG_ECS
```

Outbound rules: SGs allow **all outbound by default** — leave that. That's how
the ECS tasks reach ECR / SSM / CloudWatch / SES / S3 / OpenAI over the IGW.

---

## 6. ECR repository

```bash
aws ecr create-repository --region $AWS_REGION \
  --repository-name $P-backend \
  --image-scanning-configuration scanOnPush=true \
  --image-tag-mutability MUTABLE

export ECR_URI=$(aws ecr describe-repositories --region $AWS_REGION \
  --repository-names $P-backend --query 'repositories[0].repositoryUri' --output text)
echo "ECR_URI=$ECR_URI"     # e.g. 1111.dkr.ecr.ap-south-1.amazonaws.com/bolo-backend
```

Add a **lifecycle policy** so old images are pruned and you stay under the
500 MB/month free ECR storage:

```bash
cat > /tmp/ecr-lifecycle.json <<'JSON'
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "keep only the 10 most recent images",
      "selection": { "tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 10 },
      "action": { "type": "expire" }
    }
  ]
}
JSON
aws ecr put-lifecycle-policy --region $AWS_REGION \
  --repository-name $P-backend --lifecycle-policy-text file:///tmp/ecr-lifecycle.json
```

---

## 7. Secrets → SSM Parameter Store

The app (`config/settings/base.py`) **crashes at startup** if a required env var
is missing — by design. So every one of these must exist before a task can run.

Generate the two Django secrets locally:

```bash
export DJANGO_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(64))")
export JWT_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(64))")
```

You'll get `DATABASE_URL` and `REDIS_URL` **after** creating RDS/Redis (steps 8–9),
so do this section in two passes. Helper:

```bash
put_secret () {  # name  value
  aws ssm put-parameter --region $AWS_REGION \
    --name "/$P/$1" --value "$2" --type SecureString --overwrite >/dev/null
  echo "  wrote /$P/$1"
}

# Pass 1 — the ones you can set now
put_secret DJANGO_SECRET_KEY "$DJANGO_SECRET_KEY"
put_secret JWT_SECRET        "$JWT_SECRET"

# Pass 2 — after steps 8 & 9 (come back here):
# put_secret DATABASE_URL "postgres://boloadmin:<pw>@<rds-endpoint>:5432/bolo"
# put_secret REDIS_URL    "redis://<redis-endpoint>:6379/0"
```

Non-secret config (`ALLOWED_HOSTS`, region, feature toggles) will go straight
into the task definition as plain `environment` entries — no need to store those
in SSM.

> **Why SSM, not Secrets Manager?** Identical wiring in the ECS task definition
> (`secrets: [{ name, valueFrom: <arn> }]`), but SSM standard parameters are
> **free** and Secrets Manager is **$0.40 per secret per month**. Secrets Manager
> adds rotation and cross-account sharing you don't need here.

---

## 8. RDS PostgreSQL

Create a **DB subnet group** (RDS wants ≥2 subnets in ≥2 AZs), then the instance.

```bash
aws rds create-db-subnet-group --region $AWS_REGION \
  --db-subnet-group-name $P-db-subnets \
  --db-subnet-group-description "$P db subnets" \
  --subnet-ids $SUBNET_A $SUBNET_B

export RDS_PASSWORD=$(python -c "import secrets;print(secrets.token_urlsafe(24))")
echo "RDS_PASSWORD=$RDS_PASSWORD   # save this"

aws rds create-db-instance --region $AWS_REGION \
  --db-instance-identifier $P-pg \
  --engine postgres --engine-version 16 \
  --db-instance-class db.t4g.micro \
  --allocated-storage 20 --storage-type gp3 \
  --master-username boloadmin --master-user-password "$RDS_PASSWORD" \
  --db-name bolo \
  --db-subnet-group-name $P-db-subnets \
  --vpc-security-group-ids $SG_RDS \
  --no-publicly-accessible \
  --backup-retention-period 1 \
  --no-multi-az \
  --no-auto-minor-version-upgrade

# Wait (~5-10 min)
aws rds wait db-instance-available --region $AWS_REGION --db-instance-identifier $P-pg

export RDS_ENDPOINT=$(aws rds describe-db-instances --region $AWS_REGION \
  --db-instance-identifier $P-pg \
  --query 'DBInstances[0].Endpoint.Address' --output text)
echo "RDS_ENDPOINT=$RDS_ENDPOINT"
```

Free-tier notes: `db.t4g.micro` (or `db.t3.micro`), **single-AZ**, 20 GB gp3,
1-day backups — this fits the 12-month RDS free tier (750 instance-hours/month =
one instance running non-stop). `--no-publicly-accessible` means it only gets a
private IP even though it's in a public subnet; combined with `SG_RDS` nothing
outside the VPC can reach it.

Now write the DB URL to SSM (Django's `django-environ` accepts the `postgres://`
scheme):

```bash
put_secret DATABASE_URL "postgres://boloadmin:${RDS_PASSWORD}@${RDS_ENDPOINT}:5432/bolo"
```

---

## 9. ElastiCache Redis

```bash
aws elasticache create-cache-subnet-group --region $AWS_REGION \
  --cache-subnet-group-name $P-redis-subnets \
  --cache-subnet-group-description "$P redis subnets" \
  --subnet-ids $SUBNET_A $SUBNET_B

aws elasticache create-cache-cluster --region $AWS_REGION \
  --cache-cluster-id $P-redis \
  --engine redis --engine-version 7.1 \
  --cache-node-type cache.t3.micro \
  --num-cache-nodes 1 \
  --cache-subnet-group-name $P-redis-subnets \
  --security-group-ids $SG_REDIS

aws elasticache wait cache-cluster-available --region $AWS_REGION --cache-cluster-id $P-redis

export REDIS_ENDPOINT=$(aws elasticache describe-cache-clusters --region $AWS_REGION \
  --cache-cluster-id $P-redis --show-cache-node-info \
  --query 'CacheClusters[0].CacheNodes[0].Endpoint.Address' --output text)
echo "REDIS_ENDPOINT=$REDIS_ENDPOINT"

put_secret REDIS_URL "redis://${REDIS_ENDPOINT}:6379/0"
```

`cache.t3.micro`, single node, no cluster mode, no encryption/auth (it's only
reachable from the ECS SG inside the VPC) — fits the 12-month ElastiCache free
tier. Your `requirements/base.txt` pins `redis==5.2.1` specifically so it speaks
RESP2 and works against any Redis version — nothing to change.

> Want to shave even this? Run Redis as a **second container in the web task
> definition** instead. It's non-durable and single-AZ, but this app only uses
> Redis for the throttle, cache-aside, and the Celery broker — all tolerant of a
> cold cache. For a clean demo, ElastiCache t3.micro is simplest and free.

---

## 10. IAM roles

Three roles:

| Role | Assumed by | Purpose |
|---|---|---|
| `bolo-ecs-execution` | ECS agent | Pull the image from ECR, fetch SSM secrets, write logs. **Infra-level**, before your code runs. |
| `bolo-ecs-task` | your running container | What *your app* is allowed to do: send SES email, read/write the S3 bucket. |
| `bolo-gha-deploy` | GitHub Actions (via OIDC) | Push to ECR, register task defs, update ECS services, run the migrate task. |

### 10a. Execution role

```bash
cat > /tmp/ecs-trust.json <<'JSON'
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole" } ] }
JSON

aws iam create-role --role-name $P-ecs-execution \
  --assume-role-policy-document file:///tmp/ecs-trust.json

aws iam attach-role-policy --role-name $P-ecs-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Extra: let the agent read our SSM SecureString params (and decrypt them)
cat > /tmp/exec-ssm.json <<JSON
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow",
    "Action": ["ssm:GetParameters"],
    "Resource": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/${P}/*" },
  { "Effect": "Allow",
    "Action": ["kms:Decrypt"],
    "Resource": "*",
    "Condition": { "StringEquals": { "kms:ViaService": "ssm.${AWS_REGION}.amazonaws.com" } } }
] }
JSON
aws iam put-role-policy --role-name $P-ecs-execution \
  --policy-name ssm-read --policy-document file:///tmp/exec-ssm.json

export EXEC_ROLE_ARN=arn:aws:iam::${AWS_ACCOUNT_ID}:role/$P-ecs-execution
```

### 10b. Task role (your app's own permissions)

```bash
aws iam create-role --role-name $P-ecs-task \
  --assume-role-policy-document file:///tmp/ecs-trust.json

cat > /tmp/task-perms.json <<JSON
{ "Version": "2012-10-17", "Statement": [
  { "Sid": "S3Evidence", "Effect": "Allow",
    "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
    "Resource": ["arn:aws:s3:::${P}-media-${AWS_ACCOUNT_ID}",
                 "arn:aws:s3:::${P}-media-${AWS_ACCOUNT_ID}/*"] },
  { "Sid": "SESSend", "Effect": "Allow",
    "Action": ["ses:SendEmail","ses:SendRawEmail"], "Resource": "*" }
] }
JSON
aws iam put-role-policy --role-name $P-ecs-task \
  --policy-name app-perms --policy-document file:///tmp/task-perms.json

export TASK_ROLE_ARN=arn:aws:iam::${AWS_ACCOUNT_ID}:role/$P-ecs-task
```

(The media bucket and SES identity are optional for a first deploy — the app
degrades gracefully without them. Create the bucket with
`aws s3 mb s3://${P}-media-${AWS_ACCOUNT_ID} --region $AWS_REGION` if you want
evidence uploads to work.)

### 10c. GitHub Actions deploy role (OIDC)

First register GitHub as an OIDC identity provider in your account (once per
account):

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 1b511abead59c6ce207077c0bf0e0043b1382612
# AWS no longer actually verifies this thumbprint for this provider, but the CLI
# still requires the argument. Any 40-hex-char string is accepted; the value
# above is the historically-correct one.
```

Trust policy — **only** workflows in your backend repo may assume this role:

```bash
cat > /tmp/gha-trust.json <<JSON
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:${GH_BACKEND_REPO}:*" }
    } } ] }
JSON

aws iam create-role --role-name $P-gha-deploy \
  --assume-role-policy-document file:///tmp/gha-trust.json

cat > /tmp/gha-perms.json <<JSON
{ "Version": "2012-10-17", "Statement": [
  { "Sid": "EcrAuth",  "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
  { "Sid": "EcrPush",  "Effect": "Allow",
    "Action": ["ecr:BatchCheckLayerAvailability","ecr:CompleteLayerUpload","ecr:InitiateLayerUpload",
               "ecr:PutImage","ecr:UploadLayerPart","ecr:BatchGetImage","ecr:DescribeImages"],
    "Resource": "arn:aws:ecr:${AWS_REGION}:${AWS_ACCOUNT_ID}:repository/${P}-backend" },
  { "Sid": "EcsDeploy", "Effect": "Allow",
    "Action": ["ecs:RegisterTaskDefinition","ecs:DescribeTaskDefinition",
               "ecs:DescribeServices","ecs:UpdateService",
               "ecs:RunTask","ecs:DescribeTasks","ecs:ListTasks"],
    "Resource": "*" },
  { "Sid": "PassRoles", "Effect": "Allow", "Action": "iam:PassRole",
    "Resource": ["${EXEC_ROLE_ARN}","${TASK_ROLE_ARN}"],
    "Condition": { "StringEquals": { "iam:PassedToService": "ecs-tasks.amazonaws.com" } } },
  { "Sid": "Logs", "Effect": "Allow",
    "Action": ["logs:CreateLogGroup","logs:DescribeLogGroups"],
    "Resource": "*" }
] }
JSON
aws iam put-role-policy --role-name $P-gha-deploy \
  --policy-name deploy-perms --policy-document file:///tmp/gha-perms.json

export DEPLOY_ROLE_ARN=arn:aws:iam::${AWS_ACCOUNT_ID}:role/$P-gha-deploy
echo "DEPLOY_ROLE_ARN=$DEPLOY_ROLE_ARN"    # you'll put this in GitHub as a secret
```

---

## 11. CloudWatch log groups

```bash
for g in web worker migrate; do
  aws logs create-log-group --region $AWS_REGION --log-group-name /ecs/$P-$g
  aws logs put-retention-policy --region $AWS_REGION --log-group-name /ecs/$P-$g --retention-in-days 3
done
```

3-day retention keeps you well under the 5 GB CloudWatch free tier.

---

## 12. Small code changes in this repo

**These are already applied** on branch `chore/aws-http-deploy-prep` (423 tests
green, `ruff` clean). This section explains what they are so you can review the
diff and know which env vars drive them.

### 12a. `/healthz` endpoint (`config/urls.py`)

A plain Django view — skips DRF auth, never touches Postgres/Redis, sits outside
`/api/` so the trailing-slash normaliser ignores it:

```python
def healthz(_request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path('healthz', healthz, name='healthz'),
    # ... rest unchanged
]
```

The ALB target group (§14) health-checks `GET /healthz` and expects `200`.
Covered by `apps/common/tests/test_healthz.py` (public, and asserts zero DB
queries).

### 12b. HTTPS hardening in `prod.py` is now env-toggleable

`config/settings/prod.py` previously hardcoded TLS-in-front assumptions;
`SECURE_SSL_REDIRECT = True` on an HTTP-only ALB is an infinite redirect. Now:

```python
SECURE_SSL_REDIRECT   = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = env.bool("COOKIE_SECURE",       default=True)
CSRF_COOKIE_SECURE    = env.bool("COOKIE_SECURE",       default=True)
SECURE_HSTS_SECONDS   = env.int("SECURE_HSTS_SECONDS",  default=31536000)
SECURE_PROXY_SSL_HEADER = (
    env("SECURE_PROXY_SSL_HEADER_NAME", default="HTTP_X_FORWARDED_PROTO"), "https",
)
```

**Defaults are unchanged (secure)** — leave every one of these env vars unset in
a real HTTPS deployment. For the **HTTP bring-up phase only**, the `bolo-web`
task def (§13a) sets `SECURE_SSL_REDIRECT=False`, `COOKIE_SECURE=False`,
`SECURE_HSTS_SECONDS=0`. Delete those three entries when you move to HTTPS in
§21 — no code change.

### 12c. `corsheaders` wired into `prod.py`

`django-cors-headers` was already in `requirements/base.txt` but only active in
`dev.py`. `prod.py` now adds `corsheaders` to `INSTALLED_APPS` and splices
`CorsMiddleware` in just before `SecurityMiddleware` (correct position, ahead of
WhiteNoise/CommonMiddleware). It's **inert until `CORS_ALLOWED_ORIGINS` is set**
from the environment (§21b):

```python
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
```

Merge `chore/aws-http-deploy-prep` to `main` before wiring CD.

---

## 13. Register the ECS task definitions

One JSON per process type. They differ only in `family`, `command`, whether
there's a port, and the log group.

### 13a. `bolo-web`

```bash
cat > /tmp/td-web.json <<JSON
{
  "family": "${P}-web",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "${EXEC_ROLE_ARN}",
  "taskRoleArn": "${TASK_ROLE_ARN}",
  "containerDefinitions": [
    {
      "name": "web",
      "image": "${ECR_URI}:bootstrap",
      "essential": true,
      "portMappings": [ { "containerPort": 8000, "protocol": "tcp" } ],
      "command": ["gunicorn","config.wsgi:application","-c","docker/gunicorn.conf.py"],
      "environment": [
        { "name": "DJANGO_SETTINGS_MODULE", "value": "config.settings.prod" },
        { "name": "ALLOWED_HOSTS",          "value": "*" },
        { "name": "SECURE_SSL_REDIRECT",    "value": "False" },
        { "name": "COOKIE_SECURE",          "value": "False" },
        { "name": "SECURE_HSTS_SECONDS",    "value": "0" },
        { "name": "RUN_MIGRATIONS",         "value": "0" },
        { "name": "CELERY_TASK_ALWAYS_EAGER", "value": "0" },
        { "name": "GUNICORN_WORKERS",       "value": "2" },
        { "name": "AWS_S3_REGION",          "value": "${AWS_REGION}" }
      ],
      "secrets": [
        { "name": "DJANGO_SECRET_KEY", "valueFrom": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/${P}/DJANGO_SECRET_KEY" },
        { "name": "JWT_SECRET",        "valueFrom": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/${P}/JWT_SECRET" },
        { "name": "DATABASE_URL",      "valueFrom": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/${P}/DATABASE_URL" },
        { "name": "REDIS_URL",         "valueFrom": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/${P}/REDIS_URL" }
      ],
      "healthCheck": {
        "command": ["CMD-SHELL","python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).status==200 else 1)\""],
        "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/${P}-web",
          "awslogs-region": "${AWS_REGION}",
          "awslogs-stream-prefix": "web"
        }
      }
    }
  ]
}
JSON
aws ecs register-task-definition --region $AWS_REGION --cli-input-json file:///tmp/td-web.json
```

`ALLOWED_HOSTS=*` is acceptable **only because** the sole thing that can reach
port 8000 is the SG-locked ALB. You'll tighten it in §21.

### 13b. `bolo-worker` (Celery worker + embedded beat)

Copy `td-web.json` to `td-worker.json` and change: `family` → `${P}-worker`;
remove `portMappings` and `healthCheck`; `awslogs-group` → `/ecs/${P}-worker`
(create it: `aws logs create-log-group --log-group-name /ecs/$P-worker` +
retention); `command` →

```json
"command": ["celery","-A","config","worker","--beat","--loglevel=info","--schedule","/tmp/celerybeat-schedule"]
```

`--beat` runs the scheduler inside this one worker. That's fine while there is
**exactly one** worker task. If you ever scale workers > 1, split beat into its
own single-replica service (see `deployment-django.md` §1) or you'll double-fire
every cron sweep.

```bash
aws ecs register-task-definition --region $AWS_REGION --cli-input-json file:///tmp/td-worker.json
```

### 13c. `bolo-migrate` (one-off)

Copy `td-web.json` to `td-migrate.json`: `family` → `${P}-migrate`; drop
`portMappings` + `healthCheck`; `awslogs-group` → `/ecs/${P}-migrate`;
`command` →

```json
"command": ["python","manage.py","migrate","--noinput"]
```

```bash
aws ecs register-task-definition --region $AWS_REGION --cli-input-json file:///tmp/td-migrate.json
```

> The `entrypoint.sh` in the image already waits for Postgres and *can* run
> migrations when `RUN_MIGRATIONS=1`. We keep `RUN_MIGRATIONS=0` on `web` and
> run migrations as this **separate, ordered, gated step** instead — so N web
> tasks never race to apply the same migration, and a failed migration fails the
> pipeline *before* any new code rolls.

---

## 14. Application Load Balancer

```bash
export ALB_ARN=$(aws elbv2 create-load-balancer --region $AWS_REGION \
  --name $P-alb --type application --scheme internet-facing \
  --subnets $SUBNET_A $SUBNET_B --security-groups $SG_ALB \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

export TG_ARN=$(aws elbv2 create-target-group --region $AWS_REGION \
  --name $P-web-tg --protocol HTTP --port 8000 --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-path /healthz --health-check-interval-seconds 30 \
  --healthy-threshold-count 2 --unhealthy-threshold-count 3 \
  --matcher HttpCode=200 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

aws elbv2 create-listener --region $AWS_REGION \
  --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN

export ALB_DNS=$(aws elbv2 describe-load-balancers --region $AWS_REGION \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)
echo "ALB_DNS=$ALB_DNS      # this is your API's public address"
```

`target-type ip` is required with Fargate (`awsvpc` networking) — the ALB
forwards to task IPs directly, no instance in between. Free-tier: one ALB,
750 hrs/month, 12 months.

---

## 15. ECS cluster + services

```bash
aws ecs create-cluster --region $AWS_REGION --cluster-name $P-cluster \
  --capacity-providers FARGATE FARGATE_SPOT \
  --default-capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1

# --- web service: behind the ALB ---
aws ecs create-service --region $AWS_REGION \
  --cluster $P-cluster --service-name $P-web \
  --task-definition $P-web \
  --desired-count 1 \
  --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$SG_ECS],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=web,containerPort=8000" \
  --health-check-grace-period-seconds 90 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},minimumHealthyPercent=100,maximumPercent=200"

# --- worker service: no ALB ---
aws ecs create-service --region $AWS_REGION \
  --cluster $P-cluster --service-name $P-worker \
  --task-definition $P-worker \
  --desired-count 1 \
  --capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$SG_ECS],assignPublicIp=ENABLED}" \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}"
```

`assignPublicIp=ENABLED` **is the no-NAT bit** — without it, a task in a public
subnet still has no route out and the image pull from ECR times out.

`deploymentCircuitBreaker` = if a new version's tasks never go healthy, ECS
aborts the rollout and reverts to the last good task-def revision automatically.

**Absolute-minimum variant (1 container instead of 2):** skip the `bolo-worker`
service and add `{ "name": "CELERY_TASK_ALWAYS_EAGER", "value": "1" }` to the web
task def. Background jobs then run inline in the web request (fine for a demo;
the audit-log write and notification fan-out just happen synchronously). The
scheduled sweeps won't run at all — acceptable for "show the pipeline works",
not for a realistic deployment.

---

## 16. First (manual) deploy + smoke test

The services above point at `:bootstrap`, which doesn't exist yet. Build and
push it once by hand, run migrations, then let the service pick it up.

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_URI

docker build -t $ECR_URI:bootstrap .
docker push $ECR_URI:bootstrap

# Run migrations as a one-off task and wait for it
TASK_ARN=$(aws ecs run-task --region $AWS_REGION \
  --cluster $P-cluster --task-definition $P-migrate --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$SG_ECS],assignPublicIp=ENABLED}" \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --region $AWS_REGION --cluster $P-cluster --tasks "$TASK_ARN"
aws ecs describe-tasks --region $AWS_REGION --cluster $P-cluster --tasks "$TASK_ARN" \
  --query 'tasks[0].containers[0].exitCode'      # must be 0

# Force the web + worker services to pull and run :bootstrap
aws ecs update-service --region $AWS_REGION --cluster $P-cluster --service $P-web    --force-new-deployment
aws ecs update-service --region $AWS_REGION --cluster $P-cluster --service $P-worker --force-new-deployment
aws ecs wait services-stable --region $AWS_REGION --cluster $P-cluster --services $P-web $P-worker
```

Smoke test:

```bash
curl -i  http://$ALB_DNS/healthz            # {"status": "ok"}
curl -i  http://$ALB_DNS/api/v1/docs/       # Swagger UI HTML, 200
curl -sI http://$ALB_DNS/api/v1/schema/     # 200

# create a superadmin to log into /admin (management command in this repo)
aws ecs run-task --region $AWS_REGION --cluster $P-cluster --task-definition $P-migrate \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET_A,$SUBNET_B],securityGroups=[$SG_ECS],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"web","command":["python","manage.py","createsuperuser","--noinput","--username","admin","--email","you@example.com"]}]}'
```

If a task won't start: **CloudWatch → Log groups → `/ecs/bolo-web`**, and
`aws ecs describe-services --cluster $P-cluster --services $P-web --query 'services[0].events[:5]'`.
See the troubleshooting table (§23).

---

## 17. Register the GitHub OIDC provider + repo secret

The OIDC *provider* was created in §10c. Now tell GitHub the role ARN:

- GitHub → your **backend** repo → **Settings → Secrets and variables → Actions**
  → **New repository secret**:
  - Name `AWS_DEPLOY_ROLE_ARN`, value = `$DEPLOY_ROLE_ARN` (the
    `arn:aws:iam::…:role/bolo-gha-deploy` from §10c).
- (Optional) **Settings → Environments → New environment** → `production`. Add
  yourself under **Required reviewers** if you want a manual "Approve" click
  before each deploy. The workflow below references `environment: production`;
  if you skip creating it, the job just runs without a gate.

No AWS access keys are ever stored in GitHub — the workflow trades a short-lived
GitHub OIDC token for temporary AWS credentials at run time.

---

## 18. The single-environment workflow

**Already committed** as **`.github/workflows/deploy-simple.yml`** on branch
`chore/aws-http-deploy-prep`, alongside (not replacing) the reference
`deploy.yml`. Before it can run you must **edit its `env:` block** — the
`SUBNETS` and `SECURITY_GROUP` values are `subnet-REPLACE_A,subnet-REPLACE_B`
and `sg-REPLACE_ECS` placeholders — and set the `AWS_DEPLOY_ROLE_ARN` repo
secret (§17). Full file for reference:

```yaml
name: Deploy to AWS ECS

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      image_tag:
        description: "Existing ECR tag to redeploy instead of building"
        required: false

permissions:
  id-token: write        # to mint the GitHub OIDC token
  contents: read

env:
  AWS_REGION:      ap-south-1
  ECR_REPOSITORY:  bolo-backend
  ECS_CLUSTER:     bolo-cluster
  WEB_SERVICE:     bolo-web
  WORKER_SERVICE:  bolo-worker
  WEB_FAMILY:      bolo-web
  WORKER_FAMILY:   bolo-worker
  MIGRATE_FAMILY:  bolo-migrate
  SUBNETS:         "subnet-aaaaaaaa,subnet-bbbbbbbb"   # SUBNET_A,SUBNET_B
  SECURITY_GROUP:  "sg-cccccccc"                        # SG_ECS

jobs:
  # 1. Build the image once, tag it with the commit SHA, push to ECR.
  build:
    runs-on: ubuntu-latest
    outputs:
      image: ${{ steps.out.outputs.image }}
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build & push (reuse if the tag already exists)
        id: out
        env:
          REGISTRY: ${{ steps.ecr.outputs.registry }}
          TAG: ${{ github.event.inputs.image_tag || github.sha }}
        run: |
          IMAGE="$REGISTRY/$ECR_REPOSITORY:$TAG"
          if aws ecr describe-images --repository-name "$ECR_REPOSITORY" \
               --image-ids imageTag="$TAG" >/dev/null 2>&1; then
            echo "reusing $IMAGE"
          else
            docker build -t "$IMAGE" .
            docker push "$IMAGE"
          fi
          echo "image=$IMAGE" >> "$GITHUB_OUTPUT"

  # 2. Migrate the DB, then roll web + worker onto the new image.
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: production        # delete this line if you didn't make the env
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Run migrations (one-off task, fail the job on a non-zero exit)
        run: |
          TASK_ARN=$(aws ecs run-task \
            --cluster "$ECS_CLUSTER" --task-definition "$MIGRATE_FAMILY" \
            --launch-type FARGATE \
            --network-configuration "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$SECURITY_GROUP],assignPublicIp=ENABLED}" \
            --query 'tasks[0].taskArn' --output text)
          echo "migrate task: $TASK_ARN"
          aws ecs wait tasks-stopped --cluster "$ECS_CLUSTER" --tasks "$TASK_ARN"
          EXIT=$(aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks "$TASK_ARN" \
            --query 'tasks[0].containers[0].exitCode' --output text)
          echo "migrate exit code: $EXIT"
          test "$EXIT" = "0"

      - name: Render new web task-def revision with the built image
        id: web
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition-family: ${{ env.WEB_FAMILY }}
          container-name: web
          image: ${{ needs.build.outputs.image }}
      - name: Deploy web service
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.web.outputs.task-definition }}
          cluster: ${{ env.ECS_CLUSTER }}
          service: ${{ env.WEB_SERVICE }}
          wait-for-service-stability: true

      - name: Render new worker task-def revision with the built image
        id: worker
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition-family: ${{ env.WORKER_FAMILY }}
          container-name: web            # the container is still named "web" in the worker td
          image: ${{ needs.build.outputs.image }}
      - name: Deploy worker service
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          task-definition: ${{ steps.worker.outputs.task-definition }}
          cluster: ${{ env.ECS_CLUSTER }}
          service: ${{ env.WORKER_SERVICE }}
          wait-for-service-stability: true
```

**What each part does:**

- `permissions: id-token: write` — lets the runner request an OIDC token. Without
  it, `configure-aws-credentials` can't assume the role.
- **`build` job** — logs into ECR with temp creds, builds your `Dockerfile`,
  tags with `github.sha` (immutable, traceable), pushes. Re-runs and
  `workflow_dispatch` with an explicit `image_tag` **reuse** an existing image
  instead of rebuilding — that's how a rollback redeploys a known-good SHA.
- **`deploy` job → migrations** — runs the `bolo-migrate` task def, waits for it
  to stop, reads the container exit code, and `test "$EXIT" = "0"` **fails the
  whole job** if the migration errored — before any new code rolls.
- **render + deploy (web, then worker)** — `render-task-definition` fetches the
  latest task def for the family and swaps in the new image, producing a new
  revision; `deploy-task-definition` registers it and calls `update-service`,
  then blocks on `wait-for-service-stability` (which goes red if the circuit
  breaker rolls back).
- **`environment: production`** — if you configured Required Reviewers, the
  `deploy` job parks and waits for your click. That's the difference between
  *continuous delivery* (human approves) and *continuous deployment* (fully
  automatic).

This is deliberately simpler than the repo's existing two-environment
`deploy.yml`. Once you're comfortable, that file shows the next step:
`build → deploy-staging (auto) → deploy-production (gated)`, promoting the
*identical* image object through both.

---

## 19. Run it and test it

```bash
git checkout -b chore/enable-cd
# edit .github/workflows/deploy-simple.yml -- the env: block SUBNETS +
# SECURITY_GROUP placeholders -- then:
git add .github/workflows/deploy-simple.yml
git commit -m "chore: fill in AWS ids for single-env ECS deploy"
git push -u origin chore/enable-cd
# open the PR, let CI (ci.yml) pass, merge to main
```

Merging to `main` triggers `deploy-simple.yml`. Watch it:

```bash
gh run watch          # or the repo's Actions tab
```

**Verify the deploy actually landed:**

```bash
# the running task should now be the new SHA-tagged image
aws ecs describe-services --region $AWS_REGION --cluster $P-cluster --services $P-web \
  --query 'services[0].taskDefinition'
aws ecs describe-task-definition --region $AWS_REGION --task-definition $P-web \
  --query 'taskDefinition.containerDefinitions[0].image'

curl -s http://$ALB_DNS/healthz
```

**Prove CD works with a real change:** edit a visible response string (e.g. a
`message` in some serializer or view), commit to a branch, PR, merge. Watch the
Action run `build → migrate → rolling deploy`, then `curl` the endpoint and see
the new string. During the roll, `curl` in a loop — you should see **zero
failed requests** (old tasks serve until new ones are healthy).

**Practise a rollback** (this is a great interview story):

```bash
# list recent revisions
aws ecs list-task-definitions --region $AWS_REGION --family-prefix $P-web --sort DESC

# option A: point the service back at the previous revision
aws ecs update-service --region $AWS_REGION --cluster $P-cluster --service $P-web \
  --task-definition $P-web:<PREVIOUS_NUMBER> --force-new-deployment

# option B: re-run the pipeline for an older commit's image
gh workflow run "Deploy to AWS ECS" -f image_tag=<OLD_SHA>
```

**Automatic rollback:** temporarily break the health check (e.g. deploy an image
whose `/healthz` 500s), push, and watch the ECS **deployment circuit breaker**
abort the rollout and revert — the GitHub job goes red on
`wait-for-service-stability`, so the failure is visible, not silent.

---

## 20. Deploy the React admin console (S3 + CloudFront)

Static SPA hosting: the build output (`dist/`) sits in a **private** S3 bucket;
**CloudFront** is the only thing allowed to read it (via Origin Access Control),
serves it worldwide over HTTPS, and gives you a free `*.cloudfront.net` URL.

### 20a. Bucket (private) + build

```bash
export SITE_BUCKET=$P-admin-console-$AWS_ACCOUNT_ID
aws s3api create-bucket --bucket $SITE_BUCKET --region $AWS_REGION \
  --create-bucket-configuration LocationConstraint=$AWS_REGION
aws s3api put-public-access-block --bucket $SITE_BUCKET \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

### 20b. CloudFront distribution with OAC

Easiest via the console (**CloudFront → Create distribution**):

- **Origin domain**: pick your `$SITE_BUCKET` (S3).
- **Origin access**: **Origin access control settings (recommended)** → create a
  new OAC. CloudFront shows a bucket-policy snippet — click **Copy policy** and
  paste it into **S3 → your bucket → Permissions → Bucket policy**. (It allows
  `s3:GetObject` only from this distribution's ARN.)
- **Viewer protocol policy**: Redirect HTTP to HTTPS.
- **Default root object**: `index.html`.
- **Custom error responses** (for client-side routing) — add two:
  - HTTP 403 → response page path `/index.html`, response code `200`.
  - HTTP 404 → response page path `/index.html`, response code `200`.
- Create. Note the **Distribution domain name** (`d1234abcd.cloudfront.net`) and
  the **Distribution ID** (`E1XXXXXXXXXXXX`).

### 20c. The console's own deploy workflow

In the **`bolo-admin-console`** repo, create an OIDC deploy role the same way as
§10c but scoped to just S3 + CloudFront-invalidation, with the trust policy
`sub` set to `repo:${GH_CONSOLE_REPO}:*`:

```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow",
    "Action": ["s3:PutObject","s3:DeleteObject","s3:ListBucket"],
    "Resource": ["arn:aws:s3:::bolo-admin-console-ACCT",
                 "arn:aws:s3:::bolo-admin-console-ACCT/*"] },
  { "Effect": "Allow",
    "Action": ["cloudfront:CreateInvalidation"],
    "Resource": "arn:aws:cloudfront::ACCT:distribution/E1XXXXXXXXXXXX" }
] }
```

Add `AWS_DEPLOY_ROLE_ARN` as a repo secret there, then
**`.github/workflows/deploy.yml`** in that repo:

```yaml
name: Deploy admin console

on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

env:
  AWS_REGION:      ap-south-1
  SITE_BUCKET:     bolo-admin-console-111122223333
  DISTRIBUTION_ID: E1XXXXXXXXXXXX
  VITE_API_URL:    https://d5678efgh.cloudfront.net   # the API's URL — see §21

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
      - run: npm ci
      - run: npm run build
        env:
          VITE_API_URL: ${{ env.VITE_API_URL }}
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      # hashed assets: cache forever. index.html: never cache (so new deploys show up)
      - run: |
          aws s3 sync dist/ "s3://$SITE_BUCKET/" --delete \
            --cache-control "public,max-age=31536000,immutable" --exclude index.html
          aws s3 cp dist/index.html "s3://$SITE_BUCKET/index.html" \
            --cache-control "no-cache"
      - run: aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths "/*"
```

Push to `main` → build → `s3 sync` → CloudFront invalidation → live at
`https://d1234abcd.cloudfront.net`. CloudFront's free tier (1 TB + 10M
req/month, perpetual) makes this effectively free indefinitely.

---

## 21. Wire the two together

The console (`https://dXXX.cloudfront.net`) calls the API from a **different
origin**, and the API authenticates with **httpOnly cookies**. Two things follow:

### 21a. The API needs HTTPS for the console to log in

Browsers only send a cross-site cookie if it's `SameSite=None; Secure`, and
`Secure` requires HTTPS. The HTTP-only ALB from §14 is fine for `curl`/Postman
and for demoing the pipeline, but the console can't hold a session against it.
Give the API an HTTPS front door with **another CloudFront distribution** (still
free, still no domain, no Route 53):

- **CloudFront → Create distribution.**
- **Origin domain**: `$ALB_DNS` (type it in — it's a "custom origin").
- **Protocol**: HTTP only (CloudFront → ALB leg; the ALB has no cert).
- **Add a custom header** on the origin: name `X-Client-Proto`, value `https`.
- **Cache policy**: `CachingDisabled` (it's an API).
- **Origin request policy**: `AllViewerExceptHostHeader` (forwards cookies,
  auth headers, query strings; keeps CloudFront's own Host toward the ALB).
- **Viewer protocol policy**: Redirect HTTP to HTTPS.
- Create → note the domain, e.g. `https://d5678efgh.cloudfront.net`. **That** is
  your `VITE_API_URL` in §20c.

Then tell Django to trust that custom header for the "was this HTTPS?" check
(CloudFront sets it; the ALB passes unknown headers through untouched, unlike the
standard `X-Forwarded-Proto` which it rewrites). The header name is already an
env var (§12b) — just set it on the `bolo-web` task def:

```
SECURE_PROXY_SSL_HEADER_NAME = HTTP_X_CLIENT_PROTO
```

Now you can drop the three HTTP-phase env entries from the `bolo-web` task def
(`SECURE_SSL_REDIRECT`, `COOKIE_SECURE`, `SECURE_HSTS_SECONDS`) so the secure
defaults apply, set `COOKIE_SECURE=True`, and add
`SESSION_COOKIE_SAMESITE=None` / the auth cookie's `SameSite=None` in settings
for the cross-site case. Redeploy via the pipeline.

### 21b. The API must allow the console's origin (CORS)

`prod.py` already wires `corsheaders` (§12c) — it just needs the origin list.
Set, in the `bolo-web` task def `environment`:

```
CORS_ALLOWED_ORIGINS = https://d1234abcd.cloudfront.net
ALLOWED_HOSTS        = d5678efgh.cloudfront.net,<ALB_DNS>
```

(`ALLOWED_HOSTS` now names the API's CloudFront host and the ALB DNS instead of
`*` — the §13 hardening promise.)

### 21c. Final shape

```
 https://d1234abcd.cloudfront.net   (console)  ──calls──►  https://d5678efgh.cloudfront.net   (API)
        │                                                          │  origin: ALB DNS, +header X-Client-Proto: https
   S3 (private, OAC)                                          ALB :80  ──►  ECS bolo-web  ──►  RDS / Redis
```

---

## 22. Tear down (do this between sessions — it's how you stay at $0)

Delete in roughly reverse order. The **continuously-billing** items are ECS
tasks, RDS, ElastiCache, and the ALB — kill those first.

```bash
# ECS: stop paying for Fargate immediately
aws ecs update-service --region $AWS_REGION --cluster $P-cluster --service $P-web    --desired-count 0
aws ecs update-service --region $AWS_REGION --cluster $P-cluster --service $P-worker --desired-count 0
aws ecs delete-service --region $AWS_REGION --cluster $P-cluster --service $P-web    --force
aws ecs delete-service --region $AWS_REGION --cluster $P-cluster --service $P-worker --force
aws ecs delete-cluster --region $AWS_REGION --cluster $P-cluster

# Load balancer + target group
aws elbv2 delete-load-balancer --region $AWS_REGION --load-balancer-arn $ALB_ARN
aws elbv2 delete-target-group  --region $AWS_REGION --target-group-arn $TG_ARN

# Data stores (skip final snapshot to avoid snapshot storage cost)
aws rds delete-db-instance --region $AWS_REGION --db-instance-identifier $P-pg \
  --skip-final-snapshot --delete-automated-backups
aws elasticache delete-cache-cluster --region $AWS_REGION --cache-cluster-id $P-redis

# CloudFront: disable, then delete (must disable + wait first, easiest in console)
# S3: aws s3 rb s3://$SITE_BUCKET --force ; aws s3 rb s3://$P-media-$AWS_ACCOUNT_ID --force
# ECR:  aws ecr delete-repository --repository-name $P-backend --force
# Logs: for g in web worker migrate; do aws logs delete-log-group --log-group-name /ecs/$P-$g; done
```

Leave these — they cost nothing idle: the VPC/subnets/IGW, the security groups,
the IAM roles + OIDC provider, SSM parameters. Recreating just RDS + Redis + ECS
+ ALB next time takes ~20 minutes (script it).

**What actually costs money if you forget:** an idle ALB (~$0.025/hr ≈ $16/mo
after the free 750 hrs), an idle RDS/Redis instance (past 750 hrs), and any
**unattached Elastic IP**. The Zero-Spend Budget alarm from §1 emails you within
a day if any of it slips past free tier.

---

## 23. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Task stuck `PROVISIONING` → `STOPPED`, no logs | Can't pull image: no route out | `assignPublicIp=ENABLED` missing, or task in a private subnet |
| `STOPPED` reason `ResourceInitializationError: unable to pull secrets` | Execution role can't read SSM / KMS | Re-check the `ssm-read` inline policy on `bolo-ecs-execution`; param path must be `/bolo/*` |
| Task runs then dies, log says `ImproperlyConfigured: set the ... environment variable` | A required env var/secret is missing | Add it to the task def `secrets`/`environment`; every one in `.env.example` that has no default is required |
| Log: `DisallowedHost` / 400 on `/healthz` | `ALLOWED_HOSTS` doesn't include the health-check Host (the task IP) | Phase 1: `ALLOWED_HOSTS=*`. Phase 2: rely on the container `healthCheck` + list real hosts |
| Infinite redirect / `curl` shows 301 loop | `SECURE_SSL_REDIRECT=True` with an HTTP-only ALB | Set `SECURE_SSL_REDIRECT=False` in the task def (needs the §12b patch) |
| Target group shows tasks `unhealthy`, ECS keeps replacing them | Health check path/port wrong, or app slow to boot | Path `/healthz`, port 8000, `--health-check-grace-period-seconds 90`, `startPeriod` 60 |
| GitHub Action: `Not authorized to perform sts:AssumeRoleWithWebIdentity` | Trust policy `sub` doesn't match | It must be `repo:<owner>/<repo>:*` exactly; check the OIDC provider ARN too |
| Action: `is not authorized to perform: iam:PassRole` | Deploy role missing `PassRole` for the exec/task roles | Add both ARNs to the `PassRoles` statement in §10c |
| `migrate` task exit code `1` | A real migration error, or DB unreachable | Read `/ecs/bolo-migrate` logs; check `SG_RDS` allows `SG_ECS`; check `DATABASE_URL` |
| Console gets CORS error in browser console | `CORS_ALLOWED_ORIGINS` doesn't list the CloudFront origin, or `corsheaders` not in prod | §21b |
| Console login "works" but next request is 401 | Cross-site cookie not stored — needs `Secure` + `SameSite=None` + HTTPS on the API | §21a (put CloudFront in front of the ALB) |
| Surprise charge | Idle ALB / RDS past 750 hrs, unattached EIP, NAT Gateway | Budget alarm email; run §22 teardown; you never created a NAT — confirm with `aws ec2 describe-nat-gateways` |

---

## 24. For your resume / interview

**Resume bullets (adapt the numbers to what you actually run):**

- Built a zero-downtime CI/CD pipeline (GitHub Actions → Amazon ECR → ECS
  Fargate) that builds an immutable commit-SHA-tagged Docker image, runs Django
  migrations as a gated pre-deploy step, and performs a rolling service update
  behind an Application Load Balancer, with automatic rollback via the ECS
  deployment circuit breaker.
- Authenticated GitHub Actions to AWS with **OIDC federation and short-lived
  role assumption** — no long-lived cloud credentials stored in the CI system.
- Ran the workload without a NAT Gateway by placing Fargate tasks in public
  subnets with security-group-only ingress, cutting fixed monthly cost to ~$0
  on the AWS free tier.
- Managed configuration and secrets via **SSM Parameter Store** injected into
  ECS task definitions at container start; shipped structured JSON logs to
  CloudWatch Logs with request/tenant/actor correlation IDs.
- Deployed the React admin SPA to **S3 + CloudFront** (private bucket, Origin
  Access Control, SPA fallback routing) with cache-busting invalidations on
  every deploy.

**Questions you should be able to answer:**

- *Why ECR + ECS + Fargate and not just an EC2 box?* — ECR stores the image;
  ECS schedules and supervises containers; Fargate removes the EC2 host you'd
  otherwise patch and scale. One artifact, declarative desired-count, rolling
  deploys and health checks for free.
- *How is this zero-downtime?* — `minimumHealthyPercent=100`, `maximumPercent=200`:
  ECS starts new tasks, waits for their ALB health checks, shifts traffic, then
  drains old ones. gunicorn also recycles workers (`max_requests`) and reuses DB
  connections (`CONN_MAX_AGE`).
- *How do migrations fit in?* — A separate one-off Fargate task **before** the
  code roll, whose exit code gates the pipeline. Migrations are
  backward-compatible (expand/contract) so old and new code run against the same
  schema during the roll.
- *Why OIDC instead of an access key in GitHub secrets?* — No standing
  credential to leak or rotate; the trust policy pins it to one repo, and the
  token AWS issues lasts minutes.
- *How did you avoid the NAT Gateway cost, and what's the trade-off?* — Public
  subnet + `assignPublicIp` + strict SGs. Trade-off: the task has an outbound
  public IP (larger surface than private subnet + NAT). Production with a budget
  → private subnets + NAT or VPC endpoints.
- *How would you add staging?* — The two-environment `deploy.yml` already in the
  repo: `build` once → `deploy-staging` automatically → `deploy-production`
  behind a GitHub Environment "Required reviewers" gate, promoting the **same
  image object**, each environment migrating its own RDS first.
- *Rollback?* — Re-point the ECS service at the previous task-def revision, or
  re-run the pipeline with an older `image_tag`. DB isn't rolled back — that's
  why migrations are expand/contract.

---

## 25. Cost cheat-sheet

| Service | Free allowance | If you blow past it |
|---|---|---|
| Fargate | none (Spot ~70% off) | ~$9/mo per always-on 0.25vCPU/0.5GB task |
| RDS `db.t4g.micro` | 750 hrs/mo, 20 GB (12 mo) | ~$12/mo |
| ElastiCache `t3.micro` | 750 hrs/mo (12 mo) | ~$12/mo |
| ALB | 750 hrs/mo + 15 LCU (12 mo) | ~$16/mo + LCU |
| ECR | 500 MB-month (12 mo) | $0.10/GB-month |
| CloudWatch Logs | 5 GB ingest+store | $0.50/GB ingest |
| S3 | 5 GB, 20k GET, 2k PUT (12 mo) | pennies |
| **CloudFront** | **1 TB + 10M req/mo — always free** | $0.085/GB after |
| SSM Parameter Store (standard) | free | — |
| VPC / subnets / IGW / SG / IAM | free | — |
| **NAT Gateway** | **none — not used** | ~$32/mo + $0.045/GB |
| Route 53 | none — not used | $0.50/zone/mo |
| Secrets Manager | none — not used (SSM instead) | $0.40/secret/mo |

Keep the Zero-Spend Budget alarm on. Run §22 teardown whenever you stop working.
```
