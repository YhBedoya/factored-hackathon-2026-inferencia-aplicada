"""Postgres access for `audit.audit_events` and `audit.llm_calls`.

Writes are append-only (D12); the `fetch_*` functions at the bottom are the
read-only staff timeline queries (D7-A).

There is no update or delete function here on purpose: the audit trail is
insert-only, and a row's `payload`/`sources` never change after the fact.
`model` and `langfuse_trace_id` stay `NULL` on every insert until tracing
lands (ADR-006); this module never writes to those columns.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_engine
from app.core.errors import ToolUnavailable
from app.core.llm.sink import LLMCallRecord
from app.domains.audit.schemas import AuditEvent

__all__ = [
    "fetch_conversation_facts",
    "fetch_conversation_rollups",
    "fetch_events",
    "fetch_llm_calls",
    "fetch_messages",
    "insert_event",
    "insert_llm_call",
]

_INSERT_EVENT_SQL = text(
    """
    INSERT INTO audit.audit_events
        (id, at, conversation_id, turn_id, actor, type,
         payload, sources, policy_version, trace_id)
    VALUES
        (:id, :at, :conversation_id, :turn_id, :actor, :type,
         :payload, :sources, :policy_version, :trace_id)
    """
).bindparams(
    # asyncpg's jsonb codec only accepts an already-encoded string, and a
    # bare Python dict/list param fails with an opaque `DataError` (same
    # convention as `conversation.store.add_message`'s `ui_payload`).
    bindparam("payload", type_=JSONB),
    bindparam("sources", type_=JSONB),
)


async def insert_event(event: AuditEvent) -> None:
    """Insert one `audit.audit_events` row. Raises `ToolUnavailable` on any
    backend or data-source failure -- `AuditRecorder.record` decides from
    there whether that's fail-closed or a logged, non-fatal failure (D15).
    """
    try:
        async with get_engine().begin() as conn:
            await conn.execute(
                _INSERT_EVENT_SQL,
                {
                    "id": event.id,
                    "at": event.at,
                    "conversation_id": event.conversation_id,
                    "turn_id": event.turn_id,
                    "actor": event.actor,
                    "type": event.type,
                    "payload": event.payload,
                    "sources": event.sources,
                    "policy_version": event.policy_version,
                    "trace_id": event.trace_id,
                },
            )
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"audit event insert failed: {exc}") from exc


_INSERT_LLM_CALL_SQL = text(
    """
    INSERT INTO audit.llm_calls
        (id, at, conversation_id, turn_id, step, provider, model_id,
         prompt_version, temperature, attempt, status, input_text,
         output_json, input_tokens, output_tokens, cost_usd, latency_ms,
         langfuse_trace_id)
    VALUES
        (:id, :at, :conversation_id, :turn_id, :step, :provider, :model_id,
         :prompt_version, :temperature, :attempt, :status, :input_text,
         :output_json, :input_tokens, :output_tokens, :cost_usd, :latency_ms,
         :langfuse_trace_id)
    """
).bindparams(bindparam("output_json", type_=JSONB))


async def insert_llm_call(row_id: UUID, at: datetime, record: LLMCallRecord) -> None:
    """Insert one `audit.llm_calls` row (append-only, D9). `id` and `at` come
    from `AuditLLMCallSink`, never from the record. Raises `ToolUnavailable`.
    """
    try:
        async with get_engine().begin() as conn:
            await conn.execute(
                _INSERT_LLM_CALL_SQL,
                {
                    "id": row_id,
                    "at": at,
                    "conversation_id": UUID(record.conversation_id)
                    if record.conversation_id
                    else None,
                    "turn_id": UUID(record.turn_id) if record.turn_id else None,
                    "step": record.step,
                    "provider": record.provider,
                    "model_id": record.model_id,
                    "prompt_version": record.prompt_version,
                    "temperature": record.temperature,
                    "attempt": record.attempt,
                    "status": record.status,
                    "input_text": record.input_text,
                    "output_json": record.output_json,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cost_usd": record.cost_usd,
                    "latency_ms": record.latency_ms,
                    "langfuse_trace_id": record.langfuse_trace_id,
                },
            )
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise ToolUnavailable(f"llm call insert failed: {exc}") from exc


# --- Read-only staff timeline queries (D7-A D17, D19). ---


async def fetch_conversation_facts(
    *,
    conversation_id: UUID | None = None,
    language: str | None = None,
    countries: Sequence[str] | None = None,
    intent: str | None = None,
    escalation: str | None = None,
    date_from: datetime | None = None,
    date_to_exclusive: datetime | None = None,
) -> list[Mapping[str, Any]]:
    """Every conversation matching the SQL-expressible filters, newest first,
    with the raw facts `timeline.compute_outcome` needs (D18): the latest
    handoff queue, the last `reply_sent` route/ui kinds and that turn's NLU
    status. `countries` are `bank.customers.country` labels, already mapped by
    the caller. The outcome filter and paging happen in Python on top of this
    so the precedence lives in exactly one place.
    """
    conditions = ["TRUE"]
    params: dict[str, Any] = {}
    if conversation_id is not None:
        conditions.append("c.id = :conversation_id")
        params["conversation_id"] = conversation_id
    if language is not None:
        conditions.append("c.language = :language")
        params["language"] = language
    if countries is not None:
        conditions.append("cu.country = ANY(:countries)")
        params["countries"] = list(countries)
    if intent is not None:
        conditions.append(
            """EXISTS (SELECT 1 FROM audit.audit_events e
                WHERE e.conversation_id = c.id AND e.type = 'nlu_result'
                  AND e.payload->'intents' @> to_jsonb(CAST(:intent AS text)))"""
        )
        params["intent"] = intent
    if escalation == "none":
        conditions.append("h.queue IS NULL")
    elif escalation == "any":
        conditions.append("h.queue IS NOT NULL")
    elif escalation is not None:
        conditions.append("h.queue = :escalation")
        params["escalation"] = escalation
    if date_from is not None:
        conditions.append("c.started_at >= :date_from")
        params["date_from"] = date_from
    if date_to_exclusive is not None:
        conditions.append("c.started_at < :date_to")
        params["date_to"] = date_to_exclusive
    sql = f"""
        SELECT c.id, c.started_at, c.language, c.mode, c.status,
               cu.country AS country_label, h.queue AS handoff_queue,
               rs.turn_id IS NOT NULL AS has_reply,
               rs.payload->>'route' AS reply_route,
               COALESCE(rs.payload->'ui_kinds', '[]'::jsonb) AS reply_ui_kinds,
               nr.status AS nlu_status
        FROM app.conversations c
        LEFT JOIN bank.customers cu ON cu.customer_id = c.customer_id
        LEFT JOIN LATERAL (
            SELECT queue FROM app.handoffs WHERE conversation_id = c.id
            ORDER BY created_at DESC LIMIT 1) h ON TRUE
        LEFT JOIN LATERAL (
            SELECT turn_id, payload FROM audit.audit_events
            WHERE conversation_id = c.id AND type = 'reply_sent'
            ORDER BY at DESC LIMIT 1) rs ON TRUE
        LEFT JOIN LATERAL (
            SELECT payload->>'status' AS status FROM audit.audit_events
            WHERE conversation_id = c.id AND type = 'nlu_result'
              AND turn_id = rs.turn_id
            ORDER BY at DESC LIMIT 1) nr ON TRUE
        WHERE {" AND ".join(conditions)}
        ORDER BY c.started_at DESC, c.id
    """
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(text(sql), params)
            return [dict(row._mapping) for row in result]
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"conversation list query failed: {exc}") from exc


async def fetch_conversation_rollups(
    conversation_ids: Sequence[UUID],
) -> tuple[dict[UUID, list[str]], dict[UUID, int]]:
    """Distinct intents (first-seen order) and turn counts for the given
    conversations: the page's two summary columns that need a scan of their
    own rows.
    """
    ids = list(conversation_ids)
    try:
        async with get_engine().connect() as conn:
            intent_rows = await conn.execute(
                text(
                    """
                    SELECT e.conversation_id, x.intent
                    FROM audit.audit_events e
                    CROSS JOIN LATERAL jsonb_array_elements_text(
                        COALESCE(e.payload->'intents', '[]'::jsonb)
                    ) WITH ORDINALITY AS x(intent, n)
                    WHERE e.type = 'nlu_result' AND e.conversation_id = ANY(:ids)
                    ORDER BY e.at, x.n
                    """
                ),
                {"ids": ids},
            )
            turn_rows = await conn.execute(
                text(
                    """
                    SELECT conversation_id, count(DISTINCT turn_id) AS turns
                    FROM app.messages
                    WHERE conversation_id = ANY(:ids) AND turn_id IS NOT NULL
                    GROUP BY conversation_id
                    """
                ),
                {"ids": ids},
            )
            intents: dict[UUID, list[str]] = {}
            for row in intent_rows:
                seen = intents.setdefault(row.conversation_id, [])
                if row.intent not in seen:
                    seen.append(row.intent)
            return intents, {row.conversation_id: row.turns for row in turn_rows}
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"conversation rollup query failed: {exc}") from exc


async def fetch_events(conversation_id: UUID) -> list[Mapping[str, Any]]:
    """Every audit event of the conversation, oldest first."""
    return await _fetch_all(
        """
        SELECT at, turn_id, actor, type, payload, sources, policy_version
        FROM audit.audit_events WHERE conversation_id = :cid ORDER BY at, id
        """,
        conversation_id,
    )


async def fetch_llm_calls(conversation_id: UUID) -> list[Mapping[str, Any]]:
    """The ledger rows minus `input_text`/`output_json` (D17), oldest first."""
    return await _fetch_all(
        """
        SELECT at, turn_id, step, model_id, prompt_version, temperature, attempt,
               status, latency_ms, input_tokens, output_tokens, cost_usd,
               langfuse_trace_id
        FROM audit.llm_calls WHERE conversation_id = :cid ORDER BY at, id
        """,
        conversation_id,
    )


async def fetch_messages(conversation_id: UUID) -> list[Mapping[str, Any]]:
    """Masked text only: `content` is deliberately not selected (D17, R5)."""
    return await _fetch_all(
        """
        SELECT turn_id, role, content_masked, created_at
        FROM app.messages WHERE conversation_id = :cid ORDER BY created_at, id
        """,
        conversation_id,
    )


async def _fetch_all(sql: str, conversation_id: UUID) -> list[Mapping[str, Any]]:
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(text(sql), {"cid": conversation_id})
            return [dict(row._mapping) for row in result]
    except (SQLAlchemyError, OSError) as exc:
        raise ToolUnavailable(f"timeline query failed: {exc}") from exc
