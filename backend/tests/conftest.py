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

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, JsonValue

from app.core.llm import LLMError, PromptRef, Step
from app.domains.audit.schemas import AuditType, NullAuditRecorder
from app.domains.conversation import templates
from app.domains.conversation.graph import GraphState, TurnInput, TurnOutput, build_graph
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import FakeBank, FakeBankOverlay, FakeBankWrites
from app.domains.conversation.tools.handoff import InMemoryHandoffTools
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.tools_policy import load_tools_policy, step_up_rule, tool_allowed
from app.domains.safety.vault import InMemoryAddressVault

__all__ = ["Call", "RecordingAudit", "ScriptedLLM", "Session", "make_session"]


@dataclass(frozen=True)
class Call:
    """One recorded `ScriptedLLM.structured()` call."""

    step: Step
    prompt: PromptRef
    system: str
    user: str
    schema: type[BaseModel]


@dataclass
class ScriptedLLM:
    """A scripted `LLMClient` fake. Construct with a queue per step.

    >>> llm = ScriptedLLM({"compose": [ComposeDraft(text="hola {card_mask}")]})
    >>> await llm.structured(step="compose", ..., schema=ComposeDraft)
    ComposeDraft(text="hola {card_mask}")
    >>> llm.calls[0].step
    'compose'
    """

    outputs: dict[Step, Sequence[BaseModel | LLMError]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list, init=False)
    _queues: dict[Step, list[BaseModel | LLMError]] = field(init=False)

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
) -> Session:
    """Build one write-flow session over the test fixture (T10).

    `raw_writes` lets a test swap in a stub (R3's unverified write) instead
    of the real `FakeBankWrites`; either way the read side (`bank_tools`)
    shares one `FakeBankOverlay` with it, so a write this session made is
    visible to its own reads (D7), same as `make_fakebank_factory`.

    `write_audit=True` hands the session's `RecordingAudit` to `ConfirmedWriteTools`
    (default: `NullAuditRecorder`), so a test can read its `tool_result` rows;
    `sleep` replaces the retry backoff sleep.
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
