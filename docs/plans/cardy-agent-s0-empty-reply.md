# Plan: REQ-cardy-agent-s0 — keep the open question, never send an empty reply

Spec: [`docs/specs/cardy-agent-s0-empty-reply.md`](../specs/cardy-agent-s0-empty-reply.md) · Branch: `feat/cardy-agent-s0-empty-reply`

## Human answer that overrides one spec line

The human chose, after the spec's last edit, that **`open_question.ui` holds the asking node's own UI events, not the turn's `ui` list.** Where the spec's Contracts still say "`ui` = the turn's `ui` list", this rule wins. Reason, checked on disk: `ui` has no reducer (last write wins for the whole turn), so on a multi-intent turn an earlier intent's chips would otherwise be stored with a later intent's question (see the site table). `open_question.text` stays the last entry of the turn's `segments`. The asking turn itself is unchanged.

## Facts checked against the repo

**Branch and environment**
- Worktree is on `feat/cardy-agent-s0-empty-reply` off `develop` (51c72cc). Nothing of this card exists yet: `grep -rn "non_answer\|open_question" backend docs/solution-docs` finds only the unrelated `handoff_open_questions`.
- `backend/.venv` exists in this worktree (git-ignored). `cd backend && uv run pytest tests/unit/test_checkpoint_serde.py -q` gives 2 passed today, and `cd backend && uv run python -m app.domains.conversation.graph --mermaid` prints the graph today.
- No migration (checkpoints are created by the LangGraph saver, the alembic head is untouched), no new dependency, no frontend client regeneration, no `make data`, no stack restart.
- No existing test asserts behaviour this card changes. `tests/unit/test_graph.py:128` expects an empty reply, but in human mode, which stays empty.

**Graph mechanics the code task relies on**
- `TurnState` is in `backend/app/domains/conversation/state.py` (255–305, `clarification_failures` at 271). `GraphState(TurnState)` is in `backend/app/domains/conversation/graph.py` (172–213) and holds the per-turn channels (`ui`, `segments`, `write_failed`, `suggestion_accepted`, ...).
- `ui: NotRequired[list[UIEvent]]` has no reducer. `nodes/load_session.py` resets the per-turn channels in one dict (lines 82–101): `write_failed: False`, `suggestion_accepted: False`, `segments: RESET_SEGMENTS`, `ui: []`, `nlu: None`.
- The eight flow nodes are registered at `graph.py` 625–637 as `_track_segments(name, _guard_access(flow))`. `_guard_access` is at 396–424, `_track_segments` at 554–570, `_flow_segment` at 449–507. `_flow_segment` already yields the D11 segments with no change: an update with no `pending` key on a paused flow gives `status: "awaiting"` with the unchanged slot, and an update with `escalation_reason` gives `status: "handoff"`.
- `_after_flow` (`graph.py` 340–358) sends `escalation_reason == "clarification_exhausted"` to `handoff_summary`, and sends an update with no facts and an open pause to `finish`. No edge changes.
- `graph.py` cannot import `nodes/` or `flows/` at module level (they import `GraphState` from it; `build_graph` imports them inside its body). `fact_values.py` imports only the standard library, so `graph.py` may import `record` at module level.
- `nodes/route.py`: `route` is a pure edge function; `_answer_fits(nlu, pending)` is at 107–123. `nodes/understand.py` already imports `_answer_fits` across modules. Import it with `from app.domains.conversation.nodes.route import _answer_fits` (the package attribute `nodes.route` is the function, the dotted module import still works).
- On the LLM path `understand` writes only `nlu` and `language` (`nodes/understand.py:124`), so a non-answer turn does not touch `slots`, `selected_card_id` or `clarification_failures` before the wrapper runs.
- `flows/actions.py` `handoff(queue, reason, language)` (376–386) returns `{escalation_reason, handoff_queue, pending: None, confirmation_token_id: None}`. `ConfirmedWriteTools.cancel_plan(token_id)` is at `tools/executor.py:148`; `enqueue` reads it as `config["configurable"].get("bank_write_tools")` (`nodes/next_intent.py:71`).
- `nodes/next_intent.py`: `finish(state)` is sync and takes no config (104–124). `enqueue` clears `clarification_failures` at line 76, inside `if pending is not None`.
- `nodes/smalltalk.py`: the degraded branch (59–62) is the model for D7. With `nlu is not None`, `route` sends an `intents == []` turn to `smalltalk` only through the new D7 rule, so `not nlu.intents and not degraded` identifies D7 inside the node. `_close` is at 109–124.
- `takeover.py` `return_to_bot` writes its reset dict at lines 75–88 (`"clarification_failures": 0` at 86). It already writes a `GraphState`-only key (`handoff_request`).
- Templates that exist and are not edited: `fallback`, `clarify_rephrase`, `pending_reminder`, `otp_required`, `handoff_transfer`, `clarify_lock_vs_block` (`templates.py`).

