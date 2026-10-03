"""Postgres reads for `bank.customers`.

Mirrors the SQL semantics of `FakeBank.get_profile`
(`app/domains/conversation/tools/fakebank.py`): country-label mapping and
the `ToolUnavailable` decision for a missing row happen in `service.py`, not
here. Every query binds `customer_id` (R1) through `sqlalchemy.text()`
bound parameters, never a string-formatted value.

D2's PII boundary is enforced in SQL: the login-profile query never
selects `document_number` itself, only its normalized last 3 characters
(`right(regexp_replace(upper(document_number), '[ .-]', '', 'g'), 3)`), so
the full number never crosses into Python.

See `docs/specs/d2-a-login-read-tools-api.md` D2, D9, D11.
"""

from typing import Any

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = ["fetch_document", "fetch_known_pii", "fetch_login_profile", "fetch_profile"]


async def _fetch_one(sql: str, params: dict[str, Any]) -> RowMapping | None:
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(text(sql), params)
            row = result.mappings().first()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"customers query failed: {exc}") from exc
    return row


async def fetch_profile(customer_id: str) -> RowMapping | None:
    """`country`, `customer_status`, `first_name` and `city` for one
    customer, or `None` if unknown.
    """
    return await _fetch_one(
        """
        SELECT country, customer_status, first_name, city
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def fetch_login_profile(customer_id: str) -> RowMapping | None:
    """`first_name`, `country`, `customer_status`, `document_type` and
    `document_last3` for one customer, or `None` if unknown.
    """
    return await _fetch_one(
        """
        SELECT first_name, country, customer_status, document_type,
               right(regexp_replace(upper(document_number), '[ .-]', '', 'g'), 3)
                   AS document_last3
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def fetch_known_pii(customer_id: str) -> RowMapping | None:
    """`document_number`, `first_name` and `last_name` for one customer, or
    `None` if unknown. Feeds the runner's masking step only (D3): the values
    never leave the process except as tokens.
    """
    return await _fetch_one(
        """
        SELECT document_number, first_name, last_name
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def fetch_document(customer_id: str) -> RowMapping | None:
    """`document_type` and `document_number` for one customer, or `None` if
    unknown. Feeds the admin persona credentials lookup (D22) only.
    """
    return await _fetch_one(
        """
        SELECT document_type, document_number
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )
