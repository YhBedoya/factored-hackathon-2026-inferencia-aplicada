# Plan: REQ-interaction-analytics-pipeline — fact tables, worker, sentiment and mock seeder

Spec: [`docs/specs/interaction-analytics-pipeline.md`](../specs/interaction-analytics-pipeline.md) · Branch: `feat/interaction-analytics-pipeline` (stacked on `feat/learned-intent-fallback` @ `e7c8dc1`) · Owner: Dev A

All paths are relative to the worktree root. Every task runs inside the worktree. No task reads or copies anything from the main checkout.

## Open plan questions (PQ)

Two flow endings are not covered by spec D2, D18 or D19. The tasks that need them (T2, T5) say "apply the answer recorded in the state file; if it is missing, stop and report". Nothing else in the plan depends on them.

| # | Question | Options (recommended first) |
|---|---|---|
| PQ1 | Degraded mode: the queue head is in `degraded_handoff_intents`, so `enqueue`/`next_intent` set `llm_unavailable` and the turn goes `fallback` → `handoff_summary` without any flow node running (`nodes/next_intent.py::_degraded_handoff`). Which segments does that turn write for the intents that never reached a flow? | (a) one `handoff` segment for the head intent only, route `handoff_summary`; (b) one `handoff` segment for every intent still queued (D19 shape); (c) none |
| PQ2 | `card_unlock` on a card the customer blocked permanently answers `block_permanent_no_undo` and offers a replacement (`flows/card_unlock.py`, the `customer_block` branch). Which status does the `card_unlock` segment get? | (a) `abstained` (Cardy cannot serve it); (b) `resolved` (a grounded "nothing to do") |

## Facts checked against the repo

**Branch and environment**
- Alembic head is `0008_llm_calls_temperature_nullable.py`; `0009` is free. `alembic/env.py` takes the URL from `get_settings().database_url` (override with the `DATABASE_URL` env var).
- The worktree has **no `.env`**. `Settings` (`backend/app/core/config.py`) then uses its defaults: `postgresql+asyncpg://postgres:postgres@localhost:5432/latam_app`. Whether those match the running Postgres is **unverified** (see Risks).
- A dev stack is running from the main checkout (`latam-cs-*` containers, Compose project name fixed to `latam-cs` in `docker/docker-compose.base.yml`). Postgres is published on `5432`, Redis on `127.0.0.1:6379`.
- `backend/tests/integration/conftest.py::it_db` creates a throwaway `latam_it_<hex>` database, runs `uv run alembic upgrade head` on it and **skips** when Postgres is unreachable. `it_env` points `DATABASE_URL` at it and skips when Redis is unreachable. A skip is therefore not a pass.
- No new dependency is needed: `pyyaml`, `psycopg`, `sqlalchemy`/`asyncpg` are in `backend/pyproject.toml`; `zoneinfo.ZoneInfo("America/Bogota")` resolves inside the backend image (checked in the running container).
- mypy is strict only for `app.core.*`, `app.domains.conversation.*`, `app.domains.policy.*`. `backend/.importlinter` has no contract naming `analytics`; the layer contract (api → domains → core) covers it.

**Capture side (`backend/app/domains/conversation/`)**
- `GraphState.segments` (`graph.py`) already holds the turn's reply texts, with its reducer and `RESET_SEGMENTS` in `state.py`. Reducers must live in `state.py` because `graph.py` also runs as `__main__`. `nodes/load_session.py` writes `RESET_FACTS` and `RESET_SEGMENTS` every turn.
- The eight flow nodes are registered in `build_graph` as `graph.add_node("<name>", _guard_access(<flow>))`. `_guard_access` turns an `AccessDenied` into the `injection_suspected` refusal, or into `escalation_reason = "unauthorized_access"` at the policy threshold.
- Edges: `_after_flow` sends `tool_failure`, `llm_unavailable` and `no_cards` to `fallback`, any `HandoffReason` (or a set `handoff_queue`) to `handoff_summary`, non-empty `facts` to `compose`. `_after_compose` sends a compose `LLMError` to `fallback` → `handoff_summary`. `_after_segment` ends the turn at `finish` when `pending` is set, **leaving the queue as it is**, so on a normal resume the queue head is still the paused flow's intent.
- `_entry` routes a pick, a button confirmation, a step-up resume and an address reply straight to `_FLOW_NODES[pending["flow"]]`, with no NLU.
- `card_status` and `balance_due` both map to node `card_info` (`intents.yaml`), so a flow name does not always give one intent.
- Bot-made offers exist in **two** places, both setting `pending = {flow: "replacement", node: "offer", awaiting_slot: "offer_replacement"}`: `flows/card_block.py` (after a permanent block) and `flows/card_unlock.py` (`customer_block` branch). At that moment the queue head is still `card_block` or `card_unlock`.
- `flows/actions.py`: `cancel` answers `action_cancelled`; `execute` returns `actions: [result]` only when the result is verified, and hands off with `action_unverified` otherwise.
- `flows/card_info.py`: `balance_due` on a debit card writes the `credit_only` template **and** facts, then goes through `compose`. It is a read answered with facts.
- `runner.py::_run_turn` streams the graph with `stream_mode="updates"`, so it sees every node's update. It writes `reply_sent` with `{route, ui_kinds, length, degraded, fact_values, grounding?}`. A relayed turn returns before that.
- `store.close_conversation` sets only `status = 'closed'`. `app.conversations.closed_at` exists since migration `0002`.
- `tests/unit/test_degraded.py::test_runner_marks_degraded_in_debug_and_audit` is the only unit test that drives the real runner and reads `reply_sent`. `tests/conftest.py` has `make_session`, `ScriptedLLM`, `RecordingAudit`.

**LLM access (`backend/app/core/llm/`)**
- `Step` is a `Literal` in `registry.py`, next to `MODEL_REGISTRY` and `TEMPERATURE`. Haiku 4.5 ids: `claude-haiku-4-5-20251001` (anthropic), `us.anthropic.claude-haiku-4-5-20251001-v1:0` (bedrock). Both are priced in `pricing.py`.
- `LLMClient.structured(step, prompt, system, user, schema)` returns only the parsed object. Cost is on the `LLMCallRecord` handed to the `LLMCallSink`. The client reads `conversation_id` from `structlog.contextvars`.
- `StructuredLLMClient(settings, chat_model_factory, sink, sleep)` is the test seam (`tests/unit/test_llm_client.py`). It refuses unmasked input (`find_pii`) and retries up to `get_settings().retry_max` (2) times.
- `AuditLLMCallSink` (`audit/service.py`) writes through `get_engine()`, that is, through the app's own database role. The worker cannot reuse it (D8).

**Data the worker reads**
- `app.messages`: `id, conversation_id, turn_id, role, content, content_masked, ui_payload, created_at`. `app.handoffs`: `id, conversation_id, queue, reason, priority, packet, status (queued/claimed/returned), agent_id, created_at, claimed_at, returned_at`. `audit.llm_calls`: `conversation_id, step, cost_usd, …` (`temperature` nullable since `0008`).
- Country labels: `app.domains.customers.service.COUNTRY_LABELS` (label → `MX`/`CO`/`AR`), the same map `audit/timeline.py::_country_code` uses.

**Runtime**
- `Makefile`: `COMPOSE` = base + dev + observability + devtools; `COMPOSE_PROD` = base + observability + prod. `fill-secrets` fills the names in its `keys` list with `secrets.token_urlsafe(32)` (URL-safe, so it can sit inside a database URL). `make up` is `$(COMPOSE) up -d --build --wait`.
- `docker/docker-compose.base.yml`: the `backend` service has `env_file: ../.env` and overrides `DATABASE_URL` with the Compose-built `postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/latam_app`. The worker follows the same pattern.
- `infra/aws/render-env.sh` copies every `/swip/prod/*` SSM parameter into `.env`. A new `ANALYTICS_DB_PASSWORD` parameter needs no script change. `infra/aws/deploy.sh` runs `alembic upgrade head` on both databases from the host, so the migration sees the password.
- `pipeline/load/demo_reset.py` terminates every connection to `latam_app` and recreates it from `latam_golden`. Grants live in the database, so they survive the clone.
- The README has **no provenance table** today. The canonical one is `03` §1.

