"""NLU output contract for the `understand` node.

See `docs/solution-docs/04-contracts.md` §2 (shape) and
`docs/solution-docs/02-conversation-design.md` §1 (the closed intent catalog).
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Clarification", "Intent", "NLUResult", "NLUSlots", "NLUStatus", "Topic"]

Intent = Literal[
    # Core feature intents (`02` §1)
    "card_status",
    "balance_due",
    "decline_explain",
    "transaction_search",
    "pending_reversal_explain",
    "card_block",
    "card_unlock",
    "unrecognized_charge",
    "replacement_request",
    "human_request",
    "general_question",
    # Conversation-management intents
    "greeting",
    "thanks_close",
    "affirm",
    "deny",
    # Stretch intents
    "travel_notice",
    "spending_limits",
    "card_doctor",
    "expiry_renewal",
    "benefits_info",
    "card_activation",
    "pin_reset",
    "card_cancel",
    "limit_increase",
    "card_finder",
    "prequalification",
]

NLUStatus = Literal["clear", "ambiguous", "out_of_scope", "out_of_market", "injection_suspected"]

Topic = Literal["loans", "accounts", "investments", "insurance", "transfers", "pix_boleto", "other"]

Clarification = Literal["lock_vs_block", "which_card", "which_transaction"]


class NLUSlots(BaseModel):
    """Slots the `understand` node may fill. See `04` §2."""

    model_config = ConfigDict(extra="forbid")

    card_hint: str | None = Field(default=None, pattern=r"^(credit|debit|last4:\d{4})$")
    block_kind: Literal["temporary_lock", "permanent_block"] | None = None
    date_expression: str | None = None
    merchant_text: str | None = None
    amount: Decimal | None = None
    amount_approx: bool = False
    currency: Literal["COP", "ARS", "USD", "MXN"] | None = None
    pending_answer: str | None = None
    topic: Topic | None = None


class NLUResult(BaseModel):
    """One turn's NLU output (`understand` node). See `04` §2.

    `extra="forbid"` so a stray field (e.g. a smuggled `customer_id`) fails
    validation instead of being silently dropped (R1).
    """

    model_config = ConfigDict(extra="forbid")

    language: Literal["es", "pt", "mixed"]
    intents: list[Intent]
    status: NLUStatus
    slots: NLUSlots = Field(default_factory=NLUSlots)
    clarification: Clarification | None = None
