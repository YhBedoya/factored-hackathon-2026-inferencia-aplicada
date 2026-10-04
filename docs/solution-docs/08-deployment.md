# 08 — Deployment (AWS v0)

The deployment strategy for the public URL (K2). It was decided on 2026-09-28 and is recorded in ADR-017. Cards that build on it: **D4-A5** (deploy v0), **D6** (cost guard: turn caps and kill switch) and **D8** (final deploy and demo reset).

**Amended 2026-10-03 (ADR-017):** the deployment moves to the team's AWS project (the "new AWS experience"), which allows Regional resources **only in us-east-2** and is on the **Free plan** (USD 100 in credits). The Free plan allows only small EC2 types, so the box is an **m7i-flex.large** (2 vCPU, 8 GiB). §2 keeps the original us-east-1 comparison as the record of the 2026-09-28 decision.

Anything marked **(proposed)** is a default this doc picks that the team has not confirmed yet. The D4-A5 spec confirms or changes it. Anything marked **OPEN** is listed in §15.

---

## 1. Decision summary

| Topic | Decision |
|---|---|
| Shape | **One EC2 instance running the prod Docker Compose layer** (Option A in §2) |
| Region | **us-east-2** for everything: EC2, our S3 bucket, SSM and Bedrock (the project allows no other Region). `make` targets read `DEPLOY_REGION` (default `us-east-2`) |
| Instance | **m7i-flex.large** (2 vCPU, 8 GiB), the largest type the Free plan allows; default VPC public subnet, Elastic IP. `INSTANCE_TYPE` overrides it on a paid plan |
| OS | Ubuntu 24.04 LTS **(proposed)**. Docker's apt repository ships the Engine, Compose and Buildx plugins, and the SSM Agent comes preinstalled |
| Disk | One 80 GB gp3 root volume **(proposed)**, sized in §6 |
| Data source | **Our own S3 bucket** in us-east-2, holding a one-time copy of the organizers' `data/` prefix (§5). The deployment never reads the organizers' bucket |
| Golden DB | Built **on the box** with `make data` from our bucket, so the date shift lands on the deploy date (§6) |
| AWS access | An **IAM instance role** (S3 read, Bedrock invoke, SSM). No long-lived AWS keys on the box |
| LLM | `LLM_PROVIDER=bedrock` from us-east-2, through a `us.` cross-region inference profile (ADR-028). `nlu` and `agent` use Sonnet 4.6 there, because the project cannot call the Claude 5 family (ADR-017 amended 2026-10-04) |
| DNS / TLS | `<ip-with-dashes>.sslip.io` with a Let's Encrypt certificate. **Fallback: a Route 53 domain** pointed at the same Elastic IP (§8) |
| Secrets | SSM Parameter Store SecureStrings, written to a `0600` `.env` on the box at deploy time (§9) |
| Operator access | SSM Session Manager. **No SSH port open** |
| Observability | The OTel → Victoria → Grafana overlay runs on the box. It isn't exposed publicly and is reached through SSM port forwarding |
| Langfuse | **Not on the public deployment** (ADR-006 decided). `audit.llm_calls` stays the public record of every call, and Langfuse stays local |
| Cost | About **$80/month** (about $2.6/day) plus Bedrock usage, paid from the Free plan's USD 100 credits (§12) |

## 2. Why this option (evidence)

### Facts measured in this repo (2026-09-28)

| Fact | Value | Source |
|---|---|---|
| Postgres data | `latam_app` 7.8 GB + `latam_golden` 7.8 GB ≈ **15.5 GB**. `bank.digital_events` alone is 4.9 GB and `bank.transactions` 1.8 GB | `pg_database_size`, `pg_total_relation_size` |
| RAM of the services prod runs | backend 232 MiB, postgres 350, redis 14, nginx 11, VictoriaMetrics/Logs/Traces ≈ 200, otel-collector 50, grafana 204 → **≈ 1.1 GiB** | `docker stats` on the dev stack |
| Dataset to copy | **7,671 CSV files, 5.35 GB** | the local mirror under `data/` |
| Pipeline scratch space | `data/pipeline.duckdb` 6.2 GB, `data/raw/` Parquet 1.4 GB | `du` |
| dbt run time | ≈ 8 min (69 models and tests) on the 15 GiB dev box | `make data` log |
| demo-reset | `DROP DATABASE … WITH (FORCE)` + `CREATE DATABASE latam_app TEMPLATE latam_golden` | `pipeline/load/demo_reset.py:48-49` |
| Prod cookies | `Secure` when `APP_ENV=prod`, so **login needs HTTPS** | `backend/app/api/v1/auth.py:75` |
| SSE | Chat streams over SSE with a `: ping` keepalive | `backend/app/api/v1/conversations.py:229-238` |

