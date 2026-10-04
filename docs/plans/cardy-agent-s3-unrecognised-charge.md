# Plan: REQ-cardy-agent-s3 — S3 · Unrecognised charge

Spec: [`docs/specs/cardy-agent-s3-unrecognised-charge.md`](../specs/cardy-agent-s3-unrecognised-charge.md) · Branch: `feat/cardy-agent-s3-unrecognised-charge` (off `origin/develop` @ 40cb806)

The spec is approved as written, including the derived readings D8, D9, D10, D15 and the kept S1 D17. "Dn" below is a decision of that spec; "the flow" is `backend/app/domains/conversation/flows/unrecognized_charge.py`. This plan adds no decision. Where it fixes a name or a data shape, it is only so that tasks built at the same time agree with each other.

## Facts checked against the repo

**Environment**

- This worktree's `.env` has `AGENT_ENABLED=true` (line 90). Without a prefix, `test_dispute_flows.py`, `test_selection_gate.py` and `test_graph.py` fail with "ScriptedLLM: no scripted output left for step 'agent'". With `AGENT_ENABLED=false` on the command line the same files pass (28 passed, checked). **Every Verify sets `AGENT_ENABLED=false` on the command line.** Agent tests turn the flag on themselves with the `agent_on` fixture.
- The full check at the end of the card is `make check AGENT_ENABLED=false` (the make-variable form; the env-prefix form is overridden by `.env`).
- If the sandbox refuses a long `&&` chain, run each part of a Verify as its own command. All parts must pass.
- The dev stack mounts this worktree's `backend/app` and `policies/` and hot-reloads. Nothing in this card needs a restart, a dependency, a migration, `make data` or `make client`.
- Tasks of one wave share the checkout. A red run caused by a sibling's half-saved file is re-run once before it is treated as the task's own failure.
- Baseline, green today with the prefix: `test_agent_plan_check.py`, `test_agent_confirmation.py`, `test_agent_reply_check.py`, `test_agent_happy.py`, `test_agent_fallbacks.py`, `test_agent_step_up.py`, `test_agent_unlock_replace.py`, `test_r6_no_write_tools_in_llm_nodes.py`, `test_policy_registry.py`, `test_dispute_flows.py`, `test_selection_gate.py`, `test_graph.py`.

**What exists on the branch**

- `policies/tools.yaml` is `version: 4`. `disputes.create_claim` has no `preconditions` block. `cards.block_card` has `preconditions: {status_not_in: [Blocked, Closed]}`.
- `Preconditions` (`backend/app/domains/policy/tools_policy.py`) is frozen with `extra="forbid"`: a YAML key with no field fails at load.
- `policies/disputes.yaml` (not touched): `candidate_statuses`, `compromise: {min_picked, fraud_score_gt, block_reason}`, `possession_question`, `questions`, `handoff`, `priority.handoff`. Read through `load_disputes_policy()` (`app.domains.policy.disputes`), with `DisputesPolicy.triggers_compromise(picked_count, max_fraud_score)`.
- `policies/playbooks.yaml` is `version: 1` and has no `unrecognized_charge` entry. Entries are `>-` folded Spanish text keyed by intent.
- `backend/app/domains/conversation/prompts/agent@v2.md` exists; `agent@v3.md` does not. `load_prompt` reads the file by name; there is no manifest. `agent/node.py` has `_PROMPT = PromptRef("agent", 2)`.
- `agent/plan.py`: `_TOOL_BY_ACTION`, `_SUMMARY_BY_ACTION`, `_INTENT_BY_ACTION`, `ProposedStep`, `ProposeArgs`, `PlanBox` (`set`, `pause`, `update`, `clear`), `PlanHandoff`, `plan_segments`, `plan_labels`, `check_steps`, `cancel_open_plan`, `issue_stored_plan`, `propose_plan`, `_rejected`. It imports no LLM module.
- `agent/confirm.py`: `agent_plan`, `_decline`, `_accept`, `_CLEARED`, `count_open_plan_turn`, `replay_open_plan`, `_result_step`.
- `agent/reads.py`: `read_tools(state, config, refs)`. The row facts of a transaction list (`merchant`, `amount`, `currency`, `tx_date`, `card_mask`, source `bank.transactions:<tx_id>`) are built inside the closure `_list_rows`; nothing is exported for them. Side effects go through `refs.graph_update`.
- `agent/node.py`: `agent_tools`, `_header`, `_pick_event` (reads `state["tx_offer"]`), `_plan_event`, `agent`. `refs.graph_update` is merged into the node's update unless the turn is an `issued` one; then `box.update()` is merged on top when a plan or pause was opened. `update["tx_offer"] = None` is set in one place: the final `else` branch of `agent()`.
- `AgentTurn` (`agent/schema.py`) requires `awaiting_slot` exactly when `outcome == "asked"`.
- `state.py`: `AgentPlanStep.action` is `Literal["lock", "block", "unlock", "replace"]`; `DisputeState` has `card_id`, `offered_tx_ids`, `fraud_scores`, `picked_tx_ids`, `answers`, `question_index`, `compromise`, `block_refused`.
- `nodes/compose.py` `_format_fact` returns `str(value)` for a fixed key tuple that ends with `"tracking_id"`; any other key raises `ValueError`.
- `runner.checkpointed_offer` returns `tx_offer` with `multi=False` for `pending["flow"] in {"tx_search", "tx_explain", "agent"}`, else `dispute` with `multi=True`.
- `graph.py` needs no change (checked): `_routes_to_agent` sends a `selection` at any agent `transactions` pause to `agent`; `_agent_plan_click` sends a click at the agent `confirmation` pause to `agent_plan`; `_after_agent_plan` goes to `handoff_summary` when `escalation_reason` or `handoff_queue` is set, to `agent` when `agent_code_text` is set, else to `finish`.
- `nodes/handoff.py` needs no change (checked): the packet comes from the state keys D17 lists. On the Acepto turn both paths have `nlu = None` and `pending = None`, so `routing` is the same.
- `ActionResult.case_ids: list[str] | None` is set only by `create_claim`. The flow joins them with `", "` (`_claim_reply_text`).
- `PlanStep.tool` is a plain `str`. `cards.get_block_origin` has no `preconditions` block.
- Flow helpers to import, never copy or edit (D1): `_tx_option` (line 205), `_priority_flags` (687), `_fraud_handoff` (670), `_handoff_no_claim` (650), `_flag_lines` (713), `_claim_reply_text` (722), `_evidence` (735). Analogues to read: `_offer_candidates` (149), `_resume_pick` (216), `_start_compromise_plan` (346), `_start_claim_plan` (400), `_offer_claim_only` (438), `_resume_cancel` (504), `_confirm_compromise_plan` to `_single_charge_success` (527–647).
- Test fixtures (`backend/tests/unit/test_dispute_flows.py`): customer `CLI-TFSINGLE0002`, card `PRD-TFS2CRED0001`, `TRX-TFS2CRED0001TXN01` and `TXN02` (low score), `TXN03` (Pending, fraud score 45.00). The single-charge flow test ends with no handoff, so that customer has no priority flag. Packets are read from `session.handoff_tools.created`. `test_selection_gate.py` shows how to call `post_message` with a stub host and a recording `start_turn`.
- Test harness (`backend/tests/conftest.py`): `ScriptedLLM`, `AgentScript(rounds, finals)`, `make_session`, `agent_on`, `run_recorded_turn`, `RecordingAudit`. Tests use `asyncio.run`.
- `runner.py` records `reply_sent.route = "card_block"` for a turn where `agent_plan` ran and no node carried labels (lines 524–529). See Risks.

