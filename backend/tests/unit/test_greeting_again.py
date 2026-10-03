"""personalidad-cardy test 7: a greeting after Cardy already introduced herself
doesn't introduce her again (fake LLM)."""

import asyncio
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from app.domains.conversation import runner
from app.domains.conversation.graph import run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.store import MessageRow
from app.domains.conversation.templates import get_template
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER = "CLI-TFSINGLE0002"


def _greeting(language: Literal["es", "pt"]) -> NLUResult:
    return NLUResult(language=language, intents=["greeting"], status="clear", slots=NLUSlots())


@pytest.mark.parametrize("language", ["es", "pt"])
def test_greeting_after_welcome_no_self_intro(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch, language: Literal["es", "pt"]
) -> None:
    async def run() -> None:
        llm = ScriptedLLM({"nlu": [_greeting(language), _greeting(language)]})
        session = make_session(_CUSTOMER, fakebank_dir, llm)

        # (ii) a fresh session's first greeting still introduces Cardy.
        first, _ = await run_turn(session.graph, "Hola Cardy", config=session.config)
        assert first == get_template("greeting_named", language).replace(
            "{customer_name}", "Prueba"
        )

        # (i) the welcome already introduced her: no second "Soy Cardy".
        fresh = make_session(_CUSTOMER, fakebank_dir, llm)
        result = await fresh.graph.ainvoke(
            {
                "user_text": "Hola Cardy",
                "confirmation": None,
                "resume": None,
                "selection": None,
                "introduced": True,
            },
            fresh.config,
        )
        again = get_template("greeting_again", language).replace("{customer_name}", "Prueba")
        assert result["reply"] == again
        assert "Soy Cardy" not in again and "Sou a Cardy" not in again

        # (iii) the runner's seed: a stored welcome and no checkpoint flag.
        row = MessageRow.model_construct(role="bot")

        async def one_bot_row(_cid: object) -> list[MessageRow]:
            return [row]

        async def no_rows(_cid: object) -> list[MessageRow]:
            return []

        monkeypatch.setattr(runner.store, "list_messages", one_bot_row)
        seeded = await runner._introduced_seed(
            fresh.graph, {"configurable": {"thread_id": str(uuid4())}}, uuid4()
        )
        assert seeded == {"introduced": True}
        monkeypatch.setattr(runner.store, "list_messages", no_rows)
        assert (
            await runner._introduced_seed(
                fresh.graph, {"configurable": {"thread_id": str(uuid4())}}, uuid4()
            )
            == {}
        )

    asyncio.run(run())