### What the rules ask for
- "It works" is judged first and foremost (K6). The deployment has to be a link to where the tool runs (K2).
- The submission "is not expected to operate a live banking service". It must show "evidence of production readiness and an honest account of the work required before deployment" (problem statement, S6).
- A reproducible setup (D6.4), plus a written explanation of capacity limits, monitoring, access controls, data retention and remaining deployment work (D6.5).

### Options compared (us-east-1 on-demand prices, September 2026)

| | **A. Single EC2 + Compose (chosen)** | B. ECS Fargate (Express Mode) + RDS + ElastiCache | C. EC2 + Compose for the app, RDS for Postgres |
|---|---|---|---|
| Monthly cost | ≈ $131 (§12) | ≈ $135–150, plus ≈ $33 for a NAT gateway if tasks sit in private subnets | ≈ $94 on a t3.medium app host |
| Same artifact as dev and README | ✅ The same Compose files | ❌ Task definitions, ECR and Secrets Manager: a second way of running the app | Partly |
| demo-reset unchanged | ✅ We are the Postgres superuser | ⚠️ The RDS master user is `rds_superuser`, so `WITH (FORCE)` needs checking | ⚠️ Same as B |
| Golden DB load | `make data` on the box | 15.5 GB `pg_restore` from inside the VPC | Same as B |
| Victoria/Grafana stack | ✅ Unchanged | ❌ Replaced by CloudWatch, or more tasks with EFS | ✅ |
| SSE | Nginx settings only | The ALB idle timeout defaults to 60 s | Nginx settings only |
| High availability | ❌ Single instance, single AZ | ✅ Multi-AZ possible | App ❌, DB ✅ |
| Setup effort | Fits in D4-A5 | 1–2 days, at risk of "Deploy slips" (07 risks) | Between A and B |

Ruled out:
- **AWS App Runner** stopped accepting new customers on 2026-04-30.
- **Lightsail** instances don't use EC2 instance profiles, so Bedrock would need static access keys, which breaks ADR-017's IAM-role constraint.

Why A: it deploys the same artifact the judges can reproduce, keeps demo-reset and observability unchanged, is sized from measured usage, and fits in one task. Option B is not thrown away. It becomes the documented path to production in §14, which is the honest "remaining work" S6 asks for.

## 3. Architecture

```
                         Internet
                            │  443 (TLS), 80 (ACME challenge + redirect)
                 ┌──────────▼───────────────────────────────────────────┐
                 │ EC2 m7i-flex.large · us-east-2 · EIP · SG: 80/443     │
                 │                                                       │
                 │  nginx ── static SPA (frontend build)                 │
                 │    └── /api/ ──► backend (FastAPI, APP_ENV=prod) ──────┼──► Bedrock (us. inference profile)
                 │                     │        │                        │     via instance role
                 │                  postgres  redis                      │
                 │         (latam_app, latam_golden)                     │
                 │  otel-collector ─► VictoriaMetrics/Logs/Traces ◄─ grafana (127.0.0.1 only)
                 │                                                       │
                 │  host: uv pipeline (make data) ◄──────────────────────┼──► S3 (our bucket, us-east-2)
                 └───────────────────────────────────────────────────────┘
   Operators: SSM Session Manager (shell + port forwarding). Secrets: SSM Parameter Store.
```

## 4. AWS resources

