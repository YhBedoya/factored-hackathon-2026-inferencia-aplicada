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

`status` values: `clear`, `ambiguous`, `out_of_scope`, `out_of_market`, `injection_suspected` (built in D4-A, `nlu@v4`).

## 2. NLU (understand node)

- **One** Bedrock structured-output call per turn, plus at most one `summary` call (Haiku 4.5, temperature 0, `summary@v1`) when messages leave the 6-message window. Temperature 0, pinned model ID and prompt version.
- Input: the masked user message, the last 6 masked messages plus the masked summary of older ones (`context.build_context`; values stripped from the compose copy), the pending flow and the slot it is waiting for, the customer's country (for regional vocabulary). **No tool output** is ever passed to this node.
- Output (Pydantic-validated, schema in `04-contracts.md`): `language` (`es`, `pt`, `mixed`, `other`), `intents[]` (ordered), `status`, `slots` (card hint, block kind, date expression, merchant, amount, currency, answer to the pending question, and `topic` for out-of-scope / out-of-market requests, ADR-026), `clarification` (e.g. `lock_vs_block`, `which_card`, `which_transaction`).
- If validation fails, the node retries once with the validation error, then falls back (see §6).
- **Confidence** is not a number. It comes from explicit labels (`ambiguous`) plus counters in the graph state (ADR-004).

## 3. Turn graph (LangGraph)

```
load_session ─┬─ mode == human ─► relay_to_agent ─► END   (_entry, no LLM, no bot reply)
              └─► summarize (proposed only) ─► understand ─► route
                                            ├─ escalation rule hit ───────► handoff_summary ─► handoff ─► END
                                            ├─ status out_of_market ──────► abstain(out_of_market) ─► compose
                                            ├─ status out_of_scope ───────► abstain(scope) ─► compose
                                            ├─ status ambiguous ──────────► clarify (counter++) ─► compose
                                            ├─ pending flow & answer fits ► resume pending flow
                                            ├─ intent has flow ───────────► push intents to queue ─► run flow
                                            └─ general_question ──────────► answer_node ─► compose
flow finished ─► pop next queued intent (if any) ─► …   compose (grounding_check) ─► unmask ─► persist+audit ─► END
```

### Agent node (`AGENT_ENABLED`, ADR-035)

The flag is a global setting read at each turn. Off, the graph is the one above, unchanged. On, the `agent` node takes the turn after `load_session`. It runs a capped tool loop (`agent@v1`, at most 6 tool rounds) with the read tools, `scope_facts`, `propose_plan` and `pass_to_flow` (`04` §1). It holds no executing write tool and never sees a token (R6).

| Turn | Goes to |
|---|---|
| human mode, `llm_unavailable`, legal keyword | as without the agent: relay, degraded path, handoff |
| `pending` is a pipeline flow question (a flow-question pause, not the `anything_else` closing pause) | the pipeline: typed, button, pick and step-up turns |
| button decision on an open agent plan | the agent plan node: Acepto executes, No acepto cancels, a stale token runs nothing and shows the reminder and card |
| pick on a list the agent offered | the agent, with a turn event naming the picked reference |
| anything else | the agent |
| agent calls `pass_to_flow` | `understand` on the same message in the same turn |
| agent raises `LLMError` | `understand` on the degraded path (ADR-032) |
| agent raises `LLMRoundCap` | `handoff_summary → handoff`, reason `agent_round_cap` (`02` §5) |

**The pass rule.** `pass_to_flow` discards the loop's work and runs the unchanged pipeline on the same message. A message that mixes a migrated and a non-migrated request passes whole. While a pipeline flow's question is open, every later turn skips the agent until that flow ends.

