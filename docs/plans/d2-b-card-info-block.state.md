# State: D2-B — Card info and block/unblock in the sandbox
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D2-B (G7 + G8, owner B) · spec `docs/specs/d2-b-card-info-block.md` · plan `docs/plans/d2-b-card-info-block.md`
Branch `feat/d2-b-card-info-block`, based on `develop` (`da1f801`, includes D2-K write contracts).

## Conventions established for this card
Full list: plan §"Facts checked against the repo". The ones every task needs:
- Baseline at `da1f801`: `cd backend && uv run pytest tests/unit -q` → 27 passed; `uv run mypy app` clean; `uv run lint-imports` 4 kept. Any new red is the current task's.
- Commands run as `cd backend && uv run …`. No pytest-asyncio: drive coroutines with `asyncio.run(...)`. Fake LLM only.
- Policy loaders follow `flows/card_select.py`: frozen, `extra="forbid"` pydantic model with required `provenance` and `version`.
- `build_sandbox_session(customer_id, data_dir)` signature and 3-tuple return must not change (Streamlit `sandbox_ui.py` depends on it).
- Fixture (`backend/tests/fixtures/fakebank/`, UTF-8 BOM, CRLF): add new customers only; never change the 3 existing customers' card sets.
- No new `TurnState` field in this card. Existing reply assertions stay byte-identical (only `test_es_greeting_gets_cardy_template`'s `debug.route` changes, in T11).
- Graph node/edge changes regenerate `docs/diagrams/turn-graph-v0.mmd` (`make graph-diagram`).
- `policy/*`, `identity/*`, `safety/vault.py` must not import `app.domains.conversation`. `localization/format.py` imports no other domain.
- Queue ids are `Literal["atencion","cobranza","fraudes"]` (`Queue` in `localization/format.py`, T3); reuse it for escalation.yaml queues.
- Channel reducers/reset markers live in `state.py`, never in `graph.py` (T9: `graph.py` runs as `__main__` for `--mermaid`, so a reducer defined there is duplicated and LangGraph rejects the channel).
- `flows/actions.otp_pause(flow, node, tool, language)` takes `language` as a 4th arg (T10); `card_unlock`/`replacement` call it that way.
- `flows/actions.execute` `done_values` may be a mapping or a `Callable[[ActionResult], Mapping]` (T14, for `{reference}=tracking_id` known only after the write).
- `DEMO_OTP_CODE` is never committed: `.env.example` gets it empty; tests pass their own code.

## Human decisions taken mid-card
- Plan time: P1–P6 all option (a) — see plan §"Human decisions taken at plan time".
- Plan time (blocks T5/T14/T16): `action_unverified` handoff queue → add section `action_queues: {action_unverified: atencion}` to `policies/escalation.yaml`. Spec amendment, recorded in T20.

- T8: template digit checks strip `{...}` placeholders first (`card_last4` is a legal placeholder name).

- Re-plan after T8 (human): remaining 13 tasks merged into T9–T16 (old T10→T9, T13+T14→T10, T9+T12+T15→T11, T16→T12, T17+T19→T13, T18→T14 cut line, T20→T15, T21→T16).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | ac8feb013014fb2bf | Fixture: inactive CO + past-due AR customers, FX file; 10 passed |
| T2 | done | ab8ae36828ada2d62 | FxRate + get_fx_rate + CustomerProfile.city; 8 passed, mypy clean |
| T3 | done | a6eed53ff27ecac6f | BANK_TZ, local_today, format_time, mxn_estimate, queue_label, format_days; test_format 1 passed |
| T4 | done | abec937978b2b7b9d | min_payment.yaml + loader, min_payment(), next_due_date(); 1 passed |
| T5 | done | a1e18d026a1c079a0 | tools.yaml + escalation.yaml (+action_queues) and loaders; R2 step-up test 2 passed |
| T6 | done | aa3feabaec65d718b | InMemoryConfirmationStore, FakeStepUpGate, DEMO_OTP_CODE; R2 tests 3 passed |
| T7 | done | aa29af85158ceebd5 | FakeBank overlay + FakeBankWrites + block origin + InMemoryAddressVault; 10 passed |
| T8 | done | ae17080ba3b6b881d | 18 new ES/PT templates (32 kinds); Verify digit check strips placeholders; 6 passed |
| T9 | done | a5886179b2167d846 | Graph segments/finish/resume, entry routing, queue, smalltalk; 10 passed |
| T10 | done | a64f7696ca1b48d2f | flows/actions.py helpers, make_session harness, card_block flow; R3 + block tests 12 passed |
| T11 | done | ad55f27964d32b104 | card_info B1 + compose@v3 + nlu@v3 + block-then-balance; 18 passed |
| T12 | done | af6e4a3443ffacf8a | card_unlock flow (origin check, OTP resume, bank-side handoff); 7 passed |
| T13 | done | ae301872e289eb861 | sandbox write wiring + /confirm /cancel /otp + debug; 1 new persona, 3 annotated; 6 passed |
| T14 | done | a6efccc4d44869a6c | replacement flow (offer, address confirm, OTP, vault, RPL- tracking); 9 passed |
| T15 | done | a6c03db0e2bbc3292 | 04 §1/§3/§5, 02 §3/§4.2 and spec amendments (P1–P7, replacement_declined, action_queues) |
| T16 | pending | | human task (Dev B) |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — Fixture rows for inactive, past-due and FX cases
Changed: `backend/tests/fixtures/fakebank/customers.csv` (appended `CLI-TFINACT00004` Medellin/Inactive, `CLI-TFPASTD00005` Cordoba/Active).
Changed: `backend/tests/fixtures/fakebank/products.csv` (appended `PRD-TFI4CRED0001` COP dpd=0, `PRD-TFP5CRED0001` ARS dpd=30).
Created: `backend/tests/fixtures/fakebank/daily_exchange_rates.csv` (USD/MXN 2026-03-11 & 2026-03-12, MXN/USD 2026-03-12), UTF-8 BOM + CRLF.
Changed: `backend/tests/fixtures/fakebank/README.md` (documents the 2 new customers and the FX file).
Facts the next tasks need: existing 3 customers/cards untouched; new FX file lives alongside the fixture dir, not under `data/`.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r1_fakebank.py tests/unit/test_card_select.py tests/unit/test_sandbox_conversations.py tests/unit/test_graph.py -q` → 10 passed.

### T2 — Read-side contract: `FxRate`, `get_fx_rate`, `CustomerProfile.city`
Created: `backend/app/domains/localization/schemas.py` (`FxRate`, frozen).
Changed: `backend/app/domains/localization/__init__.py` (exports `FxRate`);
`backend/app/domains/conversation/tools/bank.py` (`BankReadTools.get_fx_rate`);
`backend/app/domains/conversation/tools/fakebank.py` (`FakeBank.get_fx_rate` reads
`<data_dir>/daily_exchange_rates.csv`, no customer filter, `NotFound` on empty pair;
`get_profile` now selects `city`);
`backend/app/domains/customers/schemas.py` (`CustomerProfile.city: str | None = None`);
`backend/app/domains/conversation/sandbox.py` (`_RecordingBankTools.get_fx_rate`).
Facts the next tasks need: fixture FX rows are ISO dates, so `date.fromisoformat` works
directly; `daily_exchange_rates.csv` columns are `date, source_currency, target_currency,
exchange_rate, buy_rate, sell_rate, source`; `customers.csv` has a `city` column already.
Deviations: none.
Verify: inline `python -c` script → no assertion error (rate `as_of` 2026-03-12,
`p.city == "Ciudad de Mexico"`); `uv run pytest tests/unit/test_r1_fakebank.py
tests/unit/test_sandbox_conversations.py -q` → 8 passed; ruff check/format and mypy on
the 4 touched paths → all clean.

### T3 — B2 formatting: MXN estimate, `BANK_TZ`, time, queue and days labels
Changed: `backend/app/domains/localization/format.py` (added `BANK_TZ`,
`local_today`, `format_time`, `mxn_estimate`, `queue_label`, `format_days`, `Queue`
literal); `backend/app/domains/localization/__init__.py` (exports all of the above).
Created: `backend/tests/unit/test_format.py` (`test_money_dates_masks_three_countries`).
Facts the next tasks need: `mxn_estimate(amount_usd, fx, language)` reuses
`format_money(converted, fx.target, "MX")` for the MX pattern, so the estimate string
never repeats the "MXN" code; `queue_label` covers `atencion`/`cobranza`/`fraudes`
(no policy-loaded `Queue` type exists yet — this is a plain `Literal`, T20 wires
`policies/escalation.yaml`'s `action_queues` separately).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_format.py -q` → 1 passed;
`uv run ruff check app/domains/localization tests/unit/test_format.py` → all checks
passed; `uv run ruff format --check app/domains/localization tests/unit/test_format.py`
→ 4 files already formatted; `uv run mypy app/domains/localization` → no issues in
3 source files.

### T4 — `policies/min_payment.yaml` and its formula
Created: `policies/min_payment.yaml` (provenance/version, then `min_payment` and
`due_date` blocks, per D5/P5/P6).
Created: `backend/app/domains/policy/min_payment.py` (`MinPaymentAmounts`,
`DueDatePolicy`, `MinPaymentPolicy` frozen/`extra="forbid"`, `load_min_payment_policy`,
`min_payment`, `next_due_date`); follows the `flows/card_select.py` loader pattern.
Created: `backend/tests/unit/test_min_payment.py` (`test_floor_percent_due_date`).
Facts the next tasks need: `min_payment` caps at `balance` *before* comparing
percent vs floor, so a floor test needs `balance >= floor` or the cap masks it;
`KeyError` on an unknown currency is a plain dict lookup, uncaught; module imports
only stdlib + pydantic + yaml.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_min_payment.py -q` → 1 passed;
`uv run ruff check app/domains/policy tests/unit/test_min_payment.py` → all checks
passed; `uv run ruff format --check app/domains/policy tests/unit/test_min_payment.py`
→ 4 files already formatted; `uv run mypy app/domains/policy` → no issues in 3
source files.

### T5 — `policies/tools.yaml` + `escalation.yaml` and their loaders
Created: `policies/tools.yaml`, `policies/escalation.yaml` (provenance/version headers,
exactly the spec's blocks plus P7's `action_queues`).
Created: `backend/app/domains/policy/tools_policy.py` (`ToolPolicy`, `ToolsPolicy`,
`load_tools_policy`, `step_up_rule`); `backend/app/domains/policy/escalation.py`
(`CustomerNotActivePolicy`, `BankSideQueuesPolicy`, `ActionQueuesPolicy`,
`EscalationPolicy`, `load_escalation_policy`).
Created: `backend/tests/unit/test_r2_confirmation_store.py` (`test_tools_yaml_step_up_rule`,
`test_headerless_policies_fail_to_load`).
Facts the next tasks need: `escalation.py` imports `Queue` from
`app.domains.localization.format` (not yet re-exported from `localization/__init__.py`)
for `queue: Queue` fields, per this card's Queue convention; `step_up_rule`'s
`KeyError` on an unknown tool is a plain dict lookup, uncaught; both loaders follow
the `card_select.py`/`min_payment.py` pattern (frozen, `extra="forbid"`, repo-root-relative
default path, four `.parents[N]`).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmation_store.py -q` → 2 passed;
`head -1 ../policies/tools.yaml ../policies/escalation.yaml` → both start with
`provenance: team-generated-synthetic`; `uv run ruff check app/domains/policy
tests/unit/test_r2_confirmation_store.py` → all checks passed; `uv run ruff format --check
app/domains/policy tests/unit/test_r2_confirmation_store.py` → 6 files already formatted;
`uv run mypy app/domains/policy` → no issues in 5 source files; `uv run lint-imports` →
4 kept, 0 broken.

### T6 — `InMemoryConfirmationStore`, `FakeStepUpGate`, `DEMO_OTP_CODE`
Created: `backend/app/domains/policy/confirmation_memory.py` (`InMemoryConfirmationStore`,
private `_StoredPlan` dataclass; `plans` dict kwarg shared across instances for owner tests).
Created: `backend/app/domains/identity/step_up_fake.py` (`FakeStepUpGate`).
Changed: `backend/app/core/config.py` (`Settings.demo_otp_code: str = ""`);
`.env.example` (new `# --- Step-up (ADR-008) ---` block, `DEMO_OTP_CODE=` empty).
Appended to `backend/tests/unit/test_r2_confirmation_store.py`:
`test_memory_store_enforces_plan_semantics`.
Facts the next tasks need: `InMemoryConfirmationStore`/`FakeStepUpGate` implement their
Protocols structurally (no inheritance), same as `FakeBank`; neither class is re-exported
from its package `__init__.py` (those files carry only a module docstring) — import the
module path directly; `FakeStepUpGate.verify(code)` returns whether that call matched,
`is_step_up_valid()` reports the sticky verified state.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmation_store.py -q` -> 3 passed;
`grep -n "DEMO_OTP_CODE=" ../.env.example` -> line 51; `uv run ruff check app/domains/policy
app/domains/identity app/core/config.py tests/unit/test_r2_confirmation_store.py` -> all
checks passed; `uv run ruff format --check` on the same paths -> 11 files already formatted;
`uv run mypy app/domains/policy app/domains/identity app/core/config.py` -> no issues in
10 source files; `uv run lint-imports` -> 4 kept, 0 broken.

### T7 — FakeBank writes + overlay, block origin, address vault stub
Changed: `backend/app/domains/conversation/tools/fakebank.py` (`FakeBankOverlay`
dataclass; `FakeBank.__init__` takes `overlay: FakeBankOverlay | None = None`,
`_to_summary` is now an instance method applying `locked`/`blocked`;
`FakeBankWrites` implements `BankWriteTools`; `make_fakebank_factory` returns
`(BankToolsFactory, BankWriteToolsFactory)` sharing one overlay).
Created: `backend/app/domains/safety/__init__.py`, `backend/app/domains/safety/vault.py`
(`AddressVault` Protocol, `InMemoryAddressVault`).
Changed: `backend/tests/unit/test_r1_fakebank.py` (`test_writes_refuse_foreign_cards`).
Created: `backend/tests/unit/test_fakebank_writes.py` (`test_writes_read_back_and_block_origin`).
Facts the next tasks need: every `FakeBankWrites` method runs
`self._reads.get_card_details(card_id)` first (a `FakeBank` built from the same
overlay) for the ownership probe, so `AccessDenied`/`NotFound` reuse the exact
read-side rule and nothing is mutated before it passes; `get_block_origin`
checks overlay block, then overlay lock, then `profile.customer_status`, then
`details.days_past_due`, then `details.status`, in that order; `block_card`'s
`reason` and `order_replacement`'s `address_ref` aren't stored anywhere (no
column/vault lookup in the fake); `InMemoryAddressVault` numbers from 1 per
instance, no `get_address` method (not needed by any contract yet).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r1_fakebank.py
tests/unit/test_fakebank_writes.py tests/unit/test_sandbox_conversations.py -q` -> 10 passed;
`uv run ruff check app/domains/conversation/tools app/domains/safety
tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py` -> all checks passed;
`uv run ruff format --check` on the same paths -> 10 files already formatted;
`uv run mypy app/domains/conversation/tools app/domains/safety` -> no issues in 8 source
files; `uv run lint-imports` -> 4 kept, 0 broken.

### T8 — ES/PT templates for B3/B5 in Cardy's voice
Changed: `backend/app/domains/conversation/templates.py` (`TemplateKind` and
`_TEMPLATES` gain 18 entries: `thanks_close`, `nothing_pending`,
`clarify_lock_vs_block`, `already_in_state`, `action_cancelled`,
`action_done_noref`, `otp_required`, `address_confirm`, `address_ask`,
`not_blocked`, `block_permanent_no_undo`, `offer_replacement`,
`replacement_declined`, `replacement_not_eligible`, `handoff_placeholder`,
`credit_only`, `synthetic_footnote`, `read_only_note`; 32 keys total, existing
14 unchanged).
Human decision mid-task: the plan's Verify digit check (`c.isdigit()` over the
raw template) fails on the pre-existing `card_last4` placeholder name (already
in unchanged `action_confirm`/`action_done`), and the spec requires the same
placeholder in 4 new templates. Human chose option 1: amend the Verify's digit
check to strip `{...}` spans first (`re.sub(r"\{[^}]*\}", "", s)`) before
scanning for digits; no rename, no other template touched.
Facts the next tasks need: `card_last4`, `queue_label`, `card_last4` etc. are
still plain `{name}` placeholders (unfilled by this task); the amended digit
check (regex-stripped) is the one to reuse if any later task re-verifies
templates for digits.
Deviations: Verify command amended per the human decision above (digit check
only); everything else in the chain unchanged.
Verify (amended): `cd backend && uv run python -c "import re,typing;from
app.domains.conversation import templates as t;ks=typing.get_args(t.TemplateKind);
assert all(not any(c.isdigit() for c in re.sub(r'\{[^}]*\}','',t.get_template(k,l)))
for k in ks for l in ('es','pt'));assert 'replacement_declined' in ks and
len(ks)==32,len(ks)"` -> digit check OK, len(ks)=32; `uv run pytest
tests/unit/test_sandbox_conversations.py -q` -> 6 passed; `uv run ruff check
app/domains/conversation/templates.py` -> all checks passed; `uv run ruff format
--check app/domains/conversation/templates.py` -> 1 file already formatted;
`uv run mypy app/domains/conversation/templates.py` -> no issues in 1 source file.

