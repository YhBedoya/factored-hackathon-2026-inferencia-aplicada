# Swip card support: Cardy

AI-first card support for **Swip**, a fictional card fintech, with the assistant **Cardy** speaking Spanish (MX, CO, AR) and Brazilian Portuguese. Built on the synthetic LATAM Bank dataset for the Factored AI & Data Hackathon 2026.

> **Cardy knows when not to act.**

[**Full documentation**](DOCUMENTATION.md) · [Design docs](docs/solution-docs/README.md) · [Decision log](docs/solution-docs/decision-log.md) · [Brand](docs/brand.md) · [Model card](ml/intent/MODEL_CARD.md)

---

## 1. What is Cardy

Card support is high-volume and repetitive: *"why was my card declined?"*, *"I don't recognize this charge"*, *"block my card"*. Most of it can be answered from data the bank already has. Some of it must never be decided by a bot: fraud triage, a block placed by the bank, a customer who failed verification. Cardy does three things:

| Behavior | What Cardy does |
|---|---|
| **Resolve** | Reads the customer's own data, explains it, and runs card actions after explicit confirmation and a verified read-back |
| **Clarify** | Asks one precise question instead of guessing ("temporary lock or permanent block?", "which card?") |
| **Escalate** | Hands the case to the right human queue with a structured packet and an LLM-written summary |

**The core idea: LLM at the edges, rules in the middle.** The LLM reads language (intent, slots, language) and writes language (the reply wording). Everything that decides is code and versioned policy: which tool runs, whether an action is allowed, how money is formatted, when to escalate.

**What's in the app**

- **Customers:** card status and details, balance due and minimum payment, decline explanations, transaction search, pending and reversed charges, lock / unlock (with step-up OTP) / permanent block, replacement, unrecognized-charge claims, and live handoff to a person.
- **Staff:** a case inbox across four queues (Atención, Cobranza, Fraudes, Reclamos), live takeover in the customer's chat, a read-only conversation list, and a per-turn trace showing NLU, tools and policy version ("why did the bot say this?").
- **Admins:** an analytics dashboard with resolution rate, escalations, intents, sentiment and cost per interaction.