**Planned names** (plan-level; an implementer who must deviate records it in the state file)

| Thing | Name |
|---|---|
| Worker role | `analytics_worker` |
| Settings (`config.py`) | `analytics_database_url: str = ""`, `analytics_db_password: str = ""`, `analytics_idle_minutes: int = 30`, `analytics_worker_interval_s: int = 120`, `analytics_timezone: str = "America/Bogota"`, `analytics_mock_enabled: bool = False`, `analytics_mock_backfill_days: int = 30` |
| `analytics.worker_state` | `id smallint` primary key, check `id = 1`; `watermark timestamptz` null; `mock_seeded_through date` null. The migration inserts the single row |
| Graph channel (D14) | `GraphState.intent_segments`; in `state.py`: `IntentSegment`, `RESET_INTENT_SEGMENTS`, `_reduce_intent_segments`, `mark_segment(status, *, awaiting_slot=None) -> dict[str, Any]` returning `{"segment_mark": {...}}` |
| Slot name for `tx_search_ask_criterion` | `criterion` |
| Pure rules | `app.domains.analytics.service.build_occurrences(turn_segments)` → list of `Occurrence(seq, intent, outcome, needed_clarification, turns, bot_offered)`; `service.METRICS_VERSION = 1` |
| Sentiment | `app.domains.analytics.sentiment`: `SentimentScorer` (Protocol), `SentimentResult`, `HaikuSentimentScorer`; prompt `PromptRef("sentiment", "v1")` |
| Mock | `app.domains.analytics.mock.generate_day(day, profile)`; ids `uuid5(<fixed namespace>, f"{day.isoformat()}:{index}")` |
| Worker | `app.domains.analytics.worker`: `AnalyticsStore` (Protocol), `run_pass(store, scorer, *, now, settings)`, CLI `python -m app.domains.analytics.worker [--once] [--recompute] [--rescore-sentiment]` |
| Store | `app.domains.analytics.repository.PostgresAnalyticsStore(engine)`, `build_engine(url)` (`pool_size=3, max_overflow=0`) |
| Tests | `backend/tests/unit/test_analytics_segments.py`, `backend/tests/unit/test_analytics_sentiment.py`, `backend/tests/integration/test_analytics_worker.py` |

## Components

