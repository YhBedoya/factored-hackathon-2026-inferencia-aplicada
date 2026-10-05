"""Card read models.

See `docs/solution-docs/04-contracts.md` §1 (`cards.list_cards`,
`cards.get_card_details`).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

__all__ = [
    "AddressRef",
    "BlockOrigin",
    "BlockReason",
    "CardDetails",
    "CardRequestDecision",
    "CardRequestDecisionResult",
    "CardRequestPanel",
    "CardRequestView",
    "CardSummary",
    "CloseCardReadback",
    "CustomerCardRequest",
    "DecisionName",
    "DecisionOutcome",
    "PanelCard",
    "PanelCreditBounds",
    "PanelCustomer",
    "PanelRequest",
]

BlockReason = Literal["lost_or_stolen", "suspected_fraud"]

AddressRef = str
"""`"on_file"` (the address in `bank.customers`) or a PII-vault token for an
address the customer typed (`⟨ADDR_n⟩`, `01` §5), resolved server-side by the
raw tool. The raw address never enters the LLM, state or checkpoint (R5, D12).
"""


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


class BlockOrigin(BaseModel):
    """`cards.get_block_origin`'s result: who put the card in its current state.

    `reason` is non-`None` only for `kind="bank_side"` (`02` §4.6-4.8, D11):
    it is what picks Cobranza vs. Fraudes when the customer wants it undone.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["customer_lock", "customer_block", "bank_side", "none"]
    reason: Literal["past_due", "fraud", "customer_status", "bank_status"] | None


class CardRequestView(BaseModel):
    """One row of `app.card_requests` (`03` §6, spec D9-C "Contracts" 4).

    `product_id` is the card to close, or the new card once an open is approved.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID
    reference: str
    customer_id: str
    conversation_id: UUID
    handoff_id: UUID | None
    kind: Literal["open", "close"]
    card_kind: Literal["credit", "debit"]
    product_id: str | None
    reason_code: str | None
    changed_fields: list[str]
    status: Literal["pending", "decided"]
    decision: Literal["approve", "decline", "cancel", "keep", "not_cancelled_balance"] | None
    decline_reason: str | None
    credit_limit: Decimal | None
    agent_id: UUID | None
    decided_at: datetime | None
    created_at: datetime


class CustomerCardRequest(BaseModel):
    """One of the customer's own card requests, as Cardy may read it.

    No `decline_reason`, `agent_id` or `customer_id`: the reason is staff-only
    (`card_requests.yaml`), so it is absent from the type, not filtered later.
    """

    model_config = ConfigDict(frozen=True)

    reference: str
    kind: Literal["open", "close"]
    card_kind: Literal["credit", "debit"]
    status: Literal["pending", "decided"]
    decision: Literal["approve", "decline", "cancel", "keep", "not_cancelled_balance"] | None
    product_id: str | None
    credit_limit: Decimal | None
    created_at: datetime
    decided_at: datetime | None


class CloseCardReadback(BaseModel):
    """The card behind a close request, re-read for `request_closure`'s
    read-back (R3). Money is raw; the caller formats it (R4)."""

    model_config = ConfigDict(frozen=True)

    last4: str
    kind: Literal["credit", "debit"]
    status: str
    current_balance: Decimal
    currency: str
    country: Literal["MX", "CO", "AR"]


DecisionName = Literal["approve", "decline", "cancel", "keep", "not_cancelled_balance"]
"""The five staff decisions (`app.card_requests.decision`)."""


class PanelRequest(BaseModel):
    """`CardRequestPanel.request` (spec D9-C Contracts 5)."""

    model_config = ConfigDict(frozen=True)

    reference: str
    kind: Literal["open", "close"]
    card_kind: Literal["credit", "debit"]
    card_mask: str | None = None
    """`•••• 1234` of the card to close; `None` for an opening."""
    reason_code: str | None = None
    reason_label: str | None = None
    """Localized label of `reason_code`. The wording lives in
    `conversation.card_request_messages`, which `cards` can't import, so the
    staff route fills it in."""
    status: Literal["pending", "decided"]
    decision: DecisionName | None = None


class PanelCustomer(BaseModel):
    model_config = ConfigDict(frozen=True)

    credit_score: float | None
    segment: str | None
    tenure_years: int | None
    occupation: str | None
    occupation_changed: bool
    income_display: str | None
    """Declared income in the country's local currency, formatted in code (R4, AS6)."""
    income_changed: bool


class PanelCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    mask: str
    kind: Literal["credit", "debit"]
    status: str
    balance_display: str | None
    credit_limit_display: str | None


class PanelCreditBounds(BaseModel):
    """The policy range the credit limit must fall in (open credit request only)."""

    model_config = ConfigDict(frozen=True)

    currency: str
    min: str
    max: str
    min_display: str
    max_display: str


class CardRequestPanel(BaseModel):
    """`GET /staff/handoffs/{id}/card-request` (spec D9-C Contracts 5). Money
    and masks are filled in code (R4); the `*_changed` flags come from the
    `customer_profile_history` rows linked to the request."""

    model_config = ConfigDict(frozen=True)

    request: PanelRequest
    customer: PanelCustomer
    cards: list[PanelCard]
    credit_bounds: PanelCreditBounds | None = None
    close_balance_display: str | None = None


class CardRequestDecision(BaseModel):
    """Body of `POST /staff/handoffs/{id}/card-request/decision`."""

    model_config = ConfigDict(frozen=True)

    decision: DecisionName
    credit_limit: str | None = None
    decline_reason: str | None = None


class DecisionOutcome(BaseModel):
    """What `cards.service.decide_request` returns."""

    model_config = ConfigDict(frozen=True)

    request: CardRequestView
    verified: bool
    """True only when a re-read after the write matches the decision (R3)."""
    replayed: bool = False
    """True when the `decision_key` was already used: nothing was written."""


class CardRequestDecisionResult(BaseModel):
    """The decision route's response."""

    model_config = ConfigDict(frozen=True)

    request: CardRequestView
    verified: bool
    message_id: UUID | None = None