**Where `OpenQuestion` lives (spec Open question 5, settled here)**
- `ui.py:27` imports `Fact` from `state.py`, so `state.py` cannot import `UIEvent`. `TurnState` cannot name a type declared in `graph.py` either (`graph.py` imports `state.py`).
- Settled: `OpenQuestion` is declared in `state.py` beside `Pending`, with `text: str` and `ui: list[Any]`, and a comment that the items are `UIEvent`s that cannot be named there. `open_question` stays a `TurnState` field as the spec says. The alternative (type and field on `GraphState` in `graph.py`, annotated `list[UIEvent]`) was not taken because the spec, its touch map and `02` §3 all place the field on `TurnState`.
- `test_checkpoint_serde.py` walks `get_type_hints(GraphState)` with `get_args` only and does not descend into a `TypedDict`, so it finds no new model. The serde works on values: every `UIEvent` member is already in `hosting.CHECKPOINT_TYPES`. No allowlist change, confirmed.
- LangGraph accepts a second, differing definition of a plain last-value channel (`langgraph/graph/state.py` 355–363 raises only for reducer channels), so the new plain channels are safe when `graph.py` runs as `__main__`.

**Two per-turn channels on `GraphState` (not `TurnState` fields, both reset by `load_session`)**
- `asked_ui: NotRequired[list[UIEvent] | None]`. `None` means no flow node wrote a flow-question `pending` this turn. A list is the asking node's own events (it may be empty).
- `non_answer_counted: NotRequired[bool]`. True only on a turn where the wrapper counted a non-answer. `finish` needs it for D4 "every other turn sets it to 0": `abstain` and `unsupported` are outside the touch map and can leave a flow question open, so `finish`, which every path reaches, does the reset.

**Test fixtures**
- `backend/tests/conftest.py`: `ScriptedLLM` (60–91), `make_session(customer_id, fakebank_dir, llm)` (172–246) returns a `Session` with `graph`, `config`, `store`, `overlay`, `handoff_tools`. Tests drive turns with `asyncio.run` and `run_turn` (`graph.py:841`), and read state with `await session.graph.aget_state(session.config)` (`.values`).
- Template variants are pinned to variant 0 by an autouse fixture, so reply equality across turns is stable.
- `debug.tools_called` is empty with `make_session` unless the test wraps the read tools: `session.config["configurable"]["bank_tools"] = _RecordingBankTools(...)` from `app.domains.conversation.sandbox` (precedent `tests/unit/test_tx_search_flow.py` 169–170). Its `.calls` list is cumulative over the session, and `load_session` adds `get_profile` every turn.
- Write tools are not in `tools_called`. The R2 proofs are `session.overlay.locked` / `session.overlay.blocked` (precedent `test_block_flows.py` 147–148) and the raw plans in `session.store._plans` (`issue` adds a plan, `cancel` pops it; precedent `test_block_flows.py:299`).
- A handoff needs a scripted `handoff_summary` output: `HandoffSummaryDraft(request=...)` from `app.domains.conversation.nodes.handoff_summary`. The created packet is `session.handoff_tools.created[-1]` with `.reason`.
- Fixture customers: `CLI-TFMULTI00001` (several cards, "quiero bloquear" asks "¿Cuál tarjeta quieres bloquear?", `test_block_flows.py` 362–388) and `CLI-TFSINGLE0002` (one card).

**Docs anchors (by text, line numbers as of this branch)**
- `02-conversation-design.md`: state list on line 55 (`clarification_failures` is in the `TurnState` part, before the "graph-local channels" tail), P1 paragraph on line 61, §5 rules table ends on line 145 ("Unverified action").
- `04-contracts.md` §6: the `fact_values: [str]` sentence is on line 291 (the spec says 293), the `awaiting_slot` bullet on line 304.

**Pause-opening sites, checks (a), (b), (c)**

