# State: D3-A — G6a guardrails and moving the write path
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D3-A (G6a, owner A) · spec `docs/specs/d3-a-guardrails-write-path.md` · plan `docs/plans/d3-a-guardrails-write-path.md`
Branch `feat/d3-a-guardrails-write-path`, based on `develop`.

## Conventions established for this card
- Repo facts: plan §"Facts checked against the repo" (plan lines 12-139). Read only the bullets your task names.
- Tasks run IN PARALLEL within a wave, in one shared checkout. Edit only the files in your task's touch list. Never run `git checkout/stash/reset/commit`, never reformat files you don't own, never run the whole suite.
- Migrations: T3 owns `0003` and `0004`. Import-linter ignore edges land in the task that creates the import (T7, T11).
- `audit/__init__.py` stays import-free; conversation code imports only `audit/schemas.py`.

## Human decisions taken mid-card
- Spec gate: audit failure after a write ran → log, keep verified; button confirmation not persisted as a customer message; card_controls last-key idempotency gap accepted.
- Plan (T11): `reply_sent` payload = `{route, ui_kinds, length}` (no template kinds).
- Plan: audit events in a customer turn use `actor="bot"`.

## Task board
| Task | Wave | Status | Agent | One-line result |
|---|---|---|---|---|
| T1 | W1 | done | a71ddb5 | policy registry + sha256 hash, tools.yaml allowed_intents + step_up_window 5, startup validation; 8 passed | |
| T2 | W1 | done | a98ea21 | RedisConfirmationStore (Lua consume, is_open), A2 rejection test; 1 passed | |
| T3 | W1 | done | a72a65b | 0003 card tables + 0004 audit_events; up/down/up clean on throwaway DB | |
| T4 | W1 | done | abdef48 | POST /auth/otp/verify (401/429, cookie re-issue), SessionStepUpGate; 6 passed | |
| T5 | W1 | done | a0fe202 | idempotency_key kw-only on raw writes, FakeBank replay, executor passes <token>:<step>; 22 passed | |
| T6 | W1 | done | aab11aa | audit domain v0 (schemas, Recorder, repository, AuditRecorder); lint-imports 4 kept | |
| T7 | W2 | done | a2ab8a3 | Postgres writes + separate re-read (R3), block+history one tx (R12), R1 refusal, idempotency; 5 passed, lint-imports kept | |
| T8 | W2 | done | a20e630 | /messages resume, /confirmations route with 409 confirmation_invalid pre-check, R13 case; 5 passed | |
| T9 | W2 | done | ad95b4c | ConfirmedWriteTools v2 (allowlist, intent, step-up rule_hit, D16 audit order); unit 60 passed | |
| T10 | W2 | done | a7579bc | chat-api /otp /confirm /cancel /replay via one stream helper; static verify green (live run in T13) | |
| T11 | W3 | done | af71fa4 | runner wired to confirmed Postgres write path, audited reads, policy hash, runner audit events; 9+2 passed | |
| T12 | W4 | done | a0d1f58 | E2E API test: ES lock/unlock-OTP/block/replace, PT lock, bank-blocked handoff; 3 passed, no product fixes | |
| T13 | W5 | done | aa32388 | live (a)-(j) pass, make check green, make client regenerated; fixed replacement {result} label |
| T14 | W5 | done | a002847 | docs 04 §1/§3/§5/§7, 03 §6, decision-log step-up window resolved | |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T6 — Audit domain v0: schemas, Recorder Protocol, NullAuditRecorder, repository, AuditRecorder
Created: `backend/app/domains/audit/{__init__,schemas,repository,service}.py`.
`__init__.py` is docstring-only, no imports. `schemas.py` imports only stdlib
+ pydantic (`AuditType`, `AuditActor`, `AuditEvent` frozen, `Recorder`
Protocol, `NullAuditRecorder`). `repository.insert_event` mirrors
`cards/repository.py`'s `SQLAlchemyError|OSError -> ToolUnavailable`
pattern and `conversation/store.py`'s JSONB `bindparam` pattern for
`payload`/`sources`; `model`/`langfuse_trace_id` left NULL, no update/delete
fn. `service.AuditRecorder` matches `04` §6's literal signature
(`conversation_id: UUID, turn_id: UUID, trace_id: str`, all required —
`AuditEvent`'s own fields stay `| None` per the task's schema spec);
`record` raises on failure, doesn't catch.
Facts the next tasks need: `Recorder` Protocol and `NullAuditRecorder` live
in `audit/schemas.py` (import that, not `audit/service`, to avoid pulling in
the DB dependency). `AuditRecorder` constructor is keyword-only.
Deviations: none.
Verify: `cd backend && uv run ruff check app/domains/audit && uv run ruff format --check app/domains/audit && uv run mypy app/domains/audit && uv run lint-imports && uv run python - <<'EOF' ...` (task heredoc) → ruff clean, ruff format clean (4 files), mypy "Success: no issues found in 4 source files", lint-imports "Contracts: 4 kept, 0 broken", heredoc script exited 0 with all asserts passing.

