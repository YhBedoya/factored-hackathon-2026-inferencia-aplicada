# Spec: cardy-agent-s3-unrecognised-charge

Card source: [`docs/requirements/cardy-agent.md`](../requirements/cardy-agent.md), slice **S3** (lines 180–192) plus the shared sections (lines 1–125, 194–222) · owner **Dev A** · reviewer **Dev B** before merge (safety-critical, ADR-018) · branch `feat/cardy-agent-s3-unrecognised-charge` off `origin/develop` (40cb806). Builds on [the S1 spec](cardy-agent-s1-conversation-reads-block.md) and [the S2 spec](cardy-agent-s2-unlock-replacement.md): "S1 Dn" / "S2 Dn" mean a decision there, and all of them stand unless a line below narrows one. "Qn" is the human's Pass-2 answer to question n (all six answered with option a); "An" is Pass-1 assumption n (all fifteen stand; A3 was put to the human and confirmed). "The flow" is `backend/app/domains/conversation/flows/unrecognized_charge.py`; "REQ" is the requirement doc.

## Objective

With `AGENT_ENABLED` on, Cardy handles an **unrecognised charge** herself instead of passing it to the pipeline. She reads the card, asks code for the candidate charges (a code-rendered multi-pick list), asks the dispute questions in her own words, and proposes a `claim` step through `propose_plan`. Code owns everything else: it checks that the charges are the ones the customer picked and that the answers `policies/disputes.yaml` requires are present, applies the compromise rule, adds the block step, builds the priority flags, issues one plan with "Acepto / No acepto", executes it from the button with a read-back per step (ADR-027), and hands off to Fraudes or Reclamos with the same packet fields the flow produces today. This serves the three S3 "Done when" lines: (1) a single-charge claim and a suspected-compromise case in ES and PT with the flag on; (2) a claim with a missing answer or a foreign transaction id is refused (R1, R8 tests); (3) the handoff packet carries the same fields as today. It also closes S1's open item F2 for claims: a claim Cardy proposes is confirmed by button only.

