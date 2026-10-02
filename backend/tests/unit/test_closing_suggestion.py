"""personalidad-cardy test 1: a finished status query closes with a policy-keyed
next-step suggestion, text only (fake LLM)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots
from app.domains.conversation.templates import get_template, template_variants
from tests.conftest import ScriptedLLM, make_session, strip_closing

_STATUS_TEXT = {
    "es": "Tu tarjeta {card_kind} {card_mask} está {status}.",
    "pt": "Seu cartao {card_kind} {card_mask} esta {status}.",
}


@pytest.mark.parametrize("language", ["es", "pt"])
def test_status_closing_suggests_movements(
    fakebank_dir: Path, language: Literal["es", "pt"]
) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language=language, intents=["card_status"], status="clear", slots=NLUSlots()
                    )
                ],
                "compose": [ComposeDraft(text=_STATUS_TEXT[language])],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        reply, debug = await run_turn(session.graph, "status de mi tarjeta", config=session.config)

        suggested = get_template("closing_suggest_transaction_search", language)
        assert reply.endswith("\n\n" + suggested)
        strip_closing(reply, language)
        assert "terminada" not in reply.lower()
        assert "encerrar a conversa" not in reply.lower()

        state = await session.graph.aget_state(session.config)
        chips = [e for e in state.values["ui"] if e.kind == "quick_replies"]
        assert not [e for e in chips if e.payload.slot == "closing"]
        assert state.values["closing_suggestion"] == "transaction_search"
        assert debug.pending == "smalltalk.anything_else"

    asyncio.run(run())


_CLOCK = datetime(2026, 4, 2, 18, 0, tzinfo=UTC)
_FOCUS_CREDIT = "PRD-TFT7CRED0001"


def _nlu(language: Literal["es", "pt"], intent: Intent, **slots: Any) -> NLUResult:
    return NLUResult(language=language, intents=[intent], status="clear", slots=NLUSlots(**slots))


@pytest.mark.parametrize("language", ["es", "pt"])
def test_accept_suggestion_lists_focus_movements(
    fakebank_dir: Path, language: Literal["es", "pt"]
) -> None:
    """Test 2: "sí" to the movements suggestion lists the focus card's movements
    with no card picker and no criterion question (D4, D6, D7)."""

    async def run() -> None:
        script: list[NLUResult] = [
            _nlu(language, "card_status", card_hint="credit"),
            _nlu(language, "affirm"),
        ]
        if language == "pt":
            script.append(_nlu(language, "transaction_search"))
        llm = ScriptedLLM({"nlu": script, "compose": [ComposeDraft(text=_STATUS_TEXT[language])]})
        session = make_session("CLI-TFTXSRC00007", fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK

        await run_turn(session.graph, "status de mi tarjeta de credito", config=session.config)
        state = await session.graph.aget_state(session.config)
        assert state.values["closing_suggestion"] == "transaction_search"

        reply, debug = await run_turn(session.graph, "si", config=session.config)
        assert debug.ui == ["transaction_list"]
        assert "card_picker" not in debug.ui
        assert reply != get_template("tx_search_ask_criterion", language)
        state = await session.graph.aget_state(session.config)
        (event,) = [e for e in state.values["ui"] if e.kind == "transaction_list"]
        assert event.payload.options
        assert all(o.label.endswith("•••• 7777") for o in event.payload.options)
        offered = state.values["tx_offer"]["offered_tx_ids"]
        assert offered and all(t.startswith("TRX-TFT7CRED") for t in offered)
        assert state.values["closing_suggestion"] is None

        if language == "pt":
            # The accepted-suggestion marker is per turn: a bare search still asks.
            reply3, _ = await run_turn(session.graph, "buscar uma compra", config=session.config)
            assert reply3 == get_template("tx_search_ask_criterion", language)

    asyncio.run(run())


@pytest.mark.parametrize(("language", "intent"), [("es", "deny"), ("pt", "thanks_close")])
def test_no_thanks_after_closing_closes(
    fakebank_dir: Path, language: Literal["es", "pt"], intent: Intent
) -> None:
    """Test 3: a "no" or thanks to the closing says goodbye and closes (D4)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [_nlu(language, "card_status"), _nlu(language, intent)],
                "compose": [ComposeDraft(text=_STATUS_TEXT[language])],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        await run_turn(session.graph, "status", config=session.config)
        reply, debug = await run_turn(session.graph, "no", config=session.config)
        assert reply in template_variants("farewell", language)
        assert debug.ui == ["conversation_closed"]
        state = await session.graph.aget_state(session.config)
        assert state.values["closing_suggestion"] is None

    asyncio.run(run())
