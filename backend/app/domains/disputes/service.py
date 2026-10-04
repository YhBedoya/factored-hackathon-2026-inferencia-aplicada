"""Claim writes: read-then-copy-then-insert, one `bank.complaints` row per
disputed transaction (D14), replay-safe per row (D15, keyed
`<idempotency_key>:<tx_id>`), all in one transaction (R12).

`create_claims` reads every transaction through `transactions.service` first
-- the own-row check (R1) runs before anything is written, so a foreign or
unknown `tx_id` raises `AccessDenied`/`NotFound` with no row written for any
of them. `get_claims` is the **separate** re-read `postgres_writes.py` calls
to compute `ActionResult.verified` (R3): a different query against a
different connection, never the same round trip as the write.

`priority_signals` is the B2 read behind `disputes.get_priority_signals`
(R1, SA1): customer-scoped, no `open_statuses` default here -- the caller
(`postgres.py`) reads that list from `policies/disputes.yaml` (R8), never
this module.
"""

import secrets
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.exc import IntegrityError

from app.domains.disputes import repository
from app.domains.disputes.schemas import ClaimRow, PrioritySignals
from app.domains.handoff.schemas import PastClaim
from app.domains.transactions import service as transactions_service

__all__ = ["create_claims", "get_claims", "priority_signals", "recent_claims"]

_CASE_TYPE = "Claim"
_CATEGORY = "Transactions"
_SUBCATEGORY = "Cargo no reconocido"
_RECEPTION_CHANNEL = "App"


def _row_key(idempotency_key: str, tx_id: str) -> str:
    return f"{idempotency_key}:{tx_id}"


def _to_claim_row(row: RowMapping) -> ClaimRow:
    return ClaimRow(
        complaint_id=row["complaint_id"],
        conversation_id=row["conversation_id"],
        customer_id=row["customer_id"],
        transaction_id=row["transaction_id"],
        affected_product_id=row["affected_product_id"],
        claimed_amount=row["claimed_amount"],
        currency=row["currency"],
        priority=row["priority"],
        status=row["status"],
        origin=row["origin"],
        creation_date=row["creation_date"],
        case_type=row["case_type"],
        category=row["category"],
        subcategory=row["subcategory"],
        reception_channel=row["reception_channel"],
        description=row["description"],
    )


async def create_claims(
    customer_id: str,
    conversation_id: UUID,
    tx_ids: list[str],
    answers: list[str],
    priority_flags: list[str],
    idempotency_key: str,
) -> list[ClaimRow]:
    priority: Literal["High"] | None = "High" if priority_flags else None
    row_keys = [_row_key(idempotency_key, tx_id) for tx_id in tx_ids]
    existing = await repository.fetch_claims_by_keys(row_keys)
    if len(existing) == len(tx_ids):  # D15 full replay: nothing mutated
        by_tx_id = {row["transaction_id"]: row for row in existing}
        return [_to_claim_row(by_tx_id[tx_id]) for tx_id in tx_ids]

    # Own-row check (R1): a foreign or unknown tx id raises before any row
    # is built, let alone written.
    transactions = await transactions_service.get_by_ids(customer_id, tx_ids)
    by_tx = {tx.tx_id: tx for tx in transactions}
    # D14 open item 1: the claim's free-text field is the code-built answers
    # string, never customer free text.
    description = "; ".join(answers)
    now = datetime.now(UTC)
    rows = [
        {
            "complaint_id": "CLM-" + secrets.token_hex(4).upper(),
            "creation_date": now,
            "customer_id": customer_id,
            "case_type": _CASE_TYPE,
            "category": _CATEGORY,
            "subcategory": _SUBCATEGORY,
            "reception_channel": _RECEPTION_CHANNEL,
            "affected_product_id": by_tx[tx_id].card_id,
            "claimed_amount": by_tx[tx_id].amount,
            "currency": by_tx[tx_id].currency,
            "priority": priority,
            "status": "Open",
            "origin": "app",
            "conversation_id": conversation_id,
            "transaction_id": tx_id,
            "idempotency_key": _row_key(idempotency_key, tx_id),
            "description": description,
        }
        for tx_id in tx_ids
    ]

    try:
        await repository.insert_claims(rows)
    except IntegrityError:
        # Raced with another call over the same key (D15): re-read instead
        # of treating it as a failure, the same way `cards.service` does.
        existing = await repository.fetch_claims_by_keys(row_keys)
        if len(existing) != len(tx_ids):
            raise
        by_tx_id = {row["transaction_id"]: row for row in existing}
        return [_to_claim_row(by_tx_id[tx_id]) for tx_id in tx_ids]

    # The values just written, not a re-read (that's `get_claims`'s job, R3).
    return [
        ClaimRow(
            complaint_id=row["complaint_id"],
            conversation_id=conversation_id,
            customer_id=customer_id,
            transaction_id=row["transaction_id"],
            affected_product_id=row["affected_product_id"],
            claimed_amount=row["claimed_amount"],
            currency=row["currency"],
            priority=row["priority"],
            status="Open",
            origin="app",
            creation_date=now,
            case_type=_CASE_TYPE,
            category=_CATEGORY,
            subcategory=_SUBCATEGORY,
            reception_channel=_RECEPTION_CHANNEL,
            description=description,
        )
        for row in rows
    ]


async def get_claims(customer_id: str, ids: list[str]) -> list[ClaimRow]:
    """The separate re-read behind `ActionResult.verified` (R3)."""
    rows = await repository.fetch_claims_by_ids(customer_id, ids)
    return [_to_claim_row(row) for row in rows]


async def priority_signals(customer_id: str, open_statuses: list[str]) -> PrioritySignals:
    """`disputes.get_priority_signals()`'s read (R1, spec B2)."""
    row = await repository.fetch_priority_signals(customer_id, open_statuses)
    return PrioritySignals(
        repeat_complainer=row["repeat_complainer"], open_critical=row["open_critical"]
    )


async def recent_claims(customer_id: str, since: datetime, limit: int) -> list[PastClaim]:
    """The customer's claims from `since`, newest first, for the handoff
    packet's history (R1)."""
    rows = await repository.fetch_recent_claims(customer_id, since, limit)
    return [
        PastClaim(
            claim_id=row["complaint_id"],
            category=row["category"],
            status=row["status"],
            created_at=row["creation_date"],
        )
        for row in rows
    ]
