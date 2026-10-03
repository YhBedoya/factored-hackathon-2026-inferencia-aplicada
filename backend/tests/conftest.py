"""Shared pytest fixtures. See D1-B state file's T8 entry for how tasks reuse these.

`ScriptedLLM` is a fake `LLMClient`: no network, no LangChain, per-step queues
of canned outputs (or exceptions) that tests script ahead of time, and a
`calls` list recording exactly what each `structured()` call was asked --
`step`, `prompt`, `system`, `user` and `schema` -- so a test can assert what
did (and did not) reach the "model".

`make_session` (T10) is the write-flow test harness: it wires the same six
objects `card_block.py` (and every later confirmed-write flow) needs --
`FakeBank`/`FakeBankWrites` over a fresh `FakeBankOverlay`, `ConfirmedWriteTools`
over an `InMemoryConfirmationStore` and a `FakeStepUpGate`, `InMemoryAddressVault`
-- once, so a flow test doesn't hand-roll that wiring itself.
"""

from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, JsonValue

from app.core.config import get_settings
from app.core.llm import (
    LLMError,
    LLMInvalidOutput,
    LLMRoundCap,
    LoopMessage,
    LoopTool,
    PromptRef,
    Step,
)
from app.domains.audit.schemas import AuditType, NullAuditRecorder
from app.domains.conversation import templates
from app.domains.conversation.classifier import IntentClassifier
from app.domains.conversation.graph import GraphState, TurnInput, TurnOutput, build_graph
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import FakeBank, FakeBankOverlay, FakeBankWrites
from app.domains.conversation.tools.handoff import InMemoryHandoffTools
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.tools_policy import (
    has_preconditions,
    load_tools_policy,
    step_up_rule,
    tool_allowed,
)
from app.domains.safety.vault import InMemoryAddressVault

__all__ = [
    "AgentScript",
    "Call",
    "RecordingAudit",
    "ScriptedLLM",
    "Session",
    "agent_on",
    "make_session",
    "run_recorded_turn",
]


@dataclass(frozen=True)
class Call:
    """One recorded `ScriptedLLM.structured()` call."""

    step: Step
    prompt: PromptRef
    system: str
    user: str
    schema: type[BaseModel]
    # Set only by `tool_loop`: the loop's input messages and every tool result
    # string, so a test can search all the text the model was given.
    messages: tuple[str, ...] = ()
    tool_results: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentScript:
    """One scripted `tool_loop` call: `rounds` are the tool calls (name, args) of
    each model response, `finals` the outputs offered in order (the second one
    is the retry after `validate` refuses the first).

    >>> AgentScript(rounds=[[("list_cards", {})]], finals=[AgentTurn(...)])
    """

    rounds: Sequence[Sequence[tuple[str, dict[str, Any]]]]
    finals: Sequence[BaseModel | LLMError]


@dataclass
class ScriptedLLM:
    """A scripted `LLMClient` fake. Construct with a queue per step.

    >>> llm = ScriptedLLM({"compose": [ComposeDraft(text="hola {card_mask}")]})
    >>> await llm.structured(step="compose", ..., schema=ComposeDraft)
    ComposeDraft(text="hola {card_mask}")
    >>> llm.calls[0].step
    'compose'
    """

    outputs: dict[Step, Sequence[BaseModel | LLMError | AgentScript]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list, init=False)
    _queues: dict[Step, list[BaseModel | LLMError | AgentScript]] = field(init=False)

    def __post_init__(self) -> None:
        self._queues = {step: list(items) for step, items in self.outputs.items()}

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[Any]
    ) -> Any:
        self.calls.append(Call(step=step, prompt=prompt, system=system, user=user, schema=schema))
        queue = self._queues.get(step)
        if not queue and step == "summary" and step not in self._queues:
            # The summary step runs from the fourth typed turn on; most tests don't
            # script it, so it gets a harmless default. A scripted queue still wins.
            return schema.model_validate({"text": "resumen previo"})
        if not queue:
            raise AssertionError(f"ScriptedLLM: no scripted output left for step {step!r}")
        result = queue.pop(0)
        if isinstance(result, LLMError):
            raise result
        return cast(Any, result)

    async def tool_loop(
        self,
        *,
        step: Step,
        prompt: PromptRef,
        system: str,
        messages: Sequence[LoopMessage],
        tools: Sequence[LoopTool],
        schema: type[Any],
        max_rounds: int,
        validate: Callable[[Any], str | None] | None = None,
    ) -> Any:
        queue = self._queues.get(step)
        if not queue:
            raise AssertionError(f"ScriptedLLM: no scripted output left for step {step!r}")
        script = queue.pop(0)
        assert isinstance(script, AgentScript), f"step {step!r}: expected an AgentScript"
        by_name = {tool.name: tool for tool in tools}
        results: list[str] = []
        self.calls.append(
            Call(
                step=step,
                prompt=prompt,
                system=system,
                user="",
                schema=schema,
                messages=tuple(m.content for m in messages),
                tool_results=(),
            )
        )
        for index, round_calls in enumerate(script.rounds):
            if index >= max_rounds:
                raise LLMRoundCap(f"script has more than {max_rounds} rounds")
            for name, args in round_calls:
                assert name in by_name, f"ScriptedLLM: scripted unknown tool {name!r}"
                tool = by_name[name]
                results.append(await tool.handler(tool.args_schema.model_validate(args)))
                # Replace the recorded call so `tool_results` is current even if a later
                # handler raises.
                self.calls[-1] = replace(self.calls[-1], tool_results=tuple(results))
        finals = list(script.finals)
        for final in finals[:2]:
            if isinstance(final, LLMError):
                raise final
            reason = validate(final) if validate is not None else None
            if reason is None:
                return final
        raise LLMInvalidOutput("ScriptedLLM: scripted finals failed validation or ran out")


