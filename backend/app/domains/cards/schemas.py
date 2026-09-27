"""Card read models.

See `docs/solution-docs/04-contracts.md` §1 (`cards.list_cards`,
`cards.get_card_details`).
"""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

__all__ = ["CardDetails", "CardSummary"]


class CardSummary(BaseModel):
    """One row of `cards.list_cards` (credit + debit, all statuses)."""

    model_config = ConfigDict(frozen=True)

    card_id: str
    """`bank.products.product_id` (`"PRD-…"`)."""
    kind: Literal["credit", "debit"]
    last4: str = Field(pattern=r"^\d{4}$")
    """Never the full card number."""
    status: Literal["Active", "Blocked", "Suspended", "Closed"]
    locked: bool
    """`False` until `app.card_controls` exists (D3)."""


class CardDetails(CardSummary):
    """The full detail behind `cards.get_card_details`."""

    currency: str
    expiration_date: date | None
    credit_limit: Decimal | None
    """`None` for debit cards (ADR-020)."""
    current_balance: Decimal | None
    interest_rate: Decimal | None
    """`None` for debit cards."""
    days_past_due: int | None
    """Bucket 0/15/30/60/90/120/180; `None` for debit cards."""
    source: str
    """`"bank.products:<card_id>"`."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_credit(self) -> Decimal | None:
        """`credit_limit - current_balance`. `None` if either is `None`.

        Computed here rather than in the data layer so FakeBank and Postgres
        can't disagree (`02` §4.2, D13). May be negative.
        """
        if self.credit_limit is None or self.current_balance is None:
            return None
        return self.credit_limit - self.current_balance
