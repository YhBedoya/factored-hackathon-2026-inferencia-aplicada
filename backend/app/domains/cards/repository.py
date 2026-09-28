"""Postgres reads for `bank.products` (cards only).

Mirrors the SQL semantics of `FakeBank.list_cards`/`get_card_details`
(`app/domains/conversation/tools/fakebank.py`): `last4 = right(product_number, 4)`,
card kinds are `Tarjeta Crédito`/`Tarjeta Débito`. Every query binds
`customer_id` (R1) except `fetch_card_probe`, which selects the single
`product_type` column for an id with no customer filter -- D1-B D17's
existence probe, kept narrow on purpose (never a balance, limit or card
number).

See `docs/specs/d2-a-login-read-tools-api.md` D11, D12.
"""

from typing import Any

from sqlalchemy import RowMapping, TextClause, bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = ["fetch_card_details", "fetch_card_probe", "fetch_cards"]

_CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")

_FETCH_CARDS_SQL = text(
    """
    SELECT product_id, product_type, right(product_number, 4) AS last4,
           product_status
    FROM bank.products
    WHERE customer_id = :customer_id
      AND product_type IN :card_types
    """
).bindparams(bindparam("card_types", expanding=True))


async def _fetch_rows(sql: str | TextClause, params: dict[str, Any]) -> list[RowMapping]:
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(text(sql) if isinstance(sql, str) else sql, params)
            return list(result.mappings().all())
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"cards query failed: {exc}") from exc


async def fetch_cards(customer_id: str) -> list[RowMapping]:
    """`product_id`, `product_type`, `last4`, `product_status` for every
    card this customer owns.
    """
    return await _fetch_rows(
        _FETCH_CARDS_SQL, {"customer_id": customer_id, "card_types": _CARD_TYPES}
    )


async def fetch_card_details(customer_id: str, card_id: str) -> RowMapping | None:
    """The full row for `card_id`, but only when it belongs to `customer_id`
    (own-row-first, D17 R1).
    """
    rows = await _fetch_rows(
        """
        SELECT product_id, product_type, right(product_number, 4) AS last4,
               currency, current_balance, credit_limit, interest_rate,
               expiration_date, product_status, days_past_due
        FROM bank.products
        WHERE product_id = :card_id AND customer_id = :customer_id
        """,
        {"card_id": card_id, "customer_id": customer_id},
    )
    return rows[0] if rows else None


async def fetch_card_probe(card_id: str) -> RowMapping | None:
    """Whether `card_id` exists *at all*, regardless of owner (D17 R1
    hardening). Selects only `product_type`, never a balance, limit, card
    number or other customer's id.
    """
    rows = await _fetch_rows(
        """
        SELECT product_type
        FROM bank.products
        WHERE product_id = :card_id
        """,
        {"card_id": card_id},
    )
    return rows[0] if rows else None
