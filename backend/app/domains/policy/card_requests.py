"""Card-request policy, loaded from `policies/card_requests.yaml` (spec D7,
Contracts §1, R8).

Holds the values the open/close card flows and the staff decision read: the
new card's currency and rate per country, the credit-limit bounds per
currency, the per-kind card cap, the expiry span and the two reason-code
lists. Money and rates are decimal strings in the file and `Decimal` here, as
in `disputes.py`. Loaded with the same pattern: a frozen, `extra="forbid"`
model whose required `provenance`/`version` make a header-less file fail to
load, plus a cross-field check for the rules the types can't express.
"""

from decimal import Decimal
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "CardRequestsPolicy",
    "CreditLimitBounds",
    "load_card_requests_policy",
]

# `backend/app/domains/policy/card_requests.py` -> repo root is four parents
# up (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "card_requests.yaml"


class CreditLimitBounds(BaseModel):
    """Inclusive credit-limit range for one currency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min: Decimal
    max: Decimal


class CardRequestsPolicy(BaseModel):
    """`policies/card_requests.yaml`, validated (`04` §5, R8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    currency_by_country: dict[str, str]
    credit_limit_bounds: dict[str, CreditLimitBounds]
    max_cards_per_kind: dict[Literal["credit", "debit"], int]
    interest_rate_by_country: dict[str, Decimal]
    expiry_years: int
    cancel_reasons: list[str]
    decline_reasons: list[str]

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        for country, currency in self.currency_by_country.items():
            if country not in self.interest_rate_by_country:
                raise ValueError(f"country {country} has no interest rate")
            if currency not in self.credit_limit_bounds:
                raise ValueError(f"currency {currency} has no credit-limit bounds")
        for country in self.interest_rate_by_country:
            if country not in self.currency_by_country:
                raise ValueError(f"country {country} has no currency")
        for currency, bounds in self.credit_limit_bounds.items():
            if bounds.min >= bounds.max:
                raise ValueError(f"bounds for {currency}: min must be below max")
        for name, reasons in (
            ("cancel_reasons", self.cancel_reasons),
            ("decline_reasons", self.decline_reasons),
        ):
            if not reasons or "other" not in reasons:
                raise ValueError(f"{name} must be non-empty and contain 'other'")
        return self


def load_card_requests_policy(path: Path | None = None) -> CardRequestsPolicy:
    """Load and validate `policies/card_requests.yaml` (R8).

    `path` defaults to `<repo root>/policies/card_requests.yaml`; tests may
    pass another path to check the rejection rules without touching the real
    file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return CardRequestsPolicy.model_validate(raw)
