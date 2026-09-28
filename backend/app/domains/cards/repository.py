"""Postgres reads and writes for `bank.products` (cards) and the D3-A3
`app.card_controls`/`card_status_history`/`card_replacements` tables.

Mirrors the SQL semantics of `FakeBank.list_cards`/`get_card_details`/
`FakeBankWrites` (`app/domains/conversation/tools/fakebank.py`): `last4 =
right(product_number, 4)`, card kinds are `Tarjeta Crédito`/`Tarjeta
Débito`. Every query binds `customer_id` (R1) except `fetch_card_probe`,
which selects the single `product_type` column for an id with no customer
filter -- D1-B D17's existence probe, kept narrow on purpose (never a
balance, limit or card number).

D9-D11: every write statement binds `customer_id` too, either directly
(`update_product_status`) or through an `INSERT ... SELECT ... FROM
bank.products WHERE product_id = :card_id AND customer_id = :customer_id`
(`upsert_lock`, `insert_replacement`): a row lands only when the product is
this customer's own, a second layer under `cards.service`'s own
own-row-first probe. `write_block` runs `update_product_status` then
`insert_status_history` in the **one** transaction it opens (R12): a
failure in the second rolls the first back with it. `IntegrityError` (a
raced `idempotency_key`, D11) is left to propagate untouched -- the caller
in `cards.service` re-reads by key instead of treating it as a failure --
while any other `SQLAlchemyError`/`OSError` becomes `ToolUnavailable`.

See `docs/specs/d2-a-login-read-tools-api.md` D11, D12 and
`docs/specs/d3-a-guardrails-write-path.md` D9-D11.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, TextClause, bindparam, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = [
    "fetch_card_details",
    "fetch_card_probe",
    "fetch_cards",
    "fetch_control_by_key",
    "fetch_history_by_key",
    "fetch_lock_row",
    "fetch_replacement_by_id",
    "fetch_replacement_by_key",
    "fetch_status_state",
    "insert_replacement",
    "insert_status_history",
    "update_product_status",
    "upsert_lock",
    "write_block",
]

_CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")

_FETCH_CARDS_SQL = text(
    """
    SELECT p.product_id, p.product_type, right(p.product_number, 4) AS last4,
           p.product_status, coalesce(cc.locked, false) AS locked
    FROM bank.products p
    LEFT JOIN app.card_controls cc ON cc.product_id = p.product_id
    WHERE p.customer_id = :customer_id
      AND p.product_type IN :card_types
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
    """`product_id`, `product_type`, `last4`, `product_status`, `locked` for
    every card this customer owns (`locked` from `app.card_controls`, D3-A3).
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
        SELECT p.product_id, p.product_type, right(p.product_number, 4) AS last4,
               p.currency, p.current_balance, p.credit_limit, p.interest_rate,
               p.expiration_date, p.product_status, p.days_past_due,
               coalesce(cc.locked, false) AS locked
        FROM bank.products p
        LEFT JOIN app.card_controls cc ON cc.product_id = p.product_id
        WHERE p.product_id = :card_id AND p.customer_id = :customer_id
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


async def fetch_lock_row(customer_id: str, card_id: str) -> RowMapping | None:
    """`app.card_controls`' current `locked`/`updated_at` for `card_id`, or
    `None` if it was never written (D9-A3 re-read).
    """
    rows = await _fetch_rows(
        """
        SELECT cc.locked, cc.updated_at
        FROM app.card_controls cc
        JOIN bank.products p ON p.product_id = cc.product_id
        WHERE cc.product_id = :card_id AND p.customer_id = :customer_id
        """,
        {"card_id": card_id, "customer_id": customer_id},
    )
    return rows[0] if rows else None


async def fetch_status_state(customer_id: str, card_id: str) -> RowMapping | None:
    """`bank.products.product_status` plus the `at`/`actor` of the latest
    `app.card_status_history` row for `card_id` (D9-A3 re-read, and D10's
    `get_block_origin`/`last_status_actor`).
    """
    rows = await _fetch_rows(
        """
        SELECT p.product_status,
               h.at AS history_at, h.actor AS history_actor
        FROM bank.products p
        LEFT JOIN LATERAL (
            SELECT at, actor
            FROM app.card_status_history
            WHERE product_id = p.product_id
            ORDER BY at DESC
            LIMIT 1
        ) h ON true
        WHERE p.product_id = :card_id AND p.customer_id = :customer_id
        """,
        {"card_id": card_id, "customer_id": customer_id},
    )
    return rows[0] if rows else None


async def fetch_replacement_by_id(
    customer_id: str, card_id: str, replacement_id: UUID
) -> RowMapping | None:
    """One `app.card_replacements` row by id, scoped to this customer's card
    (D9-A3 re-read).
    """
    rows = await _fetch_rows(
        """
        SELECT r.status, r.created_at, r.tracking_id
        FROM app.card_replacements r
        JOIN bank.products p ON p.product_id = r.product_id
        WHERE r.id = :replacement_id
          AND r.product_id = :card_id
          AND p.customer_id = :customer_id
        """,
        {"replacement_id": replacement_id, "card_id": card_id, "customer_id": customer_id},
    )
    return rows[0] if rows else None


async def fetch_control_by_key(idempotency_key: str) -> RowMapping | None:
    """Whether an `app.card_controls` write already used `idempotency_key`
    (D11 replay check).
    """
    rows = await _fetch_rows(
        "SELECT product_id FROM app.card_controls WHERE idempotency_key = :idempotency_key",
        {"idempotency_key": idempotency_key},
    )
    return rows[0] if rows else None


async def fetch_history_by_key(idempotency_key: str) -> RowMapping | None:
    """Whether an `app.card_status_history` write already used
    `idempotency_key` (D11 replay check).
    """
    rows = await _fetch_rows(
        "SELECT id FROM app.card_status_history WHERE idempotency_key = :idempotency_key",
        {"idempotency_key": idempotency_key},
    )
    return rows[0] if rows else None


async def fetch_replacement_by_key(idempotency_key: str) -> RowMapping | None:
    """The `app.card_replacements` row (if any) already written under
    `idempotency_key` (D11 replay check) -- carries `id` so the caller can
    return it unchanged.
    """
    rows = await _fetch_rows(
        "SELECT id FROM app.card_replacements WHERE idempotency_key = :idempotency_key",
        {"idempotency_key": idempotency_key},
    )
    return rows[0] if rows else None


async def upsert_lock(
    customer_id: str, card_id: str, *, locked: bool, actor: str, idempotency_key: str
) -> int:
    """Insert or update the one `app.card_controls` row for `card_id`. The
    `INSERT ... SELECT ... FROM bank.products WHERE product_id = :card_id
    AND customer_id = :customer_id` binds ownership at the SQL layer too
    (D9): the returned rowcount is `0` when the product isn't this
    customer's own.
    """
    try:
        async with get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO app.card_controls
                        (product_id, locked, locked_by, locked_at, idempotency_key)
                    SELECT product_id, :locked, :locked_by, now(), :idempotency_key
                    FROM bank.products
                    WHERE product_id = :card_id AND customer_id = :customer_id
                    ON CONFLICT (product_id) DO UPDATE SET
                        locked = EXCLUDED.locked,
                        locked_by = EXCLUDED.locked_by,
                        locked_at = EXCLUDED.locked_at,
                        updated_at = now(),
                        idempotency_key = EXCLUDED.idempotency_key
                    """
                ),
                {
                    "card_id": card_id,
                    "customer_id": customer_id,
                    "locked": locked,
                    "locked_by": actor,
                    "idempotency_key": idempotency_key,
                },
            )
            return result.rowcount
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card lock write failed: {exc}") from exc