(a) the question is its own segment and the last of the turn. (b) what the node's own update carries in `ui`, which is what `open_question.ui` will hold. (c) the update writes `pending`. Paths are under `backend/app/domains/conversation/flows/`.

| # | Site | Slot | (a) | (b) node's own `ui` | (c) |
|---|---|---|---|---|---|
| 1 | `actions.py:139-142` `offer_pieces`, `offer` 157-165 | offer_replacement, offer_unlock | pass, through callers 6 and 9 | none | yes |
| 2 | `actions.py:197-237` `start_plan` | confirmation | pass | `confirm` | yes |
| 3 | `actions.py:389-395` `otp_pause` | otp | pass | `otp_required` | yes, also on a re-pause |
| 4 | `card_block.py:164-173` | card_hint | pass | `card_picker` | yes |
| 5 | `card_block.py:216-239` `_ask_block_kind` | block_kind | pass | `quick_replies` (`block_kind`) | yes, also on its own re-ask |
| 6 | `card_block.py:304-308` `already_in_state` + `offer` | offer_replacement, offer_unlock | pass, `[already_in_state, offer]` | none | yes |
| 7 | `card_block.py:393-401` after a permanent block | offer_replacement | pass, `[action_done, offer]` | none | yes |
| 8 | `card_info.py:114-130` | card_hint | pass | `card_picker` | yes |
| 9 | `card_info.py:172` `offer_pieces`, text added by `nodes/compose.py:535-542` | offer_replacement, offer_unlock | pass, the offer is appended after the footnote and the read-only note (same in the baseline) | none | yes |
| 10 | `card_unlock.py:112-118` | card_hint | pass | `card_picker` | yes |
| 11 | `card_unlock.py:176-190` | offer_replacement | pass, `[no_undo, offer]` | none | yes |
| 12 | `replacement.py:158-164` | card_hint | pass | `card_picker` | yes |
| 13 | `replacement.py:169-173` | offer_block | pass | none | yes |
| 14 | `replacement.py:195-196` | offer_block | pass | none | yes |
| 15 | `replacement.py:257-264` | address_confirm | pass | none | yes |
| 16 | `replacement.py:307-311` `_ask_address` | address (never reaches `understand`, never replayed) | pass | none | yes |
| 17 | `decline_explain.py:101-113` | card_hint | pass | `card_picker` | yes |
| 18 | `decline_explain.py:195-216` `_offer` | transactions | pass, no compose | `transaction_list` | yes |
| 19 | `unrecognized_charge.py:120-134` | card_hint | pass | `card_picker` | yes |
| 20 | `unrecognized_charge.py:188-202` | transactions | pass, no compose | `transaction_list` | yes |
| 21 | `unrecognized_charge.py:248-261` `_ask_possession` | card_possession | pass | none | yes |
| 22 | `unrecognized_charge.py:324-343` `_ask_next_question` | dispute_question | pass | none | yes, every time, also when the slot is unchanged |
| 23 | `tx_search.py:360-385` `offer_tx_pick` (also used by `tx_explain.py:94,124`) | transactions | pass, no compose | `transaction_list` | yes |

- (a) holds on multi-intent turns too: a pause sends the turn to `finish`, and `finish` appends a closing only when nothing is pending. One note: `dispute_block_refused_offer_claim` is a single segment that starts with "No bloqueé tu tarjeta." and ends with the question; it is replayed whole.
- (c) holds, and the reverse holds: replies that keep a pause without asking again (`nothing_pending`, `pending_reminder`, `{"escalation_reason": "tool_failure"}`), the `_guard_access` refusal, `abstain`, `unsupported` and `smalltalk` on a flow pause never write `pending`. Only flow nodes write a flow-question `pending`, so a wrapper on the eight flow nodes sees every such write.
- (b) with the turn's `ui` list would fail at sites 1, 6, 9, 11, 13, 14 and 15 on a multi-intent turn, because `decline_explain.py:309`, `tx_explain.py:240` and `actions.py:143-154` (`offer_pieces("human")`) write chips without pausing. Capturing the node's own update removes the problem with no flow change.

## Components

