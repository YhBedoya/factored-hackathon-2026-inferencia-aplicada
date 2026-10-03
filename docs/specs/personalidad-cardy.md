# Spec: personalidad-cardy

Card source: [`docs/requirements/personalidad-cardy.md`](../requirements/personalidad-cardy.md). In this spec, R1–R6 are that doc's sections, and its "Hecho cuando" lines are the card's "Done when". Safety rules are written "06 R1…R13". Standalone card, owner B, group conversation, branch `feat/personalidad-cardy` (stacked on `feat/naturalidad-cardy`). Builds on [`naturalidad-cardy`](naturalidad-cardy.md) (D8, D9, D12, D14, D17, D24, D29).

## Objective

Make Cardy proactive, close and warm without changing what she is allowed to do:

- **Closing that suggests a next step.** A finished flow ends with one warm question. It suggests the next useful service (from policy) and keeps the door open, and a "sí" to it enters that flow on the focus card. The "Algo más"/"Terminar" chips and the "¿…damos por terminada la conversación?" wording go away.
- **"La otra" tarjeta.** It is resolved in code against the session's cards.
- **No second introduction.** A repeated greeting gets a re-greeting, without "Soy Cardy".
- **Template review.** Every customer-facing template is reviewed for tone.
- **Brand.** `brand.md` documents the three traits, and `compose` gets a new persona prompt.

