"""Postgres reads for `bank.daily_exchange_rates`.

Mirrors `FakeBank.get_fx_rate`'s SQL (`app/domains/conversation/tools/fakebank.py`):
the latest row for one currency pair. Reference data, so no `customer_id`
filter (D2-B D3). The `NotFound` decision for a missing pair happens in
`service.py`, not here.
"""

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable

__all__ = ["fetch_latest_fx_rate"]


async def fetch_latest_fx_rate(source: str, target: str) -> RowMapping | None:
    """`date`, `exchange_rate` of the latest `source -> target` row, or `None`."""
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT date, exchange_rate
                    FROM bank.daily_exchange_rates
                    WHERE source_currency = :source AND target_currency = :target
                    ORDER BY date DESC
                    LIMIT 1
                    """
                ),
                {"source": source, "target": target},
            )
            row = result.mappings().first()
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"fx rate query failed: {exc}") from exc
    return row
