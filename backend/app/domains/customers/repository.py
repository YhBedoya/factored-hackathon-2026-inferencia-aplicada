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
from uuid import uuid4

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = [
    "fetch_decision_profile",
    "fetch_display_names",
    "fetch_document",
    "fetch_history_fields",
    "fetch_known_pii",
    "fetch_login_profile",
    "fetch_profile",
    "fetch_profile_form_row",
    "fetch_profile_values",
    "insert_history_row",
    "lock_profile_values",
    "update_profile_columns",
]


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


async def fetch_display_names(customer_ids: list[str]) -> dict[str, str]:
    """`customer_id -> "first_name last_name"` for the judges' demo catalog
    (ADR-036) only; ids with no row are left out.
    """
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT customer_id, first_name, last_name
                    FROM bank.customers
                    WHERE customer_id = ANY(:customer_ids)
                    """
                ),
                {"customer_ids": customer_ids},
            )
            rows = result.mappings().all()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"customers query failed: {exc}") from exc
    return {
        row["customer_id"]: " ".join(
            part.strip() for part in (row["first_name"], row["last_name"]) if part and part.strip()
        )
        for row in rows
    }


# Column names are interpolated into UPDATE below; they come only from this
# allowlist, never from caller text.
_EDITABLE_COLUMNS = frozenset(
    {"email", "mobile_phone", "address", "occupation", "estimated_monthly_income"}
)


async def fetch_profile_values(customer_id: str) -> RowMapping | None:
    """The five editable columns for one customer, or `None` if unknown."""
    return await _fetch_one(
        """
        SELECT email, mobile_phone, address, occupation, estimated_monthly_income
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def fetch_profile_form_row(customer_id: str) -> RowMapping | None:
    """Editable columns plus the read-only ones the profile form shows."""
    return await _fetch_one(
        """
        SELECT email, mobile_phone, address, occupation, estimated_monthly_income,
               first_name, last_name, document_type, country, date_of_birth,
               right(regexp_replace(upper(document_number), '[ .-]', '', 'g'), 3)
                   AS document_last3
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def fetch_decision_profile(customer_id: str) -> RowMapping | None:
    """Underwriting context for staff: score, segment, whole years as a customer, income."""
    return await _fetch_one(
        """
        SELECT credit_score, segment, occupation, estimated_monthly_income, country,
               EXTRACT(YEAR FROM age(now(), registration_date))::int AS tenure_years
        FROM bank.customers
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def lock_profile_values(conn: AsyncConnection, customer_id: str) -> RowMapping | None:
    """Row-lock the customer inside the caller's transaction and return the old values."""
    result = await conn.execute(
        text(
            """
            SELECT email, mobile_phone, address, occupation, estimated_monthly_income
            FROM bank.customers
            WHERE customer_id = :customer_id
            FOR UPDATE
            """
        ),
        {"customer_id": customer_id},
    )
    return result.mappings().first()


async def update_profile_columns(
    conn: AsyncConnection, customer_id: str, values: dict[str, Any]
) -> None:
    """Update only the given columns, on the caller's connection (no commit)."""
    if not values or not set(values) <= _EDITABLE_COLUMNS:
        raise ValueError("update_profile_columns got an unknown or empty column set")
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    await conn.execute(
        text(f"UPDATE bank.customers SET {assignments} WHERE customer_id = :customer_id"),
        {**values, "customer_id": customer_id},
    )


async def insert_history_row(
    conn: AsyncConnection,
    *,
    customer_id: str,
    field: str,
    old_value_enc: str | None,
    new_value_enc: str,
    actor: str,
    conversation_id: str | None,
    card_request_id: str | None,
) -> None:
    """One `app.customer_profile_history` row, on the caller's connection (R12)."""
    await conn.execute(
        text(
            """
            INSERT INTO app.customer_profile_history
                (id, customer_id, field, old_value_enc, new_value_enc, actor,
                 conversation_id, card_request_id)
            VALUES (:id, :customer_id, :field, :old_value_enc, :new_value_enc, :actor,
                    CAST(:conversation_id AS uuid), CAST(:card_request_id AS uuid))
            """
        ),
        {
            "id": uuid4(),
            "customer_id": customer_id,
            "field": field,
            "old_value_enc": old_value_enc,
            "new_value_enc": new_value_enc,
            "actor": actor,
            "conversation_id": conversation_id,
            "card_request_id": card_request_id,
        },
    )


async def fetch_history_fields(card_request_id: str) -> list[str]:
    """Fields changed by one card request, from its history rows."""
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT DISTINCT field
                    FROM app.customer_profile_history
                    WHERE card_request_id = CAST(:card_request_id AS uuid)
                    """
                ),
                {"card_request_id": card_request_id},
            )
            return [row["field"] for row in result.mappings().all()]
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"customers query failed: {exc}") from exc
