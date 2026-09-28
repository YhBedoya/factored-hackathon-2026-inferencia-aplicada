# Spec: D2-B — G7 card info and G8 block/unblock in the sandbox

Card: `07-execution-plan.md` D2, Dev B rows B1–B6. Owner: Dev B. Branch `feat/d2-b-card-info-block` → `develop`. Builds on D1-B (`docs/specs/d1-b-agent-sandbox.md`), D2-K (`docs/specs/d2-k-write-contracts.md`) and the brand work (`docs/brand.md`, ADR-029). Safety-critical (tools, policy, identity): Dev A reviews before merge (ADR-018).

## Objective

This card finishes card info and runs lock, block, unlock and replacement end to end in the terminal sandbox, all through D2-K's write contracts:
- **B1.** `card_info` answers `balance_due`: balance, due date, synthetic minimum payment and available credit. Debit cards get the credit-only message, and customers who aren't Active get a read-only note.
- **B2.** Money, dates and masks are formatted in code for MX (USD with a labeled MXN estimate), CO and AR.
- **B3.** Conversation basics: greeting, thanks, bare yes/no, and an intent queue for several requests in one message.
- **B4.** FakeBank write tools, plus an in-memory confirmation store and OTP gate that implement the D2-K Protocols.
- **B5.** The flows `card_block`, `card_unlock` and `replacement`.
- **B6.** Rough wireframes.

