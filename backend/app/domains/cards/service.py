"""Card reads: `list_cards` and `get_card_details`.

Mirrors `FakeBank.list_cards`/`get_card_details`'s own-row-first,
existence-probe-second pattern (D1-B D17, D11, D12): an owned non-card
product is `NotFound`, and a card id that belongs to another customer is
told apart from an unknown one only by the narrow `fetch_card_probe`
column. `locked` stays `False` until `app.card_controls` exists (D3-A3).
"""

from typing import Literal

from sqlalchemy import RowMapping

from app.core.errors import AccessDenied, NotFound
from app.domains.cards import repository
from app.domains.cards.schemas import CardDetails, CardSummary

__all__ = ["get_card_details", "list_cards"]

_CARD_KINDS: dict[str, Literal["credit", "debit"]] = {
    "Tarjeta Crédito": "credit",
    "Tarjeta Débito": "debit",
}


def _to_summary(row: RowMapping) -> CardSummary:
    return CardSummary(
        card_id=row["product_id"],
        kind=_CARD_KINDS[row["product_type"]],
        last4=row["last4"],
        status=row["product_status"],
        locked=False,
    )


async def _card_exists(card_id: str) -> bool:
    """Whether `card_id` is *someone else's* card (D17 R1 hardening)."""
    row = await repository.fetch_card_probe(card_id)
    return row is not None and row["product_type"] in _CARD_KINDS


async def list_cards(customer_id: str) -> list[CardSummary]:
    rows = await repository.fetch_cards(customer_id)
    return [_to_summary(row) for row in rows]


async def get_card_details(customer_id: str, card_id: str) -> CardDetails:
    row = await repository.fetch_card_details(customer_id, card_id)
    if row is not None and row["product_type"] not in _CARD_KINDS:
        # Owned, but not a card (e.g. a savings account): R1 is satisfied
        # (it is this customer's own product), it just isn't a card.
        raise NotFound(f"no card {card_id!r}")
    if row is None:
        if await _card_exists(card_id):
            raise AccessDenied(f"card {card_id!r} does not belong to this customer")
        raise NotFound(f"no card {card_id!r}")
    summary = _to_summary(row)
    is_debit = summary.kind == "debit"
    return CardDetails(
        **summary.model_dump(),
        currency=row["currency"],
        expiration_date=row["expiration_date"],
        credit_limit=None if is_debit else row["credit_limit"],
        current_balance=row["current_balance"],
        interest_rate=None if is_debit else row["interest_rate"],
        days_past_due=None if is_debit else row["days_past_due"],
        source=f"bank.products:{row['product_id']}",
    )
