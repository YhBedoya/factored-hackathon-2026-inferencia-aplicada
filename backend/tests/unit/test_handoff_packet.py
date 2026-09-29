"""D10 handoff packet and summary fallback (R3, R4, R5, R11).

See the spec's Test list rows `test_packet_from_readbacks_only` and
`test_summary_fallback`. Fake LLM and in-memory handoff tools only.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.actions import ActionResult
from app.core.llm import LLMUnavailable
from app.domains.conversation.nodes.handoff import handoff
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft, handoff_summary
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.handoff import InMemoryHandoffTools
from app.domains.handoff.schemas import HandoffPacket, reference_for
from tests.conftest import RecordingAudit, ScriptedLLM

_TYPED = "zx-secreto-quiero-un-humano-ya"


def _ctx() -> ToolContext:
    return ToolContext(
        customer_id="CLI-TFSINGLE0002",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )


def _state(**extra: Any) -> dict[str, Any]:
    return {
        "language": "es",
        "user_text": _TYPED,
        "escalation_reason": "human_request",
        "handoff_queue": "atencion",
        **extra,
    }


def _packet_fields() -> set[str]:
    return set(HandoffPacket.model_fields)


def test_packet_from_readbacks_only() -> None:
    ctx = _ctx()
    tools = InMemoryHandoffTools()
    audit = RecordingAudit()
    llm = ScriptedLLM(
        {"handoff_summary": [HandoffSummaryDraft(request="Pidió ayuda en {queue_label}.")]}
    )
    verified = ActionResult(
        tool="cards.lock_card", status="applied", verified=True, readback={"status": "locked"}
    )
    unverified = ActionResult(
        tool="cards.unlock_card", status="applied", verified=False, readback={"status": "?"}
    )
    state = _state(actions=[verified, unverified])
    config: dict[str, Any] = {
        "configurable": {
            "llm": llm,
            "session": ctx,
            "handoff_tools": tools,
            "audit": audit,
        }
    }

    draft = asyncio.run(handoff_summary(state, config))  # type: ignore[arg-type]
    state.update(draft)
    update = asyncio.run(handoff(state, config))  # type: ignore[arg-type]

    assert update["mode"] == "human"
    [packet] = tools.created
    dumped = packet.model_dump_json()
    assert set(packet.model_dump()) == _packet_fields()
    assert packet.conversation_id == ctx.conversation_id
    assert UUID(str(packet.handoff_id))
    [(_, audit_payload)] = audit.events
    assert audit_payload["action"] == "created"
    assert audit_payload["handoff_id"] == str(packet.handoff_id)
    # R3: only the verified read-back reaches the packet.
    assert [f.fact for f in packet.verified_facts] == ["card_locked"]
    assert [a.tool for a in packet.actions_taken] == ["cards.lock_card"]
    assert "card_unlocked" not in dumped
    # R5: the customer's own words are never copied into the packet.
    assert _TYPED not in dumped
    assert packet.sentiment is None
    assert 0 < len(packet.request) <= 200
    assert "{" not in packet.request
    # The prompt saw code-built keys only, not the customer's text.
    assert _TYPED not in llm.calls[0].user


@pytest.mark.parametrize(
    "outcome",
    [
        HandoffSummaryDraft(request="Llamar al 5551234567 ya."),
        LLMUnavailable("down"),
    ],
    ids=["raw-digit", "llm-unavailable"],
)
def test_summary_fallback(outcome: Any) -> None:
    llm = ScriptedLLM({"handoff_summary": [outcome]})
    state = _state(escalation_reason="legal_regulator", handoff_queue="reclamos", language="pt")
    config: dict[str, Any] = {"configurable": {"llm": llm}}

    update = asyncio.run(handoff_summary(state, config))  # type: ignore[arg-type]

    assert update["handoff_request"] == (
        "O cliente mencionou uma via legal ou regulatória. Requer atenção prioritária."
    )
    # R11: one call, no second attempt at drafting.
    assert len(llm.calls) == 1


class _ExistingHandoffTools(InMemoryHandoffTools):
    """Mimics the repository finding an already-open handoff (created=False)."""

    def __init__(self, existing: UUID) -> None:
        super().__init__()
        self.existing = existing

    async def create(self, packet: HandoffPacket) -> UUID:
        await super().create(packet)
        return self.existing


def test_existing_open_handoff_reference_is_reported() -> None:
    existing = uuid4()
    tools = _ExistingHandoffTools(existing)
    audit = RecordingAudit()
    config: dict[str, Any] = {
        "configurable": {"session": _ctx(), "handoff_tools": tools, "audit": audit}
    }
    state = _state(handoff_request="Pidió ayuda.")

    update = asyncio.run(handoff(state, config))  # type: ignore[arg-type]

    reference = reference_for(existing)
    assert update["handoff_id"] == str(existing)
    assert update["ui"][0].payload.reference == reference
    assert update["ui"][0].payload.handoff_id == str(existing)
    assert reference in update["segments"][0]
    assert reference_for(tools.created[0].handoff_id) not in update["segments"][0]
    [(audit_type, payload)] = audit.events
    assert audit_type == "handoff"
    assert payload["action"] == "attached"
    assert payload["handoff_id"] == str(existing)
