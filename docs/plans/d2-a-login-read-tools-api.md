# Plan: D2-A — login, read tools and hosting the agent (G4)

Spec: [`docs/specs/d2-a-login-read-tools-api.md`](../specs/d2-a-login-read-tools-api.md) · Branch: `feat/d2-a-login-read-tools-api`

> **Status:** the four plan questions were answered by the human (all option A, no spec change). The decisions are recorded under "Human decisions (plan questions)" below and in the Facts where tasks need them.

## Facts checked against the repo

- **Base:** `feat/d2-a-login-read-tools-api` = `develop` = `origin/develop` = `dd6a10b` (D2-K merged). The working tree already holds the spec's doc amendments, uncommitted: `01` §6 identity bullet, `03` §6 `identity` and §8, `04` §3 (login body, `MeResponse`, `debug` event), and ADR-008 "Amended 2026-09-28". They ship with this PR, so no task rewrites them. Criterion 8 is checked by reading them.
- **Baseline is green (2026-09-27):** from `backend/`, `ruff check app tests` is clean, `ruff format --check` reports 74 files formatted, `mypy app` reports no issues in 59 files, `lint-imports` shows 4 contracts KEPT, and `pytest tests/unit -q` shows 24 passed.
- **How commands run:** run everything as `cd backend && uv run …` from the repo root. uv's `VIRTUAL_ENV` mismatch warning is harmless. There is **no pytest-asyncio**, so tests drive coroutines with `asyncio.run(...)`. `tests/` has no `__init__.py`, and tests import shared helpers as `from tests.conftest import ScriptedLLM` (`pythonpath = ["."]`). The root `tests/conftest.py` also applies to `tests/integration/`.
- **Locked versions:** langgraph 1.2.12, langgraph-checkpoint 4.2.0, fastapi 0.141.1, redis 8.1.0, sqlalchemy 2.0.54, sqlmodel 0.0.47, structlog 26.1.0, pydantic 2.13.5, httpx 0.28.1 (dev group, available under `uv run`). `pyjwt`, `psycopg` and `langgraph-checkpoint-postgres` are **not** installed in `backend/` yet. `pipeline/` has its own psycopg.
- **langgraph serde:** `JsonPlusSerializer` in checkpoint 4.2.0 still accepts unregistered msgpack types by default and only warns (strict mode only with `LANGGRAPH_STRICT_MSGPACK=true`). Checkpoint metadata copies only `str`/`int`/`float`/`bool` values out of `configurable`, so the `ToolContext`, bank tools and LLM objects in the run config never get serialized.
- **Settings** (`backend/app/core/config.py`): `pydantic-settings`, `extra="ignore"`, `.env` read from the repo root (`parents[3]`). Environment variables win over `.env`. Everything is cached through `@lru_cache get_settings()`. `app.core.db.get_engine()` and `app.core.redis.get_redis()` are `@lru_cache`d too, and their asyncpg connections and Redis clients are bound to the event loop that first used them. Any test that switches `DATABASE_URL` or runs a new event loop must `cache_clear()` all three.
- **`DATABASE_URL` shape:** `postgresql+asyncpg://…`. psycopg (checkpointer, provisioning, test harness) needs the `+asyncpg` removed. `pipeline/load/__main__.py::_psycopg_dsn` shows the pattern (it lives in another project, so reimplement it, don't import it).
- **DB state (local stack is up):** `latam_golden` and `latam_app` are both at alembic `0001`. They have schemas `bank, app, identity, audit` and **no `langgraph` schema**. `identity`/`app` have no tables beyond `app.system_metadata`. `bank.customers` has 150,000 rows, and `document_number` is non-null with 150,000 distinct values. They stay 150,000 distinct after D1 normalization (strip, drop whitespace/`.`/`-`, uppercase) and as `type:number`. The types are `DNI` (AR 29,842 and MX 74,907, 8 digits), `CC` (10 digits), `CE` (7 digits) and `Pasaporte` (8 characters, alphanumeric). No stored number contains a space, dot or dash. `country` ∈ {`México`, `Colombia`, `Argentina`}. `customer_status` ∈ {Active, Inactive, Suspended, Closed}. Card `product_type` ∈ {`Tarjeta Crédito`, `Tarjeta Débito`}, and every card `product_number` ends in 4 digits. `first_name` is never null.
- **Personas:** `eval/personas.yaml` has B's 10 personas with keys `customer_id, country, card_count, card_kinds, blocked` (plus optional `notes`). `CLI-U6NAXZG11P97` (MX, credit + debit, both Active, 70 transactions) and `CLI-15CX29YY6SS9` (CO, credit + debit) exist in `latam_app`. These are the demo and "foreign" personas for manual checks.
- **Pipeline:** `make data` = `cd pipeline && uv run python -m ingest && uv run python -m load`. `load` runs `alembic upgrade head` against `GOLDEN_DATABASE_URL` in a subprocess (cwd `backend/`, `DATABASE_URL` overridden in env), COPYs `bank.*`, then calls `load.demo_reset.reset()`. `demo_reset` terminates every connection to both DBs and recreates `latam_app` with `CREATE DATABASE latam_app TEMPLATE latam_golden`. So anything created only in `latam_app` (for example checkpointer tables made by `setup()`) is gone after a reset, and the running backend's pooled connections are killed.
- **Alembic:** `backend/app/alembic/env.py` sets the URL from `get_settings().database_url` **at import**, so an in-process `alembic.command.upgrade` inside a test would use whatever Settings are cached and could migrate `latam_app`. Run alembic as a subprocess with `DATABASE_URL` in its env, the way `pipeline/load` does. `0001` creates schemas `bank, app, identity, audit` and drops them `CASCADE` on downgrade. `03` §3 (line 61): "DDL for **all** schemas is owned by Alembic … The LangGraph checkpointer manages its own tables in schema `langgraph`." So `0002` must create the `langgraph` schema, and `setup()` creates the tables inside it.
- **Container:** the backend service builds from `backend/` (image `/app` = `Dockerfile, alembic.ini, app, pyproject.toml, uv.lock`). The dev overlay bind-mounts only `../backend/app:/app/app` and runs `uvicorn --reload`. New dependencies therefore need an image rebuild (`make up` runs `up -d --build`), and new `.env` keys reach the container only when it is recreated (`env_file: ../.env`). Port 8000 is **not** published. Everything goes through Nginx on `http://localhost` (`/api/` → backend). The dev Nginx `/api/` block sets no `proxy_buffering off`, so the SSE response must send `X-Accel-Buffering: no`. Nginx's default `proxy_read_timeout` is 60 s.
- **`/policies` is missing in the container:** `flows/card_select.py` resolves `_REPO_ROOT = parents[5]`, which is `/` in the container, and `card_info` calls `load_card_select_policy()` **on every turn**. Inside the container, `/policies/card_select.yaml` doesn't exist. **Decided (human):** the dev overlay mounts `../policies:/policies:ro` in `docker/docker-compose.dev.yml` (T14). The prod image is the deploy card's problem (D4).
- **FastAPI docs:** `create_app()` sets `openapi_url="/api/v1/openapi.json"` but leaves `docs_url` at the default `/docs`, which Nginx routes to the frontend. Criterion 4 needs `docs_url="/api/v1/docs"`.
- **`test_health.py` runs the lifespan:** it uses `with TestClient(app) as client:`, which runs startup and shutdown, even though its docstring says "no lifespan". CI (`.github/workflows/ci.yml`) runs `uv run pytest tests/unit -q` with no `.env`, no Postgres and no Redis. **Decided (human):** `test_health.py` changes one line to `client = TestClient(app)` (no `with`, so no lifespan), and its assertions stay the same (T11). D16/D21 stay literal: the lifespan refuses empty secrets and runs `saver.setup()`.
- **Routers today:** `app/api/router.py` mounts `app.api.v1.v1_router` at `/api/v1`, and `v1_router` (module-level, built at import) includes only `health.router`. A router that depends on `APP_ENV` (test-idp) must therefore be mounted inside `create_app()`, not in the import-time `v1_router`.
- **Logging:** `configure_logging()` (called by `create_app()`) uses structlog through stdlib with `cache_logger_on_first_use=True`. `structlog.testing.capture_logs()` still works in this suite: `tests/unit/test_llm_client.py` is the analogue, and `app/core/llm/client.py` logs through a module-level `_logger`. `RequestIDMiddleware` binds `request_id`/`trace_id` and logs `method, path, status, duration_ms` only, never bodies or query strings. `app.core.telemetry.get_trace_id()` returns the current trace id.
- **Graph hosting surface:** `graph.build_graph(checkpointer)` compiles the graph. `graph.run_turn(graph, text, config=)` is the only `astream` call, and it returns just `(reply, DebugInfo)`, so it can't yield per-node `status` events. The API runner therefore runs its own `astream(..., stream_mode="updates")` loop, mirroring `run_turn`, and builds `DebugInfo` (imported from `graph.py`) the same way. `graph.py` is not modified. The run config keys are `thread_id`, `session` (a `ToolContext`), `bank_tools`, `llm`, and now `bank_write_tools=None` (D13). `load_session` reads `session` and `bank_tools`. `sandbox._RecordingBankTools` is private to `sandbox.py`, which this card doesn't touch, so the registry has its own recorder.
- **Test fixtures to reuse:** `backend/tests/fixtures/fakebank/` holds invented CSVs whose headers match the `bank.customers`, `bank.products` and `bank.transactions` column lists exactly (UTF-8 with BOM, empty string = NULL). The customers are `CLI-TFMULTI00001` (MX, doc `CC`/`DOC-TF0000001`, first name `Prueba`, last name `Uno`; cards `PRD-TFM1CRED0001` credit `…6475` Active, `PRD-TFM1DEBT0002` debit Active, `PRD-TFM1DEBT0003` debit Closed, `PRD-TFM1SAVE0004` savings), `CLI-TFSINGLE0002` (CO, `DOC-TF0000002`; `PRD-TFS2CRED0001` credit Active) and `CLI-TFBLOCKD0003` (AR; `PRD-TFB3DEBT0001` debit Blocked). `tests/unit/test_sandbox_conversations.py::test_es_multi_card_asks_then_answers` is the ScriptedLLM script for "which card?" → "la de credito" on `CLI-TFMULTI00001`.
- **`.env` today:** it has none of `APP_ENV`, `BANK`, `JWT_SECRET`, `IDENTITY_HMAC_KEY` or `CREDENTIALS_SEED`, so `make setup`'s `cp -n` won't add them. The fill step must append missing keys as well as fill empty ones. `ANTHROPIC_API_KEY` is set locally, so manual `make chat-api` checks can use the real LLM. Tests never do.
- **mypy strict** applies to `app.core.*`, `app.domains.conversation.*` and `app.domains.policy.*`, not to `identity`/`customers`/`cards`/`transactions`. `app.core.events` and every new `conversation` module must therefore be fully typed.
- **import-linter:** the 4 contracts match `app.domains.*.repository` by shape. The new `customers/cards/transactions/identity` `repository.py` files are forbidden to `app.domains.conversation` and `app.core` from the moment they exist. That is why the conversation persistence module is `conversation/store.py`. The contracts need no edit.
- **`app/domains/identity/`** exists with `__init__.py` (a docstring about the step-up gate) and `step_up.py`. `step_up.py` stays untouched.
- **`data/` is git-ignored as a whole**, so `data/secrets/credentials.csv` is ignored without a `.gitignore` edit. Check it with `git check-ignore -q`.
- **Frontend client:** `make client` = `cd frontend && npx @hey-api/openapi-ts` against `http://localhost/api/v1/openapi.json` (through Nginx, so it needs the stack up with the new code). `frontend/biome.json` excludes `src/client`.
- **Redis isolation in tests (decided, human):** no key prefix in product code. Keys stay `rl:login:<login_key>`, `turn:<conversation_id>` and `conv:<conversation_id>`. Integration tests are isolated by a per-run random `IDENTITY_HMAC_KEY` (so `rl:login:` keys are unique per run) and fresh UUIDs, and they delete the keys they created at teardown.
- **Error codes (decided, human):** HTTP errors use FastAPI's `HTTPException(status, detail="<code>")`, so the body is `{"detail": "<code>"}` (`invalid_credentials`, `session_expired`, `forbidden_role`, `not_found`, `turn_in_progress`, `too_many_attempts`). A CSRF failure is `403 csrf_failed`. A failed turn emits SSE `error {"code": "turn_failed"}` then `done`.
- **Integration Verify convention:** integration tests skip when Postgres is unreachable, and a skip is not a proof. Every integration Verify pipes pytest through `tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in'`, so a skip or failure fails the Verify.

## Components

| Component | Path | Depends on |
|---|---|---|
| Settings, deps, secret filling | `backend/app/core/config.py`, `backend/pyproject.toml`, `backend/uv.lock`, `.env.example`, `Makefile` (`fill-secrets`) | nothing |
| Migration `0002` | `backend/app/alembic/versions/0002_identity_conversations.py` (new) | `0001` |
| Identity primitives (`Session`, `LoginRequest`, `MeResponse`, normalization, `login_key`, passwords, JWT) | `backend/app/domains/identity/{models,passwords,tokens}.py` (new) | Settings, `pyjwt` |
| Bank read services | `backend/app/domains/{customers,cards,transactions}/{repository,service}.py` (new) | `app.core.db`, existing `schemas.py`, `app.core.errors` |
| `PostgresBank` | `backend/app/domains/conversation/tools/postgres.py` (new) | the three `service` modules, `ToolContext` |
| Integration harness | `backend/tests/integration/conftest.py` (new) | migration, fixtures CSVs, psycopg |
| Identity service + deps | `backend/app/domains/identity/{repository,service,deps}.py` (new) | primitives, `customers.service`, `0002` |
| Auth API | `backend/app/api/v1/auth.py` (new), `backend/app/api/v1/__init__.py` | identity service + deps |
| Provisioning | `backend/app/domains/identity/provision.py` (new), `Makefile` (`seed-identity`, `data`) | primitives, `0002` on golden |
| Personas | `eval/personas.yaml`, `backend/tests/integration/test_personas.py` (new) | `latam_golden` |
| Conversation store, Redis events, registry v0 | `backend/app/domains/conversation/store.py`, `backend/app/core/events.py`, `backend/app/domains/conversation/tools/registry.py` (new) | `0002`, `app.core.redis`, `Session`, `PostgresBank`, `FakeBank` |
| Hosting + runner + lifespan | `backend/app/domains/conversation/{hosting,runner}.py` (new), `backend/app/main.py` | graph, store, events, registry, checkpointer deps |
| Conversation API | `backend/app/domains/conversation/deps.py`, `backend/app/api/v1/conversations.py` (new) | runner, store, identity deps |
| Test IdP | `backend/app/api/v1/test_idp.py` (new), `backend/app/main.py` | identity service |
| `make chat-api`, client | `backend/scripts/chat_api.py` (new), `Makefile`, `frontend/src/client/` (generated), `docker/docker-compose.dev.yml` (policies mount) | everything above, running stack |
| Login rate limit (cuttable) | `identity/service.py`, `api/v1/auth.py` | Redis, Settings |
| `/auth/refresh` (cuttable) | `identity/service.py`, `api/v1/auth.py` | identity deps |

## Build order

1. **T1 deps + Settings + secret filling.** Every later module reads these Settings, and T3/T5/T8/T11 import the new packages.
2. **T2 migration `0002`.** Identity, conversation storage, the harness and provisioning all need the tables and the `langgraph` schema.
3. **T3 identity primitives.** Pure code. T6, T8, T10 and the harness's account seeding use `Session`, `login_key` and the password helpers.
4. **T4 bank read services.** Pure DB reads over `bank.*`. They need neither `0002` nor identity. `PostgresBank` (T5) and `/me` (T6) call them.
5. **T5 integration harness + `PostgresBank` + the R1 foreign-card test.** This is the first integration test, so it creates the shared throwaway-DB fixtures that T7/T11/T12 reuse.
6. **T6 identity repository/service/deps + the D2 unit test.** Needs T3, T4 (`customers.service` for `/me`) and T2 (tables).
7. **T7 auth routes + the `/me` integration test.** Needs T6 and T5's harness, which it extends with account seeding.
8. **T8 provisioning.** Needs T3 and T2. It resets `latam_app` to `0002`, which the running stack needs from T14 on. It comes after T7 so login works before 150k accounts exist.
9. **T9 personas.** Independent of app code, but its local-only test follows T5's skip convention.
10. **T10 store + events + registry.** The runner (T11) needs all three. The registry needs `PostgresBank` (T5) and `Session` (T3).
11. **T11 hosting + runner + lifespan + restart test.** Needs T10. It also adds `main.py`'s lifespan and makes `test_health.py` skip it.
12. **T12 conversation routes + the R13 ownership integration test.** Needs the runner (T11) and the identity deps (T6).
13. **T13 test-idp + the R1/R13 route unit tests.** These walk the fully mounted app, so they come after every router exists (T7, T12).
14. **T14 `make chat-api` + `make client`.** End to end against the running stack. Needs everything above, plus T8's seeded accounts.
15. **T15 login rate limit (cuttable to D3).**
16. **T16 `/auth/refresh` (cuttable to D3).** T15 and T16 come last so the "If behind" cut removes only them. T13's R13 test already exempts `/auth/refresh`, so it passes with or without T16.

## Touch map

| File | New / modified | What changes |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modified | + `pyjwt`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]` |
| `backend/app/core/config.py` | modified | + the 8 Settings fields from the spec |
| `.env.example` | modified | + `APP_ENV`, `BANK`, empty secrets, session/login limits |
| `Makefile` | modified | + `fill-secrets` (called by `setup`), `seed-identity`, `data` runs it, `test-integration`, `chat-api` |
| `backend/app/alembic/versions/0002_identity_conversations.py` | new | `identity.accounts`, `identity.revoked_tokens`, `app.conversations`, `app.messages`, schema `langgraph` |
| `backend/app/domains/identity/models.py` | new | `DocumentType`, `Session`, `LoginRequest`, `MeResponse` |
| `backend/app/domains/identity/passwords.py` | new | normalization, `login_key`, generator, PBKDF2 hash/verify |
| `backend/app/domains/identity/tokens.py` | new | JWT issue/decode, cookie and header names, CSRF token |
| `backend/app/domains/identity/repository.py` | new | accounts and revoked-token queries |
| `backend/app/domains/identity/service.py` | new | login, me, logout, session-from-token, test-idp mint; later rate limit and refresh |
| `backend/app/domains/identity/deps.py` | new | `get_session`, `require_role`, `require_csrf` |
| `backend/app/domains/identity/provision.py` | new | 150k accounts + git-ignored export |
| `backend/app/domains/{customers,cards,transactions}/repository.py` | new | parameterized `bank.*` reads |
| `backend/app/domains/{customers,cards,transactions}/service.py` | new | read-model functions (the only door into those repositories) |
| `backend/app/domains/conversation/tools/postgres.py` | new | `PostgresBank`, `make_postgres_factory` |
| `backend/app/domains/conversation/tools/registry.py` | new | `build_tool_context`, `RecordingBankTools`, `bank_tools_for` |
| `backend/app/domains/conversation/store.py` | new | `app.conversations`/`app.messages` persistence |
| `backend/app/core/events.py` | new | Redis pub/sub for `conv:<id>` |
| `backend/app/domains/conversation/hosting.py` | new | psycopg pool, `AsyncPostgresSaver`, compiled graph (`TurnHost`) |
| `backend/app/domains/conversation/runner.py` | new | turn lock, `start_turn`, the turn task and its event stream |
| `backend/app/domains/conversation/deps.py` | new | `get_owned_conversation` |
| `backend/app/api/v1/auth.py` | new | `/auth/login`, `/logout`, `/me` (+ `/refresh` in T16) |
| `backend/app/api/v1/conversations.py` | new | `POST /conversations`, `POST …/messages`, `GET …/stream` |
| `backend/app/api/v1/test_idp.py` | new | `POST /test-idp/sessions` |
| `backend/app/api/v1/__init__.py` | modified | mounts `auth` and `conversations` |
| `backend/app/main.py` | modified | `docs_url`, lifespan (secret refusal, `TurnHost`), eval-only test-idp mount |
| `backend/scripts/chat_api.py` | new | `make chat-api` |
| `backend/tests/unit/test_login_pii.py`, `test_r1_routes.py`, `test_r13_routes.py` | new | D2, R1, R13 |
| `backend/tests/integration/conftest.py` | new | throwaway DB, fixture rows, accounts, app client |
| `backend/tests/integration/test_{auth,r1_postgres_tools,r13_ownership,restart,personas}.py` | new | the spec's six integration tests |
| `eval/personas.yaml` | modified | + ~20 personas, trait vocabulary header |
| `frontend/src/client/**` | regenerated | `make client` output only |
| `docker/docker-compose.dev.yml` | modified | mount `../policies:/policies:ro` |
| `backend/tests/unit/test_health.py` | modified | `TestClient(app)` without `with` (no lifespan) |

Not touched: `flows/`, `nodes/`, `prompts/`, `graph.py`, `state.py`, `fakebank.py`, `sandbox.py`, `identity/step_up.py`, `.importlinter`, `pipeline/`, `eval/scenarios/heldout/`.

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| The lifespan (secret refusal + `saver.setup()`) breaks `test_health.py` in CI, which has no `.env` and no Postgres | `test_health.py` uses `TestClient(app)` without `with`, so it skips the lifespan (T11). T11's Verify also runs `test_health.py` with empty secrets and an unreachable `DATABASE_URL`, simulating CI |
| API turns crash in the container because `/policies/card_select.yaml` is missing | The dev overlay mounts `../policies:/policies:ro` (T14). T14 proves a real card answer through `make chat-api` |
| `customer_id` reaches a route from a body, query or path | Every body model omits it (T3, T7, T12). T13's R1 walker checks all params and nested body fields, and proves it isn't vacuous by flagging the eval-only test-idp body |
| A route skips its role or ownership dependency | Router-level `require_role` on every non-public router (T7, T12). T13's R13 introspection test. T12's cross-customer 404 integration test |
| A bank query not filtered by `customer_id`, or a foreign card leaks data | Every repository query binds `:customer_id`. The only exception is the single-column existence probe, mirroring FakeBank (T4). T5's test proves `AccessDenied` + one `tool.access_denied` record, and that the own card works |
| `document_number` in a log, key, error or 422 body | Only `login_key` (logs: first 12 hex) is ever used (T6). `LoginRequest.document_number` is a plain `str` with no constraints, so a 422 never echoes it (T3). T6/T15's unit test checks both logs and the rate-limit key. T8's provision prints counts only |
| An alembic run in tests migrates `latam_app` through cached Settings | The harness runs alembic as a subprocess with `DATABASE_URL` in env (T5). The drop step refuses any DB name not starting with `latam_it_` |
| Cross-event-loop reuse of the cached engine or Redis client in tests | `it_env` clears `get_settings`, `get_engine` and `get_redis` before and after each test (T5) |
| `demo-reset` drops the checkpointer tables and kills the backend's pool | `seed-identity`/`data` restart the backend container when it is running, so `setup()` runs again (T8) |
| Missing `langgraph` schema makes `setup()` fail | `0002` creates it (T2, per `03` §3) |
| SSE stuck behind Nginx buffering or cut after 60 s idle | `X-Accel-Buffering: no`, `Cache-Control: no-cache`, a `: ping` comment every 15 s (T12). `chat-api` opens a stream per turn (T14) |
| A race: the POST publishes before the stream has subscribed | The stream route subscribes **before** returning its response and first sends `: connected`. `chat-api` waits for that line before posting (T12, T14) |
| The turn task gets garbage-collected or leaks the lock | The task is held in `TurnHost.tasks`. The lock is released in `finally`, only if its value is still this `turn_id`, and has a 120 s TTL as a backstop (T11) |
| A 409'd message still lands in history | `start_turn` takes the lock **before** persisting the customer message (T11) |
| An LLM call in tests | Only `ScriptedLLM` in T11's restart test. Every other test has no LLM path |
| B's parallel D2 track (B1/B2 formatting, B3 queue) changes the reply text | The restart test asserts `"6475"`, the route and `pending`, not an exact formatted sentence (T11) |
| New deps not in the running container, or new `.env` keys not in its env | T14 runs `make up` (rebuild + recreate) before any live check |
| `uv add` bumps langgraph or langgraph-checkpoint | T1 re-runs the graph and sandbox unit tests and records any version change in the state file |
| A migration that doesn't downgrade | T2's Verify runs upgrade → downgrade `0001` → upgrade on a scratch DB |
| Provisioning takes minutes (150k PBKDF2) | 1,000 iterations per D4, one COPY in one transaction. T8's Verify allows a long timeout |

## Tests

Budget: the R1/R13/D2 safety tests plus one proof per "Done when" line. Fake LLM only. Integration tests are local only (D19), run with `make test-integration`, and not in `make check`/CI.

| Test | Written in |
|---|---|
| `unit/test_r1_routes.py::test_no_route_accepts_customer_id` | T13 |
| `unit/test_r13_routes.py::test_every_route_declares_role_and_ownership` | T13 |
| `unit/test_login_pii.py::test_document_number_never_logged_or_keyed` | T6 (logs), T15 (rate-limit key) |
| `integration/test_auth.py::test_me_returns_only_own_masked_profile` | T7 |
| `integration/test_auth.py::test_five_failures_then_429` | T15 (cuttable) |
| `integration/test_r1_postgres_tools.py::test_foreign_card_refused_and_logged` | T5 |
| `integration/test_r13_ownership.py::test_other_customer_conversation_is_404` | T12 |
| `integration/test_restart.py::test_restart_mid_conversation_continues` | T11 |
| `integration/test_personas.py::test_personas_match_golden` | T9 |

Commands instead of tests: criterion 3 → T8 Verify. Criteria 4, 5 (steps 2–4) and 6 (A5) → T14 Verify plus the verifier's manual run. Criterion 7 (A6) → T14 Verify. `0002` → T2 Verify.

## Human decisions (plan questions)

All four were answered with option A. None changes the spec.

1. **Startup vs. CI:** `backend/tests/unit/test_health.py` becomes `client = TestClient(app)` (no `with`, no lifespan), with the same assertions. D16 and D21 are implemented literally (T11).
2. **Policies in the container:** `docker/docker-compose.dev.yml` mounts `../policies:/policies:ro` on the backend (T14).
3. **Redis in tests:** no key prefix in product code. Tests are isolated by a per-run HMAC key and fresh UUIDs, and delete their own keys (T5, T15).
4. **Error codes:** `{"detail": "<code>"}` via `HTTPException`, `403 csrf_failed`, SSE `error{code: "turn_failed"}` (T6, T7, T11, T12, T15, T16).

## Tasks

- [ ] T1: Dependencies, Settings, `.env.example` and `make fill-secrets`
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "New dependencies" and "Settings", Decisions D8, D21; `backend/app/core/config.py`; `Makefile` (the `setup` and `mcp-setup` targets, for the inline-`python3` style)
  - Acceptance:
    - `cd backend && uv add pyjwt langgraph-checkpoint-postgres "psycopg[binary,pool]"`, and nothing else. `uv.lock` is updated. If the resolver changes the `langgraph` or `langgraph-checkpoint` version, record the old and new versions in the state file.
    - `Settings` gains exactly `app_env: Literal["dev","eval","prod"] = "dev"`, `bank: Literal["fake","postgres"] = "postgres"`, `jwt_secret: str = ""`, `identity_hmac_key: str = ""`, `credentials_seed: str = ""`, `session_ttl_minutes: int = 60`, `login_max_failures: int = 5` and `login_window_seconds: int = 900`. `Settings()` still constructs with no env and no `.env`. Empty secrets are **not** rejected here: the refusal is at app start (T11).
    - `.env.example` gets a commented block: `APP_ENV=dev`, `BANK=postgres`, `JWT_SECRET=`, `IDENTITY_HMAC_KEY=`, `CREDENTIALS_SEED=` (empty, "filled by `make setup`, never committed"), `SESSION_TTL_MINUTES=60`, `LOGIN_MAX_FAILURES=5` and `LOGIN_WINDOW_SECONDS=900`.
    - `Makefile`: a new `fill-secrets` target, added to `.PHONY`, with a `##` help comment. `setup` runs `$(MAKE) fill-secrets` right after `cp -n .env.example .env`. `fill-secrets` is inline stdlib `python3`. For each of `JWT_SECRET`, `IDENTITY_HMAC_KEY` and `CREDENTIALS_SEED`, it appends `KEY=<secrets.token_urlsafe(32)>` when the key is absent from `.env`, fills it in place when the key is present but empty, and leaves it alone when it is non-empty. It prints only the names of the keys it filled, never a value.
  - Verify: `cd backend && uv run python -c "import jwt, psycopg, psycopg_pool; from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver; from app.core.config import Settings; s = Settings(_env_file=None); assert (s.app_env, s.bank, s.jwt_secret, s.session_ttl_minutes, s.login_max_failures, s.login_window_seconds) == ('dev', 'postgres', '', 60, 5, 900)" && uv run ruff check app/core/config.py && uv run ruff format --check app/core/config.py && uv run mypy app/core/config.py && uv run pytest tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py -q && cd .. && make fill-secrets && make fill-secrets && test "$(grep -cE '^(JWT_SECRET|IDENTITY_HMAC_KEY|CREDENTIALS_SEED)=.{20,}$' .env)" = 3 && make up && curl -sf localhost/api/v1/health` (`make up` rebuilds the backend image with the new deps and recreates it with the new `.env` keys. Without it, the hot-reloading container crashes on `import jwt` as soon as later tasks mount new routers)
  - Files: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/config.py`, `.env.example`, `Makefile`

- [ ] T2: Migration `0002` — identity, conversations, messages and the `langgraph` schema
  - Depends on: nothing in code (alembic head is `0001`)
  - Read exactly these: spec §"Contracts" → "Migration `0002`"; `backend/app/alembic/versions/0001_schemas_and_bank.py` (the style to mirror); `docs/solution-docs/03-data-architecture.md` line 61 (Alembic owns every schema's DDL; the checkpointer's tables live in `langgraph`)
  - Acceptance:
    - New `0002_identity_conversations.py`: `revision = "0002"`, `down_revision = "0001"`, and a module docstring that cites the spec and `03` §6.
    - Tables, with columns, nullability and defaults exactly as the spec lists them:
      - `identity.accounts`: `customer_id` is `unique`, with an FK to `bank.customers.customer_id`. `login_key` is `unique not null`. `role` defaults to `'customer'` and `status` to `'active'`.
      - `identity.revoked_tokens(jti text pk, expires_at timestamptz)`.
      - `app.conversations`: defaults `channel 'web'`, `mode 'bot'`, `status 'open'`. Add an index on `customer_id`.
      - `app.messages`: `conversation_id` has an FK to `app.conversations.id` `ON DELETE CASCADE`, `content_masked` is nullable, `ui_payload` is `jsonb` nullable. Add an index on `(conversation_id, created_at)`.
      - `created_at`/`started_at` are `timestamptz` with `server_default now()`. UUID primary keys are generated in code (no server default).
    - `op.execute("CREATE SCHEMA IF NOT EXISTS langgraph")`, with a comment saying the checkpointer's `setup()` creates its tables there (`03` §3).
    - Downgrade drops the indexes and the 4 tables in reverse order, then runs `DROP SCHEMA IF EXISTS langgraph CASCADE`. It leaves `identity`/`app` (they belong to `0001`).
    - No staff columns, no `staff_users` table and no FK from `app.conversations` to anything.
  - Verify: `docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE IF EXISTS latam_mig_check" -c "CREATE DATABASE latam_mig_check" && cd backend && export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check && uv run alembic upgrade head && uv run alembic downgrade 0001 && uv run alembic upgrade head && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from information_schema.tables where table_schema||'.'||table_name in ('identity.accounts','identity.revoked_tokens','app.conversations','app.messages')")" = 4 && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from pg_namespace where nspname='langgraph'")" = 1 && docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE latam_mig_check" && uv run ruff check app/alembic/versions && uv run ruff format --check app/alembic/versions`
  - Files: `backend/app/alembic/versions/0002_identity_conversations.py`

- [ ] T3: Identity primitives — models, document normalization, `login_key`, passwords and JWT
  - Depends on: T1 (`pyjwt`; the `Settings` fields `jwt_secret`, `identity_hmac_key`, `credentials_seed`, `session_ttl_minutes`, as recorded in the state file)
  - Read exactly these: spec Decisions D1, D2, D4, D6, D9 and §"Contracts" → the `/auth/login` row; `docs/solution-docs/04-contracts.md` §3 paragraph "Login and `/me`"; `backend/app/domains/customers/schemas.py` (the model style: frozen pydantic, `__all__`)
  - Acceptance:
    - `identity/models.py`:
      - `DocumentType = Literal["DNI","CC","CE","Pasaporte"]`.
      - `Session` (frozen): `account_id: UUID`, `role: Literal["customer"]`, `customer_id: str`, `step_up_at: datetime | None`.
      - `LoginRequest`: `document_type: DocumentType`, `document_number: str`, `password: str`. There is deliberately **no** length or pattern constraint on `document_number`, so a validation error never echoes it back.
      - `MeResponse`: `role: Literal["customer"]`, `login_hint: str`, `display_name: str`, `country: Literal["MX","CO","AR"]`, `customer_status: Literal["Active","Inactive","Suspended","Closed"]`.
      - No model has a `customer_id` field except `Session`.
    - `identity/passwords.py`:
      - `normalize_document_number(raw)` strips, removes all whitespace, `.` and `-`, uppercases, and keeps leading zeros.
      - `login_key(document_type, document_number, *, hmac_key) -> str` returns the hex HMAC-SHA256 of `f"doc:{document_type}:{normalize_document_number(document_number)}"`. `document_type` is used exactly as its `Literal` value.
      - `login_key_prefix(key) -> str` returns the first 12 hex characters.
      - `generate_password(customer_id, *, seed) -> str` returns the first 12 characters of the base32 of HMAC-SHA256(seed, customer_id). The account key is `customer_id`, the only stable key now that D3 leaves customers as the only accounts. Record this in the state file.
      - `hash_password(password, *, iterations=1000) -> "pbkdf2_sha256$<iter>$<salt_b64>$<hash_b64>"`, with a random 16-byte salt.
      - `verify_password(password, stored) -> bool` uses `hmac.compare_digest` and returns `False` on a malformed hash.
      - Stdlib only.
    - `identity/tokens.py`:
      - Constants `SESSION_COOKIE = "session"`, `CSRF_COOKIE = "csrf_token"`, `CSRF_HEADER = "X-CSRF-Token"`.
      - `TokenClaims` (sub `UUID`, `role`, `customer_id`, `step_up_at`, `jti`, `exp`) with `to_session() -> Session`.
      - `issue_token(session, *, secret, ttl_minutes) -> tuple[str, TokenClaims]` issues HS256 with a uuid4 `jti` and `exp = now + ttl`.
      - `decode_token(token, *, secret) -> TokenClaims` raises `InvalidToken` (defined here) on a bad signature, an expired token or missing claims.
      - `new_csrf_token()` returns `secrets.token_urlsafe(32)`.
    - No module logs anything.
  - Verify: `cd backend && uv run python - <<'EOF'
from uuid import uuid4
from app.domains.identity.passwords import normalize_document_number as n, login_key, hash_password, verify_password, generate_password
from app.domains.identity.tokens import issue_token, decode_token, InvalidToken
from app.domains.identity.models import Session, LoginRequest
assert n(" 12.345-678 ") == "12345678" and n("ab 01") == "AB01" and n("00123") == "00123"
assert login_key("DNI", "12.345.678", hmac_key="k") == login_key("DNI", "12345678", hmac_key="k") != login_key("CC", "12345678", hmac_key="k")
h = hash_password("pw"); assert h.startswith("pbkdf2_sha256$1000$") and verify_password("pw", h) and not verify_password("px", h)
p = generate_password("CLI-X", seed="s"); assert len(p) == 12 and p == generate_password("CLI-X", seed="s")
s = Session(account_id=uuid4(), role="customer", customer_id="CLI-X", step_up_at=None)
tok, claims = issue_token(s, secret="x" * 32, ttl_minutes=60)
assert decode_token(tok, secret="x" * 32).to_session() == s
try: decode_token(tok, secret="y" * 32); raise SystemExit("bad secret accepted")
except InvalidToken: pass
assert "customer_id" not in LoginRequest.model_fields
print("ok")
EOF
uv run ruff check app/domains/identity && uv run ruff format --check app/domains/identity && uv run mypy app/domains/identity`
  - Files: `backend/app/domains/identity/models.py`, `backend/app/domains/identity/passwords.py`, `backend/app/domains/identity/tokens.py`

- [ ] T4: Bank read services — `customers`, `cards`, `transactions` repositories and services
  - Depends on: nothing new (reads `bank.*`, which exists at `0001`; the local `latam_app` is loaded)
  - Read exactly these: `backend/app/domains/conversation/tools/fakebank.py` (the SQL semantics to mirror: country and kind maps, `right(product_number,4)`, debit nulls, own-row-first then single-column probe, the TxFilter conditions, newest first, limit 10); spec Decision D11; `backend/app/core/db.py`
  - Acceptance:
    - Each `repository.py` uses `app.core.db.get_engine()` and `sqlalchemy.text()` with **bound** parameters, never string-formatted values. Every query over customer data has `customer_id = :customer_id`. The one exception is the card existence probe (`SELECT product_type FROM bank.products WHERE product_id = :card_id`), which selects that single column only, as FakeBank's `_probe_card_exists` does. Database errors (`SQLAlchemyError`, `OSError`) become `app.core.errors.ToolUnavailable`.
    - `customers/service.py`:
      - `get_profile(customer_id) -> CustomerProfile` maps `México/Colombia/Argentina` → `MX/CO/AR`. A missing row or unknown country raises `ToolUnavailable`, as FakeBank does.
      - `get_login_profile(customer_id) -> LoginProfile` returns a frozen model defined in `service.py` with `first_name`, `country`, `customer_status`, `document_type` and `document_last3`. `document_last3` is the last 3 characters of the normalized document number, computed in SQL or immediately after the fetch. The full number never leaves the repository function.
    - `cards/service.py`:
      - `list_cards(customer_id) -> list[CardSummary]` returns `Tarjeta Crédito`/`Tarjeta Débito` only, with `locked=False`.
      - `get_card_details(customer_id, card_id) -> CardDetails`: debit cards get `credit_limit`/`interest_rate`/`days_past_due = None`, and `source = "bank.products:<id>"`. An owned non-card product raises `NotFound`. A card id that isn't owned raises `AccessDenied` when the probe finds a card, else `NotFound`.
    - `transactions/service.py`: `search(customer_id, tx_filter) -> list[TxView]` applies every `TxFilter` field exactly as FakeBank's `_build_tx_query` does, with `ORDER BY transaction_date DESC LIMIT 10`. It does not check card ownership itself (`PostgresBank` does that first). It still filters by `customer_id`.
    - No service imports another domain's `repository`. No `conversation` import.
  - Verify: `cd backend && uv run python - <<'EOF'
import asyncio
from app.core.errors import AccessDenied
from app.domains.customers import service as customers
from app.domains.cards import service as cards
from app.domains.transactions import service as transactions
from app.domains.transactions.schemas import TxFilter
async def main() -> None:
    me, other = "CLI-U6NAXZG11P97", "CLI-15CX29YY6SS9"
    assert (await customers.get_profile(me)).country == "MX"
    lp = await customers.get_login_profile(me); assert len(lp.document_last3) == 3
    mine = await cards.list_cards(me); assert sorted(c.kind for c in mine) == ["credit", "debit"]
    await cards.get_card_details(me, mine[0].card_id)
    theirs = await cards.list_cards(other)
    try:
        await cards.get_card_details(me, theirs[0].card_id); raise SystemExit("R1 broken")
    except AccessDenied:
        pass
    assert 0 < len(await transactions.search(me, TxFilter())) <= 10
    print("ok")
asyncio.run(main())
EOF
uv run ruff check app/domains/customers app/domains/cards app/domains/transactions && uv run ruff format --check app/domains/customers app/domains/cards app/domains/transactions && uv run mypy app/domains/customers app/domains/cards app/domains/transactions && uv run lint-imports`
  - Files: `backend/app/domains/customers/repository.py`, `backend/app/domains/customers/service.py`, `backend/app/domains/cards/repository.py`, `backend/app/domains/cards/service.py`, `backend/app/domains/transactions/repository.py`, `backend/app/domains/transactions/service.py`

- [ ] T5: Integration harness, `PostgresBank`, the R1 foreign-card test and `make test-integration`
  - Depends on: T1 (psycopg; Settings), T2 (`0002`), T4 (the three services' function names, from the state file)
  - Read exactly these: spec Decisions D11, D12, D19 and §"Test list" → `test_r1_postgres_tools`; `backend/app/domains/conversation/tools/fakebank.py` (the class shape, `make_fakebank_factory`, the ownership pattern); `backend/tests/unit/test_llm_client.py` (the `capture_logs` pattern)
  - Acceptance:
    - `tests/integration/conftest.py`. Fixtures are **not** autouse, so `test_personas.py` is unaffected.
      - `it_db` (session scope):
        - Skips the test when a 2 s connection to the `postgres` maintenance DB, reached from the host `DATABASE_URL`, fails.
        - Creates `latam_it_<8 hex>` and runs `uv run alembic upgrade head` as a **subprocess** (cwd `backend/`, `DATABASE_URL` set in its env). Never in-process.
        - COPYs `tests/fixtures/fakebank/customers.csv`, `products.csv` and every `transactions/**/*.csv` into `bank.customers`/`bank.products`/`bank.transactions` with psycopg `COPY … (FORMAT csv, HEADER true, NULL '')`. The column list comes from the CSV header, with the BOM stripped.
        - Yields the asyncpg URL. At teardown it drops the DB `WITH (FORCE)`, and refuses to drop any name that doesn't start with `latam_it_`.
      - `it_env` (function scope): monkeypatches `DATABASE_URL` (the throwaway), `APP_ENV=dev`, `BANK=postgres`, and random per-run `JWT_SECRET`/`IDENTITY_HMAC_KEY`/`CREDENTIALS_SEED`. It calls `cache_clear()` on `get_settings`, `get_engine` and `get_redis` before and after.
      - Redis isolation uses no product-code prefix: the per-run `IDENTITY_HMAC_KEY` and fresh UUIDs keep keys unique, and a finalizer deletes the Redis keys the test created (`rl:login:<key>`, `turn:<id>`, `conv:<id>`).
    - `conversation/tools/postgres.py`: `PostgresBank(ctx: ToolContext)` implements `BankReadTools` by calling only `customers.service`, `cards.service` and `transactions.service`.
      - `get_card_details` catches `AccessDenied` from `cards.service` and logs exactly one `structlog` warning `tool.access_denied` with `tool="cards.get_card_details"`, `requested_id=card_id`, `conversation_id=str(ctx.conversation_id)` and `trace_id=ctx.trace_id`, then re-raises.
      - `search_transactions` with `tx_filter.card_id` first checks ownership through `cards.service.get_card_details`. On `AccessDenied` it logs the same event with `tool="transactions.search"` and re-raises. Otherwise it calls `transactions.service.search(ctx.customer_id, tx_filter)`.
      - `make_postgres_factory() -> BankToolsFactory`.
      - Fully typed (mypy strict applies).
    - `tests/integration/test_r1_postgres_tools.py::test_foreign_card_refused_and_logged` (`asyncio.run`, uses `it_db` + `it_env`), with ctx bound to `CLI-TFMULTI00001`:
      - `get_card_details("PRD-TFS2CRED0001")` raises `AccessDenied` and `capture_logs()` holds exactly one `tool.access_denied` with that `requested_id`, the ctx's `conversation_id` and `trace_id`.
      - `search_transactions(TxFilter(card_id="PRD-TFS2CRED0001"))` raises `AccessDenied` with one record where `tool == "transactions.search"`.
      - `get_card_details("PRD-TFM1CRED0001")` returns `kind == "credit"` and `last4 == "6475"`.
    - `Makefile`: a `test-integration` target (`.PHONY`, with a `##` help comment saying "local only, needs `make up`") that runs `cd backend && uv run pytest tests/integration -q`.
  - Verify: `cd backend && uv run pytest tests/integration/test_r1_postgres_tools.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check tests/integration app/domains/conversation/tools/postgres.py && uv run ruff format --check tests/integration app/domains/conversation/tools/postgres.py && uv run mypy app/domains/conversation/tools/postgres.py && uv run lint-imports && test "$(docker exec latam-cs-postgres-1 psql -U postgres -Atc "select count(*) from pg_database where datname like 'latam_it_%'")" = 0`
  - Files: `backend/tests/integration/conftest.py`, `backend/app/domains/conversation/tools/postgres.py`, `backend/tests/integration/test_r1_postgres_tools.py`, `Makefile`

