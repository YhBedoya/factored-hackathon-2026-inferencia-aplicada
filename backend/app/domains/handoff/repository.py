"""Postgres access for `app.handoffs` (D11, D14).

Every write that changes a handoff also moves `app.conversations.mode` in the
same transaction, so the row and the mode can't disagree. Backend failures map
to `ToolUnavailable`, like the other repositories. Never imports
`app.domains.conversation`.
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import NotFound, ToolError, ToolUnavailable
from app.domains.handoff.schemas import (
    HandoffDetail,
    HandoffPacket,
    HandoffStatus,
    HandoffSummary,
    Priority,
    reference_for,
)

__all__ = [
    "AlreadyClaimed",
    "HandoffClosed",
    "NotClaimant",
    "claim",
    "get_handoff",
    "insert_handoff",
    "list_handoffs",
    "open_claim_for",
    "return_handoff",
]


class AlreadyClaimed(ToolError):
    """Another agent holds the handoff (`409 already_claimed`)."""


class HandoffClosed(ToolError):
    """The handoff was already returned (`409 handoff_closed`)."""


class NotClaimant(ToolError):
    """The caller isn't the agent holding the handoff (`409 not_claimant`)."""


_SELECT_SQL = """
    SELECT h.id, h.conversation_id, h.queue, h.reason, h.priority, h.status,
           h.agent_id, h.created_at, h.packet, a.display_name AS claimed_by
    FROM app.handoffs h
    LEFT JOIN identity.accounts a ON a.account_id = h.agent_id
"""

_INSERT_SQL = text(
    """
    INSERT INTO app.handoffs (id, conversation_id, queue, reason, priority, packet, status)
    VALUES (:id, :conversation_id, :queue, :reason, :priority, :packet, 'queued')
    ON CONFLICT DO NOTHING
    RETURNING id
    """
).bindparams(bindparam("packet", type_=JSONB))

_OPEN_FOR_CONVERSATION_SQL = text(
    """
    SELECT id FROM app.handoffs
    WHERE conversation_id = :conversation_id AND status IN ('queued', 'claimed')
    """
)

_SET_MODE_SQL = text("UPDATE app.conversations SET mode = :mode WHERE id = :conversation_id")


def _detail(row: Any) -> HandoffDetail:
    packet = HandoffPacket.model_validate(row["packet"])
    summary = HandoffSummary(
        handoff_id=row["id"],
        reference=reference_for(row["id"]),
        conversation_id=row["conversation_id"],
        queue=row["queue"],
        priority=row["priority"],
        reason=row["reason"],
        status=row["status"],
        language=packet.language,
        created_at=row["created_at"],
        claimed_by=row["claimed_by"],
    )
    return HandoffDetail(summary=summary, packet=packet)


async def insert_handoff(packet: HandoffPacket, priority: Priority) -> tuple[UUID, bool]:
    """Insert the `queued` row and set the conversation to `human` in one
    transaction. Returns `(handoff_id, created)`; if the conversation already
    has an open handoff, returns that id with `created=False` and changes nothing.
    """
    try:
        async with get_engine().begin() as conn:
            inserted = (
                await conn.execute(
                    _INSERT_SQL,
                    {
                        "id": packet.handoff_id,
                        "conversation_id": packet.conversation_id,
                        "queue": packet.queue,
                        "reason": packet.reason,
                        "priority": priority,
                        "packet": packet.model_dump(mode="json"),
                    },
                )
            ).scalar_one_or_none()
            if inserted is not None:
                await conn.execute(
                    _SET_MODE_SQL, {"mode": "human", "conversation_id": packet.conversation_id}
                )
                return inserted, True
            existing = (
                await conn.execute(
                    _OPEN_FOR_CONVERSATION_SQL, {"conversation_id": packet.conversation_id}
                )
            ).scalar_one()
            return existing, False
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff insert failed: {exc}") from exc


