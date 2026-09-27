"""The async Redis client and its liveness probe.

The client is created lazily (first call to `get_redis()`) so importing this
module never opens a socket — same reasoning as `app.core.db`.
"""

import asyncio
from functools import lru_cache

from redis.asyncio import Redis

from app.core.config import get_settings

__all__ = ["get_redis", "ping_redis"]

_PING_TIMEOUT_SECONDS = 2.0


@lru_cache
def get_redis() -> Redis:
    """Build the process-wide Redis client on first use."""
    return Redis.from_url(get_settings().redis_url)


async def ping_redis() -> bool:
    """`PING` with a short timeout. Any failure is `False`."""
    try:
        async with asyncio.timeout(_PING_TIMEOUT_SECONDS):
            return bool(await get_redis().ping())
    except Exception:  # liveness probe: any failure means "down", never raise
        return False