- [ ] T6: Identity repository, service and FastAPI deps, plus the D2 unit test (logs part)
  - Depends on: T2 (tables), T3 (`Session`, `LoginRequest`, `MeResponse`, `login_key`, `login_key_prefix`, `verify_password`, `issue_token`, `decode_token`, `InvalidToken`, cookie/header constants), T4 (`customers.service.get_login_profile`). Real names come from the state file.
  - Read exactly these: spec Decisions D2, D6, D9 and §"Contracts" → "Dependencies"; `docs/solution-docs/04-contracts.md` §3 paragraph "Auth (ADR-025)"; `backend/tests/unit/test_llm_client.py` (the `capture_logs` pattern)
  - Acceptance:
    - `identity/repository.py` (`text()`, bound params): `get_account_by_login_key(login_key)`, `get_account_by_customer_id(customer_id)`, `revoke_token(jti, expires_at)` (insert, on conflict do nothing) and `is_revoked(jti) -> bool`. It returns a small frozen `AccountRow(account_id, role, customer_id, password_hash, status)`.
    - `identity/service.py`:
      - An `AccountStore` Protocol (the repository functions above as methods) with a default implementation over `repository`, so tests inject a fake.
      - `InvalidCredentials` and `SessionExpired` exceptions.
      - `async login(req: LoginRequest, *, store=None, settings=None) -> Session`:
        - Computes `login_key` with `settings.identity_hmac_key`, looks up the account and verifies the password. It requires `status == "active"`.
        - On any failure, it logs `auth.login_failed` with only `login_key_prefix=<12 hex>` and raises `InvalidCredentials` with a constant message.
        - On success, it logs `auth.login_succeeded` with `login_key_prefix` and `account_id`.
        - The raw or normalized document number, the password and the full `login_key` never appear in a log field or exception text.
      - `async me(session) -> MeResponse` uses `customers.service.get_login_profile`. `login_hint = f"{document_type} ••••{document_last3}"`, always four U+2022 bullets. `display_name` is the first name only.
      - `async session_from_token(token) -> tuple[Session, TokenClaims]` decodes the token and checks `is_revoked`. It raises `SessionExpired` on `InvalidToken` or revocation.
      - `async logout(claims)` revokes the `jti` until its `exp`.
      - `async mint_session_for_customer(customer_id) -> Session` is for test-idp. It raises `InvalidCredentials` when there is no account.
    - `identity/deps.py`:
      - `get_session(request) -> Session` reads the `session` cookie and calls `session_from_token`. It stores the claims on `request.state.session_claims`. On a missing, invalid, expired or revoked token it raises 401 `session_expired`.
      - `require_role(*roles)` returns a dependency object that the R13 test can recognize: an instance of a small `RoleGuard` class exposing `.roles`, whose `__call__` depends on `get_session` and raises 403 `forbidden_role`. Record the marker in the state file.
      - `require_csrf(request)`: for any method other than GET/HEAD/OPTIONS, the `X-CSRF-Token` header must equal the `csrf_token` cookie (`hmac.compare_digest`). Otherwise it returns the CSRF error.
      - The error body shape and the CSRF error code are fixed: `HTTPException(status, detail="<code>")` → `{"detail": "<code>"}`, and a CSRF failure is `403 csrf_failed`.
    - `tests/unit/test_login_pii.py::test_document_number_never_logged_or_keyed` (`asyncio.run`, in-file fake `AccountStore` with one account whose document is `CC`/`"DOC-TF-0000001"`, and `Settings(identity_hmac_key="k"*32, _env_file=None)`):
      - A wrong-password login and an unknown-document login both raise `InvalidCredentials`.
      - Across every `capture_logs()` event, no stringified value contains `"DOC-TF-0000001"`, `"DOCTF0000001"`, the password or the full `login_key`.
      - Each failure event carries `login_key_prefix == login_key(...)[:12]`.
      - The module docstring says T15 extends this same test with the rate-limit key assertion.
  - Verify: `cd backend && uv run pytest tests/unit/test_login_pii.py -q && uv run ruff check app/domains/identity tests/unit/test_login_pii.py && uv run ruff format --check app/domains/identity tests/unit/test_login_pii.py && uv run mypy app/domains/identity && uv run lint-imports`
  - Files: `backend/app/domains/identity/repository.py`, `backend/app/domains/identity/service.py`, `backend/app/domains/identity/deps.py`, `backend/tests/unit/test_login_pii.py`

