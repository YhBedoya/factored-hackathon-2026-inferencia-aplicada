"""B3: conversation basics routed through `smalltalk` (fake LLM only).

See the spec's Test list row for `test_conversation_basics.py` and this
card's plan §"Components" -> "Graph shape" (Basics). Four sequential turns
on one thread, each carrying only a conversation-management intent, must
each get their own fixed template and never reach `compose` (no LLM call
beyond `understand`).
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.domains.conversation.graph import ConfirmationDecision, build_graph, run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.localization import format_date, local_today
from app.domains.policy.min_payment import load_min_payment_policy, next_due_date
from tests.conftest import ScriptedLLM, make_session, strip_closing


def _config(ctx: ToolContext, bank_tools: FakeBank, llm: ScriptedLLM, thread_id: str) -> Any:
    return {
        "configurable": {
            "thread_id": thread_id,
            "session": ctx,
            "bank_tools": bank_tools,
            "llm": llm,
        }
    }


def test_greeting_thanks_bare_yes_no(fakebank_dir: Path) -> None:
    """A lone greeting, a bare "sí", a thanks and then "no" each get their own
    template through `smalltalk`, no `compose` call. Thanks asks "anything
    else?" and the "no" to it closes the conversation.
    """
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)

    def _nlu(intent: str) -> NLUResult:
        return NLUResult(language="es", intents=[intent], status="clear", slots=NLUSlots())

    llm = ScriptedLLM(
        {"nlu": [_nlu("greeting"), _nlu("affirm"), _nlu("thanks_close"), _nlu("deny")]}
    )
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-basics")

    reply1, debug1 = asyncio.run(run_turn(graph, "hola", config=config))
    assert debug1.route == "smalltalk"
    assert reply1 == "Hola, Prueba. Soy Cardy, de Swip. ¿Qué necesitas hoy con tu tarjeta?"

    reply2, debug2 = asyncio.run(run_turn(graph, "si", config=config))
    assert debug2.route == "smalltalk"
    assert reply2 == get_template("ask_what_else", "es")

    reply3, debug3 = asyncio.run(run_turn(graph, "perfecto muchas gracias", config=config))
    assert debug3.route == "smalltalk"
    assert reply3 == get_template("anything_else", "es")
    assert debug3.pending == "smalltalk.anything_else"

    reply4, debug4 = asyncio.run(run_turn(graph, "no, eso es todo", config=config))
    assert debug4.route == "smalltalk"
    assert reply4 == get_template("farewell", "es")
    assert debug4.ui == ["conversation_closed"]
    assert debug4.pending is None

    assert all(call.step != "compose" for call in llm.calls)


def test_pt_thanks_then_yes_keeps_conversation_open(fakebank_dir: Path) -> None:
    """PT: "obrigado" asks "anything else?"; "sim" to it asks what, and the
    conversation stays open (no `conversation_closed`).
    """
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)

    def _nlu(intent: str) -> NLUResult:
        return NLUResult(language="pt", intents=[intent], status="clear", slots=NLUSlots())

    llm = ScriptedLLM({"nlu": [_nlu("thanks_close"), _nlu("affirm")]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-basics-pt")

    reply1, debug1 = asyncio.run(run_turn(graph, "obrigado", config=config))
    assert reply1 == get_template("anything_else", "pt")
    assert debug1.pending == "smalltalk.anything_else"

    reply2, debug2 = asyncio.run(run_turn(graph, "sim", config=config))
    assert reply2 == get_template("ask_what_else", "pt")
    assert debug2.pending is None
    assert debug2.ui == []


def test_block_then_balance_in_order(fakebank_dir: Path) -> None:
    """B3 Done-when: "bloquea mi tarjeta y dime mi saldo" -> clarification ->
    confirm -> `action_done` then the balance segment, in that order, with
    an empty queue at the end (D15, D20's queue).
    """

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block", "balance_due"],
                        status="clear",
                        slots=NLUSlots(card_hint="credit"),
                    ),
                    NLUResult(
                        language="es",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                ],
                "compose": [ComposeDraft(text="{due_date}")],
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        reply1, debug1 = await run_turn(
            session.graph, "bloquea mi tarjeta y dime mi saldo", config=session.config
        )
        assert reply1 == get_template("clarify_lock_vs_block", "es")
        assert debug1.pending == "card_block.block_kind"
        state1 = await session.graph.aget_state(session.config)
        assert state1.values["intent_queue"] == ["card_block", "balance_due"]

        reply2, debug2 = await run_turn(
            session.graph, "quiero un bloqueo temporal", config=session.config
        )
        assert debug2.pending == "card_block.confirmation"
        assert "6475" in reply2

        state2 = await session.graph.aget_state(session.config)
        token_id = state2.values["confirmation_token_id"]
        assert isinstance(token_id, str)

        reply3, debug3 = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        due_date_text = format_date(next_due_date(local_today("MX"), load_min_payment_policy()))
        parts = reply3.split("\n\n")
        assert len(parts) == 4
        assert "quedó bloqueada temporalmente a las" in parts[0]
        assert parts[1] == due_date_text
        assert parts[2] == get_template("synthetic_footnote", "es")
        assert parts[3] == get_template("closing_question", "es")
        assert debug3.pending == "smalltalk.anything_else"
        state3 = await session.graph.aget_state(session.config)
        assert state3.values["intent_queue"] == []
        assert "PRD-TFM1CRED0001" in session.overlay.locked

    asyncio.run(run())


async def _closing_chips(session: Any) -> list[str]:
    state = await session.graph.aget_state(session.config)
    chips = [e for e in state.values["ui"] if e.kind == "quick_replies"]
    assert [e.payload.slot for e in chips] == ["closing"]
    return [o.label for o in chips[0].payload.options]


def test_cancelled_confirmation_ends_with_closing_es(fakebank_dir: Path) -> None:
    """A cancelled confirmation card still closes the flow with the question and chips."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    )
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]

        reply, debug = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="cancel"),
        )
        assert strip_closing(reply, "es") == get_template("action_cancelled", "es")
        assert debug.pending == "smalltalk.anything_else"
        assert await _closing_chips(session) == ["Algo más", "Terminar"]
        assert session.overlay.locked == set()

    asyncio.run(run())


def test_answered_status_query_ends_with_closing_pt(fakebank_dir: Path) -> None:
    """An answered read-only query closes the flow with the question and chips."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt", intents=["card_status"], status="clear", slots=NLUSlots()
                    )
                ],
                "compose": [ComposeDraft(text="Seu cartao {card_kind} {card_mask} esta {status}.")],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        reply, debug = await run_turn(
            session.graph, "qual e o status do meu cartao?", config=session.config
        )
        assert strip_closing(reply, "pt") == "Seu cartao Crédito •••• 2222 esta Ativo."
        assert debug.pending == "smalltalk.anything_else"
        assert await _closing_chips(session) == ["Mais alguma coisa", "Encerrar"]

    asyncio.run(run())
