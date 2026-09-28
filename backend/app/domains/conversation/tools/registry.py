"""Tool registry v0: `ToolContext` construction and the read tools bound to it
(D10).

This is the one place on the API path that builds a `ToolContext`: R1's rule
that `customer_id` comes only from the session is enforced right here, by
always reading it off `session.customer_id` -- no route, tool or prompt ever
takes it as an argument. `build_tool_context` binds `actor="customer"` and
`policy_version="unversioned"` until D3-A1 adds the allowlist and a real
policy version.

No `ToolSpec`, allowlist or write tools yet (D10) -- `bank_tools_for` only
ever returns the five `BankReadTools` methods, wrapped for turn-debug
recording.
"""

from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.conversation.tools.postgres import PostgresBank
from app.domains.customers.schemas import CustomerProfile
from app.domains.identity.models import Session
from app.domains.localization.schemas import FxRate
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["RecordingBankTools", "bank_tools_for", "build_tool_context"]

# `backend/app/domains/conversation/tools/registry.py` -> repo root is five
# parents up (tools, conversation, domains, app, backend), one level deeper
# than `conversation/sandbox.py`'s own four.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DATA_DIR = _REPO_ROOT / "data"


def build_tool_context(session: Session, conversation_id: UUID, trace_id: str) -> ToolContext:
    """Build the turn's `ToolContext` from the route's `Session` (R1, D10).
    Nothing else on the API path constructs a `ToolContext`: `customer_id`
    always comes from `session.customer_id`, never from a route argument, a
    tool call or anything the LLM produced.
    """
    return ToolContext(
        customer_id=session.customer_id,
        conversation_id=conversation_id,
        actor="customer",
        policy_version="unversioned",
        trace_id=trace_id,
    )


class RecordingBankTools:
    """Records every `BankReadTools` method name called this turn.

    Same recording-proxy contract as `conversation/sandbox.py`'s
    `_RecordingBankTools` (T11: any object with a public `.calls` attribute
    works as `run_turn`'s `tools_called` debug field) -- mirrored here, not
    imported from the sandbox module, since the sandbox is a separate dev/demo
    entry point and this is the one the API hosts turns from.
    """

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

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        self.calls.append("get_fx_rate")
        return await self._inner.get_fx_rate(source, target)


def bank_tools_for(ctx: ToolContext) -> RecordingBankTools:
    """The read tools for one `ToolContext`, wrapped for turn-debug recording
    (D10). `BANK=fake` points `FakeBank` at the repo's `data/` directory (the
    same default `conversation/sandbox.py` uses); `BANK=postgres`, the
    default, calls the bank `service` modules instead (D11).
    """
    inner: BankReadTools
    if get_settings().bank == "fake":
        inner = FakeBank(ctx, _DATA_DIR)
    else:
        inner = PostgresBank(ctx)
    return RecordingBankTools(inner)
