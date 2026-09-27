# Spec: D2-K — Write-side contracts PR

Card: `07-execution-plan.md` D2 kickoff ("A pushes the write-side contracts PR"). Owner: Dev A writes, Dev B reviews (ADR-018: it touches tools and confirmation, so it is safety-critical). Branch `feat/d2-k-write-contracts` → `develop` (`06` §5).

## Objective

Land on `develop` the typed contracts every D2/D3 write-path task builds on:
- the raw write tools `BankWriteTools` (`lock_card`, `unlock_card`, `block_card`, `get_block_origin`, `order_replacement`)
- `ActionResult{verified, readback}` and `BlockOrigin`
- the plan-token confirmation interface (ADR-027)
- the step-up gate `is_step_up_valid()`
- the one R2 enforcement point, the `ConfirmedWriteTools` executor
- how the graph pauses for a confirmation: the `ui.confirm` event, the pending state and the button input

The consumers are D2-B4 (FakeBank raw writes, fake confirmation store and fake OTP, all implementing these Protocols), D2-B5 (block/lock/unlock/replacement flows through the executor), D2-A4 (the SSE `ui` event and the confirmations route shape) and D3-A (G6a: Redis store, Postgres raw writes, OTP route, `tools.yaml`).

No flow behavior ships. This card defines shapes, one small executor and the four safety tests that make them safe. It serves the D2 end-of-day test step 5 (`make chat-sandbox`: lock → confirm → read-back, unlock → OTP) only through B4/B5. Its own proof is `make check` green, plus the updated `04`/`02`.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | Every confirmation token is a plan. The interface is `issue(steps) -> ConfirmationPlan{token_id, steps, expires_at}`, `consume_step(token_id, tool, args) -> int` (checks the step at the cursor, advances it, returns the consumed step's 0-based index) and `cancel(token_id)`. A single action is a plan of one. This replaces the card's literal `issue(tool, args)` / `consume(token)` | Human Q1(a). ADR-027, `04` §7, R2 |
| D2 | `ConfirmationStore` is a `typing.Protocol` in the `policy` domain, bound to one customer + conversation at construction. `args_hash(tool, args)` is one shared function: SHA-256 over canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) of `{"tool": tool, "args": args}` | Assumption 7. `01` §4 (`policy` issues and consumes tokens), `04` §7 |
| D3 | R2 is enforced in one place, `ConfirmedWriteTools` in `conversation/tools/`. Flows call it with `04`'s signatures (`lock_card(card_id, token_id)`, …). For each write it runs, in order: (1) the step-up check, which raises `StepUpRequired` without consuming the token; (2) `consume_step(token_id, tool, args)`; (3) the raw call; (4) `cancel(token_id)` if the raw call raises or returns `verified=False`. The error is re-raised, or the unverified result returned. Raw `BankWriteTools` never sees a token. This card ships the executor and its R2 tests (stub store, stub gate, stub raw tools) | Human Q2(a). R2, R3, ADR-027 ("deleted … on the first failed or unverified step") |
| D4 | The raw write facade `BankWriteTools` is a session-bound Protocol (bound by `BankWriteToolsFactory = Callable[[ToolContext], BankWriteTools]`, as K3 D1). No method takes `ctx`, `customer_id` or a token. `get_block_origin` lives here (read-only, no token), and the executor passes it through unchanged | Assumptions 1–2, R1 |
| D5 | The graph gets writes only through `config["configurable"]["bank_write_tools"]`, which holds a `ConfirmedWriteTools`, never a raw `BankWriteTools`. The executor also exposes `issue_plan`, `cancel_plan` and `is_step_up_valid` (delegating to the store and the gate). That keeps every write-related capability behind the one key the R6 test guards | Human Q4(a), Q2(a). ADR-027 ("step-up happens before the plan is shown", so flows need the gate) |
| D6 | R6 is enforced by one static test. No module under `app/domains/conversation/nodes/` or `…/flows/` that imports `app.core.llm` may reference `bank_write_tools`, `ConfirmedWriteTools`, `BankWriteTools` or `conversation.tools.write` / `.executor` | Human Q4(a). R6, `06` §1 ("graph construction test") |
| D7 | Whether a step needs step-up is an injected rule, `StepUpRule = Callable[[str, Mapping[str, ToolArg]], bool]`, passed to the executor's constructor. This card ships no default rule, because the source of truth is `policies/tools.yaml` (D3-A1). The flags to encode are those of `04` §1: `unlock_card` always; `order_replacement` when `address_ref != "on_file"` | Human Q5(a). R8 (policy in YAML, not code), `07` D3-A1 |
| D8 | `StepUpGate` is a session-bound Protocol in the `identity` domain with one method, `async is_step_up_valid() -> bool`. OTP verification is outside the Protocol: `POST /auth/otp/verify` in D3-A4, and a method on the B4 fake. The validity window is not part of the contract | Assumption 6. ADR-008, ADR-025 (step-up checked per tool against `session.step_up_at`), decision-log deferred item |
| D9 | `ActionResult` goes in `app/core/actions.py` (frozen, `extra="forbid"`): `tool`, `status: Literal["applied"]`, `verified: bool` with **no default**, `readback: dict[str, ReadbackValue]`, `audit_event_id: UUID \| None` (None until D3-A5), `tracking_id: str \| None`. `case_id` and `priority_flags` wait for the disputes card. It lives in `core` because `cards` and `disputes` both return it, and domains can't import `conversation` | Assumption 3. `04` §1, R3, ADR-027 (the handoff lists applied steps, hence `tool`), `06` §2 layering (as K3 D7 did for errors) |
| D10 | `TurnState.actions` becomes `Annotated[list[ActionResult], add]` | Assumption 3. K3 D5 ("until D2 defines `ActionResult`") |
| D11 | `BlockOrigin{kind, reason}` with `kind: customer_lock \| customer_block \| bank_side \| none` and `reason: past_due \| fraud \| customer_status \| bank_status \| None` (non-None only for `bank_side`). `BlockReason = Literal["lost_or_stolen", "suspected_fraud"]` | Assumption 4. `02` §4.6–4.8 (the reason picks Cobranza vs Fraudes) |
| D12 | `address_ref: str` is either `"on_file"` (the address in `bank.customers`) or a PII-vault token for an address the customer typed (`⟨ADDR_n⟩`, the `01` §5 token style), resolved server-side by the raw tool. Until the vault exists, the FakeBank treats any value other than `"on_file"` as "changed" | Human Q5(a). R5 (the raw address never enters the LLM, state, checkpoint or `args_hash`) |
| D13 | Idempotency has no parameter. The key for a confirmed step is `<token_id>:<step_index>`, with `step_index` as returned by `consume_step`. This card only documents it. Storage and the "replay returns the stored `ActionResult`" lookup are D3-A3 | Human Q6(a). `01` §7, `06` §4, `07` D3-A3 |
| D14 | Errors in `core/errors.py`: `PolicyDenied(reason_code)`, `ConfirmationRequired(reason)`, `StepUpRequired`, `Conflict`. `ConfirmationRequired.reason` is one of `unknown_or_expired` (absent key: never issued, expired or already fully used), `step_mismatch` (the tool or args hash differs from the step at the cursor) or `wrong_owner` (another customer or conversation) | Assumption 5. K3 D10, `04` §1 |
| D15 | Pause for confirmation (pending state, as D1 `card_select`). The flow issues the plan, sets `confirmation_token_id = plan.token_id` and `pending = {flow, node: "confirm", awaiting_slot: "confirmation"}`, appends a `ui.confirm` event, and the turn ends. If a step needs step-up and `is_step_up_valid()` is false, it first sets `pending = {flow, node: "step_up", awaiting_slot: "otp"}`, emits `ui.otp_required` and issues no plan | Human Q3(a). `02` §3 ("resume pending flow"), ADR-027 (step-up before the plan is shown), `04` §3 `ui` kinds |
| D16 | UI output is a graph-local `ui: list[UIEvent]` channel next to `reply`, not part of the checkpointed `TurnState` contract. `load_session` resets it to `[]` each turn, and emitting nodes read, extend and write it back (last-write) | Human Q3(a). `02` §3 (`user_text`/`reply` are graph-local channels) |
| D17 | Button resume: `TurnInput` gains `confirmation: ConfirmationDecision{token_id, decision: confirm \| cancel} \| None`. When it is set, the turn skips `understand` (no LLM call). A `token_id` that differs from the state's `confirmation_token_id` is stale: nothing executes. Every caller passes `confirmation` explicitly (`None` on a typed turn), so a checkpointed value never leaks into the next turn. `run_turn` does this in this card; the routing that skips `understand` is B5 | Human Q3(a). `04` §3 ("button = typing sí") |
| D18 | Scope: Protocols, models, errors, `args_hash`, the executor, the two one-line graph resets (D16, D17), four test files and the doc updates. No FakeBank write, fake store or fake gate (B4), no flow or routing (B5), no SSE (A4), no Redis, Postgres or OTP route (D3-A2 to A4), no `ToolSpec`, registry or `tools.yaml` (D3-A1) | Assumption 1. `07` D2/D3 rows |
| D19 | This PR updates `04` §1, §3 and §7 and `02` §3 to match the Contracts below | Human (pass-2 instruction). `06` §7.4 |
| D20 | Amends D3 step (4): the executor cancels the plan only when the raw call raises an `Exception` subclass (`except Exception`) or returns `verified=False`. An `asyncio.CancelledError` (a cancelled turn, a `BaseException`) propagates **without** cancelling the plan. That case is deferred to D3-A3, together with replay and idempotency | Human, mid-card decision (plan T4) |

