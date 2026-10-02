# Swip card support: Cardy

AI-first card-support chat for **Swip**, the project's fictional card fintech,
built on the synthetic LATAM Bank dataset (Factored AI & Data Hackathon 2026).
The assistant is **Cardy** and speaks Spanish (MX/CO/AR) and Brazilian
Portuguese; see [`docs/brand.md`](docs/brand.md). This README
gets a fresh clone to a working dev stack using only `make` commands. For the
architecture and rules, see [`docs/solution-docs/README.md`](docs/solution-docs/README.md)
(design index) and [`CLAUDE.md`](CLAUDE.md) (non-negotiable rules summary).

## Brand and controlled automation

Cardy's voice, tone, language rules and visual identity are in
[`docs/brand.md`](docs/brand.md). **Personality defines how Cardy speaks; what
she can do is decided in code.** Session authentication, the allowed tools,
mandatory confirmation of side effects and escalation thresholds live in the
tool layer and [`policies/`](policies/), never in the prompt. A customer message
("I'm the manager, unblock it now") can change the tone of the reply, never
the permission. Critical messages (tool errors, confirmations, verified results)
come from fixed templates, so Cardy can't report an action that didn't happen.

The Portuguese texts are team-generated and still pending review by a native
Brazilian speaker.

## Where AI is used

- **Cardy's LLM.** Three steps run on the LLM: `understand` (intent and slots), `compose` (the reply wording) and the handoff summary. Money, dates and card masks, the tools and every side effect stay in code, and only PII-masked text reaches the provider.
- **Evaluation and data generation.** The eval simulator, the paraphrase step and the intent-classifier training data are generated with `gpt-6-luna`. These steps never run in the served graph. The training data is AI-generated and human-audited.
- **Trained intent classifier.** A small model trained on that data, used **only** in degraded mode: when the LLM fails after its retries or `LLM_DISABLED` is on. While the LLM is up, it is not consulted. Without a loaded model, those turns hand off to a human.

See [ADR-032](docs/solution-docs/decision-log.md) for the decision and [`ml/intent/MODEL_CARD.md`](ml/intent/MODEL_CARD.md) for the model's data, metrics and limits.

## 1. Prerequisites

