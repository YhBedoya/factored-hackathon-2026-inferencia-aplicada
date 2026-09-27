# Spec: D1-A — Platform foundation and bank data v0

Card: `07-execution-plan.md` D1, Dev A track, rows A1–A6 (feature groups G1 + G2). Owner: Dev A. Branch `feat/d1-a-platform-data-v0`, based on `develop` (K3 already merged).

## Objective

Stand up the platform that every later card runs on:
- a FastAPI backend with a dependency-aware health route, settings, JSON logging and Alembic;
- a Docker Compose dev stack (Postgres 16, Redis 7, backend and frontend with hot reload, Nginx) and a Makefile;
- CI and pre-commit gates;
- the `bank.*` DDL for all 13 provided tables;
- a reproducible S3 → dbt-duckdb → Postgres → `latam_golden` data load with the whole-week date shift;
- the frontend toolchain;
- the full observability layer (OTel → VictoriaMetrics/Logs/Traces + Grafana + MCP).

It serves the "Done when" lines of A1–A6 and end-of-day test steps 1–3. For step 5 it supplies the structured logger that B2's LLM-call log lines use. The observability layer is the last work in the card and the first thing cut if the card runs late (07 D1 "If behind").

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | Every TIMESTAMP column in `bank.*` is interpreted as **UTC** and stored as `timestamptz`. Local display and relative-date resolution use the customer's country time zone: `BANK_TZ` MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`. This card only stores the value and documents the mapping. The code that converts is D2's. The finding that `process_date` follows UTC−6 in every country, including CO and AR, is recorded as a D1.3 data-quality finding | Human Q1(a). EDA: `process_date` = the previous day for every row stamped 00:00–05:59, in all 3 countries. 03 §5 ("`BANK_TZ` per country"). Closes 07 §8 row "Time zone of `transaction_date`" |
| D2 | K3 `TxView.occurred_at` becomes `AwareDatetime` (UTC). FakeBank (B1) must return aware UTC datetimes | Consequence of D1. K3 docstring deferred this to A5 |
| D3 | `bank.*` keeps the **source enum values verbatim** ("Tarjeta Crédito", "México", …). They are guarded by dbt `accepted_values` on `products.product_type`, `products.product_status`, `customers.customer_status`, `customers.country` and `transactions.transaction_status`. The mapping to the K3 Literals lives in each domain's repository (D2) | Human Q2(a). 03 §3 (observed Spanish enums are documented, not hidden) |
| D4 | `bank.*` DDL is a **hand-written Alembic migration** for all 13 tables, with no ORM classes. Alembic `env.py` gets an `include_object` filter so autogenerate never proposes dropping unmodeled `bank.*` tables | Human Q3(a). 03 §6 ("DDL owned by Alembic") |
| D5 | **Full observability layer is in scope, as the last task(s), cut first:** an OTel collector, VictoriaMetrics, VictoriaLogs, VictoriaTraces, Grafana (datasources provisioned), FastAPI/asyncpg/Redis auto-instrumentation, and the Victoria MCP servers in `.mcp.json`. `make up` includes this layer | Human Q4(c). 01 §8, CLAUDE.md (`make up` = "dev stack with hot reload + observability"), 07 D1 If-behind |
| D6 | `make data` ingests **from S3 by default**, or from an existing local mirror with `SOURCE=local:<path>`. The mirror uses the S3 layout `<path>/<table>/year=…/month=…/day=…/*.csv`, plus the root CSVs `<path>/<table>.csv` for unpartitioned tables. Only the 13 table names are read, so `data/raw/` and `data/_parquet/` under `data/` are never picked up. The manifest records the S3 ETag and size, or for local sources the file SHA-256 and size, plus a `source` field. A rerun skips unchanged objects by ETag (S3) or by hash (local). Local mode needs no AWS credentials | **Amended mid-card:** human changed Q5 from (a) S3 only to (b) S3 + local mirror. It lets the load and its proofs run from the mirror both devs already have. 03 §2 step 1, 03 §4 |
| D7 | Scope excludes: Pandera contracts, `relationships` and freshness tests, freshness fixtures, incremental models, dbt `docs generate` (all D6 G2b); identity provisioning (D2 G4); the held-out freeze check (no `eval/` yet). dbt runs as a full refresh | Assumption 1. 07 A5 row lists only ingest → dbt (types, enums, date shift) → COPY → golden |
| D8 | dbt tests today: `unique` + `not_null` on each serving PK, plus the `accepted_values` in D3. Staging dedups on the PK and keeps duplicates in `stg_<table>__rejects` | Assumption 2. 03 §2 |
| D9 | `pipeline/` is its own uv project. `make data` runs on the host and reaches Postgres on a published `localhost:5432`. The dbt-duckdb warehouse file lives under git-ignored `data/` | Assumption 3. K3 D8 pattern (one uv project per component) |
| D10 | Ingest writes `data/raw/<table>/year=…/month=…/day=…/*.parquet` (source CSV → Parquet) plus `data/raw/_manifest.json` (`source` = `s3` or `local`, key or relative path, size, ETag or SHA-256, downloaded_at). For S3, bucket, prefix and credentials come only from env vars or an AWS profile | Assumption 4, D6. 03 §1–2, R10 |
| D11 | Date shift: `max_data_date` = the last partition date (2026-06-17); `load_date` = today, overridable with `LOAD_DATE`; `date_offset_days = 7 × floor((load_date − max_data_date) / 7)`. It is applied in dbt serving to every DATE and TIMESTAMP column. Time-of-day columns (`branches.opening_time`, `closing_time`) are not dates and are not shifted | Assumption 5. 03 §5, ADR-010 |
| D12 | The migration also creates `app.system_metadata` (the only `app` table today), because 03 §5 records the offset there. `app`, `identity` and `audit` are otherwise empty | Assumption 6. 03 §5–6 vs A4 row |
| D13 | `bank.*` shape: observed source columns; PKs; **no FK constraints** (03 §3 keeps orphans); `origin text not null default 'dataset'`, `created_at timestamptz`, `conversation_id uuid null` on `complaints` only (`digital_events` stays **(proposed)**); the four **(proposed)** indexes from 03 §6; money columns `numeric`; `days_past_due integer`; hive partition columns not loaded | Assumption 7. 03 §3, §6 |
| D14 | `make data` upgrades Alembic on `latam_golden`, then truncates and COPYs `bank.*` into it (idempotent), writes `app.system_metadata`, prints row counts for all 13 tables, then runs the `demo-reset` step: terminate connections to `latam_app`, drop it, `CREATE DATABASE latam_app TEMPLATE latam_golden`. All 13 tables load, `digital_events` included. Moving `digital_events` to D2 is only the If-behind cut | Assumption 8. 03 §7, ADR-011, 07 D1 End-of-day step 2 |
| D15 | `GET /api/v1/health` is public. It returns `200` when DB and Redis are both up, `503` otherwise, with the same body either way | Assumption 9. 04 §3 (health is public) |
| D16 | Logging: structlog JSON to stdout, `request_id` middleware, `trace_id` from the active OTel span and `conversation_id` bound when present. With D5 in place, logs are exported through the collector to VictoriaLogs | Assumption 10, 06 §4 "Logging", 01 §8 |
| D17 | Compose layers `docker/docker-compose.{base,dev,observability}.yml`: Postgres 16, Redis 7, backend (uvicorn `--reload`, source mounted), Vite (HMR), Nginx on `localhost:80` (`/api` → backend, everything else → Vite) | Assumption 11. 06 §3, 01 §9, A2/A6 rows |
| D18 | `make setup` assumes uv, Node 22 + npm and Docker are installed. It runs `uv sync` (backend, pipeline), `npm ci` (frontend), `pre-commit install` (including the `commit-msg` hook), and copies `.env.example` to `.env` if missing | Assumption 12. CLAUDE.md "Planned commands", 01 §9 |
| D19 | `make client` really runs `@hey-api/openapi-ts` against `/api/v1/openapi.json` into `frontend/src/client/` (generated, never hand-edited) | Assumption 13. 06 §4 "Frontend" |
| D20 | CI is GitHub Actions on PRs and pushes to `develop` and `main`: Ruff, mypy, import-linter, pytest (backend and pipeline), Biome, gitleaks (full history). No CI caching. Pre-commit runs the same linters plus gitleaks and a Conventional Commits `commit-msg` hook | Assumption 14. 06 §4–5, A3 row, 07 If-behind (caching) |
| D21 | `backend/.importlinter` holds the 06 §2 contracts: layers `app.api` → `app.domains` → `app.core`; only `app.core.llm` imports `anthropic`/`langchain_anthropic`/`boto3`/`aioboto3`/`langchain_aws`; `app.domains.conversation` may not import any `*.repository`; `app.core.llm` may not import any `app.domains.*.repository`. They are written so modules that don't exist yet don't break the run | Assumption 15. 06 §2 |
| D22 | No R-rule tests in this card: A1–A6 touch none of R1–R6, R11 or R13 (`/health` is public; R13 starts with the first non-public route in D2) | Assumption 16. wave-run test budget |