- **State** (`state.py`): `OpenQuestion`, and the `TurnState` fields `non_answer_failures` and `open_question`. Depends on nothing.
- **Per-turn channels** (`graph.py` `GraphState`, `nodes/load_session.py`): `asked_ui` and `non_answer_counted`. Depend on nothing.
- **Routing rule** (`nodes/route.py`): sends a non-answer on a flow question to the paused flow's node, and an `intents == []` turn with no flow question to `smalltalk`. Depends on `_answer_fits`, which exists.
- **Non-answer wrapper** (`graph.py`, between `_guard_access` and `_track_segments` on the eight flow nodes): counts, replays or exhausts, and captures `asked_ui`. Depends on the state fields, `route._answer_fits`, `actions.handoff`, `fact_values.record`, `bank_write_tools.cancel_plan`.
- **`finish`** (`nodes/next_intent.py`): writes and clears `open_question`, resets `non_answer_failures`, and holds the empty-reply backstop. Depends on the two per-turn channels.
- **D7 reply** (`nodes/smalltalk.py`) and the **explicit resets** (`enqueue`, `smalltalk._close`, `takeover.return_to_bot`).
- **Tests** (`backend/tests/unit/test_non_answer.py`, new). **Docs** (`02` §3 and §5, `04` §6).

## Build order

1. State fields and per-turn channels first: every other piece reads or writes them.
2. The wrapper and the route rule together, in the same task. Routing a non-answer to a flow node before the wrapper exists would send it into the flow's resume code, which the spec forbids. That is why the code is one task and is not split.
3. `finish`: capture, clear, reset and backstop. Replay needs a stored question, so it comes before the conversation tests.
4. `smalltalk` D7 and the three explicit resets.
5. The four tests, then the task's narrow verify.
6. Docs are independent of the code and build beside it.

## Touch map

| File | New or modified | What changes |
|---|---|---|
| `backend/app/domains/conversation/state.py` | modified | `OpenQuestion`; `non_answer_failures` and `open_question` on `TurnState`; `__all__` |
| `backend/app/domains/conversation/graph.py` | modified | `asked_ui` and `non_answer_counted` on `GraphState`; the non-answer wrapper; the eight flow-node registrations |
| `backend/app/domains/conversation/nodes/load_session.py` | modified | resets the two per-turn channels |
| `backend/app/domains/conversation/nodes/route.py` | modified | the non-answer rule and the D7 rule; module docstring order list |
| `backend/app/domains/conversation/nodes/next_intent.py` | modified | `finish`: `open_question` write and clear, counter reset, backstop; `enqueue` resets the counter |
| `backend/app/domains/conversation/nodes/smalltalk.py` | modified | D7 `clarify_rephrase` branch; `_close` resets the counter |
| `backend/app/domains/conversation/takeover.py` | modified | `return_to_bot` resets both fields |
| `backend/tests/unit/test_non_answer.py` | new | the four tests |
| `docs/solution-docs/02-conversation-design.md` | modified | §3 state list, §3 paragraph after P1, §5 sentence |
| `docs/solution-docs/04-contracts.md` | modified | §6 `fact_values` sentence, §6 D11 line |

Not touched: every module under `flows/`, `runner.py`, `ui.py`, `hosting.py`, `fact_values.py`, `templates.py`, `schemas.py`, `nodes/understand.py`, `policies/`, `prompts/`, `classifier/`, `baseline/`, `eval/`, `frontend/`, migrations, `tests/unit/test_checkpoint_serde.py`.

## Risks and mitigations

| Risk | Mitigation (in the task list) |
|---|---|
| A non-answer reaches a flow's resume code, where a non-"sí" cancels or declines (06 R2). | Route rule and wrapper ship in one task. The wrapper returns before calling the node. Test 4 asserts no write and the same token. |
| The wrapper issues or consumes a plan. | It calls only `cancel_plan`, and only at count 2. Test 4 asserts `len(session.store._plans) == 1` after the first non-answer and the token gone after the second. |
| The counter survives a turn it should not (abstain, `unsupported`), so the next non-answer hands off at once. | `finish` resets it on every turn the wrapper did not flag. T1 acceptance names it. |
| `open_question` outlives its pause (handoff, P1, cancel, takeover) and a later non-answer replays a dead question. | `finish` clears it whenever the turn ends with no flow question open; `return_to_bot` clears it. Test 1 asserts `None` after the handoff. |
| An earlier intent's chips are stored with a later question. | The wrapper captures the node's own `ui`. T1 acceptance names it. |
| `OpenQuestion` breaks `get_type_hints(GraphState)`, the serde allowlist or the `--mermaid` entry point. | Declared in `state.py` with `list[Any]`. T1 verify runs `test_checkpoint_serde.py` and the `--mermaid` command. |
| The backstop speaks in human mode. | Guarded by `mode != "human"`. Test 3 asserts `""`. |
| A conversation paused before the deploy has no stored question. | D17: the wrapper writes no segment and the backstop answers. Covered by the wrapper's "no `open_question`" branch in T1 acceptance. |
| The code task grows into `flows/` to fix a capture problem. | The site table shows no site needs it. T1 verify fails if `flows/`, `runner.py`, `hosting.py`, `ui.py` or `templates.py` differ from `develop`. |

