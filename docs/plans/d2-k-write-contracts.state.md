# State: D2-K — write-side contracts
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D2-K (D2 kickoff, contracts for G6a/G8, owner A) · spec `docs/specs/d2-k-write-contracts.md` · plan `docs/plans/d2-k-write-contracts.md`
Branch `feat/d2-k-write-contracts`, based on `develop` (`9ab3f7a`).

## Conventions established for this card
- Commands run as `cd backend && uv run …`. Ignore the uv `VIRTUAL_ENV` mismatch warning. There's no pytest-asyncio: drive coroutines with `asyncio.run(...)`.
- Baseline green at `9ab3f7a`: ruff clean, mypy clean (51 files), lint-imports 4 KEPT, `pytest tests/unit -q` shows 14 passed. Any red after a task comes from that task.
- New packages: `app/domains/policy/`, `app/domains/identity/`. New files: `core/actions.py`, `conversation/ui.py`, `conversation/tools/write.py`, `conversation/tools/executor.py`.
- Pattern to mirror: `conversation/tools/bank.py` (Protocol method bodies = registry-name comment + "May raise" + `...`). Every package `__init__` re-exports through `__all__` (mypy `no_implicit_reexport`).
- `core/actions.py` imports no domain. `policy/confirmation.py` and `identity/step_up.py` import only the stdlib, pydantic and `app.core.errors`, never `app.domains.conversation` (cycle risk).
- `ui.py` must not import `graph.py`. `run_turn` is the only `astream` call on the turn graph.
- When `state.actions` changes type, drop the now-unused `Any` import (F401).
- Registry tool names: `cards.get_block_origin|lock_card|unlock_card|block_card|order_replacement`.
- The mypy strict override gains `app.domains.policy.*` (not `identity`).
- Expected at the end: the 4 R-test files report **12 passed**.

## Human decisions taken mid-card
- (spec) Q1–Q6 all took option (a): plan tokens, executor in this card, pending-state pause, separate write facade + R6 test, address_ref on_file|vault token, derived idempotency key.
- (plan) Executor cancels the plan only on `except Exception`; CancelledError is left to D3-A3 (T4).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | ab09ab9 | errors + ActionResult + BlockOrigin; R3 test green |
| T2 | done | a30a269 | ConfirmationStore + StepUpGate + args_hash; R2 hash test green |
| T3 | done | ac8d01b | ui.py events + ActionResult actions + confirmation/ui turn plumbing; graph tests green |
| T4 | done | a1b583a | BankWriteTools + ConfirmedWriteTools executor; R2+R1 tests 10 passed |
| T5 | done | a242cb6 | R6 AST scan of nodes/flows + synthetic-violation check; 1 passed |
| T6 | done | a5d0102 | 04 §1/§3/§7 + 02 §3 updated to write-side contracts |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — Core write-side value types (errors, `ActionResult`, card write schemas) and the R3 test
Changed: `backend/app/core/errors.py` (`PolicyDenied`, `ConfirmationRequired`, `StepUpRequired`, `Conflict`, all in `__all__`, docstring updated).
Created: `backend/app/core/actions.py` (`ReadbackValue`, `ActionResult`; imports no `app.domains`).
Changed: `backend/app/domains/cards/schemas.py` (`BlockReason`, `AddressRef`, `BlockOrigin`, all in `__all__`).
Created: `backend/tests/unit/test_r3_action_result.py`.
Facts the next tasks need: none new beyond the spec's contracts; `errors.py` extra classes store their attribute in `__init__` (`self.reason_code`, `self.reason`) and pass it to `super().__init__()`.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r3_action_result.py -q` → 1 passed; ruff check → All checks passed; ruff format --check → 4 files already formatted; mypy → Success: no issues found in 3 source files.

### T2 — `policy` confirmation contract, `identity` step-up gate, `args_hash` R2 test
Created: `backend/app/domains/policy/__init__.py` (one-line docstring), `backend/app/domains/policy/confirmation.py` (`ToolArg`, `ToolArgs`, `args_hash`, `PlanStep`, `ConfirmationPlan`, `ConfirmationStore`).
Created: `backend/app/domains/identity/__init__.py` (one-line docstring), `backend/app/domains/identity/step_up.py` (`StepUpGate`).
Created: `backend/tests/unit/test_r2_confirmed_writes.py` (module docstring + `test_args_hash_binds_tool_and_args`; T4 appends the executor tests).
Changed: `backend/pyproject.toml` mypy override `module` list gains `"app.domains.policy.*"`.
Facts the next tasks need: neither new package imports `app.core.errors` (not needed at runtime; `ConfirmationRequired`'s reasons are only cited in `consume_step`'s docstring). `ConfirmationStore`/`StepUpGate` method bodies use `...` with inline comments only where there's something to say (no "Registry name" comment on `policy`/`identity` methods — that's a `tools/bank.py`-specific convention, not reused here).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py -q` → 1 passed; ruff check → All checks passed; ruff format --check → 5 files already formatted; mypy → Success: no issues found in 4 source files (benign mypy note: "unused section(s)" for the `app.core.*`/`app.domains.conversation.*` overrides, since this run's file list doesn't touch those modules); `lint-imports` → 4 kept, 0 broken.

### T3 — UI events and turn plumbing
Created: `backend/app/domains/conversation/ui.py` (`ConfirmStepView`, `ConfirmPayload`, `OtpRequiredPayload`, `ConfirmEvent`, `OtpRequiredEvent`, `UIEvent`; imports `Fact` from `state.py`, not `graph.py`).
Changed: `backend/app/domains/conversation/state.py` (`actions: NotRequired[Annotated[list[ActionResult], add]]`, imports `ActionResult` from `app.core.actions`, dropped unused `Any`; `Pending` docstring documents `awaiting_slot` values `"confirmation"`/`"otp"`).
Changed: `backend/app/domains/conversation/graph.py` (`ConfirmationDecision` added to `__all__`; `TurnInput.confirmation`, `TurnOutput.ui`, `GraphState.confirmation`/`ui` added; `run_turn` streams `{"user_text": text, "confirmation": None}`; no node/edge/routing change).
Changed: `backend/app/domains/conversation/nodes/load_session.py` (returns `"ui": []`, docstring notes D16 reset).
Facts the next tasks need: none beyond the spec; `ui.py` exports via `__all__` including the `UIEvent` type alias.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py -q` → 4 passed; ruff check → All checks passed; ruff format --check → 4 files already formatted; mypy → Success: no issues found in 4 source files (same benign "unused section(s)" note for `app.domains.policy.*`, since this run's file list doesn't touch that module). `git diff --stat` on `flows/`, `nodes/route.py`, `tools/fakebank.py` is empty.