## Contracts

Everything not listed stays as in `04` and in the K3 contracts.

**`app/core/errors.py`**: add these classes, all subclasses of `ToolError`:

| Class | `code` | Extra attribute | Raised when |
|---|---|---|---|
| `PolicyDenied` | `"policy_denied"` | `reason_code: str` | The policy forbids it (allowlist D3-A1, ADR-021 inactive customer) |
| `ConfirmationRequired` | `"confirmation_required"` | `reason: Literal["unknown_or_expired", "step_mismatch", "wrong_owner"]` | `consume_step` rejects the call (D14) |
| `StepUpRequired` | `"step_up_required"` | — | The executor's rule says step-up and the gate says no |
| `Conflict` | `"conflict"` | — | The state already matches (already locked, blocked or closed) |

**`app/core/actions.py`** (new)
```python
ReadbackValue = str | int | bool | Decimal | date | datetime | None

class ActionResult(BaseModel):            # frozen, extra="forbid"
    tool: str                             # registry name, e.g. "cards.lock_card"
    status: Literal["applied"]
    verified: bool                        # REQUIRED, no default (R3)
    readback: dict[str, ReadbackValue]    # the re-read record fields, e.g. {"locked": True}
    audit_event_id: UUID | None = None    # set once audit lands (D3-A5)
    tracking_id: str | None = None        # order_replacement only
```

