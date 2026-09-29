"""Per-persona restore and diff after a writing case (D14, R12).

Evidence is collected before `restore_persona` runs. Afterwards `verify_persona`
diffs the persona's rows in every `RESTORE_TABLES` table against `latam_golden`
and the run aborts on any difference. Errors name the table and key, never row
contents (no PII in output).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

RESTORE_TABLES: tuple[str, ...] = (
    "bank.products",
    "app.card_status_history",
    "app.card_controls",
    "app.card_replacements",
    "bank.complaints",
    "app.handoffs",
)

Row = Mapping[str, Any]

_PERSONA_PRODUCTS = "select product_id from bank.products where customer_id = %s"

# Per table: primary-key column and the persona-scoped WHERE (one `%s` = customer_id).
_KEY: dict[str, str] = {
    "bank.products": "product_id",
    "app.card_status_history": "id",
    "app.card_controls": "product_id",
    "app.card_replacements": "id",
    "bank.complaints": "complaint_id",
    "app.handoffs": "id",
}
_SCOPE: dict[str, str] = {
    "bank.products": "customer_id = %s",
    "app.card_status_history": f"product_id in ({_PERSONA_PRODUCTS})",
    "app.card_controls": f"product_id in ({_PERSONA_PRODUCTS})",
    "app.card_replacements": f"product_id in ({_PERSONA_PRODUCTS})",
    # Dataset complaints are never touched; only the app's own rows are in scope.
    "bank.complaints": "customer_id = %s and origin = 'app'",
    "app.handoffs": "conversation_id in (select id from app.conversations where customer_id = %s)",
}
# Tables whose persona rows are all app-created: the restore deletes them.
_DELETED = tuple(t for t in RESTORE_TABLES if t != "bank.products")


class RestoreDiffError(Exception):
    """A persona row differs from golden after the restore. Aborts the run."""

    def __init__(self, table: str, key: object) -> None:
        super().__init__(f"restore diff in {table}: key {key!r}")
        self.table = table
        self.key = key


def diff_rows(
    table: str, golden_rows: Sequence[Row], clone_rows: Sequence[Row]
) -> None:
    """Raise `RestoreDiffError(table, key)` on the first missing, extra or changed row."""
    key_col = _KEY[table]
    golden = {r[key_col]: r for r in golden_rows}
    clone = {r[key_col]: r for r in clone_rows}
    for key in sorted(clone.keys() | golden.keys(), key=str):
        if (
            key not in golden
            or key not in clone
            or dict(golden[key]) != dict(clone[key])
        ):
            raise RestoreDiffError(table, key)


def _rows(
    conn: psycopg.Connection, table: str, customer_id: str
) -> list[dict[str, Any]]:
    # `table` and the scope come from the module constants above, never from input.
    query = f"select * from {table} where {_SCOPE[table]} order by {_KEY[table]}"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, (customer_id,))
        return cur.fetchall()


def restore_persona(
    clone: psycopg.Connection, golden: psycopg.Connection, customer_id: str
) -> None:
    """Reset the persona's products to golden values and delete app-created rows."""
    # Delete first: card_status_history and card_controls are scoped through products.
    for table in _DELETED:
        clone.execute(f"delete from {table} where {_SCOPE[table]}", (customer_id,))
    key_col = _KEY["bank.products"]
    for row in _rows(golden, "bank.products", customer_id):
        cols = [c for c in row if c != key_col]
        assignments = ", ".join(f"{c} = %s" for c in cols)
        clone.execute(
            f"update bank.products set {assignments} where {key_col} = %s",
            [row[c] for c in cols] + [row[key_col]],
        )
    clone.commit()


def verify_persona(
    clone: psycopg.Connection, golden: psycopg.Connection, customer_id: str
) -> None:
    """Diff the persona's rows in every `RESTORE_TABLES` table; raise on any difference."""
    for table in RESTORE_TABLES:
        diff_rows(
            table, _rows(golden, table, customer_id), _rows(clone, table, customer_id)
        )
