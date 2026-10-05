"""The agent's claim proposal, built and executed by code (S3, spec D6-D18).

Cardy only *proposes* a `claim` step (the picked charges and the dispute answers). Code
checks it (`check_claim`), applies the compromise rule of `policies/disputes.yaml` (R8),
builds the one-token plan (`build_claim_plan`), and on the buttons runs it
(`accept_claim_plan`) or cancels it (`decline_claim_plan`). The flow's helpers are
imported, never copied (D1), so the agent path and the flow write the same claim, the same
texts and the same handoff keys. This module returns plain data, imports no LLM module
(R6) and does not import `agent/plan.py`: `plan.py` and `confirm.py` import it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast

from langchain_core.runnables import RunnableConfig

from app.core.actions import ActionResult
from app.core.errors import PolicyDenied, ToolUnavailable
from app.domains.cards.schemas import BlockReason
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.flows.actions import execute_plan, fill
from app.domains.conversation.flows.unrecognized_charge import (
    _claim_reply_text,
    _compromise_success,
    _flag_lines,
    _fraud_handoff,
    _handoff_no_claim,
    _priority_flags,
    _replace,
    _single_charge_success,
)
from app.domains.conversation.graph import GraphState
from app.domains.conversation.state import (
    AgentPlanStep,
    DisputeState,
    Fact,
    IntentSegment,
    SegmentStatus,
)
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.ui import ConfirmEvent, ConfirmPayload, ConfirmStepView
from app.domains.localization import mask_card
from app.domains.policy.confirmation import PlanStep, ToolArg
from app.domains.policy.disputes import load_disputes_policy
from app.domains.policy.registry import get_policies

__all__ = [
    "accept_claim_plan",
    "build_claim_plan",
    "check_claim",
    "claim_segments",
    "current_dispute",
    "decline_claim_plan",
    "has_claim",
]

_BLOCK_TOOL = "cards.block_card"
_CLAIM_TOOL = "disputes.create_claim"
_INTENT = "unrecognized_charge"

_CLEARED: dict[str, Any] = {
    "pending": None,
    "confirmation_token_id": None,
    "card_request_kind": None,
    "profile_changed_fields": None,
    "agent_plan_steps": None,
}


class _Box(Protocol):
    """The part of `plan.PlanBox` this module needs (plan.py is not imported here)."""

    def set(
        self,
        token_id: str,
        event: ConfirmEvent,
        steps: list[AgentPlanStep],
        extra: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class _Reading:
    """What D9 read: whether this is a compromise, the answers it read, the first missing one."""

    compromise: bool
    answers: list[str]
    missing: str | None = None


def has_claim(steps: Sequence[AgentPlanStep]) -> bool:
    return any(step["action"] == "claim" for step in steps)


def claim_segments(status: SegmentStatus) -> list[IntentSegment]:
    """The one `unrecognized_charge` segment of a claim plan, whatever steps it holds (D18)."""
    return [{"intent": _INTENT, "route": _INTENT, "status": status}]


def current_dispute(state: GraphState, refs: TurnRefs) -> DisputeState | None:
    """The dispute in effect this turn: a `dispute_candidates` call of this turn wins over the
    checkpointed one (plan I3)."""
    if "dispute" in refs.graph_update:
        return cast("DisputeState | None", refs.graph_update["dispute"])
    return state.get("dispute")


def _max_score(dispute: DisputeState) -> Decimal | None:
    scores = [
        score
        for tx_id in dispute["picked_tx_ids"]
        if (score := dispute["fraud_scores"].get(tx_id)) is not None
    ]
    return max(scores) if scores else None


def _read_answers(dispute: DisputeState, answers: Mapping[str, str] | None) -> _Reading:
    """D9, in order: the count/score rule first (no answer read); then the possession
    question; then, on "yes", every question of the policy."""
    policy = load_disputes_policy()
    if policy.triggers_compromise(len(dispute["picked_tx_ids"]), _max_score(dispute)):
        return _Reading(compromise=True, answers=[])
    given = answers or {}
    possession = policy.possession_question
    first = given.get(possession)
    if first is None:
        return _Reading(compromise=False, answers=[], missing=possession)
    if first == "no":
        return _Reading(compromise=True, answers=[f"{possession}={first}"])
    ids = [possession, *(q for q in policy.questions if q != possession)]
    for question_id in ids:
        if question_id not in given:
            return _Reading(compromise=False, answers=[], missing=question_id)
    return _Reading(compromise=False, answers=[f"{q}={given[q]}" for q in ids])


def check_claim(
    actions: Sequence[str],
    charges: list[str] | None,
    answers: Mapping[str, str] | None,
    refs: TurnRefs,
    state: GraphState,
) -> list[str | None]:
    """One reason code or `None` per step of a proposal that holds a `claim` step, in the
    spec's order: `claim_alone`, `unknown_reference`, `not_picked`, D9. `charges` and
    `answers` are the claim step's."""
    if len(actions) > 1:
        return ["claim_alone"] * len(actions)
    ids = [refs.tx_id(handle) for handle in charges or []]
    if not ids or any(tx_id is None for tx_id in ids):
        return ["unknown_reference"]
    dispute = current_dispute(state, refs)
    if dispute is None or not dispute["picked_tx_ids"]:
        return ["not_picked"]
    if set(ids) != set(dispute["picked_tx_ids"]):
        return ["not_picked"]
    missing = _read_answers(dispute, answers).missing
    return [f"missing_answer:{missing}" if missing is not None else None]


