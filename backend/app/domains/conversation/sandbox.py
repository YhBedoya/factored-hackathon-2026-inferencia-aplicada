"""Terminal sandbox for the v0 turn graph (D9, D19, B7).

    python -m app.domains.conversation.sandbox --customer <id> [--data-dir <path>]

Reads user turns from stdin, one per line, and for each one prints the
composed reply followed by one debug line (`07` §1):
`debug language=... status=... intents=[...] slots={...} route=... tools=[...]`.
`customer_id` comes only from `--customer` (the session, R1); no line typed at
the prompt is ever read as one. `trace_id`/`conversation_id` are bound once,
in `structlog.contextvars`, so every `llm.call` log line this session makes
carries them (R1's "no unmasked PII in logs" rule needs `request_id`/
`trace_id`/`conversation_id`, not the customer id, on every line).

`_RecordingBankTools` wraps the bound `FakeBank` so its public `.calls` list
of method names is what `run_turn`'s debug line reads back as `tools_called`
(T11's recording-proxy contract: any object with a `.calls` attribute works,
a plain `FakeBank` reports none called). It lives here, not next to
`FakeBank`, since nothing else needs it.

`build_sandbox_session` (T14) is the reusable session builder: it does the
same session-building work `_run_session` used to inline, so the CLI loop
below and `scripts/sandbox_ui.py`'s Streamlit page both go through the one
code path (same `ToolContext`, `_RecordingBankTools`, `build_graph`/
`MemorySaver`, `config` shape) instead of duplicating it.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.core.actions import ActionResult
from app.core.config import get_settings
from app.core.llm import LLMClient, get_llm_client
from app.core.pii import KnownPii
from app.domains.audit.schemas import NullAuditRecorder
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason, CardDetails, CardSummary
from app.domains.conversation.graph import (
    ConfirmationDecision,
    GraphState,
    TurnInput,
    TurnOutput,
    build_graph,
    run_turn,
)
from app.domains.conversation.masking import mask_user_text
from app.domains.conversation.templates import get_template
from app.domains.conversation.tools import BankReadTools, ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import make_fakebank_factory
from app.domains.conversation.tools.handoff import InMemoryHandoffTools
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.customers.schemas import CustomerProfile
from app.domains.disputes.schemas import PrioritySignals
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.localization.schemas import FxRate
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import step_up_rule, tool_allowed
from app.domains.safety.vault import InMemoryPiiVault, PiiVault
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView

__all__ = ["build_sandbox_session", "main"]

# `backend/app/domains/conversation/sandbox.py` -> repo root is four parents
# up (conversation, domains, app, backend), same count as `graph.py`'s
# `test_graph.py` sibling one level shallower than `flows/card_select.py`.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"


class _RecordingBankTools:
    """Records every `BankReadTools` method name called this turn (D9, `07` §1)."""

    def __init__(self, inner: BankReadTools) -> None:
        self._inner = inner
        self.calls: list[str] = []

    async def get_profile(self) -> CustomerProfile:
        self.calls.append("get_profile")
        return await self._inner.get_profile()

    async def list_cards(self) -> list[CardSummary]:
        self.calls.append("list_cards")
        return await self._inner.list_cards()

    async def get_card_details(self, card_id: str) -> CardDetails:
        self.calls.append("get_card_details")
        return await self._inner.get_card_details(card_id)

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        self.calls.append("search_transactions")
        return await self._inner.search_transactions(tx_filter)

    async def explain_decline(self, tx_id: str) -> DeclineExplanation:
        self.calls.append("explain_decline")
        return await self._inner.explain_decline(tx_id)

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        self.calls.append("get_fx_rate")
        return await self._inner.get_fx_rate(source, target)

    async def get_transactions_by_ids(self, tx_ids: list[str]) -> list[TxView]:
        self.calls.append("get_transactions_by_ids")
        return await self._inner.get_transactions_by_ids(tx_ids)

    async def get_priority_signals(self) -> PrioritySignals:
        self.calls.append("get_priority_signals")
        return await self._inner.get_priority_signals()

    async def get_pii_profile(self) -> KnownPii:
        # Not recorded: the masking step reads it, not an LLM node (D34).
        return await self._inner.get_pii_profile()


class _RecordingWriteTools:
    """Records every raw `BankWriteTools` method name this turn (T13), onto
    the *same* `.calls` list `_RecordingBankTools` fills: the debug line's
    `tools=[...]` already reads that one list off `bank_tools` (`run_turn`),
    so a write call shows up there too without `run_turn` itself changing.
    """

    def __init__(self, inner: BankWriteTools, calls: list[str]) -> None:
        self._inner = inner
        self._calls = calls

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        self._calls.append("get_block_origin")
        return await self._inner.get_block_origin(card_id)

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        self._calls.append("lock_card")
        return await self._inner.lock_card(card_id, idempotency_key=idempotency_key)

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        self._calls.append("unlock_card")
        return await self._inner.unlock_card(card_id, idempotency_key=idempotency_key)

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        self._calls.append("block_card")
        return await self._inner.block_card(card_id, reason, idempotency_key=idempotency_key)

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        self._calls.append("order_replacement")
        return await self._inner.order_replacement(
            card_id, address_ref, idempotency_key=idempotency_key
        )

    async def create_claim(
        self,
        tx_ids: list[str],
        answers: list[str],
        priority_flags: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        self._calls.append("create_claim")
        return await self._inner.create_claim(
            tx_ids, answers, priority_flags, idempotency_key=idempotency_key
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal sandbox for the v0 turn graph.")
    parser.add_argument("--customer", required=True, help="customer_id from the session (R1)")
    parser.add_argument("--data-dir", type=Path, default=_DEFAULT_DATA_DIR)
    return parser.parse_args(argv)


@dataclass
class _SandboxSession:
    """One sandbox session's built pieces (T13): the compiled graph, its
    per-turn `config`, the recording read tools (whose `.calls` list the
    write side shares too, D9's debug line) and the fake step-up gate the
    CLI's `/otp` command drives directly, outside the graph (D1)."""

    graph: CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput]
    config: RunnableConfig
    bank_tools: _RecordingBankTools
    gate: FakeStepUpGate
    vault: PiiVault


