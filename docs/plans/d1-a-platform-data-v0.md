# Plan: D1-A — Platform foundation and bank data v0

Spec: [`docs/specs/d1-a-platform-data-v0.md`](../specs/d1-a-platform-data-v0.md) · Branch: `feat/d1-a-platform-data-v0` (base `develop`, PR targets `develop`)

## Facts checked against the repo

**What is on disk (from K3):**
- `backend/` is a standalone uv project (`requires-python = ">=3.12,<3.13"`, `[tool.uv] package = false`, no build-system). `backend/uv.lock` is committed. The only runtime dependency is `pydantic`, and the dev group has ruff, mypy and pytest.
- Tool config lives in `backend/pyproject.toml`. Ruff: py312, line-length 100, select `E F W I B UP RUF`. mypy uses the `pydantic.mypy` plugin, with strict overrides for `app.core.*` and `app.domains.conversation.*` (`no_implicit_reexport`, so every module needs an explicit `__all__`). pytest: `pythonpath = ["."]`, `testpaths = ["tests"]`.
- Existing code: `app/core/errors.py`, `app/domains/{customers,cards,transactions}/schemas.py`, `app/domains/conversation/{schemas,state}.py`, `app/domains/conversation/tools/{context,bank}.py`, and `tests/unit/test_r1_customer_scope.py` (2 tests, must stay green).
- Nothing exists yet for any of these, so every file in the touch map is new except where it is marked "mod":
  - `backend/app/main.py` and `backend/app/api/`
  - Alembic
  - `pipeline/`, `frontend/`, `docker/`
  - `Makefile`, `.env.example`, `.pre-commit-config.yaml`, `.github/`, `.mcp.json`
- There is no `.env` at the repo root yet.
- Root `pyproject.toml` / `uv.lock` / `.venv` belong to the EDA notebooks. Don't touch them. `.gitignore` already ignores `.env`, `data/`, `.venv/` and `__pycache__/`.
- Ruff flags the Unicode minus `−` in docstrings (RUF002), so use ASCII `-`. Run `uv run ruff format` after writing, and don't hand-format.

**Host (this machine):**
- uv 0.11, Docker 29 + Compose v5, Node 22.22 + npm 10.9, pre-commit 3.6, GNU make and aws-cli v2 are installed.
- **`psql`, `gitleaks`, `duckdb` and `dbt` CLIs are not installed.** Run psql as `docker exec -i latam-cs-postgres-1 psql …` and gitleaks through its Docker image or the pre-commit hook. duckdb and dbt come from `pipeline/`'s uv env.
- Ports 80, 3000, 5432, 6379, 8000, 5173, 4317/4318, 8428, 9428 and 10428 are free. Use the spec's fixed standard ports. No port variables.
- A full local mirror of S3 `data/` is at `data/` on this machine (both devs have one). It has the S3 layout: `data/<table>/year=…/month=…/day=…/*.csv` and root `data/<table>.csv`. The same directory also holds `data/_parquet/` (EDA) and, after ingest, `data/raw/`, which is why ingest reads only the 13 table names (D6). `SOURCE=local:data` is resolved against the repo root, not the cwd. Local mode needs no AWS credentials. `.env` still supplies the DB URLs.
- The AWS profile `factored-datathon` exists in `~/.aws`. The bucket name and prefix are **not** in the repo. They are needed only for the one-time S3 proof (T7's S3 step, and the verifier's `make data` for criterion 8): the human fills `S3_BUCKET`, `S3_PREFIX` and `AWS_PROFILE=factored-datathon` into `.env`. Never write them into any tracked file.

**Plan-wide conventions (so tasks agree without talking):**
- Compose project name `latam-cs` (set as top-level `name:` in `docker/docker-compose.base.yml`), so containers are `latam-cs-<service>-1`. Services: `postgres`, `redis`, `backend`, `frontend`, `nginx`. The observability overlay adds `otel-collector`, `victoriametrics`, `victorialogs`, `victoriatraces` and `grafana`.
- The Makefile compose command is `docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml` (T18 appends `-f docker/docker-compose.observability.yml`).
- Published host ports:
  - Postgres `5432` (D9) and Nginx `80` (D17).
  - Observability overlay only: Grafana `3000`, VictoriaMetrics `8428`, VictoriaLogs `9428`, VictoriaTraces `10428`.
  - Redis, the backend, Vite and the collector are compose-network only.
- URLs:
  - `DATABASE_URL = postgresql+asyncpg://<user>:<pw>@localhost:5432/latam_app` and `GOLDEN_DATABASE_URL = …/latam_golden`. These are the host values. The compose `environment:` overrides the host to `postgres` for the backend container (assumption 3). The pipeline strips `+asyncpg` to get a libpq DSN.
  - `REDIS_URL` in the container is `redis://redis:6379/0`.
- Postgres starts with `POSTGRES_DB=latam_app`, so health is 200 on a fresh clone before `make data`. `latam_golden` is created by the load step.
- Alembic: `backend/alembic.ini` with `script_location = app/alembic`. `env.py` takes the URL from `app.core.config` settings (`DATABASE_URL`), so the golden upgrade is `cd backend && DATABASE_URL=$GOLDEN_DATABASE_URL uv run alembic upgrade head`. First revision id `0001`.
- `.env` handling:
  - Verify commands that need `.env` values start with `set -a && . ./.env && set +a` from the repo root.
  - The Makefile exposes `.env` to its recipes (`-include .env` + `export`).
  - `.env.example` holds placeholders only (R10). Its local Postgres/Redis values must work as-is for `make up`, and S3/LLM secrets stay empty.
  - `SOURCE` (optional): `s3` by default, or `local:<path>`. `make data SOURCE=local:data` overrides `.env` because the Makefile uses a bare `export`.
- Settings: importing `app.main` and running `tests/unit/` must work with **no `.env` and no env vars**. An empty `OTEL_EXPORTER_OTLP_ENDPOINT` means "don't export".

**Source data (checked on the local copy under `data/`, which mirrors S3 `data/`):**
- Six unpartitioned tables are single CSVs at the prefix root: `branches`, `customers`, `daily_exchange_rates`, `marketing_campaigns`, `products`, `service_agents`.
- Seven are partitioned as `<table>/year=YYYY/month=MM/day=DD/<table>_YYYYMMDD.csv`: `call_center_interactions`, `call_transcripts`, `campaign_sends`, `complaints`, `digital_events`, `satisfaction_surveys`, `transactions`. The last partition is `2026-06-17` for all seven. `campaign_sends` starts 2023-07-01 and the others start 2023-06-17. The local copy is about 6 GB of CSV.
- **Every CSV starts with a UTF-8 BOM.** `call_transcripts.full_text` has quoted newlines. Empty fields must become NULL.
- `process_date` is a real source column and is loaded. Only the hive `year/month/day` columns are dropped (D13).
- DATE/TIMESTAMP/TIME columns (DuckDB sniff on a sample, to be confirmed on the full set):

  | Table | DATE | TIMESTAMP | TIME |
  |---|---|---|---|
  | branches | `branch_opening_date` | | `opening_time`, `closing_time` |
  | customers | `date_of_birth` | `registration_date`, `last_updated` | |
  | daily_exchange_rates | `date` | | |
  | marketing_campaigns | `start_date`, `end_date` | | |
  | products | `opening_date`, `expiration_date` | `last_transaction_date`, `last_updated` | |
  | service_agents | `hire_date` | | |
  | call_center_interactions | `process_date` | `interaction_date` | |
  | call_transcripts | `process_date` | | |
  | campaign_sends | `process_date` | `send_date`, `open_date`, `click_date`, `conversion_date` | |
  | complaints | `process_date` | `creation_date`, `assignment_date`, `first_response_date`, `resolution_date`, `closing_date` | |
  | digital_events | `process_date` | `event_date` | |
  | satisfaction_surveys | `process_date` | `survey_date` | |
  | transactions | `process_date` | `transaction_date` | |
- Column typing rule shared by the migration (T6), staging (T8, T9) and serving (T11):
  - Ids, codes, phones, `product_number`, `postal_code`, `document_number`, `response_code` ("00", "05"…) and free text → `text`.
  - DATE → `date`. TIMESTAMP → `timestamptz`, the value read as UTC (D1). TIME → `time`, not shifted (D11).
  - Money (`amount`, `amount_usd`, `current_balance`, `credit_limit`, `claimed_amount`, `budget`, `conversion_value`, `send_cost`, `estimated_monthly_income`, the exchange-rate columns), `interest_rate` and `fraud_score` → `numeric`. These are the columns K3 types as `Decimal`.
  - `days_past_due` → `integer`. `True`/`False` → `boolean`. Integer-valued counts → `integer`. Other fractional values (scores, lat/long, durations) → `double precision`.
  - DuckDB `CAST('512.0' AS INTEGER)` works.
