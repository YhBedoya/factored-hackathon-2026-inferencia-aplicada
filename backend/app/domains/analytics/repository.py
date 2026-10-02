"""Postgres store for the analytics worker (ADR-033, D7, D8, D16).

Plain SQL over `app`, `audit`, `bank` (read) and `analytics` (read-write), run
as the `analytics_worker` role. It never uses the API's shared engine: the
worker's engine comes from `build_engine(url)` with the worker's own URL and a
small pool, so a pass cannot starve the API's pool (D16).

R5 / D11: only `content_masked` is selected, never `content`. The customer key
appears once, in the join to `bank.customers` that yields the country label;
it is not returned.
"""

from collections.abc import Sequence
from dataclasses import asdict, fields
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.llm.sink import LLMCallRecord
from app.domains.analytics.mock import MockInteraction
from app.domains.analytics.sentiment import SentimentResult
from app.domains.analytics.service import Occurrence
from app.domains.analytics.worker import (
    ConversationFacts,
    HandoffFact,
    InteractionRow,
    MessageFact,
    ReplyFact,
    ScoringTarget,
    StepCost,
    WorkerState,
)

__all__ = ["PostgresAnalyticsStore", "build_engine"]

# `InteractionRow` has no sentiment columns, so the conflict update below never
# touches them (a recompute keeps the scores, D10). The one exception is
# `_CLEAR_STALE_SENTIMENT_SQL`: it clears them when a customer message is newer
# than `sentiment_scored_at`.
_INTERACTION_COLUMNS = [f.name for f in fields(InteractionRow)]
_MOCK_COLUMNS = [f.name for f in fields(MockInteraction) if f.name != "intents"]

# Column names come from the dataclasses above, never from input.
_UPSERT_INTERACTION_SQL = text(
    f"""
    INSERT INTO analytics.interactions ({", ".join(_INTERACTION_COLUMNS)})
    VALUES ({", ".join(":" + c for c in _INTERACTION_COLUMNS)})
    ON CONFLICT (conversation_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in _INTERACTION_COLUMNS if c != "conversation_id")}
    """
)

_CLEAR_STALE_SENTIMENT_SQL = text(
    """
    UPDATE analytics.interactions i SET
        sentiment_overall = NULL, sentiment_start = NULL, sentiment_end = NULL,
        sentiment_model = NULL, sentiment_prompt_version = NULL,
        sentiment_cost_usd = NULL, sentiment_scored_at = NULL
    WHERE i.conversation_id = :cid
      AND i.sentiment_scored_at IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM app.messages m
          WHERE m.conversation_id = i.conversation_id AND m.role = 'customer'
            AND m.created_at > i.sentiment_scored_at)
    """
)

_INSERT_INTENT_SQL = text(
    """
    INSERT INTO analytics.interaction_intents
        (conversation_id, seq, intent, outcome, needed_clarification, turns, bot_offered)
    VALUES
        (:conversation_id, :seq, :intent, :outcome, :needed_clarification, :turns, :bot_offered)
    """
)

_INSERT_MOCK_SQL = text(
    f"""
    INSERT INTO analytics.interactions ({", ".join(_MOCK_COLUMNS)})
    VALUES ({", ".join(":" + c for c in _MOCK_COLUMNS)})
    ON CONFLICT (conversation_id) DO NOTHING
    RETURNING conversation_id
    """
)

# Same columns as `audit/repository.py::_INSERT_LLM_CALL_SQL`.
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


def build_engine(url: str) -> AsyncEngine:
    """The worker's engine: its own URL, a pool of 3, no overflow (D16)."""
    return create_async_engine(url, pool_size=3, max_overflow=0, pool_pre_ping=True)


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None


