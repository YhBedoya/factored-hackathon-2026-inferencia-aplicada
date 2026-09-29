"""`AuditRecorder`: a `Recorder` bound to one turn (D13).

Every write goes through `record`, which builds the `AuditEvent` (id and
timestamp are never the caller's to set) and inserts it. `record` raises on
failure -- it does not decide between fail-closed and log-and-continue; the
caller does (D15): a `tool_call` audit failure blocks the call before it
runs, while an audit failure *after* a raw write has run is caught and
logged by the caller instead.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue

from app.core.llm.sink import LLMCallRecord
from app.domains.audit import repository
from app.domains.audit.schemas import AuditActor, AuditEvent, AuditType

__all__ = ["AuditLLMCallSink", "AuditRecorder"]


class AuditRecorder:
    """Bound to `(conversation_id, turn_id, trace_id, policy_version, actor)`
    at construction, so `record` takes none of them (D13, R1-shaped).

    `insert` defaults to `repository.insert_event`; tests pass a fake to
    capture the events written without a database.
    """

    def __init__(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        trace_id: str,
        policy_version: str,
        actor: AuditActor,
        insert: Callable[[AuditEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._trace_id = trace_id
        self._policy_version = policy_version
        self._actor = actor
        self._insert = insert if insert is not None else repository.insert_event

    async def record(
        self, type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()
    ) -> UUID:
        event = AuditEvent(
            id=uuid4(),
            at=datetime.now(UTC),
            conversation_id=self._conversation_id,
            turn_id=self._turn_id,
            actor=self._actor,
            type=type,
            payload=payload,
            sources=list(sources),
            policy_version=self._policy_version,
            trace_id=self._trace_id,
        )
        await self._insert(event)
        return event.id


class AuditLLMCallSink:
    """`LLMCallSink` backed by `audit.llm_calls` (D9). `core/llm` only sees the
    protocol, so it imports no domain; id and timestamp are set here.
    """

    async def record(self, call: LLMCallRecord) -> None:
        await repository.insert_llm_call(uuid4(), datetime.now(UTC), call)
