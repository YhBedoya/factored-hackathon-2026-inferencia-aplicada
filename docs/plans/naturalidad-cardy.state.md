# State: naturalidad-cardy — Cardy naturalness and conversation memory
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card naturalidad-cardy (conversation, owner B; source `docs/requirements/naturalidad-cardy.md`) · spec `docs/specs/naturalidad-cardy.md` · plan `docs/plans/naturalidad-cardy.md`
Branch `feat/naturalidad-cardy`, based on `feat/landing-home-bienvenida` (stacked, unmerged).

## Conventions established for this card
- Binding: plan §"Settled after the spec gate" and §"Facts checked against the repo" (plan lines 5–83). Read only those, plus your task block.
- `finish` lives in `nodes/next_intent.py`; the card_select policy loader is in `flows/card_select.py` (A3).
- The address-entry turn is never appended to history (raw address is unmasked, A1).
- Next-step offer only on `card_status`, not `balance_due` (A2).
- Fake LLM only (`ScriptedLLM`); never the full suite per task.
- `redact_values` strips every digit, including inside PII tokens (`⟨NAME_1⟩` → `⟨NAME_⟨valor⟩⟩`); compose history is value-free by design (T3).

## Human decisions taken mid-card
- Spec: eligibility/offers by block origin (policy + tools.yaml allowlist, safety-critical); history+summary in graph state, `summarize` node, Haiku 4.5 temp 0; `card_hint="focus"`; Topic `new_card` with `offer_human: false`; replacement offer kept after a permanent block; N=3 variants for conversational templates.
- Plan Q3: decline-54 chip relabeled "Reponer mi tarjeta" / "Repor meu cartão".
- Plan Q2: "no" to an unlock/block offer → closing question with "Algo más"/"Terminar".
- Plan Q1: "sí" to `replacement_needs_block` → normal card_block path (picker first if no focus).
- Post-T7 (regression): queued intents after a verified action run first; closing question only when the queue is empty. Fix in `with_closing` (T5 agent).
- Verify round 1: closing_question = "¿Te ayudo con algo más o damos por terminada la conversación?" (3 variants ES/PT); closing appears once the queue drains if the turn had a verified action; ES out-of-scope variants all use "puedo".
- Verify round 2: closing follows every verified action, incl. dispute claim (test_dispute_flows asserts updated by T5 agent).
- Post-gate (human live test): block picker shows only Active unlocked cards (policy `card_block` section); one eligible → straight to temporal/permanent; none → `block_none_eligible` + closing.
- Post-gate: closing question ALWAYS when a flow finishes (incl. cancel, answered query, declined offer); skip if pending, reply already ends in a question, handoff/human, queue non-empty, or closed.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a7d5cf74 | 40 varied kinds x3 per lang, 5 new kinds, R3/R8 texts, chip relabel, harness defaults |
| T2 | done | afe226da | policy v2, focus hint, next_step_offer_kind, schema, tools.yaml allowlist (ADR-018) |
| T3 | done | a1d8fce0 | summary step (Haiku, temp 0), context.py, history/summary state, summarize node (unwired) |
| T4 | done | ae398bb9 | nlu@v6 + compose@v10 read context (compose history redacted), append_next_step_offer |
| T5 | done | a9232c9b | pause consts, closing/with_closing/offer helpers, closing slot (ui.py, sse.ts), offer slots in route |
| T6 | done | aa685426 | warm abstain, new_card topic (offer_human false), scope v2, baseline lexicon |
| T7 | done | a2b55695 | summarize wired before understand (proposed), history append/clear, tests 1,2,5 |
| T8 | done | a769838f | card_info/card_block check state first + next-step offer; closing after verified lock; baseline appends offer |
| T9 | done | af01c718 | replacement only for eligible cards, block/human offers, unlock offer resume, closing after unlock/replacement |
| T10 | done | aa914933 | docs 02+04 updated; dev scenario d-decline_explain-normal_resolution-es-ar-02 reworded |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — card_select policy v2, focus hint, offer resolver, D2 allowlist, NLU schema
Changed: `flows/card_select.py` (`ReplacementPolicy`, policy fields `replacement`/`next_step_offer`, `next_step_offer_kind`, `select_card(..., *, focus_card_id, candidate_ids)`), `schemas.py` (`card_hint` allows `focus`; `Topic` + `new_card`), `policies/card_select.yaml` (v2), `policies/tools.yaml`, `tests/unit/test_card_select.py` (+`test_r1_focus_hint_never_crosses_customer`).
Facts: `next_step_offer_kind(policy, *, status, origin_kind)` exported from `flows/card_select.py`. `scope.py` `TOPICS` not touched, so T-later must add `new_card` there/in `topic_scope.yaml` (Topic Literal now has it).
SAFETY-CRITICAL (ADR-018): `policies/tools.yaml` line 9 `cards.get_block_origin.allowed_intents` is now `[card_status, card_block, card_unlock, replacement_request]`; the PR must flag it for the other dev's review.
Deviations: none.
Verify: pytest card_select+policy_registry → 4 passed; load version → 2; ruff check/format and mypy clean.

