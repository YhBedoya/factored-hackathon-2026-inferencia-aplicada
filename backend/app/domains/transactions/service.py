"""Transaction search.

Applies every `TxFilter` field the way `FakeBank.search_transactions` does,
except card ownership: this module does not call `cards.service` to check
it, because `PostgresBank` (the tool-registry wrapper) checks ownership
first and only calls here once it has passed (D11). It still always
filters by `customer_id` (R1).
"""

from sqlalchemy import RowMapping

from app.domains.transactions import repository
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["search"]


def _to_view(row: RowMapping) -> TxView:
    return TxView(
        tx_id=row["transaction_id"],
        card_id=row["product_id"],
        occurred_at=row["occurred_at"],
        amount=row["amount"],
        currency=row["currency"],
        amount_usd=row["amount_usd"],
        type=row["transaction_type"],
        category=row["transaction_category"],
        merchant_name=row["merchant_name"],
        merchant_category=row["merchant_category"],
        channel=row["channel"],
        city=row["transaction_city"],
        country=row["transaction_country"],
        status=row["transaction_status"],
        response_code=row["response_code"],
        fraud_score=row["fraud_score"],
    )


async def search(customer_id: str, tx_filter: TxFilter) -> list[TxView]:
    rows = await repository.fetch_transactions(customer_id, tx_filter)
    return [_to_view(row) for row in rows]
