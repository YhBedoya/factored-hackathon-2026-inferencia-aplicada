"""handoff_summary@v2 (D8-H T3): masked transcript, bounded placeholders, case summary.

Fake LLM only; the transcript comes from a hand-written masked fixture.
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.llm import LLMUnavailable
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft, handoff_summary
from app.domains.conversation.store import MessageRow
from tests.conftest import ScriptedLLM

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "handoff_ho293fb42e.json"
_CONVERSATION = uuid4()


def _rows() -> list[MessageRow]:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))["rows"]
    return [
        MessageRow(
            id=uuid4(),
            conversation_id=_CONVERSATION,
            turn_id=UUID(row["turn_id"]) if row["turn_id"] else None,
            role=row["role"],
            content=row["content"],
            content_masked=row["content_masked"],
            ui_payload=row["ui_payload"],
            created_at=datetime.now(UTC),
        )
        for row in raw
    ]


def _run(llm: ScriptedLLM, *, rows: list[MessageRow], language: str = "es", **state: Any) -> Any:
    async def transcript() -> list[MessageRow]:
        return rows

    full_state: dict[str, Any] = {
        "language": language,
        "user_text": "quiero hablar con una persona",
        "escalation_reason": "human_request",
        "handoff_queue": "atencion",
        **state,
    }
    config: dict[str, Any] = {"configurable": {"llm": llm, "transcript": transcript}}
    return asyncio.run(handoff_summary(full_state, config))  # type: ignore[arg-type]


def _draft(**fields: str) -> HandoffSummaryDraft:
    base = {
        "request": "Pidió ayuda.",
        "asked": "Pidió ayuda.",
        "did": "Nada.",
        "unfinished": "Todo.",
    }
    return HandoffSummaryDraft(**{**base, **fields})


def test_replay_ho293fb42e_es() -> None:
    llm = ScriptedLLM(
        {
            "handoff_summary": [
                _draft(
                    asked="Pidió bloquear {plan_card_mask} por {tx_count} movimientos.",
                    unfinished="No confirmó el bloqueo de {plan_card_mask}.",
                )
            ]
        }
    )

    update = _run(llm, rows=_rows())

    case = update["handoff_case_summary"]
    assert "2" in case["asked"]
    assert "•••• 9118" in case["asked"]
    assert "•••• 9118" in case["unfinished"]
    assert all("0 transacciones" not in v for v in [update["handoff_request"], *case.values()])
    assert "{tx_count}" in llm.calls[0].user

    # Bug regression: no evidence and no unanswered confirm -> no `{tx_count}`.
    rows = _rows()
    answered = [*rows, rows[-1].model_copy(update={"turn_id": uuid4()})]
    llm2 = ScriptedLLM({"handoff_summary": [_draft()]})
    _run(llm2, rows=answered)
    assert "{tx_count}" not in llm2.calls[0].user
    llm3 = ScriptedLLM({"handoff_summary": [_draft()]})
    _run(llm3, rows=[])
    assert "{tx_count}" not in llm3.calls[0].user


def test_pt_happy_path() -> None:
    llm = ScriptedLLM(
        {
            "handoff_summary": [
                _draft(
                    request="Cliente pediu pessoa na fila {queue_label}.",
                    asked="Pediu para falar com uma pessoa.",
                    did="Preparou o bloqueio.",
                    unfinished="Bloqueio não confirmado.",
                )
            ]
        }
    )

    update = _run(llm, rows=_rows(), language="pt")

    assert update["handoff_request"].startswith("Cliente pediu pessoa na fila ")
    assert "{" not in update["handoff_request"]
    assert update["handoff_case_summary"]["asked"] == "Pediu para falar com uma pessoa."
    assert "Idioma de la solicitud: pt" in llm.calls[0].user


@pytest.mark.parametrize("field", ["request", "asked", "did", "unfinished"])
@pytest.mark.parametrize("bad", ["Dos movimientos 2", "Usa {invented}"])
def test_r4_raw_digit_falls_back(field: str, bad: str) -> None:
    llm = ScriptedLLM({"handoff_summary": [_draft(**{field: bad})]})

    update = _run(llm, rows=_rows())

    assert update["handoff_case_summary"] is None
    assert update["handoff_request"] == (
        "El cliente pidió hablar con una persona. Revisa el contexto verificado."
    )
    assert len(llm.calls) == 1


def test_r5_only_masked_text_sent() -> None:
    llm = ScriptedLLM({"handoff_summary": [_draft()]})

    _run(llm, rows=_rows())

    sent = llm.calls[0].user
    assert "Nombre Ficticio Prueba" not in sent
    assert "Soy [NAME_1]" in sent


def test_r11_llm_error_one_call() -> None:
    llm = ScriptedLLM({"handoff_summary": [LLMUnavailable("down")]})

    update = _run(llm, rows=_rows())

    assert update["handoff_case_summary"] is None
    assert update["handoff_request"].startswith("El cliente pidió hablar")
    assert len(llm.calls) == 1
