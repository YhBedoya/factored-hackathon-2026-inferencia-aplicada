# Spec: naturalidad-cardy

Card source: [`docs/requirements/naturalidad-cardy.md`](../requirements/naturalidad-cardy.md) (R1–R9 below = its sections; safety rules are written "06 R1…R13"). Standalone card, D7, owner B, branch `feat/naturalidad-cardy`.

## Objective

Make Cardy remember the conversation and answer from it. Each turn builds a masked context: the last 6 messages, plus a summary of the older ones written by an LLM. The NLU and `compose` both read it, so "bloquearla" resolves to the card already in focus. Flows check the card's state first and offer the next useful step:

- by block origin, not by raw status;
- replacement is offered only for cards that are eligible;
- "tarjeta nueva" is answered as out of scope, without a human chip.

After every verified action Cardy asks a closing question with two buttons. Out-of-scope replies get warmer, and the customer-facing templates get 3 variants each. The card serves every "Hecho cuando" line of R1–R9. The safety rules stay untouched: 06 R1, R2/R3, R4, R5, R6, R8 and R11.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The next-step offer and the replacement eligibility depend on `get_block_origin`, not on raw status. `customer_block` or expired → replacement. `customer_lock` → unlock. `bank_side`, card `Suspended` or `Closed` → talk to a person. The rule lives in `policies/card_select.yaml` under `replacement.eligible_origins`. | Human Q1 (a). Keeps D13 and `02` §4.7/§4.9. 06 R8. |
| D2 | `tools.yaml`: `cards.get_block_origin.allowed_intents` adds `card_status` and `card_block`. This change is **safety-critical**, so the other dev reviews it (ADR-018). | Human Q1 (a). |
| D3 | History and summary live in the checkpointed graph state. A `summarize` node runs before `understand`, only when messages have left the 6-message window. It uses Haiku 4.5, temperature 0, prompt `summary@v1`, and is a new `core/llm` step `summary`. | Human Q2 (a). 06 R7. |
| D4 | `02` §2's "one call per turn" note is amended: the NLU is still one call, and a turn may also make one `summary` call. | Human Q2 (a). |
| D5 | If the summary call fails, after `core/llm`'s bounded retries the turn continues with the last 6 messages and the previous summary. The failure is recorded in `llm_calls`. There is no handoff. | Assumption 5, not objected. 06 R11. |
| D6 | The NLU gets history as masked text inside a data fence (`nlu@v6`). | Assumption 3. `02` §2 ("last N masked turns"). 06 R5, R6. |
| D7 | `compose` gets history with code-formatted values replaced by a neutral marker: every digit run, money figure, date and card mask. Shipped as `compose@v10`. | Assumption 4. 06 R4. `compose.py`'s rule that "values never reach the LLM". |
| D8 | The window counts customer and Cardy messages only. Agent, welcome and system messages are left out. A turn without typed text adds only Cardy's reply. | Assumption 2. |
| D9 | A new `card_hint` value, `"focus"`, is resolved in code to the persisted `selected_card_id` and checked against `list_cards()`. A focus id that is missing or not in the list → treated as no hint. An ambiguous reference → the NLU returns no hint → the picker shows. | Human Q3 (a). 06 R1. |
| D10 | A new `Topic` value, `new_card`, plus a `scope.yaml` entry: `kind: out_of_scope`, `reason_key: new_card_not_available`, `closest_intents: []`, `offer_human: false`. Each `scope.yaml` entry gains an optional `offer_human: bool = true`. | Human Q4 (a). R6. |
| D11 (amended) | A verified permanent block keeps its existing replacement offer. R7's closing question and buttons follow **every** verified action (lock, unlock, replacement, dispute claim) and a declined replacement offer. *Was:* only lock, unlock and replacement. **Superseded by D29** for when the closing appears; the replacement offer after a permanent block still stands. | Human Q5 (a), `02` §4.6. Amended by a mid-card human decision. |
| D12 | R9 variants: N = 3 per language. They apply only to the conversational, customer-facing templates (list under Contracts). Labels, goals, footnotes and agent-facing texts keep one version. | Human Q6 (a). |
| D13 | Variants are chosen through an injectable RNG. Tests seed it or check that the output is one of the variants. | Assumption 10. |
| D14 | The R4 offer is a fixed template that code appends after the `compose` draft. It opens a yes/no pause: replacement uses the existing `replacement.offer` pause, unlock uses a new `card_unlock.offer` pause, and talk-to-a-person uses `ui.quick_replies` with the human option. | Assumption 7. 06 R8. |
| D15 | R7's buttons use `ui.quick_replies` with a new `slot: "closing"`. A tap sends the label as text into the `smalltalk.anything_else` pause. "Terminar" → `_close()`. "Algo más" → `ask_what_else`. | Assumption 9. |
| D16 | R3 strips the option lists from the selection texts only. The picker and list payloads don't change. | Assumption 8. |
| D17 | Baseline: it shares all the flow changes, gets no history or summary, and its `lexicon.yaml` gains `new_card` keywords. | Assumption 6. `02` §3 "Baseline". |
| D18 | The address-entry turn (`awaiting_slot = "address"`) is never appended to `history`. | Planner A1, human. |
| D19 | The R4 next-step offer appears only on a `card_status` answer, never on `balance_due`. | Planner A2, human. |
| D20 | `finish` lives in `nodes/next_intent.py`. The `card_select` policy loader stays in `flows/card_select.py`. | Planner A3, human. |
| D21 | The decline-54 `next_step` chip is relabeled "Reponer mi tarjeta" (ES) and "Repor meu cartão" (PT). | Plan Q3, human. |
| D22 | A "no" to an unlock or block offer shows the closing question with the "Algo más"/"Terminar" chips. | Plan Q2, human. |
| D23 | A "sí" to `replacement_needs_block` takes the normal `card_block` path. When no card is in focus, the picker comes first. | Plan Q1, human. |
| D24 | Queued intents run before the R7 closing. The closing appears once the queue has drained, in the same turn, if the turn had a verified action (`finish._owes_closing`). The closing text is "¿Te ayudo con algo más o damos por terminada la conversación?", with 3 variants per language. | Mid-card human decision. |
| D25 | Every ES out-of-scope variant uses the first-person "puedo". The R8 tone is carried both by the `compose@v10` abstain guidance and by the `abstain_fallback` variants. Chip labels are never listed in the text. | Mid-card human decision. R8. |
| D26 | An Active card with `locked=true` is labeled "Locked" ("Bloqueada temporalmente" / "Bloqueado temporariamente") in the `card_status` reply and in the picker. The label is display-only, formatted in code (06 R4), and never used as a status for policy. | Mid-card human decision. |
| D27 | Block picker: lists only Active cards with no lock, via `card_select.yaml` v3 section `card_block: {eligible_statuses: [Active], exclude_locked: true}`. One eligible card → straight to the temporary/permanent question. None eligible → `block_none_eligible` + the closing. A named blocked or locked card still gets `already_in_state` + the offer. | Post-gate human decision. 06 R8. |
| D28 | `new_card_not_available` is warmer. Its 3 variants per language say the service is not available for now. | Post-gate human decision. |
| D29 | The closing question always ends a finished flow turn (a verified action, a cancelled confirmation, an answered query, a declined offer), decided by `_closing_allowed` in `nodes/next_intent.py`. It is skipped when: a pending is set, the queue is not empty, there is an escalation, a handoff or human mode, the turn already has quick_replies, or the turn is smalltalk, abstain, new_card, `tx_search_ask_criterion` or `injection_suspected`. Supersedes D11 and its amendments, D22 and D24's `_owes_closing` trigger. D24's text and its 3 variants stand. | Post-gate human decision. |

