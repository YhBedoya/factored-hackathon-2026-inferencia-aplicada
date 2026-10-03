"""D8: `card_hint=other` resolves to the card that is not the focus one.

Fake LLM only; turns driven with `asyncio.run`, same shape as `test_state_offers.py`.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.domains.cards.schemas import CardSummary
from app.domains.conversation.flows.card_select import (
    Ask,
    Selected,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import Language
from tests.conftest import ScriptedLLM, make_session

_DRAFT = {
    "es": ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} esta {status}."),
    "pt": ComposeDraft(text="Seu cartao {card_kind} {card_mask} esta {status}."),
}


def _nlu(language: Language, **slots: Any) -> NLUResult:
    return NLUResult(
        language=language, intents=["card_status"], status="clear", slots=NLUSlots(**slots)
    )


@pytest.mark.parametrize("language", ["es", "pt"])
def test_other_card_two_cards(fakebank_dir: Path, language: Language) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    _nlu(language, card_hint="credit"),
                    _nlu(language, card_hint="other"),
                ],
                "compose": [_DRAFT[language], _DRAFT[language]],
            }
        )
        session = make_session("CLI-TFTXSRC00007", fakebank_dir, llm)

        await run_turn(session.graph, "estado de mi credito", config=session.config)
        reply, debug = await run_turn(session.graph, "y la otra", config=session.config)

        values = (await session.graph.aget_state(session.config)).values
        assert values["selected_card_id"] == "PRD-TFT7DEBT0002"
        assert "7778" in reply
        assert "card_picker" not in debug.ui

    asyncio.run(run())


def _card(card_id: str, kind: Any, last4: str) -> CardSummary:
    return CardSummary(card_id=card_id, kind=kind, last4=last4, status="Active", locked=False)


def test_other_card_three_cards_picker_excludes_focus() -> None:
    cards = [
        _card("PRD-A", "credit", "1111"),
        _card("PRD-B", "debit", "2222"),
        _card("PRD-C", "debit", "3333"),
    ]
    outcome = select_card(cards, "other", 0, load_card_select_policy(), "es", focus_card_id="PRD-A")
    assert isinstance(outcome, Ask)
    assert {c.card_id for c in outcome.options} == {"PRD-B", "PRD-C"}


def test_other_card_none_eligible_is_not_an_empty_picker() -> None:
    cards = [
        _card("PRD-A", "credit", "1111"),
        CardSummary(card_id="PRD-B", kind="debit", last4="2222", status="Closed", locked=False),
        CardSummary(card_id="PRD-C", kind="debit", last4="3333", status="Closed", locked=False),
    ]
    outcome = select_card(cards, "other", 0, load_card_select_policy(), "es", focus_card_id="PRD-A")
    assert not (isinstance(outcome, Ask) and not outcome.options)
    assert outcome == Selected(card_id="PRD-A")