def _build_session(customer_id: str, data_dir: Path) -> _SandboxSession:
    """Build one sandbox session: the compiled graph, its per-turn `config`,
    the recording bank tools and the fake step-up gate (T13, T14). Shared by
    `_run_session` (the CLI loop below) and `scripts/sandbox_ui.py`'s
    Streamlit page (through `build_sandbox_session`), so both drive turns
    through the exact same session, not two copies of this wiring.

    A fresh call always starts a fresh conversation: new `trace_id`/
    `conversation_id`, a new `MemorySaver` (so no checkpoint from an earlier
    session leaks in), and a `thread_id` derived from that `conversation_id`.

    `bank_write_tools` (D2-K's `ConfirmedWriteTools`) wraps a
    `_RecordingWriteTools` sharing the read side's `bank_tools.calls` list
    (T13), over one `FakeBankWrites`/`FakeBank` pair from `make_fakebank_factory`
    so a write this session makes is visible to its own reads (D7), same as
    `tests/conftest.py`'s `make_session`. `policies/tools.yaml`'s step-up
    rule and `Settings.demo_otp_code` (never committed, R8/ADR-008) are the
    same sources every write-flow test loads.
    """
    trace_id = str(uuid4())
    conversation_id = uuid4()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, conversation_id=str(conversation_id))

    bundle = get_policies()
    session = ToolContext(
        customer_id=customer_id,
        conversation_id=conversation_id,
        actor="customer",
        policy_version=bundle.hash,
        trace_id=trace_id,
    )
    read_factory, write_factory = make_fakebank_factory(data_dir)
    bank_tools = _RecordingBankTools(read_factory(session))
    write_tools = _RecordingWriteTools(write_factory(session), bank_tools.calls)

    gate = FakeStepUpGate(get_settings().demo_otp_code)
    store = InMemoryConfirmationStore(customer_id, str(conversation_id))
    bank_write_tools = ConfirmedWriteTools(
        write_tools,
        store,
        gate,
        step_up_rule(bundle.tools),
        tool_allowed(bundle.tools),
        NullAuditRecorder(),
    )

    llm: LLMClient = get_llm_client()
    vault = InMemoryPiiVault()
    graph = build_graph(MemorySaver())
    config: RunnableConfig = {
        "configurable": {
            "thread_id": str(conversation_id),
            "session": session,
            "bank_tools": bank_tools,
            "bank_write_tools": bank_write_tools,
            "vault": vault,
            "llm": llm,
            "handoff_tools": InMemoryHandoffTools(),
            "audit": NullAuditRecorder(),
        }
    }
    return _SandboxSession(
        graph=graph, config=config, bank_tools=bank_tools, gate=gate, vault=vault
    )


