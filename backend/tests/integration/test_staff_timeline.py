"""D7-A A1 Done-when: list filters count exactly what SQL counts, and a
timeline carries masked text only, with its ledger cost.

Seeds its own conversations over the three fixture customers and removes them
afterwards (`it_db` is session-scoped, so later tests must not see them).
"""

# ruff: noqa: E501  (hand-written SQL strings read better on one line)

import asyncio
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from app.domains.audit import timeline

MX, CO, AR = "CLI-TFMULTI00001", "CLI-TFSINGLE0002", "CLI-TFBLOCKD0003"
D1 = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
D2 = datetime(2026, 3, 20, 23, 30, tzinfo=UTC)
RAW = "RAWMARK"

# (customer, language, started_at, intents, reply route, ui_kinds, nlu status, handoff queue)
_SEEDS: list[dict[str, Any]] = [
    {"customer": MX, "lang": "es", "at": D1, "intents": ["card_block"], "route": "answer"},
    {"customer": CO, "lang": "es", "at": D1, "intents": ["dispute"], "route": "abstain"},
    {
        "customer": AR,
        "lang": "pt",
        "at": D2,
        "intents": ["card_block", "dispute"],
        "route": "answer",
        "ui": ["card_picker"],
    },
    {
        "customer": MX,
        "lang": "pt",
        "at": D2,
        "intents": ["dispute"],
        "route": "answer",
        "queue": "fraudes",
    },
    {"customer": CO, "lang": "pt", "at": D1, "intents": ["card_block"], "route": None},
    {
        "customer": AR,
        "lang": "es",
        "at": D2,
        "intents": ["card_block"],
        "route": "answer",
        "nlu_status": "ambiguous",
    },
    # A handoff with no `reply_sent` still has a handoff outcome.
    {
        "customer": CO,
        "lang": "es",
        "at": D2,
        "intents": ["dispute"],
        "route": None,
        "queue": "atencion",
    },
]

_EVENT_SQL = text(
    """
    INSERT INTO audit.audit_events
        (id, at, conversation_id, turn_id, actor, type, payload, sources, policy_version)
    VALUES (:id, :at, :cid, :tid, 'bot', :type, CAST(:payload AS jsonb),
            CAST(:sources AS jsonb), 'pv-test')
    """
)
_MESSAGE_SQL = text(
    """
    INSERT INTO app.messages
        (id, conversation_id, turn_id, role, content, content_masked, created_at)
    VALUES (:id, :cid, :tid, :role, :content, :masked, :at)
    """
)


async def _event(
    conn: Any,
    cid: uuid.UUID,
    tid: uuid.UUID,
    at: datetime,
    type_: str,
    payload: dict[str, Any],
    sources: list[str] | None = None,
) -> None:
    await conn.execute(
        _EVENT_SQL,
        {
            "id": uuid.uuid4(),
            "at": at,
            "cid": cid,
            "tid": tid,
            "type": type_,
            "payload": json.dumps(payload),
            "sources": json.dumps(sources or []),
        },
    )


async def _seed_turn(
    conn: Any, cid: uuid.UUID, at: datetime, seed: dict[str, Any], n: int
) -> uuid.UUID:
    tid = uuid.uuid4()
    for role, offset, masked in (
        ("customer", 0, f"hola <PII:{n}>"),
        ("bot", 3, f"respuesta {n}"),
    ):
        await conn.execute(
            _MESSAGE_SQL,
            {
                "id": uuid.uuid4(),
                "cid": cid,
                "tid": tid,
                "role": role,
                "content": f"{RAW}-{uuid.uuid4().hex}",
                "masked": masked,
                "at": at + timedelta(seconds=offset),
            },
        )
    await _event(
        conn,
        cid,
        tid,
        at + timedelta(seconds=1),
        "nlu_result",
        {"intents": seed["intents"], "status": seed.get("nlu_status", "ok")},
    )
    if seed["route"] is not None:
        await _event(
            conn,
            cid,
            tid,
            at + timedelta(seconds=3),
            "reply_sent",
            {"route": seed["route"], "ui_kinds": seed.get("ui", [])},
            ["policies/tools.yaml"],
        )
    return tid


