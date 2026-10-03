"""S1 test 6 (R4): a digit the model wrote outside a reference never reaches the customer."""

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from app.core.db import get_engine
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import AgentScript, ScriptedLLM, make_session, run_recorded_turn
from tests.stub_classifier import make_stub_classifier

_CUSTOMER = "CLI-TFSINGLE0002"
_TEXT = "como esta mi tarjeta"
_BAD_A = "Tu tarjeta 4821 esta {c1_status}."
_BAD_B1 = "Tu tarjeta terminada en 7731 esta {c1_status}."
_BAD_B2 = "Tu tarjeta terminada en 9902 esta {c1_status}."
_GOOD = "Tu tarjeta {c1_card_mask} esta {c1_status}."


def _turn(reply: str) -> AgentTurn:
    return AgentTurn(
        language="es",
        intents=["card_status"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply=reply,
    )


def _reply_sent(events: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    return next(p for t, p in events if t == "reply_sent")


@pytest.mark.usefixtures("agent_on")
def test_r4_digit_outside_reference_rejected(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    classifier = make_stub_classifier({_TEXT: {"card_status": 0.95}})
    sent: list[str] = []
    unmask = InMemoryPiiVault.unmask

    async def _spy(self: InMemoryPiiVault, text: str) -> str:
        # The runner unmasks exactly the reply it sends; record it here.
        sent.append(text)
        return await unmask(self, text)

    monkeypatch.setattr(InMemoryPiiVault, "unmask", _spy)

    async def run(script: AgentScript) -> list[tuple[str, dict[str, Any]]]:
        llm = ScriptedLLM({"agent": [script]})
        session = make_session(_CUSTOMER, fakebank_dir, llm, classifier=classifier)
        return await run_recorded_turn(session, monkeypatch, _TEXT)

    async def both() -> tuple[dict[str, Any], str, dict[str, Any], str]:
        # One event loop for both turns: the runner's DB engine binds to the first.
        rounds = [[("card_status", {})]]
        # Script A: the first final has a raw digit, the second is valid.
        a = _reply_sent(await run(AgentScript(rounds=rounds, finals=[_turn(_BAD_A), _turn(_GOOD)])))
        reply_a = sent[-1]
        # Script B: both finals have a raw digit, so the pipeline answers, degraded.
        b = _reply_sent(
            await run(AgentScript(rounds=rounds, finals=[_turn(_BAD_B1), _turn(_BAD_B2)]))
        )
        return a, reply_a, b, sent[-1]

    async def in_one_loop() -> tuple[dict[str, Any], str, dict[str, Any], str]:
        try:
            return await both()
        finally:
            # The runner's pooled DB connections belong to this loop; free them.
            await get_engine().dispose()

    a, reply_a, b, reply_b = asyncio.run(in_one_loop())

    assert a["path"] == "agent"
    assert a["degraded"] is False
    assert a["grounding"]["outcome"] == "regenerated"
    assert "4821" not in reply_a
    # Every digit run the reply carries is a code-formatted fact value.
    fact_digits = {m for v in a["fact_values"] for m in re.findall(r"\d+", v)}
    reply_digits = re.findall(r"\d+", reply_a)
    assert reply_digits
    assert set(reply_digits) <= fact_digits

    assert b["degraded"] is True
    assert b["path"] == "pipeline"
    assert "7731" not in reply_b
    assert "9902" not in reply_b