## Contracts (delta only)

**`GET /api/v1/health`** (public; D15)
```python
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["up", "down"]      # SELECT 1 on the app DB, short timeout
    redis: Literal["up", "down"]   # PING, short timeout
```

**K3 change** (D2): `backend/app/domains/transactions/schemas.py` sets `TxView.occurred_at: AwareDatetime` with the docstring "UTC; display in `BANK_TZ` of the customer's country (D1-A D1)".

**`app.system_metadata`** (D12), one row per load:
`run_id text pk, load_date date, max_data_date date, date_offset_days int, manifest_sha256 text, policy_hash text null, loaded_at timestamptz default now()`.

**`bank.*`** (D4, D13): the 13 tables in 03 §6 with the column sets observed in the source CSVs. PKs are the `*_id` first column, except `daily_exchange_rates`, whose PK is (`date`, `source_currency`, `target_currency`). TIMESTAMP columns are `timestamptz` (D1). Schemas `app`, `identity`, `audit` are created (empty apart from `app.system_metadata`). The `downgrade` drops everything the upgrade created.

**Databases**: `latam_app` (served), `latam_golden` (template), as in 03 §7.

**`.env.example`** (placeholders only, R10):
- Postgres: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL` (→ `latam_app`), `GOLDEN_DATABASE_URL`
- `REDIS_URL`
- S3: `AWS_PROFILE` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_PREFIX` (unused when `SOURCE=local:…`)
- `SOURCE` (optional; `s3` by default, or `local:<path>`; also accepted as `make data SOURCE=local:data`)
- `LOAD_DATE` (optional)
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- LLM: `LLM_PROVIDER`, `ANTHROPIC_API_KEY` (K1, left empty)

