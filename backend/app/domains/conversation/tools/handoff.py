"""The handoff write facade the `handoff` node calls (D11).

`HandoffTools` is bound to one conversation's `ToolContext` by whoever builds
it, so `create` takes no `customer_id` or context (R1). The conversation domain
reaches `app.handoffs` only through this Protocol, injected as
`config["configurable"]["handoff_tools"]`; the real implementation arrives with
the handoff service.
"""

from typing import Protocol
from uuid import UUID

from app.domains.conversation.tools.context import ToolContext
from app.domains.handoff import service
from app.domains.handoff.schemas import CustomerHistory, HandoffPacket

__all__ = ["HandoffTools", "InMemoryHandoffTools", "ServiceHandoffTools"]


class HandoffTools(Protocol):
    """Persist a packet, flip the conversation to human mode and notify staff."""

    async def create(self, packet: HandoffPacket) -> UUID:
        """Return the persisted handoff id: the packet's own, or the id of the
        handoff already open for the conversation (R3: the reference the
        customer sees must be a real row)."""
        ...

    async def history(self, days: int) -> CustomerHistory | None:
        """This customer's earlier handoffs and claims within `days`. No customer
        argument: the session decides whose (R1)."""
        ...


class InMemoryHandoffTools:
    """Records packets instead of persisting them: sandbox and unit tests."""

    def __init__(
        self, history: CustomerHistory | None = None, history_error: Exception | None = None
    ) -> None:
        self.created: list[HandoffPacket] = []
        self._history = history
        self._history_error = history_error

    async def create(self, packet: HandoffPacket) -> UUID:
        self.created.append(packet)
        return packet.handoff_id

    async def history(self, days: int) -> CustomerHistory | None:
        if self._history_error is not None:
            raise self._history_error
        return self._history


class ServiceHandoffTools:
    """The real `HandoffTools`: bound to one conversation's `ToolContext` (R1),
    it persists through `handoff.service`, the one edge the import-linter
    allows from conversation to the handoff domain."""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    async def create(self, packet: HandoffPacket) -> UUID:
        # A packet for another conversation must never be written from this one.
        if packet.conversation_id != self._ctx.conversation_id:
            raise ValueError("handoff packet does not belong to this conversation")
        return await service.create(packet, packet.priority)

    async def history(self, days: int) -> CustomerHistory | None:
        return await service.customer_history(
            self._ctx.customer_id, self._ctx.conversation_id, days, 5
        )