1. **Migration `0009`** (`backend/app/alembic/versions/0009_analytics.py`, new). Schema `analytics`, three tables, index on `app.messages(created_at)`, role and grants. Depends on settings for the password.
2. **Settings and secret** (`backend/app/core/config.py`, `.env.example`, `.env.prod.example`, `Makefile::fill-secrets`).
3. **Segment capture** (`conversation/state.py`, `graph.py`, `nodes/load_session.py`, the flow files). One wrapper in `graph.py` builds each segment from the node's update; flows add an explicit mark only where the update cannot tell (D18). No LLM is involved.
4. **Runner and store** (`conversation/runner.py`, `store.py`). `segments` on `reply_sent`; `closed_at`.
5. **Analytics domain** (`backend/app/domains/analytics/`, new): `cause_groups.py`, `service.py` (pure rules), `sentiment.py` + `prompts/sentiment@v1.md`, `mock.py` + `mock_profile.yaml`, `repository.py` (all SQL, on the worker's own engine), `worker.py` (the pass, the loop, the CLI). Imports `app.core.*` and `app.domains.customers.service` only; no `conversation` module.
6. **`sentiment` step** (`backend/app/core/llm/registry.py`).
7. **Runtime** (`docker/docker-compose.{base,dev,prod}.yml`, `Makefile`): the `analytics-worker` service and `make analytics`.
8. **Docs** (`03` §6, `04` §6, `06` §3, `08`, `README.md`).

## Build order

1. Migration, settings and the empty package (T1) first: every analytics module imports the settings, and D1 puts the migration ahead of everything.
2. The capture core (T2) runs beside T1. It shares no file with it, and the flow marks (T5, T6) and the runner (T4) need its helper and channel.
3. The three leaf modules of the analytics domain (sentiment T7, pure rules T8, mock generator T9) need only T1 and build together. The mock generator is in this first group so card 2 can start early (D1).
4. `worker.py` (T10) composes the three leaves against a store protocol, with an in-memory fake, so the two sentiment tests need no database.
5. `repository.py` (T11) implements the protocol on Postgres and proves it with the finish-rule and mock-seed tests. It needs T10's protocol and T4's `closed_at`.
6. The two end-to-end tests (T13) need the whole chain: capture, runner, worker, repository.
7. The live-stack proof (T14) is last and alone: it rebuilds the shared stack and upgrades the dev databases.

## Touch map

| File | New / modified | What changes |
|---|---|---|
| `backend/app/alembic/versions/0009_analytics.py` | new | schema, 3 tables, index, role, grants |
| `backend/app/core/config.py` | modified | seven `analytics_*` settings |
| `.env.example` | modified | the five REQ-R6.4 settings (mock on), empty `ANALYTICS_DB_PASSWORD` |
| `backend/app/domains/analytics/__init__.py` | new | package |
| `backend/app/domains/conversation/state.py` | modified | `IntentSegment`, reducer, reset marker, `mark_segment` |
| `backend/app/domains/conversation/graph.py` | modified | `intent_segments` channel, segment wrapper on branch nodes |
| `backend/app/domains/conversation/nodes/load_session.py` | modified | per-turn reset of the new channel |
| `backend/app/domains/conversation/flows/actions.py` | modified | `cancelled` mark in `cancel` |
| `backend/app/domains/conversation/flows/{card_block,card_unlock,replacement}.py` | modified | D18 marks |
| `backend/app/domains/conversation/flows/{decline_explain,tx_search,tx_explain,unrecognized_charge}.py` | modified | D18 marks |
| `backend/app/domains/conversation/runner.py` | modified | `segments` on `reply_sent` |
| `backend/app/domains/conversation/store.py` | modified | `closed_at` |
| `backend/app/core/llm/registry.py` | modified | `sentiment` step |
| `backend/app/domains/analytics/{sentiment.py,prompts/sentiment@v1.md}` | new | scorer and prompt |
| `backend/app/domains/analytics/{cause_groups.py,service.py}` | new | pure rules |
| `backend/app/domains/analytics/{mock.py,mock_profile.yaml}` | new | mock generator and profile |
| `backend/app/domains/analytics/worker.py` | new | pass, loop, CLI |
| `backend/app/domains/analytics/repository.py` | new | SQL store |
| `docker/docker-compose.{base,dev,prod}.yml` | modified | `analytics-worker` service |
| `Makefile` | modified | `analytics` target, `fill-secrets` key |
| `.env.prod.example` | modified | `ANALYTICS_DB_PASSWORD=`, mock on |
| `backend/tests/unit/test_analytics_segments.py` | new | 2 tests |
| `backend/tests/unit/test_analytics_sentiment.py` | new | 2 tests |
| `backend/tests/integration/test_analytics_worker.py` | new | 4 tests |
| `backend/tests/unit/test_degraded.py` | modified | one assertion on `segments` |
| `docs/solution-docs/{03-data-architecture,04-contracts,06-engineering-rules,08-deployment}.md`, `README.md` | modified | as the spec lists |

Not touched, although the spec's touch map lists them: `infra/aws/render-env.sh` (it already copies every SSM parameter) and `nodes/next_intent.py`, `nodes/handoff*.py`, `abstain.py`, `unsupported.py`, `fallback.py` (the wrapper in `graph.py` covers those nodes).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Unverified:** integration tests and the T1 proof assume the `Settings` defaults match the running Postgres credentials (the worktree has no `.env`) | T1, T11 and T13 must **report** a connection failure or a skipped test and stop. They never read a `.env` outside the worktree and never edit credentials |
| The role is cluster-wide; the migration runs once per database and on every throwaway test database | T1: role creation is idempotent (`IF NOT EXISTS` in a `DO` block); `downgrade` revokes this database's grants and never drops the role |
| A password literal in the migration or in a log line | T1: the password comes from `get_settings().analytics_db_password`; the `ALTER ROLE` text is built in the database with `format('%L', …)` from a bound parameter; nothing is printed |
| The worker running as the superuser by accident | T10: an empty `ANALYTICS_DATABASE_URL` is a start-up error, never a fallback to `DATABASE_URL`. T12: the service also overrides `DATABASE_URL` with the worker role's URL |
| `make up --wait` fails when the worker starts before migration `0009` is applied | T10: a failed pass is logged and the loop continues; the process does not exit. T14 applies the migration right after `make up` |
| `make demo-reset` kills the worker's connections | T10: same rule; `pool_pre_ping` in T11's engine |
| A read flow marked `resolved` although `compose` failed and the turn handed off | T2: the `resolved` of a facts-only flow is decided after `compose` |
| The segment wrapper changes the graph's shape and breaks the diagram test | T2 runs `tests/unit/test_graph.py` |
| A flow ending the plan did not foresee | T2, T5, T6: an unmarked ending writes no segment and logs `segment.unmarked`; the implementer reports it in the state file instead of choosing a status |
| An LLM call with raw text | T7 reads only `content_masked`; T10's `test_sentiment_masked_only`; the client's own `find_pii` guard stays in front |
| The ES end-to-end test never gets a row because its handoff stays open | T13 sets the handoff to `returned` in SQL before the pass |
| The PT end-to-end test turns `abandoned` through the replacement offer (D22's accepted cost) | T13 uses the **temporary lock**, which makes no offer |
| `count(DISTINCT ended_at::date)` is computed in UTC while days are cut in `America/Bogota` | T11 and T14 compare days in `ANALYTICS_TIMEZONE`, or accept "at least the backfill window" |
| The live proof replaces the containers the human's main checkout was running | T14 is alone, says so first, and ends by telling the human to run `make up` from the main checkout |

## Tests

| Spec test | Task | File |
|---|---|---|
| `test_segments_multi_intent` | T2 | `backend/tests/unit/test_analytics_segments.py` |
| `test_segments_write_flow` | T2 | same |
| `test_sentiment_masked_only` | T10 | `backend/tests/unit/test_analytics_sentiment.py` |
| `test_sentiment_unavailable` | T10 | same |
| `test_finish_rules` | T11 | `backend/tests/integration/test_analytics_worker.py` |
| `test_mock_seed_deterministic` | T11 | same |
| `test_worker_es_multi_intent` | T13 | same |
| `test_worker_pt_write_happy_path` | T13 | same |

Success criteria 8 and 9 (DW8, D8) are commands in T14. Criterion 10 is T3. No other test is added; T4 adds one assertion to an existing test.

## Tasks

- [ ] T1: Migration `0009` (schema, tables, index, role, grants), the `analytics_*` settings and the empty `analytics` package
  - Depends on: nothing
  - Read exactly these: spec §Contracts "Schema `analytics`" and D7, D8; `docs/requirements/interaction-analytics-pipeline.md` §R2 (the column list); `backend/app/alembic/versions/0007_privacy_ledger.py` (the style to mirror) and `backend/app/core/config.py`
  - Acceptance:
    - `config.py` has the seven settings under "Planned names" in the state file, with those defaults.
    - `.env.example` has a commented "Analytics" section with `ANALYTICS_IDLE_MINUTES=30`, `ANALYTICS_WORKER_INTERVAL_S=120`, `ANALYTICS_TIMEZONE=America/Bogota`, `ANALYTICS_MOCK_ENABLED=true`, `ANALYTICS_MOCK_BACKFILL_DAYS=30`, and an empty `ANALYTICS_DB_PASSWORD=` next to the other generated secrets. It has no `ANALYTICS_DATABASE_URL` (Compose builds it).
    - `backend/app/domains/analytics/__init__.py` exists with a one-paragraph docstring (D12: own SQL, no `conversation` import).
    - `0009_analytics.py` (`down_revision` = the `0008` revision id) creates:
      - schema `analytics`;
      - `analytics.interactions` with every REQ-R2 column, primary key `conversation_id` (uuid, **no foreign key**), an index on `ended_at`, and the three checks in spec §Contracts. Money columns are `Numeric(12, 6)`, times are `timestamptz`, `country` and `language` are text, `resolved` and every sentiment column are nullable;
      - `analytics.interaction_intents` with `conversation_id, seq, intent, outcome, needed_clarification, turns, bot_offered` (boolean, not null, server default false), primary key `(conversation_id, seq)`, the outcome check;
      - `analytics.worker_state` as in "Planned names", with its single row inserted;
      - index `ix_messages_created_at` on `app.messages(created_at)`;
      - role `analytics_worker`: created only when missing, `LOGIN`, in a `DO` block. When `get_settings().analytics_db_password` is non-empty, `ALTER ROLE analytics_worker PASSWORD` is run with the literal quoted by the database (`SELECT format('ALTER ROLE analytics_worker PASSWORD %L', :pw)`, then execute the result). When it is empty, no password statement runs. The password never appears in the file or in output;
      - grants: `USAGE` on schemas `app`, `audit`, `bank`, `analytics`; `SELECT` on all tables of `app`, `audit`, `bank`; `SELECT, INSERT, UPDATE, DELETE` on all tables of `analytics`; `INSERT` on `audit.llm_calls`. Nothing else.
    - `downgrade` drops the index, the three tables and the schema and revokes this database's grants. It does not drop the role.
    - If the first command of Verify cannot connect to Postgres: **stop and report it in the state file**. Do not read any `.env` outside the worktree, do not create one, do not change credentials.
  - Verify: run as one shell command from the worktree root (it creates and drops the throwaway database `latam_it_mig0009`):

        cd backend && export MIG_URL="$(uv run python -c "from app.core.config import get_settings as g; print(g().database_url.rsplit('/',1)[0] + '/latam_it_mig0009')")" \
        && uv run python -c "import os,psycopg; u=os.environ['MIG_URL'].replace('+asyncpg','').rsplit('/',1)[0]+'/postgres'; c=psycopg.connect(u,autocommit=True); c.execute('DROP DATABASE IF EXISTS latam_it_mig0009 WITH (FORCE)'); c.execute('CREATE DATABASE latam_it_mig0009')" \
        && DATABASE_URL="$MIG_URL" uv run alembic upgrade head \
        && DATABASE_URL="$MIG_URL" uv run alembic downgrade -1 \
        && DATABASE_URL="$MIG_URL" uv run alembic upgrade head \
        && uv run python - <<'PY'
        import os, psycopg
        url = os.environ["MIG_URL"].replace("+asyncpg", "")
        def allowed(sql: str) -> bool:
            with psycopg.connect(url) as conn:
                conn.execute("SET ROLE analytics_worker")
                try:
                    conn.execute(sql)
                    ok = True
                except psycopg.errors.InsufficientPrivilege:
                    ok = False
                conn.rollback()
                return ok
        assert not allowed("INSERT INTO app.messages (id) VALUES (gen_random_uuid())")
        assert not allowed("INSERT INTO audit.audit_events (id) VALUES (gen_random_uuid())")
        assert allowed("INSERT INTO analytics.worker_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        assert allowed("INSERT INTO audit.llm_calls (id, at, step, provider, model_id, prompt_version, attempt, status, latency_ms) VALUES (gen_random_uuid(), now(), 'sentiment', 'anthropic', 'proof', 'sentiment@v1', 1, 'ok', 0)")
        assert allowed("SELECT 1 FROM bank.customers LIMIT 1")
        admin = url.rsplit("/", 1)[0] + "/postgres"
        psycopg.connect(admin, autocommit=True).execute("DROP DATABASE latam_it_mig0009 WITH (FORCE)")
        print("0009 role proofs ok")
        PY

    then `cd backend && uv run ruff check app/alembic/versions/0009_analytics.py app/core/config.py app/domains/analytics/__init__.py && uv run ruff format --check app/alembic/versions/0009_analytics.py app/core/config.py app/domains/analytics/__init__.py && uv run mypy app/core/config.py`
  - Files: `backend/app/alembic/versions/0009_analytics.py`, `backend/app/core/config.py`, `.env.example`, `backend/app/domains/analytics/__init__.py`

- [ ] T2: Per-intent segment channel and the segment wrapper in the graph, with `test_segments_multi_intent` and `test_segments_write_flow`
  - Depends on: nothing
  - Read exactly these: spec D2, D4, D14, D17, D18, D19, D22 and §Contracts "`reply_sent` payload"; `backend/app/domains/conversation/graph.py` (`GraphState`, `_BRANCH_NODES`, `_entry`, `_dispatch`, `_after_flow`, `_after_compose`, `_guard_access`, `build_graph`) and `state.py` (`RESET_SEGMENTS`, `_reduce_segments`); `backend/tests/unit/test_r3_flows.py` (how a test drives a write flow with `make_session`, a confirmation and an unverified `raw_writes` stub)
  - Acceptance:
    - `state.py` defines `IntentSegment` (`intent`, `route`, `status`, optional `awaiting_slot`, optional `bot_offered`), `RESET_INTENT_SEGMENTS`, `_reduce_intent_segments` (append, or reset on the marker) and `mark_segment(status, *, awaiting_slot=None)`, which returns `{"segment_mark": {...}}` for a node to merge into its update.
    - `GraphState.intent_segments` is a graph-local channel (not in `TurnState`, not checkpointed). `load_session` resets it every turn. `GraphState.segments` (reply texts) is unchanged.
    - One wrapper in `graph.py`, applied where `build_graph` registers the eight flow nodes and `unsupported`, `abstain`, `compose` and `handoff_summary`, appends the segments. It removes `segment_mark` from the node's update before returning it. No LLM node writes a segment (R6 stays intact: the wrapper only reads the update).
    - Segment `intent`: the queue head on a fresh turn. On a turn that entered a flow through `pending`: the queue head when its node equals that flow, else the registry intent for the flow. `route` is the node's name.
    - Segment `status` for a flow node, first match wins: (1) an explicit `segment_mark`; (2) `escalation_reason = "no_cards"` → `abstained`; (3) any other `escalation_reason` or a set `handoff_queue` → `handoff`; (4) the `AccessDenied` refusal of `_guard_access` → `abstained`; (5) `pending` after the update belongs to this flow → `awaiting`, with `awaiting_slot` copied from `pending.awaiting_slot`; (6) a verified `ActionResult` in the update → `resolved`; (7) non-empty `facts` → `resolved`, but decided after `compose`: when `compose` sets an `escalation_reason` the segment is `handoff` instead; (8) nothing matched → no segment and a `segment.unmarked` warning log with the node name only.
    - `unsupported` → `abstained` for the queue head. `abstain` → one `abstained` segment per non-management intent in the turn's NLU result. A turn with no real intent writes nothing (D4).
    - `handoff_summary` reached with no segment written this turn (D19): one `handoff` segment per non-management intent in the turn's NLU result, in order, route `handoff_summary`. No intent, no segment.
    - The degraded queue-head handoff (`_degraded_handoff` in `nodes/next_intent.py`): apply the answer to **PQ1** in the state file. If it is not there, stop and report.
    - `bot_offered: true` (D22) is on every segment of a flow that was entered through a pause another flow created as an offer (today `pending.flow = "replacement"`, `node = "offer"`, set by `card_block` and `card_unlock`), on the offer turn and on every later turn of that flow. It is derived in the wrapper; if that needs a checkpointed field, add a plain `str | None` field to `TurnState` and record it in the state file. The key is absent otherwise.
    - `flows/actions.py::cancel` adds `mark_segment("cancelled")`.
    - `test_analytics_segments.py` has exactly two tests, fake LLM (`ScriptedLLM`), `make_session`, segments read from the graph's updates:
      - `test_segments_multi_intent`: one turn with a read intent that resolves and an intent that hands off writes two segments with statuses `resolved` and `handoff`, in order.
      - `test_segments_write_flow`: `card_block` is `awaiting` with `awaiting_slot = "confirmation"` on the ask turn; the confirmation turn's segment has `intent = "card_block"` (not `affirm`) and is `resolved` with a verified read-back; a cancel gives `cancelled`; an unverified result is never `resolved`.
    - Any flow ending found that fits none of D2, D18, D19: report it in the state file, do not choose a status.
  - Verify: `cd backend && uv run pytest tests/unit/test_analytics_segments.py tests/unit/test_graph.py tests/unit/test_r3_flows.py tests/unit/test_checkpoint_serde.py -q && uv run ruff check app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py app/domains/conversation/flows/actions.py tests/unit/test_analytics_segments.py && uv run ruff format --check app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py app/domains/conversation/flows/actions.py tests/unit/test_analytics_segments.py && uv run mypy app/domains/conversation/state.py app/domains/conversation/graph.py`
  - Files: `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/load_session.py`, `backend/app/domains/conversation/flows/actions.py`, `backend/tests/unit/test_analytics_segments.py`

- [ ] T3: Docs: `segments` in `04` §6, the `analytics` schema in `03` §6, the domain in `06` §3, the secret and service in `08`, the worker and mock provenance in the README
  - Depends on: nothing
  - Read exactly these: spec §Contracts and D2, D8, D17, D18, D19, D22; `docs/solution-docs/04-contracts.md` §6 and `docs/solution-docs/03-data-architecture.md` §6; `README.md` §2–§6
  - Acceptance:
    - `04` §6 documents the `segments` key of `reply_sent`: the entry shape, the five statuses, `awaiting_slot`, `bot_offered`, `[]` when there is no real intent, none on a relayed turn.
    - `03` §6 gains a `### analytics` part: the three tables with their columns, the outcome values, "no message text, no customer identifier", `source = real | mock`, the index on `app.messages(created_at)`, and the `analytics_worker` role with its exact grants. It says `make demo-reset` wipes the schema.
    - `06` §3 lists `analytics` among the backend domains.
    - `08` §9 adds `ANALYTICS_DB_PASSWORD` to the secrets table (SSM SecureString at `/swip/prod/ANALYTICS_DB_PASSWORD`, read by migration `0009`), and `08` §7 names the `analytics-worker` service with its 512 MiB limit.
    - `README.md`: `make analytics` in the daily commands; a short paragraph on the worker and its settings; a provenance line that labels the mock analytics rows as **team-generated synthetic** (`source = 'mock'`) and points to `03` §1. The README has no provenance table today, so this task adds the line as a small table.
    - Plain statements of what the spec decided; no reasoning copied from the spec.
  - Verify: `grep -q "bot_offered" docs/solution-docs/04-contracts.md && grep -q "awaiting_slot" docs/solution-docs/04-contracts.md && grep -q "analytics.interaction_intents" docs/solution-docs/03-data-architecture.md && grep -q "analytics_worker" docs/solution-docs/03-data-architecture.md && grep -q "analytics" docs/solution-docs/06-engineering-rules.md && grep -q "ANALYTICS_DB_PASSWORD" docs/solution-docs/08-deployment.md && grep -q "make analytics" README.md && grep -qi "team-generated synthetic" README.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/03-data-architecture.md`, `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/08-deployment.md`, `README.md`

- [ ] T4: Runner writes `segments` on `reply_sent`; `close_conversation` writes `closed_at`
  - Depends on: T2 (the `intent_segments` channel that the graph's node updates carry; its real name is in the state file)
  - Read exactly these: `backend/app/domains/conversation/runner.py` (`_run_turn`: the `astream` loop and the `reply_sent` record); `backend/app/domains/conversation/store.py` (`close_conversation`); `backend/tests/unit/test_degraded.py` lines 215–285
  - Acceptance:
    - The runner collects the turn's intent segments from the stream of node updates and writes them as `"segments": [...]` on every `reply_sent`, `[]` when there are none. Each entry has `intent`, `route`, `status`, plus `awaiting_slot` and `bot_offered` only when present.
    - The relayed-turn path is unchanged: it still writes no `reply_sent` (D20).
    - No other key of `reply_sent` changes.
    - `store.close_conversation` sets `status = 'closed'` and `closed_at = now()` in the same statement.
    - `test_runner_marks_degraded_in_debug_and_audit` gains one assertion: `reply_sent[0]["segments"]` is a non-empty list whose first entry has `intent`, `route` and `status`. No new test.
  - Verify: `cd backend && uv run pytest tests/unit/test_degraded.py -q && uv run ruff check app/domains/conversation/runner.py app/domains/conversation/store.py tests/unit/test_degraded.py && uv run ruff format --check app/domains/conversation/runner.py app/domains/conversation/store.py tests/unit/test_degraded.py && uv run mypy app/domains/conversation/runner.py app/domains/conversation/store.py`
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/domains/conversation/store.py`, `backend/tests/unit/test_degraded.py`

- [ ] T5: D18 segment marks in the card flows (`card_block`, `card_unlock`, `replacement`)
  - Depends on: T2 (`mark_segment` in `conversation/state.py` and the wrapper's default rules; real names in the state file)
  - Read exactly these: spec D18 and D22; `backend/app/domains/conversation/flows/card_block.py`, `card_unlock.py`, `replacement.py`
  - Acceptance:
    - Each return listed here merges `mark_segment(...)` into its update; nothing else in the flows changes:
      - `already_in_state` (`card_block`) → `resolved`; `not_blocked` (`card_unlock`) → `resolved`;
      - `replacement_not_eligible` → `abstained`;
      - `replacement_declined` → `cancelled`;
      - every return that answers `nothing_pending` **and** clears the pause (`"pending": None`) → `cancelled`. A `nothing_pending` return that leaves `pending` as it is gets no mark.
    - `card_unlock`'s `customer_block` branch (`block_permanent_no_undo` plus the replacement offer): apply the answer to **PQ2** in the state file. If it is not there, stop and report.
    - Returns already covered by the wrapper's defaults (a pause of this flow, a handoff, a verified action, facts) get no mark. A verified permanent block that sets the replacement offer needs no mark: the wrapper gives `resolved`.
    - Any ending that fits none of D2, D18: report it in the state file, do not choose a status.
  - Verify: `cd backend && uv run pytest tests/unit/test_block_flows.py tests/unit/test_r3_flows.py tests/unit/test_card_block_memory.py tests/unit/test_analytics_segments.py -q && uv run ruff check app/domains/conversation/flows/card_block.py app/domains/conversation/flows/card_unlock.py app/domains/conversation/flows/replacement.py && uv run ruff format --check app/domains/conversation/flows/card_block.py app/domains/conversation/flows/card_unlock.py app/domains/conversation/flows/replacement.py && uv run mypy app/domains/conversation/flows/card_block.py app/domains/conversation/flows/card_unlock.py app/domains/conversation/flows/replacement.py`
  - Files: `backend/app/domains/conversation/flows/card_block.py`, `backend/app/domains/conversation/flows/card_unlock.py`, `backend/app/domains/conversation/flows/replacement.py`

- [ ] T6: D18 segment marks in the transaction, decline and dispute flows
  - Depends on: T2 (`mark_segment` in `conversation/state.py` and the wrapper's default rules; real names in the state file)
  - Read exactly these: spec D18; `backend/app/domains/conversation/flows/tx_search.py`, `tx_explain.py`, `decline_explain.py`; in `unrecognized_charge.py` only the returns that write a `segments` template
  - Acceptance:
    - Each return listed here merges `mark_segment(...)` into its update; nothing else changes:
      - `decline_none`, `decline_unknown`, `tx_search_none`, `tx_explain_none`, `dispute_no_transactions` → `resolved`;
      - `tx_search_ask_criterion` (returned with `"pending": None`) → `awaiting` with `awaiting_slot="criterion"`;
      - every return that answers `nothing_pending` **and** clears the pause → `cancelled`. `pending_reminder` returns and `nothing_pending` returns that keep the pause get no mark.
    - Returns already covered by the wrapper's defaults get no mark.
    - Any ending that fits none of D2, D18: report it in the state file, do not choose a status.
  - Verify: `cd backend && uv run pytest tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py tests/unit/test_decline_explain_flow.py tests/unit/test_dispute_flows.py -q && uv run ruff check app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/tx_explain.py app/domains/conversation/flows/decline_explain.py app/domains/conversation/flows/unrecognized_charge.py && uv run ruff format --check app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/tx_explain.py app/domains/conversation/flows/decline_explain.py app/domains/conversation/flows/unrecognized_charge.py && uv run mypy app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/tx_explain.py app/domains/conversation/flows/decline_explain.py app/domains/conversation/flows/unrecognized_charge.py`
  - Files: `backend/app/domains/conversation/flows/tx_search.py`, `backend/app/domains/conversation/flows/tx_explain.py`, `backend/app/domains/conversation/flows/decline_explain.py`, `backend/app/domains/conversation/flows/unrecognized_charge.py`

- [ ] T7: `sentiment` LLM step, the `SentimentScorer` interface, the Haiku scorer and its prompt
  - Depends on: T1 (the package `backend/app/domains/analytics/`)
  - Read exactly these: spec D13 and §Contracts "`SentimentScorer` interface"; `backend/app/core/llm/registry.py` and `backend/app/core/llm/sink.py`; `backend/app/domains/conversation/nodes/handoff_summary.py` (a Haiku step called through `LLMClient.structured` with a versioned prompt file and the `llm_disabled` check)
  - Acceptance:
    - `registry.py`: `"sentiment"` is a member of `Step`; `MODEL_REGISTRY["sentiment"]` has the same two Haiku 4.5 ids as `compose`; `TEMPERATURE["sentiment"] = 0.0`.
    - `prompts/sentiment@v1.md` asks for three labels (overall, start, end), each one of `negative`, `neutral`, `positive`. It holds no policy, no cause group and no mock value.
    - `sentiment.py` defines `SentimentScorer` (a Protocol with one async method that takes the conversation id, the ordered masked customer messages and the language) and `SentimentResult` (`overall`, `start`, `end`, `model`, `prompt_version`, `cost_usd`). The method returns `SentimentResult` or `None` for "unavailable".
    - `HaikuSentimentScorer` calls only `LLMClient.structured(step="sentiment", prompt=PromptRef("sentiment", "v1"), …)`. It binds `conversation_id` in `structlog.contextvars` around the call so the ledger row is attributed. It returns `None` without calling when `get_settings().llm_disabled` is true, and `None` on any `LLMError`. It adds no retry of its own (R11: the client's two retries are the bound).
    - `cost_usd` is the sum of `LLMCallRecord.cost_usd` over the attempts of that one call, taken from a sink wrapper the scorer owns (it forwards every record to the inner sink it was given).
    - With one customer message, `start` and `end` are set to the same label in code. With no customer message it returns `None` without calling.
    - The module imports nothing from `app.domains.conversation`.
  - Verify: `cd backend && uv run python -c "from typing import get_args; from app.core.llm.registry import Step, MODEL_REGISTRY, TEMPERATURE; assert 'sentiment' in get_args(Step) and TEMPERATURE['sentiment'] == 0.0 and MODEL_REGISTRY['sentiment'] == MODEL_REGISTRY['compose']; from app.domains.analytics.sentiment import HaikuSentimentScorer, SentimentResult, SentimentScorer; print('ok')" && uv run pytest tests/unit/test_llm_client.py -q && ! grep -n "domains.conversation" app/domains/analytics/sentiment.py && uv run ruff check app/core/llm/registry.py app/domains/analytics/sentiment.py && uv run ruff format --check app/core/llm/registry.py app/domains/analytics/sentiment.py && uv run mypy app/core/llm/registry.py app/domains/analytics/sentiment.py`
  - Files: `backend/app/core/llm/registry.py`, `backend/app/domains/analytics/sentiment.py`, `backend/app/domains/analytics/prompts/sentiment@v1.md`

- [ ] T8: Pure analytics rules: cause groups, occurrences, interaction outcome, finish rule
  - Depends on: T1 (the package `backend/app/domains/analytics/`)
  - Read exactly these: spec D2–D6, D10, D17, D22; `docs/requirements/interaction-analytics-pipeline.md` §R3 (the "finished" rules and the metric table)
  - Acceptance:
    - `cause_groups.py`: one constant mapping each handoff reason to `by_design`, `customer_choice`, `bot_failure` or `security`, exactly as the requirement's "Cause group" row lists them, and a lookup that returns `None` for an unknown reason.
    - `service.py` has only pure functions and dataclasses (no SQL, no I/O, no LLM, no `conversation` import) and `METRICS_VERSION = 1`:
      - `build_occurrences(turn_segments)`: input is one list of segment dicts per `reply_sent`, in time order. It applies D5 (same intent continues only while the last status is `awaiting`), maps the last status to the outcome (D2: `awaiting` → `abandoned`), sets `needed_clarification` per D17, counts `turns` as the number of `reply_sent` entries with a segment in the occurrence, carries `bot_offered`, and numbers `seq` from 1.
      - the interaction outcome per D6 and D22: `real_intent_count` and `resolved` leave out a bot-offered occurrence that ended `cancelled`; `resolved` is `None` with no counted occurrence; `abandoned` needs `end_reason = idle` and a last occurrence that ended `abandoned`; `abstained` per D4 (an `abstained` occurrence, or any `reply_sent` with `route = "abstain"`).
      - the finish rule (REQ-R3): given the conversation's status, its last message time, its handoffs and `now`, return `None` (not finished) or the `end_reason`. An open handoff (`queued` or `claimed`) is never finished.
  - Verify: `cd backend && uv run python -c "from app.domains.analytics.service import build_occurrences as b; seg=lambda i,s,**k: {'intent':i,'route':i,'status':s,**k}; o=b([[seg('card_status','resolved'),seg('card_unlock','handoff')]]); assert [(x.seq,x.intent,x.outcome) for x in o]==[(1,'card_status','resolved'),(2,'card_unlock','handoff')]; o=b([[seg('card_block','awaiting',awaiting_slot='confirmation')],[seg('card_block','resolved')]]); assert len(o)==1 and o[0].outcome=='resolved' and o[0].turns==2 and not o[0].needed_clarification; o=b([[seg('card_block','awaiting',awaiting_slot='card_id')]]); assert o[0].outcome=='abandoned' and o[0].needed_clarification; print('ok')" && ! grep -rn "domains.conversation" app/domains/analytics/service.py app/domains/analytics/cause_groups.py && uv run ruff check app/domains/analytics/service.py app/domains/analytics/cause_groups.py && uv run ruff format --check app/domains/analytics/service.py app/domains/analytics/cause_groups.py && uv run mypy app/domains/analytics/service.py app/domains/analytics/cause_groups.py`
  - Files: `backend/app/domains/analytics/service.py`, `backend/app/domains/analytics/cause_groups.py`

- [ ] T9: Mock profile and the deterministic per-day generator
  - Depends on: T1 (the package and the `analytics_timezone` setting)
  - Read exactly these: `docs/requirements/interaction-analytics-pipeline.md` §R5 (all nine points and the profile table) and §R2 (the columns a row must fill); spec D15; `backend/app/domains/conversation/intents.yaml` (the 11 core-tier intents, read by eye: the module must not import `conversation`)
  - Acceptance:
    - `mock_profile.yaml` starts with `provenance: team-generated-synthetic` and holds every value of REQ-R5's table. The outcome shares have **no `cancelled`** and no `clarified` (D15). The 11 core intents are listed in the file itself.
    - `mock.py` has no SQL, no LLM call and no `conversation` import. `load_profile()` reads the YAML. `generate_day(day, profile, tz)` returns that day's interactions and their intent rows as plain dataclasses or dicts whose keys are the table columns.
    - It is deterministic: the day's date seeds a local `random.Random`; ids are `uuid5` of a fixed namespace and `"<iso date>:<index>"`; nothing reads the clock or global random state. Two calls for the same day return equal data.
    - Every row has `source = "mock"`. `started_at`/`ended_at` fall inside that local day in `tz`, spread over the day with the two peaks. Costs use the profile's unit costs times the turns. Sentiment labels, model and prompt version are generated values (model `mock`), with `sentiment_cost_usd = 0`.
    - `real_intent_count` equals the number of intent rows, and `resolved`, `abandoned`, `abstained`, `escalated` agree with the intent rows' outcomes under D6.
  - Verify: `cd backend && uv run python -c "from datetime import date; from zoneinfo import ZoneInfo; from app.domains.analytics import mock; p=mock.load_profile(); tz=ZoneInfo('America/Bogota'); a=mock.generate_day(date(2026,9,28),p,tz); b=mock.generate_day(date(2026,9,28),p,tz); c=mock.generate_day(date(2026,9,29),p,tz); assert a==b and a!=c; print('ok')" && head -5 app/domains/analytics/mock_profile.yaml | grep -q "provenance: team-generated-synthetic" && ! grep -n "cancelled\|clarified" app/domains/analytics/mock_profile.yaml && ! grep -n "domains.conversation" app/domains/analytics/mock.py && uv run ruff check app/domains/analytics/mock.py && uv run ruff format --check app/domains/analytics/mock.py && uv run mypy app/domains/analytics/mock.py`
  - Files: `backend/app/domains/analytics/mock.py`, `backend/app/domains/analytics/mock_profile.yaml`

- [ ] T10: The worker: one pass (compute, sentiment, mock seeding), the loop and the CLI, with `test_sentiment_masked_only` and `test_sentiment_unavailable`
  - Depends on: T1 (settings), T7 (`SentimentScorer`, `HaikuSentimentScorer`), T8 (`build_occurrences`, the outcome and finish functions, `METRICS_VERSION`), T9 (`load_profile`, `generate_day`). Real names are in the state file
  - Read exactly these: spec D7, D9, D10, D11, D13, D16 and §Contracts "Worker entrypoint"; `docs/requirements/interaction-analytics-pipeline.md` §R3 and §R5 points 2–5; `backend/tests/unit/test_llm_client.py` (the `StructuredLLMClient` seam with a fake chat-model factory and a recording sink)
  - Acceptance:
    - `worker.py` defines `AnalyticsStore`, a Protocol with everything the pass needs from the database: read and write the watermark and the last seeded mock day; list candidate conversations (D7); load one conversation's facts (conversation row, messages with `role`, `turn_id`, `created_at` and **`content_masked` only**, `reply_sent` payloads, handoffs, `audit.llm_calls` costs by step, country label); upsert one interaction with its intent rows; insert mock rows; list rows with null sentiment; list rows with an older `metrics_version`. It records the protocol's final shape in the state file.
    - `run_pass(store, scorer, *, now, settings)`:
      - computes every finished candidate and upserts it by `conversation_id` (D9); an unfinished one gets no row; then advances the watermark;
      - `cost_usd`, the per-step costs and `llm_call_count` leave out `step = "sentiment"`; the scorer's cost goes to `sentiment_cost_usd` only;
      - country is the label mapped with `app.domains.customers.service.COUNTRY_LABELS`; no customer identifier and no message text reaches a row;
      - calls the scorer one conversation at a time. A `None` result leaves the five sentiment columns null, still writes the row, and stops scoring for the rest of this pass. Rows with null sentiment and `source = 'real'` are retried on a later pass;
      - when `analytics_mock_enabled`, seeds each missing local day from `now` back to `analytics_mock_backfill_days` days, through `generate_day`, and records the last seeded day. A day already seeded is not generated again.
    - `--recompute` recomputes real rows with `metrics_version < METRICS_VERSION` and keeps their sentiment columns. `--rescore-sentiment` re-scores real rows. Both run once and exit.
    - CLI `python -m app.domains.analytics.worker`: no flag = loop every `analytics_worker_interval_s`; `--once` = one pass, exit 0. It builds the engine from `analytics_database_url` only: an empty value is a start-up error, never a fallback to `database_url`. It refuses a database whose name starts with `latam_eval_`. In the loop, an exception in a pass is logged (fields only, no text) and the loop continues.
    - The LLM client is built with `get_llm_client(sink=…)`, where the sink writes `audit.llm_calls` through the store (the worker's own role), not through `AuditLLMCallSink`.
    - `test_analytics_sentiment.py` has exactly two tests, with an in-memory `AnalyticsStore` fake and no database:
      - `test_sentiment_masked_only`: the store's message rows carry a raw value that the masked text replaces with a token; the request the fake chat model receives does not contain the raw value; the resulting row has the call's cost in `sentiment_cost_usd` and not in `cost_usd`.
      - `test_sentiment_unavailable`: once with `LLM_DISABLED=true` (no call at all) and once with a chat model that always fails (at most `retry_max + 1` attempts): the pass writes the row with the sentiment columns null.
    - `worker.py` imports nothing from `app.domains.conversation`.
  - Verify: `cd backend && uv run pytest tests/unit/test_analytics_sentiment.py -q && uv run python -m app.domains.analytics.worker --help && ! grep -n "domains.conversation" app/domains/analytics/worker.py && uv run ruff check app/domains/analytics/worker.py tests/unit/test_analytics_sentiment.py && uv run ruff format --check app/domains/analytics/worker.py tests/unit/test_analytics_sentiment.py && uv run mypy app/domains/analytics/worker.py`
  - Files: `backend/app/domains/analytics/worker.py`, `backend/tests/unit/test_analytics_sentiment.py`

- [ ] T11: Postgres store for the worker, with `test_finish_rules` and `test_mock_seed_deterministic`
  - Depends on: T1 (migration `0009`, settings), T10 (`AnalyticsStore` protocol and `run_pass`; their final shape is in the state file), T4 (`close_conversation` writes `closed_at`)
  - Read exactly these: `backend/app/domains/analytics/worker.py` (the protocol to implement); `backend/app/domains/audit/repository.py` (own SQL over other schemas, `_INSERT_LLM_CALL_SQL`); `backend/tests/integration/conftest.py` (`it_db`, `it_env`)
  - Acceptance:
    - `repository.py` has `build_engine(url)` (`create_async_engine(url, pool_size=3, max_overflow=0, pool_pre_ping=True)`, D16) and `PostgresAnalyticsStore(engine)`, which implements every method of `AnalyticsStore` with plain SQL. It never uses `app.core.db.get_engine`.
    - It selects `content_masked` and never `content`. `customer_id` appears only in the join to `bank.customers`.
    - Candidates (D7) come from `app.messages.created_at` and the `app.handoffs` time columns since the watermark minus the idle window, not from a scan of `app.conversations`. A null watermark means "all conversations once".
    - The interaction upsert and its intent rows are one transaction: `INSERT … ON CONFLICT (conversation_id) DO UPDATE`, then the conversation's intent rows are replaced.
    - The ledger insert writes the same columns as `audit/repository.py::insert_llm_call`.
    - `test_analytics_worker.py` is created with two tests. Both use `it_env`, set `ANALYTICS_DATABASE_URL` to the `it_db` URL, pass a fixed `now`, and use a scorer fake (no LLM):
      - `test_finish_rules`: rows inserted with SQL. A conversation whose last message is older than the idle threshold gets a row with `end_reason = 'idle'`; one with a `queued` handoff gets no row; one closed through `store.close_conversation` has `closed_at` set and gets `end_reason = 'customer_closed'`.
      - `test_mock_seed_deterministic`: mock enabled, empty schema. One pass gives 30 distinct local days of `source = 'mock'` rows and no `real` row; a second pass adds none; deleting both tables' rows, clearing `mock_seeded_through` and running again gives the same rows (compared without `computed_at`).
    - Both tests must **run**, not skip. If Postgres or Redis cannot be reached, or a test is skipped: stop and report it in the state file. Do not read any `.env` outside the worktree and do not change credentials.
  - Verify: `cd backend && uv run pytest tests/integration/test_analytics_worker.py -k "finish_rules or mock_seed_deterministic" -q -rs` (2 passed, 0 skipped) `&& ! grep -n "domains.conversation\|get_engine" app/domains/analytics/repository.py && uv run ruff check app/domains/analytics/repository.py tests/integration/test_analytics_worker.py && uv run ruff format --check app/domains/analytics/repository.py tests/integration/test_analytics_worker.py && uv run mypy app/domains/analytics/repository.py`
  - Files: `backend/app/domains/analytics/repository.py`, `backend/tests/integration/test_analytics_worker.py`

- [ ] T12: Compose service `analytics-worker`, `make analytics`, and the new secret in `fill-secrets` and `.env.prod.example`
  - Depends on: T1 (`.env.example` holds `ANALYTICS_DB_PASSWORD=` and the settings names)
  - Read exactly these: `docker/docker-compose.base.yml` (the `backend` service) with `docker/docker-compose.dev.yml` and `docker/docker-compose.prod.yml`; `Makefile` (`COMPOSE`, `.PHONY`, `fill-secrets`); spec D8, D16 and `docs/requirements/interaction-analytics-pipeline.md` §R6
  - Acceptance:
    - Base file: service `analytics-worker` uses the same build as `backend` (context and additional contexts), `env_file: ../.env`, command `uv run --no-sync python -m app.domains.analytics.worker`, `mem_limit: 512m`, `depends_on` Postgres healthy, no published port, no healthcheck. Its `environment` sets `ANALYTICS_DATABASE_URL` **and** `DATABASE_URL` to `postgresql+asyncpg://analytics_worker:${ANALYTICS_DB_PASSWORD}@postgres:5432/latam_app`, so nothing in that process can connect as the superuser.
    - Dev overlay: mounts `../backend/app:/app/app` and passes `LLM_DISABLED` like `backend` does. Prod overlay: `restart: unless-stopped`, `APP_ENV: prod`, `LLM_PROVIDER: bedrock`, like `backend`.
    - `Makefile`: target `analytics` (in `.PHONY`, with a `##` help text) runs `$(COMPOSE) run --rm analytics-worker uv run --no-sync python -m app.domains.analytics.worker --once`. `fill-secrets` has `ANALYTICS_DB_PASSWORD` in its `keys` list and in its help text.
    - `.env.prod.example`: `ANALYTICS_DB_PASSWORD=` in the SSM block and `ANALYTICS_MOCK_ENABLED=true` among the plain values.
    - This task starts, stops and builds nothing. `infra/aws/render-env.sh` is not edited.
  - Verify: `cd backend && uv run python -c "import yaml; b=yaml.safe_load(open('../docker/docker-compose.base.yml'))['services']['analytics-worker']; assert b['mem_limit']=='512m'; e=b['environment']; assert 'analytics_worker:' in e['ANALYTICS_DATABASE_URL'] and e['DATABASE_URL']==e['ANALYTICS_DATABASE_URL']; assert 'analytics.worker' in ' '.join(b['command']) if isinstance(b['command'], list) else 'analytics.worker' in b['command']; d=yaml.safe_load(open('../docker/docker-compose.dev.yml'))['services']['analytics-worker']; p=yaml.safe_load(open('../docker/docker-compose.prod.yml'))['services']['analytics-worker']; assert p['restart']=='unless-stopped'; print('ok')" && cd .. && make -n analytics | grep -q "analytics.worker --once" && grep -q "^ANALYTICS_DB_PASSWORD=$" .env.prod.example && T="$(mktemp -d)" && cp .env.example "$T/.env" && (cd "$T" && make -f "$OLDPWD/Makefile" fill-secrets >/dev/null) && grep -q "^ANALYTICS_DB_PASSWORD=..*" "$T/.env" && rm -rf "$T"`
  - Files: `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml`, `docker/docker-compose.prod.yml`, `Makefile`, `.env.prod.example`

- [ ] T13: End-to-end worker tests: `test_worker_es_multi_intent` and `test_worker_pt_write_happy_path`
  - Depends on: T4 (`segments` on `reply_sent`), T5 and T6 (flow marks), T11 (`PostgresAnalyticsStore`, the test file and its helpers), T10 (`run_pass`). Real names are in the state file
  - Read exactly these: `backend/tests/integration/test_write_path_api.py` (`app_client` + `ScriptedLLM` on `app.state.turn_host.llm`; `test_pt_lock_happy_path` and `test_bank_blocked_unlock_handoff` are the two scripts to mirror); `backend/tests/integration/test_analytics_worker.py` (the helpers already there); spec D5, D6, D22
  - Acceptance:
    - Two tests are added to `test_analytics_worker.py`. Both drive real turns through the API with a `ScriptedLLM`, then call `run_pass` in-process with a `now` past the idle threshold and a scorer fake. No live LLM.
    - `test_worker_es_multi_intent` (Spanish): one conversation where a read intent is answered and another intent hands off (the bank-side blocked unlock of `test_bank_blocked_unlock_handoff` is the ready-made case). The test then sets that handoff to `returned` with SQL, because an open handoff gives no row. Asserts: two `analytics.interaction_intents` rows with outcomes `resolved` and `handoff`, and `resolved = false`, `escalated = true`, `language = 'es'` on the interaction.
    - `test_worker_pt_write_happy_path` (Portuguese): a **temporary lock** with its confirmation. The permanent block is not used: it leaves a replacement offer pending, which D22 turns into `abandoned`. Asserts: exactly one intent row, `card_block`, `resolved`, `turns = 2`; `resolved = true`, `language = 'pt'` on the interaction; no message text and no `customer_id` column in either table.
    - Both tests must **run**, not skip. If Postgres or Redis cannot be reached, or a test is skipped: stop and report it in the state file. Do not read any `.env` outside the worktree and do not change credentials.
    - If a test fails because a segment has the wrong status, report which flow ending it was in the state file; do not edit flow or graph files from this task.
  - Verify: `cd backend && uv run pytest tests/integration/test_analytics_worker.py -q -rs` (4 passed, 0 skipped) `&& uv run ruff check tests/integration/test_analytics_worker.py && uv run ruff format --check tests/integration/test_analytics_worker.py`
  - Files: `backend/tests/integration/test_analytics_worker.py`

- [ ] T14: Live-stack proof from the worktree: `make up`, migration `0009` on both databases, `make analytics`, role proofs, `make check` (ALONE)
  - Depends on: T1–T13 (everything built; this task writes no code)
  - Read exactly these: spec D21 and Success criteria 8 and 9; `Makefile` (`up`, `analytics`, `check`, `fill-secrets`); `README.md` §4
  - Acceptance:
    - **First step:** check that `.env` exists in the worktree root. If it is missing, **stop and report**. Never copy, read or link a `.env` from outside the worktree: the human puts it there.
    - This task takes over the shared `latam-cs` stack. It runs no `make demo-reset`, no `make seed-identity`, no `make data`, no `make down`.
    - In the worktree's own `.env`: run `make fill-secrets` (it fills `ANALYTICS_DB_PASSWORD` without printing it) and make sure `ANALYTICS_MOCK_ENABLED=true` is present. No other line changes.
    - `make up` from the worktree. `docker compose ps` (through the Makefile's `COMPOSE` files) shows `analytics-worker` running.
    - Alembic upgrades both databases in place, golden first: `cd backend && DATABASE_URL="$(grep '^GOLDEN_DATABASE_URL=' ../.env | cut -d= -f2-)" uv run alembic upgrade head`, then `cd backend && uv run alembic upgrade head`. Both end at `0009`.
    - `make analytics` exits 0. Then `SELECT count(DISTINCT (ended_at AT TIME ZONE 'America/Bogota')::date) FROM analytics.interactions WHERE source = 'mock'` on `latam_app` returns the backfill window (30).
    - Role proofs on `latam_app`, from a superuser `psql` session in the Postgres container (criterion 9). Each statement is its own transaction that ends in `ROLLBACK`, after `SET ROLE analytics_worker`:
      - `INSERT INTO app.messages (id) VALUES (gen_random_uuid())` fails with "permission denied";
      - `INSERT INTO audit.audit_events (id) VALUES (gen_random_uuid())` fails with "permission denied";
      - `INSERT INTO analytics.worker_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING` succeeds;
      - `INSERT INTO audit.llm_calls (id, at, step, provider, model_id, prompt_version, attempt, status, latency_ms) VALUES (gen_random_uuid(), now(), 'sentiment', 'anthropic', 'proof', 'sentiment@v1', 1, 'ok', 0)` succeeds, and after the rollback `SELECT count(*) FROM audit.llm_calls WHERE model_id = 'proof'` is 0.
    - `make check` passes.
    - The results of every step (pass or the exact error, never a secret value) go into the state file. The last line written tells the human: the stack now runs the worktree's code and both databases are at `0009`; run `make up` from the main checkout to go back.
    - On any failure: report it. Fix nothing in source files from this task.
  - Verify: `test -f .env && make up && docker ps --format '{{.Names}} {{.Status}}' | grep "latam-cs-analytics-worker-1 Up" && (cd backend && DATABASE_URL="$(grep '^GOLDEN_DATABASE_URL=' ../.env | cut -d= -f2-)" uv run alembic upgrade head && uv run alembic upgrade head) && make analytics && docker exec latam-cs-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d latam_app -Atc "SELECT count(DISTINCT (ended_at AT TIME ZONE '"'"'America/Bogota'"'"')::date) FROM analytics.interactions WHERE source = '"'"'mock'"'"'"'` (prints 30), then the four role proofs above with `docker exec latam-cs-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d latam_app -c "BEGIN; SET ROLE analytics_worker; <statement>; ROLLBACK;"'`, then `make check`
  - Files: none in the repository (the worktree's untracked `.env` gets `ANALYTICS_DB_PASSWORD` and `ANALYTICS_MOCK_ENABLED`)

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3 | | No dependencies and disjoint files: migration and settings, the conversation graph, the docs. T1 touches only a throwaway database; no sibling runs an integration test |
| W2 | T4, T5, T6, T7, T8, T9, T12 | | Each depends only on T1 or T2. Files are disjoint: runner and store; three card flows; four other flows; registry and scorer; pure rules; mock; Compose and Makefile. Unit tests and static checks only |
| W3 | T10 | | Needs T7, T8 and T9. One source file and its unit tests, no database |
| W4 | T11 | | Needs T10's protocol and T4's `closed_at`. First integration tests of the card |
| W5 | T13 | | Needs T11's store and test file plus T4, T5, T6. Edits the same test file as T11, so it cannot share its wave |
| W6 | T14 | alone (rebuilds the shared stack, migrates the dev databases, live proof) | Last: it proves the finished card and changes the environment every other task runs against |
