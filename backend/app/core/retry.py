"""Bounded-retry backoff (R11): full jitter, capped."""

import random

from app.core.config import get_settings

__all__ = ["backoff_delay"]


def backoff_delay(attempt: int) -> float:
    """Seconds to wait after `attempt` (1-based) just failed.

    `uniform(0, min(cap, base * 2 ** (attempt - 1)))`.
    """
    settings = get_settings()
    ceiling = min(settings.retry_backoff_cap_s, settings.retry_backoff_base_s * 2 ** (attempt - 1))
    return random.uniform(0, ceiling)
