"""s0-empty-reply: a non-answer keeps the open flow question; no reply is empty.

Fake LLM only. A non-answer is an NLU result with no intent and no slot; the
open question is replayed once, and the second one in a row hands off. Turns are
driven with `asyncio.run`, state is read with `aget_state`.
"""

import asyncio
from pathlib import Path

from app.domains.conversation.graph import GraphState, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.nodes.next_intent import finish
from app.domains.conversation.sandbox import _RecordingBankTools
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from tests.conftest import ScriptedLLM, make_session


def _non_answer(language: str) -> NLUResult:
    return NLUResult(language=language, intents=[], status="clear")  # type: ignore[arg-type]


def test_non_answer_keeps_card_question_es(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    _non_answer("es"),
                    NLUResult(language="es", intents=["card_block"], status="clear"),
                    _non_answer("es"),
                    _non_answer("es"),
                ],
                "handoff_summary": [HandoffSummaryDraft(request="No aclaró la tarjeta.")],
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        tools = _RecordingBankTools(session.config["configurable"]["bank_tools"])
        session.config["configurable"]["bank_tools"] = tools

        reply0, _ = await run_turn(session.graph, "mmm", config=session.config)
        assert reply0 == get_template("clarify_rephrase", "es")
        state = await session.graph.aget_state(session.config)
        assert state.values.get("non_answer_failures", 0) == 0

        reply1, _ = await run_turn(session.graph, "quiero bloquear", config=session.config)
        assert reply1 == "¿Cuál tarjeta quieres bloquear?"
        asked = await session.graph.aget_state(session.config)
        asked_ui = asked.values["ui"]
        assert len(asked_ui) == 1

        calls_before = len(tools.calls)
        reply2, debug2 = await run_turn(session.graph, "Todas", config=session.config)
        assert reply2 == reply1
        assert debug2.pending == "card_block.card_hint"
        assert debug2.route == "card_block"
        replayed = await session.graph.aget_state(session.config)
        assert replayed.values["ui"] == asked_ui
        assert replayed.values["open_question"] == asked.values["open_question"]
        assert tools.calls[calls_before:] == ["get_profile"]

        reply3, _ = await run_turn(session.graph, "Todas", config=session.config)
        assert reply3 != reply1
        final = await session.graph.aget_state(session.config)
        assert session.handoff_tools.created[-1].reason == "clarification_exhausted"
        assert final.values["open_question"] is None

    asyncio.run(run())


def test_non_answer_keeps_card_question_pt(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="pt", intents=["card_block"], status="clear"),
                    _non_answer("pt"),
                    NLUResult(
                        language="pt",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(card_hint="credit"),
                    ),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        reply1, debug1 = await run_turn(
            session.graph, "quero bloquear meu cartão", config=session.config
        )
        assert reply1 == "Qual cartão você quer bloquear?"
        assert debug1.pending == "card_block.card_hint"
        asked = await session.graph.aget_state(session.config)

        reply2, debug2 = await run_turn(session.graph, "Todos", config=session.config)
        assert reply2 == reply1
        assert debug2.pending == "card_block.card_hint"
        replayed = await session.graph.aget_state(session.config)
        assert replayed.values["pending"] == asked.values["pending"]
        assert replayed.values["open_question"] == asked.values["open_question"]

        reply3, debug3 = await run_turn(session.graph, "o de crédito", config=session.config)
        assert debug3.pending == "card_block.block_kind"
        moved = await session.graph.aget_state(session.config)
        assert moved.values["open_question"]["text"] == reply3

    asyncio.run(run())


def test_finish_never_sends_empty_reply() -> None:
    for language in ("es", "pt"):
        state: GraphState = {
            "customer_id": "C",
            "language": language,
            "segments": [],
            "mode": "bot",
        }  # type: ignore[typeddict-item]
        assert finish(state)["reply"] == get_template("fallback", language)  # type: ignore[arg-type]
    human: GraphState = {"customer_id": "C", "language": "es", "segments": [], "mode": "human"}
    assert finish(human)["reply"] == ""


def test_r2_non_answer_on_confirmation_never_writes(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="ambiguous",
                        clarification="lock_vs_block",
                    ),
                    _non_answer("es"),
                    NLUResult(
                        language="es",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    _non_answer("es"),
                    _non_answer("es"),
                ],
                "handoff_summary": [HandoffSummaryDraft(request="No confirmó.")],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        reply1, debug1 = await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        assert reply1 == get_template("clarify_lock_vs_block", "es")
        assert debug1.pending == "card_block.block_kind"
        asked_kind = await session.graph.aget_state(session.config)

        reply2, debug2 = await run_turn(session.graph, "mmm", config=session.config)
        assert reply2 == reply1
        assert debug2.ui == ["quick_replies"]
        assert debug2.pending == "card_block.block_kind"
        assert (
            asked_kind.values["ui"] == (await session.graph.aget_state(session.config)).values["ui"]
        )
        assert not session.handoff_tools.created

        _, debug3 = await run_turn(session.graph, "temporal", config=session.config)
        assert debug3.pending == "card_block.confirmation"
        asked = await session.graph.aget_state(session.config)
        token_id = asked.values["confirmation_token_id"]
        confirm_reply = asked.values["open_question"]["text"]

        reply4, debug4 = await run_turn(session.graph, "eh", config=session.config)
        assert reply4 == confirm_reply
        assert debug4.pending == "card_block.confirmation"
        replayed = await session.graph.aget_state(session.config)
        assert replayed.values["ui"] == asked.values["ui"]
        assert replayed.values["confirmation_token_id"] == token_id
        assert len(session.store._plans) == 1
        assert session.overlay.locked == set()
        assert session.overlay.blocked == set()

        await run_turn(session.graph, "eh", config=session.config)
        assert session.handoff_tools.created[-1].reason == "clarification_exhausted"
        assert token_id not in session.store._plans
        assert session.overlay.locked == set()
        assert session.overlay.blocked == set()

    asyncio.run(run())
