"""Transaction read models.

See `docs/solution-docs/04-contracts.md` §1 (`transactions.search`).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["TxFilter", "TxStatus", "TxView"]

TxStatus = Literal["Approved", "Declined", "Pending", "Reversed"]


class TxFilter(BaseModel):
    """The filter accepted by `transactions.search`.

    `merchant_names` replaces `04`'s `merchant_ids`: the data has
    `merchant_name` and no merchant id (D15).
    """

    model_config = ConfigDict(extra="forbid")

    date_from: date | None = None
    date_to: date | None = None
    merchant_names: list[str] = Field(default_factory=list)
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    currency: str | None = None
    status: list[TxStatus] = Field(default_factory=list)
    card_id: str | None = None

    @model_validator(mode="after")
    def _check_date_window(self) -> Self:
        """Reject `date_from > date_to` and a window over 366 days (D15)."""
        if self.date_from is not None and self.date_to is not None:
            if self.date_from > self.date_to:
                raise ValueError("date_from must be <= date_to")
            if (self.date_to - self.date_from).days > 366:
                raise ValueError("date window must not exceed 366 days")
        return self


class TxView(BaseModel):
    """One row of `transactions.search` (at most 10, newest first)."""

    model_config = ConfigDict(frozen=True)

    tx_id: str
    """`"TRX-…"`."""
    card_id: str
    occurred_at: datetime
    """Stored `transaction_date`; time zone per A5 (`07` §8)."""
    amount: Decimal
    currency: str
    amount_usd: Decimal | None
    type: str
    """Purchase/Withdrawal/Transfer/Payment/Deposit/Adjustment."""
    category: str | None
    merchant_name: str | None
    """Untrusted text (R6: data fences downstream)."""
    merchant_category: str | None
    channel: str
    city: str | None
    country: str | None
    status: TxStatus
    response_code: str | None
    """05/14/51/54 on declines."""
    fraud_score: Decimal | None