## Tests

All four in `backend/tests/unit/test_non_answer.py`, written by T1.

| Spec test | Proves | Task |
|---|---|---|
| `test_non_answer_keeps_card_question_es` | Done-when 1 (ES), D4, D7, replay reads nothing, clear rule | T1 |
| `test_non_answer_keeps_card_question_pt` | Done-when 1 (PT), question survives, write rule | T1 |
| `test_finish_never_sends_empty_reply` | Done-when 2, 06 R11 | T1 |
| `test_r2_non_answer_on_confirmation_never_writes` | 06 R2, D2, D4, D5 | T1 |

The multi-intent capture rule has no assertion: it is neither a safety rule nor a "Done when" line. It is checked by reading the wrapper (T1 acceptance). Success criteria 5 and 6 (`make check`, the full `git diff --stat develop`) belong to the verifier.

## Tasks

- [ ] T1: Non-answer re-ask, `open_question` capture and the `finish` backstop, with the four tests
  - Depends on: nothing
  - Read exactly these: `docs/specs/cardy-agent-s0-empty-reply.md` §Decisions, §Contracts and §Test list (one override: `open_question.ui` is the asking node's own events, not the turn's `ui` list); `backend/app/domains/conversation/graph.py` lines 172–213, 396–424 and 554–637 (`GraphState`, the two wrappers the new one sits between, the node registrations); `backend/tests/unit/test_block_flows.py` lines 1–150 and 362–388 (the test analog: `ScriptedLLM`, `make_session`, `run_turn`, `aget_state`, `asyncio.run`)
  - Acceptance:
    - `state.py`: `class OpenQuestion(TypedDict)` beside `Pending`, with `text: str` and `ui: list[Any]` and a comment that the items are `UIEvent`s (`ui.py` imports this module, so the name cannot be used here). `TurnState` gains `non_answer_failures: NotRequired[int]` and `open_question: NotRequired[OpenQuestion | None]`. `OpenQuestion` is in `__all__`. No other `TurnState` field, no other key.
    - `graph.py` `GraphState` gains two per-turn channels with a comment like the one on `suggestion_accepted`: `asked_ui: NotRequired[list[UIEvent] | None]` and `non_answer_counted: NotRequired[bool]`. `nodes/load_session.py` resets them in its per-turn dict to `None` and `False`.
    - `graph.py` has one new wrapper with the signature shape of `_guard_access` plus the node name. The eight flow nodes are registered as `_track_segments(name, <wrapper>(name, _guard_access(flow)))`. No new node, no new edge.
    - The wrapper acts only when all hold: `nlu` is not `None`; `degraded` is false; `nlu.intents == []`; `pending` is set, its `awaiting_slot` is not `"anything_else"` and `_FLOW_NODES.get(pending["flow"]) == name`; `_answer_fits(nlu, pending)` is false. `_answer_fits` and `flows.actions.handoff` are imported inside the function (module-level imports would be circular); `fact_values.record` may be imported at module level.
    - When it acts it never calls the wrapped node. With `new = state.get("non_answer_failures", 0) + 1`:
      - `new == 1` and `open_question` set: returns `{"non_answer_failures": 1, "non_answer_counted": True, "segments": [open_question["text"]], "ui": list(open_question["ui"])}` and calls `record(open_question["text"])`. It calls no tool, no store and no LLM, and writes none of `pending`, `confirmation_token_id`, `open_question`.
      - `new == 1` and no `open_question`: returns `{"non_answer_failures": 1, "non_answer_counted": True}` only.
      - `new >= 2`: if `confirmation_token_id` is set and `config["configurable"].get("bank_write_tools")` is not `None`, awaits `cancel_plan(token_id)`; then returns `{**handoff("atencion", "clarification_exhausted", language), "non_answer_failures": 0}`. It issues no plan.
    - When it does not act it awaits the wrapped node and returns its update unchanged, except: if the update has a `pending` that is not `None` and whose `awaiting_slot` is not `"anything_else"`, it adds `"asked_ui": list(update.get("ui") or [])`. This is the node's own update, never `state["ui"]`.
    - `nodes/route.py`: after the existing `_answer_fits` branch and the closing-suggestion branch, and before the management-intents line, `if not degraded and not nlu.intents:` returns `_FLOW_NODES.get(pending["flow"], "unsupported")` when `pending` is a flow question (set, `awaiting_slot != "anything_else"`), else `"smalltalk"`. Everything above it (missing NLU, degraded exhaustion, injection, escalation, abstain, degraded rephrase, fitting answer) is unchanged. The module docstring's order list names the new step.
    - `nodes/smalltalk.py`: right after the degraded branch, `nlu.intents == []` on the LLM path returns only `{"segments": [get_template("clarify_rephrase", language)]}`; `pending` and `closing_suggestion` are not written. `_close` adds `"non_answer_failures": 0`.
    - `nodes/next_intent.py` `finish`, with "flow question open" meaning `state.get("pending")` is set and its `awaiting_slot != "anything_else"`:
      - not open: `update["open_question"] = None` (bot or human mode);
      - open, `state.get("asked_ui") is not None` and `segments` is non-empty: `update["open_question"] = {"text": segments[-1], "ui": list(asked_ui)}`;
      - open otherwise: `open_question` is not written;
      - `update["non_answer_failures"] = 0` unless `state.get("non_answer_counted")` is true;
      - backstop: when the joined reply is `""` and `mode != "human"`, the reply is `get_template("fallback", state.get("language", "es"))` and then goes through the existing `introduced` / `history` lines; in human mode it stays `""`. Nothing else about `finish` changes.
    - `enqueue` adds `update["non_answer_failures"] = 0` beside its `clarification_failures` reset. `takeover.return_to_bot` adds `"non_answer_failures": 0` and `"open_question": None` to its reset dict.
    - `clarification_failures` is incremented and reset exactly where it is today. No file under `flows/`, `policies/`, `prompts/` changes, nor `runner.py`, `hosting.py`, `ui.py`, `templates.py`, `fact_values.py`, `tests/unit/test_checkpoint_serde.py`.
    - `backend/tests/unit/test_non_answer.py` holds exactly the spec's four tests, with `ScriptedLLM` and fixed `NLUResult`s (a non-answer is `NLUResult(language=..., intents=[], status="clear")` with default slots), turns driven by `asyncio.run` and `run_turn`, state read with `aget_state`:
      - `test_non_answer_keeps_card_question_es` (`CLI-TFMULTI00001`, read tools wrapped with `_RecordingBankTools` from `app.domains.conversation.sandbox`): turn 0 "mmm" replies `clarify_rephrase` and leaves `non_answer_failures` at 0; "quiero bloquear" asks "¿Cuál tarjeta quieres bloquear?"; "Todas" returns the same reply, `debug.pending == "card_block.card_hint"`, `debug.route == "card_block"`, the state's `ui` equals the asking turn's `ui`, and the read-tool `.calls` list grew by `get_profile` only; "Todas" again creates a handoff with reason `clarification_exhausted` and leaves `open_question` `None`. Script one `handoff_summary` output.
      - `test_non_answer_keeps_card_question_pt` (`CLI-TFMULTI00001`): "quero bloquear meu cartão" asks "Qual cartão você quer bloquear?"; "Todos" returns the same question with `pending` and `open_question` equal to their values after the asking turn; a `card_hint="credit"` answer moves on and `open_question["text"]` equals that turn's reply.
      - `test_finish_never_sends_empty_reply`: `finish` called directly with `segments=[]` returns `get_template("fallback", lang)` for `es` and `pt` in bot mode, and `""` with `mode="human"`.
      - `test_r2_non_answer_on_confirmation_never_writes` (`CLI-TFSINGLE0002`): a `card_block` request with `status="ambiguous"`, `clarification="lock_vs_block"` opens the `block_kind` pause; a non-answer re-asks `clarify_lock_vs_block` with its `quick_replies` and creates no handoff; `block_kind="temporary_lock"` opens the `confirmation` pause; first non-answer: same reply, the state's `confirm` event and `confirmation_token_id` equal the asking turn's, `len(session.store._plans) == 1`, `session.overlay.locked == set()` and `session.overlay.blocked == set()`; second non-answer: handoff `clarification_exhausted`, the token is no longer in `session.store._plans`, both overlay sets still empty. Script one `handoff_summary` output.
  - Verify: `cd backend && uv run pytest tests/unit/test_non_answer.py tests/unit/test_checkpoint_serde.py -q && uv run python -m app.domains.conversation.graph --mermaid > /dev/null && uv run ruff check app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/takeover.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/nodes/load_session.py tests/unit/test_non_answer.py && uv run ruff format --check app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/takeover.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/nodes/load_session.py tests/unit/test_non_answer.py && uv run mypy app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/takeover.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/next_intent.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/nodes/load_session.py && git diff --quiet develop -- app/domains/conversation/flows app/domains/conversation/runner.py app/domains/conversation/hosting.py app/domains/conversation/ui.py app/domains/conversation/templates.py tests/unit/test_checkpoint_serde.py` (expected: 6 passed, four of them in `test_non_answer.py`)
  - Files: `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/load_session.py`, `backend/app/domains/conversation/nodes/route.py`, `backend/app/domains/conversation/nodes/next_intent.py`, `backend/app/domains/conversation/nodes/smalltalk.py`, `backend/app/domains/conversation/takeover.py`, `backend/tests/unit/test_non_answer.py`

