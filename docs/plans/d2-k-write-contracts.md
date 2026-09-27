# Plan: D2-K — Write-side contracts PR

Spec: [`docs/specs/d2-k-write-contracts.md`](../specs/d2-k-write-contracts.md) · Branch: `feat/d2-k-write-contracts`

## Facts checked against the repo

- **Base:** `feat/d2-k-write-contracts` is at `9ab3f7a`, the same commit as `develop` and `origin/develop`. The only change on the branch is the untracked spec. The spec's criterion 5 (`git diff develop --stat -- …`) therefore compares against `9ab3f7a`.
- **Baseline is green (checked 2026-09-27):** from `backend/`, `ruff check app tests` is clean, `ruff format --check` reports 63 files formatted, `mypy app` reports no issues in 51 files, `lint-imports` shows 4 contracts KEPT, and `pytest tests/unit -q` shows 14 passed. Any red after a task comes from that task.
- **How commands run:** every command runs as `cd backend && uv run …` from the repo root. uv warns that `VIRTUAL_ENV=…/.venv` (the root EDA venv) doesn't match `backend/.venv`. The warning is harmless, so ignore it. Pydantic is 2.13.5. There is **no pytest-asyncio**: existing tests drive coroutines with `asyncio.run(...)`, and new tests do the same.
- **New packages:** `backend/app/domains/policy/` and `backend/app/domains/identity/` don't exist yet. `backend/app/core/actions.py`, `conversation/ui.py`, `conversation/tools/write.py` and `conversation/tools/executor.py` are new too. Every other file in the touch map exists.
- **`backend/app/core/errors.py`:** has `ToolError(Exception)` plus `NotFound`, `AccessDenied` and `ToolUnavailable`, each with `code: ClassVar[str]` and an `__all__`. Its module docstring already says "D2 adds `PolicyDenied`, `ConfirmationRequired`, `StepUpRequired` and `Conflict`".
- **`backend/app/domains/cards/schemas.py`:** `__all__ = ["CardDetails", "CardSummary"]`, uses `ConfigDict(frozen=True)`, and imports only pydantic and the stdlib.
- **`backend/app/domains/conversation/tools/`:** `bank.py` holds the `BankReadTools` Protocol, which is the analogue for `BankWriteTools`. Each method body is a comment with the registry name and "May raise", followed by `...`. `BankToolsFactory = Callable[[ToolContext], BankReadTools]`, with a docstring under it. `context.py` holds `ToolContext`. `__init__.py` re-exports `BankReadTools`, `BankToolsFactory` and `ToolContext` through `__all__`. That `__all__` is mandatory, because mypy runs `no_implicit_reexport` on `app.domains.conversation.*`.
- **`backend/app/domains/conversation/state.py`:** `actions: NotRequired[Annotated[list[dict[str, Any]], add]]`. `Any` is used **only** on that line, so the import must go when the line changes (otherwise Ruff F401). `Fact` (frozen: `key`, `value`, `source`) and `Pending` (`flow`, `node`, `awaiting_slot: str | None`) are defined here. `ui.py` imports `Fact` from here. **Nothing in `app/` reads `actions` today.**
- **`backend/app/domains/conversation/graph.py`:** `TurnInput{user_text: str}`, `TurnOutput{reply: str}`, and `GraphState(TurnState)` with `user_text`/`reply` re-declared `NotRequired` (the docstring explains why). The node modules import `GraphState` from `graph.py`, and `build_graph` imports the nodes inside its own body to avoid an import cycle. So `ui.py` **must not** import `graph.py`. `run_turn` calls `graph.astream({"user_text": text}, config=config, stream_mode="updates")`. That is the **only** `astream`/`ainvoke` call on the turn graph in `app/`, `scripts/` and `tests/`: `sandbox.py`, `scripts/sandbox_ui.py`, `tests/unit/test_graph.py` and `tests/unit/test_sandbox_conversations.py` all go through `run_turn`. Changing it covers D17's "every caller passes `confirmation`".
- **`backend/app/domains/conversation/nodes/load_session.py`:** returns `{"customer_id", "country", "facts": RESET_FACTS, "nlu": None, "escalation_reason": None}`. D16 adds `"ui": []`. The graph's shape doesn't change (no new node or edge), so `docs/diagrams/turn-graph-v0.mmd` needs no regeneration.
- **The R6 scan targets:** under `conversation/nodes/` and `conversation/flows/`, only `nodes/understand.py` and `nodes/compose.py` import `app.core.llm`, both as `from app.core.llm import …`. `flows/card_info.py` and `flows/card_select.py` don't. Nothing in `app/` references `bank_write_tools`, `BankWriteTools`, `ConfirmedWriteTools`, `tools.write` or `tools.executor` today, so the new R6 test passes as soon as it is written and its non-vacuity assertion holds.
- **`backend/tests/unit/test_r1_customer_scope.py`:** has 2 tests (`test_customer_id_is_write_once`, `test_no_customer_id_reaches_tools_or_nlu`). The method check it uses is the pattern to reuse: `inspect.getmembers(Cls, predicate=inspect.isfunction)`, dropping `_`-prefixed names, then `inspect.signature(...).parameters`.
- **`backend/pyproject.toml` mypy override:** `module = ["app.core.*", "app.domains.conversation.*"]`. The spec adds `"app.domains.policy.*"`. `identity` is not added (the spec and `06` §4 name only `policy/`).
- **`backend/.importlinter`:** has 4 contracts (layers api→domains→core, LLM SDK only in `app.core.llm`, conversation doesn't import `app.domains.*.repository`, core doesn't import a repository). None of them restricts `conversation` → `policy`/`identity`/`cards.schemas` imports, so they stay KEPT unchanged. `app.core.actions` must import no domain (layers contract). `policy/confirmation.py` and `identity/step_up.py` import only the stdlib, pydantic and `app.core.errors`, never `app.domains.conversation`. That avoids an import cycle, because `conversation/tools/__init__.py` imports the executor eagerly.
- **Registry names** (`04` §1): `cards.get_block_origin`, `cards.lock_card`, `cards.unlock_card`, `cards.block_card`, `cards.order_replacement`. The executor uses these as the `tool` string passed to the rule and to `consume_step`.
- **Doc anchors:** in `docs/solution-docs/04-contracts.md`, line 27 has the errors sentence, lines 36–40 the `get_block_origin`/`lock`/`unlock`/`block`/`order_replacement` rows (currently `…, token)`), line 44 the `disputes.create_claim` row, line 47 the `ActionResult` sentence, line 84 the confirmations route, line 96 the SSE events line, and lines 160–162 §7. In `docs/solution-docs/02-conversation-design.md`, lines 48–49 hold the graph-state paragraph.
- **Criterion 3 count:** the spec's "7 new tests + 2 existing" counts test **functions**. `test_raw_write_runs_only_after_its_step_is_consumed` is parametrized over 4 writes, so pytest reports **12 passed** for the four files: R1 3, R2 4+1+1+1, R3 1, R6 1.

