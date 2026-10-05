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

from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
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
    "fetch_customer_cards_panel",
    "fetch_history_by_key",
    "fetch_lock_row",
    "fetch_pending_requests",
    "fetch_product_row",
    "fetch_recent_requests",
    "fetch_replacement_by_id",
    "fetch_replacement_by_key",
    "fetch_request_by_decision_key",
    "fetch_request_by_id",
    "fetch_request_by_key",
    "fetch_status_state",
    "insert_app_product",
    "insert_close_request",
    "insert_open_request",
    "insert_replacement",
    "insert_status_history",
    "lock_request",
    "product_number_exists",
    "update_changed_fields",
    "update_product_status",
    "update_request_decision",
    "upsert_lock",
    "write_block",
    "write_close_request",
    "write_decision",
    "write_open_request",
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
        "SELECT id, product_id, new_status FROM app.card_status_history "
        "WHERE idempotency_key = :idempotency_key",
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


_REQUEST_COLUMNS = (
    "id, reference, customer_id, conversation_id, handoff_id, kind, card_kind, product_id, "
    "reason_code, changed_fields, status, decision, decline_reason, credit_limit, agent_id, "
    "decided_at, created_at"
)


async def fetch_request_by_id(request_id: UUID) -> RowMapping | None:
    rows = await _fetch_rows(
        f"SELECT {_REQUEST_COLUMNS} FROM app.card_requests WHERE id = :request_id",
        {"request_id": request_id},
    )
    return rows[0] if rows else None


async def fetch_request_by_key(idempotency_key: str) -> RowMapping | None:
    """The request (if any) already written under `idempotency_key` (replay check)."""
    rows = await _fetch_rows(
        f"SELECT {_REQUEST_COLUMNS} FROM app.card_requests "
        "WHERE idempotency_key = :idempotency_key",
        {"idempotency_key": idempotency_key},
    )
    return rows[0] if rows else None


async def fetch_pending_requests(customer_id: str) -> list[RowMapping]:
    """The customer's undecided requests, both kinds, oldest first (R1)."""
    return await _fetch_rows(
        f"SELECT {_REQUEST_COLUMNS} FROM app.card_requests "
        "WHERE customer_id = :customer_id AND status = 'pending' ORDER BY created_at, id",
        {"customer_id": customer_id},
    )


async def fetch_recent_requests(customer_id: str, limit: int) -> list[RowMapping]:
    """The customer's latest requests, both kinds and any status, newest first (R1)."""
    return await _fetch_rows(
        f"SELECT {_REQUEST_COLUMNS} FROM app.card_requests "
        "WHERE customer_id = :customer_id ORDER BY created_at DESC, id DESC LIMIT :limit",
        {"customer_id": customer_id, "limit": limit},
    )


async def insert_open_request(
    conn: AsyncConnection,
    *,
    request_id: UUID,
    reference: str,
    customer_id: str,
    conversation_id: UUID,
    card_kind: str,
    changed_fields: list[str],
    idempotency_key: str,
) -> None:
    """Insert one pending `open` request on the caller's connection."""
    await conn.execute(
        text(
            """
            INSERT INTO app.card_requests
                (id, reference, customer_id, conversation_id, kind, card_kind,
                 changed_fields, status, idempotency_key)
            VALUES (:id, :reference, :customer_id, :conversation_id, 'open', :card_kind,
                    :changed_fields, 'pending', :idempotency_key)
            """
        ),
        {
            "id": request_id,
            "reference": reference,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "card_kind": card_kind,
            "changed_fields": changed_fields,
            "idempotency_key": idempotency_key,
        },
    )


async def update_changed_fields(
    conn: AsyncConnection, request_id: UUID, changed_fields: list[str]
) -> None:
    await conn.execute(
        text("UPDATE app.card_requests SET changed_fields = :f WHERE id = :id"),
        {"f": changed_fields, "id": request_id},
    )


