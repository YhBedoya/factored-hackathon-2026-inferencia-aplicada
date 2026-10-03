"""The raw bank write-tools facade a `ConfirmedWriteTools` executor wraps.

See `docs/solution-docs/04-contracts.md` §1 and
`docs/specs/d2-k-write-contracts.md` §"Contracts" ->
`app/domains/conversation/tools/write.py`, D3-D5. `BankWriteTools` never sees
a confirmation token (R2 is the executor's job, not this facade's): a raw
write returns `verified=True` only after re-reading the record it just wrote
(R3). The FakeBank does that re-read in B4, Postgres in D3-A3. This card
ships the Protocol and factory type only: no implementation.
"""

from collections.abc import Callable
from typing import Protocol

from app.core.actions import ActionResult
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.context import ToolContext

__all__ = ["BankWriteTools", "BankWriteToolsFactory"]


class BankWriteTools(Protocol):
    """A `ToolContext` bound at construction (D4). No method takes `ctx`,
    `customer_id` or a confirmation token: the factory below closes over the
    context instead (R1), and only `ConfirmedWriteTools` ever sees a token.
    """

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        # Registry name: cards.get_block_origin. May raise: NotFound, AccessDenied, ToolUnavailable.
        ...

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        # Registry name: cards.lock_card.
        # May raise: NotFound, AccessDenied, ToolUnavailable, Conflict.
        ...

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        # Registry name: cards.unlock_card.
        # May raise: NotFound, AccessDenied, ToolUnavailable, Conflict.
        ...

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        # Registry name: cards.block_card.
        # May raise: NotFound, AccessDenied, ToolUnavailable, Conflict.
        ...

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        # Registry name: cards.order_replacement.
        # May raise: NotFound, AccessDenied, ToolUnavailable, Conflict.
        ...

    async def create_claim(
        self,
        tx_ids: list[str],
        answers: list[str],
        priority_flags: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        # Registry name: disputes.create_claim. `priority_flags` is a sorted
        # list built in code by the flow (SA1): the row's `priority` is
        # `'High'` when it's non-empty, `NULL` otherwise.
        # May raise: NotFound, AccessDenied (any tx not the customer's), ToolUnavailable.
        ...


BankWriteToolsFactory = Callable[[ToolContext], BankWriteTools]
"""Binds a `ToolContext` to a `BankWriteTools` instance (D4, as K3 D1)."""