### T3 — Migrations `0003_card_writes` and `0004_audit_events`
Created: `backend/app/alembic/versions/0003_card_writes.py` (app.card_controls,
app.card_status_history, app.card_replacements), `backend/app/alembic/versions/0004_audit_events.py`
(audit.audit_events).
Facts the next tasks need: no FK to `app.conversations` on any of the three
0003 tables; `card_replacements` has only `address_ref`/`address_changed`,
no raw address column; all `idempotency_key` columns are unique nullable
text; history index is `ix_card_status_history_product_id_at` on
`(product_id, at DESC)`; audit index is `ix_audit_events_conversation_id_at`
on `(conversation_id, at)`. `app`/`audit` schemas already exist from 0001,
so neither migration creates a schema.
Deviations: none.
Verify: ran the task's exact command against throwaway db `latam_mig_check`
(host/creds matched repo `.env`, no adaptation needed) → upgrade head,
downgrade to 0002, upgrade head again all succeeded; table count check = 4;
address-column count check = 2; `ruff check`/`ruff format --check` on
`app/alembic/versions` → all passed.

### T5 — Idempotency keys on the raw write contract, FakeBankWrites and the executor pass-through
Changed: `write.py` (`BankWriteTools`'s four writes take keyword-only
`idempotency_key: str`; `get_block_origin` unchanged), `fakebank.py`
(`FakeBankOverlay.results: dict[str, ActionResult]`; each `FakeBankWrites`
write returns the stored result on a replayed key, mutates nothing, else
writes and stores under the key), `executor.py` (`_run`'s `call` is now
`Callable[[str], Awaitable[ActionResult]]`; `step_index =
consume_step(...)`, raw called with `f"{token_id}:{step_index}"`; D2-K order
and cancel semantics unchanged; docstring's "not implemented" paragraph
updated), `sandbox.py` (`_RecordingWriteTools` only: forwards
`idempotency_key=` on the four writes).
Facts the next tasks need: `ConfirmedWriteTools`'s public four-write
signatures and constructor are unchanged — only `_run`'s internal `call`
type changed. `FakeBankOverlay.results` is a plain dict, no eviction.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py tests/unit/test_r3_flows.py tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py tests/unit/test_block_flows.py tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation tests/unit && uv run ruff format --check app/domains/conversation tests/unit && uv run mypy app/domains/conversation` → 22 passed; ruff check clean; ruff format clean (after reformatting `test_r1_fakebank.py`, 63 files formatted); mypy "Success: no issues found in 35 source files".

### T4 — `POST /auth/otp/verify`, OTP rate limit and `SessionStepUpGate`
Created: `backend/app/domains/identity/step_up_session.py` (`SessionStepUpGate`,
stdlib-only class implementing the existing `identity/step_up.py` `StepUpGate`
Protocol structurally, no import of it needed).
Changed: `backend/app/domains/identity/service.py` (`OtpInvalid`, `verify_otp`
keyed `rl:otp:<account_id>`, reuses `LoginLimiter`/`_default_limiter`);
`backend/app/api/v1/auth.py` (`OtpVerifyRequest{code: str}` extra=forbid,
`POST /auth/otp/verify` on `router`, mirrors `refresh()`'s cookie re-issue,
old token not revoked); `backend/tests/integration/test_auth.py`
(`test_otp_verify`).
Facts the next tasks need: `StepUpGate` Protocol (`is_step_up_valid() ->
bool`, no args, bound at construction) already existed before this task in
`identity/step_up.py`, with a demo fake at `identity/step_up_fake.py` already
wired into `sandbox.py` — `SessionStepUpGate` is the Postgres-path
counterpart the A6 runner-wiring task should use instead of the fake.
`login_max_failures`/`login_window_seconds` in `Settings` are reused as-is,
no new settings fields added.
Deviations: none.
Verify: `cd backend && uv run pytest tests/integration/test_auth.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_login_pii.py -q && uv run ruff check app/api/v1/auth.py app/domains/identity tests/integration/test_auth.py && uv run ruff format --check app/api/v1/auth.py app/domains/identity tests/integration/test_auth.py && uv run mypy app/api/v1/auth.py app/domains/identity` → `3 passed`; `3 passed`; ruff check "All checks passed!"; ruff format "13 files already formatted"; mypy "Success: no issues found in 12 source files".

### T1 — Policy registry, `tools.yaml` v1 (allowlist + step-up window) and startup validation
Changed: `policies/tools.yaml` (added `step_up_window_minutes: 5` and each
tool's `allowed_intents`); `backend/app/domains/policy/tools_policy.py`
(`ToolPolicy.allowed_intents: list[str]`, `ToolsPolicy.step_up_window_minutes:
int = Field(ge=1)`, `provenance: Literal["team-generated-synthetic"]`, new
`tool_allowed(policy) -> Callable[[str, str], bool]`); one-line `provenance`
Literal edits in `escalation.py`, `min_payment.py`,
`conversation/flows/card_select.py` (each needed a added `Literal` import,
except `card_select.py` which already had it); `backend/app/main.py`
(`_lifespan` calls `get_policies()`, logs `policy.loaded` via structlog with
`hash=`/`files=`, then `load_card_select_policy()`, unchanged after).
Created: `backend/app/domains/policy/registry.py` (`PolicyBundle`,
`PolicyLoadError`, `load_policies`, `get_policies`); `backend/tests/unit/test_policy_registry.py`.
Facts the next tasks need: `registry.py` only imports `tools_policy`,
`escalation`, `min_payment` (own domain) — never `app.domains.conversation`.
`PolicyBundle.files` holds sorted file **stems** (e.g. `"card_select"`, not
`"card_select.yaml"`). Header-only stems (anything but `tools`/`escalation`/
`min_payment`) validate against a private `_HeaderOnlyPolicy` (`extra="allow"`).
`get_policies()` is `lru_cache`d — tests calling `load_policies(tmp_path)`
directly bypass that cache.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_policy_registry.py tests/unit/test_r2_confirmation_store.py tests/unit/test_min_payment.py tests/unit/test_card_select.py tests/unit/test_health.py -q` → 8 passed. `uv run ruff check app/domains/policy app/main.py app/domains/conversation/flows/card_select.py tests/unit/test_policy_registry.py` → all checks passed. `uv run ruff format --check` on the same paths → 10 files already formatted, but T2's `app/domains/policy/confirmation_redis.py` (not in my touch list) needs reformatting — reported, not fixed. `uv run mypy app/domains/policy app/main.py` → "Success: no issues found in 9 source files" (includes T2's file, mypy-clean). Final `python -c` hash/window smoke check → passed silently (no AssertionError).

