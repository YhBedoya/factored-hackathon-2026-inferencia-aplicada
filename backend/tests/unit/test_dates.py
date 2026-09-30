"""A3 (`resolve_date_expression`'s fixed ES/PT phrases) tests.

See `docs/specs/d7-b-transactions-traceability-judge.md` §"Test list"
(`test_dates.py`) and Assumptions A3. Pure function, no FakeBank, no LLM.
"""

from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo

import pytest

from app.domains.localization.dates import resolve_date_expression

# Thu 2026-04-02, `America/Mexico_City` (this card's fixed test clock).
_TODAY = date(2026, 4, 2)
_TZ = ZoneInfo("America/Mexico_City")


@pytest.mark.parametrize(
    ("language", "expr", "expected"),
    [
        ("es", "martes pasado", (date(2026, 3, 31), date(2026, 3, 31))),
        ("pt", "terça passada", (date(2026, 3, 31), date(2026, 3, 31))),
        ("es", "ayer", (date(2026, 4, 1), date(2026, 4, 1))),
        ("pt", "há 3 dias", (date(2026, 3, 30), date(2026, 3, 30))),
        ("es", "12 de marzo", (date(2026, 3, 12), date(2026, 3, 12))),
        ("es", "el mes que viene", None),
    ],
)
def test_resolve_expressions(
    language: Literal["es", "pt"],
    expr: str,
    expected: tuple[date, date] | None,
) -> None:
    assert resolve_date_expression(expr, _TODAY, _TZ, language) == expected
