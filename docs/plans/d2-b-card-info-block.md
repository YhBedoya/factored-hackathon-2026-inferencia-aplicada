# Plan: D2-B — G7 card info and G8 block/unblock in the sandbox

Spec: [`docs/specs/d2-b-card-info-block.md`](../specs/d2-b-card-info-block.md) · Branch: `feat/d2-b-card-info-block`

## Human decisions taken at plan time

The spec's plan-time open items are settled as follows. All six took option (a).

- **P1. A new flow intent while another flow is paused.** The new flow replaces the paused one. If `confirmation_token_id` is set, call `cancel_plan` on it. Clear `pending`, `confirmation_token_id` and `clarification_failures`, drop the old `intent_queue`, then queue this turn's intents. This rule goes into `02` §3 (D20).
- **P2. `card_select` for block, unlock and replacement.** Reuse `card_status.eligible_statuses` from `policies/card_select.yaml` for every intent, with no change to the YAML or the loader. A card in the wrong state is caught by the flow's own check (`already_in_state`, `not_blocked`, `replacement_not_eligible`).
- **P3. A queued intent with no flow in this card** (for example `decline_explain`, `unrecognized_charge`, `human_request`, `transaction_search`, the Stretch intents). It becomes an `unsupported_intent` template segment at its place in the queue.
- **P4. "No" at `awaiting_slot = "offer_replacement"`.** It gets a new fixed template, `replacement_declined`, clears `pending`, then pops the queue. This is a small spec amendment, recorded in T15.
- **P5. Minimum payment.** `min(max(percent × balance, floor[currency]), balance)`, and `0` when balance ≤ 0. The `max`/`min` shape is code. The percent and floors come from the YAML.
- **P6. Due date.** The next day `due_day_of_month` that falls on or after today in `BANK_TZ`, so it is today when today is the 10th.

- **P7. The `action_unverified` queue.** `policies/escalation.yaml` gains a third section, `action_queues: {action_unverified: atencion}`. This is a spec amendment, recorded in T15.

## Facts checked against the repo

- **Progress.** T1–T8 are done. What each one actually delivered (symbol names, module paths, deviations) is in the state file's task log, `docs/plans/d2-b-card-info-block.state.md`. Any later check of templates for digits strips `{...}` placeholders first (`re.sub(r"\{[^}]*\}", "", s)`), because `card_last4` is a legal placeholder name (human decision in T8).
- **Starting point.** `develop` is `da1f801`, the same commit as this branch's HEAD. The baseline at that commit:
  - `cd backend && uv run pytest tests/unit -q` shows **27 passed**.
  - `uv run mypy app` shows no issues in 59 files.
  - `uv run lint-imports` shows **4 kept, 0 broken**.

  Any red after a task comes from that task. Commands run as `cd backend && uv run …`, and a uv `VIRTUAL_ENV` mismatch warning is harmless. There is **no pytest-asyncio**: tests drive coroutines with `asyncio.run(...)`.
- **What D2-K left (all present).**
  - `core/actions.py` has `ActionResult`. It has `extra="forbid"`, a `verified` field with no default, `readback: dict[str, ReadbackValue]` and `tracking_id`.
  - `core/errors.py` has `PolicyDenied`, `ConfirmationRequired(reason)`, `StepUpRequired` and `Conflict`.
  - `domains/policy/confirmation.py` has `PlanStep{tool, args}`, `ConfirmationPlan{token_id, steps, expires_at}`, the `ConfirmationStore` Protocol (`issue`, `consume_step -> int`, `cancel`) and `args_hash`.
  - `domains/identity/step_up.py` has the `StepUpGate` Protocol (`is_step_up_valid`).
  - `conversation/tools/write.py` has `BankWriteTools` and `BankWriteToolsFactory`.
  - `conversation/tools/executor.py` has `ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up)` with `issue_plan`, `cancel_plan`, `is_step_up_valid`, the pass-through `get_block_origin`, and the four writes, each taking `token_id`. It also has `StepUpRule = Callable[[str, ToolArgs], bool]`, with no default.
  - `conversation/ui.py` has `ConfirmEvent`, `OtpRequiredEvent`, `ConfirmStepView{tool, summary_key, facts}` and `UIEvent`.
  - `cards/schemas.py` has `BlockReason`, `AddressRef` and `BlockOrigin{kind, reason}`.
- **Registry tool names.** `cards.lock_card`, `cards.unlock_card`, `cards.block_card`, `cards.order_replacement` and `cards.get_block_origin`.
- **Graph today** (`conversation/graph.py`).
  - Wiring: `load_session → understand → route`. `route` goes to `card_info`, `unsupported` or `fallback`. `card_info` goes to `compose` or `fallback`. Those three are terminal.
  - `run_turn(graph, text, *, config)` streams `{"user_text", "confirmation": None}`.
  - `DebugInfo` has `language`, `status`, `intents`, `slots`, `route` and `tools_called`. `route` is the first node in `_BRANCH_NODES = ("card_info", "unsupported", "fallback")` seen in the stream. `tools_called` reads `config["configurable"]["bank_tools"].calls`.
  - `route` sends only `card_status`, or a pending `card_hint`, to `card_info`. `balance_due` and every other intent currently go to `unsupported`.
  - `unsupported` already handles a lone `greeting` (`greeting_named`/`greeting`).
- **State** (`conversation/state.py`).
  - `TurnState` already has `intent_queue: list[Intent]`, `pending: Pending{flow, node, awaiting_slot}`, `slots: NLUSlots`, `selected_card_id`, `clarification_failures`, `confirmation_token_id`, `facts` (append, or reset on `RESET_FACTS`), `actions` (append) and `escalation_reason`. **No `TurnState` field is added in this card.**
  - `Fact.value` is `str | int | Decimal | date | datetime | None`. There is no bool and no model, so FX goes in as two facts.
  - `NLUSlots` has `card_hint`, `block_kind` (`temporary_lock` / `permanent_block`) and `pending_answer`.
  - The intents are `card_block`, `card_unlock` and `replacement_request`.
- **Compose** (`nodes/compose.py`).
  - `compose_reply` offers fact keys only, never `currency`. It rejects a draft with an unknown placeholder, a stray brace or a digit outside a placeholder.
  - `_format_fact` raises on an unknown key.
  - It uses `PromptRef("compose", 2)`, and `nodes/understand.py` uses `PromptRef("nlu", 2)`. Prompt files are `conversation/prompts/<name>@v<n>.md`. The old files stay.