**Interfaces fixed by this plan** (so that T5, T7 and T8 can be built apart)

- I1. `agent/reads.py` exports `register_tx_rows(rows, refs, bank_tools, language) -> list[str]` (async): it registers each row as a `t` reference with the same facts `_list_rows` registers today and returns the handles.
- I2. The dispute pause is `{"flow": "agent", "node": "dispute_pick", "awaiting_slot": "transactions"}`.
- I3. **The dispute in effect during a turn** is `refs.graph_update["dispute"]` when that key is present (a `dispute_candidates` call this turn), else `state.get("dispute")`. On a pick turn the node hands the tools a state copy whose `dispute` already holds the picks.
- I4. `agent/dispute.py` exports `check_claim`, `build_claim_plan`, `accept_claim_plan`, `decline_claim_plan`. It never imports `app.core.llm`, and it does not import `agent/plan.py` at module level (`plan.py` imports it).
- I5. An accepted claim proposal writes the updated `dispute` (answers, `compromise`) and `priority_flags` through `box.update()`, which the node already merges.
- I6. `agent_plan_result` after a verified single-charge claim: `{"outcome": "confirmed", "steps": [{"action": "claim", "card_id": <dispute card id>, "case_id": <case ids joined with ", ">}]}`, with `agent_code_text` set. After a declined single-charge plan: `{"outcome": "declined", "steps": []}`, as today.
- I7. A plan that holds a `claim` step is one `unrecognized_charge` segment (intent and route), whatever other step it has.

## Components

| Component | Where | Depends on |
|---|---|---|
| Policy v5 | `policies/tools.yaml`, `backend/app/domains/policy/tools_policy.py` | nothing |
| Contracts | `conversation/state.py`, `agent/schema.py`, `nodes/compose.py` | nothing |
| Prompt and playbook | `prompts/agent@v3.md` (new), `policies/playbooks.yaml` | nothing |
| Docs | `decision-log.md`, `02`, `04` | nothing |
| Candidates read tool | `agent/reads.py` (`dispute_candidates`, `register_tx_rows`) | flow `_tx_option`, `DisputesPolicy` |
| Selection gate branch | `conversation/runner.py` (`checkpointed_offer`) | I2 |
| Claim module | `agent/dispute.py` (new): check, plan build, Acepto and No acepto outcomes | policy v5, contracts, flow helpers |
| Plan and button wiring | `agent/plan.py`, `agent/confirm.py` | claim module |
| Agent node | `agent/node.py`: prompt v3, tool description, pick event, header references, `dispute` lifetime, claim result event | I1, I3, I6, prompt v3 |
| Tests | `backend/tests/unit/test_agent_dispute.py` (new) | all of the above |

## Build order

1. **W1, six tasks at once.** Policy, contracts, prompt, docs, the read tool and the gate branch touch separate files and depend on nothing. Policy must land before the claim module, because `issue_plan(steps, None)` refuses `create_claim` until it has a `preconditions` block. The one existing test this breaks is in the policy task.
2. **W2, two tasks at once.** The claim module with its wiring, and the agent node. They meet only through I3, I5, I6 and I7, so neither waits for the other.
3. **W3, the never-cut tests.** They run whole conversations, so they need every piece. This task may repair a defect a test exposes in the agent files, because two halves built against a written interface are where defects show.
4. **W4, the refused-block branch and its test.** It is last because it is the first thing the spec allows to be cut. Until it runs, No acepto on the two-step plan already behaves as Cut 1 describes.

## Touch map

| File | New or modified | What changes |
|---|---|---|
| `policies/tools.yaml` | modified | `version: 5`; `preconditions` on `disputes.create_claim` |
| `backend/app/domains/policy/tools_policy.py` | modified | `Preconditions.tx_owned`, `.answers_complete` |
| `backend/tests/unit/test_agent_plan_check.py` | modified | one stand-in tool in `test_precondition_rejects_blocked_card` |
| `backend/app/domains/conversation/state.py` | modified | `AgentPlanStep.action` gains `"claim"` |
| `backend/app/domains/conversation/agent/schema.py` | modified | `awaiting_slot` gains `"dispute_question"` |
| `backend/app/domains/conversation/nodes/compose.py` | modified | `case_id` formatted as a plain string |
| `backend/app/domains/conversation/prompts/agent@v3.md` | new | the claim step, its codes, `dispute_candidates`; the unrecognised charge leaves the pass list |
| `policies/playbooks.yaml` | modified | `unrecognized_charge` entry |
| `docs/solution-docs/decision-log.md`, `02-conversation-design.md`, `04-contracts.md` | modified | D22 lines |
| `backend/app/domains/conversation/agent/reads.py` | modified | `dispute_candidates`, `register_tx_rows` |
| `backend/app/domains/conversation/runner.py` | modified | `checkpointed_offer` branch for the dispute pause |
| `backend/app/domains/conversation/agent/dispute.py` | new | claim check, plan build, outcomes |
| `backend/app/domains/conversation/agent/plan.py` | modified | `ProposedStep`, claim branch, action maps, one-segment rule |
| `backend/app/domains/conversation/agent/confirm.py` | modified | `agent_plan` sends a claim plan to `dispute.py` |
| `backend/app/domains/conversation/agent/node.py` | modified | prompt v3, tool description, pick event, header, `dispute` lifetime, claim event |
| `backend/tests/unit/test_agent_dispute.py` | new | the six tests |

