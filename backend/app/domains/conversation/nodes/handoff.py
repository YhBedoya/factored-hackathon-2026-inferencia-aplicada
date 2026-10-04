"""Code-only handoff node (D9, D10, D12): build the packet, create it, go human.

Runs after `handoff_summary` (the LLM node that drafts `request`); this module
imports no LLM client so R6 holds: it reads tool output and the only
write it can make is `handoff_tools.create`. The packet is assembled from
verified `ActionResult`s and code-built keys only, never a transcript (R3, R5).
`customer_id` is not in the packet: `HandoffTools` is bound to the session (R1).
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue

from app.core.actions import ActionResult
from app.domains.audit.schemas import Recorder
from app.domains.conversation.fact_values import record
from app.domains.conversation.graph import GraphState
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools import ToolContext
from app.domains.conversation.tools.handoff import HandoffTools
from app.domains.conversation.ui import HandoffBannerEvent, HandoffBannerPayload
from app.domains.handoff.schemas import (
    ActionTaken,
    CaseSummary,
    CustomerHistory,
    Friction,
    HandoffPacket,
    HandoffReason,
    RiskSignals,
    Routing,
    VerifiedFact,
    reference_for,
)
from app.domains.localization.format import Language, kind_label, mask_card, queue_label
from app.domains.policy.escalation import (
    legal_hit,
    load_escalation_policy,
    resolve_escalation,
    rule,
)

__all__ = ["handoff"]

# Tool -> fact key. `disputes.*` is matched by prefix in `_fact_name`.
_FACTS: dict[str, str] = {
    "cards.lock_card": "card_locked",
    "cards.unlock_card": "card_unlocked",
    "cards.block_card": "card_status",
    "cards.order_replacement": "replacement_ordered",
}

_OPEN_QUESTIONS: dict[str, dict[str, str]] = {
    "card_in_possession": {
        "es": "¿Tiene la tarjeta en su poder?",
        "pt": "O cliente está com o cartão em mãos?",
    },
}


def _fact_name(tool: str) -> str | None:
    if tool.startswith("disputes."):
        return "claim_filed"
    return _FACTS.get(tool)


def _json(value: object) -> JsonValue:
    """Readback values may be Decimal/date; the packet stores plain JSON."""
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)


def _fact_value(result: ActionResult) -> JsonValue:
    if result.case_ids is not None:
        return list(result.case_ids)
    if result.tracking_id is not None:
        return result.tracking_id
    status = result.readback.get("status")
    return _json(status) if status is not None else True


async def _focus_card(
    state: GraphState, configurable: dict[str, Any], language: Language
) -> str | None:
    """ "Crédito •••• 9118" for the card the conversation was about (D5), built in
    code (R4). `None` when there is no card, no tools or the read fails: the packet
    never waits on it."""
    card_id = state.get("selected_card_id")
    bank_tools = configurable.get("bank_tools")
    if card_id is None or bank_tools is None:
        return None
    try:
        card = await bank_tools.get_card_details(card_id)
    except Exception:
        return None
    return f"{kind_label(card.kind, language)} {mask_card(card.last4)}"


async def _history(handoff_tools: HandoffTools, days: int) -> CustomerHistory | None:
    """A failed history read never blocks the handoff (D6, R11)."""
    try:
        return await handoff_tools.history(days)
    except Exception:
        return None


async def handoff(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Create the handoff, flip to human mode and emit the banner (D12)."""
    configurable = config["configurable"]
    session: ToolContext = configurable["session"]
    handoff_tools: HandoffTools = configurable["handoff_tools"]
    audit: Recorder = configurable["audit"]
    language = state.get("language", "es")
    policy = load_escalation_policy()
    pending = state.get("pending")
    nlu = state.get("nlu")

    resolution = resolve_escalation(
        policy,
        reason=state.get("escalation_reason"),
        queue=state.get("handoff_queue"),
        pending_flow=pending["flow"] if pending else None,
        intents=list(nlu.intents) if nlu is not None else [],
        text=state.get("user_text", ""),
    )
    if resolution is None:
        raise ValueError("handoff reached without an escalation reason")
    reason = cast(HandoffReason, resolution.reason)
    now = datetime.now(UTC)
    candidate_id = uuid4()

    facts: list[VerifiedFact] = []
    taken: list[ActionTaken] = []
    for result in state.get("actions", []):
        if not result.verified:
            continue
        name = _fact_name(result.tool)
        source = (
            f"audit:{result.audit_event_id}"
            if result.audit_event_id is not None
            else f"{result.tool} read-back"
        )
        if name is not None:
            facts.append(VerifiedFact(fact=name, value=_fact_value(result), source=source))
        taken.append(
            ActionTaken(
                tool=result.tool,
                result="applied",
                verified=True,
                audit_event_id=str(result.audit_event_id) if result.audit_event_id else None,
                at=now,
                tracking_id=result.tracking_id,
                case_ids=result.case_ids,
            )
        )
    # Claims the bot opened in this conversation (the fraud path, D4-B D16) are
    # shown on the banner.
    case_ids = [case_id for action in taken for case_id in action.case_ids or []]

    # The rule's questions, then any a flow filled in code (D4-B D10).
    questions = [
        _OPEN_QUESTIONS[key][language]
        for key in rule(policy, reason).open_questions
        if key in _OPEN_QUESTIONS
    ] + list(state.get("handoff_open_questions", []))
    # B2: a flag that did not itself pick the reason (Fraudes via compromise)
    # is still recorded as a rule hit.
    hit: list[HandoffReason] = [reason]
    if state.get("priority_flags") and reason != "priority_claim":
        hit.append("priority_claim")
    summary = state.get("handoff_case_summary")
    friction = state.get("friction") or {}
    packet = HandoffPacket(
        handoff_id=candidate_id,
        conversation_id=session.conversation_id,
        queue=resolution.queue,
        priority=resolution.priority,
        reason=reason,
        language=language,
        sentiment=None,
        request=state.get("handoff_request", ""),
        verified_facts=facts,
        actions_taken=taken,
        evidence=list(state.get("handoff_evidence", [])),
        open_questions=questions,
        escalation_rules_hit=hit,
        policy_version=session.policy_version,
        created_at=now,
        case_summary=CaseSummary.model_validate(summary) if summary else None,
        focus_card=await _focus_card(state, configurable, language),
        routing=Routing(
            reason=reason, queue=resolution.queue, branch=resolution.branch, flow=resolution.flow
        ),
        # Snapshotted from the incoming state: the return below resets the flags.
        risk=RiskSignals(
            priority_flags=list(state.get("priority_flags", [])),
            legal_keyword=legal_hit(state.get("user_text", ""), policy)
            or reason == "legal_regulator",
            unauthorized_attempts=state.get("unauthorized_attempts", 0),
        ),
        history=await _history(handoff_tools, policy.handoff_packet.history_days),
        friction=Friction(
            clarifications=friction.get("clarifications", 0),
            abstentions=friction.get("abstentions", 0),
            non_answers=friction.get("non_answers", 0),
        ),
    )
    # The persisted id wins: an already-open handoff keeps its own reference (R3).
    handoff_id = await handoff_tools.create(packet)
    await audit.record(
        "handoff",
        {
            "action": "created" if handoff_id == candidate_id else "attached",
            "handoff_id": str(handoff_id),
            "queue": resolution.queue,
            "reason": reason,
        },
    )

    reference = reference_for(handoff_id)
    label = queue_label(resolution.queue, language)
    record(label, reference)
    text = get_template("handoff_transfer", language).format(queue_label=label, reference=reference)
    return {
        "mode": "human",
        "handoff_id": str(handoff_id),
        "handoff_queue": resolution.queue,
        "escalation_reason": reason,
        "pending": None,
        "confirmation_token_id": None,
        "intent_queue": [],
        "handoff_evidence": [],
        "handoff_open_questions": [],
        "priority_flags": [],
        "ui": [
            HandoffBannerEvent(
                kind="handoff_banner",
                payload=HandoffBannerPayload(
                    handoff_id=str(handoff_id),
                    reference=reference,
                    queue=resolution.queue,
                    queue_label=label,
                    case_ids=case_ids,
                ),
            )
        ],
        "segments": [text],
    }