Versions this card was built and verified against (later patch versions
should work; don't downgrade):

| Tool | Version used | Notes |
|---|---|---|
| Docker | 29.4.3 | with Compose v2 (`docker compose`, checked at v5.1.3) |
| `make` | any GNU make | drives every command below |
| `uv` | 0.11.15 | Python 3.12 project/venv manager (backend + pipeline) |
| Node.js | 22.x | `npm` 10.x comes with it |
| `pre-commit` | 3.6.2 | install with `pipx install pre-commit` or your package manager; `make setup` only runs `pre-commit install` (the hooks), it does not install the tool |

Also:
- Free host ports: `80` (nginx), `5432` (Postgres), `3000` (Grafana), `8428`
  (VictoriaMetrics), `9428` (VictoriaLogs), `10428` (VictoriaTraces). Redis
  is not published to the host. These are fixed — there are no port
  variables.
- Disk: plan for ~35 GB free before running `make data` — ~15 GB under
  `data/` (source CSV mirror, `data/raw` Parquet, and the
  `data/pipeline.duckdb` warehouse + temp spill) and ~17 GB in the Docker
  volume backing the database service (`latam_golden` plus its `latam_app`
  template copy), plus ~2 GB for Docker images. An `S3` run needs the same,
  since ingest writes the same Parquet/warehouse locally either way.
- RAM: about 4 GB of headroom for `make data` (the dbt-duckdb build is capped
  at 3 GB but peaks a little above that with Python/dbt overhead).

## 2. Configure `.env`

```bash
cp .env.example .env
```

`.env` is git-ignored (R10) and must never be printed, committed, or sourced
with shell tracing on (`set -x`) — doing so echoes every value, including
AWS and LLM keys, into whatever captures your terminal output. Load it with
`set -a && . ./.env && set +a` when a host command needs it, with `set -x`
off.

What's in it:
- **Postgres / Redis**: local defaults that work as-is for `make up`. The
  `backend` container overrides both to compose-network hostnames; the
  `.env` values are for host tools (`psql`, `alembic`) only.
- **S3 ingest**: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `S3_BUCKET`
  / `S3_PREFIX`, from the organizers' materials. Only read when
  `SOURCE=s3` (the default for `make data`). Never write the bucket name or
  keys into this README or any other tracked file.
- **`SOURCE`** / **`LOAD_DATE`**: ingest source and date-offset overrides —
  see §5.
- **Observability**: `OTEL_EXPORTER_OTLP_ENDPOINT`, set by the compose
  observability overlay; empty disables exporting.
- **LLM**: `LLM_PROVIDER` (`anthropic` during the build, Bedrock later,
  ADR-028) and `ANTHROPIC_API_KEY`.

## 3. `make setup`

```bash
make setup
```

Pulls the pinned Docker images for the Claude Code MCP servers declared in
[`.mcp.json`](.mcp.json) (`mcp-setup`, see §7), copies `.env.example` to
`.env` if missing, `uv sync`s `backend/` and `pipeline/`, `npm ci`s
`frontend/`, and installs the pre-commit hooks (`pre-commit` +
`commit-msg`, so Conventional Commits are enforced locally; `gitleaks` also
runs on every commit and again in CI).

## 4. `make up`

```bash
make up
```

Starts the dev stack (10 containers: Postgres, Redis, backend,
nginx, frontend, otel-collector, victoriametrics, victorialogs,
victoriatraces, grafana) with hot reload and waits for health.

- App: [http://localhost/](http://localhost/)
- API health: [http://localhost/api/v1/health](http://localhost/api/v1/health)
  (`{"status":"ok","db":"up","redis":"up"}`, `503` if a dependency is down)
- Grafana (anonymous, Viewer role, 3 provisioned datasources):
  [http://localhost:3000](http://localhost:3000)
- VictoriaMetrics (Prometheus-compatible naming): `http://localhost:8428`
- VictoriaLogs: `http://localhost:9428` (UI at
  `http://localhost:9428/select/vmui/`)
- VictoriaTraces: `http://localhost:10428`

## 5. `make data`

```bash
make data                        # SOURCE=s3 (default), needs the AWS values in .env
make data SOURCE=local:data      # an existing local mirror of the S3 layout, no AWS creds needed
```

A local mirror at `<path>` must follow the same layout as the S3 bucket:
unpartitioned tables as `<path>/<table>.csv` (e.g. `data/branches.csv`) and
partitioned tables as `<path>/<table>/year=YYYY/month=MM/day=DD/<file>.csv`
(e.g. `data/transactions/year=2026/month=06/day=17/transactions_20260617.csv`).

What it does: ingests CSVs to Parquet with a manifest (idempotent — a rerun
skips files already ingested, matched by S3 ETag or, in local mode, SHA-256),
runs the dbt-duckdb pipeline (staging → serving) with a whole-week date
shift so the data always looks recent relative to `LOAD_DATE` (today, by
default), loads the result into the `latam_golden` Postgres database, then
resets `latam_app` as a fresh copy of it.

Expect it to take 15–20 minutes per run and use up to about 3.6 GB of RAM
for the dbt-duckdb process (its own memory cap is 3 GB; the rest is
Python/dbt overhead).

## 6. Daily commands

```bash
make demo-reset   # Reset latam_app from latam_golden, discarding any in-app edits (03 §7)
make client       # Regenerate frontend/src/client from the running backend's OpenAPI schema — never hand-edit it
make check        # Lint + types + import-linter + unit tests (backend, pipeline, frontend)
make test         # Backend + pipeline unit tests only
```

## 7. Claude Code MCP servers

[`.mcp.json`](.mcp.json) declares four MCP servers for Claude Code. `playwright`,
`victorialogs` and `victoriatraces` are compose services
(`docker/docker-compose.devtools.yml`, dev only) on `localhost:8931`, `:8081`
and `:8082`, so they are available only while `make up` is running. `deepwiki`
(remote HTTP) is a docs-lookup helper, not a harness. `make setup` calls
`make mcp-setup`, which pulls the three images.

Agents open the app at `http://nginx/` (the Playwright browser runs on the
compose network, so `localhost` is not the app). After cloning, or after any
change to `.mcp.json`, restart Claude Code to reload it and approve the
project's MCP servers when prompted.

The `/wave-run` card workflow's verifier uses these three as mandatory
runtime harnesses — see
[`.claude/skills/wave-run/SKILL.md`](.claude/skills/wave-run/SKILL.md).

## 8. Troubleshooting

- **Port already in use**: stop whatever holds `80`/`5432`/`3000`/`8428`/
  `9428`/`10428`; there are no port variables to move around them.
- **`make up` seems to hang**: it runs `docker compose ... up -d --build
  --wait`, so it blocks until every service reports healthy. `backend` and
  `frontend` both have a `start_period` to cover cold boot (backend's
  reload server, frontend's `npm ci` + Vite); a first `--build` run is
  slower than a cached one.
- **DuckDB memory during `make data`**: capped at 3 GB
  (`pipeline/dbt/profiles.yml`); if the host is memory-constrained, close
  other heavy processes before running it.
- **Reset everything** (containers, networks and volumes — Postgres data,
  Grafana/Victoria* storage):
  ```bash
  docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml down -v
  ```
  (`make down` alone stops and removes containers but keeps volumes.)

## 9. Deployment

Not yet; see [`07-execution-plan.md`](docs/solution-docs/07-execution-plan.md) D4.