- Observed enum values for the D3 `accepted_values`:
  - `customers.country`: Argentina, Colombia, México
  - `customers.customer_status`: Active, Closed, Inactive, Suspended
  - `products.product_type`: Cuenta Ahorro, Cuenta Corriente, Inversión, Préstamo Hipotecario, Préstamo Personal, Seguro, Tarjeta Crédito, Tarjeta Débito
  - `products.product_status`: Active, Blocked, Closed, Suspended
  - `transactions.transaction_status`: Approved, Declined, Pending, Reversed
- Known row for the time-zone proof: `transactions.transaction_id = 'TRX-UIWYPTP5S7PTBYJUSELQ'` has `transaction_date = 2026-06-17 19:51:02` in the source. The local copy has 4,425,008 transactions with no duplicate ids. `digital_events` is the largest table (about 10M rows).

**Git history (for gitleaks):**
- The only key-shaped hit in history is commit `f3582a8`, which has `aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"`. That is a variable reference, not a value.
- The dictionary PDF was never committed. Three other official PDFs are tracked.
- The pre-commit fake-key proof must not use `AKIA…EXAMPLE`, because gitleaks allowlists it. Use a random `AKIA` + 16 `[A-Z2-7]` chars.

## Components

| Component | Path | Depends on |
|---|---|---|
| Settings, DB/Redis clients and probes | `backend/app/core/{config,db,redis}.py` | pydantic-settings, SQLAlchemy async/asyncpg (via SQLModel), redis-py |
| API: app factory, router, health | `backend/app/main.py`, `backend/app/api/{router.py,v1/health.py}` | core probes |
| Logging + base telemetry | `backend/app/core/{logging,telemetry}.py` | structlog through stdlib `logging`; OTel SDK `TracerProvider` + FastAPI instrumentation, no exporter (assumption 1) |
| Migration | `backend/alembic.ini`, `backend/app/alembic/{env.py,script.py.mako,versions/0001_schemas_and_bank.py}` | settings; hand-written DDL (D4, D13) |
| Dev stack | `backend/Dockerfile`, `docker/docker-compose.{base,dev}.yml`, `docker/nginx/dev.conf`, `.env.example`, `Makefile` | backend app |
| Import contracts | `backend/.importlinter` | `06` §2, D21 |
| Ingest | `pipeline/ingest/` | boto3 (S3 mode) or a local mirror (`SOURCE=local:<path>`); `data/raw/` + `_manifest.json` (D6, D10) |
| dbt project | `pipeline/dbt/` (`dbt_project.yml`, `profiles.yml`, `models/staging`, `models/serving`, `macros/`, `tests/generic/`) | dbt-duckdb over `data/raw/**/*.parquet`; warehouse file under `data/` (D9) |
| Date offset | `pipeline/load/date_shift.py` | stdlib only (D11) |
| Load + demo reset | `pipeline/load/{__main__,postgres,demo_reset}.py` | dbt serving tables, backend Alembic, Postgres (D14) |
| Frontend | `frontend/` (Vite, React 19, TanStack Router/Query, Tailwind v4, Biome, `openapi-ts.config.ts`, `src/client/`) | Nginx dev proxy, `/api/v1/openapi.json` |
| Gates | `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | Makefile check pieces (D20) |
| Observability | `backend/app/core/telemetry.py` (exporters), `docker/docker-compose.observability.yml`, `docker/otel/collector.yaml`, `docker/grafana/provisioning/`, `.mcp.json` | everything above; cut first (D5) |

## Build order

1. **T1–T3, backend code.** Health, logging and `trace_id` need no infrastructure and are proved with a fake-backed test and a TestClient call. They come first because the Docker image runs this app.
2. **T4–T5, containers, then Makefile + import-linter.** These give every later task a running Postgres and a `make check` that grows as pieces land.
3. **T6, migration.** It needs the running Postgres. It comes before the load, which upgrades golden with it, and before dbt serving, whose column lists must match it.
4. **T7–T12, data pipeline, in data-flow order:**
   - ingest (it produces `data/raw`)
   - staging for the unpartitioned tables, which sets up the dbt project and conventions
   - staging for the partitioned tables
   - the offset function and its test
   - serving + dbt tests
   - load/golden/demo-reset, which consumes all of the above
5. **T13–T14, frontend, then the frontend behind Nginx + `make client`.** `make client` needs the backend reachable via Nginx.
6. **T15, pre-commit + CI.** It comes after all the linters it runs exist (Ruff, mypy, import-linter, pytest for backend and pipeline, Biome).
7. **T16, the D1 time-zone decision in code (`TxView`) and docs.** It is independent and sits before observability so a cut doesn't take it with it.
8. **T17–T18, observability, last (D5, 07 If-behind).** First the backend exporters, then the compose layer + `.mcp.json`. If cut, both are dropped and T1–T16 stand alone.

## Touch map

| File | New/mod | Change | Task |
|---|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | mod | runtime deps (fastapi, uvicorn[standard], pydantic-settings, sqlmodel, asyncpg, alembic, redis, structlog, opentelemetry-sdk/api, opentelemetry-instrumentation-fastapi); dev: httpx, import-linter; later OTLP exporter + asyncpg/redis instrumentation | T1, T3, T5, T17 |
| `backend/app/core/config.py` | new | `Settings` (pydantic-settings) | T1 |
| `backend/app/core/db.py` | new | async engine (`pool_pre_ping=True`), `ping_db()` | T1 |
| `backend/app/core/redis.py` | new | client, `ping_redis()` | T1 |
| `backend/app/main.py` | new/mod | app factory, router mount, OpenAPI at `/api/v1/openapi.json`; logging/telemetry setup | T2, T3, T17 |
| `backend/app/api/__init__.py`, `router.py`, `v1/__init__.py`, `v1/health.py` | new | `/api/v1` router, `HealthResponse`, health route | T2 |
| `backend/tests/unit/test_health.py` | new | `test_health_up_and_down` | T2 |
| `backend/app/core/logging.py` | new/mod | structlog JSON, `request_id` middleware, `trace_id`/`conversation_id` binding; later an OTel log handler | T3, T17 |
| `backend/app/core/telemetry.py` | new/mod | TracerProvider + FastAPI instrumentation; later OTLP exporters + asyncpg/Redis | T3, T17 |
| `backend/Dockerfile`, `backend/.dockerignore` | new | python:3.12-slim + uv, uvicorn | T4 |
| `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml` | new/mod | postgres, redis, backend (reload, mount), nginx; frontend service added later | T4, T14 |
| `docker/nginx/dev.conf` | new/mod | `/api` → backend; later `/` → Vite (+ websocket for HMR) | T4, T14 |
| `.env.example` | new | spec's list, placeholders | T4 |
| `Makefile` | new/mod | `setup up down test check`; later `data demo-reset client`, the pipeline/frontend/pre-commit pieces, the observability overlay | T5, T12, T14, T15, T18 |
| `backend/.importlinter` | new | 06 §2 contracts (D21) | T5 |
| `backend/alembic.ini`, `backend/app/alembic/env.py`, `script.py.mako`, `versions/0001_schemas_and_bank.py` | new | schemas, 13 `bank.*` tables, `app.system_metadata`, 4 indexes, `include_object` | T6 |
| `pipeline/pyproject.toml`, `pipeline/uv.lock` | new/mod | uv project (py3.12): boto3, duckdb, dbt-core, dbt-duckdb, psycopg; dev: ruff, pytest | T7 |
| `pipeline/ingest/__init__.py`, `__main__.py`, `s3.py`, `local.py` | new | S3 or local mirror → Parquet + manifest | T7 |
| `pipeline/dbt/dbt_project.yml`, `profiles.yml`, `models/sources.yml`, `macros/*.sql` | new | project, DuckDB profile, parquet sources, dedup/shift macros | T8, T11 |
| `pipeline/dbt/models/staging/stg_<t>.sql`, `stg_<t>__rejects.sql` (×13) | new | typed, deduped | T8, T9 |
| `pipeline/load/__init__.py`, `date_shift.py` | new | offset function | T10 |
| `pipeline/tests/test_date_shift.py` | new | `test_offset_is_whole_weeks` | T10 |
| `pipeline/dbt/models/serving/srv_<t>.sql` (×13), `serving/schema.yml`, `tests/generic/unique_combination.sql` | new | date shift, PK + enum tests | T11 |
| `pipeline/load/__main__.py`, `postgres.py`, `demo_reset.py` | new | dbt build → golden → counts → demo reset | T12 |
| `.gitignore` | mod | `pipeline/dbt/target/`, `pipeline/dbt/logs/`, `node_modules/` | T8, T13 |
| `frontend/**` (package.json, package-lock.json, vite.config.ts, tsconfig*.json, biome.json, index.html, `src/main.tsx`, `src/routes/*`, `src/index.css`) | new | scaffold, empty page | T13 |
| `frontend/openapi-ts.config.ts`, `frontend/src/client/**` (generated) | new | `make client` | T14 |
| `.pre-commit-config.yaml`, `.github/workflows/ci.yml` | new | D20 gates | T15 |
| `backend/app/domains/transactions/schemas.py` | mod | `occurred_at: AwareDatetime` (D2) | T16 |
| `docs/solution-docs/{01,03,04,07}-*.md`, `decision-log.md` | mod | D1 record + health row + `occurred_at` UTC + 03 §2 `SOURCE=local:<path>` note | T16 |
| `docker/docker-compose.observability.yml`, `docker/otel/collector.yaml`, `docker/grafana/provisioning/datasources/*.yaml` | new | collector, Victoria ×3, Grafana | T18 |
| `.mcp.json` | new | VictoriaLogs + VictoriaTraces MCP only | T18 |

## Risks and mitigations

| Risk | Mitigation (in task) |
|---|---|
| The unit test or app import needs a real DB, Redis or `.env` | T1 acceptance: import works with no env. T2 overrides the probe dependencies with fakes and never enters the lifespan |
| The per-request log line runs outside the OTel span, so `trace_id` is empty or zero | T3: the request-logging middleware runs inside the FastAPI-instrumented span. Its Verify asserts a non-zero 32-hex `trace_id` |
| structlog is wired straight to stdout, so T17 can't add the OTel log export without a rewrite | T3 renders JSON through stdlib `logging` (ProcessorFormatter). T17 only adds a handler |
| The migration doesn't downgrade cleanly, or autogenerate proposes dropping `bank.*` | T6 Verify runs up → down → up and checks `\dn`. `include_object` skips `bank` objects |
| Migration types and dbt serving output drift apart, so the COPY fails | The shared typing rule is in Facts. T11 reads the migration file and emits exactly its column list. T12's load uses explicit column lists |
| Naive TIMESTAMP gets shifted by a session time zone on the way into `timestamptz` | T11 converts to TIMESTAMPTZ as UTC in DuckDB. T12 Verify checks the known row `TRX-UIWYPTP5S7PTBYJUSELQ` against `2026-06-17 19:51:02+00` + offset |
| BOM, quoted newlines or leading zeros corrupt the data at ingest | T7: all-VARCHAR Parquet, BOM stripped, quoted newlines handled (assumption 2). T8/T9 turn `''` into NULL and cast explicitly |
| S3 bucket/prefix missing, or leaked into the repo | Local mode (`SOURCE=local:data`) carries every proof except the one-time S3 proof. Before T7, the orchestrator confirms the S3 values are in `.env` for T7's S3 step. T7 Verify greps tracked files for the bucket value |
| Local mode picks up `data/raw/` or `data/_parquet/` as input, since they live inside the mirror | T7 reads only the 13 table names (D6). T7 Verify asserts exactly 13 tables and a manifest with `source` set on every entry |
| Full ingest and load are slow (about 6 GB, `digital_events` about 10M rows) | Parallel downloads in T7. Agents run long Verify steps with `run_in_background` and a monitor. The If-behind cut for `digital_events` stays available only as the human's call |
| `CREATE DATABASE … TEMPLATE latam_golden` fails because of open connections | T12: the loader closes its golden connections, terminates backends on both DBs, and uses `DROP DATABASE … WITH (FORCE)`. The backend engine has `pool_pre_ping` (T1) |
| import-linter errors on modules that don't exist yet (`app.core.llm`, `*.repository`) or on uninstalled external packages | T5 acceptance: `lint-imports` reports every contract KEPT today, using optional layers / `include_external_packages` / wildcard support of the installed version. The workaround chosen goes into the state file |
| The gitleaks pre-commit hook can't build (it needs a golang toolchain) | T15 may use the upstream `gitleaks-docker` hook id. The fake-key proof stages a file and runs `pre-commit run gitleaks`, never `git commit`, so nothing leaks into history |
| The CI gitleaks action needs a license | T15 runs the gitleaks Docker image in CI (full history, `fetch-depth: 0`) |
| Vite HMR breaks behind Nginx, or host/container `node_modules` clash | T14: Nginx proxies websocket upgrades, Vite has `hmr.clientPort: 80` and `allowedHosts`, and the frontend container keeps `node_modules` in an anonymous volume |
| Exporting telemetry when the observability layer is cut, so connection errors appear on every request | T17: exporters only when `OTEL_EXPORTER_OTLP_ENDPOINT` is non-empty. Only the observability overlay sets it for the backend |
| A Grafana credential gets added to `.env` (the spec's list is fixed) | T18: the Grafana dev overlay needs no new `.env` variable (anonymous access in dev) |
| K3's T4 guard grep (`fastapi|sqlmodel|alembic…` over `backend/app`) now "fails" | This is expected. It was a K3-only Verify, not a gate. Nothing in this card runs it |

## Tests

| Test | Written by |
|---|---|
| `backend/tests/unit/test_health.py::test_health_up_and_down` | T2 |
| `pipeline/tests/test_date_shift.py::test_offset_is_whole_weeks` | T10 |

No R-rule tests (D22). Every other success criterion is proved by a command in a task's Verify.

Success criteria → tasks:
- 1 (A1): T2, T3, T4
- 2 (A2): T4, T5
- 3 (A3): T5, T15. CI green on the PR is checked by the verifier
- 4 (A4): T6
- 5–10 (A5): T7–T12
- 11 (A6): T13, T14
- 12 (observability): T17, T18
- 13 (D1 docs): T16

## Tasks

- [ ] T1: Backend runtime dependencies, settings, and the DB and Redis probes
  - Depends on: nothing. Builds on K3's `backend/` uv project.
  - Read exactly these: `backend/pyproject.toml`; spec §"Contracts" → `.env.example` and `GET /api/v1/health`; spec D15.
  - Acceptance:
    - Dependencies: `backend/pyproject.toml` adds fastapi, `uvicorn[standard]`, pydantic-settings, sqlmodel, asyncpg, alembic, redis, structlog, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, and dev `httpx`. `uv.lock` is updated.
    - `app/core/config.py`: a `Settings` (pydantic-settings) with `database_url`, `golden_database_url`, `redis_url`, `otel_exporter_otlp_endpoint` (empty = off), `llm_provider`, `anthropic_api_key`, and a `get_settings()` cached accessor. It reads env vars and the repo-root `.env` when present. Importing it with no env and no `.env` works, and the defaults contain no real credentials.
    - `app/core/db.py`: a lazily created async engine (`pool_pre_ping=True`) and `async def ping_db() -> bool` (`SELECT 1` with a short timeout, about 2 s; any error → `False`).
    - `app/core/redis.py`: a client and `async def ping_redis() -> bool` (PING, short timeout, any error → `False`).
    - `app.core` imports no domain. Explicit `__all__` everywhere (strict mypy on `app.core.*`).
  - Verify: `cd backend && uv sync && env -u DATABASE_URL -u REDIS_URL uv run python -c "from app.core.config import get_settings; from app.core.db import ping_db; from app.core.redis import ping_redis; get_settings()" && uv run ruff check app/core && uv run ruff format --check app/core && uv run mypy app`
  - Files: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/core/redis.py`

- [ ] T2: FastAPI app factory and the public `GET /api/v1/health` route with its test
  - Depends on: T1 (`ping_db`, `ping_redis` in `app.core.db` / `app.core.redis`; see the state file for the final names).
  - Read exactly these: spec §"Contracts" → `GET /api/v1/health` and D15; spec §"Test list"; `docs/solution-docs/04-contracts.md` §3 (health is public).
  - Acceptance:
    - `app/main.py` exposes `app` (FastAPI) with the v1 router mounted at `/api/v1` and OpenAPI served at `/api/v1/openapi.json` (needed by `make client`).
    - `app/api/router.py` + `app/api/v1/health.py` define `HealthResponse` exactly as in the spec.
    - The route takes the two probes as FastAPI dependencies, so tests can override them. It returns 200 + `{"status":"ok","db":"up","redis":"up"}` when both are up, and 503 with the same body shape otherwise (`status: "degraded"`).
    - `tests/unit/test_health.py::test_health_up_and_down` uses `app.dependency_overrides` with fake probes, no containers and no lifespan. It asserts 200 + both up, then 503 + `db: "down"` when the DB probe fails.
    - The K3 test still passes.
  - Verify: `cd backend && uv run pytest tests/unit/test_health.py tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/main.py app/api tests && uv run ruff format --check app/main.py app/api tests && uv run mypy app`
  - Files: `backend/app/main.py`, `backend/app/api/__init__.py`, `backend/app/api/router.py`, `backend/app/api/v1/__init__.py`, `backend/app/api/v1/health.py`, `backend/tests/unit/test_health.py`

- [ ] T3: Structured JSON logging with `request_id` and `trace_id` on every request
  - Depends on: T2 (`app.main:app`).
  - Read exactly these: spec D16; `docs/solution-docs/06-engineering-rules.md` §4 "Logging"; `backend/app/main.py`.
  - Acceptance:
    - Setup:
      - `app/core/logging.py` configures structlog to render one JSON object per line **through stdlib `logging`** (ProcessorFormatter on a stdout handler), so a later task can attach an OTel handler to the root logger.
      - A `request_id` middleware takes the id from an incoming `X-Request-ID` header or generates one, binds it through structlog contextvars, and returns it in the `X-Request-ID` response header.
      - A helper binds `conversation_id` when present. Nothing sets it yet.
    - Each request emits one access line with `request_id`, `trace_id`, method, path, status and duration.
    - `app/core/telemetry.py` installs an OTel SDK `TracerProvider` (service name `card-support-backend`) and `FastAPIInstrumentor`, **with no exporter**. The access line is emitted inside the request span, so `trace_id` is the span's 32-hex id, not zeros.
    - uvicorn's own access log is off, so there is no second non-JSON line.
    - `opentelemetry-*` imports stay in `app.core` only.
  - Verify: `cd backend && uv run python -c "from fastapi.testclient import TestClient; from app.main import app; TestClient(app).get('/api/v1/health')" 2>/dev/null | grep '"request_id"' | tail -1 | uv run python -c "import json,re,sys; d=json.loads(sys.stdin.read()); assert d['request_id'] and re.fullmatch('[0-9a-f]{32}', d['trace_id']) and d['trace_id'] != '0'*32, d" && uv run pytest tests/unit/test_health.py -q && uv run ruff check app/core app/main.py && uv run ruff format --check app/core app/main.py && uv run mypy app`
  - Files: `backend/app/core/logging.py`, `backend/app/core/telemetry.py`, `backend/app/main.py`, `backend/pyproject.toml`, `backend/uv.lock`

- [ ] T4: Backend image and dev compose stack (Postgres 16, Redis 7, backend with reload, Nginx `/api`) plus `.env.example`
  - Depends on: T2/T3 (`app.main:app` serves `/api/v1/health`).
  - Read exactly these: spec D15, D17 and §"Contracts" → `.env.example` / Databases; the "Plan-wide conventions" block in the state file.
  - Acceptance:
    - `backend/Dockerfile`: python:3.12-slim + uv, `uv sync --frozen` from `backend/uv.lock`, runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Plus `backend/.dockerignore` (`.venv`, `__pycache__`).
    - `docker/docker-compose.base.yml`:
      - Top-level `name: latam-cs`.
      - `postgres` (postgres:16, `POSTGRES_DB=latam_app`, volume, healthcheck, published `5432:5432`).
      - `redis` (redis:7, healthcheck, not published).
      - `backend`: `env_file: ../.env`, with `environment:` overriding `DATABASE_URL` to host `postgres` and `REDIS_URL=redis://redis:6379/0`. It depends on healthy postgres/redis.
      - `nginx` (published `80:80`).
    - `docker/docker-compose.dev.yml`: the backend runs `uvicorn --reload` with `../backend/app` mounted.
    - `docker/nginx/dev.conf` proxies `/api/` to `backend:8000`. The frontend location comes later, so there is no reference to a `frontend` upstream yet.
    - `.env.example` has exactly the spec's variables with placeholders:
      - Local Postgres/Redis values that work as-is.
      - Host-side `DATABASE_URL`/`GOLDEN_DATABASE_URL` on `localhost:5432`.
      - `S3_BUCKET`, `S3_PREFIX`, AWS keys and `ANTHROPIC_API_KEY` empty.
      - `AWS_PROFILE` and `LOAD_DATE` commented or empty. S3 vars are commented as unused when `SOURCE=local:…`.
      - `SOURCE` optional, empty or commented (default `s3`), documented as `s3` or `local:<path>`.
      - `OTEL_EXPORTER_OTLP_ENDPOINT` empty.
    - With `redis` stopped, health returns 503 with `"redis":"down"`.
  - Verify: `cp -n .env.example .env; docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml up -d --build --wait && sleep 3 && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/health)" = 200 && curl -s localhost/api/v1/health | grep -q '"status":"ok","db":"up","redis":"up"' && docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml stop redis && sleep 2 && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/health)" = 503 && curl -s localhost/api/v1/health | grep -q '"redis":"down"' && docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml start redis && docker logs latam-cs-backend-1 2>&1 | grep '"request_id"' | tail -1 | grep -q '"trace_id"'`
  - Files: `backend/Dockerfile`, `backend/.dockerignore`, `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml`, `docker/nginx/dev.conf`, `.env.example`

- [ ] T5: Makefile (`setup`, `up`, `down`, `test`, `check`) and the import-linter contracts
  - Depends on: T4 (compose files, `.env.example`). T1–T3 (backend code to lint).
  - Read exactly these: spec D18, D21 and §"Contracts" → Makefile targets; `docs/solution-docs/06-engineering-rules.md` §2.
  - Acceptance:
    - `Makefile`:
      - `-include .env` + `export`.
      - A `COMPOSE` variable (the base + dev files from the state file's conventions).
      - `setup`: copies `.env.example` → `.env` if missing, and runs `uv sync` in `backend/`. Later tasks add the pipeline, npm and pre-commit steps.
      - `up`: `$(COMPOSE) up -d --build --wait`.
      - `down`: `$(COMPOSE) down`.
      - `test`: backend `pytest tests/unit -q`.
      - `check`: backend `ruff check`, `ruff format --check`, `mypy app`, `lint-imports`, `pytest tests/unit -q`.
      - Each group of lines is easy for later tasks to extend (pipeline, Biome).
    - `backend/.importlinter` holds the four D21 contracts. `import-linter` is added to backend dev deps.
    - `lint-imports` reports every contract KEPT on today's tree, even though `app.core.llm` and the `*.repository` modules don't exist yet. Record how that was achieved in the state file.
  - Verify: `make down >/dev/null 2>&1; make setup && make up && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/health)" = 200 && make check && (cd backend && uv run lint-imports) && make down && ! docker ps --format '{{.Names}}' | grep -q '^latam-cs-'`
  - Files: `Makefile`, `backend/.importlinter`, `backend/pyproject.toml`, `backend/uv.lock`

- [ ] T6: Alembic setup and the hand-written `0001` migration (schemas, 13 `bank.*` tables, `app.system_metadata`)
  - Depends on: T1 (`app.core.config.get_settings().database_url`), T4/T5 (`make up` gives Postgres on `localhost:5432`).
  - Read exactly these: spec D1, D4, D12, D13 and §"Contracts" → `bank.*` / `app.system_metadata`; `docs/solution-docs/03-data-architecture.md` §6; the state file's "Source data" facts (column list via `head -1` of each CSV under `data/`, typing rule, time-column table).
  - Acceptance:
    - `backend/alembic.ini` (`script_location = app/alembic`), plus `app/alembic/env.py` (async, URL from settings, `target_metadata` = SQLModel metadata) and `script.py.mako`. `include_object` skips reflected tables that have no model, which today means all `bank.*` tables and `app.system_metadata`, so `alembic check` reports no changes.
    - Revision `0001` (`versions/0001_schemas_and_bank.py`):
      - Schemas: creates `bank`, `app`, `identity` and `audit`.
      - `bank` tables: all 13, with the observed source columns in source order, no hive partition columns, and types per the typing rule (TIMESTAMP → `timestamptz`).
      - Keys: PK on the first `*_id` column, except `daily_exchange_rates` (`date`, `source_currency`, `target_currency`). **No FKs.**
      - `complaints` additionally has `origin text not null default 'dataset'`, `created_at timestamptz` and `conversation_id uuid null`.
      - Indexes: the four 03 §6 ones.
      - `app.system_metadata` exactly as in the spec.
      - `downgrade()` drops everything, including all four schemas.
    - Its column lists are the ones T11 will match.
  - Verify: `set -a && . ./.env && set +a && make up && docker exec -i latam-cs-postgres-1 psql -U "$POSTGRES_USER" -d latam_app -c 'DROP SCHEMA IF EXISTS bank, app, identity, audit CASCADE; DROP TABLE IF EXISTS public.alembic_version' && cd backend && uv run alembic upgrade head && uv run alembic downgrade base && test -z "$(docker exec -i latam-cs-postgres-1 psql -U "$POSTGRES_USER" -d latam_app -Atc "select nspname from pg_namespace where nspname in ('bank','app','identity','audit')")" && uv run alembic upgrade head && test "$(docker exec -i latam-cs-postgres-1 psql -U "$POSTGRES_USER" -d latam_app -Atc "select count(*) from information_schema.tables where table_schema='bank'")" = 13 && uv run alembic check && uv run ruff check app/alembic && uv run ruff format --check app/alembic && uv run mypy app`
  - Files: `backend/alembic.ini`, `backend/app/alembic/env.py`, `backend/app/alembic/script.py.mako`, `backend/app/alembic/versions/0001_schemas_and_bank.py`

- [ ] T7: `pipeline/` uv project and the idempotent S3 → Parquet ingest with manifest
  - Depends on: nothing in code. T4's `.env` exists (DB URLs, optional `SOURCE`). **The S3 step of Verify needs `S3_BUCKET`, `S3_PREFIX` and `AWS_PROFILE` filled in the root `.env`** (the orchestrator confirms before dispatch). The local step needs no AWS credentials.
  - Read exactly these: spec D6, D9, D10; `docs/solution-docs/03-data-architecture.md` §1–2; the state file's "Source data" and local-mirror facts.
  - Acceptance:
    - `pipeline/pyproject.toml`: uv project (py3.12, `package = false`) with boto3, duckdb, dbt-core, dbt-duckdb, psycopg[binary]; dev ruff + pytest; pytest `pythonpath = ["."]`. `uv.lock` is committed.
    - `uv run python -m ingest` (cwd `pipeline/`) reads `SOURCE` from the env, `s3` by default:
      - `s3` (`ingest/s3.py`): lists `s3://$S3_BUCKET/$S3_PREFIX`.
      - `local:<path>` (`ingest/local.py`): walks the mirror, with a relative `<path>` resolved against the repo root. It needs no AWS credentials and never creates a boto3 client.
      - Both read **only** the 13 table names: `<table>/year=…/month=…/day=…/*.csv` and `<table>.csv`. That excludes `data/raw/`, `data/_parquet/` and the S3 backup/root copies.
    - For each CSV it writes all-VARCHAR Parquet (BOM stripped, quoted newlines kept, empty fields → NULL):
      - partitioned tables: `data/raw/<table>/year=…/month=…/day=…/<file>.parquet`
      - unpartitioned tables: `data/raw/<table>/<table>.parquet`
    - `data/raw/_manifest.json` entries use the fields `source` (`s3`/`local`), `key` (the S3 key or the relative path), `size`, `etag` (S3) or `sha256` (local, hex), and `downloaded_at`.
    - A rerun skips every file whose entry has the same `source` and the same ETag+size (S3) or SHA-256+size (local), and whose Parquet exists. Switching source re-ingests. It prints `ingested=N skipped=M`.
    - No bucket name or key in any tracked file.
  - Verify (both ingests move about 6 GB; run them in the background and monitor):
    ```
    set -a && . ./.env && set +a && cd pipeline && uv sync
    env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY SOURCE=local:data uv run python -m ingest
    env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY SOURCE=local:data uv run python -m ingest | grep -q 'ingested=0'
    test "$(ls ../data/raw | grep -v _manifest | wc -l)" = 13
    uv run python -c "import json; m=json.load(open('../data/raw/_manifest.json')); e=m if isinstance(m, list) else m.get('entries', m); e=list(e.values()) if isinstance(e, dict) else e; assert e and all(x['source']=='local' and len(x.get('sha256',''))==64 for x in e)"
    # S3 step (one-time proof; needs the S3 values in .env)
    SOURCE=s3 uv run python -m ingest && SOURCE=s3 uv run python -m ingest | grep -q 'ingested=0'
    uv run ruff check ingest && uv run ruff format --check ingest && cd .. && ! git grep -nF "$S3_BUCKET" -- . ':!*.lock'
    ```
    Record the manifest's real JSON shape in the state file, because T10 and T12 read it.
  - Files: `pipeline/pyproject.toml`, `pipeline/uv.lock`, `pipeline/ingest/__init__.py`, `pipeline/ingest/__main__.py`, `pipeline/ingest/s3.py`, `pipeline/ingest/local.py`

- [ ] T8: dbt-duckdb project and staging for the six unpartitioned tables
  - Depends on: T7 (`data/raw/<table>/…parquet`), T6 (column types in `backend/app/alembic/versions/0001_schemas_and_bank.py`).
  - Read exactly these: spec D7, D8, D9; `docs/solution-docs/03-data-architecture.md` §2–3; `backend/app/alembic/versions/0001_schemas_and_bank.py`.
  - Acceptance:
    - Project setup:
      - `pipeline/dbt/dbt_project.yml` + `profiles.yml` (dbt-duckdb, warehouse file under the repo's `data/` so it is git-ignored, path resolved from the repo root regardless of cwd, and `TimeZone` set to UTC).
      - `models/sources.yml` declares all 13 raw sources over `data/raw/<table>/**/*.parquet` (no hive columns).
      - A dedup macro in `macros/`. No dbt packages and no `dbt deps`.
    - Staging for the six tables: `models/staging/stg_<t>.sql` casts every column explicitly to its migration type (`nullif(trim(x), '')` first) with no date shift, and dedups on the PK. `stg_<t>__rejects.sql` keeps the duplicate rows.
    - `.gitignore` adds `pipeline/dbt/target/` and `pipeline/dbt/logs/`. Record the dbt invocation (cwd, `--project-dir`/`--profiles-dir`) in the state file.
  - Verify: `cd pipeline/dbt && uv run --project .. dbt build --project-dir . --profiles-dir . --select staging && cd ../.. && git check-ignore -q pipeline/dbt/target/x pipeline/dbt/logs/x && test -z "$(git status --porcelain --untracked-files=all | grep -E '\.duckdb|/target/|/logs/')"`
  - Files: `pipeline/dbt/dbt_project.yml`, `pipeline/dbt/profiles.yml`, `pipeline/dbt/models/sources.yml`, `pipeline/dbt/macros/dedup.sql`, `pipeline/dbt/models/staging/stg_{branches,customers,daily_exchange_rates,marketing_campaigns,products,service_agents}{,__rejects}.sql`, `.gitignore`

- [ ] T9: dbt staging for the seven partitioned tables
  - Depends on: T8 (the dbt project, the dedup macro, the invocation recorded in the state file), T6 (column types).
  - Read exactly these: `pipeline/dbt/models/staging/stg_products.sql` and `stg_products__rejects.sql` (the pattern to mirror); `backend/app/alembic/versions/0001_schemas_and_bank.py`.
  - Acceptance:
    - For `call_center_interactions`, `call_transcripts`, `campaign_sends`, `complaints`, `digital_events`, `satisfaction_surveys` and `transactions`: `stg_<t>.sql` casts each column to its migration type. `process_date` is kept, and hive `year/month/day` are dropped. The model dedups on the PK, with rejects in `stg_<t>__rejects.sql`.
    - TIMESTAMPs stay naive-UTC in staging. There is no shift in staging.
    - `stg_transactions` has 4,425,008 rows if S3 matches the local copy. Record the real counts in the state file.
  - Verify: `cd pipeline/dbt && uv run --project .. dbt build --project-dir . --profiles-dir . --select staging && test "$(ls models/staging/stg_*.sql | wc -l)" = 26`
  - Files: `pipeline/dbt/models/staging/stg_{call_center_interactions,call_transcripts,campaign_sends,complaints,digital_events,satisfaction_surveys,transactions}{,__rejects}.sql`

- [ ] T10: Whole-week date offset function and its test
  - Depends on: T7 (the `pipeline/` uv project and the `data/raw/_manifest.json` shape; see the state file).
  - Read exactly these: spec D11 and §"Test list"; `docs/solution-docs/03-data-architecture.md` §5.
  - Acceptance:
    - `pipeline/load/date_shift.py` provides:
      - `date_offset_days(load_date: date, max_data_date: date) -> int` = `7 * floor((load_date - max_data_date).days / 7)`
      - `max_data_date_from_manifest(manifest) -> date` = the latest `year=/month=/day=` partition date among the manifest entries' S3 key or relative path, whichever `source` they came from (2026-06-17 on this dataset)
      - `resolve_load_date() -> date`: the `LOAD_DATE` env var if set, else today
    - `pipeline/tests/test_date_shift.py::test_offset_is_whole_weeks` checks, for several `load_date`s including `load_date == max_data_date` (→ 0), that the offset `% 7 == 0` and that `max_data_date + offset` lies in `(load_date - 7, load_date]`.
  - Verify: `cd pipeline && uv run pytest tests/test_date_shift.py -q && uv run ruff check load tests && uv run ruff format --check load tests`
  - Files: `pipeline/load/__init__.py`, `pipeline/load/date_shift.py`, `pipeline/tests/test_date_shift.py`

- [ ] T11: dbt serving layer with the date shift, plus PK and enum tests
  - Depends on: T8/T9 (all 13 `stg_*` models and the dbt invocation in the state file), T6 (the exact Postgres column list and order per table).
  - Read exactly these: spec D3, D8, D11; `backend/app/alembic/versions/0001_schemas_and_bank.py`; `docs/solution-docs/03-data-architecture.md` §5.
  - Acceptance:
    - Models: `models/serving/srv_<t>.sql` for all 13 tables.
      - Each selects **exactly** the migration's columns in its order. For `complaints` that excludes `origin`, `created_at` and `conversation_id`, which take their defaults at load.
      - Every DATE and TIMESTAMP column is shifted by `var('date_offset_days')` days, including `date_of_birth`, expirations, exchange-rate `date` and `process_date`. TIME columns are not shifted.
      - TIMESTAMPs come out as TIMESTAMPTZ, interpreted as UTC.
      - A shift macro lives in `macros/`. The var has no default, so a missing var fails.
    - Tests: `models/serving/schema.yml` has `unique` + `not_null` on each single-column PK, and a project generic test in `tests/generic/` for the `daily_exchange_rates` composite key. It also has the five D3 `accepted_values` with the observed values listed in the state file (verbatim, accents included).
  - Verify: `cd pipeline/dbt && uv run --project .. dbt build --project-dir . --profiles-dir . --select 'serving' --vars '{"date_offset_days": 98}'`
  - Files: `pipeline/dbt/macros/shift_date.sql`, `pipeline/dbt/models/serving/srv_*.sql` (13), `pipeline/dbt/models/serving/schema.yml`, `pipeline/dbt/tests/generic/unique_combination.sql`

- [ ] T12: `make data` (dbt build → `latam_golden` → counts → system_metadata) and `make demo-reset`
  - Depends on:
    - T6: the Alembic head and the upgrade command against golden, in the state file conventions.
    - T7: `python -m ingest`.
    - T10: `load.date_shift` functions.
    - T11: `srv_*` tables and the dbt invocation.
    - T5: Makefile.
  - Read exactly these: spec D14 and §"Contracts" → `app.system_metadata` / Databases; `docs/solution-docs/03-data-architecture.md` §7.
  - Acceptance:
    - `pipeline/load/__main__.py` (`uv run python -m load`):
      1. Resolves `load_date` and `max_data_date` from the manifest, then computes the offset.
      2. Runs `dbt build --vars '{"date_offset_days": N}'` (the tests must pass).
      3. Creates `latam_golden` if missing, then runs `alembic upgrade head` against it (cwd `backend/`, `DATABASE_URL=$GOLDEN_DATABASE_URL`).
      4. `pipeline/load/postgres.py`: TRUNCATEs the 13 `bank.*` tables and copies each `srv_<t>` in with an explicit column list (DuckDB `postgres` extension or psycopg COPY).
      5. Inserts one `app.system_metadata` row. `manifest_sha256` is computed over the sorted (`source`, key/path, size, ETag/SHA-256) entries, so a rerun with nothing ingested gives the same hash.
      6. Prints `bank.<t>: <count>` for all 13.
      7. Runs the demo reset.
    - `pipeline/load/demo_reset.py` (`uv run python -m load.demo_reset`): closes and terminates connections to both DBs, drops `latam_app` (`WITH (FORCE)`), and runs `CREATE DATABASE latam_app TEMPLATE latam_golden`.
    - `Makefile`:
      - `data`: `cd pipeline && uv run python -m ingest && uv run python -m load`. `SOURCE` reaches ingest through the environment (`.env`, or `make data SOURCE=local:data` on the command line), with `s3` by default.
      - `demo-reset`
      - `setup` adds `uv sync` in `pipeline/`
      - `test`/`check` add pipeline pytest + ruff
    - Timestamps land as the source UTC instant plus the offset.
    - The proofs run in local mode with no AWS credentials. The S3 end-to-end `make data` for criterion 8 is the verifier's one-time proof, not this task's.
  - Verify (long: run in the background and monitor):
    ```
    set -a && . ./.env && set +a && unset AWS_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY && make up && make data SOURCE=local:data | tee data/make_data_1.txt && test "$(grep -cE '^bank\.[a-z_]+: [1-9]' data/make_data_1.txt)" = 13
    P="docker exec -i latam-cs-postgres-1 psql -U $POSTGRES_USER -Atc"
    $P "select 1 from pg_database where datname='latam_golden'" -d latam_app | grep -q 1
    $P "select max(transaction_date) >= now() - interval '7 days' from bank.transactions" -d latam_app | grep -q t
    $P "select bool_and(date_offset_days % 7 = 0) from app.system_metadata" -d latam_app | grep -q t
    $P "select t.transaction_date - m.date_offset_days * interval '1 day' = timestamptz '2026-06-17 19:51:02+00' from bank.transactions t, (select date_offset_days from app.system_metadata order by loaded_at desc limit 1) m where t.transaction_id='TRX-UIWYPTP5S7PTBYJUSELQ'" -d latam_app | grep -q t
    make data SOURCE=local:data | tee data/make_data_2.txt && grep -q 'ingested=0' data/make_data_2.txt && diff <(grep -E '^bank\.' data/make_data_1.txt) <(grep -E '^bank\.' data/make_data_2.txt)
    $P "update bank.products set product_status='Closed' where product_id='PRD-L6Q5DZNKOUR8'" -d latam_app && make demo-reset && $P "select product_status from bank.products where product_id='PRD-L6Q5DZNKOUR8'" -d latam_app | grep -q Active
    cd pipeline && uv run ruff check load && uv run ruff format --check load
    ```
  - Files: `pipeline/load/__main__.py`, `pipeline/load/postgres.py`, `pipeline/load/demo_reset.py`, `Makefile`

- [ ] T13: Frontend toolchain scaffold (Vite, React 19, TanStack Router/Query, Tailwind v4, Biome)
  - Depends on: nothing in code.
  - Read exactly these: spec §"Touch map" → `frontend/`; `docs/solution-docs/06-engineering-rules.md` §3 (frontend layout) and §4 "Frontend".
  - Acceptance:
    - `frontend/` contains:
      - Vite + React 19 + TypeScript, with TanStack Router (routes under `src/routes/`) and a TanStack Query client provider.
      - Tailwind v4 via `@tailwindcss/vite` with CSS-first `src/index.css`.
      - Biome (`biome.json`) that ignores `src/client/` and any generated route tree.
    - `package-lock.json` is committed. The page renders an empty shell with no product UI.
    - `vite.config.ts`: `server.host: true`, `port 5173`, `hmr.clientPort: 80`, `allowedHosts` covering `localhost`.
    - Scripts: `dev`, `build`, `lint` (`biome ci .`).
    - `.gitignore` adds `node_modules/` and `frontend/dist/`.
  - Verify: `cd frontend && npm ci && npx biome ci . && npm run build`
  - Files: `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/biome.json`, `frontend/index.html`, `frontend/src/{main.tsx,index.css,routes/__root.tsx,routes/index.tsx}`, `frontend/tsconfig*.json`, `.gitignore`

- [ ] T14: Frontend service behind the Nginx dev proxy, and `make client`
  - Depends on:
    - T13: `frontend/` builds.
    - T4: compose files and `docker/nginx/dev.conf` with `/api/` → backend.
    - T2: `/api/v1/openapi.json`.
    - T5: Makefile.
  - Read exactly these: spec D17, D19; `docker/docker-compose.dev.yml`; `docker/nginx/dev.conf`.
  - Acceptance:
    - Compose: a `frontend` service (node:22 image, `frontend/` mounted, `node_modules` in an anonymous volume, `npm ci && npm run dev`). Nginx proxies `/` to `frontend:5173` with websocket upgrade headers (HMR), keeping `/api/` → backend.
    - `make up` serves the empty page at `http://localhost/`.
    - `make client`: `frontend/openapi-ts.config.ts` runs `@hey-api/openapi-ts` (dev dependency) with input `http://localhost/api/v1/openapi.json` and output `src/client/`. The generated files are committed and never hand-edited.
    - `Makefile`: `client` target; `setup` adds `npm ci` in `frontend/`; `check` adds `npx biome ci .` in `frontend/`.
  - Verify: `make up && curl -s localhost/ | grep -qi '<div id="root"' && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/health)" = 200 && rm -rf frontend/src/client && make client && test -n "$(ls frontend/src/client)" && grep -rq health frontend/src/client && (cd frontend && npx biome ci .)`
  - Files: `docker/docker-compose.dev.yml`, `docker/nginx/dev.conf`, `frontend/openapi-ts.config.ts`, `frontend/package.json` (+ lock), `Makefile`, `frontend/src/client/**` (generated)

