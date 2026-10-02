"""Degraded mode (ADR-032): a classifier-served turn under an always-failing LLM.

R2 and R3 must hold exactly as on the normal path: no write without a
server-issued token, no "done" without a verified read-back. The LLM here only
ever raises `LLMUnavailable`; the stub classifier is the real adapter over a
text -> probabilities map.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import get_settings
from app.core.llm import LLMError, LLMUnavailable
from app.domains.conversation import runner
from app.domains.conversation.flows.card_block import TEMPORARY_LOCK_LABEL
from app.domains.conversation.graph import ConfirmationDecision, DebugInfo, run_turn
from app.domains.conversation.templates import get_template
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import Session, make_session
from tests.stub_classifier import make_stub_classifier

_CUSTOMER = "CLI-TFSINGLE0002"

# Per language: the typed texts the stub recognises (exact scored text -> label).
_TEXTS = {
    "es": {
        "status": "como esta mi tarjeta",
        "block": "bloquea mi tarjeta",
        "yes": "si",
        "no": "no gracias",
        "pix": "quiero hacer un pix",
        "search": "busca mis compras de ayer",
        "decline": "por que rechazaron mi compra",
    },
    "pt": {
        "status": "como está meu cartão",
        "block": "quero bloquear meu cartão",
        "yes": "sim",
        "no": "não obrigado",
        "pix": "quero fazer um pix",
        "search": "procure minhas compras de ontem",
        "decline": "por que recusaram minha compra",
    },
}


class _DownLLM:
    """Every `structured` call raises `LLMUnavailable`; counts the attempts."""

    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, **_: Any) -> Any:
        self.calls += 1
        raise LLMUnavailable("down")


def _classifier(lang: str) -> Any:
    t = _TEXTS[lang]
    return make_stub_classifier(
        {
            t["status"]: {"card_status": 0.95},
            t["block"]: {"card_block": 0.95},
            t["yes"]: {"affirm": 0.95},
            t["no"]: {"deny": 0.95},
            t["pix"]: {"pix_boleto": 0.95},
            t["search"]: {"transaction_search": 0.95},
            t["decline"]: {"decline_explain": 0.95},
        }
    )


def _session(fakebank_dir: Path, lang: str = "es", **kw: Any) -> tuple[Session, _DownLLM]:
    llm = _DownLLM()
    return (
        make_session(_CUSTOMER, fakebank_dir, llm, classifier=_classifier(lang), **kw),  # type: ignore[arg-type]
        llm,
    )


async def _plan_lock(session: Session, lang: str) -> str:
    """Typed block -> lock-vs-block chip -> the confirmation token id."""
    _, debug = await run_turn(session.graph, _TEXTS[lang]["block"], config=session.config)
    assert debug.pending == "card_block.block_kind"
    _, debug = await run_turn(session.graph, TEMPORARY_LOCK_LABEL[lang], config=session.config)
    assert debug.pending == "card_block.confirmation"
    state = await session.graph.aget_state(session.config)
    return str(state.values["confirmation_token_id"])


def _confirm(token_id: str) -> ConfirmationDecision:
    return ConfirmationDecision(token_id=token_id, decision="confirm")


@pytest.mark.parametrize("case", ["missing", "stale", "replayed"])
def test_degraded_write_needs_token(case: str, fakebank_dir: Path) -> None:
    """R2: a degraded card_block runs no write tool without a live, matching token."""

    async def run() -> None:
        session, _ = _session(fakebank_dir)
        if case == "missing":
            # A bare "si" with no plan (so no token) pending: nothing may be written.
            await run_turn(session.graph, _TEXTS["es"]["yes"], config=session.config)
            assert not session.overlay.locked
            return
        token = await _plan_lock(session, "es")
        if case == "stale":
            await run_turn(
                session.graph,
                "",
                config=session.config,
                confirmation=ConfirmationDecision(token_id="not-the-token", decision="confirm"),
            )
            assert not session.overlay.locked
            return
        await run_turn(session.graph, "", config=session.config, confirmation=_confirm(token))
        assert session.overlay.locked
        before = set(session.overlay.locked)
        # Replaying the consumed token must not write again nor re-lock.
        await run_turn(session.graph, "", config=session.config, confirmation=_confirm(token))
        assert set(session.overlay.locked) == before

    asyncio.run(run())


def test_degraded_done_requires_readback(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    """R3: an unverified read-back on a degraded turn yields no "done" text."""
    monkeypatch.setenv("FAULTS", "readback_mismatch")
    get_settings.cache_clear()

    async def run() -> None:
        session, _ = _session(fakebank_dir)
        token = await _plan_lock(session, "es")
        reply, _ = await run_turn(
            session.graph, "", config=session.config, confirmation=_confirm(token)
        )
        assert "bloqueada" not in reply.lower()
        assert get_template("handoff_transfer", "es").split("{queue_label}")[0] in reply
        assert session.handoff_tools.created[0].reason == "action_unverified"

    asyncio.run(run())


@pytest.mark.parametrize("lang", ["es", "pt"])
def test_degraded_paths(lang: str, fakebank_dir: Path) -> None:
    t = _TEXTS[lang]

    async def run() -> None:
        session, _ = _session(fakebank_dir, lang)
        cfg = session.config

        reply, debug = await run_turn(session.graph, t["status"], config=cfg)
        assert reply and debug.degraded
        assert debug.route == "card_info"

        # card block: chip -> confirm -> verified read-back
        token = await _plan_lock(session, lang)
        reply, debug = await run_turn(session.graph, "", config=cfg, confirmation=_confirm(token))
        # A button confirmation runs no NLU, so there is nothing to degrade: the
        # lock itself must still be verified (R3) and the reply a normal one.
        assert session.overlay.locked
        assert not session.handoff_tools.created

        # affirm / deny on a pending yes/no: a fresh plan, then "no" cancels
        await _plan_lock(session2 := _fresh(fakebank_dir, lang), lang)
        _, debug = await run_turn(session2.graph, t["no"], config=session2.config)
        assert debug.degraded
        assert not session2.overlay.locked
        await _plan_lock(session3 := _fresh(fakebank_dir, lang), lang)
        _, debug = await run_turn(session3.graph, t["yes"], config=session3.config)
        assert debug.degraded
        assert session3.overlay.locked

        # Pix -> abstain (a fixed reply, no handoff)
        reply, debug = await run_turn(session.graph, t["pix"], config=cfg)
        assert debug.degraded
        assert debug.route == "abstain"

        # transaction_search -> handoff llm_unavailable (D7)
        _, debug = await run_turn(session.graph, t["search"], config=cfg)
        assert debug.degraded
        assert session.handoff_tools.created[-1].reason == "llm_unavailable"

    def _fresh(d: Path, language: str) -> Session:
        return _session(d, language)[0]

    asyncio.run(run())


def test_degraded_decline_explain_hands_off(fakebank_dir: Path) -> None:
    """A degraded decline_explain hands off before any tool runs (human decision at
    the verify gate): the reply is the handoff one, not the canned apology."""

    async def run() -> None:
        session, _ = _session(fakebank_dir)
        reply, debug = await run_turn(session.graph, _TEXTS["es"]["decline"], config=session.config)
        assert debug.degraded
        assert not debug.tools_called
        assert get_template("handoff_transfer", "es").split("{queue_label}")[0] in reply
        assert session.handoff_tools.created[-1].reason == "llm_unavailable"

    asyncio.run(run())


def test_runner_marks_degraded_in_debug_and_audit(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    """The real runner path (not `run_turn`): a failed LLM call plus a loaded
    classifier marks the turn degraded in `DebugInfo` and in `reply_sent`."""

    class _FailingLLM:
        async def structured(self, **_: Any) -> Any:
            raise LLMError("boom")

    session = make_session(
        _CUSTOMER,
        fakebank_dir,
        _FailingLLM(),  # type: ignore[arg-type]
        classifier=_classifier("es"),
    )
    cfg: Any = session.config["configurable"]
    ctx = cfg["session"]
    published: list[tuple[str, dict[str, Any]]] = []

    async def _publish(_: Any, kind: str, data: dict[str, Any]) -> None:
        published.append((kind, data))

    async def _add_message(*_: Any, **__: Any) -> None:
        return None

    class _Redis:
        async def eval(self, *_: Any) -> int:
            return 0

    monkeypatch.setattr(runner.registry, "build_tool_context", lambda *_: ctx)
    # The runner reads `tools.calls` for the debug line; the fake bank has none.
    bank = cfg["bank_tools"]
    bank.calls = []
    monkeypatch.setattr(runner.registry, "audit_recorder_for", lambda *_: session.audit)
    monkeypatch.setattr(runner.registry, "turn_tools", lambda *_: (bank, cfg["bank_write_tools"]))
    monkeypatch.setattr(runner.events, "publish", _publish)
    monkeypatch.setattr(runner.store, "add_message", _add_message)
    monkeypatch.setattr(runner, "get_redis", lambda: _Redis())
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(runner.trace, "get_tracer", lambda name: provider.get_tracer(name))

    async def run() -> None:
        host: Any = SimpleNamespace(
            graph=session.graph, llm=cfg["llm"], classifier=cfg["classifier"]
        )
        await runner._run_turn_traced(
            host,
            session=SimpleNamespace(),  # type: ignore[arg-type]
            conversation_id=ctx.conversation_id,
            turn_id=uuid4(),
            text=_TEXTS["es"]["status"],
            graph_text=_TEXTS["es"]["status"],
            vault=InMemoryPiiVault(),
            resume=None,
            confirmation=None,
            selection=None,
            trace_id="test-trace",
        )

    asyncio.run(run())

    debug = DebugInfo.model_validate(next(d for k, d in published if k == "debug"))
    assert debug.degraded
    reply_sent = [p for t, p in session.audit.events if t == "reply_sent"]
    assert reply_sent and reply_sent[0]["degraded"] is True
    # The attribute lands on the turn's own span, which outlives the request span.
    (turn_span,) = exporter.get_finished_spans()
    assert turn_span.name == "cardy.turn"
    assert (turn_span.attributes or {})["cardy.degraded"] is True