async def write_open_request(
    work: Callable[[AsyncConnection], Awaitable[None]],
) -> None:
    """Run `work` in one transaction (R12): the request row and the profile
    writes land together or not at all. `IntegrityError` (a raced key or the
    pending-open index) propagates untouched for `cards.service` to classify;
    any other `SQLAlchemyError`/`OSError` becomes `ToolUnavailable`.
    """
    try:
        async with get_engine().begin() as conn:
            await work(conn)
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card request write failed: {exc}") from exc


async def insert_close_request(
    conn: AsyncConnection,
    *,
    request_id: UUID,
    reference: str,
    customer_id: str,
    conversation_id: UUID,
    card_kind: str,
    product_id: str,
    reason_code: str,
    idempotency_key: str,
) -> None:
    """Insert one pending `close` request on the caller's connection."""
    await conn.execute(
        text(
            """
            INSERT INTO app.card_requests
                (id, reference, customer_id, conversation_id, kind, card_kind,
                 product_id, reason_code, status, idempotency_key)
            VALUES (:id, :reference, :customer_id, :conversation_id, 'close', :card_kind,
                    :product_id, :reason_code, 'pending', :idempotency_key)
            """
        ),
        {
            "id": request_id,
            "reference": reference,
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "card_kind": card_kind,
            "product_id": product_id,
            "reason_code": reason_code,
            "idempotency_key": idempotency_key,
        },
    )


async def write_close_request(
    work: Callable[[AsyncConnection], Awaitable[None]],
) -> None:
    """Run `work` in one transaction. `IntegrityError` (a raced key or the
    pending-close index) propagates for `cards.service` to classify; any other
    `SQLAlchemyError`/`OSError` becomes `ToolUnavailable`.
    """
    try:
        async with get_engine().begin() as conn:
            await work(conn)
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card close request write failed: {exc}") from exc


async def fetch_request_by_decision_key(decision_key: str) -> RowMapping | None:
    """The request (if any) already decided under the staff `decision_key` (replay check)."""
    rows = await _fetch_rows(
        f"SELECT {_REQUEST_COLUMNS} FROM app.card_requests WHERE decision_key = :decision_key",
        {"decision_key": decision_key},
    )
    return rows[0] if rows else None


async def lock_request(conn: AsyncConnection, request_id: UUID) -> RowMapping | None:
    """The request row, locked `FOR UPDATE` until the caller's transaction ends.
    `decision_key` is selected too so a raced replay can be told apart from a
    different decision."""
    result = await conn.execute(
        text(
            f"SELECT {_REQUEST_COLUMNS}, decision_key FROM app.card_requests "
            "WHERE id = :request_id FOR UPDATE"
        ),
        {"request_id": request_id},
    )
    return result.mappings().first()


async def fetch_product_row(product_id: str) -> RowMapping | None:
    """One product row by id, with no owner check: callers pass an id taken
    from a `card_requests` row, never from the chat."""
    rows = await _fetch_rows(
        """
        SELECT product_id, customer_id, product_type, right(product_number, 4) AS last4,
               currency, current_balance, credit_limit, interest_rate, opening_date,
               expiration_date, product_status, days_past_due, opening_channel, origin,
               conversation_id
        FROM bank.products
        WHERE product_id = :product_id
        """,
        {"product_id": product_id},
    )
    return rows[0] if rows else None


async def lock_product(conn: AsyncConnection, product_id: str) -> RowMapping | None:
    """The product's status and balance, read fresh and locked `FOR UPDATE` so the
    zero-balance check and the close share one consistent view (spec AS8)."""
    result = await conn.execute(
        text(
            "SELECT product_status, current_balance FROM bank.products "
            "WHERE product_id = :product_id FOR UPDATE"
        ),
        {"product_id": product_id},
    )
    return result.mappings().first()


async def set_product_closed(conn: AsyncConnection, product_id: str) -> None:
    await conn.execute(
        text("UPDATE bank.products SET product_status = 'Closed' WHERE product_id = :product_id"),
        {"product_id": product_id},
    )