### T3 — `summary` step, context builder, history state, `summarize` node
Created: `backend/app/domains/conversation/context.py` (`WINDOW`, `ConversationContext`, `build_context`, `redact_values`), `nodes/summarize.py` (`SummaryDraft`, `summarize`), `prompts/summary@v1.md`.
Changed: `core/llm/registry.py` (`summary` step, Haiku 4.5, temp 0.0), `conversation/state.py` (`HistoryMessage`, `history`, `summary`), `test_r6_no_write_tools_in_llm_nodes.py` (+`test_r6_summarize_has_no_write_tools`).
Facts the next tasks need: `HistoryMessage` is defined in `state.py` and re-exported from `context.py`; `redact_values` also strips digits inside PII tokens (`⟨NAME_1⟩` -> `⟨NAME_⟨valor⟩⟩`); `summarize` is not wired into the graph (T7). On Windows consoles printing `⟨valor⟩` needs `PYTHONIOENCODING=utf-8`.
Deviations: none.
Verify: r6 + llm_client tests 9 passed; inline python OK; ruff check/format, mypy clean.

### T1 — Template variants, new kinds, R3/R8/R9 texts and test-harness defaults
Changed: `templates.py` (`_TEMPLATES` values `str | list[str]`; `get_template(kind, lang, rng=None)`, `template_variants`, module `_RNG`; 40 varied kinds with 3 variants/lang, variant 0 = the old text where there was one; new kinds `closing_question`, `offer_unlock`, `offer_human`, `replacement_needs_block`, `new_card_not_available`; `ask_which_card_*` no longer carry `{card_options}`; `decline_replacement_option` relabeled).
Changed: `tests/conftest.py` (autouse `_first_template_variant`; `ScriptedLLM` default `{"text": "resumen previo"}` for `summary` with no queue). Created `tests/unit/test_templates.py` (tests 13, 8). Fixed old-text asserts in `test_block_flows.py` (question alone; `offer_replacement` now ends ", ou ajudo você com mais alguma coisa?") and `test_sandbox_conversations.py`.
Facts: `offer_unlock`/`offer_human` have no placeholders; `abstain_fallback` variants keep the four placeholders and add a thank-you + question (T6 must replace `abstain.py:123` equality; under tests `get_template("fallback")` is variant 0). Files may be CRLF in the checkout; edit with care. Other tests asserting old offer/ask texts were not run.
Deviations: none.
Verify: pytest 4 files -> 19 passed; ruff check/format, mypy clean; grep guard clean.

### T5 — Offer and closing helpers, `closing` slot, offer-pause routing
Changed: `flows/actions.py` (`OFFER_REPLACEMENT_PAUSE`, `OFFER_UNLOCK_PAUSE`, `OFFER_BLOCK_PAUSE`, `CLOSING_PAUSE`, `closing`, `with_closing`, `offer`, `offer_pieces`; all in `__all__`), `ui.py` (`slot` + `"closing"`, docstring), `nodes/route.py` (`_CONFIRMATION_SLOTS` + `offer_unlock`, `offer_block`), `frontend/src/lib/sse.ts` (slot union; normalized to LF).
Facts: `offer(kind, language, card_last4)` and `offer_pieces(kind, language)` take kind as `str` ("replacement"|"unlock"|"human"). No flow calls them yet. Python on Windows: edit these CRLF/UTF-8 files with `open(..., encoding="utf-8", newline="")`, the default cp1252 corrupts accents.
Deviations: none.
Verify: pytest r3_flows+block_flows 9 passed; ruff check/format, mypy clean; biome ci sse.ts + typecheck pass.

