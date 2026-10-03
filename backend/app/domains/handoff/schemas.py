"""Handoff contracts: the packet, the staff API views and the reference code.

See `docs/specs/d4-a-escalation-handoff-deploy.md` §"Contracts" and
`04-contracts.md` §4. Imports only the stdlib, pydantic and the `Queue`
literal, so `conversation/` (state, tools) can depend on it without pulling in
the repository. Every model is frozen and rejects unknown fields.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domains.localization.format import Queue

__all__ = [
    "ActionTaken",
    "CaseSummary",
    "CustomerHistory",
    "Friction",
    "HandoffDetail",
    "HandoffEvidence",
    "HandoffPacket",
    "HandoffReason",
    "HandoffStatus",
    "HandoffSummary",
    "PastClaim",
    "PastHandoff",
    "Priority",
    "RiskSignals",
    "Routing",
    "TranscriptMessage",
    "VerifiedFact",
    "reference_for",
]

HandoffReason = Literal[
    "human_request",
    "clarification_exhausted",
    "legal_regulator",
    "customer_not_active",
    "bank_side_block",
    "action_unverified",
    "unauthorized_access",
    "suspected_fraud",
    "tool_failure",
    "llm_unavailable",
    "priority_claim",
    "agent_round_cap",
]
Priority = Literal["high", "normal"]
HandoffStatus = Literal["queued", "claimed", "returned"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HandoffEvidence(_Frozen):
    """A piece of evidence a flow attaches to the packet (fraud path)."""

    type: Literal["transaction"]
    ref: str
    fraud_score: Decimal | None


class VerifiedFact(_Frozen):
    """One fact backed by a verified `ActionResult` (R3)."""

    fact: str
    value: JsonValue
    source: str


class ActionTaken(_Frozen):
    """A write the bot already applied and read back before the handoff (R3)."""

    tool: str
    result: Literal["applied"]
    verified: Literal[True]
    audit_event_id: str | None
    at: datetime
    tracking_id: str | None = None
    case_ids: list[str] | None = None


class CaseSummary(_Frozen):
    """LLM-written case summary, placeholders already filled (D4)."""

    asked: str = Field(max_length=280)
    did: str = Field(max_length=280)
    unfinished: str = Field(max_length=280)


class Routing(_Frozen):
    """Why the case landed in this queue (D5)."""

    reason: HandoffReason
    queue: Queue
    # rule queue | queue set by the flow | human_request_queues.by_flow | .default
    branch: Literal["rule", "flow", "by_flow", "default"]
    flow: str | None  # pending flow used for by_flow, else None


class RiskSignals(_Frozen):
    priority_flags: list[str]
    legal_keyword: bool  # legal_hit() on this turn's masked text, or reason == legal_regulator
    unauthorized_attempts: int


class PastHandoff(_Frozen):
    reference: str
    reason: HandoffReason
    queue: Queue
    status: HandoffStatus
    created_at: datetime


class PastClaim(_Frozen):
    claim_id: str
    category: str | None
    status: str | None
    created_at: datetime | None


class CustomerHistory(_Frozen):
    """Earlier handoffs and claims of this customer, each at most 5, newest first."""

    days: int
    handoffs: list[PastHandoff]
    claims: list[PastClaim]


class Friction(_Frozen):
    clarifications: int
    abstentions: int
    non_answers: int


class HandoffPacket(_Frozen):
    """The `04` §4 packet. `request` and `case_summary` are the LLM-written fields."""

    handoff_id: UUID
    conversation_id: UUID
    queue: Queue
    priority: Priority
    reason: HandoffReason
    language: Literal["es", "pt"]
    sentiment: None = None
    request: str = Field(max_length=200)
    verified_facts: list[VerifiedFact]
    actions_taken: list[ActionTaken]
    evidence: list[HandoffEvidence]
    open_questions: list[str]
    escalation_rules_hit: list[HandoffReason]
    policy_version: str
    created_at: datetime
    case_summary: CaseSummary | None = None
    focus_card: str | None = None  # "Crédito •••• 9118", built in code (R4)
    routing: Routing | None = None
    risk: RiskSignals | None = None
    history: CustomerHistory | None = None
    friction: Friction | None = None


class HandoffSummary(_Frozen):
    """A row of the staff inbox; `claimed_by` is the agent's display name."""

    handoff_id: UUID
    reference: str
    conversation_id: UUID
    queue: Queue
    priority: Priority
    reason: HandoffReason
    status: HandoffStatus
    language: Literal["es", "pt"]
    created_at: datetime
    claimed_by: str | None
    request: str
    case_summary: CaseSummary | None
    claimed_at: datetime | None


class HandoffDetail(_Frozen):
    """`GET /staff/handoffs/{id}`: the summary plus the full packet."""

    summary: HandoffSummary
    packet: HandoffPacket


class TranscriptMessage(_Frozen):
    """One message of a claimed conversation's transcript."""

    role: Literal["bot", "customer", "agent", "system"]
    text: str
    created_at: datetime


def reference_for(handoff_id: UUID) -> str:
    """`HO-` plus the first 8 hex digits of the id, uppercased (built in code)."""
    return "HO-" + handoff_id.hex[:8].upper()
