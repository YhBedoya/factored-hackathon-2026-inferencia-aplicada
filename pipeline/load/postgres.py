"""TRUNCATE + COPY the 13 `bank.*` tables from dbt's `srv_*` models (D14).

Streams row batches from a read-only DuckDB connection into Postgres through
psycopg's COPY protocol -- `digital_events` alone is 15.6M rows, so no table
is ever materialized whole in Python (see the state file's memory note).
Column lists come from DuckDB's own catalog rather than being duplicated
here: `srv_<table>` already carries the migration's exact column order
(T11), so introspecting it keeps the COPY's column list and the SELECT's
column list provably in sync.
"""

from __future__ import annotations

import duckdb
import psycopg

from ingest import PARTITIONED_TABLES, UNPARTITIONED_TABLES

# Same order as `0001_schemas_and_bank.py`'s `_BANK_TABLES` (unpartitioned
# sources first, then partitioned) -- single source of truth, not duplicated.
TABLES: tuple[str, ...] = UNPARTITIONED_TABLES + PARTITIONED_TABLES

_BATCH_SIZE = 50_000


def _srv_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Column names of `srv_<table>`, in ordinal order."""
    rows = con.execute(
        "select column_name from information_schema.columns "
        "where table_name = ? order by ordinal_position",
        [f"srv_{table}"],
    ).fetchall()
    columns = [row[0] for row in rows]
    if not columns:
        raise RuntimeError(f"srv_{table} has no columns -- was `dbt build` run first?")
    return columns


def copy_all(warehouse_path: str, dsn: str) -> dict[str, int]:
    """TRUNCATE and COPY all 13 `bank.*` tables; returns `{table: row_count}`.

    Runs inside a single Postgres transaction (psycopg's connection default,
    committed on the `with` block's clean exit): a failure partway through
    leaves the previous `bank.*` state untouched, since nothing commits
    until every table has copied.

    `identity.accounts` is truncated in the same statement: migration
    `0002` gives it an FK to `bank.customers`, and Postgres refuses to
    truncate a referenced table on its own (`cannot truncate a table
    referenced in a foreign key constraint`). A full FK scan of
    `latam_golden` (`pg_constraint`, `contype = 'f'`) found this as the
    only FK pointing into `bank.*`, so an explicit table list -- rather
    than `CASCADE`, which would silently follow any future FK too -- is
    enough and stays scoped to what's actually there. `make data` runs
    `make seed-identity` right after the load, which re-provisions
    `identity.accounts`, so emptying it here is expected, not a data loss.
    """
    con = duckdb.connect(warehouse_path, read_only=True)
    con.execute("SET memory_limit='3GB'")
    con.execute("SET preserve_insertion_order=false")

    counts: dict[str, int] = {}
    try:
        with psycopg.connect(dsn) as pg, pg.cursor() as cur:
            # app.handoffs has an FK to identity.accounts; Postgres refuses to
            # truncate the referenced table unless the referencing one is listed.
            truncate_targets = [f"bank.{t}" for t in TABLES] + [
                "identity.accounts",
                "app.handoffs",
            ]
            cur.execute("TRUNCATE TABLE " + ", ".join(truncate_targets))
            for table in TABLES:
                columns = _srv_columns(con, table)
                col_list = ", ".join(columns)
                duck_cursor = con.execute(f"select {col_list} from srv_{table}")
                row_count = 0
                with cur.copy(f"COPY bank.{table} ({col_list}) FROM STDIN") as copy:
                    while True:
                        batch = duck_cursor.fetchmany(_BATCH_SIZE)
                        if not batch:
                            break
                        for row in batch:
                            copy.write_row(row)
                        row_count += len(batch)
                counts[table] = row_count
    finally:
        con.close()
    return counts
