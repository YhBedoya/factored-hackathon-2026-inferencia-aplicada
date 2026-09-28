"""Reset `latam_app` from `latam_golden` from inside the backend (D21).

The in-process twin of `pipeline/load/demo_reset.py` (`make demo-reset`): it
terminates the other backends on both databases, drops the app DB `WITH
(FORCE)` and recreates it as a copy of the golden DB, then clears the Redis
keys that belong to the discarded conversations. Core only: DB and Redis, no
domain import. Closing the LangGraph checkpointer pool is the caller's job
(the admin route), since the pool lives outside `app.core`.
"""

import asyncio
import re
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.redis import get_redis

__all__ = ["reset_app_database"]

# Identifiers are interpolated into DDL (CREATE DATABASE takes no bind params).
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_REDIS_PATTERNS = ("conf:*", "turn:*")


def _admin_dsn(database_url: str) -> str:
    """SQLAlchemy async URL -> psycopg DSN for the `postgres` maintenance DB.

    DROP/CREATE DATABASE are illegal against the database you're connected to.
    """
    parts = urlsplit(database_url)
    return urlunsplit(("postgresql", parts.netloc, "/postgres", parts.query, parts.fragment))


def _recreate(admin_dsn: str, app_db: str, golden_db: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for dbname in (app_db, golden_db):
            conn.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()",
                (dbname,),
            )
        conn.execute(f"DROP DATABASE IF EXISTS {app_db} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {app_db} TEMPLATE {golden_db}")


async def reset_app_database(*, app_db: str = "latam_app", golden_db: str = "latam_golden") -> int:
    """Drop and recreate `app_db` from `golden_db`; return the duration in ms."""
    for ident in (app_db, golden_db):
        if not _IDENT.fullmatch(ident):
            raise ValueError(f"invalid database identifier: {ident!r}")
    started = time.monotonic()
    admin_dsn = _admin_dsn(get_settings().database_url)

    # Release our own pooled connections first, and drop the cached engine so
    # the next `get_engine()` builds a fresh pool against the recreated DB.
    await get_engine().dispose()
    get_engine.cache_clear()

    await asyncio.to_thread(_recreate, admin_dsn, app_db, golden_db)

    redis = get_redis()
    for pattern in _REDIS_PATTERNS:
        keys = [key async for key in redis.scan_iter(match=pattern)]
        if keys:
            await redis.delete(*keys)
    return int((time.monotonic() - started) * 1000)
