"""B1 `tx_search` flow tests (D1-D2, `02` §4.4).

See the spec's Test list rows 1-3. Fake LLM only, `make_session` over the
fixture, every turn driven with `asyncio.run` (this card's convention: no
pytest-asyncio). The bank clock is fixed to `datetime(2026, 4, 2, 18, 0,
tzinfo=UTC)` (Thursday), so `resolve_date_expression`'s "martes pasado" /
"terça passada" resolves to `2026-03-31` (Tuesday), the fixture's own date.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.domains.conversation.graph import TxSelection, run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.sandbox import _RecordingBankTools
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools import BankReadTools
from app.domains.transactions.schemas import TxFilter
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER = "CLI-TFTXSRC00007"
_CLOCK = datetime(2026, 4, 2, 18, 0, tzinfo=UTC)


class _FilterSpy:
    """Wraps `BankReadTools` and records every `search_transactions` filter,
    delegating everything else untouched (test 1 needs the actual `TxFilter`,
    not just that the call happened)."""

    def __init__(self, inner: BankReadTools) -> None:
        self._inner = inner
        self.filters: list[TxFilter] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def search_transactions(self, tx_filter: TxFilter) -> Any:
        self.filters.append(tx_filter)
        return await self._inner.search_transactions(tx_filter)


def test_super_ahorro_last_tuesday_es(fakebank_dir: Path) -> None:
    """Test 1, B1 "Done when": "el cargo de Super Ahorro del martes pasado
    por unos 350" finds it, offered in a single-pick list."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["transaction_search"],
                        status="clear",
                        slots=NLUSlots(
                            merchant_text="Super Ahorro",
                            date_expression="martes pasado",
                            amount=Decimal("350"),
                            amount_approx=True,
                        ),
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK
        spy = _FilterSpy(session.config["configurable"]["bank_tools"])
        session.config["configurable"]["bank_tools"] = spy

        _reply, debug = await run_turn(
            session.graph,
            "el cargo de Super Ahorro del martes pasado por unos 350",
            config=session.config,
        )

        assert len(spy.filters) == 1
        tx_filter = spy.filters[0]
        assert tx_filter.date_from == tx_filter.date_to
        assert tx_filter.date_from.isoformat() == "2026-03-31"
        assert tx_filter.merchant_names == ["Super Ahorro"]
        assert tx_filter.amount_min == 315
        assert tx_filter.amount_max == 385

        assert debug.ui == ["transaction_list"]
        state = await session.graph.aget_state(session.config)
        assert state.values["tx_offer"] == {
            "flow": "tx_search",
            "offered_tx_ids": ["TRX-TFT7CRED0001TXN01"],
        }
        event = state.values["ui"][0]
        assert event.payload.multi is False
        assert [option.tx_id for option in event.payload.options] == ["TRX-TFT7CRED0001TXN01"]

    asyncio.run(run())


class _CappedSearch(_FilterSpy):
    """An unfiltered `search_transactions` misses the offered row, as the
    real one does once the customer has 10+ newer rows."""

    async def search_transactions(self, tx_filter: TxFilter) -> Any:
        if tx_filter == TxFilter():
            return []
        return await super().search_transactions(tx_filter)


def test_pick_rereads_the_row_by_id_es(fakebank_dir: Path) -> None:
    """D2 pick: the picked row is re-read by id, so it is found even when it
    is not among the newest rows an unfiltered search returns."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["transaction_search"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Super Ahorro"),
                    )
                ],
                "compose": [ComposeDraft(text="Tu movimiento en {merchant} por {amount}.")],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK
        spy = _CappedSearch(_RecordingBankTools(session.config["configurable"]["bank_tools"]))
        session.config["configurable"]["bank_tools"] = spy

        await run_turn(session.graph, "el cargo de Super Ahorro", config=session.config)
        reply, debug = await run_turn(
            session.graph,
            "",
            config=session.config,
            selection=TxSelection(tx_ids=["TRX-TFT7CRED0001TXN01"]),
        )

        assert "get_transactions_by_ids" in debug.tools_called
        assert "Super Ahorro" in reply
        assert reply != get_template("nothing_pending", "es")

    asyncio.run(run())


def test_widen_once_then_nothing_found_pt(fakebank_dir: Path) -> None:
    """Test 2, PT: a merchant with no rows searches twice (the second one
    +-3 days), then answers with the fixed no-results text."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="pt",
                        intents=["transaction_search"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Cine Premium"),
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK
        bank_tools = _RecordingBankTools(session.config["configurable"]["bank_tools"])
        session.config["configurable"]["bank_tools"] = bank_tools

        reply, debug = await run_turn(
            session.graph, "onde foi minha compra no Cine Premium?", config=session.config
        )

        assert bank_tools.calls.count("search_transactions") == 2
        assert "Cine Premium" in reply
        assert debug.pending is None
        assert debug.ui == []

    asyncio.run(run())


@pytest.mark.parametrize("language", ["es", "pt"])
def test_vague_date_clarifies_without_search(fakebank_dir: Path, language: str) -> None:
    """Test 3, A1: no merchant, amount or resolvable date at all -> the fixed
    clarify text, and `search_transactions` never runs."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language=language,  # type: ignore[arg-type]
                        intents=["transaction_search"],
                        status="clear",
                        slots=NLUSlots(),
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.config["configurable"]["now"] = _CLOCK
        bank_tools = _RecordingBankTools(session.config["configurable"]["bank_tools"])
        session.config["configurable"]["bank_tools"] = bank_tools

        opening = "quiero ver un movimiento" if language == "es" else "quero ver uma movimentação"
        reply, debug = await run_turn(session.graph, opening, config=session.config)

        assert reply == get_template("tx_search_ask_criterion", language)  # type: ignore[arg-type]
        assert "search_transactions" not in bank_tools.calls
        assert debug.pending is None

    asyncio.run(run())
