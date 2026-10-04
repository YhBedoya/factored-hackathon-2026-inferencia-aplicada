"""B2 `unrecognized_charge` flow tests (D7-D13, `02` §4.8).

See the spec's Test list rows for `test_dispute_flows.py`. Fake LLM only,
`make_session` (D4-B T6) wires `ConfirmedWriteTools` and D4-A's
`InMemoryHandoffTools` over the test fixture, and every turn is driven with `asyncio.run` (this
card's convention: no pytest-asyncio).
"""

import asyncio
import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.domains.conversation.flows.actions import fill
from app.domains.conversation.graph import ConfirmationDecision, TxSelection, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.localization.format import format_date, format_money, mask_card
from app.domains.transactions.schemas import TxFilter
from tests.conftest import ScriptedLLM, make_session, strip_closing

_CARD_ID = "PRD-TFS2CRED0001"
_TXN01 = "TRX-TFS2CRED0001TXN01"  # Approved, low fraud_score
_TXN02 = "TRX-TFS2CRED0001TXN02"  # Approved, low fraud_score
_TXN03 = "TRX-TFS2CRED0001TXN03"  # Pending, empty merchant, fraud_score 45.00
_SUMMARY = HandoffSummaryDraft(
    request="{tx_count} cargos no reconocidos, cola {queue_label}.",
    asked="Pidió ayuda.",
    did="Nada.",
    unfinished="Todo.",
)


@pytest.mark.parametrize(
    ("language", "picked_tx_ids", "possession_answer"),
    [
        ("es", [_TXN01, _TXN02], None),
        ("pt", [_TXN01], "no"),
        ("es", [_TXN03], None),
    ],
    ids=["es-two_picked", "pt-possession_no", "es-score_gt_30"],
)
def test_compromise_path(
    fakebank_dir: Path,
    language: Language,
    picked_tx_ids: list[str],
    possession_answer: str | None,
) -> None:
    """D8, D9: `min_picked`, a "no" to possession and a `fraud_score` over
    the threshold each trigger the compromise rule on their own. The
    two-step `[block_card, create_claim]` plan, confirmed and verified,
    replies with the case ids and the Fraudes handoff text, and the handoff
    node created exactly one packet with the picked ids as evidence."""

    async def run() -> None:
        nlu_outputs = [
            NLUResult(language=language, intents=["unrecognized_charge"], status="clear")
        ]
        if possession_answer is not None:
            nlu_outputs.append(NLUResult(language=language, intents=["deny"], status="clear"))
        llm = ScriptedLLM({"nlu": nlu_outputs, "handoff_summary": [_SUMMARY]})
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        opening = (
            "no reconozco estas compras" if language == "es" else "não reconheço essas compras"
        )
        _reply1, debug1 = await run_turn(session.graph, opening, config=session.config)
        assert debug1.pending == "unrecognized_charge.transactions"
        assert debug1.ui == ["transaction_list"]

        nlu_calls_before_pick = sum(1 for call in llm.calls if call.step == "nlu")
        _reply2, debug2 = await run_turn(
            session.graph,
            "",
            config=session.config,
            selection=TxSelection(tx_ids=picked_tx_ids),
        )
        assert sum(1 for call in llm.calls if call.step == "nlu") == nlu_calls_before_pick

        if possession_answer is not None:
            assert debug2.pending == "unrecognized_charge.card_possession"
            deny_text = "no" if language == "es" else "não"
            _reply2b, debug2 = await run_turn(session.graph, deny_text, config=session.config)

        assert debug2.pending == "unrecognized_charge.confirmation"
        assert debug2.ui == ["confirm"]

        state = await session.graph.aget_state(session.config)
        confirm_event = state.values["ui"][0]
        assert [step.tool for step in confirm_event.payload.steps] == [
            "cards.block_card",
            "disputes.create_claim",
        ]
        token_id = state.values["confirmation_token_id"]

        reply3, debug3 = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        assert debug3.pending is None
        assert "Fraudes" in reply3
        assert session.overlay.blocked == {_CARD_ID}

        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.queue == "fraudes"
        assert {ev.ref for ev in packet.evidence} == set(picked_tx_ids)
        block_taken, claim_taken = packet.actions_taken
        assert block_taken.tool == "cards.block_card"
        assert claim_taken.tool == "disputes.create_claim"
        case_ids = claim_taken.case_ids
        assert case_ids is not None
        assert len(case_ids) == len(picked_tx_ids)
        for case_id in case_ids:
            assert case_id in reply3

        final_state = await session.graph.aget_state(session.config)
        banner = final_state.values["ui"][0]
        assert banner.kind == "handoff_banner"
        assert banner.payload.case_ids == case_ids

    asyncio.run(run())


