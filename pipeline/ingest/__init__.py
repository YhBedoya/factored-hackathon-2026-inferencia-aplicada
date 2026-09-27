"""Idempotent S3 -> Parquet ingest for the 13 provided bank tables (D6, D10).

Both sources (`ingest.s3`, `ingest.local`) share the table registry, the
CSV -> Parquet conversion and the manifest read/write helpers defined here, so
the two only differ in how they list objects and compute a change fingerprint
(S3 ETag vs. local SHA-256).
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import TypedDict

import duckdb

# The 13 provided tables (D6). Anything else under the source root -- S3's
# `data_backup_20260831/` and root `marketing_campaigns.csv`, or the local
# mirror's `data/raw/` and `data/_parquet/` -- is never a match below, so it
# is never read.
UNPARTITIONED_TABLES = (
    "branches",
    "customers",
    "daily_exchange_rates",
    "marketing_campaigns",
    "products",
    "service_agents",
)
PARTITIONED_TABLES = (
    "call_center_interactions",
    "call_transcripts",
    "campaign_sends",
    "complaints",
    "digital_events",
    "satisfaction_surveys",
    "transactions",
)
TABLE_NAMES = frozenset(UNPARTITIONED_TABLES) | frozenset(PARTITIONED_TABLES)

# `ingest/__init__.py` -> `ingest/` -> `pipeline/` -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "_manifest.json"


class ManifestEntry(TypedDict, total=False):
    """One `data/raw/_manifest.json` entry (D10)."""

    source: str  # "s3" or "local"
    key: str  # S3 key or path relative to the source root, hive segments kept
    size: int
    etag: str  # S3 only
    sha256: str  # local only, hex
    downloaded_at: str  # ISO 8601 UTC


def classify_relative_key(relative_key: str) -> str | None:
    """Return the table name if `relative_key` is a known raw CSV, else None.

    `relative_key` is relative to the source root (the S3 prefix, or the
    local mirror path): `<table>.csv` for the six unpartitioned tables, or
    `<table>/year=.../month=.../day=.../<file>.csv` for the seven partitioned
    ones. Anything else (backups, `data/raw/`, `data/_parquet/`) returns None.
    """
    parts = PurePosixPath(relative_key).parts
    if len(parts) == 1 and relative_key.endswith(".csv"):
        table = relative_key[: -len(".csv")]
        return table if table in UNPARTITIONED_TABLES else None
    if len(parts) == 5:
        table, year_part, month_part, day_part, filename = parts
        if (
            table in PARTITIONED_TABLES
            and year_part.startswith("year=")
            and month_part.startswith("month=")
            and day_part.startswith("day=")
            and filename.endswith(".csv")
        ):
            return table
    return None


def destination_parquet_path(table: str, relative_key: str) -> Path:
    """Where the Parquet file for `relative_key` lands under `data/raw/`."""
    if table in UNPARTITIONED_TABLES:
        return RAW_DIR / table / f"{table}.parquet"
    return RAW_DIR / (relative_key[: -len(".csv")] + ".parquet")


def csv_to_parquet(csv_path: Path, parquet_path: Path) -> None:
    """Convert one source CSV to an all-VARCHAR Parquet file.

    `read_csv` strips the UTF-8 BOM and keeps quoted newlines (both are
    DuckDB CSV-reader defaults, verified against `call_transcripts.full_text`);
    `nullstr=''` turns empty fields into NULL.
    """
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        # COPY ... TO doesn't accept a bound parameter for the destination
        # (only `read_csv`'s source path can be bound), so the destination
        # is a literal with its own quotes escaped -- both paths are ours,
        # never source-data-controlled.
        escaped_dest = str(parquet_path).replace("'", "''")
        con.execute(
            f"""
            COPY (
                SELECT * FROM read_csv(
                    ?, all_varchar = true, header = true,
                    quote = '"', escape = '"', nullstr = ''
                )
            ) TO '{escaped_dest}' (FORMAT PARQUET)
            """,
            [str(csv_path)],
        )
    finally:
        con.close()


def load_manifest() -> dict[str, ManifestEntry]:
    """Read `data/raw/_manifest.json`, or `{}` if it doesn't exist yet."""
    if not MANIFEST_PATH.exists():
        return {}
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return dict(data.get("entries", {}))


def save_manifest(entries: dict[str, ManifestEntry]) -> None:
    """Write `data/raw/_manifest.json`, keyed by the entries' `key`."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, indent=2, sort_keys=True)
        f.write("\n")
