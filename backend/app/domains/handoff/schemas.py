"""The handoff packet contract and the staff-facing shapes built on it.

See `docs/solution-docs/04-contracts.md` §4 and D4-B D1. `HandoffDraft` is
everything a flow assembles in code before the packet exists (R4: money,
dates and case ids are already formatted by the time they land in
`verified_facts`/`evidence`); the bound `HandoffPort` completes it into a
`HandoffPacket` with the fields only the port can set (`handoff_id`,
`request`, `sentiment`, `policy_version`, `created_at`). `request` is the
only LLM-written field in the whole packet, and it never reaches this
module: the port builds it. `HandoffSummary`/`HandoffDetail` are what the
`/staff/*` routes return (D2); `AgentMessageRequest`/`AgentMessageResponse`
are the agent-to-customer chat message shape.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.localization.format import Queue

__all__ = [
    "ActionTaken",
    "AgentMessageRequest",
    "AgentMessageResponse",
    "Evidence",
    "HandoffDetail",
    "HandoffDraft",
    "HandoffListResponse",
    "HandoffPacket",
    "HandoffPort",
    "HandoffRef",
    "HandoffStatus",
    "HandoffSummary",
    "Priority",
    "VerifiedFact",
]

Priority = Literal["normal", "high"]
HandoffStatus = Literal["queued", "claimed", "returned", "closed"]
"""`03` §6."""


class VerifiedFact(BaseModel):
    """One fact the packet states as already checked, with where it came from."""

    model_config = ConfigDict(frozen=True)

    fact: str
    value: str | list[str]
    source: str


class ActionTaken(BaseModel):
    """One confirmed write already applied before the handoff (D9, D10)."""

    model_config = ConfigDict(frozen=True)

    tool: str
    result: Literal["applied"]
    verified: bool
    audit_event_id: UUID | None
    at: datetime | None
    case_ids: list[str] | None = None
    """Set only for `disputes.create_claim` (D16)."""


class Evidence(BaseModel):
    """One transaction backing the handoff (D13)."""

    model_config = ConfigDict(frozen=True)

    type: Literal["transaction"]
    ref: str
    fraud_score: Decimal | None


class HandoffDraft(BaseModel):
    """Everything code assembles before the port completes the packet.

    `open_questions` is already code-filled ES/PT text in `language` (D10);
    nothing here is LLM-written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue: Queue
    priority: Priority
    reason: str
    language: Literal["es", "pt"]
    verified_facts: list[VerifiedFact]
    actions_taken: list[ActionTaken]
    evidence: list[Evidence]
    open_questions: list[str]
    escalation_rules_hit: list[str]


class HandoffPacket(HandoffDraft):
    """The draft plus what the bound `HandoffPort` fills in (`04` §4, exactly)."""

    handoff_id: UUID
    conversation_id: UUID
    request: str
    """The only LLM-written field, masked and length-capped. A's port builds it."""
    sentiment: Literal["negative", "neutral", "positive"] | None
    """How it is set is A's decision; `InMemoryHandoffPort` always sets `None`."""
    policy_version: str
    created_at: datetime


class HandoffRef(BaseModel):
    """What `HandoffPort.create` returns to the flow that requested it."""

    model_config = ConfigDict(frozen=True)

    handoff_id: UUID
    queue: Queue
    created_at: datetime


class HandoffPort(Protocol):
    """Bound per turn to `(conversation_id, policy_version)` (D1, D19).

    `config["configurable"]["handoff"]` carries the bound instance; an LLM
    node never sees this key (R6).
    """

    async def create(self, draft: HandoffDraft) -> HandoffRef: ...


class HandoffSummary(BaseModel):
    """One row of the staff inbox list (`GET /staff/handoffs`)."""

    model_config = ConfigDict(frozen=True)

    handoff_id: UUID
    conversation_id: UUID
    queue: Queue
    priority: Priority
    reason: str
    status: HandoffStatus
    created_at: datetime
    claimed_by: str | None
    """The claiming agent's `display_name`, or `None` while queued."""


class HandoffListResponse(BaseModel):
    """`GET /staff/handoffs` response body."""

    model_config = ConfigDict(frozen=True)

    items: list[HandoffSummary]


class HandoffDetail(HandoffSummary):
    """`GET /staff/handoffs/{id}` response body: the summary plus the full packet."""

    packet: HandoffPacket


class AgentMessageRequest(BaseModel):
    """`POST /staff/conversations/{id}/messages` request body."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


class AgentMessageResponse(BaseModel):
    """`POST /staff/conversations/{id}/messages` response body."""

    model_config = ConfigDict(frozen=True)

    message_id: UUID
