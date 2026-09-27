"""`uv run python -m load` -- dbt build -> load `bank.*` -> demo reset (D11, D14).

Order: resolve the whole-week date offset from the ingest manifest, `dbt
build` the serving layer with that offset, create `latam_golden` if it
doesn't exist yet and run Alembic against it, TRUNCATE + COPY the 13
`bank.*` tables from dbt's `srv_*` models, write one `app.system_metadata`
row, print each table's row count, then reset `latam_app` from the fresh
golden DB (03 §7).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg

from ingest import ManifestEntry, load_manifest
from load import demo_reset
from load.date_shift import date_offset_days, max_data_date_from_manifest, resolve_load_date
from load.postgres import TABLES, copy_all

# `load/__main__.py` -> `load/` -> `pipeline/` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "pipeline" / "dbt"
BACKEND_DIR = REPO_ROOT / "backend"
WAREHOUSE_PATH = str(REPO_ROOT / "data" / "pipeline.duckdb")

_GOLDEN_DB = "latam_golden"


def _psycopg_dsn(database_url: str, *, dbname: str | None = None) -> str:
    """SQLAlchemy async URL -> a bare psycopg-compatible DSN.

    Psycopg only understands `postgresql://` (no `+asyncpg` driver suffix).
    An explicit `dbname` swaps the path, e.g. to the always-present
    `postgres` maintenance DB for `CREATE DATABASE` (illegal against the DB
    you're connected to).
    """
    parts = urlsplit(database_url)
    path = f"/{dbname}" if dbname is not None else parts.path
    return urlunsplit(("postgresql", parts.netloc, path, parts.query, parts.fragment))


def _manifest_sha256(manifest: dict[str, ManifestEntry]) -> str:
    """Sorted `(source, key, size, etag/sha256)` fingerprint (D14).

    A rerun that ingests nothing new reads back the same manifest content,
    so it produces the same hash regardless of dict/JSON key order.
    """
    rows = sorted(
        (
            entry.get("source", ""),
            entry.get("key", ""),
            entry.get("size", 0),
            entry.get("etag") or entry.get("sha256") or "",
        )
        for entry in manifest.values()
    )
    canonical = json.dumps(rows, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ensure_database(database_url: str, dbname: str) -> None:
    """`CREATE DATABASE <dbname>` if it doesn't exist yet."""
    admin_dsn = _psycopg_dsn(database_url, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute("select 1 from pg_database where datname = %s", (dbname,)).fetchone()
        if exists is None:
            conn.execute(f"CREATE DATABASE {dbname}")


def _run_dbt_build(offset: int) -> None:
    """`dbt build --vars '{"date_offset_days": N}'`, per the fixed invocation
    convention recorded in the state file (T8/T9/T11): `uv run --project ..
    dbt ... --project-dir . --profiles-dir .` from `pipeline/dbt`.
    """
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "..",
            "dbt",
            "build",
            "--project-dir",
            ".",
            "--profiles-dir",
            ".",
            "--vars",
            json.dumps({"date_offset_days": offset}),
        ],
        cwd=DBT_DIR,
        check=True,
    )


def _run_alembic_upgrade(golden_database_url: str) -> None:
    """`alembic upgrade head` against the golden DB (cwd `backend/`)."""
    env = dict(os.environ, DATABASE_URL=golden_database_url)
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
    )


def _insert_system_metadata(
    dsn: str,
    *,
    load_date: date,
    max_data_date: date,
    offset: int,
    manifest_sha256: str,
) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            """
            insert into app.system_metadata
                (run_id, load_date, max_data_date, date_offset_days,
                 manifest_sha256, policy_hash)
            values (%s, %s, %s, %s, %s, null)
            """,
            (uuid4().hex, load_date, max_data_date, offset, manifest_sha256),
        )


def main() -> None:
    manifest = load_manifest()
    load_date = resolve_load_date()
    max_data_date = max_data_date_from_manifest(manifest)
    offset = date_offset_days(load_date, max_data_date)

    _run_dbt_build(offset)

    golden_url = os.environ["GOLDEN_DATABASE_URL"]
    _ensure_database(golden_url, _GOLDEN_DB)
    _run_alembic_upgrade(golden_url)

    golden_dsn = _psycopg_dsn(golden_url)
    counts = copy_all(WAREHOUSE_PATH, golden_dsn)
    _insert_system_metadata(
        golden_dsn,
        load_date=load_date,
        max_data_date=max_data_date,
        offset=offset,
        manifest_sha256=_manifest_sha256(manifest),
    )

    for table in TABLES:
        print(f"bank.{table}: {counts[table]}")

    demo_reset.reset()


if __name__ == "__main__":
    main()
