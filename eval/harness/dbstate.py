"""Compile B's `expected_db_state` items into parameterized SQL (D15 `db_state`).

Item shape: `{table, where, expect | count}`. `$persona.customer_id` is the only
interpolation and is always bound as a parameter. Identifiers are validated
against `DB_ALLOWLIST`, never taken from the item verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PERSONA_REF = "$persona.customer_id"


def _cols(names: str) -> frozenset[str]:
    return frozenset(names.split())


_COLUMNS: dict[str, frozenset[str]] = {
    "bank.products": _cols(
        "product_id customer_id product_type product_number currency current_balance "
        "credit_limit interest_rate opening_date expiration_date opening_branch_id "
        "product_status opening_channel has_linked_app days_past_due "
        "last_transaction_date last_updated"
    ),
    "bank.transactions": _cols(
        "transaction_id transaction_date process_date product_id customer_id "
        "transaction_type transaction_category amount currency amount_usd channel "
        "branch_id merchant_name merchant_category transaction_country "
        "transaction_city transaction_status response_code is_fraud fraud_score "
        "latitude longitude"
    ),
    "bank.complaints": _cols(
        "complaint_id creation_date process_date customer_id case_type category "
        "subcategory reception_channel affected_product_id related_branch_id "
        "origin_interaction_id description claimed_amount currency priority status "
        "assigned_agent_id assignment_date first_response_date resolution_date "
        "closing_date sla_breached resolution_days resolution compensation_granted "
        "resolution_satisfaction is_repeat_complainer origin created_at "
        "conversation_id"
    ),
    "app.card_status_history": _cols(
        "id product_id old_status new_status reason actor conversation_id trace_id "
        "at idempotency_key"
    ),
    "app.card_controls": _cols(
        "product_id locked locked_by locked_at updated_at idempotency_key"
    ),
    "app.card_replacements": _cols(
        "id product_id address_ref address_changed tracking_id status conversation_id "
        "created_at idempotency_key"
    ),
    "app.handoffs": _cols(
        "id conversation_id queue reason priority packet status agent_id created_at "
        "claimed_at returned_at"
    ),
}
DB_ALLOWLIST: frozenset[str] = frozenset(_COLUMNS)


class DbStateLoadError(ValueError):
    """An `expected_db_state` item names an unknown table or column."""


def _check_columns(table: str, names: Any) -> None:
    unknown = [n for n in names if n not in _COLUMNS[table]]
    if unknown:
        raise DbStateLoadError(f"unknown column(s) {unknown} on {table}")


def compile_item(
    item: Mapping[str, Any], customer_id: str, conversation_id: str | None
) -> tuple[str, list[Any]]:
    """Return `(sql, params)` for one item. Params are positional `%s` (psycopg)."""
    table = item.get("table")
    if table not in DB_ALLOWLIST:
        raise DbStateLoadError(f"table {table!r} is not in the allowlist")
    where: Mapping[str, Any] = item.get("where") or {}
    _check_columns(table, where)

    clauses: list[str] = []
    params: list[Any] = []
    for col, value in where.items():
        clauses.append(f"{col} = %s")
        params.append(customer_id if value == _PERSONA_REF else value)
    # Scope app.* assertions to the case's own conversation when the table has the column.
    if table.startswith("app.") and "conversation_id" in _COLUMNS[table]:
        clauses.append("conversation_id = %s")
        params.append(conversation_id)

    if "count" in item:
        select = "count(*)"
    else:
        expect: Mapping[str, Any] = item.get("expect") or {}
        if not expect:
            raise DbStateLoadError(f"item on {table} has neither expect nor count")
        _check_columns(table, expect)
        select = ", ".join(expect)
    sql = f"SELECT {select} FROM {table}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return sql, params
