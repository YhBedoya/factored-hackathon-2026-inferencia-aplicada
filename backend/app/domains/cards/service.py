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
import string
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.errors import AccessDenied, Conflict, NotFound, ToolError, ToolUnavailable
from app.domains.cards import repository
from app.domains.cards.schemas import (
    AddressRef,
    BlockReason,
    CardDetails,
    CardRequestDecision,
    CardRequestPanel,
    CardRequestView,
    CardSummary,
    CloseCardReadback,
    CustomerCardRequest,
    DecisionOutcome,
    PanelCard,
    PanelCreditBounds,
    PanelCustomer,
    PanelRequest,
)
from app.domains.customers import service as customers_service
from app.domains.customers.schemas import ProfileField, ProfileValues
from app.domains.localization.format import format_money, local_today, mask_card
from app.domains.policy.card_requests import CardRequestsPolicy
from app.domains.policy.registry import get_policies

__all__ = [
    "AlreadyDecided",
    "BalanceNotZero",
    "BlockState",
    "ClosurePending",
    "DecisionNotAllowed",
    "DeclineReasonInvalid",
    "LimitOutOfBounds",
    "LimitRequired",
    "LockState",
    "ReplacementState",
    "RequestPending",
    "block_card",
    "build_panel",
    "create_close_request",
    "create_open_request",
    "decide_request",
    "get_block_state",
    "get_card_details",
    "get_lock_state",
    "get_replacement",
    "get_request",
    "last_status_actor",
    "list_cards",
    "order_replacement",
    "pending_requests",
    "read_back_close_request",
    "read_back_open_request",
    "recent_requests",
    "set_locked",
]

_CARD_KINDS: dict[str, Literal["credit", "debit"]] = {
    "Tarjeta Crédito": "credit",
    "Tarjeta Débito": "debit",
}


class RequestPending(Conflict):
    """The customer already has an undecided `open` request (AS7, partial unique index)."""

    code: ClassVar[str] = "request_pending"


class ClosurePending(Conflict):
    """The card already has an undecided `close` request (AS7, partial unique index)."""

    code: ClassVar[str] = "closure_pending"


class AlreadyDecided(Conflict):
    """The request already has a decision under another key (`409 already_decided`)."""

    code: ClassVar[str] = "already_decided"


class BalanceNotZero(Conflict):
    """Cancel refused: `current_balance != 0` at the click (`409 balance_not_zero`, D5)."""

    code: ClassVar[str] = "balance_not_zero"


class DecisionNotAllowed(ToolError):
    """approve/decline only on `open`; cancel/keep/not_cancelled_balance only on
    `close` (`422 decision_not_allowed`)."""

    code: ClassVar[str] = "decision_not_allowed"


class LimitRequired(ToolError):
    """Approving a credit card needs a `credit_limit` (`422 limit_required`)."""

    code: ClassVar[str] = "limit_required"


class LimitOutOfBounds(ToolError):
    """`credit_limit` is outside the policy range (`422 limit_out_of_bounds`)."""

    code: ClassVar[str] = "limit_out_of_bounds"


class DeclineReasonInvalid(ToolError):
    """Missing, or not in `card_requests.yaml` `decline_reasons` (`422 decline_reason_invalid`)."""

    code: ClassVar[str] = "decline_reason_invalid"


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


def _to_request_view(row: RowMapping) -> CardRequestView:
    return CardRequestView.model_validate(dict(row))


