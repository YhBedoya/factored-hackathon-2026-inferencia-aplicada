"""Transaction search.

Applies every `TxFilter` field the way `FakeBank.search_transactions` does,
except card ownership: this module does not call `cards.service` to check
it, because `PostgresBank` (the tool-registry wrapper) checks ownership
first and only calls here once it has passed (D11). It still always
filters by `customer_id` (R1).

`get_by_ids` is D4-B's own-row lookup, used by `disputes.service` before any
claim is written: an id owned by another customer raises `AccessDenied`, an
unknown one raises `NotFound`, both before the probe reveals anything beyond
"exists somewhere" (`repository.probe_transactions_exist`, D17 R1).

`get_declined` is `transactions.explain_decline`'s own-row lookup (spec
`d5-b-decline-explainer-test-sets.md` D4): unlike `get_by_ids`, a foreign
id is `NotFound`, not `AccessDenied` -- explaining a decline never confirms
that some other customer's transaction exists, so there is no second,
narrower probe. A non-`Declined` own row is `NotFound` too, since there is
nothing to explain.
"""

import base64
from datetime import datetime

from sqlalchemy import RowMapping

from app.core.errors import AccessDenied, NotFound
from app.domains.transactions import repository
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["InvalidCursor", "get_by_ids", "get_declined", "list_page", "search"]


class InvalidCursor(ValueError):
    """The page cursor isn't one `list_page` issued (the API maps it to 422)."""


def _encode_cursor(view: TxView) -> str:
    raw = f"{view.occurred_at.isoformat()}|{view.tx_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_text, tx_id = raw.split("|", 1)
        ts = datetime.fromisoformat(ts_text)
    except ValueError as exc:  # includes UnicodeDecodeError and binascii.Error
        raise InvalidCursor("malformed cursor") from exc
    if ts.tzinfo is None or not tx_id:
        raise InvalidCursor("malformed cursor")
    return ts, tx_id


def _to_view(row: RowMapping) -> TxView:
    return TxView(
        tx_id=row["transaction_id"],
        card_id=row["product_id"],
        occurred_at=row["occurred_at"],
        amount=row["amount"],
        currency=row["currency"],
        amount_usd=row["amount_usd"],
        type=row["transaction_type"],
        category=row["transaction_category"],
        merchant_name=row["merchant_name"],
        merchant_category=row["merchant_category"],
        channel=row["channel"],
        city=row["transaction_city"],
        country=row["transaction_country"],
        status=row["transaction_status"],
        response_code=row["response_code"],
        fraud_score=row["fraud_score"],
    )


async def search(customer_id: str, tx_filter: TxFilter) -> list[TxView]:
    rows = await repository.fetch_transactions(customer_id, tx_filter)
    return [_to_view(row) for row in rows]


async def list_page(
    customer_id: str, tx_filter: TxFilter, cursor: str | None, limit: int = 20
) -> tuple[list[TxView], str | None]:
    """One keyset page, newest first, and the cursor for the next one (`None`
    on the last page). Like `search`, it does not check card ownership: the
    caller does, before paging (R1 still holds: always `customer_id`).
    """
    after = _decode_cursor(cursor) if cursor is not None else None
    rows = await repository.fetch_transactions_page(customer_id, tx_filter, after, limit + 1)
    views = [_to_view(row) for row in rows[:limit]]
    next_cursor = _encode_cursor(views[-1]) if len(rows) > limit else None
    return views, next_cursor


async def get_by_ids(customer_id: str, tx_ids: list[str]) -> list[TxView]:
    """`tx_ids`' own rows, in the same order, but only when every one of them
    belongs to `customer_id` (own-row-first, R1). Raises `AccessDenied` if
    any missing id exists for another customer, `NotFound` if none of the
    missing ids exist at all.
    """
    rows = await repository.fetch_transactions_by_ids(customer_id, tx_ids)
    by_id = {row["transaction_id"]: row for row in rows}
    missing = [tx_id for tx_id in tx_ids if tx_id not in by_id]
    if missing:
        existing = await repository.probe_transactions_exist(missing)
        if existing:
            foreign_id = sorted(existing)[0]
            raise AccessDenied(f"transaction {foreign_id!r} does not belong to this customer")
        raise NotFound(f"no transaction {missing[0]!r}")
    return [_to_view(by_id[tx_id]) for tx_id in tx_ids]


async def get_declined(customer_id: str, tx_id: str) -> TxView:
    """`tx_id`'s own row, but only when it belongs to `customer_id` and its
    `status` is `"Declined"` (R1, D4). A missing id, another customer's id
    or a non-`Declined` row are all `NotFound` alike -- no `AccessDenied`
    and no existence probe, unlike `get_by_ids`.
    """
    rows = await repository.fetch_transactions_by_ids(customer_id, [tx_id])
    if not rows or rows[0]["transaction_status"] != "Declined":
        raise NotFound(f"no declined transaction {tx_id!r}")
    return _to_view(rows[0])