**Replacement offer after an agent plan.** After an Acepto whose `block` steps are all verified, code offers a replacement for the cards that plan permanently blocked (D28–D30). Nothing is offered after a `lock`, after No acepto or after a failed or unverified step.
- One card: today's `offer_replacement` text and pause (`OFFER_REPLACEMENT_PAUSE`, `selected_card_id`); the pipeline's `replacement` flow handles the answer.
- Several cards: `offer_replacement_multi` plus a multi `card_picker` of exactly those cards, pause `replacement.replacement_cards`, `replacement_card_ids` set. The text input is disabled while it is open and a typed body gets `409 selection_required`.
- Code builds the offer; the agent node appends it after Cardy's reply, or after `agent_code_text` when her call fails. Cardy never offers a replacement herself.
- Reload decline (D39): a page that loads with the picker open, or that gets `409 selection_required` with no picker, posts `card_selection: {card_ids: []}`, which declines the offer.

**Confirming an agent plan.** An agent plan is confirmed only by the card's buttons, labelled "Acepto / No acepto" ("Aceito / Não aceito"). No typed text confirms it on any path, including a degraded turn where the classifier reads `affirm`. Acepto runs the plan through `execute_plan` with no LLM call before the writes; Cardy then phrases the result from the verified read-backs, and on an `LLMError` the code result text is sent. A failed or unverified step sends the handoff text, never Cardy's. No acepto cancels the plan in code (`cancel_plan`) and Cardy asks what to change (the `action_cancelled` text if that call fails). Pipeline plans (flag off, or a passed flow) keep "Confirmar / Cancelar" and still accept a typed "sí".

**A typed message while an agent plan is open.** The plan stays open and the agent takes the message. If the turn ends with the same plan open, code shows the same card again (the stored event, the same `token_id`, no `issue_plan` call). A change ("solo la 5214") is a new `propose_plan`, which replaces the plan; only one plan is open at a time.

**Masking and grounding (D5-A).** There is no `mask_pii` node: `start_turn` in the runner masks the typed text through the conversation's `PostgresPiiVault` before it becomes graph input (`⟨KIND_n⟩` tokens, `03` §6 `pii_vault`), so the checkpoint never holds raw `user_text`. `grounding_check` is not a separate node: it runs inside `compose` on each draft, in this order: (1) placeholders only from the offered keys, (2) no stray braces, (3) no digit outside a placeholder, (4) no PII detector hit, (5) the draft's language equals the turn language (a stopword heuristic; drafts too short to judge pass). On the first failure `compose` calls the LLM once more with the reason; a second failure uses the goal's fact template (`goal_card_status`, `goal_balance_due`, `abstain`, in `templates.py`, no digits). `fallback` is used only on an `LLMError`. Each outcome (`ok`, `regenerated`, `template`) goes on `reply_sent.payload.grounding` (`04` §6). `unmask` then resolves the tokens (nested ones included) just before the reply is published and stored.

**Baseline (D5-A).** `build_graph(system="baseline")` swaps four nodes and keeps the tools, policy, flows and graph shape: `understand` becomes a keyword NLU (no lexicon hit gives `general_question`), `compose` fills the goal templates, `handoff_summary` uses its fixed template and `abstain` goes straight to the four-part template. It makes no LLM call and is refused at startup unless `APP_ENV=eval`.

**Handoff nodes (D4-A).** `handoff_summary` is the only LLM step: it writes `request` from masked facts (fixed template on a raw digit or an `LLMError`, R4/R11). `handoff` is code only: it assembles the packet from verified read-backs, calls `HandoffTools.create`, sets `mode = human` and emits the `handoff_transfer` text and the banner; the flow that triggers a handoff never writes the reply. `relay_to_agent` publishes the customer's text as `message{role: customer}`. `abstain` builds its four facts from `policies/scope.yaml` with no tool call and `compose@v5` phrases them.

