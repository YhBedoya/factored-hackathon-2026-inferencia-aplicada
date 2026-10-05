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
from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.actions import ActionResult
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.context import ToolContext

__all__ = ["BankWriteTools", "BankWriteToolsFactory", "PendingCardRequests"]


@dataclass(frozen=True)
class PendingCardRequests:
    """The session customer's open card requests (D9-C I9): whether a card
    opening is pending, and the ids of the cards with a pending closure."""

    open_pending: bool
    close_card_ids: frozenset[str]


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

    async def request_card(
        self,
        kind: Literal["credit", "debit"],
        changed_fields: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        # Registry name: cards.request_card. Reads the changed values from the
        # vault, never from an argument (R5). `tracking_id` is the request
        # reference; the read-back is `{status, kind, fields_saved, request_id, at}`.
        # May raise: ToolUnavailable, Conflict.
        ...

    async def request_closure(
        self, card_id: str, reason: str, *, idempotency_key: str
    ) -> ActionResult:
        # Registry name: cards.request_closure. `reason` is a `cancel_reasons`
        # code (T29's `check_steps` validates it, not this tool). `tracking_id`
        # is the request reference; the read-back is `{status, reason, request_id,
        # card_id, card_kind, last4, current_balance, currency, at}`, the balance
        # a raw `Decimal` for code to format (R4).
        # May raise: NotFound, AccessDenied, ToolUnavailable, Conflict.
        ...

    async def pending_card_requests(self) -> PendingCardRequests:
        # Registry name: cards.pending_card_requests (read, scoped to the session).
        # May raise: ToolUnavailable.
        ...


BankWriteToolsFactory = Callable[[ToolContext], BankWriteTools]
"""Binds a `ToolContext` to a `BankWriteTools` instance (D4, as K3 D1)."""