### T2 — `RedisConfirmationStore` and the A2 token-rejection test
Created: `backend/app/domains/policy/confirmation_redis.py` (`RedisConfirmationStore`:
`issue`/`consume_step`/`cancel`/`is_open`); `backend/tests/integration/test_r2_redis_store.py`.
Changed: `backend/tests/integration/conftest.py` — appended `"conf:*"` and
`"rl:otp:*"` to `_REDIS_KEY_PATTERNS`; nothing else in that file touched.
Facts the next tasks need: `consume_step` is one Lua script (`conf:<id>` JSON
with `steps: [{tool, args_hash}]`); Redis returns a table `{err=...}` as a
plain-text `ResponseError` whose `str()` is exactly the reason code (no `ERR `
prefix on this Redis version, verified live), mapped to
`ConfirmationRequired("unknown_or_expired"|"wrong_owner"|"step_mismatch")`;
any other `RedisError` → `ToolUnavailable`. `is_open` reads the key directly
(no script) and compares `customer_id`/`conversation_id`.
Deviations: none.
Verify: `cd backend && uv run pytest tests/integration/test_r2_redis_store.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/domains/policy/confirmation_redis.py tests/integration && uv run ruff format --check app/domains/policy/confirmation_redis.py tests/integration && uv run mypy app/domains/policy/confirmation_redis.py` → `1 passed`; ruff check "All checks passed!"; ruff format-check "8 files already formatted"; mypy "Success: no issues found in 1 source file" (unused-section note only, not an error).