**`app/domains/cards/schemas.py`**: add
```python
BlockReason = Literal["lost_or_stolen", "suspected_fraud"]
AddressRef = str                          # "on_file" | a PII-vault token "⟨ADDR_n⟩" (D12)

class BlockOrigin(BaseModel):             # frozen
    kind: Literal["customer_lock", "customer_block", "bank_side", "none"]
    reason: Literal["past_due", "fraud", "customer_status", "bank_status"] | None  # bank_side only
```

**`app/domains/policy/confirmation.py`** (new package `app/domains/policy/`)
```python
ToolArg = str | int | bool | None
ToolArgs = Mapping[str, ToolArg]

def args_hash(tool: str, args: ToolArgs) -> str: ...   # D2; hex sha256

class PlanStep(BaseModel):                 # frozen, extra="forbid"
    tool: str                              # registry name
    args: dict[str, ToolArg]               # exactly the raw call's keyword args (never a token)

class ConfirmationPlan(BaseModel):         # frozen
    token_id: str                          # opaque, unguessable
    steps: list[PlanStep]                  # ≥ 1
    expires_at: datetime                   # aware UTC; issue time + 5 min (04 §7)

class ConfirmationStore(Protocol):         # bound to one customer + conversation at construction
    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan: ...
    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int: ...  # raises ConfirmationRequired
    async def cancel(self, token_id: str) -> None: ...                                  # idempotent; unknown id is a no-op
```
The storage semantics (Redis `conf:<id>`, atomic cursor, deleted after the last step) stay as in `04` §7. They are the implementer's job: B4 fake, D3-A2 Redis.

**`app/domains/identity/step_up.py`** (new package `app/domains/identity/`)
```python
class StepUpGate(Protocol):                # bound to the session
    async def is_step_up_valid(self) -> bool: ...
```

