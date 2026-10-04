"""The agent's read tools on a customer whose newest decline is on a savings account: a
search with no card keeps only card rows, and a non-card decline that still reaches the
explain step is answered as "no explanation", never a crashed turn (NotFound)."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from app.domains.conversation.agent.reads import read_tools
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.graph import GraphState
from app.domains.policy.decline_codes import lookup_decline_code
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView
from tests.conftest import ScriptedLLM, make_session


def _decline(tx_id: str, card_id: str, day: int, merchant: str) -> TxView:
    return TxView(
        tx_id=tx_id,
        card_id=card_id,
        occurred_at=datetime(2026, 3, day, 15, 0, tzinfo=UTC),
        amount=Decimal("120.00"),
        currency="USD",
        amount_usd=Decimal("120.00"),
        type="Purchase",
        category="Retail",
        merchant_name=merchant,
        merchant_category="Retail",
        channel="POS",
        city="Ciudad de Mexico",
        country="México",
        status="Declined",
        response_code="51",
        fraud_score=Decimal("0.01"),
    )


_SAVINGS = _decline("TRX-TFM1SAVE0004TXN99", "PRD-TFM1SAVE0004", 29, "Cuota Ahorro")
_CARD = _decline("TRX-TFM1CRED0001TXN98", "PRD-TFM1CRED0001", 20, "Tienda Prueba")


def _tools(fakebank_dir: Path, rows: list[TxView]) -> tuple[dict[str, Any], TurnRefs]:
    session = make_session("CLI-TFMULTI00001", fakebank_dir, ScriptedLLM({}))
    bank = session.config["configurable"]["bank_tools"]

    async def _search(tx_filter: TxFilter) -> list[TxView]:
        return [tx for tx in rows if tx_filter.card_id in (None, tx.card_id)]

    async def _by_ids(tx_ids: list[str]) -> list[TxView]:
        return [tx for tx in rows if tx.tx_id in tx_ids]

    async def _explain(tx_id: str) -> DeclineExplanation:
        tx = next(tx for tx in rows if tx.tx_id == tx_id)
        code = lookup_decline_code(tx.response_code)
        return DeclineExplanation(
            code=tx.response_code or "",
            cause_key=code.cause_key,
            next_step_key=code.next_step_key,
            self_service=code.self_service,
            source="policy:decline_codes@test",
        )

    # The rows are this test's own, not the fixture CSV's: the bank's reads serve them.
    bank.search_transactions = _search
    bank.get_transactions_by_ids = _by_ids
    bank.explain_decline = _explain
    state = cast(GraphState, {"language": "es", "country": "MX"})
    refs = TurnRefs("es", "MX")
    return {t.name: t for t in read_tools(state, session.config, refs)}, refs


def test_decline_without_card_skips_non_card_rows(fakebank_dir: Path) -> None:
    async def run() -> None:
        tools, refs = _tools(fakebank_dir, [_SAVINGS, _CARD])
        tool = tools["explain_decline"]
        out = await tool.handler(tool.args_schema())
        assert refs.tx_id("t1") == _CARD.tx_id
        assert "decline_cause" in out

    asyncio.run(run())


def test_search_without_card_skips_non_card_rows(fakebank_dir: Path) -> None:
    async def run() -> None:
        tools, refs = _tools(fakebank_dir, [_SAVINGS, _CARD])
        tool = tools["search_transactions"]
        await tool.handler(tool.args_schema.model_validate({"status": ["Declined"]}))
        assert refs.tx_id("t1") == _CARD.tx_id
        assert refs.tx_id("t2") is None

    asyncio.run(run())


def test_non_card_decline_is_no_explanation(fakebank_dir: Path) -> None:
    async def run() -> None:
        tools, refs = _tools(fakebank_dir, [_SAVINGS])
        handle = refs.add_tx(_SAVINGS.tx_id, [])
        tool = tools["explain_decline"]
        out = await tool.handler(tool.args_schema.model_validate({"transaction": handle}))
        assert out == "no explanation available for this transaction."

    asyncio.run(run())