The card serves every "Hecho cuando" line of R1–R6. The safety rules it touches (06 R1, R4, R5, R6, R8) stay as they are.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | One suggestion per situation, keyed by the intent that just finished: `card_status` → `transaction_search`, `balance_due` → `transaction_search`, `transaction_search` / `pending_reversal_explain` → `unrecognized_charge`, anything else → generic. The other rows of the R1.3 table need no code. Their turns already end in an offer pause or a chip (non-active status, verified permanent block, decline with a cause), and D29 skips the closing there. | Human Q3 (a). Assumption 3. `brand.md` "one question at a time". |
| D2 | The table lives in `policies/card_select.yaml` v4, in a new section `closing_suggestion`, read by the existing `card_select` policy loader. | Human Q6 (a). 06 R8. |
| D3 | The text is written in code. `next_intent._closing_update` picks the template kind from D2 and appends it. There is one kind per suggestion, each with 3 variants per language, no digits and no figures. `compose` never writes the closing. | Human Q5 (a). 06 R4, R8. naturalidad D14 precedent. |
| D4 | The closing keeps the `smalltalk.anything_else` pause (`CLOSING_PAUSE`) and sets a new checkpointed field, `closing_suggestion: Intent \| None`. Inside that pause:<br>• `affirm`, or an NLU intent list whose first intent equals `closing_suggestion` → enqueue that intent with `card_hint="focus"`.<br>• `deny` / `thanks_close` → `_close` (`farewell` + `conversation_closed`).<br>• `affirm` with a generic closing (`closing_suggestion=None`) → `ask_what_else`.<br>• Any other card request replaces the pause (P1).<br>`closing_suggestion` is cleared whenever the pause is consumed or replaced, and by `_close`. | Human Q1 (a). R1.6, R2.2–R2.3. |
| D5 | The `closing` chips are removed. `QuickRepliesPayload.slot` drops `"closing"` (`ui.py`, `frontend/src/lib/sse.ts`, `04` §"SSE"), and `_CLOSING_OPTIONS` is deleted. The D29 skip list doesn't change. | R2.1. Assumption 5. naturalidad D29. |
| D6 | An accepted `transaction_search` suggestion counts as a search criterion. `tx_search` searches only the focus card, over the default 12-month window (A2), newest first, at most 10 rows, shown in the usual `transaction_list`. A typed request with no criterion still gets `tx_search_ask_criterion`. | Human Q2 (a). `02` §4.4. |
| D7 | `tx_search._narrow_card_id` resolves `focus` to `selected_card_id` only if that id is in `list_cards()`. A foreign id or a missing focus → `None` (every own card). | Human Q2 (a). 06 R1. naturalidad D9. |
| D8 | New `card_hint` value `other`, shipped in `nlu@v7`. `select_card` resolves it against `list_cards()`:<br>• Candidates = every card except the focus card (D12: hints resolve over every status).<br>• Exactly one candidate → `Selected`.<br>• Two or more → `Ask` whose options are the eligible cards minus the focus card.<br>• Focus missing or not in the list → treated as no hint, with no failure counted.<br>• No candidate besides the focus card (a one-card customer) → also treated as no hint (as built). | Assumption 2. naturalidad D9, D12. 06 R1. R3. |
| D9 | `card_info` already moves `selected_card_id` to the card it answered, so "la otra" becomes the focus card. | R3.3. Existing behavior. |
| D10 | New checkpointed `introduced: bool`:<br>• `finish` sets it to `True` whenever it emits a bot reply.<br>• On a conversation's first graph turn (flag absent in the checkpoint), the runner seeds `introduced=True` when `store.list_messages` already holds a `role="bot"` message (the welcome).<br>The same seed puts the welcome's masked text at the head of `history` (naturalidad-cardy D8, amended 2026-10-03). | Human Q4 (a). |
| D11 | A lone `greeting` with `introduced=True` → new kind `greeting_again` (`{customer_name}` variants) or `greeting_again_plain`, 3 variants each. Neither contains "Soy Cardy" / "Sou a Cardy", and neither reuses a welcome body. With `introduced` false, today's `greeting` / `greeting_named` stay. No "who are you" intent is added. | R4. Assumption 4. |
| D12 | The baseline shares D1–D11, because the flows are shared. `baseline/lexicon.yaml` maps "la otra", "el otro", "a outra", "o outro" to `card_hint=other`. The baseline still gets no history. | Assumption 1. `02` §3 "Baseline (D5-A)". `05`. naturalidad D17. |
| D13 | R5 tone pass over every customer-facing template. The rules:<br>• keep the placeholders and ≥3 variants where they exist today;<br>• no digits;<br>• keep the meaning of the security templates (`injection_suspected`, unauthorized access, `tool_error`, `failure_handoff*`, `escalation_handoff`);<br>• `closing_question` is replaced by `closing_generic` ("¿Te puedo ayudar con algo adicional?" and variants).<br>PT still needs a native speaker's review. | R5. |
| D14 | `brand.md` Personality adds Propositiva / Cercana / Amable, each with a "así no / así sí" example from R6.1. Voice and tone gets a "Cierre de un flujo" row, and its Greeting example stays as the first-message intro. `compose@v11` aligns its persona block with these traits and carries no suggestion logic. | R6. 06 R8. |
| D15 | `docs/requirements/personalidad-cardy.md` is committed with the card. | Human instruction (pass 2). |
| D16 | An accepted `unrecognized_charge` suggestion starts on the focus card. `flows/unrecognized_charge.py` passes `focus_card_id=state.get("selected_card_id")` to `select_card`, which still validates it against `list_cards()` (06 R1, naturalidad D9), so the enqueued `card_hint="focus"` (D4) resolves without a picker. This extends D4's "on the focus card" to the second suggestion target. | Mid-card human decision (planner Q1 on T5, option a). |

## Contracts (delta only)

**Graph state** (`state.py` `TurnState`, checkpointed):
```python
closing_suggestion: NotRequired[Intent | None]   # set with CLOSING_PAUSE; cleared on consume/replace/_close
introduced: NotRequired[bool]                     # True after any bot reply or a stored welcome
```
`_close` also resets `closing_suggestion=None`. It keeps `introduced`, because the conversation is closed anyway.

**NLU** (`schemas.py`, `04` §2): the `NLUSlots.card_hint` pattern becomes `^(credit|debit|focus|other|last4:\d{4})$`. The prompt bumps to `nlu@v7`, with ES/PT examples of "y la otra" / "e a outra".

**Policy** (`policies/card_select.yaml`, `version: 4`, `provenance` header kept, `04` §5):
```yaml
closing_suggestion:          # intent just finished -> suggested intent (D1); missing key -> generic
  card_status: transaction_search
  balance_due: transaction_search
  transaction_search: unrecognized_charge
  pending_reversal_explain: unrecognized_charge
```
`CardSelectPolicy` gains `closing_suggestion: dict[Intent, Intent]`. Every value must be a core intent that Cardy resolves (R1.2), and the loader validates that.

