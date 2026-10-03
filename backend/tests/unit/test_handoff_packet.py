"""D10 handoff packet and summary fallback (R3, R4, R5, R11).

See the spec's Test list rows `test_packet_from_readbacks_only` and
`test_summary_fallback`. Fake LLM and in-memory handoff tools only.
"""

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.actions import ActionResult
from app.core.llm import LLMUnavailable
from app.domains.conversation import takeover
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.handoff import handoff
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft, handoff_summary
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.handoff import (
    HandoffTools,
    InMemoryHandoffTools,
    ServiceHandoffTools,
)
from app.domains.handoff.schemas import (
    CustomerHistory,
    HandoffPacket,
    PastHandoff,
    reference_for,
)
from tests.conftest import RecordingAudit, ScriptedLLM, make_session

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
        {
            "handoff_summary": [
                HandoffSummaryDraft(
                    request="Pidió ayuda en {queue_label}.",
                    asked="Pidió ayuda.",
                    did="Nada.",
                    unfinished="Todo.",
                )
            ]
        }
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
        HandoffSummaryDraft(
            request="Llamar al 5551234567 ya.",
            asked="Pidió ayuda.",
            did="Nada.",
            unfinished="Todo.",
        ),
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


def _run_handoff(state: dict[str, Any], tools: InMemoryHandoffTools) -> HandoffPacket:
    config: dict[str, Any] = {
        "configurable": {"session": _ctx(), "handoff_tools": tools, "audit": RecordingAudit()}
    }
    asyncio.run(handoff(state, config))  # type: ignore[arg-type]
    return tools.created[-1]


def test_packet_v2_code_fields(fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Routing branch: by_flow with a pending flow, default without one.
    pending = {"flow": "unrecognized_charge", "node": "n", "awaiting_slot": "transactions"}
    ask = NLUResult(language="es", intents=["human_request"], status="clear")
    unrouted = {"escalation_reason": None, "handoff_queue": None, "nlu": ask}
    by_flow = _run_handoff(_state(**unrouted, pending=pending), InMemoryHandoffTools())
    assert (by_flow.routing.branch, by_flow.routing.flow) == ("by_flow", "unrecognized_charge")  # type: ignore[union-attr]
    plain = _run_handoff(_state(**unrouted), InMemoryHandoffTools())
    assert (plain.routing.branch, plain.routing.flow) == ("default", None)  # type: ignore[union-attr]

    # Risk is snapshotted from the incoming state, which the node's return resets.
    state = _state(priority_flags=["fraud_suspected"], unauthorized_attempts=2)
    tools = InMemoryHandoffTools()
    config: dict[str, Any] = {
        "configurable": {"session": _ctx(), "handoff_tools": tools, "audit": RecordingAudit()}
    }
    update = asyncio.run(handoff(state, config))  # type: ignore[arg-type]
    risk = tools.created[0].risk
    assert update["priority_flags"] == []
    assert risk is not None
    assert (risk.priority_flags, risk.unauthorized_attempts) == (["fraud_suspected"], 2)

    # History comes from the tools; a failed read leaves it None and the handoff goes on.
    history = CustomerHistory(
        days=90,
        handoffs=[
            PastHandoff(
                reference="HO-1",
                reason="human_request",
                queue="atencion",
                status="returned",
                created_at=datetime.now(UTC),
            )
        ],
        claims=[],
    )
    assert _run_handoff(_state(), InMemoryHandoffTools(history=history)).history == history
    failed = _run_handoff(_state(), InMemoryHandoffTools(history_error=RuntimeError("db down")))
    assert failed.history is None

    # Friction is counted across two flows, then cleared by `return_to_bot`.
    async def drive() -> HandoffPacket:
        non_answer = NLUResult(language="es", intents=[], status="clear")
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["general_question"],
                        status="out_of_scope",
                        slots={"topic": "new_card"},  # type: ignore[arg-type]
                    ),
                    NLUResult(language="es", intents=["card_block"], status="clear"),
                    non_answer,
                    non_answer,
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(
                        request="No aclaró la tarjeta.",
                        asked="Pidió ayuda.",
                        did="Nada.",
                        unfinished="Todo.",
                    )
                ],
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        for text in ("quiero una tarjeta nueva", "quiero bloquear", "Todas", "Todas"):
            await run_turn(session.graph, text, config=session.config)
        return session.handoff_tools.created[-1]

    friction = asyncio.run(drive()).friction
    assert friction is not None
    assert friction.model_dump() == {"clarifications": 0, "abstentions": 1, "non_answers": 2}

    # An `understand`-level clarification counts too.
    async def ambiguous() -> dict[str, int] | None:
        class _Classifier:
            def predict(self, *_: Any, **__: Any) -> NLUResult:
                return NLUResult(language="es", intents=[], status="ambiguous")

        # The ambiguity counter lives in `understand`'s classifier path (degraded turn).
        llm = ScriptedLLM({"nlu": [LLMUnavailable("down")]})
        session = make_session(
            "CLI-TFMULTI00001",
            fakebank_dir,
            llm,
            classifier=_Classifier(),  # type: ignore[arg-type]
        )
        await run_turn(session.graph, "mmm", config=session.config)
        return (await session.graph.aget_state(session.config)).values.get("friction")

    counted = asyncio.run(ambiguous())
    assert counted is not None
    assert counted["clarifications"] == 1

    recorded: list[dict[str, Any]] = []

    class _Graph:
        async def aupdate_state(self, _config: Any, values: dict[str, Any]) -> None:
            recorded.append(values)

    class _Redis:
        async def set(self, *_: Any, **__: Any) -> bool:
            return True

        async def eval(self, *_: Any) -> int:
            return 0

    class _Vault:
        def __init__(self, _conversation_id: UUID) -> None: ...

        async def mask(self, text: str, _known: Any) -> str:
            return text

    async def _noop(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(takeover, "get_redis", lambda: _Redis())
    monkeypatch.setattr(takeover, "PostgresPiiVault", _Vault)
    monkeypatch.setattr(takeover.store, "add_message", _noop)
    monkeypatch.setattr(takeover.events, "publish", _noop)
    monkeypatch.setattr(takeover, "publish_mode", _noop)
    asyncio.run(takeover.return_to_bot(SimpleNamespace(graph=_Graph()), uuid4(), "es"))  # type: ignore[arg-type]
    assert recorded[0]["friction"] == {"clarifications": 0, "abstentions": 0, "non_answers": 0}


def test_r1_history_session_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    assert list(inspect.signature(HandoffTools.history).parameters) == ["self", "days"]
    ctx = _ctx()
    seen: list[tuple[Any, ...]] = []

    async def fake_history(*args: Any) -> None:
        seen.append(args)

    monkeypatch.setattr(
        "app.domains.conversation.tools.handoff.service.customer_history", fake_history
    )
    asyncio.run(ServiceHandoffTools(ctx).history(90))
    assert seen == [(ctx.customer_id, ctx.conversation_id, 90, 5)]