**Makefile targets**: `setup`, `up`, `down`, `check` (lint + types + import-linter + unit tests), `test`, `data`, `demo-reset`, `client`.

**Docs updated by this card** (decision record for D1):
- 07 §8 row "Time zone of `transaction_date`" → decided.
- `decision-log.md` "Deferred to implementation" row → decided.
- 01 §11 open item closed.
- 03 §5 gets the UTC + `BANK_TZ` zones.
- 01 §10 / 03 §3 get the CO/AR `process_date` finding.
- 03 §2 step 1 gets one line noting the `SOURCE=local:<path>` mirror option (D6).

## Touch map

- `backend/`:
  - `pyproject.toml` (+ fastapi, uvicorn, pydantic-settings, sqlmodel, asyncpg, alembic, redis, structlog, opentelemetry-*, import-linter, httpx)
  - `Dockerfile`, `.importlinter`, `alembic.ini`
  - `app/main.py`
  - `app/api/` (router, `v1/health.py`)
  - `app/core/` (`config.py`, `db.py`, `redis.py`, `logging.py`, `telemetry.py`)
  - `app/alembic/` (`env.py`, `versions/0001_schemas_and_bank.py`)
  - `app/domains/transactions/schemas.py` (D2)
  - `tests/unit/test_health.py`
- `pipeline/`:
  - `pyproject.toml`
  - `ingest/` (S3 or local mirror → Parquet + manifest)
  - `dbt/` (project, profile, `staging/`, `serving/` with the date shift, `schema.yml` tests)
  - `load/` (Alembic upgrade on golden, COPY, system_metadata, counts, demo-reset)
  - `tests/test_date_shift.py`
- `frontend/`: Vite + React 19 + TanStack Router/Query + Tailwind v4 + Biome scaffold, `package.json` + lock, `openapi-ts.config.ts`, `src/client/` (generated).
- `docker/`:
  - `docker-compose.base.yml`, `docker-compose.dev.yml`, `docker-compose.observability.yml`
  - `nginx/dev.conf`
  - `otel/collector.yaml`
  - `grafana/provisioning/`
- Root:
  - `Makefile`, `.env.example`, `.pre-commit-config.yaml`
  - `.github/workflows/ci.yml`
  - `.mcp.json`
  - `.gitignore` (node_modules, dbt target, the DuckDB file; `data/` is already ignored)
- Docs: the rows listed under "Docs updated by this card".

## Test list

