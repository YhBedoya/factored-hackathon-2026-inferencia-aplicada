"""Postgres reads and writes for `bank.complaints`' claim rows (D14, D15).

`insert_claims` writes every row of one `create_claim` step in the caller's
own transaction (R12): all rows land or none do. `fetch_claims_by_keys` is
the D15 replay check -- a hit on every row's `<idempotency_key>:<tx_id>`
means this exact step already ran, so `service.create_claims` re-reads
instead of writing a second set. `fetch_claims_by_ids` is the **separate**
re-read `postgres_writes.py` uses to compute `verified` (R3): it never runs
inside the same transaction `insert_claims` used.
"""

from typing import Any

from sqlalchemy import RowMapping, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = ["fetch_claims_by_ids", "fetch_claims_by_keys", "insert_claims"]

_SELECT = """
    SELECT complaint_id, conversation_id, customer_id, transaction_id,
           affected_product_id, claimed_amount, currency, status, origin,
           creation_date, case_type, category, subcategory,
           reception_channel, description
    FROM bank.complaints
"""

_FETCH_BY_KEYS_SQL = text(f"{_SELECT} WHERE idempotency_key IN :keys").bindparams(
    bindparam("keys", expanding=True)
)

_FETCH_BY_IDS_SQL = text(
    f"{_SELECT} WHERE customer_id = :customer_id AND complaint_id IN :complaint_ids"
).bindparams(bindparam("complaint_ids", expanding=True))

_INSERT_SQL = text(
    """
    INSERT INTO bank.complaints
        (complaint_id, creation_date, customer_id, case_type, category,
         subcategory, reception_channel, affected_product_id, claimed_amount,
         currency, priority, status, origin, conversation_id, transaction_id,
         idempotency_key, description)
    VALUES
        (:complaint_id, :creation_date, :customer_id, :case_type, :category,
         :subcategory, :reception_channel, :affected_product_id, :claimed_amount,
         :currency, :priority, :status, :origin, :conversation_id, :transaction_id,
         :idempotency_key, :description)
    """
)


async def fetch_claims_by_keys(idempotency_keys: list[str]) -> list[RowMapping]:
    """Whichever rows of `idempotency_keys` already exist (D15 replay check),
    regardless of owner: `service.create_claims` only calls this with keys it
    is about to write or has just written under this customer's own
    `create_claims` call, so no additional ownership filter is needed here.
    """
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(_FETCH_BY_KEYS_SQL, {"keys": idempotency_keys})
            return list(result.mappings().all())
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"complaints query failed: {exc}") from exc


async def fetch_claims_by_ids(customer_id: str, complaint_ids: list[str]) -> list[RowMapping]:
    """Own rows only, by `complaint_id` (R1) -- the separate re-read (R3)."""
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                _FETCH_BY_IDS_SQL, {"customer_id": customer_id, "complaint_ids": complaint_ids}
            )
            return list(result.mappings().all())
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"complaints query failed: {exc}") from exc


async def insert_claims(rows: list[dict[str, Any]]) -> None:
    """Insert every row in **one** transaction (R12): a failure on any row
    rolls every earlier one in this call back with it. A unique-violation
    `IntegrityError` (a raced `idempotency_key`, D15) is left to propagate
    untouched -- `service.create_claims` re-reads by key instead of treating
    it as a failure, the same way `cards.service`'s writes do.
    """
    try:
        async with get_engine().begin() as conn:
            for row in rows:
                await conn.execute(_INSERT_SQL, row)
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"complaints write failed: {exc}") from exc
