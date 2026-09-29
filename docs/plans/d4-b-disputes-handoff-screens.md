# Plan: D4-B — G9 disputes and fraud, and the handoff screens

Spec: [`docs/specs/d4-b-disputes-handoff-screens.md`](../specs/d4-b-disputes-handoff-screens.md) · Branch: `feat/d4-b-disputes-handoff-screens`

Spec open items, planned as the spec proposes them. If the human decided otherwise at the gate, the orchestrator seeds the answer into the state file. Only the named task changes.
- (1) Claim `description` is the code-built answers string, for example `"card_in_possession=no; contacted_merchant=yes"`, with no customer free text. Affects T4.
- (2) Settings defaults: `STAFF_DISPLAY_NAME = "Sofía"`, `STAFF_USERNAME = "agente"`. Affects T2.
- (4) On the compromise path, an already-blocked card keeps `block_card` in the plan. Affects T6.
- (3) Inbox filter and order belong to Dev A (A4). No task here implements them.

Execution model (human requirement): minimum tasks, with parallel waves where it is truly safe. Tasks in the same wave run **in parallel in one shared checkout** (no worktrees). Inside a wave no two tasks touch the same file, and no task's Verify depends on a sibling's output. Waves run in order W1 → W5.

## Facts checked against the repo

**Baseline on this branch (HEAD `a199c1a` = `develop`, D3-A + D3-B merged, stack up):**
- `cd backend && uv run pytest tests/unit -q` → **65 passed**.
- `uv run lint-imports` → 4 kept, 0 broken.
- `uv run mypy app` → clean, 108 files.
- A new red belongs to the task that caused it.

**Working tree:** the doc amendments the spec lists are already in the working tree (uncommitted, written at the spec phase):
- `04` §1/§3/§4/§5/§7
- `02` §3 and §4.8
- `03` §6 and §8
- `decision-log.md`: ADR-008 amended, `### D4-B D8` resolved

No task writes them from scratch. T10 checks they're still true and fixes only what a logged deviation contradicts.

**Commands and conventions (from the D2-A/D3-A/D3-B state files; still true):**
- Backend commands run as `cd backend && uv run …`.
- There is no pytest-asyncio. Drive coroutines with `asyncio.run(...)`.
- `get_settings()`, `get_engine()` and `get_redis()` are `lru_cache`d and loop-bound. `cache_clear()` them between a test's own `asyncio.run` and a `TestClient` request.
- Integration tests use `it_env`/`it_db`/`it_accounts`/`app_client` from `backend/tests/integration/conftest.py`:
  - `it_db` is session-scoped: one migrated `latam_it_<hex>` DB per pytest process.
  - It is loaded from `tests/fixtures/fakebank/{customers,products}.csv` and every `transactions/**/*.csv`.
  - `_insert_accounts` inserts rows with no `role`, so they get the default `'customer'`.
- `it_env` teardown deletes the Redis keys `rl:login:*`, `turn:*`, `conv:*`, `conf:*` and `rl:otp:*` **globally** (the real dev Redis).
- An integration Verify must fail on a skip: pipe through `tail -1 | grep -E '^N passed(, [0-9]+ warnings?)? in'`.
- Errors are `HTTPException(status, detail="<code>")`. Dependencies use the `Annotated[X, Depends(...)]` style.
- Tests use `ScriptedLLM` (`backend/tests/conftest.py`), never a real provider.
- Checkouts are CRLF (`core.autocrlf=true`). The fixture CSVs are UTF-8 **with BOM** and CRLF (`tests/fixtures/fakebank/README.md`).
- Never `git add`, `git commit` or push. The orchestrator commits.

**mypy / import-linter:**
- mypy strict covers `app.core.*`, `app.domains.conversation.*` and `app.domains.policy.*`.
- `make check` runs `uv run mypy app` (whole package). mypy follows imports: a scoped run (`mypy <files>`) also checks what those files import, but not what imports them.
- `conversation.tools.registry` is where `FakeBankWrites` and `PostgresBankWrites` are checked against the `BankWriteTools` Protocol. Neither `graph.py`, `flows/*`, `executor.py`, `fakebank.py` nor `sandbox.py` imports `registry`.
- The `conversation-no-repository` contract defaults to `error` for an ignore edge whose import doesn't exist yet. **A new ignore edge lands in the same task as its import.**
- No contract stops another domain importing `app.domains.conversation.templates`. `templates.py` imports nothing from `app`.

**Database:**
- Alembic head is `0004` (`backend/app/alembic/versions/0001…0004`, string ids `"0001"`…`"0004"`).
- **The live `latam_app` and `latam_golden` are at `0002`** (checked: no `app.card_*` tables, and `identity.accounts` is 150000 `customer` rows). Until `make seed-identity` runs (T10), the live stack has neither the D3-A tables nor `0005`.
- `bank.complaints` (in `0001`) has PK `complaint_id text` and already has `origin`, `created_at` and `conversation_id`. It has no `transaction_id` or `idempotency_key`.
- `identity.accounts` (in `0002`): `customer_id` is NOT NULL, UNIQUE, with an FK to `bank.customers`; `role text default 'customer'`; `login_key` is unique.
- `pipeline/load/postgres.py` COPYs with an explicit column list (from the `srv_*` models) and TRUNCATEs `identity.accounts`. New nullable columns don't break `make data`.
- Migration check pattern (D3-A T3), on the container `latam-cs-postgres-1`: create `latam_mig_check`, then upgrade/downgrade/upgrade with `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check`, then drop it.

**Fixture data (`backend/tests/fixtures/fakebank/`):**

| Customer | Card | Transactions today |
|---|---|---|
| `CLI-TFMULTI00001` (MX) | several | `TRX-TFM1CRED0001TXN01` (on `PRD-TFM1CRED0001`, 150.25 USD, Approved), `TRX-TFM1DEBT0002TXN01` (on `PRD-TFM1DEBT0002`, Approved) |
| `CLI-TFSINGLE0002` (CO) | one: `PRD-TFS2CRED0001`, last4 2222 | `TXN01` (85000 COP, Approved, fraud 0.02), `TXN02` (500000 COP, Approved, fraud 0.0) |
| `CLI-TFBLOCKD0003` | — | one Declined, one Approved |
| `CLI-TFPASTD00005` (AR) | one: `PRD-TFP5CRED0001`, last4 5555 | none |

- `fraud_score` in the fixture is ≤ 0.03. No existing test asserts transaction counts, so adding rows is safe.

**Code on disk that this card extends:**
- `TxView.fraud_score: Decimal | None`. `TxFilter.status: list[TxStatus]`, where `TxStatus = Approved|Declined|Pending|Reversed`.
- `transactions.service` has only `search(customer_id, tx_filter)`. **There is no lookup by transaction id**, so T4 adds one. This is an addition to the spec's touch map.
- `FakeBank.search_transactions` caps at 10 rows, newest first, with an ownership probe on `card_id`. `PostgresBank.search_transactions` likewise.
- `localization/format.py` has:
  - `format_money(amount, currency, country)`, `format_date(d)`, `mask_card(last4)`, `local_today`, `format_time`.
  - `queue_label(queue, language)` and `Queue = Literal["atencion","cobranza","fraudes"]`.
- `flows/actions.py`:
  - `start_plan(state, config, *, flow, tool, args, summary_key, view_facts, confirm_values, intent)` issues a **one-step** plan.
  - Its callers are `card_block.py` (~L224), `card_unlock.py` (~L212) and `replacement.py` (~L263).
  - It also has `decision`, `cancel`, `execute`, `handoff`, `otp_pause` and `fill`.
- `executor.ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up, allowed, audit)`:
  - `_run` follows the D16 order and passes the key `f"{token_id}:{step_index}"`.
  - On `AccessDenied`, only `get_block_origin` records `access_denied`. `_run` does not.
- The in-memory store raises `ConfirmationRequired("step_mismatch")` / `("unknown_or_expired")`.
- `policy/confirmation.py`: `ToolArg = str | int | bool | None`.
- `ActionResult` (`core/actions.py`) is frozen, `extra="forbid"`, and has no `case_ids`.
- `ui.py`: `UIEvent` is a discriminated union of `confirm | otp_required | conversation_closed | card_picker | quick_replies`. There is no `transaction_list` or `handoff_banner`.
- `graph.py`:
  - `ConfirmationDecision` lives here and the API imports it from here.
  - `TurnInput{user_text, confirmation?, resume?}`, `_entry`, `_INTENT_NODES`, `_FLOW_NODES`, `_BRANCH_NODES`.
  - `run_turn(graph, text, *, config, confirmation, resume)`.
  - `Intent` (`schemas.py`) already contains `unrecognized_charge`.
- `nodes/route.py`: `_CONFIRMATION_SLOTS = {"confirmation","address_confirm","offer_replacement"}` are the affirm/deny slots.
- `runner.py`:
  - `start_turn(host, *, session, conversation_id, trace_id, text=None, resume=None, confirmation=None)`, exactly one of the three.
  - `checkpointed_confirmation_token(host, id)`.
  - `_run_turn` builds `config["configurable"]` = `thread_id, session, bank_tools, llm, bank_write_tools, vault`, and keeps a copy of `_BRANCH_NODES`.
- `tests/conftest.py`: `make_session(customer_id, fakebank_dir, llm, *, otp_code, raw_writes, clock)` builds the same config keys and returns `Session(graph, config, gate, store, overlay)`.
- `sandbox.py`:
  - `_RecordingWriteTools` mirrors every raw write.
  - `_build_session` builds the config without `handoff`.
  - It imports `get_policies`, not `registry`.