Not touched, as the spec says: `flows/`, `graph.py`, `nodes/handoff.py`, `nodes/handoff_summary.py`, `tools/executor.py`, `api/v1/conversations.py`, `agent/refs.py`, `policies/disputes.yaml`, `policies/escalation.yaml`, `templates.py`, the frontend, `eval/`. A task that finds it needs one of these stops and reports; it is a spec question.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `tools.yaml` v5 breaks `test_agent_plan_check.py::test_precondition_rejects_blocked_card`, which uses `disputes.create_claim` as the tool with no `preconditions`. | T1 owns that file and swaps the stand-in to `cards.get_block_origin` (success criterion 1). |
| A YAML key lands before its `Preconditions` field and the policy fails to load. | T1 edits both files; its Verify loads the registry. |
| The pick is not visible to `propose_plan` in the turn it is made, because tools close over the state as it was at the start of the turn. | I3: T8 builds the tools from a state copy that holds the picks; T7 reads the dispute through I3. Test 4 and test 5 propose in the pick turn. |
| `plan.py` and `dispute.py` import each other. | I4: `dispute.py` returns plain data and builds its own segment; `plan.py` does `box.set`. |
| The model shrinks the claim, or names a raw id. | T7: unknown handles are never looked up; resolved ids must equal the picked set; the claim, the count and the evidence read `dispute.picked_tx_ids`, never the proposal. Test 1. |
| A threshold, question id, queue or block reason is written in Python or the prompt (R8). | T7 and T8 read them from `load_disputes_policy()`; T3's Verify greps the prompt for the banned words of success criterion 5. |
| An LLM module names a write tool (R6). | `dispute.py` imports no LLM module; `node.py` and `reads.py` reach writes only through `propose_plan`. T5, T7 and T8 run the R6 scan. |
| Cardy writes on a handoff turn. | T7: outcomes (a) to (d) and the no-claim handoffs set the handoff keys and no `agent_code_text`, so `_after_agent_plan` goes to `handoff_summary`. Test 5 asserts no LLM call wrote the result. |
| The packet differs from the flow's. | T5 sets `selected_card_id`; T7 writes `priority_flags` at plan build and uses `_fraud_handoff` and `_evidence`. Test 6 compares both paths. |
| T7 and T8 are built apart and disagree. | I1 to I7 are in the state file; T9 runs both halves end to end and may repair the agent files. |
| Flag-off behaviour changes. | T1, T6 and T9 run `test_dispute_flows.py` and `test_selection_gate.py` with the flag off. T10 runs the `git diff --stat` of success criterion 1. |
| The turn that re-issues the claim-only plan (D15), and a stale click on a claim plan, are recorded with `reply_sent.route = "card_block"` by `runner.py`. The spec limits `runner.py` to `checkpointed_offer`. | Built as the spec says, route label left as it is. Reported to the human as a non-blocking question. `intent_segments` and `path: "agent"` are right (D18). |
| 18:00 freeze. | The cut line below. T10 is the only task that Cut 1 changes. |

## Tests

The spec's list, nothing added. All in `backend/tests/unit/test_agent_dispute.py`, with `ScriptedLLM`.

| # | Test | Task |
|---|---|---|
| 1 | `test_r1_foreign_or_unpicked_charge_refused` | T9 |
| 2 | `test_r8_claim_gated_by_policy_preconditions` | T9 |
| 3 | `test_r2_refused_block_reissues_claim_only` | T10 |
| 4 | `test_single_charge_claim[es, pt]` | T9 |
| 5 | `test_compromise_block_and_claim[es, pt]` | T9 |
| 6 | `test_handoff_packet_same_as_flow` | T9 |
| edit | `test_agent_plan_check.py::test_precondition_rejects_blocked_card` (stand-in only) | T1 |

No test for the prompt, the playbook, the schema fields, the `case_id` formatter, the gate branch on its own or the docs: their proof is a command in the task's Verify.

## Verification map

| Success criterion | Proved by |
|---|---|
| 1 Flag off unchanged | T1, T6, T9 Verify (flag-off files); T10 Verify (`git diff --stat`); verifier: `make check AGENT_ENABLED=false` |
| 2 Refusals | T9 (`-k "r1 or r8"`), T10 (`-k r2`) |
| 3 ES and PT | T9 (`-k "single_charge or compromise"`, 4 passed) |
| 4 Packet | T9 (`-k packet`) |
| 5 Policy and prompt | T1, T3, T8 Verify greps |
| 6 Browser | Outside the task list: verifier or human, `/home` in ES and PT. The flag is already on in this worktree's `.env`. Step (c) is skipped under Cut 1. |
| 7 Docs | T4 Verify greps |

## Cut line

Crossing a cut is the human's decision (spec "Ask first"). The orchestrator writes `Cut 1 taken` or `Cut 2 taken` in the state file; the task blocks below say what changes.

- **Never cut:** T1 to T9. They hold tests 1 and 2 (R1 and R8 refusals), tests 4 and 5 (ES and PT happy paths) and test 6 (packet parity).
- **Cut 1 (first): the refused-block branch.** T10 does not build the branch. T7 already leaves No acepto on the two-step plan as an immediate Fraudes handoff with no claim and the open question `dispute_open_question_card_active`. T10 then only writes the reduced test 3 and corrects the D15 sentence in the docs. Decide it when W3 ends.
- **Cut 2 (second): the multi-pick list.** T6 is dropped. T5 emits `multi: false` and also writes `tx_offer` the way `_list_rows` does, so the unchanged gate accepts one pick. T8 builds the pick event for one id. T9's test 5 ES reaches compromise through a "no" to possession. T4 words the list as single-pick. It saves little once W1 has run, so decide it before W1 is dispatched or not at all.

## Tasks

