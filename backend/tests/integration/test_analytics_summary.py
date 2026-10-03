"""The dashboard summary against the fact tables (spec D1, D3, D10-D12).

Runs on the throwaway `it_db`. The oracle is independent of the module under
test: it reads every row of `analytics.*` and recomputes each block in Python,
so a wrong SQL filter or bucket cannot hide behind the same SQL.
"""

import asyncio
import secrets
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.db import get_engine
from app.domains.analytics.dashboard import (
    AnalyticsSummary,
    AppliedFilters,
    get_summary,
    resolve_filters,
)
from app.domains.identity.tokens import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from tests.integration.conftest import ItStaff, _delete_staff, _insert_staff

_RANK = {"negative": 0, "neutral": 1, "positive": 2}
_BUCKETS = ("escalated", "resolved", "abandoned", "abstained", "other")


def _bucket(r: dict[str, Any]) -> str:
    if r["escalated"]:
        return "escalated"
    if r["resolved"]:
        return "resolved"
    if r["abandoned"]:
        return "abandoned"
    if r["abstained"]:
        return "abstained"
    return "other"


async def _insert(
    conn: AsyncConnection,
    ended_at: datetime,
    intents: Sequence[tuple[str, str, bool]] = (),
    **overrides: Any,
) -> uuid.UUID:
    row: dict[str, Any] = {
        "conversation_id": uuid.uuid4(),
        "source": "real",
        "started_at": ended_at - timedelta(minutes=5),
        "ended_at": ended_at,
        "end_reason": "idle",
        "duration_s": 300,
        "language": "es",
        "country": "MX",
        "customer_messages": 2,
        "bot_messages": 3,
        "agent_messages": 0,
        "resolved": None,
        "abandoned": False,
        "abstained": False,
        "escalated": False,
        "cost_usd": 0.01,
        "cost_nlu_usd": 0.004,
        "cost_compose_usd": 0.005,
        "cost_handoff_summary_usd": 0.001,
        "metrics_version": 1,
    }
    row.update(overrides)
    cols = list(row)
    await conn.execute(
        text(
            f"INSERT INTO analytics.interactions ({', '.join(cols)}) "
            f"VALUES ({', '.join(':' + c for c in cols)})"
        ),
        row,
    )
    for seq, (intent, outcome, bot_offered) in enumerate(intents):
        await conn.execute(
            text(
                "INSERT INTO analytics.interaction_intents "
                "(conversation_id, seq, intent, outcome, needed_clarification, turns, bot_offered) "
                "VALUES (:c, :s, :i, :o, false, 1, :b)"
            ),
            {"c": row["conversation_id"], "s": seq, "i": intent, "o": outcome, "b": bot_offered},
        )
    return row["conversation_id"]


async def _forget(conn: AsyncConnection, ids: Sequence[uuid.UUID]) -> None:
    for table in ("analytics.interaction_intents", "analytics.interactions"):
        await conn.execute(
            text(f"DELETE FROM {table} WHERE conversation_id = ANY(:ids)"), {"ids": list(ids)}
        )


