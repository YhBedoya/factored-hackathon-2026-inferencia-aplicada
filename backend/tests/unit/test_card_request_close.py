"""D9-C spec T9, T10: closing a card on the agent path. Reason -> OTP -> Acepto ends in one
`retencion` handoff carrying the reason code; the balance in Cardy's reply is code-built
(R4), and a non-zero balance is still filed (the staff decides). Fake LLM and fake bank."""

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pytest

from app.domains.cards.schemas import CardDetails
from app.domains.conversation.agent.plan import close_balance_text
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.templates import Language
from app.domains.localization.format import format_money
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session

_OTP = "000000"
_SUMMARY = HandoffSummaryDraft(
    request="Solicitud de cierre de tarjeta.",
    asked="Pidió cerrar su tarjeta.",
    did="Nada.",
    unfinished="Todo.",
)


def _turn(language: Language, reply: str) -> AgentTurn:
    lang: Literal["es", "pt"] = language
    return AgentTurn(
        language=lang,
        intents=["card_cancel"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply=reply,
    )


def _script(language: Language, card_ref: str, reason: str, reply: str) -> ScriptedLLM:
    rounds: list[list[tuple[str, dict[str, Any]]]] = [
        [("card_status", {})],
        [("propose_plan", {"steps": [{"action": "close", "card": card_ref, "reason": reason}]})],
    ]
    scripts = [
        AgentScript(rounds=rounds, finals=[_turn(language, reply)]),
        AgentScript(rounds=[], finals=[_turn(language, "Revisa tu solicitud.")]),
    ]
    # No output for the Acepto turn: a model call writing the result would find the queue empty.
    return ScriptedLLM({"agent": scripts, "handoff_summary": [_SUMMARY]})


async def _close(session: Session, text: str) -> tuple[str, Session]:
    """Drive the turns up to Acepto; return Cardy's first reply (the `{close_balance}` one)."""
    graph, config = session.graph, session.config
    await run_turn(graph, text, config=config)
    values = dict((await graph.aget_state(config)).values)
    assert values["pending"]["awaiting_slot"] == "otp"
    assert not session.overlay.card_requests  # nothing written at the OTP pause (R2)
    reply = " ".join(values.get("segments") or [])

    assert session.gate.verify(_OTP)
    await run_turn(graph, "", config=config, resume="step_up")
    values = dict((await graph.aget_state(config)).values)
    assert values["pending"]["node"] == "confirm"
    assert not session.overlay.card_requests
    token = str(values["confirmation_token_id"])
    await run_turn(
        graph,
        "",
        config=config,
        confirmation=ConfirmationDecision(token_id=token, decision="confirm"),
    )
    return reply, session


def _check_handoff(session: Session, mask: str, product_id: str) -> None:
    assert len(session.handoff_tools.created) == 1
    packet = session.handoff_tools.created[0]
    assert packet.queue == "retencion"
    assert packet.reason == "card_close_request"
    assert packet.card_request is not None
    assert packet.card_request.kind == "close"
    assert packet.card_request.reason_code == "high_cost"
    assert packet.card_request.card_mask == mask
    (request,) = session.overlay.card_requests.values()
    assert request["kind"] == "close"
    assert request["product_id"] == product_id
    assert request["reference"] == packet.card_request.reference


@pytest.mark.usefixtures("agent_on")
def test_close_es_happy(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFMULTI00001",
            fakebank_dir,
            _script("es", "c2", "high_cost", "Para cerrarla, {close_balance}."),
            otp_code=_OTP,
        )
        reply, _ = await _close(session, "quiero cerrar mi tarjeta, sale muy cara")
        # The balance in the reply is the code-formatted one, not a placeholder.
        assert "{close_balance}" not in reply
        expected = format_money(Decimal("850.00"), "USD", "MX")
        assert expected in reply
        assert "850.00" not in reply.replace(expected, "")
        _check_handoff(session, "•••• 1203", "PRD-TFM1DEBT0002")

    asyncio.run(run())


@pytest.mark.usefixtures("agent_on")
def test_close_pt_nonzero_balance_happy(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFMULTI00001",
            fakebank_dir,
            _script("pt", "c1", "high_cost", "O saldo é {close_balance}."),
            otp_code=_OTP,
        )
        reply, _ = await _close(session, "quero encerrar meu cartão de crédito")
        expected = format_money(Decimal("1234.50"), "USD", "MX")
        assert expected in reply
        assert "1234" not in reply.replace(expected, "")
        _check_handoff(session, "•••• 6475", "PRD-TFM1CRED0001")

    asyncio.run(run())


@pytest.mark.parametrize(
    ("language", "text"), [("es", "saldo no disponible"), ("pt", "saldo indisponível")]
)
def test_close_balance_text_none_is_not_zero(language: Language, text: str) -> None:
    details = CardDetails.model_construct(current_balance=None, currency="USD")
    shown = close_balance_text(details, "MX", language)
    assert shown == text
    assert "0" not in shown
