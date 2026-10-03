"""A2 Done-when: an out-of-market / out-of-scope request abstains with no tool.

Drives `run_turn` over a fake LLM. Turn 1 leaves a `pending` clarification
(a multi-card customer asks about status without naming a card), then the
recorded tool calls are cleared: turn 2 (Pix / loans) must call no read,
write or handoff tool, keep `pending`, offer exactly the four scope facts to
`compose`, and emit one `abstain` quick-reply set.
"""

import asyncio
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest

from app.core.llm import LLMUnavailable
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.abstain import abstain
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.sandbox import _RecordingBankTools, _RecordingWriteTools
from app.domains.conversation.schemas import NLUResult, NLUSlots, NLUStatus
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBankOverlay, FakeBankWrites
from tests.conftest import ScriptedLLM, make_session
from tests.stub_classifier import make_stub_classifier

_FOUR_KEYS = ["topic_label", "abstain_reason", "closest_action", "human_offer"]


@pytest.mark.parametrize(
    ("language", "status", "topic", "text", "draft"),
    [
        (
            "es",
            "out_of_market",
            "pix_boleto",
            "¿puedo pagar con Pix?",
            "Con {topic_label}: {abstain_reason} {closest_action}. {human_offer}.",
        ),
        (
            "pt",
            "out_of_scope",
            "loans",
            "quero pedir um empréstimo",
            "Sobre {topic_label}: {abstain_reason} {closest_action}. {human_offer}.",
        ),
    ],
    ids=["es-pix", "pt-loans"],
)
def test_abstains_without_tools(
    fakebank_dir: Path,
    language: Literal["es", "pt"],
    status: NLUStatus,
    topic: Any,
    text: str,
    draft: str,
) -> None:
    ask = NLUResult(language=language, intents=["card_status"], status="clear", slots=NLUSlots())
    abstain_nlu = NLUResult(
        language=language, intents=["general_question"], status=status, slots=NLUSlots(topic=topic)
    )
    llm = ScriptedLLM({"nlu": [ask, abstain_nlu], "compose": [ComposeDraft(text=draft)]})

    # One shared call list records reads and raw writes alike.
    calls: list[str] = []
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    raw = _RecordingWriteTools(FakeBankWrites(ctx, fakebank_dir, FakeBankOverlay()), calls)
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm, raw_writes=raw)
    bank_tools = _RecordingBankTools(session.config["configurable"]["bank_tools"])
    bank_tools.calls = calls
    session.config["configurable"]["bank_tools"] = bank_tools

    _, debug1 = asyncio.run(run_turn(session.graph, "cual es el estado?", config=session.config))
    assert debug1.pending is not None
    calls.clear()

    _, debug2 = asyncio.run(run_turn(session.graph, text, config=session.config))

    assert debug2.route == "abstain"
    assert debug2.pending == debug1.pending
    # `load_session` reads the profile every turn (name + country); nothing else may run.
    assert calls == ["get_profile"]
    assert session.handoff_tools.created == []
    compose_call = [call for call in llm.calls if call.step == "compose"][-1]
    offered = compose_call.user.split("```")[1].split()
    assert offered == _FOUR_KEYS
    assert debug2.ui == ["quick_replies"]
    state = asyncio.run(session.graph.aget_state(session.config)).values
    (event,) = state["ui"]
    assert event.kind == "quick_replies"
    assert event.payload.slot == "abstain"


@pytest.mark.parametrize("with_classifier", [True, False], ids=["classifier", "no-classifier"])
def test_abstain_llm_error_marks_degraded_only_with_classifier(with_classifier: bool) -> None:
    llm = ScriptedLLM({"compose": [LLMUnavailable("boom")]})
    configurable: dict[str, Any] = {"llm": llm}
    if with_classifier:
        configurable["classifier"] = make_stub_classifier({})
    state: Any = {"language": "es", "country": "MX"}

    result = asyncio.run(abstain(state, {"configurable": configurable}))

    if with_classifier:
        assert result["degraded"] is True
    else:
        assert "degraded" not in result
