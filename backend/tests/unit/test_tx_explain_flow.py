"""B1 `tx_explain` flow tests (D3, A5, `02` §4.5).

See the spec's Test list rows 5-6. Fake LLM only, `make_session` over the
fixture, every turn driven with `asyncio.run` (no pytest-asyncio). The bank
clock is fixed to `datetime(2026, 4, 2, 18, 0, tzinfo=UTC)`, same as
`test_tx_search_flow.py`: the fixture's Pending row (`occurred_at`
2026-03-31) is still inside its 3-day hold on that clock, so
`clear_by_date` is 2026-04-03, not yet overdue.
"""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.core.errors import NotFound
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.tools.fakebank import FakeBank
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER = "CLI-TFTXSRC00007"
_CLOCK = datetime(2026, 4, 2, 18, 0, tzinfo=UTC)


def test_pending_explained_pt(fakebank_dir: Path) -> None:
    """Test 5, PT: a Pending row's hold-days date is formatted in code (R4)
    and the fact's source is `policy:transaction_states@...`."""

    async def run() -> None:
        draft = (
            "{merchant} {amount} {tx_date} {card_mask} {tx_state_cause} "
            "{tx_state_next_step} {clear_by_date}"
        )
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt",
                        intents=["pending_reversal_explain"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Uber"),
                    )
                ],
                "compose": [ComposeDraft(text=draft)],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK

        reply, debug = await run_turn(
            session.graph, "o que houve com minha compra no Uber?", config=session.config
        )

        assert debug.pending is None
        assert "03/04/2026" in reply

        state = await session.graph.aget_state(session.config)
        facts_by_key = {fact.key: fact for fact in state.values["facts"]}
        assert facts_by_key["clear_by_date"].value == date(2026, 4, 3)
        assert facts_by_key["tx_state_cause"].source.startswith("policy:transaction_states@")

    asyncio.run(run())


def test_reversed_explained_es(fakebank_dir: Path) -> None:
    """Test 6, ES: a Reversed row's cause is `reversed_charge`, and the
    facts never claim a second (twin) line exists (A5)."""

    async def run() -> None:
        draft = "{merchant} {amount} {tx_date} {card_mask} {tx_state_cause} {tx_state_next_step}"
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["pending_reversal_explain"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Mercado Central"),
                    )
                ],
                "compose": [ComposeDraft(text=draft)],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK

        _reply, debug = await run_turn(
            session.graph,
            "que paso con mi compra en Mercado Central?",
            config=session.config,
        )

        assert debug.pending is None
        state = await session.graph.aget_state(session.config)
        facts_by_key = {fact.key: fact for fact in state.values["facts"]}
        assert facts_by_key["tx_state_cause"].value == "reversed_charge"
        assert "clear_by_date" not in facts_by_key

    asyncio.run(run())


def test_pending_on_non_card_product_still_explained(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a Pending row on a savings account makes
    `get_card_details` raise `NotFound`; the turn must still explain it,
    just without a `card_mask` fact."""

    async def not_a_card(self: FakeBank, card_id: str) -> None:
        raise NotFound(f"no card {card_id!r}")

    monkeypatch.setattr(FakeBank, "get_card_details", not_a_card)

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt",
                        intents=["pending_reversal_explain"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Uber"),
                    )
                ],
                "compose": [ComposeDraft(text="{merchant} {tx_state_cause} {tx_state_next_step}")],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK

        reply, debug = await run_turn(
            session.graph, "o que houve com minha compra no Uber?", config=session.config
        )

        assert debug.pending is None
        assert "Uber" in reply
        state = await session.graph.aget_state(session.config)
        assert "card_mask" not in {fact.key for fact in state.values["facts"]}

    asyncio.run(run())