async def _seed(conn: Any) -> list[uuid.UUID]:
    ids = []
    for i, seed in enumerate(_SEEDS):
        cid = uuid.uuid4()
        ids.append(cid)
        await conn.execute(
            text(
                "INSERT INTO app.conversations (id, customer_id, language, started_at) "
                "VALUES (:id, :customer, :lang, :at)"
            ),
            {"id": cid, "customer": seed["customer"], "lang": seed["lang"], "at": seed["at"]},
        )
        turns = 2 if i == 0 else 1
        for n in range(turns):
            tid = await _seed_turn(conn, cid, seed["at"] + timedelta(minutes=n), seed, n)
            if i == 0:
                await _event(
                    conn,
                    cid,
                    tid,
                    seed["at"] + timedelta(minutes=n, seconds=2),
                    "rule_hit",
                    {"rule": "r1"},
                    ["policies/a.yaml"],
                )
                await _event(
                    conn,
                    cid,
                    tid,
                    seed["at"] + timedelta(minutes=n, seconds=2, milliseconds=500),
                    "tool_call",
                    {"tool": "list_cards"},
                    ["bank.products"],
                )
        if seed.get("queue"):
            await conn.execute(
                text(
                    "INSERT INTO app.handoffs (id, conversation_id, queue, reason, priority, packet) "
                    "VALUES (:id, :cid, :queue, 'r', 'normal', CAST('{}' AS jsonb))"
                ),
                {"id": uuid.uuid4(), "cid": cid, "queue": seed["queue"]},
            )
    return ids


async def _seed_ledger(conn: Any, cid: uuid.UUID) -> None:
    first_turn = (
        await conn.execute(
            text(
                "SELECT turn_id FROM app.messages WHERE conversation_id = :c ORDER BY created_at LIMIT 1"
            ),
            {"c": cid},
        )
    ).scalar_one()
    for offset, (cost, trace) in enumerate((("0.001500", "trace-abc"), ("0.002500", None))):
        await conn.execute(
            text(
                """
                INSERT INTO audit.llm_calls
                    (id, at, conversation_id, turn_id, step, provider, model_id, prompt_version,
                     temperature, attempt, status, input_text, output_json, input_tokens,
                     output_tokens, cost_usd, latency_ms, langfuse_trace_id)
                VALUES (:id, :at, :c, :t, 'nlu', 'anthropic', 'm', 'nlu@v1', 0, 1, 'ok',
                        :raw, CAST('{}' AS jsonb), 10, 5, :cost, 120, :trace)
                """
            ),
            {
                "id": uuid.uuid4(),
                "at": D1 + timedelta(seconds=offset),
                "c": cid,
                "t": first_turn,
                "raw": f"{RAW}-input",
                "cost": cost,
                "trace": trace,
            },
        )


