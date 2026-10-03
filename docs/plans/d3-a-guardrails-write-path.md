# Plan: D3-A — G6a guardrails and moving the write path

Spec: [`docs/specs/d3-a-guardrails-write-path.md`](../specs/d3-a-guardrails-write-path.md) · Branch: `feat/d3-a-guardrails-write-path`

Human decisions at the spec gate (the spec's three open items, all taken as the spec's defaults):
- (1) An audit insert that fails after a raw write has run is logged as `audit.write_failed` and the verified result is kept (D15, second half).
- (2) A button confirmation is not persisted as a customer message. The `confirmation_used` audit event records it.
- (3) `card_controls.idempotency_key` holding only the last write's key is accepted.

Execution model (human requirement): Sonnet implementers. Tasks in the same wave run **in parallel in the same checkout**. Inside a wave no two tasks edit the same file, and no task's Verify depends on another same-wave task's output. Waves run in order: W1 → W2 → W3 → W4 → W5. A shared checkout means a sibling's half-finished edit can make your Verify fail on a file your task doesn't own. When that happens, wait for the sibling to finish and rerun. Never edit another same-wave task's file.

## Facts checked against the repo

**Baseline on this branch (`2dd439d`, stack up):**
- `cd backend && uv run pytest tests/unit -q` → 55 passed.
- `uv run lint-imports` → 4 contracts kept.
- `uv run mypy app` → clean, 98 files.
- A new red belongs to the task that caused it.

**Commands and conventions (from D2-A/D2-B state files; still true):**
- Commands run as `cd backend && uv run …`.
- There is no pytest-asyncio. Drive coroutines with `asyncio.run(...)`.
- `get_settings()`, `get_engine()` and `get_redis()` are `lru_cache`d and bound to their event loop. `cache_clear()` all three whenever a test switches DB or loop, including between a test's own `asyncio.run` and a `TestClient` request.
- Alembic always runs as a subprocess with `DATABASE_URL` in its env, never in-process.
- Integration tests use `it_env`/`it_db`/`it_accounts`/`app_client` from `backend/tests/integration/conftest.py`. `it_db` is **session-scoped**: every integration test file in one pytest run shares one migrated DB.
- An integration Verify must fail on a skip: pipe pytest through `tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in'`.
- Errors are `HTTPException(status, detail="<code>")`. FastAPI dependencies use the `Annotated[X, Depends(...)]` style.
- Tests always use `ScriptedLLM` (`backend/tests/conftest.py`), never a real provider.

**mypy and import-linter:**
- mypy strict covers `app.core.*`, `app.domains.conversation.*` and `app.domains.policy.*` (`backend/pyproject.toml`).
- import-linter is version 2.15. The `conversation-no-repository` contract has **no** `unmatched_ignore_imports_alerting` line, so it defaults to `error`: an `ignore_imports` edge whose import doesn't exist yet fails `lint-imports`. **Every new ignore edge lands in the same task that creates the import.**
- The forbidden pattern `app.domains.*.repository` also matches `app.domains.audit.repository`.

**Database:**
- `latam_app` and `latam_golden` are both at alembic `0002`.
- `0001` already creates schemas `bank`, `app`, `identity` and `audit`.
- Migration files are `backend/app/alembic/versions/0001_schemas_and_bank.py` and `0002_identity_conversations.py`, with string revision ids `"0001"`/`"0002"`.
- The Postgres container is `latam-cs-postgres-1`.
- D2-A T2's migration Verify pattern: create `latam_mig_check`, upgrade head, downgrade, upgrade, count tables, drop.

**Redis:**
- The container is `latam-cs-redis-1`, Redis 7.4.11, so `KEEPTTL` and Lua `cjson` are available.
- The integration conftest deletes the key patterns in `_REDIS_KEY_PATTERNS = ("rl:login:*", "turn:*", "conv:*")` after each test.

**Settings (`app/core/config.py`) already has:**
- `demo_otp_code` (default `""`)
- `bank: Literal["fake","postgres"]`
- `login_max_failures=5`, `login_window_seconds=900`
- `session_ttl_minutes=60`

The local `.env` has non-empty `DEMO_OTP_CODE` and `ANTHROPIC_API_KEY`. Never print them. `data/secrets/credentials.csv` exists.

**Policy loaders:**
- `policy/tools_policy.py` (`ToolPolicy`, `ToolsPolicy`, `load_tools_policy`, `step_up_rule`), `policy/escalation.py` and `policy/min_payment.py`.
- `conversation/flows/card_select.py` has `CardSelectPolicy` and `load_card_select_policy`.
- All use `provenance: str` today and resolve `_REPO_ROOT = Path(__file__).resolve().parents[4]`. In the container that is `/`, and dev compose mounts `../policies:/policies:ro`.
- `policies/` holds `card_select.yaml`, `escalation.yaml`, `min_payment.yaml` and `tools.yaml`.

**Lifespan (`app/main.py` `_lifespan`):** `_require_secrets` → `open_host` → yield → `close_host`. `tests/unit/test_health.py` builds `TestClient(app)` without `with`, so it never runs the lifespan.

**Identity:**
- `Session{account_id, role, customer_id, step_up_at}` (`identity/models.py`).
- `TokenClaims` already carries `step_up_at` round-trip (`identity/tokens.py`).
- `identity/service.py` has `LoginLimiter` (Protocol), `_RedisLoginLimiter` (`get_failures`/`record_failure(key, window_seconds=)`) and `TooManyAttempts`.
- `api/v1/auth.py` has `router` (role + CSRF at router level), `public_router` and `_set_auth_cookies`. `/auth/refresh` is the re-issue pattern to mirror.
- `identity/step_up.py` has `StepUpGate` (Protocol, `is_step_up_valid()`). `identity/step_up_fake.py` has `FakeStepUpGate`.

**Write contracts (D2-K/D2-B):**
- `conversation/tools/write.py` has the `BankWriteTools` Protocol with no `idempotency_key` yet.
- `conversation/tools/executor.py`:
  - `ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up)`.
  - `issue_plan(steps)` and `get_block_origin(card_id)` take no intent yet.
  - `_run` ignores `consume_step`'s returned index.
- `policy/confirmation.py` has `ConfirmationStore`, `ConfirmationPlan`, `PlanStep` and `args_hash`. `policy/confirmation_memory.py` has `InMemoryConfirmationStore`.
- `core/errors.py` has `PolicyDenied(reason_code)`, `StepUpRequired`, `ConfirmationRequired(reason)`, `ToolUnavailable` and `AccessDenied`.
- `core/actions.py` has `ActionResult` (frozen), with `audit_event_id: UUID | None = None`.

**Implementers of the raw `BankWriteTools` shape (all change when D11 adds `idempotency_key`):**
- `FakeBankWrites` (`tools/fakebank.py` ~L336-416; `FakeBankOverlay` ~L55-67).
- `sandbox._RecordingWriteTools` (`conversation/sandbox.py` ~L102-131).
- `_StubRawWrites` (`tests/unit/test_r2_confirmed_writes.py`).
- `_UnverifiedLockWrites` (`tests/unit/test_r3_flows.py`).

Direct `FakeBankWrites` write callers are `tests/unit/test_r1_fakebank.py` and `tests/unit/test_fakebank_writes.py`.

**`ConfirmedWriteTools` constructor callers:**
- `conversation/sandbox.py` ~L190
- `tests/conftest.py` `make_session` ~L141
- `tests/unit/test_r2_confirmed_writes.py` (4 sites)

**Flow call sites that gain `intent`:**
- `flows/actions.py` `start_plan` (~L68, calls `issue_plan` ~L85).
- `flows/card_block.py` `start_plan(` ~L224 → `"card_block"`.
- `flows/card_unlock.py` `get_block_origin(` ~L144 and `start_plan(` ~L212 → `"card_unlock"`.
- `flows/replacement.py` `get_block_origin(` ~L169 and `start_plan(` ~L263 → `"replacement_request"`.
- `Intent` is `app.domains.conversation.schemas.Intent`. It contains all three values.

**Runner and hosting:**
- `conversation/runner.py` `start_turn(host, *, session, conversation_id, text, trace_id)` persists the customer message, then schedules `_run_turn`.
- `_run_turn` builds `ctx` via `registry.build_tool_context` and `tools` via `registry.bank_tools_for(ctx)`, and passes `"bank_write_tools": None`. It has no `vault` key.
- `test_restart.py` calls `start_turn(..., text=..., trace_id=...)` by keyword.
- `TurnHost` (`conversation/hosting.py`) is a **mutable** `@dataclass` with `.graph`, `.pool`, `.llm` and `.tasks`, so a test can swap `app.state.turn_host.llm` for a `ScriptedLLM` after the lifespan starts.
- `ConfirmationDecision{token_id, decision}` and `TurnInput{user_text, confirmation?, resume?}` live in `conversation/graph.py`. The checkpointed plan id is `TurnState.confirmation_token_id`. Read it with `await host.graph.aget_state({"configurable": {"thread_id": str(conversation_id)}})` → `.values.get("confirmation_token_id")`.

**Registry (`conversation/tools/registry.py`):**
- `build_tool_context` sets `policy_version="unversioned"`.
- `RecordingBankTools(inner)` wraps five reads.
- `bank_tools_for(ctx)` picks `FakeBank(ctx, _DATA_DIR)` or `PostgresBank(ctx)` from `get_settings().bank`.
- `make_fakebank_factory(data_dir)` returns a read/write factory pair sharing one overlay.

