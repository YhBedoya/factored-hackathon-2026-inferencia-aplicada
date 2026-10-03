"""S1 tests 3 and 4: an agent plan is confirmed by the button only (R2) and a "done"
claim without a verified read-back is never sent (R3)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import ConfirmationDecision, run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.templates import get_template
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session, run_recorded_turn
from tests.unit.test_r3_flows import _UnverifiedLockWrites

_REPLY = "Revisa la tarjeta de confirmación."


def _turn(reply: str = _REPLY, reported_done: list[int] | None = None) -> AgentTurn:
    return AgentTurn(
        language="es",
        intents=["card_block"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=reported_done or [],
        reply=reply,
    )


def _propose(*cards: str) -> AgentScript:
    steps = [{"action": "lock", "card": handle} for handle in cards]
    return AgentScript(
        rounds=[[("card_status", {})], [("propose_plan", {"steps": steps})]], finals=[_turn()]
    )


async def _state(session: Session) -> dict[str, Any]:
    return dict((await session.graph.aget_state(session.config)).values)


def test_r2_typed_text_never_confirms(
    fakebank_dir: Path, agent_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "agent": [
                    _propose("c1", "c2"),
                    AgentScript(rounds=[], finals=[_turn()]),  # typed "sí"
                    _propose("c2"),  # the change
                    AgentScript(rounds=[], finals=[_turn()]),  # typed 1 on the new plan
                    # (the old token click takes no agent call and does not reset the count)
                    AgentScript(rounds=[], finals=[_turn()]),  # typed 2, 3
                    AgentScript(rounds=[], finals=[_turn()]),
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(
                        request="Sin respuesta al plan.",
                        asked="Pidió ayuda.",
                        did="Nada.",
                        unfinished="Todo.",
                    )
                ],
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        run_one = lambda text, **kw: run_turn(session.graph, text, config=session.config, **kw)  # noqa: E731

        await run_one("bloquea todas mis tarjetas")
        first = await _state(session)
        old = first["confirmation_token_id"]
        assert len(first["agent_plan_steps"]) == 2
        assert old in session.store._plans

        _, debug = await run_one("sí")
        again = await _state(session)
        assert not session.overlay.locked
        assert again["confirmation_token_id"] == old
        assert debug.ui == ["confirm"]

        await run_one("mejor solo una")
        changed = await _state(session)
        assert old not in session.store._plans
        assert changed["confirmation_token_id"] in session.store._plans
        assert len(changed["agent_plan_steps"]) == 1

        # Typed turn 1 on the new plan, then a stale click: only a new plan resets the count.
        await run_one("sí")
        events = await run_recorded_turn(
            session,
            monkeypatch,
            "",
            confirmation=ConfirmationDecision(token_id=old, decision="confirm"),
        )
        sent = next(p for t, p in events if t == "reply_sent")
        assert (sent["path"], sent["route"]) == ("agent", "card_block")
        assert not session.overlay.locked
        assert (await _state(session))["confirmation_token_id"] == changed["confirmation_token_id"]
        assert [c.step for c in llm.calls].count("agent") == 4

        # Replay at the second typed turn, hand off at the third (D17 b).
        await run_one("sí")
        assert (await _state(session)).get("escalation_reason") is None
        await run_one("sí")
        final = await _state(session)
        assert not session.overlay.locked
        assert session.handoff_tools.created[-1].reason == "clarification_exhausted"
        assert final["confirmation_token_id"] is None
        assert changed["confirmation_token_id"] not in session.store._plans

    asyncio.run(run())


def test_r3_unverified_claim_is_replaced(fakebank_dir: Path, agent_on: None) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "agent": [
                    _propose("c1"),
                    AgentScript(rounds=[], finals=[_turn("Ya quedó bloqueada.", [0])]),
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(
                        request="Acción sin verificar.",
                        asked="Pidió ayuda.",
                        did="Nada.",
                        unfinished="Todo.",
                    )
                ],
            }
        )
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, raw_writes=_UnverifiedLockWrites()
        )
        await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        token = (await _state(session))["confirmation_token_id"]

        # A claim of "done" with nothing verified: code's text goes out, the card again.
        reply, debug = await run_turn(session.graph, "listo?", config=session.config)
        assert "bloqueada" not in reply
        assert debug.ui == ["confirm"]

        reply, _ = await run_turn(
            session.graph,
            "",
            config=session.config,
            confirmation=ConfirmationDecision(token_id=token, decision="confirm"),
        )
        assert "Listo" not in reply
        assert get_template("handoff_transfer", "es").split("{queue_label}")[0] in reply
        assert session.handoff_tools.created[-1].reason == "action_unverified"
        assert [c.step for c in llm.calls].count("agent") == 2

    asyncio.run(run())
