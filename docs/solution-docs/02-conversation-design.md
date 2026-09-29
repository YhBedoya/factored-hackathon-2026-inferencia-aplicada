# 02 — Conversation design

## 1. Intent catalog (closed enum)

The NLU call must return intents from this list only. Anything else is `status = out_of_scope`. The queues come from the handoff domain. Tier **Core** is built and evaluated first; **If-time** items follow in the order given in decision-log ADR-019.

| Intent | Feature(s) | Handler | Side effect | Tier |
|---|---|---|---|---|
| `card_status` | Card status and details | flow `card_info` | — | Core |
| `balance_due` | Balance, due date and minimum payment (credit cards only) | flow `card_info` | — | Core |
| `decline_explain` | Decline explainer (51, 14, 05, 54) | flow `decline_explain` | — | Core |
| `transaction_search` | Natural-language transaction search | flow `tx_search` | — | If-time (2) |
| `pending_reversal_explain` | Pending and reversed explainer | flow `tx_explain` | — | If-time (4) |
| `card_block` | Lost/stolen block; temporary lock vs permanent block | flow `card_block` | lock / block | Core |
| `card_unlock` | Unblock with reason check | flow `card_unlock` | unlock | If-time (1) |
| `unrecognized_charge` | Unrecognized-charge intake; suspected-fraud triage | flow `unrecognized_charge` | block, claim, handoff | Core (priority flags: If-time (3)) |
| `replacement_request` | Replacement and reissue | flow `replacement` | replacement order | Core |
| `human_request` | Explicit request for a human | rule → handoff | handoff | Core |
| `general_question` | Informational follow-ups that fit no flow | answer node (read-only); until it exists, structured abstain (ADR-026) | — | If-time (5) |
| `greeting`, `thanks_close`, `affirm`, `deny` | Conversation management | router | — | Core |
| `travel_notice`, `spending_limits`, `card_doctor`, `expiry_renewal`, `benefits_info`, `card_activation`, `pin_reset`, `card_cancel`, `limit_increase`, `card_finder`, `prequalification` | Stretch features | flows added later | various | Stretch |

`status` values: `clear`, `ambiguous`, `out_of_scope`, `out_of_market`, `injection_suspected` **(proposed)**.

## 2. NLU (understand node)

- **One** Bedrock structured-output call per turn. Temperature 0, pinned model ID and prompt version.
- Input: the masked user message, the last N masked turns, the pending flow and the slot it is waiting for, the customer's country (for regional vocabulary). **No tool output** is ever passed to this node.
- Output (Pydantic-validated, schema in `04-contracts.md`): `language` (`es`, `pt`, `mixed`), `intents[]` (ordered), `status`, `slots` (card hint, block kind, date expression, merchant, amount, currency, answer to the pending question, and `topic` for out-of-scope / out-of-market requests, ADR-026), `clarification` (e.g. `lock_vs_block`, `which_card`, `which_transaction`).
- If validation fails, the node retries once with the validation error, then falls back (see §6).
- **Confidence** is not a number. It comes from explicit labels (`ambiguous`) plus counters in the graph state (ADR-004).

## 3. Turn graph (LangGraph)

```
load_session ─┬─ mode == human ─► relay_to_agent ─► END   (_entry, no LLM, no bot reply)
              └─► mask_pii ─► understand ─► route
                                            ├─ escalation rule hit ───────► handoff_summary ─► handoff ─► END
                                            ├─ status out_of_market ──────► abstain(out_of_market) ─► compose
                                            ├─ status out_of_scope ───────► abstain(scope) ─► compose
                                            ├─ status ambiguous ──────────► clarify (counter++) ─► compose
                                            ├─ pending flow & answer fits ► resume pending flow
                                            ├─ intent has flow ───────────► push intents to queue ─► run flow
                                            └─ general_question ──────────► answer_node ─► compose
flow finished ─► pop next queued intent (if any) ─► …   compose ─► grounding_check ─► unmask ─► persist+audit ─► END
```

