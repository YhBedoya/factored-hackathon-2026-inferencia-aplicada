"""S1 test 8 (R11): the round cap hands off, and an LLM error falls back to the pipeline."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core.db import get_engine
from app.core.llm import LLMError
from app.domains.conversation import runner
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.templates import get_template
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import AgentScript, ScriptedLLM, make_session, run_recorded_turn
from tests.stub_classifier import make_stub_classifier

_CUSTOMER = "CLI-TFSINGLE0002"
_TEXT = "como esta mi tarjeta"


@pytest.mark.usefixtures("agent_on")
def test_round_cap_hands_off_and_llm_error_degrades(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    sent: list[str] = []
    unmask = InMemoryPiiVault.unmask

    async def _spy(self: InMemoryPiiVault, text: str) -> str:
        # The runner unmasks exactly the reply it sends; record it here.
        sent.append(text)
        return await unmask(self, text)

    monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)

    async def run() -> None:
        # An agent plan is open first; then seven rounds of a read tool, one more than
        # `MAX_ROUNDS`, hand off and cancel it.
        open_plan = AgentScript(
            rounds=[
                [("card_status", {})],
                [("propose_plan", {"steps": [{"action": "lock", "card": "c1"}]})],
            ],
            finals=[
                AgentTurn(
                    language="es",
                    intents=["card_block"],
                    outcome="answered",
                    awaiting_slot=None,
                    reported_done=[],
                    reply="Confirma en la tarjeta.",
                )
            ],
        )
        llm = ScriptedLLM(
            {
                "agent": [open_plan, AgentScript(rounds=[[("card_status", {})]] * 7, finals=[])],
                "handoff_summary": [HandoffSummaryDraft(request="El asistente no pudo completar.")],
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        # The runner builds the real (DB-backed) handoff tools; use the session's in-memory ones.
        monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)
        await run_recorded_turn(session, monkeypatch, "bloquea mi tarjeta")
        token = (await session.graph.aget_state(session.config)).values["confirmation_token_id"]
        assert token in session.store._plans
        events = await run_recorded_turn(session, monkeypatch, _TEXT)
        assert token not in session.store._plans
        assert session.handoff_tools.created[-1].reason == "agent_round_cap"
        prefix = get_template("handoff_transfer", "es").split("{queue_label}")[0]
        assert sent[-1].startswith(prefix)
        assert "nlu" not in [c.step for c in llm.calls]
        assert next(p for t, p in events if t == "reply_sent")["route"] == "handoff"

        # A scripted LLM error: the classifier serves the turn through the pipeline.
        classifier = make_stub_classifier({_TEXT: {"card_status": 0.95}})
        llm = ScriptedLLM({"agent": [AgentScript(rounds=[], finals=[LLMError("boom")])]})
        session = make_session(_CUSTOMER, fakebank_dir, llm, classifier=classifier)
        events = await run_recorded_turn(session, monkeypatch, _TEXT)
        reply_sent: dict[str, Any] = next(p for t, p in events if t == "reply_sent")
        assert reply_sent["degraded"] is True
        assert reply_sent["path"] == "pipeline"
        assert reply_sent["route"] == "card_info"

    async def in_one_loop() -> None:
        try:
            await run()
        finally:
            # The runner's pooled DB connections belong to this loop; free them.
            await get_engine().dispose()

    asyncio.run(in_one_loop())
