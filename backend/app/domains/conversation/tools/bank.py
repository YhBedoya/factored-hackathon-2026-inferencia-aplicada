"""The session-bound read-tools facade flows call.

See `docs/solution-docs/04-contracts.md` §1 and
`docs/specs/d1-k3-contracts.md` §"Contracts" → `app/domains/conversation/tools/`.
K3 ships the Protocol and factory type only: no implementation, `FakeBank` or
`BANK` selector (those are B1/D2-A3, D11).
"""

from collections.abc import Callable
from typing import Protocol

from app.core.pii import KnownPii
from app.domains.cards.schemas import CardDetails, CardSummary, CustomerCardRequest
from app.domains.conversation.tools.context import ToolContext
from app.domains.customers.schemas import CustomerProfile
from app.domains.disputes.schemas import PrioritySignals
from app.domains.localization.schemas import FxRate
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView

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

    async def get_transactions_by_ids(self, tx_ids: list[str]) -> list[TxView]:
        # Registry name: transactions.get_by_ids. This customer's own rows, in
        # `tx_ids`' order (R1): own-row first, then an existence probe.
        # May raise: NotFound, AccessDenied, ToolUnavailable.
        ...

    async def explain_decline(self, tx_id: str) -> DeclineExplanation:
        # Registry name: transactions.explain_decline. tx_id must be this
        # customer's own Declined transaction (R1): a missing, foreign or
        # non-Declined id is NotFound, never AccessDenied.
        # May raise: NotFound, DeclineCodeUnknown, ToolUnavailable.
        ...

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        # Registry name: reference.get_fx_rate. May raise: NotFound, ToolUnavailable.
        ...

    async def get_priority_signals(self) -> PrioritySignals:
        # Registry name: disputes.get_priority_signals. No arguments: bound
        # to this session's customer_id only (R1). May raise: ToolUnavailable.
        ...

    async def get_card_requests(self) -> list[CustomerCardRequest]:
        # Registry name: cards.get_card_requests. The session customer's latest
        # requests, newest first; no staff-only field (R1). May raise: ToolUnavailable.
        ...

    async def get_pii_profile(self) -> KnownPii:
        # No registry name and no `tool_call` audit event (D34): the runner's masking
        # step reads it, never an LLM node. May raise: ToolUnavailable.
        ...


BankToolsFactory = Callable[[ToolContext], BankReadTools]
"""Binds a `ToolContext` to a `BankReadTools` instance (D1, D2)."""
