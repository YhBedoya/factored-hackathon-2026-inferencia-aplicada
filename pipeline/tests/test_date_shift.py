"""D11 / A5: the date-shift offset is a whole number of weeks (spec Test list)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from load.date_shift import date_offset_days

MAX_DATA_DATE = date(2026, 6, 17)


@pytest.mark.parametrize(
    "load_date",
    [
        MAX_DATA_DATE,  # offset must be exactly 0
        MAX_DATA_DATE + timedelta(days=1),
        MAX_DATA_DATE + timedelta(days=6),
        MAX_DATA_DATE + timedelta(days=7),
        MAX_DATA_DATE + timedelta(days=8),
        MAX_DATA_DATE + timedelta(days=100),
        date(2026, 9, 27),  # today, as of writing this test
    ],
)
def test_offset_is_whole_weeks(load_date: date) -> None:
    offset = date_offset_days(load_date, MAX_DATA_DATE)

    assert offset % 7 == 0
    shifted = MAX_DATA_DATE + timedelta(days=offset)
    assert load_date - timedelta(days=7) < shifted <= load_date

    if load_date == MAX_DATA_DATE:
        assert offset == 0