**`app/domains/conversation/tools/write.py`** (new)
```python
class BankWriteTools(Protocol):            # raw; bound to one ToolContext; never sees a token
    async def get_block_origin(self, card_id: str) -> BlockOrigin: ...                      # cards.get_block_origin
    async def lock_card(self, card_id: str) -> ActionResult: ...                             # cards.lock_card
    async def unlock_card(self, card_id: str) -> ActionResult: ...                           # cards.unlock_card
    async def block_card(self, card_id: str, reason: BlockReason) -> ActionResult: ...       # cards.block_card
    async def order_replacement(self, card_id: str, address_ref: AddressRef) -> ActionResult: ...  # cards.order_replacement

BankWriteToolsFactory = Callable[[ToolContext], BankWriteTools]
```
Every method may raise `NotFound`, `AccessDenied` or `ToolUnavailable`. The four writes may also raise `Conflict`. A raw write returns `verified=True` only after re-reading the record (R3). The FakeBank does that in B4, Postgres in D3-A3.

**`app/domains/conversation/tools/executor.py`** (new)
```python
StepUpRule = Callable[[str, ToolArgs], bool]   # (tool, args) -> needs step-up; injected (D7)

class ConfirmedWriteTools:                     # what config["configurable"]["bank_write_tools"] holds (D5)
    def __init__(self, raw: BankWriteTools, confirmations: ConfirmationStore,
                 step_up: StepUpGate, requires_step_up: StepUpRule) -> None: ...
    async def issue_plan(self, steps: Sequence[PlanStep]) -> ConfirmationPlan: ...
    async def cancel_plan(self, token_id: str) -> None: ...
    async def is_step_up_valid(self) -> bool: ...
    async def get_block_origin(self, card_id: str) -> BlockOrigin: ...          # pass-through
    async def lock_card(self, card_id: str, token_id: str) -> ActionResult: ...
    async def unlock_card(self, card_id: str, token_id: str) -> ActionResult: ...
    async def block_card(self, card_id: str, reason: BlockReason, token_id: str) -> ActionResult: ...
    async def order_replacement(self, card_id: str, address_ref: AddressRef, token_id: str) -> ActionResult: ...
```
Each write builds `args` from its own non-token parameters (e.g. `{"card_id": …, "reason": …}`) and follows D3's order. The idempotency key `<token_id>:<step_index>` is documented in the module docstring, not implemented (D13).

**`app/domains/conversation/ui.py`** (new)
```python
class ConfirmStepView(BaseModel):          # frozen
    tool: str; summary_key: str; facts: list[Fact]         # 04 §7
class ConfirmPayload(BaseModel):           # frozen
    token_id: str; steps: list[ConfirmStepView]
class OtpRequiredPayload(BaseModel):       # frozen
    tool: str                              # the action waiting on step-up
class ConfirmEvent(BaseModel):  kind: Literal["confirm"];      payload: ConfirmPayload
class OtpRequiredEvent(BaseModel): kind: Literal["otp_required"]; payload: OtpRequiredPayload
UIEvent = Annotated[ConfirmEvent | OtpRequiredEvent, Field(discriminator="kind")]
# card_picker / transaction_list / handoff_banner are added by the cards that emit them
```

**`app/domains/conversation/state.py`**: `actions: NotRequired[Annotated[list[ActionResult], add]]` (D10). `Pending.awaiting_slot` gains the documented values `"confirmation"` and `"otp"` (the type stays `str | None`).

**`app/domains/conversation/graph.py`**
```python
class ConfirmationDecision(BaseModel):     # frozen, extra="forbid"
    token_id: str
    decision: Literal["confirm", "cancel"]

TurnInput:   + confirmation: NotRequired[ConfirmationDecision | None]   # D17
TurnOutput:  + ui: NotRequired[list[UIEvent]]                           # D16
GraphState:  + confirmation: NotRequired[ConfirmationDecision | None]; ui: NotRequired[list[UIEvent]]
```
`run_turn` passes `{"user_text": text, "confirmation": None}`. `load_session` additionally returns `"ui": []`.

**Pause/resume protocol for B5** (normative; B5 implements it):
1. Before a write: if the rule says step-up and `is_step_up_valid()` is false → D15 OTP pause.
2. Otherwise `issue_plan` → D15 confirm pause, with the `ui.confirm` payload built from the plan (money, dates and masks in `facts`, formatted in code, R4).
3. The next turn resumes on either a `confirmation` input (the button; `understand` is skipped) or NLU `affirm`/`deny` against `pending.awaiting_slot == "confirmation"`. A stale `token_id` executes nothing.
4. On confirm, call each step through `bank_write_tools` with the token, then append the `ActionResult`. On cancel or deny, `cancel_plan`. Either way, clear `pending` and `confirmation_token_id`. Report "done" only when `verified` is true. Otherwise hand off (`action_unverified`, `02` §4.6).

