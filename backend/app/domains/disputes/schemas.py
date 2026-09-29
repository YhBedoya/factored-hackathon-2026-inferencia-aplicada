"""`ClaimRow`: one `bank.complaints` row this domain wrote or re-read.

See `docs/solution-docs/04-contracts.md` §1 (`disputes.create_claim`) and D14.
`priority` and every claim-lifecycle column (`status` moves past `"Open"`,
`assigned_agent_id`, ...) stay out of this model: D14 fixes `priority` to
`NULL` and D16 defers `priority_flags`, so nothing here reads them yet.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

__all__ = ["ClaimRow"]


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
