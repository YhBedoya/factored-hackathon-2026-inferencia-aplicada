"""D5/P5/P6 minimum-payment formula and due date. No FakeBank, no LLM."""

from datetime import date
from decimal import Decimal

from app.domains.policy.min_payment import load_min_payment_policy, min_payment, next_due_date

_POLICY = load_min_payment_policy()


def test_floor_percent_due_date() -> None:
    # The percent wins: 1234.50 * 0.05 = 61.725, ROUND_HALF_UP to 2 places.
    assert min_payment(Decimal("1234.50"), "USD", _POLICY) == Decimal("61.73")

    # The floor wins when the percent falls short of it (balance well above
    # the floor, so the cap never kicks in).
    assert min_payment(Decimal("500000"), "COP", _POLICY) == Decimal("40000")
    assert min_payment(Decimal("60000"), "ARS", _POLICY) == Decimal("5000")

    # Capped at the balance itself, even when both percent and floor exceed it.
    assert min_payment(Decimal("5"), "USD", _POLICY) == Decimal("5")

    # No debt, no minimum payment.
    assert min_payment(Decimal("0"), "USD", _POLICY) == Decimal("0")
    assert min_payment(Decimal("-10"), "USD", _POLICY) == Decimal("0")

    # A currency with no floor in the policy fails loudly.
    try:
        min_payment(Decimal("100"), "BRL", _POLICY)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for a currency with no floor")

    # Due date: on the 10th itself, then rolling over the month and the year.
    assert next_due_date(date(2026, 3, 10), _POLICY) == date(2026, 3, 10)
    assert next_due_date(date(2026, 3, 11), _POLICY) == date(2026, 4, 10)
    assert next_due_date(date(2026, 12, 11), _POLICY) == date(2027, 1, 10)