async def _sql_count(conn: Any, where: str, ids: list[uuid.UUID]) -> int:
    """Matches among the conversations this test seeded (the DB is shared)."""
    result = await conn.execute(
        text(
            f"SELECT count(*) FROM app.conversations c "
            f"LEFT JOIN bank.customers cu ON cu.customer_id = c.customer_id WHERE ({where}) AND c.id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    return int(result.scalar_one())


_HAS_REPLY = "EXISTS (SELECT 1 FROM audit.audit_events e WHERE e.conversation_id = c.id AND e.type = 'reply_sent')"
_NO_HANDOFF = "NOT EXISTS (SELECT 1 FROM app.handoffs h WHERE h.conversation_id = c.id)"
# D18 follows the LAST reply and that turn's NLU status, not any turn's.
_LAST_REPLY_TURN = (
    "(SELECT e.turn_id FROM audit.audit_events e WHERE e.conversation_id = c.id "
    "AND e.type = 'reply_sent' ORDER BY e.at DESC LIMIT 1)"
)
_LAST_REPLY = (
    "(SELECT e.payload FROM audit.audit_events e WHERE e.conversation_id = c.id "
    "AND e.type = 'reply_sent' ORDER BY e.at DESC LIMIT 1)"
)
_LAST_NLU_STATUS = (
    "(SELECT n.payload->>'status' FROM audit.audit_events n WHERE n.conversation_id = c.id "
    f"AND n.type = 'nlu_result' AND n.turn_id = {_LAST_REPLY_TURN} ORDER BY n.at DESC LIMIT 1)"
)
_ABSTAIN = f"{_LAST_REPLY}->>'route' = 'abstain'"
_PICKER = f"{_LAST_REPLY}->'ui_kinds' @> '[\"card_picker\"]'::jsonb"
_AMBIGUOUS = f"{_LAST_NLU_STATUS} = 'ambiguous'"
_CASES: list[tuple[dict[str, Any], str]] = [
    ({"language": "pt"}, "c.language = 'pt'"),
    ({"country": "CO"}, "cu.country = 'Colombia'"),
    (
        {"intent": "dispute"},
        "EXISTS (SELECT 1 FROM audit.audit_events e WHERE e.conversation_id = c.id "
        "AND e.type = 'nlu_result' "
        "AND e.payload->'intents' @> '\"dispute\"'::jsonb)",
    ),
    ({"outcome": "handoff"}, f"NOT {_NO_HANDOFF}"),
    (
        {"outcome": "handoff:fraudes"},
        "EXISTS (SELECT 1 FROM app.handoffs h WHERE h.conversation_id = c.id AND h.queue = 'fraudes')",
    ),
    ({"outcome": "abstained"}, f"{_NO_HANDOFF} AND {_ABSTAIN}"),
    (
        {"outcome": "clarified"},
        f"{_HAS_REPLY} AND {_NO_HANDOFF} AND NOT {_ABSTAIN} AND ({_PICKER} OR {_AMBIGUOUS})",
    ),
    (
        {"outcome": "resolved"},
        f"{_HAS_REPLY} AND {_NO_HANDOFF} AND NOT {_ABSTAIN} AND NOT {_PICKER} AND NOT {_AMBIGUOUS}",
    ),
    ({"escalation": "none"}, _NO_HANDOFF),
    ({"escalation": "any"}, f"NOT {_NO_HANDOFF}"),
    (
        {"escalation": "fraudes"},
        "EXISTS (SELECT 1 FROM app.handoffs h WHERE h.conversation_id = c.id AND h.queue = 'fraudes')",
    ),
    (
        {"date_from": date(2026, 3, 15)},
        "c.started_at >= '2026-03-15T00:00:00+00'",
    ),
    (
        {"date_to": date(2026, 3, 10)},
        "c.started_at < '2026-03-11T00:00:00+00'",
    ),
    (
        {"language": "es", "country": "AR", "date_from": date(2026, 3, 20)},
        "c.language = 'es' AND cu.country = 'Argentina' AND c.started_at >= '2026-03-20T00:00:00+00'",
    ),
]


async def _run() -> None:
    # `it_db` is session-scoped: earlier tests may have left conversations, so
    # each filter's `total` is compared as a delta against its pre-seed value.
    baseline = [
        (await timeline.list_conversations(limit=200, **filters)).total for filters, _ in _CASES
    ]
    baseline_all = (await timeline.list_conversations(limit=200)).total
    async with get_engine().begin() as conn:
        ids = await _seed(conn)
        await _seed_ledger(conn, ids[0])
    try:
        async with get_engine().connect() as conn:
            for (filters, where), before in zip(_CASES, baseline, strict=True):
                page = await timeline.list_conversations(limit=200, **filters)
                expected = await _sql_count(conn, where, ids)
                assert page.total - before == expected, filters
                assert expected >= 1, filters
            # Paging keeps `total` at every match.
            paged = await timeline.list_conversations(limit=2, offset=1)
            assert len(paged.items) == 2
            assert paged.total - baseline_all == await _sql_count(conn, "TRUE", ids)

        outcomes = {
            item.conversation_id: item.outcome
            for item in (await timeline.list_conversations(limit=200)).items
            if item.conversation_id in ids
        }
        assert [outcomes[i] for i in ids] == [
            "resolved",
            "abstained",
            "clarified",
            "handoff:fraudes",
            None,
            "clarified",
            "handoff:atencion",
        ]

        result = await timeline.get_timeline(ids[0])
        assert [t.customer_text_masked for t in result.turns] == ["hola <PII:0>", "hola <PII:1>"]
        assert [t.bot_text_masked for t in result.turns] == ["respuesta 0", "respuesta 1"]
        first, second = result.turns
        assert first.started_at < second.started_at
        assert [c.cost_usd for c in first.llm_calls] == [0.0015, 0.0025]
        assert first.cost_usd == pytest.approx(0.004)
        assert second.llm_calls == [] and second.cost_usd is None
        assert first.latency_ms == pytest.approx(3000)
        assert first.langfuse_url == "http://langfuse.test/trace/trace-abc"
        assert second.langfuse_url is None
        assert first.sources == ["policies/a.yaml", "bank.products", "policies/tools.yaml"]
        assert len(first.rules) == 1 and len(first.tools) == 1
        assert result.conversation.intents == ["card_block"]
        assert result.conversation.turns == 2
        assert RAW not in result.model_dump_json()
    finally:
        async with get_engine().begin() as conn:
            for table in ("audit.llm_calls", "audit.audit_events", "app.handoffs", "app.messages"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE conversation_id = ANY(:ids)"),
                    {"ids": ids},
                )
            await conn.execute(
                text("DELETE FROM app.conversations WHERE id = ANY(:ids)"), {"ids": ids}
            )


def test_filter_counts_match_sql(it_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse.test/")
    asyncio.run(_run())
    get_engine.cache_clear()