def build_sandbox_session(
    customer_id: str, data_dir: Path
) -> tuple[
    CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput],
    RunnableConfig,
    _RecordingBankTools,
]:
    """The Streamlit page's entry point (T14): same session `_build_session`
    builds, minus the `gate` handle only the CLI's `/otp` command needs.
    Signature and 3-tuple return are unchanged (`scripts/sandbox_ui.py`
    depends on both).
    """
    session = _build_session(customer_id, data_dir)
    return session.graph, session.config, session.bank_tools


async def _run_session(customer_id: str, data_dir: Path) -> None:
    """Build the session, then drive one turn per stdin line (D9, D14, T13).

    `/confirm` and `/cancel` are the button-resume equivalents (D14): the
    token is read off the checkpointed `pending`'s owner,
    `confirmation_token_id`, never typed by the customer. `/otp <code>`
    drives the fake gate directly (D1), the same way the app's
    `POST /auth/otp/verify` would outside the graph: on a match it resumes
    the turn with `resume="step_up"`; on a mismatch nothing runs, and the
    `otp_required` template repeats so the customer knows to retry. Every
    other line is a fresh typed turn, with `confirmation`/`resume` passed
    explicitly as `None` (`04` §3, D2-K D17).
    """
    session = _build_session(customer_id, data_dir)
    graph, config, bank_tools, gate = (
        session.graph,
        session.config,
        session.bank_tools,
        session.gate,
    )

    for line in sys.stdin:
        text = line.rstrip("\n")
        if not text:
            continue
        bank_tools.calls.clear()

        if text in ("/confirm", "/cancel"):
            state = await graph.aget_state(config)
            token_id = state.values.get("confirmation_token_id") or ""
            decision: Literal["confirm", "cancel"] = "confirm" if text == "/confirm" else "cancel"
            confirmation = ConfirmationDecision(token_id=token_id, decision=decision)
            reply, debug = await run_turn(graph, "", config=config, confirmation=confirmation)
        elif text.startswith("/otp "):
            code = text.removeprefix("/otp ").strip()
            if not gate.verify(code):
                state = await graph.aget_state(config)
                language = state.values.get("language", "es")
                print(get_template("otp_required", language))
                continue
            reply, debug = await run_turn(graph, "", config=config, resume="step_up")
        else:
            # D4: mask the typed line before it becomes graph input; slash
            # commands above carry no customer text and are not masked.
            masked = await mask_user_text(text, bank_tools=bank_tools, vault=session.vault)
            reply, debug = await run_turn(
                graph, masked, config=config, confirmation=None, resume=None
            )

        print(await session.vault.unmask(reply))
        print(
            f"debug language={debug.language} status={debug.status} "
            f"intents={debug.intents} slots={debug.slots.model_dump(exclude_none=True)} "
            f"route={debug.route} tools={debug.tools_called} "
            f"pending={debug.pending} ui={debug.ui}"
        )
        if "conversation_closed" in debug.ui:
            # The customer said goodbye: the next line starts a new
            # conversation (new `conversation_id`/thread), like the app does.
            print("[conversation closed; the next message starts a new one]")
            session = _build_session(customer_id, data_dir)
            graph, config, bank_tools, gate = (
                session.graph,
                session.config,
                session.bank_tools,
                session.gate,
            )


def _force_utf8_streams() -> None:
    """Reconfigure stdin/stdout to UTF-8 (orchestrator repair round 1).

    Piped stdin/stdout otherwise default to the OS locale code page on
    Windows (cp1252), which mangles `¿cuál`, `cartão`, `••••` -- every
    accented or multi-byte character the ES/PT scripts and card masks use.
    Guarded with `hasattr` since a stream without `reconfigure` (e.g. a
    test's `io.StringIO`) should be left alone rather than crash.
    """
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: `python -m app.domains.conversation.sandbox`."""
    _force_utf8_streams()
    args = _parse_args(argv)
    asyncio.run(_run_session(args.customer, args.data_dir))


if __name__ == "__main__":
    main()
