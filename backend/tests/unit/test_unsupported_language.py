"""A message in neither Spanish nor Portuguese gets the fixed bilingual
`unsupported_language` reply: no flow runs, no tool is called and no compose
call is made, while an ES and a PT greeting still get their normal reply.
Fake LLM, fixture bank, no network.
"""

import asyncio
from pathlib import Path

import pytest

from app.domains.conversation.graph import run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import Language, get_template
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER_ID = "CLI-TFMULTI00001"


@pytest.mark.parametrize("language", ["es", "pt"])
def test_other_language_gets_the_bilingual_reply(language: Language, fakebank_dir: Path) -> None:
    greeting = NLUResult(language=language, intents=["greeting"], status="clear")
    english = NLUResult(
        language="other",
        intents=["card_status"],
        status="clear",
        slots=NLUSlots(card_hint="credit"),
    )
    llm = ScriptedLLM({"nlu": [greeting, english]})
    session = make_session(_CUSTOMER_ID, fakebank_dir, llm)

    first, first_debug = asyncio.run(run_turn(session.graph, "hola", config=session.config))
    assert first_debug.route == "smalltalk"
    assert first != get_template("unsupported_language", language)

    reply, debug = asyncio.run(
        run_turn(session.graph, "what is the status of my credit card?", config=session.config)
    )

    # The reply keeps the conversation's language first, and carries both.
    assert reply == get_template("unsupported_language", language)
    assert "español o portugués" in reply
    assert "espanhol ou português" in reply
    assert debug.route == "unsupported"
    assert debug.tools_called == []
    assert [call.step for call in llm.calls] == ["nlu", "nlu"]