Flag off, the flow, `allowed_intents`, `policies/disputes.yaml`, `policies/escalation.yaml`, `nodes/handoff.py` and the degraded path are unchanged (A1, A8).

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **The flow stays as it is; preconditions are added, not moved.** Nothing under `flows/` changes. Helpers the agent path needs are imported, as S2 imports `_card_eligible`: from the flow `_priority_flags`, `_fraud_handoff`, `_handoff_no_claim`, `_flag_lines`, `_claim_reply_text`, `_compromise_success`, `_single_charge_success`, `_replace`, `_tx_option`; from `flows/actions.py` `execute_plan` and `fill`. `_evidence` is reached through `_fraud_handoff` and `_single_charge_success`, not imported. | A1. S1 D9, S2 D5. REQ D5. |
| D2 | **Cardy takes the request type.** `agent@v3` drops "un cargo que el cliente no reconoce" from the `pass_to_flow` list and explains the claim step, its reason codes and that she never names a block, a reason, a queue or a threshold. `policies/playbooks.yaml` gains `unrecognized_charge` (guidance only). | Card "What is built". A10. S2 D20. 06 R8. |
| D3 | **Candidate charges come from a new read tool, `dispute_candidates(card)`.** Code runs the flow's search (`TxFilter(card_id, status=disputes.yaml candidate_statuses)`; at most 10 rows through the existing `LIMIT 10` in `transactions/repository.py`, agent code has no cap of its own), registers each row as a `t` reference with the facts `_list_rows` registers, emits `ui.transaction_list` with `multi: true` (labels from `_tx_option`), and stores a `DisputeState` in `state.dispute` (card, offered ids, fraud scores, empty picks) plus `selected_card_id`. No candidates: the tool says so and nothing is stored. `search_transactions` keeps its single-pick list. | Q2 (a). `02` §4.8 step 1. S1 D21. |
| D4 | **The picked set is written only by a `selection` turn.** The route's gate accepts a multi-pick at the agent dispute pause against `dispute.offered_tx_ids` (`409 selection_invalid` otherwise, no turn). The agent node checks again that the picked ids are a subset of the offered ones, stores them in `dispute.picked_tx_ids`, and gives Cardy a code-written turn event naming the picked `t` references. Typed text never sets or changes the picks: Cardy calls `dispute_candidates` again and the customer picks on the list. A pick at the dispute pause that is empty or holds an id that was not offered is answered with `nothing_pending` and the whole pick is dropped; nothing is stored and no LLM call runs (H5). The route's gate makes this unreachable through the API today. | Q2 (a). `04` §3 (selection gate). 06 R1. S1 D21. H5. |
| D5 | **Picks live in state and reach Cardy as references each turn.** While an agent pause is open (`pending.flow == "agent"`) and `dispute.picked_tx_ids` is not empty, the turn header lists the picked charges as `t` references in a data fence. `dispute` is cleared wherever the node clears `tx_offer` today (a turn that ends with no question and no plan), when a claim plan ends, on a handoff, and it is replaced by a new `dispute_candidates` call. **When a list replaces the confirm pause of an open plan, code cancels that plan's token** (H4): no token stays live that the customer can no longer confirm. One merge point in `agent/node.py` serves both list reads, so this holds for `dispute_candidates` and for a `search_transactions` list. The replaced plan is not shown again and the turn is not counted as a typed turn on an open plan (S1 D13, D17 b). | Q2 (a). S1 D18 (references are per turn). `agent/node.py` (`tx_offer` lifetime). H4. 06 R2. |
| D6 | **Cardy proposes only the claim, and asks the questions herself.** `propose_plan` gains the action `claim`, with `charges` (this turn's `t` references) and `answers` (question id → `yes` \| `no`). Cardy asks the dispute questions in her own words; code never asks them on the agent path. A rejected plan names what is missing and Cardy asks for it. | A2, A3 (confirmed by the human). REQ D4. Card item 1. |
| D7 | **A claim plan stands alone.** A proposal that holds a `claim` step and any other step (or two `claim` steps) is rejected whole with `claim_alone`. The only extra step in a claim plan is the block that code adds (D10). | Q5 (a). |
| D8 | **Charge ownership (R1).** A `charges` reference that is not a transaction reference of this turn is `unknown_reference` and is never looked up; this includes a raw id and another customer's transaction. The resolved ids must equal `dispute.picked_tx_ids`, else `not_picked` (a charge the customer did not pick on the list, a picked one left out, or no list picked yet). The claim, the compromise count and the evidence are always computed over the full picked set, so the model cannot shrink it. The executor's `AccessDenied` on a foreign id stays as the last gate. | A4. Q2 (a). Card items 1–2. 06 R1. `04` §3 ("a customer can't claim a transaction that was never offered"). |
| D9 | **Required answers, as today.** In this order: (1) `policy.triggers_compromise(picked count, highest picked fraud score)` true → compromise, no answer is read; (2) otherwise `possession_question` is required, missing → `missing_answer:<id>`; "no" → compromise; (3) "yes" → every id in `questions` is required, the first missing one → `missing_answer:<id>`. Only the answers the rule read are stored and sent, as `"<id>=<yes\|no>"` strings in `dispute.answers`, so the claim's `answers` equal the flow's for the same case. Any other key Cardy passes is not read. | Q1 (a). `policies/disputes.yaml`. `02` §4.8 (D4-B D8). Card item 3 ("as today"). 06 R8. |
| D10 | **Code builds the plan.** Compromise → two steps, `cards.block_card` (reason `disputes.yaml compromise.block_reason`) then `disputes.create_claim`; otherwise one `create_claim` step. Claim args are the flow's: `tx_ids` (picked), `answers` (sorted), `priority_flags` (from `_priority_flags`, also written to `state.priority_flags`). The tool result is `accepted`, or `accepted (block_added)` when code added the block, so Cardy's sentence can mention it. Fraud scores, flags, the reason and the token never reach her. | Card items 2–3. A2, A5. S1 D8, D12. `flows/unrecognized_charge.py` (`_start_compromise_plan`, `_start_claim_plan`). |
| D11 | **Compromise on a card already Blocked or Closed: skip the block.** When the dispute's card status is in `cards.block_card` `preconditions.status_not_in`, the plan is the claim alone, the result is `accepted`, and on a verified claim the Fraudes handoff and evidence are those of D14's compromise row, without a block action. | Q4 (a). `policies/tools.yaml`. 06 R8. |
| D12 | **`tools.yaml` v5** gives `disputes.create_claim` a `preconditions` block (`tx_owned`, `answers_complete`; Contracts), so `issue_plan(steps, intent=None)` accepts it. D8 and D9 are how the validator applies them. The block's presence is what `issue_plan` requires; the two values are not switches: the D8 and D9 checks run on every claim proposal, whatever the YAML value (06 R1). | A10. S1 D9. 06 R1, R8. "Done when" 2. |
| D13 | **Button only.** A claim plan is one token from `issue_plan(steps, intent=None)`, shown with `accept_decline` labels and the flow's step views (`block_card` with `card_mask`, `create_claim` with `tx_count`). Cardy writes the sentence; code adds the card. No typed text confirms it. | A6. S1 D11, D12. Closes S1 F2 for claims. |
| D14 | **Acepto** runs the steps through `execute_plan` with no LLM call before the writes, one read-back per step. Outcomes, all built in code with the flow's templates and helpers: (a) block + claim verified → `dispute_claim_opened`, then the Fraudes handoff (`_fraud_handoff`, no extra open question); (b) compromise claim alone because the card was already blocked (D11) → `dispute_claim_opened_single`, then the same Fraudes handoff; (c) claim alone after a refused block (D15) → `dispute_claim_opened_single`, then the Fraudes handoff with `dispute_open_question_card_active`; (d) single charge with priority flags → `dispute_claim_opened_single`, then the `priority.handoff` reason and queue with the evidence and `_flag_lines`; (e) single charge, no flags → Cardy words the result from the code-written event, with the case id as a `{reference}`; if her call fails or the claims check replaces it, the text is `dispute_claim_opened_single`. In (a)–(d) Cardy does not write: the handoff keys send the turn to `handoff_summary`. No replacement offer follows a claim plan's block. | A7. S1 D14, D16, D18. Card item 3. `graph._after_agent_plan`. |
| D15 | **No acepto.** On the two-step plan: code cancels the token, marks `dispute.block_refused`, and in the same turn issues the claim-only plan with `dispute_block_refused_offer_claim` and a new card, with no LLM call. A No acepto on that claim-only plan hands off to Fraudes with no claim (`_handoff_no_claim`: text `dispute_handoff_no_claim`, both open questions). On the D11 claim-only plan, No acepto hands off to Fraudes with no claim and, of the two refusal questions, `dispute_open_question_claim_refused` only (the card is not active). Every Fraudes handoff here also carries the priority flag lines after its open questions, as the flow's `_fraud_handoff` adds them. On a single-charge plan, S1 D15 applies: the plan is cancelled and Cardy asks what to change. | Q3 (a). S1 D15. `flows/unrecognized_charge.py` (`_resume_cancel`, `_fraud_handoff`). The D11 case is a derived reading, confirmed by the human (H3). |
| D16 | **Failures are today's.** A failed or unverified step sends the existing `execute_plan` handoff, never Cardy's text. A customer who is not active is handed off with `customer_not_active` before any plan (`PlanHandoff`). A `ToolUnavailable` while building the plan takes the node's existing `tool_failure` path; the same error while code re-issues the claim-only plan (D15) returns `escalation_reason: tool_failure`, as the flow's `_offer_claim_only` does. | A7, A9. Q3 (a). S1 D14. S2 D5, D6. ADR-027. |
| D17 | **Handoff packet.** The agent path sets the same state keys the flow sets (`escalation_reason`, `handoff_queue`, `handoff_evidence`, `handoff_open_questions`, `priority_flags`, `actions`, `selected_card_id`); `nodes/handoff.py` builds the packet unchanged. Only `suspected_fraud` and `priority_claim` are used. | A8. `04` §4. REQ "Contracts that stay as they are". "Done when" 3. |
| D18 | **Labels.** Every step of a claim plan belongs to one `unrecognized_charge` segment (route `unrecognized_charge`): `resolved` for D14 (e), `handoff` for D14 (a)–(d) and for a no-claim handoff (as `graph._flow_segment` records the flow), `cancelled` for a declined single-charge plan. Turns have `path: "agent"`. `reply_sent.route` stays `card_block` on the turn that re-issues the claim-only plan and on a stale click at a claim plan; the `runner.py` stale-click block is not changed (H1). | S1 D23, D24. `graph._flow_segment`. H1. |
| D19 | **Counters unchanged.** S1 D13 and D17 apply as written. `AgentTurn.awaiting_slot` gains `"dispute_question"` (the flow's slot name) for a turn where Cardy asks a dispute question. | S1 D13, D17. `02` §3 (`awaiting_slot` values). |
| D20 | **A request for a person mid-dispute goes to Atención**, as any agent-path human request does today. No code. Recorded as a follow-up. | Q6 (a). |
| D21 | **Tests:** seven test functions, nine cases (six functions and eight cases as approved, plus the R2 case H4 adds, Test list row 7), all with `ScriptedLLM`. No dev scenario, no eval run, no metric target. | A12. `wave-run` test budget. S2 D21. Memory: postpone performance eval. |
| D22 | **Docs in the same PR:** an S3 amendment line on ADR-035; `02` §3 (routing row for the agent pick, `dispute` on the agent path, `dispute_question` slot) and §4.8 (agent-path note); `04` §1 (agent tools: `dispute_candidates`, the `claim` step, reason codes, `agent_plan_steps`), §3 (selection gate at the agent dispute pause), §5 (`tools.yaml` v5). | A10. 06 §7. S2 D22. |
| D23 | **Not in this card:** the SSE replay and reload behaviour of an open list (S1 follow-up) and `actions_taken[].at` (S2 follow-up). "Same fields as today" is met with `at` unchanged. | A13. |
| D24 | **Cut order** if the 18:00 freeze is at risk (see "Cut order"). **No cut was taken** (H2): the refused-block branch and the multi-pick list were built in full. | A15. H2. |

## Contracts (delta only)

Everything not listed is as in `04` §1, §3, §4, §5 and the S1 and S2 specs' Contracts.

**`policies/tools.yaml` → version 5** (`04` §5):

```yaml
version: 5
tools:
  disputes.create_claim: {requires_confirmation: true, step_up: never, allowed_intents: [unrecognized_charge], preconditions: {tx_owned: true, answers_complete: true}}
  # every other entry unchanged
```

`Preconditions` (`domains/policy/tools_policy.py`) gains `tx_owned: bool | None = None` and `answers_complete: bool | None = None`. `tx_owned`: D8. `answers_complete`: D9, read from `policies/disputes.yaml` through `DisputesPolicy` (`triggers_compromise`, `possession_question`, `questions`); no threshold or question id is written in Python or in the prompt. The question ids reach Cardy only through text that code builds from `DisputesPolicy`: the `missing_answer:<id>` result and the `propose_plan` tool description.

**Read tool** (`agent/reads.py`, `04` §1 agent tools table):

| Tool | Arguments | Result to the agent |
|---|---|---|
| `dispute_candidates` | `card: str` (a card reference of this turn) | The candidate charges as `t` references in a data fence, or "no candidate transactions". Side effects in the graph update: `ui.transaction_list {options, multi: true}`, `dispute`, `selected_card_id`, and the pick pause below. `fraud_score` is stored in `dispute.fraud_scores` and is not a fact. |

**`propose_plan`** (`agent/plan.py`):

```python
class ProposedStep(BaseModel):
    action: Literal["lock", "block", "unlock", "replace", "claim"]
    card: str | None = None                      # required for every action but "claim"; rejected on "claim"
    address: Literal["on_file", "new"] | None = None
    charges: list[str] | None = None             # "claim" only, min 1: t references of this turn
    answers: dict[str, Literal["yes", "no"]] | None = None   # "claim" only: question id -> answer
_TOOL_BY_ACTION |= {"claim": "disputes.create_claim"}
```

Tool result for a claim proposal: `accepted` | `accepted (block_added)` | `rejected (claim: <code>)`. New codes: `claim_alone` (every step of a mixed proposal), `not_picked`, `missing_answer:<question id>`; `unknown_reference` and `tool_not_allowed` (S1: `issue_plan` raised `PolicyDenied`) are reused. Check order: `customer_not_active` handoff (S2 D5) → `claim_alone` → `unknown_reference` → `not_picked` → D9. The result never carries a fraud score, a flag, the block reason or the token.

**Graph state** (`state.py`, checkpointed):

```python
class AgentPlanStep(TypedDict):
    action: Literal["lock", "block", "unlock", "replace", "claim"]
    card_id: str                      # for "claim": dispute.card_id
    address_ref: NotRequired[str]
```

- `state.dispute` (`DisputeState`, unchanged shape) is reused on the agent path: `card_id`, `offered_tx_ids`, `fraud_scores`, `picked_tx_ids`, `answers` (D9 strings), `compromise`, `block_refused`; `question_index` stays 0. The claim's `tx_ids`, `answers` and flags are read from `dispute` and `priority_flags` when the calls are built at Acepto, as the flow does.
- In a plan that holds a `claim` step, the `block` step's reason is `disputes.yaml compromise.block_reason`; in every other plan it stays `lost_or_stolen` (S1 D8). The reason is not stored in `agent_plan_steps`.
- New `pending` value: `{"flow": "agent", "node": "dispute_pick", "awaiting_slot": "transactions"}`.
- `AgentTurn.awaiting_slot` (`agent/schema.py`): `Literal["card_hint", "block_kind", "criterion", "dispute_question"] | None`.

**Selection gate** (`runner.checkpointed_offer`, `04` §3): at `pending.flow == "agent"` and `pending.node == "dispute_pick"` the offer is `dispute.offered_tx_ids` with `multi = True`; every other agent pause keeps `tx_offer` with `multi = False`. `_routes_to_agent` already takes a pick at an agent `transactions` pause. `post_message` is unchanged.

**Turn events** (`agent/node.py`, code-written, S1 D21):
- Pick at the dispute pause: "the customer picked these charges on the list", one line per `t` reference with its fenced facts (D4).
- Header while a dispute with picks is open: the picked charges as `t` references (D5).
- Confirmed single-charge claim (D14 e): the `claim` step as verified, with a fact `case_id` (source `disputes.create_claim`) that Cardy can only reference; it is registered on the step's card reference, next to `card_mask`, as `tracking_id` is. `nodes/compose._format_fact` formats `case_id` as a plain string, as it does `tracking_id` (S2 D23, 06 R4).

**Prompt and playbook:** `backend/app/domains/conversation/prompts/agent@v3.md` (new; `agent@v2.md` stays), `_PROMPT = PromptRef("agent", 3)`. `policies/playbooks.yaml` `unrecognized_charge`: identify the card; call `dispute_candidates` and ask the customer to pick on the list; propose the claim with the picked references; when the result names a missing answer, ask that question and propose again; never promise a refund or an outcome.

**Templates:** no new key. D14 and D15 reuse `dispute_claim_opened`, `dispute_claim_opened_single`, `dispute_block_refused_offer_claim`, `dispute_handoff_no_claim`, `dispute_open_question_card_active`, `dispute_open_question_claim_refused`, `priority_flag_*`.

**Frontend:** no change expected. `ui.transaction_list` with `multi: true`, the `accept_decline` card and the handoff banner already render.

## Touch map

- `policies/tools.yaml` (v5), `policies/playbooks.yaml` (one entry), `backend/app/domains/conversation/prompts/agent@v3.md` (new).
- `backend/app/domains/policy/tools_policy.py`: two `Preconditions` fields.
- `backend/app/domains/conversation/agent/`: `reads.py` (`dispute_candidates`), `plan.py` (`ProposedStep`, claim branch of the check, `_TOOL_BY_ACTION`, segments for a claim plan, `PlanBox.set(extra=)` to carry `dispute` and `priority_flags` with the plan, D10), a new `dispute.py` for the claim check, plan build, Acepto and No acepto outcomes (no LLM import, R6), `confirm.py` (`agent_plan` sends a plan with a `claim` step to `dispute.py`; `count_open_plan_turn` clears `dispute` when its handoff ends a claim plan, D5), `node.py` (pick event at the dispute pause, header references, `dispute` lifetime, `_plan_event` for a claim, prompt version, the cancel of an open plan's token when a list replaces its confirm pause, H4), `schema.py` (`dispute_question`).
- `backend/app/domains/conversation/state.py` (`AgentPlanStep`), `runner.py` (`checkpointed_offer`), `nodes/compose.py` (`case_id`).
- Tests: `backend/tests/unit/test_agent_dispute.py` (new); `backend/tests/unit/test_agent_plan_check.py` (one stand-in, success criterion 1).
- Docs: `docs/solution-docs/decision-log.md` (ADR-035 S3 line), `02-conversation-design.md` §3, §4.8, `04-contracts.md` §1, §3, §5.
- **Not touched:** anything under `backend/app/domains/conversation/flows/`, `nodes/handoff.py`, `nodes/handoff_summary.py`, `tools/executor.py`, `api/v1/conversations.py`, `policies/disputes.yaml`, `policies/escalation.yaml`, `templates.py`, `eval/`.

## Test list

All in `backend/tests/unit/test_agent_dispute.py`, with `ScriptedLLM` and the fake bank; fixtures as `test_dispute_flows.py` uses (two low-score charges and one with fraud score 45). Each task runs only its own tests; the full suite runs once per card.

| # | Test | Proves |
|---|---|---|
| 1 | `test_r1_foreign_or_unpicked_charge_refused` | 06 R1, "Done when" 2, D4, D8: (a) a `selection` holding another customer's transaction id at the agent dispute pause gets `409 selection_invalid` and no turn runs; (b) a `claim` whose `charges` holds a raw foreign id is `rejected (claim: unknown_reference)`; (c) a `claim` naming a charge of this customer that was not picked is `rejected (claim: not_picked)`. In (b) and (c) no token is issued, no `confirmation_issued` is recorded and no write tool ran. |
| 2 | `test_r8_claim_gated_by_policy_preconditions` | 06 R8, "Done when" 2, D9, D11, D12: one low-score pick, `answers` empty → `missing_answer:card_in_possession`; with possession `yes` only → `missing_answer:contacted_merchant`; no token either time. With the card already blocked and the score-45 charge picked, the accepted plan has one `disputes.create_claim` step and no block. `issue_plan([create_claim], intent=None)` under a tools policy without the `preconditions` block raises `PolicyDenied`. |
| 3 | `test_r2_refused_block_reissues_claim_only` | 06 R2, D15: No acepto on the two-step plan cancels that token, runs no write and no LLM call, and the reply is `dispute_block_refused_offer_claim` with a new token for one `create_claim` step; a second No acepto hands off to Fraudes with no claim, both open questions and zero writes. Cut with the branch (Cut order 1). |
| 4 | `test_single_charge_claim[es, pt]` | "Done when" 1, D3–D6, D13, D14 (e), 06 R3, R4: request → `dispute_candidates` → a pick of one low-score charge → the two answers → an `accept_decline` card with one `create_claim` step → Acepto → one `readback` → Cardy's result; the case id reaches the reply only through `fact_values`; segment `unrecognized_charge` `resolved`, `path: "agent"`; no handoff. |
| 5 | `test_compromise_block_and_claim[es, pt]` | "Done when" 1, D9, D10, D14 (a): ES picks two charges (count rule), PT picks the score-45 charge; the tool result is `accepted (block_added)` with no question asked; the card shows `cards.block_card` then `disputes.create_claim`; Acepto → two `readback`s; the reply is `dispute_claim_opened` then `handoff_transfer`; the handoff is asserted as `reply_sent.route == "handoff"` and exactly one packet created; no LLM call wrote the result. |
| 6 | `test_handoff_packet_same_as_flow` | "Done when" 3, D17: the same compromise case run with the flag off (the flow) and with the flag on gives packets that are equal on the fields named after the colon. Left out: `handoff_id`, `conversation_id`, `created_at`, `actions_taken[].at`, audit ids and sources, `request`, `case_summary`, `friction`, `history`, and `language`, `sentiment`, `policy_version` (the unedited `nodes/handoff.py` sets these three from the session and state on both paths; `sentiment` is the literal `None`). Case ids are random per run, so each is normalised to `CLM-*` before comparing. Compared: `reason`, `queue`, `priority`, `evidence` (refs and fraud scores), `verified_facts` names and values, `actions_taken` tools and `case_ids`, `open_questions`, `escalation_rules_hit`, `routing`, `risk.priority_flags`, `focus_card`. |
| 7 | `test_r2_new_list_cancels_open_claim_token` | 06 R2, H4, D5: with a claim plan open, a typed turn in which a `dispute_candidates` list replaces the confirm pause cancels the open token; no write ran. The `search_transactions` list goes through the same merge point and has no test of its own. |

Reused, must stay green: `test_agent_confirmation.py` (R2 button only, R3 claims check), `test_agent_reply_check.py` (R4), `test_r6_no_write_tools_in_llm_nodes.py` (R6: the scan covers `agent/dispute.py`), `test_agent_plan_check.py` (R1 for card references), `test_policy_registry.py` (v5 loads). Flag-off proof: `test_dispute_flows.py` and `test_selection_gate.py` pass unchanged.

## Cut order

**Outcome: no cut was taken (H2).** Both items below were built in full; the fallbacks are kept as the record of what was offered.

For the planner to mark the cut line. Never cut: tests 1 and 2 (R1, R8 refusals), tests 4 and 5 (ES and PT happy paths), test 6 (packet parity).

1. **First: the refused-block branch** (D15 falls back to Q3 option c). No acepto on the two-step plan cancels it and hands off to Fraudes at once with no claim and the open question `dispute_open_question_card_active`. The claim-only offer and its two outcomes (D14 c, the second No acepto) are not built. Test 3 then asserts only: token cancelled, zero writes, Fraudes handoff.
2. **Second: the multi-pick list** (D3 and D4 fall back to Q2 option b). The list stays single-pick, so the `checkpointed_offer` branch and the multi-id pick event are not built, and compromise rests on the fraud score and the possession answer. Test 5 ES then reaches compromise through a "no" to possession instead of two picks.

## Boundaries

- **Always:** resolve charges only from this turn's references and the picked set in state; take the compromise thresholds, the question ids, the block reason, the queues and the priority thresholds from `policies/*.yaml` through the existing policy models; build flags, evidence, masks and the case id in code; keep fraud scores, flags, the block reason and the token out of every prompt, tool result and turn event; issue no token for a rejected proposal; bump the prompt to `agent@v3`; update `02`, `04` and the decision log in the same PR.
- **Ask first:** any change under `flows/` (import the helpers instead), to `nodes/handoff.py`, to `tools/executor.py` or to the frontend; any new or changed text in `templates.py`; any new handoff reason; any dispute behaviour not in D1–D20; crossing a line of the Cut order.
- **Never:** let Cardy name a transaction id, a block, a reason, a queue or a flag; let typed text set or change the picked charges; confirm a claim plan from typed text; let Cardy write on a turn that hands off or where a step failed; drop a picked charge from the claim or from the compromise count; put a threshold, a question id list or a queue name in `agent@v3.md`; give the LLM module an executing tool; fold the SSE replay or the `actions_taken[].at` follow-ups into this card; edit `eval/scenarios/heldout/`; commit secrets, `data/`, `.env` or the dictionary PDF.

## Success criteria

1. **Flag off unchanged.** The local `.env` now sets `AGENT_ENABLED=true`, so both commands of this criterion run with `AGENT_ENABLED=false` in front (without it the flag-off pytest below fails, 9 failed; with it, 9 passed). `make check` is green with the flag off. `git diff --stat origin/develop -- backend/app/domains/conversation/flows backend/app/domains/conversation/nodes/handoff.py backend/app/domains/conversation/templates.py policies/disputes.yaml policies/escalation.yaml eval` prints nothing. `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_dispute_flows.py tests/unit/test_selection_gate.py -q` passes. The only existing test file changed is `tests/unit/test_agent_plan_check.py`: in `test_precondition_rejects_blocked_card` the tool without a `preconditions` block is no longer `disputes.create_claim` (it has one now) but `cards.get_block_origin` or a policy loaded from a test path, still `pytest.raises(PolicyDenied)`.
2. **Refusals (Done when 2; 06 R1, R8, R2).** `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_dispute.py -q -k "r1 or r8 or r2"` reports 4 passed (Test list rows 1, 2, 3 and 7).
3. **ES and PT (Done when 1, backend half).** `uv run pytest tests/unit/test_agent_dispute.py -q -k "single_charge or compromise"` reports 4 passed.
4. **Packet (Done when 3).** `uv run pytest tests/unit/test_agent_dispute.py -q -k packet` reports 1 passed.
5. **Policy and prompt.** `grep -n 'version: 5' policies/tools.yaml` matches and `grep -n 'disputes.create_claim.*preconditions: {tx_owned: true, answers_complete: true}' policies/tools.yaml` matches; `policies/playbooks.yaml` has `unrecognized_charge:`; `backend/app/domains/conversation/prompts/agent@v3.md` exists, `grep -n -i 'fraudes\|suspected_fraud\|priority_claim\|min_picked\|fraud_score\|card_in_possession\|contacted_merchant' backend/app/domains/conversation/prompts/agent@v3.md` prints nothing, and `grep -n 'PromptRef("agent", 3)' backend/app/domains/conversation/agent/node.py` matches.
6. **Browser, flag on (Done when 1).** With `AGENT_ENABLED=true` in the local `.env` (not committed) and the backend restarted, in ES and in PT with a demo customer whose card has two or more charges in `candidate_statuses`: (a) "no reconozco un cargo" → a multi-pick list; pick one low-score charge → Cardy asks about the card and about the merchant → an "Acepto / No acepto" card with the claim → Acepto → a reply with a case id, no handoff; (b) pick two charges → a card with the block and the claim and no question → Acepto → the block-and-claim text, the transfer text and the banner with the case ids; `/staff` lists the handoff in `fraudes`, priority high, with the picked transactions as evidence; (c) repeat (b) pressing No acepto: the claim-only card appears with no bot question in between (applies: no cut was taken, H2).
7. **Docs.** `decision-log.md` ADR-035 has an S3 amendment line; `04` §1, §3, §5 and `02` §3, §4.8 carry the lines named in D22.

## Amendments (end of card)

"Hn" is a decision the human took after the spec was approved.

- **H1.** `reply_sent.route` stays `card_block` on the re-issued claim-only plan turn and on a stale click at a claim plan (D18). It was the planner's open question.
- **H2.** No cut was taken (D24, Cut order).
- **H3.** The five derived readings were confirmed at the gate: Open question 1 (a)–(d) and Open question 2 (S1 D17 kept as written). Both open questions are closed.
- **H4** (verify gate). When a list replaces the confirm pause of an open plan, code cancels that plan's token (D5, Test list row 7, task T11). It was the safety verifier's finding: the old token stayed live, failing closed. The human asked for a re-verify before commit. As built: `agent/node.py` calls the existing `cancel_open_plan` (`agent/plan.py`, unedited) when a plan was open, no plan was opened this turn, the turn is not the post-OTP one, and a list read set a new pause. Two as-built choices of the implementer, **not separately decided by the human**: the same turn sets `dispute` to `None` (a new `dispute_candidates` result overrides it), and `non_answer_failures` is left unchanged.
- **H5** (verify gate). An empty or off-list pick at the dispute pause is answered with `nothing_pending` and dropped whole (D4). The flow's answer (keep the offered subset, `pending_reminder` for none) was the option not taken.
- Corrections from the repo, no decision involved: the source of the 10-row cap (D3); the `AGENT_ENABLED=false` prefix (Success criteria 1 and 2); the wording of D1, D12, D15, D16, the `propose_plan` result codes, the `case_id` turn event, the Touch map and Test list rows 5 and 6, each made to match the code under the decision it already cites.

## Open questions

Closed (H3). Kept as the record of what was confirmed.

1. **Derived readings, confirmed by the human at spec approval** (each follows from an answer, none was asked word for word): (a) No acepto on the D11 claim-only plan hands off to Fraudes with no claim (D15, from Q3 a and Q4 a); (b) the claim must cover exactly the picked set, else `not_picked` (D8, from Q2 a and card item 2); (c) only the answers the rule read are recorded on the claim (D9, from "as today"); (d) Cardy words the plan sentence and learns of the added block through `accepted (block_added)` (D10, from S1 D12).
2. **Asked-turn count on the single-charge path.** S1 D17 (a) hands off on the third `asked` turn in a row for one request type. The two dispute questions use two of them, so one unclear answer ends in a `clarification_exhausted` handoff. This spec keeps S1 D17 as written (D19). Confirmed by the human at approval (H3).

## Follow-ups (not in this card)

- A request for a person in the middle of an agent-path dispute goes to Atención, not Fraudes, because `human_request_queues.by_flow` keys on the paused pipeline flow (Q6 a). A later card owns it.
- The SSE stream has no replay, and a `/home` reload leaves an open list or offer paused (recorded by S1). It now also covers the dispute list.
- `actions_taken[].at` holds the handoff time, not the action time (recorded by S2, `nodes/handoff.py`).