async def fetch_customer_cards_panel(customer_id: str) -> list[RowMapping]:
    """The customer's cards with what the staff panel shows (R1: by customer)."""
    return await _fetch_rows(
        _PANEL_CARDS_SQL, {"customer_id": customer_id, "card_types": _CARD_TYPES}
    )


_PANEL_CARDS_SQL = text(
    """
    SELECT product_id, product_type, right(product_number, 4) AS last4, product_status,
           currency, current_balance, credit_limit
    FROM bank.products
    WHERE customer_id = :customer_id AND product_type IN :card_types
    ORDER BY opening_date NULLS LAST, product_id
    """
).bindparams(bindparam("card_types", expanding=True))


async def product_number_exists(conn: AsyncConnection, product_number: str) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM bank.products WHERE product_number = :n LIMIT 1"),
        {"n": product_number},
    )
    return result.first() is not None


async def insert_app_product(
    conn: AsyncConnection,
    *,
    product_id: str,
    customer_id: str,
    product_type: str,
    product_number: str,
    currency: str,
    credit_limit: Decimal | None,
    interest_rate: Decimal,
    opening_date: date,
    expiration_date: date,
    conversation_id: UUID,
) -> None:
    """Insert the approved card on the caller's connection (spec AS4).
    `origin='app'` marks it as not from the dataset (R12)."""
    await conn.execute(
        text(
            """
            INSERT INTO bank.products
                (product_id, customer_id, product_type, product_number, currency,
                 current_balance, credit_limit, interest_rate, opening_date, expiration_date,
                 product_status, opening_channel, days_past_due, last_updated,
                 origin, created_at, conversation_id)
            VALUES (:product_id, :customer_id, :product_type, :product_number, :currency,
                    0, :credit_limit, :interest_rate, :opening_date, :expiration_date,
                    'Active', 'App', 0, now(),
                    'app', now(), :conversation_id)
            """
        ),
        {
            "product_id": product_id,
            "customer_id": customer_id,
            "product_type": product_type,
            "product_number": product_number,
            "currency": currency,
            "credit_limit": credit_limit,
            "interest_rate": interest_rate,
            "opening_date": opening_date,
            "expiration_date": expiration_date,
            "conversation_id": conversation_id,
        },
    )


async def update_request_decision(
    conn: AsyncConnection,
    request_id: UUID,
    *,
    decision: str,
    decline_reason: str | None,
    credit_limit: Decimal | None,
    agent_id: UUID,
    decision_key: str,
    product_id: str | None,
) -> None:
    """Close the request with the staff decision. `handoff_id` is the open
    handoff of the request's conversation (R-a: written here, not at creation)."""
    await conn.execute(
        text(
            """
            UPDATE app.card_requests
            SET status = 'decided', decision = :decision, decline_reason = :decline_reason,
                credit_limit = :credit_limit, agent_id = :agent_id, decided_at = now(),
                decision_key = :decision_key,
                handoff_id = (
                    SELECT h.id FROM app.handoffs h
                    WHERE h.conversation_id = app.card_requests.conversation_id
                      AND h.status IN ('queued', 'claimed')
                ),
                product_id = coalesce(:product_id, product_id)
            WHERE id = :id
            """
        ),
        {
            "id": request_id,
            "decision": decision,
            "decline_reason": decline_reason,
            "credit_limit": credit_limit,
            "agent_id": agent_id,
            "decision_key": decision_key,
            "product_id": product_id,
        },
    )


async def write_decision[T](work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    """Run `work` in one transaction (R12): the bank write and the request
    update land together or not at all. Domain errors raised by `work` roll the
    transaction back and propagate; `IntegrityError` propagates untouched for
    `cards.service` to classify; other `SQLAlchemyError`/`OSError` become
    `ToolUnavailable`.
    """
    try:
        async with get_engine().begin() as conn:
            return await work(conn)
    except IntegrityError:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"card request decision failed: {exc}") from exc
