"""Card reads (`list_cards`, `get_card_details`) and the D3-A3 raw writes
`PostgresBankWrites` calls (`set_locked`, `block_card`, `order_replacement`,
plus their re-reads).

Reads mirror `FakeBank.list_cards`/`get_card_details`'s own-row-first,
existence-probe-second pattern (D1-B D17, D11, D12): an owned non-card
product is `NotFound`, and a card id that belongs to another customer is
told apart from an unknown one only by the narrow `fetch_card_probe`
column. `locked` now comes from `app.card_controls` (D3-A3, the `left join`
in `repository.fetch_cards`/`fetch_card_details`).

D9-D11: each write function first checks `repository.fetch_*_by_key` for
`idempotency_key` -- a hit means some earlier call (this turn's checkpoint
replay, or a genuine race) already wrote this exact step, so the function
returns without touching anything, and the caller's own re-read (in
`conversation/tools/postgres_writes.py`) reports whatever that earlier
write left behind. A unique-violation `IntegrityError` racing the same key
is treated the same way: it means another call won the write between this
one's own check and its `INSERT`/`UPDATE`, so this one re-reads by key
instead of failing. `block_card` runs inside `repository.write_block`'s one
transaction (R12): the status flip and the history row either both land or
neither does.

See `docs/specs/d2-a-login-read-tools-api.md` D11, D12 and
`docs/specs/d3-a-guardrails-write-path.md` D9-D11.
"""

import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import RowMapping
from sqlalchemy.exc import IntegrityError

from app.core.errors import AccessDenied, NotFound
from app.domains.cards import repository
from app.domains.cards.schemas import AddressRef, BlockReason, CardDetails, CardSummary

__all__ = [
    "BlockState",
    "LockState",
    "ReplacementState",
    "block_card",
    "get_block_state",
    "get_card_details",
    "get_lock_state",
    "get_replacement",
    "last_status_actor",
    "list_cards",
    "order_replacement",
    "set_locked",
]

_CARD_KINDS: dict[str, Literal["credit", "debit"]] = {
    "Tarjeta Crédito": "credit",
    "Tarjeta Débito": "debit",
}


class LockState(BaseModel):
    """The re-read behind `lock_card`/`unlock_card`'s `ActionResult.readback` (R3)."""

    model_config = ConfigDict(frozen=True)

    locked: bool
    at: datetime


class BlockState(BaseModel):
    """The re-read behind `block_card`'s `ActionResult.readback` (R3)."""

    model_config = ConfigDict(frozen=True)

    status: str
    at: datetime


class ReplacementState(BaseModel):
    """The re-read behind `order_replacement`'s `ActionResult.readback` (R3)."""

    model_config = ConfigDict(frozen=True)

    status: str
    at: datetime
    tracking_id: str


def _to_summary(row: RowMapping) -> CardSummary:
    return CardSummary(
        card_id=row["product_id"],
        kind=_CARD_KINDS[row["product_type"]],
        last4=row["last4"],
        status=row["product_status"],
        locked=row["locked"],
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


async def set_locked(
    customer_id: str, card_id: str, *, locked: bool, actor: str, idempotency_key: str
) -> None:
    """Upsert `app.card_controls` for `card_id` (D9-D11)."""
    existing = await repository.fetch_control_by_key(idempotency_key)
    if existing is not None:
        return  # D11 replay: nothing mutated
    try:
        rowcount = await repository.upsert_lock(
            customer_id, card_id, locked=locked, actor=actor, idempotency_key=idempotency_key
        )
    except IntegrityError:
        existing = await repository.fetch_control_by_key(idempotency_key)
        if existing is None:
            raise
        return
    if rowcount == 0:
        raise AccessDenied(f"card {card_id!r} does not belong to this customer")


async def get_lock_state(customer_id: str, card_id: str) -> LockState:
    row = await repository.fetch_lock_row(customer_id, card_id)
    if row is None:
        # No `app.card_controls` row yet: the card was never locked. Callers
        # only re-read right after `set_locked` has run, which always
        # upserts a row, so this branch means "never written", not "the
        # write we just did vanished".
        return LockState(locked=False, at=datetime.now(UTC))
    return LockState(locked=row["locked"], at=row["updated_at"])


async def block_card(
    customer_id: str,
    card_id: str,
    *,
    reason: BlockReason,
    actor: str,
    conversation_id: UUID | None,
    trace_id: str | None,
    idempotency_key: str,
) -> None:
    """Flip `bank.products.product_status` to `"Blocked"` and insert one
    `app.card_status_history` row, in `repository.write_block`'s one
    transaction (R12, D9-D10).
    """
    existing = await repository.fetch_history_by_key(idempotency_key)
    if existing is not None:
        return  # D11 replay: nothing mutated
    try:
        old_status = await repository.write_block(
            customer_id,
            card_id,
            new_status="Blocked",
            reason=reason,
            actor=actor,
            conversation_id=conversation_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            history_id=uuid4(),
        )
    except IntegrityError:
        existing = await repository.fetch_history_by_key(idempotency_key)
        if existing is None:
            raise
        return
    if old_status is None:
        raise AccessDenied(f"card {card_id!r} does not belong to this customer")


async def get_block_state(customer_id: str, card_id: str) -> BlockState:
    row = await repository.fetch_status_state(customer_id, card_id)
    if row is None:
        raise NotFound(f"no card {card_id!r}")
    at = row["history_at"] if row["history_at"] is not None else datetime.now(UTC)
    return BlockState(status=row["product_status"], at=at)


async def last_status_actor(customer_id: str, card_id: str) -> str | None:
    """The `actor` of `card_id`'s latest `app.card_status_history` row, or
    `None` if it has none yet (D10's `get_block_origin` `customer_block` check).
    """
    row = await repository.fetch_status_state(customer_id, card_id)
    if row is None:
        return None
    actor: str | None = row["history_actor"]
    return actor


async def order_replacement(
    customer_id: str,
    card_id: str,
    *,
    address_ref: AddressRef,
    address_changed: bool,
    conversation_id: UUID | None,
    idempotency_key: str,
) -> UUID:
    """Insert one `app.card_replacements` row and return its id. Never
    resolves or stores a raw address (D9): `address_ref` stays the opaque
    token or `"on_file"` the caller passed in.
    """
    existing = await repository.fetch_replacement_by_key(idempotency_key)
    if existing is not None:
        replacement_id: UUID = existing["id"]
        return replacement_id  # D11 replay: nothing mutated
    replacement_id = uuid4()
    tracking_id = "RPL-" + secrets.token_hex(4).upper()
    try:
        rowcount = await repository.insert_replacement(
            customer_id,
            card_id,
            replacement_id=replacement_id,
            address_ref=address_ref,
            address_changed=address_changed,
            tracking_id=tracking_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = await repository.fetch_replacement_by_key(idempotency_key)
        if existing is None:
            raise
        return existing["id"]
    if rowcount == 0:
        raise AccessDenied(f"card {card_id!r} does not belong to this customer")
    return replacement_id


async def get_replacement(customer_id: str, card_id: str, replacement_id: UUID) -> ReplacementState:
    row = await repository.fetch_replacement_by_id(customer_id, card_id, replacement_id)
    if row is None:
        raise NotFound(f"no replacement {replacement_id} for card {card_id!r}")
    return ReplacementState(
        status=row["status"], at=row["created_at"], tracking_id=row["tracking_id"]
    )
