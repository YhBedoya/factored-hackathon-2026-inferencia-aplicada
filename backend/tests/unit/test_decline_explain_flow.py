"""B1 `decline_explain` flow tests (D1-D7, `02` §4.3).

See the spec's Test list rows 1-2 for `test_decline_explain_flow.py`. Fake
LLM only, `make_session` over the fixture, every turn driven with
`asyncio.run` (this card's convention: no pytest-asyncio).
"""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.domains.conversation.graph import run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import Language, get_template
from app.domains.localization.format import format_date, format_money, mask_card
from tests.conftest import ScriptedLLM, make_session, strip_closing

_CUSTOMER = "CLI-TFDECLN00006"
_DATE = date(2026, 3, 30)

# code -> (merchant, amount, cause_key, next_step_key, self_service): the
# fixture's own `TRX-TFD6CRED0001TXN01..04` rows (T1 state entry), and
# `policies/decline_codes.yaml`'s mapping for each.
_CODES: dict[str, tuple[str, Decimal, str, str, bool]] = {
    "51": ("Super Uno", Decimal("45000"), "insufficient_funds", "pay_or_use_other_card", False),
    "14": ("Libreria Dos", Decimal("60000"), "invalid_card_number", "check_card_number", False),
    "05": ("Cine Tres", Decimal("30000"), "do_not_honor", "contact_or_retry", False),
    "54": ("Viajes Cuatro", Decimal("250000"), "expired_card", "offer_replacement", True),
}


@pytest.mark.parametrize("language", ["es", "pt"])
@pytest.mark.parametrize("code", ["51", "14", "05", "54"])
def test_explains_decline(fakebank_dir: Path, code: str, language: Language) -> None:
    """Test 1: a `merchant_text` slot naming that code's merchant picks that
    decline (D2); `compose`'s draft is filled with the code-formatted
    amount/date (R4) and the fixed `decline_cause`/`decline_next_step`
    labels (D6, R8); only code 54 offers the replacement quick reply (D7)."""
    merchant, amount, cause_key, next_step_key, self_service = _CODES[code]

    async def run() -> None:
        from app.domains.conversation.nodes.compose import ComposeDraft

        draft_text = "{merchant} {amount} {tx_date} {card_mask} {decline_cause} {decline_next_step}"
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language=language,
                        intents=["decline_explain"],
                        status="clear",
                        slots=NLUSlots(merchant_text=merchant),
                    )
                ],
                "compose": [ComposeDraft(text=draft_text)],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)

        opening = (
            f"por que se rechazo mi compra en {merchant}?"
            if language == "es"
            else f"por que minha compra em {merchant} foi recusada?"
        )
        reply, debug = await run_turn(session.graph, opening, config=session.config)

        cause_text = get_template(f"decline_cause_{cause_key}", language)  # type: ignore[arg-type]
        next_text = get_template(f"decline_next_{next_step_key}", language)  # type: ignore[arg-type]
        expected = (
            f"{merchant} {format_money(amount, 'COP', 'CO')} {format_date(_DATE)} "
            f"{mask_card('6666')} {cause_text} {next_text}"
        )
        if self_service:
            # The reply already offers the replacement chip: no closing question.
            assert reply == expected
            assert debug.pending is None
            assert debug.ui == ["quick_replies"]
        else:
            assert strip_closing(reply, language) == expected
            assert debug.pending == "smalltalk.anything_else"
            assert debug.ui == []

    asyncio.run(run())


@pytest.mark.parametrize("language", ["es", "pt"])
def test_no_declines(fakebank_dir: Path, language: Language) -> None:
    """Test 2: a credit card with no Declined rows answers with the fixed
    `decline_none` template and makes no LLM call beyond `nlu` (D5)."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language=language,
                        intents=["decline_explain"],
                        status="clear",
                        slots=NLUSlots(card_hint="credit"),
                    )
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        opening = (
            "¿por qué rechazaron mi compra?"
            if language == "es"
            else "por que minha compra foi recusada?"
        )
        reply, debug = await run_turn(session.graph, opening, config=session.config)

        assert strip_closing(reply, language) == get_template("decline_none", language)
        assert debug.pending == "smalltalk.anything_else"
        assert debug.ui == []
        assert [call.step for call in llm.calls] == ["nlu"]

    asyncio.run(run())
