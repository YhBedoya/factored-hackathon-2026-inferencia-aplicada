# Plan: personalidad-cardy — Cardy propositiva, cercana y amable

Spec: [`docs/specs/personalidad-cardy.md`](../specs/personalidad-cardy.md) · Branch: `feat/personalidad-cardy` (stacked on `feat/naturalidad-cardy`) · Source: [`docs/requirements/personalidad-cardy.md`](../requirements/personalidad-cardy.md)

## Pending human answer (planner question Q1)

The spec's D4 enqueues an accepted suggestion with `card_hint="focus"`, but `unrecognized_charge` calls `select_card` **without** `focus_card_id` (`flows/unrecognized_charge.py:116`), so `focus` acts as no hint there, and a customer with two or more cards gets the picker after "sí" to the `unrecognized_charge` suggestion. The spec's touch map doesn't name that file.

This plan is drafted on the recommended option **(a)**: T5 passes `focus_card_id=state.get("selected_card_id")` in `unrecognized_charge._select_card` (one line, no new test, because `select_card`'s `focus` resolution is already R1-tested). If the human picks **(b)** (leave `unrecognized_charge` as is, so the picker shows on multi-card customers), delete that bullet and the file from T5. Nothing else changes.

Execution model: tasks in the same wave run at the same time **in one shared checkout** (no worktrees, no branches, no commits; the orchestrator commits). Within a wave no two tasks touch the same file.

## Facts checked against the repo

**Baseline (HEAD `9aeeb75` on `feat/personalidad-cardy`; stack containers up: `latam-cs-{backend,postgres,redis,nginx,frontend}-1`):**
- `cd backend && uv run pytest tests/unit -q` → **205 passed** (about 22 s). Any new failure belongs to the task that caused it.
- **No migration, no new dependency, no lockfile change.** Both new state fields live in the LangGraph checkpointed state. No task runs alone.
- `docs/requirements/personalidad-cardy.md` and `docs/specs/personalidad-cardy.md` are untracked. The orchestrator commits them with the card (D15). No task touches them.
- `eval/scenarios/dev/` has no "Terminar", "Algo más", "Encerrar" or "terminada": **no dev scenario needs an update**. Never touch `eval/scenarios/heldout/`.

**Commands and conventions:**
- Backend commands run as `cd backend && uv run …`. There is no pytest-asyncio, so drive coroutines with `asyncio.run(...)`. Lint each touched file explicitly: `uv run ruff check <files> && uv run ruff format --check <files> && uv run mypy <py files>`.
- Frontend: `MSYS_NO_PATHCONV=1 docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/lib/sse.ts && npm run typecheck"`. Checkouts are CRLF and biome rejects CRLF, so normalize touched frontend files to LF. `frontend/src/client/` (generated) has **no** `QuickRepliesPayload` type, so **no `make client` regeneration** is needed. `sse.ts:16` is the only frontend reference to the `"closing"` slot.
- Never `git add`, commit or push.

**Where things really are (the spec's touch map is approximate on these):**
- The `card_select` policy loader (`CardSelectPolicy`, `load_card_select_policy`) lives in `backend/app/domains/conversation/flows/card_select.py`, **not** in `domains/policy/`. The model is `extra="forbid"`, so the YAML's new `closing_suggestion` section and the model's new field must land together. `domains/policy/registry.py` only checks `card_select.yaml`'s header (`extra="allow"`), so it needs no change. `load_card_select_policy()` re-reads the file on each call (no cache).
- `select_card(cards, hint, failures, policy, language, *, focus_card_id=None, candidate_ids=None)` is pure. The `focus` branch is already there (naturalidad D9). `_resolve_hint` handles `credit`/`debit`/`last4:`. Callers passing `focus_card_id`: `card_info` (line 111), `card_block`, `card_unlock`, `replacement`. **Not** passing it: `decline_explain`, `unrecognized_charge` (see Q1).
- `NLUSlots.card_hint` pattern is at `schemas.py:60`: `^(credit|debit|focus|last4:\d{4})$`.
- Prompt pins: `nodes/understand.py:23` `_PROMPT = PromptRef("nlu", 6)`; `nodes/compose.py:53` `_PROMPT = PromptRef("compose", 10)`. `tests/unit/test_compose.py:65` asserts `call.prompt.label == "compose@v10"`. No test asserts the NLU label.
- Baseline NLU (`baseline/keyword_nlu.py`, `baseline/lexicon.yaml`) extracts **no `card_hint` at all today**. It fills only `topic` and `block_kind`. D12 adds the first hint, `other`. The lexicon's `thanks_close` ("terminar", "encerrar") and `affirm` ("algo mas", "mais alguma coisa") entries came from the old chips. They are harmless and stay.
- The closing today:
  - `flows/actions.py`: `CLOSING_PAUSE` (`smalltalk.anything_else`), `_CLOSING_OPTIONS`, `closing(language)` (returns `pending`, `segments=[closing_question]`, `ui=[quick_replies slot="closing"]`) and `with_closing(state, update)`.
  - `nodes/next_intent.py`: `_closing_update(state)` wraps `closing(...)`. `next_intent` calls it with the just-finished intent in `queue[0]`. `finish` calls it through `_owes_closing` (a verified action whose closing was held back; that closing is generic).
  - `closing(language)` is also called directly by `card_block.py:159,196`, `card_unlock.py:140` and `replacement.py:209`. Those callers read only `["segments"]`, so they need **no edit** as long as `closing()` keeps its `language` argument and its return keys `pending`/`segments`. Their closing is generic.
- `smalltalk.py` handles the `anything_else` pause (deny/thanks_close → `_close`; affirm → `ask_what_else`; a lone greeting answers and keeps the pause). `_close` resets turn state and emits `ConversationClosedEvent`. `route.py` sends a management-only turn to `smalltalk`. A card intent goes to `enqueue`, and `enqueue` clears any open `pending` (P1). `"anything_else"` is **not** in `route._CONFIRMATION_SLOTS`, so a bare "sí" in the closing pause reaches `smalltalk` today.
- Flows read the card hint from **`state["nlu"].slots.card_hint`**, not from `state["slots"]` (`card_info.py:87`, `tx_search._run_search`, `unrecognized_charge.py:107`). `load_session` resets `nlu` to `None` every turn.
- `tx_search`:
  - `_run_search` builds the filter with `build_tx_filter(slots, *, today, tz, language, cards, status=None)`. `tx_explain` also calls it, so new parameters are **keyword-only with defaults**.
  - `_narrow_card_id(cards, hint)` maps `focus` to `None` today.
  - With no criterion the flow returns `tx_search_ask_criterion` (a D29 no-closing kind).
  - The bank search is already newest-first, `LIMIT 10` (`tools/fakebank.py:404`, `transactions/repository.py:85`), so D6's "at most 10, newest first" needs no code.
  - FakeBank `search_transactions` raises `AccessDenied` for a foreign `card_id`, so D7's membership check must happen before the filter is built.
- `graph.py`:
  - `StateGraph(GraphState, input_schema=TurnInput, output_schema=TurnOutput)`. **A key not declared on `TurnInput` is not accepted as graph input**, so the D10 seed needs `introduced: NotRequired[bool]` on `TurnInput`.
  - `GraphState` holds graph-local per-turn flags such as `write_failed` and `actions_at_turn_start`, which `load_session` resets every turn.
- Runner (`runner.py`): `_run_turn` builds `config` (thread id = `conversation_id`) and calls `host.graph.astream({"user_text":…, "confirmation":…, "resume":…, "selection":…}, config=…)` at line ~300. `store.list_messages(conversation_id) -> list[MessageRow]` (`store.py:168`) returns rows with `.role`. The welcome is stored by `welcome.post_welcome` as `store.add_message(..., role="bot", ...)`. There is **no runner unit test** today.
- Templates (`templates.py`, 1477 lines): `TemplateKind` is a `Literal`; `_TEMPLATES` values are a string or a list of variants. `greeting`/`greeting_named` hold "Soy Cardy, de Swip" / "Sou a Cardy, do Swip". `closing_question` (line ~720) is the only kind with "terminada"/"encerrar a conversa". `WELCOME_BODIES`/`WELCOME_SALUTATIONS` are at line ~1394.
- `tests/unit/test_templates.py`: `_VARIED` (line 16) lists the varied kinds, including `closing_question`. `test_every_varied_kind_has_three_clean_variants` is at line 60.
- Test harness (`backend/tests/conftest.py`):
  - an autouse fixture forces **variant 0** of every varied kind (`_FirstVariant`);
  - `strip_closing(reply, language)` (line 105) asserts the reply ends with `"\n\n" + get_template("closing_question", …)` and strips it. Ten test files use it (`test_baseline`, `test_block_flows`, `test_card_info_flows`, `test_conversation_basics`, `test_decline_explain_flow`, `test_dispute_flows`, `test_graph`, `test_sandbox_conversations`, plus the direct `closing_question` users listed below);
  - `make_session(customer_id, fakebank_dir, llm)` gives `session.graph` and `session.config`. `graph.aupdate_state(config, {...})` after a first turn can seed checkpointed fields. `session.config["configurable"]["now"] = _CLOCK` pins the bank clock (`test_tx_search_flow.py:28`, `datetime(2026, 4, 2, 18, 0, tzinfo=UTC)`);
  - the `_nlu(language, intent, **slots)` helper pattern is in `test_state_offers.py:34`.
- Tests that assert the old closing directly:
  - `test_conversation_basics.py:172` (`closing_question`), `:181-243` (`_closing_chips`, `["Algo más","Terminar"]`, `["Mais alguma coisa","Encerrar"]`);
  - `test_state_offers.py:146,149,206,209` (`closing_question`, `slot == "closing"`, and "Terminar" as a typed reply at line 153);
  - `test_replacement_offers.py:67,91,111`;
  - `test_dispute_flows.py:174`.
- Tests that hard-code template text (relevant to the R5 tone pass):
  - `test_conversation_basics.py:64` and `test_sandbox_conversations.py:149` (`greeting_named` variant text);
  - `test_sandbox_conversations.py:72` (`"¿Sobre cuál tarjeta quieres saber?"`);
  - `test_block_flows.py:378` (`"¿Cuál tarjeta quieres bloquear?"`);
  - `test_unsupported_language.py:42-43` ("español o portugués" / "espanhol ou português");
  - `test_r3_flows.py:79-80` ("Listo" not in reply, "Atención" in reply);
  - `test_faults.py:281,323` (negative asserts "Não fiz nenhuma alteração", "bloqueada").
- Fixture customers (`backend/tests/fixtures/fakebank/products.csv`):
  - `CLI-TFTXSRC00007` has **exactly two cards**, credit `PRD-TFT7CRED0001` (•••• 7777, 2 transactions) and debit `PRD-TFT7DEBT0002` (•••• 7778, 1 transaction), both Active. This is example C (the spec's "9653" is not in the fixture) and the focus-card movements test;
  - `CLI-TFSINGLE0002` has one Active COP credit card, `PRD-TFS2CRED0001` (•••• 2222);
  - `CLI-TFMULTI00001` has credit 6475 Active, debit 1203 Active and debit 9001 Closed.
  - A "foreign" card for R1 tests is any other customer's id, e.g. `PRD-TFS2CRED0001` while the session is `CLI-TFTXSRC00007`.
- Docs to update: `02` §4.1 (`card_select`), §4.4 (`tx_search`), §4.6 (`card_block`, step 6 closing); `04` §2 (NLU output), §3 SSE (quick_replies slot union), §5 (the `policies/card_select.yaml (v3)` block at line ~258); `docs/brand.md` `## Personality` (line 22) and `## Voice and tone` (line 35).

**Names this plan fixes (binding on every task):**
- **Per-turn acceptance marker: `suggestion_accepted: NotRequired[bool]`, declared on `GraphState` in `graph.py`** (graph-local, beside `write_failed`). `load_session` resets it to `False` every turn. `enqueue` sets it `True` only when it consumes an accepted suggestion. Only `tx_search._run_search` reads it (D6). It is not on `NLUSlots` (the NLU contract in `04` §2 stays unchanged apart from `other`).
- Checkpointed `TurnState` fields (`state.py`): `closing_suggestion: NotRequired[Intent | None]` and `introduced: NotRequired[bool]` (spec §Contracts).
- `TurnInput.introduced: NotRequired[bool]` (`graph.py`) carries the D10 seed. The runner passes the key **only** with value `True`, and only when the checkpoint has no `introduced`. It never passes `False`.
- Template kinds: `closing_suggest_transaction_search`, `closing_suggest_unrecognized_charge`, `closing_generic`, `greeting_again` (`{customer_name}`), `greeting_again_plain`. The closing helper maps the suggested intent `X` to `closing_suggest_X` and maps `None` to `closing_generic`.
- `CardSelectPolicy.closing_suggestion: dict[Intent, Intent]`. A validator checks that every value is a key of `graph._INTENT_NODES` (an intent with a flow; importing it from `card_select.py` creates no cycle, because `graph.py` imports no flow module at load time).
- New test files: `test_other_card.py` (T2), `test_r1_other_focus.py` (T2 creates it, T5 extends it), `test_closing_suggestion.py` (T4 creates it, T5 extends it), `test_greeting_again.py` (T5).

## Components

- **Templates** (`backend/app/domains/conversation/templates.py`): five new varied kinds, the R5 tone pass, and the removal of `closing_question`. No dependencies.
- **"La otra" resolution** (`schemas.py`, `flows/card_select.py`): the `other` hint value and `select_card`'s D8 branch. Depends on the policy file for eligibility.
- **Policy** (`policies/card_select.yaml` v4 + `CardSelectPolicy`): the `closing_suggestion` table (D2). Depends on `graph._INTENT_NODES` for validation.
- **NLU** (`prompts/nlu@v7.md`, `nodes/understand.py`, `baseline/lexicon.yaml`, `baseline/keyword_nlu.py`): emits `card_hint=other` (D8, D12). Depends on the schema.
- **Closing writer** (`flows/actions.py`, `nodes/next_intent.py`, `ui.py`, `frontend/src/lib/sse.ts`, `state.py`): picks the kind from the policy, sets `closing_suggestion`, and emits no chips (D1, D3, D5). Depends on templates and policy.
- **Pause consumer** (`nodes/route.py`, `nodes/next_intent.enqueue`, `nodes/smalltalk.py`, `nodes/load_session.py`, `graph.py`): accepts, declines or replaces the suggestion (D4). Depends on the closing writer.
- **Focus-card search** (`flows/tx_search.py`): D6 and D7. Depends on the marker.
- **Re-greeting** (`state.introduced`, `finish`, `smalltalk` greeting, `runner._run_turn` seed): D10 and D11. Depends on templates.
- **Persona and docs** (`prompts/compose@v11.md`, `nodes/compose.py`, `docs/brand.md`, `02`, `04`): R6 and contract docs. Independent.

## Build order

1. **Templates, "la otra"/policy/NLU, persona/docs** in parallel (W1). They share no file, and each later step needs the new template kinds (T1) and the policy table (T2).
2. **Closing writer** (T4). It needs the `closing_suggest_*`/`closing_generic` kinds and `policy.closing_suggestion`. It removes `closing_question` and the chips, so every old-closing test is fixed in the same step.
3. **Pause consumer, focus search, re-greeting** (T5). It needs `closing_suggestion` to be set by T4 and the `greeting_again*` kinds from T1. It edits `next_intent.py`/`smalltalk.py`/`graph.py`, which T4 also touches, so it runs after T4.

## Touch map

| File | New / modified | Change | Task |
|---|---|---|---|
| `backend/app/domains/conversation/templates.py` | modified | new kinds, R5 tone pass | T1 |
| | | remove `closing_question` | T4 |
| `backend/tests/unit/test_templates.py` | modified | `_VARIED` gains the 5 new kinds | T1 |
| | | `_VARIED` drops `closing_question`; `test_no_procedural_closing_in_templates` | T4 |
| `backend/tests/unit/test_block_flows.py`, `test_sandbox_conversations.py`, `test_unsupported_language.py`, `test_r3_flows.py` | modified (only if T1 changes the asserted text) | hard-coded text → `get_template(...)` | T1 |
| `backend/tests/unit/test_conversation_basics.py` | modified | line 64 greeting text (if changed) | T1 |
| | | closing text and chips | T4 |
| `backend/app/domains/conversation/schemas.py` | modified | `card_hint` pattern adds `other` | T2 |
| `backend/app/domains/conversation/flows/card_select.py` | modified | `closing_suggestion` field + validator; `other` in `select_card` | T2 |
| `policies/card_select.yaml` | modified | `version: 4`, `closing_suggestion` | T2 |
| `backend/app/domains/conversation/prompts/nlu@v7.md` | new | v6 + `other` + ES/PT examples | T2 |
| `backend/app/domains/conversation/nodes/understand.py` | modified | `PromptRef("nlu", 7)` | T2 |
| `backend/app/domains/conversation/baseline/lexicon.yaml`, `baseline/keyword_nlu.py` | modified | `card_hints.other` terms → `card_hint="other"` | T2 |
| `backend/tests/unit/test_other_card.py` | new | tests 4, 5 | T2 |
| `backend/tests/unit/test_r1_other_focus.py` | new | test 6, `other` case | T2 |
| | | test 6, accepted-suggestion case | T5 |
| `backend/app/domains/conversation/prompts/compose@v11.md` | new | persona aligned with the 3 traits | T3 |
| `backend/app/domains/conversation/nodes/compose.py` | modified | `PromptRef("compose", 11)` | T3 |
| `backend/tests/unit/test_compose.py` | modified | label `compose@v11` | T3 |
| `docs/brand.md` | modified | Personality traits, "Cierre de un flujo" row | T3 |
| `docs/solution-docs/02-conversation-design.md` | modified | §4.1, §4.4, §4.6 | T3 |
| `docs/solution-docs/04-contracts.md` | modified | §2, §3 SSE, §5 | T3 |
| `backend/app/domains/conversation/state.py` | modified | `closing_suggestion`, `introduced` | T4 |
| `backend/app/domains/conversation/flows/actions.py` | modified | `closing(language, suggestion=None)`, `with_closing`, delete `_CLOSING_OPTIONS` | T4 |
| `backend/app/domains/conversation/nodes/next_intent.py` | modified | `_closing_update` policy lookup | T4 |
| | | `enqueue` acceptance; `finish` sets `introduced` | T5 |
| `backend/app/domains/conversation/ui.py` | modified | slot union drops `"closing"` | T4 |
| `frontend/src/lib/sse.ts` | modified | slot union drops `"closing"` | T4 |
| `backend/tests/conftest.py` | modified | `strip_closing` accepts the new closing kinds | T4 |
| `backend/tests/unit/test_state_offers.py`, `test_replacement_offers.py`, `test_dispute_flows.py` | modified | old closing text/chips | T4 |
| `backend/tests/unit/test_closing_suggestion.py` | new | test 1 | T4 |
| | | tests 2, 3 | T5 |
| `backend/app/domains/conversation/graph.py` | modified | `GraphState.suggestion_accepted`, `TurnInput.introduced` | T5 |
| `backend/app/domains/conversation/nodes/route.py` | modified | "sí" to a suggestion → `enqueue` | T5 |
| `backend/app/domains/conversation/nodes/smalltalk.py` | modified | D4 clears, D11 greeting | T5 |
| `backend/app/domains/conversation/nodes/load_session.py` | modified | reset `suggestion_accepted` | T5 |
| `backend/app/domains/conversation/flows/tx_search.py` | modified | `focus` (D7), marker as criterion (D6) | T5 |
| `backend/app/domains/conversation/flows/unrecognized_charge.py` | modified (Q1 = a) | pass `focus_card_id` | T5 |
| `backend/app/domains/conversation/runner.py` | modified | D10 seed helper | T5 |
| `backend/tests/unit/test_greeting_again.py` | new | test 7 | T5 |

## Risks and mitigations

- **`extra="forbid"` on `CardSelectPolicy`.** A YAML section the model doesn't declare fails every flow that loads the policy. *Mitigation (T2):* the YAML and the model change in one task, and the Verify calls `load_card_select_policy()`.
- **The validator imports `graph._INTENT_NODES` into `card_select.py`.** *Mitigation (T2):* the Verify imports `app.domains.conversation.graph` and `flows.card_select` and builds the graph (`build_graph(MemorySaver())`) in one command, so an import cycle shows up immediately.
- **Removing `closing_question` breaks ten test files through `strip_closing`.** *Mitigation (T4):* `strip_closing` accepts variant 0 of any of the three closing kinds and is updated in the same task, and T4's Verify runs every file that uses it.
- **The R5 tone pass silently changes text that tests hard-code, or drops a placeholder.** *Mitigation (T1):* the Facts list each hard-coded assert. T1 rewrites those asserts with `get_template(...)` only where it changes the text. `test_templates` checks placeholders and digits, and T1's Verify runs every file with a hard-coded assert.
- **Security templates change meaning** (06 R3; `injection_suspected`, `tool_error`, `failure_handoff*`, `escalation_handoff`; "Ask first"). *Mitigation (T1):* the acceptance limits the change to tone. `test_r3_flows` and `test_faults` are in T1's Verify.
- **A stale `True` marker makes a later typed search skip `tx_search_ask_criterion`.** *Mitigation (T5):* `load_session` resets `suggestion_accepted=False` every turn. Test 2's PT case is followed by a plain typed search turn to check this (see T5 acceptance).
- **`focus` or `other` resolves to another customer's card (06 R1).** *Mitigation:* T2 resolves `other` only over `list_cards()`, and T5 resolves `focus` only if its id is in `list_cards()`, before building the filter (FakeBank would raise `AccessDenied` otherwise). Test 6 covers both.
- **The D10 seed is dropped because `TurnInput` doesn't declare it, or is passed as `False` and overwrites a checkpointed `True`.** *Mitigation (T5):* `TurnInput.introduced` is added, the runner passes the key only when it is `True`, and test 7 drives `graph.ainvoke` with the key to prove the input is accepted.
- **An LLM call on the new paths (06 R6).** *Mitigation:* `next_intent`, `smalltalk`, `route` and `card_select` stay LLM-free. The existing `test_r6_no_write_tools_in_llm_nodes.py` covers them and runs in the final `make check`.
- **A policy suggestion with no template kind** (a future row added under "Ask first"). *Mitigation (T4):* the closing helper falls back to `closing_generic` for an intent with no `closing_suggest_<intent>` kind, so the reply never breaks.
- **An explicit card in the acceptance turn is overridden by `focus`** (for example "sí, los de la débito"). This is D4/D6 as written. T5 follows the spec, and the verifier can see it.

## Tests

| # | Test | File | Task |
|---|---|---|---|
| 1 | `test_status_closing_suggests_movements[es,pt]` | `test_closing_suggestion.py` | T4 |
| 2 | `test_accept_suggestion_lists_focus_movements[es,pt]` | `test_closing_suggestion.py` | T5 |
| 3 | `test_no_thanks_after_closing_closes[es,pt]` | `test_closing_suggestion.py` | T5 |
| 4 | `test_other_card_two_cards[es,pt]` | `test_other_card.py` | T2 |
| 5 | `test_other_card_three_cards_picker_excludes_focus` | `test_other_card.py` | T2 |
| 6 | `test_r1_other_and_focus_never_cross_customer`, `other` case | `test_r1_other_focus.py` | T2 |
| | same test, accepted-suggestion case | `test_r1_other_focus.py` | T5 |
| 7 | `test_greeting_after_welcome_no_self_intro[es,pt]` | `test_greeting_again.py` | T5 |
| 8a | `test_every_varied_kind_has_three_clean_variants` (existing; new kinds added) | `test_templates.py` | T1 |
| 8b | `test_no_procedural_closing_in_templates` | `test_templates.py` | T4 |

Success criterion 8 (examples A, B and C in the web chat) is a manual check for the verifier after `make check`.

## Tasks

- [ ] T1: Template kinds for the new closing and re-greeting, and the R5 tone pass
  - Depends on: nothing
  - Read exactly these: spec §Decisions D3, D11, D13 and §Contracts "Templates"; `docs/brand.md` §Personality and §Voice and tone; `backend/tests/unit/test_templates.py`
  - Acceptance:
    - `templates.py` adds the varied kinds `closing_suggest_transaction_search`, `closing_suggest_unrecognized_charge`, `closing_generic`, `greeting_again` and `greeting_again_plain`. Each has 3 ES and 3 PT variants with no digits and no figures.
      - The two `closing_suggest_*` kinds read like "¿Quieres que revisemos tus últimos movimientos o te puedo ayudar con algo adicional?" and offer reporting a charge the customer doesn't recognize, respectively.
      - `closing_generic` reads like "¿Te puedo ayudar con algo adicional?".
      - `greeting_again` uses `{customer_name}` ("¡Hola de nuevo, {customer_name}! Cuéntame, ¿en qué te ayudo con tus tarjetas?"); `greeting_again_plain` has no placeholder.
      - None of them contains "Soy Cardy" or "Sou a Cardy", and none reuses a `WELCOME_BODIES` text.
    - Every other customer-facing template is reviewed for tone (D13), with these limits:
      - same placeholders, and at least as many variants as today;
      - no digits;
      - security templates keep their meaning;
      - `greeting`/`greeting_named` keep the self-introduction.
      - **`closing_question` is left exactly as it is** (T4 removes it).
    - `_VARIED` in `test_templates.py` gains the five new kinds.
    - Wherever T1 changed a text that a test hard-codes (Facts, "Tests that hard-code template text"), that assert now compares against `get_template(...)`/`template_variants(...)` instead of a literal. The test keeps checking the same thing.
  - Verify: `cd backend && uv run pytest tests/unit/test_templates.py tests/unit/test_welcome.py tests/unit/test_conversation_basics.py tests/unit/test_sandbox_conversations.py tests/unit/test_block_flows.py tests/unit/test_unsupported_language.py tests/unit/test_r3_flows.py tests/unit/test_faults.py -q && uv run ruff check app/domains/conversation/templates.py tests/unit/test_templates.py && uv run ruff format --check app/domains/conversation/templates.py tests/unit/test_templates.py && uv run mypy app/domains/conversation/templates.py` (add any test file you edited to the ruff commands)
  - Files: `backend/app/domains/conversation/templates.py`, `backend/tests/unit/test_templates.py`, `backend/tests/unit/test_conversation_basics.py`, `backend/tests/unit/test_sandbox_conversations.py`, `backend/tests/unit/test_block_flows.py`, `backend/tests/unit/test_unsupported_language.py`, `backend/tests/unit/test_r3_flows.py` (the last five only if their asserted text changes)

- [ ] T2: "La otra" tarjeta (`card_hint=other`, NLU v7, baseline lexicon) and `card_select.yaml` v4 with `closing_suggestion`
  - Depends on: nothing
  - Read exactly these: spec §Decisions D1, D2, D8, D12 and §Contracts "NLU" and "Policy"; `backend/app/domains/conversation/flows/card_select.py`; `backend/tests/unit/test_state_offers.py` (the `_nlu` helper and `make_session`/`run_turn` usage to mirror)
  - Acceptance:
    - `schemas.py`'s `card_hint` pattern is `^(credit|debit|focus|other|last4:\d{4})$`.
    - `policies/card_select.yaml` has `version: 4`, keeps its `provenance` header and adds the D2 `closing_suggestion` mapping exactly as in spec §Contracts, with a comment.
    - `CardSelectPolicy.closing_suggestion: dict[Intent, Intent]` has a validator that rejects any value that is not a key of `graph._INTENT_NODES`.
    - `select_card` with `hint == "other"` (D8):
      - with `focus_card_id` in `cards`, the candidates are every card except the focus card, over every status (D12). Exactly one candidate gives `Selected`. Two or more give `Ask`, whose options are the eligible cards minus the focus card, with failures unchanged;
      - with the focus missing or not in `cards`, it is treated as no hint and no failure is counted (the same path as an unresolved `focus`).
    - `prompts/nlu@v7.md` is v6 plus the `other` value, with ES/PT examples ("y la otra", "el otro", "e a outra", "o outro"). `understand.py` pins `PromptRef("nlu", 7)`. `nlu@v6.md` is kept.
    - The baseline: `lexicon.yaml` gets a `card_hints: other: {es: [...], pt: [...]}` section ("la otra", "el otro", "a outra", "o outro", accent-free). `keyword_nlu` sets `slots.card_hint="other"` when one of these terms matches, alongside whatever intents and slots it already returns.
    - Tests written:
      - `test_other_card.py::test_other_card_two_cards[es,pt]`, graph-level on `CLI-TFTXSRC00007` with a scripted LLM. Turn 1 is `card_status` with `card_hint=credit`; turn 2 is `card_status` with `card_hint=other`. Turn 2 answers the status of `PRD-TFT7DEBT0002`, emits no `card_picker`, and leaves `selected_card_id == "PRD-TFT7DEBT0002"`.
      - `test_other_card.py::test_other_card_three_cards_picker_excludes_focus`: pure `select_card` over three Active `CardSummary` values with focus on one of them. The result is `Ask`, and its options don't include the focus card.
      - `test_r1_other_focus.py::test_r1_other_and_focus_never_cross_customer`, parametrized, with this task's case `other_foreign_focus`: pure `select_card(cards_of_customer, "other", 0, policy, lang, focus_card_id="<another customer's card id>")` returns only this customer's cards, either `Selected` with an own id or `Ask` with own options, and never the foreign id.
  - Verify: `cd backend && uv run pytest tests/unit/test_other_card.py tests/unit/test_r1_other_focus.py tests/unit/test_card_select.py tests/unit/test_state_offers.py tests/unit/test_baseline.py -q && uv run python -c "from langgraph.checkpoint.memory import MemorySaver; from app.domains.conversation.graph import build_graph; from app.domains.conversation.flows.card_select import load_card_select_policy as l; from app.domains.conversation.baseline.keyword_nlu import keyword_nlu as k; build_graph(MemorySaver()); p=l(); assert p.version==4 and p.closing_suggestion['card_status']=='transaction_search'; assert k('y la otra que estado tiene').slots.card_hint=='other'; assert k('e a outra?', 'pt').slots.card_hint=='other'" && uv run ruff check app/domains/conversation/schemas.py app/domains/conversation/flows/card_select.py app/domains/conversation/nodes/understand.py app/domains/conversation/baseline/keyword_nlu.py tests/unit/test_other_card.py tests/unit/test_r1_other_focus.py && uv run ruff format --check app/domains/conversation/schemas.py app/domains/conversation/flows/card_select.py app/domains/conversation/nodes/understand.py app/domains/conversation/baseline/keyword_nlu.py tests/unit/test_other_card.py tests/unit/test_r1_other_focus.py && uv run mypy app/domains/conversation/schemas.py app/domains/conversation/flows/card_select.py app/domains/conversation/nodes/understand.py app/domains/conversation/baseline/keyword_nlu.py`
  - Files: `backend/app/domains/conversation/schemas.py`, `backend/app/domains/conversation/flows/card_select.py`, `policies/card_select.yaml`, `backend/app/domains/conversation/prompts/nlu@v7.md` (new), `backend/app/domains/conversation/nodes/understand.py`, `backend/app/domains/conversation/baseline/lexicon.yaml`, `backend/app/domains/conversation/baseline/keyword_nlu.py`, `backend/tests/unit/test_other_card.py` (new), `backend/tests/unit/test_r1_other_focus.py` (new)

- [ ] T3: Brand personality, `compose@v11` persona and the contract docs
  - Depends on: nothing
  - Read exactly these: spec §Decisions D1, D4–D8, D14 and §Contracts; `docs/requirements/personalidad-cardy.md` R6 (the "así no / así sí" table); `backend/app/domains/conversation/prompts/compose@v10.md` (the persona block at the top)
  - Acceptance:
    - `docs/brand.md`:
      - `## Personality` lists Propositiva, Cercana and Amable, each with an "así no / así sí" example from R6.1;
      - `## Voice and tone` has a "Cierre de un flujo" row;
      - its Greeting example stays as the first-message introduction.
    - `prompts/compose@v11.md` is v10 with the persona block aligned to the three traits. It carries no suggestion table, no closing question and no "la otra" logic, and v10's hard rules are unchanged. `compose.py` pins `PromptRef("compose", 11)`. `test_compose.py:65` expects `compose@v11`. `compose@v10.md` is kept.
    - `02`:
      - §4.1 documents the `other` hint (D8);
      - §4.4 documents that an accepted suggestion is a focus-card search (D6, D7);
      - §4.6 step 6 describes the closing as one suggestion from policy, with no chips (D1, D4, D5).
    - `04`:
      - §2 shows the `card_hint` pattern with `other`;
      - §3 SSE drops `"closing"` from the quick_replies slot union;
      - §5 shows `card_select.yaml` v4 with `closing_suggestion`.
  - Verify: `cd backend && uv run pytest tests/unit/test_compose.py -q && uv run ruff check app/domains/conversation/nodes/compose.py tests/unit/test_compose.py && uv run ruff format --check app/domains/conversation/nodes/compose.py tests/unit/test_compose.py && uv run mypy app/domains/conversation/nodes/compose.py && grep -c "Propositiva\|Cercana\|Amable\|Cierre de un flujo" ../docs/brand.md && grep -n "other" ../docs/solution-docs/04-contracts.md | grep card_hint`
  - Files: `backend/app/domains/conversation/prompts/compose@v11.md` (new), `backend/app/domains/conversation/nodes/compose.py`, `backend/tests/unit/test_compose.py`, `docs/brand.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/04-contracts.md`

- [ ] T4: A closing that suggests the next step from policy, with no chips and no `closing_question`
  - Depends on:
    - T1: the kinds `closing_suggest_transaction_search`, `closing_suggest_unrecognized_charge` and `closing_generic`;
    - T2: `load_card_select_policy().closing_suggestion`.
  - Read exactly these: spec §Decisions D1, D3, D4 (setting side only), D5 and §Contracts "Graph state", "UI" and "Flow behavior"; `backend/app/domains/conversation/flows/actions.py` (`closing`, `with_closing`); `backend/app/domains/conversation/nodes/next_intent.py`
  - Acceptance:
    - `state.py` `TurnState` gains `closing_suggestion: NotRequired[Intent | None]` and `introduced: NotRequired[bool]`, each with a short comment (`introduced` is used by T5).
    - `actions.py`:
      - `closing(language, suggestion: Intent | None = None)` returns `{"pending": CLOSING_PAUSE, "closing_suggestion": suggestion, "segments": [<template>]}` with **no `ui`**;
      - the template is `closing_suggest_<suggestion>` when that kind exists, else `closing_generic`;
      - `_CLOSING_OPTIONS` is deleted;
      - `with_closing` uses `closing(language)` (generic) and forwards `closing_suggestion`.
      - `card_block.py`/`card_unlock.py`/`replacement.py` keep calling `closing(language)` unchanged.
    - `next_intent._closing_update(state)`: when D29 allows the closing (`_closing_allowed` unchanged), it looks up the just-finished intent (`queue[0]` in `next_intent`) in `load_card_select_policy().closing_suggestion` and returns the segment, `pending=CLOSING_PAUSE` and `closing_suggestion=<intent or None>`. It keeps the turn's existing `ui` events and adds none. The `finish` / `_owes_closing` path passes no intent, so that closing is generic.
    - `ui.py`: `QuickRepliesPayload.slot` is `Literal["block_kind", "abstain", "next_step"]`, and the docstring line about `"closing"` is removed. `frontend/src/lib/sse.ts:16` is the same union.
    - `templates.py`: `closing_question` is removed from `TemplateKind` and `_TEMPLATES`. `test_templates.py`: `_VARIED` drops it, and the new `test_no_procedural_closing_in_templates` asserts that no ES/PT variant of any kind contains "terminada" or "encerrar a conversa" (case-insensitive).
    - `conftest.strip_closing(reply, language)` asserts that the reply ends with `"\n\n"` plus variant 0 of `closing_generic`, `closing_suggest_transaction_search` or `closing_suggest_unrecognized_charge`, and strips it.
    - The old-closing tests are updated to the new behavior, without duplicating test 1:
      - `test_conversation_basics.py`: `:172` expects the right closing kind; `_closing_chips` and its two uses assert that **no** quick_replies event has `slot == "closing"`;
      - `test_state_offers.py`: `:146,206` use `closing_generic` variants; `:149,209` assert no closing chip; `:153` types "no, gracias" instead of "Terminar" (still NLU `thanks_close`);
      - `test_replacement_offers.py`: `:67,91,111`;
      - `test_dispute_flows.py`: `:174` (generic).
    - New `test_closing_suggestion.py::test_status_closing_suggests_movements[es,pt]` (test 1), on `CLI-TFSINGLE0002` with `card_status` and a scripted compose:
      - the reply ends with a `closing_suggest_transaction_search` variant and contains neither "terminada" nor "encerrar a conversa";
      - no `quick_replies` event has `slot == "closing"`;
      - the checkpointed `closing_suggestion == "transaction_search"` and `pending` is `smalltalk.anything_else`.
  - Verify: `cd backend && uv run pytest tests/unit/test_closing_suggestion.py tests/unit/test_templates.py tests/unit/test_conversation_basics.py tests/unit/test_state_offers.py tests/unit/test_replacement_offers.py tests/unit/test_dispute_flows.py tests/unit/test_block_flows.py tests/unit/test_card_info_flows.py tests/unit/test_decline_explain_flow.py tests/unit/test_baseline.py tests/unit/test_graph.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/state.py app/domains/conversation/flows/actions.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/ui.py app/domains/conversation/templates.py tests/conftest.py tests/unit/test_closing_suggestion.py tests/unit/test_templates.py tests/unit/test_conversation_basics.py tests/unit/test_state_offers.py tests/unit/test_replacement_offers.py tests/unit/test_dispute_flows.py && uv run ruff format --check <same files> && uv run mypy app/domains/conversation/state.py app/domains/conversation/flows/actions.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/ui.py app/domains/conversation/templates.py && ! grep -rniE "terminada|encerrar a conversa" app/domains/conversation/templates.py && ! grep -rn '"closing"' app/domains/conversation/ui.py ../frontend/src/lib/sse.ts && MSYS_NO_PATHCONV=1 docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/lib/sse.ts && npm run typecheck"`
  - Files: `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/flows/actions.py`, `backend/app/domains/conversation/nodes/next_intent.py`, `backend/app/domains/conversation/ui.py`, `frontend/src/lib/sse.ts`, `backend/app/domains/conversation/templates.py`, `backend/tests/conftest.py`, `backend/tests/unit/test_templates.py`, `backend/tests/unit/test_closing_suggestion.py` (new), `backend/tests/unit/test_conversation_basics.py`, `backend/tests/unit/test_state_offers.py`, `backend/tests/unit/test_replacement_offers.py`, `backend/tests/unit/test_dispute_flows.py`

- [ ] T5: Accepting or declining the suggestion (focus-card movements) and the re-greeting without a second introduction
  - Depends on:
    - T1: the kinds `greeting_again` and `greeting_again_plain`;
    - T2: `select_card` `focus`/`other`, the `test_r1_other_focus.py` file;
    - T4: `closing_suggestion` and `introduced` on `TurnState`, `CLOSING_PAUSE` set with `closing_suggestion` by every closing, `test_closing_suggestion.py`.
  - Read exactly these: spec §Decisions D4, D6, D7, D10, D11 and §Contracts "Flow behavior"; `backend/app/domains/conversation/nodes/smalltalk.py`; `backend/app/domains/conversation/flows/tx_search.py` (`_run_search`, `build_tx_filter`, `_narrow_card_id`)
  - Acceptance:
    - `graph.py`: `GraphState.suggestion_accepted: NotRequired[bool]` (graph-local, documented beside `write_failed`) and `TurnInput.introduced: NotRequired[bool]`. `load_session` writes `suggestion_accepted: False` every turn.
    - `route.py`: before the management-only step, a turn whose `pending.awaiting_slot == "anything_else"`, with a non-`None` `closing_suggestion`, `"affirm"` in the intents and no `"deny"`, returns `"enqueue"`.
    - `next_intent.enqueue` handles a consumed or replaced closing pause:
      - **Acceptance**, meaning the closing pause is open and either (`affirm` with a suggestion) or (the first NLU intent == `closing_suggestion`). It writes:
        - `intent_queue=[suggestion]`;
        - `nlu` replaced by a copy with `intents=[suggestion]` and `slots.card_hint="focus"`;
        - `suggestion_accepted=True`;
        - `closing_suggestion=None`;
        - the pause cleared, as today.
      - **Any other** enqueue that replaces the closing pause writes `closing_suggestion=None`.
    - `finish` writes `introduced=True` whenever it emits a non-empty reply outside human mode.
    - `smalltalk.py`:
      - inside the `anything_else` pause, `affirm` with `closing_suggestion=None` → `ask_what_else`, `pending=None`, `closing_suggestion=None`;
      - deny/thanks_close → `_close`, which also writes `closing_suggestion=None` and keeps `introduced`;
      - opening the plain `anything_else` pause (thanks with nothing pending) writes `closing_suggestion=None`;
      - a lone `greeting` with `state.get("introduced")` → `greeting_again` filled with `{customer_name}`, or `greeting_again_plain` with no name. With `introduced` false or absent → today's `greeting_named`/`greeting`.
    - `tx_search.py`:
      - `build_tx_filter(..., focus_card_id: str | None = None)` is keyword-only, so `tx_explain` is untouched;
      - `_narrow_card_id` resolves `focus` to `focus_card_id` only if that id is in `cards`, else `None` (D7);
      - `_run_search` passes `focus_card_id=state.get("selected_card_id")` and treats `state.get("suggestion_accepted")` as a criterion (D6). A typed search with no criterion still gets `tx_search_ask_criterion`.
    - (Q1 = a) `unrecognized_charge._select_card` passes `focus_card_id=state.get("selected_card_id")` to `select_card`.
    - `runner.py`:
      - a helper `async def _introduced_seed(graph, config, conversation_id) -> dict[str, bool]` returns `{"introduced": True}` only when the checkpoint (`graph.aget_state(config).values`) has no `introduced` and `store.list_messages(conversation_id)` holds a `role == "bot"` row; otherwise `{}`;
      - `_run_turn` merges it into the `astream` input. D8 (welcome kept out of history) is unchanged.
    - Tests written:
      - `test_closing_suggestion.py::test_accept_suggestion_lists_focus_movements[es,pt]` (test 2), on `CLI-TFTXSRC00007` with `configurable["now"]` pinned to `datetime(2026, 4, 2, 18, 0, tzinfo=UTC)`:
        - turn 1 is `card_status` with `card_hint=credit`; turn 2 is NLU `affirm`;
        - turn 2 emits a `transaction_list` whose every row is a `PRD-TFT7CRED0001` movement (its labels end in `•••• 7777`), with no `card_picker` and no `tx_search_ask_criterion`;
        - the PT case adds turn 3, `transaction_search` with no slots, which gets `tx_search_ask_criterion` (the marker doesn't leak).
      - `test_closing_suggestion.py::test_no_thanks_after_closing_closes[es,pt]` (test 3): after a closing, NLU `deny`/`thanks_close` → a `farewell` variant and `conversation_closed` in `debug.ui`.
      - `test_r1_other_focus.py`: a new parametrized case `accepted_suggestion_foreign_focus`. After turn 1 on `CLI-TFTXSRC00007`, seed `selected_card_id="PRD-TFS2CRED0001"`, `pending=CLOSING_PAUSE` and `closing_suggestion="transaction_search"` with `graph.aupdate_state`. "sí" then gives a search over the customer's own cards only: no `TFS2` id, no `2222` mask, no `AccessDenied`.
      - `test_greeting_again.py::test_greeting_after_welcome_no_self_intro[es,pt]` (test 7):
        - (i) `graph.ainvoke({"user_text": "Hola Cardy", "confirmation": None, "resume": None, "selection": None, "introduced": True}, config)` with NLU `greeting` → a `greeting_again` variant without "Soy Cardy"/"Sou a Cardy";
        - (ii) a fresh session's first greeting through `run_turn` → still `greeting_named`;
        - (iii) `_introduced_seed` with `store.list_messages` monkeypatched to one `role="bot"` row → `{"introduced": True}`, and with no rows → `{}`.
  - Verify: `cd backend && uv run pytest tests/unit/test_closing_suggestion.py tests/unit/test_r1_other_focus.py tests/unit/test_greeting_again.py tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py tests/unit/test_dispute_flows.py tests/unit/test_conversation_basics.py tests/unit/test_conversation_memory.py tests/unit/test_sandbox_conversations.py tests/unit/test_unsupported_language.py tests/unit/test_graph.py -q && uv run ruff check app/domains/conversation/graph.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/nodes/load_session.py app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/unrecognized_charge.py app/domains/conversation/runner.py tests/unit/test_closing_suggestion.py tests/unit/test_r1_other_focus.py tests/unit/test_greeting_again.py && uv run ruff format --check <same files> && uv run mypy app/domains/conversation/graph.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/nodes/load_session.py app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/unrecognized_charge.py app/domains/conversation/runner.py`
  - Files: `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/route.py`, `backend/app/domains/conversation/nodes/next_intent.py`, `backend/app/domains/conversation/nodes/smalltalk.py`, `backend/app/domains/conversation/nodes/load_session.py`, `backend/app/domains/conversation/flows/tx_search.py`, `backend/app/domains/conversation/flows/unrecognized_charge.py` (Q1 = a), `backend/app/domains/conversation/runner.py`, `backend/tests/unit/test_closing_suggestion.py`, `backend/tests/unit/test_r1_other_focus.py`, `backend/tests/unit/test_greeting_again.py` (new)

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3 | no | Three independent chains with disjoint files: templates and their text-asserting tests (T1); schema, `card_select`, policy, NLU prompt and baseline (T2); compose prompt and docs (T3). None adds a dependency or touches the stack. |
| W2 | T4 | no | Needs T1's closing kinds and T2's `closing_suggestion` table. It touches `templates.py`, `test_templates.py` and `test_conversation_basics.py` after T1 is done with them. |
| W3 | T5 | no | Needs T4's state fields and closing pause, T1's `greeting_again*` kinds and T2's R1 test file. It shares `next_intent.py` and `test_closing_suggestion.py` with T4, so it runs after it. |
