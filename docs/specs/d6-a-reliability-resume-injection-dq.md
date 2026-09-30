# Spec: D6-A — Reliability, session resume, injection hardening, data quality

Card D6-A (Dev A's D6 track: G12b reliability, G4 resume, G6c injection, G2b data quality) · `07` lines 261-289, rows A1-A4 · branch `feat/d6-a-reliability-resume-injection-dq` (base `develop`).

## Objective

This card makes the system fail safely and report on its own data:

- **A1: bounded retries, faults, fallback, cost guard.**
  - LLM and tool calls get 2 retries with backoff and a per-call timeout.
  - Every attempt is visible in the audit log.
  - Three fault flags make the failures reproducible.
  - When retries run out, the customer gets a fixed ES/PT template (no LLM), followed by a handoff with the reason.
  - An `LLM_DISABLED` kill switch and per-conversation and per-account turn caps bound the cost.
- **A2: session expiry and resume.** A `401 session_expired` changes nothing on the server. The client re-sends the rejected request after re-login. Another customer can't resume.
- **A3: injection hardening.**
  - The eval runner plants instructions in data fields (`setup.db_patches`) on the clone.
  - The R6 scan proves it fails when a write tool is added.
  - A test proves tool-output text never reaches an LLM.
- **Frontend follow-through (human decision, planner gate):** `make client` regenerates the client types with the two new handoff reasons, and the staff console gets ES/PT labels `staff.reason.tool_failure` and `staff.reason.llm_unavailable`.
- **A4: data quality.**
  - Pandera contracts on raw partitions.
  - dbt relationship and semantic tests.
  - A quality report and lineage on every `make data` run.
  - Three labeled fixtures (late partition, schema change, duplicate batch) with tests.

It serves these "Done when" lines:
- A1: "One test per fault: retry count in the audit log, fallback in the right language, handoff".
- A2: "API test".
- A3: "The graph test fails if a write tool is added".
- A4: "`make data` writes the report; the fixture tests pass".

It also serves end-of-day steps 1, 3 and 4. Step 2 (the browser modal) is B2's, over the contract in D12. Step 5 is B1's.

**Cut line (`07` D6 "If behind"):** turn caps (D11) and the schema-change fixture (D20c) move to D7. The deploy at the end of D6 (`07` §8, D5 row) is the separate `/wave-run D5-A-deploy` follow-up and is not graded here.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Scope** is A1-A4 as listed in the Objective, plus the small frontend task in D23. **Out:** dbt incremental models (D19), a `GET …/pending` or server-side replay endpoint (D12), the simulator and the UI modal (B1, B2), B3's dev cases, the deploy | `07` D6; human answers 1(a), 4(a) |
| D2 | **Already built, reused as is:**<br>• the `injection_suspected` status, its routing and the refusal count (nlu@v4, `route`, `unsupported`, D4-A D6);<br>• `compose` and `handoff_summary` see only fact **keys**, fenced, never values;<br>• the R6 source scan;<br>• `401 session_expired` from `get_session` and the `404` from `get_owned_conversation`;<br>• the plan TTL is independent of the session (`04` §7, D3-A D4);<br>• one `audit.llm_calls` row per attempt;<br>• the dedup into `stg_<t>__rejects`;<br>• the unique, not_null and accepted_values tests on serving | Assumption 1 |
| D3 | **LLM retries move into `StructuredLLMClient`.**<br>• The provider SDK is built with `max_retries=0`. Bedrock uses botocore `retries={"total_max_attempts": 1, "mode": "standard"}`, because botocore's `max_attempts` counts retries, not attempts (A9).<br>• The client makes 1 call plus 2 retries on a retryable transport error (timeout, connection, 429, 5xx), with exponential backoff and full jitter: base 0.5 s, cap 2 s. The tool wrappers (D5) use the same values.<br>• Every attempt is ledgered as its own `audit.llm_calls` row: `attempt` 1..3, status `unavailable` on a failure.<br>• After the third failure it raises `LLMUnavailable`.<br>• A non-retryable 4xx (auth, bad request) raises on the first attempt.<br>• The existing single retry on invalid output is unchanged and uses the same attempt counter | Assumption 2, R11, `01` §7 |
| D4 | **Timeouts:** LLM 20 s per attempt (existing `timeout_s`), tools 3 s per attempt. The tool timeout surfaces as `ToolUnavailable` | `01` §7 (the proposed values, now decided), assumption 2 |
| D5 | **Tool retries.**<br>• Read tools (the `RecordingBankTools` wrapper in `tools/registry.py`) and the raw write call inside `ConfirmedWriteTools` (step 4 of D3-A D16) retry `ToolUnavailable` 2 times with backoff.<br>• A write calls `consume_step` once, then retries the raw call with the **same** idempotency key `<token_id>:<step_index>`.<br>• Each failed attempt records `tool_result {tool, error, attempt}`.<br>• When the retries are exhausted, the executor cancels the plan exactly as today and re-raises `ToolUnavailable`.<br>• In `flows/actions.py`, a `ToolUnavailable` becomes `tool_failure` (D8). Any other exception keeps today's `action_unverified` | Assumption 3, R2, R11 |
| D6 | **Fault flags:** `FAULTS` is a comma-separated env var read into Settings. Allowed values are `bedrock_timeout`, `cards_write_error` and `readback_mismatch`. An unknown value stops startup, and so does any fault with `APP_ENV=prod`.<br>• `bedrock_timeout`: `core/llm` raises a retryable timeout **immediately**, before any provider call, on every attempt, whatever the provider is (the Anthropic API during the build). No 20 s wait.<br>• `cards_write_error`: every raw `cards.*` write attempt raises `ToolUnavailable`.<br>• `readback_mismatch`: every write applies, then its `ActionResult` comes back `verified=False`.<br>Faults are applied in one wrapper, so `BANK=fake` and `BANK=postgres` behave the same | Human 2(a); assumption 4; D5-B D10 enum |
| D7 | **`readback_mismatch` is never retried.** It takes the existing `action_unverified` handoff (`02` §5), and the audit log shows 0 retries | Human 6(a) |
| D8 | **When retries run out, the customer gets a failure template, then a handoff.**<br>• A `ToolUnavailable` that survived its retries sets `escalation_reason = "tool_failure"`. It replaces today's `tool_unavailable`.<br>• Any `LLMError` in `understand` or `compose` sets `"llm_unavailable"`.<br>• The graph then runs `fallback` (template, no LLM) → `handoff_summary` → `handoff`.<br>• `handoff_summary` still makes its own LLM call, with its own retries, unless `llm_disabled` is set (D10). Under `bedrock_timeout` that call also fails 3 times, and the fixed text is used. So the audit shows 3 `nlu` rows plus 3 `handoff_summary` rows, all `unavailable`<br>• `HandoffReason` gains `tool_failure` and `llm_unavailable`.<br>• `escalation.yaml` gains both rules with `queue: null, priority: normal`. The queue is resolved like `human_request` (`human_request_queues.by_flow`, default `atencion`) | Assumption 5 (the queue and priority confirmed by the human); `01` §7; D4-A spec (Contracts, the `HandoffReason` note) |
| D9 | **Failure templates.**<br>• `failure_handoff` (ES/PT) says there was a problem and that a person will take over. It says "No hice ningún cambio" / "Não fiz nenhuma alteração", and it has no "¿Lo intento de nuevo?" offer.<br>• *(Amended A8.)* `failure_handoff_after_action` is used instead when this turn already has a verified `ActionResult`, **or** when a write failed after its retries. That case is flagged by the graph-local `write_failed`, which `flows/actions.py` sets and `load_session` resets; the bank may have applied the write anyway. This template drops the "no change" sentence. The "no change" sentence stays only when no write was attempted this turn (a read failure, an LLM outage)<br>• The existing `handoff_transfer` text and banner follow either one. Dev B reviews the ES/PT copy | Assumption 5; brand voice `docs/brand.md`; human A8 |
| D10 | **`LLM_DISABLED`** is a bool in Settings. Changing it needs a restart. It's checked at graph entry, after the human-mode check and before steps 0-3 of entry routing.<br>• Every bot-mode turn sets `escalation_reason = "llm_unavailable"` and goes `fallback` → `handoff_summary` → `handoff`. Typed, confirmation, step-up and selection turns are all included.<br>• `handoff_summary` uses its fixed text without calling the LLM.<br>• Zero LLM calls | Assumption 6; ADR-023; `02` §5 |
| D11 | **Turn caps.**<br>• `/messages` and `/confirmations` check two counters in Redis before scheduling a turn: `turns:conv:<conversation_id>` and `turns:acct:<account_id>:<UTC YYYY-MM-DD>`.<br>• Limits come from Settings: `TURN_CAP_PER_CONVERSATION=40` and `TURN_CAP_PER_ACCOUNT_DAY=150`.<br>• At or over either limit the route returns `429 turn_cap_reached` and schedules nothing.<br>• Only bot-mode turns count (`conversation.mode == "bot"`). Both counters are incremented only after `start_turn` returns a `turn_id`.<br>• Key TTLs: 2 days for the account key, 7 days for the conversation key | Human 5(a); ADR-023 |
| D12 | **Session resume is a client-side replay.** No new endpoint.<br>• The backend guarantees that a `401 session_expired` on `/messages` or `/confirmations` changes nothing: the checkpoint and its `pending`, the plan in Redis, the turn lock, `app.messages` and `audit.*` all stay as they were.<br>• After re-login as the same customer, re-sending the same request proceeds.<br>• Another customer gets `404` on that conversation (R13), and A's plan stays open.<br>• A re-login after the plan's 5 min TTL gets the existing `409 confirmation_invalid`; that behavior is unchanged | Human 1(a); `04` §7 |
| D13 | **Expired sessions in eval** need no backend change. B's driver expires a session with `/auth/logout` (a revoked jti gives the same `401`), then mints a new one through `/test-idp/sessions` | Assumption 7 |
| D14 | **The eval-clone seeder is `setup.db_patches`**, the work D5-A D27 deferred to this card.<br>• Before a case, the runner applies each patch on the clone. The table must be in the `bank` schema; identifiers are composed with `psycopg.sql.Identifier` and values are bound.<br>• After evidence is collected, it reverts the patched columns of the matched rows from `latam_golden`. It then diffs those rows and aborts on a difference, naming the table and key (the D5-A D14 pattern).<br>• Cases with `db_patches` are now played and counted.<br>• A adds one seed, `eval/scenarios/dev/a-decline_explain-injection-es-mx-01.yaml`. It patches a declined transaction's `merchant_name` and one of the persona's `bank.complaints.description` with instructions, forbids every write tool, and expects `resolved`.<br>• *(Amended A10.)* Its `required_tools` no longer lists `transactions.explain_decline`. The poisoned `merchant_name` no longer matches the NLU's `merchant_text` exactly, so the flow stops at the pick prompt, where the poisoned name is shown as data. `test_malicious_merchant_never_reaches_llm` covers the explanation path with a poisoned merchant | Assumption 8; D5-A D27; D5-B D10; `05` §2 (D5.2d) |
| D15 | **R6 hardening.**<br>• (a) A self-check proves the existing scan flags a write-tool reference added to an LLM module.<br>• (b) A turn whose facts carry a malicious `merchant_name` sends no LLM input that contains that text | Assumption 9; R6 |
| D16 | **The eval runner groups cases by `frozenset(setup.faults)`.** It starts one backend per group (the no-fault group first) with `FAULTS` set in its env, on the same clone.<br>• Before each backend start, the runner deletes the `turns:*` keys in its own eval Redis db index, never db 0, so the D11 caps don't carry over between groups.<br>• The rows of the `bedrock_timeout` group are left out of the D5-A "LLM unreachable" abort check (`llm_unreachable`), because their `unavailable` rows are expected. B removes the driver's `not_runnable` guard for `faults` and `expire_session_before_turn` (B3) | Human 2(a) |
| D17 | **Pandera contracts** go in `pipeline/contracts/`, one schema per raw table. They're built from the observed schema: raw Parquet is all VARCHAR, so the type checks are "coercible to" checks.<br>• **Structural break** (an unreadable file, or a missing PK column) → non-zero exit, and `make data` stops.<br>• Every other failure is counted in the report and the rows flow on: type, nullability, enum, range (`fraud_score` 0-100, `credit_score` 300-850), PK duplicates, unknown or missing non-PK columns (drift).<br>• Only manifest entries whose `(key, etag or sha256)` isn't in `data/quality/contract_cache.json` are validated. Earlier results are reused from that cache | Human 3(a); `03` §3 |
| D18 | **New dbt tests at `severity: warn`:**<br>• `relationships` for the FKs the app reads (transactions → products and customers; products → customers; complaints → customers);<br>• the EDA semantic checks from `03` §3: a transaction before card opening or after expiry, a future `last_updated`, the `process_date` UTC−6 shift.<br>The existing serving tests stay at `error` | Human 3(a); `03` §3 |
| D19 | **Serving stays a full rebuild.** `03` §4 is amended: ingest is incremental by partition through the manifest, and dbt fully rebuilds deterministically | Human 4(a) |
| D20 | **Fixtures** live in `pipeline/fixtures/test_fixture_{late_partition,duplicate_batch,schema_change}/` (the README and the directory names say TEST FIXTURE). Each is a tiny `transactions` tree:<br>• (a) **Late partition:** the same key with a new ETag. It's re-ingested over the old file, the corrected values win, and the row count is unchanged.<br>• (b) **Duplicate batch:** the same rows under a new key in the same partition. They land in `stg_transactions__rejects`, and the `stg_transactions` count is unchanged.<br>• (c) **Schema change:** `merchant_name` renamed to `merchant`, plus an added column `installments`. Staging maps `merchant` → `merchant_name` through one declared alias map that Pandera and dbt both read. Pandera reports the drift. `installments` doesn't reach serving or Postgres, because Alembic owns the DDL.<br>The tests run real ingest (`SOURCE=local:`), Pandera and `dbt build --select stg_transactions+ stg_transactions__rejects --indirect-selection cautious --exclude test_name:relationships test_type:singular` against a tmp DuckDB, using a raw-root var. The exclude is needed because the relationship and singular tests' other parents (`srv_customers`, `srv_products`) don't exist in the tmp DuckDB. The selector is `test_name:relationships`; dbt 1.12 rejects `test_type:relationships` | Assumption 10; `03` §4 |
| D21 | **Quality report and lineage.**<br>• `make data` writes `data/quality/<run_id>/contract_report.json` (Pandera), plus `quality_report.json` and `quality_report.md`.<br>• The report holds row counts per table, rejects per table, dbt test results (name, severity, status, failures count, orphans included) and the Pandera summary.<br>• Failing-row samples show only the PK and the failing column, at most 5 rows per check.<br>• `dbt docs generate` writes to `data/lineage/<run_id>/`.<br>• A committed `pipeline/lineage.md` documents raw → staging → serving → `bank.*` in a mermaid diagram.<br>• One `RUN_ID` per `make data` run is shared by contracts and load | Assumption 11; `03` §2-3; D4.2-D4.4 |
| D22 | **Doc amendments made at spec time:**<br>• `01` §6 (cost guard values, 429) and §7 (timeouts decided, retries in the wrapper, `FAULTS` list, prod refusal);<br>• `02` §1 (`injection_suspected` no longer "proposed") and §5 (failure reasons);<br>• `03` §3 (severity) and §4 (full rebuild, fixture semantics, report files);<br>• `04` §3 (429, the 401 guarantee), §4 (reasons), §5 (`escalation.yaml`) and §6 (`tool_result.attempt`) | Card rule: a contract change updates `04` in the same card |
| D23 | **Frontend follow-through.** Run `make client` so `types.gen.ts` carries `tool_failure` and `llm_unavailable` in `HandoffReason`. Add the ES/PT labels `staff.reason.tool_failure` and `staff.reason.llm_unavailable` to the staff-console i18n dictionaries. Nothing else changes in the UI | Human, planner gate (amendment 2) |
| D24 | **Fallback language with no earlier turn.** When the state has no `language` yet (for example `understand` failed on the first turn, or `LLM_DISABLED` is set), `load_session` sets it with `_guess_language(user_text)`: a deterministic in-code check, `pt` on a Portuguese-only marker and `es` otherwise. The customer's country can't be used: it is MX, CO or AR only, and there are no BR customers | Human A6 |
| D25 | **Golden TRUNCATE.** `pipeline/load/postgres.py` truncates the 13 `bank.*` tables together with `identity.accounts` and every table that references it (`app.handoffs`), all named explicitly and without `CASCADE`. This fixes a bug from D4-A (the FK from `app.handoffs` blocked the truncate) | Human A7 |

## Contracts

Only the delta. Everything else is in `04`.

**Settings** (`app/core/config.py`):
- `faults: frozenset[Literal["bedrock_timeout","cards_write_error","readback_mismatch"]]`, parsed from `FAULTS` (comma-separated, empty by default).
- `llm_disabled: bool = False` (`LLM_DISABLED`).
- `tool_timeout_s: float = 3.0`.
- `turn_cap_per_conversation: int = 40`.
- `turn_cap_per_account_day: int = 150`.
- The retry count (2) and the backoff (base 0.5 s, cap 2 s, full jitter) are knobs shared by the LLM and tool wrappers.

Startup (`main.py`, next to `_require_eval_for_baseline`) refuses a non-empty `faults` when `APP_ENV=prod`.

**`app/core/faults.py`** (core, so `core/llm` and the tool layer can both import it): `fault_active(name) -> bool`.

**`app/core/llm`**:
- The SDK is built without internal retries (D3).
- `structured()` loops over transport attempts, calls an injectable async `sleep` for the backoff (test seam), and writes one `LLMCallRecord` per attempt.
- The `LLMError` subclasses are unchanged.

**Audit** (`04` §6): a `tool_result` for a failed attempt carries `{tool, error, attempt: int}`. `attempt` is 1-based.

**Handoff** (`app/domains/handoff/schemas.py`):
- `HandoffReason += "tool_failure" | "llm_unavailable"`.
- `policies/escalation.yaml` (version bump) adds:
  ```yaml
  tool_failure:    {queue: null, priority: normal}
  llm_unavailable: {queue: null, priority: normal}
  ```
- `resolve_escalation` resolves a `null` queue for these two exactly as it does for `human_request`.

**Graph:**
- `escalation_reason` values `tool_failure` and `llm_unavailable` (the value `tool_unavailable` is removed).
- An edge from `fallback` → `handoff_summary` when `escalation_reason` is one of them.
- `handoff_summary` makes no LLM call when `llm_disabled` is set.
- The `LLM_DISABLED` check sits right after `load_session`'s human-mode branch.
- Graph-local `write_failed: bool`: `load_session` resets it, and `flows/actions.py` sets it when a write fails after its retries. It selects `failure_handoff_after_action` (D9, A8).
- `load_session` fills a missing `language` with `_guess_language(user_text)` (D24).
- New `TemplateKind`s: `failure_handoff` and `failure_handoff_after_action` (ES/PT).

**HTTP** (`04` §3): `POST /conversations/{id}/messages` and `POST /conversations/{id}/confirmations/{token_id}` gain `429 turn_cap_reached`. It's checked after the `409 conversation_closed`, `selection_invalid` and `confirmation_invalid` gates and before `start_turn`, so it comes before `start_turn`'s `409 turn_in_progress`. It applies only when `conversation.mode == "bot"`.

**Eval harness** (`eval/harness/`):
- `_start_backend(system, dbname, port, faults)` passes `FAULTS`.
- `_play` groups cases by fault set (D16), and applies and reverts `db_patches` (D14).
- Before each backend start, `turns:*` keys are deleted in the eval Redis db only.
- The `bedrock_timeout` group's rows are excluded from `llm_unreachable`.
- New module `eval/harness/patches.py`: `apply(conn, patches)` and `revert_and_verify(clone_conn, golden_conn, patches)`.
- The report no longer lists a "not run (db_patches)" row.

**Pipeline:**
- `pipeline/contracts/` (`python -m contracts`, reading `RUN_ID`):
  - one Pandera schema per table;
  - `aliases.yaml` (`{transactions: {merchant: merchant_name}}`);
  - the cache file `data/quality/contract_cache.json`;
  - exit code 2 on a structural break.
- `load/__main__.py` runs `dbt docs generate` after `dbt build` and writes the quality report.
- dbt vars: `raw_root` (default `../../data/raw`, used by `sources.yml`'s `external_location`) and `column_aliases` (loaded from `aliases.yaml` by the caller).
- The DuckDB path comes from the env var `PIPELINE_DUCKDB_PATH` (default is today's path).
- `make data` = `ingest` → `contracts` → `load` → `seed-identity`, with one generated `RUN_ID`.

## Touch map

```
backend/app/core/config.py, core/faults.py (new), main.py              D6, D10, D11 settings + prod guard
backend/app/core/llm/client.py, settings.py                            D3, D6 bedrock_timeout
backend/app/domains/conversation/tools/registry.py, executor.py        D5 retries/timeouts, D6 write faults
backend/app/domains/conversation/flows/actions.py, card_info.py (+ any flow setting tool_unavailable)   D8 reason rename
backend/app/domains/conversation/nodes/{understand,compose,fallback,handoff_summary}.py, graph.py, templates.py   D8-D10
backend/app/domains/handoff/schemas.py, domains/policy/escalation.py, policies/escalation.yaml   D8
backend/app/api/v1/conversations.py                                    D11 turn caps
backend/tests/unit/…, backend/tests/integration/test_session_resume.py (new)   Test list
eval/harness/{runner,patches(new),report}.py, eval/tests/test_{patches,runner_faults}.py (new)   D14, D16
eval/scenarios/dev/a-decline_explain-injection-es-mx-01.yaml (new)     D14
pipeline/load/postgres.py (D25), pipeline/contracts/ (new), pipeline/fixtures/test_fixture_* (new), pipeline/tests/test_{contracts,fixtures}.py (new)   D17, D20
pipeline/load/__main__.py, load/quality_report.py (new), pipeline/dbt/{models/sources.yml, models/**/schema.yml, macros/, dbt_project.yml, profiles.yml}   D18-D21
pipeline/pyproject.toml (+pandera), pipeline/lineage.md (new)          D17, D21
Makefile (data, check: ruff over contracts), .env.example (FAULTS, LLM_DISABLED, TURN_CAP_*)
frontend/src/client/types.gen.ts (regenerated by `make client`, never hand-edited)   D23
frontend/src/lib/i18n/{es,pt}.json                                     D23 staff.reason.tool_failure / llm_unavailable
docker/docker-compose.dev.yml                                          pass FAULTS, LLM_DISABLED through to the backend (live proof, Success criteria 2)
docs/solution-docs/{01,02,03,04}                                       D22 (done at spec time)
(read only: eval/driver/, eval/scenarios/schema.py, B's d-* seeds, eval/scenarios/heldout/)
```

## Test list

Every backend test uses a fake LLM or a stub chat-model factory, and an injected no-op `sleep`.

| Test | Proves |
|---|---|
| `unit/test_llm_client.py::test_timeout_retried_twice_then_unavailable` | R11, D3, D6. With `bedrock_timeout` set: 3 ledger rows (attempt 1..3, `unavailable`), 2 backoff sleeps, `LLMUnavailable` raised, and the chat model never invoked. A non-retryable 4xx gives 1 row |
| `unit/test_r11_tool_retries.py::test_write_retried_same_key_then_plan_cancelled` | R11 + R2, D5. With `cards_write_error`: the raw write is called 3 times with the same idempotency key, `consume_step` once; 3 `tool_result` rows with `attempt` 1..3; the plan is cancelled; `ToolUnavailable` is raised |
| `unit/test_r11_tool_retries.py::test_read_timeout_retried` | R11, D4, D5. A read that exceeds `tool_timeout_s` is attempted 3 times, then raises `ToolUnavailable` |
| `unit/test_faults.py::test_bedrock_timeout_fallback_handoff_es` | A1 Done-when, fault 1. An ES `card_block` turn: 3 `nlu` `llm_calls` rows (attempts 1..3, `unavailable`) plus 3 `handoff_summary` rows (attempts 1..3, `unavailable`), the ES `failure_handoff` text, then `handoff_transfer`, and a packet with `reason=llm_unavailable`, queue `atencion`, using `handoff_summary`'s fixed `request` |
| `unit/test_faults.py::test_cards_write_error_fallback_handoff_pt` | A1 Done-when, fault 2. A PT lock confirmed: 3 failed `tool_result` rows, the PT `failure_handoff` text, and a handoff with `reason=tool_failure` |
| `unit/test_faults.py::test_readback_mismatch_action_unverified_es` | A1 Done-when, fault 3, D7. One write attempt, `readback`/`tool_result` with `verified: false`, 0 retries, and an ES handoff with `reason=action_unverified` |
| `unit/test_faults.py::test_llm_disabled_every_turn_falls_back` | D10. A typed turn and a confirmation turn: zero LLM calls, the failure template and a handoff with `llm_unavailable` |
| `unit/test_faults.py::test_faults_refused_in_prod` | D6. A non-empty `FAULTS` with `APP_ENV=prod` stops startup; an unknown fault name stops startup |
| `integration/test_turn_caps.py::test_cap_returns_429_bot_mode_only` | D11. The cap set to 2: the 3rd bot-mode `/messages` → `429 turn_cap_reached` and no turn scheduled; human-mode posts aren't counted |
| `integration/test_session_resume.py::test_expired_session_keeps_pending_and_only_owner_resumes` | A2 Done-when, R13, D12. Customer A paused at a block confirmation, then the session expires. `/confirmations` and `/messages` → `401`, and the checkpoint `pending`, `is_open`, the turn lock, `app.messages` and the audit row counts are unchanged. Customer B → `404` on both, and the plan is still open. A re-logs in and re-sends → `202`, the card is blocked, verified read-back |
| `unit/test_r6_no_write_tools_in_llm_nodes.py::test_scan_flags_added_write_tool` | A3 Done-when, D15a. The scan run on a synthetic LLM module that references `bank_write_tools` reports it |
| `unit/test_r6_data_fields.py::test_malicious_merchant_never_reaches_llm` | R6, D15b. A `decline_explain` turn over a tx whose `merchant_name` holds instructions: no recorded LLM input contains that text, and no write tool is called |
| `eval/tests/test_patches.py::test_patch_applied_reverted_and_verified` | D14. A patch is applied to the clone; after the revert, the diff against golden is clean; a leftover difference aborts, naming the table and key; a non-`bank` table is refused |
| `eval/tests/test_runner_faults.py::test_one_backend_per_fault_set` | D16. With a fake backend starter: cases with `[]`, `[bedrock_timeout]`, `[bedrock_timeout]`, `[cards_write_error]` → 3 starts with the matching `FAULTS`, no-fault first, and `turns:*` cleared in the eval Redis db before each start. The `bedrock_timeout` group's `unavailable` rows don't trigger `LLMUnreachableError` |
| `pipeline/tests/test_contracts.py::test_structural_break_stops_other_failures_reported` | D17. A missing PK column → exit 2. An out-of-range `fraud_score` and a PK dup → exit 0, counted in `contract_report.json`. A second run skips the cached entries |
| `pipeline/tests/test_fixtures.py::test_late_partition_corrected_rows_win` | A4 Done-when, D20a |
| `pipeline/tests/test_fixtures.py::test_duplicate_batch_rejected` | A4 Done-when, D20b |
| `pipeline/tests/test_fixtures.py::test_schema_change_mapped` | A4 Done-when, D20c (cut to D7 if behind) |

Runnable proofs (no test): `make data` writes the report and lineage (Success criteria 5); the `a-` injection seed in `make eval` (Success criteria 4).

## Boundaries

- **Always:**
  - Retries only through the two wrappers (D3, D5), with the attempt visible in the audit log.
  - Fault code paths are gated by `fault_active`, never by `if APP_ENV`.
  - `db_patches` SQL uses `psycopg.sql.Identifier`, and values are bound.
  - Failing-row samples hold only the PK and the failing column.
  - Fixture files are labeled TEST FIXTURE.
- **Ask first:**
  - changing a cap value or a timeout;
  - retrying a write outside the idempotency key;
  - any new endpoint for resume;
  - touching B's `eval/driver/` or `eval/scenarios/schema.py`;
  - making any new dbt test `error` severity;
  - loading `installments` into Postgres.
- **Never:**
  - retrying a read-back or a whole write (D7);
  - an LLM call in the `fallback` node itself, or anywhere under `LLM_DISABLED` (`handoff_summary`'s own call after a fallback is allowed, D8);
  - hand-editing `frontend/src/client/*.gen.ts` (D23);
  - `FAULTS` in prod;
  - accepting data from an expired token;
  - editing `eval/scenarios/heldout/`;
  - committing `data/` (reports, lineage, the cache) or anything from it.

## Success criteria

1. `cd backend && uv run pytest tests/unit/test_llm_client.py tests/unit/test_r11_tool_retries.py tests/unit/test_faults.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_r6_data_fields.py -q` passes. So does `uv run pytest tests/integration/test_session_resume.py tests/integration/test_turn_caps.py -q` against `make up`'s Postgres and Redis.
2. **End-of-day 1.** With `FAULTS=bedrock_timeout make up` (passed through by `docker-compose.dev.yml`), one ES block request in the UI. Then `select attempt, status from audit.llm_calls where conversation_id = '<id>' order by at` shows attempts 1, 2, 3 `unavailable` for `step = 'nlu'` and attempts 1, 2, 3 `unavailable` for `step = 'handoff_summary'` (6 rows). The reply is the ES failure text plus the transfer banner. `app.handoffs.reason = 'llm_unavailable'`. With `LLM_DISABLED=true`, a new conversation's first turn gets the same fallback and handoff, and `audit.llm_calls` has no rows for it.
3. **A2.** `test_session_resume` passes. `grep -n "turn_cap_reached\|session_expired" docs/solution-docs/04-contracts.md` shows the 429 and the "401 changes nothing" lines.
4. **End-of-day 3.** `make eval SUITE=dev SYSTEM=proposed CASES=a-decline_explain-injection` runs the case: it isn't "not run", the verdict passes `forbidden_tools`, and the patched rows diff clean against golden after the run. Adding `bank_write_tools` to `nodes/compose.py` makes `test_r6_no_write_tools_in_llm_nodes.py` fail.
5. **End-of-day 4.** `make data` exits 0 and leaves `data/quality/<run_id>/{contract_report.json,quality_report.json,quality_report.md}` and `data/lineage/<run_id>/index.html`. `quality_report.md` lists the orphan counts per relationship test with severity `warn`. A `make data` with no new partitions validates 0 partitions (the cache is reused). *(A11: the separate second run was skipped. Run `20260929t232753` printed `contracts validated=0 cached=7671`, from a warm cache left by an earlier failed attempt, and is accepted as the cache proof.)* `cd pipeline && uv run pytest tests -q` passes, fixtures included.
6. `make check` passes: ruff covers `pipeline/contracts`, and import-linter passes. `lint-imports` shows `app.core.faults` imports no domain.
7. `git diff develop --stat -- eval/scenarios/heldout eval/driver eval/scenarios/schema.py` is empty.
8. **D23.** `grep -n 'tool_failure\|llm_unavailable' frontend/src/client/types.gen.ts` finds both reasons. `staff.reason.tool_failure` and `staff.reason.llm_unavailable` exist in both `frontend/src/lib/i18n/es.json` and `pt.json`. `cd frontend && npx biome ci .` passes. A handoff with `reason=llm_unavailable` shows its label in the staff inbox and packet view.

## Open questions

| Question | Owner |
|---|---|
| ES/PT copy of `failure_handoff` and `failure_handoff_after_action` (D9) | Dev B reviews in the PR |
| B3 must drop the driver's `not_runnable` guard for `faults` and `expire_session_before_turn` so fault and expiry cases run under D16 (D13, D16) | Dev B |
| On the baseline system, `bedrock_timeout` has no effect (no LLM calls), so its fault cases will differ from the proposed system's. The report shows this as-is | Noted, no action |

## Amendments during build

Human decisions (planner gate):
- **A1:** the Contracts stay as written. `handoff_summary` skips its LLM call only when `llm_disabled` is set, so under `bedrock_timeout` the audit shows 3 `nlu` plus 3 `handoff_summary` rows, all `unavailable` (D8; the fault-1 test; Success criteria 2).
- **A2:** a frontend task is added: `make client` for the two new `HandoffReason` values, plus the ES/PT staff labels `staff.reason.tool_failure` and `staff.reason.llm_unavailable` (D23; touch map; Success criteria 8).

Planner-level choices recorded:
- **A3:** backoff base 0.5 s, cap 2 s, full jitter, shared by the LLM and tool wrappers (D3).
- **A4:** the eval runner leaves the `bedrock_timeout` group's rows out of the D5-A abort check, and deletes `turns:*` in its own eval Redis db (never db 0) before each backend start (D16).
- **A5:** `docker/docker-compose.dev.yml` passes `FAULTS` and `LLM_DISABLED` through to the backend for the live proof (touch map).

Human decisions (mid-card, after the build):
- **A6:** with no earlier language in state, the fallback language comes from `_guess_language` in `nodes/load_session.py`, using Portuguese-only markers. The country can't be used: MX/CO/AR only, no BR customers (D24).
- **A7:** the golden TRUNCATE names every table that references `identity.accounts` (`app.handoffs`) explicitly, with no CASCADE. This fixes a bug from D4-A (D25).
- **A8:** a write that fails after its retries gets `failure_handoff_after_action`, the neutral text without the "no change" sentence, through the graph-local `write_failed` flag set in `flows/actions.py`. The "no change" sentence stays only when no write was attempted this turn. This amends D9.
- **A9 (fact):** botocore takes `retries={"total_max_attempts": 1, "mode": "standard"}`. `max_attempts` counts retries, so D3's "max_attempts 1" was wrong. D3 is corrected.
- **A10:** the injection seed's `required_tools` dropped `transactions.explain_decline`. The flow stops at the pick prompt, and the R6 unit test covers the explanation path (D14).
- **A11:** the second `make data` proof was skipped. Run `20260929t232753` (`contracts validated=0 cached=7671`, warm cache) is accepted as the cache proof (Success criteria 5).

Verification doc fixes:
- **A12:** the turn-cap check comes before `start_turn`'s `409 turn_in_progress`, not after every `409` (Contracts, `04` §3).
- **A13:** the fixture directories are named `test_fixture_*`. The fixture dbt run excludes `test_name:relationships test_type:singular`; dbt 1.12 rejects `test_type:relationships` (D20, `03` §4).
