"""Apply, revert and verify `setup.db_patches` on the eval clone (D14, R12).

A patch seeds one case's data on the clone (e.g. a malicious `merchant_name`).
After evidence is collected the patched columns are copied back from
`latam_golden` and the matched rows are diffed in full; the run aborts on any
difference. Only the `bank` schema is patchable. Errors name the table and the
`where` key, never row values (no PII in output).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from eval.scenarios.schema import DbPatch

__all__ = ["PatchDiffError", "PatchError", "apply", "revert_and_verify"]

_ALLOWED_SCHEMA = "bank"


class PatchError(Exception):
    """A patch is not allowed or cannot be applied. Aborts the run."""


class PatchDiffError(Exception):
    """A patched row differs from golden after the revert. Aborts the run."""

    def __init__(self, table: str, key: Mapping[str, Any]) -> None:
        super().__init__(f"patch revert diff in {table}: key {dict(key)!r}")
        self.table = table
        self.key = dict(key)


def _table(patch: DbPatch) -> sql.Identifier:
    schema, dot, name = patch.table.partition(".")
    if not dot or not name or "." in name or schema != _ALLOWED_SCHEMA:
        raise PatchError(f"db_patches may only target bank.<table>: {patch.table!r}")
    return sql.Identifier(schema, name)


def _where(where: Mapping[str, Any]) -> tuple[sql.Composable, list[Any]]:
    if not where:
        raise PatchError("db_patches need a non-empty where")
    clause = sql.SQL(" and ").join(
        sql.SQL("{} = %s").format(sql.Identifier(k)) for k in where
    )
    return clause, list(where.values())


def _check(patches: Sequence[DbPatch]) -> None:
    for patch in patches:
        _table(patch)
        if not patch.set:
            raise PatchError(f"db_patches need a non-empty set: {patch.table!r}")


def apply(conn: psycopg.Connection, patches: Sequence[DbPatch]) -> None:
    """Apply each patch on the clone. Every table is checked before any SQL runs."""
    _check(patches)
    for patch in patches:
        where, where_vals = _where(patch.where)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(k)) for k in patch.set
        )
        query = sql.SQL("update {} set {} where {}").format(
            _table(patch), assignments, where
        )
        conn.execute(query, [*patch.set.values(), *where_vals])
    conn.commit()


def _select(
    conn: psycopg.Connection, patch: DbPatch, columns: Sequence[str] | None
) -> list[dict[str, Any]]:
    where, where_vals = _where(patch.where)
    cols = (
        sql.SQL(", ").join(sql.Identifier(c) for c in columns)
        if columns
        else sql.SQL("*")
    )
    query = sql.SQL("select {} from {} where {}").format(cols, _table(patch), where)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, where_vals)
        return cur.fetchall()


def revert_and_verify(
    clone_conn: psycopg.Connection,
    golden_conn: psycopg.Connection,
    patches: Sequence[DbPatch],
) -> None:
    """Copy the patched columns back from golden, then diff the matched rows in full."""
    _check(patches)
    for patch in patches:
        cols = list(patch.set)
        golden_vals = _select(golden_conn, patch, cols)
        distinct = {tuple(map(repr, r.values())) for r in golden_vals}
        if len(distinct) != 1:
            # No golden row, or rows disagreeing on the patched columns: not revertible.
            raise PatchDiffError(patch.table, patch.where)
        where, where_vals = _where(patch.where)
        assignments = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols
        )
        query = sql.SQL("update {} set {} where {}").format(
            _table(patch), assignments, where
        )
        clone_conn.execute(query, [golden_vals[0][c] for c in cols] + where_vals)
    clone_conn.commit()
    for patch in patches:
        golden_rows = sorted(map(repr, (_select(golden_conn, patch, None))))
        clone_rows = sorted(map(repr, (_select(clone_conn, patch, None))))
        if golden_rows != clone_rows:
            raise PatchDiffError(patch.table, patch.where)
