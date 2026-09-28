"""The synthetic minimum-payment formula and due date (spec D5, plan P5/P6).

Credit cards only. There is no overdue term: a positive `days_past_due`
surfaces as a separate `payment_overdue` fact built by the caller, never as
an input here (`02` §4.2). The `max`/`min`/rounding shape is code (R4); the
percent and the per-currency floors come from `policies/min_payment.yaml`
(R8), loaded with the `card_select.py` pattern: a frozen, `extra="forbid"`
model whose required `provenance`/`version` make a header-less file fail to
load.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = [
    "DueDatePolicy",
    "MinPaymentAmounts",
    "MinPaymentPolicy",
    "load_min_payment_policy",
    "min_payment",
    "next_due_date",
]

# `backend/app/domains/policy/min_payment.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "min_payment.yaml"

_TWO_PLACES = Decimal("0.01")


class MinPaymentAmounts(BaseModel):
    """The `min_payment` block: percent of balance and a floor per currency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    percent_of_balance: Decimal
    floors: dict[str, Decimal]


class DueDatePolicy(BaseModel):
    """The `due_date` block: the recurring day of month the payment is due."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    due_day_of_month: int


class MinPaymentPolicy(BaseModel):
    """`policies/min_payment.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no formula.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    min_payment: MinPaymentAmounts
    due_date: DueDatePolicy


def load_min_payment_policy(path: Path | None = None) -> MinPaymentPolicy:
    """Load and validate `policies/min_payment.yaml` (R8).

    `path` defaults to `<repo root>/policies/min_payment.yaml`; tests may
    pass another path to check the rejection rule without touching the real
    file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return MinPaymentPolicy.model_validate(raw)


def min_payment(balance: Decimal, currency: str, policy: MinPaymentPolicy) -> Decimal:
    """`min(max(percent x balance, floor[currency]), balance)` (D5, P5).

    `0` when `balance <= 0`. Raises `KeyError` when `currency` has no floor
    in the policy, so a missing currency fails loudly instead of defaulting
    to some other country's floor.
    """
    if balance <= 0:
        return Decimal("0")
    floor = policy.min_payment.floors[currency]
    percent_amount = policy.min_payment.percent_of_balance * balance
    uncapped = max(percent_amount, floor)
    capped = min(uncapped, balance)
    return capped.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def next_due_date(today: date, policy: MinPaymentPolicy) -> date:
    """The next `due_day_of_month`, on or after `today` (D5, P6).

    Rolls over the month, and the year past December, so today being the
    due day itself counts (today is included, not "strictly after").
    """
    day = policy.due_date.due_day_of_month
    if today.day <= day:
        return date(today.year, today.month, day)
    if today.month == 12:
        return date(today.year + 1, 1, day)
    return date(today.year, today.month + 1, day)
