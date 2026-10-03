# Spec: cardy-agent-s0-empty-reply

Card source: [`docs/requirements/cardy-agent.md`](../requirements/cardy-agent.md), slice **S0** only (not a `07` row; S1–S3 are other cards) · owner **Dev A** (human, pass 2) · reviewer **Dev B** (safety-critical, see D14) · branch `feat/cardy-agent-s0-empty-reply` off `develop` (51c72cc). In this spec "Done when" means S0's two lines in that doc. Safety rules are written "06 R1…R13".

## Objective

Stop the current pipeline from answering with an empty message. Today, on the LLM-NLU path, a message that carries no intent and does not answer the open question ("Todas" after "¿Cuál tarjeta quieres bloquear?") goes `route → enqueue → finish`: `enqueue` deletes the open question and `finish` joins zero segments into `""`. This card (1) keeps the open flow question and asks it again, counting the miss so the existing `clarification_exhausted` handoff still applies, and (2) makes `finish` send the safe fallback whenever a bot turn produced no segment. It serves both S0 "Done when" lines and the requirement's "No turn ends with an empty reply, on either path". No agent code, no prompt change, no policy change.

## Decisions

A **non-answer** is a turn that reached `understand` on the LLM path whose `NLUResult` has `intents == []` and for which `route._answer_fits(nlu, pending)` is false. A **flow question** is an open `pending` whose `awaiting_slot` is not `anything_else`.