## Components

| Component | Path | Depends on |
|---|---|---|
| Write-side errors (`PolicyDenied`, `ConfirmationRequired`, `StepUpRequired`, `Conflict`) | `backend/app/core/errors.py` | `ToolError` (exists) |
| `ActionResult`, `ReadbackValue` | `backend/app/core/actions.py` (new) | pydantic |
| `BlockReason`, `AddressRef`, `BlockOrigin` | `backend/app/domains/cards/schemas.py` | pydantic |
| Confirmation contract (`ToolArg`, `ToolArgs`, `args_hash`, `PlanStep`, `ConfirmationPlan`, `ConfirmationStore`) | `backend/app/domains/policy/{__init__,confirmation}.py` (new) | `app.core.errors` |
| Step-up gate (`StepUpGate`) | `backend/app/domains/identity/{__init__,step_up}.py` (new) | nothing |
| UI events (`ConfirmStepView`, `ConfirmPayload`, `OtpRequiredPayload`, `ConfirmEvent`, `OtpRequiredEvent`, `UIEvent`) | `backend/app/domains/conversation/ui.py` (new) | `state.Fact` |
| Turn plumbing (`actions` type, `ConfirmationDecision`, `TurnInput`/`TurnOutput`/`GraphState` channels, `run_turn` passing `confirmation=None`, `load_session` resetting `ui`) | `conversation/state.py`, `graph.py`, `nodes/load_session.py` | `ActionResult`, `ui.py` |
| Raw write facade (`BankWriteTools`, `BankWriteToolsFactory`) | `backend/app/domains/conversation/tools/write.py` (new) | `ActionResult`, cards schemas, `ToolContext` |
| R2 executor (`StepUpRule`, `ConfirmedWriteTools`) | `backend/app/domains/conversation/tools/executor.py` (new) | write facade, `ConfirmationStore`, `StepUpGate`, errors |
| Safety tests R1 (+1), R2, R3, R6 | `backend/tests/unit/test_r{1,2,3,6}_*.py` | the modules above |
| Doc updates | `04-contracts.md` §1/§3/§7, `02-conversation-design.md` §3 | the symbols as built (state file) |

