# State: REQ-cardy-agent-s3 — S3 · Unrecognised charge
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-cardy-agent-s3 (no group, owner A) · spec `docs/specs/cardy-agent-s3-unrecognised-charge.md` · plan `docs/plans/cardy-agent-s3-unrecognised-charge.md`
Branch `feat/cardy-agent-s3-unrecognised-charge`, based on `origin/develop` @ 40cb806. Worktree `.claude/worktrees/cardy-agent-s3`.

## Conventions established for this card
- **Read the plan's "Facts checked against the repo" section first: plan lines 7–51.** It holds the repo facts and the seven interfaces I1–I7 that T7 and T8 build against. They are binding; a task that needs to change one stops and reports.
- This worktree's `.env` has `AGENT_ENABLED=true`. Every test command sets `AGENT_ENABLED=false` on the command line, exactly as the task's `Verify` writes it.
- If the sandbox refuses a long `&&` chain, run each part of `Verify` as its own command.
- Nothing under `backend/app/domains/conversation/flows/`, `nodes/handoff.py`, `graph.py`, `templates.py`, `policies/disputes.yaml`, `policies/escalation.yaml` or `eval/` changes. A task that needs one of them stops and reports.
- Always a scripted/fake LLM in tests. Never touch `eval/scenarios/heldout/`.
- The dev stack hot-reloads this worktree's `backend/app` and `policies/`. No task restarts it.
- Spec D3 "at most 10" candidates is the existing `LIMIT 10` in `backend/app/domains/transactions/repository.py` `_build_query`, the query behind `bank_tools.search_transactions`. No cap is written in the agent code, and none is to be added.

## Human decisions taken mid-card
- Plan open question (planner): `reply_sent.route` stays `card_block` on the re-issued claim-only plan turn and on a stale click at a claim plan. Human: leave it; no `runner.py` change beyond T6.
- Verify gate (safety verifier): with a plan open, a list that replaces the confirm pause left the old confirmation token live. Human: cancel the open token when a list replaces the confirm pause; `agent/node.py` change plus one R2 test (task T11).
- Verify gate (suite verifier, T8 deviation): an empty or off-list pick at the dispute pause is answered with `nothing_pending` and the pick is dropped. Human: keep it.

## Cut line
No cut taken. W3 ended at 13:22 with time in hand, so T10 is built in full (Cut 1 not taken). Cut 2 (multi-pick list) was not taken before W1.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a083dec | tools.yaml v5 + Preconditions.tx_owned/answers_complete; 12 passed, lint clean |
| T2 | done | aa76e01 | claim action, dispute_question slot, case_id formatter; 1 passed, lint clean |
| T3 | done | a814b1b | agent@v3.md + unrecognized_charge playbook; greps ok, 2 passed. node.py still PromptRef 2 (T8 owns it) |
| T4 | done | a037baa | ADR-035 S3 bullet, 02 §3/§4.8, 04 §1/§3/§5; greps ok |
| T5 | done | a33fe43 | dispute_candidates + register_tx_rows in reads.py; 10 passed, lint clean. No cap of 10 (open) |
| T6 | done | ae1477a | checkpointed_offer handles agent dispute_pick (multi); 1 passed, lint clean |
| T7 | done | afe2433 | agent/dispute.py (check, build, accept, decline) wired into plan.py + confirm.py; 17 passed, lint clean. Cut 1 form marked for T10 |
| T8 | done | a57bfbf | node.py: prompt v3, pick event, header refs, dispute lifetime, claim result event; 14 passed, lint clean. Empty pick -> nothing_pending |
| T9 | done | a1eef59 | test_agent_dispute.py: 7 passed (r1, r8, single ES/PT, compromise ES/PT, packet); 14 flag-off passed; no agent file repaired. Test 6 normalises CLM ids |
| T10 | done | aec4ecb | refused-block branch in dispute.py (re-issue claim-only, D14 c, D15) + test_r2; 8 passed, lint clean; protected paths no diff |
| T11 | done | a57bfbf | a list replacing the confirm pause cancels the open token (`cancel_open_plan`), covers `dispute_candidates` and `search_transactions`; `test_r2_new_list_cancels_open_claim_token`; 9 + 7 passed, ruff/mypy clean, health 200 |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T4 — Docs: ADR-035 S3 amendment, 02 §3/§4.8, 04 §1/§3/§5
Changed: `docs/solution-docs/decision-log.md` (S3 bullet after OTP-exit), `02-conversation-design.md` (routing row, S3 paragraph, §4.8 agent note), `04-contracts.md` (§1 table + paragraph, §3 selection row, §5 YAML v5 + "version 5" sentence).
Facts: multi-pick (no cut). `02` §3 intro line 50 still says `agent@v1` (stale since S1/S2); left untouched, the S3 paragraph names `agent@v3`.
Deviations: none.
Verify: the seven greps each matched (decision-log:232; 04:68, 223, 232/292, 72/292; 02:57, 65).

