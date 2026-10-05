"""Card requests with the agent off: the fixed C7 text, a human chip, no request (D3, R2).

Topic `new_card` and intent `card_cancel` both land on `card_request_unavailable`.
"""

import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest

from app.core.llm import LLMError
from app.domains.conversation.graph import run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import template_variants
from tests.conftest import AgentScript, ScriptedLLM, make_session

_HUMAN = {"es": "Hablar con una persona", "pt": "Falar com uma pessoa"}


def _nlu(case: str, language: Literal["es", "pt"]) -> NLUResult:
    if case == "open":
        return NLUResult(
            language=language, intents=["general_question"], status="out_of_scope",
            slots=NLUSlots(topic="new_card"),
        )  # fmt: skip
    return NLUResult(language=language, intents=["card_cancel"], status="clear", slots=NLUSlots())


@pytest.mark.parametrize(
    ("case", "language", "text"),
    [
        ("open", "es", "Quiero una tarjeta nueva"),
        ("close", "pt", "Quero cancelar meu cartão"),
        ("open", "es", "Quiero una tarjeta nueva"),
        ("close", "pt", "Quero cancelar meu cartão"),
    ],
    ids=["flag_off-open", "flag_off-close", "llm_down-open", "llm_down-close"],
)
def test_card_requests_off_path(
    fakebank_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    case: str,
    language: Literal["es", "pt"],
    text: str,
) -> None:
    llm_down = request.node.callspec.id.startswith("llm_down")
    if llm_down:
        # The agent step raises LLMError: code's keyword check answers (Q2), no NLU call.
        request.getfixturevalue("agent_on")
        llm = ScriptedLLM({"agent": [AgentScript(rounds=[], finals=[LLMError("boom")])]})
    else:
        monkeypatch.setenv("AGENT_ENABLED", "false")
        llm = ScriptedLLM({"nlu": [_nlu(case, language)]})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

    reply, _ = asyncio.run(run_turn(session.graph, text, config=session.config))
    state: dict[str, Any] = asyncio.run(session.graph.aget_state(session.config)).values

    assert reply in template_variants("card_request_unavailable", language)
    (event,) = state.get("ui") or []
    assert [option.label for option in event.payload.options] == [_HUMAN[language]]
    assert session.overlay.card_requests == {}
    assert session.handoff_tools.created == []
    assert [call.step for call in llm.calls] == (["agent"] if llm_down else ["nlu"])


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    "text",
    [
        "quiero bloquear mi otra tarjeta",
        "no reconozco un cargo en mi otra tarjeta",
        "quiero dar de baja el seguro",
        "quero bloquear meu outro cartão",
        "não reconheço uma compra no meu outro cartão",
        "quiero cancelar mi tarjeta robada",
        "me robaron la tarjeta, quiero cancelar la tarjeta",
        "perdí mi tarjeta, quiero cancelar tarjeta y que me manden otra",
        "quero cancelar o cartão roubado",
        "no quiero cancelar la tarjeta",
    ],
)
def test_llm_down_other_messages_are_not_card_requests(fakebank_dir: Path, text: str) -> None:
    # The degraded turn falls to the pipeline, whose NLU is down too.
    llm = ScriptedLLM(
        {
            "agent": [AgentScript(rounds=[], finals=[LLMError("boom")])],
            "nlu": [LLMError("boom")],
            "handoff_summary": [LLMError("boom")],
        }
    )
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

    asyncio.run(run_turn(session.graph, text, config=session.config))
    state: dict[str, Any] = asyncio.run(session.graph.aget_state(session.config)).values

    segments = state.get("segments") or []
    for language in ("es", "pt"):
        assert not set(segments) & set(template_variants("card_request_unavailable", language))
    assert state.get("degraded") is True


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    "text",
    [
        "quiero solicitar una tarjeta, ¿ya fue aprobada?",
        "solicitar una tarjeta preaprobada",
        "quiero cancelar la tarjeta, no quiero pagar más anualidad",
        "quero encerrar meu cartão, não quero mais",
    ],
)
def test_llm_down_whole_word_exclusions_keep_real_requests(fakebank_dir: Path, text: str) -> None:
    llm = ScriptedLLM({"agent": [AgentScript(rounds=[], finals=[LLMError("boom")])]})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

    reply, _ = asyncio.run(run_turn(session.graph, text, config=session.config))

    assert reply in template_variants("card_request_unavailable", "es") + template_variants(
        "card_request_unavailable", "pt"
    )
    assert session.overlay.card_requests == {}
