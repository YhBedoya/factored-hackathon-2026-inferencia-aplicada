"""B8: three scripted conversations, driven through `run_turn` (fake LLM only).

See the spec's Test list rows for `test_sandbox_conversations.py` and `07` D1's
end-of-day test step 4. Each test builds the compiled graph, a fresh
`ToolContext`/`FakeBank` over a TEST FIXTURE customer, and a `ScriptedLLM`
that stands in for the NLU/compose calls a real turn would make -- no
network, no `data/`.
"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from app.core.errors import ToolUnavailable
from app.domains.cards.schemas import CardSummary
from app.domains.conversation.graph import build_graph, run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from tests.conftest import ScriptedLLM


def _config(ctx: ToolContext, bank_tools: FakeBank, llm: ScriptedLLM, thread_id: str) -> Any:
    return {
        "configurable": {
            "thread_id": thread_id,
            "session": ctx,
            "bank_tools": bank_tools,
            "llm": llm,
        }
    }


def test_es_multi_card_asks_then_answers(fakebank_dir: Path) -> None:
    """`07` D1 end-of-day step 4a: which-card, then status/expiry/limit/available."""
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    ask_nlu = NLUResult(language="es", intents=["card_status"], status="clear", slots=NLUSlots())
    answer_nlu = NLUResult(
        language="es",
        intents=["card_status"],
        status="clear",
        slots=NLUSlots(card_hint="credit"),
    )
    ask_draft = ComposeDraft(text="Cual tarjeta queres consultar?\n{card_options}")
    answer_draft = ComposeDraft(
        text=(
            "Tu tarjeta {card_kind} {card_mask} esta {status}. Vence el {expiry}. "
            "Limite {credit_limit}, disponible {available_credit}."
        )
    )
    llm = ScriptedLLM({"nlu": [ask_nlu, answer_nlu], "compose": [ask_draft, answer_draft]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-es-multi")

    reply1, debug1 = asyncio.run(
        run_turn(graph, "hola, cual es el estado de mi tarjeta?", config=config)
    )
    assert debug1.route == "card_info"
    assert "Crédito" in reply1
    assert "6475" in reply1

    reply2, debug2 = asyncio.run(run_turn(graph, "la de credito", config=config))
    assert debug2.route == "card_info"
    assert reply2 == (
        "Tu tarjeta Crédito •••• 6475 esta Activa. Vence el 31/08/2027. "
        "Limite US$5,000.00, disponible US$3,765.50."
    )


def test_pt_single_card_answers_in_pt(fakebank_dir: Path) -> None:
    """B6: the PT question to a one-card customer answers directly, in PT."""
    ctx = ToolContext(
        customer_id="CLI-TFSINGLE0002",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    nlu = NLUResult(language="pt", intents=["card_status"], status="clear", slots=NLUSlots())
    draft = ComposeDraft(text="Seu cartao {card_kind} {card_mask} esta {status}.")
    llm = ScriptedLLM({"nlu": [nlu], "compose": [draft]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-pt-single")

    reply, debug = asyncio.run(run_turn(graph, "qual e o status do meu cartao?", config=config))
    assert debug.route == "card_info"
    assert debug.language == "pt"
    assert reply == "Seu cartao Crédito •••• 2222 esta Ativo."


def test_pix_routes_out_of_market(fakebank_dir: Path) -> None:
    """B8: Pix asks about a rail this bank doesn't support here (`out_of_market`)."""
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    nlu = NLUResult(
        language="es", intents=["general_question"], status="out_of_market", slots=NLUSlots()
    )
    llm = ScriptedLLM({"nlu": [nlu]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-pix")

    reply, debug = asyncio.run(run_turn(graph, "quiero pagar con Pix", config=config))
    assert debug.status == "out_of_market"
    assert debug.route == "unsupported"
    assert reply == get_template("out_of_market", "es")
    assert all(call.step != "compose" for call in llm.calls)


def test_es_greeting_gets_cardy_template(fakebank_dir: Path) -> None:
    """Brand: a lone greeting gets Cardy's fixed intro, no compose call."""
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    nlu = NLUResult(language="es", intents=["greeting"], status="clear", slots=NLUSlots())
    llm = ScriptedLLM({"nlu": [nlu]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-greeting")

    reply, debug = asyncio.run(run_turn(graph, "hola", config=config))
    assert debug.route == "unsupported"
    assert reply == get_template("greeting", "es")
    assert all(call.step != "compose" for call in llm.calls)


class _DownBank(FakeBank):
    async def list_cards(self) -> list[CardSummary]:
        raise ToolUnavailable("down")


def test_pt_tool_unavailable_gets_tool_error_template(fakebank_dir: Path) -> None:
    """Brand/D15: a failed card read says so and that nothing changed, in PT."""
    ctx = ToolContext(
        customer_id="CLI-TFSINGLE0002",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = _DownBank(ctx, fakebank_dir)
    nlu = NLUResult(language="pt", intents=["card_status"], status="clear", slots=NLUSlots())
    llm = ScriptedLLM({"nlu": [nlu]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, "t-tool-down")

    reply, debug = asyncio.run(run_turn(graph, "qual e o status do meu cartao?", config=config))
    assert debug.route == "card_info"
    assert reply == get_template("tool_error", "pt")
