"""Warm abstain (naturalidad-cardy D10, D17): `new_card` is not a replacement and
carries no human chip; loans / other keep their chips; the fallback is first person."""

import asyncio
from pathlib import Path
from typing import Any, Literal

import pytest

from app.domains.conversation.baseline.keyword_nlu import keyword_nlu
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import template_variants
from tests.conftest import ScriptedLLM, make_session

_HUMAN = {"es": "Hablar con una persona", "pt": "Falar com uma pessoa"}


def _turn(
    fakebank_dir: Path, language: Literal["es", "pt"], topic: Any, text: str, draft: str | None
) -> tuple[str, Any, list[Any]]:
    nlu = NLUResult(
        language=language, intents=["general_question"], status="out_of_scope",
        slots=NLUSlots(topic=topic),
    )  # fmt: skip
    script: dict[str, Any] = {"nlu": [nlu]}
    if draft is not None:
        script["compose"] = [ComposeDraft(text=draft)]
    session = make_session("CLI-TFMULTI00001", fakebank_dir, ScriptedLLM(script))
    reply, debug = asyncio.run(run_turn(session.graph, text, config=session.config))
    state = asyncio.run(session.graph.aget_state(session.config)).values
    return reply, debug, state.get("ui") or []


@pytest.mark.parametrize(
    ("language", "text", "forced"),
    [
        ("es", "Quiero solicitar una nueva tarjeta", "Quiero solicitar una nueva tarjeta"),
        ("pt", "Quero solicitar um novo cartão", "Quero solicitar um novo cartão"),
    ],
    ids=["es", "pt"],
)
def test_new_card_not_replacement(
    fakebank_dir: Path, language: Literal["es", "pt"], text: str, forced: str
) -> None:
    reply, debug, ui = _turn(fakebank_dir, language, "new_card", text, None)

    assert debug.route == "abstain"
    assert reply in template_variants("new_card_not_available", language)
    assert all(option.label != _HUMAN[language] for event in ui for option in event.payload.options)
    nlu = keyword_nlu(forced)
    assert nlu.status == "out_of_scope"
    assert nlu.slots.topic == "new_card"


@pytest.mark.parametrize(
    ("language", "topic", "text", "draft", "closest"),
    [
        ("es", "loans", "quiero un préstamo", "Sobre {topic_label}: {closest_action}.", True),
        ("pt", "other", "quero outra coisa", "Sobre {topic_label}: {abstain_reason}.", False),
    ],
    ids=["es-loans", "pt-other"],
)
def test_abstain_warm_keeps_chips(
    fakebank_dir: Path,
    language: Literal["es", "pt"],
    topic: Any,
    text: str,
    draft: str,
    closest: bool,
) -> None:
    _, debug, ui = _turn(fakebank_dir, language, topic, text, draft)

    assert debug.route == "abstain"
    (event,) = ui
    labels = [option.label for option in event.payload.options]
    assert labels[-1] == _HUMAN[language]
    assert (len(labels) == 2) is closest
    marker = "puedo" if language == "es" else ("consigo", "posso")
    for variant in template_variants("abstain_fallback", language):
        assert any(m in variant for m in ([marker] if isinstance(marker, str) else marker))