### T9 — Turn graph: I/O plumbing, entry routing, intent queue, conversation basics
Changed: `graph.py` (`segments`/`resume` channels, `_entry`, `_dispatch`,
`_after_flow`, `_after_segment`, `_INTENT_NODES`/`_FLOW_NODES`/
`_MANAGEMENT_INTENTS`, `_BRANCH_NODES` +smalltalk, `run_turn(confirmation,
resume)`, `DebugInfo.pending`/`.ui`); `nodes/route.py` (new 5-step `route`);
`nodes/{compose,unsupported,fallback,load_session,__init__}.py`.
Created: `nodes/next_intent.py` (`enqueue`, `next_intent`, `finish`);
`nodes/smalltalk.py`; `tests/unit/test_conversation_basics.py`.
Facts next tasks need: `_INTENT_NODES`/`_FLOW_NODES` double as intent->flow
and flow->node maps (node name == flow name everywhere); flow tasks add
their node to both plus `_BRANCH_NODES` only, no edit to `route.py`/
`next_intent.py` needed; `astream(stream_mode="updates")` reports an
empty-dict node update as `None`, not `{}` (`run_turn` skips `values is None`).
Deviations: `state.py` also changed (not in T9's Files list) to hold
`RESET_SEGMENTS`/`_SegmentsReset`/`_reduce_segments`: `graph.py` also runs as
`__main__` for the mermaid CLI, so a reducer defined there exists as two
distinct objects across the two module identities, and `add_node` raised
"segments already exists with a different type" the moment a node module
imported `GraphState` by its normal package path; `state.py` is never run as
`__main__`, so it is the one safe home (same reasoning as `RESET_FACTS`).
Verify: diagram regenerated; `uv run pytest tests/unit/test_conversation_basics.py
tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py
tests/unit/test_compose.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q`
-> 10 passed; ruff check/format clean on the touched paths; `uv run mypy
app/domains/conversation` -> no issues in 26 source files.

### T10 — Flow action helpers, test harness and the `card_block` flow
Created: `backend/app/domains/conversation/flows/actions.py` (`fill`,
`start_plan`, `decision`, `cancel`, `execute`, `handoff`, `otp_pause`);
`backend/app/domains/conversation/flows/card_block.py` (node `card_block`,
staged on `pending.node` in {none/`card_select`, `block_kind`, `confirm`}).
Changed: `backend/app/domains/conversation/graph.py` (`card_block` node +
edges; `_INTENT_NODES`/`_FLOW_NODES`/`_BRANCH_NODES` gain `"card_block"`);
`backend/tests/conftest.py` (`Session` dataclass, `make_session`).
Created: `backend/tests/unit/test_block_flows.py` (3 tests),
`backend/tests/unit/test_r3_flows.py` (`test_unverified_write_never_says_done`).
Facts the next tasks need: `card_block` persists the chosen `block_kind`
into `state["slots"]` (a plain `NLUSlots(block_kind=...)`, no reducer, last
write wins) so the "confirm" resume -- whose own NLU turn only ever carries
affirm/deny -- still knows which tool to call; a verified permanent block
sets `pending{flow:"replacement", node:"offer", awaiting_slot:"offer_replacement"}`
without registering `"replacement"` in `_FLOW_NODES` (P3: falls to
`unsupported` until the flow that answers it ships); `otp_pause(flow, node,
tool, language)` in `actions.py` takes a 4th `language` param beyond the
plan's 3-arg listing (needed to fill the template) -- unused by this task,
first real caller (`card_unlock`) should sanity-check the signature still
fits; the "card_select.yaml limit" for `block_kind` clarification is a local
`_MAX_BLOCK_KIND_FAILURES = 2` constant in `card_block.py` (no such field
exists in the policy file, matches `card_select.py`'s own private R11 bound).
Deviations: `otp_pause` signature widened by one param (`language`), noted
above; not exercised by this task's tests.
Verify: diagram regenerated; `uv run pytest tests/unit/test_block_flows.py
tests/unit/test_r3_flows.py tests/unit/test_graph.py
tests/unit/test_r6_no_write_tools_in_llm_nodes.py
tests/unit/test_sandbox_conversations.py -q` -> 12 passed; R6 grep clean;
`uv run ruff check`/`ruff format --check` on the touched paths -> all clean;
`uv run mypy app/domains/conversation` -> no issues in 28 source files.

### T11 — `card_info` B1 (`balance_due`), `compose@v3`, `nlu@v3`, "block then balance"
Changed: `backend/app/domains/conversation/flows/card_info.py` (now handles
both `card_status` and `balance_due`, reading the current intent off
`state["intent_queue"][0]`; new `_credit_balance_facts`,
`_read_only_note_fact`, `_facts_and_segments`); `backend/app/domains/
conversation/nodes/compose.py` (`PromptRef("compose", 3)`, `Goal` gains
`balance_due`/`credit_only_offer`, `_HIDDEN_KEYS`, `_money_fact` (adds the
MXN estimate), footnote/read-only-note segments appended after the draft);
`backend/app/domains/conversation/nodes/understand.py`
(`PromptRef("nlu", 3)`); `backend/tests/unit/test_compose.py` (one
assertion: `call.prompt.label == "compose@v3"`, required by the mandatory
version bump -- not in this task's Files list, but "stays green" can't
hold otherwise).
Created: `backend/app/domains/conversation/prompts/{compose@v3,nlu@v3}.md`;
`backend/tests/unit/test_card_info_flows.py` (3 tests, 7 cases: `es-mx-fx`/
`pt-co`/`pt-ar-dpd` for the credit case, `es`/`pt` for debit and inactive).
Appended: `test_conversation_basics.py::test_block_then_balance_in_order`.
Facts the next tasks need: a queued `balance_due` reached with no fresh
`nlu` this turn (a button/OTP resume skips `understand`) reuses
`state["selected_card_id"]` instead of re-running `select_card` with no
hint -- a fresh-`nlu` turn is unaffected, but a customer with 2+ eligible
cards would otherwise re-ask "which card?" on the queued segment; no fix
needed in `next_intent.py`/`route.py`, the wrinkle was `card_info`'s own.
`compose`'s goal-picking reads `state["intent_queue"][0]` the same way
`card_info` does (small private helper duplicated in both files, not
shared, since neither is a natural home for the other).
Deviations: none beyond the `test_compose.py` one-line fix above.
Verify: `uv run python -c "...'balance_due' in load_prompt(PromptRef('nlu',3))"`
-> ok; `uv run pytest tests/unit/test_card_info_flows.py
tests/unit/test_conversation_basics.py tests/unit/test_compose.py
tests/unit/test_sandbox_conversations.py tests/unit/test_graph.py
tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q` -> 18 passed; ruff
check/format clean on the touched paths; `uv run mypy
app/domains/conversation` -> no issues in 28 source files.

### T12 — `card_unlock` flow (origin check, OTP resume, bank-side handoff)
Created: `backend/app/domains/conversation/flows/card_unlock.py` (node
`card_unlock`, staged on `pending.node` in {none/`card_select`, `otp`,
`confirm`}; `_check_status_and_origin` does the `customer_not_active`
refusal then the 4-way `get_block_origin` split per D8/D9/D11/D12).
Changed: `backend/app/domains/conversation/graph.py` (`card_unlock` node +
edges; `_INTENT_NODES`/`_FLOW_NODES`/`_BRANCH_NODES` gain `"card_unlock"`).
Regenerated: `docs/diagrams/turn-graph-v0.mmd`.
Appended to `backend/tests/unit/test_block_flows.py`:
`test_pt_bank_side_unlock_hands_off`, `test_es_unlock_own_lock_needs_otp`.
Facts the next tasks need: the OTP resume node (`pending.node == "otp"`) is
reached only through `_entry`'s `resume == "step_up"` branch -- `route.py`'s
`_answer_fits` has no `"otp"` case, so a typed message never lands there;
`bank_write_tools.get_block_origin` is a plain pass-through on
`ConfirmedWriteTools` (no token, no step-up rule), called the same way
`is_step_up_valid`/`issue_plan` are, through `config["configurable"]
["bank_write_tools"]`; the `customer_block` branch sets the same
`pending{flow:"replacement", node:"offer", awaiting_slot:"offer_replacement"}`
shape `card_block` uses, with no write and no plan (the block already
happened in an earlier turn); a bank-side handoff needs no `get_card_details`
call (the `handoff_placeholder` template only fills `{queue_label}`).
Deviations: none.
Verify: diagram regenerated; `uv run pytest tests/unit/test_block_flows.py
tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q`
-> 7 passed; R6 grep clean; `uv run ruff check`/`ruff format --check` on
`app/domains/conversation tests/unit/test_block_flows.py` -> all clean (36
files already formatted); `uv run mypy app/domains/conversation` -> no
issues in 29 source files.

### T13 — Sandbox write wiring, `/confirm` `/cancel` `/otp`, debug `pending`/`ui`, personas
Changed: `backend/app/domains/conversation/sandbox.py` (new
`_RecordingWriteTools` sharing `_RecordingBankTools.calls`; new
`_SandboxSession` dataclass and `_build_session` building `bank_write_tools`
(`ConfirmedWriteTools` over `_RecordingWriteTools`, `InMemoryConfirmationStore`,
`FakeStepUpGate(get_settings().demo_otp_code)`, `step_up_rule(load_tools_policy())`)
and `vault` (`InMemoryAddressVault`); `build_sandbox_session` now delegates to
`_build_session` and returns its same 3-tuple; `_run_session`'s CLI loop
handles `/confirm`/`/cancel` (token from `graph.aget_state(config).values
["confirmation_token_id"]`), `/otp <code>` (`gate.verify`, then
`resume="step_up"` or the `otp_required` template on a miss, no turn run),
and every other line as a typed turn with `confirmation=None, resume=None`;
debug line appends `pending=… ui=…`).
Changed: `eval/personas.yaml` (added `CLI-UAJ81O52ZM1R`, MX single USD credit
card Active dpd0; added `notes` to 3 existing personas that already fit --
`CLI-2FKTNVMZ3HVH` for bank-side `past_due`, `CLI-UZ7Z6C3JFXGX` for bank-side
`bank_status`, `CLI-AO5PZVMZCL1V` for the Inactive-customer-with-Active-card
case -- no duplicates added).
Facts the next tasks need: `run_turn`'s `text` argument is `""` on every
confirmation/resume turn (matches `test_block_flows.py`'s own convention,
since `_entry` never routes those to `understand`); `graph.aget_state
(config).values` is a plain dict with `.get`, used for both
`confirmation_token_id` and `language` reads; all 4 new/annotated personas'
`get_block_origin`/`customer_status` traits were checked live against
`data/` (`none`, `past_due`, `bank_status`, `customer_status`).
Deviations: none.
Verify: `uv run python -c "...build_sandbox_session...assert {'bank_write_tools','vault'}<=set(...)"` -> OK;
`uv run pytest tests/unit/test_sandbox_conversations.py -q` -> 6 passed;
`uv run ruff check`/`ruff format --check app/domains/conversation/sandbox.py`
-> all clean; `uv run mypy app/domains/conversation/sandbox.py` -> no issues
in 1 source file; personas one-liner (`ANTHROPIC_API_KEY=dummy`) -> `11`
(all personas' `get_profile()` resolved against local `data/`).

### T14 — `replacement` flow: offer, address confirm, OTP for a new address, vault, tracking id
Created: `backend/app/domains/conversation/flows/replacement.py` (node
`replacement`, staged on `pending.node` in {none/`card_select`, `offer`,
`address_confirm`, `otp`, `address`, `confirm`}; shared
`_check_active_and_eligibility` runs the D10 not-active refusal then the
D13 eligibility gate (`customer_block` or an expired card), used by both a
fresh `card_select` and the offer's own affirm).
Changed: `backend/app/domains/conversation/graph.py` (`replacement` node +
edges; `_INTENT_NODES` gains `"replacement_request"`, `_FLOW_NODES` gains
`"replacement"`, `_BRANCH_NODES` gains `"replacement"`); `backend/app/domains/
conversation/flows/actions.py` (`execute`'s `done_values` widened to
`DoneValues = Mapping[str, str] | Callable[[ActionResult], Mapping[str, str]]`
so `{reference}=tracking_id` -- known only after the write returns -- can
fill `action_done`; existing lock/unlock/block callers pass a plain mapping,
unaffected).
Regenerated: `docs/diagrams/turn-graph-v0.mmd`.
Appended to `backend/tests/unit/test_block_flows.py`:
`test_es_lost_card_block_replacement_tracking`,
`test_pt_new_address_needs_otp_and_is_vaulted`.
Facts the next tasks need: `address_ref` (`"on_file"` or the vault's
`"⟨ADDR_n⟩"`) persists from the address/address-confirm turn to the
"confirm" resume via `state["slots"].pending_answer` (existing `NLUSlots`
field, no schema change, same pattern `card_block` uses for `block_kind`);
`_ask_address(language)` is the one place that fills the `address_ask`
template, called from both the address-confirm deny (gate already valid)
and the OTP resume; the R5 test reaches into `session.store._plans` (a
test-only, non-exported attribute) since `ConfirmationStore` has no public
peek -- the only other way to prove the plan's args without consuming the
step.
Deviations: `flows/actions.py` changed (not in this task's Files list) to
widen `execute`'s `done_values` to accept a callable, needed to fill
`{reference}=tracking_id` per D17/the acceptance line; no other caller's
behavior changes (verified by the full Verify run below, which includes
every flow that calls `execute`).
Verify: diagram regenerated; `uv run pytest tests/unit/test_block_flows.py
tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q`
-> 9 passed; R6 grep clean; `uv run ruff check`/`ruff format --check` on
`app/domains/conversation tests/unit/test_block_flows.py` -> all clean (37
files already formatted); `uv run mypy app/domains/conversation` -> no
issues in 30 source files.

### T15 — Docs: `04` §1/§3/§5, `02` §3/§4.2, spec amendment
Changed: `docs/solution-docs/04-contracts.md` (§1: `reference.get_fx_rate` row,
`CustomerProfile.city`, `ActionResult.readback` keys per write; §3:
`TurnInput.resume`/OTP resume path paragraph, `/auth/otp/verify` row note;
§5: `tools.yaml`/`min_payment.yaml`/`escalation.yaml` shapes incl.
`action_queues`); `docs/solution-docs/02-conversation-design.md` (§3:
`pending.awaiting_slot` value list incl. `address`/`address_confirm`/
`offer_replacement`/`block_kind`/`card_hint`, entry-routing order, P1/P3
paragraph for `enqueue`/`next_intent`; §4.2: no-overdue-term formula, P5/P6,
`payment_overdue` fact); `docs/specs/d2-b-card-info-block.md` (`replacement_declined`
added to §"New templates"; `action_queues: {action_unverified: atencion}`
added to the escalation.yaml block, D8 and D11; Open questions' two
plan-time rows replaced by a "Resolved at plan time" note covering P1-P7).
Facts the next tasks need: every symbol name was verified against the
actual code/yaml before writing (grep on `fakebank.py`, `bank.py`,
`graph.py`, `route.py`, `next_intent.py`, `card_info.py`, `actions.py`,
`card_block.py`/`card_unlock.py`/`replacement.py`, and the three real
`policies/*.yaml` files), not copied from the plan/spec text alone.
Deviations: none.
Verify: `grep -n "get_fx_rate\|resume\|min_payment.yaml"
docs/solution-docs/04-contracts.md && grep -n
"offer_replacement\|next_intent\|payment_overdue"
docs/solution-docs/02-conversation-design.md && grep -n
"replacement_declined" docs/specs/d2-b-card-info-block.md` -> all three
greps matched (see task reply for line output).
