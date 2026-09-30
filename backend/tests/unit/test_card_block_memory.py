"""B4 fix: `card_block` remembers `block_kind` across the which-card question
(D10, D11). See the spec's Test list item 6.

Fake LLM only, `make_session` wires `ConfirmedWriteTools` over the test
fixture; every turn is driven with `asyncio.run` (this card's convention: no
pytest-asyncio), same pattern as `test_block_flows.py`.
"""

import asyncio
from pathlib import Path

from app.domains.conversation.graph import run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from tests.conftest import ScriptedLLM, make_session


def test_block_kind_survives_card_question_es(fakebank_dir: Path) -> None:
    """Turn 1 says "block temporarily" with no card hint; `CLI-TFMULTI00001`
    has two eligible cards, so the flow asks which one. The remembered
    `block_kind` then carries into the `card_hint` resume turn, whose own NLU
    only ever names the card: straight to the plan, no lock-vs-block
    question."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    NLUResult(
                        language="es",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(card_hint="last4:6475"),
                    ),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(
            session.graph, "bloquea temporalmente mi tarjeta", config=session.config
        )
        assert debug1.pending == "card_block.card_hint"
        assert debug1.ui == ["card_picker"]

        reply2, debug2 = await run_turn(
            session.graph, "la que termina en 6475", config=session.config
        )
        assert debug2.pending == "card_block.confirmation"
        assert debug2.ui == ["confirm"]
        assert "6475" in reply2

    asyncio.run(run())


def test_block_kind_survives_card_question_pt(fakebank_dir: Path) -> None:
    """Same as the ES case, in Brazilian Portuguese."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    NLUResult(
                        language="pt",
                        intents=[],
                        status="clear",
                        slots=NLUSlots(card_hint="last4:6475"),
                    ),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(
            session.graph, "bloqueia temporariamente meu cartão", config=session.config
        )
        assert debug1.pending == "card_block.card_hint"
        assert debug1.ui == ["card_picker"]

        reply2, debug2 = await run_turn(
            session.graph, "o que termina em 6475", config=session.config
        )
        assert debug2.pending == "card_block.confirmation"
        assert debug2.ui == ["confirm"]
        assert "6475" in reply2

    asyncio.run(run())
