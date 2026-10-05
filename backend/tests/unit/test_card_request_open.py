"""D9-C spec T4, T5, T6, T8: opening a card on the agent path. Form -> OTP -> Acepto ends in
one `creditos` handoff; nothing is written before Acepto (R2); an unverified read-back is
the `action_unverified` handoff, never a "done" (R3). Fake LLM and fake bank only."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest

from app.core.actions import ActionResult
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.templates import Language
from app.domains.conversation.tools.fakebank import FakeBankOverlay, FakeBankWrites
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session

_OTP = "000000"
_EMAIL = "zq7-nuevo@example.test"
_SUMMARY = HandoffSummaryDraft(
    request="Solicitud de tarjeta nueva.",
    asked="Pidió una tarjeta.",
    did="Nada.",
    unfinished="Todo.",
)


def _turn(language: Language, reply: str) -> AgentTurn:
    lang: Literal["es", "pt"] = language
    return AgentTurn(
        language=lang,
        intents=["general_question"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply=reply,
    )


def _script(language: Language, kind: str, *, after_cancel: bool = False) -> ScriptedLLM:
    rounds: list[list[tuple[str, dict[str, Any]]]] = [
        [("propose_plan", {"steps": [{"action": "open", "kind": kind}]})]
    ]
    scripts = [
        AgentScript(rounds=rounds, finals=[_turn(language, "Completa el formulario.")]),
        AgentScript(rounds=[], finals=[_turn(language, "Revisa tu solicitud.")]),
    ]
    if after_cancel:
        scripts.append(AgentScript(rounds=[], finals=[_turn(language, "Cancelado.")]))
    # No output for the Acepto turn: a model call writing the result would find the queue empty.
    return ScriptedLLM({"agent": scripts, "handoff_summary": [_SUMMARY]})


def _snapshot(session: Session) -> tuple[Any, ...]:
    overlay = session.overlay
    return (
        dict(overlay.profile),
        dict(overlay.card_requests),
        list(overlay.profile_history),
        len(session.handoff_tools.created),
    )


async def _to_plan_card(
    session: Session, text: str, changed: dict[str, str], snapshots: list[tuple[Any, ...]]
) -> str:
    """Drive the turns up to the open plan card; record the state at each pause."""
    graph, config = session.graph, session.config

    async def pending() -> dict[str, Any]:
        return dict((await graph.aget_state(config)).values)

    await run_turn(graph, text, config=config)
    assert (await pending())["pending"]["awaiting_slot"] == "profile_form"
    snapshots.append(_snapshot(session))

    await session.overlay.vault.stage_form_values(changed)
    await run_turn(
        graph, "", config=config, resume="profile_form", form_changed_fields=list(changed)
    )
    assert (await pending())["pending"]["awaiting_slot"] == "otp"
    snapshots.append(_snapshot(session))

    assert session.gate.verify(_OTP)
    await run_turn(graph, "", config=config, resume="step_up")
    values = await pending()
    assert values["pending"]["node"] == "confirm"
    snapshots.append(_snapshot(session))
    return str(values["confirmation_token_id"])


async def _click(session: Session, token: str, decision: Literal["confirm", "cancel"]) -> None:
    await run_turn(
        session.graph,
        "",
        config=session.config,
        confirmation=ConfirmationDecision(token_id=token, decision=decision),
    )


@pytest.mark.usefixtures("agent_on")
def test_open_credit_es_happy(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFMULTI00001", fakebank_dir, _script("es", "credit"), otp_code=_OTP
        )
        snapshots: list[tuple[Any, ...]] = []
        token = await _to_plan_card(
            session, "quiero una tarjeta de crédito nueva", {"email": _EMAIL}, snapshots
        )
        await _click(session, token, "confirm")

        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.queue == "creditos"
        assert packet.reason == "card_open_request"
        assert packet.card_request is not None
        assert packet.card_request.kind == "open"
        assert packet.card_request.card_kind == "credit"
        reference = packet.card_request.reference
        assert [(f.fact, f.value) for f in packet.verified_facts] == [
            ("card_request_filed", reference)
        ]
        assert session.overlay.profile["email"] == _EMAIL
        assert [e["field"] for e in session.overlay.profile_history] == ["email"]
        (request,) = session.overlay.card_requests.values()
        assert request["status"] == "pending"
        assert request["reference"] == reference
        # R5: the packet carries names and the reference, never the form value.
        assert _EMAIL not in packet.model_dump_json()

    asyncio.run(run())


@pytest.mark.usefixtures("agent_on")
def test_open_debit_pt_happy(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, _script("pt", "debit"), otp_code=_OTP
        )
        token = await _to_plan_card(session, "quero um cartão de débito novo", {}, [])
        await _click(session, token, "confirm")

        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.queue == "creditos"
        assert packet.card_request is not None
        assert packet.card_request.kind == "open"
        assert packet.card_request.card_kind == "debit"
        assert session.overlay.profile == {}
        assert session.overlay.profile_history == []
        (request,) = session.overlay.card_requests.values()
        assert request["status"] == "pending"
        assert request["changed_fields"] == []

    asyncio.run(run())


@pytest.mark.usefixtures("agent_on")
def test_open_nothing_written_before_accept(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFMULTI00001",
            fakebank_dir,
            _script("es", "credit", after_cancel=True),
            otp_code=_OTP,
        )
        untouched = _snapshot(session)
        snapshots: list[tuple[Any, ...]] = []
        token = await _to_plan_card(
            session, "quiero una tarjeta de crédito nueva", {"email": _EMAIL}, snapshots
        )
        await _click(session, token, "cancel")
        snapshots.append(_snapshot(session))

        # Form, OTP, plan card and after No acepto: all as before the request, no handoff.
        assert snapshots == [untouched] * 4

    asyncio.run(run())


class _UnverifiedWrites(FakeBankWrites):
    """`request_card` comes back `verified=False` and writes nothing (R3)."""

    def __init__(self) -> None:  # only `pending_card_requests` (eligibility) reads the overlay
        self._overlay = FakeBankOverlay()

    async def request_card(
        self, kind: Literal["credit", "debit"], changed_fields: list[str], *, idempotency_key: str
    ) -> ActionResult:
        return ActionResult(
            tool="cards.request_card",
            status="applied",
            verified=False,
            readback={"status": "unknown", "kind": kind, "at": datetime.now(UTC)},
            tracking_id="CRQ-DEADBEEF",
        )


@pytest.mark.usefixtures("agent_on")
def test_request_card_unverified_readback(fakebank_dir: Path) -> None:
    async def run() -> None:
        session = make_session(
            "CLI-TFMULTI00001",
            fakebank_dir,
            _script("es", "credit"),
            otp_code=_OTP,
            raw_writes=_UnverifiedWrites(),
        )
        token = await _to_plan_card(session, "quiero una tarjeta de crédito nueva", {}, [])
        await _click(session, token, "confirm")

        assert len(session.handoff_tools.created) == 1
        packet = session.handoff_tools.created[0]
        assert packet.reason == "action_unverified"
        assert packet.card_request is None
        assert packet.verified_facts == []
        assert session.overlay.card_requests == {}
        values = (await session.graph.aget_state(session.config)).values
        text = " ".join(values.get("segments") or [])
        assert "CRQ-DEADBEEF" not in text

    asyncio.run(run())
