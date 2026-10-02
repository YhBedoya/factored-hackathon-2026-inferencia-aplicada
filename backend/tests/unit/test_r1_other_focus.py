"""R1: `other` and `focus` never resolve to another customer's card."""

import asyncio
from pathlib import Path

import pytest

from app.domains.cards.schemas import CardSummary
from app.domains.conversation.flows.actions import CLOSING_PAUSE
from app.domains.conversation.flows.card_select import (
    Ask,
    Selected,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from tests.conftest import ScriptedLLM, make_session

_OWN = [
    CardSummary(
        card_id="PRD-TFT7CRED0001", kind="credit", last4="7777", status="Active", locked=False
    ),
    CardSummary(
        card_id="PRD-TFT7DEBT0002", kind="debit", last4="7778", status="Active", locked=False
    ),
]
_FOREIGN = "PRD-TFS2CRED0001"


@pytest.mark.parametrize("case", ["other_foreign_focus", "accepted_suggestion_foreign_focus"])
def test_r1_other_and_focus_never_cross_customer(case: str, fakebank_dir: Path) -> None:
    if case == "accepted_suggestion_foreign_focus":
        asyncio.run(_accepted_suggestion_with_foreign_focus(fakebank_dir))
        return
    outcome = select_card(_OWN, "other", 0, load_card_select_policy(), "es", focus_card_id=_FOREIGN)
    own_ids = {c.card_id for c in _OWN}
    if isinstance(outcome, Selected):
        assert outcome.card_id in own_ids
    else:
        assert isinstance(outcome, Ask)
        assert {c.card_id for c in outcome.options} <= own_ids
    assert _FOREIGN not in repr(outcome)


async def _accepted_suggestion_with_foreign_focus(fakebank_dir: Path) -> None:
    """A "sí" to the movements suggestion with a foreign card id planted as the
    focus (D7): the search covers only the customer's own cards."""

    def nlu(intent: str) -> NLUResult:
        return NLUResult(language="es", intents=[intent], status="clear", slots=NLUSlots())

    llm = ScriptedLLM(
        {
            "nlu": [nlu("card_status"), nlu("affirm")],
            "compose": [ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} está {status}.")],
        }
    )
    session = make_session("CLI-TFTXSRC00007", fakebank_dir, llm)
    await run_turn(session.graph, "status de mi tarjeta", config=session.config)
    await session.graph.aupdate_state(
        session.config,
        {
            "selected_card_id": _FOREIGN,
            "pending": CLOSING_PAUSE,
            "closing_suggestion": "transaction_search",
        },
    )

    reply, _debug = await run_turn(session.graph, "si", config=session.config)

    state = await session.graph.aget_state(session.config)
    dump = reply + repr(state.values.get("ui")) + repr(state.values.get("tx_offer"))
    assert _FOREIGN not in dump and "TFS2" not in dump and "2222" not in dump
    assert state.values.get("escalation_reason") is None
    offered = state.values["tx_offer"]["offered_tx_ids"]
    assert offered and all(t.startswith("TRX-TFT7") for t in offered)
