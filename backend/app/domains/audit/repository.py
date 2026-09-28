"""Postgres writes for `audit.audit_events` (append-only, D12).

There is no update or delete function here on purpose: the audit trail is
insert-only, and a row's `payload`/`sources` never change after the fact.
`model` and `langfuse_trace_id` stay `NULL` on every insert until tracing
lands (ADR-006); this module never writes to those columns.
"""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable
from app.domains.audit.schemas import AuditEvent

__all__ = ["insert_event"]

_INSERT_EVENT_SQL = text(
    """
    INSERT INTO audit.audit_events
        (id, at, conversation_id, turn_id, actor, type,
         payload, sources, policy_version, trace_id)
    VALUES
        (:id, :at, :conversation_id, :turn_id, :actor, :type,
         :payload, :sources, :policy_version, :trace_id)
    """
).bindparams(
    # asyncpg's jsonb codec only accepts an already-encoded string, and a
    # bare Python dict/list param fails with an opaque `DataError` (same
    # convention as `conversation.store.add_message`'s `ui_payload`).
    bindparam("payload", type_=JSONB),
    bindparam("sources", type_=JSONB),
)


async def insert_event(event: AuditEvent) -> None:
    """Insert one `audit.audit_events` row. Raises `ToolUnavailable` on any
    backend or data-source failure -- `AuditRecorder.record` decides from
    there whether that's fail-closed or a logged, non-fatal failure (D15).
    """
    try:
        async with get_engine().begin() as conn:
            await conn.execute(
                _INSERT_EVENT_SQL,
                {
                    "id": event.id,
                    "at": event.at,
                    "conversation_id": event.conversation_id,
                    "turn_id": event.turn_id,
                    "actor": event.actor,
                    "type": event.type,
                    "payload": event.payload,
                    "sources": event.sources,
                    "policy_version": event.policy_version,
                    "trace_id": event.trace_id,
                },
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"audit event insert failed: {exc}") from exc