async def _seed(conn: AsyncConnection, now: datetime) -> list[uuid.UUID]:
    def ago(days: int, hours: int = 1) -> datetime:
        return now - timedelta(days=days, hours=hours)

    neg = {
        "sentiment_overall": "negative",
        "sentiment_start": "neutral",
        "sentiment_end": "negative",
    }
    pos = {
        "sentiment_overall": "positive",
        "sentiment_start": "negative",
        "sentiment_end": "positive",
    }
    same = {
        "sentiment_overall": "neutral",
        "sentiment_start": "neutral",
        "sentiment_end": "neutral",
    }
    return [
        await _insert(
            conn,
            ago(0),
            [("card_block", "handoff", False)],
            escalated=True,
            resolved=True,
            handoff_queue="atencion",
            handoff_cause_group="fraud",
            time_to_claim_s=30,
            handoff_count=1,
            sentiment_cost_usd=0.002,
            cost_usd=0.05,
            **neg,
        ),
        await _insert(
            conn,
            ago(1),
            [("card_block", "resolved", False), ("balance", "cancelled", True)],
            language="pt",
            country="CO",
            resolved=True,
            sentiment_cost_usd=0.002,
            **pos,
        ),
        await _insert(
            conn,
            ago(1, 3),
            [("balance", "resolved", False)],
            source="mock",
            country="AR",
            resolved=True,
            **same,
        ),
        await _insert(
            conn,
            ago(2),
            [("dispute", "abandoned", False)],
            source="mock",
            language="pt",
            abandoned=True,
            resolved=False,
        ),
        await _insert(
            conn, ago(2, 4), [("limit", "abstained", False)], country="CO", abstained=True
        ),
        # cancelled-only: a bucket "other" row whose only intent is not counted (D3)
        await _insert(conn, ago(3), [("balance", "cancelled", True)], resolved=None),
        await _insert(
            conn,
            ago(3, 5),
            [("card_block", "handoff", False)],
            source="mock",
            language="pt",
            country="AR",
            escalated=True,
            handoff_count=1,
            cost_usd=0.2,
        ),
        await _insert(conn, ago(4), [("balance", "cancelled", False)], resolved=False),
        await _insert(conn, ago(9), [("card_block", "resolved", False)], resolved=True),
    ]