**Handoff nodes (D4-A).** `handoff_summary` is the only LLM step: it writes `request` from masked facts (fixed template on a raw digit or an `LLMError`, R4/R11). `handoff` is code only: it assembles the packet from verified read-backs, calls `HandoffTools.create`, sets `mode = human` and emits the `handoff_transfer` text and the banner; the flow that triggers a handoff never writes the reply. `relay_to_agent` publishes the customer's text as `message{role: customer}`. `abstain` builds its four facts from `policies/scope.yaml` with no tool call and `compose@v5` phrases them.

**Graph state** (checkpointed in Postgres, keyed by `conversation_id`):
`customer_id` (bound from the validated session passed in the run config, read-only; ADR-025), `language`, `country`, `mode` (`bot` / `human`), `nlu` (the current turn's `NLUResult`, or none), `intent_queue`, `pending` (`flow`, `node`, `awaiting_slot`), `slots`, `selected_card_id`, `clarification_failures`, `confirmation_token_id`, `dispute` (`unrecognized_charge`'s `DisputeState`: card, offered and picked tx ids, fraud scores, answers, question index, compromise and block-refused flags; D4-B), `facts[]` (for the composer, reset by `load_session` at the start of each turn and appended to by flows within that turn; Dev A reviews the reducer), `actions: list[ActionResult]` (tool results, D9), `escalation_reason`. `user_text`, `confirmation`, `resume` (in) and `reply`, `ui` (out) are graph-local channels, not part of the checkpointed `TurnState`: `confirmation` carries the button's `ConfirmationDecision{token_id, decision}` and is `None` on a typed turn (D17); `resume: Literal["step_up"] | None` marks a step-up completed outside the chat and is `None` on every other turn (D2-B D1, amends D2-K D17); `ui` is `list[UIEvent]`, reset to `[]` by `load_session` each turn (D16).

