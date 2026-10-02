# State: personalidad-cardy — Cardy personality (proactive, close, kind)
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card personalidad-cardy (conversation, owner B) · requirements `docs/requirements/personalidad-cardy.md` · spec `docs/specs/personalidad-cardy.md` · plan `docs/plans/personalidad-cardy.md`
Branch `feat/personalidad-cardy`, based on `feat/naturalidad-cardy` (stacked, not merged).

## Conventions established for this card
- Backend: `cd backend && uv run …`; no pytest-asyncio, use `asyncio.run(...)`. Lint only touched files: `uv run ruff check <f> && uv run ruff format --check <f> && uv run mypy <py f>`.
- Frontend: biome via `docker exec -w /app latam-cs-frontend-1`; normalize touched frontend files to LF.
- Never `git add`, commit or push. No migration, no dependency, no lockfile change.
- Baseline unit suite before the card: 205 passed.
- `card_select` policy loader lives in `flows/card_select.py` (`extra="forbid"`: YAML section + model field land together).
- Example C fixture: `CLI-TFTXSRC00007` (credit •••• 7777, debit •••• 7778). Foreign card for R1 tests: `PRD-TFS2CRED0001`.
- Per-turn marker: `suggestion_accepted: NotRequired[bool]` on `GraphState` (graph.py); reset in load_session, set by enqueue, read only by tx_search.
- Prompts: `nlu@v7`, `compose@v11`.

## Human decisions taken mid-card
- Planner Q1 (T5): accepted unrecognized_charge suggestion starts on the focus card (option a; unrecognized_charge.py passes focus_card_id).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | aaf322d | 5 new kinds (3 ES+3 PT), tone pass; "terminada en" → "que termina en" |
| T2 | done | a83bfec | card_hint=other, nlu@v7, baseline hint, card_select.yaml v4 |
| T3 | done | a3adf3a | brand traits, compose@v11, 02/04 docs |
| T4 | done | a9d4b90 | policy closing suggestion, text only; closing slot + closing_question removed |
| T5 | done | a4b647b | accept suggestion → focus movements, re-greeting, introduced seed, R1 case |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T3 — Brand personality, compose@v11 and contract docs
Created: `backend/app/domains/conversation/prompts/compose@v11.md` (v10 + persona traits; v10 kept).
Changed: `compose.py` (`PromptRef("compose", 11)`), `test_compose.py:65`, `docs/brand.md`, `02` §4.1/§4.4/§4.6, `04` §2/§3/§5 (card_select v4 `closing_suggestion`).
Facts the next tasks need: 02 §4.4 numbering shifted (new step 3 = focus-card search, widen is 4, routing is 5); text doesn't depend on Q1.
Deviations: none.
Verify: test_compose 5 passed; ruff/format/mypy clean; brand grep 7; 04 card_hint line 72 shows `other`.

### T2 — "La otra" tarjeta (`card_hint=other`)
Created: `prompts/nlu@v7.md`, `tests/unit/test_other_card.py`, `tests/unit/test_r1_other_focus.py`.
Changed: `schemas.py` (pattern), `flows/card_select.py` (`other` branch; `closing_suggestion` field + validator, lazy import of `graph._INTENT_NODES`), `policies/card_select.yaml` (v4), `nodes/understand.py` (nlu@v7), `baseline/lexicon.yaml` (`card_hints`), `baseline/keyword_nlu.py` (wrapper adds `card_hint`).
Facts the next tasks need: `policy.closing_suggestion[intent]` is a `dict[Intent, Intent]`; `other` with only the focus card left, or no/foreign focus, acts as no hint.
Deviations: none.
Verify: 28 passed; build_graph/policy/baseline smoke ok; ruff check, format and mypy clean.

### T1 — Template kinds for closing and re-greeting, R5 tone pass
Changed: `backend/app/domains/conversation/templates.py` (5 new kinds in `TemplateKind` + `_TEMPLATES`, 3 ES + 3 PT each: `closing_suggest_transaction_search`, `closing_suggest_unrecognized_charge`, `closing_generic`, `greeting_again` ({customer_name}), `greeting_again_plain`); `backend/tests/unit/test_templates.py` (`_VARIED` +5).
Tone pass: "terminada en {card_last4}" -> "que termina en {card_last4}" everywhere (spec: no template contains "terminada"; only `closing_question`'s "terminada la conversación" remains, T4 removes it); warmer `no_cards`, `thanks_close`, `replacement_declined`, `back_with_cardy`, `already_in_state`.
Facts: no hard-coded test texts changed, so no other test file edited. Placeholders and variant counts untouched; `closing_question` untouched.
Deviations: none.
Verify: 8 test files -> 34 passed; ruff check/format --check and mypy clean.

### T4 — Closing that suggests the next step, no chips
Created: `backend/tests/unit/test_closing_suggestion.py` (test 1, ES+PT).
Changed: `state.py` (`closing_suggestion`, `introduced`), `flows/actions.py` (`closing(language, suggestion)`, no ui; `_CLOSING_OPTIONS` gone; `with_closing` generic + forwards `closing_suggestion`), `nodes/next_intent.py` (`_closing_update(state, finished=None)` reads `load_card_select_policy().closing_suggestion`), `ui.py` + `frontend/src/lib/sse.ts` (slot drops "closing"), `templates.py` (`closing_question` removed), `conftest.strip_closing` (accepts the 3 closing kinds), updated tests: templates, conversation_basics, state_offers, replacement_offers, dispute_flows.
Facts: `closing_suggestion` is not yet cleared on consume/replace/`_close` (T5). The lock-then-balance turn closes with `closing_suggest_transaction_search`.
Deviations: also edited `tests/unit/test_decline_explain_flow.py` (lines 84, 118) and `test_dispute_flows.py:198`: `debug.ui == ["quick_replies"]` became `[]` (the closing chips are gone); the decline file wasn't in Files but Verify runs it.
Verify: 78 passed; ruff check/format and mypy clean; greps ok; biome ci + `npm run typecheck` clean. No other frontend file uses the "closing" slot.

### T5 — Accepting the suggestion (focus movements) and re-greeting without a second intro
Created: `tests/unit/test_greeting_again.py` (test 7).
Changed: `graph.py` (`TurnInput.introduced`, `GraphState.suggestion_accepted`), `nodes/load_session.py` (reset), `route.py` (affirm + suggestion -> enqueue), `next_intent.py` (`enqueue` accept/clear; `finish` sets `introduced`), `smalltalk.py` (clears `closing_suggestion`, `greeting_again*`), `flows/tx_search.py` (`focus_card_id`, D6/D7), `flows/unrecognized_charge.py` (focus, Q1), `runner.py` (`_introduced_seed`, typed `TurnInput` for astream), tests: `test_closing_suggestion.py` (tests 2, 3), `test_r1_other_focus.py` (`accepted_suggestion_foreign_focus`).
Facts: `_introduced_seed` is called once per turn and only adds `introduced` to the input when truthy. Acceptance rewrites `nlu` (intents=[suggestion], card_hint=focus).
Deviations: none.
Verify: 11 test files -> 45 passed; ruff check/format and mypy clean.

### T2 repair — `other` with no eligible non-focus card
Changed: `flows/card_select.py` (`other` Ask only when eligible-minus-focus is non-empty; else treated as no hint, no failure), `tests/unit/test_other_card.py` (+1 test).
Verify: 3 files pytest passed; ruff check, format and mypy clean.
