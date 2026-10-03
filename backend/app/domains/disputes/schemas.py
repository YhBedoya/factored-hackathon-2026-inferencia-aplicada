"""`ClaimRow`: one `bank.complaints` row this domain wrote or re-read.

See `docs/solution-docs/04-contracts.md` §1 (`disputes.create_claim`, D14,
D7-B SA1) and `disputes.get_priority_signals()` (`04` §1, D7-B B2).
`priority` is `"High"` when `create_claims`' `priority_flags` argument was
non-empty and `NULL` otherwise (SA1); every other claim-lifecycle column
(`status` moves past `"Open"`, `assigned_agent_id`, ...) stays out of this
model, since nothing here reads them yet.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = ["ClaimRow", "PrioritySignals"]


class ClaimRow(BaseModel):
    """What `service.create_claims`/`service.get_claims` return: exactly the
    `bank.complaints` fields D14 fixes, plus the ones `postgres_writes.py`
    needs to verify a re-read against the transaction it was copied from
    (R3).
    """

    model_config = ConfigDict(frozen=True)

    complaint_id: str
    """`"CLM-" + 8 upper hex`."""
    conversation_id: UUID
    customer_id: str
    transaction_id: str
    affected_product_id: str
    claimed_amount: Decimal
    currency: str
    priority: Literal["High"] | None
    status: Literal["Open"]
    origin: Literal["app"]
    creation_date: datetime
    case_type: Literal["Claim"]
    category: Literal["Transactions"]
    subcategory: str
    reception_channel: Literal["App"]
    description: str
    """The answers built in code (D14, spec open item 1), e.g.
    `"card_in_possession=no; contacted_merchant=yes"` -- never customer free
    text."""


class PrioritySignals(BaseModel):
    """`disputes.get_priority_signals()`'s pinned return shape (spec B2): the
    two customer-scoped signals `unrecognized_charge`'s flow (T5) reads to
    build `create_claim`'s `priority_flags` -- never a raw `bank.complaints`
    row, and never the priority-claim rule itself (that stays in
    `policies/disputes.yaml`, R8).
    """

    model_config = ConfigDict(frozen=True)

    repeat_complainer: bool
    open_critical: bool
