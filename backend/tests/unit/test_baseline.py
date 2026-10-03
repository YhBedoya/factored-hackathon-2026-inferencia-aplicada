"""Keyword baseline NLU (ADR-005): precedence, negation window, ambiguity, out-of-market."""

import asyncio
from pathlib import Path
from typing import cast

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domains.conversation.baseline.keyword_nlu import keyword_nlu
from app.domains.conversation.graph import build_graph, run_turn
from app.domains.conversation.templates import get_template
from tests.conftest import ScriptedLLM, make_session, strip_closing


@pytest.mark.parametrize(
    ("text", "language", "intents", "status", "clarification", "topic"),
    [
        (
            "No reconozco este cargo, bloquea mi tarjeta",
            "es",
            ["unrecognized_charge"],
            "clear",
            None,
            None,
        ),
        (
            "Não reconheço essa compra e quero bloquear o cartão",
            "pt",
            ["unrecognized_charge"],
            "clear",
            None,
            None,
        ),
        ("Ya no quiero bloquearla, ¿cuál es mi saldo?", "es", ["balance_due"], "clear", None, None),
        ("Não quero bloquear, qual é o meu saldo?", "pt", ["balance_due"], "clear", None, None),
        ("Quiero bloquear mi tarjeta", "es", ["card_block"], "ambiguous", "lock_vs_block", None),
        ("Quero bloquear meu cartão", "pt", ["card_block"], "ambiguous", "lock_vs_block", None),
        ("no quiero bloquear mi tarjeta", "es", [], "out_of_scope", None, "other"),
        ("não quero bloquear o cartão", "pt", [], "out_of_scope", None, "other"),
        ("¿Puedo pagar con Pix?", "es", [], "out_of_market", None, "pix_boleto"),
        ("Preciso pagar um boleto", "pt", [], "out_of_market", None, "pix_boleto"),
    ],
)
def test_keyword_nlu_es_pt(text, language, intents, status, clarification, topic):
    result = keyword_nlu(text)
    assert result.language == language
    assert result.intents == intents
    assert result.status == status
    assert result.clarification == clarification
    assert result.slots.topic == topic


def test_baseline_turn_makes_no_llm_call(fakebank_dir: Path) -> None:
    class _NoLLM:
        async def structured(self, **_: object) -> object:
            raise AssertionError("the baseline must not call the LLM")

    session = make_session("CLI-TFSINGLE0002", fakebank_dir, cast(ScriptedLLM, _NoLLM()))
    graph = build_graph(MemorySaver(), system="baseline")

    reply, _ = asyncio.run(
        run_turn(graph, "cual es el estado de mi tarjeta?", config=session.config)
    )

    expected = get_template("goal_card_status", "es").format(
        card_kind="Crédito", card_mask="•••• 2222", status="Activa", expiry="30/11/2027"
    )
    assert strip_closing(reply, "es") == expected
