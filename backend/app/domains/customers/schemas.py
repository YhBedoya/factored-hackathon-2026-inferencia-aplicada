"""Customer read model.

See `docs/solution-docs/04-contracts.md` §1 (`customers.get_profile`).
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "PROFILE_FIELDS",
    "CustomerProfile",
    "DecisionProfile",
    "ProfileField",
    "ProfileFormReadOnly",
    "ProfileFormView",
    "ProfileValues",
]

ProfileField = Literal["email", "mobile_phone", "address", "occupation", "estimated_monthly_income"]
# The one order every list of changed fields follows (I7).
PROFILE_FIELDS: tuple[ProfileField, ...] = (
    "email",
    "mobile_phone",
    "address",
    "occupation",
    "estimated_monthly_income",
)


class CustomerProfile(BaseModel):
    """The masked profile behind `customers.get_profile`.

    `load_session` uses `country` to seed NLU context and `customer_status`
    for ADR-021 status precedence. `first_name` lets Cardy address the
    customer by name (`docs/brand.md`); it is PII, so it only ever reaches
    the LLM as the `{customer_name}` placeholder key, never as a value
    (R5). `city` is PII too, and only ever reaches a reply as the masked
    `•••, <city>` delivery-address label (D2-B D4), never the raw address.
    See `04` §1.
    """

    model_config = ConfigDict(frozen=True)

    country: Literal["MX", "CO", "AR"]
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]
    first_name: str | None = None
    city: str | None = None


class ProfileValues(BaseModel):
    """The five editable profile values; income is a `Decimal`, the rest trimmed text."""

    model_config = ConfigDict(frozen=True)

    email: str
    mobile_phone: str
    address: str
    occupation: str
    estimated_monthly_income: Decimal


class ProfileFormReadOnly(BaseModel):
    model_config = ConfigDict(frozen=True)

    full_name: str
    document_masked: str
    date_of_birth_display: str


class ProfileFormView(BaseModel):
    """`GET /conversations/{id}/profile-form` body (D9-C spec §5). Never persisted."""

    model_config = ConfigDict(frozen=True)

    editable: ProfileValues
    read_only: ProfileFormReadOnly
    income_currency: Literal["MXN", "COP", "ARS"]
    # Set by the route from the pending pause's `card_request_kind`: the profile
    # service has no conversation. The default only covers a service-level read.
    card_kind: Literal["credit", "debit"] = "credit"


class DecisionProfile(BaseModel):
    """What the staff panel shows next to a card request (D9-C spec §5)."""

    model_config = ConfigDict(frozen=True)

    credit_score: float | None
    segment: str | None
    tenure_years: int | None
    occupation: str | None
    estimated_monthly_income: Decimal | None
    country: Literal["MX", "CO", "AR"]
