"""`uv run python -m load.demo_reset` -- reset `latam_app` from `latam_golden`
(D14, `03-data-architecture.md` §7).

Terminates every other backend connection to both databases (a stale psql or
backend connection would otherwise block the DROP), drops `latam_app` (`WITH
(FORCE)` covers any connection this process itself races against) and
recreates it as a byte-for-byte copy of the golden DB via `CREATE DATABASE
... TEMPLATE`.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg

_APP_DB = "latam_app"
_GOLDEN_DB = "latam_golden"


def _psycopg_dsn(database_url: str, *, dbname: str) -> str:
    """SQLAlchemy async URL -> a bare psycopg-compatible DSN for `dbname`.

    Psycopg only understands `postgresql://` (no `+asyncpg` driver suffix).
    """
    parts = urlsplit(database_url)
    return urlunsplit(("postgresql", parts.netloc, f"/{dbname}", parts.query, parts.fragment))


def _terminate_connections(conn: psycopg.Connection, dbname: str) -> None:
    conn.execute(
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname = %s and pid <> pg_backend_pid()",
        (dbname,),
    )


def reset() -> None:
    """Drop and recreate `latam_app` from `latam_golden`."""
    app_url = os.environ["DATABASE_URL"]
    # Connect to the always-present `postgres` maintenance DB: DROP/CREATE
    # DATABASE are illegal against the database you're connected to.
    admin_dsn = _psycopg_dsn(app_url, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        _terminate_connections(conn, _APP_DB)
        _terminate_connections(conn, _GOLDEN_DB)
        conn.execute(f"DROP DATABASE IF EXISTS {_APP_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {_APP_DB} TEMPLATE {_GOLDEN_DB}")


if __name__ == "__main__":
    reset()