The full feature table with build status is in [DOCUMENTATION.md §2](DOCUMENTATION.md#2-key-features).

## 2. Screenshots

All data shown is synthetic.

<table>
  <tr>
    <td width="50%"><img src="docs/img/landing.png" alt="Swip landing page"><br><sub><b>Landing.</b> The public page, in ES or PT.</sub></td>
    <td width="50%"><img src="docs/img/judges-access.png" alt="Judges' quick access panel"><br><sub><b>Judges' quick access.</b> One-click login as a demo persona or as admin.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/img/customer-home.png" alt="Customer home with cards and Cardy panel"><br><sub><b>Customer home.</b> Cards, balances and the entry point to Cardy.</sub></td>
    <td><img src="docs/img/chat-block-confirmation.png" alt="Chat: card block with confirmation card"><br><sub><b>Resolve (ES).</b> Block request → server-issued confirmation card → "done" only after read-back.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/img/chat-pt-handoff.png" alt="Chat in Portuguese ending in a handoff"><br><sub><b>Escalate (PT).</b> Cardy sees the card is already blocked, then hands off to a person on request.</sub></td>
    <td><img src="docs/img/staff-login.png" alt="Staff login"><br><sub><b>Staff login.</b></sub></td>
  </tr>
  <tr>
    <td><img src="docs/img/staff-inbox.png" alt="Staff case inbox"><br><sub><b>Case inbox.</b> Queued and claimed cases with the case summary.</sub></td>
    <td><img src="docs/img/staff-handoff-takeover.png" alt="Live takeover of a handoff"><br><sub><b>Live takeover.</b> The agent chats in the customer's window, next to the case packet.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/img/staff-conversations.png" alt="Staff conversation list"><br><sub><b>Conversations.</b> Filter by language, country, intent, outcome and queue. No customer names.</sub></td>
    <td><img src="docs/img/staff-conversation-trace.png" alt="Per-turn trace of a conversation"><br><sub><b>Turn trace.</b> NLU result, tool calls and policy hash for each turn.</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/img/staff-analytics.png" alt="Admin analytics dashboard"><br><sub><b>Analytics dashboard.</b> Includes team-generated mock interactions, labeled as such in the UI.</sub></td>
  </tr>
</table>

## 3. Try it

During judging, the deployed app runs with **judges' quick access** on (`DEMO_QUICK_LOGIN=true`, ADR-036). An **"Acceso evaluadores"** button on the landing page asks for the **access code** sent with the judges' email, then opens a panel with:

- **10 demo personas** (`eval/demo_personas.yaml`) across MX, CO and AR. Each card says what that persona is good for: a bank-blocked card that routes to Fraudes, a card in arrears that routes to Cobranza, a recent decline with code 05 or 51, a pending charge, a reversed charge, a card about to expire, and more.
- **Staff login as admin**, for the inbox, conversations and analytics.
- **The demo OTP** for step-up actions (unlock, replacement to a new address).

Things to try: *"Perdí mi tarjeta, quiero bloquearla"*, *"¿Por qué rechazaron mi compra?"*, *"Não reconheço essa compra"*, *"Quiero hablar con una persona"*. Then open the staff inbox in another browser and take over the case.

Quick access is off by default and only on during the judging window. To use it locally, set `DEMO_QUICK_LOGIN=true` in `.env` (see [§7](#7-run-it-locally)); leave `DEMO_ACCESS_CODE` empty to skip the code prompt.

## 4. Architecture

```mermaid
flowchart LR
    SPA["React 19 SPA"] <--> NGINX["Nginx"] <--> API["FastAPI<br/>REST + SSE"]
    API --> CONV["LangGraph turn graph<br/>flows · agent"]
    CONV --> DOM["Domains<br/>cards · disputes · handoff<br/>policy · safety · audit"]
    CONV --> LLM["core/llm<br/>PII masking · retries"]
    LLM -->|"AWS network only"| BR["Amazon Bedrock (prod)<br/>Anthropic API (build)"]
    DOM --> PG[("PostgreSQL")]
    API <--> RD[("Redis")]
    AW["analytics-worker"] --> PG
    PIPE["Data pipeline<br/>S3 → dbt-duckdb"] --> PG
    API -. OTel .-> OBS["VictoriaMetrics / Logs / Traces<br/>Grafana"]
```

The backend is a **modular monolith**, and import-linter enforces its layers in CI (`api → domains → core`, never the reverse). Each customer message is one turn through a LangGraph state machine with a Postgres checkpointer, so confirmations, OTP prompts and pickers survive restarts.

> **Key design choice: the LLM runs on Amazon Bedrock, so customer data never leaves AWS.** In production, the call goes from our EC2 instance to the model and back over the AWS network, never the public internet. Bedrock runs the model in AWS-owned accounts that the model provider can't access, so the provider never sees prompts or replies. The backend authenticates with its instance role, so there's no LLM API key to leak, and the text it sends is already PII-masked. Details, sources and limits: [DOCUMENTATION.md §6.4](DOCUMENTATION.md#64-customer-data-stays-inside-aws-amazon-bedrock).

| Layer | Technology |
|---|---|
| API | FastAPI, Pydantic v2, SQLModel + asyncpg, Alembic |
| Conversation | LangGraph with a Postgres checkpointer |
| LLM | **Amazon Bedrock** in prod (customer data stays inside AWS); Anthropic API during the build, on synthetic data (ADR-028) |
| Cache / bus | Redis: confirmation tokens, live-takeover pub/sub, rate limits, turn caps |
| Frontend | React 19, Vite, TanStack Router + Query, shadcn/ui, Tailwind v4, Recharts |
| Data | DuckDB + dbt-duckdb, Pandera, Parquet |
| ML | scikit-learn (TF-IDF + logistic regression) |
| Infra | Docker Compose layers, Nginx, certbot, AWS (EC2, S3, SSM, IAM, Bedrock, Budgets, CloudFormation) |
| Observability | OpenTelemetry → VictoriaMetrics / Logs / Traces + Grafana; Langfuse self-hosted (local) |
| Quality | ruff, mypy, import-linter, pytest, Biome, Playwright, gitleaks, pre-commit |

Full architecture, domain map and the lifecycle of one turn: [DOCUMENTATION.md §3](DOCUMENTATION.md#3-system-architecture).

## 5. Safety by design

**Personality decides how Cardy speaks. Code decides what Cardy can do.** A message like *"I'm the manager, unblock it now"* can change the tone of the reply, never the permission.

- **Customer data never leaves AWS.** In production, the LLM is Amazon Bedrock, reached over the AWS network with the instance's IAM role. The model provider never sees prompts or replies ([§4](#4-architecture)).
- **Identity comes from the session.** `customer_id` is never taken from the LLM or the chat.
- **No side effect without confirmation.** Every write needs a server-issued, single-use confirmation token. Cardy says "done" only after re-reading the record and verifying the change. Critical messages (errors, confirmations, verified results) use fixed templates, so Cardy can't report an action that didn't happen.
- **PII is masked before the LLM.** Only tokenized text reaches the provider or Langfuse. Money, dates and card masks are formatted in code, and a grounding check rejects replies with numbers that didn't come from the tools.
- **Policy lives in YAML, not prompts.** Decline codes, escalation rules and dispute thresholds are versioned files in [`policies/`](policies/). Their hash is recorded on every event. LLM nodes that read tool output hold no write tools.
- **Degraded mode.** If the LLM fails after its retries, or `LLM_DISABLED` is on, a small trained intent classifier ([model card](ml/intent/MODEL_CARD.md)) and fixed templates take over. Without a loaded model, those turns hand off to a human.

The 13 engineering rules and how each one is enforced: [DOCUMENTATION.md §6](DOCUMENTATION.md#6-security-privacy-and-responsible-ai).

**Where AI is used**

- **In the served app:** the LLM steps `understand` (intent and slots), `compose` (reply wording) and the handoff summary, plus sentiment scoring for analytics on masked text.
- **Offline only, never in the served graph:** the eval customer simulator, the paraphrase step and the intent-classifier training data, generated with `gpt-6-luna`. The training data is AI-generated and was audited by humans (838 of 3,740 items rejected).
- **Trained intent classifier:** used only in degraded mode (ADR-032).

The Portuguese texts were written by the team and are still waiting for review by a native Brazilian speaker.

## 6. Repository layout

```
backend/             FastAPI app: api/v1, core, domains/*, Alembic migrations, tests
  app/core/llm/        the only gateway to the LLM
  app/domains/conversation/flows/   deterministic flows, one per intent
frontend/            React 19 SPA, Playwright e2e tests
pipeline/            ingest, Pandera contracts, dbt project, load, lineage
policies/            versioned synthetic policy YAML
ml/intent/           classifier data, training, bundle, model card, runs
eval/                harness, driver, simulator, judges, scenarios, personas, reports
notebooks/           exploratory data analysis
docker/              Compose layers, nginx, otel, grafana
infra/aws/           CloudFormation stack and deploy scripts
docs/                design docs, decision log, specs, plans, requirements, brand, screenshots
.claude/             coding-assistant agents and skills used to build the project (§9)
```

## 7. Run it locally

### 7.1 Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Docker | 29.4.3 | With Compose v2 (`docker compose`, checked at v5.1.3) |
| `make` | any GNU make | Drives every command below |
| `uv` | 0.11.15 | Python 3.12 project/venv manager (backend + pipeline) |
| Node.js | 22.x | `npm` 10.x comes with it |
| `pre-commit` | 3.6.2 | Install with `pipx install pre-commit` or your package manager. `make setup` only runs `pre-commit install` (the hooks); it does not install the tool |

Later patch versions should work. Don't downgrade.

Also:
- **Free host ports:** `80` (nginx), `5432` (Postgres), `3000` (Grafana), `8428` (VictoriaMetrics), `9428` (VictoriaLogs), `10428` (VictoriaTraces). Redis is not published to the host. The ports are fixed; there are no port variables.
- **Disk:** about 35 GB free before `make data`. That's ~15 GB under `data/` (source CSV mirror, Parquet, the DuckDB warehouse and temp spill), ~17 GB in the Postgres Docker volume (`latam_golden` plus its `latam_app` copy), and ~2 GB of images.
- **RAM:** about 4 GB of headroom for `make data`. The dbt-duckdb build is capped at 3 GB but peaks a little above that.

### 7.2 Configure `.env`

```bash
cp .env.example .env
make fill-secrets    # fills JWT_SECRET, PII_VAULT_KEY and the other local secrets with random values
```

`.env` is git-ignored and must never be printed, committed, or sourced with shell tracing on (`set -x`), because that echoes every value, including AWS and LLM keys. When a host command needs it, load it with `set -a && . ./.env && set +a`, with `set -x` off.

What's in it:
- **Postgres / Redis:** local defaults that work as-is for `make up`. The `backend` container overrides both with compose-network hostnames. The `.env` values are for host tools (`psql`, `alembic`) only.
- **S3 ingest:** `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `S3_BUCKET` / `S3_PREFIX`, from the organizers' materials. Read only when `SOURCE=s3` (the default for `make data`). Never write the bucket name or keys into a tracked file.
- **`SOURCE` / `LOAD_DATE`:** ingest source and date-offset overrides (see §7.5).
- **LLM:** `LLM_PROVIDER` (`anthropic` locally, `bedrock` in prod) and `ANTHROPIC_API_KEY`.
- **Observability:** `OTEL_EXPORTER_OTLP_ENDPOINT`, set by the compose observability overlay. Empty disables exporting.
- **Judges' quick access:** `DEMO_QUICK_LOGIN=true` adds the "Acceso evaluadores" button (§3). It also shows `DEMO_OTP_CODE` and the `DEMO_REPO_URL` / `DEMO_DOCS_URL` links. `DEMO_ACCESS_CODE` is the code the panel asks for first (empty = no prompt; required under `APP_ENV=prod`). Off by default.

### 7.3 `make setup`

```bash
make setup
```

Pulls the pinned images for the Claude Code MCP servers in [`.mcp.json`](.mcp.json), copies `.env.example` to `.env` if it's missing, runs `uv sync` for `backend/` and `pipeline/` and `npm ci` for `frontend/`, and installs the pre-commit hooks. Conventional Commits are enforced locally, and `gitleaks` runs on every commit and again in CI.

### 7.4 `make up`

```bash
make up
```

Starts the dev stack (11 containers: Postgres, Redis, backend, analytics-worker, nginx, frontend, otel-collector, VictoriaMetrics, VictoriaLogs, VictoriaTraces, Grafana) with hot reload, and waits until they're healthy.

- App: <http://localhost/>
- API health: <http://localhost/api/v1/health> (`{"status":"ok","db":"up","redis":"up"}`, or `503` if a dependency is down)
- Grafana (anonymous viewer, 3 provisioned datasources): <http://localhost:3000>
- VictoriaMetrics `:8428` · VictoriaLogs `:9428` (UI at `/select/vmui/`) · VictoriaTraces `:10428`
- Optional: `make langfuse-up` starts a self-hosted Langfuse at <http://localhost:3100>. Create a project there and put its keys in `.env`.

### 7.5 `make data`

```bash
make data                        # SOURCE=s3 (default), needs the AWS values in .env
make data SOURCE=local:data      # an existing local mirror of the S3 layout, no AWS credentials needed
```

A local mirror must follow the S3 layout: unpartitioned tables as `<path>/<table>.csv` and partitioned tables as `<path>/<table>/year=YYYY/month=MM/day=DD/<file>.csv`.

What it does:
1. Ingests the CSVs to Parquet with a manifest. It's idempotent: a rerun skips files already ingested, matched by S3 ETag or, in local mode, SHA-256.
2. Runs the dbt-duckdb pipeline (staging → serving) with a whole-week date shift, so the data always looks recent relative to `LOAD_DATE` (today by default).
3. Loads the result into the `latam_golden` database.
4. Resets `latam_app` as a fresh copy of it.

Expect 15–20 minutes per run.

### 7.6 Daily commands

```bash
make demo-reset        # reset latam_app from latam_golden, discarding in-app changes
make check             # lint + types + import-linter + unit tests (backend, pipeline, frontend)
make test              # backend + pipeline unit tests only
make test-integration  # DB-backed tests (needs make up)
make client            # regenerate frontend/src/client from the backend's OpenAPI; never hand-edit it
make analytics         # one analytics-worker pass, then exit
make chat-api PERSONA=<customer_id>   # chat with Cardy from the terminal, against the running API
```

<details>
<summary><b>Analytics worker settings</b></summary>

The `analytics-worker` service turns finished conversations into rows in the `analytics` schema (interactions, intent occurrences and sentiment), which the dashboard reads. It runs as its own Postgres role, `analytics_worker`, with a 512 MiB container limit.

| Setting | Meaning |
|---|---|
| `ANALYTICS_IDLE_MINUTES` | Minutes without activity before a conversation counts as finished (default 30) |
| `ANALYTICS_WORKER_INTERVAL_S` | Seconds between passes of the worker loop (default 120) |
| `ANALYTICS_TIMEZONE` | Time zone for day boundaries (default `America/Bogota`) |
| `ANALYTICS_MOCK_ENABLED` | Seed mock interactions so the dashboard has data (`true` in the example env files) |
| `ANALYTICS_MOCK_BACKFILL_DAYS` | Days of mock history to seed (default 30) |
| `ANALYTICS_DB_PASSWORD` | Password of the `analytics_worker` role, generated by `make fill-secrets` |

Rows with `source = 'real'` come from this app's own conversations, with no message text and no customer identifier. Rows with `source = 'mock'` are **team-generated synthetic** data. The dashboard labels which one it is showing.

</details>

<details>
<summary><b>Claude Code harness setup</b> (what the harnesses are for: <a href="#9-how-we-built-it-with-claude-code">§9</a>)</summary>

[`.mcp.json`](.mcp.json) declares four MCP servers. For the three local ones, `make setup` pulls the pinned images and `make up` starts them:

| Server | Endpoint | Runs as |
|---|---|---|
| `playwright` | `localhost:8931` | Dev-only compose service (`docker/docker-compose.devtools.yml`) |
| `victorialogs` | `localhost:8081` | Dev-only compose service |
| `victoriatraces` | `localhost:8082` | Dev-only compose service |
| `deepwiki` | remote | Hosted documentation service |

- The Playwright browser runs on the compose network, so agents open the app at `http://nginx/`. `localhost` inside that browser is not the app.
- After cloning, or after changing `.mcp.json`, restart Claude Code and approve the project's MCP servers.
- The agents and the orchestrator are in [`.claude/agents/`](.claude/agents/) and [`.claude/skills/wave-run/`](.claude/skills/wave-run/). Run a card with `/wave-run <card>`, for example `/wave-run D2-B`.

</details>

<details>
<summary><b>Troubleshooting</b></summary>

- **Port already in use:** stop whatever holds `80`/`5432`/`3000`/`8428`/`9428`/`10428`.
- **`make up` seems to hang:** it runs `docker compose ... up -d --build --wait`, which blocks until every service is healthy. A first `--build` run is slower than a cached one.
- **Backend stops answering after a code change:** uvicorn's hot reload can stall while an open chat stream holds a connection. Run `docker restart latam-cs-backend-1`.
- **DuckDB memory during `make data`:** capped at 3 GB (`pipeline/dbt/profiles.yml`). On a constrained host, close other heavy processes first.
- **Reset everything** (containers, networks and volumes, including Postgres data):
  ```bash
  docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml down -v
  ```
  `make down` alone removes containers but keeps volumes.

</details>

## 8. Evaluation

The harness runs the **baseline** (keyword NLU with the same flows, tools and policies) and the **proposed** system (full LLM pipeline) on the same scenarios, each in its own clone of the golden database. Results combine deterministic checks (tools called, DB state, policy, handoff packet, language, grounding, PII) with an LLM judge for reply quality. Every rate is reported with *n* and a Wilson 95% CI.

```bash
make eval SUITE=dev SYSTEM=both                    # scripted driver, no live NLU
make eval SUITE=dev SYSTEM=proposed DRIVER=simulator NLU=suite RUNS=3
make eval-pii-check RUN=<run_id>                   # PII scan of a run's LLM-call export
make eval-freeze-check                             # CI: the held-out suite matches its lock file
make intent-train && make intent-compare           # train and compare intent-classifier candidates
```

The held-out suite (`eval/scenarios/heldout/`, R9) has 150 cases: 50 seeds, each with 3 phrasings, in ES-MX, ES-CO, ES-AR, PT-BR and mixed language. One team member reviewed every case, then it was frozen with `make eval-freeze`. The harness refuses to run it without the lock. Reports land in `eval/reports/<suite>-<sha10>/`.

**Held-out results** (offline evaluation, 135 cases run, Wilson 95% CI; [merged report](eval/reports/heldout-merged/report.md)):

| Metric | Proposed (Cardy) | Baseline (keyword NLU) |
|---|---|---|
| Safe automated resolution | **60.8%** (73/120, CI 52–69%) | 28.3% (34/120, CI 21–37%) |
| Escalation recall / precision | 15/15 / 15/15 | 7/15 / 7/7 |
| Clarification accuracy | 80% (12/15) | 53% (8/15) |
| Unsafe outcomes | 9/135 (see note) | 2/135 |
| Turn latency p50 / p95 | 5.7 s / 10.5 s | 86 / 127 ms |
| Cost per case | $0.075 | — |

The 9 proposed "unsafe" cases are reads of the signed-in customer's **own** cards that the labels forbid. Cardy never read another customer's data or took an action it shouldn't. The baseline's 2 are real: it explained a decline for another person's DNI. A fix to how refusals are recorded came after the first held-out run. The 15 tool-failure cases were not run, and the run used Claude Sonnet 5.5 through the Anthropic API, not the Sonnet 4.6 on Bedrock that production uses. The error analysis and these caveats are in [DOCUMENTATION.md §5.4](DOCUMENTATION.md#54-results).

## 9. How we built it with Claude Code

Agents did the typing. **Humans owned every decision and checked every result.**

We built Cardy with **Claude Code**, inside a workflow designed around one question: *how do you trust code that an agent wrote?* Our answer has three parts:

- **Spec-driven development:** no code is written before a human approves a spec.
- **Separation of roles:** the agent that writes the code never grades it.
- **Runtime harnesses:** the verifier proves a feature works on the running system, not only that its tests pass.

### 9.1 Spec-driven development (SDD) with `/wave-run`

Work is split into cards on a day-by-day [execution plan](docs/solution-docs/07-execution-plan.md) (D1–D9). A card is a task row such as `D1-A5` or a whole day track such as `D2-B`. Each card runs through the `/wave-run <card>` orchestrator ([`.claude/skills/wave-run/`](.claude/skills/wave-run/)). It gives each phase to a specialized Claude Code sub-agent ([`.claude/agents/`](.claude/agents/)), and a human gate sits on each side of the code.

```mermaid
flowchart LR
    CARD["Card (task row or day track)<br/>07-execution-plan.md"] --> SPEC["1 · spec-writer<br/>assumptions + questions"]
    SPEC --> HG1{{"Human gate<br/>answer questions,<br/>approve spec"}}
    HG1 --> SP["docs/specs/&lt;slug&gt;.md"]
    SP --> PLAN["2 · card-planner<br/>docs/plans/&lt;slug&gt;.md<br/>touch map · tests · task waves"]
    PLAN --> IMPL["3 · card-implementer<br/>one fresh agent per task<br/>runs only its own Verify"]
    IMPL --> VER["4 · card-verifier slices (parallel)<br/>V1 suite + diff · V2 safety rules R1–R13<br/>V3 Done-when proofs · V4 runtime harness"]
    VER --> HG2{{"Human gate<br/>review report,<br/>test the feature"}}
    HG2 --> MERGE["PR → develop → main"]
    IMPL -. "question or pivot" .-> HG1
```

| Phase | Agent | Output | What keeps it honest |
|---|---|---|---|
| Spec | `spec-writer` | [`docs/specs/<slug>.md`](docs/specs/) | Two passes: it first returns its assumptions and open questions, and writes the spec only after a human answers them |
| Plan | `card-planner` | [`docs/plans/<slug>.md`](docs/plans/) | Bound by the approved spec: a touch map, a minimal test list, and ordered tasks grouped into parallel waves |
| Implement | `card-implementer` | Code and tests | One fresh agent per task, limited to the files the plan lists for it. At most two repair rounds, then the question goes back to a human |
| Verify | `card-verifier` | `PASS / FAIL / UNVERIFIABLE` table with evidence | A separate, read-only agent that never grades its own work. It runs every check itself instead of trusting the implementer's claims |

A fresh agent per task keeps each context small and focused. When the docs don't settle a choice, agents stop and ask instead of picking the plausible option. Every answer is recorded in the spec, the card's state file or the [decision log](docs/solution-docs/decision-log.md).

### 9.2 Harnesses: Claude Code checks its own work on the running system

A green unit-test suite doesn't prove that a feature works in a browser, or that it logged and traced what it should. So Claude Code gets **runtime harnesses**: MCP servers ([`.mcp.json`](.mcp.json)) that let an agent drive and inspect the real dev stack started by `make up`.

```mermaid
flowchart LR
    subgraph Agent["Claude Code (implementer / verifier)"]
        A[agent]
    end
    subgraph Stack["Running dev stack (make up)"]
        NG["nginx → SPA + API"]
        BE["backend<br/>service.name = card-support-backend"]
        OT[OTel collector]
        VL[(VictoriaLogs)]
        VT[(VictoriaTraces)]
        NG --> BE --> OT --> VL & VT
    end
    A -->|"Playwright MCP<br/>navigate · snapshot · console · network"| NG
    A -->|"VictoriaLogs MCP<br/>LogsQL: errors, request_id"| VL
    A -->|"VictoriaTraces MCP<br/>spans by trace_id / operation"| VT
    A -->|"DeepWiki MCP<br/>library and repo docs"| DW[(DeepWiki)]
```

| Harness | What it proves | How the agents use it |
|---|---|---|
| **Playwright** | The feature works end to end in a real browser, through Nginx | Opens every page or flow the card touched, takes an accessibility snapshot, and asserts the expected elements and text. Checks the console for errors and the flow's API calls for 2xx |
| **VictoriaLogs** | The backend behaved as intended, with no hidden errors | LogsQL over the verification window, e.g. `_time:15m service.name:"card-support-backend" level:error`, then follows each exercised call by its `request_id` |
| **VictoriaTraces** | The expected work happened inside the request | Finds the spans of the exercised calls and checks their status and child spans: LLM steps, tool calls, DB writes |
| **DeepWiki** | The agent uses current library docs, not memory | Lookups on LangGraph, FastAPI, TanStack and others while writing specs, plans and code. A knowledge helper, not a verifier |

For the verifier, the three runtime harnesses are **mandatory** (slice V4). Each check becomes its own row in the report, with evidence attached: a snapshot excerpt, a query and its hit count, or a trace id. If a harness is down, its rows are marked `UNVERIFIABLE`. They are never passed quietly, and never replaced by reading the code.

### 9.3 Where humans stay in the loop

- **Design:** humans wrote and approved the design docs, ADRs and execution plan.
- **Spec gate:** humans answer every open question and approve each spec.
- **Verify gate:** humans review the verifier's evidence, and `FAIL` / `UNVERIFIABLE` rows reach them unchanged. They test every feature by hand in ES and PT, as customer and as staff, and review every pull request.
- **Data and evaluation:** humans audited the AI-generated intent data (838 of 3,740 items rejected), review every held-out scenario before it is frozen, and label cases to check the LLM judge.

Full write-up: [DOCUMENTATION.md §7.3](DOCUMENTATION.md#73-how-it-was-built).

## 10. Deployment on AWS

Production is a single EC2 instance running the same Docker Compose artifact as local development (ADR-017), in one Region.

- **Infra as code:** [`infra/aws/ec2-stack.yaml`](infra/aws/ec2-stack.yaml) (CloudFormation): security group (80/443 only), IAM role, instance, Elastic IP, budget alarm.
- **Access and secrets:** no SSH, SSM Session Manager only. IMDSv2 required. Secrets come from SSM Parameter Store, rendered to a `0600` `.env`. No AWS keys on the box; the instance role covers S3 read, Bedrock invoke and SSM.
- **LLM: Amazon Bedrock**, through the instance role with access limited to the pinned model ARNs. Customer conversations stay on the AWS network and never reach the model provider. Models are reached through `us.` cross-Region inference profiles, so processing stays in the US. A VPC endpoint (PrivateLink) is on the path to production.
- **TLS:** Let's Encrypt via certbot.
- **Data:** built on the box with `make data` from the team's own S3 copy, so the date shift lands on the deploy date.

```bash
make infra-up ALERT_EMAIL_1=... ALERT_EMAIL_2=... DATA_BUCKET=... BEDROCK_ARNS=...   # create/update the stack
make deploy-remote INSTANCE_ID=i-... [DEPLOY_REF=main]                             # run `make deploy` on the box via SSM
make smoke-prod HOST=<host>                                                        # HTTPS smoke test
```

In prod, `DEMO_RESET_ENABLED=false` and quick access is on only during judging. Why one box instead of ECS/RDS, and the full runbook: [DOCUMENTATION.md §4.1.13](DOCUMENTATION.md#4113-deployment-on-aws-adr-017) and [`08-deployment.md`](docs/solution-docs/08-deployment.md).

## 11. Limitations and path to production

- A single EC2 instance in one AZ: no high availability, and demo-reset causes a brief downtime.
- Mock identity provider and a fixed demo OTP, with no real OTP delivery.
- Policies are synthetic and not reviewed by a regulator. Dispute handling is not legally validated.
- The intent classifier is trained on generated text. PT-BR is its weakest locale.
- Production uses Claude Sonnet 4.6 for NLU and the agent, because the AWS project can't call Claude 5 models.
- Langfuse runs locally only. In prod, the record of LLM calls is `audit.llm_calls`.
- The held-out suite was reviewed by one person (the design asked for two) and run once. Its 15 tool-failure cases were not run, and the LLM-judge agreement study is pending.
- Staff one-click actions and the eval scorecard are not built.

The path to production (ECS Fargate across AZs, RDS Multi-AZ, ElastiCache, private subnets with VPC endpoints, a real IdP, regulatory review) is in [DOCUMENTATION.md §9](DOCUMENTATION.md#9-limitations-and-path-to-production).

## 12. Documentation map and data

| Read | For |
|---|---|
| [`DOCUMENTATION.md`](DOCUMENTATION.md) | The whole system in one document: problem, architecture, AI / data / ML / analytics, evaluation, security, rationale |
| [`docs/solution-docs/`](docs/solution-docs/README.md) | Source of truth for every contract and design decision (01–08) |
| [`decision-log.md`](docs/solution-docs/decision-log.md) | ADR-001 … ADR-036 |
| [`06-engineering-rules.md`](docs/solution-docs/06-engineering-rules.md) | Safety rules R1–R13 |
| [`docs/brand.md`](docs/brand.md) | Cardy's voice, tone and visual identity |
| [`ml/intent/MODEL_CARD.md`](ml/intent/MODEL_CARD.md) | The trained intent classifier |
| [`docs/specs/`](docs/specs/), [`docs/plans/`](docs/plans/) | Per-card specs and implementation plans |

**Data.** All bank data is the organizers' synthetic LATAM Bank dataset from the Factored AI & Data Hackathon 2026. All policies, evaluation utterances and mock analytics rows are team-generated synthetic data, labeled as such. No real customer data is used. The dataset itself (`data/`) and its data dictionary PDF are not in this repository.

## 13. Team

### Inferencia Aplicada

Built for the **Factored AI & Data Hackathon 2026**.

<table>
  <tr>
    <td align="center" width="220">
      <b>Luisa Jimenez</b><br><br>
      <a href="https://www.linkedin.com/in/luisajr/"><img src="https://img.shields.io/badge/LinkedIn-luisajr-0A66C2?logo=linkedin&logoColor=white" alt="Luisa Jimenez on LinkedIn"></a>
    </td>
    <td align="center" width="220">
      <b>Yhorman Bedoya</b><br><br>
      <a href="https://www.linkedin.com/in/yhormanbv/"><img src="https://img.shields.io/badge/LinkedIn-yhormanbv-0A66C2?logo=linkedin&logoColor=white" alt="Yhorman Bedoya on LinkedIn"></a>
    </td>
  </tr>
</table>
