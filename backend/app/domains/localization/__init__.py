"""Money, date, card-mask and label formatting. See `docs/specs/d1-b-agent-sandbox.md` D11.

Code-only, Babel-based; the LLM never writes money, dates or masks (R4).
Imports no other domain.
"""

from app.domains.localization.format import (
    format_date,
    format_money,
    kind_label,
    mask_card,
    status_label,
)

__all__ = [
    "format_date",
    "format_money",
    "kind_label",
    "mask_card",
    "status_label",
]
