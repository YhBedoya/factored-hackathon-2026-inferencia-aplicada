"""FX reference reads behind `reference.get_fx_rate` (D2-B D3).

Calls `repository`, never SQL directly, and raises `NotFound` for a pair
with no row, as `FakeBank.get_fx_rate` does.
"""

from app.core.errors import NotFound
from app.domains.localization import repository
from app.domains.localization.schemas import FxRate

__all__ = ["get_fx_rate"]


async def get_fx_rate(source: str, target: str) -> FxRate:
    row = await repository.fetch_latest_fx_rate(source, target)
    if row is None or row["exchange_rate"] is None:
        raise NotFound(f"no fx rate for {source!r} -> {target!r}")
    return FxRate(source=source, target=target, rate=row["exchange_rate"], as_of=row["date"])
