"""What one played case leaves behind (D15): B's `Transcript` plus the clone's
rows for its conversation. `collect` runs before the persona restore (D14), on
a sync psycopg connection to the clone, like `restore.py`. The checks in
`checks.py` are pure functions over a `CaseEvidence`, so they need no DB.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from eval.driver.driver import Transcript
from eval.harness.dbstate import DbStateLoadError, compile_item
from eval.scenarios.schema import Case

__all__ = ["CaseEvidence", "DbResult", "collect"]


class DbResult(BaseModel):
    item_index: int
    ok: bool
    detail: str


class CaseEvidence(BaseModel):
    """One per played case, collected before the restore (D14)."""

    case: Case
    transcript: Transcript
    audit_events: list[dict[str, Any]]
    llm_calls: list[dict[str, Any]]
    handoffs: list[dict[str, Any]]
    db_results: list[DbResult]
    segment: str | None


def _plain(value: Any) -> Any:
    """JSON-friendly copy of a row value (ids, timestamps, numerics)."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def _rows(
    conn: psycopg.Connection[Any], sql: str, params: list[Any]
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        return [{k: _plain(v) for k, v in row.items()} for row in cur.fetchall()]


def _matches(actual: Any, wanted: Any) -> bool:
    return bool(actual == wanted or str(actual) == str(wanted))


def _db_result(
    conn: psycopg.Connection[Any], index: int, case: Case, conversation_id: str | None
) -> DbResult:
    item = case.labels.expected_db_state[index].model_dump(exclude_none=True)
    try:
        sql, params = compile_item(item, case.persona, conversation_id)
    except DbStateLoadError as exc:
        return DbResult(item_index=index, ok=False, detail=f"load error: {exc}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)  # type: ignore[arg-type]
        rows = cur.fetchall()
    if "count" in item:
        got = next(iter(rows[0].values())) if rows else 0
        return DbResult(
            item_index=index,
            ok=got == item["count"],
            detail=f"count {got}, want {item['count']}",
        )
    if not rows:
        return DbResult(item_index=index, ok=False, detail="no matching row")
    expect = item["expect"]
    bad = [
        c for c, want in expect.items() if not all(_matches(r[c], want) for r in rows)
    ]
    return DbResult(
        item_index=index,
        ok=not bad,
        detail="ok" if not bad else f"column(s) differ: {', '.join(bad)}",
    )


def collect(
    conn: psycopg.Connection[Any], case: Case, transcript: Transcript
) -> CaseEvidence:
    """Read the clone for `transcript.conversation_id`. A `not_runnable`
    transcript has no conversation, so it gets empty evidence."""
    cid = transcript.conversation_id
    audit: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    results: list[DbResult] = []
    if cid is not None:
        audit = _rows(
            conn,
            "SELECT id, at, turn_id, actor, type, payload FROM audit.audit_events "
            "WHERE conversation_id = %s ORDER BY at",
            [cid],
        )
        calls = _rows(
            conn,
            "SELECT * FROM audit.llm_calls WHERE conversation_id = %s ORDER BY at",
            [cid],
        )
        handoffs = _rows(
            conn,
            "SELECT id, queue, reason, priority, packet FROM app.handoffs "
            "WHERE conversation_id = %s ORDER BY created_at",
            [cid],
        )
        results = [
            _db_result(conn, i, case, cid)
            for i in range(len(case.labels.expected_db_state))
        ]
    seg = _rows(
        conn,
        "SELECT segment FROM bank.customers WHERE customer_id = %s",
        [case.persona],
    )
    return CaseEvidence(
        case=case,
        transcript=transcript,
        audit_events=audit,
        llm_calls=calls,
        handoffs=handoffs,
        db_results=results,
        segment=seg[0]["segment"] if seg else None,
    )