**Postgres reads:**
- `conversation/tools/postgres.py` `PostgresBank(ctx)` has `get_profile`, `list_cards` and `get_card_details`. `get_card_details` raises `AccessDenied` on a foreign card and logs `tool.access_denied`.
- `cards/service.py`:
  - `list_cards` and `get_card_details` hard-code `locked=False`.
  - Uses `repository.fetch_cards`, `fetch_card_details` and `fetch_card_probe`.
  - `repository._fetch_rows` wraps `SQLAlchemyError`/`OSError` into `ToolUnavailable`.
- `.importlinter` already ignores `conversation.tools.postgres -> {customers,cards,transactions,localization}.service`.

**Integration fixture customers and cards (`tests/fixtures/fakebank/README.md`):**

| Customer | Cards |
|---|---|
| `CLI-TFMULTI00001` (MX) | `PRD-TFM1CRED0001` credit, Active, last4 6475; `PRD-TFM1DEBT0002` debit, Active; `PRD-TFM1DEBT0003` debit, Closed; `PRD-TFM1SAVE0004` (not a card) |
| `CLI-TFSINGLE0002` (CO) | `PRD-TFS2CRED0001` |
| `CLI-TFBLOCKD0003` (AR) | `PRD-TFB3DEBT0001` debit, **Blocked** |

- `it_accounts` logs in only these three.
- `CLI-TFINACT00004` and `CLI-TFPASTD00005` exist in the fixture CSVs but have no `it_accounts` login.
- The unit test `test_block_flows.py` holds the scripted-NLU sequences for lock, block, replacement, new-address OTP and unlock OTP. It is the analogue for the API end-to-end test.

