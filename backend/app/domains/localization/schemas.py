"""Reference-data shapes for `localization`. See `docs/specs/d2-b-card-info-block.md`
§"Contracts" (`FxRate`) and decision D3.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

__all__ = ["FxRate"]


class FxRate(BaseModel):
    """The latest `daily_exchange_rates` row for one currency pair (D3).

    Reference data, not customer data: `BankReadTools.get_fx_rate` has no
    customer filter (R1 doesn't apply). `format.py`'s MXN-estimate footnote
    (D18) reads `rate` and `as_of`; the currency codes let it label the pair.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    rate: Decimal
    as_of: date
