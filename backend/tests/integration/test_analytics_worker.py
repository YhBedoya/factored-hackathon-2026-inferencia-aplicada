"""The analytics worker against a real Postgres (REQ-R3, D7, D15).

Runs on the throwaway `it_db` database (connected as its owner, so no
`analytics_worker` password is involved). No LLM: the scorer is a fake. Each
test deletes what it created; the analytics tables of `it_db` are private to
this suite.

T13 reuses: `NOW`, `FakeScorer`, `analytics_settings`, `with_store`,
`insert_conversation`, `insert_handoff`.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.config import Settings, get_settings
from app.core.db import get_engine
from app.core.pii import TOKEN_RE
from app.domains.analytics.repository import PostgresAnalyticsStore, build_engine
from app.domains.analytics.sentiment import SentimentResult
from app.domains.analytics.worker import run_pass
from app.domains.conversation import store as conversation_store
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.identity.tokens import CSRF_HEADER
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount
from tests.integration.test_write_path_api import (
    _BLOCKED_CUSTOMER_ID,
    _SINGLE_CARD_ID,
    _SINGLE_CUSTOMER_ID,
    _confirm_token,
    _login,
    _psycopg_dsn,
    _wait_for_bot_message,
)

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
_RAW_EMAIL = "ana.prueba@example.com"
_CUSTOMER = "CLI-TFSINGLE0002"  # a fixture customer in `bank.customers`
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


class FakeScorer:
    """`SentimentScorer` with a fixed answer; no LLM."""

    async def score(
        self, conversation_id: str, messages: Sequence[str], language: str
    ) -> SentimentResult | None:
        return SentimentResult("neutral", "neutral", "neutral", "fake", "v0", Decimal("0.001"))


class RecordingScorer(FakeScorer):
    """`FakeScorer` that keeps the messages it was asked to score (R5 proof)."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def score(
        self, conversation_id: str, messages: Sequence[str], language: str
    ) -> SentimentResult | None:
        self.seen.extend(messages)
        return await super().score(conversation_id, messages, language)


@pytest.fixture
def analytics_settings(
    it_env: None, it_db: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    """Settings whose `ANALYTICS_DATABASE_URL` is the throwaway database."""
    monkeypatch.setenv("ANALYTICS_DATABASE_URL", it_db)
    monkeypatch.setenv("ANALYTICS_MOCK_ENABLED", "false")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


async def with_store[T](
    settings: Settings, body: Callable[[PostgresAnalyticsStore, AsyncEngine], Awaitable[T]]
) -> T:
    """Run `body` with a store on a fresh worker engine (loop-bound, so per call)."""
    engine = build_engine(settings.analytics_database_url)
    try:
        return await body(PostgresAnalyticsStore(engine), engine)
    finally:
        await engine.dispose()


async def insert_conversation(
    conn: AsyncConnection,
    *,
    last_message_at: datetime,
    roles: Sequence[str] = ("customer", "bot"),
) -> uuid.UUID:
    """A conversation whose messages end at `last_message_at`, one second apart."""
    cid = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO app.conversations (id, customer_id, language, started_at) "
            "VALUES (:id, :customer, 'es', :started)"
        ),
        {"id": cid, "customer": _CUSTOMER, "started": last_message_at - timedelta(minutes=5)},
    )
    for i, role in enumerate(roles):
        at = last_message_at - timedelta(seconds=len(roles) - 1 - i)
        await conn.execute(
            text(
                "INSERT INTO app.messages "
                "(id, conversation_id, turn_id, role, content, content_masked, created_at) "
                "VALUES (:id, :cid, :turn, :role, 'enc', :masked, :at)"
            ),
            {
                "id": uuid.uuid4(),
                "cid": cid,
                "turn": uuid.uuid4(),
                "role": role,
                "masked": f"{role} message",
                "at": at,
            },
        )
    return cid


async def insert_handoff(
    conn: AsyncConnection, cid: uuid.UUID, *, status: str, at: datetime
) -> None:
    await conn.execute(
        text(
            "INSERT INTO app.handoffs "
            "(id, conversation_id, queue, reason, priority, packet, status, created_at) "
            "VALUES (:id, :cid, 'atencion', 'customer_requested', 'normal', '{}'::jsonb, "
            ":status, :at)"
        ),
        {"id": uuid.uuid4(), "cid": cid, "status": status, "at": at},
    )