- [ ] T7: Auth routes (`/auth/login`, `/auth/logout`, `/auth/me`) and the A1 integration test
  - Depends on: T6 (`service.login/me/logout`, `InvalidCredentials`, `get_session`, `require_role`, `require_csrf`, error shape), T3 (cookie constants, `issue_token`, `new_csrf_token`), T5 (`it_db`, `it_env` in `tests/integration/conftest.py`). Real names come from the state file.
  - Read exactly these: spec §"Contracts" → the HTTP table rows for `/auth/*` and Decision D6; `backend/app/api/v1/health.py` and `backend/app/api/v1/__init__.py` (router style and mounting); `backend/tests/integration/conftest.py`
  - Acceptance:
    - `api/v1/auth.py` defines two routers:
      - `public_router` (no role): `POST /auth/login` (`LoginRequest` → `200 MeResponse`). It sets the `session` cookie (httpOnly, `SameSite=Lax`, `Secure` only when `app_env == "prod"`, `max_age = session_ttl_minutes*60`, path `/`) and the readable `csrf_token` cookie (same flags, not httpOnly). `InvalidCredentials` → `401 invalid_credentials`.
      - `router` with `dependencies=[Depends(require_role("customer")), Depends(require_csrf)]`: `POST /auth/logout` (revokes the `jti` from `request.state.session_claims`, deletes both cookies, `204`) and `GET /auth/me` (`MeResponse`).
      - No route takes `customer_id`. `/auth/refresh` is **not** here (T16).
    - `api/v1/__init__.py` mounts both routers.
    - `tests/integration/conftest.py` gains:
      - `it_accounts`: inserts `identity.accounts` rows for the three fixture customers, using `login_key` with the per-run `IDENTITY_HMAC_KEY` and `hash_password` of known in-test passwords. It exposes `(document_type, document_number, password)` per customer id.
      - `app_client`: builds `create_app()` **after** `it_env` and yields a `TestClient` used as a context manager.
    - `tests/integration/test_auth.py::test_me_returns_only_own_masked_profile`:
      - Logs in as `CLI-TFMULTI00001` (`CC`, `"DOC-TF0000001"`) → 200 with both cookies.
      - `GET /api/v1/auth/me` returns exactly `{"role": "customer", "login_hint": "CC ••••001", "display_name": "Prueba", "country": "MX", "customer_status": "Active"}`. The raw body contains neither `DOC-TF0000001`, `DOCTF0000001`, `Uno`, `CLI-TFMULTI00001`, nor `CLI-TFSINGLE0002`.
      - A fresh client with no cookie gets `401` with the `session_expired` code.
  - Verify: `cd backend && uv run pytest tests/integration/test_auth.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/api tests/integration && uv run ruff format --check app/api tests/integration && uv run mypy app/api && uv run lint-imports && uv run pytest tests/unit/test_health.py -q`
  - Files: `backend/app/api/v1/auth.py`, `backend/app/api/v1/__init__.py`, `backend/tests/integration/conftest.py`, `backend/tests/integration/test_auth.py`