class _FirstVariant:
    """A stand-in for `random` that always picks the first variant."""

    def choice(self, seq: Sequence[str], /) -> str:
        return seq[0]


@pytest.fixture(autouse=True)
def _first_template_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Template variants are random in production (D13); tests see variant 0."""
    monkeypatch.setattr(templates, "_RNG", _FirstVariant())


def strip_closing(reply: str, language: str) -> str:
    """Assert `reply` ends with a closing (generic or one of the two suggestions,
    variant 0 under tests) and return it without that last segment, so a flow's
    own text is asserted alone."""
    for kind in (
        "closing_generic",
        "closing_suggest_transaction_search",
        "closing_suggest_unrecognized_charge",
    ):
        closing = "\n\n" + templates.get_template(cast(Any, kind), cast(Any, language))
        if reply.endswith(closing):
            return reply[: -len(closing)]
    raise AssertionError(f"reply does not end with a closing: {reply!r}")


@pytest.fixture(autouse=True)
def _empty_intent_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test may pick up a real classifier bundle from the checkout (D24)."""
    monkeypatch.setenv("INTENT_MODEL_DIR", str(tmp_path / "intent-models"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def scripted_llm() -> type[ScriptedLLM]:
    """A factory fixture: call it with the per-step outputs dict to build one `ScriptedLLM`."""
    return ScriptedLLM


@pytest.fixture
def fakebank_dir() -> Path:
    """The fabricated TEST FIXTURE data directory (T5), never `data/`."""
    return Path(__file__).resolve().parent / "fixtures" / "fakebank"


@dataclass
class RecordingAudit:
    """A `Recorder` fake that keeps what it was asked to record, so a flow
    test can assert which audit events a turn wrote."""

    events: list[tuple[AuditType, dict[str, JsonValue]]] = field(default_factory=list)

    async def record(
        self, type: AuditType, payload: dict[str, JsonValue], sources: Sequence[str] = ()
    ) -> UUID:
        self.events.append((type, payload))
        return uuid4()


@dataclass
class Session:
    """One write-flow test session (T10): the compiled graph, its `config`,
    and the pieces a test pokes at directly (`gate.verify`, `store`'s raw
    plans, `overlay`'s locked/blocked sets, `handoff`'s recorded packets, D4-B)."""

    graph: CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]
    config: RunnableConfig
    gate: FakeStepUpGate
    store: InMemoryConfirmationStore
    overlay: FakeBankOverlay
    handoff_tools: InMemoryHandoffTools
    audit: RecordingAudit


def make_session(
    customer_id: str,
    fakebank_dir: Path,
    llm: ScriptedLLM,
    *,
    otp_code: str = "0000",
    raw_writes: BankWriteTools | None = None,
    clock: Callable[[], datetime] | None = None,
    write_audit: bool = False,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    classifier: IntentClassifier | None = None,
) -> Session:
    """Build one write-flow session over the test fixture (T10).

    `raw_writes` lets a test swap in a stub (R3's unverified write) instead
    of the real `FakeBankWrites`; either way the read side (`bank_tools`)
    shares one `FakeBankOverlay` with it, so a write this session made is
    visible to its own reads (D7), same as `make_fakebank_factory`.

    `write_audit=True` hands the session's `RecordingAudit` to `ConfirmedWriteTools`
    (default: `NullAuditRecorder`), so a test can read its `tool_result` rows;
    `sleep` replaces the retry backoff sleep; `classifier` (default none, i.e.
    today's behaviour) lands in `configurable` for the degraded path (ADR-032).
    """
    conversation_id = uuid4()
    ctx = ToolContext(
        customer_id=customer_id,
        conversation_id=conversation_id,
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    overlay = FakeBankOverlay()
    bank_tools = FakeBank(ctx, fakebank_dir, overlay)
    raw = raw_writes if raw_writes is not None else FakeBankWrites(ctx, fakebank_dir, overlay)
    store = InMemoryConfirmationStore(
        customer_id, str(conversation_id), **({} if clock is None else {"clock": clock})
    )
    gate = FakeStepUpGate(otp_code)
    policy = load_tools_policy()
    handoff_tools = InMemoryHandoffTools()
    audit = RecordingAudit()
    write_tools = ConfirmedWriteTools(
        raw,
        store,
        gate,
        step_up_rule(policy),
        tool_allowed(policy),
        audit if write_audit else NullAuditRecorder(),
        **({} if sleep is None else {"sleep": sleep}),
        has_preconditions=has_preconditions(policy),
    )

    config: RunnableConfig = {
        "configurable": {
            "thread_id": str(conversation_id),
            "session": ctx,
            "bank_tools": bank_tools,
            "bank_write_tools": write_tools,
            "vault": InMemoryAddressVault(),
            "llm": llm,
            "handoff_tools": handoff_tools,
            "audit": audit,
            "classifier": classifier,
        }
    }
    graph = build_graph(MemorySaver())
    return Session(
        graph=graph,
        config=config,
        gate=gate,
        store=store,
        overlay=overlay,
        handoff_tools=handoff_tools,
        audit=audit,
    )


@pytest.fixture
def agent_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Turn the agent on (`AGENT_ENABLED=true`) for one test; the settings cache is
    cleared before and after so no other test sees the flag.

    >>> def test_x(agent_on): ...
    """
    monkeypatch.setenv("AGENT_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def run_recorded_turn(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    *,
    confirmation: Any = None,
    selection: Any = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Run one turn through `runner._run_turn_traced` (the patches `test_degraded.py`
    uses) and return the audit events that turn appended to `session.audit.events`.

    >>> events = await run_recorded_turn(session, monkeypatch, "bloquea mi tarjeta")
    """
    from app.domains.conversation import runner
    from app.domains.safety.vault import InMemoryPiiVault

    cfg: Any = session.config["configurable"]
    ctx = cfg["session"]

    async def _publish(_: Any, kind: str, data: dict[str, Any]) -> None:
        return None

    async def _add_message(*_: Any, **__: Any) -> None:
        return None

    async def _no_messages(*_: Any, **__: Any) -> list[Any]:
        return []

    class _Redis:
        async def eval(self, *_: Any) -> int:
            return 0

    monkeypatch.setattr(runner.registry, "build_tool_context", lambda *_: ctx)
    bank = cfg["bank_tools"]
    # The runner reads `tools.calls` for the debug line; the fake bank has none.
    bank.calls = []
    monkeypatch.setattr(runner.registry, "audit_recorder_for", lambda *_: session.audit)
    monkeypatch.setattr(runner.registry, "turn_tools", lambda *_: (bank, cfg["bank_write_tools"]))
    monkeypatch.setattr(runner.events, "publish", _publish)
    monkeypatch.setattr(runner.store, "add_message", _add_message)
    monkeypatch.setattr(runner.store, "list_messages", _no_messages)
    monkeypatch.setattr(runner, "get_redis", lambda: _Redis())

    before = len(session.audit.events)
    host: Any = SimpleNamespace(graph=session.graph, llm=cfg["llm"], classifier=cfg["classifier"])
    await runner._run_turn_traced(
        host,
        session=SimpleNamespace(),
        conversation_id=ctx.conversation_id,
        turn_id=uuid4(),
        text=text,
        graph_text=text,
        vault=InMemoryPiiVault(),
        resume=None,
        confirmation=confirmation,
        selection=selection,
        trace_id="test-trace",
    )
    return [(str(t), dict(p)) for t, p in session.audit.events[before:]]