- `identity`:
  - `Session{account_id, role: Literal["customer"], customer_id: str, step_up_at}` and `TokenClaims`, the same shape.
  - `service.login()` never checks `role`.
  - `me()`, `mint_session_for_customer` and `refresh` exist.
  - `passwords.login_key` hashes `doc:<TYPE>:<NUMBER>`, and `generate_password(key, seed=)`.
  - `provision.main()` does TRUNCATE + COPY customers and writes the git-ignored `data/secrets/credentials.csv`.
- `Session.customer_id` call sites that break when it becomes `str | None`:
  - `api/v1/conversations.py` (`create_conversation`, and `RedisConfirmationStore(...)` in `post_confirmation`; the comparison in `get_owned_conversation` still type-checks)
  - `conversation/tools/registry.py` (`build_tool_context`)
  - `identity/service.py` (`me`, `mint_session_for_customer`)
- `api/v1/auth.py`:
  - `public_router` has `/auth/login` and `/auth/refresh` (CSRF, no role).
  - `router` has `require_role("customer")` + `require_csrf` and holds `/auth/logout`, `/auth/me` and `/auth/otp/verify`.
- `api/v1/__init__.py` mounts health, auth public, auth and conversations.
- `test_r13_routes.py`: `_EXEMPT_PATHS = {/api/v1/health, /api/v1/auth/login, /api/v1/auth/refresh}`, and it detects `RoleGuard` instances in route dependencies.
- `test_r6_no_write_tools_in_llm_nodes.py` substring-scans every `nodes/`/`flows/` module that AST-imports `app.core.llm` for `_FORBIDDEN_NAMES`. Today those modules (`compose`, `understand`, `next_intent`) contain the word "handoff" zero times.
- `test_personas.py::test_personas_match_golden` validates a **closed** trait vocabulary against `latam_golden`. `customer_id` and `notes` are not traits. No trait exists for `fraud_score`, so the demo persona carries it in `notes`.
- `scripts/chat_api.py` has `/otp`, `/confirm`, `/cancel`, `/replay`, and reads credentials from `data/secrets/credentials.csv`.

**Frontend:**
- **There is no Node on the host** (`which node` fails). All frontend commands run in Docker (D3-B human decision Q1b), from the repo root in Git Bash:
  - NODE-RO: `MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules:ro -w /app node:22.22-bookworm sh -c '<cmd>'`. The volume `d3b_frontend_node_modules` exists and is populated.
  - PW: `MSYS_NO_PATHCONV=1 docker run --rm --ipc=host -v "$(pwd -W)/frontend:/app" -v /app/node_modules -w /app mcr.microsoft.com/playwright:v1.63.0-noble sh -c 'npm ci && npm run build && npx playwright test <spec>'`.
- `npm run build` = `vite build && tsc -b`. It writes `frontend/dist/` and regenerates `src/routeTree.gen.ts` (git-ignored).
- `make client` = `cd frontend && npx @hey-api/openapi-ts`. `openapi-ts.config.ts` reads `http://localhost/api/v1/openapi.json`, writes to `src/client`, and has `plugins: [{name: "@hey-api/client-fetch", baseUrl: false}]`. It can't run on the host, because there is no Node there.
- Biome ignores `src/client` and `src/routeTree.gen.ts`.
- Generated SDK urls are single-quoted: `url: '/api/v1/…'`.
- `src/lib/api.ts`:
  - The CSRF interceptor is a side effect of importing it.
  - `withAuthRetry` does refresh-then-`/login`.
  - Wrappers: `postMessage`, `postResume`, `postConfirmation`, `verifyOtp`, `conversationStore`.
- `src/lib/sse.ts`: `openConversationStream`, with typed `UiEvent` = the five current kinds. It has no `mode` handler.
- i18n uses one flat `errors.<code>` namespace. `es.json` and `pt.json` must have identical key sets; the D3-B parity script checks this.
- `ConfirmCard` renders `confirm.steps.<summary_key>`.
- `AppShell` (in `__root.tsx`) calls `me()` (`/auth/me`) on every route. An agent session gets `403`, the query errors, and the customer greeting stays hidden. This is acceptable: staff pages render their own header.
- `e2e/mock-api.ts` `installMockApi(page, {password, fixtures, customer?})` records every `/messages` body as-is, so a `{selection}` body needs no mock change.
- The e2e specs import JSON with `with { type: "json" }`.
- `@playwright/test` is pinned to `1.63.0`.

**Settings:** `app/core/config.py` has `bank`, `demo_otp_code`, `login_max_failures`, `login_window_seconds`, `session_ttl_minutes`, `credentials_seed` and `identity_hmac_key`. It has no staff settings.

## Cross-task names (pinned by this plan)

Later tasks rely on these exact names. An implementer who must deviate logs it in the state file.
- `app.domains.policy.disputes`:
  - `DisputesPolicy`, and `load_disputes_policy(path=None)` (lru-cached or not, like `load_escalation_policy`).
  - **`DisputesPolicy.triggers_compromise(picked_count: int, max_fraud_score: Decimal | None) -> bool`**: count ≥ `min_picked` or score > `fraud_score_gt`.
  - The flow calls this and never reads the two threshold attributes itself. SC2 greps for their names outside the model.
- `app.domains.identity`:
  - In `models.py`: `require_customer_id(session) -> str`, `StaffLoginRequest`, `StaffMeResponse`.
  - In `passwords.py`: `staff_login_key(username: str, *, hmac_key: str) -> str` = hex HMAC-SHA256 of `staff:<username>`.
  - In `service.py`: `staff_login(req, *, store=None, limiter=None, settings=None) -> Session` and `staff_me(session) -> StaffMeResponse`.
  - In `core/config.py`: `staff_username`, `staff_display_name`.
