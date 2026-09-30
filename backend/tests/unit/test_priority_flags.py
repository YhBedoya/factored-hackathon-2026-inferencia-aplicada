"""B2 priority-claim tests (D5-D10, SA1): the flag set is built in code, is
bound into the signed plan, and a flagged verified claim goes to Reclamos while
the compromise path stays with Fraudes. Fake LLM only (`make_session`)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.domains.conversation.graph import ConfirmationDecision, TxSelection, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.templates import Language, get_template
from tests.conftest import ScriptedLLM, Session, make_session

_SUMMARY = HandoffSummaryDraft(request="Reclamo de cargo no reconocido, cola {queue_label}.")
_OPENING = {"es": "no reconozco esta compra", "pt": "não reconheço essa compra"}
_YES = {"es": "sí", "pt": "sim"}


def _nlu(language: Language, *intents: Any) -> NLUResult:
    return NLUResult(language=language, intents=list(intents), status="clear")


def _plan_flags(session: Session, token_id: str) -> list[str]:
    """The flags the store signed into the claim step (private read: no public
    accessor exists for an open plan)."""
    plan = session.store._plans[token_id]
    (step,) = [s for s in plan.steps if s.tool == "disputes.create_claim"]
    flags = step.args["priority_flags"]
    assert isinstance(flags, list)
    return [str(flag) for flag in flags]


async def _to_questions(
    session: Session, language: Language, tx_ids: list[str], *, answers: int
) -> None:
    await run_turn(session.graph, _OPENING[language], config=session.config)
    await run_turn(session.graph, "", config=session.config, selection=TxSelection(tx_ids=tx_ids))
    for _ in range(answers):
        await run_turn(session.graph, _YES[language], config=session.config)


@pytest.mark.parametrize(
    ("customer", "tx_id", "flag", "language"),
    [
        ("CLI-TFREPT00008", "TRX-TFR8CRED0001TXN01", "repeat_complainer", "es"),
        ("CLI-TFREPT00008", "TRX-TFR8CRED0001TXN01", "repeat_complainer", "pt"),
        ("CLI-TFAMNT00009", "TRX-TFA9CRED0001TXN01", "amount_over_threshold", "pt"),
        ("CLI-TFAMNT00009", "TRX-TFA9CRED0001TXN01", "amount_over_threshold", "es"),
        ("CLI-TFCRIT00010", "TRX-TFC0CRED0001TXN01", "open_critical", "es"),
        ("CLI-TFCRIT00010", "TRX-TFC0CRED0001TXN01", "open_critical", "pt"),
    ],
    ids=["repeat-es", "repeat-pt", "amount-pt", "amount-es", "critical-es", "critical-pt"],
)
def test_flag_hands_off_to_reclamos(
    fakebank_dir: Path, customer: str, tx_id: str, flag: str, language: Language
) -> None:
    """D5, D6: a flagged single-charge claim carries the flag in its signed
    plan, is filed `High`, verified, and is then handed to Reclamos."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    _nlu(language, "unrecognized_charge"),
                    _nlu(language, "affirm"),
                    _nlu(language, "affirm"),
                ],
                "handoff_summary": [_SUMMARY],
            }
        )
        session = make_session(customer, fakebank_dir, llm)
        await _to_questions(session, language, [tx_id], answers=2)

        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]
        assert state.values["priority_flags"] == [flag]
        assert _plan_flags(session, token_id) == [flag]

        reply, _debug = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )

        [packet] = session.handoff_tools.created
        assert packet.reason == "priority_claim"
        assert packet.queue == "reclamos"
        assert packet.priority == "high"
        (claim,) = packet.actions_taken
        assert claim.tool == "disputes.create_claim"
        assert claim.verified
        assert claim.case_ids is not None
        (case_id,) = claim.case_ids
        assert session.overlay.claim_priorities[case_id] == "High"
        assert case_id in reply

    asyncio.run(run())


@pytest.mark.parametrize(
    ("language", "keyword"), [("es", "condusef"), ("pt", "procon")], ids=["es", "pt"]
)
def test_regulator_mention_goes_to_reclamos(
    fakebank_dir: Path, language: Language, keyword: str
) -> None:
    """A regulator mention while the claim is paused at a question hands off to
    Reclamos as `legal_regulator`; no claim is written."""

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [_nlu(language, "unrecognized_charge"), _nlu(language)],
                "handoff_summary": [_SUMMARY],
            }
        )
        session = make_session("CLI-TFSINGLE0002", fakebank_dir, llm)
        await _to_questions(session, language, ["TRX-TFS2CRED0001TXN02"], answers=0)

        await run_turn(session.graph, f"voy a ir a {keyword}", config=session.config)

        [packet] = session.handoff_tools.created
        assert packet.reason == "legal_regulator"
        assert packet.queue == "reclamos"
        assert packet.actions_taken == []
        assert session.overlay.claim_priorities == {}

    asyncio.run(run())


def test_compromise_keeps_fraudes(fakebank_dir: Path) -> None:
    """D7: two picked rows trigger the compromise plan; the handoff stays
    Fraudes / `suspected_fraud`, with the flag recorded as a rule hit and as an
    open-question line."""

    async def run() -> None:
        llm = ScriptedLLM(
            {"nlu": [_nlu("es", "unrecognized_charge")], "handoff_summary": [_SUMMARY]}
        )
        session = make_session("CLI-TFREPT00008", fakebank_dir, llm)
        await _to_questions(
            session,
            "es",
            ["TRX-TFR8CRED0001TXN01", "TRX-TFR8CRED0001TXN02"],
            answers=0,
        )
        state = await session.graph.aget_state(session.config)
        token_id = state.values["confirmation_token_id"]
        assert _plan_flags(session, token_id) == ["repeat_complainer"]

        await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token_id, decision="confirm"),
        )

        [packet] = session.handoff_tools.created
        assert packet.queue == "fraudes"
        assert packet.reason == "suspected_fraud"
        assert "priority_claim" in packet.escalation_rules_hit
        assert get_template("priority_flag_repeat_complainer", "es") in packet.open_questions

    asyncio.run(run())