It serves every B "Done when" line of D2, end-of-day test step 5 (`make chat-sandbox`: lock → confirm → read-back, unlock → OTP, "la perdí" → block → replacement → tracking ID, bank-blocked → handoff placeholder), and the sandbox half of step 2 (credit balance in the country's format in ES and PT; debit-only → credit-only message). A5 hosts the same graph on Postgres. **Cut line** (`07` "If behind"): the `replacement` flow (D11–D13 and its tests) moves to D3 morning.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **OTP resume.** The code is verified outside the chat, never in chat text or the LLM. `TurnInput` gains `resume: Literal["step_up"] \| None`. When set, the turn skips `understand` (no LLM) and resumes a `pending.awaiting_slot == "otp"` pause. Once the gate is valid, the flow issues its plan and pauses for confirmation (D2-K D15). With no matching pause, or with the gate still invalid, nothing executes and the turn replies with the `otp_required` template again. Every caller passes `resume` explicitly (`None` on a typed turn), as D2-K D17 does for `confirmation`. In the sandbox, `/otp <code>` calls the fake gate's `verify(code)` and, on success, runs a turn with `resume="step_up"`. In the app, D3-A4's `POST /auth/otp/verify` (or the frontend right after it) sends the same signal. **Amends D2-K D17 and `04` §3** | Human Q1(a). `04` §3 (`/auth/otp/verify`), ADR-027 (step-up before the plan) |
| D2 | **Step-up rule source.** B4 writes a provisional `policies/tools.yaml` (provenance header, `version: 1`) with only the confirmation and step-up flags of the five write tools. A tiny loader in `app/domains/policy/tools_policy.py` builds the D2-K `StepUpRule` from it. D3-A1 extends this file and loader rather than replacing them (Ask first: Dev A) | Human Q2(a). R8, D2-K D7 |
| D3 | **FX rate read tool.** `BankReadTools` gains `get_fx_rate(source, target) -> FxRate{source, target, rate, as_of}`: the latest `daily_exchange_rates` row for the pair, using the `exchange_rate` column. It is reference data, so there is no customer filter. FakeBank implements it now, and Dev A adds the Postgres query (A3/A5). This is a K3 contract change: Dev A reviews it | Human Q3(a), assumption 9. ADR-014, `06` §2 |
| D4 | **New delivery address.** After step-up, `replacement` pauses with `awaiting_slot = "address"`. The next turn skips `understand`. Code puts the raw text into an in-memory vault stub, which returns `⟨ADDR_n⟩` as `address_ref`. The raw text never reaches the LLM, `slots`, `facts`, `PlanStep.args` or the `ui` payload. The address on file is shown masked: `•••, <city>`. To support that, `CustomerProfile` gains `city: str \| None` (a K3 change; Dev A reviews) | Human Q4(a). D2-K D12, R5 |
| D5 | **`policies/min_payment.yaml` (synthetic).** For credit cards only: `min_payment = max(percent × balance, floor[currency])`, with percent 5% and floors USD 10 / COP 40.000 / ARS 5.000. **There is no overdue term.** When `days_past_due > 0`, a separate `payment_overdue` fact carries the bucket. The due date is the next `due_day_of_month: 10`, counted from today in the country's `BANK_TZ`. The reply footnotes the minimum payment and due date as synthetic, using a fixed template | Human Q5(b). `07` §8 (formula proposal), `02` §4.2, R8 |
| D6 | **B6 is in scope as the last task.** Rough wireframes for landing, login and chat, as photos in the PR. No code, no tests | Human Q6(b) |
| D7 | **B4 fakes are per session and in memory** (`07` §1):<br>• A `FakeBankOverlay` records locks, blocks and replacements. FakeBank reads apply it (`list_cards` sees `locked` and status), and FakeBank writes re-read it before returning `verified=True` (R3).<br>• `InMemoryConfirmationStore` implements `04` §7: single use, step cursor, 5-minute TTL on an injectable clock, bound to customer and conversation.<br>• `FakeStepUpGate` checks the fixed code from `DEMO_OTP_CODE` (ADR-008). Once verified, it stays valid for the session; the window N is the decision-log deferred item (D3-A4) | Assumption 3. ADR-008, `04` §7 |
| D8 | **`get_block_origin` in the FakeBank.**<br>• A lock or block made in this session is `customer_lock` / `customer_block`.<br>• A dataset product status `Blocked`/`Suspended`, `days_past_due > 0`, or a customer who isn't `Active` gives `bank_side`, with the reason checked in this order: `customer_status`, then `past_due`, otherwise `bank_status`.<br>• Otherwise `none`.<br>The queue for each reason and ADR-021's lists of statuses and allowed actions live in a new `policies/escalation.yaml` v1, which holds only those sections, plus `action_queues: {action_unverified: atencion}` (P7) for a write that comes back unverified | Assumption 4. `02` §4.7, §5, ADR-021, `04` §5 |
| D9 | **Handoff placeholder.** The `handoff_placeholder` template names the queue through a `{queue_label}` filled in code, sets `escalation_reason`, and clears `pending`. There is no `mode=human`, no packet and no Redis (D4 day) | Assumption 5 |
| D10 | **Customer not Active (ADR-021).** Card info adds a `read_only_note` fact. Lock and block are allowed. Unlock and replacement are refused with the handoff placeholder (Atención), driven by `escalation.yaml` | Assumption 6. ADR-021 |
| D11 | **`card_block` flow** (`02` §4.6):<br>• `card_select`, then the `lock_vs_block` clarification if `block_kind` is missing (fixed template, `clarification_failures += 1`).<br>• The policy check: a card that is already Blocked or Closed, or already locked for a lock, gets the `already_in_state` template.<br>• A one-step plan and the D2-K D15 confirm pause.<br>• The write through `bank_write_tools`, then `action_done` only if `verified`, otherwise the `action_unverified` handoff placeholder, naming the queue from `escalation.yaml`'s `action_queues.action_unverified` (P7).<br>• A permanent block uses reason `lost_or_stolen`. After a verified block, the flow offers a replacement (`awaiting_slot = "offer_replacement"`, where affirm starts `replacement`). Block and replacement stay separate one-step plans | `02` §4.6, ADR-027 ("other flows keep one-step plans"), R2, R3 |
| D12 | **`card_unlock` flow** (`02` §4.7):<br>• `get_block_origin` first.<br>• `customer_lock`: OTP pause (D1), then plan, confirm, unlock, read-back.<br>• `customer_block`: the "can't be undone" template plus the replacement offer (as D11).<br>• `bank_side`: handoff placeholder to the queue from `escalation.yaml` (Cobranza or Fraudes; Atención for `customer_status`).<br>• `none`: the `not_blocked` template | `02` §4.7, D8, D9 |
| D13 | **`replacement` flow** (`02` §4.9):<br>• Precondition: the card is `customer_block` or past its expiry. Otherwise the `replacement_not_eligible` template.<br>• Ask "send it to `•••, <city>`?" (`awaiting_slot = "address_confirm"`). Yes → plan `order_replacement(card_id, "on_file")`. No → OTP pause (D1), then the address pause (D4), then a plan with `⟨ADDR_n⟩`.<br>• Confirm, write, then `action_done` with `{reference} = tracking_id` | `02` §4.9, D2-K D12, Human Q4(a) |
| D14 | **Button equivalents in the sandbox.** `/confirm` and `/cancel` send `TurnInput.confirmation{token_id: <state's confirmation_token_id>, decision}`. A typed "sí"/"no" also works through NLU `affirm`/`deny` against `awaiting_slot = "confirmation"`. On deny or cancel, the flow calls `cancel_plan` and replies with `action_cancelled` | Assumption 2. `04` §3 ("equivalent to typing sí/no"), D2-K D17 |
| D15 | **Intent queue (B3, `02` §3).** `route` pushes this turn's flow intents onto `intent_queue` in message order and runs the first. When a flow finishes (a done, cancel, deny or refusal template, but not a pause), a `next_intent` node pops the next one. A pause ends the turn and leaves the rest queued. The turn's reply is its segments joined in order: fixed templates for actions and refusals, one `compose` call per informational segment | Assumption 7. `02` §3 |
| D16 | **Conversation basics.** A lone `greeting` gets `greeting_named` (or `greeting`). A greeting alongside a flow intent is dropped. `thanks_close` gets a new template. `affirm`/`deny` with nothing pending get `nothing_pending`. No LLM call for any of them beyond `understand` | Assumption 7. `02` §1 (router intents), ADR-029 |
| D17 | **`action_done` references.** `{reference}` is `tracking_id` for a replacement. Lock, unlock and block use a variant without a reference until `audit_event_id` exists (D3-A5). `{time}` is the read-back's `at` field, formatted `HH:MM` in `BANK_TZ` in code | Assumption 8. R3, R4, `docs/brand.md` |
| D18 | **Formatting (B2).** Money uses the account country's pattern with the record currency (D1-B D24). MX cards in USD append the labeled estimate in the MX pattern: `(≈ MXN $21,480.00, tipo de cambio del 12/03/2026)`, and in PT `(≈ MXN $21,480.00, câmbio de 12/03/2026)`, from D3's `FxRate`. CO is `COP $1.234.567` and AR is `ARS $ 1.234,50`. Dates are day-first and masks are `•••• 1234`. Everything goes in `domains/localization/` and is inserted through placeholders | `02` §7, ADR-014, R4 |
| D19 | **Prompt versions.** A goal change in `compose` (new goals `balance_due`, `credit_only_offer`) bumps it to `compose@v3`. If the NLU prompt changes (examples for `block_kind`, several intents, voseo for block/unlock), it bumps to `nlu@v3`. The old files stay | `06` §4 (version bump on every change), R7 |
| D20 | **Doc updates in this PR:**<br>• `04` §1: `get_fx_rate` / `FxRate`, `CustomerProfile.city`, read-back keys<br>• `04` §3: `TurnInput.resume`, the OTP resume path<br>• `04` §5: `tools.yaml` and `escalation.yaml` v1 shapes, `min_payment.yaml`<br>• `02` §3: the `awaiting_slot` values `"address"`, `"address_confirm"`, `"offer_replacement"`, the `resume` channel, `next_intent`<br>• `02` §4.2: min payment without the overdue term, plus the `payment_overdue` fact | `06` §7.4 |

## Contracts

Everything not listed stays as in `04`, K3 and D2-K.

**`app/domains/localization/schemas.py`** (new)
```python
class FxRate(BaseModel):          # frozen
    source: str; target: str      # "USD", "MXN"
    rate: Decimal                 # daily_exchange_rates.exchange_rate
    as_of: date                   # the row's date (shifted in Postgres, raw in FakeBank)
```

**`BankReadTools`** (`conversation/tools/bank.py`): `+ async def get_fx_rate(self, source: str, target: str) -> FxRate` (latest row; `NotFound` if the pair has none). **`CustomerProfile`**: `+ city: str | None = None` (D4).

**Read-back keys** (`ActionResult.readback`, FakeBank now, Postgres D3-A3):
- `lock_card`: `{"locked": True, "at": datetime}`
- `unlock_card`: `{"locked": False, "at": datetime}`
- `block_card`: `{"status": "Blocked", "at": datetime}`
- `order_replacement`: `{"status": "ordered", "at": datetime}` + `tracking_id`

**`app/domains/conversation/graph.py`**
```python
TurnInput:  + resume: NotRequired[Literal["step_up"] | None]     # D1
GraphState: + resume: NotRequired[Literal["step_up"] | None]
async def run_turn(graph, text, *, config, confirmation: ConfirmationDecision | None = None,
                   resume: Literal["step_up"] | None = None) -> tuple[str, DebugInfo]
DebugInfo:  + pending: str | None   # "<flow>.<awaiting_slot>"; + ui: list[str] (event kinds)
```
Input routing before `understand`, in this order:
1. `confirmation` set → resume the `confirmation` pause.
2. `resume == "step_up"` → resume the `otp` pause.
3. `pending.awaiting_slot == "address"` → address capture (D4).
4. Otherwise → `understand`.

**Graph config:** `configurable` gains `"bank_write_tools"` (a `ConfirmedWriteTools`, D2-K D5) and `"vault"` (`AddressVault`).

**`app/domains/safety/vault.py`** (new)
```python
class AddressVault(Protocol):
    def put_address(self, raw: str) -> str: ...     # returns "⟨ADDR_n⟩"
class InMemoryAddressVault: ...                    # per conversation; replaced by the D5 Fernet vault
```

**`app/domains/policy/`**
- `confirmation_memory.py`: `InMemoryConfirmationStore(customer_id, conversation_id, *, clock=…)` implements `ConfirmationStore` (`04` §7).
- `tools_policy.py`: `load_tools_policy(path) -> ToolsPolicy`, `step_up_rule(policy) -> StepUpRule`. It raises at load on a missing `provenance`.
- `min_payment.py`: `min_payment(balance, currency, policy) -> Decimal`, `next_due_date(today, policy) -> date`.
- `escalation.py`: loads `escalation.yaml`.

**`app/domains/identity/step_up_fake.py`**: `FakeStepUpGate(code: str)` implements `StepUpGate` + `verify(code) -> bool`.

**`app/domains/conversation/tools/fakebank.py`**: `FakeBankOverlay`, and `FakeBankWrites(ctx, data_dir, overlay)` implements `BankWriteTools` (every query filtered by `ctx.customer_id`, R1). `make_fakebank_factory` shares one overlay between reads and writes.

**Policies** (all `provenance: team-generated-synthetic`, `version: 1`)
```yaml
# policies/tools.yaml (provisional, D2)
tools:
  cards.lock_card:         {requires_confirmation: true, step_up: never}
  cards.unlock_card:       {requires_confirmation: true, step_up: always}
  cards.block_card:        {requires_confirmation: true, step_up: never}
  cards.order_replacement: {requires_confirmation: true, step_up: when_address_changed}
  cards.get_block_origin:  {requires_confirmation: false, step_up: never}
# policies/min_payment.yaml (D5)
min_payment: {percent_of_balance: "0.05", floors: {USD: "10", COP: "40000", ARS: "5000"}}
due_date:    {due_day_of_month: 10}
# policies/escalation.yaml (D8, D10, D11; D4-day adds the rest)
customer_not_active: {statuses: [Closed, Suspended, Inactive], allowed: [lock_card, block_card], queue: atencion}
bank_side_queues:    {past_due: cobranza, fraud: fraudes, bank_status: fraudes, customer_status: atencion}
action_queues:       {action_unverified: atencion}   # P7: queue for an unverified write's handoff
```

**New templates** (`templates.py`, ES/PT, no digits, placeholders filled in code): `thanks_close`, `nothing_pending`, `clarify_lock_vs_block`, `already_in_state`, `action_cancelled`, `action_done_noref`, `otp_required`, `address_confirm`, `address_ask`, `not_blocked`, `block_permanent_no_undo`, `offer_replacement`, `replacement_declined`, `replacement_not_eligible`, `handoff_placeholder`, `credit_only`, `synthetic_footnote`, `read_only_note`. `action_confirm`/`action_done` get wired. `replacement_declined` answers "no" at `awaiting_slot = "offer_replacement"` (P4): it doesn't claim that no change was made (the block/lock already happened), clears `pending`, then the queue moves on.

## Touch map

```
backend/app/domains/localization/{schemas.py (new), format.py}     FxRate; MXN estimate, 3-country money (D18)
backend/app/domains/customers/schemas.py                           + city
backend/app/domains/conversation/tools/{bank.py, fakebank.py}      get_fx_rate; overlay + FakeBankWrites
backend/app/domains/policy/{confirmation_memory,tools_policy,min_payment,escalation}.py   new
backend/app/domains/identity/step_up_fake.py                       new
backend/app/domains/safety/{__init__,vault}.py                     new (stub)
backend/app/domains/conversation/flows/{card_info,card_block,card_unlock,replacement}.py
backend/app/domains/conversation/nodes/{route,load_session,next_intent,smalltalk,compose,...}.py
backend/app/domains/conversation/{graph.py, templates.py, sandbox.py}
backend/app/domains/conversation/prompts/compose@v3.md (+ nlu@v3.md if changed)
policies/{tools,min_payment,escalation}.yaml                       new
backend/tests/fixtures/fakebank/                                   + daily_exchange_rates.csv, an inactive customer,
                                                                     an AR credit card with days_past_due > 0 (README updated)
backend/tests/unit/…                                               see Test list
docs/diagrams/turn-graph-v0.mmd                                    regenerated
docs/solution-docs/{04-contracts,02-conversation-design}.md       D20
eval/personas.yaml                                                 + bank-blocked / inactive personas if missing
.env.example                                                       + DEMO_OTP_CODE
docs/wireframes/ (optional photos, or in the PR only)              B6
```
The `app/domains/policy` mypy-strict override already covers the new policy modules. The flow modules must not import `app.core.llm` (the D2-K R6 scan).

## Test list

All tests use `ScriptedLLM` (fake LLM) and the fixture. None touch the network or `data/`.

| Test | Proves |
|---|---|
| `test_r1_fakebank.py::test_writes_refuse_foreign_cards` | R1, B4. Each of the 4 writes and `get_block_origin` on another customer's card → `AccessDenied`, and the overlay is unchanged |
| `test_r2_confirmation_store.py::test_memory_store_enforces_plan_semantics` | R2, B4. `InMemoryConfirmationStore`: a reused token and an expired token (injected clock) → `unknown_or_expired`; a wrong tool/args or reordered step → `step_mismatch`; another customer or conversation → `wrong_owner`; the key is gone after the last step |
| `test_r2_confirmation_store.py::test_tools_yaml_step_up_rule` | R2, R8, D2. The loaded rule: unlock always; replacement only when `address_ref != "on_file"`; lock/block never. A file with no `provenance` fails to load |
| `test_r3_flows.py::test_unverified_write_never_says_done` | R3. A raw write returning `verified=False` → no `action_done` text, `escalation_reason = "action_unverified"`, the plan is cancelled |
| `test_format.py::test_money_dates_masks_three_countries` | R4, B2. MX `US$…` with the labeled MXN estimate and the rate's date (ES and PT), CO `COP $1.234.567`, AR `ARS $ 1.234,50`, day-first date, `•••• 1234` |
| `test_min_payment.py::test_floor_percent_due_date` | B1, D5. Percent vs floor per currency, next day-10 in `BANK_TZ`, no overdue term |
| `test_card_info_flows.py::test_credit_balance_due[es,pt]` | B1, step 2. MX credit in ES: balance, due date, synthetic min payment, available credit, MXN estimate, synthetic footnote. CO in PT. A card with `dpd > 0` adds `payment_overdue` |
| `test_card_info_flows.py::test_debit_gets_credit_only[es,pt]` | B1, ADR-020. `balance_due` on debit → the `credit_only` template + what it can show, with no money facts |
| `test_card_info_flows.py::test_inactive_customer_read_only[es,pt]` | B1, ADR-021. The `read_only_note` is present |
| `test_conversation_basics.py::test_block_then_balance_in_order` | B3 Done-when. "bloquea mi tarjeta y dime mi saldo" → clarification → confirm → `action_done` then the balance segment, in that order, with an empty queue at the end |
| `test_conversation_basics.py::test_greeting_thanks_bare_yes_no` | B3. Each gets its template with no `compose` call |
| `test_fakebank_writes.py::test_writes_read_back_and_block_origin` | B4, R3. Lock, unlock, block and replacement return `verified=True` with the read-back keys, and `list_cards` reflects them. `get_block_origin` gives `customer_lock`, `customer_block`, `bank_side` (`past_due`, `bank_status`, `customer_status`) and `none` |
| `test_block_flows.py::test_es_lock_clarify_confirm_readback` | B5 happy path + clarification (ES), step 5a |
| `test_block_flows.py::test_pt_block_by_button_offers_replacement` | B5 happy path (PT), button `confirmation` input, replacement offer |
| `test_block_flows.py::test_es_deny_cancels_plan` | B5 "no". A typed deny → `cancel_plan`, `action_cancelled`, no write called |
| `test_block_flows.py::test_pt_bank_side_unlock_hands_off` | B5 bank-side, step 5d. Handoff placeholder naming Cobranza (`past_due`) / Fraudes (`bank_status`); no write, no OTP |
| `test_block_flows.py::test_es_unlock_own_lock_needs_otp` | B5 unlock, step 5b, D1. `otp_required`, then a `resume="step_up"` turn with the gate still invalid executes nothing. After `verify`, a resume turn → confirm → `unlock` → `action_done`. `understand` is not called on resume turns |
| `test_block_flows.py::test_es_lost_card_block_replacement_tracking` | B5 replacement, step 5c. "la perdí" → block → offer → on-file address → confirm → tracking ID in the reply, with no OTP |
| `test_block_flows.py::test_pt_new_address_needs_otp_and_is_vaulted` | B5 "OTP only for a change of address", R5, D4. No → OTP → address turn: no LLM call, and `PlanStep.args`, facts and the ui payload hold `⟨ADDR_1⟩`, never the raw text |
| `test_graph.py::test_graph_compiles_and_diagram_is_current` (existing) | The regenerated diagram matches |

R6 is covered by the existing D2-K scan, which now also scans the new flows. The existing D1/D2-K tests must stay green.

## Boundaries

- **Always**
  - Call writes only through `config["configurable"]["bank_write_tools"]`.
  - Say "done" only on `verified=True`.
  - Build every value-bearing reply (confirm, done, handoff) from a template filled in code.
  - Read policy from `policies/*.yaml`.
  - Filter every FakeBank query by the bound customer.
  - Keep the raw address out of the LLM, state, facts, plan args and ui.
  - Pass `confirmation` and `resume` explicitly on every turn.
- **Ask first**
  - Any other `BankReadTools`, `CustomerProfile`, `TurnState` or `TurnInput` change beyond D1, D3 and D4 (Dev A reviews).
  - Changing the `tools.yaml` shape.
  - Chaining block + replacement into one plan.
  - Touching the Streamlit page.
  - Adding a runtime dependency.
- **Never**
  - Put policy (step-up, eligibility, queues, formula) in prompts or code constants.
  - Send the OTP or a raw address to the LLM.
  - Import `app.core.llm` from a flow that touches `bank_write_tools`.
  - Build Redis, Postgres writes, the OTP route, SSE, the handoff packet or `mode=human` (D3-A / D4).
  - Touch `eval/scenarios/heldout/`, or commit `data/`, `.env` or real rows.

## Success criteria

1. `make check` passes (ruff, format, mypy, `lint-imports` with every contract KEPT, all unit tests), and the same checks pass in CI.
2. `cd backend && uv run pytest -q tests/unit/test_r1_fakebank.py tests/unit/test_r2_confirmation_store.py tests/unit/test_r3_flows.py tests/unit/test_format.py tests/unit/test_min_payment.py tests/unit/test_card_info_flows.py tests/unit/test_conversation_basics.py tests/unit/test_fakebank_writes.py tests/unit/test_block_flows.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py` → every test in the Test list is present and green.
3. `make chat-sandbox CUSTOMER=<id>` reproduces end-of-day step 5 with the personas in `eval/personas.yaml`:
   - lock → `/confirm` → "Listo…" with the time
   - unlock → `otp_required` → `/otp <DEMO_OTP_CODE>` → confirm → done
   - "la perdí" → block → replacement → tracking ID
   - a bank-blocked persona → handoff placeholder naming the queue

   The debug line shows `pending` and the write tools called.
4. The sandbox reproduces the sandbox half of step 2:
   - "¿cuánto debo de mi tarjeta de crédito?" on an MX persona → balance, due date, synthetic min payment (footnoted), MXN estimate with the rate date
   - the same in PT
   - a debit-only persona → the credit-only message
5. `policies/tools.yaml`, `min_payment.yaml` and `escalation.yaml` each start with `provenance: team-generated-synthetic`.
6. `grep -rn "import app.core.llm\|from app.core.llm" backend/app/domains/conversation/flows` returns nothing.
7. `04` §1/§3/§5 and `02` §3/§4.2 reflect D20. `.env.example` has `DEMO_OTP_CODE`.
8. The PR contains photos of the landing, login and chat wireframes (B6). Dev A approves it (ADR-018), and it is squash-merged.

## Open questions

| Question | Who decides |
|---|---|
| The raw address still sits in the checkpointed `user_text` input channel for the address turn (the MemorySaver in the sandbox). It closes with the D5 masking / vault work, under the R5 gap already accepted in D1-B D2 | D5-A (G6b) |
| The step-up validity window N, and the fate of an open plan when the session expires | Decision-log deferred item, D3-A4 |
| The Postgres `get_fx_rate` and `CustomerProfile.city` implementations | Dev A in A3/A5 |

**Resolved at plan time** (`docs/plans/d2-b-card-info-block.md` §"Human decisions taken at plan time"), all option (a) unless noted:
- **P1.** A new flow intent while another is paused: the new flow replaces the paused one (`cancel_plan` if a token is set; `pending`, `confirmation_token_id` and `clarification_failures` clear; the old `intent_queue` is dropped for this turn's intents). `02` §3.
- **P2.** `card_select` for block, unlock and replacement reuses `card_status.eligible_statuses` from `policies/card_select.yaml` unchanged; a card in the wrong state is caught by the flow's own check (`already_in_state`, `not_blocked`, `replacement_not_eligible`).
- **P3.** A queued intent with no flow in this card becomes an `unsupported_intent` template segment at its place in the queue. `02` §3.
- **P4.** "No" at `awaiting_slot = "offer_replacement"` gets the new `replacement_declined` template, clears `pending`, then pops the queue.
- **P5.** Minimum payment: `min(max(percent × balance, floor[currency]), balance)`, `0` when balance ≤ 0. `02` §4.2.
- **P6.** Due date: the next `due_day_of_month` on or after today in `BANK_TZ`. `02` §4.2.
- **P7.** The `action_unverified` queue: `policies/escalation.yaml` gains `action_queues: {action_unverified: atencion}`.