### T6 — Warm out-of-scope replies, `new_card`, scope policy v2, baseline lexicon
Created: `backend/tests/unit/test_abstain_warm.py` (tests 10, 12).
Changed: `domains/policy/scope.py` (`TOPICS` + `new_card`, `TopicScope.offer_human=True`), `policies/scope.yaml` (v2, `new_card` offer_human false), `nodes/abstain.py` (new_card -> fixed template, no compose, no chips; human chip/fact only if `offer_human`; no `quick_replies` event when no chip; `text in template_variants("fallback", …)`), `baseline/lexicon.yaml` (new_card scope terms, replacement terms dropped, thanks_close +terminar/encerrar, new `affirm` intent).
Facts: new_card returns before any reason/compose lookup, so `_REASONS` has no `new_card_not_available` key.
Deviations: ES `abstain_fallback` variant 3 says "pueda", not "puedo" (T1 template); test 12 checks "pued" for ES. Not edited (templates.py not mine).
Verify: pytest 4 files -> 19 passed; ruff check/format, mypy clean.

### T4 — NLU and compose read the conversation context
Created: `prompts/nlu@v6.md` (history fence, `card_hint=focus`, `topic=new_card`, closing buttons), `prompts/compose@v10.md` (history for coherence only, `next_step_offer` hidden key).
Changed: `nodes/understand.py` (`PromptRef("nlu", 6)`, `run_nlu(..., context=)`, `_context(state)` drops this turn's own trailing customer entry), `nodes/compose.py` (`PromptRef("compose", 10)`, `context=` on `compose_checked`/`compose_reply`/`_compose_draft`, redacted history fence, `append_next_step_offer`, `next_step_offer` in `_HIDDEN_KEYS`), `tests/unit/test_compose.py` (label v10).
Facts: `append_next_step_offer(segments, facts_by_key, language)` reads the `card_mask` fact's raw value as `card_last4`. The three files were CRLF in the working tree; now LF (index is LF).
Deviations: none.
Verify: pytest compose+graph+r5_llm_guard -> 8 passed; ruff check/format, mypy clean.

### T10 — Contract and design docs, dev-scenario sweep
Changed: `docs/solution-docs/02-conversation-design.md` (§2 summary call and window, §3 `summarize` node and `offer_unlock`/`offer_block`, §4.6 state-first + closing, §4.9 eligibility/picker, §5 warm + `new_card` abstain), `docs/solution-docs/04-contracts.md` (§2 `focus`, `new_card`; §3 `closing` slot; §5 card_select v2, scope `offer_human` + `new_card`, tools.yaml allowlist marked safety-critical).
Dev scenarios changed: `eval/scenarios/dev/d-decline_explain-normal_resolution-es-ar-02.yaml` (3 cases: "una tarjeta nueva" -> "reponer mi tarjeta", since "tarjeta nueva" now routes to `new_card`). No other dev scenario had options-in-text, new-card or post-action thanks wording.
Deviations: none.
Verify: grep chain + heldout diff empty + yaml parse -> ok.

### T9 — Replacement eligibility, unlock offer resume, closing after unlock/replacement
Created: `backend/tests/unit/test_replacement_offers.py` (tests 9 x3, 11 unlock/replacement part).
Changed: `flows/replacement.py` (`_select_card` eligible set via origin for Blocked/locked + expiry, `focus_card_id`, `candidate_ids`; no eligible -> `replacement_needs_block` + `OFFER_BLOCK_PAUSE`; named non-eligible card: Active/lock -> needs_block with `selected_card_id`, bank_side/Suspended/Closed -> `offer("human")`; declined offer -> `closing`; verified write -> `with_closing`), `flows/card_unlock.py` (`focus_card_id`, `node == "offer"` resume: yes -> `_check_status_and_origin`, no -> `closing`; `with_closing`).
Facts: `test_block_flows.py` lines 244, 304, 353 (`debug.pending is None` after a verified replacement/unlock) now fail with `smalltalk.anything_else`; they need `pending == "smalltalk.anything_else"` (not in T9 Files; owner of test_block_flows.py must update).
Deviations: none.
Verify: new tests + r3_flows + step_up 7 passed; test_block_flows 3 failed (stale asserts above, outside T9 files); ruff check/format, mypy clean.
T9 addendum: `test_block_flows.py` lines 244/304/353 now expect `smalltalk.anything_else`; `test_es_lock_clarify_confirm_readback` (line 66, card_block verified lock) newly fails the same way, caused by the card_block closing change (T8), not T9.
T9 addendum 2: `test_block_flows.py` line 66 now expects `smalltalk.anything_else` (T8's verified-lock closing); file passes.

### T8 — State-first `card_info`/`card_block`, next-step offers, closing after a lock
Created: `backend/tests/unit/test_state_offers.py` (tests 6 es/pt, 7 x3, 11 lock part).
Changed: `flows/card_info.py` (focus passed; `_next_step_kind`, `next_step_offer` fact + `offer_pieces` on `card_status` only; reads `bank_write_tools.get_block_origin(…, "card_status")` only for Blocked/locked), `flows/card_block.py` (`_already_in_state` + offer before the block-kind question; `_resume_offer` for `pending.node=="offer"`: sí -> `_check_state_and_plan(block_kind=None)` or picker with no focus, no -> `closing`; verified lock -> `with_closing`, permanent keeps `offer_replacement`), `baseline/template_compose.py` (`append_next_step_offer`).
Facts: `_check_state_and_plan` now takes `block_kind | None` and asks lock-vs-block itself after the state check. `card_info` now needs `bank_write_tools` in config for non-active card_status turns (tests must use `make_session`).
Deviations: edited `tests/unit/test_block_flows.py` line 66 (`pending == "smalltalk.anything_else"` after a verified lock), not in my Files but a direct consequence (T1 touched the same file earlier).
SC8 manual proof (for the verifier, not run by me): web chat at http://localhost, lock a card -> chips "Algo más"/"Terminar"; tap "Terminar" -> farewell and closed conversation.
Verify: 5 pytest files -> 36 passed (+r6 scan 40 passed); ruff check/format, mypy clean.

### T7 — Memory wired into the turn graph
Created: `backend/tests/unit/test_conversation_memory.py` (tests 1, 2, 5; balance_due turns reach `compose`, `general_question` goes to `unsupported`).
Changed: `graph.py` (`summarize` node + `summarize → understand`, `_entry` "understand" → "summarize" only when not baseline), `nodes/__init__.py`, `nodes/load_session.py` (`_is_typed_turn`; appends customer text, skips address turn, human mode), `nodes/next_intent.py` (`finish` appends cardy reply), `nodes/smalltalk.py` (`_close` clears history/summary), `docs/diagrams/turn-graph-v0.mmd` regenerated.
Facts: seed memory in tests with `graph.aupdate_state(config, {"history": [...]}, as_node="finish")`. Mermaid shows the `load_session -> summarize` edge labelled "understand".
Deviations: none.
Verify: memory+graph+checkpoint_serde pass; `test_conversation_basics.py::test_block_then_balance_in_order` FAILS outside my files (after the card_block confirm, reply has 2 segments: action_done + closing question; the balance segment is missing; likely T8 mid-edit of `flows/card_block.py`). ruff, format, mypy, lint-imports clean.

### T5 repair — no closing while intents are queued
Changed: `flows/actions.py` `with_closing(state, update)` (signature now takes state; returns `update` unchanged when `len(intent_queue) > 1`); call sites in `card_block.py`, `card_unlock.py`, `replacement.py`. Declined-offer `closing(...)` calls unchanged. Verify: 22 passed; ruff, format, mypy clean.
T10 repair 1: `decision-log.md` amendments (D7 `summary` step, ADR-026 `offer_human`/`new_card`); `02` §4.6 reordered (state check first) and closing text + queue-drains-first noted (§4.6 step 6). Verify: greps ok, heldout diff empty.

### T7 repair — address-turn proof
Added `test_r5_address_turn_not_in_history` to `backend/tests/unit/test_conversation_memory.py` (seeded address pause: history unchanged, raw address in no history entry or LLM call). Verify: 4 passed; ruff check/format clean.

### T4 repair (verify round 1) — abstain wording in `compose@v10.md`
Changed: `prompts/compose@v10.md` only (abstain guidance + ES/PT examples per R8: apology, Swip only cards, thanks, open question, no chip labels); live Haiku calls returned the reference texts; pytest compose+abstain_warm -> 9 passed.

### T6 repair (verify round 1)
Changed: `templates.py` (`abstain_fallback` no longer inlines chip labels, 3 sentences, "puedo"/PT "posso"/"consigo", no "cuidar de"; `closing_question` offers to end the conversation), `abstain.py` (format only topic_label/reason), `test_abstain_warm.py` (ES requires "puedo"). Verify: 8 passed; ruff, mypy clean.
T8 repair 1: `card_info` sends `status="Blocked"` to compose for a locked Active card (reply says "Bloqueada", never "Activa", agrees with the unlock offer); "temporalmente" needs a new `status_label`/template (localization or templates.py), not done. Test asserts no "Activa", has "Bloqueada". Verify: state_offers + card_info_flows 15 passed; ruff, mypy clean.

### T5 repair 2 — closing after the queue drains
Changed: `nodes/next_intent.py` (`finish` appends `closing(lang)` segment, `pending` and `ui` via `_owes_closing`: verified action this turn, queue empty, no pending/escalation/handoff, not human mode); `test_conversation_basics.py::test_block_then_balance_in_order` (4 parts, closing last, pending `smalltalk.anything_else`). `actions.py` unchanged. Verify: 26 passed; ruff, format, mypy clean.
T8 repair 2: `format.py` `CardStatus` + "Locked" (ES "Bloqueada temporalmente", PT "Bloqueado temporariamente"); `compose._format_fact` cast widened; `card_info` sends `status="Locked"` for Active + locked (baseline shares `_format_fact`); test asserts "Bloqueada temporalmente". Verify: state_offers+card_info_flows+compose 3 files green; ruff, mypy clean.

### T5 repair 3 — dispute test asserts the closing
Changed: `tests/unit/test_dispute_flows.py` (`test_single_charge_questions_claim`: pending `smalltalk.anything_else`, reply ends with `closing_question`). Verify: full `uv run pytest -q` 199 passed, 27 skipped; ruff check/format clean.

### T2 repair — picker label for locked cards
Changed: `flows/card_select.py` (`_build_card_options` uses the "Locked" status label for Active+locked), `tests/unit/test_card_select.py` (+1 test). Verify: full unit suite 200 passed, 27 skipped; ruff and mypy clean.
T8 repair 3: block picker lists only Active, unlocked cards: `card_select.yaml` v3 `card_block` section (`eligible_statuses`, `exclude_locked`), `block_candidate_ids` fed to `select_card(candidate_ids=)` in `card_block`; none eligible -> new `block_none_eligible` template + `closing`; 04 §5 updated. Verify: full unit suite 204 passed, 27 skipped; ruff, mypy, load_policies clean.

### T6 repair 2 — `new_card_not_available` rewritten warmer (3 ES + 3 PT) in `templates.py`; 8 passed, ruff/mypy clean.

### T5 repair 4 — closing after every finished flow
Changed: `nodes/next_intent.py` (`next_intent` adds closing when the last queued flow intent finishes with no pending; `_closing_allowed` skips: pending, queue, escalation/handoff, human mode, quick_replies already in ui, `tx_search_ask_criterion`/`injection_suspected` replies); tests updated (`strip_closing` helper in conftest) + 2 new in `test_conversation_basics.py`. Verify: full `uv run pytest -q` 206 passed, 27 skipped.
