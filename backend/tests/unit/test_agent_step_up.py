"""S2 tests 1 and 2: the agent's step-up gate (R2) and the address that never reaches the
LLM (R5). Everything runs on `ScriptedLLM` over the fakebank fixture."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.api.v1.conversations as conversations_module
from app.api.v1.conversations import PostMessageRequest, post_message
from app.core.config import get_settings
from app.core.errors import StepUpRequired
from app.domains.conversation.agent.plan import AGENT_ADDRESS_PAUSE, AGENT_OTP_PAUSE
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import run_turn
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.templates import get_template
from app.domains.identity.models import Session as IdentitySession
from app.domains.policy.confirmation import PlanStep
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session

_CUSTOMER = "CLI-TFSINGLE0002"
_CARD = "PRD-TFS2CRED0001"
_ADDRESS = "Calle Falsa 123, Bogotá"


def _turn(reply: str, *, intents: list[Any], language: Literal["es", "pt"] = "es") -> AgentTurn:
    return AgentTurn(
        language=language,
        intents=intents,
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply=reply,
    )


async def _values(session: Session) -> dict[str, Any]:
    return (await session.graph.aget_state(session.config)).values


@pytest.mark.usefixtures("agent_on")
def test_r2_plan_needs_valid_step_up(fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    async def _recorder(*args: Any, **kwargs: Any) -> Any:
        started.append((args, kwargs))
        return uuid4()

    monkeypatch.setattr(conversations_module, "start_turn", _recorder)

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(
                        rounds=[
                            [("card_status", {})],
                            [("propose_plan", {"steps": [{"action": "unlock", "card": "c1"}]})],
                        ],
                        finals=[_turn("Necesito verificar tu identidad.", intents=["card_unlock"])],
                    ),
                    # The cancel turn: Cardy words the cancellation from the code text.
                    AgentScript(
                        rounds=[],
                        finals=[_turn("Listo, cancelé. ¿Qué cambiamos?", intents=["card_unlock"])],
                    ),
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm, otp_code="000000", write_audit=True)
        session.overlay.locked.add(_CARD)
        write_tools = session.config["configurable"]["bank_write_tools"]

        # (a) the executor refuses at issue time, before any token exists.
        with pytest.raises(StepUpRequired):
            await write_tools.issue_plan(
                [PlanStep(tool="cards.unlock_card", args={"card_id": _CARD})], None
            )
        recorded = [(t, p.get("rule_id")) for t, p in session.audit.events]
        assert ("rule_hit", "step_up_required") in recorded
        assert "confirmation_issued" not in [t for t, _ in recorded]
        assert not session.store._plans

        # (b) through the graph: the OTP pause, cancellable, and no token.
        _, debug = await run_turn(session.graph, "desbloquea mi tarjeta", config=session.config)
        values = await _values(session)
        assert values["pending"] == AGENT_OTP_PAUSE
        otp = [e for e in values["ui"] if e.kind == "otp_required"]
        assert len(otp) == 1 and otp[0].payload.cancellable is True
        assert "otp_required" in debug.ui
        assert not values.get("confirmation_token_id")
        assert not session.store._plans

        # (c) typed text at the pause is refused before any turn is scheduled.
        conversation = ConversationRow(
            id=UUID(session.config["configurable"]["thread_id"]),
            customer_id=_CUSTOMER,
            language="es",
            mode="bot",
            status="open",
        )
        identity_session = IdentitySession(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER, step_up_at=None
        )
        turn_host = SimpleNamespace(graph=session.graph)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(turn_host=turn_host)))
        with pytest.raises(HTTPException) as exc:
            await post_message(
                body=PostMessageRequest(text="123456"),
                request=request,  # type: ignore[arg-type]
                session=identity_session,
                conversation=conversation,
            )
        assert exc.value.status_code == 409 and exc.value.detail == "otp_required"
        assert started == []

        # (d) the gate is still invalid: nothing is issued, the OTP UI goes out again.
        _, debug = await run_turn(session.graph, "", config=session.config, resume="step_up")
        values = await _values(session)
        assert not session.store._plans
        assert values["pending"] == AGENT_OTP_PAUSE
        assert "otp_required" in debug.ui

        # (e) Cancel drops the steps and the pause; no write ran, the card stays locked.
        await run_turn(session.graph, "", config=session.config, resume="step_up_cancel")
        values = await _values(session)
        assert not values.get("agent_plan_steps")
        assert not values.get("pending")
        assert [s["status"] for s in values["intent_segments"]] == ["cancelled"]
        assert not session.store._plans
        assert session.overlay.locked == {_CARD}
        assert "confirmation_used" not in [t for t, _ in session.audit.events]

    asyncio.run(run())


@pytest.mark.usefixtures("agent_on")
def test_r5_new_address_never_reaches_llm(fakebank_dir: Path) -> None:
    async def run() -> None:
        step = {"action": "replace", "card": "c1", "address": "new"}
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(
                        rounds=[[("card_status", {})], [("propose_plan", {"steps": [step]})]],
                        finals=[
                            _turn(
                                "Necesito verificar tu identidad.",
                                intents=["replacement_request"],
                            )
                        ],
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm, otp_code="000000")
        session.overlay.blocked.add(_CARD)

        await run_turn(session.graph, "quiero una tarjeta nueva", config=session.config)
        assert (await _values(session))["pending"] == AGENT_OTP_PAUSE

        assert session.gate.verify("000000")
        await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert (await _values(session))["pending"] == AGENT_ADDRESS_PAUSE

        calls_before = len(llm.calls)
        await run_turn(session.graph, _ADDRESS, config=session.config)
        values = await _values(session)

        assert len(llm.calls) == calls_before
        for call in llm.calls:
            texts = [call.system, call.user, *call.messages, *call.tool_results]
            assert not any("Calle Falsa" in t for t in texts)
        replaces = [s for s in values["agent_plan_steps"] if s["action"] == "replace"]
        assert replaces and all(s["address_ref"].startswith("⟨ADDR_") for s in replaces)
        assert values["pending"]["node"] == "confirm"

    asyncio.run(run())


def test_r5_flag_off_address_never_reaches_llm(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        monkeypatch.setenv("AGENT_ENABLED", "true")
        get_settings.cache_clear()
        step = {"action": "replace", "card": "c1", "address": "new"}
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(
                        rounds=[[("card_status", {})], [("propose_plan", {"steps": [step]})]],
                        finals=[
                            _turn(
                                "Necesito verificar tu identidad.",
                                intents=["replacement_request"],
                            )
                        ],
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm, otp_code="000000")
        session.overlay.blocked.add(_CARD)

        await run_turn(session.graph, "quiero una tarjeta nueva", config=session.config)
        assert session.gate.verify("000000")
        await run_turn(session.graph, "", config=session.config, resume="step_up")
        assert (await _values(session))["pending"] == AGENT_ADDRESS_PAUSE

        # The kill switch: the flag is read per turn, so the next turn sees it off.
        monkeypatch.setenv("AGENT_ENABLED", "false")
        get_settings.cache_clear()
        calls_before = len(llm.calls)
        await run_turn(session.graph, _ADDRESS, config=session.config)
        values = await _values(session)

        assert len(llm.calls) == calls_before
        for call in llm.calls:
            texts = [call.system, call.user, *call.messages, *call.tool_results]
            assert not any("Calle Falsa" in t for t in texts)
        assert not values.get("pending")
        assert not values.get("agent_plan_steps")
        assert values["segments"] == [get_template("action_cancelled", "es")]
        assert "confirmation_used" not in [t for t, _ in session.audit.events]

    try:
        asyncio.run(run())
    finally:
        get_settings.cache_clear()
