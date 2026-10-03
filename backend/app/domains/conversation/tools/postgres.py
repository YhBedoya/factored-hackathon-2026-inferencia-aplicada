"""`PostgresBank`: `BankReadTools` over Postgres, via the `service` modules.

D11: it calls only `customers.service`, `cards.service`,
`transactions.service`, `localization.service` (D2-B's FX reference read)
and `disputes.service` (D7-B B2's priority signals), never a `repository`
directly (import-linter's `conversation-no-repository` contract enforces
this). Country labels, card kinds, `last4` and the transaction filter set
already live in those `service` modules (D1-B D17), matched to `FakeBank`'s
own SQL. This module adds only the one thing those `service` calls don't do
on their own: `search_transactions`' card-ownership check (D11 --
`transactions.service` doesn't call `cards.service` itself, so `PostgresBank`
does it first) and `get_priority_signals`' `open_statuses` (read from
`policies/disputes.yaml`, R8 -- `disputes.service` takes it as an argument
rather than loading the policy itself).

R1/D12: a foreign `card_id` -- in `get_card_details` or `tx_filter.card_id`
-- surfaces as `AccessDenied` from `cards.service` (D1-B D17's
own-row-first, existence-probe-second pattern) and is logged here exactly
once as `tool.access_denied`, with the opaque `product_id` and never a card
number, before it re-raises.
"""

import structlog

from app.core.errors import AccessDenied
from app.core.pii import KnownPii
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools, BankToolsFactory
from app.domains.conversation.tools.context import ToolContext
from app.domains.customers import service as customers_service
from app.domains.customers.schemas import CustomerProfile
from app.domains.disputes import service as disputes_service
from app.domains.disputes.schemas import PrioritySignals
from app.domains.localization import service as localization_service
from app.domains.localization.schemas import FxRate
from app.domains.policy.decline_codes import lookup_decline_code
from app.domains.policy.disputes import load_disputes_policy
from app.domains.transactions import service as transactions_service
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView

__all__ = ["PostgresBank", "make_postgres_factory"]

_logger = structlog.get_logger()


class PostgresBank:
    """`BankReadTools` bound to one `ToolContext` over Postgres (D11)."""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx

    async def get_profile(self) -> CustomerProfile:
        return await customers_service.get_profile(self._ctx.customer_id)

    async def get_pii_profile(self) -> KnownPii:
        return await customers_service.get_known_pii(self._ctx.customer_id)

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

    async def get_transactions_by_ids(self, tx_ids: list[str]) -> list[TxView]:
        # The same own-row lookup `disputes.create_claim` runs (D4-B, R1). A
        # pick re-reads its one row by id: `search` returns only the newest
        # 10, so an older picked row would fall out of an unfiltered re-read.
        try:
            return await transactions_service.get_by_ids(self._ctx.customer_id, tx_ids)
        except AccessDenied:
            self._log_access_denied(tool="transactions.get_by_ids", requested_id=tx_ids[0])
            raise

    async def explain_decline(self, tx_id: str) -> DeclineExplanation:
        # `get_declined` is already own-row-only with no AccessDenied path
        # (D4, R1), so there is nothing to catch and log here.
        tx = await transactions_service.get_declined(self._ctx.customer_id, tx_id)
        code = lookup_decline_code(tx.response_code)
        return DeclineExplanation(
            code=tx.response_code or "",
            cause_key=code.cause_key,
            next_step_key=code.next_step_key,
            self_service=code.self_service,
            source=f"policy:decline_codes@{self._ctx.policy_version}",
        )

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        # Reference data (D2-B D3): no `customer_id` to bind.
        return await localization_service.get_fx_rate(source, target)

    async def get_priority_signals(self) -> PrioritySignals:
        open_statuses = load_disputes_policy().priority.open_statuses
        return await disputes_service.priority_signals(self._ctx.customer_id, open_statuses)

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