- [ ] T8: Identity provisioning, `make seed-identity`, and `make data` running it
  - Depends on: T2 (`0002`), T3 (`login_key`, `generate_password`, `hash_password`), T1 (`credentials_seed`, `identity_hmac_key`, `fill-secrets` already run so `.env` has both)
  - Read exactly these: spec Decisions D4, D5, D2 and Success criterion 3; `pipeline/load/__main__.py` (`_psycopg_dsn`, `_run_alembic_upgrade`: the patterns to reimplement, not import); `pipeline/load/demo_reset.py`
  - Acceptance:
    - `python -m app.domains.identity.provision`:
      - Exits non-zero with a message naming only the empty variable(s) when `CREDENTIALS_SEED` or `IDENTITY_HMAC_KEY` is empty.
      - Connects to `latam_golden` (`golden_database_url` with `+asyncpg` removed) with sync psycopg and reads `customer_id, document_type, document_number` from `bank.customers`.
      - In **one** transaction, it runs `TRUNCATE identity.accounts` and COPYs one row per customer: `account_id` = uuid4, `role` = `customer`, `login_key`, a PBKDF2 hash at 1,000 iterations of `generate_password(customer_id)`, `status` = `active`.
      - Writes `data/secrets/credentials.csv` (repo root, parents created, mode `0600`) with header `customer_id,document_type,document_number,password` and the number as stored.
      - Prints only `identity.accounts: <n>` and the export path. No document number or password is printed or logged.
      - Rerunnable: the same passwords come out and the counts are unchanged.
    - `Makefile`:
      - `seed-identity` (`.PHONY`, `##` help) runs, in order: `cd backend && DATABASE_URL=$(GOLDEN_DATABASE_URL) uv run alembic upgrade head`, then `cd backend && uv run python -m app.domains.identity.provision`, then `cd pipeline && uv run python -m load.demo_reset`. Last, it restarts the backend container **only if it is running** (`$(COMPOSE) ps -q backend` non-empty → `$(COMPOSE) restart backend`), because the reset drops the checkpointer tables and kills the backend's pool.
      - `data` runs `$(MAKE) seed-identity` after the existing `ingest && load`.
  - Verify: `make seed-identity 2>&1 | tail -3 && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select count(*)||'|'||count(distinct login_key)||'|'||count(*) filter (where role <> 'customer') from identity.accounts")" = "150000|150000|0" && git check-ignore -q data/secrets/credentials.csv && test "$(head -1 data/secrets/credentials.csv)" = "customer_id,document_type,document_number,password" && test "$(wc -l < data/secrets/credentials.csv)" = 150001 && ! (cd backend && CREDENTIALS_SEED= uv run python -m app.domains.identity.provision) && cd backend && uv run ruff check app/domains/identity/provision.py && uv run ruff format --check app/domains/identity/provision.py && uv run mypy app/domains/identity/provision.py` (allow a timeout of several minutes)
  - Files: `backend/app/domains/identity/provision.py`, `Makefile`