- [ ] T1: Policy: `tools.yaml` v5, the two `Preconditions` fields, the test stand-in
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "`policies/tools.yaml` → version 5"; `backend/app/domains/policy/tools_policy.py`; `backend/tests/unit/test_agent_plan_check.py` lines 49–83
  - Acceptance:
    - `policies/tools.yaml` is `version: 5`. The `disputes.create_claim` entry is exactly the spec's line: it keeps `requires_confirmation`, `step_up: never` and `allowed_intents: [unrecognized_charge]` and gains `preconditions: {tx_owned: true, answers_complete: true}`. The header comment names v5. No other entry changes.
    - `Preconditions` gains `tx_owned: bool | None = None` and `answers_complete: bool | None = None`. Nothing else in the module changes.
    - In `test_precondition_rejects_blocked_card`, the `PlanStep` that must raise `PolicyDenied` under `issue_plan(..., None)` uses `cards.get_block_origin` (args `{"card_id": card_id}`), a tool with no `preconditions` block. Still `pytest.raises(PolicyDenied)`. No other test line changes.
    - Write the new version and the field names in the state file.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_plan_check.py tests/unit/test_policy_registry.py tests/unit/test_dispute_flows.py -q && uv run ruff check app/domains/policy/tools_policy.py tests/unit/test_agent_plan_check.py && uv run ruff format --check app/domains/policy/tools_policy.py tests/unit/test_agent_plan_check.py && uv run mypy app/domains/policy/tools_policy.py --follow-imports=silent && grep -n 'version: 5' ../policies/tools.yaml && grep -n 'disputes.create_claim.*preconditions: {tx_owned: true, answers_complete: true}' ../policies/tools.yaml`
  - Files: `policies/tools.yaml`, `backend/app/domains/policy/tools_policy.py`, `backend/tests/unit/test_agent_plan_check.py`

- [ ] T2: Contracts: `AgentPlanStep` claim action, `dispute_question` slot, `case_id` formatter
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "Graph state" and "Turn events"; `backend/app/domains/conversation/agent/schema.py`; `backend/app/domains/conversation/nodes/compose.py` lines 342–400
  - Acceptance:
    - `state.py`: `AgentPlanStep.action` is `Literal["lock", "block", "unlock", "replace", "claim"]`. `DisputeState` is not changed.
    - `agent/schema.py`: `AgentTurn.awaiting_slot` is `Literal["card_hint", "block_kind", "criterion", "dispute_question"] | None`.
    - `nodes/compose.py`: `_format_fact` returns `str(value)` for the key `case_id`, in the same tuple as `tracking_id`, with a one-line comment (D14 e, R4: a server-issued reference shown as it is).
    - No test is added.
  - Verify: `cd backend && uv run python -c "from app.domains.conversation.agent.schema import AgentTurn; from app.domains.conversation.nodes.compose import format_fact; from app.domains.conversation.state import Fact; AgentTurn(language='es', intents=['unrecognized_charge'], outcome='asked', awaiting_slot='dispute_question', reported_done=[], reply='x'); f = Fact(key='case_id', value='REC-1', source='disputes.create_claim'); assert format_fact('case_id', {'case_id': f}, language='es', country='MX') == 'REC-1'; print('ok')" && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_reply_check.py -q && uv run ruff check app/domains/conversation/state.py app/domains/conversation/agent/schema.py app/domains/conversation/nodes/compose.py && uv run ruff format --check app/domains/conversation/state.py app/domains/conversation/agent/schema.py app/domains/conversation/nodes/compose.py && uv run mypy app/domains/conversation/agent/schema.py app/domains/conversation/nodes/compose.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/agent/schema.py`, `backend/app/domains/conversation/nodes/compose.py`

- [ ] T3: Prompt `agent@v3` and the `unrecognized_charge` playbook
  - Depends on: nothing
  - Read exactly these: spec D2, D6, D7 and §"Contracts" → "`propose_plan`", "Read tool", "Prompt and playbook", and §"Boundaries" → "Never"; `backend/app/domains/conversation/prompts/agent@v2.md`; `policies/playbooks.yaml`
  - Acceptance:
    - `agent@v3.md` is a copy of `agent@v2.md` (title `agent@v3`) with these changes only. `agent@v2.md` is not edited.
    - "un cargo que el cliente no reconoce" leaves the `pass_to_flow` list, and the closing paragraph that lists what is passed no longer excludes claims.
    - The tools section gains `dispute_candidates` (argument `card`, a card reference; the code shows the customer a list to pick from; result: the charges as `t` references, or that there are none).
    - `propose_plan` gains the action `claim`: `charges` (the `t` references the system event or the header gave this turn) and `answers` (question id → `yes` or `no`; the ids are listed in the tool's own description, not in this prompt). A `claim` step takes no `card` and stands alone in its plan.
    - Results explained: `accepted`; `accepted (block_added)` (the system added a block of the card to the plan: the sentence may say the plan also blocks the card, nothing more); `rejected (claim: <code>)` with `claim_alone`, `unknown_reference`, `not_picked` (the customer must pick on the list: call `dispute_candidates` again) and `missing_answer:<question id>` (ask that one question in your own words, `outcome: "asked"`, `awaiting_slot: "dispute_question"`, then propose again with the answers so far).
    - A section for the unrecognised charge: read the card, call `dispute_candidates`, ask the customer to pick on the list; typed text never picks a charge; after the pick event propose the claim with exactly the picked references; never name a transaction id, a block reason, a queue, a flag or a threshold; never promise a refund or an outcome; after Acepto, the case id is cited only as a `{reference}`.
    - "Cómo responder" lists `dispute_question` among the `awaiting_slot` values.
    - The file never contains (case-insensitive) `fraudes`, `suspected_fraud`, `priority_claim`, `min_picked`, `fraud_score`, `card_in_possession`, `contacted_merchant`. The `<<PLAYBOOKS>>` slot stays.
    - `policies/playbooks.yaml` gains `unrecognized_charge` in the file's style (Spanish, `>-`), with the five points of the spec's "Prompt and playbook" line. `version` stays 1. It holds no threshold, question id or queue.
  - Verify: `test -f backend/app/domains/conversation/prompts/agent@v3.md && grep -c '<<PLAYBOOKS>>' backend/app/domains/conversation/prompts/agent@v3.md && grep -n 'dispute_candidates' backend/app/domains/conversation/prompts/agent@v3.md && grep -n 'unrecognized_charge:' policies/playbooks.yaml && ! grep -n -i 'fraudes\|suspected_fraud\|priority_claim\|min_picked\|fraud_score\|card_in_possession\|contacted_merchant' backend/app/domains/conversation/prompts/agent@v3.md && git diff --stat -- 'backend/app/domains/conversation/prompts/agent@v2.md' && cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_policy_registry.py -q` (the `git diff --stat` prints nothing)
  - Files: `backend/app/domains/conversation/prompts/agent@v3.md`, `policies/playbooks.yaml`

- [ ] T4: Docs: ADR-035 S3 amendment, `02` §3 and §4.8, `04` §1, §3 and §5
  - Depends on: nothing
  - Read exactly these: spec D22, D3 to D15 and §"Contracts"; `docs/solution-docs/decision-log.md` lines 223–232 (ADR-035 and its S2 bullets); `docs/solution-docs/04-contracts.md` §1 "Agent tools" (lines 60–72), the `selection` row of §3 (line 110) and the `tools.yaml` block and version note of §5 (lines 221–232, 289)
  - Acceptance:
    - `decision-log.md`: one bullet under ADR-035, after the OTP-exit bullet, starting `**S3 amendment (spec \`docs/specs/cardy-agent-s3-unrecognised-charge.md\`).**`: the unrecognised charge becomes an agent claim plan; Cardy proposes only the claim and asks the questions; code checks the picked charges and the required answers, adds the block and the flags, and hands off with the flow's packet; button only.
    - `02` §3 "Agent node": the routing row for a pick covers the dispute list (pause `agent/dispute_pick`, multi-pick, turn event naming the picked references); a short paragraph says `dispute` is reused on the agent path and when it is cleared (D5), and that `dispute_question` is the slot of a turn where Cardy asks a dispute question; the prompt is `agent@v3`.
    - `02` §4.8: one agent-path note: with the flag on, steps 1 to 4 run as D3 to D15 describe (same rules and policy, Cardy asks the questions, code builds the plan), including No acepto (D15).
    - `04` §1: the agent tools table gains `dispute_candidates`; the `propose_plan` row and the paragraph under it gain the `claim` step (`charges`, `answers`), the results `accepted (block_added)` and `rejected (claim: <code>)`, the codes `claim_alone`, `not_picked`, `missing_answer:<question id>`, the check order, and `agent_plan_steps` with `action: "claim"` and `card_id` = the dispute's card.
    - `04` §3: the `selection` row says that at the agent dispute pause the offer is `dispute.offered_tx_ids`, multi-pick.
    - `04` §5: the YAML block shows `version: 5` and the new `disputes.create_claim` line; a "`tools.yaml` version 5" sentence explains `tx_owned` and `answers_complete`.
    - If the state file says `Cut 2 taken`, the list is described as single-pick and `04` §3 is not changed.
  - Verify: `grep -n 'S3 amendment' docs/solution-docs/decision-log.md && grep -n 'dispute_candidates' docs/solution-docs/04-contracts.md && grep -n 'version: 5' docs/solution-docs/04-contracts.md && grep -n 'tx_owned' docs/solution-docs/04-contracts.md && grep -n 'missing_answer' docs/solution-docs/04-contracts.md && grep -n 'dispute_pick' docs/solution-docs/02-conversation-design.md && grep -n 'agent@v3' docs/solution-docs/02-conversation-design.md`
  - Files: `docs/solution-docs/decision-log.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/04-contracts.md`

- [ ] T5: Read tool `dispute_candidates` and the shared row-facts helper
  - Depends on: nothing
  - Read exactly these: spec D3 and §"Contracts" → "Read tool"; `backend/app/domains/conversation/agent/reads.py` (whole file; `_list_rows` is the analogue); `backend/app/domains/conversation/flows/unrecognized_charge.py` lines 149–214 (`_offer_candidates`, `_tx_option`)
  - Acceptance:
    - A module-level `async def register_tx_rows(rows, refs, bank_tools, language) -> list[str]` registers each `TxView` as a `t` reference with exactly the facts `_list_rows` registers today (`merchant` with the language fallback, `amount`, `currency`, `tx_date`, and `card_mask` when the card's last4 is known; source `bank.transactions:<tx_id>`) and returns the handles in row order. `_list_rows` calls it and behaves as before. It is added to `__all__`.
    - A new tool `dispute_candidates`, argument `card: str` (a card reference of this turn). An unknown reference returns `_NO_CARD_REF` and reads nothing (R1).
    - It runs the flow's search: `TxFilter(card_id=<card>, status=<candidate_statuses of load_disputes_policy()>)`, as `_offer_candidates` does. No status or limit is written in Python.
    - No rows: it returns `no candidate transactions.` and writes nothing to `refs.graph_update`.
    - Rows: it registers them with `register_tx_rows`, returns the fenced references, and writes to `refs.graph_update`: `ui` (one `TransactionListEvent` with `multi=True` and options from the flow's `_tx_option`), `dispute` (a `DisputeState` shaped as `_offer_candidates` builds it: `card_id`, `offered_tx_ids`, `fraud_scores`, empty `picked_tx_ids` and `answers`, `question_index` 0, both flags `False`), `selected_card_id`, and `pending` = `{"flow": "agent", "node": "dispute_pick", "awaiting_slot": "transactions"}`.
    - `fraud_score` is never a fact and never in the returned text.
    - `search_transactions` keeps its single-pick list. The module still names no write tool.
    - If the state file says `Cut 2 taken`: the event has `multi=False` and the update also carries `tx_offer` = `{"flow": "agent", "offered_tx_ids": [...]}`.
    - Write the tool name, the helper's real signature and the keys written to `refs.graph_update` in the state file.
  - Verify: `cd backend && uv run python -c "from app.domains.conversation.agent.reads import read_tools, register_tx_rows; print('ok')" && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_happy.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/agent/reads.py && uv run ruff format --check app/domains/conversation/agent/reads.py && uv run mypy app/domains/conversation/agent/reads.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/reads.py`

- [ ] T6: Selection gate: `checkpointed_offer` reads the dispute list at the agent dispute pause
  - Depends on: nothing
  - Read exactly these: spec D4 and §"Contracts" → "Selection gate"; `backend/app/domains/conversation/runner.py` lines 249–279 (`checkpointed_offer`)
  - Acceptance:
    - When `pending["flow"] == "agent"` and `pending["node"] == "dispute_pick"`, `checkpointed_offer` returns `(pending, set(dispute["offered_tx_ids"]), True)` (an empty set when `dispute` is missing). The check sits before the `tx_offer` branch.
    - Every other agent pause keeps `tx_offer` with `multi=False`. The docstring says so. Nothing else in `runner.py` changes, and `api/v1/conversations.py` is not touched.
    - Dropped if the state file says `Cut 2 taken`.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_selection_gate.py -q && grep -n 'dispute_pick' app/domains/conversation/runner.py && uv run ruff check app/domains/conversation/runner.py && uv run ruff format --check app/domains/conversation/runner.py && uv run mypy app/domains/conversation/runner.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/runner.py`

- [ ] T7: Claim module and wiring: the check, the plan build, Acepto and No acepto
  - Depends on: T1 (`issue_plan(steps, None)` accepts `disputes.create_claim` only with its `preconditions` block), T2 (`AgentPlanStep` action `"claim"`)
  - Read exactly these: spec D6 to D18 and §"Contracts" → "`propose_plan`" and "Graph state"; `backend/app/domains/conversation/agent/plan.py` and `agent/confirm.py` (whole files); `backend/app/domains/conversation/flows/unrecognized_charge.py` lines 346–747 (the plan starters, `_resume_cancel`, the three success builders and the helpers to import)
  - Acceptance:
    - **Module rules.** New `agent/dispute.py` with `check_claim`, `build_claim_plan`, `accept_claim_plan`, `decline_claim_plan`. It imports no `app.core.llm` and does not import `agent/plan.py` at module level; it returns plain data and builds its own `unrecognized_charge` segment. `plan.py` and `confirm.py` import it. The flow's helpers (`_priority_flags`, `_evidence`, `_fraud_handoff`, `_handoff_no_claim`, `_flag_lines`, `_claim_reply_text`) are imported, never copied; nothing under `flows/` is edited.
    - **Proposal shape (`plan.py`).** `ProposedStep` is the spec's: action `claim` added, `card: str | None`, `charges: list[str] | None`, `answers: dict[str, Literal["yes", "no"]] | None`. The validator requires `card` for every action but `claim`, rejects `card` and `address` on `claim`, requires at least one charge on `claim`, and rejects `charges` and `answers` elsewhere. `_TOOL_BY_ACTION["claim"] = "disputes.create_claim"`, `_SUMMARY_BY_ACTION["claim"] = "create_claim"`.
    - **One segment.** `plan_segments` and `plan_labels` return exactly one `unrecognized_charge` segment or intent (route `unrecognized_charge`) for a step list that holds a `claim` step, including its block step. Other plans are unchanged.
    - **Check order.** `customer_not_active` handoff (the existing start of `check_steps`, now covering `claim`) → `claim_alone` on every step when a `claim` step comes with any other step → `unknown_reference` when a `charges` handle is not a transaction reference of this turn (`refs.tx_id` is `None`; never looked up) → `not_picked` when the resolved ids are not exactly the set `dispute.picked_tx_ids`, when that set is empty, or when there is no dispute → D9.
    - **The dispute read by the check** is `refs.graph_update["dispute"]` when that key is present, else `state.get("dispute")`.
    - **D9**, through `load_disputes_policy()` only: `triggers_compromise(len(picked), highest picked fraud score)` true → compromise, no answer read; else `possession_question` missing → `missing_answer:<id>`, "no" → compromise; "yes" → the first id of `questions` with no answer → `missing_answer:<id>`. The stored `dispute.answers` are only the answers the rule read, as `"<id>=<yes|no>"` strings. Other keys the model sent are ignored. No question id or threshold is written in Python.
    - **Result text.** `rejected (claim: <code>)`; in a mixed proposal each card step is labelled with its card handle and the claim step with `claim`, all `claim_alone`. A rejection issues no token and cancels nothing.
    - **Plan build (D10, D11, D13)**, after `cancel_open_plan`: `priority_flags` from `_priority_flags` over the full picked set; compromise and the card's status not in `cards.block_card` `preconditions.status_not_in` → two steps, `cards.block_card` with reason `compromise.block_reason` from the disputes policy and view fact `card_mask`, then `disputes.create_claim`; otherwise the claim alone. Claim args are the flow's: `tx_ids` (the picked ids from the dispute), `answers` (sorted), `priority_flags`; view fact `Fact(key="tx_count", value=<n>, source="conversation")`. One token from `issue_plan(steps, None)`, labels `accept_decline`. `PolicyDenied` → `rejected (claim: tool_not_allowed)`. `ToolUnavailable` propagates to the node.
    - **What is stored.** `agent_plan_steps` is `[{"action": "block", "card_id": <dispute card>}, {"action": "claim", "card_id": <dispute card>}]` or the claim step alone; no reason is stored. The box update also carries the updated `dispute` (`answers`, `compromise`) and `priority_flags` (for example through an optional `extra` on `PlanBox.set`). The result is `accepted (block_added)` when the block was added, else `accepted`. It never carries a score, a flag, the reason or the token.
    - **Other plans.** `issue_stored_plan` keeps `lost_or_stolen` for every plan without a `claim` step.
    - **Button (`confirm.py`).** `agent_plan` sends a stored plan that holds a `claim` step to `accept_claim_plan` on Acepto and to `decline_claim_plan` on No acepto. A stale click is unchanged. `count_open_plan_turn`'s handoff also clears `dispute` when the open plan holds a claim.
    - **Acepto (D14).** Calls are built from state, as the flow does: the block with the policy's reason, then `create_claim(dispute.picked_tx_ids, sorted(dispute.answers), sorted(state priority_flags), token)`, through `execute_plan`, with no LLM call. A failed or unverified step returns `execute_plan`'s handoff update with the cleared keys, `dispute: None` and one `handoff` segment. Verified outcomes, each with `actions`, the cleared keys (`pending`, `confirmation_token_id`, `agent_plan_steps`) and `dispute: None`:
      - (a) block and claim → `segments` = the `dispute_claim_opened` text (card last4, case ids, the block read-back's time, as `_compromise_success` fills it) plus `_fraud_handoff(state, dispute, [])`; segment `handoff`.
      - (b) compromise, claim alone, `block_refused` false (D11) → `_claim_reply_text` plus `_fraud_handoff(state, dispute, [])`; segment `handoff`.
      - (d) not compromise, `priority_flags` set → `_claim_reply_text` plus the `priority.handoff` reason and queue, `_evidence(dispute)` and `_flag_lines(state)`, as `_single_charge_success` does; segment `handoff`.
      - (e) not compromise, no flags → `agent_code_text` = `_claim_reply_text`, `agent_plan_result` = `{"outcome": "confirmed", "steps": [{"action": "claim", "card_id": <dispute card>, "case_id": <case ids joined with ", ">}]}`, `agent_offer: None`, segment `resolved`. No handoff key.
      - In (a), (b) and (d) there is no `agent_code_text`. No outcome sets a replacement offer.
    - **No acepto (D15).** The token is cancelled first, always. Not compromise → today's `_decline` update plus `dispute: None`, segment `cancelled`. Compromise with a claim-only plan and `block_refused` false (D11) → `_handoff_no_claim(state, dispute)` with `handoff_open_questions` reduced to `dispute_open_question_claim_refused` plus the flag lines, cleared keys, segment `handoff`. Two-step plan → for now the Cut 1 form: a Fraudes handoff with no claim, text `dispute_handoff_no_claim`, open questions `dispute_open_question_card_active` plus the flag lines, cleared keys, `dispute: None`, segment `handoff`, in one clearly marked branch that T10 replaces.
    - Write in the state file: the real signatures of the four functions, how `propose_plan` reaches them, and any deviation from I3 to I7.
  - Verify: `cd backend && uv run python -c "from app.domains.conversation.agent.dispute import check_claim, build_claim_plan, accept_claim_plan, decline_claim_plan; from app.domains.conversation.agent.plan import ProposedStep; ProposedStep(action='claim', charges=['t1'], answers={}); print('ok')" && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_plan_check.py tests/unit/test_agent_confirmation.py tests/unit/test_agent_unlock_replace.py tests/unit/test_agent_step_up.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/agent/dispute.py app/domains/conversation/agent/plan.py app/domains/conversation/agent/confirm.py && uv run ruff format --check app/domains/conversation/agent/dispute.py app/domains/conversation/agent/plan.py app/domains/conversation/agent/confirm.py && uv run mypy app/domains/conversation/agent/dispute.py app/domains/conversation/agent/plan.py app/domains/conversation/agent/confirm.py --follow-imports=silent && ! grep -n 'app.core.llm' app/domains/conversation/agent/dispute.py`
  - Files: `backend/app/domains/conversation/agent/dispute.py`, `backend/app/domains/conversation/agent/plan.py`, `backend/app/domains/conversation/agent/confirm.py`

- [ ] T8: Agent node: prompt v3, the pick event, header references, `dispute` lifetime, the claim result event
  - Depends on: T2 (`dispute_question`, `case_id`), T3 (`agent@v3.md` must exist), T5 (`register_tx_rows`, the `dispute_pick` pause and the `dispute` it stores)
  - Read exactly these: spec D4, D5, D14 (e), D19 and §"Contracts" → "Turn events" and the sentence on the question ids under "`policies/tools.yaml`"; `backend/app/domains/conversation/agent/node.py` (whole file); `backend/app/domains/conversation/flows/unrecognized_charge.py` lines 216–247 (`_resume_pick`: how the picks are checked and stored)
  - Acceptance:
    - `_PROMPT = PromptRef("agent", 3)`.
    - **Tool description.** The `propose_plan` description also explains the `claim` step, and lists the question ids for `answers` built from `load_disputes_policy()` (`possession_question`, then `questions`). No id is a literal in this file.
    - **Pick at the dispute pause (D4).** When `selection` is set and `pending` is `{"flow": "agent", "node": "dispute_pick", "awaiting_slot": "transactions"}`: if `state["dispute"]` is missing or the ids are not a subset of `dispute.offered_tx_ids`, the turn ends as today's unknown pick does (`nothing_pending`, nothing stored). Otherwise the picks are stored in `dispute.picked_tx_ids` the way `_resume_pick` stores them, the rows are read with `bank_tools.get_transactions_by_ids` and registered with `register_tx_rows`, and the turn's message is a code-written event: "the customer picked these charges on the list", one line per `t` reference with its fenced facts (`refs.render`). A pick at the `pick` pause of `search_transactions` behaves as before.
    - **Same-turn visibility.** On that turn the tools are built from a state copy whose `dispute` holds the picks, so a `propose_plan` call in the pick turn sees them. The picks are also written to the node's update.
    - **Header (D5).** On any other turn where `pending["flow"] == "agent"` and `dispute.picked_tx_ids` is not empty, the header lists the picked charges as `t` references in a data fence (same read and same helper). These reads sit inside the node's `try`, so `ToolUnavailable` takes the existing `tool_failure` path. Typed text never changes the picks.
    - **Lifetime (D5).** `dispute` is set to `None` in the branch that sets `tx_offer` to `None` today, and on every handoff this node returns (`PlanHandoff`, the round cap, `clarification_exhausted`). A `dispute` that `refs.graph_update` or the box update carries this turn still wins: the existing merge order is kept.
    - **Claim result event (D14 e).** `_plan_event` names a `claim` step ("reclamo por cargos no reconocidos") and registers on its card handle the facts `card_mask` and `case_id` (value: the step's `case_id`, source `disputes.create_claim`), so Cardy can only reference the case id. The step index is verified, as for other steps.
    - The counters are not changed (D19): the `asked` branch stores `awaiting_slot: "dispute_question"` like any slot.
    - The module still names no write tool, token or executor (R6). No fraud score, flag, block reason or queue enters a header, an event or a tool description.
    - If the state file says `Cut 2 taken`: the pick event handles one id.
    - Write in the state file: where the picks are stored in the update, the event's first line, and any deviation from I3 or I6.
  - Verify: `cd backend && grep -n 'PromptRef("agent", 3)' app/domains/conversation/agent/node.py && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_happy.py tests/unit/test_agent_confirmation.py tests/unit/test_agent_fallbacks.py tests/unit/test_agent_reply_check.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/agent/node.py && uv run ruff format --check app/domains/conversation/agent/node.py && uv run mypy app/domains/conversation/agent/node.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/node.py`

- [ ] T9: Tests 1, 2, 4, 5 and 6 in `test_agent_dispute.py`
  - Depends on: T1 to T8 (the tests run the policy, the read tool, the gate, the claim module, the button node and the agent node end to end; real names are in the state file)
  - Read exactly these: spec §"Test list" rows 1, 2, 4, 5, 6; `backend/tests/unit/test_agent_unlock_replace.py` (how an agent conversation is scripted and asserted) and `backend/tests/unit/test_dispute_flows.py` (the fixtures and the flow run that test 6 compares with); `backend/tests/unit/test_selection_gate.py` (the `post_message` call for test 1 a) and `test_agent_plan_check.py` (a direct `propose_plan` call for tests 1 b, 1 c and 2)
  - Acceptance:
    - New file with exactly these functions, all with `ScriptedLLM` and the fake bank, customer `CLI-TFSINGLE0002`, no other test added:
    - `test_r1_foreign_or_unpicked_charge_refused`: (a) at a checkpoint paused on the agent dispute pause, `post_message` with a `selection` holding another customer's transaction id (taken from `backend/tests/fixtures/fakebank`) raises `409 selection_invalid` and `start_turn` is not called; as the control in the same test, an offered id does reach `start_turn`. (b) `propose_plan` with a `claim` whose `charges` holds a raw foreign id returns `rejected (claim: unknown_reference)`. (c) a `claim` naming a registered charge of this customer that is not in the picked set returns `rejected (claim: not_picked)`. In (b) and (c): no plan in `session.store._plans`, no `confirmation_issued` event, no write tool ran.
    - `test_r8_claim_gated_by_policy_preconditions`: one low-score pick, `answers` empty → `missing_answer:card_in_possession`; possession `yes` only → `missing_answer:contacted_merchant`; no token either time. With the card blocked (`session.overlay.blocked`) and the score-45 charge picked, the accepted plan has one `disputes.create_claim` step and no block. `issue_plan([create_claim step], None)` under a tools policy without that `preconditions` block raises `PolicyDenied`.
    - `test_single_charge_claim[es, pt]`: request → `card_status` and `dispute_candidates` → a `selection` of `TXN01` → the two answers over two typed turns → a card with `labels == "accept_decline"` and one `disputes.create_claim` step → Acepto → one `readback` → Cardy's reply written with the `case_id` reference; the case id is in `reply_sent.fact_values`; one `unrecognized_charge` segment `resolved`; `path == "agent"`; `session.handoff_tools.created == []`.
    - `test_compromise_block_and_claim[es, pt]`: ES picks `TXN01` and `TXN02`, PT picks `TXN03`; the scripted `propose_plan` call carries no answers and the plan is accepted in the pick turn; the card shows `cards.block_card` then `disputes.create_claim`; Acepto → two `readback`s; the reply is the `dispute_claim_opened` text then `handoff_transfer`; mode is human; the script has no `agent` output for the Acepto turn, so no LLM call wrote the result.
    - `test_handoff_packet_same_as_flow`: the same compromise case run once with the flag off (the flow) and once with it on; the two packets from `session.handoff_tools.created` are equal on `reason`, `queue`, `priority`, `evidence` (refs and fraud scores), `verified_facts` names and values, `actions_taken` tools and `case_ids`, `open_questions`, `escalation_rules_hit`, `routing`, `risk.priority_flags`, `focus_card`, after removing the fields the spec's row 6 lists. The test sets `AGENT_ENABLED` itself for each run (`monkeypatch.setenv` and `get_settings.cache_clear()`), because `.env` has it on.
    - The flag-off files still pass unchanged.
    - A failing test that shows a defect in `agent/dispute.py`, `agent/plan.py`, `agent/confirm.py`, `agent/node.py` or `agent/reads.py` is repaired there, within the spec, and the repair is written in the state file. A fix that would need `flows/`, `graph.py`, `nodes/handoff.py` or `tools/executor.py` is not made: stop and report it.
    - If the state file says `Cut 2 taken`: test 1 (a) uses the single-pick gate, and test 5 ES reaches compromise through a "no" to possession.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_dispute.py -q -k "r1 or r8 or single_charge or compromise or packet" && AGENT_ENABLED=false uv run pytest tests/unit/test_dispute_flows.py tests/unit/test_selection_gate.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check tests/unit/test_agent_dispute.py && uv run ruff format --check tests/unit/test_agent_dispute.py` (the first command reports 7 passed)
  - Files: `backend/tests/unit/test_agent_dispute.py`, and only to repair a defect a test exposes: `backend/app/domains/conversation/agent/dispute.py`, `backend/app/domains/conversation/agent/plan.py`, `backend/app/domains/conversation/agent/confirm.py`, `backend/app/domains/conversation/agent/node.py`, `backend/app/domains/conversation/agent/reads.py`

- [ ] T10: The refused-block branch (D15, D14 c) and test 3
  - Depends on: T7 (`decline_claim_plan`, `accept_claim_plan` and the marked two-step branch it replaces), T9 (the test file and its helpers)
  - Read exactly these: spec D14 (c), D15, §"Test list" row 3 and §"Cut order" item 1; `backend/app/domains/conversation/agent/dispute.py` (as T7 left it; see the state file); `backend/app/domains/conversation/flows/unrecognized_charge.py` lines 438–525 and 608–667 (`_offer_claim_only`, `_resume_cancel`, `_claim_only_success`, `_handoff_no_claim`)
  - Acceptance:
    - **No acepto on the two-step plan.** The token is cancelled, `dispute.block_refused` becomes true, and in the same turn code issues the claim-only plan with `issue_plan(steps, None)`: no write, no LLM call. The update holds the new `confirmation_token_id`, `agent_plan_steps` = the claim step alone, the confirmation pause `{"flow": "agent", "node": "confirm", "awaiting_slot": "confirmation"}`, `ui` and `asked_ui` = the new `accept_decline` card (one `create_claim` step, fact `tx_count`), `segments` = the `dispute_block_refused_offer_claim` text, the updated `dispute`, `priority_flags`, and one `unrecognized_charge` segment `awaiting` with slot `confirmation`. It sets no `agent_code_text` and no handoff key, so the turn ends at `finish`. `ToolUnavailable` while building it gives `tool_failure` with the cleared keys.
    - **No acepto on that claim-only plan** (`block_refused` true) → `_handoff_no_claim(state, dispute)` as it is (text `dispute_handoff_no_claim`, both open questions), cleared keys, segment `handoff`, zero writes.
    - **Acepto on that claim-only plan (D14 c)** → `_claim_reply_text` plus `_fraud_handoff(state, dispute, [dispute_open_question_card_active])`, as `_claim_only_success` does; segment `handoff`; no `agent_code_text`.
    - `test_r2_refused_block_reissues_claim_only` is added to `test_agent_dispute.py`: after No acepto on the two-step plan the first token is cancelled, no write ran, no `agent` LLM output was consumed, the reply is the `dispute_block_refused_offer_claim` text and the new card has a new token and one `create_claim` step; a second No acepto gives one Fraudes packet with no claim, both open questions and zero writes.
    - Nothing outside `agent/dispute.py` and the test file changes.
    - **If the state file says `Cut 1 taken`:** the branch is not built. `dispute.py` is left as T7 wrote it. The test asserts only: token cancelled, zero writes, one Fraudes packet with no claim. The D15 sentence in `02` §4.8 and in the ADR-035 S3 bullet is corrected to the Cut 1 behaviour.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_dispute.py -q && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_confirmation.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/agent/dispute.py tests/unit/test_agent_dispute.py && uv run ruff format --check app/domains/conversation/agent/dispute.py tests/unit/test_agent_dispute.py && uv run mypy app/domains/conversation/agent/dispute.py --follow-imports=silent && cd .. && git diff --stat origin/develop -- backend/app/domains/conversation/flows backend/app/domains/conversation/nodes/handoff.py backend/app/domains/conversation/templates.py policies/disputes.yaml policies/escalation.yaml eval` (the first command reports 8 passed; the `git diff --stat` prints nothing)
  - Files: `backend/app/domains/conversation/agent/dispute.py`, `backend/tests/unit/test_agent_dispute.py`, and only under Cut 1: `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/decision-log.md`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3, T4, T5, T6 | | Each depends on nothing and owns its own files: policy and its test; contracts; prompt and playbook; docs; `reads.py`; `runner.py`. T1 and T3 both run `test_policy_registry.py`, which only reads. |
| W2 | T7, T8 | | T7 owns `dispute.py`, `plan.py`, `confirm.py`; T8 owns `node.py`. They meet only through I3, I5, I6 and I7, which are in the state file. |
| W3 | T9 | | It runs every piece end to end and may repair the five agent files, so nothing else may write to them at the same time. |
| W4 | T10 | | It edits `dispute.py` and the test file T9 created. Under Cut 1 it shrinks to the reduced test and one doc sentence. |

No task changes the shared environment: no dependency, lockfile, migration, `make data`, `make client` or restart, so none is marked alone. The backend full check is the verifier's `make check AGENT_ENABLED=false`. The browser proof (success criterion 6) is outside the task list.