- **Templates** (`templates.py`). They use `TemplateKind` with `get_template(kind, language)` and contain no digits. `action_confirm` and `action_done` already exist, with `{action}`, `{card_last4}`, `{effect}`, `{result}`, `{time}` and `{reference}`. Filling is the caller's job: `unsupported` uses `str.replace("{customer_name}", …)`.
- **Localization** (`localization/format.py`).
  - `format_money(amount, currency, country)` already gives `US$1,234.50` for MX in USD, `COP $1.234.567` and `ARS $ 1.234,50`, and `MXN $21,480.00` for MXN in MX.
  - `format_date` gives `dd/mm/yyyy`, and `mask_card(last4)` gives `•••• 1234`.
  - There is **no** `BANK_TZ` code. The zones are decided in `03` §5: MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`. They become a constant table in `localization/format.py`, because they are a documented fact, not policy.
- **Policy-loader pattern.** `flows/card_select.py` sets it: a frozen, `extra="forbid"` pydantic model with required `provenance` and `version`. `_REPO_ROOT` is `Path(__file__).resolve().parents[N]`, where N is 5 from `conversation/flows/` and 4 from `domains/policy/`. The mypy strict override already covers `app.domains.policy.*`. `policies/` holds only `card_select.yaml` today.
- **FakeBank** (`tools/fakebank.py`). It is bound to a `ToolContext` and runs one fresh DuckDB connection per query, with `all_varchar=true` and bound parameters. The R1 probe pattern is `_probe_card_exists`. `_to_summary` hardcodes `locked=False`. `get_profile` selects `country, customer_status, first_name`, and not `city`. `make_fakebank_factory(data_dir)` has **no callers**, so its return type is free to change.
- **Sandbox** (`conversation/sandbox.py`).
  - `_RecordingBankTools` records method names.
  - `build_sandbox_session(customer_id, data_dir)` returns `(graph, config, recording_tools)`. **`backend/scripts/sandbox_ui.py` (Streamlit) calls it and unpacks that 3-tuple.** Touching the Streamlit page is Ask-first, so that signature and its return value must not change.
  - `make chat-sandbox CUSTOMER=<id>` runs `python -m app.domains.conversation.sandbox --customer <id>` against `data/`.
- **Settings** (`core/config.py`). There is no `demo_otp_code` yet. ADR-008 says the OTP is a fixed code read from env and **never committed**, so `.env.example` gets `DEMO_OTP_CODE=` empty with a comment. Tests pass their own code.
- **Fixture** (`backend/tests/fixtures/fakebank/`, UTF-8 with BOM, CRLF).
  - It has 3 customers: `CLI-TFMULTI00001` (MX, city `Ciudad de Mexico`), `CLI-TFSINGLE0002` (CO) and `CLI-TFBLOCKD0003` (AR).
  - `CLI-TFMULTI00001` has `PRD-TFM1CRED0001`: USD credit, 6475, balance 1234.50, limit 5000.00, dpd 0, expiry 2027-08-31.
  - `CLI-TFSINGLE0002` has `PRD-TFS2CRED0001`: COP credit, 2222, balance 1234567.
  - `CLI-TFBLOCKD0003` has `PRD-TFB3DEBT0001`: ARS debit, **Blocked**, 3333.
  - There is no `daily_exchange_rates.csv`. `test_r1_fakebank.py::_EXPECTED_CARD_IDS` pins those three customers' card sets, so **add new customers only**.
- **Real data.** `data/daily_exchange_rates.csv` has columns `date,source_currency,target_currency,exchange_rate,buy_rate,sell_rate,source`, with a direct `USD,MXN` pair every day (1097 rows, last 2026-06-17). Credit cards in `data/products.csv` use USD, COP and ARS only, which are exactly the three floors. `data/` exists locally for picking personas (traits only, R10).
- **R6 scan.** `test_r6_no_write_tools_in_llm_nodes.py` scans every `conversation/nodes/*.py` and `conversation/flows/*.py`. A module that imports `app.core.llm` must not contain `bank_write_tools`, `ConfirmedWriteTools` or `BankWriteTools`. Only `understand.py` and `compose.py` import the LLM.
- **Diagram.** `test_graph.py::test_graph_compiles_and_diagram_is_current` compares the compiled graph to `docs/diagrams/turn-graph-v0.mmd`. Every task that changes the graph's nodes or edges regenerates it with `cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd` (same as `make graph-diagram`).
- **Existing tests that pin behaviour this card changes.**
  - `test_sandbox_conversations.py::test_es_greeting_gets_cardy_template` asserts `debug.route == "unsupported"` for a lone greeting. T9 moves greetings to `smalltalk` and updates **only that one assertion**. The reply assertion stays byte-identical.
  - Every other existing reply assertion must stay byte-identical. A single segment joined is the old reply.
  - Existing test configs carry only `thread_id`, `session`, `bank_tools` and `llm`. Nodes that aren't write flows must not require `bank_write_tools` or `vault`.
- **Imports.** The import-linter contracts are layers `api → domains → core`, LLM SDKs only in `core.llm`, and no `*.repository` from `conversation` or `core`. `conversation → policy/identity/safety/localization/cards/customers` is allowed.
  - `policy/confirmation.py` and `identity/step_up.py` must not import `app.domains.conversation` (cycle). The same holds for the new `policy/*.py`, `identity/step_up_fake.py` and `safety/vault.py`.
  - `localization/format.py` imports no other domain. `localization/schemas.py` imports only pydantic and the stdlib.

## Components

### Graph shape

This is the one design every graph task shares. Tasks cite this section.

- **Channels** (graph-local, in `GraphState` only, not `TurnState`):
  - `resume: Literal["step_up"] | None`.
  - `segments: Annotated[list[str], <append, reset on RESET_SEGMENTS>]`. The marker pattern is the same as `RESET_FACTS` and lives in `graph.py`. `load_session` resets it every turn.
  - `TurnInput` gains `resume`.
  - `DebugInfo` gains `pending: str | None` (`"<flow>.<awaiting_slot>"`) and `ui: list[str]` (event kinds).
- **Entry.** A conditional edge after `load_session` (`_entry`), checked in this order:
  1. `confirmation` is set. If `pending.awaiting_slot == "confirmation"`, go to that flow's node. Otherwise go to `smalltalk`.
  2. `resume == "step_up"`. If `pending.awaiting_slot == "otp"`, go to that flow's node. Otherwise go to `smalltalk`.
  3. `pending.awaiting_slot == "address"` goes to that flow's node.
  4. Anything else goes to `understand`.
- **`route`** (conditional after `understand`), checked in this order:
  1. `nlu is None` goes to `fallback`.
  2. `out_of_market`, `out_of_scope` or `injection_suspected` goes to `unsupported`. `pending` is kept.
  3. `pending` is set **and the answer fits** goes to `_FLOW_NODES[pending.flow]` (unknown → `unsupported`). An answer fits when the NLU carries the awaited thing (`card_hint`, `block_kind`, or affirm/deny for `confirmation`, `address_confirm` and `offer_replacement`) and no flow intent other than the pending flow's own.
  4. Only management intents (`greeting`, `thanks_close`, `affirm`, `deny`) go to `smalltalk`.
  5. Anything else goes to `enqueue`.
- **`enqueue`** (in `nodes/next_intent.py`). Applies P1 when `pending` is set. `cancel_plan` goes through `config["configurable"].get("bank_write_tools")`, and only if a token is set. Then `intent_queue` becomes this turn's non-management intents in message order. A greeting next to a flow intent is dropped (D16).
- **`_dispatch`** maps `intent_queue[0]` through `_INTENT_NODES`:
  - `card_status` and `balance_due` → `card_info`
  - `card_block` → `card_block`
  - `card_unlock` → `card_unlock`
  - `replacement_request` → `replacement`
  - anything else → `unsupported` (P3)

  Flow tasks add their node to `_INTENT_NODES`, `_FLOW_NODES` and `_BRANCH_NODES`.
- **After a flow node** (`_after_flow`):
  - `escalation_reason` in `{tool_unavailable, no_cards, clarification_exhausted}` goes to `fallback`.
  - Non-empty `facts` goes to `compose`.
  - Anything else goes to `_after_segment`.
- **`_after_segment`** (after `compose`, `fallback`, `unsupported` and template-only flow outcomes): if `pending` is set, go to `finish` (a pause ends the turn and keeps the queue). Otherwise go to `next_intent`.
- **`next_intent`** pops the head of `intent_queue`. If anything is left, it writes `RESET_FACTS` and dispatches the new head. Otherwise it goes to `finish`, and `facts` stay, so `test_graph`'s snapshot still sees the D13 keys. `smalltalk` goes straight to `finish`.
- **`finish`** sets `reply = "\n\n".join(segments)`.
- **Flows append their reply text to `segments`**, from templates filled in code, and never set `reply`. `compose` appends its filled draft. `unsupported` and `fallback` append their template.

### Components by file

| Component | Where | Depends on |
|---|---|---|
| `FxRate` | `backend/app/domains/localization/schemas.py` (new) | pydantic |
| `get_fx_rate`, `CustomerProfile.city` | `conversation/tools/bank.py`, `customers/schemas.py`, `tools/fakebank.py`, `sandbox.py` recorder | `FxRate`, fixture |
| B2 formatting: MXN estimate, `BANK_TZ`, `local_today`, `format_time`, `queue_label`, `format_days` | `localization/format.py` | `FxRate` |
| Min-payment policy | `policies/min_payment.yaml`, `domains/policy/min_payment.py` | — |
| Tools and escalation policy | `policies/tools.yaml`, `policies/escalation.yaml`, `domains/policy/tools_policy.py`, `domains/policy/escalation.py` | `StepUpRule` shape |
| In-memory confirmation store, fake OTP gate | `domains/policy/confirmation_memory.py`, `domains/identity/step_up_fake.py`, `core/config.py` | D2-K Protocols |
| FakeBank writes and overlay; address vault stub | `tools/fakebank.py`; `domains/safety/{__init__,vault}.py` | `BankWriteTools`, fixture |
| Templates | `conversation/templates.py` | `docs/brand.md` |
| NLU prompt v3 | `prompts/nlu@v3.md`, `nodes/understand.py` | — |
| Graph plumbing, queue, basics | `graph.py`, `nodes/{load_session,compose,unsupported,fallback,route,next_intent,smalltalk}.py` | templates |
| `card_info` B1 + `compose@v3` | `flows/card_info.py`, `nodes/compose.py`, `prompts/compose@v3.md` | formatting, policies, graph |
| Flow action helpers + test harness | `flows/actions.py` (new), `tests/conftest.py` | all B4 fakes, templates |
| `card_block`, `card_unlock`, `replacement` | `flows/{card_block,card_unlock,replacement}.py` | helpers, graph |
| Sandbox commands | `conversation/sandbox.py` | fakes, graph |

## Build order

1. **T1–T8 (done).** The fixture, read contracts, formatting, the three policies, the in-memory fakes, FakeBank writes and the templates.
2. **T9.** The graph: plumbing (segments, `finish`, resume) and routing (entry, queue, basics) in one pass over `graph.py` and `nodes/`. Every later flow plugs into its tables.
3. **T10.** The helpers and harness come before any write flow, and `card_block` is their first user. It comes before unlock, because unlock reuses the offer pause.
4. **T11.** `card_info` B1 plus both prompt bumps (`compose@v3`, `nlu@v3`). It needs formatting, policies, templates and the queue routing of `balance_due`, and comes after T10 because its "block then balance" test needs both `card_block` and `make_session`.
5. **T12.** `card_unlock` reuses T10's helpers and offer pause.
6. **T13.** The sandbox and its demo personas, once block and unlock work, so the end-of-day demo runs without replacement.
7. **T14.** Replacement. **This is the cut line**: it can move to D3 morning with nothing before it changing.
8. **T15.** The docs record the final shapes.
9. **T16.** The B6 wireframes, last. This is a human task.

## Touch map

| File | New/Mod | Change |
|---|---|---|
| `backend/tests/fixtures/fakebank/{customers,products}.csv`, `README.md` | Mod | + inactive customer, + AR credit card with dpd 30 |
| `backend/tests/fixtures/fakebank/daily_exchange_rates.csv` | New | invented USD→MXN rows |
| `backend/app/domains/localization/schemas.py` | New | `FxRate` |
| `backend/app/domains/localization/{__init__,format}.py` | Mod | estimate, tz, time, queue label, days label |
| `backend/app/domains/customers/schemas.py` | Mod | `+ city` |
| `backend/app/domains/conversation/tools/bank.py` | Mod | `get_fx_rate` |
| `backend/app/domains/conversation/tools/fakebank.py` | Mod | `get_fx_rate`, `city`, `FakeBankOverlay`, `FakeBankWrites`, overlay-aware reads, factory pair |
| `backend/app/domains/policy/{min_payment,tools_policy,escalation,confirmation_memory}.py` | New | loaders, formula, in-memory store |
| `backend/app/domains/identity/step_up_fake.py` | New | `FakeStepUpGate` |
| `backend/app/domains/safety/{__init__,vault}.py` | New | `AddressVault`, `InMemoryAddressVault` |
| `backend/app/core/config.py`, `.env.example` | Mod | `DEMO_OTP_CODE` |
| `policies/{min_payment,tools,escalation}.yaml` | New | v1, `provenance` header |
| `backend/app/domains/conversation/templates.py` | Mod | 18 new kinds (17 from the spec + `replacement_declined`) |
| `backend/app/domains/conversation/prompts/{nlu@v3,compose@v3}.md` | New | prompt bumps |
| `backend/app/domains/conversation/graph.py` | Mod | channels, entry, dispatch, `run_turn(confirmation, resume)`, `DebugInfo` |
| `backend/app/domains/conversation/nodes/{load_session,compose,unsupported,fallback,route,understand,__init__}.py` | Mod | segments, routing, v3 |
| `backend/app/domains/conversation/nodes/{next_intent,smalltalk}.py` | New | queue, finish, basics |
| `backend/app/domains/conversation/flows/card_info.py` | Mod | B1 |
| `backend/app/domains/conversation/flows/{actions,card_block,card_unlock,replacement}.py` | New | B5 |
| `backend/app/domains/conversation/sandbox.py` | Mod | recorder, write wiring, `/confirm` `/cancel` `/otp`, debug line |
| `backend/tests/conftest.py` | Mod | `make_session` harness |
| `backend/tests/unit/test_{format,min_payment,r2_confirmation_store,fakebank_writes,conversation_basics,card_info_flows,block_flows,r3_flows}.py` | New | Test list |
| `backend/tests/unit/test_r1_fakebank.py` | Mod | + `test_writes_refuse_foreign_cards` |
| `backend/tests/unit/test_sandbox_conversations.py` | Mod | one route assertion (`smalltalk`) |
| `docs/diagrams/turn-graph-v0.mmd` | Mod | regenerated |
| `eval/personas.yaml` | Mod | + bank-side and inactive personas |
| `docs/solution-docs/{04-contracts,02-conversation-design}.md`, `docs/specs/d2-b-card-info-block.md` | Mod | D20 + P1–P6 amendment |
| `docs/wireframes/` | New (optional) | B6 photos |

## Risks and mitigations

- **`action_unverified` had no queue in the spec's `escalation.yaml` v1.** The D11 handoff placeholder needs a `{queue_label}`, and policy can't live in code (R8). *Mitigation (P7):* T5 adds `action_queues: {action_unverified: atencion}`, the T10 `execute` helper reads it through `escalation.py`, and T15 records the spec amendment.
- **An LLM node gains a path to write tools (R6).** *Mitigation:* every write-side call lives in `flows/actions.py` or the flow modules, which never import `app.core.llm`. `enqueue` is in `nodes/next_intent.py`, which imports no LLM. Every flow task's Verify runs the R6 scan and the success-criterion-6 grep.
- **"Done" said on an unverified or failed write (R3).** *Mitigation:* the single `execute` helper in T10 maps `verified=True` to the done template. `verified=False`, **or any exception other than `ConfirmationRequired`**, maps to the handoff placeholder with `action_unverified`: a failed call may or may not have written, so it is never reported as done or as "no change". `ConfirmationRequired` maps to cancel + `action_cancelled`. T10's R3 test proves it.
- **The raw address leaks into state, plan args, facts or `ui` (R5).** *Mitigation:* the address turn skips `understand`. The flow reads `user_text` once, calls `vault.put_address`, and stores only `⟨ADDR_n⟩`. T14's test asserts the raw string is absent from `PlanStep.args`, `facts`, `ui`, `slots` and all `llm.calls`. The known gap that the `user_text` channel is checkpointed stays open, and is the accepted R5 gap assigned to D5-A.
- **`customer_id` taken from anywhere but the session (R1).** *Mitigation:* `FakeBankWrites` is bound to `ctx`, and every write and `get_block_origin` runs `WHERE product_id = ? AND customer_id = ?` before touching the overlay. A miss runs the existing probe, `AccessDenied` or `NotFound`. T7's R1 test asserts the overlay is unchanged after a refused call.
- **Policy creeps into code (R8).** *Mitigation:* step-up comes from `tools.yaml`. The ADR-021 statuses, allowed actions and queues come from `escalation.yaml`. Percent, floors and due day come from `min_payment.yaml`. Each loader fails when `provenance` is missing (T5 test).
- **The graph restructure breaks existing replies or the diagram test.** *Mitigation:* T9 keeps every existing reply byte-identical, and its Verify runs every existing conversation test. Each topology task regenerates the `.mmd` and runs `test_graph.py`.
- **The Streamlit page breaks.** *Mitigation:* T13 keeps `build_sandbox_session`'s signature and 3-tuple, and adds a private `_build_session` for the CLI.
- **A token confirms the wrong plan after a topic switch.** *Mitigation:* P1 in `enqueue` cancels the open token. Flows check `confirmation.token_id == state["confirmation_token_id"]`. A mismatch executes nothing and replies `nothing_pending`.
- **Replacement slips to D3.** *Mitigation:* T14 is self-contained: one flow module, its `_FLOW_NODES` and `_INTENT_NODES` entries, and two tests. With it absent, `offer_replacement` (whose `pending.flow` is `"replacement"`) routes to `unsupported`, and no earlier test depends on it.
- **The fixture drifts from the pinned R1 expectations.** *Mitigation:* T1 only adds customers.

## Tests

| Test | Task |
|---|---|
| `test_format.py::test_money_dates_masks_three_countries` | T3 |
| `test_min_payment.py::test_floor_percent_due_date` | T4 |
| `test_r2_confirmation_store.py::test_tools_yaml_step_up_rule` | T5 |
| `test_r2_confirmation_store.py::test_memory_store_enforces_plan_semantics` | T6 |
| `test_r1_fakebank.py::test_writes_refuse_foreign_cards` | T7 |
| `test_fakebank_writes.py::test_writes_read_back_and_block_origin` | T7 |
| `test_conversation_basics.py::test_greeting_thanks_bare_yes_no` | T9 |
| `test_block_flows.py::test_es_lock_clarify_confirm_readback` | T10 |
| `test_block_flows.py::test_pt_block_by_button_offers_replacement` | T10 |
| `test_block_flows.py::test_es_deny_cancels_plan` | T10 |
| `test_r3_flows.py::test_unverified_write_never_says_done` | T10 |
| `test_card_info_flows.py::test_credit_balance_due[es,pt]` | T11 |
| `test_card_info_flows.py::test_debit_gets_credit_only[es,pt]` | T11 |
| `test_card_info_flows.py::test_inactive_customer_read_only[es,pt]` | T11 |
| `test_conversation_basics.py::test_block_then_balance_in_order` | T11 |
| `test_block_flows.py::test_pt_bank_side_unlock_hands_off` | T12 |
| `test_block_flows.py::test_es_unlock_own_lock_needs_otp` | T12 |
| `test_block_flows.py::test_es_lost_card_block_replacement_tracking` | T14 |
| `test_block_flows.py::test_pt_new_address_needs_otp_and_is_vaulted` | T14 |
| `test_graph.py::test_graph_compiles_and_diagram_is_current` (existing) | T9, T10, T11, T12, T14 |
| `test_r6_no_write_tools_in_llm_nodes.py` (existing) | T9, T10, T11, T12, T14 |

Where each success criterion is met:
- **Criterion 1** (`make check`): the verifier.
- **Criterion 2** (the Test list): the tasks above.
- **Criterion 3** (sandbox step 5): T13 (sandbox + personas) + T14, manual check.
- **Criterion 4** (sandbox step 2): T11 + T13 (sandbox + personas), manual check.
- **Criterion 5** (YAML headers): T4 + T5.
- **Criterion 6** (no LLM import in flows): the R6 scan and grep in T10, T11, T12 and T14.
- **Criterion 7** (docs and `.env.example`): T15 and T6.
- **Criterion 8** (wireframes, review, merge): T16 and the PR.

## Tasks

- [x] T1: Fixture rows for inactive, past-due and FX cases
  - Depends on: nothing
  - Read exactly these: `backend/tests/fixtures/fakebank/README.md`; the header lines of `backend/tests/fixtures/fakebank/{customers,products}.csv`; `data/daily_exchange_rates.csv` header only (`head -3`, never copy rows)
  - Acceptance:
    - Append to `customers.csv` (UTF-8 BOM, CRLF, invented values in the file's existing style):
      - `CLI-TFINACT00004`: Colombia, city `Medellin`, `customer_status=Inactive`, first name `Prueba`.
      - `CLI-TFPASTD00005`: Argentina, city `Cordoba`, Active.
    - Append to `products.csv`:
      - `PRD-TFI4CRED0001`: owner `CLI-TFINACT00004`, `Tarjeta Crédito`, COP, Active, number `0000000000004444`, balance `500000`, limit `2000000`, dpd `0`, expiry `2028-01-31`.
      - `PRD-TFP5CRED0001`: owner `CLI-TFPASTD00005`, `Tarjeta Crédito`, ARS, Active, number `0000000000005555`, balance `123456.50`, limit `900000.00`, dpd `30`, expiry `2027-05-31`.
    - New `daily_exchange_rates.csv`, same header as `data/`, with invented rows:
      - `2026-03-11,USD,MXN,17.100000,…`
      - `2026-03-12,USD,MXN,17.400000,…` (the latest)
      - one `2026-03-12,MXN,USD,0.057471,…`
    - README lists the new customers and the FX file.
    - Existing customers are untouched.
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_fakebank.py tests/unit/test_card_select.py tests/unit/test_sandbox_conversations.py tests/unit/test_graph.py -q`
  - Files: `backend/tests/fixtures/fakebank/customers.csv`, `products.csv`, `daily_exchange_rates.csv` (new), `README.md`

- [x] T2: Read-side contract: `FxRate`, `get_fx_rate`, `CustomerProfile.city`
  - Depends on: T1 (fixture FX file and new customers)
  - Read exactly these: spec §"Contracts" (`FxRate`, `BankReadTools`, D3, D4); `backend/app/domains/conversation/tools/fakebank.py`; `backend/app/domains/conversation/tools/bank.py`
  - Acceptance:
    - `localization/schemas.py` (new) defines a frozen `FxRate{source, target, rate: Decimal, as_of: date}`, exported from `localization/__init__.py`.
    - `BankReadTools` gains `get_fx_rate(source, target) -> FxRate`, with the comment `# Registry name: reference.get_fx_rate. May raise: NotFound, ToolUnavailable.`
    - `FakeBank.get_fx_rate` returns the latest row for the pair from `<data_dir>/daily_exchange_rates.csv`. It has no customer filter (reference data, D3), uses bound parameters, and raises `NotFound` when the pair has no rows.
    - `CustomerProfile` gains `city: str | None = None`, and `FakeBank.get_profile` fills it.
    - `sandbox._RecordingBankTools` gains a recording `get_fx_rate`.
  - Verify: `cd backend && uv run python -c "import asyncio,uuid;from pathlib import Path;from app.domains.conversation.tools.context import ToolContext;from app.domains.conversation.tools.fakebank import FakeBank;b=FakeBank(ToolContext(customer_id='CLI-TFMULTI00001',conversation_id=uuid.uuid4(),actor='customer',trace_id='t',policy_version='u'),Path('tests/fixtures/fakebank'));r=asyncio.run(b.get_fx_rate('USD','MXN'));p=asyncio.run(b.get_profile());assert str(r.as_of)=='2026-03-12' and p.city=='Ciudad de Mexico',(r,p)" && uv run pytest tests/unit/test_r1_fakebank.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/localization app/domains/customers app/domains/conversation/tools app/domains/conversation/sandbox.py && uv run ruff format --check app/domains/localization app/domains/customers app/domains/conversation/tools app/domains/conversation/sandbox.py && uv run mypy app/domains/localization app/domains/customers app/domains/conversation/tools app/domains/conversation/sandbox.py`
  - Files: `backend/app/domains/localization/schemas.py` (new), `backend/app/domains/localization/__init__.py`, `backend/app/domains/conversation/tools/bank.py`, `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/customers/schemas.py`, `backend/app/domains/conversation/sandbox.py`

- [x] T3: B2 formatting: MXN estimate, `BANK_TZ`, time, queue and days labels
  - Depends on: T2 (`FxRate` in `app.domains.localization.schemas`)
  - Read exactly these: `backend/app/domains/localization/format.py`; spec D17, D18 and the `test_format.py` row; `docs/solution-docs/03-data-architecture.md` §5 (the `BANK_TZ` zones)
  - Acceptance:
    - Add these to `format.py` and export them:
      - `BANK_TZ: dict[Country, ZoneInfo]`: MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`.
      - `local_today(country, now: datetime | None = None) -> date`.
      - `format_time(at: datetime, country) -> "HH:MM"` in `BANK_TZ`.
      - `mxn_estimate(amount_usd, fx: FxRate, language) -> str`, giving ES `(≈ MXN $21,480.30, tipo de cambio del 12/03/2026)` and PT `(≈ MXN $…, câmbio de 12/03/2026)`. It rounds to 2 decimals and uses the MX pattern.
      - `queue_label(queue, language)` for `atencion`/`cobranza`/`fraudes`. Display labels only: ES `Atención al cliente`/`Cobranza`/`Fraudes`, PT `Atendimento`/`Cobrança`/`Fraudes`.
      - `format_days(n, language)`: `30 días` / `30 dias`.
    - `format.py` still imports no other domain. It may import `app.domains.localization.schemas`.
    - New `test_format.py::test_money_dates_masks_three_countries` covers:
      - MX `US$1,234.50` + the estimate in ES and PT
      - CO `COP $1.234.567`
      - AR `ARS $ 1.234,50`
      - `format_date` day-first
      - `mask_card` → `•••• 1234`
      - `format_time` of a UTC datetime in MX
  - Verify: `cd backend && uv run pytest tests/unit/test_format.py -q && uv run ruff check app/domains/localization tests/unit/test_format.py && uv run ruff format --check app/domains/localization tests/unit/test_format.py && uv run mypy app/domains/localization`
  - Files: `backend/app/domains/localization/format.py`, `backend/app/domains/localization/__init__.py`, `backend/tests/unit/test_format.py` (new)

- [x] T4: `policies/min_payment.yaml` and its formula
  - Depends on: nothing
  - Read exactly these: spec D5 and §"Policies"; this plan §"Human decisions" P5 and P6; `backend/app/domains/conversation/flows/card_select.py` (loader pattern only, lines 1–90)
  - Acceptance:
    - `policies/min_payment.yaml` starts with `provenance: team-generated-synthetic`, `version: 1`, then `min_payment: {percent_of_balance: "0.05", floors: {USD: "10", COP: "40000", ARS: "5000"}}` and `due_date: {due_day_of_month: 10}`.
    - `app/domains/policy/min_payment.py` provides:
      - A frozen, `extra="forbid"` `MinPaymentPolicy` with required `provenance`/`version`.
      - `load_min_payment_policy(path=<repo>/policies/min_payment.yaml)`.
      - `min_payment(balance, currency, policy) -> Decimal`, which is `min(max(pct×balance, floor), balance)`, `0` when balance ≤ 0, and `KeyError` for a currency with no floor.
      - `next_due_date(today, policy) -> date`: on or after today, rolling over the month and the year.
    - It imports only the stdlib, pydantic and yaml.
    - `test_min_payment.py::test_floor_percent_due_date` covers:
      - the percent wins (USD 1234.50 → 61.73 or 61.72; pin the rounding to 2 decimals, `ROUND_HALF_UP`)
      - the floor wins (COP, ARS)
      - the cap at the balance (USD 5 → 5)
      - balance ≤ 0 → 0
      - due date on the 10th → same day; the 11th → next month; 11 Dec → 10 Jan
      - no overdue term: dpd has no input
  - Verify: `cd backend && uv run pytest tests/unit/test_min_payment.py -q && uv run ruff check app/domains/policy tests/unit/test_min_payment.py && uv run ruff format --check app/domains/policy tests/unit/test_min_payment.py && uv run mypy app/domains/policy`
  - Files: `policies/min_payment.yaml` (new), `backend/app/domains/policy/min_payment.py` (new), `backend/tests/unit/test_min_payment.py` (new)

- [x] T5: `policies/tools.yaml` + `escalation.yaml` and their loaders
  - Depends on: nothing
  - Read exactly these: spec D2, D8, D10 and §"Policies", plus this plan §"Human decisions" P7; `backend/app/domains/conversation/tools/executor.py` (`StepUpRule`); `backend/app/domains/conversation/flows/card_select.py` (loader pattern, lines 1–90)
  - Acceptance:
    - `policies/tools.yaml` is exactly the spec's block, with the header `provenance: team-generated-synthetic`, `version: 1`.
    - `policies/escalation.yaml` has the header plus `customer_not_active` and `bank_side_queues` as in the spec, plus `action_queues: {action_unverified: atencion}` (P7). `EscalationPolicy` models all three sections.
    - `policy/tools_policy.py` provides:
      - `ToolsPolicy`, where `step_up` is `Literal["never", "always", "when_address_changed"]`
      - `load_tools_policy(path=…)`
      - `step_up_rule(policy) -> Callable[[str, Mapping[str, str | int | bool | None]], bool]`: `when_address_changed` means `args.get("address_ref") != "on_file"`, and an unknown tool raises `KeyError`
    - `policy/escalation.py` provides `EscalationPolicy` and `load_escalation_policy(path=…)`.
    - Both loaders fail with a `ValidationError` when `provenance` is missing.
    - Neither module imports `app.domains.conversation`: it redeclares the rule's callable type structurally.
    - New `tests/unit/test_r2_confirmation_store.py` contains `test_tools_yaml_step_up_rule`:
      - unlock → always
      - replacement → `on_file` False, `⟨ADDR_1⟩` True
      - lock/block → never
      - a `tmp_path` copy with no `provenance` fails to load, for both files
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmation_store.py -q && head -1 ../policies/tools.yaml ../policies/escalation.yaml && uv run ruff check app/domains/policy tests/unit/test_r2_confirmation_store.py && uv run ruff format --check app/domains/policy tests/unit/test_r2_confirmation_store.py && uv run mypy app/domains/policy && uv run lint-imports`
  - Files: `policies/tools.yaml` (new), `policies/escalation.yaml` (new), `backend/app/domains/policy/tools_policy.py` (new), `backend/app/domains/policy/escalation.py` (new), `backend/tests/unit/test_r2_confirmation_store.py` (new)

- [x] T6: `InMemoryConfirmationStore`, `FakeStepUpGate`, `DEMO_OTP_CODE`
  - Depends on: T5 (creates `test_r2_confirmation_store.py`, which this task appends to)
  - Read exactly these: `backend/app/domains/policy/confirmation.py`; `backend/app/domains/identity/step_up.py`; `docs/solution-docs/04-contracts.md` §7
  - Acceptance:
    - `policy/confirmation_memory.py`: `InMemoryConfirmationStore(customer_id, conversation_id, *, clock: Callable[[], datetime] = <utc now>)` implements `ConfirmationStore`:
      - `issue`: `secrets.token_urlsafe` id, a 5-minute TTL, and the plan bound to the owner.
      - `consume_step`: raises `ConfirmationRequired("unknown_or_expired")` when absent or expired, `ConfirmationRequired("wrong_owner")` when the store instance's owner differs from the plan's, and `ConfirmationRequired("step_mismatch")` on a tool or `args_hash` mismatch at the cursor. It advances the cursor, returns the index, and deletes the plan after the last step.
      - `cancel`: idempotent.
      - Plans live in a dict that can be shared, so a test can make a second store with a different owner see the same plan (e.g. a `plans: dict | None = None` kwarg).
    - `identity/step_up_fake.py`: `FakeStepUpGate(code)` with `async is_step_up_valid()` and a sync `verify(code) -> bool`. An empty configured code never verifies. Once verified, it stays valid.
    - `Settings.demo_otp_code: str = ""`.
    - `.env.example` gets a `# --- Step-up (ADR-008) ---` block with `DEMO_OTP_CODE=` left empty and a comment: the value is never committed and is shared with judges by email.
    - Append `test_memory_store_enforces_plan_semantics` to `test_r2_confirmation_store.py`. It covers the reused token, the expired token (injected clock), the wrong tool/args, the reordered two-step plan, another customer, another conversation, and the key gone after the last step.
  - Verify: `cd backend && uv run pytest tests/unit/test_r2_confirmation_store.py -q && grep -n "DEMO_OTP_CODE=" ../.env.example && uv run ruff check app/domains/policy app/domains/identity app/core/config.py tests/unit/test_r2_confirmation_store.py && uv run ruff format --check app/domains/policy app/domains/identity app/core/config.py tests/unit/test_r2_confirmation_store.py && uv run mypy app/domains/policy app/domains/identity app/core/config.py && uv run lint-imports`
  - Files: `backend/app/domains/policy/confirmation_memory.py` (new), `backend/app/domains/identity/step_up_fake.py` (new), `backend/app/core/config.py`, `.env.example`, `backend/tests/unit/test_r2_confirmation_store.py`

- [x] T7: FakeBank writes + overlay, block origin, address vault stub
  - Depends on: T1 (the new customers `CLI-TFINACT00004` Inactive and `CLI-TFPASTD00005` with dpd 30 on `PRD-TFP5CRED0001`), T2 (`get_profile` reads `customer_status`)
  - Read exactly these: `backend/app/domains/conversation/tools/fakebank.py`; `backend/app/domains/conversation/tools/write.py`; spec D4, D7, D8 and §"Contracts" (read-back keys, `vault.py`, `fakebank.py`)
  - Acceptance:
    - `FakeBankOverlay` (a plain per-session in-memory object) holds `locked: set[card_id]`, `blocked: set[card_id]` and `replacements: dict[card_id, tracking_id]`.
    - `FakeBank(ctx, data_dir, overlay=None)`: `list_cards` and `get_card_details` apply the overlay. `locked` comes from `overlay.locked`. A blocked card's status becomes `Blocked`.
    - `FakeBankWrites(ctx, data_dir, overlay)` implements `BankWriteTools`:
      - It first runs an ownership query (`WHERE product_id = ? AND customer_id = ?` on a card type), then uses the same probe as reads: `AccessDenied` for another customer's card, `NotFound` for an unknown one. Nothing is mutated before ownership passes.
      - It writes, then re-reads the overlay to build `readback` with the spec's keys and `at = datetime.now(UTC)`, and sets `verified=True` only when the re-read matches.
      - `order_replacement` sets `tracking_id = "RPL-" + uppercase 8 hex`, readback `{"status": "ordered", "at": …}`, and accepts `"on_file"` or a `⟨ADDR_n⟩` token.
      - `get_block_origin` implements D8 in order: overlay block → `customer_block`; overlay lock → `customer_lock`; then bank-side, where customer not `Active` → `customer_status`, dpd > 0 → `past_due`, dataset `Blocked`/`Suspended` → `bank_status`; otherwise `none`.
    - `make_fakebank_factory(data_dir)` now returns `(BankToolsFactory, BankWriteToolsFactory)` sharing one new overlay. Callers make one pair per session.
    - `domains/safety/__init__.py` + `vault.py`: an `AddressVault` Protocol and `InMemoryAddressVault` (`put_address(raw) -> "⟨ADDR_n⟩"`, n from 1, raw kept only inside the object). Neither imports `conversation`.
    - Append `test_writes_refuse_foreign_cards` to `test_r1_fakebank.py`: each of the 4 writes and `get_block_origin` on `PRD-TFS2CRED0001` from `CLI-TFMULTI00001` → `AccessDenied`, and the overlay sets/dict are still empty.
    - New `test_fakebank_writes.py::test_writes_read_back_and_block_origin`:
      - the four writes verified with their keys, and `list_cards` reflects lock and block
      - origins: `customer_lock`, `customer_block`, `bank_side/past_due` (`PRD-TFP5CRED0001`), `bank_side/bank_status` (`PRD-TFB3DEBT0001`), `bank_side/customer_status` (`PRD-TFI4CRED0001`), and `none` (`PRD-TFS2CRED0001`)
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/tools app/domains/safety tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py && uv run ruff format --check app/domains/conversation/tools app/domains/safety tests/unit/test_r1_fakebank.py tests/unit/test_fakebank_writes.py && uv run mypy app/domains/conversation/tools app/domains/safety && uv run lint-imports`
  - Files: `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/safety/__init__.py` (new), `backend/app/domains/safety/vault.py` (new), `backend/tests/unit/test_r1_fakebank.py`, `backend/tests/unit/test_fakebank_writes.py` (new)

- [x] T8: ES/PT templates for B3/B5 in Cardy's voice
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/templates.py`; `docs/brand.md`; spec §"New templates", D9, D11–D14, D17; this plan §"Human decisions" P4
  - Acceptance:
    - `TemplateKind` and `_TEMPLATES` gain, in ES and PT: `thanks_close`, `nothing_pending`, `clarify_lock_vs_block`, `already_in_state`, `action_cancelled`, `action_done_noref`, `otp_required`, `address_confirm`, `address_ask`, `not_blocked`, `block_permanent_no_undo`, `offer_replacement`, `replacement_declined`, `replacement_not_eligible`, `handoff_placeholder`, `credit_only`, `synthetic_footnote` and `read_only_note`.
    - Placeholders, filled in code:
      - `action_done_noref`: `{card_last4}`, `{result}`, `{time}`
      - `already_in_state`: `{card_last4}`, `{state}`
      - `address_confirm`: `{address_masked}`
      - `handoff_placeholder`: `{queue_label}`
      - `offer_replacement` and `block_permanent_no_undo`: `{card_last4}`
    - `action_cancelled` says nothing was executed. `replacement_declined` doesn't claim that no change was made. `handoff_placeholder` says a person from `{queue_label}` will review it, without claiming a transfer happened (D9). `synthetic_footnote` labels the minimum payment and due date as a synthetic Swip policy.
    - No template contains a digit. Existing templates are unchanged.
  - Verify: `cd backend && uv run python -c "import typing;from app.domains.conversation import templates as t;ks=typing.get_args(t.TemplateKind);assert all(not any(c.isdigit() for c in t.get_template(k,l)) for k in ks for l in ('es','pt'));assert 'replacement_declined' in ks and len(ks)==32,len(ks)" && uv run pytest tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/templates.py && uv run ruff format --check app/domains/conversation/templates.py && uv run mypy app/domains/conversation/templates.py`
  - Files: `backend/app/domains/conversation/templates.py`

- [ ] T9: Turn graph: I/O plumbing, entry routing, intent queue and conversation basics (B3)
  - Depends on: T8 (the `thanks_close`, `nothing_pending` and `otp_required` templates). Otherwise the D2-K graph on `develop`.
  - Read exactly these: this plan §"Components" → "Graph shape" (all of it) and §"Human decisions" P1, P3; `backend/app/domains/conversation/graph.py`; `backend/app/domains/conversation/nodes/route.py`; `backend/app/domains/conversation/state.py` (the `RESET_FACTS` pattern only)
  - Acceptance:
    - *Plumbing:*
      - `TurnInput` and `GraphState` gain `resume: NotRequired[Literal["step_up"] | None]`.
      - `GraphState` gains a `segments` channel whose reducer appends or resets on a `RESET_SEGMENTS` marker (`_SegmentsReset` subclass, same pattern as `RESET_FACTS`).
      - `load_session` also returns `"segments": RESET_SEGMENTS`.
      - `compose`, `unsupported` and `fallback` return `{"segments": [text]}` instead of `reply`.
      - A `finish` node in new `nodes/next_intent.py` sets `reply = "\n\n".join(segments)`, and `finish` goes to `END`.
      - `run_turn(graph, text, *, config, confirmation=None, resume=None)` streams both inputs explicitly.
      - `DebugInfo` gains `pending: str | None` (`"<flow>.<awaiting_slot>"` read from the final state via `graph.aget_state(config)`) and `ui: list[str]` (the kinds of the last `ui` value seen).
    - *Routing:*
      - Implement `_entry`, the new `route`, `enqueue`, `_dispatch`, `next_intent`, `_after_flow` and `_after_segment` exactly as "Graph shape" says.
      - Hold the mapping tables `_INTENT_NODES` and `_FLOW_NODES` in `graph.py`, starting with `card_info` and `unsupported` only.
      - `card_info` goes through `_after_flow`. `balance_due` dispatches to `card_info`; `card_info`'s own B1 behaviour is T11.
      - `enqueue` applies P1, calling `config["configurable"].get("bank_write_tools")`'s `cancel_plan` only if both it and a token exist. Put it in `nodes/next_intent.py`, which must not import `app.core.llm`.
      - `_BRANCH_NODES` gains `smalltalk`. The debug `route` is the first branch node seen, never `enqueue`, `next_intent` or `finish`.
    - *Basics:* new `nodes/smalltalk.py`:
      - a lone greeting → `greeting_named`/`greeting` (moved from `unsupported`)
      - `thanks_close` → `thanks_close`
      - `affirm`/`deny` with nothing pending → `nothing_pending`
      - an entry-level `confirmation` with no matching pause, or a stale token → `nothing_pending`
      - `resume="step_up"` with no `otp` pause → `otp_required`
      - management intents while a pause is waiting on something else → `otp_required` when the pause is `otp`, otherwise `nothing_pending`, with `pending` kept
      - no LLM call beyond `understand`
    - *Tests:*
      - Every existing reply assertion is unchanged. In `test_sandbox_conversations.py::test_es_greeting_gets_cardy_template`, change only `debug.route == "unsupported"` to `"smalltalk"`.
      - New `test_conversation_basics.py::test_greeting_thanks_bare_yes_no`, on `CLI-TFMULTI00001` with a `ScriptedLLM` that has only `nlu` outputs: greeting, thanks, bare "sí" and bare "no" each get their template, and no `compose` call is made.
    - The diagram is regenerated.
  - Verify: `cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd && uv run pytest tests/unit/test_conversation_basics.py tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py tests/unit/test_compose.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation tests/unit/test_conversation_basics.py tests/unit/test_sandbox_conversations.py && uv run ruff format --check app/domains/conversation tests/unit/test_conversation_basics.py tests/unit/test_sandbox_conversations.py && uv run mypy app/domains/conversation`
  - Files: `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/{load_session,compose,unsupported,fallback,route,__init__}.py`, `backend/app/domains/conversation/nodes/{next_intent,smalltalk}.py` (new), `backend/tests/unit/test_conversation_basics.py` (new), `backend/tests/unit/test_sandbox_conversations.py`, `docs/diagrams/turn-graph-v0.mmd`

- [ ] T10: Flow action helpers, test harness and the `card_block` flow
  - Depends on:
    - T3: `format_time`, `queue_label`
    - T5: `load_tools_policy`, `step_up_rule`, `load_escalation_policy` (`EscalationPolicy.action_queues.action_unverified` = `atencion`, P7)
    - T6: `app.domains.policy.confirmation_memory.InMemoryConfirmationStore`, `app.domains.identity.step_up_fake.FakeStepUpGate` (import the module paths; they are not re-exported)
    - T7: `FakeBankWrites(ctx, data_dir, overlay)`, `FakeBankOverlay`, `make_fakebank_factory` returns a pair, `app.domains.safety.vault.InMemoryAddressVault`
    - T8: the templates
    - T9: the `segments` channel, and the `_INTENT_NODES`, `_FLOW_NODES` and `_BRANCH_NODES` tables in `graph.py`
  - Read exactly these: `backend/app/domains/conversation/tools/executor.py`; `backend/app/domains/conversation/ui.py`; `backend/app/domains/conversation/flows/card_info.py` (how `select_card` is driven); spec D11, D14, D15, D17 and the `test_block_flows.py`/`test_r3_flows.py` rows; `docs/solution-docs/02-conversation-design.md` §4.6
  - Acceptance:
    - *Helpers.* New `flows/actions.py`. It never imports `app.core.llm` and gets the write tools only from `config["configurable"]["bank_write_tools"]`. It provides:
      - `fill(template, **values)`, which uses `str.replace` on `{key}`.
      - `start_plan(state, config, *, flow, tool, args, summary_key, view_facts, confirm_values) -> dict`. It calls `issue_plan([PlanStep])` and returns `confirmation_token_id`, `pending{flow, node:"confirm", awaiting_slot:"confirmation"}`, `ui:[ConfirmEvent]` and the `segments` `action_confirm` filled.
      - `decision(state) -> "confirm" | "cancel" | "stale" | None`. It reads the button `confirmation` (token must equal `confirmation_token_id`, else `"stale"`) or NLU `affirm`/`deny`.
      - `cancel(state, config)`: `cancel_plan`, clear `pending`/token, `action_cancelled`.
      - `execute(state, config, call, *, done_template, done_values, card_last4)`:
        - `verified=True` → append to `actions`, fill `action_done` or `action_done_noref`, `{time}` = `format_time(readback["at"], country)`, clear `pending`/token.
        - `verified=False` or any exception except `ConfirmationRequired` → the handoff placeholder naming `load_escalation_policy().action_queues.action_unverified` (Atención, P7), with `escalation_reason="action_unverified"`.
        - `ConfirmationRequired` → `cancel`.
      - `handoff(queue, reason, language)` → the `handoff_placeholder` filled with `queue_label`, `escalation_reason=reason`, `pending=None`.
      - `otp_pause(flow, node, tool)` → `pending{…, awaiting_slot:"otp"}`, `ui:[OtpRequiredEvent]`, the `otp_required` segment.
    - *Harness.* `tests/conftest.py` gains `make_session(customer_id, fakebank_dir, llm, *, otp_code="0000", raw_writes=None, clock=None)`. It returns a dataclass with `graph`, `config` (`thread_id`, `session`, `bank_tools`, `bank_write_tools` = `ConfirmedWriteTools(raw_writes or FakeBankWrites, InMemoryConfirmationStore, FakeStepUpGate(otp_code), step_up_rule(load_tools_policy()))`, `vault`, `llm`), `gate`, `store` and `overlay`.
    - *Flow.* New `flows/card_block.py` (node `card_block`), staged on `pending.awaiting_slot`:
      1. `card_select` with the `card_status` policy (P2). `Ask` → `card_hint` pause + `card_options` fact (goes to compose).
      2. Missing `block_kind` (the NLU slot, or `state["slots"]`) → `clarify_lock_vs_block` segment, `awaiting_slot="block_kind"`, `clarification_failures += 1`. At the `card_select.yaml` limit the flow goes to `clarification_exhausted`.
      3. A card already `Blocked` or `Closed`, or already `locked` for a lock → `already_in_state`.
      4. `start_plan` (lock: `cards.lock_card {card_id}`; block: `cards.block_card {card_id, reason:"lost_or_stolen"}`).
      5. On `decision`:
         - confirm → `execute` with `action_done_noref`. After a verified block, also append `offer_replacement` and set `pending{flow:"replacement", node:"offer", awaiting_slot:"offer_replacement"}`.
         - cancel → `cancel`.
         - stale → `nothing_pending`.
    - Register `card_block` in the three tables and regenerate the diagram.
    - New `test_block_flows.py` with `test_es_lock_clarify_confirm_readback`, `test_pt_block_by_button_offers_replacement` and `test_es_deny_cancels_plan`, on `CLI-TFMULTI00001`/`CLI-TFSINGLE0002` via `make_session`.
    - New `test_r3_flows.py::test_unverified_write_never_says_done`: `raw_writes` is a stub whose `lock_card` returns `verified=False`. The reply has no `action_done*` text, `escalation_reason == "action_unverified"`, and the plan is cancelled: consuming the same token again raises `unknown_or_expired`.
  - Verify: `cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd && uv run pytest tests/unit/test_block_flows.py tests/unit/test_r3_flows.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_sandbox_conversations.py -q && ! grep -rn "import app.core.llm\|from app.core.llm" app/domains/conversation/flows && uv run ruff check app/domains/conversation tests/conftest.py tests/unit/test_block_flows.py tests/unit/test_r3_flows.py && uv run ruff format --check app/domains/conversation tests/conftest.py tests/unit/test_block_flows.py tests/unit/test_r3_flows.py && uv run mypy app/domains/conversation`
  - Files: `backend/app/domains/conversation/flows/{actions,card_block}.py` (new), `backend/app/domains/conversation/graph.py`, `docs/diagrams/turn-graph-v0.mmd`, `backend/tests/conftest.py`, `backend/tests/unit/{test_block_flows,test_r3_flows}.py` (new)

- [ ] T11: `card_info` B1 (`balance_due`, credit-only, read-only) + `compose@v3` + `nlu@v3` + "block then balance"
  - Depends on:
    - T2: `get_fx_rate`, `FxRate`
    - T3: `mxn_estimate`, `local_today`, `format_days`
    - T4: `load_min_payment_policy`, `min_payment` (caps at the balance before comparing percent vs floor), `next_due_date`
    - T5: `load_escalation_policy`, `.customer_not_active.statuses`
    - T8: `credit_only`, `synthetic_footnote`, `read_only_note`
    - T9: `balance_due` is dispatched to `card_info`, the head of `intent_queue` is the current intent, `_after_flow`, `enqueue`/`next_intent`
    - T10: `card_block` registered, `tests/conftest.py::make_session`
  - Read exactly these: `backend/app/domains/conversation/flows/card_info.py`; `backend/app/domains/conversation/nodes/compose.py`; `backend/app/domains/conversation/prompts/nlu@v2.md` and `backend/app/domains/conversation/nodes/understand.py` (for the NLU bump); spec D5, D10, D15, D18, D19, the three `test_card_info_flows.py` rows and the `test_block_then_balance_in_order` row
  - Acceptance:
    - `card_info` reads the current intent from `state["intent_queue"][0]`, falling back to `card_status` when the queue is empty.
    - For a credit card on `balance_due`, it adds these facts:
      - `current_balance`
      - `due_date`, via `next_due_date(local_today(country))`
      - `min_payment`
      - `available_credit`
      - `currency`
      - `payment_overdue` (the int bucket) when dpd > 0
      - `fx_rate` and `fx_as_of`, from `get_fx_rate("USD", "MXN")`, when the country is MX and the currency is USD. `NotFound` means no estimate.

      Each fact's `source` is `CardDetails.source`, or `policy:min_payment@v1` for the policy-derived facts.
    - For a debit card on `balance_due`, it appends the `credit_only` segment and emits only the non-money facts (mask, kind, status, expiry).
    - When the profile's `customer_status` is in `escalation.yaml`'s `customer_not_active.statuses`, it adds a `read_only_note` fact (value = the status string).
    - `compose`:
      - Uses `PromptRef("compose", 3)` and the new `prompts/compose@v3.md` (v2 plus the goals `balance_due` and `credit_only_offer`).
      - Picks the goal: `ask_which_card` when awaiting `card_hint`; otherwise `credit_only_offer` for a debit card on `balance_due`, `balance_due` on `balance_due`, else `card_status`.
      - Never offers `currency`, `fx_rate`, `fx_as_of` or `read_only_note` as placeholders.
      - Formats `current_balance`/`min_payment`/`credit_limit`/`available_credit` with `format_money`, followed by `" " + mxn_estimate(...)` when the FX facts are present.
      - Formats `due_date` with `format_date` and `payment_overdue` with `format_days`.
      - After the filled draft, appends the `synthetic_footnote` template when `min_payment` is present, and the `read_only_note` template when that fact is present.
    - `flows/card_info.py` does not import `app.core.llm`.
    - New `test_card_info_flows.py` with the three tests, each parametrized `es`/`pt`, on `CLI-TFMULTI00001`, `CLI-TFSINGLE0002`, `CLI-TFPASTD00005` (dpd) and `CLI-TFINACT00004`. They build their own config like `test_sandbox_conversations._config` (no write tools needed).
    - Append `test_conversation_basics.py::test_block_then_balance_in_order` on `CLI-TFMULTI00001` via `make_session`:
      - Turn 1: NLU `[card_block, balance_due]`, hint `credit`, no `block_kind` → the clarification segment only; the queue still holds `balance_due`.
      - Turn 2: NLU `block_kind=temporary_lock` → `action_confirm`.
      - Turn 3: button confirm → the reply is `action_done_noref` text, **then** the balance segment (compose scripted once), then the footnote, in that order; the final `intent_queue` is `[]`.

      Fix `nodes/next_intent.py`/`route.py` only if this test exposes a bug.
    - *NLU prompt (D19):*
      - New `prompts/nlu@v3.md` is a copy of v2 plus:
        - examples mapping "pausar", "bloquear temporalmente", "pausar o cartão" → `block_kind=temporary_lock`, and "la perdí", "me la robaron", "cancelarla", "perdi meu cartão" → `permanent_block`
        - `intents[]` in message order for "bloquea mi tarjeta y dime mi saldo" → `[card_block, balance_due]`
        - voseo ("desbloqueá", "¿me la podés pausar?")
        - "sí"/"no" → `affirm`/`deny` against a pending question, and "¿cuánto debo?" → `balance_due`
        - no digits of card numbers are echoed into slots except as `last4:`
      - `understand.py` uses `PromptRef("nlu", 3)`.
      - v1/v2 are untouched.
    - The existing `test_compose.py` and `test_sandbox_conversations.py` stay green.
  - Verify: `cd backend && uv run python -c "from app.core.llm import PromptRef;from app.domains.conversation.prompts import load_prompt;assert 'balance_due' in load_prompt(PromptRef('nlu',3))" && uv run pytest tests/unit/test_card_info_flows.py tests/unit/test_conversation_basics.py tests/unit/test_compose.py tests/unit/test_sandbox_conversations.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation tests/unit/test_card_info_flows.py tests/unit/test_conversation_basics.py && uv run ruff format --check app/domains/conversation tests/unit/test_card_info_flows.py tests/unit/test_conversation_basics.py && uv run mypy app/domains/conversation`
  - Files: `backend/app/domains/conversation/flows/card_info.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/prompts/{compose@v3,nlu@v3}.md` (new), `backend/app/domains/conversation/nodes/understand.py`, `backend/tests/unit/test_card_info_flows.py` (new), `backend/tests/unit/test_conversation_basics.py`; only if the queue test exposes a bug: `backend/app/domains/conversation/nodes/{next_intent,route}.py`

- [ ] T12: `card_unlock` flow (origin check, OTP resume, bank-side handoff)
  - Depends on:
    - T10: helpers (`otp_pause`, `handoff`, `start_plan`, `execute`), `make_session` (whose `gate.verify(code)` is used in the test), and the offer pause shape `pending{flow:"replacement", node:"offer", awaiting_slot:"offer_replacement"}`
    - T5: `escalation.yaml` (`customer_not_active`, `bank_side_queues`; an unverified unlock goes to `action_queues.action_unverified` = `atencion` through T10's `execute`, P7)
    - T9: the entry routing of `resume="step_up"`
  - Read exactly these: spec D1, D8, D10, D12 and the two unlock test rows; `docs/solution-docs/02-conversation-design.md` §4.7; `backend/app/domains/conversation/flows/card_block.py` (the analogue)
  - Acceptance:
    - New `flows/card_unlock.py` (node `card_unlock`):
      1. `card_select`.
      2. When `get_profile().customer_status` is in `customer_not_active.statuses` (unlock is not in `allowed`) → `handoff(customer_not_active.queue, "customer_not_active")`.
      3. Otherwise `get_block_origin`:
         - `customer_lock` → if `is_step_up_valid()`, `start_plan(cards.unlock_card)`; otherwise `otp_pause`. On the `resume` turn, a valid gate → `start_plan`; an invalid gate → `otp_required` again, nothing issued.
         - `customer_block` → `block_permanent_no_undo` + the offer pause.
         - `bank_side` → `handoff(bank_side_queues[reason], "bank_side_block")`, with no OTP and no write.
         - `none` → `not_blocked`.
      4. Confirm → `execute(unlock)` → `action_done_noref`.
    - Register `card_unlock` in the three tables and regenerate the diagram.
    - Append to `test_block_flows.py`:
      - `test_pt_bank_side_unlock_hands_off`: `CLI-TFPASTD00005` names Cobranza, and `CLI-TFBLOCKD0003` names Fraudes. No write is called, and there is no `otp_required`.
      - `test_es_unlock_own_lock_needs_otp`: lock first through the overlay. Then: `otp_required` → a resume turn with the gate invalid executes nothing → `gate.verify(code)` → a resume turn gives `action_confirm` → confirm gives `action_done_noref`. `llm.calls` gains no `nlu` call on the resume and confirm turns.
  - Verify: `cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd && uv run pytest tests/unit/test_block_flows.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && ! grep -rn "import app.core.llm\|from app.core.llm" app/domains/conversation/flows && uv run ruff check app/domains/conversation tests/unit/test_block_flows.py && uv run ruff format --check app/domains/conversation tests/unit/test_block_flows.py && uv run mypy app/domains/conversation`
  - Files: `backend/app/domains/conversation/flows/card_unlock.py` (new), `backend/app/domains/conversation/graph.py`, `docs/diagrams/turn-graph-v0.mmd`, `backend/tests/unit/test_block_flows.py`

- [ ] T13: Sandbox: write wiring, `/confirm` `/cancel` `/otp`, debug `pending` and writes + demo personas
  - Depends on:
    - T7: `make_fakebank_factory` returns `(read_factory, write_factory)`, `InMemoryAddressVault`; `FakeBankWrites.get_block_origin` over `data/` (to check the personas)
    - T6: `InMemoryConfirmationStore`, `FakeStepUpGate`, `Settings.demo_otp_code`
    - T5: `load_tools_policy`, `step_up_rule`
    - T9: `run_turn(confirmation, resume)`, `DebugInfo.pending`/`ui`
  - Read exactly these: `backend/app/domains/conversation/sandbox.py`; `backend/scripts/sandbox_ui.py` (lines 90–115 only; it must keep working, so don't edit it); spec D1, D14 and success criteria 3–4; `eval/personas.yaml` (header comment and schema)
  - Acceptance:
    - Add a private `_build_session(customer_id, data_dir) -> _SandboxSession(graph, config, bank_tools, gate)`. The config gains `bank_write_tools` (a `ConfirmedWriteTools` over a `_RecordingWriteTools` that appends the write method names to the same `calls` list) and `vault`.
    - `build_sandbox_session` keeps its signature and returns the same 3-tuple from it.
    - In the CLI loop:
      - `/confirm` and `/cancel` → `run_turn(..., confirmation=ConfirmationDecision(token_id=<state's confirmation_token_id>, decision=…))`, with the token read via `graph.aget_state(config)`.
      - `/otp <code>` → `gate.verify(code)`. On success → `run_turn(..., resume="step_up")`. On failure, print `get_template("otp_required", language)` and run no turn.
      - Every other line → `run_turn(..., confirmation=None, resume=None)`.
    - The debug line appends `pending=… ui=[…]`.
    - *Personas:*
      - Add to `eval/personas.yaml`, picked from local `data/` by traits only (no names, numbers, balances or addresses; R10), with the existing keys plus `notes`:
        - one MX customer with a single USD credit card, Active, dpd 0 (step 2)
        - one bank-side `past_due` customer
        - one bank-side `bank_status` customer
        - one `Inactive` customer with an Active card
      - Verify each with FakeBank over `data/`. If an existing persona already fits, reference it in `notes` instead of adding a duplicate.
  - Verify: `cd backend && uv run python -c "from pathlib import Path;from app.domains.conversation.sandbox import build_sandbox_session;g,c,t=build_sandbox_session('CLI-TFMULTI00001',Path('tests/fixtures/fakebank'));assert {'bank_write_tools','vault'}<=set(c['configurable'])" && uv run pytest tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/sandbox.py && uv run ruff format --check app/domains/conversation/sandbox.py && uv run mypy app/domains/conversation/sandbox.py && uv run python -c "import yaml,asyncio,uuid;from pathlib import Path;from app.domains.conversation.tools.context import ToolContext;from app.domains.conversation.tools.fakebank import FakeBank;ps=yaml.safe_load(open('../eval/personas.yaml',encoding='utf-8'))['personas'];[asyncio.run(FakeBank(ToolContext(customer_id=p['customer_id'],conversation_id=uuid.uuid4(),actor='customer',trace_id='t',policy_version='u'),Path('../data')).get_profile()) for p in ps];print(len(ps))"`. The import needs an LLM client: if `get_llm_client()` requires `ANTHROPIC_API_KEY`, set a dummy key in the env for this one-liner. Manual check (verifier, needs the key and `DEMO_OTP_CODE`): `make chat-sandbox CUSTOMER=<MX credit persona>` for lock → `/confirm`, and unlock → `/otp <code>` → `/confirm`.
  - Files: `backend/app/domains/conversation/sandbox.py`, `eval/personas.yaml`

- [ ] T14: `replacement` flow: offer, address confirm, OTP for a new address, vault, tracking ID (CUT LINE)
  - Depends on:
    - T10: helpers, `make_session` with its `vault`, and the offer pause set by `card_block`
    - T12: the `otp_pause`/resume usage pattern in `card_unlock`
    - T7: `order_replacement` returns `tracking_id`; `CustomerProfile.city` (T2)
    - T9: the entry route for `awaiting_slot == "address"`
  - Read exactly these: spec D4, D10, D13 and the two replacement test rows; `docs/solution-docs/02-conversation-design.md` §4.9; `backend/app/domains/conversation/flows/card_unlock.py` (the analogue)
  - Acceptance:
    - New `flows/replacement.py` (node `replacement`):
      - `offer_replacement`: affirm → continue with `selected_card_id`. Deny → `replacement_declined`, `pending=None`.
      - A fresh `replacement_request` → `card_select`.
      - Customer not active → `handoff(atencion)`.
      - Eligible only when `get_block_origin` is `customer_block` or `expiration_date < local_today(country)`. Otherwise `replacement_not_eligible`.
      - `address_confirm` pause with `{address_masked} = "•••, " + city` (or `•••` when there is no city). Affirm → `start_plan(cards.order_replacement {card_id, address_ref:"on_file"})`. Deny → `otp_pause`, unless the gate is already valid.
      - Resume valid → `address_ask` with `awaiting_slot="address"`.
      - The address turn (no `understand`) → `vault.put_address(state["user_text"])` → `start_plan` with the `⟨ADDR_n⟩` ref.
      - Confirm → `execute` with `action_done` and `{reference}=tracking_id`.
      - The raw address is never written to `slots`, `facts`, `ui`, plan args or `segments`.
    - Register `replacement` for `replacement_request` in the three tables and regenerate the diagram.
    - Append to `test_block_flows.py`:
      - `test_es_lost_card_block_replacement_tracking`: "la perdí" (`permanent_block`) → confirm → offer → "sí" → address confirm → "sí" → confirm → the reply contains the `RPL-` tracking ID, and there is no `otp_required`.
      - `test_pt_new_address_needs_otp_and_is_vaulted`: "não" → `otp_required` → verify + resume → `address_ask` → the address turn makes no LLM call; plan args, `facts`, `ui` and every `llm.calls[*].user` hold `⟨ADDR_1⟩` / never the raw text.
  - Verify: `cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd && uv run pytest tests/unit/test_block_flows.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && ! grep -rn "import app.core.llm\|from app.core.llm" app/domains/conversation/flows && uv run ruff check app/domains/conversation tests/unit/test_block_flows.py && uv run ruff format --check app/domains/conversation tests/unit/test_block_flows.py && uv run mypy app/domains/conversation`
  - Files: `backend/app/domains/conversation/flows/replacement.py` (new), `backend/app/domains/conversation/graph.py`, `docs/diagrams/turn-graph-v0.mmd`, `backend/tests/unit/test_block_flows.py`

- [ ] T15: Docs: `04` §1/§3/§5, `02` §3/§4.2, and the spec amendment
  - Depends on: T2–T14. Record the final symbol names from the state file.
  - Read exactly these: spec D20; this plan §"Human decisions"; `docs/solution-docs/04-contracts.md` §1, §3 and §5 and `docs/solution-docs/02-conversation-design.md` §3 and §4.2 (only those sections)
  - Acceptance:
    - `04` §1: `get_fx_rate`/`FxRate`, `CustomerProfile.city`, the read-back keys.
    - `04` §3: `TurnInput.resume` and the OTP resume path (amends D2-K D17).
    - `04` §5: the shapes of `tools.yaml`, `escalation.yaml` v1 (including `action_queues: {action_unverified: atencion}`) and `min_payment.yaml`.
    - `02` §3: the `awaiting_slot` values `address`, `address_confirm`, `offer_replacement`, `block_kind`, `card_hint`; the `resume` channel; the entry-routing order; `enqueue`/`next_intent`; P1 (a new flow replaces a paused one); P3.
    - `02` §4.2: the min payment has no overdue term, plus P5 and P6 and the `payment_overdue` fact.
    - Spec: add `replacement_declined` to §"New templates"; add `action_queues: {action_unverified: atencion}` to the `policies/escalation.yaml` block in §"Policies" and to D8/D11; move the plan-time open questions to a "Resolved at plan time" note (P1–P7).
  - Verify: `grep -n "get_fx_rate\|resume\|min_payment.yaml" docs/solution-docs/04-contracts.md && grep -n "offer_replacement\|next_intent\|payment_overdue" docs/solution-docs/02-conversation-design.md && grep -n "replacement_declined" docs/specs/d2-b-card-info-block.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`, `docs/specs/d2-b-card-info-block.md`

- [ ] T16: B6 rough wireframes (human task, Dev B)
  - Depends on: nothing (last by decision D6)
  - Read exactly these: spec D6; `docs/brand.md`
  - Acceptance: Dev B sketches landing, login and chat on paper or a whiteboard and attaches photos to the PR description, or optionally commits them under `docs/wireframes/`. No code and no tests. No agent is dispatched; the orchestrator only checks that the PR body contains the three images.
  - Verify: `gh pr view --json body -q .body | grep -ci "wireframe"` (or `ls docs/wireframes/`)
  - Files: `docs/wireframes/` (optional, new)