| Resource | Configuration |
|---|---|
| **S3 bucket** (our data) | us-east-2, Block Public Access on, SSE-S3 default encryption. Prefix `data/` mirrors the organizers' layout. It outlives the instance stack (retain on delete). The bucket name lives in `.env` and SSM, never in the repo **(proposed, same treatment as the organizers' bucket)** |
| **EC2 instance** | m7i-flex.large, Ubuntu 24.04, **IMDSv2 required with hop limit 2** (the backend container needs role credentials, and the extra network hop from Docker's bridge network needs a hop limit of 2), termination protection on during judging |
| **EBS** | 80 GB gp3 root volume |
| **Elastic IP** | Fixed IP, so the sslip.io name and any fallback DNS record stay stable across stop/start |
| **Security group** | Inbound TCP 80 and 443 from `0.0.0.0/0` only. Outbound: all |
| **IAM role + instance profile** | See the policy below |
| **SSM Parameter Store** | SecureStrings under `/swip/prod/` **(proposed path)** (§9) |
| **AWS Budgets** | A monthly cost budget with an actual and a forecast alert to both team members (ADR-023). Threshold: **$90** (above the ≈ $80 forecast, below the Free plan's USD 100 credits; `MONTHLY_BUDGET_USD` overrides it) |
| **Route 53** | Only if the sslip.io fallback is triggered (§8) |

**Instance role policy (least privilege)**
- `AmazonSSMManagedInstanceCore` (the managed policy), for Session Manager and `send-command`.
- `s3:ListBucket` on our bucket with an `s3:prefix` condition of `data/*`, and `s3:GetObject` on `arn:aws:s3:::<bucket>/data/*`. Read-only.
- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on:
  - the `us.` **inference-profile** ARNs in us-east-2 for exactly the model IDs pinned in the `core/llm` registry, and
  - the matching **foundation-model** ARNs in every region the profile routes to.

  Newer Claude models such as Haiku 4.5 are invoked through a cross-region inference profile, so a policy that only covers the foundation model fails with `AccessDeniedException`. The exact model IDs are deferred to the dev benchmark (decision log), so the policy is updated whenever the registry changes.
- `ssm:GetParametersByPath` on `/swip/prod/*`.

## 5. Data: from the organizers' S3 to ours (one-time)

**Why:** the deployment must not depend on the organizers' bucket, their credentials or cross-region traffic. Once copied, the box reads its data from the same region under its own role. Nothing in the code changes: `pipeline/ingest/s3.py` already reads `S3_BUCKET` and `S3_PREFIX` from the environment, and boto3's default credential chain picks up the instance role.

**Steps (run once from a laptop):**
1. **Download fresh** from the organizers into a clean staging folder outside the repo, using the organizer credentials from the data dictionary (env vars or a profile, never written down):
   `aws s3 sync s3://<organizers-bucket>/data/ <staging>/data/`
2. **Upload** with the team's AWS profile:
   `aws s3 sync <staging>/data/ s3://<our-bucket>/data/`
3. **Verify**: the file count (7,671) and the key + size listing match the source. **Compare sizes, not ETags**: a multipart upload's ETag depends on part size, so ETags can differ between the two buckets for byte-identical files.
4. **Record provenance** for 03 §1: save the source listing (key, size, ETag, listing date) and the copy date. Keep the organizers' bucket name out of any committed file.

> ⚠️ **Never sync the repo's `data/` folder to S3.** Besides the CSV mirror it holds `data/secrets/credentials.csv` (every customer's demo password), `data/raw/`, `data/_parquet/` and `pipeline.duckdb`. `credentials.csv` is itself a `.csv`, so an `--include "*.csv"` filter would upload it too. Always upload from the clean staging folder.

**Cost:** 5.35 GB × $0.023/GB-month ≈ $0.12/month. Transfer from S3 to EC2 in the same region costs nothing.

## 6. Building the data on the box

`make data` runs on the host (through `uv`, not inside a container) against our bucket: ingest → contracts → dbt → load → `seed-identity` → golden snapshot → demo reset (03 §2).

- **First deploy order:** start only `postgres` and `redis`, run `make data`, then start the full prod stack. That keeps DuckDB's memory away from a running app on the 8 GiB box. DuckDB is already capped at `memory_limit = 3GB` (`pipeline/dbt/profiles.yml`, `pipeline/load/postgres.py`) and spills to disk, so the run fits next to Postgres's 2 GB `shared_buffers`. Measure the run time on the first deploy.
- **Date shift:** the whole-week offset is computed from the load date (ADR-010, 03 §5). Re-run `make data` on the box on **D8, before the code freeze**, so the data ends in submission week. After that the data ages with the real clock, which the app already handles.
- **Persona passwords stay stable:** passwords come from `CREDENTIALS_SEED` (03 §8). The box must use **the same seed** as the credentials sent to the judges. That's why the seed lives in SSM (§9): a rebuilt instance produces the same passwords.
- **CPU:** m7i-flex instances have no CPU credits to run out of. They give a 40% baseline per vCPU and can use the full core most of the time, so a long pipeline run is slower than on 4 vCPU but costs nothing extra.

**Disk budget (80 GB):** Postgres 15.5 GB (+ WAL and growth) · DuckDB 6.2 GB · Parquet 1.4 GB · CSV temp files (one at a time) · Docker images and build cache ≈ 5–8 GB · Victoria data · OS ≈ 5 GB. That leaves more than 35 GB free for a second golden rebuild or a temporary eval database (7.8 GB each).

## 7. The prod Compose layer

New file `docker/docker-compose.prod.yml`, already expected by 01 §9 and 06 §3. It is layered as **base → observability → prod** (no dev overlay; prod comes last so its `!override` port lists win over the ones observability re-adds). A `COMPOSE_PROD` variable goes in the Makefile.

| Service | Prod settings |
|---|---|
| `backend` | No `--reload`. `APP_ENV=prod` (disables `/test-idp`, which `test_r1_routes.py` asserts, and turns on `Secure` cookies). `LLM_PROVIDER=bedrock`, `AWS_REGION=us-east-2`. **Mounts `../policies:/policies:ro`** exactly as dev does: the image doesn't contain `policies/`, and `card_select.py` resolves them at `/policies`. `restart: unless-stopped`. Uvicorn worker count **(OPEN)**: start with 1 and measure |
| `nginx` | A **prod image** **(proposed: `docker/nginx/Dockerfile.prod`, multi-stage)** that runs `npm ci && npm run build` on `node:22`, then copies `dist/` into `nginx:1.27-alpine`. Config `docker/nginx/prod.conf`: port 80 serves `/.well-known/acme-challenge/` and redirects everything else to 443. Port 443 terminates TLS, serves the SPA with `try_files $uri /index.html`, and proxies `/api/` with SSE-safe settings: `proxy_http_version 1.1`, `proxy_set_header Connection ""`, `proxy_buffering off`, `proxy_cache off`, and a `proxy_read_timeout` well above the `: ping` interval. Adds HSTS and basic security headers |
| `postgres` | Port bound to **`127.0.0.1:5432`** only (the host pipeline needs it). Data in the named volume on EBS. Memory tuning such as `shared_buffers` **(proposed: 2 GB)** |
| `redis` | No published port |
| `frontend` | **Not run.** The dev Vite server (784 MiB) is replaced by the static build in `nginx` |
| observability | The existing overlay, with every published port rebound to `127.0.0.1` |
| `analytics-worker` | The interaction-analytics worker loop (`python -m app.domains.analytics.worker`). Memory limit **512 MiB**, database pool of 3 connections, `restart: unless-stopped`. Connects as the `analytics_worker` role |
| `certbot` | Issues and renews the certificate through the HTTP-01 webroot shared with `nginx` (§8) |

**Ports:** the base and observability files publish ports on all interfaces (`5432`, `8428`, `9428`, `10428`, `3000`). The prod overlay has to **replace** those lists, not add to them, using Compose's `!override` / `!reset` YAML tags (Docker Compose ≥ 2.24). The security group already blocks these ports. The overlay is the second guard, because Docker's port publishing bypasses host firewalls such as ufw.

**Grafana access:** only through `aws ssm start-session --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000`. Grafana's anonymous Viewer access is acceptable only because Grafana is never exposed.

## 8. DNS and TLS

- **Hostname:** `<a-b-c-d>.sslip.io`, where `a-b-c-d` is the Elastic IP with dashes. sslip.io resolves it to that IP with no DNS setup. It is set as `PUBLIC_HOST` **(proposed name)** and used by Nginx's `server_name` and by certbot.
- **Certificate:** Let's Encrypt through certbot (HTTP-01 webroot). **Run against the Let's Encrypt staging environment first**, and only request the real certificate once staging passes, so we don't use up quota. Renewal runs on a daily timer followed by an Nginx reload. Let's Encrypt certificates are valid for 90 days.
- **Known risk:** sslip.io is deliberately left off the Public Suffix List, so **every sslip.io certificate worldwide shares one Let's Encrypt rate limit**, and that limit has run out before (sslip.io issue #108).
- **Fallback (decided):** if issuance is rate-limited, register a cheap domain in Route 53, add an A record pointing at the same Elastic IP, change `PUBLIC_HOST`, and issue again. Nothing else changes. Cookies are host-only, so users simply log in again.
- **Plain HTTP is not a fallback.** Prod cookies are `Secure` (§2), so login doesn't work without HTTPS.

## 9. Secrets and configuration

The box's `.env` is **rendered at deploy time** from SSM Parameter Store (`aws ssm get-parameters-by-path --with-decryption`), written with mode `0600` and never printed (R10). SSM is used instead of a hand-made `.env` so that a rebuilt instance gets **identical** secrets. That matters most for `CREDENTIALS_SEED` and `IDENTITY_HMAC_KEY`, which the judges' persona credentials depend on. Standard-tier parameters cost nothing extra.

| Variable | Where it comes from |
|---|---|
| `JWT_SECRET`, `IDENTITY_HMAC_KEY`, `CREDENTIALS_SEED` | SSM SecureString. The seed must equal the one behind the credentials sent to the judges |
| `DEMO_OTP_CODE` | SSM SecureString (ADR-008) |
| `PII_VAULT_KEY` | SSM SecureString at `/swip/prod/PII_VAULT_KEY`, a Fernet key. Losing it makes the vault rows and the encrypted message content unreadable, so back it up with the other secrets |
| `POSTGRES_PASSWORD` | SSM SecureString. **Not** the dev default `postgres`. `DATABASE_URL` and `GOLDEN_DATABASE_URL` are built from it |
| `ANALYTICS_DB_PASSWORD` | SSM SecureString at `/swip/prod/ANALYTICS_DB_PASSWORD`. Password of the Postgres role `analytics_worker`; migration `0009` reads it to set the role's password. `ANALYTICS_DATABASE_URL` is built from it in Compose |
| `S3_BUCKET` | SSM (our bucket) |
| `APP_ENV=prod`, `LLM_PROVIDER=bedrock`, `AWS_REGION=us-east-2`, `S3_PREFIX=data`, `BANK=postgres`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `PUBLIC_HOST`, session and rate-limit values | Plain values in a committed template **(proposed: `.env.prod.example`)** |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROFILE`, `ANTHROPIC_API_KEY`, organizer credentials | **Absent.** The instance role supplies AWS credentials, and the Anthropic API isn't used in prod (ADR-028) |

## 10. Provisioning and deploy workflow

**Infrastructure as code (proposed):** one CloudFormation template, `infra/aws/ec2-stack.yaml`. It creates the security group, the IAM role and instance profile, the EC2 instance with IMDSv2 and user data, the Elastic IP and the Budget. User data installs Docker Engine with the Compose and Buildx plugins, git, make and uv, then clones the public repo. We chose CloudFormation because it needs no extra tool on the laptops and `delete-stack` tears everything down. The bucket and SSM parameters are created outside the stack so they survive a teardown. Makefile targets **(proposed)**: `infra-up`, `infra-down`.

**First deploy (runbook):**
1. Copy the data to our bucket (§5) and write the SSM parameters (§9).
2. `make infra-up` → the instance boots with the repo cloned.
3. SSM session → render `.env` → start `postgres` + `redis` → `make data` (§6).
4. Issue the certificate (§8), then start the full prod stack.
5. Smoke test: `GET /api/v1/health` returns 200 over HTTPS, a persona logs in, and one chat turn streams through SSE and reaches Bedrock (visible in the ledger: `SELECT provider, model_id, status FROM audit.llm_calls ORDER BY at DESC LIMIT 5` shows `bedrock`).

**Redeploy: `make deploy` on the box (proposed):**
1. `git fetch` and check out the deploy ref **(OPEN: `main` or a release tag)**.
2. Render `.env` from SSM.
3. `docker compose -f base -f observability -f prod build` and `up -d --wait`.
4. Run Alembic migrations on `latam_app` **and** `latam_golden`, so demo-reset doesn't bring back an old schema.
5. Run the smoke test above.

A laptop-side wrapper **(proposed: `make deploy-remote`)** runs the same thing through `aws ssm send-command`.

**Demo reset:** there is an admin-protected endpoint (07 D4-A5) and `make demo-reset` on the box. Both drop active connections (`WITH (FORCE)`) and copy 7.8 GB, so the app is briefly unavailable. Measure how long on the first deploy.

**Rollback:** check out the previous ref and run `make deploy`. If a migration broke the data, rebuild with `make data`: the golden DB can always be rebuilt from our bucket.

## 11. Security posture (D6.5 access controls)

- Public surface: 80 and 443 only. No SSH: operators use SSM, and every session is logged by AWS.
- IMDSv2 only. The role is least-privilege (§4). There are no long-lived AWS keys on the box or in the repo.
- Postgres, Redis, Grafana and the Victoria services are bound to localhost and blocked by the security group.
- `APP_ENV=prod` turns off `/test-idp` and turns on `Secure` cookies. JWTs are in httpOnly cookies with CSRF protection (ADR-008).
- Secrets live in SSM SecureStrings and a `0600` `.env`. The data bucket is private and encrypted.
- Cost guard (ADR-023): a Budgets alarm here, and the turn caps and `LLM_DISABLED` kill switch on D6.
- Staff panel protection: **decided (D4-A, ADR-008 amended 2026-09-28).** Seeded staff accounts (one agent per handoff queue plus one admin) log in with `POST /auth/staff/login`, get the same httpOnly cookie + CSRF session with role `agent` or `admin`, and every `/staff/*` and `/admin/*` router declares `require_role` (R13). Staff passwords derive from `CREDENTIALS_SEED`, so a rebuilt box keeps them.

## 12. Cost (us-east-2 on-demand, checked 2026-10-03 with the AWS Pricing API)

| Item | Monthly |
|---|---|
| EC2 m7i-flex.large ($0.09576/h × 730 h) | $69.90 |
| EBS gp3, 80 GB × $0.08 | $6.40 |
| Public IPv4 (Elastic IP), $0.005/h | $3.65 |
| S3, 5.35 GB | $0.12 |
| SSM Parameter Store (standard), Session Manager | $0 |
| **Infrastructure total** | **≈ $80.1/month ≈ $2.6/day**. The USD 100 Free plan credits cover about 5 weeks of uptime |
| Bedrock | Per token, bounded by ADR-023's caps and kill switch. Reported per case and per resolution in the eval (E9) |

Stopping the instance outside the judging window stops the EC2 charge. EBS and the Elastic IP (≈ $10/month) keep billing.

## 13. Capacity, recovery and retention (D6.5)

- **Capacity:** one instance and one AZ. Throughput (turns/s) and p50/p95 latency are measured by the eval harness against the deployed stack. Bedrock throughput is capped by the account's tokens-per-minute quota for the model (check Service Quotas on D4). The prod services currently use ≈ 1.1 GiB of 8 GiB.
- **Recovery:** if the instance is lost, the rebuild is `make infra-up` + `make data` + the certificate, from our bucket and SSM. Recovery time is to be measured on the first deploy. The app DB is **disposable by design**: it is synthetic and demo-reset restores it, so there's no backup job. The only state lost is what was changed in the app since the last reset.
- **Retention:** conversation and audit rows live in `latam_app` until the next demo reset. The Victoria stores use their default retention on the instance's disk. No customer data is real (B1).

## 14. Path to production (remaining work, S6)

What a real deployment would add, which is roughly Option B in §2 plus operations work:
- ECS on Fargate across 2 or more AZs behind an ALB, with ACM certificates and AWS WAF. Images in ECR, built and signed by CI, with no builds on the host.
- RDS PostgreSQL Multi-AZ with point-in-time recovery, and ElastiCache for Redis.
- Private subnets with VPC endpoints for Bedrock and S3 (no NAT for AWS traffic), and Secrets Manager with rotation.
- CloudWatch alarms and on-call, log retention policies, and Langfuse on its own host sized to its published minimum (≥ 4 cores and 16 GiB for Langfuse alone).
- Load testing and a quota plan for Bedrock (provisioned throughput or raised quotas).
- A security review and pentest, and the items already listed in 01 §9: a real IdP, regulatory review of disputes, and workforce integration.

## 15. Open items for the D4-A5 spec

Every item below, and every **(proposed)** default in §1–§10, was **confirmed by the D4-A5 spec** (`docs/specs/d4-a-escalation-handoff-deploy.md`, D19–D20) on 2026-09-28.

| Item | Decision |
|---|---|
| Staff panel protection before the URL is public | **Decided:** seeded staff accounts + `POST /auth/staff/login`, roles `agent`/`admin` (ADR-008 amended 2026-09-28, §11) |
| Uvicorn worker count | **Confirmed:** 1 to start, measured with the eval harness |
| DuckDB `memory_limit` for `make data` on 16 GiB | **Confirmed:** only if the first run is OOM-killed. **Superseded 2026-10-03:** the pipeline already caps DuckDB at 3 GB, which the 8 GiB box relies on (§6) |
| Deploy ref | **Confirmed:** `main` for D4, a release tag for the D8 freeze |
| CloudFormation vs. a scripted AWS CLI setup | **Confirmed:** CloudFormation (§10) |
| Budget threshold | **Confirmed:** $150/month. **Amended 2026-10-03:** $90/month: above the ≈ $80 forecast, below the Free plan credits |
| Bedrock model IDs in the IAM policy | **Confirmed:** follow the `core/llm` registry (deferred to the dev benchmark) |

## Sources

Prices and service facts checked on 2026-09-28:
- [EC2 t3.xlarge](https://instances.vantage.sh/aws/ec2/t3.xlarge) · [EC2 on-demand pricing](https://aws.amazon.com/ec2/pricing/on-demand/) · [EBS pricing](https://aws.amazon.com/ebs/pricing) · [Public IPv4 charge](https://computingforgeeks.com/aws-costs-explained-real-numbers/)
- [Fargate pricing](https://aws.amazon.com/fargate/pricing/) · [RDS db.t4g.medium](https://instances.vantage.sh/aws/rds/db.t4g.medium) · [RDS storage](https://www.usage.ai/blogs/aws/reserved-instances/rds/storage-cost/) · [ELB pricing](https://aws.amazon.com/elasticloadbalancing/pricing/) · [ElastiCache t4g.micro](https://instances.vantage.sh/aws/elasticache/cache.t4g.micro) · [ECS Express Mode](https://repost.aws/articles/ARDZrGhYT1SMCAeGbojOMbsg/re-invent-2025-launch-web-applications-in-seconds-with-amazon-ecs-express-mode)
- [App Runner availability change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html)
- [Bedrock inference profile prerequisites](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html) · [Inference-profile IAM failure example](https://github.com/aws-amplify/amplify-category-api/issues/3502)
- [Langfuse Docker Compose requirements](https://langfuse.com/self-hosting/deployment/docker-compose)
- [sslip.io Let's Encrypt rate limit](https://github.com/cunnie/sslip.io/issues/108) · [Let's Encrypt rate limits](https://letsencrypt.org/docs/rate-limits/)