async def create_open_request(
    customer_id: str,
    conversation_id: UUID,
    card_kind: Literal["credit", "debit"],
    changes: Mapping[ProfileField, str],
    *,
    idempotency_key: str,
) -> CardRequestView:
    """Create one pending `open` request and save the changed profile fields in
    the same transaction (R12, spec D10). `customer_id` is the session's (R1).
    A repeated `idempotency_key` re-reads the stored row; a second pending open
    for the customer raises `RequestPending`.
    """
    existing = await repository.fetch_request_by_key(idempotency_key)
    if existing is not None:
        return _to_request_view(existing)
    request_id = uuid4()

    async def work(conn: AsyncConnection) -> None:
        await repository.insert_open_request(
            conn,
            request_id=request_id,
            reference="CRQ-" + secrets.token_hex(4).upper(),
            customer_id=customer_id,
            conversation_id=conversation_id,
            card_kind=card_kind,
            changed_fields=list(changes),
            idempotency_key=idempotency_key,
        )
        changed = await customers_service.apply_profile_changes(
            conn,
            customer_id,
            changes,
            actor="customer",
            conversation_id=str(conversation_id),
            card_request_id=str(request_id),
        )
        if set(changed) != set(changes):
            # Only the fields that really differ are "saved" (history rows match).
            await repository.update_changed_fields(conn, request_id, list(changed))

    try:
        await repository.write_open_request(work)
    except IntegrityError as exc:
        existing = await repository.fetch_request_by_key(idempotency_key)
        if existing is not None:
            return _to_request_view(existing)  # raced the same key: the winner's row
        if "uq_card_requests_pending_open_customer" in str(exc.orig):
            raise RequestPending("customer already has a pending card request") from exc
        raise
    return await get_request(request_id)


async def get_request(request_id: UUID) -> CardRequestView:
    row = await repository.fetch_request_by_id(request_id)
    if row is None:
        raise NotFound(f"no card request {request_id}")
    return _to_request_view(row)


async def read_back_open_request(request_id: UUID) -> tuple[CardRequestView, ProfileValues]:
    """The re-read behind `request_card`'s `ActionResult.readback` (R3): the
    request row and the customer's current profile values.
    """
    view = await get_request(request_id)
    return view, await customers_service.get_profile_values(view.customer_id)


async def create_close_request(
    customer_id: str,
    conversation_id: UUID,
    card_id: str,
    reason_code: str,
    *,
    idempotency_key: str,
) -> CardRequestView:
    """Create one pending `close` request for `card_id` (spec D9-C, AS7). The
    card must be the session customer's own (R1/R13): `get_card_details` gives
    the existing refusal for another customer's or an unknown card. A repeated
    `idempotency_key` re-reads the stored row; a second pending close on the
    card raises `ClosurePending`.
    """
    existing = await repository.fetch_request_by_key(idempotency_key)
    if existing is not None:
        return _to_request_view(existing)
    card = await get_card_details(customer_id, card_id)
    request_id = uuid4()

    async def work(conn: AsyncConnection) -> None:
        await repository.insert_close_request(
            conn,
            request_id=request_id,
            reference="CRQ-" + secrets.token_hex(4).upper(),
            customer_id=customer_id,
            conversation_id=conversation_id,
            card_kind=card.kind,
            product_id=card.card_id,
            reason_code=reason_code,
            idempotency_key=idempotency_key,
        )

    try:
        await repository.write_close_request(work)
    except IntegrityError as exc:
        existing = await repository.fetch_request_by_key(idempotency_key)
        if existing is not None:
            return _to_request_view(existing)  # raced the same key: the winner's row
        if "uq_card_requests_pending_close_product" in str(exc.orig):
            raise ClosurePending("card already has a pending closure request") from exc
        raise
    return await get_request(request_id)


async def read_back_close_request(request_id: UUID) -> tuple[CardRequestView, CloseCardReadback]:
    """The re-read behind `request_closure`'s `ActionResult.readback` (R3): the
    request row and the card as it is now."""
    view = await get_request(request_id)
    if view.kind != "close" or view.product_id is None:
        raise NotFound(f"no close request {request_id}")
    card = await get_card_details(view.customer_id, view.product_id)
    profile = await customers_service.get_decision_profile(view.customer_id)
    return view, CloseCardReadback(
        last4=card.last4,
        kind=card.kind,
        status=card.status,
        current_balance=card.current_balance,
        currency=card.currency,
        country=profile.country,
    )