- [ ] T15: Pre-commit hooks and the GitHub Actions CI workflow (with gitleaks)
  - Depends on: T5 (backend `check` pieces, `.importlinter`), T10/T12 (pipeline tests + ruff), T13/T14 (Biome).
  - Read exactly these: spec D20 and success criterion 3; `Makefile` (`check` target); `docs/solution-docs/06-engineering-rules.md` §4 "Commits" and §5.
  - Acceptance:
    - `.pre-commit-config.yaml`:
      - Ruff lint + format (per-project config is picked up), mypy and `lint-imports` as local hooks running `uv run` in `backend/`, Biome for `frontend/`.
      - gitleaks (upstream hook, or `gitleaks-docker` if golang bootstrap fails; record which).
      - A Conventional Commits `commit-msg` hook.
    - `make setup` adds `pre-commit install --hook-type pre-commit --hook-type commit-msg`.
    - `.github/workflows/ci.yml`: on `pull_request` and `push` to `develop` and `main`, no caching. Jobs:
      - backend: uv sync, ruff check + format check, mypy, lint-imports, pytest
      - pipeline: uv sync, ruff, pytest
      - frontend: npm ci, `biome ci`
      - gitleaks: `fetch-depth: 0`, gitleaks Docker image, `detect` over full history
    - `gitleaks detect` over full history passes locally.
  - Verify:
    ```
    pre-commit install --hook-type pre-commit --hook-type commit-msg && pre-commit run --all-files
    docker run --rm -v "$PWD:/repo" ghcr.io/gitleaks/gitleaks:latest detect --source /repo --redact -v
    docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color
    K="AKIA$(tr -dc 'A-Z2-7' </dev/urandom | head -c 16)"; S="$(tr -dc 'A-Za-z0-9/+' </dev/urandom | head -c 40)"
    printf 'aws_access_key_id = %s\naws_secret_access_key = %s\n' "$K" "$S" > leak_probe.txt && git add leak_probe.txt
    pre-commit run gitleaks; rc=$?; git rm -q --cached leak_probe.txt; rm -f leak_probe.txt; test $rc -ne 0
    ```
  - Files: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `Makefile`