- [ ] T2: Update `02` §3 and §5 and `04` §6 for the non-answer rule
  - Depends on: nothing (the text comes from the spec, not from T1's code)
  - Read exactly these: `docs/specs/cardy-agent-s0-empty-reply.md` §Decisions D1, D2, D4, D7, D8, D11, D16 and §Contracts "Graph state" and "Docs to update"; `docs/solution-docs/02-conversation-design.md` lines 54–63 and 127–147; `docs/solution-docs/04-contracts.md` lines 289–309
  - Acceptance:
    - `02` §3, the state list (the line under "**Graph state**"): `non_answer_failures` and `open_question` are added in the checkpointed part, next to `clarification_failures` and before the "graph-local channels" tail. `open_question` is described as the text and the asking node's own UI events of the open flow question, written and cleared by `finish`.
    - `02` §3, one new paragraph right after the P1 paragraph ("**A new flow intent while one is paused (P1).**"), stating D1, D2, D7 and D8: which pauses the rule covers, that a no-intent message that does not answer the open flow question changes nothing but `non_answer_failures` and gets the same question and UI again, that the same message with no flow question open gets `clarify_rephrase` and is not counted, and that a bot turn with no segment replies with the `fallback` template (never in human mode).
    - `02` §5, one sentence right after the rules table (after the "Unverified action" row, before "Queues:"): such a message is re-asked once and hands off with `clarification_exhausted` on the second in a row, counted in `non_answer_failures` and not in `clarification_failures`. The two "Clarify" rows of the table are unchanged.
    - `04` §6, the sentence that defines `fact_values: [str]`: it adds that on a replayed question the stored sentence is recorded as one value (D16).
    - `04` §6, one new bullet right after the `awaiting_slot` bullet, stating D11 for a replayed question: the re-ask turn writes the paused flow's node as `route` and one `awaiting` segment with the unchanged slot, the exhaustion turn writes that segment with `status: "handoff"`, a no-intent turn with no flow question open writes `route: "smalltalk"` and `segments: []`, and a backstop turn keeps its route and segments.
    - Both `04` additions contain the words "replayed question". Where the spec says "the turn's `ui` list", the docs say the asking node's own UI events. No other section of either file changes.
  - Verify: `test "$(grep -c 'non_answer_failures' docs/solution-docs/02-conversation-design.md)" -ge 3 && grep -q 'open_question' docs/solution-docs/02-conversation-design.md && test "$(grep -c 'replayed question' docs/solution-docs/04-contracts.md)" -ge 2 && git diff --stat develop -- docs/solution-docs` (expected: exactly the two files listed, a few lines each)
  - Files: `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/04-contracts.md`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2 | no | Two independent chains with disjoint files: backend code and its one new test file (T1), two solution docs (T2). Neither adds a dependency, applies a migration or restarts the stack. T2 writes from the spec, so it needs nothing T1 builds. |