**Templates** (`templates.py`): new kinds `closing_suggest_transaction_search`, `closing_suggest_unrecognized_charge`, `closing_generic`, `greeting_again`, `greeting_again_plain`. All of them are varied kinds (N = 3 per language). `closing_question` is removed. No template, in ES or PT, contains "terminada" or "encerrar a conversa".

**UI** (`ui.py`, `sse.ts`, `04` §"SSE"): the slot union drops `"closing"`. If the schema changed, regenerate the API client.

**Flow behavior**
- `next_intent._closing_update(state)`: when D29 allows the closing, it looks up the just-finished intent in `closing_suggestion` and returns:
  - the template segment;
  - `pending=CLOSING_PAUSE`;
  - `closing_suggestion=<intent or None>`;
  - no ui event.

  `with_closing` (after a verified action) uses the same helper. The intent that finished there is the action intent, so the closing is generic.
- `route` / `smalltalk`, with the `anything_else` pause open, apply D4. On acceptance the turn goes to `enqueue` with `intent_queue=[suggested]` and slots `card_hint="focus"`. `enqueue` also sets the graph-local, per-turn `GraphState.suggestion_accepted` (`graph.py`, reset by `load_session`, not checkpointed), which only `tx_search` reads as D6's criterion.
- `smalltalk` greeting: D11.
- Runner `_run_turn`: D10 seed, passed in the graph input only when the checkpoint has no `introduced`.

## Touch map

- `backend/app/domains/conversation/`:
  - `state.py`, `graph.py` (`suggestion_accepted`), `schemas.py`, `templates.py`, `ui.py`, `runner.py` (the D10 seed);
  - `nodes/load_session.py` (resets `suggestion_accepted`);
  - `nodes/next_intent.py`, `nodes/smalltalk.py`, `nodes/route.py`;
  - `flows/actions.py` (`closing`, `with_closing`, remove `_CLOSING_OPTIONS`), `flows/card_select.py` (`other`), `flows/tx_search.py` (`focus`, D6), `flows/unrecognized_charge.py` (focus card, D16);
  - `prompts/nlu@v7.md`, `prompts/compose@v11.md`, and the prompt version pins wherever `understand` / `compose` select them;
  - `baseline/lexicon.yaml`, `baseline/keyword_nlu.py`.
- `backend/app/domains/policy/`: the `card_select` loader (`closing_suggestion`).
- `policies/card_select.yaml` (v4).
- `frontend/src/lib/sse.ts`. Regenerate the API client if needed.
- Docs:
  - `docs/brand.md`: Personality and Voice-and-tone.
  - `02` §4.6 step 6: closing text, no chips, suggestion.
  - `02` §4.1: the `other` hint.
  - `02` §4.4: an accepted suggestion = focus-card search.
  - `04` §2, §5 and §"SSE".
  - `docs/requirements/personalidad-cardy.md`: commit it (D15).
- Tests: `backend/tests/unit/`. Update the existing tests that assert the old closing text or chips (`test_block_flows`, `test_state_offers`, `test_conversation_basics`, `test_card_info_flows`, `test_replacement_offers`, `test_graph`, `test_baseline`, `test_sandbox_conversations`, …). Don't duplicate them.
- `eval/scenarios/dev/`: only if a scenario turns out to depend on the old closing; none does today. Never touch `heldout/`.

## Test list (fake LLM only)

