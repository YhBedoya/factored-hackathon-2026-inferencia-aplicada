"""Conversation memory in the turn graph (naturalidad-cardy D3, D5, D8). Fake LLM only."""

import asyncio
from pathlib import Path
from typing import Any

from app.core.llm import LLMUnavailable
from app.core.pii import find_pii
from app.domains.conversation.graph import run_turn
from app.domains.conversation.masking import mask_user_text
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.summarize import SummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import ScriptedLLM, Session, make_session

# A balance question is the cheapest turn that reaches `compose`.
_NLU = NLUResult(
    language="es", intents=["balance_due"], status="clear", slots=NLUSlots(card_hint="credit")
)
_DRAFT = ComposeDraft(text="{due_date}")
_SEED = ["alfa", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]


def _seed(session: Session, texts: list[str]) -> None:
    history = [
        {"role": "customer" if i % 2 == 0 else "cardy", "text": t} for i, t in enumerate(texts)
    ]
    asyncio.run(session.graph.aupdate_state(session.config, {"history": history}, as_node="finish"))


def _state(session: Session) -> Any:
    return asyncio.run(session.graph.aget_state(session.config)).values


def _calls(llm: ScriptedLLM, step: str) -> list[Any]:
    return [c for c in llm.calls if c.step == step]


def test_context_window_and_summary(fakebank_dir: Path) -> None:
    """D3: three turns carry the earlier messages and no summary; past the 6-message
    window exactly one `summary` call folds the overflow and both NLU and compose
    read the last 6 plus its text."""
    llm = ScriptedLLM({"nlu": [_NLU] * 3, "compose": [_DRAFT] * 3})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    for text in ("uno dos", "tres cuatro", "cinco seis"):
        asyncio.run(run_turn(session.graph, text, config=session.config))
    assert not _calls(llm, "summary")
    nlu3, compose3 = _calls(llm, "nlu")[2], _calls(llm, "compose")[2]
    for call in (nlu3, compose3):
        assert "cliente: " in call.user and "uno dos" in call.user and "tres cuatro" in call.user
        assert "resumen:" not in call.user

    llm = ScriptedLLM(
        {
            "nlu": [_NLU],
            "compose": [_DRAFT],
            "summary": [SummaryDraft(text="charla previa sobre tarjetas")],
        }
    )
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    _seed(session, _SEED)
    asyncio.run(run_turn(session.graph, "octavo", config=session.config))
    assert len(_calls(llm, "summary")) == 1
    nlu, compose = _calls(llm, "nlu")[0], _calls(llm, "compose")[0]
    for call in (nlu, compose):
        assert "resumen: charla previa sobre tarjetas" in call.user
        assert "gamma" in call.user and "zeta" in call.user
        assert "alfa" not in call.user and "beta" not in call.user
    assert "octavo" in compose.user


def test_r5_history_prompts_masked(fakebank_dir: Path) -> None:
    """R5: raw PII typed in earlier turns reaches no nlu, summary or compose prompt,
    and compose never sees a digit."""
    texts = [
        "Soy Prueba, mi correo es ana@example.com",
        "mi telefono es +525512345678",
        "me llamo Prueba y escribo desde ana@example.com",
        "otra vez +525512345678 por favor",
    ]
    llm = ScriptedLLM({"nlu": [_NLU] * 4, "compose": [_DRAFT] * 4})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    vault = InMemoryPiiVault()
    session.config["configurable"]["vault"] = vault  # type: ignore[index]
    bank_tools = session.config["configurable"]["bank_tools"]  # type: ignore[index]

    async def turns() -> None:
        for text in texts:
            masked = await mask_user_text(text, bank_tools=bank_tools, vault=vault)
            await run_turn(session.graph, masked, config=session.config)

    asyncio.run(turns())
    assert _calls(llm, "summary")
    for step in ("nlu", "summary", "compose"):
        for call in _calls(llm, step):
            assert find_pii(call.system + call.user) == []
    for call in _calls(llm, "compose"):
        assert not any(ch.isdigit() for ch in call.user)


def test_r11_summary_failure_degrades(fakebank_dir: Path) -> None:
    """R11, D5: a failed summary neither escalates nor blocks the reply; the window
    is still trimmed to 6 before `finish` appends the reply."""
    llm = ScriptedLLM(
        {
            "nlu": [_NLU],
            "compose": [_DRAFT],
            "summary": [LLMUnavailable("down")],
        }
    )
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    _seed(session, _SEED[:6])
    reply, debug = asyncio.run(run_turn(session.graph, "septimo", config=session.config))
    assert reply
    assert debug.route not in ("handoff_summary", "fallback")
    values = _state(session)
    assert not values.get("escalation_reason")
    history = values["history"]
    assert len(history) == 7  # 6 kept by `summarize` + this turn's reply from `finish`
    assert [m["text"] for m in history[:2]] == ["beta", "gamma"]
    assert history[-1] == {"role": "cardy", "text": reply}


def test_r5_address_turn_not_in_history(fakebank_dir: Path) -> None:
    """R5, A1: the replacement address turn carries the raw new address (the vault
    cannot mask it), so it never enters `history` and no LLM call sees it."""
    raw = "Calle Falsa zzz 123, Colonia Centro"
    llm = ScriptedLLM({})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    _seed(session, _SEED[:2])
    asyncio.run(
        session.graph.aupdate_state(
            session.config,
            {
                "language": "es",
                "selected_card_id": "PRD-TFM1CRED0001",
                "pending": {"flow": "replacement", "node": "address", "awaiting_slot": "address"},
            },
            as_node="finish",
        )
    )
    asyncio.run(run_turn(session.graph, raw, config=session.config))
    history = _state(session)["history"]
    assert [m["text"] for m in history[:2]] == _SEED[:2]
    assert all(raw not in m["text"] for m in history)
    assert all(raw not in call.system + call.user for call in llm.calls)