**Graph state** (checkpointed in Postgres, keyed by `conversation_id`):
`customer_id` (bound from the validated session passed in the run config, read-only; ADR-025), `language`, `country`, `mode` (`bot` / `human`), `nlu` (the current turn's `NLUResult`, or none), `intent_queue`, `pending` (`flow`, `node`, `awaiting_slot`), `slots`, `selected_card_id`, `clarification_failures`, `non_answer_failures` (non-answers in a row on the open flow question, below), `open_question` (the text and the asking node's own UI events of the open flow question as it was asked; written and cleared by `finish`), `confirmation_token_id`, `dispute` (`unrecognized_charge`'s `DisputeState`: card, offered and picked tx ids, fraud scores, answers, question index, compromise and block-refused flags; D4-B), `facts[]` (for the composer, reset by `load_session` at the start of each turn and appended to by flows within that turn; Dev A reviews the reducer), `actions: list[ActionResult]` (tool results, D9), `escalation_reason`. `user_text`, `confirmation`, `resume` (in) and `reply`, `ui` (out) are graph-local channels, not part of the checkpointed `TurnState`: `confirmation` carries the button's `ConfirmationDecision{token_id, decision}` and is `None` on a typed turn (D17); `resume: Literal["step_up"] | None` marks a step-up completed outside the chat and is `None` on every other turn (D2-B D1, amends D2-K D17); `ui` is `list[UIEvent]`, reset to `[]` by `load_session` each turn (D16).

`pending.awaiting_slot` values: `"confirmation"` and `"otp"` for a plan pause and a step-up pause (D2-K D15); `"card_hint"` (`card_select`'s re-ask, D2-B); `"block_kind"` (`card_block`'s lock-vs-block clarification); `"address_confirm"` (`replacement`'s "send it to the address on file?" gate) and `"address"` (the raw-address turn that follows a "no", D2-B D4); `"offer_replacement"` (the yes/no gate `card_block` and `card_unlock` both use to offer a replacement after a verified permanent block); `"offer_unlock"` and `"offer_block"` (the same yes/no gate for the unlock offer after a `card_status` answer on a customer-locked card, and the block offer from `replacement` when the card is still active; "no" to either shows the closing question, the same as a declined replacement offer); `"transactions"` (`unrecognized_charge` waiting on a `selection` from `ui.transaction_list`), `"card_possession"` and `"dispute_question"` (its yes/no questions, D4-B).

**Entry routing** (the conditional edge right after `load_session`, before `understand`; D2-B D1/D4/D20), in this order: (0) `selection` set (the transaction pick, `04` §3, D4-B D7) → resume `unrecognized_charge` when paused at `awaiting_slot == "transactions"`, else `smalltalk` (the route has already rejected ids that weren't offered with `409 selection_invalid`, and the flow checks again); (1) `confirmation` set → resume the flow paused at `awaiting_slot == "confirmation"`, else `smalltalk`; (2) `resume == "step_up"` → resume the flow paused at `awaiting_slot == "otp"`, else `smalltalk`; (3) `awaiting_slot == "address"` → resume that flow directly; (4) otherwise → `understand`. The human-mode check comes before all five: `mode == human` goes `load_session → relay_to_agent → finish` (D4-A D13). Steps 0–3 skip the LLM entirely; `smalltalk` is what a stale button or an OTP resume with no matching pause falls to instead of crashing.

**A new flow intent while one is paused (P1).** `route` sends a fresh (or replacing) card-action turn to `enqueue` rather than queuing it behind the paused flow: `enqueue` cancels any open plan (`bank_write_tools.cancel_plan`, only if a token is set), clears `pending`, `confirmation_token_id` and `clarification_failures`, then queues this turn's non-management intents in message order. A queued intent with no flow of its own yet (P3 — `decline_explain`, `human_request`, `transaction_search`, the Stretch intents) becomes an `unsupported_intent` template segment at its place in the queue, with no LLM call. `next_intent` pops the intent a flow node just answered and, when another remains queued, resets `facts` so `compose` never blends two intents' facts into one segment; an empty queue ends the turn.

**A message that answers nothing (non-answer).** On the LLM path, a turn whose NLU result has no intent and does not answer the open question is a non-answer. The rule covers every flow question: `card_hint`, `block_kind`, `confirmation`, `otp`, `transactions` and the yes/no pauses. It does not cover the `anything_else` closing pause. A non-answer on a flow question changes nothing but `non_answer_failures`: `pending`, `confirmation_token_id`, `intent_queue`, `slots` and `selected_card_id` stay as they were, no plan is cancelled or issued, and the customer gets the same question again with the same UI, replayed from `open_question` and not rendered again. The same message with no flow question open (no pause, or the closing pause) gets `clarify_rephrase` from `smalltalk` and is not counted. A bot turn that ends with no segment replies with the `fallback` template; in human mode the reply stays empty, since the message goes to the agent.

**Digressions:** if a flow is waiting for a slot and the user asks a `general_question`, the answer node replies and `pending` stays intact. The next composer message restates the pending question.

## 4. Flow specifications (MVP)

Notation: **T** = tool call (customer-scoped), **C** = confirmation required (server-issued token), **S** = OTP step-up required, **V** = verified read-back.

### 4.1 `card_select` (shared sub-flow)
1. T `cards.list_cards()`. If there's one eligible card, select it. If there are several, emit a `ui.card_picker` event with masked options such as "Crédito •••• 6475 · Activa" and "Débito •••• 1203 · Bloqueada", then ask.
2. If the slot has a hint ("la de crédito", "la que termina en 6475"), resolve it in code. If it's still ambiguous, ask again and increment `clarification_failures`.
3. The hint `other` ("la otra", "a outra") means every card except the focus card (`selected_card_id`), resolved in code over `list_cards()` and every status: one candidate is selected, two or more are asked about (the options exclude the focus card). A missing focus, one not in the list, or no card besides the focus card (or none eligible) is treated as no hint: the normal selector runs and no failure is counted (personalidad-cardy D8).

### 4.2 `card_info` (status, details, balance, due date, minimum payment)
1. `card_select` → T `cards.get_card_details(card_id)`.
2. Facts: masked number, status, expiry, credit limit, available credit (= limit − balance, computed in code), interest rate, balance, `days_past_due` bucket, and the minimum payment from the **synthetic policy formula** (labeled as synthetic in the reply footnote). Each fact carries its source (`bank.products:<product_id>` or `policy:min_payment@<hash>`).
   - **The formula has no overdue term** (D2-B D5, P5): `min_payment = min(max(percent × balance, floor[currency]), balance)`, `0` when balance ≤ 0. `days_past_due > 0` instead adds a separate `payment_overdue` fact carrying the bucket, so a card can be both current on the formula and flagged overdue.
   - **Due date** (P6): the next `due_day_of_month` on or after today in the country's `BANK_TZ`, so it is today when today is the 10th.
3. **Debit cards** (ADR-020, ADR-034) have no credit limit and no days past due. `card_info` shows the masked number, status, expiry and recent transactions. For `balance_due` on a debit card, the bot answers with its **available balance** (`current_balance`, fact `available_balance`, goal `debit_balance`); due date and minimum payment stay credit-only.

### 4.3 `decline_explain`
1. `card_select` → T `transactions.search(status=Declined, …)` to find the decline (by default the most recent; otherwise ask which one). With a `merchant_text`/`amount` slot, code narrows the ≤10 declines (case-insensitive merchant match, or amount ±10%); one match explains it directly, two or more offer those in a single-pick `ui.transaction_list` (`multi: false`), and zero offer every decline the same way (D5-B D2).
2. Rules map `response_code` → cause + next step from `policies/decline_codes.yaml` (51 insufficient funds, 14 invalid card number, 05 do not honor, 54 expired card). The LLM only phrases it.
3. If the next step is actionable (e.g., 54 → replacement), offer the matching flow.

### 4.4 `tx_search`
1. The LLM slots carry date expressions, merchant, amount and currency. **Code** resolves the dates in the customer's time zone (MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`) against the bank clock, fuzzy-matches the merchant against the known merchant list, and applies amount ±10%.
2. T `transactions.search(filter)` returns at most 10 rows, shown as a `ui.transaction_list`.
3. When the customer accepts a closing suggestion ("sí" to the proposal to review their latest movements), the search is a focus-card search: it counts as a criterion, so there is no `tx_search_ask_criterion`, and it covers only the focus card (`selected_card_id`, honored only if it is in `list_cards()`; otherwise every own card), the default 12-month window, newest first, at most 10 rows (personalidad-cardy D6, D7). A typed request with no criterion still asks for one.
4. With 0 results, widen once (date ±3 days), then say nothing was found and show the filters used.
5. `transaction_search` routes to `tx_search` in the graph, reusing the shared `transactions` pause; a Pending/Reversed pick explains from `tx_explain`'s rules, an Approved (or other) pick shows decoded details, and an ambiguous result just shows the single-pick list, with no new clarification (D7-B D1-D2).

### 4.5 `tx_explain` (pending and reversed)
Rules from `policies/transaction_states.yaml`: why a hold shows up, the expected drop date (synthetic policy), and what a Reversed row means. T `transactions.get(tx_id)`.
`pending_reversal_explain` routes to `tx_explain`, searching the same slot filter restricted to `status in [Pending, Reversed]`: one match explains it, two or more offer a single-pick list first, zero with a slot offers every Pending/Reversed row from the last 12 months, and none at all gets a fixed "nothing pending or reversed" reply (D7-B D3). The data has no twin original for a Reversed row, so the reversal is explained from the single row and the reply never claims two lines exist (D7-B A5). A row on a non-card product (for example a savings account) is explained without a card mask; there is no `card_mask` fact (D7-B D19).

### 4.6 `card_block` (MVP centerpiece)
1. `card_select`.
2. **State is checked before lock-vs-block**: a card already Blocked, Closed or locked gets `already_in_state` plus a next-step offer (replacement, unlock or a person, by block origin from `policies/card_select.yaml` `next_step_offer`), not the lock-vs-block question. The policy check makes sure the card is not already Blocked/Closed.
3. If `block_kind` is missing, **clarify** `lock_vs_block`: "¿Quieres pausarla temporalmente o cancelarla y pedir una nueva?" This is the demo's ambiguous case. Then **C**: the server issues a confirmation token and emits `ui.confirm`.
4. On affirm (a button or "sí"):
   - `temporary_lock` → T `cards.lock_card(card_id, token)` → **V** `card_controls.locked = true`.
   - `permanent_block` (lost/stolen) → T `cards.block_card(card_id, reason, token)` → **V** `products.product_status = 'Blocked'` → offer `replacement`.
5. If the read-back fails: handoff (`action_unverified`). Never say "done".
6. After a verified lock, and once any queued intents have run (the queue drains first), the reply ends with one warm closing question written in code from fixed templates, with no chips (personalidad-cardy D1, D4, D5). The suggestion comes from `policies/card_select.yaml` `closing_suggestion`, keyed by the intent that just finished; after a verified action the closing is generic ("¿Te puedo ayudar con algo adicional?"). The pause is `smalltalk`'s `anything_else`: an affirm (or the suggested intent) enters that flow on the focus card, a deny or thanks ends the conversation with the farewell, and any other card request replaces the pause.

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
4. **Priority flags** (repeat complainer, amount above the per-currency threshold, an open Critical complaint) are checked in code before the claim plan is issued, on both the single-charge and compromise paths, never asked of the LLM (D7-B D5). On the single-charge path, the claim still runs C → `create_claim` → V, and after a verified read-back the flow sets `escalation_reason = priority_claim` and hands off to Reclamos; an unverified claim goes through the existing `action_unverified` handoff instead (D7-B D6). On the compromise path, Fraudes still wins: the handoff stays `suspected_fraud` → Fraudes, and `priority_claim` is appended to `escalation_rules_hit` (D7-B D7). A regulator mention is unchanged: `legal_regulator` still hands off to Reclamos at once with no claim, even when it lands mid-flow on a paused `unrecognized_charge` (D7-B D8). "Open Critical" means a `bank.complaints` row for the customer with `priority = Critical` and `status in disputes.yaml priority.open_statuses` (`[Open, In Process, Escalated]`) (D7-B D9).

### 4.9 `replacement`
1. Precondition: the card is eligible. Eligibility is a `customer_block` origin (`policies/card_select.yaml` `replacement.eligible_origins`) or an expired card (checked in code against the expiration date). The picker lists eligible cards only. One eligible card means no picker. None, or an ineligible active card, gets an explanation plus an offer to block it (pause `offer_block`). Bank-side, Suspended or Closed cards go to a person. A request for a *new* card (not a replacement) is the `new_card` abstain (§5), never this flow.
2. Confirm the delivery address (masked). An **address change** requires **S** step-up.
3. **C** → T `cards.order_replacement` → **V** → simulated tracking ID.

**Several cards (after an agent block, D31, D34–D36).** The flow works on a list: `replacement_card_ids`, falling back to `[selected_card_id]`.
- Entry is the pause `replacement_cards`: `card_selection` with the picked ids (`[]` declines).
- Decline: `replacement_declined_multi`, then the closing; segment `cancelled`; no plan issued.
- `customer_not_active` runs once; then each card is checked for eligibility. An ineligible card is dropped with `replacement_card_not_eligible`; none left gets `replacement_not_eligible`.
- Address: `address_confirm_multi`, or `address_ask_multi` after a "no" (several cards left). OTP at most once, for a new address only.
- One plan, one token: N `cards.order_replacement` steps with the same `address_ref`, `action_confirm_multi`, labels `confirm_cancel`. One **V** read-back per step; the first failed or unverified step stops the plan and hands off.
- `action_done` once per card, each with its own tracking ID, only after every step is verified.
- The input is disabled at the pause; the S0 non-answer re-show does not apply to it.

## 5. Clarification, abstention and escalation rules

Deterministic, defined in `policies/escalation.yaml`, evaluated in `route` and after every tool result. When `LLM_DISABLED` is set (cost guard, ADR-023), every turn takes the degraded path (ADR-032): the trained classifier replaces `understand` and the baseline templates replace the LLM nodes, with zero LLM calls. A degraded turn hands off only when no classifier is loaded, when its intent is in `degraded_handoff_intents` (`transaction_search`, `general_question`), or after two ambiguous turns in a row (`clarify_rephrase` first, then `clarification_exhausted`).

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
| Tool / LLM failure | Tool retries exhausted (2 retries, `01` §7); with a loaded classifier, an `LLMError` or `LLM_DISABLED` runs the degraded path first and hands off only per the rules above; with none loaded, any `LLMError` or `LLM_DISABLED` | `failure_handoff` template (no LLM; `failure_handoff_after_action` when the turn already has a verified action or a write failed after its retries, the graph-local `write_failed` flag; with no language in state yet, `load_session` picks ES/PT with the in-code `_guess_language` check, since the country can't tell PT) + handoff (`tool_failure` / `llm_unavailable`, queue as `human_request`, priority normal; D6-A D8-D10) |
| Unverified action | Read-back mismatch | Handoff (`action_unverified`) |

**Stuck conversation (agent).** Code counts and hands off with `clarification_exhausted` (Atención): (a) the third agent turn labelled `asked` for the same request type; (b) typed turns that end with the same agent plan still open get the card again twice, and the third such turn hands off, with the plan cancelled first. A button click, a replaced plan or any other outcome resets the count.

**Round cap (agent).** When the agent loop uses its 6 tool rounds, code cancels any open plan and hands off with `agent_round_cap` (Atención, normal). The customer reads the existing `handoff_transfer` text; the agent's partial work is never shown.

A message with no intent that does not answer the open flow question is re-asked once, and the second in a row hands off with `clarification_exhausted`. It is counted in `non_answer_failures`, not in `clarification_failures`.

Queues: `atencion`, `cobranza`, `fraudes`, `reclamos` (one seeded agent each). `retencion` and `creditos` are Stretch **(proposed)**.

**Structured abstain (ADR-026).** An abstain reply is never just a list of topics. Code builds four facts from `policies/scope.yaml` using the NLU `topic`, and `compose` phrases them: (1) acknowledge the topic, (2) the `reason_key` (why this chat can't do it), (3) the closest supported action, if `closest_intents` has one, as a one-tap suggestion, and (4) an offer of a human (`human_queue`). After two abstains in a row, the human offer becomes a button **(proposed)**. The reply is warm and in the first person (the `abstain_fallback` variants thank the customer and ask a question). The `new_card` topic (a request for a new card, not a replacement) is a fixed template with no compose call and no human chip (`scope.yaml` `offer_human: false`): this chat can't issue a new card, and a person can't either. If a flow is pending, it stays pending and the reply restates its question. Example: "¿Me das un préstamo?" → "Por aquí no puedo gestionar préstamos: este chat atiende tus tarjetas. Si quieres, reviso el cupo disponible de tu tarjeta de crédito, o te paso con un asesor."

## 6. Live takeover (handoff UX)

1. The handoff node builds the packet (`04-contracts.md` §4), sets `mode = human`, and publishes to Redis `handoff:<queue>`.
2. The customer sees, in their language, "Te estoy transfiriendo con un especialista de Fraudes. Caso #…" plus the facts already verified. The bot stops replying.
3. An agent claims the handoff in the staff console and sees the packet, the audit timeline and the (unmasked, role-gated) conversation. Agent messages are posted over HTTP and relayed to the customer's SSE stream through Redis pub/sub.
4. Agents can trigger one-click actions (e.g., unlock). These go through the **same policy engine** and are audited with `actor = agent:<id>`.
5. **Return to bot** (D4-A D27, D28): only the claimant may return; anyone else gets `409 not_claimant` with nothing changed. `return_to_bot` runs first: under the conversation's turn lock it sets `mode = bot` (graph and `app.conversations`) and clears `pending`, `intent_queue`, `confirmation_token_id`, `clarification_failures` and all handoff state (`escalation_reason`, `handoff_queue`, `unauthorized_attempts`, `handoff_id`, `handoff_evidence`, `handoff_request`). A busy lock is `409 turn_in_progress` with nothing changed. Only after that succeeds is the handoff marked `returned` and the fixed `back_with_cardy` system message and `mode{bot}` persisted and emitted. **No summary fact is written:** `facts` are reset every turn by `load_session`, so a fact written between turns would never reach `compose`.

## 7. Language and localization

- The reply language equals the **current turn's** detected language. `mixed` replies in the language that dominates the latest message (ties go to the previous reply language). `other` (neither Spanish nor Portuguese, nlu@v5) gets the fixed bilingual `unsupported_language` template, conversation language first; no flow runs and `pending` is kept.
- Regional lexicon (`localization/lexicon/*.yaml`): tarjeta/cartão, bloquear/travar, "compra no reconocida"/"compra não reconhecida", voseo ("¿me podés bloquear…?"), MX/CO terms. Used in NLU prompt examples and by the keyword baseline.
- Money follows the **account's country format**, whatever language the reply is in:
  - MX: `US$1,234.50 (≈ MXN $21,480.00, tipo de cambio del 12/03/2026)`. The record currency comes first and the MXN estimate is labeled.
  - CO: `COP $1.234.567`.
  - AR: `ARS $ 1.234,50`.
- Dates are always day-first. Formatting is done in code (Babel) and inserted through placeholders.
- Channel-aware replies and plain-language mode are Stretch: composer parameters (`channel`, `register`).
