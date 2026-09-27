"""Whole-week date shift for the simulated "now" (D11, 03 §5, ADR-010).

`max_data_date` (the last partition date in the ingested manifest) is shifted
forward by a whole number of weeks so that today's data looks recent while
weekday patterns and relative expressions ("el martes pasado") stay
consistent. The offset itself is computed here; applying it to DATE/TIMESTAMP
columns happens in the dbt serving layer -- raw and staging are never
shifted.
"""

from __future__ import annotations

import math
import os
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingest import ManifestEntry


def date_offset_days(load_date: date, max_data_date: date) -> int:
    """`7 * floor((load_date - max_data_date) / 7)` (D11)."""
    return 7 * math.floor((load_date - max_data_date).days / 7)


def max_data_date_from_manifest(manifest: dict[str, ManifestEntry]) -> date:
    """The latest `year=/month=/day=` partition date among the manifest entries.

    Both sources (`ingest.s3`, `ingest.local`) store `key` relative to the
    source root with the hive segments kept, so this reads `key` the same way
    regardless of which source an entry came from.
    """
    dates: list[date] = []
    for entry in manifest.values():
        year = month = day = None
        for part in PurePosixPath(entry["key"]).parts:
            if part.startswith("year="):
                year = part[len("year=") :]
            elif part.startswith("month="):
                month = part[len("month=") :]
            elif part.startswith("day="):
                day = part[len("day=") :]
        if year is not None and month is not None and day is not None:
            dates.append(date(int(year), int(month), int(day)))

    if not dates:
        raise ValueError("manifest has no partitioned entries to derive max_data_date from")
    return max(dates)


def resolve_load_date() -> date:
    """The `LOAD_DATE` env var (`YYYY-MM-DD`) if set, else today (UTC)."""
    raw = os.environ.get("LOAD_DATE")
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(UTC).date()