### T4 — Raw write facade, `ConfirmedWriteTools` executor, R2 and R1 tests
Created: `backend/app/domains/conversation/tools/write.py` (`BankWriteTools`, `BankWriteToolsFactory`); `backend/app/domains/conversation/tools/executor.py` (`StepUpRule`, `ConfirmedWriteTools` with a private `_run` helper shared by the 4 writes).
Changed: `backend/app/domains/conversation/tools/__init__.py` (re-exports `BankWriteTools`, `BankWriteToolsFactory`, `ConfirmedWriteTools`, `StepUpRule`); `backend/tests/unit/test_r2_confirmed_writes.py` (+3 tests, one parametrized over the 4 writes, in-file `_StubStore`/`_StubGate`/`_StubRawWrites`); `backend/tests/unit/test_r1_customer_scope.py` (+`test_no_customer_id_on_write_side`).
Facts the next tasks need: `ConfirmedWriteTools._run(tool, args, token_id, call)` centralizes D3's order (step-up → consume_step → raw call → cancel-on-exception/unverified); `get_block_origin` bypasses `_run` entirely (no rule/gate/store call). No default `StepUpRule` shipped, per D7/R8.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmed_writes.py tests/unit/test_r1_customer_scope.py -q` → 10 passed; ruff check → All checks passed; ruff format --check → 8 files already formatted; mypy → Success: no issues found in 6 source files; `lint-imports` → 4 kept, 0 broken; the success-criteria import one-liner exits 0 silently; final grep shows only docstring lines (no parameter/field named `customer_id`).

### T5 — R6 static test: LLM nodes cannot reach write tools
Created: `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` (`_imports_llm`, `_write_tool_references` helpers over `ast`/source text; `test_llm_nodes_cannot_reach_write_tools`).
Facts the next tasks need: the scan walks `conversation/nodes/*.py` and `conversation/flows/*.py` (path from `Path(__file__).resolve().parents[2]`); today only `nodes/understand.py` and `nodes/compose.py` import `app.core.llm`, and neither references a write tool.
Deviations: none. No app code changed.
Verify: `cd backend && uv run pytest tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q` → 1 passed; `uv run ruff check tests/unit/test_r6_no_write_tools_in_llm_nodes.py` → All checks passed; `uv run ruff format --check tests/unit/test_r6_no_write_tools_in_llm_nodes.py` → 1 file already formatted.

### T6 — Docs: `04` §1/§3/§7 and `02` §3 to the write-side contracts (D19)
Changed: `docs/solution-docs/04-contracts.md` (§1: write rows take `token_id`; error line lists the four new errors incl. reason literals, drops "D2 adds the rest"; `BlockOrigin`/`BlockReason`/`address_ref` value sets; concrete `ActionResult`; `BankWriteTools` vs `ConfirmedWriteTools` paragraph; idempotency-key note; §3: confirmations route row + `ui.confirm`/`ui.otp_required` payload note; §7: `issue`/`consume_step`/`cancel` signatures, `ConfirmationRequired` reasons, `args_hash`).
Changed: `docs/solution-docs/02-conversation-design.md` (§3: `awaiting_slot` gains `"confirmation"`/`"otp"`, `actions: list[ActionResult]`, channels sentence adds `confirmation` and `ui`).
Facts the next tasks need: none (doc-only task).
Deviations: none.
Verify: `grep -n "token_id" docs/solution-docs/04-contracts.md | head -20 && grep -n "consume_step\|step_mismatch\|wrong_owner\|unknown_or_expired\|otp_required\|BlockReason\|address_ref\|ConfirmedWriteTools\|<token_id>:<step_index>" docs/solution-docs/04-contracts.md && grep -n "awaiting_slot\|ActionResult\|confirmation\`\|\`ui\`" docs/solution-docs/02-conversation-design.md && git diff --stat -- docs/solution-docs` → all four greps produced the expected matches (see command output); `git diff --stat` shows only `02-conversation-design.md` (2 lines) and `04-contracts.md` (32 lines) changed.