1. `test_status_closing_suggests_movements[es,pt]`: example B. An Active credit card's status ends with a `closing_suggest_transaction_search` variant. The reply contains neither "terminada" nor "encerrar a conversa". No `quick_replies` has `slot == "closing"`. `closing_suggestion == "transaction_search"`. (R1 Hecho 1, R2 Hecho 1, ES+PT happy path for `card_info`)
2. `test_accept_suggestion_lists_focus_movements[es,pt]`: after test 1, "sí" (NLU `affirm`) → a `transaction_list` whose rows all belong to the focus card. There is no `card_picker` and no `tx_search_ask_criterion`. (R1 Hecho 2, D6, ES+PT happy path for `tx_search`)
3. `test_no_thanks_after_closing_closes[es,pt]`: after a closing, "no, gracias" / "não, obrigado" → `farewell` + `conversation_closed`. (R2 Hecho 2)
4. `test_other_card_two_cards[es,pt]`: example C. Focus on credit •••• 9653, then `card_status` with `card_hint=other` → the status of the debit card. There is no `card_picker`, and `selected_card_id` is now the debit card. (R3 Hecho 1)
5. `test_other_card_three_cards_picker_excludes_focus`: the picker options don't include the focus card. (R3 Hecho 2)
6. `test_r1_other_and_focus_never_cross_customer`: the parametrized cases are:
   - `card_hint=other` with a `selected_card_id` that belongs to another customer;
   - an accepted suggestion with that foreign focus.

   No card, row or mask from the other customer appears: the result is the picker or a search over the customer's own cards. (R3 Hecho 3, 06 R1, D7, D8)
7. `test_greeting_after_welcome_no_self_intro[es,pt]`: with `introduced` seeded from a stored welcome, "Hola Cardy" → a `greeting_again` variant without "Soy Cardy" / "Sou a Cardy". With no welcome and a first turn, the reply is still `greeting_named`. (R4 Hecho, D10)
8. `test_every_varied_kind_has_three_clean_variants` (existing; it now covers the new kinds) and a new `test_no_procedural_closing_in_templates`: no ES/PT variant of any kind contains "terminada" or "encerrar a conversa". (R5 Hecho)

06 R5 and R6 need no new test. The new state fields hold an intent and a bool (no text). `next_intent` and `smalltalk` stay LLM-free, which the existing `test_r6_no_write_tools_in_llm_nodes.py` already covers.

## Boundaries

- **Always:**
  - Resolve `other` and `focus` only against `list_cards()` from the session.
  - Keep suggestions free of figures.
  - Write every new text in ES and PT, with ≥3 variants.
  - Bump the prompt version for any prompt edit.
  - An accepted block or replacement still goes through the normal confirmation token and read-back (06 R2/R3). The D1 table offers none today.
- **Ask first:**
  - Adding a suggestion row to `closing_suggestion` beyond D1.
  - Changing the D29 skip list.
  - Changing the meaning of a security template (`injection_suspected`, `tool_error`, `failure_handoff*`, `escalation_handoff`).
  - Touching any dev scenario beyond wording.
- **Never:**
  - Put the suggestion table or "la otra" logic in a prompt.
  - Let the NLU or the history supply a card id.
  - Bring back the closing chips.
  - Edit `eval/scenarios/heldout/`.
  - Give `compose` or `understand` a write tool.

## Success criteria

1. `uv run pytest backend/tests/unit -k "status_closing_suggests or accept_suggestion or no_thanks_after_closing or other_card or r1_other_and_focus or greeting_after_welcome or three_clean_variants or no_procedural_closing"` passes.
2. `make check` is green (lint, mypy, import-linter, unit tests).
3. Each of these finds no matches:
   - `grep -rniE "terminada|encerrar a conversa" backend/app/domains/conversation/templates.py`
   - `grep -rn '"closing"' backend/app/domains/conversation/ui.py frontend/src/lib/sse.ts`
4. `policies/card_select.yaml` has `version: 4`, the `provenance` header, and the `closing_suggestion` section of D2.
5. `prompts/nlu@v7.md` and `prompts/compose@v11.md` exist and are the versions in use. `schemas.py` accepts `card_hint="other"`.
6. `docs/brand.md` Personality lists Propositiva, Cercana and Amable, each with "así no / así sí". Voice and tone has a "Cierre de un flujo" row. `02` §4.1, §4.4 and §4.6 and `04` §2, §5 and §"SSE" reflect the deltas.
7. `git diff --stat main -- eval/scenarios/heldout/` is empty. `docs/requirements/personalidad-cardy.md` is tracked in git.
8. In the web chat, examples A, B and C play out as in R1–R4: a re-greeting without the intro, a suggestion with no chips, "sí" opens the movements, and "y la otra" answers directly (manual check).

## Open questions

- The PT wording of the new and rewritten templates needs a native speaker's review (R5.4). Owner: the team, outside this card.