async def _oracle_rows(conn: AsyncConnection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inter = [
        dict(r._mapping) for r in await conn.execute(text("SELECT * FROM analytics.interactions"))
    ]
    ints = [
        dict(r._mapping)
        for r in await conn.execute(
            text("SELECT * FROM analytics.interaction_intents ORDER BY seq")
        )
    ]
    return inter, ints


def _oracle_checks(
    got: AnalyticsSummary, inter: list[dict[str, Any]], ints: list[dict[str, Any]], now: datetime
) -> None:
    f = got.filters
    tz = ZoneInfo(f.timezone)
    rows = [
        r
        for r in inter
        if r["ended_at"] <= now
        and f.date_from <= r["ended_at"].astimezone(tz).date() <= f.date_to
        and f.language in (None, r["language"])
        and f.country in (None, r["country"])
        and f.source in ("all", r["source"])
    ]
    ids = {r["conversation_id"] for r in rows}
    counted = [
        i
        for i in ints
        if i["conversation_id"] in ids and not (i["bot_offered"] and i["outcome"] == "cancelled")
    ]
    n = len(rows)
    resolved = [r for r in rows if r["resolved"]]
    assert got.tiles.interactions == n
    assert got.includes_mock == any(r["source"] == "mock" for r in rows)
    assert (got.tiles.resolution.num, got.tiles.resolution.den) == (
        len(resolved),
        sum(r["resolved"] is not None for r in rows),
    )
    assert (got.tiles.escalation.num, got.tiles.escalation.den) == (
        sum(r["escalated"] for r in rows),
        n,
    )
    total = float(sum(r["cost_usd"] for r in rows))
    assert got.tiles.cost_per_interaction.total_usd == pytest.approx(total)
    assert got.cost.total_usd == pytest.approx(total)
    assert got.tiles.cost_per_interaction.avg_usd == pytest.approx(total / n if n else None)
    msgs = sum(r["customer_messages"] + r["bot_messages"] + r["agent_messages"] for r in rows)
    assert got.tiles.messages_per_interaction.avg == pytest.approx(msgs / n if n else None)
    scored = [r for r in rows if r["sentiment_overall"]]
    assert (got.tiles.negative_sentiment.num, got.tiles.negative_sentiment.den) == (
        sum(r["sentiment_overall"] == "negative" for r in scored),
        len(scored),
    )
    assert got.sentiment.overall.scored == len(scored)
    for level in ("negative", "neutral", "positive"):
        assert getattr(got.sentiment.overall, level) == sum(
            r["sentiment_overall"] == level for r in scored
        )
    pairs = [
        (_RANK[r["sentiment_start"]], _RANK[r["sentiment_end"]])
        for r in rows
        if r["sentiment_start"] and r["sentiment_end"]
    ]
    assert got.sentiment.trajectory.scored == len(pairs)
    assert got.sentiment.trajectory.better == sum(e > s for s, e in pairs)
    assert got.sentiment.trajectory.same == sum(e == s for s, e in pairs)
    assert got.sentiment.trajectory.worse == sum(e < s for s, e in pairs)
    assert got.cost.sentiment_overhead_usd == pytest.approx(
        float(sum(r["sentiment_cost_usd"] or 0 for r in rows))
    )
    assert got.cost.per_resolved.resolved == len(resolved)
    assert got.cost.per_resolved.usd == pytest.approx(total / len(resolved) if resolved else None)

    # per_day: every day, exclusive buckets
    assert [d.day for d in got.per_day] == [
        f.date_from + timedelta(days=k) for k in range((f.date_to - f.date_from).days + 1)
    ]
    for d, cd in zip(got.per_day, got.cost.per_day, strict=True):
        day_rows = [r for r in rows if r["ended_at"].astimezone(tz).date() == d.day]
        counts = Counter(_bucket(r) for r in day_rows)
        assert [getattr(d, b) for b in _BUCKETS] == [counts[b] for b in _BUCKETS]
        assert cd.day == d.day
        assert cd.nlu_usd == pytest.approx(float(sum(r["cost_nlu_usd"] for r in day_rows)))
        assert cd.compose_usd == pytest.approx(float(sum(r["cost_compose_usd"] for r in day_rows)))
        assert cd.handoff_summary_usd == pytest.approx(
            float(sum(r["cost_handoff_summary_usd"] for r in day_rows))
        )
    assert sum(sum(getattr(d, b) for b in _BUCKETS) for d in got.per_day) == got.tiles.interactions

    # intents: D3 rule, count desc then name
    by_intent = Counter(i["intent"] for i in counted)
    expected = sorted(by_intent.items(), key=lambda kv: (-kv[1], kv[0]))
    assert [(x.intent, x.count) for x in got.intents] == expected
    for x in got.intents:
        res = sum(i["outcome"] == "resolved" for i in counted if i["intent"] == x.intent)
        assert (x.resolution.num, x.resolution.den) == (res, x.count)
        assert x.resolution.rate == pytest.approx(res / x.count)

    esc = [r for r in rows if r["escalated"]]
    assert {(x.group, x.count) for x in got.escalations.by_cause_group} == set(
        Counter(r["handoff_cause_group"] for r in esc).items()
    )
    assert {(x.queue, x.count) for x in got.escalations.by_queue} == set(
        Counter(r["handoff_queue"] for r in esc).items()
    )
    claims = sorted(r["time_to_claim_s"] for r in rows if r["time_to_claim_s"] is not None)
    assert got.escalations.time_to_claim_count == len(claims)
    middle = (claims[(len(claims) - 1) // 2] + claims[len(claims) // 2]) / 2 if claims else None
    assert got.escalations.time_to_claim_median_s == pytest.approx(middle)

    recent = sorted(rows, key=lambda r: r["ended_at"], reverse=True)[:50]
    assert [x.conversation_id for x in got.recent] == [r["conversation_id"] for r in recent]
    for x, r in zip(got.recent, recent, strict=True):
        assert x.outcome == _bucket(r)
        assert x.intents == [
            i["intent"] for i in counted if i["conversation_id"] == r["conversation_id"]
        ]


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    finally:
        get_engine.cache_clear()


def test_summary_matches_fact_tables(it_env: None) -> None:
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo(get_settings().analytics_timezone)).date()
    cases: list[AppliedFilters] = [
        resolve_filters(None, None, None, None, "all"),
        resolve_filters(today - timedelta(days=3), today - timedelta(days=1), None, None, "all"),
        resolve_filters(today - timedelta(days=12), None, None, None, "all"),
        resolve_filters(None, None, "pt", None, "all"),
        resolve_filters(None, None, None, "AR", "all"),
        resolve_filters(None, None, None, None, "mock"),
        resolve_filters(None, None, None, None, "real"),
    ]

    async def body() -> None:
        ids: list[uuid.UUID] = []
        try:
            async with get_engine().begin() as conn:
                ids = await _seed(conn, now)
            async with get_engine().connect() as conn:
                inter, ints = await _oracle_rows(conn)
            default = await get_summary(cases[0])
            assert default.tiles.interactions > 0
            assert sum(sum(getattr(d, b) for b in _BUCKETS) for d in default.per_day) == (
                default.tiles.interactions
            )
            # "balance": 2 rows count; the 2 bot-offered cancelled ones do not (D3)
            balance = next(x for x in default.intents if x.intent == "balance")
            assert balance.count == 2
            for f in cases:
                _oracle_checks(await get_summary(f), inter, ints, now)
        finally:
            async with get_engine().begin() as conn:
                await _forget(conn, ids)

    _run(body())


def test_summary_future_and_mock(it_env: None) -> None:
    now = datetime.now(UTC)

    async def body() -> None:
        ids: list[uuid.UUID] = []
        try:
            async with get_engine().begin() as conn:
                past_mock = await _insert(conn, now - timedelta(hours=1), source="mock")
                real = await _insert(conn, now - timedelta(hours=2), source="real")
                future = await _insert(
                    conn,
                    now + timedelta(minutes=5),
                    [("future_intent", "resolved", False)],
                    source="mock",
                    cost_usd=777,
                    resolved=True,
                    escalated=True,
                    sentiment_overall="negative",
                    sentiment_cost_usd=55,
                )
                ids = [past_mock, real, future]
            everything = await get_summary(resolve_filters(None, None, None, None, "all"))
            only_real = await get_summary(resolve_filters(None, None, None, None, "real"))
            assert everything.includes_mock is True
            assert only_real.includes_mock is False
            for got in (everything, only_real):
                assert future not in {x.conversation_id for x in got.recent}
                assert all(x.intent != "future_intent" for x in got.intents)
                assert got.cost.total_usd < 700
                assert got.cost.sentiment_overhead_usd < 50
                assert got.tiles.negative_sentiment.num == 0
                assert got.escalations.by_queue == []
            assert real in {x.conversation_id for x in only_real.recent}
        finally:
            async with get_engine().begin() as conn:
                await _forget(conn, ids)

    _run(body())


@pytest.fixture
def it_admin(it_env: None) -> Iterator[ItStaff]:
    """One admin account (an `it_staff`-style row promoted to `admin`)."""
    admin = ItStaff(
        uuid.uuid4(),
        f"it.admin.{secrets.token_hex(4)}",
        f"it-admin-{secrets.token_hex(4)}",
        "Ada",
        "x",
    )

    async def _create() -> None:
        await _insert_staff([admin])
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "UPDATE identity.accounts SET role='admin', staff_queue=NULL "
                    "WHERE account_id = :id"
                ),
                {"id": str(admin.account_id)},
            )

    asyncio.run(_create())
    get_engine.cache_clear()  # loop-bound: see `it_accounts`
    yield admin
    get_engine.cache_clear()
    asyncio.run(_delete_staff([admin]))
    get_engine.cache_clear()


def _login(client: TestClient, who: ItStaff) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/staff/login", json={"username": who.username, "password": who.password}
    )
    assert response.status_code == 200
    session, csrf = response.cookies[SESSION_COOKIE], response.cookies[CSRF_COOKIE]
    client.cookies.clear()
    return {"Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}", CSRF_HEADER: csrf}


def test_summary_access(
    app_client: TestClient, it_staff: dict[str, ItStaff], it_admin: ItStaff
) -> None:
    url = "/api/v1/staff/analytics/summary"
    agent = app_client.get(url, headers=_login(app_client, it_staff["atencion"]))
    assert agent.status_code == 403
    assert agent.json()["detail"] == "forbidden_role"

    admin = app_client.get(url, headers=_login(app_client, it_admin))
    assert admin.status_code == 200, admin.text
    body = admin.json()
    assert "tiles" in body
    assert body["filters"]["source"] == "all"