## Build order

1. **T1: core value types (errors, `ActionResult`, card write schemas) plus the R3 test.** These are leaves that everything else imports.
2. **T2: `policy` and `identity` Protocols plus `args_hash` and its R2 binding test.** The executor needs `ConfirmationStore`, `PlanStep`, `ToolArgs` and `StepUpGate`. `args_hash` is pure, so its test can land with it. This step needs `ConfirmationRequired` from T1.
3. **T3: UI events and the turn plumbing (state, graph, load_session).** `state.actions` needs `ActionResult` (T1). `graph.py` needs `ui.py`. It has to come before T4, because T4's R1 test inspects `ConfirmationDecision`.
4. **T4: raw write facade, executor, re-exports, the three executor R2 tests and the R1 extension.** Needs T1 to T3. Its Verify runs the spec's criterion-1 import line and the criterion-4 grep, because every module exists by then.
5. **T5: R6 static scan.** It has no code dependency (it scans source for names). It comes after T4 so it's written against the real module names.
6. **T6: docs.** Written last, from the state file, so `04`/`02` record the names as built.

## Touch map

| File | New / modified | What changes |
|---|---|---|
| `backend/app/core/errors.py` | modified | +4 `ToolError` subclasses with `code` ClassVars; `PolicyDenied.reason_code`, `ConfirmationRequired.reason`; `__all__` |
| `backend/app/core/actions.py` | new | `ReadbackValue`, `ActionResult` (frozen, `extra="forbid"`, `verified` required) |
| `backend/app/domains/cards/schemas.py` | modified | +`BlockReason`, `AddressRef`, `BlockOrigin`; `__all__` |
| `backend/app/domains/policy/__init__.py` | new | package marker |
| `backend/app/domains/policy/confirmation.py` | new | `ToolArg`, `ToolArgs`, `args_hash`, `PlanStep`, `ConfirmationPlan`, `ConfirmationStore` |
| `backend/app/domains/identity/__init__.py` | new | package marker |
| `backend/app/domains/identity/step_up.py` | new | `StepUpGate` Protocol |
| `backend/pyproject.toml` | modified | mypy strict override adds `"app.domains.policy.*"` |
| `backend/app/domains/conversation/ui.py` | new | confirm / OTP payloads and events, `UIEvent` discriminated union |
| `backend/app/domains/conversation/state.py` | modified | `actions: NotRequired[Annotated[list[ActionResult], add]]`; drop `Any`; `Pending.awaiting_slot` docstring lists `"confirmation"`, `"otp"` |
| `backend/app/domains/conversation/graph.py` | modified | `ConfirmationDecision`; `TurnInput.confirmation`, `TurnOutput.ui`, `GraphState.confirmation`/`.ui`; `run_turn` input `{"user_text": text, "confirmation": None}` |
| `backend/app/domains/conversation/nodes/load_session.py` | modified | return also `"ui": []` |
| `backend/app/domains/conversation/tools/write.py` | new | `BankWriteTools` Protocol, `BankWriteToolsFactory` |
| `backend/app/domains/conversation/tools/executor.py` | new | `StepUpRule`, `ConfirmedWriteTools`; the idempotency-key note in the docstring |
| `backend/app/domains/conversation/tools/__init__.py` | modified | re-export `BankWriteTools`, `BankWriteToolsFactory`, `ConfirmedWriteTools`, `StepUpRule` |
| `backend/tests/unit/test_r3_action_result.py` | new | 1 test |
| `backend/tests/unit/test_r2_confirmed_writes.py` | new | 4 tests (T2 writes 1, T4 appends 3) |
| `backend/tests/unit/test_r1_customer_scope.py` | modified | +1 test |
| `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` | new | 1 test |
| `docs/solution-docs/04-contracts.md` | modified | §1, §3, §7 (D19) |
| `docs/solution-docs/02-conversation-design.md` | modified | §3 graph-state paragraph (D19) |