async def list_handoffs(
    queues: Sequence[str] | None, statuses: Sequence[HandoffStatus]
) -> list[HandoffDetail]:
    """Handoffs in the given queues (all when `None`) and statuses, newest first."""
    sql = _SELECT_SQL + " WHERE h.status = ANY(:statuses)"
    params: dict[str, Any] = {"statuses": list(statuses)}
    if queues is not None:
        sql += " AND h.queue = ANY(:queues)"
        params["queues"] = list(queues)
    sql += " ORDER BY h.created_at DESC"
    try:
        async with get_engine().connect() as conn:
            rows = (await conn.execute(text(sql), params)).mappings().all()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff list failed: {exc}") from exc
    return [_detail(r) for r in rows]


async def get_handoff(handoff_id: UUID) -> HandoffDetail:
    """One handoff, or `NotFound`."""
    try:
        async with get_engine().connect() as conn:
            row = (
                (await conn.execute(text(_SELECT_SQL + " WHERE h.id = :id"), {"id": handoff_id}))
                .mappings()
                .first()
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff read failed: {exc}") from exc
    if row is None:
        raise NotFound(f"handoff {handoff_id} not found")
    return _detail(row)


async def claim(handoff_id: UUID, agent_id: UUID) -> tuple[HandoffDetail, bool]:
    """Claim a queued handoff. Returns `(detail, changed)`; re-claiming by the
    same agent is a no-op (`changed=False`). Another claimant raises
    `AlreadyClaimed`, a returned handoff `HandoffClosed`, an unknown id `NotFound`.
    """
    try:
        async with get_engine().begin() as conn:
            # FOR UPDATE serialises two agents racing for the same row.
            row = (
                (
                    await conn.execute(
                        text(_SELECT_SQL + " WHERE h.id = :id FOR UPDATE OF h"), {"id": handoff_id}
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound(f"handoff {handoff_id} not found")
            if row["status"] == "returned":
                raise HandoffClosed(str(handoff_id))
            if row["status"] == "claimed":
                if row["agent_id"] != agent_id:
                    raise AlreadyClaimed(str(handoff_id))
                return _detail(row), False
            await conn.execute(
                text(
                    "UPDATE app.handoffs SET status = 'claimed', agent_id = :agent_id, "
                    "claimed_at = now() WHERE id = :id"
                ),
                {"id": handoff_id, "agent_id": agent_id},
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff claim failed: {exc}") from exc
    return await get_handoff(handoff_id), True


async def return_handoff(handoff_id: UUID, agent_id: UUID) -> HandoffSummary:
    """Mark the handoff `returned` and the conversation `bot` in one transaction.
    Raises `NotClaimant` unless `agent_id` holds it, `NotFound` for an unknown id.
    """
    try:
        async with get_engine().begin() as conn:
            row = (
                (
                    await conn.execute(
                        text(_SELECT_SQL + " WHERE h.id = :id FOR UPDATE OF h"), {"id": handoff_id}
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound(f"handoff {handoff_id} not found")
            if row["status"] != "claimed" or row["agent_id"] != agent_id:
                raise NotClaimant(str(handoff_id))
            await conn.execute(
                text(
                    "UPDATE app.handoffs SET status = 'returned', returned_at = now() "
                    "WHERE id = :id"
                ),
                {"id": handoff_id},
            )
            await conn.execute(
                _SET_MODE_SQL, {"mode": "bot", "conversation_id": row["conversation_id"]}
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff return failed: {exc}") from exc
    return (await get_handoff(handoff_id)).summary


async def open_claim_for(conversation_id: UUID, agent_id: UUID) -> bool:
    """True if `agent_id` holds a claimed, not yet returned handoff on the conversation."""
    try:
        async with get_engine().connect() as conn:
            found = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM app.handoffs WHERE conversation_id = :c "
                        "AND agent_id = :a AND status = 'claimed'"
                    ),
                    {"c": conversation_id, "a": agent_id},
                )
            ).first()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"handoff claim check failed: {exc}") from exc
    return found is not None
