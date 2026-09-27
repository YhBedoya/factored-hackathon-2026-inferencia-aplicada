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
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.core.llm import LLMClient, get_llm_client
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.graph import GraphState, TurnInput, TurnOutput, build_graph, run_turn
from app.domains.conversation.tools import BankReadTools, ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.customers.schemas import CustomerProfile
from app.domains.transactions.schemas import TxFilter, TxView

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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal sandbox for the v0 turn graph.")
    parser.add_argument("--customer", required=True, help="customer_id from the session (R1)")
    parser.add_argument("--data-dir", type=Path, default=_DEFAULT_DATA_DIR)
    return parser.parse_args(argv)


def build_sandbox_session(
    customer_id: str, data_dir: Path
) -> tuple[
    CompiledStateGraph[GraphState, Any, TurnInput, TurnOutput],
    RunnableConfig,
    _RecordingBankTools,
]:
    """Build one sandbox session: the compiled graph, its per-turn `config`
    and the recording bank tools (T14). Shared by `_run_session` (the CLI
    loop below) and `scripts/sandbox_ui.py`'s Streamlit page, so both drive
    turns through the exact same session, not two copies of this wiring.

    A fresh call always starts a fresh conversation: new `trace_id`/
    `conversation_id`, a new `MemorySaver` (so no checkpoint from an earlier
    session leaks in), and a `thread_id` derived from that `conversation_id`.
    """
    trace_id = str(uuid4())
    conversation_id = uuid4()
    structlog.contextvars.bind_contextvars(trace_id=trace_id, conversation_id=str(conversation_id))

    session = ToolContext(
        customer_id=customer_id,
        conversation_id=conversation_id,
        actor="customer",
        policy_version="unversioned",
        trace_id=trace_id,
    )
    bank_tools = _RecordingBankTools(FakeBank(session, data_dir))
    llm: LLMClient = get_llm_client()
    graph = build_graph(MemorySaver())
    config: RunnableConfig = {
        "configurable": {
            "thread_id": str(conversation_id),
            "session": session,
            "bank_tools": bank_tools,
            "llm": llm,
        }
    }
    return graph, config, bank_tools


async def _run_session(customer_id: str, data_dir: Path) -> None:
    """Build the session, then drive one turn per stdin line (D9)."""
    graph, config, bank_tools = build_sandbox_session(customer_id, data_dir)

    for line in sys.stdin:
        text = line.rstrip("\n")
        if not text:
            continue
        bank_tools.calls.clear()
        reply, debug = await run_turn(graph, text, config=config)
        print(reply)
        print(
            f"debug language={debug.language} status={debug.status} "
            f"intents={debug.intents} slots={debug.slots.model_dump(exclude_none=True)} "
            f"route={debug.route} tools={debug.tools_called}"
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
