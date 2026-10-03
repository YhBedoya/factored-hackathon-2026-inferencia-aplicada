"""R4 (money, dates and card masks are formatted in code) tests for
`localization.format`. See `docs/specs/d2-b-card-info-block.md` §"Test list"
(`test_format.py`) and decisions D17, D18.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.domains.localization.format import (
    format_date,
    format_money,
    format_time,
    mask_card,
    mxn_estimate,
)
from app.domains.localization.schemas import FxRate


def test_money_dates_masks_three_countries() -> None:
    """One country pattern each for MX, CO and AR (D18), plus the MXN
    estimate footnote in ES and PT, a day-first date and a card mask.
    """
    assert format_money(Decimal("1234.50"), "USD", "MX") == "US$1,234.50"
    assert format_money(Decimal("1234567"), "COP", "CO") == "COP $1.234.567"
    assert format_money(Decimal("1234.50"), "ARS", "AR") == "ARS $ 1.234,50"

    fx = FxRate(source="USD", target="MXN", rate=Decimal("17.40"), as_of=date(2026, 3, 12))
    assert mxn_estimate(Decimal("1234.50"), fx, "es") == (
        "(≈ MXN $21,480.30, tipo de cambio del 12/03/2026)"
    )
    assert mxn_estimate(Decimal("1234.50"), fx, "pt") == (
        "(≈ MXN $21,480.30, câmbio de 12/03/2026)"
    )

    assert format_date(date(2026, 3, 12)) == "12/03/2026"
    assert mask_card("1234") == "•••• 1234"

    at = datetime(2026, 3, 12, 18, 0, tzinfo=UTC)
    assert format_time(at, "MX") == "12:00"
