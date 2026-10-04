"""USD per million (input, output) tokens per model id. See D9, D28.

List prices from https://platform.claude.com/docs/en/about-claude/pricing, checked 2026-09-29:
Sonnet 5.5 $2 input / $10 output per MTok; Sonnet 4.6 $3 / $15; Haiku 4.5 $1 / $5.
Bedrock is billed by AWS and may differ; the Bedrock ids reuse the first-party price
as an estimate.
An id missing here gives `cost_usd=None` in the ledger.
"""

from decimal import Decimal

__all__ = ["PRICE_PER_MTOK", "cost_usd"]

_SONNET_5_5 = (Decimal("2.00"), Decimal("10.00"))
_SONNET_4_6 = (Decimal("3.00"), Decimal("15.00"))
_HAIKU_4_5 = (Decimal("1.00"), Decimal("5.00"))

PRICE_PER_MTOK: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-5-5": _SONNET_5_5,
    "us.anthropic.claude-sonnet-4-6": _SONNET_4_6,
    "claude-haiku-4-5-20251001": _HAIKU_4_5,
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": _HAIKU_4_5,
}


def cost_usd(model_id: str, input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    """Cost of one call, or `None` when the model has no price or tokens are unknown."""
    price = PRICE_PER_MTOK.get(model_id)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (price[0] * input_tokens + price[1] * output_tokens) / Decimal(1_000_000)
