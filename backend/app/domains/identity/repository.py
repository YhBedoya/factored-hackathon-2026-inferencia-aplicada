"""Postgres reads and writes for `identity.accounts` and
`identity.revoked_tokens` (D2, D6, and D3/D4 for the staff rows).

Every account lookup goes by `login_key`, `customer_id` or `account_id`,
never by the raw document number -- `identity.accounts` doesn't even have a
column for it (D2). `AccountRow` never carries `login_key` itself: a caller
that already holds the key doesn't need it echoed back, and one that only
has a `customer_id` must never learn it from this row.

See `docs/specs/d2-a-login-read-tools-api.md` D2, D6 and
`docs/specs/d4-b-disputes-handoff-screens.md` D3, D4.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = [
    "AccountRow",
    "get_account_by_customer_id",
    "get_account_by_id",
    "get_account_by_login_key",
    "is_revoked",
    "revoke_token",
]


class AccountRow(BaseModel):
    """One `identity.accounts` row, the only shape this module hands back.

    `customer_id` is nullable (D4: an agent row has none), and
    `username`/`display_name` default to `None` so the in-file fakes in
    `test_login_pii.py` -- built before the staff columns existed -- still
    construct without change.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    role: str
    customer_id: str | None
    password_hash: str
    status: str
    username: str | None = None
    display_name: str | None = None


_SELECT_COLUMNS = "account_id, role, customer_id, password_hash, status, username, display_name"


async def _fetch_account(sql: str, params: dict[str, str]) -> AccountRow | None:
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(text(sql), params)
            row = result.mappings().first()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"identity account query failed: {exc}") from exc
    if row is None:
        return None
    return AccountRow(
        account_id=row["account_id"],
        role=row["role"],
        customer_id=row["customer_id"],
        password_hash=row["password_hash"],
        status=row["status"],
        username=row["username"],
        display_name=row["display_name"],
    )


async def get_account_by_login_key(login_key: str) -> AccountRow | None:
    """The account for one `login_key` (D2), or `None` if unknown."""
    return await _fetch_account(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM identity.accounts
        WHERE login_key = :login_key
        """,
        {"login_key": login_key},
    )


async def get_account_by_customer_id(customer_id: str) -> AccountRow | None:
    """The account for one `customer_id` (test-idp, D8), or `None` if there
    isn't one.
    """
    return await _fetch_account(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM identity.accounts
        WHERE customer_id = :customer_id
        """,
        {"customer_id": customer_id},
    )


async def get_account_by_id(account_id: UUID) -> AccountRow | None:
    """The account for one `account_id` (D3: `staff_me` reflects the
    caller's own session back), or `None` if it no longer exists.
    """
    return await _fetch_account(
        f"""
        SELECT {_SELECT_COLUMNS}
        FROM identity.accounts
        WHERE account_id = :account_id
        """,
        {"account_id": str(account_id)},
    )


async def revoke_token(jti: str, expires_at: datetime) -> None:
    """Insert one `identity.revoked_tokens` row. A repeat revoke of the same
    `jti` is a no-op, not an error (`ON CONFLICT DO NOTHING`).
    """
    try:
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO identity.revoked_tokens (jti, expires_at)
                    VALUES (:jti, :expires_at)
                    ON CONFLICT (jti) DO NOTHING
                    """
                ),
                {"jti": jti, "expires_at": expires_at},
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"identity token revoke failed: {exc}") from exc


async def is_revoked(jti: str) -> bool:
    """Whether `jti` has a live `identity.revoked_tokens` row."""
    try:
        async with get_engine().connect() as conn:
            result: Any = await conn.execute(
                text("SELECT 1 FROM identity.revoked_tokens WHERE jti = :jti"),
                {"jti": jti},
            )
            return result.first() is not None
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"identity revoke lookup failed: {exc}") from exc