async def update_product_status(
    conn: AsyncConnection, *, customer_id: str, card_id: str, new_status: str
) -> str | None:
    """The status `card_id` held right before this update, or `None` if the
    row doesn't belong to `customer_id`. Read-then-write inside the caller's
    own transaction (R12) -- `write_block` below is the only caller, and it
    opens that transaction.
    """
    result = await conn.execute(
        text(
            "SELECT product_status FROM bank.products "
            "WHERE product_id = :card_id AND customer_id = :customer_id"
        ),
        {"card_id": card_id, "customer_id": customer_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    old_status: str = row["product_status"]
    await conn.execute(
        text(
            "UPDATE bank.products SET product_status = :new_status "
            "WHERE product_id = :card_id AND customer_id = :customer_id"
        ),
        {"new_status": new_status, "card_id": card_id, "customer_id": customer_id},
    )
    return old_status


async def insert_status_history(
    conn: AsyncConnection,
    *,
    history_id: UUID,
    card_id: str,
    old_status: str | None,
    new_status: str,
    reason: str | None,
    actor: str,
    conversation_id: UUID | None,
    trace_id: str | None,
    idempotency_key: str,
) -> None:
    """Insert one `app.card_status_history` row on the connection
    `write_block` opened -- the seam the R12 test monkeypatches to prove the
    status flip and the history insert share one transaction.
    """
    await conn.execute(
        text(
            """
            INSERT INTO app.card_status_history
                (id, product_id, old_status, new_status, reason, actor,
                 conversation_id, trace_id, idempotency_key)
            VALUES
                (:history_id, :card_id, :old_status, :new_status, :reason, :actor,
                 :conversation_id, :trace_id, :idempotency_key)
            """
        ),
        {
            "history_id": history_id,
            "card_id": card_id,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
            "actor": actor,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "idempotency_key": idempotency_key,
        },
    )


async def write_block(
    customer_id: str,
    card_id: str,
    *,
    new_status: str,
    reason: str | None,
    actor: str,
    conversation_id: UUID | None,
    trace_id: str | None,
    idempotency_key: str,
    history_id: UUID,
) -> str | None:
    """Run `update_product_status` then `insert_status_history` in **one**
    `get_engine().begin()` transaction (R12): a failure in the second rolls
    the first back with it. Returns the status `card_id` held before the
    update, or `None` if it doesn't belong to `customer_id`.
    """
    try:
        async with get_engine().begin() as conn:
            old_status = await update_product_status(
                conn, customer_id=customer_id, card_id=card_id, new_status=new_status
            )
            if old_status is None:
                return None
            await insert_status_history(
                conn,
                history_id=history_id,
                card_id=card_id,
                old_status=old_status,
                new_status=new_status,
                reason=reason,
                actor=actor,
                conversation_id=conversation_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )
        return old_status
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card block write failed: {exc}") from exc


async def insert_replacement(
    customer_id: str,
    card_id: str,
    *,
    replacement_id: UUID,
    address_ref: str,
    address_changed: bool,
    tracking_id: str,
    conversation_id: UUID | None,
    idempotency_key: str,
) -> int:
    """Insert one `app.card_replacements` row, status `"ordered"`. The
    `INSERT ... SELECT ... FROM bank.products WHERE product_id = :card_id
    AND customer_id = :customer_id` binds ownership at the SQL layer too
    (D9): the returned rowcount is `0` when the product isn't this
    customer's own. Never carries a raw address (D9): only the opaque
    `address_ref` and the `address_changed` flag.
    """
    try:
        async with get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    """
                    INSERT INTO app.card_replacements
                        (id, product_id, address_ref, address_changed, tracking_id,
                         status, conversation_id, idempotency_key)
                    SELECT :replacement_id, product_id, :address_ref, :address_changed,
                           :tracking_id, 'ordered', :conversation_id, :idempotency_key
                    FROM bank.products
                    WHERE product_id = :card_id AND customer_id = :customer_id
                    """
                ),
                {
                    "replacement_id": replacement_id,
                    "card_id": card_id,
                    "customer_id": customer_id,
                    "address_ref": address_ref,
                    "address_changed": address_changed,
                    "tracking_id": tracking_id,
                    "conversation_id": conversation_id,
                    "idempotency_key": idempotency_key,
                },
            )
            return result.rowcount
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card replacement write failed: {exc}") from exc