**Other facts:**
- `app.messages` has columns `(id, conversation_id, turn_id, role, content, content_masked, ui_payload jsonb, created_at)`. The bot row's `ui_payload` holds the `ui.confirm` event, with `payload.token_id`.
- **`TurnState` records no template kinds.** The runner sees only `reply`, `ui`, the route and `escalation_reason`. See Open question Q1 (affects only T11's `reply_sent` payload).
- Makefile targets that exist: `check`, `test`, `test-integration`, `seed-identity` (alembic on golden → provision → demo-reset → restart backend if running), `chat-api PERSONA=`, `client`.
- `COMPOSE := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml`.
- The frontend has a generated client in `frontend/src/client/`, regenerated by `make client` against the running backend. `make check` ends with `npx biome ci .` in `frontend/`.
- `docs/solution-docs/decision-log.md` L182 is the deferred row "Step-up validity window …". `03-data-architecture.md` L75-77 hold the three app-table rows.

## Components

| Component | Where | Depends on |
|---|---|---|
| Policy registry (`PolicyBundle`, `load_policies`, `get_policies`, `PolicyLoadError`) | `backend/app/domains/policy/registry.py` (new) | the three policy-domain loaders; a header-only model for any other stem |
| `tools.yaml` v1 + `ToolPolicy.allowed_intents`, `ToolsPolicy.step_up_window_minutes`, `tool_allowed()` | `policies/tools.yaml`, `backend/app/domains/policy/tools_policy.py` | — |
| `RedisConfirmationStore` (+ `is_open`) | `backend/app/domains/policy/confirmation_redis.py` (new) | `policy/confirmation.py`, `core/redis.py` |
| Migrations `0003_card_writes`, `0004_audit_events` | `backend/app/alembic/versions/` (new) | `0002` |
| Card write services + `locked` read | `backend/app/domains/cards/{repository,service}.py` | migration `0003` |
| `PostgresBankWrites` | `backend/app/domains/conversation/tools/postgres_writes.py` (new) | `cards.service`, `PostgresBank` (ownership probe and profile, like `FakeBankWrites` uses `FakeBank`) |
| OTP verify + `rl:otp:<account_id>` limiter | `backend/app/api/v1/auth.py`, `backend/app/domains/identity/service.py` | `_RedisLoginLimiter`, `tokens.issue_token` |
| `SessionStepUpGate` | `backend/app/domains/identity/step_up_session.py` (new) | stdlib only |
| Audit domain | `backend/app/domains/audit/` (new): `__init__.py` (docstring only, **no imports**); `schemas.py` (`AuditType`, `AuditActor`, `AuditEvent`, the `Recorder` Protocol, `NullAuditRecorder`: stdlib + pydantic only); `repository.py` (`insert_event`); `service.py` (`AuditRecorder`, DB-backed). Conversation code types against `audit.schemas.Recorder`. Only `conversation.tools.registry` imports `audit.service`, which is the one new ignore edge D13 asks for | migration `0004` |
| `ConfirmedWriteTools` v2 (allowlist, intent, D16 order, audit, idempotency key) | `backend/app/domains/conversation/tools/executor.py` | `Recorder`, `tool_allowed`, the `StepUpGate` Protocol |
| Routes: `/messages` resume, `/confirmations/{token_id}` | `backend/app/api/v1/conversations.py`, `backend/app/domains/conversation/runner.py` (`start_turn` inputs, `checkpointed_confirmation_token`) | `RedisConfirmationStore.is_open` |
| Runner wiring + registry builders + runner audit events | `runner.py` (`_run_turn`), `tools/registry.py` | everything above |
| `make chat-api` commands | `backend/scripts/chat_api.py` | the HTTP contract in the spec |

## Build order

Waves come from the spec's build-order groups, re-cut so that same-wave touch maps are disjoint and every ignore edge lands with its import.

- **W1 (six in parallel).** Everything that depends on nothing new:
  - T1 policy registry
  - T2 Redis store
  - T3 both migrations. One task owns the whole revision chain, so no same-wave `alembic upgrade head` ever sees a half-written sibling revision.
  - T4 OTP + gate
  - T5 raw-write idempotency on the FakeBank side and the executor pass-through
  - T6 audit domain. No DB proof yet: its insert path is proven by `test_restart.py` in T11, and by the audit rows in T12/T13.
- **W2 (four in parallel).**
  - T7 Postgres writes. Needs T3's `0003` for its integration tests. Owns the `postgres_writes -> cards.service` edge.
  - T8 routes. Needs T2's `is_open`.
  - T9 executor v2. Needs T1's `tool_allowed`, T4's `SessionStepUpGate`, T5's executor and T6's `Recorder`.
  - T10 `chat_api.py`. Needs only the spec's HTTP contract.
- **W3 (one).** T11 runner wiring and registry. Needs T7, T8 and T9, because it constructs all three. Owns the `registry -> audit.service` edge.
- **W4 (one).** T12, the end-to-end API test. Needs the full wiring.
- **W5 (two in parallel).** T13 live end-of-day checks + `make client`, and T14 docs (D19). Docs go last so they can record the deviations logged in the state file.

Shared-file resolutions:
- `.importlinter`: T7 (W2) and T11 (W3). Each adds only the edge its own import creates.
- `backend/tests/integration/conftest.py`: T2 (W1) adds the key patterns `conf:*` and `rl:otp:*`. T7 (W2) adds the `restore_cards` fixture. T4's OTP test does not depend on T2's cleanup, because each run's `account_id` is fresh.
- `executor.py`: T5 (W1) and T9 (W2).
- `sandbox.py`: T5 (W1) touches the recording wrapper; T9 (W2) touches the constructor.
- `tests/unit/test_r2_confirmed_writes.py`: T5 (W1) and T9 (W2).
- `runner.py`: T8 (W2) handles turn inputs; T11 (W3) handles wiring and audit.
- `policies/tools.yaml` and `tools_policy.py`: T1 only.
- `ToolContext` (`context.py`): no task edits it. Only the value of `policy_version` changes, in T9 (sandbox) and T11 (registry).

## Touch map

| File | New/Mod | Task | Change |
|---|---|---|---|
| `policies/tools.yaml` | mod | T1 | `step_up_window_minutes: 5`, `allowed_intents` per tool (spec Contracts) |
| `backend/app/domains/policy/tools_policy.py` | mod | T1 | new fields, `provenance` Literal, `tool_allowed()` |
| `backend/app/domains/policy/registry.py` | new | T1 | `PolicyBundle`, `load_policies`, `get_policies`, `PolicyLoadError`, D1 hash |
| `backend/app/domains/policy/{escalation,min_payment}.py` | mod | T1 | `provenance: Literal["team-generated-synthetic"]` only |
| `backend/app/domains/conversation/flows/card_select.py` | mod | T1 | `provenance` Literal only |
| `backend/app/main.py` | mod | T1 | lifespan: `get_policies()` first, log `policy.loaded`, call `load_card_select_policy()` |
| `backend/tests/unit/test_policy_registry.py` | new | T1 | A1 Done-when |
| `backend/app/domains/policy/confirmation_redis.py` | new | T2 | `RedisConfirmationStore` |
| `backend/tests/integration/conftest.py` | mod | T2, T7 | T2: key patterns; T7: `restore_cards` fixture |
| `backend/tests/integration/test_r2_redis_store.py` | new | T2 | A2 Done-when |
| `backend/app/alembic/versions/0003_card_writes.py` | new | T3 | three `app.*` tables |
| `backend/app/alembic/versions/0004_audit_events.py` | new | T3 | `audit.audit_events` |
| `backend/app/domains/identity/step_up_session.py` | new | T4 | `SessionStepUpGate` |
| `backend/app/domains/identity/service.py` | mod | T4 | `verify_otp`, `OtpInvalid`, `rl:otp:` limiter use |
| `backend/app/api/v1/auth.py` | mod | T4 | `POST /auth/otp/verify` |
| `backend/tests/integration/test_auth.py` | mod | T4 | `+test_otp_verify` |
| `backend/app/domains/conversation/tools/write.py` | mod | T5 | `*, idempotency_key: str` on the four writes |
| `backend/app/domains/conversation/tools/fakebank.py` | mod | T5 | overlay key → `ActionResult` map; keyed writes |
| `backend/app/domains/conversation/tools/executor.py` | mod | T5, T9 | T5: pass `f"{token_id}:{step_index}"`; T9: allowlist, intent, audit, D16 order, new constructor |
| `backend/app/domains/conversation/sandbox.py` | mod | T5, T9 | T5: `_RecordingWriteTools` forwards the key; T9: constructor + policy hash |
| `backend/tests/unit/test_r2_confirmed_writes.py` | mod | T5, T9 | T5: stubs take the key, and the tests assert `tok-1:0`; T9: new constructor + `test_intent_not_allowed_is_refused` |
| `backend/tests/unit/{test_r3_flows,test_r1_fakebank,test_fakebank_writes}.py` | mod | T5 | stub signature / pass `idempotency_key=` |
| `backend/app/domains/audit/{__init__,schemas,repository,service}.py` | new | T6 | audit domain |
| `backend/app/domains/cards/repository.py` | mod | T7 | `locked` join; write/re-read SQL; transaction seam |
| `backend/app/domains/cards/service.py` | mod | T7 | write + re-read functions, `last_status_actor`, `locked` from `card_controls` |
| `backend/app/domains/conversation/tools/postgres_writes.py` | new | T7 | `PostgresBankWrites` |
| `backend/.importlinter` | mod | T7, T11 | T7: `postgres_writes -> cards.service`; T11: `registry -> audit.service` |
| `backend/tests/integration/test_postgres_writes.py` | new | T7 | R1, R3, R12, D11 |
| `backend/app/api/v1/conversations.py` | mod | T8 | resume body, confirmations route |
| `backend/app/domains/conversation/runner.py` | mod | T8, T11 | T8: `start_turn` inputs + `checkpointed_confirmation_token`; T11: wiring + audit |
| `backend/tests/integration/test_confirmations_route.py` | new | T8 | step 6 / D7 |
| `backend/tests/integration/test_r13_ownership.py` | mod | T8 | +confirmations case |
| `backend/app/domains/conversation/flows/{actions,card_block,card_unlock,replacement}.py` | mod | T9 | pass `intent` (one-line call-site edits) |
| `backend/tests/conftest.py` | mod | T9 | `make_session` new constructor |
| `backend/tests/unit/test_step_up.py` | new | T9 | A4 Done-when |
| `backend/scripts/chat_api.py` | mod | T10 | `/otp`, `/confirm`, `/cancel`, `/replay` |
| `backend/app/domains/conversation/tools/registry.py` | mod | T11 | policy hash, audited reads, `audit_recorder_for`, `turn_tools` |
| `backend/tests/unit/test_audit_pairs.py` | new | T11 | A5 Done-when |
| `backend/tests/integration/test_write_path_api.py` | new | T12 | A6 Done-when, steps 3-5, 7, PT |
| `frontend/src/client/**` | regen | T13 | `make client` (generated, no hand edits) |
| `docs/solution-docs/{04-contracts,03-data-architecture,decision-log}.md` | mod | T14 | D19 |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| An ignore edge added before its import fails `lint-imports` (default `error`) | Each edge lands in the task that creates the import: T7 and T11 |
| `audit/__init__.py` importing `service` makes every `conversation` → `audit.schemas` import reach `audit.repository` | T6 keeps `__init__.py` import-free. T6's Verify runs `lint-imports`, and a `sys.modules` check that importing `audit.schemas` does not load `audit.repository` |
| Two tasks write migrations in one checkout, so `alembic upgrade head` sees a half-written revision | T3 owns both `0003` and `0004` |
| Postgres write tests mutate the session-shared `it_db` (block MULTI's credit card), breaking later files (`test_restart`, `test_r1_postgres_tools`) | T7 adds a `restore_cards` fixture that resets `product_status` and deletes the three app tables' rows for the given cards. T7 and T12 use it |
| Block updates the product but the history insert fails, a half-write (R12) | T7: both statements run in one `engine.begin()` transaction, with the history insert in a module-level repository function the test monkeypatches to raise |
| A write reports "done" from a stale read (R3) | T7: `verified` compares a separate re-read service call with the expected value. The test monkeypatches that re-read to stale → `verified=False` |
| A tool takes `customer_id` from arguments (R1) | T7: every service write binds `customer_id` in SQL (card_controls via `INSERT … SELECT … FROM bank.products WHERE product_id=:card AND customer_id=:customer`), after the `PostgresBank.get_card_details` probe. `test_r1_customer_scope.py` still guards the signatures |
| A token is replayed or confirmed for another conversation (R2, R13) | T2: the Lua script is atomic and checks the owner. T8: the route gate (`is_open` + checkpoint match) → `409`, with no turn scheduled |
| Step-up window or allowlist hard-coded in Python (R8) | T1 puts both in YAML. T11's Verify greps `conversation/` and `identity/` for a `timedelta(minutes=` literal |
| Audit down turns a verified write into a failure | T9 follows D15: fail closed only before `consume_step`, and after the write log `audit.write_failed` and keep the result |
| User or reply text in audit payloads (R5) | T9 and T11 build payloads from structural keys only. `test_audit_pairs` asserts every payload key is in an allowlist |
| An LLM node gets write tools (R6) | No node changes. `test_r6_no_write_tools_in_llm_nodes.py` runs in `make check` |
| The OTP code or session token lands in logs | T4 never logs `code`, and uses `hmac.compare_digest`. `test_login_pii.py` stays green in `make check` |
| A same-wave task's test depends on another's output | Each task's Verify uses only prior-wave outputs (checked per task below) |
| The 5-minute step-up window from the unlock OTP silently covers the replacement's changed-address OTP in the e2e and live runs (step 5 expects an OTP) | T12 and T13 log in again (fresh session, `step_up_at=None`) before the block → replacement sequence |
| The API's `BANK=fake` fallback gives reads and writes separate overlays | T11 builds both from one `make_fakebank_factory(_DATA_DIR)` pair per turn |

## Tests

| Test | Task |
|---|---|
| `unit/test_policy_registry.py::test_headerless_file_fails_startup` | T1 |
| `unit/test_r2_confirmed_writes.py::test_intent_not_allowed_is_refused` | T9 |
| `unit/test_r2_confirmed_writes.py` (existing four, updated) | T5 (idempotency key), T9 (constructor) |
| `integration/test_r2_redis_store.py::test_reused_expired_foreign_tokens_rejected` | T2 |
| `integration/test_confirmations_route.py::test_replayed_token_is_409` | T8 |
| `integration/test_r13_ownership.py` (+1 case) | T8 |
| `integration/test_postgres_writes.py::test_each_write_verified_from_reread` | T7 |
| `integration/test_postgres_writes.py::test_foreign_card_write_refused` | T7 (`AccessDenied`, no row). The `access_denied` audit event is asserted in `test_audit_pairs` (T11), because the executor emits it (D14) |
| `integration/test_postgres_writes.py::test_block_history_same_transaction` | T7 |
| `integration/test_postgres_writes.py::test_idempotency_key_replay` | T7 |
| `unit/test_step_up.py::test_unlock_without_valid_step_up_refused` | T9 |
| `integration/test_auth.py::test_otp_verify` | T4 |
| `unit/test_audit_pairs.py::test_every_tool_call_leaves_a_pair_with_policy_hash` | T11 |
| `integration/test_write_path_api.py::test_lock_confirm_unlock_otp_block_replace` | T12 |
| `integration/test_write_path_api.py::test_pt_lock_happy_path` | T12 |
| `integration/test_write_path_api.py::test_bank_blocked_unlock_handoff` | T12 |

Success criteria, when not obvious from the table:
- SC1 (live startup failure): T13.
- SC2: T1 + T9, plus T11's grep.
- SC3's `curl`: T13.
- SC4's `SELECT`: T13.
- SC6's live check that audit rows match the startup hash: T13.
- SC7's `make chat-api`: T13.
- SC8: T14 for the docs; `make check` runs in the verifier.

## Open question (non-blocking; affects only T11)

**Q1. `reply_sent` payload.** D13 says `reply_sent` carries "template kinds and length", but no template kind is recorded anywhere the runner can see. `TurnState` has none, and a new field is "Ask first".
- **(a) Recommended:** `{route, ui_kinds, length}`, with no template kinds. This needs no state change.
- **(b)** Add a graph-local `template_kinds` list that flows append to. This touches every flow and `graph.py`.
- **(c)** Add a checkpointed `TurnState` field. This is ask-first.

T11 is written for (a). If the human picks (b) or (c), the spec must change first.

## Tasks

- [ ] T1: [W1] Policy registry, `tools.yaml` v1 (allowlist + step-up window) and startup validation
  - Depends on: nothing.
  - Read exactly these:
    - spec §Decisions D1, D2, D3, D4 and §Contracts → "`policies/tools.yaml`" and "`app/domains/policy/registry.py`"
    - `backend/app/domains/policy/tools_policy.py`, the loader pattern to mirror
    - `backend/app/main.py` `_lifespan`
  - Acceptance:
    - `policies/tools.yaml` equals the spec's Contracts block (keep the header comment).
    - `ToolPolicy` gains `allowed_intents: list[str]`. `ToolsPolicy` gains `step_up_window_minutes: int = Field(ge=1)`.
    - `provenance: Literal["team-generated-synthetic"]` goes on `ToolsPolicy`, `EscalationPolicy`, `MinPaymentPolicy` and `CardSelectPolicy`. That is a one-line change in each of `escalation.py`, `min_payment.py` and `flows/card_select.py`; nothing else changes in those files.
    - New `tool_allowed(policy) -> Callable[[str, str], bool]` in `tools_policy.py`, called as `(intent, tool)`. An unknown tool or intent → `False`.
    - New `policy/registry.py`:
      - `PolicyBundle` (frozen): `hash`, `tools`, `escalation`, `min_payment`, `files`.
      - `PolicyLoadError(RuntimeError)`, whose message names the file.
      - `load_policies(directory: Path | None = None)` loads every `*.yaml` in the directory, default `<repo root>/policies` via `parents[4]`. The stems `tools`, `escalation` and `min_payment` use their own models. Any other stem (including `card_select`) is validated against a private header-only model (`provenance` Literal, `version: int`, `extra="allow"`). Any validation or YAML error is re-raised as `PolicyLoadError(<file name>)`.
      - The hash is exactly `"sha256:" + sha256(b"".join(name.encode() + b"\0" + bytes + b"\0" for name in sorted file names)).hexdigest()`.
      - `get_policies()` is `functools.lru_cache`d.
      - `policy/registry.py` must not import `app.domains.conversation`.
    - `main.py` `_lifespan`:
      - Calls `get_policies()` first.
      - Logs `policy.loaded` with `hash=` and `files=` via structlog.
      - Calls `load_card_select_policy()` once, then continues as today.
  - Test: `backend/tests/unit/test_policy_registry.py::test_headerless_file_fails_startup`.
    - Copy the real `policies/*.yaml` to `tmp_path`, remove the `provenance` line from one file → `pytest.raises(PolicyLoadError)` whose message contains that file name.
    - A clean copy loads twice to the same `hash`. Changing one byte in one file changes it.
  - Verify: `cd backend && uv run pytest tests/unit/test_policy_registry.py tests/unit/test_r2_confirmation_store.py tests/unit/test_min_payment.py tests/unit/test_card_select.py tests/unit/test_health.py -q && uv run ruff check app/domains/policy app/main.py app/domains/conversation/flows/card_select.py tests/unit/test_policy_registry.py && uv run ruff format --check app/domains/policy app/main.py app/domains/conversation/flows/card_select.py tests/unit/test_policy_registry.py && uv run mypy app/domains/policy app/main.py && uv run python -c "from app.domains.policy.registry import get_policies as g; b=g(); assert b.hash.startswith('sha256:') and b.tools.step_up_window_minutes==5, b"`
  - Files:
    - `policies/tools.yaml`
    - `backend/app/domains/policy/tools_policy.py`
    - `backend/app/domains/policy/registry.py` (new)
    - `backend/app/main.py`
    - `backend/tests/unit/test_policy_registry.py` (new)
    - one-line edits: `backend/app/domains/policy/escalation.py`, `backend/app/domains/policy/min_payment.py`, `backend/app/domains/conversation/flows/card_select.py`

- [ ] T2: [W1] `RedisConfirmationStore` and the A2 token-rejection test
  - Depends on: nothing.
  - Read exactly these:
    - `docs/solution-docs/04-contracts.md` §7 (Confirmation token)
    - spec §Decisions D8 and §Contracts → "`confirmation_redis.py`"
    - `backend/app/domains/policy/confirmation_memory.py`, the semantics to mirror. `backend/app/domains/policy/confirmation.py` is the Protocol.
  - Acceptance:
    - `RedisConfirmationStore(customer_id: str, conversation_id: str)` structurally implements `ConfirmationStore`.
    - `issue`:
      - Stores `conf:<token_id>` as JSON `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor: 0, expires_at}` with `EX 300`.
      - `token_id = secrets.token_urlsafe(32)`.
      - Returns `ConfirmationPlan` with `expires_at = now + 300 s`, aware UTC.
    - `consume_step` is **one** Lua script (cjson):
      - Missing key → `ConfirmationRequired("unknown_or_expired")`.
      - Owner mismatch → `"wrong_owner"`.
      - The step at the cursor has a different tool or `args_hash(tool, args)` → `"step_mismatch"`.
      - Otherwise advance the cursor (`SET … KEEPTTL`), or `DEL` after the last step. Return the consumed 0-based index.
    - `cancel` is an idempotent `DEL`.
    - `is_open(token_id) -> bool`: the key exists **and** its `customer_id` and `conversation_id` match this store's.
    - Redis errors → `ToolUnavailable`.
    - Imports only stdlib, pydantic, `app.core.*` and `policy.confirmation`. mypy strict.
    - In `backend/tests/integration/conftest.py`, append `"conf:*"` and `"rl:otp:*"` to `_REDIS_KEY_PATTERNS`. Nothing else in that file changes.
  - Test: `backend/tests/integration/test_r2_redis_store.py::test_reused_expired_foreign_tokens_rejected`.
    - Uses the `it_env` fixture, with one `asyncio.run` for the body.
    - A fully consumed token reused → `unknown_or_expired`.
    - Issued then `await get_redis().expire("conf:<id>", 0)` → `unknown_or_expired`.
    - A store with another customer, and another with another conversation → `wrong_owner`, and `is_open` is `False` for both.
    - A two-step plan consumed out of order → `step_mismatch`.
    - `is_open` is `True` for the owner's open plan.
  - Verify: `cd backend && uv run pytest tests/integration/test_r2_redis_store.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/domains/policy/confirmation_redis.py tests/integration && uv run ruff format --check app/domains/policy/confirmation_redis.py tests/integration && uv run mypy app/domains/policy/confirmation_redis.py`
  - Files:
    - `backend/app/domains/policy/confirmation_redis.py` (new)
    - `backend/tests/integration/test_r2_redis_store.py` (new)
    - `backend/tests/integration/conftest.py`

- [ ] T3: [W1] Migrations `0003_card_writes` and `0004_audit_events`
  - Depends on: nothing. The alembic head is `0002`.
  - Read exactly these:
    - spec §Contracts → "Migration `0003_card_writes`" and "Migration `0004_audit_events`", plus D9 and D12
    - `backend/app/alembic/versions/0002_identity_conversations.py`, the style to mirror
  - Acceptance:
    - `0003`: `revision = "0003"`, `down_revision = "0002"`. Creates `app.card_controls`, `app.card_status_history` and `app.card_replacements` with exactly the spec's columns, unique nullable `idempotency_key` on all three, unique `tracking_id`, and the index `(product_id, at desc)` on history.
      - No FK to `app.conversations`.
      - No address column. `card_replacements` stores `address_ref` and `address_changed` only.
      - UUID PKs are generated in code (no server default), like `0002`.
    - `0004`: `revision = "0004"`, `down_revision = "0003"`. Creates `audit.audit_events` with exactly the spec's columns (`payload` jsonb not null, `sources` jsonb not null default `'[]'`) and the index `(conversation_id, at)`.
    - Each `downgrade()` drops exactly what its `upgrade()` created.
    - `0001`/`0002` are unchanged.
  - Verify: `docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE IF EXISTS latam_mig_check" -c "CREATE DATABASE latam_mig_check" && cd backend && export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check && uv run alembic upgrade head && uv run alembic downgrade 0002 && uv run alembic upgrade head && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from information_schema.tables where table_schema||'.'||table_name in ('app.card_controls','app.card_status_history','app.card_replacements','audit.audit_events')")" = 4 && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from information_schema.columns where table_schema='app' and table_name='card_replacements' and column_name like '%address%'")" = 2 && docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE latam_mig_check" && uv run ruff check app/alembic/versions && uv run ruff format --check app/alembic/versions`
  - Files:
    - `backend/app/alembic/versions/0003_card_writes.py` (new)
    - `backend/app/alembic/versions/0004_audit_events.py` (new)

- [ ] T4: [W1] `POST /auth/otp/verify`, the OTP rate limit and `SessionStepUpGate`
  - Depends on: nothing.
  - Read exactly these:
    - spec §Decisions D4, D5 and §Contracts → HTTP row `POST /auth/otp/verify` and "`step_up_session.py`"
    - `backend/app/api/v1/auth.py` (`refresh` is the pattern to mirror)
    - `backend/app/domains/identity/service.py` (`login`, `LoginLimiter`, `_RedisLoginLimiter`)
  - Acceptance:
    - `identity/step_up_session.py`:
      - `SessionStepUpGate(step_up_at: datetime | None, window: timedelta, now: Callable[[], datetime] = _utcnow)` implements `StepUpGate`.
      - Valid iff `step_up_at is not None and now() - step_up_at <= window`.
      - Stdlib only.
    - `identity/service.py`:
      - New `OtpInvalid(Exception)`.
      - New `async def verify_otp(session: Session, code: str, *, limiter: LoginLimiter | None = None, settings: Settings | None = None) -> Session`, using the key `f"rl:otp:{session.account_id}"`.
      - If failures ≥ `login_max_failures` → `TooManyAttempts`, checked first, even for the right code.
      - Match = `bool(settings.demo_otp_code) and hmac.compare_digest(code.encode(), settings.demo_otp_code.encode())`.
      - A miss → `record_failure(window_seconds=login_window_seconds)`, then `OtpInvalid`.
      - A match → `session.model_copy(update={"step_up_at": datetime.now(UTC)})`.
      - Logs `auth.otp_failed` / `auth.otp_verified` with `account_id` only. **The code is never logged or put in an exception message.**
    - `api/v1/auth.py`:
      - `@router.post("/auth/otp/verify", response_model=MeResponse)`, with body model `OtpVerifyRequest{code: str}` (`extra="forbid"`) defined in `auth.py`.
      - Gets the `Session` via `Depends(get_session)`.
      - Maps `TooManyAttempts` → `429 too_many_attempts` and `OtpInvalid` → `401 otp_invalid`.
      - On success, `issue_token(new_session, …)` + `new_csrf_token()` + `_set_auth_cookies`, and returns `identity_service.me(new_session)`. The old token is not revoked.
    - `tests/unit/test_r13_routes.py` stays green, because the route is on `router`.
  - Test: `backend/tests/integration/test_auth.py::test_otp_verify`, using the existing `app_client` and `it_accounts`.
    - `monkeypatch.setenv("DEMO_OTP_CODE", "<test code>")` then `get_settings.cache_clear()` before any request.
    - Log in, then post the right code → `200`, and `decode_token(<session cookie>, secret=get_settings().jwt_secret).step_up_at` is not `None`.
    - Post a wrong code 5 times → `401 otp_invalid` each time, then the right code → `429 too_many_attempts`.
    - The CSRF header must come from the **latest** `csrf_token` cookie, because verify rotates it.
    - Don't rely on the conftest Redis cleanup: `account_id` is fresh per run.
  - Verify: `cd backend && uv run pytest tests/integration/test_auth.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_login_pii.py -q && uv run ruff check app/api/v1/auth.py app/domains/identity tests/integration/test_auth.py && uv run ruff format --check app/api/v1/auth.py app/domains/identity tests/integration/test_auth.py && uv run mypy app/api/v1/auth.py app/domains/identity`
  - Files:
    - `backend/app/domains/identity/step_up_session.py` (new)
    - `backend/app/domains/identity/service.py`
    - `backend/app/api/v1/auth.py`
    - `backend/tests/integration/test_auth.py`

- [ ] T5: [W1] Idempotency keys on the raw write contract, `FakeBankWrites` and the executor pass-through (D11)
  - Depends on: nothing.
  - Read exactly these:
    - spec §Decisions D11 and §Contracts → "`app/domains/conversation/tools/write.py`"
    - `backend/app/domains/conversation/tools/executor.py`
    - `backend/app/domains/conversation/tools/fakebank.py` (`FakeBankOverlay`, `FakeBankWrites`)
  - Acceptance:
    - `write.py`: the four writes gain a keyword-only `idempotency_key: str`, exactly the spec signatures. `get_block_origin` is unchanged.
    - `FakeBankOverlay` gains `results: dict[str, ActionResult]`. Each `FakeBankWrites` write:
      1. If `idempotency_key in overlay.results`, returns that stored result and mutates nothing.
      2. Otherwise it writes as today and stores the result under the key.
    - `sandbox._RecordingWriteTools` forwards `idempotency_key=` on the four writes. Only that class changes in `sandbox.py`.
    - `executor._run`:
      - Keeps D2-K's order and cancel semantics.
      - Stores `step_index = await self._confirmations.consume_step(...)`.
      - Calls the raw write with `idempotency_key=f"{token_id}:{step_index}"`. `call` becomes `Callable[[str], Awaitable[ActionResult]]`, taking the key.
      - The module docstring's "not implemented" paragraph is updated.
      - The constructor is unchanged; T9 changes it.
    - Test updates:
      - `_StubRawWrites` (test_r2) and `_UnverifiedLockWrites` (test_r3) take `*, idempotency_key: str`. `_StubRawWrites` records it.
      - The existing test_r2 tests assert that the raw call got `idempotency_key == "tok-1:0"` (the stub store returns index 0).
      - `test_r1_fakebank.py` and `test_fakebank_writes.py` pass `idempotency_key="k-…"`, a distinct key per call. Their assertions are otherwise unchanged.
    - No new test file (FakeBank idempotency isn't on the test list).
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py tests/unit/test_r3_flows.py tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py tests/unit/test_block_flows.py tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation tests/unit && uv run ruff format --check app/domains/conversation tests/unit && uv run mypy app/domains/conversation`
  - Files:
    - `backend/app/domains/conversation/tools/write.py`
    - `backend/app/domains/conversation/tools/fakebank.py`
    - `backend/app/domains/conversation/tools/executor.py`
    - `backend/app/domains/conversation/sandbox.py` (`_RecordingWriteTools` only)
    - mechanical test edits: `backend/tests/unit/test_r2_confirmed_writes.py`, `test_r3_flows.py`, `test_r1_fakebank.py`, `test_fakebank_writes.py`

- [ ] T6: [W1] Audit domain v0: schemas, `Recorder` Protocol, `NullAuditRecorder`, repository and `AuditRecorder`
  - Depends on: nothing. Migration `0004` is written in parallel by T3; this task needs no DB.
  - Read exactly these:
    - spec §Decisions D12, D13, D15 and §Contracts → "`app/domains/audit/`"
    - `docs/solution-docs/04-contracts.md` §6
    - `backend/app/domains/cards/repository.py` (the `_fetch_rows` + `ToolUnavailable` pattern)
  - Acceptance:
    - `audit/__init__.py` is a docstring only, with **no imports**. Otherwise every `conversation` → `audit.schemas` import would reach `audit.repository` through the package.
    - `audit/schemas.py` imports only stdlib and pydantic. It defines:
      - `AuditType`, the spec's Literal.
      - `AuditActor = Literal["bot","customer","system"]`.
      - `AuditEvent` (frozen): `id: UUID`, `at: datetime`, `conversation_id: UUID | None`, `turn_id: UUID | None`, `actor`, `type`, `payload: dict[str, JsonValue]`, `sources: list[str]`, `policy_version: str`, `trace_id: str | None`.
      - `class Recorder(Protocol)`: `async def record(self, type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()) -> UUID`.
      - `NullAuditRecorder`, which implements it and returns `uuid4()`.
    - `audit/repository.py`: `async def insert_event(event: AuditEvent) -> None`, an `INSERT` into `audit.audit_events` with `payload`/`sources` as jsonb and `model`/`langfuse_trace_id` NULL. `SQLAlchemyError`/`OSError` → `ToolUnavailable`. There is no update or delete function (append-only, D12).
    - `audit/service.py`: `AuditRecorder(*, conversation_id, turn_id, trace_id, policy_version, actor, insert: Callable[[AuditEvent], Awaitable[None]] | None = None)`, keyword-only.
      - `record` builds `AuditEvent(id=uuid4(), at=now UTC, …)`, awaits `insert` (default `repository.insert_event`) and returns the id.
      - It **raises** on failure. Callers decide between fail-closed and log (D15).
    - Nothing outside `app/domains/audit/` changes. No `.importlinter` change: T11 adds the `registry -> audit.service` edge with its import.
  - Verify (a heredoc, run from `backend/`):
    ```bash
    cd backend && uv run ruff check app/domains/audit && uv run ruff format --check app/domains/audit && uv run mypy app/domains/audit && uv run lint-imports && uv run python - <<'EOF'
    import asyncio, sys, uuid
    import app.domains.audit.schemas as s
    assert "app.domains.audit.repository" not in sys.modules
    assert isinstance(asyncio.run(s.NullAuditRecorder().record("tool_call", {"tool": "cards.lock_card"})), uuid.UUID)
    from app.domains.audit.service import AuditRecorder
    seen = []
    async def ins(e): seen.append(e)
    r = AuditRecorder(conversation_id=uuid.uuid4(), turn_id=uuid.uuid4(), trace_id="t", policy_version="sha256:x", actor="bot", insert=ins)
    i = asyncio.run(r.record("readback", {"verified": True}))
    assert seen[0].id == i and seen[0].policy_version == "sha256:x"
    EOF
    ```
  - Files:
    - `backend/app/domains/audit/__init__.py` (new)
    - `backend/app/domains/audit/schemas.py` (new)
    - `backend/app/domains/audit/repository.py` (new)
    - `backend/app/domains/audit/service.py` (new)

- [ ] T7: [W2] Postgres card writes with read-back, block in one transaction, idempotency, and `PostgresBankWrites` (A3)
  - Depends on:
    - T3: migration `0003` exists, and `it_db` migrates to head.
    - T5: the D11 keyword signature in `write.py` (read it; don't edit it).
    - The state file has T3's and T5's actual names.
  - Read exactly these:
    - spec §Decisions D9, D10, D11 and §Contracts → "Migration `0003_card_writes`"
    - `backend/app/domains/conversation/tools/fakebank.py` `FakeBankWrites` (the behavior and read-back keys to match, including the `get_block_origin` order)
    - `backend/app/domains/conversation/tools/postgres.py` (the `PostgresBank` ownership probe and the `tool.access_denied` log)
  - Acceptance:
    - `cards/repository.py`:
      - `fetch_cards`/`fetch_card_details` add `LEFT JOIN app.card_controls` → `coalesce(cc.locked, false) AS locked`.
      - New write SQL. Every statement binds `customer_id`. `card_controls` is written by `INSERT … SELECT … FROM bank.products WHERE product_id=:card_id AND customer_id=:customer_id ON CONFLICT (product_id) DO UPDATE`.
      - The block runs as **one** `async with get_engine().begin() as conn:` that calls two module-level functions, `update_product_status(conn, …)` then `insert_status_history(conn, …)`. The second is the seam the R12 test monkeypatches.
      - Re-read SQL: the lock row, `product_status` + latest history `at`/`actor`, the replacement by id, and an existing row by `idempotency_key` in each table.
    - `cards/service.py`:
      - `_to_summary` uses `row["locked"]`.
      - New functions: `set_locked(customer_id, card_id, *, locked, actor, idempotency_key)`, `get_lock_state`, `block_card(customer_id, card_id, *, reason, actor, conversation_id, trace_id, idempotency_key)`, `get_block_state`, `order_replacement(customer_id, card_id, *, address_ref, address_changed, conversation_id, idempotency_key) -> UUID`, `get_replacement`, `last_status_actor(customer_id, card_id) -> str | None`.
      - Return types are small frozen dataclasses or pydantic models defined in `service.py`. Don't edit `cards/schemas.py`.
      - A write whose `idempotency_key` already exists writes nothing and returns or leads to the existing record. An `IntegrityError` on the key is treated the same way.
      - `tracking_id = "RPL-" + secrets.token_hex(4).upper()`.
    - `conversation/tools/postgres_writes.py` `PostgresBankWrites(ctx)`:
      - Holds `self._reads = PostgresBank(ctx)`. Each method first runs `await self._reads.get_card_details(card_id)`, which gives the R1 probe, the `AccessDenied` + `tool.access_denied` log, and `NotFound`.
      - Calls the service write, then a **separate** re-read service call, and returns `ActionResult` with `verified` true only when the re-read shows the expected value. Read-back keys are exactly those in `04` §1 (`locked`/`status` + `at`), and `tracking_id` is set for a replacement.
      - `block_card` sets `actor=ctx.actor`, `conversation_id=ctx.conversation_id` and `trace_id=ctx.trace_id`.
      - `order_replacement` sets `address_changed = address_ref != "on_file"` and never resolves or stores an address.
      - `get_block_origin` follows D10's order: customer block (status `Blocked` and `last_status_actor == "customer"`), customer lock (`details.locked`), `profile.customer_status != "Active"` → `bank_side/customer_status`, `days_past_due > 0` → `past_due`, `Blocked`/`Suspended` → `bank_status`, else `none`.
      - It never raises `Conflict`.
      - Imports `cards.service` only, not the repository.
    - `.importlinter`: **after** `postgres_writes.py` exists and imports `cards.service` (a dangling edge breaks `lint-imports` for the other W2 tasks), add exactly `app.domains.conversation.tools.postgres_writes -> app.domains.cards.service` under `conversation-no-repository`'s `ignore_imports`.
    - `tests/integration/conftest.py`: add a `restore_cards` fixture that yields a `set[str]` the test fills with card ids. On teardown, for those ids it:
      - deletes rows from the three `app.card_*` tables,
      - restores `bank.products.product_status` from a snapshot taken before the test (take the snapshot in the fixture for the fixture's known card list, or lazily), and
      - clears `get_engine` around its own `asyncio.run`.
  - Tests: `backend/tests/integration/test_postgres_writes.py`, all using `it_env` + `restore_cards` and building `ToolContext` directly (see `test_r1_postgres_tools.py`).
    - `test_each_write_verified_from_reread`: lock / unlock / block / replacement on `PRD-TFM1CRED0001` (`CLI-TFMULTI00001`). Each result is `verified=True`, and its `readback` equals the DB row. Then, with `monkeypatch.setattr(postgres_writes.cards_service, "get_lock_state", <stale>)`, a lock → `verified=False`.
    - `test_foreign_card_write_refused`: MULTI's ctx writing `PRD-TFS2CRED0001` → `AccessDenied` for each of the four writes, and zero rows for that product in the three tables.
    - `test_block_history_same_transaction`: after a block, `product_status='Blocked'` and exactly one history row with `old_status`, `new_status='Blocked'`, `reason`, `actor='customer'` and `conversation_id`. With `insert_status_history` monkeypatched to raise, a block of another card (`PRD-TFM1DEBT0002`) → an exception, and that product's status is unchanged.
    - `test_idempotency_key_replay`: the same key twice for block, replacement and lock → one history row, one replacement row, one controls change, and an equal `readback`/`tracking_id`.
  - Verify: `cd backend && uv run pytest tests/integration/test_postgres_writes.py tests/integration/test_r1_postgres_tools.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run lint-imports && uv run ruff check app/domains/cards app/domains/conversation/tools/postgres_writes.py tests/integration && uv run ruff format --check app/domains/cards app/domains/conversation/tools/postgres_writes.py tests/integration && uv run mypy app/domains/cards app/domains/conversation/tools/postgres_writes.py`
  - Files:
    - `backend/app/domains/cards/repository.py`
    - `backend/app/domains/cards/service.py`
    - `backend/app/domains/conversation/tools/postgres_writes.py` (new)
    - `backend/.importlinter`
    - `backend/tests/integration/test_postgres_writes.py` (new)
    - `backend/tests/integration/conftest.py` (fixture only)

- [ ] T8: [W2] `/messages` resume, `POST /conversations/{id}/confirmations/{token_id}`, and `start_turn` inputs (D6, D7)
  - Depends on:
    - T2: `RedisConfirmationStore(customer_id, conversation_id).is_open(token_id)` and the `conf:*` cleanup.
    - The state file has T2's actual names.
  - Read exactly these:
    - spec §Decisions D6, D7 and §Contracts → HTTP rows `/messages` and `/confirmations`, plus "Runner"
    - `backend/app/api/v1/conversations.py`
    - `backend/app/domains/conversation/runner.py` (`start_turn`, and the `_run_turn` input dict only)
  - Acceptance:
    - `runner.start_turn(host, *, session, conversation_id, trace_id, text: str | None = None, resume: Literal["step_up"] | None = None, confirmation: ConfirmationDecision | None = None)`. Exactly one of the three must be set, else `ValueError`.
    - Only `text` is persisted as a customer message (human decision 2).
    - `_run_turn` receives all three and streams `{"user_text": text or "", "confirmation": confirmation, "resume": resume}`. The rest of `_run_turn` is unchanged; T11 rewires it.
    - New `async def checkpointed_confirmation_token(host: TurnHost, conversation_id: UUID) -> str | None` in `runner.py`.
    - `PostMessageRequest` becomes `{text: str | None (1..2000), resume: Literal["step_up"] | None}` with a `model_validator` enforcing exactly one → `422` otherwise.
    - New `@router.post("/{conversation_id}/confirmations/{token_id}", status_code=202, response_model=PostMessageResponse)`:
      - Body `ConfirmationRequest{decision: Literal["confirm","cancel"]}` (`extra="forbid"`).
      - Depends on `get_owned_conversation`.
      - Before scheduling anything, it requires `await RedisConfirmationStore(session.customer_id, str(conversation.id)).is_open(token_id)` **and** `await checkpointed_confirmation_token(host, conversation.id) == token_id`. Otherwise it returns `409 confirmation_invalid`.
      - Then `start_turn(..., confirmation=ConfirmationDecision(token_id=token_id, decision=body.decision))`, with `TurnInProgress` → `409 turn_in_progress`.
    - `tests/unit/test_r13_routes.py` stays green.
  - Tests:
    - `backend/tests/integration/test_confirmations_route.py::test_replayed_token_is_409`, using `app_client` + `it_accounts`:
      - Log in as A and create a conversation.
      - In a separate `asyncio.run`, clearing the caches first, issue plans with `RedisConfirmationStore`:
        - (i) Fully consume one → post it → `409 {"detail":"confirmation_invalid"}`.
        - (ii) Issue for A with a different conversation id → `409`.
        - (iii) Issue for A on this conversation. It is open but not checkpointed → `409`.
      - After each case, assert no turn was scheduled: no `turn:<conversation_id>` key, and `app.messages` has no row for the conversation.
      - Also assert `{}` and `{"text":"x","resume":"step_up"}` on `/messages` → `422`.
    - `backend/tests/integration/test_r13_ownership.py`: add to the existing test that customer B posting `{"decision":"confirm"}` to A's `/confirmations/<any>` → `404 not_found`.
  - Verify: `cd backend && uv run pytest tests/integration/test_confirmations_route.py tests/integration/test_r13_ownership.py tests/integration/test_restart.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py -q && uv run ruff check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration && uv run ruff format --check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration && uv run mypy app/api/v1/conversations.py app/domains/conversation/runner.py`
  - Files:
    - `backend/app/api/v1/conversations.py`
    - `backend/app/domains/conversation/runner.py`
    - `backend/tests/integration/test_confirmations_route.py` (new)
    - `backend/tests/integration/test_r13_ownership.py`

- [ ] T9: [W2] `ConfirmedWriteTools` v2: allowlist, intent, step-up rule hit, audit events and the D16 order
  - Depends on:
    - T1: `tool_allowed`, `get_policies`.
    - T4: `SessionStepUpGate`.
    - T5: the executor's `idempotency_key` pass-through.
    - T6: `app.domains.audit.schemas.Recorder`, `NullAuditRecorder`.
    - The state file has their actual names.
  - Read exactly these:
    - spec §Decisions D3, D13, D14, D15, D16 and §Contracts → "`executor.py`"
    - `backend/app/domains/conversation/tools/executor.py`
    - `backend/app/domains/conversation/flows/actions.py` (`start_plan`)
  - Acceptance:
    - The constructor is `ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up, allowed: IntentAllowlist, audit: Recorder)`. `IntentAllowlist = Callable[[str, str], bool]` is exported. Import `Recorder` from `app.domains.audit.schemas` only, never `audit.service`.
    - `issue_plan(steps, intent)`: if any step's tool isn't allowed → record `rule_hit {rule_id:"tool_not_allowed", tool, intent}` (best effort) and raise `PolicyDenied("tool_not_allowed")` **before** touching the store. Otherwise issue, then record `confirmation_issued {tools, step_count}`.
    - `get_block_origin(card_id, intent)` runs, in order:
      1. The same allowlist check.
      2. `tool_call` (fail closed → `ToolUnavailable`).
      3. The raw call. `AccessDenied` → record `access_denied {tool, card_id}` + `tool_result {tool, error:"AccessDenied"}`, then re-raise.
      4. `tool_result {tool, kind, reason}`.
    - Each write follows D16 exactly:
      1. `tool_call {tool, card_id, args_hash}`. If recording raises → `ToolUnavailable`, with no consume and no raw call.
      2. Step-up needed and invalid → `rule_hit {rule_id:"step_up_required", tool}`, `tool_result {tool, error:"StepUpRequired"}`, raise `StepUpRequired`. Nothing is consumed and the plan is not cancelled (unchanged semantics).
      3. `consume_step` → `confirmation_used {tool, step_index}`. A `ConfirmationRequired` → `tool_result{error}`, then re-raise, with no cancel (unchanged).
      4. The raw call with `idempotency_key=f"{token_id}:{step_index}"`.
      5. `readback {tool, verified, readback}`, with the read-back JSON-safe via `result.model_dump(mode="json")`, then `tool_result {tool, verified}`. Return `result.model_copy(update={"audit_event_id": <readback id>})`.
    - Any recording failure after step 4 → structlog `audit.write_failed` (ids and type only), and the result is kept with `audit_event_id=None` (D15, human decision 1).
    - A raw exception or `verified=False` → `tool_result{error|verified:false}` (best effort) and `cancel`, as today.
    - Payloads carry no free text. `card_id` is the opaque product id.
    - `flows/actions.start_plan(..., intent: Intent)` passes it to `issue_plan`. Call sites:
      - `card_block.py` → `intent="card_block"`
      - `card_unlock.py` → `"card_unlock"`, for `start_plan` and `get_block_origin(card_id, "card_unlock")`
      - `replacement.py` → `"replacement_request"`, for both
    - No other flow logic changes.
    - `sandbox.py` `_build_session`:
      - Uses `bundle = get_policies()`.
      - The constructor becomes `ConfirmedWriteTools(write_tools, store, gate, step_up_rule(bundle.tools), tool_allowed(bundle.tools), NullAuditRecorder())`.
      - `policy_version=bundle.hash`.
      - The signature and 3-tuple of `build_sandbox_session` are unchanged.
    - `tests/conftest.py` `make_session` uses `tool_allowed(load_tools_policy())` and `NullAuditRecorder()`.
  - Tests:
    - `backend/tests/unit/test_r2_confirmed_writes.py`: update the four constructor sites (allow-all lambda + a list recorder defined in the test file), and add `test_intent_not_allowed_is_refused`. `issue_plan([PlanStep(tool="cards.lock_card", …)], intent="card_unlock")` with `tool_allowed(load_tools_policy())` → `PolicyDenied` with `reason_code == "tool_not_allowed"`. A store stub whose `issue` raises proves the store was never called. The list recorder holds one `rule_hit`.
    - `backend/tests/unit/test_step_up.py::test_unlock_without_valid_step_up_refused`: `SessionStepUpGate(None, window)` and `SessionStepUpGate(now-6min, window)`, with `window = timedelta(minutes=load_tools_policy().step_up_window_minutes)`. With `step_up_rule(load_tools_policy())`, `unlock_card` → `StepUpRequired`, the stub store's `consume_step` is never called, and a `rule_hit` `step_up_required` is recorded.
  - Verify: `cd backend && uv run pytest tests/unit -q && uv run ruff check app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py tests/conftest.py tests/unit && uv run ruff format --check app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py tests/conftest.py tests/unit && uv run mypy app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py`. The whole unit dir is the narrow check here: the constructor change touches `make_session`, which every flow test uses. `lint-imports` is left out because T7 edits `.importlinter` in this wave; T11 runs it. The whole unit dir is the narrow check here: the constructor change touches `make_session`, which every flow test uses.
  - Files:
    - `backend/app/domains/conversation/tools/executor.py`
    - `backend/tests/unit/test_r2_confirmed_writes.py`
    - `backend/tests/unit/test_step_up.py` (new)
    - `backend/tests/conftest.py`
    - `backend/app/domains/conversation/sandbox.py`
    - one-line call-site edits: `backend/app/domains/conversation/flows/{actions,card_block,card_unlock,replacement}.py`

- [ ] T10: [W2] `make chat-api`: `/otp`, `/confirm`, `/cancel` and `/replay` (D18)
  - Depends on: nothing in code. It only calls the HTTP contract in spec §Contracts → "HTTP". The live run is T13.
  - Read exactly these:
    - spec §Decisions D18, D6, D7 and §Contracts → "HTTP"
    - `backend/scripts/chat_api.py`
  - Acceptance:
    - The script remembers the last `ui` event whose `kind == "confirm"` (its `payload.token_id`) and the last token it posted.
    - `/otp <code>`: `POST /api/v1/auth/otp/verify {code}` with CSRF, printing only the status and `detail`, never the code. On `200`, it runs a turn by posting `{"resume":"step_up"}` to `/messages`.
    - `/confirm` and `/cancel`: run a turn by posting `{"decision": …}` to `/conversations/{id}/confirmations/{last_token}`. Print `no open confirmation` if there is none.
    - `/replay`: re-post the last **used** token with `{"decision":"confirm"}` and print `replay -> <status> <detail>`, without opening a stream.
    - Every turn-starting post goes through one helper: open `GET …/stream`, wait for `: connected`, post, print events until `done`. This generalizes today's `_run_turn`.
    - The CSRF header is read from the cookie jar on every call.
    - Plain text lines behave as today.
    - The module docstring lists the commands.
  - Verify: `cd backend && uv run ruff check scripts/chat_api.py && uv run ruff format --check scripts/chat_api.py && uv run python scripts/chat_api.py --help >/dev/null && uv run python -c "import ast,sys; src=open('scripts/chat_api.py',encoding='utf-8').read(); ast.parse(src); assert all(c in src for c in ('/otp','/confirm','/cancel','/replay','otp/verify','confirmations','resume'))"`
  - Files:
    - `backend/scripts/chat_api.py`

- [ ] T11: [W3] Runner wiring: policy hash, audited reads, the confirmed write path on the API, and the runner's audit events (A6, D2, D17)
  - Depends on:
    - T1: `get_policies`, `tool_allowed`, `step_up_rule`.
    - T2: `RedisConfirmationStore`.
    - T4: `SessionStepUpGate`.
    - T6: `AuditRecorder`, `Recorder`.
    - T7: `PostgresBankWrites`.
    - T8: `start_turn`/`_run_turn` inputs.
    - T9: the new `ConfirmedWriteTools` constructor.
    - The state file has their actual names.
  - Read exactly these:
    - spec §Decisions D2, D13, D14, D15, D17
    - `backend/app/domains/conversation/tools/registry.py`
    - `backend/app/domains/conversation/runner.py` (`_run_turn`)
  - Acceptance:
    - `registry.build_tool_context` sets `policy_version=get_policies().hash`.
    - `RecordingBankTools(inner, audit: Recorder)`: each of the five reads runs:
      1. `tool_call {tool}`, with the card id when there is one. Fail closed → `ToolUnavailable`, and the read doesn't run.
      2. The read. `AccessDenied` → `access_denied` + `tool_result{error}`, then re-raise. Any other exception → `tool_result{error: <class name>}`, then re-raise.
      3. `tool_result {tool, count | card_id}`.
      4. `.calls` is still appended.
    - New `registry.audit_recorder_for(ctx, turn_id) -> AuditRecorder`, bound to `conversation_id`, `turn_id`, `trace_id`, `policy_version=ctx.policy_version` and `actor="bot"`.
    - New `registry.turn_tools(ctx, session, audit) -> tuple[RecordingBankTools, ConfirmedWriteTools]`:
      - With `BANK=fake`: one `make_fakebank_factory(_DATA_DIR)` pair, so reads and writes share the overlay.
      - Otherwise `PostgresBank(ctx)` + `PostgresBankWrites(ctx)`.
      - Wrapped as `ConfirmedWriteTools(raw, RedisConfirmationStore(ctx.customer_id, str(ctx.conversation_id)), SessionStepUpGate(session.step_up_at, timedelta(minutes=bundle.tools.step_up_window_minutes)), step_up_rule(bundle.tools), tool_allowed(bundle.tools), audit)`.
      - `bank_tools_for` is removed, or kept as a thin wrapper, if nothing else uses it (grep).
    - `.importlinter`: add exactly `app.domains.conversation.tools.registry -> app.domains.audit.service`.
    - `runner._run_turn`:
      - Builds `ctx`, then `audit = registry.audit_recorder_for(ctx, turn_id)`, then `tools, write_tools = registry.turn_tools(ctx, session, audit)`.
      - The config gets `"bank_write_tools": write_tools` and `"vault": InMemoryAddressVault()`.
      - Records `nlu_result {language, status, intents}` when `understand` updates, with no slots.
      - Records `rule_hit {rule_id: <escalation_reason>}` for any non-`None` `escalation_reason` in this turn's updates.
      - Records `reply_sent {route, ui_kinds, length}` just before publishing `message`. This is Q1 option (a).
      - Runner audit failures log `audit.write_failed` and never fail the turn.
      - The module docstring drops the "`bank_write_tools` is always `None`" text.
  - Test: `backend/tests/unit/test_audit_pairs.py::test_every_tool_call_leaves_a_pair_with_policy_hash`.
    - `ctx = registry.build_tool_context(Session(...), uuid4(), "t")`.
    - A real `AuditRecorder` bound like `audit_recorder_for`, with an in-memory `insert` list.
    - `RecordingBankTools(FakeBank(ctx, fixture_dir), rec)` → one `list_cards` read.
    - `ConfirmedWriteTools(FakeBankWrites…, InMemoryConfirmationStore, gate, step_up_rule, tool_allowed, rec)`:
      - One refused `unlock_card` (gate invalid).
      - One verified `lock_card` after `issue_plan(…, "card_block")`.
      - One `get_block_origin` on another customer's card → `AccessDenied`.
    - Assertions:
      - One `tool_call`/`tool_result` pair per call.
      - An `access_denied` event.
      - Every event's `policy_version == get_policies().hash`.
      - The lock result's `audit_event_id` equals the `readback` event's id.
      - Every payload key is in an allowlist of structural keys, with no free text.
  - Verify: `cd backend && uv run pytest tests/unit/test_audit_pairs.py tests/unit/test_r2_confirmed_writes.py -q && uv run pytest tests/integration/test_restart.py tests/integration/test_r1_postgres_tools.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run lint-imports && uv run mypy app/domains/conversation && uv run ruff check app/domains/conversation tests/unit/test_audit_pairs.py && uv run ruff format --check app/domains/conversation tests/unit/test_audit_pairs.py && ! grep -rn "timedelta(minutes=[0-9]" app/domains/conversation app/domains/identity`. `test_restart.py` now runs audited reads through the real `AuditRecorder` into `audit.audit_events`, so it also proves T6's insert path.
  - Files:
    - `backend/app/domains/conversation/tools/registry.py`
    - `backend/app/domains/conversation/runner.py`
    - `backend/.importlinter`
    - `backend/tests/unit/test_audit_pairs.py` (new)

- [ ] T12: [W4] The end-to-end API test for the write path: ES full flow, PT lock and bank-blocked handoff (A6 Done-when)
  - Depends on: T11, the whole API write path wired, and T7's `restore_cards` fixture. The state file has the actual names.
  - Read exactly these:
    - spec §Test list rows `test_write_path_api.py`, and `07-execution-plan.md` D3 "End-of-day test" steps 3-5 and 7
    - `backend/tests/unit/test_block_flows.py` (the scripted-NLU sequences for lock, block → replacement, the new-address OTP and the unlock OTP, to reuse)
    - `backend/tests/integration/test_r13_ownership.py` (login and CSRF over `app_client`)
  - Acceptance:
    - Harness:
      - `monkeypatch.setenv("DEMO_OTP_CODE", …)` + `get_settings.cache_clear()` before `app_client` requests.
      - Swap `app_client.app.state.turn_host.llm = ScriptedLLM({...})` per scenario.
      - Post turns over HTTP.
      - Wait for each turn by polling `app.messages` (a sync `psycopg` connection to the `it_db` DSN) for `role='bot' AND turn_id=<id>`, with a timeout of about 20 s.
      - Read the confirm `token_id` from that row's `ui_payload`.
      - Clear the caches between the test's own DB reads and client requests.
    - `test_lock_confirm_unlock_otp_block_replace` (ES, `CLI-TFMULTI00001`, credit card):
      1. Lock → `ui.confirm` → `/confirmations {confirm}` → `app.card_controls.locked` is true, and the reply is the done template, which appears only from a verified result.
      2. Unlock → `ui` `otp_required` → `/auth/otp/verify` → `/messages {resume:"step_up"}` → confirm → `locked` is false.
      3. **Log in again** (fresh session, no step-up).
      4. Lost card → confirm → `product_status='Blocked'` + one history row → accept the replacement with a changed address → `otp_required` → OTP → resume → confirm → one `card_replacements` row with `address_changed=true` and `RPL-` in the reply.
      5. `audit.audit_events` for the conversation contains `tool_call`/`tool_result` pairs, all with one `policy_version` starting `sha256:`.
    - `test_pt_lock_happy_path` (PT, `CLI-TFSINGLE0002`): lock → confirm → locked, with the PT done text.
    - `test_bank_blocked_unlock_handoff` (`CLI-TFBLOCKD0003`, `PRD-TFB3DEBT0001`): unlock → the handoff placeholder reply. There is no `ui.confirm`, no `conf:*` key for the conversation and no `app.card_*` row.
    - All three use `restore_cards`.
    - If a scenario exposes a product bug, fix it in the owning file and log the deviation in the state file. No other task runs in this wave.
  - Verify: `cd backend && uv run pytest tests/integration/test_write_path_api.py -q 2>&1 | tail -1 | grep -E '^3 passed(, [0-9]+ warnings?)? in' && uv run ruff check tests/integration/test_write_path_api.py && uv run ruff format --check tests/integration/test_write_path_api.py`
  - Files:
    - `backend/tests/integration/test_write_path_api.py` (new)
    - any product fix, logged

- [ ] T13: [W5] Live end-of-day checks (steps 3-7, SC1, SC3, SC4, SC6, SC7) and `make client`
  - Depends on: T12 green. `make up` is running.
  - Read exactly these:
    - spec §Success criteria
    - `07-execution-plan.md` D3 "End-of-day test"
    - `README.md` (make targets)
    - `eval/personas.yaml` (pick a multi-card persona and a persona with `blocked: true`)
  - Acceptance and commands (from the repo root). Record each output line in the state file.
    - (a) `make seed-identity`, then `docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select version_num from alembic_version"` → `0004`.
    - (b) SC1:
      - `sed -i.bak '/^provenance/d' policies/min_payment.yaml && $COMPOSE restart backend`, where `$COMPOSE` is the Makefile's `COMPOSE` value.
      - `$COMPOSE logs backend --tail 50 | grep min_payment` shows the startup error.
      - `mv policies/min_payment.yaml.bak policies/min_payment.yaml && $COMPOSE restart backend && curl -sf localhost/api/v1/health`.
      - `git diff --exit-code policies/`.
    - (c) SC6: `$COMPOSE logs backend | grep policy.loaded` shows `hash=sha256:…`.
    - (d) Steps 3-5 through `make chat-api PERSONA=<multi-card persona>`, stdin piped. Step 5 expects an OTP for the changed address, so step 4's OTP must not still be in its window: quit and restart `make chat-api` (a fresh login) between steps 4 and 5.
    - (e) Step 6: in the same run, `/replay` prints `replay -> 409 confirmation_invalid`.
    - (f) Step 7: `make chat-api PERSONA=<blocked persona>` → the handoff placeholder.
    - (g) SC4: `psql` on `latam_app` shows the persona's card `product_status='Blocked'`, one `card_status_history` row, and one `card_replacements` row with `address_changed=t`.
    - (h) SC6: `select distinct policy_version from audit.audit_events` has one value equal to (c)'s hash.
    - (i) `make client && cd frontend && npx biome ci .`, which regenerates `frontend/src/client` with `/auth/otp/verify`, `/confirmations` and the `resume` body.
    - (j) `$COMPOSE logs backend | grep -c "<the DEMO_OTP_CODE value read from .env inside the command, never echoed>"` → `0`.
    - A bug found here gets fixed in its owning file and logged. T14 touches only docs.
  - Verify: `make check` passes, and `git status --porcelain policies/` is empty.
  - Files:
    - `frontend/src/client/**` (generated)
    - fixes only if needed, logged

- [ ] T14: [W5] Docs (D19): `04` §1/§3/§5/§7, `03` §6, and the resolved decision-log row
  - Depends on: T1–T12 merged on the branch. It reads the state file's deviations, so docs record what was built.
  - Read exactly these:
    - spec §Decisions D19 and §Contracts
    - `docs/solution-docs/04-contracts.md` §1, §3, §5, §7
    - `docs/solution-docs/03-data-architecture.md` §6 (L70-80)
  - Acceptance:
    - `04` §1:
      - `issue_plan(steps, intent)` / `get_block_origin(card_id, intent)` with `PolicyDenied("tool_not_allowed")`.
      - Raw writes take `*, idempotency_key` (`<token_id>:<step_index>`, with replay returning the existing record).
      - The D16 order replaces the old 4-step paragraph.
      - `ActionResult.audit_event_id` is the `readback` event id.
    - `04` §3:
      - The `POST /auth/otp/verify` errors (`401 otp_invalid`, `429 too_many_attempts`) and cookie re-issue.
      - The `/messages` `{text} | {resume:"step_up"}` body and `422`.
      - The `/confirmations/{token_id}` body `{decision}` → `202`, and `409 confirmation_invalid`.
    - `04` §5: the `tools.yaml` block with `step_up_window_minutes` and `allowed_intents`, and the combined-hash definition.
    - `04` §7: Redis `is_open`.
    - `03` §6: the three app tables' columns as built. `card_replacements` has `address_ref`/`address_changed` and no snapshot until D5-A1. `audit.audit_events` too.
    - `decision-log.md` L182: the row moves out of "Deferred" or is marked resolved, pointing at D3-A D4 (5-minute window in `tools.yaml`; an open plan dies at its own TTL, and `/confirmations` returns `401` after session expiry).
  - Verify: `grep -q "step_up_window_minutes" docs/solution-docs/04-contracts.md && grep -q "allowed_intents" docs/solution-docs/04-contracts.md && grep -q "confirmation_invalid" docs/solution-docs/04-contracts.md && grep -q "otp_invalid" docs/solution-docs/04-contracts.md && grep -q "idempotency_key" docs/solution-docs/03-data-architecture.md && grep -n "Step-up validity window" docs/solution-docs/decision-log.md`. Check that the last match shows the row as resolved, not under "Deferred".
  - Files:
    - `docs/solution-docs/04-contracts.md`
    - `docs/solution-docs/03-data-architecture.md`
    - `docs/solution-docs/decision-log.md`
