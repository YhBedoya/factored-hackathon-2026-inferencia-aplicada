"""Eval clone lifecycle (D13 steps 1 and 8): `latam_eval_<run_id>` from `latam_golden`."""

from __future__ import annotations

import os
import re
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg

GOLDEN_DB = "latam_golden"
_RUN_ID_RE = re.compile(r"^[a-z0-9_]+$")


def dsn(dbname: str, database_url: str | None = None) -> str:
    """`DATABASE_URL` (SQLAlchemy async form) -> a bare psycopg DSN for `dbname`."""
    parts = urlsplit(database_url or os.environ["DATABASE_URL"])
    return urlunsplit(
        ("postgresql", parts.netloc, f"/{dbname}", parts.query, parts.fragment)
    )


def clone_name(run_id: str) -> str:
    # The name is interpolated into DDL, so the run id is restricted to a safe alphabet.
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(f"run_id must match {_RUN_ID_RE.pattern}: {run_id!r}")
    return f"latam_eval_{run_id}"


def _terminate(conn: psycopg.Connection, dbname: str) -> None:
    conn.execute(
        "select pg_terminate_backend(pid) from pg_stat_activity "
        "where datname = %s and pid <> pg_backend_pid()",
        (dbname,),
    )


def create(run_id: str) -> tuple[str, float]:
    """Clone the golden DB. Returns (dbname, seconds); the report states the duration."""
    dbname = clone_name(run_id)
    started = time.monotonic()
    # CREATE DATABASE ... TEMPLATE needs the template idle, so end its sessions first.
    with psycopg.connect(dsn("postgres"), autocommit=True) as conn:
        _terminate(conn, GOLDEN_DB)
        conn.execute(f"CREATE DATABASE {dbname} TEMPLATE {GOLDEN_DB}")
    return dbname, time.monotonic() - started


def drop(dbname: str) -> None:
    """Drop the clone. Idempotent; refuses anything that is not an eval clone."""
    if not dbname.startswith("latam_eval_") or not _RUN_ID_RE.match(dbname):
        raise ValueError(f"refusing to drop non-eval database {dbname!r}")
    with psycopg.connect(dsn("postgres"), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