## Contracts (delta only)

**Graph state** (`state.py` `TurnState`, checkpointed):
```python
class HistoryMessage(TypedDict):
    role: Literal["customer", "cardy"]
    text: str            # masked: state["user_text"] or the masked reply
history: NotRequired[list[HistoryMessage]]   # last 6 kept; older ones folded into summary
summary: NotRequired[str | None]             # masked, LLM-written, R5-checked by core/llm
```
- `load_session` appends `{"customer", user_text}` when the turn has typed text.
- `finish` appends `{"cardy", reply}` (the masked reply).
- `summarize` pops whatever goes past 6 and folds it into `summary`.
- `smalltalk._close` clears `history` and `summary`, the same way it already clears `selected_card_id`.

**Context builder** (pure, `conversation/context.py`):
- `build_context(history, summary) -> ConversationContext{messages: list[HistoryMessage], summary: str | None}`
- `redact_values(text) -> str`, used for D7.
- Both `understand` (`run_nlu(..., context=...)`) and `compose_checked(..., context=...)` take it.

**LLM step** (`core/llm/registry.py`):
- `Step` adds `"summary"`. Model: `claude-haiku-4-5-20251001` / `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Temperature 0.0.
- New prompt `prompts/summary@v1.md`, with ES and PT examples.

**NLU** (`schemas.py`, `04` §2):
- `NLUSlots.card_hint` pattern becomes `^(credit|debit|focus|last4:\d{4})$`.
- `Topic` adds `"new_card"`.
- Prompt bump to `nlu@v6`.

**Policy:**
```yaml
# policies/card_select.yaml  (version: 2)
replacement:
  eligible_origins: [customer_block]   # plus expired, checked in code against local_today (D13)