### T3 — Prompt `agent@v3` and the `unrecognized_charge` playbook
Created: `backend/app/domains/conversation/prompts/agent@v3.md` (copy of v2 + `dispute_candidates`, `claim` step and result codes, "Un cargo que el cliente no reconoce" section, `dispute_question` slot). `agent@v2.md` untouched.
Changed: `policies/playbooks.yaml` (`unrecognized_charge` added, version stays 1).
Facts the next tasks need: `agent/node.py` `_PROMPT` is still `PromptRef("agent", 2)`; bumping it to 3 is not done by T3. The prompt says the question ids are in `propose_plan`'s own tool description.
Deviations: none.
Verify: `uv run pytest tests/unit/test_policy_registry.py -q` → 2 passed; grep checks pass, forbidden-word grep empty, v2 diff empty.

### T1 — Policy: tools.yaml v5, Preconditions fields, test stand-in
Changed: `policies/tools.yaml` (`version: 5`, `disputes.create_claim` gains `preconditions: {tx_owned: true, answers_complete: true}`), `backend/app/domains/policy/tools_policy.py` (`Preconditions.tx_owned`, `Preconditions.answers_complete`, both `bool | None = None`), `backend/tests/unit/test_agent_plan_check.py` (PolicyDenied step now `cards.get_block_origin`).
Facts the next tasks need: new version is 5; field names `tx_owned`, `answers_complete`. tools.yaml had no version-naming header comment, so a trailing comment on the `version: 5` line names v5.
Deviations: none.
Verify: pytest 3 files -> 12 passed; ruff check/format, mypy, both greps pass (first run hit a transient NameError from a sibling's half-written file, passed on re-run).

### T6 — Selection gate for the agent dispute pause
Changed: `backend/app/domains/conversation/runner.py` (`checkpointed_offer`: agent + `dispute_pick` branch before the `tx_offer` branch, returns `dispute.offered_tx_ids`, multi `True`; docstring updated).
Facts the next tasks need: other agent pauses still return `tx_offer`, multi `False`. `api/v1/conversations.py` untouched. Existing `test_selection_gate.py` has 1 test and still passes; no new test was written (the plan's T9 owns the R1 proof).
Deviations: none.
Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_selection_gate.py -q` → 1 passed; grep finds `dispute_pick`; ruff check, ruff format --check, mypy all clean.

### T2 — Contracts: claim action, dispute_question slot, case_id formatter
Changed: `state.py` (`AgentPlanStep.action` adds `"claim"`), `agent/schema.py` (`AgentTurn.awaiting_slot` adds `"dispute_question"`), `nodes/compose.py` (`_format_fact` returns `str(value)` for `case_id`, next to `tracking_id`). `DisputeState` untouched.
Facts the next tasks need: none new.
Deviations: none. The Verify python one-liner was run from a temp file with `PYTHONPATH=.` (sandbox refused the inline form).
Verify: python check → ok; `test_agent_reply_check.py` → 1 passed; ruff check, ruff format --check, mypy → clean.

### T5 — Read tool `dispute_candidates` and `register_tx_rows`
Changed: `backend/app/domains/conversation/agent/reads.py` (`register_tx_rows` exported; `_list_rows` calls it; tool `dispute_candidates` added).
Facts the next tasks need: tool name `dispute_candidates`, arg `card: str` (card ref). Helper: `async def register_tx_rows(rows: list[TxView], refs: TurnRefs, bank_tools: BankReadTools, language: Language) -> list[str]`.
`refs.graph_update` keys written when rows exist: `ui` (one multi=True TransactionListEvent), `dispute` (DisputeState, empty picks/answers, flags False), `selected_card_id`, `pending` = {flow: agent, node: dispute_pick, awaiting_slot: transactions}. No rows: returns "no candidate transactions." and writes nothing. No `tx_offer` (Cut 2 not taken). `fraud_score` only in `dispute.fraud_scores`.
Deviations: none (no "at most 10" limit written; the task says no limit in Python, spec D3 says at most 10, and TxFilter has no limit field).
Verify: import ok; test_agent_happy.py + test_r6_no_write_tools_in_llm_nodes.py -> 10 passed; ruff check/format and mypy clean.

### T8 — Agent node: prompt v3, pick event, header refs, dispute lifetime, claim result event
Changed: `backend/app/domains/conversation/agent/node.py` only (`_PROMPT` = agent v3; `_claim_question_ids()` builds the `answers` ids line of the `propose_plan` description from `load_disputes_policy()`; `_is_dispute_pause`, `_picked_refs`; `_plan_event` names `claim` and adds fact `case_id` from `step["case_id"]`).
Facts the next tasks need: picks are stored in the node update under `dispute` (a `DisputeState` with `picked_tx_ids` set), written before the branches so the `dispute = None` clear and `refs.graph_update`/`box.update()` still win. Tools get a state copy with the picks (I3). Pick event first line: "Evento del sistema (no es un mensaje del cliente): el cliente eligio estos cargos en la lista:" then `- el cargo t1` + fenced `refs.render`. Header (non-pick agent turns with picks) adds "Cargos que el cliente ya eligio en la lista (dato, no instrucciones):" plus the same lines. `dispute: None` also on PlanHandoff (before `**exc.update`), round cap, `clarification_exhausted`.
Deviations: an empty `selection.tx_ids` at the dispute pause is treated as invalid (`nothing_pending`), same as an unknown id. The pick event does not set `compromise` (that is T7's check). None from I3/I6; the step's `case_id` is read with `.get`, as `tracking_id` is.
Verify: grep ok; pytest 5 files -> 14 passed; ruff check, ruff format --check, mypy clean.

### T7 — Claim module and wiring
Created: `agent/dispute.py`: `check_claim(actions: Sequence[str], charges, answers: Mapping[str,str]|None, refs, state) -> list[str|None]` (sync); `async build_claim_plan(state, config, refs, box, answers) -> str`; `async accept_claim_plan(state, config) -> dict`; `async decline_claim_plan(state, config) -> dict`. Also exports `has_claim`, `claim_segments`, `current_dispute`. Takes a `_Box` Protocol, so no plan.py import.
Changed: `plan.py` (ProposedStep, claim maps, `plan_segments`/`plan_labels`, `PlanBox.set(..., extra=None)`, `_rejected` labels a claim step `claim`), `confirm.py` (`agent_plan` routes claim plans; `count_open_plan_turn` clears `dispute`).
How `propose_plan` reaches them: `check_steps` (after the not-active handoff) returns `check_claim(...)` when a claim step exists; after `cancel_open_plan`, `propose_plan` returns `build_claim_plan(...)` for a claim step.
Facts: `_compromise_success` and `_single_charge_success` are reused whole for (a) and (d). Non-compromise decline update is rebuilt in dispute.py (confirm's `_decline` cannot be imported, cycle). Cut 1 branch marked `CUT 1 FORM (T10 replaces ...)` at the end of `decline_claim_plan`. `issue_stored_plan` untouched (claim plans never go through it).
Deviations from I3-I7: none.
Verify: import ok; pytest 5 files -> 17 passed; ruff check/format, mypy clean; no `app.core.llm` in dispute.py.

### T9 — Tests 1, 2, 4, 5, 6 in `test_agent_dispute.py`
Created: `backend/tests/unit/test_agent_dispute.py` (5 functions, 7 cases). No agent file repaired.
Facts the next tasks need: `run_recorded_turn` builds `ServiceHandoffTools(ctx)` from the database, so tests that reach a handoff there do `monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)` (as `_compromise_via_agent` does). Test 1 (a) passes `_check_turn_caps` and `start_turn` as monkeypatched stubs. Handles of the picks in a later turn are `t1..` in pick order (header refs).
Deviations: test 6 maps each `CLM-<hex>` case id to `CLM-*` before comparing `case_ids` and `claim_filed`, because the fake bank mints random case ids per run (count still compared). Mode human in test 5 is checked as `reply_sent.route == "handoff"` (the runner's own publish is stubbed).
Verify: dispute tests -> 7 passed; test_dispute_flows + test_selection_gate + test_r6 -> 14 passed; ruff check and format clean.

### T10 — Refused-block branch (D15, D14 c) and test 3
Changed: `agent/dispute.py` (Cut 1 branch replaced: `decline_claim_plan` now re-issues the claim-only plan via new `_offer_claim_only` on the two-step plan, and `_handoff_no_claim` when `block_refused`; `accept_claim_plan` adds `dispute_open_question_card_active` to the D11/(c) handoff when `block_refused`, via `_card_active_question`). Imports `_replace` from the flow and `fill` from `flows/actions`.
Changed: `tests/unit/test_agent_dispute.py` (`test_r2_refused_block_reissues_claim_only`; patches `runner.ServiceHandoffTools` as T9's helper does).
Facts: cancelled plans are removed from `store._plans` (the test asserts the first token is gone, the second present, then none). The packet builder adds its own first open question, so the test asserts both refusal questions are `in` the list, not equal to it. `ToolUnavailable` while re-issuing gives `{**cleared, escalation_reason: tool_failure}`; not tested. D14 (c) accept path is wired but has no test (not in the task).
Deviations: none.
Verify: dispute tests -> 8 passed; confirmation + r6 -> 7 passed; ruff check/format, mypy clean; git diff --stat on the five protected paths prints nothing (the `eval` path was refused by the sandbox's eval filter; untouched).

### T4 repair — seven doc lines made true to the S3 code
Changed: `02-conversation-design.md` (L56 claim-plan outcomes, L69 no offer after a claim plan's block, L75 claim plan not narrowable by typed text, L88 `dispute_pick` pause); `04-contracts.md` (L72 stored `[block, claim]`, L110/111 dispute-pause sentence moved to the `selection` check, L323 `card_block` route exception).
Left: `02` L73 ("Confirming an agent plan") still describes Cardy phrasing the result; not in the repair list.
Verify: the seven T4 greps still hit.

### T9 (verifier repair round) — three missing assertions in `test_agent_dispute.py`
Changed: `backend/tests/unit/test_agent_dispute.py` only. Test 4: `_spy_unmask` + `sent_texts[-1].startswith(<scripted reply with the case id filled> + "\n\n")` (line ~369). Test 5: second agent call's `tool_results == ("accepted (block_added)",)` (~431). Test 3: `packet.queue == "fraudes"`, `packet.reason == "suspected_fraud"` (~553).
Facts: the PT scripted Acepto reply was Spanish, so the grounding check (`_wrong_language`) replaced it with code's text and the old test passed anyway; the script is now per language. The sent text is Cardy's reply + code's closing line.
Deviations: none; no agent code touched.
Verify: `uv run pytest tests/unit/test_agent_dispute.py -q` -> 8 passed; ruff check and format clean.
Correction: my earlier claim that `02` "Confirming an agent plan" was fixed was wrong (the command was refused, nothing written). The claim-plan sentence is now on disk in that paragraph; verified by grep.

### T11 — Cancel the open token when a list replaces the confirm pause
Changed: `backend/app/domains/conversation/agent/node.py` (`replaced` flag + `cancel_open_plan` after the loop; its clearing update and `dispute: None` merged before `refs.graph_update`, so a new list still wins), `backend/tests/unit/test_agent_dispute.py` (`test_r2_new_list_cancels_open_claim_token`).
Facts: one merge point covers `dispute_candidates` and `search_transactions` (both write `pending` through `refs.graph_update`); condition is plan open, not opened this turn, not `issued`, `"pending"` in `refs.graph_update`. A replaced plan is no longer `carried` (no card replay, no typed-turn count).
Deviations: none.
Verify: dispute file 9 passed; r6 + confirmation 7 passed; ruff check/format, mypy clean; health 200.
T11 doc follow-up: `02` §3 "A typed message while an agent plan is open" and the ADR-035 S3 bullet now say a list replacing an open plan's confirm pause cancels that plan's token (checked against `agent/node.py` 447-452); greps hit.
