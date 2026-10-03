# Plan: naturalidad-cardy — Cardy's conversation memory, state-first offers and warmer templates

Spec: [`docs/specs/naturalidad-cardy.md`](../specs/naturalidad-cardy.md) · Branch: `feat/naturalidad-cardy` · Source: [`docs/requirements/naturalidad-cardy.md`](../requirements/naturalidad-cardy.md)

## Settled after the spec gate (binding on every task)

The human answered the planner's three questions (option (a) on all three) and accepted assumptions A1–A3:

- **Q1 (T8).** "Sí" to the `card_block` offer that `replacement` opens through `replacement_needs_block` takes the normal `card_block` path on `selected_card_id`: state check, then the temporary-or-permanent question. With no card in focus, the picker (`_select_card`) comes first.
- **Q2 (T8, T9).** "No" to the unlock offer or the block offer shows the closing question with the "Algo más"/"Terminar" buttons (`closing(lang)`), the same as a declined replacement offer.
- **Q3 (T1).** The decline-54 chip `decline_replacement_option` is relabeled `"Reponer mi tarjeta"` / `"Repor meu cartão"`, so its tap still routes to `replacement_request` and never to `new_card`.
- **A1.** `load_session` never adds the replacement address turn (`pending.awaiting_slot == "address"`) to `history` (06 R5).
- **A2.** `card_info` makes the next-step offer only on the `card_status` intent (D2's allowlist has no `balance_due`).
- **A3.** `finish` lives in `nodes/next_intent.py`, and the card_select policy loader lives in `flows/card_select.py` (see Facts).

Execution model: tasks in the same wave run at the same time **in one shared checkout** (no worktrees, no branches, no commits; the orchestrator commits). Within a wave no two tasks touch the same file.

## Facts checked against the repo

**Baseline (HEAD `77d300d` on `feat/naturalidad-cardy`; stack containers up: `latam-cs-{backend,postgres,redis,nginx,frontend}-1`):**
- `cd backend && uv run pytest tests/unit -q` → **176 passed**. A new red belongs to the task that caused it.
- **This card has no migration and no new dependency.** History and summary live in the LangGraph checkpointed state (D3), not in Postgres.
- `main` is far behind this branch (`38d4d90`). Success criterion 7 (`git diff --stat main -- eval/scenarios/heldout/`) is still the right check, because nothing on this branch touches `heldout/`.

**Commands and conventions (still true, from earlier state files):**
- Backend commands run as `cd backend && uv run …`. There is no pytest-asyncio, so drive coroutines with `asyncio.run(...)`. Lint each touched file explicitly: `uv run ruff check <files> && uv run ruff format --check <files> && uv run mypy <py files>`.
- Frontend commands run in the container. Under Git Bash, use `MSYS_NO_PATHCONV=1 docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci <file> && npm run typecheck"`. Checkouts are CRLF and biome rejects CRLF, so normalize your own files to LF.
- `frontend/src/client/` (generated) has **no** `QuickRepliesPayload`/`NLUSlots` type. SSE UI events are hand-typed in `frontend/src/lib/sse.ts` (line 16: `slot: "block_kind" | "abstain" | "next_step"`). **No `make client` regeneration is needed.** `QuickReplies.tsx` never reads `slot`, so it needs **no change**, even though the spec's touch map names it.
- Never `git add`, commit or push. Never touch `eval/scenarios/heldout/`.

**Where things really are (the spec's touch map is approximate on these):**
- `finish` lives in `backend/app/domains/conversation/nodes/next_intent.py` (`def finish`), **not** in `graph.py`. `graph.py` only wires it.
- The `card_select` policy loader (`CardSelectPolicy`, `load_card_select_policy`) lives in `backend/app/domains/conversation/flows/card_select.py`, not in `domains/policy/`. `domains/policy/registry.py` validates `card_select.yaml` against a header-only model (`extra="allow"`), so new fields there need no registry change. The `scope` loader is `backend/app/domains/policy/scope.py` (`TopicScope`, `TOPICS`, `_every_topic_present`). `TOPICS` must stay equal to the YAML's topic keys.
- `select_card(cards, hint, failures, policy, language)` is pure. It is called by `card_info`, `card_block`, `card_unlock`, `replacement`, `decline_explain` and `unrecognized_charge`. New parameters must be **keyword-only with defaults**, so the last two flows stay untouched.
- `get_block_origin` is on `ConfirmedWriteTools` (`tools/executor.py:154`): `get_block_origin(card_id, intent)`. It raises `PolicyDenied("tool_not_allowed")` when `intent` isn't in `policies/tools.yaml` `cards.get_block_origin.allowed_intents`, which today is `[card_unlock, replacement_request]`. Flows read it as `config["configurable"]["bank_write_tools"]`. The R6 scan (`tests/unit/test_r6_no_write_tools_in_llm_nodes.py`) only flags modules under `nodes/` and `flows/` that **also import `app.core.llm`**. So `card_info.py` may read `bank_write_tools`, and `compose.py`, `understand.py`, `summarize.py` and `abstain.py` never may.
- Because of D2's allowlist, `card_info` calls `get_block_origin(card_id, "card_status")` **only on the `card_status` intent**. A `balance_due` turn gets no next-step offer. Widening the allowlist is "Ask first".
- The FakeBank origin (`tools/fakebank.py:517`):
  - `overlay.blocked` → `customer_block`;
  - `overlay.locked` → `customer_lock`;
  - customer not Active → `bank_side/customer_status`;
  - `days_past_due > 0` → `bank_side/past_due`;
  - status Blocked/Suspended → `bank_side/bank_status`;
  - otherwise `none`.
- `CardSummary` (`domains/cards/schemas.py:24`) has `status` and `locked` but **no expiry**. Expiry needs `get_card_details(card_id).expiration_date`, compared against `local_today(country)` as `replacement.py` already does.
- `user_text` in the graph is already masked by the runner (`runner.py:146`, `vault.mask`), and `reply` carries tokens until the runner unmasks it (`runner.py:369`). **Exception:** on the `replacement` address turn (`pending.awaiting_slot == "address"`, routed by `_entry` with no `understand`), `user_text` is the customer's raw new address, which `vault.mask` doesn't know.
- Button, selection and step-up turns reach the graph with `user_text == ""` (`runner.py:302`, `graph_text or ""`). A "typed" turn is one where `user_text` is non-empty and `confirmation`, `selection` and `resume` are all `None`.
- Template RNG pattern to mirror: `welcome.py` (`_Rng` protocol, `pick_body(..., rng)`, the module-level `random`).
- The quick-reply human chip already exists:
  - slot `"next_step"` with `get_template("tx_human_option", lang)` ("Hablar con una persona" / "Falar com uma pessoa");
  - the abstain human label is `abstain._HUMAN_OFFERS`.
  - Tapping a chip sends its label as text, which NLU routes as `human_request`.
- `abstain.py:123` compares `text == get_template("fallback", language)`. Once `fallback` has variants that equality is wrong, so T6 must replace it.
- Tests that assert old text and must change:
  - `test_block_flows.py:375,382` (`startswith("¿Cuál tarjeta quieres bloquear?\n")`);
  - `test_sandbox_conversations.py:72` (`startswith("¿Sobre cuál tarjeta quieres saber?\n")`);
  - `test_compose.py:65` (`label == "compose@v9"`).
- Test harness (`backend/tests/conftest.py`):
  - `ScriptedLLM` raises `AssertionError` when a step has no scripted output. Every existing test with 4 or more typed turns would therefore crash on the new `summary` step unless T1 gives `summary` a default.
  - `make_session(customer_id, fakebank_dir, llm)` gives `session.graph`, `session.config` and `session.overlay` (`.locked`/`.blocked` sets used to seed origins).
  - `graph.aupdate_state(config, {...})` can pre-seed checkpointed `history`/`summary`.
  - `InMemoryPiiVault` + `masking.mask_user_text` (see `tests/unit/test_r5_masking.py`) mask raw text the way the runner does.
- Fixture customers (`backend/tests/fixtures/fakebank/README.md`):
  - `CLI-TFMULTI00001` (MX): credit `PRD-TFM1CRED0001` ••6475, debit `PRD-TFM1DEBT0002` ••1203, **Closed** debit `PRD-TFM1DEBT0003` ••9001;
  - `CLI-TFSINGLE0002` (CO): credit `PRD-TFS2CRED0001` ••2222;
  - `CLI-TFBLOCKD0003` (AR): **Blocked** debit `PRD-TFB3DEBT0001` ••3333, origin `bank_side`.
- Prompts are new files per version (`prompts/__init__.py` `load_prompt`). Today `understand.py` pins `PromptRef("nlu", 5)` and `compose.py` pins `PromptRef("compose", 9)`.
- `core/llm/registry.py` has a `Step` Literal plus `MODEL_REGISTRY` and `TEMPERATURE` dicts. Haiku IDs are `claude-haiku-4-5-20251001` / `us.anthropic.claude-haiku-4-5-20251001-v1:0`. `StructuredLLMClient.structured` refuses a prompt that `find_pii` flags (`LLMUnmaskedInput`, an `LLMError`) and records failures in `llm_calls`.
- `route.py` `_CONFIRMATION_SLOTS` lists which `awaiting_slot`s an affirm/deny answers: `confirmation`, `address_confirm`, `offer_replacement`, `card_possession`, `dispute_question`. The new offer pauses must be added there or a "sí" won't reach the flow.
- `smalltalk._ANYTHING_ELSE` is `{"flow": "smalltalk", "node": "anything_else", "awaiting_slot": "anything_else"}`. With that pause open, `thanks_close`/`deny` → `_close` (farewell + `ConversationClosedEvent`) and `affirm` → `ask_what_else`. R7's buttons reuse this unchanged.
- Baseline lexicon: `replacement_request` contains `"nueva tarjeta"` and `"novo cartao"`, and there is no `affirm` intent. `keyword_nlu` only checks `out_of_scope` when no intent matched. So for `new_card` to win, the `replacement_request` terms must go.

**Settled shapes every task must use (planner-fixed names, so parallel tasks agree):**
- **Pauses.** Replacement offer: the existing `{"flow": "replacement", "node": "offer", "awaiting_slot": "offer_replacement"}`. Unlock offer: `{"flow": "card_unlock", "node": "offer", "awaiting_slot": "offer_unlock"}`. Block offer: `{"flow": "card_block", "node": "offer", "awaiting_slot": "offer_block"}`. Closing: `smalltalk._ANYTHING_ELSE`.
- **Closing chip labels** (fixed, one version, D12): ES `"Algo más"` / `"Terminar"`, PT `"Mais alguma coisa"` / `"Encerrar"`, sent as `QuickRepliesPayload(slot="closing", …)`.
- **Next-step offer kinds:** `"replacement" | "unlock" | "human"`. The human offer is `ui.quick_replies` with `slot="next_step"` and the one `tx_human_option` label, and no pause.
- **Hidden fact `next_step_offer`** (value = offer kind, plus `card_mask` already in facts). It is how `card_info` asks `compose`/`baseline_compose` to append the offer text after the draft. The pause and chips are returned by `card_info` itself.
- **History pieces:**
  - `HistoryMessage{role: "customer" | "cardy", text}`;
  - `TurnState.history`, `TurnState.summary`;
  - `context.build_context(history, summary) -> ConversationContext(messages, summary)` and `context.redact_values(text)`;
  - `WINDOW = 6` in `context.py`;
  - the summary node's output schema is `SummaryDraft{text: str}`, defined in `nodes/summarize.py`.

## Components

| Component | Where | Depends on |
|---|---|---|
| Template variants + new kinds | `backend/app/domains/conversation/templates.py` | — |
| Test harness defaults (pinned template RNG, default `summary` output) | `backend/tests/conftest.py` | templates RNG hook |
| `card_select` policy v2 + `focus` + replacement candidate set + offer resolver | `policies/card_select.yaml`, `flows/card_select.py` | — |
| NLU contract (`card_hint` `focus`, `Topic` `new_card`) | `conversation/schemas.py` | — |
| Tool allowlist (D2, safety-critical) | `policies/tools.yaml` | — |
| `summary` LLM step | `core/llm/registry.py`, `prompts/summary@v1.md` | — |
| History state + context builder | `conversation/state.py`, `conversation/context.py` (new) | — |
| `summarize` node | `conversation/nodes/summarize.py` (new) | state, context, registry |
| Memory wiring (append, fold, clear) | `graph.py`, `nodes/__init__.py`, `nodes/load_session.py`, `nodes/next_intent.py` (`finish`), `nodes/smalltalk.py` | summarize node |
| NLU + compose read context; compose appends offer | `nodes/understand.py`, `nodes/compose.py`, `prompts/nlu@v6.md`, `prompts/compose@v10.md` | context, templates, schemas |
| Offer + closing helpers, closing slot, offer routing | `flows/actions.py`, `ui.py`, `nodes/route.py`, `frontend/src/lib/sse.ts` | templates, card_select resolver |
| `card_info` / `card_block` state-first | `flows/card_info.py`, `flows/card_block.py`, `baseline/template_compose.py` | helpers, compose append, policy |
| `card_unlock` / `replacement` | `flows/card_unlock.py`, `flows/replacement.py` | helpers, policy |
| Warm abstain + `new_card` | `nodes/abstain.py`, `policy/scope.py`, `policies/scope.yaml`, `baseline/lexicon.yaml` | templates, schemas |
| Docs + dev scenarios | `docs/solution-docs/02-…`, `04-…`, `eval/scenarios/dev/` | final names |

## Build order

1. **W1, three independent roots.**
   - Templates and test harness (T1): every later reply and test builds on the variant API and the pinned RNG.
   - Policy/NLU contract (T2): flows and abstain read `CardSelectPolicy` v2, `focus` and `new_card`.
   - Summary step and state (T3): the memory chain starts here.
2. **W2.**
   - NLU/compose context (T4) needs `context.py` (T3), the offer templates (T1) and the `focus`/`new_card` schema (T2), for the prompt text.
   - Offer/closing helpers (T5) need the templates (T1) and the offer resolver (T2).
   - Abstain (T6) needs the templates (T1) and `Topic.new_card` (T2).
3. **W3.**
   - Memory wiring and its end-to-end tests (T7) need the summarize node (T3) and context-reading NLU/compose (T4).
   - `card_info`/`card_block` (T8) need the helpers (T5), compose's offer append (T4) and the policy (T2).
   - `card_unlock`/`replacement` (T9) need the helpers (T5) and the policy (T2).
   - Docs + dev scenarios (T10) need every name fixed above.
4. The verifier runs `make check` once, and the live check for success criterion 8.

## Touch map

| File | New/Mod | Change | Task |
|---|---|---|---|
| `backend/app/domains/conversation/templates.py` | mod | `_TEMPLATES` values become `str` or `list[str]`. `get_template(kind, lang, rng=None)`. `template_variants(kind, lang)`. New kinds. R3 strips `{card_options}`. R8 warm `abstain_fallback`. Q3 chip label. | T1 |
| `backend/tests/conftest.py` | mod | Autouse fixture pins the template RNG to variant 0. `ScriptedLLM` gives a default `summary` output when unscripted. | T1 |
| `backend/tests/unit/test_templates.py` | new | Tests 8, 13. | T1 |
| `backend/tests/unit/test_block_flows.py` | mod | Lines 375/382: no `\n` + options after the question. | T1 |
| `backend/tests/unit/test_sandbox_conversations.py` | mod | Line 72: same. | T1 |
| `policies/card_select.yaml` | mod | `version: 2`, `replacement.eligible_origins`, `next_step_offer`. | T2 |
| `policies/tools.yaml` | mod | `cards.get_block_origin.allowed_intents` + `card_status`, `card_block` (**safety-critical, ADR-018**). | T2 |
| `backend/app/domains/conversation/schemas.py` | mod | `card_hint` pattern adds `focus`. `Topic` adds `new_card`. | T2 |
| `backend/app/domains/conversation/flows/card_select.py` | mod | Policy model v2. `select_card(..., focus_card_id=None, candidate_ids=None)`. `next_step_offer_kind(...)`. | T2 |
| `backend/tests/unit/test_card_select.py` | mod | Test 3. | T2 |
| `backend/app/core/llm/registry.py` | mod | `Step` adds `summary`: Haiku 4.5, temperature 0.0. | T3 |
| `backend/app/domains/conversation/prompts/summary@v1.md` | new | Summary prompt, ES + PT examples, data fence. | T3 |
| `backend/app/domains/conversation/context.py` | new | `HistoryMessage`, `ConversationContext`, `WINDOW`, `build_context`, `redact_values`. | T3 |
| `backend/app/domains/conversation/state.py` | mod | `TurnState.history`, `TurnState.summary`. | T3 |
| `backend/app/domains/conversation/nodes/summarize.py` | new | `summarize` node + `SummaryDraft`. | T3 |
| `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` | mod | Test 4: `summarize.py` is scanned and clean. | T3 |
| `backend/app/domains/conversation/nodes/understand.py` | mod | `run_nlu(..., context=None)`, fenced masked history, `nlu@v6`. | T4 |
| `backend/app/domains/conversation/nodes/compose.py` | mod | `compose_checked/compose_reply(..., context=None)`, redacted history, `compose@v10`. Hidden `next_step_offer` + `append_next_step_offer(...)`. | T4 |
| `backend/app/domains/conversation/prompts/nlu@v6.md` | new | History fence, `focus`, `new_card`, closing-chip labels → `thanks_close`/`affirm`. | T4 |
| `backend/app/domains/conversation/prompts/compose@v10.md` | new | History use (no repeats, no re-greeting, never a source of figures). | T4 |
| `backend/tests/unit/test_compose.py` | mod | `compose@v10` label. | T4 |
| `backend/app/domains/conversation/flows/actions.py` | mod | Offer/closing helpers + pause constants. | T5 |
| `backend/app/domains/conversation/ui.py` | mod | `QuickRepliesPayload.slot` adds `"closing"`. | T5 |
| `backend/app/domains/conversation/nodes/route.py` | mod | `_CONFIRMATION_SLOTS` adds `offer_unlock`, `offer_block`. | T5 |
| `frontend/src/lib/sse.ts` | mod | `slot` union adds `"closing"`. | T5 |
| `backend/app/domains/conversation/nodes/abstain.py` | mod | `new_card` label/reason, `offer_human` honored, fallback check through `template_variants`. | T6 |
| `backend/app/domains/policy/scope.py` | mod | `TOPICS` + `new_card`. `TopicScope.offer_human: bool = True`. | T6 |
| `policies/scope.yaml` | mod | `version: 2`, `new_card` entry. | T6 |
| `backend/app/domains/conversation/baseline/lexicon.yaml` | mod | `out_of_scope.new_card`. Drop `nueva tarjeta`/`novo cartao` from `replacement_request`. Closing-chip words. | T6 |
| `backend/tests/unit/test_abstain_warm.py` | new | Tests 10, 12. | T6 |
| `backend/app/domains/conversation/graph.py` | mod | `summarize` node before `understand` (proposed only). | T7 |
| `backend/app/domains/conversation/nodes/__init__.py` | mod | Export `summarize`. | T7 |
| `backend/app/domains/conversation/nodes/load_session.py` | mod | Append the customer message on typed turns (not the address turn). | T7 |
| `backend/app/domains/conversation/nodes/next_intent.py` | mod | `finish` appends the Cardy reply. | T7 |
| `backend/app/domains/conversation/nodes/smalltalk.py` | mod | `_close` clears `history`/`summary`. | T7 |
| `docs/diagrams/turn-graph-v0.mmd` | mod | Regenerated (`make graph-diagram`). | T7 |
| `backend/tests/unit/test_conversation_memory.py` | new | Tests 1, 2, 5. | T7 |
| `backend/app/domains/conversation/flows/card_info.py` | mod | `focus`; next-step offer for an inactive card on `card_status`. | T8 |
| `backend/app/domains/conversation/flows/card_block.py` | mod | `focus`; state check before `block_kind`; offers; `offer` resume; closing after a verified lock. | T8 |
| `backend/app/domains/conversation/baseline/template_compose.py` | mod | Baseline appends the offer too. | T8 |
| `backend/tests/unit/test_state_offers.py` | new | Tests 6, 7, 11 (lock). | T8 |
| `backend/app/domains/conversation/flows/card_unlock.py` | mod | `focus`; `offer` resume; closing after a verified unlock. | T9 |
| `backend/app/domains/conversation/flows/replacement.py` | mod | `focus`; eligibility-filtered picker; needs-block / human offers; closing after a verified order and a declined offer. | T9 |
| `backend/tests/unit/test_replacement_offers.py` | new | Tests 9, 11 (unlock, replacement). | T9 |
| `docs/solution-docs/02-conversation-design.md` | mod | §2 (one NLU call + an optional summary call; history input), §3 (`summarize` node, new `awaiting_slot`s), §4.6, §4.9, §5 (new_card abstain). | T10 |
| `docs/solution-docs/04-contracts.md` | mod | §2 (`card_hint` `focus`, `Topic` `new_card`), §5 (`card_select` v2, `scope` v2, `tools` allowlist), §3 "SSE" (`slot: closing`). | T10 |
| `eval/scenarios/dev/*.yaml` | mod (only if needed) | Only scenarios that depend on old wording or routing. | T10 |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| Variants make every exact-text assertion in ~13 test files flaky. | The `conftest.py` autouse fixture pins the module RNG to variant 0. Tests that compute expectations through `get_template` stay deterministic. Only the 3 literal-text asserts listed in Facts change (T1). |
| Production code compares a template by equality (`abstain.py:123`). | T6 checks membership in `template_variants("fallback", lang)` instead. T1's acceptance greps `== get_template` / `!= get_template` under `backend/app` so nothing else hides. |
| The new `summary` step crashes every existing long test (`ScriptedLLM` `AssertionError`). | T1 gives `ScriptedLLM` a default `summary` output, used only when the test scripted none for that step. |
| Raw new delivery address enters `history` → later NLU/summary prompts (06 R5). | T7: `load_session` never appends on the address turn (`pending.awaiting_slot == "address"`). Test 2 runs PII through `InMemoryPiiVault` as the runner does. |
| Values reach `compose` through history (06 R4, D7). | `redact_values` replaces digit runs, money, dates and masks before `compose` sees history or the summary (T3). Test 2 asserts no digit in the `compose` user message (T7). |
| The summary LLM call fails and the turn hands off (06 R11). | `summarize` catches `LLMError`: it keeps the last 6 and the previous summary and sets no `escalation_reason` (T3). Test 5 proves it (T7). |
| `summarize`, `understand` or `compose` gains a write tool (06 R6). | `summarize.py` imports `app.core.llm` and reads only `llm` from `config`. Test 4 extends the source scan (T3). |
| `focus` resolves another customer's card (06 R1). | `select_card` accepts `focus` only when `focus_card_id` is in this session's `list_cards()`. Otherwise it behaves as no hint. `customer_id` is never involved. Test 3 (T2). |
| `get_block_origin` refused (`PolicyDenied`) because the intent isn't allowlisted. | T2 adds `card_status`, `card_block` (D2). `card_info` calls it only on `card_status` (Facts). A `PolicyDenied` from it is a bug, not a handled path. |
| An offer pause gets a "sí" that `route` doesn't send to the flow. | T5 adds `offer_unlock` and `offer_block` to `_CONFIRMATION_SLOTS`. T8/T9 tests drive the "sí" through the graph. |
| Two parallel flow tasks invent different pause shapes. | Pause dicts and chip labels are fixed in Facts and built only by the T5 helpers. |
| `new_card` steals the decline chip "Quiero una tarjeta nueva" (decline 54 → replacement). | Settled Q3: T1 relabels the chip "Reponer mi tarjeta" / "Repor meu cartão". |
| Policy files lose their `provenance` header or the registry hash breaks. | T2/T6 keep the header and bump `version`. The verify step runs `load_policies()`. |
| Baseline drifts from proposed (D17). | Flows are shared. T6 updates `lexicon.yaml`. T8 updates `baseline_compose`. T7 skips `summarize` for `system="baseline"`. Test 10 checks baseline too. |
| `make graph-diagram` output goes stale. | T7 regenerates `docs/diagrams/turn-graph-v0.mmd`. |

## Tests

| # | Test (spec name) | File | Task |
|---|---|---|---|
| 1 | `test_context_window_and_summary` | `test_conversation_memory.py` | T7 |
| 2 | `test_r5_history_prompts_masked` | `test_conversation_memory.py` | T7 |
| 3 | `test_r1_focus_hint_never_crosses_customer` | `test_card_select.py` | T2 |
| 4 | `test_r6_summarize_has_no_write_tools` | `test_r6_no_write_tools_in_llm_nodes.py` | T3 |
| 5 | `test_r11_summary_failure_degrades` | `test_conversation_memory.py` | T7 |
| 6 | `test_focus_already_blocked_offers_replacement[es,pt]` | `test_state_offers.py` | T8 |
| 7 | `test_status_offer_by_origin` | `test_state_offers.py` | T8 |
| 8 | `test_selection_text_has_no_options` | `test_templates.py` | T1 |
| 9 | `test_replacement_single_eligible_skips_picker[es,pt]`, `test_replacement_active_card_offers_block` | `test_replacement_offers.py` | T9 |
| 10 | `test_new_card_not_replacement[es,pt]` | `test_abstain_warm.py` | T6 |
| 11 | `test_closing_after_action_lock` / `test_closing_after_action_unlock_replacement` (both match `-k closing_after`) | `test_state_offers.py` / `test_replacement_offers.py` | T8 / T9 |
| 12 | `test_abstain_warm_keeps_chips[es,pt]` | `test_abstain_warm.py` | T6 |
| 13 | `test_template_variants_format` | `test_templates.py` | T1 |

Success criteria coverage:
- SC1: tests above.
- SC2: verifier `make check`.
- SC3: T2.
- SC4: T2 + T6.
- SC5: T3 + T4.
- SC6: T10.
- SC7: T10 verify.
- SC8: verifier live check. The command is in T8's acceptance.

## Tasks

- [ ] T1: Template variants, new kinds, R3/R8/R9 texts and test-harness defaults
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/templates.py` (whole file); `backend/app/domains/conversation/welcome.py` (the `_Rng`/`pick_body` pattern to mirror); spec §"Contracts" → **Templates**, D12, D13; `docs/brand.md` (voice: neutral tú, `você`, no emojis, ≤3 sentences, one question at a time); `backend/tests/conftest.py` (`ScriptedLLM`)
  - Acceptance:
    - **Variant API.** `_TEMPLATES` values may be `str` (one version) or `list[str]` (variants). `get_template(kind, language, rng=None)` returns one variant, picked by `(rng or _RNG).choice(...)`. `_RNG` is a module-level object, `random` by default, and is the test hook. `template_variants(kind, language) -> tuple[str, ...]` returns them all. `TemplateKind` gains `closing_question`, `offer_unlock`, `offer_human`, `replacement_needs_block`, `new_card_not_available`.
    - **Variant contents.** Every kind in the spec's "Varied kinds" list has ≥3 variants per language, including every `ask_which_card_*` kind (`status`, `balance`, `block`, `unlock`, `replacement`, `dispute`, `decline`). Variants contain no digit. All variants and both languages share the same placeholder set.
    - **R3.** No `ask_which_card_*` variant contains `{card_options}`. The callers' `.replace("{card_options}", …)` becomes a harmless no-op. Leave `decline_explain.py`/`unrecognized_charge.py` untouched.
    - **R8.** The `abstain_fallback` variants are first person, apologize, say Swip only handles cards, thank the customer and ask what they need with their cards. They keep `{topic_label} {reason} {closest_action} {human_offer}`.
    - **Offer and closing texts.** `offer_replacement`, `offer_unlock` and `offer_human` end with the "¿o te ayudo con algo más?" turn (R4). `offer_replacement` keeps `{card_last4}`. `closing_question` is R7's question. `replacement_needs_block` says the card must first be blocked or reported lost/stolen, and offers to block it. `new_card_not_available` says new cards can't be requested in this chat and asks what else.
    - **Q3 label.** `decline_replacement_option` becomes `"Reponer mi tarjeta"` / `"Repor meu cartão"` (settled Q3), which keeps decline-54 routing to `replacement_request`.
    - **Harness.** In `conftest.py`:
      - an autouse fixture monkeypatches `templates._RNG` with an object whose `.choice(seq)` returns `seq[0]`;
      - `ScriptedLLM.structured` returns `schema.model_validate({"text": "resumen previo"})` for `step == "summary"` when that step has no scripted queue. A scripted queue, including an `LLMError`, still wins.
    - **Old-text tests.** The asserts in `test_block_flows.py` (375, 382) and `test_sandbox_conversations.py` (72) check the question alone (no `\n` + options).
    - **New tests.** `test_templates.py` holds tests 13 and 8:
      - test 13 covers every varied kind (≥3 per language, no digits, equal placeholder sets);
      - test 8 checks that every `ask_which_card_*` and pick-prompt variant (`decline_pick_ask`, `tx_search_pick_ask`, `tx_explain_pick_ask`, `dispute_transactions_prompt`) has no `{card_options}`, and that `card_select.ask_which_card_text(action, Ask(...), lang)` contains none of the `Ask.card_options` lines, for every action.
  - Verify: `cd backend && uv run pytest tests/unit/test_templates.py tests/unit/test_block_flows.py tests/unit/test_sandbox_conversations.py tests/unit/test_conversation_basics.py -q && uv run ruff check app/domains/conversation/templates.py tests/conftest.py tests/unit/test_templates.py tests/unit/test_block_flows.py tests/unit/test_sandbox_conversations.py && uv run ruff format --check app/domains/conversation/templates.py tests/conftest.py tests/unit/test_templates.py tests/unit/test_block_flows.py tests/unit/test_sandbox_conversations.py && uv run mypy app/domains/conversation/templates.py && ! grep -rnE "[=!]= *get_template\(" app --include=*.py | grep -v nodes/abstain.py`
  - Files: `backend/app/domains/conversation/templates.py`, `backend/tests/conftest.py`, `backend/tests/unit/test_templates.py`, `backend/tests/unit/test_block_flows.py`, `backend/tests/unit/test_sandbox_conversations.py`

- [ ] T2: card_select policy v2, `focus` hint, replacement candidate set, offer resolver, D2 allowlist, NLU schema
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/flows/card_select.py`; `policies/card_select.yaml`, `policies/tools.yaml` line 9; spec D1, D2, D9, D16 and §"Contracts" → **NLU**, **Policy**; `backend/tests/unit/test_card_select.py`
  - Acceptance:
    - **`schemas.py`.** The `NLUSlots.card_hint` pattern is `^(credit|debit|focus|last4:\d{4})$`. `Topic` adds `"new_card"`.
    - **`card_select.yaml`.** `version: 2`, provenance header kept, plus `replacement: {eligible_origins: [customer_block]}` and `next_step_offer: {customer_block: replacement, customer_lock: unlock, bank_side: human, suspended: human, closed: human}`, exactly as the spec shows. The comment names "expired" as the code-side check.
    - **`CardSelectPolicy`.** It gains required `replacement` (`eligible_origins: list[Literal["customer_block"]]`) and `next_step_offer` (`dict[Literal["customer_block","customer_lock","bank_side","suspended","closed"], Literal["replacement","unlock","human"]]`), both frozen and `extra="forbid"`.
    - **`select_card(..., *, focus_card_id: str | None = None, candidate_ids: frozenset[str] | None = None)`:**
      - `hint == "focus"` resolves to `focus_card_id` only when that id is in `cards`. Otherwise, or when `focus_card_id` is None, it behaves exactly as `hint is None` and doesn't count a failure.
      - `candidate_ids`, when given, replaces the status-eligibility set for the **no-hint** branch only. A real hint still resolves over every card (D12).
      - Every existing call site keeps working unchanged.
    - **Resolver.** New pure `next_step_offer_kind(policy, *, status, origin_kind) -> Literal["replacement","unlock","human"] | None`:
      - `Closed` → `policy.next_step_offer["closed"]`;
      - `Suspended` → `["suspended"]`;
      - otherwise `origin_kind` in (`customer_block`, `customer_lock`, `bank_side`) → that entry;
      - anything else → `None`.
    - **`tools.yaml`.** Only `cards.get_block_origin.allowed_intents` changes, to `[card_status, card_block, card_unlock, replacement_request]`. Record in the state file that this line is **safety-critical (ADR-018)** and the PR must flag it.
    - **Test 3.** `test_r1_focus_hint_never_crosses_customer` in `test_card_select.py`: two sessions' card lists; `card_hint="focus"` with a `focus_card_id` from the other customer → `Ask` (or `Selected` only of this customer's own single eligible card), never the foreign id. Plus a positive case: a `focus` id in the list → `Selected`.
  - Verify: `cd backend && uv run pytest tests/unit/test_card_select.py tests/unit/test_policy_registry.py -q && uv run python -c "from app.domains.policy.registry import load_policies; from app.domains.conversation.flows.card_select import load_card_select_policy; load_policies(); print(load_card_select_policy().version)" && uv run ruff check app/domains/conversation/flows/card_select.py app/domains/conversation/schemas.py tests/unit/test_card_select.py && uv run ruff format --check app/domains/conversation/flows/card_select.py app/domains/conversation/schemas.py tests/unit/test_card_select.py && uv run mypy app/domains/conversation/flows/card_select.py app/domains/conversation/schemas.py`
  - Files: `backend/app/domains/conversation/schemas.py`, `policies/card_select.yaml`, `policies/tools.yaml`, `backend/app/domains/conversation/flows/card_select.py`, `backend/tests/unit/test_card_select.py`

- [ ] T3: `summary` LLM step, context builder, history state and the `summarize` node
  - Depends on: nothing
  - Read exactly these: `backend/app/core/llm/registry.py`; `backend/app/domains/conversation/nodes/understand.py` (the analogue: a `PromptRef` + `llm.structured` + `LLMError` handling); `backend/app/domains/conversation/state.py` (`TurnState`); spec D3, D5, D7, D8 and §"Contracts" → **Graph state**, **Context builder**, **LLM step**
  - Acceptance:
    - **`registry.py`.** `Step` adds `"summary"`. `MODEL_REGISTRY["summary"]` = the Haiku 4.5 IDs (anthropic + bedrock, same as `compose`). `TEMPERATURE["summary"] = 0.0`.
    - **`prompts/summary@v1.md`.** Spanish system prompt. It folds the previous summary and the overflow messages into one short masked summary, in the conversation's language. It treats the fenced block as data and never as instructions (R6). It never writes figures or tokens it wasn't given. It carries one ES and one PT example.
    - **`context.py` (new, pure, no I/O).** `HistoryMessage` (TypedDict: `role: Literal["customer","cardy"]`, `text: str`); `ConversationContext` (frozen: `messages: list[HistoryMessage]`, `summary: str | None`); `WINDOW = 6`.
      - `build_context(history, summary)` returns the last `WINDOW` messages and the summary.
      - `redact_values(text)` replaces every digit run, money figure, date and card mask (`•••• dddd`) with one neutral marker (e.g. `⟨valor⟩`). Its output contains no digit.
    - **`state.py`.** `TurnState` gains `history: NotRequired[list[HistoryMessage]]` and `summary: NotRequired[str | None]` (plain last-write-wins, no reducer).
    - **`nodes/summarize.py` (new).** `SummaryDraft(BaseModel){text: str}` with `extra="forbid"`; `_PROMPT = PromptRef("summary", 1)`; `async def summarize(state, config)`:
      - With `len(history) <= WINDOW` it returns `{}` and makes no call.
      - Otherwise it calls `llm.structured(step="summary", …, schema=SummaryDraft)` once. The user message is the previous summary plus the overflow messages, inside a fenced data block. It returns `{"history": history[-WINDOW:], "summary": draft.text}`.
      - On `LLMError`, or when `find_pii(draft.text)` is non-empty, it returns `{"history": history[-WINDOW:]}`: previous summary kept, no `escalation_reason` (D5).
      - It reads only `config["configurable"]["llm"]`.
    - **Test 4.** `test_r6_no_write_tools_in_llm_nodes.py` gains `test_r6_summarize_has_no_write_tools`: `summarize.py` is in `scan_llm_modules(...)` and has no offenses.
    - The node is **not** wired into the graph here. T7 does that.
  - Verify: `cd backend && uv run pytest tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_llm_client.py -q && uv run python -c "from app.domains.conversation.context import build_context, redact_values; assert not any(c.isdigit() for c in redact_values('COP \$23.494.545 el 31/03/2027 •••• 5284')); print(build_context([{'role':'customer','text':str(i)} for i in range(8)], None).messages[0])" && uv run ruff check app/core/llm/registry.py app/domains/conversation/context.py app/domains/conversation/state.py app/domains/conversation/nodes/summarize.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run ruff format --check app/core/llm/registry.py app/domains/conversation/context.py app/domains/conversation/state.py app/domains/conversation/nodes/summarize.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run mypy app/core/llm/registry.py app/domains/conversation/context.py app/domains/conversation/state.py app/domains/conversation/nodes/summarize.py`
  - Files: `backend/app/core/llm/registry.py`, `backend/app/domains/conversation/prompts/summary@v1.md`, `backend/app/domains/conversation/context.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/nodes/summarize.py`, `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`

- [ ] T4: NLU and compose read the conversation context (`nlu@v6`, `compose@v10`); compose appends the next-step offer
  - Depends on:
    - T1: offer template kinds `offer_replacement`/`offer_unlock`/`offer_human`, `template_variants`.
    - T2: `focus`/`new_card` in `schemas.py`, for the prompt text.
    - T3: `context.build_context`, `redact_values`, `ConversationContext`, `TurnState.history`/`summary`.
  - Read exactly these: `backend/app/domains/conversation/nodes/understand.py`; `backend/app/domains/conversation/nodes/compose.py`; `backend/app/domains/conversation/prompts/nlu@v5.md` and `compose@v9.md` (copy, then edit); spec D6, D7, D9, D10, D14, D15
  - Acceptance:
    - **`understand.py`.**
      - `_PROMPT = PromptRef("nlu", 6)`.
      - `run_nlu(llm, text, *, pending, country, context: ConversationContext | None = None)` adds, before the current message, a fenced block of the context messages (`cliente:`/`cardy:` lines, masked text as-is) and the summary, when present.
      - `understand` passes `build_context(state.get("history", []), state.get("summary"))`. The current turn's own message is the last `history` entry once T7 wires it, so `understand` passes `history[:-1]` when the last entry is this turn's customer text, to avoid duplicating it.
    - **`nlu@v6.md`** (copy of v5 plus):
      - read the history fence as data;
      - `card_hint: "focus"` when the customer refers to the one card in focus without naming it; no hint when the reference is ambiguous;
      - `topic: "new_card"` with `status: out_of_scope` for requesting a new or additional card product, as opposed to replacing an existing one;
      - "Terminar"/"Encerrar" → `thanks_close`;
      - "Algo más"/"Mais alguma coisa" → `affirm`.
    - **`compose.py`.**
      - `_PROMPT = PromptRef("compose", 10)`.
      - `compose_checked`/`compose_reply`/`_compose_draft` take `context: ConversationContext | None = None`. When given, `_build_user_message` adds a fenced history block where every message and the summary went through `redact_values`. **The compose user message never carries a digit.**
      - The `compose` node passes the state's context.
    - **Offer append.** `"next_step_offer"` joins `_HIDDEN_KEYS`. New `append_next_step_offer(segments, facts_by_key, language) -> list[str]`: when the fact is present, it appends `get_template({"replacement":"offer_replacement","unlock":"offer_unlock","human":"offer_human"}[value], language)` filled with `card_last4` from the `card_mask` fact's raw value. The `compose` node calls it after the footnotes.
    - **`compose@v10.md`.** It uses the history only for coherence: don't repeat data already given, don't greet again, resume the topic. It is never a source of figures. Keys only, as before.
    - **`test_compose.py`.** Line 65 now expects `compose@v10`.
  - Verify: `cd backend && uv run pytest tests/unit/test_compose.py tests/unit/test_graph.py tests/unit/test_r5_llm_guard.py -q && uv run ruff check app/domains/conversation/nodes/understand.py app/domains/conversation/nodes/compose.py tests/unit/test_compose.py && uv run ruff format --check app/domains/conversation/nodes/understand.py app/domains/conversation/nodes/compose.py tests/unit/test_compose.py && uv run mypy app/domains/conversation/nodes/understand.py app/domains/conversation/nodes/compose.py`
  - Files: `backend/app/domains/conversation/nodes/understand.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/prompts/nlu@v6.md`, `backend/app/domains/conversation/prompts/compose@v10.md`, `backend/tests/unit/test_compose.py`

- [ ] T5: Offer and closing helpers, `closing` quick-reply slot, offer-pause routing
  - Depends on:
    - T1: `closing_question`, `offer_*` template kinds.
    - T2: `next_step_offer_kind`.
  - Read exactly these: `backend/app/domains/conversation/flows/actions.py`; `backend/app/domains/conversation/nodes/route.py` (`_CONFIRMATION_SLOTS`); `backend/app/domains/conversation/ui.py` (`QuickRepliesPayload`); this plan's Facts → "Settled shapes"
  - Acceptance:
    - **Pause constants in `actions.py`.** `OFFER_REPLACEMENT_PAUSE`, `OFFER_UNLOCK_PAUSE` and `OFFER_BLOCK_PAUSE` (the three `Pending` dicts in Facts) and `CLOSING_PAUSE` (equal to `smalltalk._ANYTHING_ELSE`; define it here and don't import from `nodes/`).
    - **`closing(language) -> dict`.** Returns `{"pending": CLOSING_PAUSE, "segments": [closing_question], "ui": [QuickRepliesEvent(slot="closing", options=[Algo más, Terminar] / [Mais alguma coisa, Encerrar])]}`.
    - **`with_closing(update, language) -> dict`.** Merges `closing(...)` into a verified `execute(...)` update: segments appended, `pending`/`ui` set. It returns `update` unchanged when it carries no `"actions"`, because a failure or handoff never gets the closing.
    - **`offer(kind, language, card_last4) -> dict`.**
      - `"replacement"` → `{"segments": [offer_replacement filled], "pending": OFFER_REPLACEMENT_PAUSE}`;
      - `"unlock"` → `{"segments": [offer_unlock filled], "pending": OFFER_UNLOCK_PAUSE}`;
      - `"human"` → `{"segments": [offer_human], "ui": [QuickRepliesEvent(slot="next_step", options=[tx_human_option])]}` with no pause.
    - **`offer_pieces(kind, language) -> dict`.** The same, minus `segments`, for `card_info`, whose text `compose` appends.
    - **Elsewhere.** `ui.QuickRepliesPayload.slot` adds `"closing"`, and its docstring names it. `route._CONFIRMATION_SLOTS` adds `"offer_unlock"` and `"offer_block"`. `frontend/src/lib/sse.ts` `slot` union adds `"closing"`.
    - No behavior change for existing flows yet. Existing tests stay green.
  - Verify: `cd backend && uv run pytest tests/unit/test_r3_flows.py tests/unit/test_block_flows.py -q && uv run ruff check app/domains/conversation/flows/actions.py app/domains/conversation/ui.py app/domains/conversation/nodes/route.py && uv run ruff format --check app/domains/conversation/flows/actions.py app/domains/conversation/ui.py app/domains/conversation/nodes/route.py && uv run mypy app/domains/conversation/flows/actions.py app/domains/conversation/ui.py app/domains/conversation/nodes/route.py && MSYS_NO_PATHCONV=1 docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/lib/sse.ts && npm run typecheck"`
  - Files: `backend/app/domains/conversation/flows/actions.py`, `backend/app/domains/conversation/ui.py`, `backend/app/domains/conversation/nodes/route.py`, `frontend/src/lib/sse.ts`

- [ ] T6: Warm out-of-scope replies and `new_card` (R6, R8), scope policy v2, baseline lexicon
  - Depends on:
    - T1: warm `abstain_fallback` variants, `new_card_not_available`, `template_variants`.
    - T2: `Topic` `new_card`.
  - Read exactly these: `backend/app/domains/conversation/nodes/abstain.py`; `backend/app/domains/policy/scope.py`; `policies/scope.yaml`; `backend/app/domains/conversation/baseline/lexicon.yaml`; `backend/tests/unit/test_abstain.py` (the analogue test); spec D10, D17 and the R6/R8 "Hecho cuando"
  - Acceptance:
    - **`scope.py`.** `TOPICS` adds `"new_card"`. `TopicScope.offer_human: bool = True`.
    - **`scope.yaml`.** `version: 2`, header kept, plus `new_card: {kind: out_of_scope, reason_key: new_card_not_available, closest_intents: [], human_queue: atencion, offer_human: false}`.
    - **`abstain.py`:**
      - `_TOPIC_LABELS["new_card"]` (ES "tarjetas nuevas" / PT "cartões novos").
      - For `reason_key == "new_card_not_available"`, the reply is `get_template("new_card_not_available", lang)` with no compose call.
      - The human chip and the `human_offer` fact are added only when `entry.offer_human`. When no chip remains, no `quick_replies` event is emitted.
      - The `text == get_template("fallback", …)` check becomes `text in template_variants("fallback", language)`.
      - `pending` is still untouched.
    - **`lexicon.yaml`:**
      - `out_of_scope.new_card` gets ES (`solicitar una (nueva )?tarjeta`, `tarjeta (nueva|adicional)`, `nueva tarjeta`) and PT (`solicitar um (novo )?cartao`, `cartao (novo|adicional)`, `novo cartao`).
      - `replacement_request` drops `nueva tarjeta` and `novo cartao`.
      - `thanks_close` adds `terminar`/`encerrar`.
      - A new `affirm` intent has ES `algo mas` and PT `mais alguma coisa` only.
    - **Test 10** (`test_new_card_not_replacement[es,pt]`): scripted NLU `status=out_of_scope, topic=new_card` → route `abstain`, no `replacement` node in the run, reply is a `new_card_not_available` variant, and no `quick_replies` option carries the human label. Plus `keyword_nlu("Quiero solicitar una nueva tarjeta")` / `("Quero solicitar um novo cartão")` → `topic == "new_card"`.
    - **Test 12** (`test_abstain_warm_keeps_chips[es,pt]`): loans (ex. 9) and `other` (ex. 10) keep the closest-action chip (loans) and the human chip. Every `abstain_fallback` variant is first person (ES contains "puedo", PT "consigo"/"posso").
  - Verify: `cd backend && uv run pytest tests/unit/test_abstain_warm.py tests/unit/test_abstain.py tests/unit/test_baseline.py tests/unit/test_policy_registry.py -q && uv run ruff check app/domains/conversation/nodes/abstain.py app/domains/policy/scope.py tests/unit/test_abstain_warm.py && uv run ruff format --check app/domains/conversation/nodes/abstain.py app/domains/policy/scope.py tests/unit/test_abstain_warm.py && uv run mypy app/domains/conversation/nodes/abstain.py app/domains/policy/scope.py`
  - Files: `backend/app/domains/conversation/nodes/abstain.py`, `backend/app/domains/policy/scope.py`, `policies/scope.yaml`, `backend/app/domains/conversation/baseline/lexicon.yaml`, `backend/tests/unit/test_abstain_warm.py`

- [ ] T7: Wire memory into the turn graph (append, summarize, clear) and prove R1-memory/R5/R11 end to end
  - Depends on:
    - T3: `summarize` node, `TurnState.history`/`summary`, `HistoryMessage`, `WINDOW`.
    - T4: `understand`/`compose` read the context.
    - T1: `ScriptedLLM` default `summary` output.
  - Read exactly these: `backend/app/domains/conversation/graph.py` (`_entry`, `build_graph`); `backend/app/domains/conversation/nodes/load_session.py`; `backend/app/domains/conversation/nodes/next_intent.py` (`finish`); `backend/tests/unit/test_r5_masking.py` (masking analogue for test 2); spec D3, D5, D8 and §"Graph state"
  - Acceptance:
    - **`graph.py`.** It adds the `summarize` node. For `system="proposed"`, `_entry`'s `"understand"` target maps to `"summarize"`, then the edge `summarize → understand`. For `"baseline"` the map goes straight to `understand`, so the baseline never summarizes (D17). `_BRANCH_NODES` and `run_turn` are unchanged. `nodes/__init__.py` exports `summarize`.
    - **`load_session`.** On a typed turn it returns `history = [*history, {"role": "customer", "text": user_text}]`. A typed turn has non-empty `user_text` and `confirmation`/`selection`/`resume` all `None`. Two exceptions:
      - the address turn (`pending.awaiting_slot == "address"`) appends **nothing**, because that text is the raw new address (R5);
      - human mode appends nothing.
    - **`finish`.** When `reply` is non-empty and `mode != "human"`, it also returns `history = [*history, {"role": "cardy", "text": reply}]`. It doesn't trim; `summarize` folds the overflow on the next typed turn.
    - **`smalltalk._close`.** Adds `"history": []` and `"summary": None`.
    - **Diagram.** `docs/diagrams/turn-graph-v0.mmd` regenerated with `make graph-diagram`, or the same command from the Makefile line 116.
    - **Test 1** (`test_context_window_and_summary`):
      - (a) 3 typed turns → the 3rd NLU and compose user messages carry the earlier messages and no summary line; no `summary` call.
      - (b) Pre-seed the checkpoint via `graph.aupdate_state` with 7 history messages and no summary, run 1 typed turn (8 messages) → exactly 1 `summary` call; NLU and compose carry the last 6 messages plus the scripted summary text.
    - **Test 2** (`test_r5_history_prompts_masked`): raw texts with a name/email/phone go through `InMemoryPiiVault` + `mask_user_text`, enough turns run to trigger `summarize`, then `find_pii(call.system + call.user)` is empty for every `nlu`, `summary` and `compose` call, and no `compose` call's `user` contains a digit.
    - **Test 5** (`test_r11_summary_failure_degrades`): `summary` scripted as `LLMUnavailable(...)` → the turn replies normally; no `handoff_summary`/`fallback` route; `escalation_reason` is not set; `history` holds 6 entries before `finish` appends.
  - Verify: `cd backend && uv run pytest tests/unit/test_conversation_memory.py tests/unit/test_graph.py tests/unit/test_conversation_basics.py tests/unit/test_checkpoint_serde.py -q && uv run ruff check app/domains/conversation/graph.py app/domains/conversation/nodes/__init__.py app/domains/conversation/nodes/load_session.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py tests/unit/test_conversation_memory.py && uv run ruff format --check app/domains/conversation/graph.py app/domains/conversation/nodes/__init__.py app/domains/conversation/nodes/load_session.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py tests/unit/test_conversation_memory.py && uv run mypy app/domains/conversation/graph.py app/domains/conversation/nodes/load_session.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py && uv run lint-imports`
  - Files: `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/__init__.py`, `backend/app/domains/conversation/nodes/load_session.py`, `backend/app/domains/conversation/nodes/next_intent.py`, `backend/app/domains/conversation/nodes/smalltalk.py`, `docs/diagrams/turn-graph-v0.mmd`, `backend/tests/unit/test_conversation_memory.py`

- [ ] T8: `card_info` and `card_block` check the card's state first and offer the next step; closing after a verified lock
  - Depends on:
    - T2: `select_card(focus_card_id=…)`, `next_step_offer_kind`, D2 allowlist.
    - T4: `next_step_offer` hidden fact and `append_next_step_offer` in `compose.py`.
    - T5: `offer`, `offer_pieces`, `with_closing`, `OFFER_*_PAUSE` in `actions.py`.
  - Read exactly these: `backend/app/domains/conversation/flows/card_block.py`; `backend/app/domains/conversation/flows/card_info.py`; `backend/tests/unit/test_block_flows.py` (scenario style: `make_session`, `ScriptedLLM`, `run_turn`); spec §"Flow behavior" (`card_block`, `card_info`, closing) and D1, D11, D14
  - Acceptance:
    - **`card_info`:**
      - Passes `focus_card_id=state.get("selected_card_id")` to `select_card`.
      - On the `card_status` intent only, for a card that isn't active (status ≠ Active, or `locked`), it computes the offer kind with `next_step_offer_kind`. It calls `bank_write_tools.get_block_origin(card_id, "card_status")` only when the status is Blocked or the card is locked.
      - When the kind isn't `None`, it adds `Fact(key="next_step_offer", value=kind, source="policies/card_select.yaml")` and merges `offer_pieces(kind, lang)` (pause or human chip) into its update, instead of `pending: None`.
    - **`card_block`:**
      - Passes `focus_card_id`.
      - After `Selected`, it reads `get_card_details` **before** asking `block_kind`:
        - Blocked or Closed → `already_in_state` + `offer(kind, …)`, where kind comes from `next_step_offer_kind`, with origin from `get_block_origin(card_id, "card_block")` when Blocked.
        - Locked with `block_kind` in (`None`, `temporary_lock`) → `already_in_state` + the unlock offer.
        - Otherwise the existing path (`_ask_block_kind` or plan).
      - Neither already-in-state case shows block-kind quick replies or a picker.
      - A verified `temporary_lock` → `with_closing(update, lang)`. A verified `permanent_block` keeps today's `offer_replacement` (D11).
      - New `pending.node == "offer"` resume (`OFFER_BLOCK_PAUSE`, opened by T9's `replacement`):
        - "sí" → (settled Q1) run the normal `card_block` path on `selected_card_id` (state check, then the lock-vs-block question). With no `selected_card_id`, run `_select_card` (picker) first.
        - "no" → (settled Q2) `closing(lang)`: the closing question + "Algo más"/"Terminar" chips + pending `smalltalk.anything_else`, the same as a declined replacement offer.
    - **`baseline/template_compose.py`.** `baseline_compose` calls `append_next_step_offer` after its footnotes.
    - **Test 6** (`test_focus_already_blocked_offers_replacement[es,pt]`): `CLI-TFMULTI00001`, `overlay.blocked.add("PRD-TFM1CRED0001")`. Turn 1 "estado de mi crédito" (scripted NLU `card_status`, `last4:6475`; scripted compose). Turn 2 "quiero bloquearla" (NLU `card_block`, `card_hint="focus"`, no `block_kind`) → reply has an `already_in_state` variant and an `offer_replacement` variant, `pending == "replacement.offer_replacement"`, no `card_picker`, no `quick_replies` with `slot="block_kind"`.
    - **Test 7** (`test_status_offer_by_origin`, parametrized), each after a `card_status` answer:
      - `customer_lock` (`overlay.locked`) → unlock offer, pending `card_unlock.offer_unlock`;
      - `CLI-TFBLOCKD0003` (bank_side) → human offer, `quick_replies` with `slot="next_step"` and the human label, no pause;
      - the Closed card `last4:9001` → human offer.
    - **Test 11, lock part** (`test_closing_after_action_lock`): lock confirmed → the reply ends with a `closing_question` variant, `quick_replies` `slot="closing"`, pending `smalltalk.anything_else`. Then "Terminar" (scripted `thanks_close`) → a `conversation_closed` UI event.
    - **SC8 manual proof**, recorded in the state file, for the verifier: in the web chat at `http://localhost`, lock a card → chips "Algo más"/"Terminar"; tap "Terminar" → the farewell and a closed conversation.
  - Verify: `cd backend && uv run pytest tests/unit/test_state_offers.py tests/unit/test_card_info_flows.py tests/unit/test_block_flows.py tests/unit/test_card_block_memory.py tests/unit/test_baseline.py -q && uv run ruff check app/domains/conversation/flows/card_info.py app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/template_compose.py tests/unit/test_state_offers.py && uv run ruff format --check app/domains/conversation/flows/card_info.py app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/template_compose.py tests/unit/test_state_offers.py && uv run mypy app/domains/conversation/flows/card_info.py app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/template_compose.py`
  - Files: `backend/app/domains/conversation/flows/card_info.py`, `backend/app/domains/conversation/flows/card_block.py`, `backend/app/domains/conversation/baseline/template_compose.py`, `backend/tests/unit/test_state_offers.py`

- [ ] T9: `replacement` only for eligible cards, `card_unlock` offer resume, closing after a verified unlock/replacement
  - Depends on:
    - T2: `select_card(focus_card_id=…, candidate_ids=…)`, `CardSelectPolicy.replacement.eligible_origins`, `next_step_offer_kind`.
    - T5: `offer`, `with_closing`, `closing`, `OFFER_BLOCK_PAUSE`, `OFFER_UNLOCK_PAUSE`.
  - Read exactly these: `backend/app/domains/conversation/flows/replacement.py`; `backend/app/domains/conversation/flows/card_unlock.py`; `backend/tests/unit/test_block_flows.py` (`test_es_lost_card_block_replacement_tracking`, `test_es_unlock_own_lock_needs_otp` as analogues); spec §"Flow behavior" (`replacement`, closing), D1, D11, D14, D16
  - Acceptance:
    - **`replacement._select_card`:**
      - Computes the eligible set over this session's non-Closed cards. A card is eligible when `get_block_origin(card_id, "replacement_request").kind in policy.replacement.eligible_origins`, or `get_card_details(card_id).expiration_date < local_today(country)`. Call origin only for Blocked/locked cards.
      - Calls `select_card(..., focus_card_id=state.get("selected_card_id"), candidate_ids=eligible)`:
        - no hint and one eligible card → straight to `_check_active_and_eligibility` (address confirm), with no picker;
        - several → picker with only eligible cards, text without options;
        - none → `replacement_needs_block` + `OFFER_BLOCK_PAUSE` (no `selected_card_id`).
      - A hinted, selected card that isn't eligible goes by `next_step_offer_kind`/status:
        - Active or `customer_lock` → `replacement_needs_block` + `OFFER_BLOCK_PAUSE` with `selected_card_id` set, and no `address_confirm`;
        - bank_side, Suspended or Closed → `offer("human", …)`.
      - `replacement_not_eligible` stays only as the guard inside `_check_active_and_eligibility`.
    - **`replacement` after the write.** A verified `order_replacement` → `with_closing`. `_resume_offer` "no" → `replacement_declined` + `closing(lang)`.
    - **`card_unlock`:**
      - Passes `focus_card_id`.
      - New `pending.node == "offer"` resume (`OFFER_UNLOCK_PAUSE`, opened by T8's `card_info`/`card_block`): "sí" → `_check_status_and_origin(state, config, selected_card_id)` (step-up, then plan). "no" → (settled Q2) `closing(lang)`: the closing question + chips.
      - A verified unlock → `with_closing`.
    - **Test 9.**
      - `test_replacement_single_eligible_skips_picker[es,pt]`: `CLI-TFMULTI00001`, `overlay.blocked = {PRD-TFM1CRED0001}`, NLU `replacement_request` with no hint → no `card_picker`; pending `replacement.address_confirm`.
      - `test_replacement_active_card_offers_block`: same customer, no blocked card, hint `last4:1203` → a `replacement_needs_block` variant, pending `card_block.offer_block`, never `address_confirm`, no `address_confirm` text.
    - **Test 11, unlock/replacement part** (`test_closing_after_action_unlock_replacement`): a verified unlock (with OTP via `session.gate`) and a verified replacement each end with `closing_question` + `slot="closing"` + pending `smalltalk.anything_else`.
  - Verify: `cd backend && uv run pytest tests/unit/test_replacement_offers.py tests/unit/test_block_flows.py tests/unit/test_r3_flows.py tests/unit/test_step_up.py -q && uv run ruff check app/domains/conversation/flows/replacement.py app/domains/conversation/flows/card_unlock.py tests/unit/test_replacement_offers.py && uv run ruff format --check app/domains/conversation/flows/replacement.py app/domains/conversation/flows/card_unlock.py tests/unit/test_replacement_offers.py && uv run mypy app/domains/conversation/flows/replacement.py app/domains/conversation/flows/card_unlock.py`
  - Files: `backend/app/domains/conversation/flows/replacement.py`, `backend/app/domains/conversation/flows/card_unlock.py`, `backend/tests/unit/test_replacement_offers.py`

- [ ] T10: Contract and design docs (02, 04) and the dev-scenario sweep
  - Depends on:
    - T2: final policy/schema shapes.
    - T5: slot `closing`, pause names.
    - T6: `scope.yaml` v2.
    - It reads names from this plan's Facts and from the state file, not from code.
  - Read exactly these: spec §"Touch map" → Docs, D1–D17; `docs/solution-docs/02-conversation-design.md` §2, §3 (the `pending.awaiting_slot` paragraph), §4.6, §4.9, §5; `docs/solution-docs/04-contracts.md` §2, §3 "Handoff deltas" paragraph (`ui.quick_replies.slot`), §5
  - Acceptance:
    - **`02` §2.** "One NLU call per turn, plus at most one `summary` call (Haiku 4.5, temperature 0, `summary@v1`) when messages leave the 6-message window." Input: the last 6 masked messages plus the masked summary.
    - **`02` §3.** The `summarize` node before `understand` (proposed only), and the new `awaiting_slot` values `offer_unlock`, `offer_block`.
    - **`02` §4.6.** State checked before lock-vs-block; already Blocked/Closed/locked → `already_in_state` + next-step offer; closing after a verified lock.
    - **`02` §4.9.** Eligibility = `customer_block` or expired (`card_select.yaml` `replacement.eligible_origins`); the picker lists eligible cards only; one → no picker; none or an ineligible active card → explain + offer block; bank-side/Suspended/Closed → person.
    - **`02` §5.** The `new_card` abstain (no human chip) and the warm first-person abstain.
    - **`04` §2.** `card_hint: "credit | debit | focus | last4:6475 | null"`; `topic` list adds `new_card`.
    - **`04` §5.**
      - `card_select.yaml` v2 block, as in the spec;
      - `scope.yaml` entry shape gains optional `offer_human` (default true), plus the `new_card` row;
      - the `tools.yaml` `get_block_origin` line becomes `[card_status, card_block, card_unlock, replacement_request]`, marked safety-critical.
    - **`04` §3 SSE.** `ui.quick_replies.slot` is `block_kind | abstain | next_step | closing`, with the closing options and their tap behavior.
    - **Dev scenarios.** Grep `eval/scenarios/dev/` for the options-in-text wording, "tarjeta nueva"/"cartão novo" routing and a post-action "gracias" expectation. Update only scenarios that depend on old wording or routing, and list each one changed in the state file. Never `heldout/`.
  - Verify: `cd c:/Users/USUARIO/factored-hackathon-2026-inferencia-aplicada && grep -q "focus" docs/solution-docs/04-contracts.md && grep -q "new_card" docs/solution-docs/04-contracts.md && grep -q "closing" docs/solution-docs/04-contracts.md && grep -q "summary" docs/solution-docs/02-conversation-design.md && grep -q "offer_block" docs/solution-docs/02-conversation-design.md && test -z "$(git diff --stat main -- eval/scenarios/heldout/)" && (cd backend && uv run python -c "import glob,yaml;[yaml.safe_load(open(f,encoding='utf-8')) for f in glob.glob('../eval/scenarios/dev/*.yaml')];print('ok')")`
  - Files: `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/04-contracts.md`, `eval/scenarios/dev/*.yaml` (only the ones the sweep finds; list them in the state file)

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3 | | Three roots with no dependency: templates + harness, card_select policy + schema + allowlist, summary step + state + node. Disjoint files: `conftest.py` and `test_block_flows.py`/`test_sandbox_conversations.py` only in T1, `schemas.py` only in T2, `state.py` only in T3. No dependency, lockfile, migration or stack change. |
| W2 | T4, T5, T6 | | T4 (`understand.py`, `compose.py`, prompts, `test_compose.py`), T5 (`actions.py`, `ui.py`, `route.py`, `sse.ts`) and T6 (`abstain.py`, `scope.py`, `scope.yaml`, `lexicon.yaml`) share no file. Each needs only W1 outputs. T5's frontend check is a typecheck/lint, not a build or restart. |
| W3 | T7, T8, T9, T10 | | T7 is the memory wiring (`graph.py`, `load_session`, `finish`, `smalltalk`, diagram). T8 is `card_info`/`card_block`/`template_compose`. T9 is `replacement`/`card_unlock`. T10 is docs + `eval/scenarios/dev`. No shared paths; each depends only on W1/W2. T8 and T9 agree on pauses through T5's constants, not through each other. |

No task changes the shared environment (no dependency, lockfile, migration, `make data` or stack restart), so none runs alone. `make check` and the SC8 web-chat check run once, at the end, by the verifier.