async def _forget(conn: AsyncConnection, ids: Sequence[uuid.UUID]) -> None:
    for table in ("analytics.interaction_intents", "analytics.interactions"):
        await conn.execute(
            text(f"DELETE FROM {table} WHERE conversation_id = ANY(:ids)"), {"ids": list(ids)}
        )
    await conn.execute(
        text("DELETE FROM app.handoffs WHERE conversation_id = ANY(:ids)"), {"ids": list(ids)}
    )
    await conn.execute(
        text("DELETE FROM app.conversations WHERE id = ANY(:ids)"), {"ids": list(ids)}
    )
    await conn.execute(
        text("UPDATE analytics.worker_state SET watermark = NULL, mock_seeded_through = NULL")
    )


def test_finish_rules(analytics_settings: Settings) -> None:
    async def body(store: PostgresAnalyticsStore, engine: AsyncEngine) -> dict[str, Any]:
        ids: list[uuid.UUID] = []
        try:
            async with engine.begin() as conn:
                idle = await insert_conversation(conn, last_message_at=NOW - timedelta(hours=2))
                queued = await insert_conversation(conn, last_message_at=NOW - timedelta(hours=2))
                await insert_handoff(conn, queued, status="queued", at=NOW - timedelta(hours=2))
                closed = await insert_conversation(conn, last_message_at=NOW - timedelta(minutes=5))
                active = await insert_conversation(conn, last_message_at=NOW - timedelta(minutes=5))
                ids = [idle, queued, closed, active]
            # The real close path (UI `conversation_closed`): it_env points the app engine at it_db.
            await conversation_store.close_conversation(closed)
            await get_engine().dispose()

            await run_pass(store, FakeScorer(), now=NOW, settings=analytics_settings)

            async with engine.connect() as conn:
                rows = {
                    r.conversation_id: r
                    for r in await conn.execute(
                        text(
                            "SELECT conversation_id, end_reason, customer_messages, bot_messages, "
                            "sentiment_overall FROM analytics.interactions "
                            "WHERE conversation_id = ANY(:ids)"
                        ),
                        {"ids": ids},
                    )
                }
                closed_at = (
                    await conn.execute(
                        text("SELECT closed_at FROM app.conversations WHERE id = :id"),
                        {"id": closed},
                    )
                ).scalar_one()
            return {
                "idle": rows.get(idle),
                "queued": rows.get(queued),
                "closed": rows.get(closed),
                "active": rows.get(active),
                "closed_at": closed_at,
            }
        finally:
            async with engine.begin() as conn:
                await _forget(conn, ids)

    try:
        got = asyncio.run(with_store(analytics_settings, body))
    finally:
        get_engine.cache_clear()

    assert got["idle"] is not None and got["idle"].end_reason == "idle"
    assert (got["idle"].customer_messages, got["idle"].bot_messages) == (1, 1)
    assert got["idle"].sentiment_overall == "neutral"  # the fake scorer ran after compute
    assert got["queued"] is None  # an open handoff is never finished
    assert got["active"] is None  # recent and still open
    assert got["closed_at"] is not None
    assert got["closed"] is not None and got["closed"].end_reason == "customer_closed"