- [ ] T16: Record the D1 time-zone decision in code (`TxView.occurred_at`) and in the docs
  - Depends on: nothing.
  - Read exactly these: spec D1, D2 and §"Contracts" → "K3 change" / "Docs updated by this card"; `backend/app/domains/transactions/schemas.py`.
  - Acceptance:
    - Code: `TxView.occurred_at: AwareDatetime` with the docstring `UTC; display in \`BANK_TZ\` of the customer's country (D1-A D1)`.
    - `07` §8 row "Time zone of `transaction_date`" is marked decided: UTC, `timestamptz`, `BANK_TZ` per country.
    - `decision-log.md` "Deferred to implementation" row "Time zone semantics of `transaction_date`" is marked decided (or moved out of the deferred table), with the same content.
    - `01` §11 open item closed.
    - `03` §5 gets UTC storage + the `BANK_TZ` zones (MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`).
    - `03` §2 step 1 gets one line noting the `SOURCE=local:<path>` local-mirror option (D6).
    - `01` §10 and `03` §3 get the D1.3 finding: `process_date` follows UTC-6 in all three countries (rows stamped 00:00–05:59 carry the previous day).
    - `04` §3 table gets `GET /api/v1/health` (public, `HealthResponse{status, db, redis}`, 200/503). `04` §1 notes `occurred_at` is aware UTC.
    - The K3 R1 test still passes.
  - Verify: `cd backend && uv run python -c "from pydantic import AwareDatetime; from app.domains.transactions.schemas import TxView; assert TxView.model_fields['occurred_at'].annotation is AwareDatetime" && uv run pytest tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/transactions && uv run mypy app && cd .. && grep -q 'America/Argentina/Buenos_Aires' docs/solution-docs/03-data-architecture.md && grep -q 'SOURCE=local:' docs/solution-docs/03-data-architecture.md && grep -q '/health' docs/solution-docs/04-contracts.md && ! grep -q 'Time zone semantics of `transaction_date` (EDA' docs/solution-docs/01-technical-design.md && grep -n 'Time zone of `transaction_date`' docs/solution-docs/07-execution-plan.md | grep -qi 'utc'`
  - Files: `backend/app/domains/transactions/schemas.py`, `docs/solution-docs/07-execution-plan.md`, `docs/solution-docs/decision-log.md`, `docs/solution-docs/01-technical-design.md`, `docs/solution-docs/03-data-architecture.md`, `docs/solution-docs/04-contracts.md`

- [ ] T17: (Observability, cut first) OTLP exporters and asyncpg/Redis instrumentation in the backend
  - Depends on: T3 (`app/core/telemetry.py` TracerProvider, and `app/core/logging.py` rendering through stdlib `logging`), T1 (`Settings.otel_exporter_otlp_endpoint`).
  - Read exactly these: spec D5, D16; `backend/app/core/telemetry.py`; `backend/app/core/logging.py`.
  - Acceptance:
    - When `OTEL_EXPORTER_OTLP_ENDPOINT` is non-empty, the backend exports over OTLP/HTTP:
      - traces (BatchSpanProcessor)
      - metrics (PeriodicExportingMetricReader, so the FastAPI HTTP server metrics are exported)
      - logs: an OTel `LoggingHandler` on the root logger, so the same JSON log records with `request_id`/`trace_id` reach the collector
    - asyncpg and Redis instrumentation are enabled.
    - When the endpoint is unset or empty, no exporter is created and no network call is made. T3's behavior is unchanged.
    - New dependencies: `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-asyncpg`, `opentelemetry-instrumentation-redis`.
  - Verify: `cd backend && uv sync && uv run pytest tests/unit/test_health.py -q && OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318 uv run python -c "from fastapi.testclient import TestClient; from app.main import app; assert TestClient(app).get('/api/v1/health').status_code in (200, 503)" && uv run ruff check app/core app/main.py && uv run ruff format --check app/core app/main.py && uv run mypy app`
  - Files: `backend/app/core/telemetry.py`, `backend/app/core/logging.py`, `backend/app/main.py`, `backend/pyproject.toml`, `backend/uv.lock`

- [ ] T18: (Observability; no longer cuttable, since T20's MCP harnesses need it) Collector, VictoriaMetrics/Logs/Traces, Grafana, and the Victoria MCP servers
  - Depends on: T17 (backend exports when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; service name `card-support-backend`), T4/T5 (compose files, Makefile `COMPOSE`), T3 (`X-Request-ID` response header).
  - Read exactly these: spec D5 and success criterion 12; `docs/solution-docs/01-technical-design.md` §8; `docker/docker-compose.base.yml`.
  - Acceptance:
    - `docker/docker-compose.observability.yml` adds:
      - `otel-collector`: OTLP in on 4317/4318, compose-network only.
      - `victoriametrics` (8428), `victorialogs` (9428), `victoriatraces` (10428), all published.
      - `grafana` (3000), published, with no new `.env` variable (anonymous dev access with a role that can list datasources).
      - Backend `environment: OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318`.
      - Pinned image tags.
    - `docker/otel/collector.yaml` routes traces → VictoriaTraces, logs → VictoriaLogs and metrics → VictoriaMetrics, over their OTLP HTTP ingest paths. Expected: `/insert/opentelemetry/v1/traces`, `/insert/opentelemetry/v1/logs`, `/opentelemetry/v1/metrics`. Confirm them against the pinned versions and record them in the state file.
    - `docker/grafana/provisioning/datasources/` provisions three datasources: Prometheus type → VictoriaMetrics, the VictoriaLogs plugin, and Jaeger type → VictoriaTraces `/select/jaeger`. Plugins are installed via env.
    - `.mcp.json` declares the VictoriaLogs and VictoriaTraces MCP servers (human decision: no VictoriaMetrics MCP), pointing at `localhost:9428` / `localhost:10428`. T20 later adds Playwright to the same file.
    - `Makefile` `COMPOSE` appends `-f docker/docker-compose.observability.yml`.
  - Verify:
    ```
    make up && sleep 5
    RID=$(curl -s -D - -o /dev/null localhost/api/v1/health | awk -F': ' 'tolower($1)=="x-request-id"{print $2}' | tr -d '\r') && sleep 30
    curl -s localhost:9428/select/logsql/query --data-urlencode "query=\"$RID\"" | grep -q "$RID"
    curl -s localhost:10428/select/jaeger/api/services | grep -q card-support-backend
    curl -s localhost:8428/api/v1/label/__name__/values | grep -qi 'http_server'
    test "$(curl -s localhost:3000/api/datasources | uv run --project backend python -c 'import json,sys; print(len(json.load(sys.stdin)))')" = 3
    uv run --project backend python -c "import json; s=json.load(open('.mcp.json'))['mcpServers']; ks=[k.lower() for k in s]; assert any('logs' in k for k in ks) and any('traces' in k for k in ks) and not any('metrics' in k for k in ks), s"
    ```
  - Files: `docker/docker-compose.observability.yml`, `docker/otel/collector.yaml`, `docker/grafana/provisioning/datasources/victoria.yaml`, `.mcp.json`, `Makefile`


- [ ] T20: Claude verification harnesses (Playwright, VictoriaLogs and VictoriaTraces MCPs) wired into /wave-run (added by the human mid-card; runs after T18, before T19)
  - Depends on: T18 (`.mcp.json` with the two Victoria MCP servers; the observability stack up), T14 (app at `http://localhost/`), T3/T17 (`request_id` and `trace_id` in logs and spans).
  - Read exactly these: `.mcp.json`; `.claude/skills/wave-run/SKILL.md` (§"Step 3", §"Step 4 — VERIFY", §"The test budget"); `.claude/agents/card-verifier.md`; `.claude/agents/card-implementer.md`; the state file (T3/T17/T18 entries). Confirm current Claude Code behavior for project `.mcp.json` servers and for MCP tools in subagents (`tools:` frontmatter) against the official docs. Don't rely on memory.
  - Acceptance:
    - `.mcp.json` adds a `playwright` server run from Docker (human decision: no local Chromium): `docker run -i --rm --init --network host mcr.microsoft.com/playwright/mcp:<exact tag>` (headless inside the image; `--network host` so `http://localhost/` reaches Nginx). It keeps the two Victoria servers. `make mcp-setup` (also called from `make setup`) pulls every pinned MCP image. No secrets in `.mcp.json`.
    - `.mcp.json` also adds `deepwiki`, the public DeepWiki MCP (remote HTTP transport, no key), as a docs and repo lookup for implementers and planners. It is not a verification harness (human decision; matches `01` §"MCP servers"). Confirm its current URL and transport in the official DeepWiki docs.
    - `.claude/agents/card-verifier.md`:
      - It can call the three servers' tools. Its `tools:` list names them the way Claude Code requires, or drops the restriction if that's the only way to allow MCP tools. It stays read-only on source.
      - Its §"How to verify" gains a mandatory **runtime harness** step, run with the stack up (`make up`):
        - (a) Playwright: navigate to every page or flow the card touched, take an accessibility snapshot, and assert the expected elements or text. Check that the browser console has no errors and that API calls return 2xx through Nginx.
        - (b) VictoriaLogs: query the verification time window for `level=error` (or equivalent) from `backend`, and follow the `request_id`s of the exercised calls.
        - (c) VictoriaTraces: find the spans for the exercised endpoints (by service and operation, or by `trace_id` from the logs), and confirm the status and expected child spans.
        - Each harness check is a row in the report with evidence (snapshot excerpt, query plus hit count, trace id). A harness that's unavailable (MCP not loaded, stack down) makes its rows `UNVERIFIABLE`, never `PASS`.
        - Cards with no UI still run (b) and (c) against the endpoints they touched.
    - `.claude/skills/wave-run/SKILL.md`:
      - Step 4 says the verifier must use the three MCP harnesses as above, and that the orchestrator makes sure the stack is up and the MCP servers are loaded first. After a `.mcp.json` change, it asks the human to restart or resume Claude Code and approve the project servers.
      - Step 3 says implementers may use the same MCPs for their own `Verify` on UI or observability tasks.
      - The test budget stays unchanged: harness checks are runtime proofs, not new test files.
    - `.claude/agents/card-implementer.md`: one short paragraph allowing optional use of the harnesses (same `tools:` rule as the verifier).
    - No other changes to the skill or the agents.
  - Verify:
    ```
    python3 -c "import json; s=json.load(open('.mcp.json'))['mcpServers']; ks=[k.lower() for k in s]; assert 'playwright' in ks and 'deepwiki' in ks and any('logs' in k for k in ks) and any('traces' in k for k in ks) and not any('metrics' in k for k in ks), s; p=s['playwright']; a=' '.join(p.get('args',[])); assert p['command']=='docker' and 'mcr.microsoft.com/playwright/mcp:' in a and ':latest' not in a and '--network host' in a, a"
    make -n mcp-setup >/dev/null && make mcp-setup
    grep -qiE 'playwright' .claude/agents/card-verifier.md && grep -qiE 'victorialogs|victoria.?logs' .claude/agents/card-verifier.md && grep -qiE 'victoriatraces|victoria.?traces' .claude/agents/card-verifier.md && grep -q 'UNVERIFIABLE' .claude/agents/card-verifier.md
    grep -qiE 'playwright' .claude/skills/wave-run/SKILL.md && grep -qiE 'mcp' .claude/skills/wave-run/SKILL.md
    docker image inspect "$(python3 -c "import json;print([a for a in json.load(open('.mcp.json'))['mcpServers']['playwright']['args'] if a.startswith('mcr.microsoft.com/playwright/mcp:')][0])")" >/dev/null
    ```
    Plus a live smoke test by the orchestrator after the human restarts Claude Code: one Playwright navigation to `http://localhost/`, one VictoriaLogs query and one VictoriaTraces query, all returning results.
  - Files: `.mcp.json`, `Makefile`, `.claude/agents/card-verifier.md`, `.claude/agents/card-implementer.md`, `.claude/skills/wave-run/SKILL.md`

- [ ] T19: Root `README.md` with the steps to reproduce the dev environment (added by the human mid-card)
  - Depends on: T1–T18 and T20 (documents what exists at the end of the card, including `make mcp-setup` and the Claude MCP harnesses in `.mcp.json`).
  - Read exactly these: `Makefile` (every target and its `##` help); `.env.example`; `docker/docker-compose.*.yml` (services and host ports); the state file (conventions, human decisions, T7/T12 timings and memory notes); `CLAUDE.md`; `docs/solution-docs/README.md` (link to it, don't copy it).
  - Acceptance:
    - A new root `README.md` lets a developer with a fresh clone reach a working stack using only `make` commands. It is short and task-ordered, with these sections:
      1. What this is: one paragraph, plus links to `docs/solution-docs/README.md` and `CLAUDE.md`.
      2. Prerequisites: Docker + Compose, `make`, `uv`, Node 22 + npm, `pre-commit`, with the versions the card used. Also: ports that must be free, and roughly 6 GB of disk and about 4 GB of RAM headroom for `make data`.
      3. Configure `.env`:
         - `cp .env.example .env`, then what each group of variables is for.
         - The AWS/S3 values come from the organizers' materials. Never write the bucket name or keys in the README.
         - `.env` is git-ignored and must never be printed, committed or sourced under `set -x`.
      4. `make setup`: toolchains, `uv sync`, `npm ci` and the pre-commit hooks.
      5. `make up`: what starts, and the URLs (app `http://localhost/`, API health `/api/v1/health`, plus Grafana and the rest if T18 landed).
      6. `make data`:
         - The S3 default.
         - `make data SOURCE=local:<path>` for an existing local mirror (no AWS keys needed).
         - What it produces: `latam_golden`, then `latam_app` as a template copy.
         - The weekly date shift.
         - Expected duration and memory (from the T12 log).
         - Reruns skip files that were already ingested.
      7. Daily commands: `make demo-reset`, `make client` (regenerate the API client after backend API changes; never hand-edit `src/client/`), `make check`, `make test`.
      8. Troubleshooting: port already in use, `make up` health wait, DuckDB memory cap, and how to reset everything (`docker compose down -v` via the Makefile if a target exists; otherwise the exact command).
    - Every `make <target>` the README names exists in the `Makefile`. Every relative link resolves.
    - The Development flow section of `CLAUDE.md`, and the "Status"/"Planned commands" lines that say the commands don't exist yet, get a one-line pointer to the README. No other `CLAUDE.md` changes.
  - Verify:
    ```
    for t in $(grep -oE 'make [a-z-]+' README.md | awk '{print $2}' | sort -u); do make -n "$t" >/dev/null 2>&1 || { echo "missing target: $t"; exit 1; }; done
    python3 -c "import re,os,sys; bad=[l for l in re.findall(r'\]\(([^)#]+)', open('README.md').read()) if not l.startswith('http') and not os.path.exists(l)]; sys.exit(print('broken links:',bad) or 1) if bad else None"
    python3 -c "import re,sys; env=dict(l.strip().split('=',1) for l in open('.env') if '=' in l and not l.lstrip().startswith('#')); t=open('README.md').read(); sec=[v.strip().strip(chr(34)) for k,v in env.items() if re.search('KEY|SECRET|PASSWORD|TOKEN|BUCKET',k)]; sys.exit('secret value in README') if any(len(v)>=6 and v in t for v in sec) else print('no secret .env values in README')"
    ```
  - Files: `README.md`, `CLAUDE.md` (pointer lines only)