- `app.domains.handoff`: `schemas.py` (the spec's models + `HandoffPort`) and `memory.InMemoryHandoffPort(conversation_id, policy_version)` with `.packets`. Template kind `handoff_request`.
- `app.domains.conversation.graph.TxSelection` (`tx_ids`: 1–10 unique, frozen, `extra="forbid"`). It sits next to `ConfirmationDecision`, because the API imports both from here.
- Tool args:
  - `ConfirmedWriteTools.create_claim(tx_ids: list[str], answers: list[str], token_id: str)`. Its plan-step args are exactly `{"tx_ids": tx_ids, "answers": answers}`, with no re-sorting inside, so the caller passes `answers` already sorted.
  - The raw key is `f"{token_id}:{step_index}"`. The raw write appends `:<tx_id>` per row.
- `config["configurable"]["handoff"]`: a `HandoffPort`.
- `runner.start_turn(..., selection: TxSelection | None = None)` and `runner.checkpointed_dispute(host, conversation_id)`.

## Components

| Component | Where | Depends on |
|---|---|---|
| Disputes policy + `triggers_compromise`; tools allowlist; `ToolArg` list form | `policies/{disputes,tools}.yaml`, `backend/app/domains/policy/{disputes,registry,confirmation}.py` | — |
| Migration `0005_claims_staff` | `backend/app/alembic/versions/0005_claims_staff.py` (new) | `0004` |
| Identity: typed session, staff login, staff provisioning | `backend/app/domains/identity/*`, `backend/app/core/config.py` | `0005` at run time (repository columns) |
| Handoff contract + in-memory port | `backend/app/domains/handoff/{__init__,schemas,memory}.py` (new) | `conversation/templates.py` (`handoff_request`), `localization.format.Queue` |
| Shared result/UI/input types | `core/actions.py` (`case_ids`), `conversation/ui.py` (two events), `conversation/graph.py` (`TxSelection`) | — |
| Claim write path | `domains/transactions/{repository,service}.py` (lookup by ids), `domains/disputes/*` (new), `conversation/tools/{write,executor,fakebank,postgres_writes}.py`, `sandbox._RecordingWriteTools` | policy (`ToolArg`, `tools.yaml`), `case_ids`, `0005` |
| Staff + messages API surface, generated client | `api/v1/{auth,staff,__init__,conversations}.py`, `frontend/src/client/` | identity, handoff schemas, `TxSelection` |
| `unrecognized_charge` flow + graph wiring + multi-step plans | `conversation/{state,graph,templates}.py`, `nodes/route.py`, `flows/{actions,unrecognized_charge,card_block,card_unlock,replacement}.py` | claim write path (executor + FakeBank), handoff port, policy |
| Runner/route gate, sandbox, `make chat-api /pick` | `conversation/runner.py`, `api/v1/conversations.py`, `conversation/sandbox.py`, `scripts/chat_api.py` | flow, Postgres claim path |
| Customer widgets | `frontend/src/components/chat/*`, `routes/chat.tsx`, `lib/{api,sse}.ts`, i18n | generated client |
| Staff screens | `frontend/src/routes/staff/*`, `components/staff/*`, `lib/api.ts`, i18n | generated client, customer widgets task (shared `api.ts`/i18n) |

## Build order

1. **W1**: contracts that nothing else in the card has to exist for. These are the policy, the migration, identity, and the handoff/result/UI/input types. Everything later imports one of them.
2. **W2**: the claim write path and the staff/messages API surface. The claim path needs `ToolArg` lists, the `tools.yaml` allowlist, `case_ids` and `0005`. The API needs typed sessions, handoff schemas and `TxSelection`. The OpenAPI contract is final after W2, so the client is regenerated there.
3. **W3**: the flow (it needs the executor and FakeBank `create_claim`, the port and the policy) and the customer widgets (they need the generated client).
4. **W4**: the runner and route gate (they need the flow's `dispute` state and the Postgres claim path, so the whole of `mypy app` holds), and the staff screens (they come after the customer widgets because of the shared `api.ts`, i18n and build outputs).
5. **W5**: live end-of-day checks. They need everything, plus `make seed-identity` to bring the live DBs from `0002` to `0005`.

## Parallel waves

| Wave | Tasks | Why the group is safe |
|---|---|---|
| W1 | T1, T2, T3 | Touch maps are disjoint: T1 only `policies/`, `policy/` and the new migration; T2 only `identity/`, `config.py` and two one-line call-site narrowings (`api/v1/conversations.py`, `tools/registry.py`); T3 only `handoff/` (new), `core/actions.py`, `ui.py`, `templates.py` and `graph.py`. `tools.yaml` and the migration chain are T1's alone. No `.importlinter`, `main.py`/`v1/__init__.py`, client, package or fixture file is touched. No Verify reads a sibling's output: T2's checks are unit-only (the `0005` columns are proved in W2), and T3 doesn't use `ToolArg` lists |
| W2 | T4, T5 | Touch maps are disjoint: T4 is `transactions/`, `disputes/`, `tools/{write,executor,fakebank,postgres_writes}.py`, `sandbox.py`, `.importlinter` and its two test files; T5 is `api/v1/*`, `test_auth.py`, `test_r13_routes.py` and `frontend/src/client/`. Each pytest process builds its own `latam_it_<hex>` DB. The shared Redis cleanup can't hurt either: T4's tests use no Redis keys (in-memory confirmation store, no login), and T5 runs only its new test by node id (its single login reads the rate-limit counter and never depends on it). T5's staff account is inserted by a fixture inside `test_auth.py`, so `tests/integration/conftest.py` is untouched |
| W3 | T6, T7 | T6 is backend only (it owns `tests/conftest.py` and the fixture CSVs, which no sibling touches). T7 is frontend only and never runs or imports the backend (the client was generated in W2). T7 is the wave's only frontend task, so its `npm ci`/`npm run build` (`dist/`, `routeTree.gen.ts`) has no competitor |
| W4 | T8, T9 | T8 is backend only (`runner.py`, `conversations.py`, `sandbox.py`, `chat_api.py`, one integration test). T9 is frontend only and the wave's only frontend task |
| W5 | T10 | Live stack checks, alone |

The frontend tasks T7 and T9 **cannot** share a wave, for three reasons. Both edit `lib/api.ts`, `es.json` and `pt.json`. Both `npm run build` into the same `frontend/dist/` and regenerate `src/routeTree.gen.ts`. And the node image mounts one shared `node_modules` volume. A separate "frontend foundation" task would buy nothing: the frontend would still take two waves, at the cost of one more task.

**Shared-checkout rule, for every wave:**
- A sibling's half-finished edit can make a whole-package command (`mypy app`, `lint-imports`, a pytest collection that imports `tests/conftest.py`, the OpenAPI dump) fail on a file your task doesn't own. When that happens, wait for the sibling to finish and rerun.
- Never edit a sibling's file.
- A failure that persists after the sibling is done is escalated, not patched across ownership.

## Touch map

| File | New/Mod | Task | Change |
|---|---|---|---|
| `policies/disputes.yaml` | new | T1 | spec §Contracts, verbatim |
| `policies/tools.yaml` | mod | T1 | `disputes.create_claim` row; `cards.block_card.allowed_intents` += `unrecognized_charge` |
| `backend/app/domains/policy/disputes.py` | new | T1 | `DisputesPolicy`, `triggers_compromise`, `load_disputes_policy` |
| `backend/app/domains/policy/registry.py` | mod | T1 | `"disputes": DisputesPolicy` in `_MODELS_BY_STEM` |
| `backend/app/domains/policy/confirmation.py` | mod | T1 | `ToolArg` += `list[str]` |
| `backend/app/alembic/versions/0005_claims_staff.py` | new | T1 | complaints + accounts changes |
| `backend/app/domains/identity/{models,tokens,service,repository,passwords,provision}.py` | mod | T2 | D3/D4; staff login; staff row + `staff_credentials.csv` |
| `backend/app/core/config.py` | mod | T2 | `staff_username`, `staff_display_name` |
| `backend/app/api/v1/conversations.py` | mod | T2, T5, T8 | T2: `require_customer_id` at two sites; T5: `selection` body, interim `409`; T8: real D7 gate |
| `backend/app/domains/conversation/tools/registry.py` | mod | T2 | `require_customer_id` in `build_tool_context` |
| `backend/app/domains/handoff/{__init__,schemas,memory}.py` | new | T3 | D1 contract, in-memory port |
| `backend/app/core/actions.py` | mod | T3 | `case_ids: list[str] \| None = None` |
| `backend/app/domains/conversation/ui.py` | mod | T3 | `TxOption`, `TransactionListPayload/Event`, `HandoffBannerPayload/Event` in `UIEvent` |
| `backend/app/domains/conversation/templates.py` | mod | T3, T6 | T3: `handoff_request`; T6: the dispute templates |
| `backend/app/domains/conversation/graph.py` | mod | T3, T6 | T3: `TxSelection`; T6: `selection` channel, step 0, node, `run_turn(selection=)` |
| `backend/app/domains/transactions/{repository,service}.py` | mod | T4 | own-row lookup by ids (not in the spec's touch map; needed by "reads each transaction through `transactions.service`") |
| `backend/app/domains/disputes/{__init__,schemas,repository,service}.py` | new | T4 | `create_claims`, `get_claims`, one transaction |
| `backend/app/domains/conversation/tools/{write,executor,fakebank,postgres_writes}.py` | mod | T4 | `create_claim` end to end; executor records `access_denied` |
| `backend/app/domains/conversation/sandbox.py` | mod | T4, T8 | T4: `_RecordingWriteTools.create_claim`; T8: `handoff` config key |
| `backend/.importlinter` | mod | T4 | `postgres_writes -> disputes.service` |
| `backend/tests/unit/test_r2_confirmed_writes.py` | mod | T4 | stub `create_claim` + `test_compromise_plan_order_and_allowlist` |
| `backend/tests/integration/test_postgres_disputes.py` | new | T4 | B1 Done-when, R1 |
| `backend/app/api/v1/auth.py` | mod | T5 | staff login; logout router `customer,agent`; refresh 403 for agent |
| `backend/app/api/v1/staff.py` | new | T5 | `/staff/me` + six `501` routes |
| `backend/app/api/v1/__init__.py` | mod | T5 | mount staff + logout routers |
| `backend/tests/integration/test_auth.py` | mod | T5 | `test_staff_login_and_role_split` + local staff-account fixture |
| `backend/tests/unit/test_r13_routes.py` | mod | T5 | exempt `/auth/staff/login`; staff routes guard `("agent",)` |
| `frontend/src/client/**` | regen | T5 | generated, no hand edits |
| `backend/app/domains/conversation/state.py` | mod | T6 | `DisputeState`, `TurnState.dispute` |
| `backend/app/domains/conversation/nodes/route.py` | mod | T6 | `card_possession`, `dispute_question` as affirm/deny slots |
| `backend/app/domains/conversation/flows/actions.py` | mod | T6 | `start_plan(steps=[...])`, `execute_plan` |
| `backend/app/domains/conversation/flows/{card_block,card_unlock,replacement}.py` | mod | T6 | call-site update for the new `start_plan` |
| `backend/app/domains/conversation/flows/unrecognized_charge.py` | new | T6 | the flow |
| `backend/tests/conftest.py` | mod | T6 | `make_session` adds `handoff` (and exposes it on `Session`) |
| `backend/tests/fixtures/fakebank/transactions/…/transactions_20260330.csv`, `README.md` | mod | T6 | new rows (see T6) |
| `backend/tests/unit/test_dispute_flows.py` | new | T6 | five tests |
| `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` | mod | T6 | `handoff` forbidden |
| `frontend/src/lib/{api.ts,sse.ts,i18n/es.json,i18n/pt.json}` | mod | T7, T9 | T7: selection, UI kinds, `mode`; T9: staff wrappers, 401 → `/staff/login`, staff keys |
| `frontend/src/components/chat/{TransactionList,HandoffBanner,ModeIndicator}.tsx` | new | T7 | B3 widgets |
| `frontend/src/components/chat/MessageList.tsx`, `frontend/src/routes/chat.tsx` | mod | T7 | render the new kinds, header mode |
| `frontend/e2e/unrecognized.es.spec.ts`, `frontend/e2e/fixtures/unrecognized-*.sse` | new | T7 | B3 e2e |
| `backend/app/domains/conversation/runner.py` | mod | T8 | `selection`, `checkpointed_dispute`, `handoff` key, `_BRANCH_NODES` |
| `backend/scripts/chat_api.py` | mod | T8 | `/pick <n,…>` |
| `backend/tests/integration/test_confirmations_route.py` | mod | T8 | `test_injected_tx_id_is_409` |
| `frontend/src/routes/staff/{login,index,handoffs.$handoffId}.tsx` | new | T9 | B4 screens |
| `frontend/src/components/staff/{InboxList,PacketView,AgentChat}.tsx` | new | T9 | B4 components |
| `frontend/e2e/staff.es.spec.ts`, `frontend/e2e/mock-staff-api.ts` | new | T9 | B4 e2e (own mock file, so `mock-api.ts` stays T7's) |
| `eval/personas.yaml` | mod | T10 | one demo persona (`notes` only for the score) |
| `docs/solution-docs/{02,03,04,decision-log}.md` | mod (only if a deviation needs it) | T10 | reconcile the pre-written amendments |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| SC2 (`grep fraud_score_gt\|min_picked` shows only the policy model) fails because the flow reads `policy.compromise.min_picked` | T1 puts the comparison in `DisputesPolicy.triggers_compromise`. T6 calls only that. T6's Verify runs the grep (with `--include=*.py`, so `__pycache__` doesn't match) |
| Adding `create_claim` to the `BankWriteTools` Protocol breaks `mypy app` until every implementer has it | T4 owns the Protocol, `FakeBankWrites`, `PostgresBankWrites` and the sandbox recorder together, and runs `mypy app` |
| `Session.customer_id: str \| None` breaks mypy at the call sites | T2 narrows every site (`conversations.py`, `registry.py`, `identity/service.py`) with `require_customer_id` and runs `mypy app` |
| `0005` downgrade fails once an agent row exists (NOT NULL can't be restored) | T1's `downgrade()` deletes `role='agent'` rows, drops the CHECK and the columns, then restores NOT NULL. Its Verify runs upgrade → downgrade `0004` → upgrade |
| A tx id that wasn't offered, or a foreign one, gets claimed (R1, human Q6) | Three gates: the route (T8, `409 selection_invalid`, no turn scheduled); the flow re-check against `dispute.offered_tx_ids` (T6); the service own-row check before any write (T4, `AccessDenied`, audited). Tests: T8 and T4 |
| `customer_id` taken from a selection or an argument (R1) | `create_claims` takes `customer_id` only from `ToolContext`/the `Session` (T4). `require_customer_id` is the only path (T2). `test_r1_customer_scope.py` still runs in `make check` |
| Claim rows half-written (R12), or doubled on replay | T4: all rows are written in one `engine.begin()` transaction; per-row unique key `<token_id>:<step_index>:<tx_id>`; a replay re-reads and returns the existing rows (tested) |
| A "done" or case ID shown from a stale write (R3) | T4: `verified` comes from a separate re-read of every row (tested with a stubbed stale re-read). T6: the case ID reaches the reply and the banner only from a verified `ActionResult.case_ids` |
| An LLM node reaches `handoff` or write tools (R6) | The port lives only in `config["configurable"]["handoff"]` (T6, T8). T6 adds `handoff` to the R6 test's forbidden names. The current LLM modules contain the word zero times, so no false positive |
| An agent session reaches customer routes, or a customer reaches staff routes (R13) | T5: router-level `RoleGuard`; `/auth/refresh` returns `403` for an agent; the R13 test is extended; `test_staff_login_and_role_split` |
| The pick turn calls the LLM, or the selection is persisted as a message | T6: step 0 in `_entry` skips `understand`; the flow tests assert no `nlu` call on the pick turn (`ScriptedLLM.calls`). T8: `start_turn` persists only `text` |
| The live DBs are at `0002`, so live checks run against the wrong schema | T10 runs `make seed-identity` first. If the sandbox denies its `DROP DATABASE` (D3-A T13 history), T10 stops and escalates. It doesn't retry through another route |
| There is no host Node, so `make client` can't run as written | T5 dumps OpenAPI offline and runs the same generator and config in the Node image. T10 regenerates against the live backend and diffs, proving no drift |
| Parallel siblings interfere through the shared Redis cleanup | W2 analysis above: T5 runs only `::test_staff_login_and_role_split`. T4's tests use no Redis keys |
| Staff credentials leak | T2 writes them only to the git-ignored `data/secrets/staff_credentials.csv` (mode `0600`) and never prints or logs the username/password pair. T10 reads them without echoing |
| Fixture CSV edits break the encoding (BOM/CRLF), so every FakeBank/it_db test fails | T6 appends rows keeping the BOM and CRLF. Its Verify runs the existing fixture-reading tests (`test_card_info_flows.py`, `test_block_flows.py`) |
| The staff SPA loops on refresh (an agent's `/auth/refresh` is `403`) | T9: the staff wrappers send any `401` straight to `/staff/login`, with no refresh attempt (D5) |

## Tests

| Spec test | Task |
|---|---|
| `unit/test_dispute_flows.py::test_compromise_path[es-two_picked, pt-possession_no, es-score_gt_30]` | T6 |
| `unit/test_dispute_flows.py::test_single_charge_questions_claim[es, pt]` | T6 |
| `unit/test_dispute_flows.py::test_no_transactions_writes_nothing` | T6 |
| `unit/test_dispute_flows.py::test_refused_block` | T6 |
| `unit/test_dispute_flows.py::test_transaction_list_labels_from_code` | T6 |
| `unit/test_r2_confirmed_writes.py::test_compromise_plan_order_and_allowlist` | T4 |
| `unit/test_r6_no_write_tools_in_llm_nodes.py` (+ `handoff`) | T6 |
| `integration/test_postgres_disputes.py::test_claim_row_matches_transaction` | T4 |
| `integration/test_postgres_disputes.py::test_foreign_transaction_refused` | T4 |
| `integration/test_confirmations_route.py::test_injected_tx_id_is_409` | T8 |
| `integration/test_auth.py::test_staff_login_and_role_split` | T5 |
| `unit/test_r13_routes.py` (allowlist + `/auth/staff/login`) | T5 |
| `e2e/unrecognized.es.spec.ts` | T7 |
| `e2e/staff.es.spec.ts` | T9 |

Success criteria coverage:
- SC1: T4 (tests), T10 (live SQL)
- SC2: T6 (tests + grep), T1 (the values in YAML)
- SC3: T4, T6, T1
- SC4: T8
- SC5: T7
- SC6: T5 (tests, OpenAPI, client), T9 (e2e)
- SC7: the verifier's `make check`; T10 (doc amendments)
- SC8: deferred to A3/A4

## Tasks

- [ ] T1: Disputes policy, tools allowlist, `ToolArg` list form, and migration `0005_claims_staff`
  - Wave: 1
  - Depends on: nothing.
  - Read exactly these:
    - spec §Contracts "`policies/disputes.yaml`" and "Migration `0005_claims_staff`", and D8, D15, D17, D18, D23
    - `backend/app/domains/policy/escalation.py` (the loader analogue)
    - `backend/app/alembic/versions/0004_audit_events.py` (the migration analogue)
  - Acceptance:
    - `policies/disputes.yaml` is exactly the spec block, with `min_picked: 2` and `fraud_score_gt: 30`.
    - `policy/disputes.py` has these (`provenance: Literal["team-generated-synthetic"]`, frozen, `extra="forbid"`, like `escalation.py`):
      - `DisputesPolicy` with nested models
      - `triggers_compromise(picked_count, max_fraud_score) -> bool` (count ≥ `min_picked` or score > `fraud_score_gt`; `None` score never triggers)
      - `load_disputes_policy(path=None)`
    - `policy/registry.py` validates the `disputes` stem against `DisputesPolicy`. `PolicyBundle` is unchanged, so the file stays optional for the bundle.
    - `tools.yaml` gains `disputes.create_claim: {requires_confirmation: true, step_up: never, allowed_intents: [unrecognized_charge]}`, and `cards.block_card.allowed_intents` becomes `[card_block, unrecognized_charge]`.
    - `ToolArg = str | int | bool | None | list[str]`, and `args_hash` stays canonical for lists.
    - `0005` (revision `"0005"`, down `"0004"`):
      - `bank.complaints` gains `transaction_id text null` and `idempotency_key text unique null`.
      - `identity.accounts.customer_id` becomes nullable (FK and unique stay), and the table gains `username text unique null` and `display_name text null`.
      - The CHECK is `(role='customer' AND customer_id IS NOT NULL) OR (role='agent' AND customer_id IS NULL AND username IS NOT NULL)`.
      - `downgrade()` deletes `role='agent'` rows before restoring NOT NULL, and reverses everything else.
  - Verify: `docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE IF EXISTS latam_mig_check" -c "CREATE DATABASE latam_mig_check" && cd backend && export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check && uv run alembic upgrade head && uv run alembic downgrade 0004 && uv run alembic upgrade head && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from information_schema.columns where (table_schema,table_name,column_name) in (('bank','complaints','transaction_id'),('bank','complaints','idempotency_key'),('identity','accounts','username'),('identity','accounts','display_name'))")" = 4 && docker exec latam-cs-postgres-1 psql -U postgres -c "DROP DATABASE latam_mig_check" && unset DATABASE_URL && uv run pytest tests/unit/test_policy_registry.py tests/unit/test_r2_confirmation_store.py -q && uv run python -c "from decimal import Decimal as D; from app.domains.policy.disputes import load_disputes_policy as l; p=l(); assert p.triggers_compromise(2, None) and p.triggers_compromise(1, D('30.01')) and not p.triggers_compromise(1, D('30')); from app.domains.policy.registry import load_policies; assert 'disputes' in load_policies().files; from app.domains.policy.tools_policy import load_tools_policy, tool_allowed; a=tool_allowed(load_tools_policy()); assert a('unrecognized_charge','disputes.create_claim') and a('unrecognized_charge','cards.block_card') and not a('card_block','disputes.create_claim'); from app.domains.policy.confirmation import args_hash; assert args_hash('t',{'x':['a','b']})!=args_hash('t',{'x':['b','a']})" && uv run mypy app/domains/policy && uv run ruff check app/domains/policy app/alembic/versions/0005_claims_staff.py && uv run ruff format --check app/domains/policy app/alembic/versions/0005_claims_staff.py`
  - Files: `policies/disputes.yaml` (new), `policies/tools.yaml`, `backend/app/domains/policy/disputes.py` (new), `backend/app/domains/policy/registry.py`, `backend/app/domains/policy/confirmation.py`, `backend/app/alembic/versions/0005_claims_staff.py` (new)

- [ ] T2: Identity: typed customer/agent session, staff login service, and staff provisioning
  - Wave: 1
  - Depends on: nothing at build time. The `username`/`display_name` columns come from T1's `0005`, but they are exercised only by later integration tests. This task's proofs are unit-level.
  - Read exactly these:
    - spec D3, D4, D5 and §Contracts "Identity" (plus "Provisioning")
    - `backend/app/domains/identity/service.py` (`login()` is the analogue for `staff_login`)
    - `backend/app/domains/identity/provision.py`
  - Acceptance:
    - `Session` and `TokenClaims`:
      - `Session.role: Literal["customer","agent"]` and `customer_id: str | None`.
      - A model validator enforces customer ⇔ `customer_id` set, agent ⇔ `None`.
      - `TokenClaims` changes the same way. Issue and decode round-trip an agent session.
    - `models.py` adds `require_customer_id(session) -> str` (raises on `None`), `StaffLoginRequest{username, password}` (frozen) and `StaffMeResponse{role: Literal["agent"], display_name}`.
    - `passwords.staff_login_key(username, *, hmac_key)` = hex HMAC-SHA256(`staff:<username>`).
    - `repository.AccountRow`:
      - gains `customer_id: str | None`, `username: str | None = None` and `display_name: str | None = None`, with defaults so the existing fakes in `test_login_pii.py` still build
      - the selects return the new columns
      - there's a lookup by `account_id` for `staff_me`
    - `service.login()` accepts only `role='customer'`. Any other role counts as `InvalidCredentials` (same limiter, same message).
    - `service.staff_login(req, …)`:
      - accepts only `role='agent'`
      - `login_key` = `staff_login_key(req.username, …)`, using the same `rl:login:<key>` limiter
      - `429` is checked first
      - failures log only `login_key_prefix`
      - it returns `Session(role="agent", customer_id=None)`
    - `service.staff_me(session) -> StaffMeResponse`.
    - `me()` and `mint_session_for_customer` narrow through `require_customer_id`.
    - `core/config.py` adds `staff_username: str = "agente"` and `staff_display_name: str = "Sofía"`.
    - `provision.main()`:
      - also inserts one agent row: `customer_id NULL`, `username`, `display_name`, `login_key = staff_login_key`, and password `generate_password(f"staff:{username}", seed=CREDENTIALS_SEED)`, hashed, all in the same transaction
      - writes `data/secrets/staff_credentials.csv` (`username,password`, mode `0600`)
      - never prints either value
    - Call sites narrowed with `require_customer_id`, with no other change:
      - `api/v1/conversations.py`: `create_conversation`, and the `RedisConfirmationStore(...)` in `post_confirmation`
      - `conversation/tools/registry.py`: `build_tool_context`
  - Verify: `cd backend && uv run pytest tests/unit/test_login_pii.py tests/unit/test_audit_pairs.py tests/unit/test_r1_routes.py -q && uv run python -c "import app.domains.identity.provision" && uv run python - <<'EOF' && uv run mypy app && uv run ruff check app/domains/identity app/core/config.py app/api/v1/conversations.py app/domains/conversation/tools/registry.py && uv run ruff format --check app/domains/identity app/core/config.py app/api/v1/conversations.py app/domains/conversation/tools/registry.py
from uuid import uuid4
from pydantic import ValidationError
from app.domains.identity.models import Session, require_customer_id
from app.domains.identity.tokens import issue_token, decode_token
agent = Session(account_id=uuid4(), role="agent", customer_id=None, step_up_at=None)
tok, _ = issue_token(agent, secret="s" * 32, ttl_minutes=5)
back = decode_token(tok, secret="s" * 32).to_session()
assert back.role == "agent" and back.customer_id is None
try:
    require_customer_id(agent)
    raise SystemExit("require_customer_id accepted an agent")
except SystemExit:
    raise
except Exception:
    pass
for bad in ({"role": "agent", "customer_id": "CLI-X"}, {"role": "customer", "customer_id": None}):
    try:
        Session(account_id=uuid4(), step_up_at=None, **bad)
        raise SystemExit(f"accepted {bad}")
    except ValidationError:
        pass
EOF
` (the heredoc body is the Python check; every other command is chained with `&&` on the first line).
  - Files: `backend/app/domains/identity/{models,tokens,service,repository,passwords,provision}.py`, `backend/app/core/config.py`, `backend/app/api/v1/conversations.py` (two-line narrowing only), `backend/app/domains/conversation/tools/registry.py` (one-line narrowing only)

- [ ] T3: Shared contracts: handoff schemas and in-memory port, `ActionResult.case_ids`, the two UI events, `TxSelection`
  - Wave: 1
  - Depends on: nothing.
  - Read exactly these:
    - spec D1, D13, D16 and §Contracts "`app/domains/handoff/schemas.py`", "UI events" and "Graph and state" (only `TxSelection`)
    - `docs/solution-docs/04-contracts.md` §4
    - `backend/app/domains/conversation/ui.py` (the event pattern)
  - Acceptance:
    - `app/domains/handoff/__init__.py` holds only a docstring and makes no imports.
    - `schemas.py` defines exactly the spec's models, frozen, with `extra="forbid"` on `HandoffDraft`, `AgentMessageRequest` and `TxSelection`: `Priority`, `HandoffStatus`, `VerifiedFact`, `ActionTaken`, `Evidence`, `HandoffDraft`, `HandoffPacket`, `HandoffRef`, the `HandoffPort` Protocol, `HandoffSummary`, `HandoffListResponse`, `HandoffDetail`, `AgentMessageRequest` (text 1..2000) and `AgentMessageResponse`. `Queue` comes from `app.domains.localization.format`.
    - `memory.InMemoryHandoffPort(conversation_id, policy_version)`:
      - `.create(draft)` appends a `HandoffPacket` to `.packets` with `request` filled from the `handoff_request` template in `draft.language` and `sentiment=None`
      - it returns a `HandoffRef`
    - `templates.py` gains only `handoff_request` (ES + PT, no digits, placeholders filled in code).
    - `core/actions.py` gains `case_ids: list[str] | None = None`.
    - `ui.py` gains `TxOption{tx_id, label}`, `TransactionListPayload{options, multi: Literal[True] = True}`, `TransactionListEvent{kind: "transaction_list"}`, `HandoffBannerPayload{handoff_id: UUID, queue: Queue, queue_label, case_ids: list[str]}` and `HandoffBannerEvent{kind: "handoff_banner"}`, all joined to `UIEvent`. The module docstring is updated.
    - `graph.py` gains only `TxSelection(BaseModel)`: `tx_ids: list[str]`, 1–10, unique (validator), frozen, `extra="forbid"`. It is exported in `__all__`.
  - Verify: `cd backend && uv run pytest tests/unit/test_r3_action_result.py tests/unit/test_graph.py -q && uv run python - <<'EOF' && uv run mypy app/domains/handoff app/core/actions.py app/domains/conversation/ui.py app/domains/conversation/templates.py app/domains/conversation/graph.py && uv run lint-imports && uv run ruff check app/domains/handoff app/core/actions.py app/domains/conversation/ui.py app/domains/conversation/templates.py app/domains/conversation/graph.py && uv run ruff format --check app/domains/handoff app/core/actions.py app/domains/conversation/ui.py app/domains/conversation/templates.py app/domains/conversation/graph.py
import asyncio
from uuid import uuid4
from pydantic import TypeAdapter, ValidationError
from app.domains.handoff.schemas import HandoffDraft
from app.domains.handoff.memory import InMemoryHandoffPort
from app.domains.conversation.graph import TxSelection
from app.domains.conversation.ui import UIEvent
for lang in ("es", "pt"):
    port = InMemoryHandoffPort(uuid4(), "sha256:x")
    draft = HandoffDraft(queue="fraudes", priority="high", reason="suspected_fraud", language=lang, verified_facts=[], actions_taken=[], evidence=[], open_questions=[], escalation_rules_hit=[])
    ref = asyncio.run(port.create(draft))
    assert len(port.packets) == 1 and port.packets[0].request and port.packets[0].sentiment is None and ref.queue == "fraudes"
for bad in ([], ["a", "a"], [str(i) for i in range(11)]):
    try:
        TxSelection(tx_ids=bad)
        raise SystemExit(f"accepted {bad}")
    except ValidationError:
        pass
TypeAdapter(UIEvent).validate_python({"kind": "transaction_list", "payload": {"options": [{"tx_id": "T1", "label": "x"}]}})
TypeAdapter(UIEvent).validate_python({"kind": "handoff_banner", "payload": {"handoff_id": str(uuid4()), "queue": "fraudes", "queue_label": "Fraudes", "case_ids": ["CLM-0000ABCD"]}})
EOF
` (the heredoc body is the Python check; every other command is chained with `&&` on the first line).
  - Files: `backend/app/domains/handoff/{__init__,schemas,memory}.py` (new), `backend/app/core/actions.py`, `backend/app/domains/conversation/ui.py`, `backend/app/domains/conversation/templates.py` (`handoff_request` only), `backend/app/domains/conversation/graph.py` (`TxSelection` only)

- [ ] T4: Claim write path: transaction lookup, disputes domain, `create_claim` on the Protocol, the executor, FakeBank and Postgres, with the R2 and B1 tests
  - Wave: 2
  - Depends on:
    - T1: `ToolArg` list form; `tools.yaml` has `disputes.create_claim` for `unrecognized_charge`; `0005` adds `bank.complaints.transaction_id`/`idempotency_key`
    - T3: `ActionResult.case_ids`
    - Real symbol names are in the state file.
  - Read exactly these:
    - spec D14–D17 and §Contracts "Tools" (plus `docs/solution-docs/04-contracts.md` §1: the `disputes.create_claim` row and the idempotency paragraph)
    - `backend/app/domains/conversation/tools/postgres_writes.py` (the write → separate re-read analogue, and how it reaches a domain `service`)
    - `backend/tests/integration/test_postgres_writes.py` (integration analogue); `backend/tests/unit/test_audit_pairs.py` shows how to build `ConfirmedWriteTools` with an in-memory `AuditRecorder(insert=...)`
  - Acceptance:
    - `transactions.{repository,service}` gain an own-row lookup by a list of ids for one `customer_id`. An id that exists for another customer raises `AccessDenied`; an unknown id raises `NotFound`. It follows the cards probe shape: the probe selects no data column.
    - `app/domains/disputes/` (`__init__` docstring only):
      - `schemas.ClaimRow`
      - `service.create_claims(customer_id, conversation_id, tx_ids, answers, idempotency_key) -> list[ClaimRow]`. It reads each transaction through `transactions.service` first (own-row check), then writes one `bank.complaints` row per transaction exactly as D14 says, all in **one transaction**.
      - `description` = the code-built answers string (spec open item 1).
      - The per-row key is `<idempotency_key>:<tx_id>`. A replay whose keys already exist re-reads and returns the existing rows and writes nothing.
      - `service.get_claims(customer_id, ids)` is the separate re-read.
    - `write.BankWriteTools.create_claim(tx_ids, answers, *, idempotency_key) -> ActionResult`.
    - `ConfirmedWriteTools.create_claim(tx_ids, answers, token_id)` follows the D16 order through `_run`, with args exactly `{"tx_ids": tx_ids, "answers": answers}`. `_run` now records `access_denied` (best effort) when the raw call raises `AccessDenied`.
    - `PostgresBankWrites.create_claim` calls `disputes.service` and sets:
      - `case_ids`
      - `readback = {"status": "Open", "count": n, "at": datetime}`
      - `verified` only when every re-read row matches its transaction (amount, currency, product, `transaction_id`, `origin='app'`) and the session's customer
    - `.importlinter` gains `app.domains.conversation.tools.postgres_writes -> app.domains.disputes.service`.
    - `FakeBankWrites.create_claim` does the same over the overlay: DuckDB own-row lookup by ids, `CLM-` + 8 upper hex, and the same replay behavior.
    - `sandbox._RecordingWriteTools.create_claim` forwards it.
    - Tests:
      - `test_r2_confirmed_writes.py`: `_StubRawWrites` gains `create_claim`, and `test_compromise_plan_order_and_allowlist` is added (spec test list).
      - `tests/integration/test_postgres_disputes.py`:
        - `test_claim_row_matches_transaction`: `CLI-TFMULTI00001` with `TRX-TFM1CRED0001TXN01` + `TRX-TFM1DEBT0002TXN01`; a stale re-read monkeypatched in gives `verified=False`; a same-key replay makes no new rows and returns the same `case_ids`. Rows are filtered by the test's own `conversation_id`.
        - `test_foreign_transaction_refused`: bound to `CLI-TFMULTI00001`, `TRX-TFS2CRED0001TXN01`, through `ConfirmedWriteTools(PostgresBankWrites, InMemoryConfirmationStore, …, AuditRecorder(insert=<list append>))` under intent `unrecognized_charge`. It gets `AccessDenied`, no row for that `transaction_id`, and one `access_denied` event.
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py tests/unit/test_fakebank_writes.py tests/unit/test_audit_pairs.py tests/unit/test_r1_customer_scope.py -q && uv run pytest tests/integration/test_postgres_disputes.py -q 2>&1 | tail -1 | grep -E '^2 passed(, [0-9]+ warnings?)? in' && uv run mypy app && uv run lint-imports && uv run ruff check app/domains/disputes app/domains/transactions app/domains/conversation/tools app/domains/conversation/sandbox.py tests/unit/test_r2_confirmed_writes.py tests/integration/test_postgres_disputes.py && uv run ruff format --check app/domains/disputes app/domains/transactions app/domains/conversation/tools app/domains/conversation/sandbox.py tests/unit/test_r2_confirmed_writes.py tests/integration/test_postgres_disputes.py`
  - Files: `backend/app/domains/transactions/{repository,service}.py`, `backend/app/domains/disputes/{__init__,schemas,repository,service}.py` (new), `backend/app/domains/conversation/tools/{write,executor,fakebank,postgres_writes}.py`, `backend/app/domains/conversation/sandbox.py` (recorder only), `backend/.importlinter`, `backend/tests/unit/test_r2_confirmed_writes.py`, `backend/tests/integration/test_postgres_disputes.py` (new)

- [ ] T5: Staff and messages API surface (staff login, role split, `/staff/*` declared, `selection` body) and the regenerated client
  - Wave: 2
  - Depends on:
    - T2: `StaffLoginRequest`, `StaffMeResponse`, `identity_service.staff_login`/`staff_me`, `passwords.staff_login_key`, typed `Session`
    - T3: handoff API models in `app.domains.handoff.schemas`, `graph.TxSelection`
    - T1: `0005`, for `it_db`
  - Read exactly these:
    - spec D2, D5, D6, D7 (only the request body) and §Contracts "HTTP"
    - `backend/app/api/v1/auth.py`
    - `backend/tests/integration/test_auth.py` (analogue); `backend/tests/unit/test_r13_routes.py`
  - Acceptance:
    - `auth.py`:
      - `POST /auth/staff/login` on `public_router`. It maps `TooManyAttempts` → `429 too_many_attempts` and `InvalidCredentials` → `401 invalid_credentials`, then sets the same cookies as customer login and returns `StaffMeResponse`.
      - `/auth/logout` moves to a new router with `require_role("customer","agent")` + `require_csrf`.
      - `/auth/me` and `/auth/otp/verify` stay customer-only.
      - `/auth/refresh` returns `403 forbidden_role` for an agent session.
    - New `api/v1/staff.py` (`prefix="/staff"`, router-level `require_role("agent")` + `require_csrf`):
      - `GET /staff/me` is fully implemented (`staff_me`).
      - These six routes have real request/response models (`HandoffListResponse`, `HandoffDetail`, `HandoffSummary`, `AgentMessageRequest` → `202 AgentMessageResponse`, SSE) and raise `HTTPException(501, "not_implemented")`: `GET /staff/handoffs?queue=`, `GET /staff/handoffs/{handoff_id}`, `POST /staff/handoffs/{handoff_id}/claim`, `POST /staff/handoffs/{handoff_id}/return`, `POST /staff/conversations/{conversation_id}/messages` and `GET /staff/conversations/{conversation_id}/stream`.
    - `api/v1/__init__.py` mounts both new routers.
    - `conversations.py` `PostMessageRequest`:
      - gains `selection: TxSelection | None`, and the validator requires exactly one of `text`, `resume`, `selection` (else `422`)
      - **interim**: a `selection` body always answers `409 selection_invalid` and schedules nothing, because no list can be pending until the flow lands. T8 replaces this with the real D7 gate.
    - Tests:
      - `test_auth.py::test_staff_login_and_role_split` (spec list). It uses a staff-account fixture defined **inside `test_auth.py`**: it inserts `role='agent'`, `customer_id NULL`, `username`, `display_name`, `login_key = staff_login_key(username, hmac_key=get_settings().identity_hmac_key)`, and deletes the row on teardown. `tests/integration/conftest.py` stays untouched.
      - `test_r13_routes.py`: `/api/v1/auth/staff/login` is exempt, every `/api/v1/staff/…` route declares `RoleGuard` with `roles == ("agent",)`, and `/auth/logout` declares `("customer","agent")`.
    - Client regen (no host Node; same generator and config as `make client`), run from the repo root:
      1. `(cd backend && uv run python -c "import json,pathlib; from app.main import create_app; pathlib.Path('../frontend/openapi.tmp.json').write_text(json.dumps(create_app().openapi()), encoding='utf-8')")`
      2. `sed 's#http://localhost/api/v1/openapi.json#./openapi.tmp.json#' frontend/openapi-ts.config.ts > frontend/openapi-ts.tmp.config.ts`
      3. NODE-RO with `npx @hey-api/openapi-ts -f openapi-ts.tmp.config.ts`
      4. delete both temp files
      - If this generator version rejects `-f`, record the working equivalent in the state file.
  - Verify: `cd backend && uv run pytest "tests/integration/test_auth.py::test_staff_login_and_role_split" -q 2>&1 | tail -1 | grep -E '^1 passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py -q && uv run python -c "from app.main import create_app; p=create_app().openapi()['paths']; need={'/api/v1/auth/staff/login','/api/v1/staff/me','/api/v1/staff/handoffs','/api/v1/staff/handoffs/{handoff_id}','/api/v1/staff/handoffs/{handoff_id}/claim','/api/v1/staff/handoffs/{handoff_id}/return','/api/v1/staff/conversations/{conversation_id}/messages','/api/v1/staff/conversations/{conversation_id}/stream'}; assert need <= set(p), need - set(p)" && uv run mypy app/api && uv run ruff check app/api tests/integration/test_auth.py tests/unit/test_r13_routes.py && uv run ruff format --check app/api tests/integration/test_auth.py tests/unit/test_r13_routes.py && cd .. && test "$(grep -o "url: '/api/v1/staff/[^']*'" frontend/src/client/sdk.gen.ts | sort -u | wc -l)" -ge 6 && grep -q "/api/v1/auth/staff/login" frontend/src/client/sdk.gen.ts && grep -q "selection" frontend/src/client/types.gen.ts && ! grep -q "http://" frontend/src/client/client.gen.ts && test ! -e frontend/openapi.tmp.json && test ! -e frontend/openapi-ts.tmp.config.ts`
  - Files: `backend/app/api/v1/{auth,__init__,conversations}.py`, `backend/app/api/v1/staff.py` (new), `backend/tests/integration/test_auth.py`, `backend/tests/unit/test_r13_routes.py`, `frontend/src/client/**` (regenerated)

- [ ] T6: The `unrecognized_charge` flow: multi-step plans, graph wiring, dispute state, templates, fixture rows, and the flow and R6 tests
  - Wave: 3
  - Depends on:
    - T1: `load_disputes_policy`, `DisputesPolicy.triggers_compromise`, `tools.yaml` allowlist
    - T3: `InMemoryHandoffPort`, handoff schemas, `TransactionListEvent`/`HandoffBannerEvent`, `TxSelection`, `ActionResult.case_ids`, `handoff_request`
    - T4: `ConfirmedWriteTools.create_claim` and `FakeBankWrites.create_claim`
    - Names are in the state file.
  - Read exactly these:
    - spec D7–D13, D19 and §Contracts "Graph and state"
    - `docs/solution-docs/02-conversation-design.md` §3 (entry routing, step 0) and §4.8
    - `backend/app/domains/conversation/flows/card_block.py` (flow analogue); `backend/tests/unit/test_block_flows.py` (test analogue, `make_session` + `ScriptedLLM`)
  - Acceptance:
    - `flows/actions.py`:
      - `start_plan` takes `steps` (one `ui.confirm` with one `ConfirmStepView` per step). The three callers (`card_block`, `card_unlock`, `replacement`) are updated with behavior unchanged.
      - New `execute_plan` runs the confirmed calls in order and stops at the first failed or unverified step, going through the existing `action_unverified` handoff.
    - `state.py`: `DisputeState` exactly per spec, and `TurnState.dispute: NotRequired[DisputeState | None]`.
    - `graph.py`:
      - `TurnInput`/`GraphState` gain `selection`.
      - `_entry` step 0: `selection` set + `awaiting_slot == "transactions"` → `unrecognized_charge`, else `smalltalk`, without `understand`.
      - `_INTENT_NODES`/`_FLOW_NODES`/`_BRANCH_NODES` gain `unrecognized_charge`; the node and edges are registered.
      - `run_turn(..., selection=None)`.
    - `nodes/route.py`: `card_possession` and `dispute_question` are affirm/deny slots.
    - `flows/unrecognized_charge.py` covers D8–D13:
      - card select; candidates via `search_transactions(TxFilter(card_id, status=candidate_statuses))`
      - none → `dispute_no_transactions`, `pending` cleared, nothing written
      - `ui.transaction_list` labels from `localization.format` ("Comercio"/"Estabelecimento" when the merchant is missing); `pending.awaiting_slot = "transactions"`
      - the pick re-checked against `offered_tx_ids`
      - the compromise rule only via `triggers_compromise` + the possession answer
      - the compromise plan `[block_card(card_id, "suspected_fraud"), create_claim(tx_ids, answers)]` under `unrecognized_charge`, with a verified reply carrying the case IDs + a Fraudes handoff via `config["configurable"]["handoff"]` (`HandoffDraft` built in code) + `ui.handoff_banner` with the claim's `case_ids`
      - D10 refused block → claim-only plan → handoff with the `open_questions` saying the card is still active; both refused → handoff with no claim
      - the D11 single-charge path with no handoff
      - an already-blocked card keeps `block_card` (spec open item 4)
    - `templates.py`: `dispute_no_transactions`, `dispute_q_card_in_possession`, `dispute_q_contacted_merchant`, and whatever else the flow needs, in ES + PT with no digits. Log the kinds in the state file.
    - `tests/conftest.py`: `make_session` adds `"handoff": InMemoryHandoffPort(conversation_id, "unversioned")` to the config and exposes it as `Session.handoff`.
    - Fixture, keeping the BOM and CRLF, with `README.md` updated:
      - `CLI-TFSINGLE0002`/`PRD-TFS2CRED0001` gains `TXN03` (Pending, empty merchant, `fraud_score` 45.00) and `TXN04` (Declined), which gives 3 non-declined (one > 30) + 1 declined.
      - `CLI-TFPASTD00005`/`PRD-TFP5CRED0001` gains one Declined row, so its only transaction is declined.
    - Tests:
      - `tests/unit/test_dispute_flows.py`: the five spec tests with their cases. The pick turn asserts no `nlu` call in `ScriptedLLM.calls`.
      - The R6 test adds `"handoff"` to `_FORBIDDEN_NAMES`.
  - Verify: `cd backend && uv run pytest tests/unit/test_dispute_flows.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_block_flows.py tests/unit/test_r3_flows.py tests/unit/test_graph.py tests/unit/test_card_info_flows.py -q && test "$(grep -rl --include=*.py 'fraud_score_gt\|min_picked' app)" = "app/domains/policy/disputes.py" && uv run mypy app && uv run lint-imports && uv run ruff check app/domains/conversation tests/conftest.py tests/unit/test_dispute_flows.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run ruff format --check app/domains/conversation tests/conftest.py tests/unit/test_dispute_flows.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py`
  - Files: `backend/app/domains/conversation/{state,graph,templates}.py`, `backend/app/domains/conversation/nodes/route.py`, `backend/app/domains/conversation/flows/{actions,card_block,card_unlock,replacement}.py`, `backend/app/domains/conversation/flows/unrecognized_charge.py` (new), `backend/tests/conftest.py`, `backend/tests/fixtures/fakebank/{README.md,transactions/year=2026/month=03/day=30/transactions_20260330.csv}`, `backend/tests/unit/test_dispute_flows.py` (new), `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`

- [ ] T7: Customer chat widgets: transaction list, handoff banner, bot/agent indicator, and the ES e2e
  - Wave: 3
  - Depends on: T5, for `frontend/src/client/`: `PostMessageRequest` has `selection` and the staff functions exist. It needs no backend at run time: the e2e mocks the API.
  - Read exactly these:
    - spec D13, D21, §Contracts "UI events", and the test-list row `e2e/unrecognized.es.spec.ts`
    - `frontend/src/routes/chat.tsx` (with `src/lib/sse.ts` next to it)
    - `frontend/e2e/block.pt.spec.ts` + `frontend/e2e/mock-api.ts` (the e2e analogue: fixtures are the fake LLM)
  - Acceptance:
    - `api.ts`: `postSelection(conversationId, txIds)` posts `{selection: {tx_ids}}` through the generated SDK, with the existing `withAuthRetry`.
    - `sse.ts`: typed `transaction_list` and `handoff_banner` UI kinds, and a `mode` event handler (`{mode: "bot"|"human", agent_display_name}`).
    - `TransactionList.tsx`: native checkboxes, one per option `label`. The "Continuar" button is disabled until something is picked, and a pick posts the ids. It disables itself after use, like `CardPicker`.
    - `HandoffBanner.tsx` shows `queue_label` and the `case_ids`.
    - `ModeIndicator.tsx`: the header shows Cardy or the agent's `agent_display_name`.
    - `MessageList.tsx`/`chat.tsx` render the new kinds.
    - i18n (ES + PT, same key set) adds `confirm.steps.create_claim`, the widget labels and the mode label.
    - No new npm dependency: `package.json`/`package-lock.json` are untouched.
    - `e2e/unrecognized.es.spec.ts` with its own `.sse` fixtures proves the spec row: checkboxes → pick 2 + "Continuar" posts `{selection:{tx_ids:[…]}}` → confirm card with 2 steps → banner with queue label and case ID → a `mode` event switches the header.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules:ro -w /app node:22.22-bookworm sh -c 'npx biome check --write src/routes/chat.tsx src/lib src/components/chat e2e && npx biome ci src/routes/chat.tsx src/lib src/components/chat e2e && (npm run -s typecheck > .tc-t7.txt 2>&1; ! grep -E "src/(routes/chat\.tsx|lib/|components/chat/)" .tc-t7.txt) && rm .tc-t7.txt' && uv run --no-project python -c "import json;a=json.load(open('frontend/src/lib/i18n/es.json',encoding='utf-8'));b=json.load(open('frontend/src/lib/i18n/pt.json',encoding='utf-8'));d=sorted(set(a)^set(b));print(*d,sep='\n');raise SystemExit(1 if d else 0)" && git diff --quiet -- frontend/package.json frontend/package-lock.json && MSYS_NO_PATHCONV=1 docker run --rm --ipc=host -v "$(pwd -W)/frontend:/app" -v /app/node_modules -w /app mcr.microsoft.com/playwright:v1.63.0-noble sh -c 'npm ci && npm run build && npx playwright test e2e/unrecognized.es.spec.ts'`
  - Files: `frontend/src/lib/{api.ts,sse.ts,i18n/es.json,i18n/pt.json}`, `frontend/src/components/chat/{TransactionList,HandoffBanner,ModeIndicator}.tsx` (new), `frontend/src/components/chat/MessageList.tsx`, `frontend/src/routes/chat.tsx`, `frontend/e2e/unrecognized.es.spec.ts` (new), `frontend/e2e/fixtures/unrecognized-*.sse` (new)

- [ ] T8: Runner and route selection gate, sandbox handoff wiring, and `make chat-api` `/pick`
  - Wave: 4
  - Depends on:
    - T6: `TurnInput.selection`, `TurnState.dispute`, the `unrecognized_charge` node, the fixture rows loaded into `it_db`
    - T4: `PostgresBankWrites.create_claim`
    - T5: `PostMessageRequest.selection` and the interim `409` this task replaces
    - T3: `InMemoryHandoffPort`, `TxSelection`
  - Read exactly these:
    - spec D1 (the runner uses the in-memory port until A3), D7, §Contracts "Graph and state" (runner lines) and the `/messages` row of §Contracts "HTTP"
    - `backend/app/domains/conversation/runner.py`
    - `backend/tests/integration/test_write_path_api.py` (the analogue for driving a real turn over HTTP with a `ScriptedLLM` swapped onto `app.state.turn_host.llm`)
  - Acceptance:
    - `runner.start_turn(..., selection: TxSelection | None = None)` takes exactly one of four inputs. `selection` is never persisted as a message, and is passed into `astream` input with `selection` explicitly `None` on other turns.
    - `_run_turn` adds `"handoff": InMemoryHandoffPort(conversation_id, ctx.policy_version)` to `config["configurable"]`.
    - `_BRANCH_NODES` gains `unrecognized_charge`.
    - New `checkpointed_dispute(host, conversation_id)` returns the checkpoint's `pending` + `dispute`.
    - `conversations.py` replaces T5's interim guard with the D7 gate: paused at `awaiting_slot == "transactions"` and every id in `dispute.offered_tx_ids`, else `409 selection_invalid` before any lock or turn.
    - `sandbox.py` `_build_session` adds the `handoff` key.
    - `scripts/chat_api.py` prints a `ui transaction_list` with 1-based indices. `/pick 1,2` posts `{selection: {tx_ids}}` for those indices from the last list and runs the turn like a typed message.
    - `test_confirmations_route.py::test_injected_tx_id_is_409` (spec list) covers both cases. First: no list pending → `409`. Second: after a scripted `unrecognized_charge` turn for `CLI-TFSINGLE0002` whose bot row carries `transaction_list`, a non-offered id (for example `TRX-TFM1CRED0001TXN01`) → `409`. In both cases no new turn is scheduled: no new `app.messages` row appears.
  - Verify: `cd backend && uv run pytest tests/integration/test_confirmations_route.py -q 2>&1 | tail -1 | grep -E '^2 passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_sandbox_conversations.py tests/unit/test_r13_routes.py -q && uv run python scripts/chat_api.py --help > /dev/null && uv run mypy app && uv run lint-imports && uv run ruff check app/domains/conversation/runner.py app/domains/conversation/sandbox.py app/api/v1/conversations.py scripts/chat_api.py tests/integration/test_confirmations_route.py && uv run ruff format --check app/domains/conversation/runner.py app/domains/conversation/sandbox.py app/api/v1/conversations.py scripts/chat_api.py tests/integration/test_confirmations_route.py`
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/api/v1/conversations.py`, `backend/app/domains/conversation/sandbox.py` (config key only), `backend/scripts/chat_api.py`, `backend/tests/integration/test_confirmations_route.py`

- [ ] T9: Staff screens: login, live inbox, claim, packet view, agent chat, return to bot, and the ES e2e
  - Wave: 4
  - Depends on:
    - T5: generated staff functions in `frontend/src/client/`
    - T7: the current `lib/api.ts`, `sse.ts` and i18n, which this task extends; T7's i18n keys and exports are in the state file
  - Read exactly these:
    - spec D2, D5, D20, D21, §Contracts "HTTP" (the `/staff/*` rows), and the test-list row `e2e/staff.es.spec.ts`
    - `frontend/src/routes/login.tsx` (the RHF + zod form analogue)
    - `frontend/e2e/mock-api.ts` (the mock shape to mirror in a separate staff mock file)
  - Acceptance:
    - `api.ts` gains staff wrappers over the generated SDK (staff login, me, handoffs list/detail/claim/return, agent message) with the CSRF interceptor. Any `401` goes straight to `/staff/login`, with no refresh (D5).
    - Routes:
      - `routes/staff/login.tsx`: username + password, error mapping through `errors.<code>`.
      - `routes/staff/index.tsx`: the inbox, `GET /staff/handoffs` via TanStack Query with `refetchInterval: 3000`.
      - `routes/staff/handoffs.$handoffId.tsx`:
        - claim → `PacketView` (verified facts, actions with case IDs, evidence with scores, open questions)
        - `AgentChat`: send posts `/staff/conversations/{id}/messages`; the stream is `GET /staff/conversations/{id}/stream`, and `sse.ts` may be extended for that path
        - "Devolver al bot" posts `/return`
    - `components/staff/{InboxList,PacketView,AgentChat}.tsx`.
    - ES/PT keys come from the shared dictionary, with identical key sets.
    - No new npm dependency.
    - `e2e/mock-staff-api.ts` is a new, separate `page.route` mock of `/api/v1/**` for staff. `e2e/staff.es.spec.ts` proves the spec row: login → the inbox shows a queued Fraudes case after a poll → claim → packet sections → a message posts to `/staff/conversations/{id}/messages` → "Devolver al bot" posts `/return`.
  - Verify: `cd "$(git rev-parse --show-toplevel)" && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/frontend:/app" -v d3b_frontend_node_modules:/app/node_modules:ro -w /app node:22.22-bookworm sh -c 'npx biome check --write src/routes/staff src/components/staff src/lib e2e && npx biome ci src/routes/staff src/components/staff src/lib e2e && (npm run -s typecheck > .tc-t9.txt 2>&1; ! grep -E "src/(routes/staff/|components/staff/|lib/)" .tc-t9.txt) && rm .tc-t9.txt' && uv run --no-project python -c "import json;a=json.load(open('frontend/src/lib/i18n/es.json',encoding='utf-8'));b=json.load(open('frontend/src/lib/i18n/pt.json',encoding='utf-8'));d=sorted(set(a)^set(b));print(*d,sep='\n');raise SystemExit(1 if d else 0)" && git diff --quiet -- frontend/package.json frontend/package-lock.json && MSYS_NO_PATHCONV=1 docker run --rm --ipc=host -v "$(pwd -W)/frontend:/app" -v /app/node_modules -w /app mcr.microsoft.com/playwright:v1.63.0-noble sh -c 'npm ci && npm run build && npx playwright test e2e/staff.es.spec.ts'`
  - Files: `frontend/src/routes/staff/{login,index,handoffs.$handoffId}.tsx` (new), `frontend/src/components/staff/{InboxList,PacketView,AgentChat}.tsx` (new), `frontend/src/lib/{api.ts,sse.ts,i18n/es.json,i18n/pt.json}`, `frontend/e2e/staff.es.spec.ts` (new), `frontend/e2e/mock-staff-api.ts` (new)

- [ ] T10: Live end-of-day checks (SC1, SC2, SC6), demo persona, client drift, and reconciling the pre-written doc amendments
  - Wave: 5
  - Depends on: every earlier task. Read their deviations in the state file before checking the docs.
  - Read exactly these:
    - spec §Success criteria and §Touch map "Doc amendments in this PR"
    - `eval/personas.yaml` (header: the closed trait vocabulary)
    - `Makefile` targets `seed-identity` and `chat-api`
  - Acceptance:
    - (a) `curl -sf localhost/api/v1/health` returns 200 before anything else runs.
    - (b) `make seed-identity`: golden goes to alembic `0005`, provisioning writes the customers plus one agent row, then demo-reset and a backend restart. If the Bash sandbox denies its `DROP DATABASE`, stop and escalate. Don't retry through another tool.
    - (c) `select version_num from alembic_version` on `latam_app` returns `0005`. `select count(*) from identity.accounts where role='agent'` returns `1`.
    - (d) The demo persona is added to `eval/personas.yaml`. It is chosen by a read-only query on `latam_golden`: an Active customer with exactly one card whose 10 newest non-declined transactions include one with `fraud_score > 30`. Existing trait keys only; the score goes in `notes`. `uv run pytest tests/integration/test_personas.py -q` passes.
    - (e) SC1, one live run of `make chat-api PERSONA=<that id>`: "no reconozco estas compras" → `/pick 1,2` → `/confirm`. The reply carries case IDs and the Fraudes handoff text. Then `SELECT claimed_amount, currency, transaction_id, origin FROM bank.complaints WHERE conversation_id = '<id>'` returns 2 rows equal to the 2 picked transactions' amount and currency, with `origin='app'`. At most 3 live LLM calls.
    - (f) Staff: log in with the username/password read from `data/secrets/staff_credentials.csv` (never echoed). Then `/api/v1/staff/me` → 200 with the display name, `/api/v1/staff/handoffs` → 501, and a customer session on `/api/v1/staff/me` → 403.
    - (g) Client drift: `curl -s localhost/api/v1/openapi.json` into a temp file, regenerate into a scratch copy with the same config (T5's mechanics), and `diff -r` against `frontend/src/client` shows no difference.
    - (h) SC2 grep holds.
    - (i) The doc amendments are present (greps below). Edit `02`/`03`/`04`/`decision-log.md` only where a logged deviation in the state file contradicts them.
  - Verify: `curl -sf localhost/api/v1/health && cd backend && uv run pytest tests/integration/test_personas.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select version_num from alembic_version")" = 0005 && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select count(*) from identity.accounts where role='agent'")" = 1 && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select count(*) from bank.complaints where origin='app' and transaction_id is not null")" -ge 2 && test "$(grep -rl --include=*.py 'fraud_score_gt\|min_picked' app)" = "app/domains/policy/disputes.py" && cd .. && grep -q "disputes.create_claim" docs/solution-docs/04-contracts.md && grep -q "selection_invalid" docs/solution-docs/04-contracts.md && grep -q "HandoffDraft" docs/solution-docs/04-contracts.md && grep -q "staff_credentials.csv" docs/solution-docs/03-data-architecture.md && grep -q "D4-B D8" docs/solution-docs/decision-log.md && grep -q "awaiting_slot == \"transactions\"" docs/solution-docs/02-conversation-design.md && ! git ls-files --error-unmatch data/secrets/staff_credentials.csv 2>/dev/null`, plus the recorded outputs of (e), (f) and (g) in the state file (their commands and results, with the password and document numbers never printed).
  - Files: `eval/personas.yaml`, `docs/solution-docs/{02-conversation-design,03-data-architecture,04-contracts,decision-log}.md` (only if a logged deviation requires it)