def test_mock_seed_deterministic(
    analytics_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANALYTICS_MOCK_ENABLED", "true")
    get_settings.cache_clear()
    settings = get_settings()

    snapshot_sql = text(
        "SELECT * FROM analytics.interactions WHERE source = 'mock' ORDER BY conversation_id"
    )
    intents_sql = text("SELECT * FROM analytics.interaction_intents ORDER BY conversation_id, seq")

    async def snapshot(conn: AsyncConnection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = [
            {k: v for k, v in r._mapping.items() if k != "computed_at"}
            for r in await conn.execute(snapshot_sql)
        ]
        intents = [dict(r._mapping) for r in await conn.execute(intents_sql)]
        return rows, intents

    async def park(engine: AsyncEngine) -> None:
        # Real activity is not under test: a far-future watermark leaves no candidates.
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE analytics.worker_state SET watermark = :w"), {"w": _FAR_FUTURE}
            )

    async def body(store: PostgresAnalyticsStore, engine: AsyncEngine) -> dict[str, Any]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM analytics.interaction_intents"))
                await conn.execute(text("DELETE FROM analytics.interactions"))
                await conn.execute(
                    text("UPDATE analytics.worker_state SET mock_seeded_through = NULL")
                )
            await park(engine)
            first_stats = await run_pass(store, FakeScorer(), now=NOW, settings=settings)
            async with engine.connect() as conn:
                days = (
                    await conn.execute(
                        text(
                            "SELECT count(DISTINCT (started_at AT TIME ZONE :tz)::date) "
                            "FROM analytics.interactions WHERE source = 'mock'"
                        ),
                        {"tz": settings.analytics_timezone},
                    )
                ).scalar_one()
                real = (
                    await conn.execute(
                        text("SELECT count(*) FROM analytics.interactions WHERE source = 'real'")
                    )
                ).scalar_one()
                first = await snapshot(conn)

            await park(engine)
            second_stats = await run_pass(store, FakeScorer(), now=NOW, settings=settings)
            async with engine.connect() as conn:
                second = await snapshot(conn)

            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM analytics.interaction_intents"))
                await conn.execute(text("DELETE FROM analytics.interactions"))
                await conn.execute(
                    text("UPDATE analytics.worker_state SET mock_seeded_through = NULL")
                )
            await park(engine)
            await run_pass(store, FakeScorer(), now=NOW, settings=settings)
            async with engine.connect() as conn:
                third = await snapshot(conn)
            return {
                "days": days,
                "real": real,
                "first_stats": first_stats,
                "second_stats": second_stats,
                "first": first,
                "second": second,
                "third": third,
            }
        finally:
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM analytics.interaction_intents"))
                await conn.execute(text("DELETE FROM analytics.interactions"))
                await conn.execute(
                    text(
                        "UPDATE analytics.worker_state "
                        "SET watermark = NULL, mock_seeded_through = NULL"
                    )
                )

    got = asyncio.run(with_store(settings, body))

    assert got["days"] == 30
    assert got["real"] == 0
    assert got["first_stats"].mock_days == 30
    assert len(got["first"][0]) > 0
    assert got["second_stats"].mock_days == 0
    assert got["second"] == got["first"]  # a second pass adds nothing
    assert got["third"] == got["first"]  # reseeding from scratch gives the same rows


def _run_worker_over(
    settings: Settings,
    cid: str,
    *,
    between: Callable[[], None],
    scorer: FakeScorer | None = None,
) -> dict[str, Any]:
    """Run one worker pass (idle threshold passed) and read back the rows of `cid`.

    `between` runs after the conversation exists and before the pass (the ES test
    returns the handoff there). The turns ran on `app_client`'s own loop, so the
    worker gets its own engine from `with_store`.
    """

    async def body(store: PostgresAnalyticsStore, engine: AsyncEngine) -> dict[str, Any]:
        try:
            between()
            await run_pass(
                store,
                scorer or FakeScorer(),
                now=datetime.now(UTC) + timedelta(hours=3),
                settings=settings,
            )
            async with engine.connect() as conn:
                interaction = (
                    (
                        await conn.execute(
                            text("SELECT * FROM analytics.interactions WHERE conversation_id = :c"),
                            {"c": uuid.UUID(cid)},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                intents = (
                    (
                        await conn.execute(
                            text(
                                "SELECT * FROM analytics.interaction_intents "
                                "WHERE conversation_id = :c ORDER BY seq"
                            ),
                            {"c": uuid.UUID(cid)},
                        )
                    )
                    .mappings()
                    .all()
                )
            return {"interaction": interaction, "intents": intents}
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM analytics.interaction_intents WHERE conversation_id = :c"),
                    {"c": uuid.UUID(cid)},
                )
                await conn.execute(
                    text("DELETE FROM analytics.interactions WHERE conversation_id = :c"),
                    {"c": uuid.UUID(cid)},
                )
                await conn.execute(
                    text(
                        "UPDATE analytics.worker_state "
                        "SET watermark = NULL, mock_seeded_through = NULL"
                    )
                )

    return asyncio.run(with_store(settings, body))


def test_worker_es_multi_intent(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
    analytics_settings: Settings,
) -> None:
    """A read answered and a bank-side unlock handed off, in one conversation (D5, D6)."""
    dsn = _psycopg_dsn(it_db)
    restore_cards.add("PRD-TFB3DEBT0001")
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language="es",
                    intents=["card_status", "card_unlock"],
                    status="clear",
                    slots=NLUSlots(),
                )
            ],
            "compose": [ComposeDraft(text="Tu tarjeta {card_mask} esta {status}.")],
            "handoff_summary": [
                HandoffSummaryDraft(
                    request="La tarjeta tiene un bloqueo del banco.",
                    asked="Pidió ayuda.",
                    did="Nada.",
                    unfinished="Todo.",
                )
            ],
        }
    )
    csrf = _login(app_client, it_accounts[_BLOCKED_CUSTOMER_ID])
    created = app_client.post("/api/v1/conversations", json={}, headers={CSRF_HEADER: csrf})
    cid = created.json()["conversation_id"]
    sent = app_client.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"text": "como esta mi tarjeta y desbloqueala"},
        headers={CSRF_HEADER: csrf},
    )
    _wait_for_bot_message(dsn, sent.json()["turn_id"])

    def return_handoff() -> None:
        # An open handoff gives no row (D2): the agent has handed the conversation back.
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "UPDATE app.handoffs SET status = 'returned' WHERE conversation_id = %s",
                (uuid.UUID(cid),),
            )

    got = _run_worker_over(analytics_settings, cid, between=return_handoff)

    assert [r["outcome"] for r in got["intents"]] == ["resolved", "handoff"]
    assert got["interaction"] is not None
    assert got["interaction"]["resolved"] is False
    assert got["interaction"]["escalated"] is True
    assert got["interaction"]["language"] == "es"