## Touch map

```
backend/app/core/errors.py                               edit: 4 error classes (D14)
backend/app/core/actions.py                              new: ActionResult (D9)
backend/app/domains/cards/schemas.py                     edit: BlockReason, AddressRef, BlockOrigin
backend/app/domains/policy/{__init__,confirmation}.py    new: args_hash, PlanStep, ConfirmationPlan, ConfirmationStore
backend/app/domains/identity/{__init__,step_up}.py       new: StepUpGate
backend/app/domains/conversation/tools/write.py          new: BankWriteTools, BankWriteToolsFactory
backend/app/domains/conversation/tools/executor.py       new: StepUpRule, ConfirmedWriteTools
backend/app/domains/conversation/tools/__init__.py       edit: re-export the new names
backend/app/domains/conversation/ui.py                   new: UIEvent and payloads
backend/app/domains/conversation/state.py                edit: actions type
backend/app/domains/conversation/graph.py                edit: ConfirmationDecision, TurnInput/TurnOutput/GraphState, run_turn passes confirmation=None
backend/app/domains/conversation/nodes/load_session.py   edit: reset ui
backend/tests/unit/test_r1_customer_scope.py             edit: +1 test
backend/tests/unit/test_r2_confirmed_writes.py           new
backend/tests/unit/test_r3_action_result.py              new
backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py new
docs/solution-docs/04-contracts.md                       §1, §3, §7 (D19)
docs/solution-docs/02-conversation-design.md             §3 (D19)
```
mypy strict already covers `core` and `conversation`. Add `app/domains/policy` to the strict set (`06` §4 lists `policy/`).

## Test list

All tests use stubs and no LLM.

| Test | Proves |
|---|---|
| `test_r1_customer_scope.py::test_no_customer_id_on_write_side` | R1. No public method of `BankWriteTools`, `ConfirmedWriteTools`, `ConfirmationStore` or `StepUpGate` has a `customer_id` or `ctx` parameter (checked with `inspect.signature`), and `PlanStep`/`ConfirmationDecision` have no `customer_id` field |
| `test_r2_confirmed_writes.py::test_raw_write_runs_only_after_its_step_is_consumed` | R2. Parametrized over the 4 writes: the stub store receives the exact `(tool, args)` of the raw call (no token in `args`). When the store raises `ConfirmationRequired`, the raw write is never called and the error propagates |
| `test_r2_confirmed_writes.py::test_step_up_checked_before_token_is_consumed` | R2 step-up. Rule true and gate false → `StepUpRequired`, `consume_step` not called, raw not called. Rule true and gate true → the write proceeds |
| `test_r2_confirmed_writes.py::test_failed_or_unverified_step_cancels_the_plan` | R2 + R3 (ADR-027). Raw raises `ToolUnavailable` → `cancel(token_id)` is called and the error re-raised. Raw returns `verified=False` → `cancel` is called and the result is returned unchanged |
| `test_r2_confirmed_writes.py::test_args_hash_binds_tool_and_args` | R2 binding. Same hash for reordered keys; a different hash for a different tool or any different arg value |
| `test_r3_action_result.py::test_verified_is_required` | R3. `ActionResult.model_validate` without `verified` raises `ValidationError` |
| `test_r6_no_write_tools_in_llm_nodes.py::test_llm_nodes_cannot_reach_write_tools` | R6 (D6). A source scan of `conversation/nodes/**` and `conversation/flows/**`: every module importing `app.core.llm` has no reference to `bank_write_tools`, `ConfirmedWriteTools`, `BankWriteTools`, `tools.write` or `tools.executor`. It also asserts that at least one scanned module does import `app.core.llm`, so the scan isn't vacuous |

Reused, expired, reordered and cross-customer token rejection is the store's behavior. It is tested against the B4 fake and the D3-A2 Redis store, not here. There are no schema-shape tests (test budget).

## Boundaries