| Test | Proves |
|---|---|
| `backend/tests/unit/test_health.py::test_health_up_and_down` | A1: 200 + `db/redis: up` with both fakes healthy; 503 + `db: down` when the DB probe fails. Fakes only, no containers |
| `pipeline/tests/test_date_shift.py::test_offset_is_whole_weeks` | A5 "within the past 7 days": the offset is a multiple of 7, and `max_data_date + offset` lies in `(load_date − 7, load_date]` for several `load_date`s (including `load_date == max_data_date` → 0) |

Everything else is a runnable proof in the Success criteria. No R-rule tests (D22).

## Boundaries

- **Always:**
  - S3 credentials and the bucket name only via env or profile.
  - Local mode only reads the 13 table paths under the mirror and never writes into it.
  - Treat `data/`, `data/raw/` and `data/secrets/` as git-ignored.
  - DDL only through Alembic.
  - Log JSON only.
  - Keep the observability task(s) last in the plan.
- **Ask first:**
  - Changing any K3 contract beyond D2.
  - Adding tables beyond `app.system_metadata`.
  - Normalizing or rewriting source values.
  - Dropping a table from the load (apart from the named `digital_events` cut).
  - Committing anything under `docs/official-docs/`.
- **Never:**
  - Commit `.env`, keys, `data/` or the dictionary PDF (R10).
  - Reproduce S3 keys in code, docs or tests.
  - Import an LLM SDK outside `app.core.llm`.
  - Touch `eval/scenarios/heldout/`.
  - Shift dates in raw or staging (03 §5).

## Success criteria

1. **A1:**
   - With the stack up, `curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/health` → `200` and body `{"status":"ok","db":"up","redis":"up"}`.
   - After `docker compose … stop redis` it returns `503` with `"redis":"down"`.
   - The backend logs one JSON line per request, with `request_id` and `trace_id`.
2. **A2:** on a fresh clone (with `.env` values filled in), `make setup && make up` succeeds and the health check above returns 200. `make down` stops the stack.
3. **A3:**
   - The CI workflow is green on the PR.
   - `make check` passes locally.
   - Committing a file that contains a fake AWS key (e.g. `AKIA` + 16 chars plus a 40-char secret) is rejected by the pre-commit gitleaks hook.
   - `gitleaks detect` over full history passes.
4. **A4:** against an empty DB, `uv run alembic upgrade head` → `uv run alembic downgrade base` → `upgrade head`, run in `backend/`, all exit 0. After `downgrade base`, `\dn` shows no `bank`/`app`/`identity`/`audit` schemas.
5. **A5, row counts:** `make data SOURCE=local:data` prints non-zero row counts for all 13 `bank.*` tables (12 if the `digital_events` cut is taken, stated in the PR). `app.system_metadata` has a row with `date_offset_days % 7 = 0`.
6. **A5, recency:** `SELECT max(transaction_date) >= now() - interval '7 days' FROM bank.transactions` → `t` in `latam_app`.
7. **A5, golden DB:** `psql -l` lists `latam_golden`.
8. **A5, idempotency:** a second `make data SOURCE=local:data` ingests nothing (every file is skipped by hash) and produces the same counts. The manifest entries show `source: local` and a SHA-256. S3 mode is proven once by `make data` with credentials: the ingest completes, the manifest shows ETags, and a rerun skips every object by ETag. The fresh-clone path uses S3 (03 §2).
9. **A5, demo reset:** an `UPDATE` in `latam_app` followed by `make demo-reset` restores the golden value.
10. **A5, enums:** dbt tests pass, including the `accepted_values` in D3.
11. **A6:**
    - `make up` serves the empty React page at `http://localhost/`.
    - `make client` regenerates `frontend/src/client/`.
    - Biome passes in `make check`.
12. **Observability (D5):**
    - After a health request, the request's trace is visible in VictoriaTraces, a log line with its `request_id` in VictoriaLogs, and an HTTP server metric in VictoriaMetrics.
    - Grafana at its dev port shows the three datasources as provisioned.
    - `.mcp.json` declares the VictoriaLogs and VictoriaTraces MCP servers.
    - If this item is cut, the PR says so and items 1–11 still hold.
13. **D1 docs:** the D1 decision is recorded in the docs listed under Contracts.

## Open questions

- Whether `.mcp.json` also gets a VictoriaMetrics MCP server. 01 §8 lists only Logs and Traces. Dev A decides while building D5; the default is Logs + Traces only.
- Whether local mode also runs without an `.env` at all, or only without AWS keys. The spec requires only the latter: Postgres settings still come from `.env`.
- 06 §5 says branches come off `main`, but this card is based on `develop`. The team should reconcile 06 §5 with the `develop` integration branch. That doesn't block this card.
