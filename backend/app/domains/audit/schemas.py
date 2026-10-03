"""The audit event contract and the `Recorder` Protocol behind it.

See `docs/solution-docs/04-contracts.md` §6, D12, D13. This module imports
only the stdlib and pydantic: `conversation/tools/` and the runner import it
directly (a new import-linter ignore edge, T11), and it must stay free of
the database dependency `audit.repository` carries, or importing it would
pull that dependency in too (`06` §2).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints

__all__ = [
    "AuditActor",
    "AuditEvent",
    "AuditType",
    "ConversationPage",
    "ConversationSummary",
    "ConversationTimeline",
    "LLMCallView",
    "NullAuditRecorder",
    "Outcome",
    "PolicyFileInfo",
    "Recorder",
    "StepInfo",
    "SystemInfo",
    "TimelineEvent",
    "TurnTimeline",
]

AuditType = Literal[
    "nlu_result",
    "rule_hit",
    "tool_call",
    "tool_result",
    "confirmation_issued",
    "confirmation_used",
    "readback",
    "access_denied",
    "handoff",
    "reply_sent",
    "error",
]

AuditActor = (
    Literal["bot", "customer", "system"]
    | Annotated[
        str,
        StringConstraints(pattern=r"^agent:[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$"),
    ]
)
"""Who the event is attributed to; staff actions use `agent:<account_id>` (D23).

A customer turn's events use `"bot"` (human decision, D2-K): the assistant is the one
calling tools and
composing the reply, not the customer directly.
"""


class AuditEvent(BaseModel):
    """One `audit.audit_events` row (frozen: `AuditRecorder` is the only writer).

    `payload` is structural only -- intents, status, rule id, tool, opaque
    `card_id`, `args_hash`, `step_index`, `verified`, read-back, error class,
    template kind and length. Never user text or reply text (R5, D13).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    at: datetime
    conversation_id: UUID | None
    turn_id: UUID | None
    actor: AuditActor
    type: AuditType
    payload: dict[str, JsonValue]
    sources: list[str]
    policy_version: str
    trace_id: str | None


class Recorder(Protocol):
    """Bound to one turn's `(conversation_id, turn_id, trace_id,
    policy_version, actor)` at construction, so `record` takes none of them
    (D13). Implemented structurally by `audit.service.AuditRecorder` and by
    `NullAuditRecorder` below.
    """

    async def record(
        self, type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()
    ) -> UUID:
        """Write one event and return its id. May raise: `ToolUnavailable`
        (D15 -- callers decide between fail-closed and log).
        """
        ...


class NullAuditRecorder:
    """A `Recorder` that never persists anything: the sandbox executor and
    unit tests that don't care about the audit trail (`04` §6).
    """

    async def record(
        self, type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()
    ) -> UUID:
        return uuid4()


# --- Staff timeline views (D7-A D23): read-only shapes, never written back. ---

Outcome = Literal["resolved", "clarified", "abstained"] | str
"""`"handoff:<queue>"` is the open-ended member (D18)."""


class ConversationSummary(BaseModel):
    """One row of the staff conversation list; `created_at` is `started_at`
    (`app.conversations` has no `created_at`, human decision Q1).
    """

    conversation_id: UUID
    created_at: datetime
    language: Literal["es", "pt"] | None
    country: Literal["MX", "CO", "AR"] | None
    intents: list[str]  # distinct, first-seen order
    outcome: str | None
    escalated: bool
    queue: str | None
    mode: str
    status: str
    turns: int


class ConversationPage(BaseModel):
    total: int
    items: list[ConversationSummary]


class LLMCallView(BaseModel):
    """An `audit.llm_calls` row without `input_text` or `output_json` (D17)."""

    step: str
    model_id: str
    prompt_version: str
    temperature: float | None
    attempt: int
    status: str
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None


class TimelineEvent(BaseModel):
    at: datetime
    type: AuditType
    actor: str
    payload: dict[str, JsonValue]
    sources: list[str]


class TurnTimeline(BaseModel):
    turn_id: UUID
    started_at: datetime
    customer_text_masked: str | None
    bot_text_masked: str | None
    nlu: dict[str, JsonValue] | None  # the turn's nlu_result payload
    rules: list[TimelineEvent]
    tools: list[TimelineEvent]  # tool_call + tool_result
    events: list[TimelineEvent]  # every audit event of the turn, in order
    sources: list[str]  # union, first-seen order
    policy_version: str | None
    llm_calls: list[LLMCallView]
    latency_ms: float | None  # reply_sent.at - customer message created_at
    cost_usd: float | None  # sum of llm_calls.cost_usd; None if none priced
    langfuse_url: str | None  # D20


class ConversationTimeline(BaseModel):
    conversation: ConversationSummary
    turns: list[TurnTimeline]


class StepInfo(BaseModel):
    step: str
    model_id: str
    temperature: float | None
    prompt_version: str


class PolicyFileInfo(BaseModel):
    file: str
    sha256: str


class SystemInfo(BaseModel):
    git_sha: str
    app_env: str
    llm_provider: str
    llm_disabled: bool
    steps: list[StepInfo]
    policy_hash: str
    policies: list[PolicyFileInfo]