next_step_offer:                       # R4 table, read by card_info and card_block
  customer_block: replacement
  customer_lock: unlock
  bank_side: human
  suspended: human
  closed: human
# policies/scope.yaml (version: 2)
  new_card: {kind: out_of_scope, reason_key: new_card_not_available, closest_intents: [], human_queue: atencion, offer_human: false}
# policies/tools.yaml
  cards.get_block_origin: {..., allowed_intents: [card_status, card_block, card_unlock, replacement_request]}
```

**UI** (`ui.py` `QuickRepliesPayload.slot`, `frontend/src/lib/sse.ts`, `04` §"SSE"): the slot adds `"closing"`. The options are "Algo más"/"Terminar" (ES) and "Mais alguma coisa"/"Encerrar" (PT).

**Templates** (`templates.py`):
- `get_template(kind, language, rng=random)` returns one variant. `_TEMPLATES` values become `list[str]` for the varied kinds.
- New kinds: `closing_question`, `offer_unlock`, `offer_human`, `replacement_needs_block` (R5.4, offers a block), `new_card_not_available`.
- Varied kinds (N = 3): `ask_which_card_*`, `decline_pick_ask`, `tx_search_pick_ask`, `tx_explain_pick_ask`, `dispute_transactions_prompt`, `clarify_lock_vs_block`, `action_confirm`, `action_done`, `action_done_noref`, `action_cancelled`, `already_in_state`, `offer_replacement`, `offer_unlock`, `offer_human`, `replacement_declined`, `replacement_not_eligible`, `replacement_needs_block`, `new_card_not_available`, `closing_question`, `abstain_fallback`, `anything_else`, `ask_what_else`, `farewell`, `fallback`, `tool_error`, `failure_handoff`, `failure_handoff_after_action`, `clarification_exhausted`, `nothing_pending`, `pending_reminder`, `injection_suspected`, `unsupported_intent`, `escalation_handoff`, `no_cards`.

**Flow behavior:**
- `card_block`: card picked → `get_card_details`. If the card is already Blocked or Closed → `already_in_state` + the R4 offer, with no `block_kind` question. If it is already locked and the kind is unknown or temporary → the same, with the unlock offer. Only then `_ask_block_kind`.
- `card_info`: on a `card_status` answer only (D19), for a card that isn't active (Blocked, locked, Suspended or Closed), append the D14 offer after the draft, then "¿o te ayudo con algo más?". A locked Active card shows the "Locked" label (D26).
- `replacement`: the picker lists only eligible cards. One eligible card → straight to `address_confirm`. None, or the customer names an ineligible active card → `replacement_needs_block` + offer `card_block` (a pause). A named bank-side card → `offer_human`.
- Closing (D29): `_closing_allowed` decides; when it allows, the turn gets `closing_question` + `ui.quick_replies{slot: closing}` + the `smalltalk.anything_else` pause. The `card_block` picker follows D27. A "sí" to `replacement_needs_block` enters `card_block`, with the picker first if no card is in focus (D23).

## Touch map

- `backend/app/core/llm/registry.py`: the `summary` step.
- `backend/app/domains/conversation/`:
  - `state.py`, `graph.py` (`summarize` node before `understand`, baseline skips it), `context.py` (new).
  - `nodes/summarize.py` (new), `nodes/understand.py`, `nodes/compose.py`, `nodes/abstain.py` (`offer_human`), `nodes/load_session.py`, `nodes/smalltalk.py`.
  - `finish` in `nodes/next_intent.py` (D20, D24).
  - `schemas.py`, `templates.py`, `ui.py`.
  - `flows/card_select.py` (eligibility filter + `focus` resolution), `flows/card_info.py`, `flows/card_block.py`, `flows/card_unlock.py` (offer pause), `flows/replacement.py`.
  - `prompts/nlu@v6.md`, `prompts/compose@v10.md`, `prompts/summary@v1.md`.
  - `baseline/lexicon.yaml`, `baseline/keyword_nlu.py`.
- `backend/app/domains/policy/`: the loaders for the new `card_select` and `scope` fields.
- `policies/card_select.yaml`, `policies/scope.yaml`, `policies/tools.yaml` (safety-critical, ADR-018 review).
- `frontend/src/lib/sse.ts`, `frontend/src/components/chat/QuickReplies.tsx`: the `closing` slot. Regenerate the API client if schemas changed.
- Docs:
  - `02` §2: one NLU call + an optional summary call; history input.
  - `02` §4.6, §4.9: state check first; replacement eligibility + picker filter.
  - `02` §5: the new_card abstain.
  - `04` §2: `card_hint` `focus`, `Topic` `new_card`.
  - `04` §5: the `card_select`, `scope` and `tools` YAML.
  - `04` §"SSE": `slot: closing`.
- `eval/scenarios/dev/`: update a scenario only if it depends on old wording or old routing. Never `heldout/`.
- Tests: `backend/tests/unit/` (list below).

## Test list (fake LLM only)

1. `test_context_window_and_summary`: with ≤6 messages, the NLU and `compose` user messages carry those messages and no summary. With 8 messages, they carry the last 6 plus the summary, and `summarize` ran exactly once. (R1 Hecho 1)
2. `test_r5_history_prompts_masked`: a conversation whose raw text has PII. The prompts sent by `understand`, `summarize` and `compose` contain only tokens (`find_pii` finds nothing), and the `compose` prompt contains no digit. (R1 Hecho 2, 06 R5, D7)
3. `test_r1_focus_hint_never_crosses_customer`: `card_hint=focus` with a `selected_card_id` not in this session's `list_cards()` → picker, no other customer's card. (06 R1, D9)
4. `test_r6_summarize_has_no_write_tools`: extends the existing graph-construction check in `test_r6_no_write_tools_in_llm_nodes.py` to cover `summarize`. (06 R6)
5. `test_r11_summary_failure_degrades`: the summary LLM raises → the turn still replies, using the last 6 messages, with no handoff. (06 R11, D5)
6. `test_focus_already_blocked_offers_replacement[es,pt]`: example 2. Status of a `customer_block` card, then "quiero bloquearla" (`focus`) → `already_in_state` + replacement offer, no `card_picker`, no `block_kind` quick replies. (R2, R4 Hecho, ES+PT happy path for card_block)
7. `test_status_offer_by_origin`: parametrized over `customer_lock` → unlock, `bank_side` → human, and a Closed card → human, after a `card_status` answer. (R4 Hecho, ex. 3/4)
8. `test_selection_text_has_no_options`: every `ask_which_card_*` and pick-prompt reply contains none of its picker labels. (R3 Hecho)
9. `test_replacement_single_eligible_skips_picker[es,pt]` (ex. 5) and `test_replacement_active_card_offers_block` (ex. 7, no `address_confirm`). (R5 Hecho, ES+PT happy path for replacement)
10. `test_new_card_not_replacement[es,pt]`: NLU `topic=new_card` → the `replacement` flow never runs, and there is no human chip. (R6 Hecho)
11. `test_closing_after_action`: a verified action, a cancelled confirmation, an answered query and a declined offer each end with `closing_question` + `slot: closing`. None appears with a pending set, a non-empty queue, a handoff, or on smalltalk, abstain or new_card. "Terminar" → `conversation_closed`. (R7 Hecho, D29)
12. `test_abstain_warm_keeps_chips[es,pt]`: example 9 (loans) and example 10 (`other`) keep the action and human chips. The `abstain_fallback` variants are first person. (R8 Hecho)
13. `test_template_variants_format`: every varied kind has ≥3 variants per language, no digits, and the same placeholder set across variants and languages. (R9 Hecho; no such test exists today, so this one adds it)

## Boundaries

- **Always:**
  - `customer_id` from the session.
  - Writes only through `ConfirmedWriteTools` with a token and a read-back.
  - Values formatted in code.
  - History and summary are masked only, and never a source of figures.
  - Prompt version bumps.
  - ES + PT for every new text.
- **Ask first:**
  - Any `tools.yaml` change beyond D2.
  - Changing `selected_card_id` reset semantics beyond `_close`.
  - Changing the window size or summary trigger.
  - Touching dev scenarios beyond wording or routing updates.
- **Never:**
  - Edit `eval/scenarios/heldout/`.
  - Put the eligibility or offer rules in a prompt.
  - Give `summarize`, `understand` or `compose` any write tool.
  - Send `content` (unmasked) to an LLM.
  - Add a human chip to `new_card`.

## Success criteria

1. `uv run pytest backend/tests/unit -k "context_window or r5_history or r1_focus or r6_summarize or r11_summary or focus_already or status_offer or selection_text or replacement_single or replacement_active or new_card or closing_after or abstain_warm or template_variants"` passes.
2. `make check` is green, including import-linter and mypy.
3. `policies/tools.yaml` lists `card_status` and `card_block` under `cards.get_block_origin.allowed_intents`. The PR is flagged safety-critical for review.
4. `policies/card_select.yaml` has `replacement.eligible_origins` and `next_step_offer`. `policies/scope.yaml` has `new_card` with `offer_human: false`. Both files keep their `provenance` header.
5. `prompts/summary@v1.md`, `nlu@v6.md` and `compose@v10.md` exist. `core/llm/registry.py` pins `summary` to Haiku 4.5 at temperature 0.
6. `02` §2, §4.6, §4.9, §5 and `04` §2, §5, "SSE" reflect the deltas above.
7. `git diff --stat main -- eval/scenarios/heldout/` is empty.
8. In the web chat, a verified lock shows the "Algo más"/"Terminar" chips, and "Terminar" ends the conversation (manual check or the existing Playwright e2e).

## Open questions

- The PT texts for the new variants and the `closing` chip labels need a native speaker's review (R9.4). Owner: the team, outside this card.
- R9.4 itself is still open: the requirements doc leaves the PT review to a native speaker, after this card.
