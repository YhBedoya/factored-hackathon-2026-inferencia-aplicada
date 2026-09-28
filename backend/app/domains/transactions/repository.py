"""Postgres reads for `bank.transactions`.

Mirrors `FakeBank._build_tx_query`'s filter set and ordering
(`app/domains/conversation/tools/fakebank.py`): every `TxFilter` field maps
to one bound condition, newest first, at most 10 rows. It always filters by
`customer_id` (R1) but does not check card ownership -- `PostgresBank` does
that first (D11).

See `docs/specs/d2-a-login-read-tools-api.md` D11.
"""

from typing import Any

from sqlalchemy import RowMapping, TextClause, bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable
from app.domains.transactions.schemas import TxFilter

__all__ = ["fetch_transactions"]

_SELECT = """
    SELECT transaction_id, product_id, transaction_date AS occurred_at,
           amount, currency, amount_usd, transaction_type,
           transaction_category, merchant_name, merchant_category, channel,
           transaction_city, transaction_country, transaction_status,
           response_code, fraud_score
    FROM bank.transactions
"""


def _build_query(customer_id: str, tx_filter: TxFilter) -> tuple[TextClause, dict[str, Any]]:
    conditions = ["customer_id = :customer_id"]
    params: dict[str, Any] = {"customer_id": customer_id}
    expanding: list[str] = []
    if tx_filter.card_id is not None:
        conditions.append("product_id = :card_id")
        params["card_id"] = tx_filter.card_id
    if tx_filter.date_from is not None:
        conditions.append("transaction_date::date >= :date_from")
        params["date_from"] = tx_filter.date_from
    if tx_filter.date_to is not None:
        conditions.append("transaction_date::date <= :date_to")
        params["date_to"] = tx_filter.date_to
    if tx_filter.currency is not None:
        conditions.append("currency = :currency")
        params["currency"] = tx_filter.currency
    if tx_filter.amount_min is not None:
        conditions.append("amount >= :amount_min")
        params["amount_min"] = tx_filter.amount_min
    if tx_filter.amount_max is not None:
        conditions.append("amount <= :amount_max")
        params["amount_max"] = tx_filter.amount_max
    if tx_filter.status:
        conditions.append("transaction_status IN :status")
        params["status"] = tx_filter.status
        expanding.append("status")
    if tx_filter.merchant_names:
        conditions.append("merchant_name IN :merchant_names")
        params["merchant_names"] = tx_filter.merchant_names
        expanding.append("merchant_names")
    where_clause = " AND ".join(conditions)
    sql = text(f"{_SELECT} WHERE {where_clause} ORDER BY transaction_date DESC LIMIT 10")
    if expanding:
        sql = sql.bindparams(*(bindparam(name, expanding=True) for name in expanding))
    return sql, params


async def fetch_transactions(customer_id: str, tx_filter: TxFilter) -> list[RowMapping]:
    """At most 10 rows matching `tx_filter`, newest first."""
    sql, params = _build_query(customer_id, tx_filter)
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(sql, params)
            return list(result.mappings().all())
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"transactions query failed: {exc}") from exc