async def build_claim_plan(
    state: GraphState,
    config: RunnableConfig,
    refs: TurnRefs,
    box: _Box,
    answers: Mapping[str, str] | None,
) -> str:
    """The plan for an accepted claim proposal (D10, D11, D13), after the open plan was
    cancelled. Code decides the block step, the flags and every argument; the model's
    answers are only read through D9. `ToolUnavailable` propagates to the node."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    current = current_dispute(state, refs)
    assert current is not None  # check_claim accepted it
    reading = _read_answers(current, answers)
    dispute = cast(
        DisputeState, {**current, "answers": reading.answers, "compromise": reading.compromise}
    )
    flags = await _priority_flags(bank_tools, dispute)
    details = await bank_tools.get_card_details(dispute["card_id"])

    block_policy = get_policies().tools.tools.get(_BLOCK_TOOL)
    pre = block_policy.preconditions if block_policy is not None else None
    already = pre is not None and details.status in pre.status_not_in
    add_block = reading.compromise and not already

    plan_steps: list[PlanStep] = []
    views: list[ConfirmStepView] = []
    stored: list[AgentPlanStep] = []
    if add_block:
        reason = load_disputes_policy().compromise.block_reason
        plan_steps.append(
            PlanStep(tool=_BLOCK_TOOL, args={"card_id": details.card_id, "reason": reason})
        )
        views.append(
            ConfirmStepView(
                tool=_BLOCK_TOOL,
                summary_key="block_card",
                facts=[
                    Fact(key="card_mask", value=mask_card(details.last4), source=details.source)
                ],
            )
        )
        stored.append({"action": "block", "card_id": dispute["card_id"]})
    claim_args: dict[str, ToolArg] = {
        "tx_ids": list(dispute["picked_tx_ids"]),
        "answers": sorted(dispute["answers"]),
        "priority_flags": flags,
    }
    plan_steps.append(PlanStep(tool=_CLAIM_TOOL, args=claim_args))
    views.append(
        ConfirmStepView(
            tool=_CLAIM_TOOL,
            summary_key="create_claim",
            facts=[
                Fact(key="tx_count", value=len(dispute["picked_tx_ids"]), source="conversation")
            ],
        )
    )
    stored.append({"action": "claim", "card_id": dispute["card_id"]})

    try:
        plan = await write_tools.issue_plan(plan_steps, None)
    except PolicyDenied:
        return "rejected (claim: tool_not_allowed)"
    event = ConfirmEvent(
        kind="confirm",
        payload=ConfirmPayload(token_id=plan.token_id, steps=views, labels="accept_decline"),
    )
    box.set(
        plan.token_id,
        event,
        stored,
        extra={"dispute": dispute, "priority_flags": flags},
    )
    return "accepted (block_added)" if add_block else "accepted"


async def accept_claim_plan(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Acepto on a stored claim plan (D14): calls built from state as the flow does, run
    through `execute_plan` with no LLM call; the result text is code's."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    token_id = state.get("confirmation_token_id")
    steps = state.get("agent_plan_steps") or []
    dispute = state.get("dispute")
    assert token_id is not None
    assert dispute is not None
    with_block = any(step["action"] == "block" for step in steps)
    tx_ids = dispute["picked_tx_ids"]
    answers = sorted(dispute["answers"])
    flags = sorted(state.get("priority_flags", []))

    calls = []
    details = await bank_tools.get_card_details(dispute["card_id"]) if with_block else None
    if with_block:
        block_reason = cast(BlockReason, load_disputes_policy().compromise.block_reason)

        async def block_call() -> ActionResult:
            return await write_tools.block_card(dispute["card_id"], block_reason, token_id)

        calls.append(block_call)

    async def claim_call() -> ActionResult:
        return await write_tools.create_claim(tx_ids, answers, flags, token_id)

    calls.append(claim_call)

    outcome = await execute_plan(state, config, calls)
    if isinstance(outcome, dict):
        # A failed or unverified step cancelled the plan: the flow's handoff update, as is.
        return {
            **outcome,
            **_CLEARED,
            "dispute": None,
            "intent_segments": claim_segments("handoff"),
        }

    claim_result = outcome[-1]
    handoff_segments = claim_segments("handoff")
    if details is not None:
        update = _compromise_success(state, dispute, details, outcome[0], claim_result)
        return {**update, "agent_plan_steps": None, "intent_segments": handoff_segments}
    if dispute["compromise"]:
        # D11: the card was already Blocked or Closed, so the claim stands alone.
        return {
            "actions": outcome,
            **_CLEARED,
            "dispute": None,
            "segments": [_claim_reply_text(state, claim_result)],
            **_fraud_handoff(state, dispute, _card_active_question(state, dispute)),
            "intent_segments": handoff_segments,
        }
    if flags:
        update = _single_charge_success(state, dispute, claim_result)
        return {**update, "agent_plan_steps": None, "intent_segments": handoff_segments}
    done: dict[str, Any] = {**_CLEARED, "actions": outcome, "dispute": None}
    case_ids = claim_result.case_ids or []
    return {
        **done,
        "agent_code_text": _claim_reply_text(state, claim_result),
        "agent_plan_result": {
            "outcome": "confirmed",
            "steps": [
                {
                    "action": "claim",
                    "card_id": dispute["card_id"],
                    "case_id": ", ".join(case_ids),
                }
            ],
        },
        "agent_offer": None,
        "intent_segments": claim_segments("resolved"),
    }


async def decline_claim_plan(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """No acepto on a stored claim plan (D15). The token is cancelled first, always."""
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state.get("language", "es")
    token_id = state.get("confirmation_token_id")
    assert token_id is not None
    await write_tools.cancel_plan(token_id)
    dispute = state.get("dispute")
    steps = state.get("agent_plan_steps") or []
    cleared: dict[str, Any] = {**_CLEARED, "dispute": None}

    if dispute is None or not dispute["compromise"]:
        # Single charge: S1 D15, the plan is cancelled and Cardy asks what to change.
        return {
            **cleared,
            "agent_code_text": get_template("action_cancelled", language),
            "agent_plan_result": {"outcome": "declined", "steps": []},
            "intent_segments": claim_segments("cancelled"),
        }

    if not any(step["action"] == "block" for step in steps) and not dispute["block_refused"]:
        # D11: the card is not active, so the only open question is the refused claim.
        update = _handoff_no_claim(state, dispute)
        update["handoff_open_questions"] = [
            get_template("dispute_open_question_claim_refused", language),
            *_flag_lines(state),
        ]
        return {**update, **cleared, "intent_segments": claim_segments("handoff")}

    if dispute["block_refused"]:
        # D15: the claim-only plan was refused too: Fraudes, no claim, both open questions.
        return {
            **_handoff_no_claim(state, dispute),
            **cleared,
            "intent_segments": claim_segments("handoff"),
        }

    # D15: the two-step plan was refused; the claim alone is offered in the same turn.
    return await _offer_claim_only(state, config, _replace(dispute, block_refused=True), cleared)


def _card_active_question(state: GraphState, dispute: DisputeState) -> list[str]:
    """D14 (c): after a refused block the card is still active, and Fraudes is told."""
    if not dispute["block_refused"]:
        return []
    return [get_template("dispute_open_question_card_active", state.get("language", "es"))]


async def _offer_claim_only(
    state: GraphState, config: RunnableConfig, dispute: DisputeState, cleared: dict[str, Any]
) -> dict[str, Any]:
    """D15: the claim-only plan after a refused block, issued by code with no LLM call."""
    bank_tools: BankReadTools = config["configurable"]["bank_tools"]
    write_tools: ConfirmedWriteTools = config["configurable"]["bank_write_tools"]
    language = state.get("language", "es")
    try:
        flags = await _priority_flags(bank_tools, dispute)
        claim_args: dict[str, ToolArg] = {
            "tx_ids": list(dispute["picked_tx_ids"]),
            "answers": sorted(dispute["answers"]),
            "priority_flags": flags,
        }
        plan = await write_tools.issue_plan([PlanStep(tool=_CLAIM_TOOL, args=claim_args)], None)
    except ToolUnavailable:
        return {**cleared, "escalation_reason": "tool_failure"}
    tx_count = len(dispute["picked_tx_ids"])
    event = ConfirmEvent(
        kind="confirm",
        payload=ConfirmPayload(
            token_id=plan.token_id,
            steps=[
                ConfirmStepView(
                    tool=_CLAIM_TOOL,
                    summary_key="create_claim",
                    facts=[Fact(key="tx_count", value=tx_count, source="conversation")],
                )
            ],
            labels="accept_decline",
        ),
    )
    steps: list[AgentPlanStep] = [{"action": "claim", "card_id": dispute["card_id"]}]
    return {
        "confirmation_token_id": plan.token_id,
        "agent_plan_steps": steps,
        "pending": {"flow": "agent", "node": "confirm", "awaiting_slot": "confirmation"},
        "ui": [event],
        "asked_ui": [event],
        "segments": [
            fill(
                get_template("dispute_block_refused_offer_claim", language),
                tx_count=str(tx_count),
            )
        ],
        "dispute": dispute,
        "priority_flags": flags,
        "intent_segments": [
            {**claim_segments("awaiting")[0], "awaiting_slot": "confirmation"},
        ],
    }