class PostgresAnalyticsStore:
    """`worker.AnalyticsStore` on Postgres."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_state(self) -> WorkerState:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT watermark, mock_seeded_through FROM analytics.worker_state")
                )
            ).one()
        return WorkerState(watermark=row.watermark, mock_seeded_through=row.mock_seeded_through)

    async def set_watermark(self, watermark: datetime) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE analytics.worker_state SET watermark = :w WHERE id = 1"),
                {"w": watermark},
            )

    async def set_mock_seeded_through(self, day: date) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE analytics.worker_state SET mock_seeded_through = :d WHERE id = 1"),
                {"d": day},
            )

    async def list_candidates(self, since: datetime | None) -> list[str]:
        # D7: activity is read from messages (indexed by time) and the handoff
        # time columns. A null watermark is the first run: every conversation.
        if since is None:
            sql = "SELECT id FROM app.conversations ORDER BY id"
            params: dict[str, Any] = {}
        else:
            sql = """
                SELECT conversation_id AS id FROM app.messages WHERE created_at >= :since
                UNION
                SELECT conversation_id FROM app.handoffs
                WHERE created_at >= :since OR claimed_at >= :since OR returned_at >= :since
                UNION
                SELECT id FROM app.conversations WHERE closed_at >= :since
                ORDER BY id
            """
            params = {"since": since}
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return [str(row.id) for row in result if row.id is not None]

    async def load_facts(self, conversation_id: str) -> ConversationFacts | None:
        cid = {"cid": UUID(conversation_id)}
        async with self._engine.connect() as conn:
            head = (
                await conn.execute(
                    text(
                        """
                        SELECT c.status, c.language, c.channel, cu.country AS country_label
                        FROM app.conversations c
                        LEFT JOIN bank.customers cu ON cu.customer_id = c.customer_id
                        WHERE c.id = :cid
                        """
                    ),
                    cid,
                )
            ).first()
            if head is None:
                return None
            messages = await conn.execute(
                text(
                    """
                    SELECT role, turn_id, created_at, content_masked
                    FROM app.messages WHERE conversation_id = :cid
                    ORDER BY created_at, id
                    """
                ),
                cid,
            )
            replies = await conn.execute(
                text(
                    """
                    SELECT payload->>'route' AS route,
                           COALESCE((payload->>'degraded')::boolean, false) AS degraded,
                           COALESCE(payload->'segments', '[]'::jsonb) AS segments
                    FROM audit.audit_events
                    WHERE conversation_id = :cid AND type = 'reply_sent'
                    ORDER BY at, id
                    """
                ),
                cid,
            )
            handoffs = await conn.execute(
                text(
                    """
                    SELECT queue, reason, status, created_at, claimed_at
                    FROM app.handoffs WHERE conversation_id = :cid
                    ORDER BY created_at, id
                    """
                ),
                cid,
            )
            costs = await conn.execute(
                text(
                    """
                    SELECT step, COALESCE(sum(cost_usd), 0) AS cost_usd, count(*) AS calls
                    FROM audit.llm_calls WHERE conversation_id = :cid
                    GROUP BY step
                    """
                ),
                cid,
            )
            return ConversationFacts(
                conversation_id=conversation_id,
                status=head.status,
                language=head.language,
                channel=head.channel,
                country_label=head.country_label,
                messages=[
                    MessageFact(
                        r.role,
                        str(r.turn_id) if r.turn_id else None,
                        r.created_at,
                        r.content_masked,
                    )
                    for r in messages
                ],
                replies=[ReplyFact(r.route, r.degraded, r.segments) for r in replies],
                handoffs=[
                    HandoffFact(r.queue, r.reason, r.status, r.created_at, r.claimed_at)
                    for r in handoffs
                ],
                step_costs={r.step: StepCost(r.cost_usd, r.calls) for r in costs},
            )

    async def upsert_interaction(self, row: InteractionRow, intents: Sequence[Occurrence]) -> None:
        values = asdict(row)
        values["conversation_id"] = UUID(row.conversation_id)
        async with self._engine.begin() as conn:  # one transaction: row + intents
            await conn.execute(_UPSERT_INTERACTION_SQL, values)
            # A reopened conversation: the customer wrote after the last scoring
            # (`sentiment_scored_at`, the only scoring time the row stores), so the
            # old labels are stale. Clear them and the next pass rescores. With no
            # newer customer message the scores are left as they are.
            await conn.execute(_CLEAR_STALE_SENTIMENT_SQL, {"cid": values["conversation_id"]})
            await conn.execute(
                text("DELETE FROM analytics.interaction_intents WHERE conversation_id = :cid"),
                {"cid": values["conversation_id"]},
            )
            await _insert_intents(conn, values["conversation_id"], intents)

    async def insert_mock(self, rows: Sequence[MockInteraction]) -> None:
        async with self._engine.begin() as conn:
            for mock in rows:
                values = {c: getattr(mock, c) for c in _MOCK_COLUMNS}
                values["conversation_id"] = UUID(mock.conversation_id)
                inserted = (await conn.execute(_INSERT_MOCK_SQL, values)).first()
                if inserted is None:  # id already there: left alone
                    continue
                await _insert_intents(conn, values["conversation_id"], mock.intents)

    async def list_scoring_targets(
        self, *, all_real: bool, limit: int | None
    ) -> list[ScoringTarget]:
        where = "source = 'real'"
        if not all_real:
            # At least one customer message with text to score; others stay null
            # and never take a batch slot.
            where += """ AND sentiment_overall IS NULL AND EXISTS (
                SELECT 1 FROM app.messages m
                WHERE m.conversation_id = analytics.interactions.conversation_id
                  AND m.role = 'customer' AND COALESCE(m.content_masked, '') <> '')"""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"""
                    SELECT conversation_id, language FROM analytics.interactions
                    WHERE {where}
                    ORDER BY ended_at DESC, conversation_id
                    LIMIT CAST(:limit AS integer)
                    """
                ),
                {"limit": limit},
            )
            return [ScoringTarget(str(r.conversation_id), r.language) for r in result]

    async def customer_messages(self, conversation_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT content_masked FROM app.messages
                    WHERE conversation_id = :cid AND role = 'customer'
                      AND COALESCE(content_masked, '') <> ''
                    ORDER BY created_at, id
                    """
                ),
                {"cid": UUID(conversation_id)},
            )
            return [r.content_masked for r in result]

    async def set_sentiment(
        self, conversation_id: str, result: SentimentResult, scored_at: datetime
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE analytics.interactions SET
                        sentiment_overall = :overall, sentiment_start = :start,
                        sentiment_end = :end, sentiment_model = :model,
                        sentiment_prompt_version = :prompt_version,
                        sentiment_cost_usd = :cost, sentiment_scored_at = :scored_at
                    WHERE conversation_id = :cid
                    """
                ),
                {
                    "overall": result.overall,
                    "start": result.start,
                    "end": result.end,
                    "model": result.model,
                    "prompt_version": result.prompt_version,
                    "cost": result.cost_usd,
                    "scored_at": scored_at,
                    "cid": UUID(conversation_id),
                },
            )

    async def list_stale(self, metrics_version: int) -> list[str]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT conversation_id FROM analytics.interactions
                    WHERE source = 'real' AND metrics_version < :v
                    ORDER BY conversation_id
                    """
                ),
                {"v": metrics_version},
            )
            return [str(r.conversation_id) for r in result]

    async def record_llm_call(self, call: LLMCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                _INSERT_LLM_CALL_SQL,
                {
                    "id": uuid4(),
                    "at": datetime.now(UTC),
                    "conversation_id": _uuid(call.conversation_id),
                    "turn_id": _uuid(call.turn_id),
                    "step": call.step,
                    "provider": call.provider,
                    "model_id": call.model_id,
                    "prompt_version": call.prompt_version,
                    "temperature": call.temperature,
                    "attempt": call.attempt,
                    "status": call.status,
                    "input_text": call.input_text,
                    "output_json": call.output_json,
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "cost_usd": call.cost_usd,
                    "latency_ms": call.latency_ms,
                    "langfuse_trace_id": call.langfuse_trace_id,
                },
            )


async def _insert_intents(
    conn: AsyncConnection, conversation_id: UUID, intents: Sequence[Any]
) -> None:
    """Insert `Occurrence` / `MockIntent` rows (same intent columns); the id is ours."""
    for intent in intents:
        values = asdict(intent)
        values["conversation_id"] = conversation_id
        await conn.execute(_INSERT_INTENT_SQL, values)
