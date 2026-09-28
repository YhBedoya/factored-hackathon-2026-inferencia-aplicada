"""The audit event contract and the `Recorder` Protocol behind it.

See `docs/solution-docs/04-contracts.md` §6, D12, D13. This module imports
only the stdlib and pydantic: `conversation/tools/` and the runner import it
directly (a new import-linter ignore edge, T11), and it must stay free of
the database dependency `audit.repository` carries, or importing it would
pull that dependency in too (`06` §2).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue

__all__ = ["AuditActor", "AuditEvent", "AuditType", "NullAuditRecorder", "Recorder"]

AuditType = Literal[
    "nlu_result",
    "rule_hit",
    "tool_call",
    "tool_result",
    "confirmation_issued",
    "confirmation_used",
    "readback",
    "access_denied",
    "reply_sent",
    "error",
]

AuditActor = Literal["bot", "customer", "system"]
"""Who the event is attributed to. A customer turn's events use `"bot"`
(human decision, this card): the assistant is the one calling tools and
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
