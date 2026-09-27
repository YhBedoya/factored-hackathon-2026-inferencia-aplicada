"""The session-bound read-tools facade flows call.

See `docs/solution-docs/04-contracts.md` §1 and
`docs/specs/d1-k3-contracts.md` §"Contracts" → `app/domains/conversation/tools/`.
K3 ships the Protocol and factory type only: no implementation, `FakeBank` or
`BANK` selector (those are B1/D2-A3, D11).
"""

from collections.abc import Callable
from typing import Protocol

from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.context import ToolContext
from app.domains.customers.schemas import CustomerProfile
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["BankReadTools", "BankToolsFactory"]


class BankReadTools(Protocol):
    """A `ToolContext` bound at construction (D1). No method takes `ctx` or
    `customer_id`: the factory below closes over the context instead (R1).
    """

    async def get_profile(self) -> CustomerProfile:
        # Registry name: customers.get_profile. May raise: ToolUnavailable.
        ...

    async def list_cards(self) -> list[CardSummary]:
        # Registry name: cards.list_cards. May raise: ToolUnavailable.
        ...

    async def get_card_details(self, card_id: str) -> CardDetails:
        # Registry name: cards.get_card_details. May raise: NotFound, AccessDenied, ToolUnavailable.
        ...

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        # Registry name: transactions.search. May raise: AccessDenied (tx_filter.card_id
        # not the customer's), ToolUnavailable.
        ...


BankToolsFactory = Callable[[ToolContext], BankReadTools]
"""Binds a `ToolContext` to a `BankReadTools` instance (D1, D2)."""