async def pending_requests(customer_id: str) -> list[CardRequestView]:
    """The customer's `pending` requests, open and close (R1)."""
    return [_to_request_view(r) for r in await repository.fetch_pending_requests(customer_id)]


async def recent_requests(customer_id: str, limit: int = 3) -> list[CustomerCardRequest]:
    """The customer's latest `limit` requests, newest first, without staff-only fields (R1)."""
    rows = await repository.fetch_recent_requests(customer_id, limit)
    return [CustomerCardRequest.model_validate(dict(row)) for row in rows]


_PRODUCT_TYPES = {"credit": "Tarjeta Crédito", "debit": "Tarjeta Débito"}
_ID_ALPHABET = string.ascii_uppercase + string.digits
_CLOSE_DECISIONS = ("cancel", "keep", "not_cancelled_balance")
_MAX_NUMBER_TRIES = 5  # R11: bounded, then fail loudly (the transaction rolls back)


def _luhn_check_digit(body: str) -> str:
    """The digit that makes `body + digit` pass the Luhn check."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:  # the digit next to the check digit is doubled
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def _new_product_number() -> str:
    """16 digits, Luhn-valid, not starting with 0 (spec AS4)."""
    body = str(secrets.randbelow(9) + 1) + "".join(secrets.choice(string.digits) for _ in range(14))
    return body + _luhn_check_digit(body)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 into a non-leap year
        return d.replace(year=d.year + years, day=28)


def _validate_open_decision(
    row: RowMapping, body: CardRequestDecision, policy: CardRequestsPolicy, currency: str | None
) -> Decimal | None:
    """Spec Contracts 5 validation for approve/decline; returns the limit to store."""
    if row["kind"] != "open" or body.decision not in ("approve", "decline"):
        raise DecisionNotAllowed(f"{body.decision} is not allowed on a {row['kind']} request")
    if body.decision == "decline":
        if body.decline_reason is None or body.decline_reason not in policy.decline_reasons:
            raise DeclineReasonInvalid("decline_reason is missing or not in policy")
        return None
    if row["card_kind"] != "credit":
        return None  # a debit card has no limit (ADR-020)
    if body.credit_limit is None or not body.credit_limit.strip():
        raise LimitRequired("a credit approval needs a credit_limit")
    try:
        limit = Decimal(body.credit_limit.strip())
    except InvalidOperation as exc:
        raise LimitOutOfBounds("credit_limit is not a number") from exc
    bounds = policy.credit_limit_bounds[currency] if currency is not None else None
    if bounds is None or not limit.is_finite() or not bounds.min <= limit <= bounds.max:
        raise LimitOutOfBounds("credit_limit is outside the policy range")
    return limit


async def _decision_verified(
    view: CardRequestView, *, decision_key: str, agent_id: UUID, decision: str
) -> bool:
    """R3: true only if what a fresh read shows is the decision (request row and,
    on approve, the new bank row)."""
    stored = await repository.fetch_request_by_decision_key(decision_key)
    if (
        stored is None
        or stored["id"] != view.id
        or view.status != "decided"
        or view.decision != decision
        or view.agent_id != agent_id
    ):
        return False
    if view.kind == "close":
        if decision != "cancel":
            return True  # no bank write to read back
        product = await repository.fetch_product_row(view.product_id) if view.product_id else None
        history = await repository.fetch_history_by_key(decision_key)
        return (
            product is not None
            and product["customer_id"] == view.customer_id
            and product["product_status"] == "Closed"
            and history is not None
            and history["product_id"] == view.product_id
            and history["new_status"] == "Closed"
        )
    if decision == "decline":
        return view.product_id is None
    if decision != "approve" or view.product_id is None:
        return False
    product = await repository.fetch_product_row(view.product_id)
    return (
        product is not None
        and product["customer_id"] == view.customer_id
        and product["origin"] == "app"
        and product["product_status"] == "Active"
        and product["product_type"] == _PRODUCT_TYPES[view.card_kind]
        and product["conversation_id"] == view.conversation_id
        and product["credit_limit"] == view.credit_limit
    )


async def decide_request(
    request_id: UUID,
    agent_id: UUID,
    body: CardRequestDecision,
    *,
    decision_key: str,
    before_write: Callable[[], Awaitable[None]],
) -> DecisionOutcome:
    """The staff decision on one request (spec AS3, AS4, Contracts 5).

    Lock the row, validate, call `before_write` (the caller's audit hook), then
    write the bank row (approve) and the request update in one transaction
    (R12), and re-read to set `verified` (R3). A known `decision_key` returns
    the stored outcome with `replayed=True` and writes nothing. On a close
    request `cancel` re-reads the balance under the product lock and refuses a
    non-zero one with `BalanceNotZero` before `before_write` (spec D5); it then
    closes the card and writes its history row in the same transaction.
    """
    known = await repository.fetch_request_by_decision_key(decision_key)
    if known is not None:
        if known["id"] != request_id:
            raise AlreadyDecided("that idempotency key belongs to another request")
        return await _replayed(known, decision_key)

    first = await repository.fetch_request_by_id(request_id)
    if first is None:
        raise NotFound(f"no card request {request_id}")
    policy = get_policies().card_requests
    country = None
    currency: str | None = None
    if body.decision == "approve" and first["kind"] == "open":
        country = (await customers_service.get_decision_profile(first["customer_id"])).country
        currency = policy.currency_by_country[country]

    async def work(conn: AsyncConnection) -> RowMapping | None:
        row = await repository.lock_request(conn, request_id)
        if row is None:
            raise NotFound(f"no card request {request_id}")
        if row["decision_key"] == decision_key:
            return row  # raced replay: the winner already wrote it
        if row["status"] != "pending":
            raise AlreadyDecided(f"request {row['reference']} is already decided")
        limit: Decimal | None = None
        if row["kind"] == "close":
            if body.decision not in _CLOSE_DECISIONS:
                raise DecisionNotAllowed(f"{body.decision} is not allowed on a close request")
            if body.decision == "cancel":
                product = await repository.lock_product(conn, row["product_id"])
                if product is None:
                    raise NotFound(f"no product {row['product_id']}")
                if product["current_balance"] != 0:  # fresh, under the lock (AS8)
                    raise BalanceNotZero("the card balance is not zero")
                await before_write()
                await repository.set_product_closed(conn, row["product_id"])
                await repository.insert_status_history(
                    conn,
                    history_id=uuid4(),
                    card_id=row["product_id"],
                    old_status=product["product_status"],
                    new_status="Closed",
                    reason=row["reason_code"],
                    actor=f"staff:{agent_id}",
                    conversation_id=row["conversation_id"],
                    trace_id=None,
                    idempotency_key=decision_key,
                )
            else:
                await before_write()
        else:
            limit = _validate_open_decision(row, body, policy, currency)
            await before_write()
        product_id: str | None = None
        if body.decision == "approve":
            assert country is not None and currency is not None  # set above for approve
            product_id = await _insert_card(conn, row, limit, country, currency, policy)
        await repository.update_request_decision(
            conn,
            request_id,
            decision=body.decision,
            decline_reason=body.decline_reason if body.decision == "decline" else None,
            credit_limit=limit,
            agent_id=agent_id,
            decision_key=decision_key,
            product_id=product_id,
        )
        return None

    try:
        replay_row = await repository.write_decision(work)
    except IntegrityError as exc:
        if await repository.fetch_request_by_decision_key(decision_key) is not None:
            raise AlreadyDecided("raced the same decision key") from exc
        raise
    if replay_row is not None:
        return await _replayed(replay_row, decision_key)
    view = await get_request(request_id)
    verified = await _decision_verified(
        view, decision_key=decision_key, agent_id=agent_id, decision=body.decision
    )
    return DecisionOutcome(request=view, verified=verified)


async def _replayed(row: RowMapping, decision_key: str) -> DecisionOutcome:
    view = _to_request_view(row)
    verified = (
        view.decision is not None
        and view.agent_id is not None
        and await _decision_verified(
            view,
            decision_key=decision_key,
            agent_id=view.agent_id,
            decision=view.decision,
        )
    )
    return DecisionOutcome(request=view, verified=verified, replayed=True)


async def _insert_card(
    conn: AsyncConnection,
    row: RowMapping,
    limit: Decimal | None,
    country: Literal["MX", "CO", "AR"],
    currency: str,
    policy: CardRequestsPolicy,
) -> str:
    """Write the approved card's `bank.products` row (spec AS4); returns its id."""
    for _ in range(_MAX_NUMBER_TRIES):
        number = _new_product_number()
        if not await repository.product_number_exists(conn, number):
            break
    else:
        raise ToolUnavailable("could not allocate a unique card number")
    product_id = "PRD-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(12))
    opened = local_today(country)
    is_credit = row["card_kind"] == "credit"
    await repository.insert_app_product(
        conn,
        product_id=product_id,
        customer_id=row["customer_id"],
        product_type=_PRODUCT_TYPES[row["card_kind"]],
        product_number=number,
        currency=currency,
        credit_limit=limit if is_credit else None,
        interest_rate=policy.interest_rate_by_country[country] if is_credit else Decimal(0),
        opening_date=opened,
        expiration_date=_add_years(opened, policy.expiry_years),
        conversation_id=row["conversation_id"],
    )
    return product_id


async def build_panel(request_id: UUID, language: Literal["es", "pt"]) -> CardRequestPanel:
    """The staff panel for one request (spec Contracts 5). Money and masks are
    formatted here (R4). `language` is accepted for the route's symmetry with
    the localized labels it adds; nothing in the panel is worded here.
    """
    del language
    view = await get_request(request_id)
    profile = await customers_service.get_decision_profile(view.customer_id)
    policy = get_policies().card_requests
    country = profile.country
    currency = policy.currency_by_country[country]
    changed = await customers_service.changed_fields_for_request(str(view.id))

    income = profile.estimated_monthly_income
    customer = PanelCustomer(
        credit_score=profile.credit_score,
        segment=profile.segment,
        tenure_years=profile.tenure_years,
        occupation=profile.occupation,
        occupation_changed="occupation" in changed,
        income_display=(
            format_money(income, customers_service.income_currency(country), country)
            if income is not None
            else None
        ),
        income_changed="estimated_monthly_income" in changed,
    )

    def money(value: object, cur: str) -> str | None:
        return None if value is None else format_money(Decimal(str(value)), cur, country)

    cards = [
        PanelCard(
            mask=mask_card(r["last4"]),
            kind=_CARD_KINDS[r["product_type"]],
            status=r["product_status"],
            balance_display=money(r["current_balance"], r["currency"]),
            credit_limit_display=money(r["credit_limit"], r["currency"]),
        )
        for r in await repository.fetch_customer_cards_panel(view.customer_id)
    ]

    card_mask: str | None = None
    close_balance: str | None = None
    if view.kind == "close" and view.product_id is not None:
        product = await repository.fetch_product_row(view.product_id)
        if product is not None:
            card_mask = mask_card(product["last4"])
            close_balance = money(product["current_balance"], product["currency"])

    bounds = None
    if view.kind == "open" and view.card_kind == "credit":
        b = policy.credit_limit_bounds[currency]
        bounds = PanelCreditBounds(
            currency=currency,
            min=str(b.min),
            max=str(b.max),
            min_display=format_money(b.min, currency, country),
            max_display=format_money(b.max, currency, country),
        )

    return CardRequestPanel(
        request=PanelRequest(
            reference=view.reference,
            kind=view.kind,
            card_kind=view.card_kind,
            card_mask=card_mask,
            reason_code=view.reason_code,
            status=view.status,
            decision=view.decision,
        ),
        customer=customer,
        cards=cards,
        credit_bounds=bounds,
        close_balance_display=close_balance,
    )
