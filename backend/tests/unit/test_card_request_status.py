"""`card_request_status`: Cardy answers "¿se aprobó?" from the bank, not from the chat.

Labels per status, the staff-only decline reason never reaching the agent, figures
formatted in code (R4), and one ES and one PT happy path with a fake LLM.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig

from app.domains.cards.schemas import CustomerCardRequest
from app.domains.conversation.agent.reads import read_tools, request_status
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import GraphState, run_turn
from app.domains.conversation.nodes.compose import format_fact
from app.domains.conversation.state import Fact
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank, FakeBankOverlay
from app.domains.conversation.tools.registry import RecordingBankTools
from app.domains.localization.format import format_money, mask_card
from tests.conftest import AgentScript, RecordingAudit, ScriptedLLM, make_session

_CUSTOMER = "CLI-TFMULTI00001"
_CREDIT_CARD = "PRD-TFM1CRED0001"  # last4 6475, USD, MX customer
_NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)

_PAIRS: list[tuple[Literal["pending", "decided"], Any]] = [
    ("pending", None),
    ("decided", "approve"),
    ("decided", "decline"),
    ("decided", "cancel"),
    ("decided", "keep"),
    ("decided", "not_cancelled_balance"),
]


def _request(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "reference": "CRQ-0A1B2C3D",
        "kind": "open",
        "card_kind": "credit",
        "status": "decided",
        "decision": "approve",
        "decline_reason": None,
        "product_id": _CREDIT_CARD,
        "credit_limit": Decimal("5000.00"),
        "changed_fields": [],
        "reason_code": None,
        "created_at": _NOW,
        "decided_at": _NOW + timedelta(hours=1),
    }
    row.update(over)
    return row


def test_every_request_status_has_es_and_pt_label() -> None:
    labels: dict[str, set[str]] = {"es": set(), "pt": set()}
    for status, decision in _PAIRS:
        request = CustomerCardRequest(
            reference="CRQ-X",
            kind="open",
            card_kind="credit",
            status=status,
            decision=decision,
            product_id=None,
            credit_limit=None,
            created_at=_NOW,
            decided_at=None,
        )
        code = request_status(request)
        for language in ("es", "pt"):
            fact = Fact(key="request_status", value=code, source="test")
            text = format_fact(
                "request_status", {"request_status": fact}, language=language, country="MX"
            )
            assert text, (code, language)
            labels[language].add(text)
    assert len(labels["es"]) == len(_PAIRS) and len(labels["pt"]) == len(_PAIRS)


async def _tool_output(overlay: FakeBankOverlay, fakebank_dir: Path) -> tuple[str, TurnRefs]:
    ctx = ToolContext(
        customer_id=_CUSTOMER,
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    config = cast(
        RunnableConfig, {"configurable": {"bank_tools": FakeBank(ctx, fakebank_dir, overlay)}}
    )
    refs = TurnRefs("es", "MX")
    state = cast(GraphState, {"language": "es", "country": "MX"})
    tool = next(t for t in read_tools(state, config, refs) if t.name == "card_request_status")
    return await tool.handler(tool.args_schema()), refs


def test_decline_reason_never_reaches_the_agent(fakebank_dir: Path) -> None:
    overlay = FakeBankOverlay()
    overlay.card_requests[uuid4()] = _request(
        decision="decline", decline_reason="low_credit_score", product_id=None, credit_limit=None
    )
    out, refs = asyncio.run(_tool_output(overlay, fakebank_dir))
    assert "low_credit_score" not in out and "credit_score" not in out
    assert refs.value("r1_request_status") == "no aprobada"
    assert "r1_credit_limit" not in refs.keys()


def test_approved_credit_figures_are_formatted_in_code(fakebank_dir: Path) -> None:
    """R4: the mask and the limit come from code, never from the chat."""
    overlay = FakeBankOverlay()
    overlay.card_requests[uuid4()] = _request(created_at=_NOW - timedelta(days=2), kind="close")
    overlay.card_requests[uuid4()] = _request()
    _, refs = asyncio.run(_tool_output(overlay, fakebank_dir))
    assert refs.value("r1_request_status") == "aprobada"  # newest first
    assert refs.value("r1_card_mask") == mask_card("6475")
    assert refs.value("r1_credit_limit") == format_money(Decimal("5000.00"), "USD", "MX")
    assert refs.value("r1_tracking_id") == "CRQ-0A1B2C3D"
    assert refs.value("r2_request_kind") == "cierre de tarjeta"


@pytest.mark.usefixtures("agent_on")
@pytest.mark.parametrize(
    ("language", "text", "reply", "expected"),
    [
        ("es", "¿Se aprobó mi tarjeta?", "Tu solicitud está {r1_request_status}.", "aprobada"),
        ("pt", "Meu cartão foi aprovado?", "Sua solicitação está {r1_request_status}.", "aprovada"),
    ],
)
def test_customer_asks_if_approved(
    fakebank_dir: Path, language: Literal["es", "pt"], text: str, reply: str, expected: str
) -> None:
    async def run() -> tuple[str, list[str], RecordingAudit]:
        final = AgentTurn(
            language=language,
            intents=["card_status"],
            outcome="answered",
            awaiting_slot=None,
            reported_done=[],
            reply=reply,
        )
        llm = ScriptedLLM(
            {"agent": [AgentScript(rounds=[[("card_request_status", {})]], finals=[final])]}
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)
        session.overlay.card_requests[uuid4()] = _request()
        configurable = session.config["configurable"]
        configurable["bank_tools"] = RecordingBankTools(configurable["bank_tools"], session.audit)
        answer, debug = await run_turn(session.graph, text, config=session.config)
        return answer, debug.tools_called, session.audit

    answer, tools_called, audit = asyncio.run(run())
    assert expected in answer
    assert "get_card_requests" in tools_called
    assert any(
        kind == "tool_call" and payload.get("tool") == "cards.get_card_requests"
        for kind, payload in audit.events
    )