- **Always:**
  - Keep tokens out of raw `BankWriteTools` and out of `PlanStep.args`.
  - Keep `customer_id` out of every new signature and model (R1).
  - Check step-up before consuming.
  - Cancel the plan on a failed or unverified step.
  - Point docstrings at `04`/`02` and this spec rather than restating them.
- **Ask first:**
  - Adding a runtime dependency.
  - Adding any field to `TurnState` beyond D10.
  - Giving `ActionResult` a default for `verified`.
  - Adding a default `StepUpRule` in code (R8).
  - Changing the K3 read contracts.
- **Never:**
  - Implement FakeBank writes, a fake store or a fake gate (B4).
  - Implement flows or `route` changes (B5).
  - Implement SSE or the confirmations route (A4 / D3-A2).
  - Implement Redis, Postgres or the OTP route (D3-A).
  - Implement `tools.yaml`, `ToolSpec` or the registry (D3-A1).
  - Import an LLM SDK.
  - Put a raw address anywhere.
  - Touch `eval/scenarios/heldout/` or commit `data/`.

## Success criteria

1. In `backend/`, this command exits 0: `uv run python -c "from app.core.actions import ActionResult; from app.core.errors import PolicyDenied, ConfirmationRequired, StepUpRequired, Conflict; from app.domains.cards.schemas import BlockOrigin, BlockReason, AddressRef; from app.domains.policy.confirmation import ConfirmationStore, ConfirmationPlan, PlanStep, args_hash; from app.domains.identity.step_up import StepUpGate; from app.domains.conversation.tools import BankWriteTools, BankWriteToolsFactory, ConfirmedWriteTools; from app.domains.conversation.ui import UIEvent, ConfirmPayload; from app.domains.conversation.graph import ConfirmationDecision"`.
2. `make check` passes. That means ruff, format, mypy, `lint-imports` with the existing contracts unchanged and KEPT, and every unit test including the existing D1 tests.
3. `cd backend && uv run pytest -q tests/unit/test_r1_customer_scope.py tests/unit/test_r2_confirmed_writes.py tests/unit/test_r3_action_result.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py` reports exactly the new tests above (7) plus the 2 existing R1 tests, all green.
4. `grep -rn "customer_id" backend/app/domains/conversation/tools/write.py backend/app/domains/conversation/tools/executor.py backend/app/domains/policy backend/app/domains/identity` shows no parameter or field named `customer_id` (docstring mentions only).
5. `git diff develop --stat -- backend/app/domains/conversation/flows backend/app/domains/conversation/nodes/route.py backend/app/domains/conversation/tools/fakebank.py` is empty. No behavior changes beyond D16/D17.
6. `04-contracts.md` shows the following, and `02` §3 lists the `ui` output channel, the `confirmation` input channel, the `awaiting_slot` values and `actions: list[ActionResult]`:
   - §1: `token_id` in the write signatures, the concrete `ActionResult`, `BlockOrigin` and `BlockReason`, `address_ref`, the raw-vs-executor split, the four new errors and the idempotency-key note
   - §3: the `ui.confirm` and `ui.otp_required` payloads and the button → `TurnInput.confirmation` mapping
   - §7: `issue` / `consume_step` / `cancel`, the step index and the `ConfirmationRequired` reasons
7. The PR into `develop` is approved by Dev B (ADR-018) and squash-merged.

## Open questions

| Question | Who decides |
|---|---|
| Where the step-up rule lives in the sandbox before `tools.yaml` exists. B4/B5 must not hard-code policy (R8): a provisional YAML with a `provenance` header, or D3-A1 lands first | Dev B in B4, reviewed by Dev A |
| How a flow resumes after OTP verification (the next typed turn re-checks the gate, or a `TurnInput` step-up signal like `confirmation`) | Dev A (D3-A4) with Dev B (B5) |
| Step-up validity window N, and what happens to an open plan when the session expires | Decision-log deferred item, D3-A4 |
| Where R11 retries wrap a write. They must sit inside the executor, between `consume_step` and `cancel`, or a retry after a cancel always fails | Dev A in D3-A3 |
| The idempotency lookup order (look up `<token_id>:<step_index>` before `consume_step` on a checkpoint replay) and its store | Dev A in D3-A3 |
| What happens to a consumed plan when the turn is cancelled mid-write (`asyncio.CancelledError`, D20): today the plan is left as is | Dev A in D3-A3, with replay and idempotency |
