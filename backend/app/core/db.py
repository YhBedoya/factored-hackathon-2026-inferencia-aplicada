"""The async Postgres engine and its liveness probe.

The engine is created lazily (first call to `get_engine()`) so importing this
module never opens a socket — needed for `Settings` to import cleanly with no
env configured, and for the health route to fail soft instead of at import
time.
"""

import asyncio
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

__all__ = ["get_engine", "ping_db"]

_PING_TIMEOUT_SECONDS = 2.0


@lru_cache
def get_engine() -> AsyncEngine:
    """Build the process-wide async engine on first use."""
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def ping_db() -> bool:
    """`SELECT 1` against the app DB with a short timeout. Any failure is `False`."""
    try:
        async with asyncio.timeout(_PING_TIMEOUT_SECONDS):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # liveness probe: any failure means "down", never raise
        return False