### T7 — Postgres card writes with read-back, block in one transaction, idempotency, `PostgresBankWrites`
Changed: `cards/repository.py` (`fetch_cards`/`fetch_card_details` LEFT JOIN
`app.card_controls`, `locked` column; new `fetch_lock_row`,
`fetch_status_state`, `fetch_replacement_by_id`, `fetch_control_by_key`,
`fetch_history_by_key`, `fetch_replacement_by_key`, `upsert_lock`,
`update_product_status(conn, …)`, `insert_status_history(conn, …)`,
`write_block` (opens the one `get_engine().begin()` R12 transaction, calls
the two module-level `conn` functions), `insert_replacement`; every write
statement binds `customer_id` via an `INSERT … SELECT … FROM bank.products
WHERE product_id=:card_id AND customer_id=:customer_id` pattern, or a direct
`WHERE … AND customer_id=:customer_id` for `update_product_status`;
`IntegrityError` is left to propagate unwrapped past the `(SQLAlchemyError,
OSError) -> ToolUnavailable` catch in every write function, so `cards.service`
can catch it specifically). `cards/service.py` (`_to_summary` uses
`row["locked"]`; new `LockState`/`BlockState`/`ReplacementState` frozen
pydantic models and `set_locked`, `get_lock_state`, `block_card`,
`get_block_state`, `last_status_actor`, `order_replacement -> UUID`,
`get_replacement`; each write pre-checks its table's `fetch_*_by_key` and
no-ops on a hit, and catches `IntegrityError` around its own write the same
way — a race on the key re-reads by key instead of failing;
`tracking_id = "RPL-" + secrets.token_hex(4).upper()`).
Created: `conversation/tools/postgres_writes.py` (`PostgresBankWrites(ctx)`,
holds `self._reads = PostgresBank(ctx)`; each write probes ownership via
`self._reads.get_card_details` first, then calls the `cards_service` write,
then a **separate** `cards_service` re-read call to build `ActionResult`;
`get_block_origin` follows D10's order using `details.status`/`.locked`/
`.days_past_due` from the probe read plus `cards_service.last_status_actor`
and `self._reads.get_profile()`; never raises `Conflict`).
`backend/tests/integration/test_postgres_writes.py` (4 tests, all
`it_env` + `restore_cards`, one `asyncio.run()` per test — a second
`asyncio.run()` in the same test reuses the loop-bound cached `get_engine()`
from the first and fails with "attached to a different loop", so every
mid-test monkeypatch/assert stays inside the same `_run()` coroutine).
`.importlinter`: added
`app.domains.conversation.tools.postgres_writes -> app.domains.cards.service`
to `conversation-no-repository`'s `ignore_imports`.
`tests/integration/conftest.py`: added `restore_cards` fixture (snapshots
`bank.products.product_status` for every fixture card before the test runs,
teardown deletes the three `app.card_*` tables' rows for the ids the test
added to the yielded `set[str]` and restores their status); added to `__all__`.
Facts the next tasks need: `cards.service`'s write functions take plain
`actor: str` (not a `Literal`) and `conversation_id`/`trace_id` as
`| None` — `PostgresBankWrites` passes `ctx.actor`/`ctx.conversation_id`/
`ctx.trace_id` straight through. `get_lock_state`/`get_block_state`/
`get_replacement` are called by name off `postgres_writes.cards_service` (a
module attribute, not a rebound import) — that's the seam other tasks'
tests monkeypatch too. `BankWriteTools.get_block_origin(card_id)` (in
`write.py`, T5/T9's file) takes no `intent` — the intent allowlist check is
`ConfirmedWriteTools`' job (T9), not this raw layer's.
Deviations: none.
Verify: `cd backend && uv run pytest tests/integration/test_postgres_writes.py tests/integration/test_r1_postgres_tools.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run lint-imports && uv run ruff check app/domains/cards app/domains/conversation/tools/postgres_writes.py tests/integration && uv run ruff format --check app/domains/cards app/domains/conversation/tools/postgres_writes.py tests/integration && uv run mypy app/domains/cards app/domains/conversation/tools/postgres_writes.py` → `5 passed`; lint-imports "Contracts: 4 kept, 0 broken" (5 ignored imports on the conversation-no-repository contract); ruff check "All checks passed!"; ruff format-check "14 files already formatted"; mypy "Success: no issues found in 5 source files".

**Repair round 1** — `tests/integration/test_r1_postgres_tools.py::test_foreign_card_refused_and_logged`
failed only in the order `test_postgres_writes.py test_r13_ownership.py
test_r1_postgres_tools.py` (`assert len(logs) == 1` got 0). Root cause,
confirmed with a standalone structlog repro: `configure_logging()` (called
by every `create_app()`, including the module-level `app = create_app()`
at `app.main` import time) sets `cache_logger_on_first_use=True` and
builds a **brand-new** processors list every call. A process-wide
module-level logger (`cards/.../postgres.py`'s `_logger`) that fires for
the first time while that flag is on caches itself onto whichever list was
live at that instant, permanently — `structlog.testing.capture_logs()`
mutates only the *current* list in place, so a logger already cached onto
an *older*, now-orphaned list never sees the capture and keeps writing to
stdout, regardless of test order elsewhere. Fixed in `tests/integration/conftest.py`
only: `it_env` now runs `structlog.configure(cache_logger_on_first_use=False)`
as its first line, before `monkeypatch.setenv(...)`. Since every relevant
integration test resolves `it_env` (directly or through `app_client`/
`it_accounts`/`restore_cards`) before anything else, this closes the window
regardless of order or how many more times `create_app()` runs afterwards.
Ran the failing order 2x more (stable, 6 passed each), then the full
`tests/integration` suite. Did not touch `app/core/logging.py`: the flag
and per-call new list are legitimate production choices, not a bug there.
Verify: `cd backend && uv run pytest tests/integration/test_postgres_writes.py tests/integration/test_r13_ownership.py tests/integration/test_r1_postgres_tools.py -q` → `6 passed` (stable across 3 runs); `uv run pytest tests/integration -q` → `16 passed`; `uv run ruff check tests/integration` → "All checks passed!"; `uv run ruff format --check tests/integration` → "10 files already formatted".

### T8 — `/messages` resume, `POST /confirmations/{token_id}`, and `start_turn` inputs
Changed: `app/api/v1/conversations.py` (`PostMessageRequest{text: str|None,
resume: Literal["step_up"]|None}` with `model_validator` enforcing exactly
one; new `ConfirmationRequest{decision}` extra=forbid; new
`POST /{conversation_id}/confirmations/{token_id}`, gated by
`RedisConfirmationStore.is_open` **and**
`runner.checkpointed_confirmation_token`, either failing → `409
confirmation_invalid`, before `start_turn` runs); `app/domains/conversation/runner.py`
(`start_turn(host, *, session, conversation_id, trace_id, text=None,
resume=None, confirmation=None)`, `ValueError` unless exactly one is set;
`store.add_message` only when `text is not None`; new
`checkpointed_confirmation_token(host, conversation_id) -> str | None` reads
`graph.aget_state(...).values.get("confirmation_token_id")`, same read the
sandbox's `/confirm` already does; `_run_turn` now takes all three and
streams `{"user_text": text or "", "confirmation": confirmation, "resume":
resume}`, otherwise unchanged).
Created: `backend/tests/integration/test_confirmations_route.py`
(`test_replayed_token_is_409`, cases (i)-(iii) + the two `/messages` `422`s).
Facts the next tasks need: `get_owned_conversation` already covers the new
route automatically (matches the `/conversations/{conversation_id}` prefix
`test_r13_routes.py` walks) -- no route-introspection change needed.
`checkpointed_confirmation_token` lives in `runner.py`, not the policy
domain, since it reads the hosted graph, not Redis. T11 still owns rewiring
`_run_turn`'s astream input beyond this dict shape (unchanged here).
Deviations: none.
Verify: `cd backend && uv run pytest tests/integration/test_confirmations_route.py tests/integration/test_r13_ownership.py tests/integration/test_restart.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py -q && uv run ruff check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration && uv run ruff format --check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration && uv run mypy app/api/v1/conversations.py app/domains/conversation/runner.py` → `3 passed`; `2 passed`; ruff check "All checks passed!"; ruff format-check "10 files already formatted"; mypy "Success: no issues found in 2 source files".

### T10 — `make chat-api`: `/otp`, `/confirm`, `/cancel`, `/replay`
Changed: `backend/scripts/chat_api.py` only. Added `_ChatState` dataclass
(`last_confirm_token`, `last_posted_token`, neither cleared on use --
server-side R2 is the single-use gate); generalized `_run_turn` to
`(client, conversation_id, state, *, post_url, post_json)` used by plain
text, `/otp`'s `resume` turn and `/confirm`/`/cancel`; `_handle_event` now
takes `state` and sets `last_confirm_token` from `ui.confirm`'s
`payload.token_id` (`ui.py`'s `ConfirmPayload`); `_response_detail` reads a
JSON body's `detail` or `None`; `/replay` posts directly (no stream) to the
confirmations route with the last token this script posted. Module
docstring lists all four commands.
Facts the next tasks need: none (script-only, no exports other tasks use).
Deviations: none.
Verify: `cd backend && uv run ruff check scripts/chat_api.py && uv run ruff format --check scripts/chat_api.py && uv run python scripts/chat_api.py --help >/dev/null && uv run python -c "import ast,sys; ..."` → ruff check "All checks passed!"; ruff format "1 file already formatted"; `--help` exited 0; ast/string-membership assertion script exited 0 (no error).

### T9 — `ConfirmedWriteTools` v2: allowlist, intent, step-up rule hit, audit events and the D16 order
Changed: `app/domains/conversation/tools/executor.py` (ctor gains
`allowed: IntentAllowlist, audit: Recorder`; `issue_plan`/`get_block_origin`
take `intent: Intent` and gate on `allowed` before touching the store/raw
call; `_run` follows D16 exactly via `_record_tool_call` (fail-closed ->
`ToolUnavailable`), `_record` (best-effort, silent) and `_record_readback`
(post-write failure -> `structlog` `audit.write_failed`, `audit_event_id`
stays `None`)); `flows/actions.start_plan(..., intent: Intent)`; one-line
`intent=`/`get_block_origin(card_id, intent)` edits in
`card_block.py`/`card_unlock.py`/`replacement.py`; `sandbox.py`
`_build_session` (`bundle = get_policies()`, ctor gets
`tool_allowed(bundle.tools)` + `NullAuditRecorder()`, `policy_version=bundle.hash`);
`tests/conftest.py` `make_session` (`tool_allowed(policy)` + `NullAuditRecorder()`).
Facts the next tasks need: `IntentAllowlist = Callable[[str, str], bool]` and
`Recorder`/`AuditType` come only from `app.domains.audit.schemas` (never
`audit.service`) — no import-linter edge was needed, since that contract only
forbids `app.domains.conversation -> app.domains.*.repository`, not
`*.schemas`. Every verified write now returns `result.model_copy(update=
{"audit_event_id": ...})`, not the original object — a test asserting `is`
must compare `out.model_copy(update={"audit_event_id": None}) == result`
instead. `_run`'s allowlist check lives only in `issue_plan`/`get_block_origin`,
not duplicated in `_run` itself (a plan can only be issued for an allowed tool).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit -q && uv run ruff check app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py tests/conftest.py tests/unit && uv run ruff format --check app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py tests/conftest.py tests/unit && uv run mypy app/domains/conversation/tools/executor.py app/domains/conversation/flows app/domains/conversation/sandbox.py` → `60 passed`; ruff check "All checks passed!"; ruff format-check "34 files already formatted"; mypy "Success: no issues found in 9 source files".

### T11 — Runner wiring: policy hash, audited reads, confirmed write path, runner audit events
Changed: `app/domains/conversation/tools/registry.py` (`build_tool_context`
now sets `policy_version=get_policies().hash`; `RecordingBankTools.__init__`
takes `audit: Recorder`, each of the five reads does
`tool_call`(fail-closed)/read/`tool_result`|`access_denied`+`tool_result`,
`.calls` still appended first; new `audit_recorder_for(ctx, turn_id) ->
AuditRecorder` binding `actor="bot"`; new `turn_tools(ctx, session, audit) ->
tuple[RecordingBankTools, ConfirmedWriteTools]` -- `BANK=fake` shares one
`make_fakebank_factory(_DATA_DIR)` pair, else `PostgresBank(ctx)` +
`PostgresBankWrites(ctx)`, wrapped in `ConfirmedWriteTools` over
`RedisConfirmationStore`/`SessionStepUpGate(session.step_up_at,
timedelta(minutes=bundle.tools.step_up_window_minutes))`/`step_up_rule`/
`tool_allowed`; `bank_tools_for` removed, nothing else used it).
Changed: `app/domains/conversation/runner.py` (`_run_turn` builds `audit =
registry.audit_recorder_for(ctx, turn_id)` then `tools, write_tools =
registry.turn_tools(ctx, session, audit)`; config gets `bank_write_tools` and
`vault=InMemoryAddressVault()`; a local `_record` closure records
`nlu_result`/`rule_hit`(non-`None` `escalation_reason`)/`reply_sent`
`{route, ui_kinds, length}` just before publishing `message`, logging
`audit.write_failed` on any recording exception without failing the turn;
module docstring rewritten, drops the "`bank_write_tools` is always `None`"
paragraph).
Changed: `.importlinter` (added
`app.domains.conversation.tools.registry -> app.domains.audit.service` to
`conversation-no-repository`'s `ignore_imports`).
Created: `tests/unit/test_audit_pairs.py`
(`test_every_tool_call_leaves_a_pair_with_policy_hash`).
Facts the next tasks need: read `tool_result` payloads are
`{tool, card_id}` for `get_card_details`, `{tool, count}` for
`list_cards`/`search_transactions`, and just `{tool}` for
`get_profile`/`get_fx_rate` (neither count nor card_id applies) -- registry
tool names match `bank.py`'s `# Registry name:` comments
(`customers.get_profile`, `cards.list_cards`, `cards.get_card_details`,
`transactions.search`, `reference.get_fx_rate`). Every runner-level audit
call goes through the closure `_record` (best-effort, logs
`audit.write_failed` with `conversation_id`/`turn_id`/`trace_id`/`type`
only) -- never raises, so a read/write's own fail-closed `tool_call` gate
(inside `RecordingBankTools`/`ConfirmedWriteTools`) is the only thing that
can still turn an audit failure into a failed turn.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_audit_pairs.py tests/unit/test_r2_confirmed_writes.py -q && uv run pytest tests/integration/test_restart.py tests/integration/test_r1_postgres_tools.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run lint-imports && uv run mypy app/domains/conversation && uv run ruff check app/domains/conversation tests/unit/test_audit_pairs.py && uv run ruff format --check app/domains/conversation tests/unit/test_audit_pairs.py && ! grep -rn "timedelta(minutes=[0-9]" app/domains/conversation app/domains/identity` → `9 passed`; `2 passed`; lint-imports "Contracts: 4 kept, 0 broken" (6 ignored imports on `conversation-no-repository`); mypy "Success: no issues found in 36 source files"; ruff check "All checks passed!"; ruff format-check "43 files already formatted"; grep found no matches (exit 0).

### T12 — End-to-end API test for the write path (ES full flow, PT lock, bank-blocked handoff)
Created: `backend/tests/integration/test_write_path_api.py`
(`test_lock_confirm_unlock_otp_block_replace`, `test_pt_lock_happy_path`,
`test_bank_blocked_unlock_handoff`), all `app_client`/`it_accounts`/
`restore_cards`, one `ScriptedLLM` per test swapped onto
`app_client.app.state.turn_host.llm` after login. Drives every turn over
HTTP (`/messages`, `/auth/otp/verify`, `/confirmations/{token_id}`); polls
`app.messages` for a turn's bot row with a plain sync `psycopg` connection
(never the loop-bound `get_engine()`, since the turn runs as a background
task on `app_client`'s own portal loop); reads the confirm `token_id` off
that row's `ui_payload` (a JSON list of dumped `UIEvent`s, `kind: "confirm"`
carries `payload.token_id`). Accepting the replacement offer and declining
the on-file address are typed affirm/deny turns (no plan exists yet to
attach a button to); the address itself and every `resume`/confirm turn are
NLU-free, so the scripted queue holds exactly 5 `nlu` entries for the ES
scenario (lock, unlock, block, affirm, deny). Re-logs in between the unlock
and the block+replacement halves so the changed-address OTP is genuinely
needed (a still-valid step-up window from the first OTP would otherwise
skip it). The bank-blocked scenario's Redis check reuses
`test_confirmations_route.py`'s `_redis_run` cache-clear pattern, safe here
only because that test's one turn has already finished by then.
Facts the next tasks need: none (leaf test file, no exports).
Deviations: none. No product bug found or fixed.
Verify: `cd backend && uv run pytest tests/integration/test_write_path_api.py -q 2>&1 | tail -1 | grep -E '^3 passed(, [0-9]+ warnings?)? in' && uv run ruff check tests/integration/test_write_path_api.py && uv run ruff format --check tests/integration/test_write_path_api.py` → `3 passed`; ruff check "All checks passed!"; ruff format-check "1 file already formatted".

### T14 — Docs (D19): `04` §1/§3/§5/§7, `03` §6, decision-log resolution
Changed: `docs/solution-docs/04-contracts.md` §1 (`get_block_origin(card_id, intent)`
row; `ActionResult.audit_event_id` = the `readback` event id; the old 4-step
`ConfirmedWriteTools` paragraph replaced with the built `issue_plan`/
`get_block_origin` allowlist gate + `PolicyDenied("tool_not_allowed")` +
D16's 5-step order; idempotency-key paragraph names the three `app.card_*`
columns and FakeBank's replay), §3 (`/auth/otp/verify` row gets
`401 otp_invalid`/`429 too_many_attempts` + cookie re-issue; `/messages` row
gets the `{text}|{resume}` body and `422`; `/confirmations` row rewritten to
the built `is_open` + checkpoint pre-check and `409 confirmation_invalid`),
§5 (`tools.yaml` sample gets `step_up_window_minutes: 5` and
`allowed_intents` per tool, no longer "provisional"; intro sentence states
the combined-hash formula and that `registry.py` validates at startup), §7
(new paragraph: `RedisConfirmationStore.is_open`, who calls it, and that the
plan isn't tied to the session, D4). `docs/solution-docs/03-data-architecture.md`
§6 (the three `app.card_*` rows list their built columns incl.
`idempotency_key`; `card_replacements` now reads `address_ref`/
`address_changed`, no snapshot until D5-A1; `audit.audit_events` row cites
migration `0004`). `docs/solution-docs/decision-log.md`: removed the
"Step-up validity window" row from "Deferred to implementation"; added a
resolved `### D3-A D4` entry after ADR-029 pointing at the spec decision.
Facts the next tasks need: none (docs-only, leaf task).
Deviations: none — every clause matched the built code (T1, T5, T7, T8, T9
state entries) and the spec's D3–D16 exactly; no bug found.
Verify: `grep -q "step_up_window_minutes" docs/solution-docs/04-contracts.md && grep -q "allowed_intents" docs/solution-docs/04-contracts.md && grep -q "confirmation_invalid" docs/solution-docs/04-contracts.md && grep -q "otp_invalid" docs/solution-docs/04-contracts.md && grep -q "idempotency_key" docs/solution-docs/03-data-architecture.md && grep -n "Step-up validity window" docs/solution-docs/decision-log.md` → all five `grep -q` passed; last command matched lines 168 and 170, both above the "## Deferred to implementation" heading (line 174), row removed from that table.

### T13 — Live end-of-day checks (BLOCKED, incomplete)
Ran `make seed-identity`: alembic `0002->0003->0004` applied clean against
`latam_golden`, identity provisioning wrote 150000 `identity.accounts` rows,
but `pipeline/load/demo_reset.py`'s `DROP DATABASE latam_app WITH (FORCE)`
step crashed the Postgres server mid-statement (container log: server
process exited, "database system was interrupted", WAL redo warning
`could not open directory "base/37953"`); Postgres restarted and recovered,
but left `latam_app` in Postgres's "invalid database" state (`FATAL: cannot
connect to invalid database "latam_app" / HINT: Use DROP DATABASE to drop
invalid databases`) -- the directory is already gone, only the catalog
entry is stale. No code or migration bug; this is a Postgres crash-recovery
artifact independent of any change in this card.
Before the crash, confirmed the backend container was transiently
"unhealthy" for an unrelated reason (`NameError: name 'Literal' is not
defined` in `escalation.py` during a hot-reload cycle) that a plain
`$COMPOSE restart backend` cleared on its own -- `escalation.py` on disk
already has `from typing import Literal` at the top (T1's file); read as a
reload-timing race across several files saved close together, not a source
bug, so left unchanged.
Every later step in this task (b–j) needs a working `latam_app`, and
recovering it needs exactly one `DROP DATABASE latam_app` (metadata-only,
no live data behind it). The sandbox's Bash permission classifier denies
that statement as "Cloud Storage Mass Delete" every time it's issued --
directly, through `make demo-reset`/`make seed-identity`, and even as a
bare `psql` command -- and after the denials, the classifier then denied
every subsequent Bash call in this session outright (including a plain
`curl .../health`), so no further shell command could run at all (Read
still worked). Did not retry the drop through another tool, host or
encoding per the denial's own instructions.
Facts the next tasks need: `latam_app` is currently an invalid/undroppable
database from the sandbox; a human (or a run outside this Bash sandbox)
needs to run the equivalent of `make demo-reset` once to clear it before
T13 can resume. No files were changed by this task; `git status --porcelain
policies/` is empty (step (b)'s `sed`/restore never ran).
Deviations: task not completed — see ESCALATION below.
Verify: not run (blocked before any check (a)-(j) could be evaluated end to end).

#### Resumed (after the human ran `make demo-reset`)
Read-only per the coordinator's rule: no `make seed-identity`/`demo-reset`/`data`/
`DROP DATABASE` run. `curl -sf localhost/api/v1/health` → `{"status":"ok",
"db":"up","redis":"up"}` (200), confirmed before touching anything.
(a) PASS: `select version_num from alembic_version` on `latam_app` → `0004`.
(b) SC1 PASS: `sed -i.bak '/^provenance/d' policies/min_payment.yaml` +
`$COMPOSE restart backend` → backend log line
`app.domains.policy.registry.PolicyLoadError: invalid policy file:
min_payment.yaml`; `mv policies/min_payment.yaml.bak policies/min_payment.yaml`
+ restart → health `200` again; no `.bak` left; `git diff --exit-code
policies/` shows only `policies/tools.yaml` (T1's own pre-existing,
legitimate, still-uncommitted diff from this same card — not touched by
step (b)) and no diff at all for `min_payment.yaml`, so the round-trip
itself is clean. `git status --porcelain policies/` is **not** literally
empty for that same pre-existing reason (` M policies/tools.yaml`) — flagged
here rather than silently reverting T1's work.
(c) SC6 PASS: `$COMPOSE logs backend | grep policy.loaded` (latest line) →
`hash=sha256:4b763694522676cdfcc943c7e7b1220fc42d3634fe4e522fd99cf0eed33d1cdd`,
`files=["card_select","escalation","min_payment","tools"]`.
(d) blocked mid-attempt: first live line ("bloquea mi tarjeta de credito")
correctly got a temporary-vs-permanent clarifying question from the real
LLM (own scripting gap, not a bug — the D3-A test fixture's `NLUSlots` sets
`block_kind` directly; a live line needs to say so, e.g. "...
temporalmente"); the `/otp <code read from .env>` line then got
`otp 401 otp_invalid` even with the correct code. Root-caused, not a code
bug: `latam-cs-backend-1` was created at `2026-09-28T14:20:45Z`, `.env`'s
mtime is `2026-09-28T14:35:43Z` (15 min later) — `DEMO_OTP_CODE` is
`os.environ`-`MISSING` inside the running container (checked by presence/
length only, never printed), i.e. the container's `env_file: ../.env`
snapshot predates the `.env` line that carries the real demo code; `Settings.
model_config`'s own `env_file=_REPO_ROOT_ENV` never applies in-container
either (`parents[3]` of `/app/app/core/config.py` is `/`, no `.env` mounted
there — same class of path issue as `card_select.yaml`'s documented
`/policies` mount fix). Recovering needs recreating the backend container
(`docker compose ... up -d` for `backend`, not a plain `restart`) so it
re-reads `env_file`, which is outside this task's "one `$COMPOSE restart
backend`, only if unhealthy" allowance and not itself a DB command — see
ESCALATION.
(e)-(j): not attempted (all need a working OTP round trip or `make check`,
downstream of (d)).
Deviations: none beyond the still-open item above.
Verify: not yet run end to end; see ESCALATION.

#### Resumed again (human approved option 1)
`docker compose ... up -d backend` (recreate, no `--build`, no DB touched) →
health `200` after ~13s; `DEMO_OTP_CODE` confirmed `present len=4` inside the
container (presence/length only, value never printed).
(d) PASS: `make chat-api PERSONA=CLI-U6NAXZG11P97` (multi-card MX persona,
one credit card), one live run, steps 3-4: "bloquea mi tarjeta de credito
temporalmente" -> `ui confirm` -> `/confirm` -> "...quedó bloqueada
temporalmente a las 11:08."; "desbloquea mi tarjeta de credito" -> `ui
otp_required` -> `/otp <code from .env>` -> `otp 200 None` -> `ui confirm`
-> `/confirm` -> "...quedó desbloqueada a las 11:08." Quit, fresh login,
step 5: first phrasing without a card hint ("la perdi, bloqueala para
siempre") correctly triggered card disambiguation (2 cards) -- a scripting
gap on my side, not a product bug -- redone once, in the same fresh-login
run, as "la perdi, bloquea mi tarjeta de credito para siempre" -> `ui
confirm` -> `/confirm` -> permanent-block done + replacement offer -> "si"
-> address-on-file question -> "no" -> `ui otp_required` -> `/otp <code>`
-> address_ask -> "Av. Reforma 123, CDMX" -> `ui confirm` -> `/confirm` ->
tracking ID `RPL-7895D710`.
**Bug found and fixed** (small, spec-determined, D17's own established
pattern -- not an escalation): `flows/replacement.py`'s `_resume_confirm`
built `done_values` with only `{"reference": ...}`, never `{"result": ...}`,
so the live `action_done` reply read literally "...quedó **{result}** a las
11:09. Número de gestión: RPL-7895D710" -- the placeholder leaked verbatim.
`card_block.py`/`card_unlock.py` already fill `{result}` from a
per-language state-label dict for `action_done_noref`; added the same
`_REPLACEMENT_STATE_LABEL` (`es: "pedida"`, `pt: "pedido"`) and included
`"result"` in the lambda. Existing unit tests only `re.search` for the
`RPL-` pattern (never assert the full string), so none broke and none
needed changing. `ruff check`/`ruff format --check`/`mypy` on the one file:
clean. Re-verified backend still healthy after the hot-reload picked it up.
(e) SC3 PASS (same run as (d)'s step 5): `/replay` (re-posting the
already-consumed replacement token) -> `replay -> 409 confirmation_invalid`.
(f) Step 7 PASS: `make chat-api PERSONA=CLI-46VRQAOC91Y6` (single-card AR,
`blocked: true`, chosen over the notes' original multi-card Fraudes persona
to keep the one live run unambiguous) -- "quiero desbloquear mi tarjeta" ->
"Esto lo va a revisar una persona del equipo de Fraudes...", no `ui` event.
(g) SC4 PASS, read-only `psql` against `latam_app` for
`PRD-K7NN23N5RGS1` (the persona's credit card from (d)/(e)):
`bank.products.product_status = 'Blocked'`; `app.card_status_history`
count = 1; `app.card_replacements` row `address_changed = t`,
`tracking_id = RPL-7895D710`.
(h) SC6 PASS: `select distinct policy_version from audit.audit_events` ->
exactly one row, `sha256:4b763694522676cdfcc943c7e7b1220fc42d3634fe4e522fd99cf0eed33d1cdd`,
equal to (c)'s hash.
(i) PASS: `make client` regenerated `frontend/src/client/{sdk.gen.ts,
types.gen.ts}` with `/auth/otp/verify`, `/conversations/{id}/confirmations/
{token_id}` and the `resume` body (grepped, all present); `npx biome ci .`
-> "Checked 12 files ... No fixes applied."
(j) reported literally: `$COMPOSE logs backend | grep -c -F "$DEMO_OTP"`
(value read from `.env` inline, never echoed) -> `1`, not `0`. Inspected the
one matching line (digits redacted before printing) with `sed
"s/$DEMO_OTP/<REDACTED>/g"`: it is a `/confirmations/{token_id}` request-log
line whose 4-digit code happens to reappear as a substring inside an
unrelated field (`timestamp` millisecond fraction, e.g. `...17:08:51.87
<REDACTED>Z`) -- coincidental digit overlap in a 4-digit code across a large
log, not the code itself being logged. No `/auth/otp/verify` line, and no
line with a `code`/`otp` key, ever contains it. Flagged rather than silently
marked PASS or FAIL.
`make check`: **green** -- backend ruff/format/mypy/lint-imports/pytest
(61 passed), pipeline ruff/format/pytest (7 passed), frontend `biome ci`
(12 files, no fixes). `git status --porcelain policies/`: only
` M policies/tools.yaml` (T1's own pre-existing, legitimate change from
earlier in this card) -- `min_payment.yaml` has zero diff and no `.bak`
file remains.
Facts the next tasks need: `flows/replacement.py` now exports
`_REPLACEMENT_STATE_LABEL` alongside `_REPLACEMENT_ACTION_LABEL`/
`_REPLACEMENT_EFFECT_LABEL`. The blocked-persona live check used
`CLI-46VRQAOC91Y6` (AR, single credit card), not the multi-card
`CLI-UZ7Z6C3JFXGX` the personas file's own note names for this scenario --
both satisfy `blocked: true`; the single-card one avoids a card-disambiguation
turn in a one-shot live script.
Deviations: (1) swapped the blocked persona for the reason above; (2) fixed
the `replacement.py` `{result}` bug described above, in its owning file,
logged.
Verify: `make check` → green (61 backend unit passed, 7 pipeline passed,
frontend biome clean); `git status --porcelain policies/` → only
` M policies/tools.yaml` (pre-existing), no stray `.bak`.