- [ ] T9: Persona catalog (~30) and the local-only persona test
  - Depends on: T1 (psycopg in the backend venv)
  - Read exactly these: `docs/solution-docs/03-data-architecture.md` §8 "Persona catalog" bullet; `eval/personas.yaml`; spec Decision D20
  - Acceptance:
    - `eval/personas.yaml` keeps B's 10 entries unchanged and adds about 20 customer ids found by SQL against `latam_golden`. Together they cover each `03` §8 category at least once:
      - several cards (3 or more), a bank-blocked card, a suspended customer, missing income, a repeat complainer, a regulator case, recent declines per code (05/14/51/54), pending transactions and reversed transactions, expiring cards, each of MX/CO/AR, and a USD-card customer.
      - If a category has no matching customer in the data, the header says so and the state file records it. Don't invent one.
    - A header comment defines the **closed** trait vocabulary. The existing keys stay: `country`, `card_count`, `card_kinds`, `blocked`. Each new key is defined as its SQL meaning, and time-relative traits ("recent", "expiring") are measured from `app.system_metadata.load_date`.
    - Entries hold `customer_id` + traits + optional `notes` only: no names, documents, emails, phones, addresses, card numbers or balances (R10).
    - `backend/tests/integration/test_personas.py::test_personas_match_golden`:
      - Connects to `latam_golden` (the `golden_database_url` setting) itself and skips when it is unreachable. It uses no `conftest` fixture.
      - Asserts at least 28 personas and all 10 original ids present.
      - For every persona and every trait, it runs that trait's predicate SQL (bound params) and asserts it holds. An unknown trait key fails the test.
  - Verify: `cd backend && uv run pytest tests/integration/test_personas.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check tests/integration/test_personas.py && uv run ruff format --check tests/integration/test_personas.py && cd .. && ! grep -niE 'document|email|phone|address|first_name|last_name|product_number' eval/personas.yaml | grep -v '^[0-9]*:\s*#'`
  - Files: `eval/personas.yaml`, `backend/tests/integration/test_personas.py`

