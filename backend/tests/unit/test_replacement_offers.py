"""`replacement` only for eligible cards, and the closing after a verified
unlock/replacement (D1, D11, D14, D16). Fake LLM only."""

import asyncio
from pathlib import Path

import pytest

from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import Language, template_variants
from tests.conftest import ScriptedLLM, make_session

_TEXTS: dict[Language, str] = {"es": "quiero una tarjeta nueva", "pt": "quero um cartão novo"}


@pytest.mark.parametrize("language", ["es", "pt"])
def test_replacement_single_eligible_skips_picker(fakebank_dir: Path, language: Language) -> None:
    """One blocked card among several: no picker, straight to the address question."""

    async def run() -> None:
        llm = ScriptedLLM(
            {"nlu": [NLUResult(language=language, intents=["replacement_request"], status="clear")]}
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        session.overlay.blocked.add("PRD-TFM1CRED0001")

        _reply, debug = await run_turn(session.graph, _TEXTS[language], config=session.config)
        assert "card_picker" not in debug.ui
        assert debug.pending == "replacement.address_confirm"

    asyncio.run(run())


def test_replacement_active_card_offers_block(fakebank_dir: Path) -> None:
    """A named Active card is not replaceable: offer the block, never the address."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["replacement_request"],
                        status="clear",
                        slots=NLUSlots(card_hint="last4:1203"),
                    )
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        reply, debug = await run_turn(
            session.graph, "quiero una tarjeta nueva de la 1203", config=session.config
        )
        assert debug.pending == "card_block.offer_block"
        assert reply in template_variants("replacement_needs_block", "es")
        assert reply not in template_variants("address_confirm", "es")

    asyncio.run(run())


def test_closing_after_action_unlock_replacement(fakebank_dir: Path) -> None:
    """A verified unlock and a verified replacement each end with the generic closing."""

    async def run() -> None:
        closing_texts = template_variants("closing_generic", "es")

        # Unlock of a lock made in this session: step-up, then confirm.
        llm = ScriptedLLM(
            {"nlu": [NLUResult(language="es", intents=["card_unlock"], status="clear")]}
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm, otp_code="1234")
        session.overlay.locked.add("PRD-TFS2CRED0001")
        await run_turn(session.graph, "quiero desbloquear mi tarjeta", config=session.config)
        assert session.gate.verify("1234") is True
        await run_turn(session.graph, "", config=session.config, resume="step_up")
        state = await session.graph.aget_state(session.config)
        reply, debug = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(
                token_id=state.values["confirmation_token_id"], decision="confirm"
            ),
        )
        assert any(text in reply for text in closing_texts)
        assert debug.pending == "smalltalk.anything_else"
        assert "quick_replies" not in debug.ui

        # Replacement on the file address.
        llm2 = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="es", intents=["replacement_request"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                ]
            }
        )
        session2 = make_session("CLI-TFSINGLE0002", fakebank_dir, llm2)
        session2.overlay.blocked.add("PRD-TFS2CRED0001")
        await run_turn(session2.graph, "quiero una tarjeta nueva", config=session2.config)
        await run_turn(session2.graph, "sí", config=session2.config)
        reply2, debug2 = await run_turn(session2.graph, "sí", config=session2.config)
        assert any(text in reply2 for text in closing_texts)
        assert debug2.pending == "smalltalk.anything_else"
        assert "quick_replies" not in debug2.ui

    asyncio.run(run())