def test_worker_pt_write_happy_path(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_db: str,
    restore_cards: set[str],
    analytics_settings: Settings,
) -> None:
    """A temporary lock with its confirmation: one resolved `card_block` over two turns."""
    dsn = _psycopg_dsn(it_db)
    restore_cards.add(_SINGLE_CARD_ID)
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [
                NLUResult(
                    language="pt",
                    intents=["card_block"],
                    status="clear",
                    slots=NLUSlots(block_kind="temporary_lock"),
                )
            ]
        }
    )
    csrf = _login(app_client, it_accounts[_SINGLE_CUSTOMER_ID])
    # The interaction's language is the conversation's (set when it starts), not the NLU's.
    created = app_client.post(
        "/api/v1/conversations", json={"language": "pt"}, headers={CSRF_HEADER: csrf}
    )
    cid = created.json()["conversation_id"]
    base_url = f"/api/v1/conversations/{cid}"
    ask = app_client.post(
        f"{base_url}/messages",
        json={"text": f"quero bloquear meu cartao temporariamente, meu email e {_RAW_EMAIL}"},
        headers={CSRF_HEADER: csrf},
    )
    token = _confirm_token(_wait_for_bot_message(dsn, ask.json()["turn_id"])["ui_payload"])
    confirmed = app_client.post(
        f"{base_url}/confirmations/{token}",
        json={"decision": "confirm"},
        headers={CSRF_HEADER: csrf},
    )
    _wait_for_bot_message(dsn, confirmed.json()["turn_id"])

    # The raw value is stored encrypted in `content`; `content_masked` holds the token.
    with psycopg.connect(dsn) as conn:
        masked_rows = conn.execute(
            "SELECT content_masked FROM app.messages "
            "WHERE conversation_id = %s AND role = 'customer'",
            (uuid.UUID(cid),),
        ).fetchall()
    assert any(TOKEN_RE.search(r[0]) and _RAW_EMAIL not in r[0] for r in masked_rows)

    scorer = RecordingScorer()
    got = _run_worker_over(analytics_settings, cid, between=lambda: None, scorer=scorer)

    # R5: the scorer got only tokenized text (the store reads `content_masked`).
    assert scorer.seen
    assert all(_RAW_EMAIL not in m for m in scorer.seen)
    assert any(TOKEN_RE.search(m) for m in scorer.seen)

    assert [(r["intent"], r["outcome"], r["turns"]) for r in got["intents"]] == [
        ("card_block", "resolved", 2)
    ]
    assert got["interaction"] is not None
    assert got["interaction"]["resolved"] is True
    assert got["interaction"]["language"] == "pt"
    # Privacy (REQ-R2): no message text and no customer id in either table.
    banned = {"customer_id", "content", "content_masked", "text", "message"}
    assert not banned & set(got["interaction"].keys())
    assert not banned & set(got["intents"][0].keys())