- [ ] T10: Conversation store, Redis event bus and tool registry v0
  - Depends on: T2 (tables), T3 (`Session` in `app.domains.identity.models`), T5 (`PostgresBank`/`make_postgres_factory` in `conversation/tools/postgres.py`)
  - Read exactly these: spec Decisions D10, D14 (event names and the channel `conv:<conversation_id>`) and D17; `backend/app/domains/conversation/sandbox.py` (`_RecordingBankTools` and `build_sandbox_session`: the recorder and `ToolContext` construction to mirror, **not** import); `backend/app/core/redis.py`
  - Acceptance:
    - `conversation/store.py` (fully typed, `text()` + bound params, imports only `app.core.db`):
      - `create_conversation(customer_id, language) -> UUID`
      - `get_conversation(conversation_id) -> ConversationRow | None` (frozen: `id, customer_id, language, mode, status`)
      - `add_message(conversation_id, turn_id, role, content, ui_payload=None) -> UUID`, where `content_masked` stays NULL (D17)
      - `list_messages(conversation_id) -> list[MessageRow]` (ordered by `created_at`)
      - The docstring says it is named `store` because import-linter forbids `conversation` → `*.repository`.
    - `app/core/events.py` (strict-typed, no domain imports):
      - `channel(conversation_id) -> "conv:<id>"`.
      - `async publish(conversation_id, event, data)` sends JSON `{"event": …, "data": …}`.
      - `subscribe(conversation_id)` is an async context manager. It is subscribed when entered, yields an async iterator of `(event, data)`, and unsubscribes and closes its pubsub on exit.
    - `conversation/tools/registry.py`:
      - `build_tool_context(session: Session, conversation_id: UUID, trace_id: str) -> ToolContext`, with `customer_id=session.customer_id`, `actor="customer"`, `policy_version="unversioned"`. The docstring says nothing else on the API path constructs a `ToolContext` (R1).
      - `RecordingBankTools(inner)` has a public `.calls: list[str]` and the 4 `BankReadTools` methods.
      - `bank_tools_for(ctx) -> RecordingBankTools` wraps `PostgresBank(ctx)` when `get_settings().bank == "postgres"`, or `FakeBank(ctx, <repo root>/data)` when it is `"fake"`.
      - No `ToolSpec`, allowlist or write tools.
  - Verify: `cd backend && BANK=fake uv run python - <<'EOF'
from uuid import uuid4
from app.domains.identity.models import Session
from app.domains.conversation.tools.registry import build_tool_context, bank_tools_for
from app.domains.conversation.tools.fakebank import FakeBank
import app.domains.conversation.store, app.core.events
s = Session(account_id=uuid4(), role="customer", customer_id="CLI-X", step_up_at=None)
cid = uuid4(); ctx = build_tool_context(s, cid, "trace-1")
assert (ctx.customer_id, ctx.conversation_id, ctx.actor, ctx.policy_version, ctx.trace_id) == ("CLI-X", cid, "customer", "unversioned", "trace-1")
tools = bank_tools_for(ctx); assert tools.calls == [] and isinstance(tools._inner, FakeBank)
print("ok")
EOF
uv run ruff check app/core/events.py app/domains/conversation/store.py app/domains/conversation/tools/registry.py && uv run ruff format --check app/core/events.py app/domains/conversation/store.py app/domains/conversation/tools/registry.py && uv run mypy app/core/events.py app/domains/conversation/store.py app/domains/conversation/tools/registry.py && uv run lint-imports` (if the recorder's inner attribute has another name, use it and record it in the state file)
  - Files: `backend/app/domains/conversation/store.py`, `backend/app/core/events.py`, `backend/app/domains/conversation/tools/registry.py`

- [ ] T11: Hosting (Postgres checkpointer), the turn runner, the app lifespan and the A4 restart test
  - Depends on: T10 (`store`, `app.core.events`, `registry.build_tool_context`/`bank_tools_for`), T5 (`it_db`, `it_env`), T1 (checkpointer deps; `app_env`, `jwt_secret`, `identity_hmac_key`). Real names come from the state file.
  - Read exactly these: spec Decisions D13–D16, D21 and §"Test list" → `test_restart`; `backend/app/domains/conversation/graph.py` (`build_graph`, `run_turn`, `DebugInfo`: the `astream` loop and debug assembly to mirror); `backend/tests/unit/test_sandbox_conversations.py::test_es_multi_card_asks_then_answers` (the ScriptedLLM script)
  - Acceptance:
    - `conversation/hosting.py`:
      - `psycopg_conninfo(database_url)` removes `+asyncpg`.
      - `TurnHost` holds the `graph`, `pool`, `llm` and `tasks: set[asyncio.Task[None]]`.
      - `async open_host(database_url, llm) -> TurnHost` builds a `psycopg_pool.AsyncConnectionPool(conninfo, open=False, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row, "options": "-c search_path=langgraph"})`, awaits `pool.open()`, creates `AsyncPostgresSaver(pool)`, awaits `saver.setup()`, then runs `build_graph(saver)`.
      - `async close_host(host)` cancels and awaits pending tasks, then closes the pool.
    - `conversation/runner.py`:
      - `TurnInProgress`.
      - `async start_turn(host, *, session, conversation_id, text, trace_id) -> UUID`:
        - Takes the lock first: `SET turn:<conversation_id> <turn_id> NX EX 120`. If the key is taken it raises `TurnInProgress` with nothing persisted.
        - Then persists the customer message (`role="customer"`, `turn_id`), schedules the turn task in `host.tasks` (discarded on completion), and returns `turn_id`.
      - The turn task:
        - Builds the `ToolContext` and bank tools **only** through the registry. The config is `{"configurable": {"thread_id": str(conversation_id), "session": ctx, "bank_tools": tools, "llm": host.llm, "bank_write_tools": None}}` (D13).
        - Runs `host.graph.astream({"user_text": text, "confirmation": None}, config=config, stream_mode="updates")`. It publishes `status {"step": <node>}` per node update and collects `ui`, `nlu`/`language`, the route and `reply` exactly as `run_turn` does.
        - Then, in order:
          1. It publishes one `ui` per `UIEvent` (`model_dump(mode="json")`).
          2. It persists the bot message (`role="bot"`, `content=reply`, `ui_payload` = the dumped list, or `None` when empty).
          3. It publishes `message {"role": "bot", "text": reply, "sources": []}`.
          4. When `app_env != "prod"`, it publishes `debug` (`DebugInfo` built as in `run_turn`, `tools_called` = `tools.calls`).
          5. It publishes `done {"turn_id"}`.
        - On any exception it logs `turn.failed` (no user text) and publishes `error {"code": "turn_failed"}` then `done`.
        - In `finally`, it deletes the lock only if its value is still this `turn_id`.
      - No write tools and no `graph.py` edit.
    - `app/main.py`:
      - `FastAPI(openapi_url="/api/v1/openapi.json", docs_url="/api/v1/docs", lifespan=…)`.
      - The lifespan raises at startup when `jwt_secret` or `identity_hmac_key` is empty, naming only the variables (D21). It opens `app.state.turn_host = await open_host(settings.database_url, get_llm_client())` and closes it on shutdown (D16).
      - `tests/unit/test_health.py` changes `with TestClient(app) as client:` to `client = TestClient(app)` (no lifespan, as its docstring already says). Its assertions stay unchanged, so it passes with no `.env` and no Postgres.
    - `tests/integration/test_restart.py::test_restart_mid_conversation_continues` (one `asyncio.run`, `it_db` + `it_env`, `ScriptedLLM` only):
      1. It creates a conversation for `CLI-TFMULTI00001` through `store` and a `Session` for that customer.
      2. It builds `host1` with a ScriptedLLM of `nlu=[card_status, no hint]` and `compose=[the "which card" draft]`, subscribes to the conversation's events, calls `start_turn("hola, cual es el estado de mi tarjeta?")`, and collects events until `done`. It asserts at least one `status`, one `message`, a `debug` with `route == "card_info"`, and `done` with the returned `turn_id`, in that order.
      3. It runs `close_host(host1)`.
      4. It builds `host2` with a fresh ScriptedLLM (`nlu=[card_status, card_hint="credit"]`, `compose=[the answer draft]`). It asserts `(await host2.graph.aget_state({"configurable": {"thread_id": str(cid)}})).values["pending"]["awaiting_slot"] == "card_hint"`.
      5. It runs `start_turn("la de credito")` and asserts the `message` text contains `"6475"`, then asserts that `store.list_messages` returns 4 rows with roles `customer, bot, customer, bot`.
      6. Assert on `"6475"`, not the full formatted sentence, because B's D2 formatting work may change it.
  - Verify: `cd backend && uv run pytest tests/integration/test_restart.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && env JWT_SECRET= IDENTITY_HMAC_KEY= DATABASE_URL=postgresql+asyncpg://nobody:x@127.0.0.1:1/none uv run pytest tests/unit/test_health.py -q && uv run ruff check app/main.py app/domains/conversation tests/integration tests/unit/test_health.py && uv run ruff format --check app/main.py app/domains/conversation tests/integration tests/unit/test_health.py && uv run mypy app/main.py app/domains/conversation && uv run lint-imports`
  - Files: `backend/app/domains/conversation/hosting.py`, `backend/app/domains/conversation/runner.py`, `backend/app/main.py`, `backend/tests/integration/test_restart.py`, `backend/tests/unit/test_health.py`

- [ ] T12: Conversation routes, `get_owned_conversation` and the R13 ownership integration test
  - Depends on: T11 (`runner.start_turn`, `TurnInProgress`, `app.state.turn_host`), T10 (`store`, `app.core.events.subscribe`), T6 (`get_session`, `require_role`, `require_csrf`, error shape), T7 (`it_accounts`, `app_client` fixtures). Real names come from the state file.
  - Read exactly these: spec Decisions D14, D18 and §"Contracts" → the three `/conversations` rows; `docs/solution-docs/04-contracts.md` §3 paragraphs "Auth (ADR-025)" and "SSE events"; `backend/app/api/v1/auth.py` (router style as built)
  - Acceptance:
    - `conversation/deps.py`: `get_owned_conversation(conversation_id: UUID, session = Depends(get_session)) -> ConversationRow`. It returns `404 not_found` with the same body whether the row is missing or belongs to another customer.
    - `api/v1/conversations.py`: `router = APIRouter(prefix="/conversations", dependencies=[Depends(require_role("customer")), Depends(require_csrf)])`.
      - `POST ""`: body `{language?: "es" | "pt"}` → `201 {conversation_id}`. The customer comes from the session only.
      - `POST "/{conversation_id}/messages"`: depends on `get_owned_conversation`, body `{text: str, 1–2000 chars}` → `202 {turn_id}` via `start_turn(request.app.state.turn_host, …, trace_id=get_trace_id())`. `TurnInProgress` → `409 turn_in_progress`.
      - `GET "/{conversation_id}/stream"`: depends on `get_owned_conversation`. It enters `events.subscribe(...)` **before** returning a `StreamingResponse(media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`. The generator first yields `: connected\n\n`, then `event: <name>\ndata: <json>\n\n` per event, and `: ping\n\n` after 15 s without one. It stops and unsubscribes on client disconnect.
      - Customer-only (D18). No body, query or path field is named `customer_id`.
    - `api/v1/__init__.py` mounts the router.
    - `tests/integration/test_r13_ownership.py::test_other_customer_conversation_is_404`:
      - Customer A (`CLI-TFMULTI00001`) logs in and creates a conversation.
      - Customer B (`CLI-TFSINGLE0002`) logs in with a separate client. `POST …/messages` on A's id, with B's own CSRF header, returns 404, and `GET …/stream` on A's id returns 404.
      - A random UUID gives the same 404 body.
      - No turn runs (no LLM).
  - Verify: `cd backend && uv run pytest tests/integration/test_r13_ownership.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/api app/domains/conversation/deps.py tests/integration/test_r13_ownership.py && uv run ruff format --check app/api app/domains/conversation/deps.py tests/integration/test_r13_ownership.py && uv run mypy app/api app/domains/conversation/deps.py && uv run lint-imports`
  - Files: `backend/app/domains/conversation/deps.py`, `backend/app/api/v1/conversations.py`, `backend/app/api/v1/__init__.py`, `backend/tests/integration/test_r13_ownership.py`

- [ ] T13: Eval-only `/test-idp/sessions` and the R1/R13 route-introspection unit tests
  - Depends on: T7 and T12 (every router mounted), T6 (the `RoleGuard` marker, `service.mint_session_for_customer`), T11 (`create_app()` with lifespan). Real names come from the state file.
  - Read exactly these: spec Decisions D8, D6 (CSRF exemption) and §"Test list" → `test_r1_routes`, `test_r13_routes`; `backend/app/main.py`; `backend/app/api/v1/auth.py` (cookie setting as built)
  - Acceptance:
    - `api/v1/test_idp.py`: `POST /test-idp/sessions` with body `{customer_id: str}`. It calls `mint_session_for_customer`, sets the same cookies as login and returns `MeResponse`. An unknown customer → `404 not_found`. It is CSRF-exempt, and its docstring says it is the one route that takes a `customer_id`, eval only (ADR-025).
    - `create_app()` includes it under `/api/v1` **only** when `get_settings().app_env == "eval"`.
    - `tests/unit/test_r1_routes.py::test_no_route_accepts_customer_id`:
      - Sets `APP_ENV=dev` (monkeypatch + `get_settings.cache_clear()`) and calls `create_app()` with no `TestClient` and no lifespan.
      - For every `APIRoute`, it walks `route.dependant` recursively (path, query, header, cookie and body params of the route and of every sub-dependency) and the fields of every body model, recursing into nested pydantic models. It asserts none is named `customer_id`.
      - Asserts no path starts with `/api/v1/test-idp`, and that `/api/v1/auth/login` and `/api/v1/conversations/{conversation_id}/messages` exist.
      - Non-vacuity: with `APP_ENV=eval`, the same walker flags `/api/v1/test-idp/sessions`.
    - `tests/unit/test_r13_routes.py::test_every_route_declares_role_and_ownership`:
      - Uses `create_app()` in dev.
      - Every `APIRoute` except `/api/v1/health`, `/api/v1/auth/login` and `/api/v1/auth/refresh` has a `RoleGuard` among `route.dependencies`.
      - Every route whose path starts with `/api/v1/conversations/{conversation_id}` has `get_owned_conversation` somewhere in its dependant tree, and at least 2 such routes exist.
    - Both tests pass with no Postgres, no Redis and no `.env` secrets.
  - Verify: `cd backend && env JWT_SECRET= IDENTITY_HMAC_KEY= uv run pytest tests/unit/test_r1_routes.py tests/unit/test_r13_routes.py -q && APP_ENV=eval uv run python -c "from app.main import create_app; assert any(getattr(r, 'path', '') == '/api/v1/test-idp/sessions' for r in create_app().routes)" && uv run ruff check app/api app/main.py tests/unit/test_r1_routes.py tests/unit/test_r13_routes.py && uv run ruff format --check app/api app/main.py tests/unit/test_r1_routes.py tests/unit/test_r13_routes.py && uv run mypy app/api app/main.py && uv run lint-imports`
  - Files: `backend/app/api/v1/test_idp.py`, `backend/app/main.py`, `backend/tests/unit/test_r1_routes.py`, `backend/tests/unit/test_r13_routes.py`

- [ ] T14: `make chat-api`, `make client` regeneration, and the live end-of-day checks
  - Depends on: T8 (accounts seeded, `data/secrets/credentials.csv`), T12 (routes, `: connected` first line, SSE event format), T7 (login cookies), T11 (`/api/v1/docs`).
  - Read exactly these: spec Decisions D8, D14, D15 and Success criteria 4–7; `backend/app/domains/conversation/sandbox.py` (the debug-line format and `_force_utf8_streams` to mirror); `docker/docker-compose.dev.yml`
  - Acceptance:
    - `backend/scripts/chat_api.py` (`python scripts/chat_api.py --persona <customer_id> [--base-url http://localhost]`, httpx):
      - Reads the persona's row from `<repo root>/data/secrets/credentials.csv`. If the row is missing it says to run `make seed-identity`.
      - Logs in through `POST /api/v1/auth/login` (the document and password are never printed), then `POST /api/v1/conversations`.
      - For each non-empty stdin line, it opens `GET …/stream`, waits for `: connected`, then `POST …/messages` with `X-CSRF-Token` from the `csrf_token` cookie. It prints events until `done`:
        - `status <step>`
        - `bot: <text>`
        - `ui <kind>`
        - `debug language=… status=… intents=[…] slots={…} route=… tools=[…]` (the sandbox's format)
        - `error <code>`
        - A 409 prints `turn in progress`.
      - UTF-8 stdout/stdin as in the sandbox.
    - `Makefile`: `chat-api` (`.PHONY`, `##` help) runs `@test -n "$(PERSONA)" || (echo "Usage: make chat-api PERSONA=<customer_id>" && exit 1)` then `cd backend && uv run python scripts/chat_api.py --persona "$(PERSONA)"`.
    - `docker/docker-compose.dev.yml` backend volumes gain `- ../policies:/policies:ro`, with a comment explaining that `card_select` resolves the repo root to `/` in the container.
    - `make up` rebuilds and recreates the stack. `make client` regenerates `frontend/src/client` with the auth and conversation operations. Nothing in it is hand-edited.
  - Verify: `make up && curl -sf localhost/api/v1/health && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/docs)" = 200 && make client && git diff --stat -- frontend/src/client && grep -qi 'conversations' frontend/src/client/sdk.gen.ts && grep -qi 'login' frontend/src/client/sdk.gen.ts && printf '¿cuánto debo de mi tarjeta de crédito?\nquanto devo no meu cartão de crédito?\n' | make chat-api PERSONA=CLI-U6NAXZG11P97 | tee /dev/stderr | grep -c 'route=card_info' | grep -qx 2 && test "$(docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml logs backend 2>&1 | grep -c "$(grep '^CLI-U6NAXZG11P97,' data/secrets/credentials.csv | cut -d, -f3)")" = 0 && cd backend && uv run ruff check scripts/chat_api.py && uv run ruff format --check scripts/chat_api.py`. This uses the real LLM (`ANTHROPIC_API_KEY` is set locally). It is a manual end-of-day check, not a test. The verifier also runs steps 3 and 4 by hand: a foreign last 4, and `docker compose restart backend` between two turns. It also runs the A5 comparison against `make chat-sandbox CUSTOMER=CLI-U6NAXZG11P97`.
  - Files: `backend/scripts/chat_api.py`, `Makefile`, `docker/docker-compose.dev.yml`, `frontend/src/client/` (generated)

- [ ] T15: Login rate limit (cuttable to D3) and its tests
  - Depends on: T6 (`service.login`, `InvalidCredentials`, the `test_login_pii.py` test function), T7 (`api/v1/auth.py` login route, `tests/integration/test_auth.py`, `it_accounts`/`app_client`), T1 (`login_max_failures`, `login_window_seconds`). Real names come from the state file.
  - Read exactly these: spec Decisions D7, D2 and §"Test list" → `test_five_failures_then_429` and `test_login_pii`; `backend/app/domains/identity/service.py`; `backend/tests/unit/test_login_pii.py`
  - Acceptance:
    - `identity/service.py`: a `LoginLimiter` Protocol plus a Redis implementation (`app.core.redis.get_redis()`), injected into `login(...)` like the store. The key is exactly `rl:login:<full login_key>`, with no prefix.
      - Before verifying: if the count is `>= login_max_failures`, raise `TooManyAttempts`, even with the right password.
      - On every failure, including an unknown identifier: `INCR`, and on the first increment `EXPIRE login_window_seconds`, then raise `InvalidCredentials`.
      - A success doesn't reset the counter.
      - Log `auth.login_throttled` with `login_key_prefix` only.
    - `api/v1/auth.py`: `TooManyAttempts` → `429 too_many_attempts`.
    - `test_login_pii.py::test_document_number_never_logged_or_keyed` (the same function, extended) uses an in-file fake limiter that records keys. The recorded key equals `f"rl:login:{login_key(...)}"` and contains neither the raw nor the normalized document number.
    - `tests/integration/test_auth.py::test_five_failures_then_429`: 5 wrong passwords for `CLI-TFSINGLE0002` give `401 invalid_credentials` ×5, and a 6th attempt with the **right** password gives `429 too_many_attempts`.
  - Verify: `cd backend && uv run pytest tests/unit/test_login_pii.py -q && uv run pytest tests/integration/test_auth.py -q -rs 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/domains/identity app/api tests/unit/test_login_pii.py tests/integration/test_auth.py && uv run ruff format --check app/domains/identity app/api tests/unit/test_login_pii.py tests/integration/test_auth.py && uv run mypy app/domains/identity app/api`
  - Files: `backend/app/domains/identity/service.py`, `backend/app/api/v1/auth.py`, `backend/tests/unit/test_login_pii.py`, `backend/tests/integration/test_auth.py`

- [ ] T16: `POST /auth/refresh` (cuttable to D3)
  - Depends on: T6 (`session_from_token`, `require_csrf`, error shape), T7 (`public_router` and the cookie-setting helper in `api/v1/auth.py`), T3 (`issue_token`, `new_csrf_token`), T13 (the R13 test already exempts `/api/v1/auth/refresh`), T8 (credentials export, for the live check). Real names come from the state file.
  - Read exactly these: spec Decision D6 (refresh bullet) and §"Contracts" → the `/auth/refresh` row; `backend/app/api/v1/auth.py`; `backend/app/domains/identity/service.py`
  - Acceptance:
    - `identity/service.py`: `async refresh(token) -> tuple[Session, str, TokenClaims]` re-issues a token (new `jti`, new `exp`) when the current one is valid and not revoked. Otherwise it raises `SessionExpired`. The spec doesn't say to revoke the old `jti`, so this task doesn't.
    - `api/v1/auth.py`: `POST /auth/refresh` goes on `public_router` with `dependencies=[Depends(require_csrf)]`. It reads the `session` cookie and sets new `session` and `csrf_token` cookies → `200 MeResponse`. `SessionExpired` → `401 session_expired`. No role dependency, which matches the spec's "public (needs a valid cookie + CSRF)".
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py -q && uv run ruff check app/domains/identity app/api && uv run ruff format --check app/domains/identity app/api && uv run mypy app/domains/identity app/api && cd .. && jar=$(mktemp) && IFS=, read -r _ t n p < <(grep '^CLI-U6NAXZG11P97,' data/secrets/credentials.csv) && test "$(curl -s -c "$jar" -o /dev/null -w '%{http_code}' -H 'content-type: application/json' -d "{\"document_type\":\"$t\",\"document_number\":\"$n\",\"password\":\"$p\"}" localhost/api/v1/auth/login)" = 200 && csrf=$(awk '$6=="csrf_token"{print $7}' "$jar") && test "$(curl -s -b "$jar" -c "$jar" -o /dev/null -w '%{http_code}' -X POST -H "X-CSRF-Token: $csrf" localhost/api/v1/auth/refresh)" = 200 && test "$(curl -s -b "$jar" -o /dev/null -w '%{http_code}' -X POST localhost/api/v1/auth/refresh)" != 200 && rm -f "$jar"`
  - Files: `backend/app/domains/identity/service.py`, `backend/app/api/v1/auth.py`