| # | Decision | Why |
|---|---|---|
| D1 | The keep-and-re-ask rule covers every flow question: `card_hint`, `block_kind`, `confirmation`, `otp`, `transactions`, and the yes/no pauses `address_confirm`, `offer_replacement`, `offer_unlock`, `offer_block`, `card_possession`, `dispute_question`. It does not cover the `anything_else` closing pause (D7). The `address` pause never reaches `understand` (`graph._entry`), so it is unaffected. | Human Q1 (a). Requirement S0 item 1. |
| D2 | A non-answer on a flow question changes nothing but `non_answer_failures` (D4): `pending`, `confirmation_token_id`, `intent_queue`, `slots` and `selected_card_id` stay as they were. No plan is cancelled, no plan is issued, no tool with a side effect runs. `enqueue`'s P1 clearing stays for turns that carry a real flow intent. | Human Q1 (a). 06 R2. `02` §3 P1. |
| D3 | The re-ask is the flow's own question again, with its UI. **Amended by the replay decision (D15):** it is the sentence the asking turn sent and the asking node's own UI events, repeated unchanged from `open_question` (Contracts). **Amended again (human decision on the `ui` write rule):** the UI is the asking node's own events, not the turn's `ui` list, so a replay shows only the question's own UI; the asking turn itself is unchanged and still shows whatever it shows today. Nothing is rendered again: no template or variant is picked, no read tool is called, no LLM call writes it. It contains the question only: never the answer or `action_done*` text that preceded the question on the asking turn. The first version of this row said the question was re-rendered from the same template kind and that a varied template could pick another variant; the replay decision replaces that. | Human Q2 (a). Human decision on the re-ask mechanism ("replay a stored question"). Human decision on the `ui` write rule, after the planner's finding (Contracts, `open_question` write rule). `02` §4.1 "ask again". 06 R3, R4. |
| D4 | Non-answers are counted per open question, in a new checkpointed field `non_answer_failures` (Contracts), separate from `clarification_failures`:<br>• A non-answer on a flow question (D1) adds 1.<br>• When the new value is 1 the turn re-asks (D3).<br>• When the new value reaches 2 the turn does not re-ask: it sets `escalation_reason = "clarification_exhausted"`, goes `handoff_summary → handoff` (queue `atencion`, which `policies/escalation.yaml` gives for this reason, D19), and leaves the field at 0.<br>• Every other turn sets it to 0: a turn that asks a question, a fitting answer, a turn with any intent, an abstain, a button or step-up turn, a degraded turn.<br>So the first non-answer always re-asks and the second in a row hands off, on every pause. `clarification_failures` and everything that increments or resets it today stay unchanged; a non-answer never touches it. This departs from the requirement's literal "counts toward `clarification_failures`", which the human accepted, because that counter is already 1 after `card_block` asks "¿temporal o definitivo?" (`_ask_block_kind`) and would hand off on the first non-answer. | Human answer at the gate, option (a). The reset by every other turn (any intervening turn, not only a question asked or answered) was derived, shown to the human and not vetoed. Requirement S0 item 1. `02` §5. ADR-004. `policies/escalation.yaml` v6. `flows/card_block.py` 216–231. |
| D5 | When D4's handoff happens on a `confirmation` pause, the open plan is cancelled through `bank_write_tools.cancel_plan(token_id)` before the handoff, as `enqueue` and `actions.cancel` do today. Nothing runs. | Human Q3 (a). 06 R2. `04` §7 (`cancel` is idempotent). |
| D6 | **No template text changes.** On this handoff the customer reads `handoff_transfer` ("Te estoy transfiriendo con una persona del equipo de {queue_label}. Tu caso es {reference}…" / "Estou transferindo você para uma pessoa da equipe de {queue_label}. Seu caso é {reference}…"), which is already neutral. The card-specific `clarification_exhausted` customer template is spoken only by the `fallback` node, and `graph._after_flow` sends this reason to `handoff_summary`, never to `fallback`. The agent-facing fallback text (`handoff_summary._FALLBACK`) is neutral too. This corrects pass 1, which said a neutral wording was needed. | `graph._after_flow`, `nodes/handoff.py`, `nodes/fallback.py`. Human Q3 (a) accepted a neutral wording; none has to be written. |
| D7 | A turn with `intents == []` on the LLM path and no flow question open (no `pending`, or the `anything_else` closing pause) is answered by `smalltalk` with `clarify_rephrase`. It is not counted (it touches neither `clarification_failures` nor, beyond D4's reset to 0, `non_answer_failures`) and never hands off. An open closing pause and its `closing_suggestion` stay as they are, as on the degraded path. | Human Q4 (b), Q1 (a). `nodes/smalltalk.py` (degraded branch leaves the pause open). |
| D8 | `finish` backstop: when the joined reply is empty and `mode != "human"`, the reply is `get_template("fallback", language)`. No handoff, no change to `pending` or any other field beyond what `finish` already does for any reply. In human mode the reply stays empty (`relay_to_agent`). | Requirement S0 item 2. Assumption 5 (pass 1, not contested). `02` §3 (human mode has no bot reply). 06 R11. |
| D9 | The degraded (classifier) path keeps its own rule: `clarify_rephrase`, pause kept, second miss in a row hands off. D1–D7 apply only when `state["degraded"]` is false. | Assumption 2. `learned-intent-fallback` D8. |
| D10 | A turn with only management intents on an open flow question keeps today's reply (`pending_reminder`, or `otp_required` for `otp`) and does not count. It carries an intent, so it is not a non-answer. | Requirement S0 item 1 ("carries no intent"). `nodes/smalltalk.py`. |
| D11 | Audit shape. A re-ask turn writes `reply_sent.route` = the paused flow's node and one segment `{intent: <paused flow's intent>, route: <flow node>, status: "awaiting", awaiting_slot: <unchanged slot>}`. The exhaustion turn writes that segment with `status: "handoff"`, as a flow's own exhaustion does today. A D7 turn writes `route: "smalltalk"`, `segments: []`. A D8 backstop turn keeps the route and segments the turn already had. | Assumption 6. `04` §6. `graph._flow_segment`. |
| D12 | `system="baseline"` shares `route` and `finish`, so it gets the same behaviour. No baseline file changes. | `graph.build_graph` (the baseline swaps four nodes only). `personalidad-cardy` D12. |
| D13 | `nlu@v7`, `schemas.py`, `policies/*.yaml` and `templates.py` are not changed. "Todas" stays unrepresentable as a slot; S0 only keeps the question alive. | Assumption 1. Requirement S0 scope. 06 R8. |
| D14 | The card is treated as **safety-critical**: Dev B reviews the PR before merge. It changes when the `clarification_exhausted` handoff fires and what happens at a `confirmation` pause (the 06 R2 surface). No file under `conversation/tools/`, `policies/` or `domains/identity` changes, so the human may overrule this at the gate. | ADR-018 (amended 2026-09-26). Human Q5 (owner Dev A). |
| D15 | Re-ask mechanism: **replay a stored question.** The turn that asks a flow question stores the question's text and UI events in one new checkpointed field, `open_question`, written by `finish`. One wrapper in `graph.py`, on the eight flow nodes beside `_guard_access` and `_track_segments`, handles a non-answer: it counts it (D4), then replays the stored question or sets the exhaustion reason, and does not call the flow. `route` sends a non-answer on a flow question to the paused flow's own node (`_FLOW_NODES[pending["flow"]]`), so the turn's route and segment are the flow's (D11) with no new branch node and no change to `runner.py`. Exhaustion leaves through the existing `_after_flow` edge to `handoff_summary`. **No flow module changes.** Accepted with it: the `confirm` card shown again is exactly the one issued (same `token_id` and steps, `issue_plan` not called again); the field holds code-built text with card masks and merchant and amount labels, the class of data already in `history`; the picker or list shown again is the one read on the asking turn, not a fresh read. | Human decision on the re-ask mechanism. Planner facts: `route` is an edge function and cannot write state; `runner.py:81` mirrors `_BRANCH_NODES` and is outside the touch map. |
| D16 | On a replay turn the wrapper calls `fact_values.record(<stored sentence>)`, so `reply_sent.fact_values` still covers every digit run in the reply and the eval `grounding` check reads the turn as grounded. The stored shape stays text and UI events. The sentence was already covered by the asking turn's own `fact_values`, so this lets through nothing that was not grounded once. | `04` §6 ("`fact_values` lists … every value code wrote into the turn's reply … the eval `grounding` check reads it"). The human's shape (text and UI events). Precedent: `card_options` is recorded as one multi-line string (`flows/card_select.py:172`). Derived by the spec author as the one option that keeps both `04` §6 and the approved shape; shown to the human, not vetoed. Not a human decision. |
| D17 | When a non-answer finds no `open_question` (a conversation that was paused before this change was deployed), the wrapper writes no segment. D8's backstop then answers `fallback`, the pause stays, the miss is counted, and the second miss in a row hands off as D4 says. | D4 and D8 as approved; no new behaviour is added. |
| D18 | Two per-turn channels on `GraphState` (not `TurnState`, so not part of the checkpointed contract), both reset by `load_session` at the start of every turn: `asked_ui`, the asking node's own UI events, kept by the wrapper for `finish` to store in `open_question.ui`; and `non_answer_counted`, set when this turn already counted a non-answer, so one turn increments `non_answer_failures` at most once and `finish` resets the count on every other turn (D4). | Derived by the planner (plan, "Two per-turn channels on `GraphState`"), shown to the human, not vetoed. Not a human decision. `asked_ui` carries the human's `ui` write rule (D3). |
| D19 | The exhaustion handoff's queue is policy, not code. The wrapper never writes a queue literal: it passes `handoff()` the queue that `rule_queue` reads from the `clarification_exhausted` rule in `policies/escalation.yaml` (today `atencion`), resolved at call time. What the human approved is unchanged: handoff, reason `clarification_exhausted`, queue `atencion`. This corrects the first wording of the wrapper table, which named `actions.handoff("atencion", …)` with a literal queue and wrongly called it what a flow's own exhaustion returns. | 06 R8. Verifier finding: flows return no queue (`flows/card_block.py` 177–181, 220–224) and a queue in state overrides the YAML (`policy/escalation.py:213`). `policies/escalation.yaml` v6. D13 (policy files unchanged). |

## Contracts (delta only)

**Routing (`nodes/route.py`), LLM path only, after the escalation, abstain and injection checks that exist today:**

| Turn | Goes to | Reply |
|---|---|---|
| non-answer, flow question open, `non_answer_failures` becomes 1 | the paused flow's node, where the wrapper replays (D15) | the stored question again (below) |
| non-answer, flow question open, `non_answer_failures` reaches 2 | the paused flow's node, where the wrapper sets the reason, then `handoff_summary → handoff` | `handoff_transfer` |
| `intents == []`, no flow question open | `smalltalk` | `clarify_rephrase` |

**Re-ask per pause (D3).** `pending`, `confirmation_token_id` and `open_question` are byte-for-byte unchanged after the turn. Text and UI are the stored ones: the sentence the asking turn sent and the asking node's own events.

| `awaiting_slot` | Text (the stored sentence) | UI (the stored events) |
|---|---|---|
| `card_hint` | the flow's `ask_which_card_<action>` | the same `card_picker` event |
| `block_kind` | `clarify_lock_vs_block` | the same `quick_replies` event, `slot="block_kind"` |
| `confirmation` | the plan's confirm question | the same `confirm` event: **same** `token_id` and steps (no `issue_plan` call) |
| `otp` | `otp_required` | the same `otp_required` event |
| `transactions` | the flow's list prompt | the same `transaction_list` event |
| yes/no pauses (D1) | the flow's question for that pause | whatever that question carried |

**Graph state** (`TurnState`, checkpointed). Two new fields, no other:
```python
non_answer_failures: NotRequired[int]             # non-answers in a row on the open flow question (D4); absent = 0
open_question: NotRequired[OpenQuestion | None]   # the open flow question as it was asked (D15); absent or None = none stored

class OpenQuestion(TypedDict):
    text: str           # the question segment, exactly as the asking turn put it in the reply
    ui: list[Any]       # the asking node's own UI events (`UIEvent`s), unchanged; [] if that node wrote none
```

`non_answer_failures`:
- +1 on a non-answer turn on a flow question (D1), LLM path only.
- Hands off when the new value is 2; that turn leaves it at 0.
- Set to 0 by every other turn (D4): `finish` does it on every turn where `non_answer_counted` is not set (D18). Also set to 0 wherever `clarification_failures` is cleared outside a flow (`enqueue`, `smalltalk._close`, `takeover.return_to_bot`).

`open_question`:
- **Written** by `finish` only, on a turn in which a node's update wrote a flow-question `pending` and the turn ends with that pause open: `text` = the last entry of the turn's `segments`, `ui` = the asking node's own events, that is `update.get("ui", [])` of the flow node's update that wrote that `pending`, not the turn's `ui` list (which has no reducer, so on a multi-intent turn it can still hold an earlier intent's events). This covers a turn that opens a pause, moves to another pause, or asks the next question on the same pause.
- **Kept unchanged** on a turn that ends with the same flow question open and in which no node wrote `pending`: a replay turn, an abstain, a `pending_reminder` or `otp_required` reminder (D10), a degraded `clarify_rephrase`, a refused tool call.
- **Cleared** (`None`) by `finish` on every turn, in bot or human mode, that ends with no flow question open (`pending` is `None` or the `anything_else` pause): the question was answered and the flow finished, was cancelled, was dropped by P1, or the turn handed off. `takeover.return_to_bot` clears it too, because it clears `pending` outside a turn.
- So after any turn `open_question` is set only if a flow question is open. Every graph path ends in `finish` (`graph.py` 811–836), which is why both rules live there.
- **Read** only by the wrapper and by `finish`. No prompt builder (`understand`, `summarize`, `compose`, `handoff_summary`), no tool and no handoff packet reads it.

**Per-turn channels** (`graph.py` `GraphState`, not `TurnState`; both reset by `load_session` at the start of every turn; D18):
```python
asked_ui: NotRequired[list[UIEvent] | None]   # the asking node's own UI events; None = no flow node wrote a flow-question pending this turn
non_answer_counted: NotRequired[bool]         # set when this turn already counted a non-answer
```
Mechanism: the `graph.py` wrapper on the eight flow nodes sees each node's update. When an update writes a flow-question `pending`, the wrapper keeps `update.get("ui", [])` in `asked_ui`, and `finish` stores that value in `open_question.ui`; `asked_ui` not being `None` is also how `finish` knows a node asked this turn. The wrapper sets `non_answer_counted` when it counts a non-answer, so one turn increments `non_answer_failures` at most once, and `finish` sets the count to 0 on every turn where it is not set. Neither channel is a `TurnState` field and neither carries anything across turns. `OpenQuestion` is declared in `state.py` beside `Pending`; `ui.py` imports `Fact` from `state.py`, so `UIEvent` cannot be named there and `ui` is typed `list[Any]` with a comment that its items are `UIEvent`s (settled by the planner; `get_type_hints(GraphState)` and `test_checkpoint_serde.py` are unaffected). Verified by the planner at all 23 pause-opening sites: the question is a segment of its own and the last entry of the turn's `segments`; every node that asks writes `pending` in its update, also when the pause is unchanged; no digression node (`abstain`, `unsupported`, `smalltalk`, the `_guard_access` refusal) writes it. `clarification_failures` is unchanged.

**Non-answer wrapper (`graph.py`)**, on the eight nodes of `_FLOW_NODES`, placed so that `_track_segments` sees its update. It acts as a non-answer handler only when all of these hold; otherwise it calls the node as today and, when the node's update writes a flow-question `pending`, keeps that update's `ui` in `asked_ui`:
`nlu` is not `None` · `degraded` is false · `nlu.intents == []` · `pending` is a flow question of this node · `route._answer_fits(nlu, pending)` is false.

| New `non_answer_failures` | The wrapper returns | It never does |
|---|---|---|
| 1, `open_question` set | `{non_answer_failures: 1, non_answer_counted: True, segments: [open_question.text], ui: open_question.ui}`, and records the sentence (D16) | call the flow node, a read or write tool, the confirmation store or the LLM; write `pending`, `confirmation_token_id` or `open_question` |
| 1, no `open_question` | `{non_answer_failures: 1, non_answer_counted: True}` (D17) | the same |
| 2 | after `bank_write_tools.cancel_plan(confirmation_token_id)` when a token is set (D5): `actions.handoff(rule_queue(get_policies().escalation, "clarification_exhausted"), "clarification_exhausted", language)` plus `non_answer_failures: 0`. So the update carries the reason, `handoff_queue`, `pending: None` and `confirmation_token_id: None`. The queue is the one `policies/escalation.yaml` gives for that reason (today `atencion`), resolved at call time with `policy.escalation.rule_queue`, the idiom the other `handoff()` callers use (D19) | replay; call the flow node; issue a plan; write a literal queue |

**Safety of `open_question`:**
- **06 R2.** The replayed `confirm` event is the stored one, so it carries the `token_id` and steps of the plan issued on the asking turn; the wrapper never calls `issue_plan` or `consume_step`. A card shown again for a plan that was cancelled, consumed or expired cannot run anything: `POST /conversations/{id}/confirmations/{token_id}` starts a turn only when `is_open(token_id)` and the token equals the checkpointed `confirmation_token_id` (else `409 confirmation_invalid`), a typed "sí" uses the checkpointed token and never the event's, and `consume_step` rejects unknown, expired, mismatched and wrong-owner tokens (`04` §7).
- **06 R5 (PII).** The field holds one reply segment in the same masked form as `segments` and `history`, and UI events that the `ui` channel already puts in the checkpoint. It is never part of a prompt and is never sent to the LLM provider or to Langfuse. The replayed sentence enters `history` the way the first one did. No new class of PII is stored (the address question carries `•••, <city>`, not the address; only greeting templates carry `{customer_name}`).
- **06 R1.** The checkpoint is keyed by conversation and `customer_id` is bind-once, so a stored picker or list can only show the session customer's own cards and transactions.
- **Checkpoint serde.** A `TypedDict` is a plain dict to msgpack and every `UIEvent` member is already in `hosting.CHECKPOINT_TYPES`, so the allowlist and `test_checkpoint_serde.py` need no change. No migration and no frontend client regeneration.

**`finish` (`nodes/next_intent.py`):** `reply == ""` and `mode != "human"` → `reply = get_template("fallback", language)`.

**Docs to update in the same PR (06 §7.4):**
- `04-contracts.md` §6, after the `awaiting_slot` bullet (line 304): one line stating D11.
- `04-contracts.md` §6, the `fact_values` sentence (line 293): add that on a replayed question the stored sentence is recorded as one value (D16).
- `02-conversation-design.md` §3, after the P1 paragraph (line 61): one paragraph for D1, D2, D7 and D8.
- `02-conversation-design.md` §5, after the rules table: one sentence stating that a message with no intent that doesn't answer the open flow question is re-asked once and hands off with `clarification_exhausted` on the second in a row, counted in `non_answer_failures` and not in `clarification_failures`. Lines 133–134 are unchanged.
- `02-conversation-design.md` §3, the state list (line 55): add `non_answer_failures` and `open_question` (text and UI events of the open flow question, written and cleared by `finish`).

## Touch map

- `backend/app/domains/conversation/nodes/route.py`: the non-answer rule (send it to the paused flow's node; D7 to `smalltalk`).
- `backend/app/domains/conversation/graph.py`: the wrapper on the eight flow nodes (D15), which handles a non-answer and keeps the asking node's `ui`, and the two per-turn channels on `GraphState` (`asked_ui`, `non_answer_counted`). No new node, no new edge.
- `backend/app/domains/conversation/nodes/next_intent.py`: `finish` writes and clears `open_question` and holds the backstop (D8); `enqueue` resets `non_answer_failures`.
- `backend/app/domains/conversation/nodes/smalltalk.py`: `clarify_rephrase` for D7; `_close` resets `non_answer_failures`.
- `backend/app/domains/conversation/state.py`: `non_answer_failures` and `open_question`.
- `backend/app/domains/conversation/takeover.py`: `return_to_bot` resets both fields.
- `backend/app/domains/conversation/nodes/load_session.py`: resets the two per-turn channels.
- `backend/tests/unit/test_non_answer.py` (new).
- `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/04-contracts.md`.

Not touched: every module under `flows/`, `runner.py`, `ui.py`, `hosting.py`, `fact_values.py`, `policies/`, `prompts/`, `schemas.py`, `templates.py`, `classifier/`, `baseline/`, `eval/`, `frontend/`, migrations.

## Test list

All in `backend/tests/unit/test_non_answer.py`, `ScriptedLLM` with fixed NLU output, customer `CLI-TFMULTI00001` unless noted.

1. `test_non_answer_keeps_card_question_es` (Done-when 1, ES; D4, D7). Turn 0, "mmm" with `intents=[]` and nothing open: reply is `clarify_rephrase`, `non_answer_failures` stays 0. Then "quiero bloquear" → "¿Cuál tarjeta quieres bloquear?". Then "Todas" (`intents=[]`, no slot): the reply equals the asking turn's reply, `pending == "card_block.card_hint"`, the replay's `ui` equals the asking node's events (here its one `card_picker` event), and no card read tool is called on this turn (the replay reads nothing). Then "Todas" again: the turn hands off with reason `clarification_exhausted` and `open_question` is `None` (clear rule).
2. `test_non_answer_keeps_card_question_pt` (Done-when 1, PT). "quero bloquear meu cartão" → "Qual cartão você quer bloquear?"; "Todos" → the same question, `pending` and `open_question` unchanged; then a `card_hint=credit` answer moves the flow on, which proves the question survived, and `open_question.text` is now the next question's sentence (write rule).
3. `test_finish_never_sends_empty_reply` (Done-when 2; 06 R11). `finish` with `segments=[]` in bot mode returns the `fallback` template in ES and in PT; with `mode="human"` it returns `""`.
4. `test_r2_non_answer_on_confirmation_never_writes` (06 R2; D2, D4, D5), customer `CLI-TFSINGLE0002`. An ambiguous block request (`clarification="lock_vs_block"`) opens the `block_kind` pause, where `clarification_failures` is already 1. A non-answer there re-asks `clarify_lock_vs_block` with its `quick_replies` (no handoff). A `block_kind=temporary_lock` answer opens the `confirmation` pause. First non-answer on it: the confirm question and a `confirm` event equal to the one issued (same `token_id` and steps), `issue_plan` not called a second time, no write tool called, card still Active (the count restarted at 0). Second non-answer: handoff, `cancel_plan` called for that token, no write tool called, card still Active.

Still four tests. `open_question` adds assertions to tests 1, 2 and 4 and no new test: R2 is proven by test 4; R1 (the stored picker was built by session-bound tools in the same bind-once conversation), R3 (no "done" is said), R4/R5 (no LLM call, no new value, the field is in no prompt) and R6 (no LLM node gains a tool) are covered by their existing tests; `test_checkpoint_serde.py` proves the checkpoint still round-trips.

## Boundaries

- **Always:** run only `tests/unit/test_non_answer.py` per task and the full suite once per card; keep the re-ask free of LLM calls and tool calls; update `02` and `04` in the same PR.
- **Ask first:** adding a `TurnState` field other than `non_answer_failures` and `open_question`, or a key to `OpenQuestion` other than `text` and `ui`; changing any file under `flows/` (the capture rule holds at all 23 pause-opening sites, see Contracts; no flow change is approved); changing how `clarification_failures` is incremented or reset; changing any template text; changing a dev eval scenario; any frontend change.
- **Never:** cancel or issue a plan on a first non-answer; route a non-answer into a flow's resume code where a non-"sí" means decline or cancel; repeat `action_done*` text in a re-ask; read `open_question` from a prompt builder or send it to the LLM provider or Langfuse; change the degraded path, `nlu@v7`, `policies/` or `eval/scenarios/heldout/`; fire the backstop in human mode.

## Success criteria

1. `cd backend && uv run pytest tests/unit/test_non_answer.py -q` reports 4 passed.
2. In test 1 and test 2 the reply to "Todas"/"Todos" equals the asking turn's reply and `debug.pending` is `card_block.card_hint` before and after the turn.
3. In test 3 `finish` returns `get_template("fallback", language)` for an empty bot turn and `""` in human mode.
4. In test 4 no write tool appears in `debug.tools_called` on either non-answer, and the token cannot be used after the handoff.
5. `make check` is green, including `tests/unit/test_degraded.py` unchanged.
6. `git diff --stat develop` shows no file under `policies/`, `backend/app/domains/conversation/prompts/`, `backend/app/domains/conversation/flows/`, `eval/` or `frontend/`, and neither `runner.py` nor `hosting.py`.
7. `02` §3 and §5 and `04` §6 carry the lines named in Contracts.
8. `cd backend && uv run pytest tests/unit/test_checkpoint_serde.py -q` passes with that test file and `hosting.CHECKPOINT_TYPES` unchanged.
9. Reading `graph.py`: the wrapper's replay branch calls `fact_values.record` with the stored sentence and calls no tool, no store and no LLM (D15, D16).

## Open questions

No question is open. Every question raised during the card is answered:

1. **D16, `fact_values` on a replay.** Answered: shown to the human, not vetoed (D16).
2. **Capture rule (question is its own, last segment).** Answered: verified by the planner at all 23 pause-opening sites (Contracts, per-turn channels).
3. **Does the turn's `ui` hold only the asking node's events?** Answered: no, on a multi-intent turn. The human decided that `open_question.ui` holds the asking node's own events (D3, D18).
4. **Does every asking node write `pending`, and no digression node?** Answered: verified by the planner at all 23 sites.
5. **Where `OpenQuestion` is declared.** Answered: `state.py` beside `Pending`, `ui` typed `list[Any]` (Contracts).

Two statements of fact stay. They are not questions and nobody has to decide them; they were not checked in this card:

6. **Frontend (not verified).** A second `confirm` event with the same `token_id`, or a second picker, is expected to render as a new card with no frontend change. Nobody has checked it in the UI.
7. **Eval (not run).** `eval/harness/checks.outcome` reads a turn that ends on `.card_hint` or `.block_kind` as "clarified", so re-ask turns change what dev scenarios with a no-intent turn report. No suite is run in this card.