Not touched (criterion 5): `conversation/flows/**`, `nodes/route.py`, `tools/fakebank.py`, `.importlinter`.

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| `ActionResult.verified` gets a default, and "done" without read-back becomes possible (R3) | T1 writes `test_verified_is_required`; T1 acceptance forbids a default |
| An import cycle through `tools/__init__.py`: the executor pulls in `policy`/`identity`, and if either imported `conversation` the package would fail to import | T2 acceptance: `policy`/`identity` import only stdlib, pydantic and `app.core.errors`; T4 Verify runs the criterion-1 import line |
| `ui.py` imports `graph.py` and creates a cycle with the node modules | T3 acceptance: `ui.py` imports only `state.Fact` and pydantic |
| The executor consumes the token before step-up, so a failed OTP burns the plan (R2, ADR-027) | T4 acceptance fixes the order rule → gate → `consume_step` → raw → cancel; `test_step_up_checked_before_token_is_consumed` |
| The executor forgets to cancel on a raised or unverified step, so a half-applied plan stays open | T4 acceptance + `test_failed_or_unverified_step_cancels_the_plan` |
| A token leaks into the raw call or into `PlanStep.args` / `args_hash`, and the step never matches (R2) | T4: the executor builds `args` from non-token params only; the parametrized R2 test asserts exact `(tool, args)` and no token key |
| A checkpointed `confirmation` replays on the next typed turn (D17) | T3: `run_turn` passes `"confirmation": None` every turn; T3 Verify re-runs the two existing `run_turn` test files |
| `ui` is a last-write channel with no reset, so the previous turn's confirm card re-emits | T3: `load_session` returns `"ui": []` |
| LangGraph drops or rejects the new input key if `GraphState` doesn't declare it | T3 declares `confirmation` and `ui` on `GraphState` as `NotRequired`, as `user_text`/`reply` already are |
| The R6 scan is vacuous, or misses `from app.core import llm` / `from …tools import write` | T5: AST-based import detection for both forms, a non-vacuity assertion, and an in-test synthetic violating snippet that the checker must flag |
| `except BaseException` in the executor would cancel plans on task cancellation (`asyncio.CancelledError`) | T4 uses `except Exception` (the spec's "if the raw call raises"); cancellation/replay stays with D3-A3's open question |
| A new `policy` module escapes mypy strict | T2 adds `app.domains.policy.*` to the override and runs mypy on the new files |
| `Any` left unused in `state.py` after the retype (Ruff F401) | T3 Verify runs ruff on `state.py` |

## Tests

| Test | Task |
|---|---|
| `test_r3_action_result.py::test_verified_is_required` | T1 |
| `test_r2_confirmed_writes.py::test_args_hash_binds_tool_and_args` | T2 |
| `test_r2_confirmed_writes.py::test_raw_write_runs_only_after_its_step_is_consumed` (×4 writes) | T4 |
| `test_r2_confirmed_writes.py::test_step_up_checked_before_token_is_consumed` | T4 |
| `test_r2_confirmed_writes.py::test_failed_or_unverified_step_cancels_the_plan` | T4 |
| `test_r1_customer_scope.py::test_no_customer_id_on_write_side` | T4 |
| `test_r6_no_write_tools_in_llm_nodes.py::test_llm_nodes_cannot_reach_write_tools` | T5 |

Success criteria: 1 → T4 Verify; 2 → verifier (`make check`); 3 → verifier (expects 12 passed, see Facts); 4 → T4 Verify; 5 → verifier (`git diff develop --stat -- …`); 6 → T6; 7 → human (Dev B review, ADR-018).

## Tasks

- [ ] T1: Core write-side value types (errors, `ActionResult`, card write schemas) and the R3 test
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → `app/core/errors.py`, `app/core/actions.py`, `app/domains/cards/schemas.py` (and Decisions D9, D11, D14); `backend/app/core/errors.py`; `backend/app/domains/cards/schemas.py`
  - Acceptance:
    - `errors.py` adds `PolicyDenied` (`code = "policy_denied"`, constructor takes `reason_code: str` and stores it), `ConfirmationRequired` (`code = "confirmation_required"`, constructor takes `reason: Literal["unknown_or_expired", "step_mismatch", "wrong_owner"]` and stores it), `StepUpRequired` (`"step_up_required"`) and `Conflict` (`"conflict"`). All subclass `ToolError`, all are in `__all__`, and the docstring no longer says "D2 adds".
    - New `app/core/actions.py` has `ReadbackValue` and `ActionResult` exactly as in the spec: frozen, `extra="forbid"`, `verified: bool` with **no default**, `audit_event_id: UUID | None = None`, `tracking_id: str | None = None`. It imports no `app.domains` module.
    - `cards/schemas.py` adds `BlockReason`, `AddressRef` (a `str` alias; the docstring cites D12) and `BlockOrigin` (frozen) exactly as in the spec, all in `__all__`.
    - `tests/unit/test_r3_action_result.py::test_verified_is_required`: `ActionResult.model_validate` on a payload with `tool`, `status`, `readback` and no `verified` raises `ValidationError`. The same payload with `verified=True` validates, so the test fails only on the missing field.
  - Verify: `cd backend && uv run pytest tests/unit/test_r3_action_result.py -q && uv run ruff check app/core/errors.py app/core/actions.py app/domains/cards/schemas.py tests/unit/test_r3_action_result.py && uv run ruff format --check app/core/errors.py app/core/actions.py app/domains/cards/schemas.py tests/unit/test_r3_action_result.py && uv run mypy app/core/errors.py app/core/actions.py app/domains/cards/schemas.py`
  - Files: `backend/app/core/errors.py`, `backend/app/core/actions.py`, `backend/app/domains/cards/schemas.py`, `backend/tests/unit/test_r3_action_result.py`

- [ ] T2: `policy` confirmation contract, `identity` step-up gate, and the `args_hash` R2 test
  - Depends on: T1 (`ConfirmationRequired` in `app.core.errors`, referenced in the `consume_step` docstring as what it raises)
  - Read exactly these: spec §"Contracts" → `app/domains/policy/confirmation.py` and `app/domains/identity/step_up.py` (and Decisions D1, D2, D8); `backend/app/domains/conversation/tools/bank.py` (the Protocol style to mirror); `backend/pyproject.toml` `[[tool.mypy.overrides]]`
  - Acceptance:
    - New package `app/domains/policy/` (`__init__.py` is a one-line docstring) with `confirmation.py` defining `ToolArg`, `ToolArgs`, `args_hash`, `PlanStep` (frozen, `extra="forbid"`), `ConfirmationPlan` (frozen, `steps` requires at least 1 item) and the `ConfirmationStore` Protocol with `issue`, `consume_step` and `cancel`, exactly as in the spec. The docstrings state the store is bound to one customer and conversation at construction, that `consume_step` returns the consumed step's 0-based index and raises `ConfirmationRequired` with the D14 reasons, and that `cancel` is idempotent. They point at `04` §7 for storage semantics.
    - `args_hash(tool, args)` returns the hex SHA-256 of `json.dumps({"tool": tool, "args": dict(args)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8 (D2).
    - New package `app/domains/identity/` with `step_up.py` defining the `StepUpGate` Protocol with only `async def is_step_up_valid(self) -> bool`.
    - Neither package imports `app.domains.conversation` (only the stdlib, pydantic and `app.core.errors`). No parameter or field is named `customer_id`.
    - `backend/pyproject.toml`: the mypy override `module` list becomes `["app.core.*", "app.domains.conversation.*", "app.domains.policy.*"]`.
    - New `tests/unit/test_r2_confirmed_writes.py` with a module docstring (R2, the spec's test list; T4 appends the executor tests) and `test_args_hash_binds_tool_and_args`: the same hash for `{"card_id": "PRD-1", "reason": "suspected_fraud"}` and the key-reordered dict; a different hash when the tool changes (`cards.lock_card` vs `cards.block_card`) and when any single arg value changes.
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py -q && uv run ruff check app/domains/policy app/domains/identity tests/unit/test_r2_confirmed_writes.py && uv run ruff format --check app/domains/policy app/domains/identity tests/unit/test_r2_confirmed_writes.py && uv run mypy app/domains/policy app/domains/identity && uv run lint-imports`
  - Files: `backend/app/domains/policy/__init__.py`, `backend/app/domains/policy/confirmation.py`, `backend/app/domains/identity/__init__.py`, `backend/app/domains/identity/step_up.py`, `backend/pyproject.toml`, `backend/tests/unit/test_r2_confirmed_writes.py`

- [ ] T3: UI events and turn plumbing (`actions` type, `confirmation` input, `ui` output, per-turn resets)
  - Depends on: T1 (`app.core.actions.ActionResult`)
  - Read exactly these: spec §"Contracts" → `app/domains/conversation/ui.py`, `…/state.py`, `…/graph.py` (and Decisions D10, D15–D17); `backend/app/domains/conversation/graph.py`; `backend/app/domains/conversation/nodes/load_session.py`
  - Acceptance:
    - New `conversation/ui.py` with `ConfirmStepView`, `ConfirmPayload`, `OtpRequiredPayload` (all frozen), `ConfirmEvent`, `OtpRequiredEvent` and `UIEvent = Annotated[ConfirmEvent | OtpRequiredEvent, Field(discriminator="kind")]`, exactly as in the spec. `ConfirmStepView.facts: list[Fact]` imports `Fact` from `app.domains.conversation.state`. `ui.py` does not import `graph.py`. The docstring cites `04` §3/§7 and notes that other kinds arrive with their cards.
    - `state.py`: `actions: NotRequired[Annotated[list[ActionResult], add]]`, and the now-unused `Any` import is removed. The `Pending` docstring documents `awaiting_slot` values `"confirmation"` and `"otp"` (the type stays `str | None`). No other `TurnState` field changes.
    - `graph.py`: `ConfirmationDecision` (frozen, `extra="forbid"`, `token_id: str`, `decision: Literal["confirm", "cancel"]`) is added to `__all__`. `TurnInput` gains `confirmation: NotRequired[ConfirmationDecision | None]`. `TurnOutput` gains `ui: NotRequired[list[UIEvent]]`. `GraphState` gains `confirmation: NotRequired[ConfirmationDecision | None]` and `ui: NotRequired[list[UIEvent]]`. `run_turn` streams `{"user_text": text, "confirmation": None}`. No node, edge or routing change.
    - `load_session` returns `"ui": []` in addition to its current keys. Its docstring says `ui` is reset each turn (D16).
    - The existing `run_turn` tests still pass unchanged. `flows/`, `nodes/route.py` and `tools/fakebank.py` are untouched.
  - Verify: `cd backend && uv run pytest tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py && uv run ruff format --check app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py && uv run mypy app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py`
  - Files: `backend/app/domains/conversation/ui.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/load_session.py`

- [ ] T4: Raw write facade, the `ConfirmedWriteTools` executor, and its R2 and R1 tests
  - Depends on: T1 (`ActionResult`, the 4 errors, `BlockOrigin`/`BlockReason`/`AddressRef`), T2 (`ConfirmationStore`, `PlanStep`, `ConfirmationPlan`, `ToolArgs`, `StepUpGate`, and `test_r2_confirmed_writes.py` with its `args_hash` test), T3 (`ConfirmationDecision` in `graph.py`, checked by the R1 test). Use the real symbol names recorded in the state file.
  - Read exactly these: spec §"Contracts" → `app/domains/conversation/tools/write.py` and `…/executor.py` (and Decisions D3–D5, D7, D13, plus §"Test list"); `backend/app/domains/conversation/tools/bank.py` (the analogue to mirror); `backend/tests/unit/test_r1_customer_scope.py`
  - Acceptance:
    - New `tools/write.py`: the `BankWriteTools` Protocol (`get_block_origin`, `lock_card`, `unlock_card`, `block_card`, `order_replacement`, with signatures exactly as in the spec and no `ctx`, `customer_id` or token), each body a comment with the registry name and "May raise" (NotFound/AccessDenied/ToolUnavailable; the 4 writes also Conflict). Plus `BankWriteToolsFactory = Callable[[ToolContext], BankWriteTools]` with a docstring. The module docstring states the R3 read-back duty (`verified=True` only after re-reading).
    - New `tools/executor.py`: `StepUpRule = Callable[[str, ToolArgs], bool]` and `ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up)`. `issue_plan`, `cancel_plan` and `is_step_up_valid` delegate to the store and the gate. `get_block_origin` passes through with no rule, gate or store call. Each of the 4 writes takes its spec signature (`…, token_id: str`), builds `args` from its non-token params only (`{"card_id"}`, `{"card_id"}`, `{"card_id", "reason"}`, `{"card_id", "address_ref"}`) with the registry tool name, and runs in this order: (1) if `requires_step_up(tool, args)` and not `await step_up.is_step_up_valid()`, raise `StepUpRequired` (no consume); (2) `await confirmations.consume_step(token_id, tool, args)`, letting `ConfirmationRequired` propagate with no cancel; (3) the raw call; (4) on `except Exception`, `await confirmations.cancel(token_id)` then bare `raise`; if `result.verified` is false, `cancel` and return the result unchanged. No default rule. The module docstring documents the `<token_id>:<step_index>` idempotency key as D13, not implemented, and cites `04` §7 / ADR-027.
    - `tools/__init__.py` re-exports `BankWriteTools`, `BankWriteToolsFactory`, `ConfirmedWriteTools` and `StepUpRule` alongside the existing names in `__all__`.
    - `test_r2_confirmed_writes.py` gains, using in-file stubs (a store recording `consume_step`/`cancel` calls with optional raise, a gate with a fixed bool, raw tools recording calls and returning a configurable `ActionResult` or raising) and `asyncio.run`:
      - `test_raw_write_runs_only_after_its_step_is_consumed`, parametrized over the 4 writes: the store receives exactly `(token_id, tool, args)` with no token in `args`, and raw is called with the same args. With the store raising `ConfirmationRequired("step_mismatch")`, raw is never called and the error propagates.
      - `test_step_up_checked_before_token_is_consumed`: rule true and gate false gives `StepUpRequired`, with `consume_step` and raw both not called. Rule true and gate true lets the write proceed.
      - `test_failed_or_unverified_step_cancels_the_plan`: raw raising `ToolUnavailable` calls `cancel(token_id)` and re-raises. Raw returning `verified=False` calls `cancel` and returns that same result.
    - `test_r1_customer_scope.py` gains `test_no_customer_id_on_write_side`: for `BankWriteTools`, `ConfirmedWriteTools`, `ConfirmationStore` and `StepUpGate`, no public method has a `customer_id` or `ctx` parameter (the existing `inspect` pattern, which also asserts that the expected method names are present). `customer_id` is not in `PlanStep.model_fields` or `ConfirmationDecision.model_fields`.
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation/tools tests/unit/test_r2_confirmed_writes.py tests/unit/test_r1_customer_scope.py && uv run ruff format --check app/domains/conversation/tools tests/unit/test_r2_confirmed_writes.py tests/unit/test_r1_customer_scope.py && uv run mypy app/domains/conversation/tools && uv run lint-imports && uv run python -c "from app.core.actions import ActionResult; from app.core.errors import PolicyDenied, ConfirmationRequired, StepUpRequired, Conflict; from app.domains.cards.schemas import BlockOrigin, BlockReason, AddressRef; from app.domains.policy.confirmation import ConfirmationStore, ConfirmationPlan, PlanStep, args_hash; from app.domains.identity.step_up import StepUpGate; from app.domains.conversation.tools import BankWriteTools, BankWriteToolsFactory, ConfirmedWriteTools; from app.domains.conversation.ui import UIEvent, ConfirmPayload; from app.domains.conversation.graph import ConfirmationDecision" && cd .. && grep -rn "customer_id" backend/app/domains/conversation/tools/write.py backend/app/domains/conversation/tools/executor.py backend/app/domains/policy backend/app/domains/identity`. The final grep may print docstring lines only, with no parameter or field.
  - Files: `backend/app/domains/conversation/tools/write.py`, `backend/app/domains/conversation/tools/executor.py`, `backend/app/domains/conversation/tools/__init__.py`, `backend/tests/unit/test_r2_confirmed_writes.py`, `backend/tests/unit/test_r1_customer_scope.py`

- [ ] T5: R6 static test — LLM nodes cannot reach write tools
  - Depends on: nothing in code (it scans source text). Use the module names in the state file: `app.domains.conversation.tools.write` and `app.domains.conversation.tools.executor`.
  - Read exactly these: spec Decision D6 and §"Test list" → `test_r6_…`; `backend/app/domains/conversation/nodes/understand.py` (lines 1–20, the LLM import form); `backend/tests/unit/test_r1_customer_scope.py` (test file style)
  - Acceptance:
    - New `tests/unit/test_r6_no_write_tools_in_llm_nodes.py::test_llm_nodes_cannot_reach_write_tools`. It walks every `*.py` under `backend/app/domains/conversation/nodes/` and `…/flows/` (the path resolves from `__file__`) and uses `ast` to decide whether a module imports the LLM package (`import app.core.llm…`, `from app.core.llm… import …`, or `from app.core import llm`).
    - For each such module, it asserts that the source contains none of `bank_write_tools`, `ConfirmedWriteTools` or `BankWriteTools`, and imports neither `app.domains.conversation.tools.write`/`.executor` nor `write`/`executor` from `app.domains.conversation.tools`. The failure message names the file and the offending reference.
    - It asserts that at least one scanned module imports the LLM package (today: `nodes/understand.py`, `nodes/compose.py`).
    - The checker is a small helper over source text, and the same test asserts that it flags a synthetic snippet (`"from app.core.llm import LLMClient\nx = config['configurable']['bank_write_tools']"`), so the scan provably fails when the rule is broken.
    - No app code changes.
  - Verify: `cd backend && uv run pytest tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run ruff format --check tests/unit/test_r6_no_write_tools_in_llm_nodes.py`
  - Files: `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`

- [ ] T6: Update `04` §1/§3/§7 and `02` §3 to the write-side contracts (D19)
  - Depends on: T1 to T4 (the symbol names as built, recorded in the state file)
  - Read exactly these: spec §"Contracts" (including "Pause/resume protocol for B5") and Decisions D1, D3, D9, D11–D17; `docs/solution-docs/04-contracts.md` lines 1–97 and 155–162; `docs/solution-docs/02-conversation-design.md` lines 33–51
  - Acceptance:
    - `04` §1:
      - The write rows (lines 37–40) read `…, token_id)`.
      - Line 27 lists the four new errors with `PolicyDenied(reason_code)` and `ConfirmationRequired(reason: unknown_or_expired | step_mismatch | wrong_owner)`, and drops "D2 adds the rest".
      - Line 47 becomes the concrete `ActionResult` (`tool`, `status`, `verified` required, `readback`, `audit_event_id`, `tracking_id`). The `disputes.create_claim` row keeps `{case_id, priority_flags}` with a note that they land with the disputes card (D9).
      - `BlockOrigin{kind, reason}` gets its value sets, and `BlockReason` and `address_ref` (`"on_file"` or a vault token `⟨ADDR_n⟩`, D12) are stated.
      - A short paragraph explains the raw `BankWriteTools` (session-bound, never sees a token) vs the `ConfirmedWriteTools` executor (the one R2 point, the order step-up → consume → raw → cancel on failure/unverified; the graph gets it only via `configurable["bank_write_tools"]`; the step-up rule comes from `tools.yaml`, D3-A1).
      - The idempotency-key note says `<token_id>:<step_index>`, storage in D3-A3.
    - `04` §3: the SSE line (or a note under it) gives the `ui.confirm` payload `{token_id, steps: [{tool, summary_key, facts}]}` and `ui.otp_required` `{tool}`. The confirmations route row says the button maps to `TurnInput.confirmation{token_id, decision: confirm | cancel}`, and a stale `token_id` executes nothing.
    - `04` §7 names the interface `issue(steps) -> {token_id, steps, expires_at}`, `consume_step(token_id, tool, args) -> step_index` (0-based), and `cancel(token_id)` (idempotent), plus the three `ConfirmationRequired` reasons and `args_hash` (SHA-256 of canonical JSON of `{tool, args}`). The existing Redis semantics are unchanged.
    - `02` §3: `pending.awaiting_slot` lists `"confirmation"` and `"otp"`, `actions[]` becomes `actions: list[ActionResult]`, and the channels sentence adds `confirmation` (input, the button, `None` on typed turns) and `ui` (output, `list[UIEvent]`, reset by `load_session`).
    - Docs point at the spec and ADR-027 rather than restating rationale. No other section changes.
  - Verify: `grep -n "token_id" docs/solution-docs/04-contracts.md | head -20 && grep -n "consume_step\|step_mismatch\|wrong_owner\|unknown_or_expired\|otp_required\|BlockReason\|address_ref\|ConfirmedWriteTools\|<token_id>:<step_index>" docs/solution-docs/04-contracts.md && grep -n "awaiting_slot\|ActionResult\|confirmation\`\|\`ui\`" docs/solution-docs/02-conversation-design.md && git diff --stat -- docs/solution-docs`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`