@pytest.mark.parametrize("language", ["es", "pt"])
def test_single_charge_questions_claim(fakebank_dir: Path, language: Language) -> None:
    """D11, end-of-day step 3: one low-score pick, "sí" to possession, then
    `contacted_merchant`, then a one-step claim plan -> the case id, and no
    handoff is created."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language=language, intents=["unrecognized_charge"], status="clear"),
                    NLUResult(language=language, intents=["affirm"], status="clear"),
                    NLUResult(language=language, intents=["affirm"], status="clear"),
                ]
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        opening = "no reconozco esta compra" if language == "es" else "não reconheço essa compra"
        _reply1, debug1 = await run_turn(session.graph, opening, config=session.config)
        assert debug1.pending == "unrecognized_charge.transactions"

        _reply2, debug2 = await run_turn(
            session.graph,
            "",
            config=session.config,
            selection=TxSelection(tx_ids=[_TXN02]),
        )
        assert debug2.pending == "unrecognized_charge.card_possession"

        yes = "sí" if language == "es" else "sim"
        _reply3, debug3 = await run_turn(session.graph, yes, config=session.config)
        assert debug3.pending == "unrecognized_charge.dispute_question"

        _reply4, debug4 = await run_turn(session.graph, yes, config=session.config)
        assert debug4.pending == "unrecognized_charge.confirmation"

        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]

        reply5, debug5 = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )
        assert debug5.pending == "smalltalk.anything_else"
        assert reply5.endswith(get_template("closing_generic", language))
        assert re.search(r"CLM-[0-9A-F]+", reply5)
        assert "Fraudes" not in reply5
        assert session.handoff_tools.created == []
        assert session.overlay.blocked == set()

    asyncio.run(run())


def test_no_transactions_writes_nothing(fakebank_dir: Path) -> None:
    """D12: a card with only Declined transactions offers nothing, writes
    nothing and clears `pending`."""

    async def run() -> None:
        llm = ScriptedLLM(
            {"nlu": [NLUResult(language="es", intents=["unrecognized_charge"], status="clear")]}
        )
        session = make_session("CLI-TFPASTD00005", fakebank_dir, llm)

        reply, debug = await run_turn(
            session.graph, "no reconozco estas compras", config=session.config
        )
        assert strip_closing(reply, "es") == get_template("dispute_no_transactions", "es")
        assert debug.pending == "smalltalk.anything_else"
        assert debug.ui == []
        assert session.handoff_tools.created == []

    asyncio.run(run())


def test_refused_block(fakebank_dir: Path) -> None:
    """D10: cancelling the `[block, claim]` plan writes nothing and offers
    the claim alone; confirming that plan gives the case id and hands off to
    Fraudes with `open_questions` noting the card is still active. The card
    stays unblocked throughout."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(language="es", intents=["unrecognized_charge"], status="clear"),
                    NLUResult(language="es", intents=["deny"], status="clear"),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                ],
                "handoff_summary": [_SUMMARY],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _reply1, debug1 = await run_turn(
            session.graph, "no reconozco estas compras", config=session.config
        )
        assert debug1.pending == "unrecognized_charge.transactions"

        _reply2, debug2 = await run_turn(
            session.graph,
            "",
            config=session.config,
            selection=TxSelection(tx_ids=[_TXN01, _TXN02]),
        )
        assert debug2.pending == "unrecognized_charge.confirmation"

        reply3, debug3 = await run_turn(session.graph, "no", config=session.config)
        assert debug3.pending == "unrecognized_charge.confirmation"
        assert reply3 == fill(get_template("dispute_block_refused_offer_claim", "es"), tx_count="2")
        assert session.overlay.blocked == set()

        reply4, debug4 = await run_turn(session.graph, "sí", config=session.config)
        assert debug4.pending is None
        assert re.search(r"CLM-[0-9A-F]+", reply4)
        assert session.overlay.blocked == set()

        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.queue == "fraudes"
        assert packet.reason == "suspected_fraud"
        assert get_template("dispute_open_question_card_active", "es") in packet.open_questions

    asyncio.run(run())


def test_transaction_list_labels_from_code(fakebank_dir: Path) -> None:
    """R4, D13: every offered option's label is exactly `localization.format`'s
    merchant/money/date/mask output, with the fixed "Comercio" fallback for
    the candidate whose `merchant_name` is empty."""

    async def run() -> None:
        llm = ScriptedLLM(
            {"nlu": [NLUResult(language="es", intents=["unrecognized_charge"], status="clear")]}
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)

        _reply, debug = await run_turn(
            session.graph, "no reconozco estas compras", config=session.config
        )
        assert debug.pending == "unrecognized_charge.transactions"

        state = await session.graph.aget_state(session.config)
        event = state.values["ui"][0]
        assert event.kind == "transaction_list"

        ctx = ToolContext(
            customer_id="CLI-TFSINGLE0002",
            conversation_id=uuid4(),
            actor="customer",
            trace_id="test-trace",
            policy_version="unversioned",
        )
        bank_tools = FakeBank(ctx, fakebank_dir)
        candidates = await bank_tools.search_transactions(
            TxFilter(card_id=_CARD_ID, status=["Approved", "Pending", "Reversed"])
        )
        assert {tx.tx_id for tx in candidates} == {_TXN01, _TXN02, _TXN03}

        expected_by_id = {
            tx.tx_id: (
                f"{tx.merchant_name or 'Comercio'} · {format_money(tx.amount, tx.currency, 'CO')} "
                f"· {format_date(tx.occurred_at.date())} · {mask_card('2222')}"
            )
            for tx in candidates
        }
        options = {opt.tx_id: opt.label for opt in event.payload.options}
        assert options == expected_by_id

    asyncio.run(run())