`pending.awaiting_slot` values: `"confirmation"` and `"otp"` for a plan pause and a step-up pause (D2-K D15); `"card_hint"` (`card_select`'s re-ask, D2-B); `"block_kind"` (`card_block`'s lock-vs-block clarification); `"address_confirm"` (`replacement`'s "send it to the address on file?" gate) and `"address"` (the raw-address turn that follows a "no", D2-B D4); `"offer_replacement"` (the yes/no gate `card_block` and `card_unlock` both use to offer a replacement after a verified permanent block); `"transactions"` (`unrecognized_charge` waiting on a `selection` from `ui.transaction_list`), `"card_possession"` and `"dispute_question"` (its yes/no questions, D4-B).

**Entry routing** (the conditional edge right after `load_session`, before `understand`; D2-B D1/D4/D20), in this order: (0) `selection` set (the transaction pick, `04` §3, D4-B D7) → resume `unrecognized_charge` when paused at `awaiting_slot == "transactions"`, else `smalltalk` (the route has already rejected ids that weren't offered with `409 selection_invalid`, and the flow checks again); (1) `confirmation` set → resume the flow paused at `awaiting_slot == "confirmation"`, else `smalltalk`; (2) `resume == "step_up"` → resume the flow paused at `awaiting_slot == "otp"`, else `smalltalk`; (3) `awaiting_slot == "address"` → resume that flow directly; (4) otherwise → `understand`. The human-mode check comes before all five: `mode == human` goes `load_session → relay_to_agent → finish` (D4-A D13). Steps 0–3 skip the LLM entirely; `smalltalk` is what a stale button or an OTP resume with no matching pause falls to instead of crashing.

**A new flow intent while one is paused (P1).** `route` sends a fresh (or replacing) card-action turn to `enqueue` rather than queuing it behind the paused flow: `enqueue` cancels any open plan (`bank_write_tools.cancel_plan`, only if a token is set), clears `pending`, `confirmation_token_id` and `clarification_failures`, then queues this turn's non-management intents in message order. A queued intent with no flow of its own yet (P3 — `decline_explain`, `human_request`, `transaction_search`, the Stretch intents) becomes an `unsupported_intent` template segment at its place in the queue, with no LLM call. `next_intent` pops the intent a flow node just answered and, when another remains queued, resets `facts` so `compose` never blends two intents' facts into one segment; an empty queue ends the turn.

**Digressions:** if a flow is waiting for a slot and the user asks a `general_question`, the answer node replies and `pending` stays intact. The next composer message restates the pending question.

## 4. Flow specifications (MVP)

Notation: **T** = tool call (customer-scoped), **C** = confirmation required (server-issued token), **S** = OTP step-up required, **V** = verified read-back.

### 4.1 `card_select` (shared sub-flow)
1. T `cards.list_cards()`. If there's one eligible card, select it. If there are several, emit a `ui.card_picker` event with masked options such as "Crédito •••• 6475 · Activa" and "Débito •••• 1203 · Bloqueada", then ask.
2. If the slot has a hint ("la de crédito", "la que termina en 6475"), resolve it in code. If it's still ambiguous, ask again and increment `clarification_failures`.

### 4.2 `card_info` (status, details, balance, due date, minimum payment)
1. `card_select` → T `cards.get_card_details(card_id)`.
2. Facts: masked number, status, expiry, credit limit, available credit (= limit − balance, computed in code), interest rate, balance, `days_past_due` bucket, and the minimum payment from the **synthetic policy formula** (labeled as synthetic in the reply footnote). Each fact carries its source (`bank.products:<product_id>` or `policy:min_payment@<hash>`).
   - **The formula has no overdue term** (D2-B D5, P5): `min_payment = min(max(percent × balance, floor[currency]), balance)`, `0` when balance ≤ 0. `days_past_due > 0` instead adds a separate `payment_overdue` fact carrying the bucket, so a card can be both current on the formula and flagged overdue.
   - **Due date** (P6): the next `due_day_of_month` on or after today in the country's `BANK_TZ`, so it is today when today is the 10th.
3. **Debit cards** (ADR-020) have no credit limit and no days past due. `card_info` shows the masked number, status, expiry and recent transactions. For `balance_due` on a debit card, the bot says plainly that balance, due date and minimum payment apply to credit cards, and offers what it can show.

### 4.3 `decline_explain`
1. `card_select` → T `transactions.search(status=Declined, …)` to find the decline (by default the most recent; otherwise ask which one).
2. Rules map `response_code` → cause + next step from `policies/decline_codes.yaml` (51 insufficient funds, 14 invalid card number, 05 do not honor, 54 expired card). The LLM only phrases it.
3. If the next step is actionable (e.g., 54 → replacement), offer the matching flow.

### 4.4 `tx_search`
1. The LLM slots carry date expressions, merchant, amount and currency. **Code** resolves the dates in the customer's time zone (MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`) against the bank clock, fuzzy-matches the merchant against the known merchant list, and applies amount ±10%.
2. T `transactions.search(filter)` returns at most 10 rows, shown as a `ui.transaction_list`.
3. With 0 results, widen once (date ±3 days), then say nothing was found and show the filters used.

### 4.5 `tx_explain` (pending and reversed)
Rules from `policies/transaction_states.yaml`: why a hold shows up, the expected drop date (synthetic policy), and why a reversal appears as two lines (the original plus a Reversed line). T `transactions.get(tx_id)`.

### 4.6 `card_block` (MVP centerpiece)
1. `card_select`.
2. If `block_kind` is missing, **clarify** `lock_vs_block`: "¿Quieres pausarla temporalmente o cancelarla y pedir una nueva?" This is the demo's ambiguous case.
3. The policy check makes sure the card is not already Blocked/Closed. **C**: the server issues a confirmation token and emits `ui.confirm`.
4. On affirm (a button or "sí"):
   - `temporary_lock` → T `cards.lock_card(card_id, token)` → **V** `card_controls.locked = true`.
   - `permanent_block` (lost/stolen) → T `cards.block_card(card_id, reason, token)` → **V** `products.product_status = 'Blocked'` → offer `replacement`.
5. If the read-back fails: handoff (`action_unverified`). Never say "done".

### 4.7 `card_unlock`
1. `card_select` → T `cards.get_block_origin(card_id)`.
2. The origin decides:
   - **Customer temporary lock** (`card_controls.locked`, actor = customer) → **S** step-up OTP → **C** → T `cards.unlock_card` → **V** → done.
   - **Customer permanent block** → cannot be undone. Offer a replacement.
   - **Bank-side** (dataset `Blocked` / `Suspended` status, `days_past_due` > 0, fraud flag, or customer `Suspended`) → no self-service. Handoff to **Cobranza** (days past due) or **Fraudes** (fraud / unknown bank block), with the reason stated.

### 4.8 `unrecognized_charge` (dispute intake + fraud triage)
1. `card_select` → T `transactions.search(card, status in disputes.yaml candidate_statuses)` (Declined excluded, max 10, newest first; none → a fixed "no transactions" reply and nothing written) → `ui.transaction_list` → the customer picks one or more transactions (`TurnInput.selection`, validated against the offered ids).
2. **Recognize before you dispute** (Stretch): show the decoded merchant, city, channel and date first.
3. Rules decide the path:
   - **Suspected compromise** (decided in D4-B D8: picked ≥ `compromise.min_picked` (2), or any picked `fraud_score` > `compromise.fraud_score_gt` (30), or "no" to the possession question, which is asked right after the pick only when count and score haven't already triggered; thresholds in `policies/disputes.yaml`) → **one plan confirmation** (ADR-027) that lists both steps, the permanent block and the claim draft → T `cards.block_card` → **V** → T `disputes.create_claim` → **V** → **handoff to Fraudes**. If a step fails or can't be verified, execution stops and the handoff lists what was applied. **Refused block** (D4-B D10): nothing is written; the bot offers the claim alone as a one-step plan, then hands off to Fraudes with `open_questions` noting the card is still active (and hands off even if the claim is refused too).
   - **Single charge** → required questions from `policies/disputes.yaml` (e.g., card in possession? tried contacting the merchant?). Amount, currency and date are filled from the record, never typed by the customer → **C** → T `disputes.create_claim` (appends one `bank.complaints` row per transaction, `origin='app'`, linked by `transaction_id`) → **V** re-read → case ID.
4. **Priority flags** (`is_repeat_complainer`, regulator mention, amount > threshold, Critical priority) → the claim is created and then **always** handed off to Reclamos.

### 4.9 `replacement`
1. Precondition: the card is permanently blocked or expired.
2. Confirm the delivery address (masked). An **address change** requires **S** step-up.
3. **C** → T `cards.order_replacement` → **V** → simulated tracking ID.

## 5. Clarification, abstention and escalation rules

Deterministic, defined in `policies/escalation.yaml`, evaluated in `route` and after every tool result. When `LLM_DISABLED` is set (cost guard, ADR-023), every turn takes the safe-fallback path.

| Rule | Trigger | Outcome |
|---|---|---|
| Clarify | `status = ambiguous` or a required slot is missing | Ask one targeted question and increment `clarification_failures` |
| Clarification exhausted | `clarification_failures ≥ 2` in the same flow | Handoff (Atención) |
| Out of market | Pix, boleto, a Brazilian account, CPF | Structured abstain (below): the bank doesn't serve that market, plus the closest thing it can do |
| Out of scope | Non-card banking topics, anything else | Structured abstain (below) |
| Human request | `human_request` | Handoff (queue chosen by the current flow, otherwise Atención) |
| Bank-side block | Unlock attempt on a bank-side block | Handoff to Fraudes / Cobranza |
| Confirmed or suspected fraud | Fraud triage path | Handoff to Fraudes |
| Legal / regulator mention | Keywords or NLU flag (demanda, abogado, Condusef, SIC, BCRA, Procon…) | Handoff to Reclamos with priority |
| Claim priority flags | See 4.8 | Handoff to Reclamos |
| Customer not active | Customer status is Closed, Suspended or Inactive (it takes precedence over card status, ADR-021) | Card info read-only, block still allowed, no unlock or replacement; handoff (Atención) |
| Unauthorized access | An `injection_suspected` turn (another person's data) or a tool raising `AccessDenied` | Refuse with the `injection_suspected` template and audit `access_denied{source: nlu\|tool, attempt}` every time; the 2nd attempt in a conversation (`attempts_before_handoff`) → handoff (Atención, `unauthorized_access`) |
| Tool / LLM failure | Retries exhausted | Safe fallback template + handoff |
| Unverified action | Read-back mismatch | Handoff (`action_unverified`) |

Queues: `atencion`, `cobranza`, `fraudes`, `reclamos` (one seeded agent each). `retencion` and `creditos` are Stretch **(proposed)**.

**Structured abstain (ADR-026).** An abstain reply is never just a list of topics. Code builds four facts from `policies/scope.yaml` using the NLU `topic`, and `compose` phrases them: (1) acknowledge the topic, (2) the `reason_key` (why this chat can't do it), (3) the closest supported action, if `closest_intents` has one, as a one-tap suggestion, and (4) an offer of a human (`human_queue`). After two abstains in a row, the human offer becomes a button **(proposed)**. If a flow is pending, it stays pending and the reply restates its question. Example: "¿Me das un préstamo?" → "Por aquí no puedo gestionar préstamos: este chat atiende tus tarjetas. Si quieres, reviso el cupo disponible de tu tarjeta de crédito, o te paso con un asesor."

## 6. Live takeover (handoff UX)

1. The handoff node builds the packet (`04-contracts.md` §4), sets `mode = human`, and publishes to Redis `handoff:<queue>`.
2. The customer sees, in their language, "Te estoy transfiriendo con un especialista de Fraudes. Caso #…" plus the facts already verified. The bot stops replying.
3. An agent claims the handoff in the staff console and sees the packet, the audit timeline and the (unmasked, role-gated) conversation. Agent messages are posted over HTTP and relayed to the customer's SSE stream through Redis pub/sub.
4. Agents can trigger one-click actions (e.g., unlock). These go through the **same policy engine** and are audited with `actor = agent:<id>`.
5. **Return to bot** (D4-A D27, D28): only the claimant may return; anyone else gets `409 not_claimant` with nothing changed. `return_to_bot` runs first: under the conversation's turn lock it sets `mode = bot` (graph and `app.conversations`) and clears `pending`, `intent_queue`, `confirmation_token_id`, `clarification_failures` and all handoff state (`escalation_reason`, `handoff_queue`, `unauthorized_attempts`, `handoff_id`, `handoff_evidence`, `handoff_request`). A busy lock is `409 turn_in_progress` with nothing changed. Only after that succeeds is the handoff marked `returned` and the fixed `back_with_cardy` system message and `mode{bot}` persisted and emitted. **No summary fact is written:** `facts` are reset every turn by `load_session`, so a fact written between turns would never reach `compose`.

## 7. Language and localization

- The reply language equals the **current turn's** detected language. `mixed` replies in the language that dominates the latest message (ties go to the previous reply language).
- Regional lexicon (`localization/lexicon/*.yaml`): tarjeta/cartão, bloquear/travar, "compra no reconocida"/"compra não reconhecida", voseo ("¿me podés bloquear…?"), MX/CO terms. Used in NLU prompt examples and by the keyword baseline.
- Money follows the **account's country format**, whatever language the reply is in:
  - MX: `US$1,234.50 (≈ MXN $21,480.00, tipo de cambio del 12/03/2026)`. The record currency comes first and the MXN estimate is labeled.
  - CO: `COP $1.234.567`.
  - AR: `ARS $ 1.234,50`.
- Dates are always day-first. Formatting is done in code (Babel) and inserted through placeholders.
- Channel-aware replies and plain-language mode are Stretch: composer parameters (`channel`, `register`).
