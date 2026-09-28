"""Handoff use cases: create, list, claim, return (D11, D14, D17).

Wraps the repository, maps rows to the staff API views and publishes the
`handoff_created` / `handoff_updated` events on `handoff:<queue>`. Never
imports `app.domains.conversation`; the conversation side reaches this through
its `HandoffTools` protocol.
"""

from collections.abc import Sequence
from uuid import UUID

from app.core.events import publish_handoff
from app.domains.handoff import repository
from app.domains.handoff.repository import AlreadyClaimed, HandoffClosed, NotClaimant
from app.domains.handoff.schemas import (
    HandoffDetail,
    HandoffPacket,
    HandoffStatus,
    HandoffSummary,
    Priority,
)

__all__ = [
    "AlreadyClaimed",
    "HandoffClosed",
    "NotClaimant",
    "claim",
    "create",
    "get_detail",
    "is_claimed_by",
    "list_handoffs",
    "return_handoff",
]


async def _publish(event: str, summary: HandoffSummary) -> None:
    await publish_handoff(summary.queue, event, summary.model_dump(mode="json"))


async def create(packet: HandoffPacket, priority: Priority) -> UUID:
    """Queue a handoff and flip the conversation to `human`. Idempotent per
    conversation: an open handoff is returned as is, with no second event.
    """
    handoff_id, created = await repository.insert_handoff(packet, priority)
    if created:
        detail = await repository.get_handoff(handoff_id)
        await _publish("handoff_created", detail.summary)
    return handoff_id


async def list_handoffs(
    queues: Sequence[str] | None, statuses: Sequence[HandoffStatus]
) -> list[HandoffSummary]:
    """Inbox rows, newest first. `queues=None` means every queue (admin)."""
    return [d.summary for d in await repository.list_handoffs(queues, statuses)]


async def get_detail(handoff_id: UUID) -> HandoffDetail:
    return await repository.get_handoff(handoff_id)


async def claim(handoff_id: UUID, agent_id: UUID) -> HandoffDetail:
    """Claim for `agent_id`; only a real state change emits `handoff_updated`."""
    detail, changed = await repository.claim(handoff_id, agent_id)
    if changed:
        await _publish("handoff_updated", detail.summary)
    return detail


async def return_handoff(handoff_id: UUID, agent_id: UUID) -> HandoffSummary:
    summary = await repository.return_handoff(handoff_id, agent_id)
    await _publish("handoff_updated", summary)
    return summary


async def is_claimed_by(conversation_id: UUID, agent_id: UUID) -> bool:
    return await repository.open_claim_for(conversation_id, agent_id)
