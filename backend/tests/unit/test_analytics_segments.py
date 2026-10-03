"""The per-intent segments the turn graph records for analytics (spec D2, D14, D17, R3).

Both tests read the segments off the graph's own node updates, the way the
runner does, with a scripted LLM.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.domains.analytics.worker import (
    ConversationFacts,
    MessageFact,
    ReplyFact,
    StepCost,
    compute_interaction,
)
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots
from app.domains.conversation.state import IntentSegment
from tests.conftest import ScriptedLLM, Session, make_session
from tests.unit.test_r3_flows import _UnverifiedLockWrites


async def _turn_segments(session: Session, text: str) -> list[IntentSegment]:
    """Run one typed turn and collect the `intent_segments` its nodes appended."""
    segments: list[IntentSegment] = []
    inputs: Any = {"user_text": text, "confirmation": None, "resume": None, "selection": None}
    async for update in session.graph.astream(inputs, config=session.config, stream_mode="updates"):
        for values in update.values():
            segments.extend((values or {}).get("intent_segments") or [])
    return segments


def _nlu(*intents: Intent, slots: NLUSlots | None = None) -> NLUResult:
    return NLUResult(
        language="es", intents=list(intents), status="clear", slots=slots or NLUSlots()
    )


def test_segments_multi_intent(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [_nlu("card_status", "card_unlock")],
                "compose": [ComposeDraft(text="{card_kind} {card_mask} {status} {expiry}")],
                "handoff_summary": [
                    HandoffSummaryDraft(request="Bloqueo del banco en {queue_label}.")
                ],
            }
        )
        # A past-due card: the status read answers, the unlock is a bank-side block.
        session = make_session("CLI-TFPASTD00005", fakebank_dir, llm)

        segments = await _turn_segments(session, "como esta mi tarjeta y desbloqueala")

        assert [(s["intent"], s["status"]) for s in segments] == [
            ("card_status", "resolved"),
            ("card_unlock", "handoff"),
        ]

    asyncio.run(run())


def test_segments_write_flow(fakebank_dir: Path) -> None:
    lock = _nlu("card_block", slots=NLUSlots(block_kind="temporary_lock"))

    async def run() -> None:
        # Ask, then a verified confirmation.
        llm = ScriptedLLM({"nlu": [lock, _nlu("affirm")]})
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        ask = await _turn_segments(session, "bloquea mi tarjeta")
        assert ask == [
            {
                "intent": "card_block",
                "route": "card_block",
                "status": "awaiting",
                "awaiting_slot": "confirmation",
            }
        ]
        done = await _turn_segments(session, "si")
        state = await session.graph.aget_state(session.config)
        assert state.values["actions"][-1].verified is True
        assert [(s["intent"], s["status"]) for s in done] == [("card_block", "resolved")]

        # Ask, then a "no".
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, ScriptedLLM({"nlu": [lock, _nlu("deny")]})
        )
        await _turn_segments(session, "bloquea mi tarjeta")
        cancelled = await _turn_segments(session, "no")
        assert [(s["intent"], s["status"]) for s in cancelled] == [("card_block", "cancelled")]

        # A write that does not read back verified is never `resolved`.
        llm = ScriptedLLM(
            {
                "nlu": [lock, _nlu("affirm")],
                "handoff_summary": [
                    HandoffSummaryDraft(request="Acción sin verificar en {queue_label}.")
                ],
            }
        )
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, raw_writes=_UnverifiedLockWrites()
        )
        await _turn_segments(session, "bloquea mi tarjeta")
        unverified = await _turn_segments(session, "si")
        assert [(s["intent"], s["status"]) for s in unverified] == [("card_block", "handoff")]

    asyncio.run(run())


def test_served_by_agent_and_agent_cost() -> None:
    """D24: replies all written by the agent give `served_by == "agent"` and its step cost."""
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    facts = ConversationFacts(
        conversation_id="c1",
        status="closed",
        language="es",
        channel="web",
        country_label=None,
        messages=[
            MessageFact("customer", "t1", now, "hola"),
            MessageFact("bot", "t1", now, "hola"),
        ],
        replies=[ReplyFact("card_status", False, [], path="agent")],
        handoffs=[],
        step_costs={"agent": StepCost(Decimal("0.012"), 2)},
    )

    computed = compute_interaction(facts, now=now, idle_minutes=30)

    assert computed is not None
    row, _ = computed
    assert row.served_by == "agent"
    assert row.cost_agent_usd == Decimal("0.012")
