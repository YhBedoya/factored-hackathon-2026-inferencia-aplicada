"""`PostgresBank`: `BankReadTools` over Postgres, via the `service` modules.

D11: it calls only `customers.service`, `cards.service` and
`transactions.service`, never a `repository` directly (import-linter's
`conversation-no-repository` contract enforces this). Country labels, card
kinds, `last4` and the transaction filter set already live in those
`service` modules (D1-B D17), matched to `FakeBank`'s own SQL. This module
adds only the one thing those `service` calls don't do on their own:
`search_transactions`' card-ownership check (D11 -- `transactions.service`
doesn't call `cards.service` itself, so `PostgresBank` does it first).

R1/D12: a foreign `card_id` -- in `get_card_details` or `tx_filter.card_id`
-- surfaces as `AccessDenied` from `cards.service` (D1-B D17's
own-row-first, existence-probe-second pattern) and is logged here exactly
once as `tool.access_denied`, with the opaque `product_id` and never a card
number, before it re-raises.
"""

import structlog

from app.core.errors import AccessDenied
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools, BankToolsFactory
from app.domains.conversation.tools.context import ToolContext
from app.domains.customers import service as customers_service
from app.domains.customers.schemas import CustomerProfile
from app.domains.transactions import service as transactions_service
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["PostgresBank", "make_postgres_factory"]

_logger = structlog.get_logger()


class PostgresBank:
    """`BankReadTools` bound to one `ToolContext` over Postgres (D11)."""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    async def get_profile(self) -> CustomerProfile:
        return await customers_service.get_profile(self._ctx.customer_id)

    async def list_cards(self) -> list[CardSummary]:
        return await cards_service.list_cards(self._ctx.customer_id)

    async def get_card_details(self, card_id: str) -> CardDetails:
        try:
            return await cards_service.get_card_details(self._ctx.customer_id, card_id)
        except AccessDenied:
            self._log_access_denied(tool="cards.get_card_details", requested_id=card_id)
            raise

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        if tx_filter.card_id is not None:
            try:
                await cards_service.get_card_details(self._ctx.customer_id, tx_filter.card_id)
            except AccessDenied:
                self._log_access_denied(tool="transactions.search", requested_id=tx_filter.card_id)
                raise
        return await transactions_service.search(self._ctx.customer_id, tx_filter)

    def _log_access_denied(self, *, tool: str, requested_id: str) -> None:
        _logger.warning(
            "tool.access_denied",
            tool=tool,
            requested_id=requested_id,
            conversation_id=str(self._ctx.conversation_id),
            trace_id=self._ctx.trace_id,
        )


def make_postgres_factory() -> BankToolsFactory:
    """No closed-over state to bind (unlike `make_fakebank_factory`'s
    `data_dir`): `PostgresBank` reaches Postgres through `service` modules
    that resolve `get_engine()` themselves.
    """

    def factory(ctx: ToolContext) -> BankReadTools:
        return PostgresBank(ctx)

    return factory
