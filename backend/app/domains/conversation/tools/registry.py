"""Tool registry: `ToolContext` construction, the audited read tools and the
confirmed write tools a turn runs against (D2, D10, D13, D17).

This is the one place on the API path that builds a `ToolContext`: R1's rule
that `customer_id` comes only from the session is enforced right here, by
always reading it off `session.customer_id` -- no route, tool or prompt ever
takes it as an argument. `build_tool_context` binds `actor="customer"` and
`policy_version` to the combined `PolicyBundle.hash` (D2) -- every audit
event this turn writes carries that same value.

`audit_recorder_for` builds the one `AuditRecorder` a turn's tools and the
runner share, bound to `(conversation_id, turn_id, trace_id, policy_version,
actor="bot")` (D13: every event in a customer turn is attributed to the bot,
the one actually calling tools and composing the reply). `turn_tools` then
wraps the read side in `RecordingBankTools` (records the D14 `tool_call`/
`tool_result` pair for every read, plus `access_denied`) and the write side
in `ConfirmedWriteTools` (D16's order), both bound to that one recorder.
`BANK=fake` points both sides at the same `FakeBankOverlay` (D7, via
`make_fakebank_factory`) so a write is visible to this turn's own reads;
`BANK=postgres`, the default, calls the bank `service` modules instead
(`PostgresBank` + `PostgresBankWrites`, D10, D11).
"""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue

from app.core.config import get_settings
from app.core.errors import AccessDenied, ToolUnavailable
from app.domains.audit.schemas import AuditType, Recorder
from app.domains.audit.service import AuditRecorder
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import make_fakebank_factory
from app.domains.conversation.tools.postgres import PostgresBank
from app.domains.conversation.tools.postgres_writes import PostgresBankWrites
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.customers.schemas import CustomerProfile
from app.domains.identity.models import Session
from app.domains.identity.step_up_session import SessionStepUpGate
from app.domains.localization.schemas import FxRate
from app.domains.policy.confirmation_redis import RedisConfirmationStore
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import step_up_rule, tool_allowed
from app.domains.transactions.schemas import TxFilter, TxView

__all__ = ["RecordingBankTools", "audit_recorder_for", "build_tool_context", "turn_tools"]

# `backend/app/domains/conversation/tools/registry.py` -> repo root is five
# parents up (tools, conversation, domains, app, backend), one level deeper
# than `conversation/sandbox.py`'s own four.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DATA_DIR = _REPO_ROOT / "data"


def build_tool_context(session: Session, conversation_id: UUID, trace_id: str) -> ToolContext:
    """Build the turn's `ToolContext` from the route's `Session` (R1, D10).
    Nothing else on the API path constructs a `ToolContext`: `customer_id`
    always comes from `session.customer_id`, never from a route argument, a
    tool call or anything the LLM produced. `policy_version` is the combined
    policy hash (D2), so it reaches every audit event this turn writes.
    """
    return ToolContext(
        customer_id=session.customer_id,
        conversation_id=conversation_id,
        actor="customer",
        policy_version=get_policies().hash,
        trace_id=trace_id,
    )


def audit_recorder_for(ctx: ToolContext, turn_id: UUID) -> AuditRecorder:
    """The one `AuditRecorder` this turn's tools and the runner share (D13),
    bound to `ctx`'s `conversation_id`/`trace_id`/`policy_version`, this
    turn's `turn_id`, and `actor="bot"` (human decision, this card: a
    customer turn's events are attributed to the assistant calling the
    tools, not the customer directly).
    """
    return AuditRecorder(
        conversation_id=ctx.conversation_id,
        turn_id=turn_id,
        trace_id=ctx.trace_id,
        policy_version=ctx.policy_version,
        actor="bot",
    )


class RecordingBankTools:
    """Records every `BankReadTools` method name called this turn, and audits
    each one as a `tool_call`/`tool_result` pair, plus `access_denied` on a
    foreign card (D14).

    `.calls` is the same debug-line contract `run_turn`'s `tools_called`
    field reads off `bank_tools` (any object with a public `.calls` list of
    method names works): appended before the audited call runs, so a call
    that raises `ToolUnavailable` before the read (a failed `tool_call`
    audit, D15) still shows up in the debug trail.
    """

    def __init__(self, inner: BankReadTools, audit: Recorder) -> None:
        self._inner = inner
        self._audit = audit
        self.calls: list[str] = []

    async def get_profile(self) -> CustomerProfile:
        self.calls.append("get_profile")
        tool = "customers.get_profile"
        await self._record_tool_call(tool, None)
        try:
            result = await self._inner.get_profile()
        except Exception as exc:
            await self._record_error(tool, None, exc)
            raise
        await self._record("tool_result", {"tool": tool})
        return result

    async def list_cards(self) -> list[CardSummary]:
        self.calls.append("list_cards")
        tool = "cards.list_cards"
        await self._record_tool_call(tool, None)
        try:
            result = await self._inner.list_cards()
        except Exception as exc:
            await self._record_error(tool, None, exc)
            raise
        await self._record("tool_result", {"tool": tool, "count": len(result)})
        return result

    async def get_card_details(self, card_id: str) -> CardDetails:
        self.calls.append("get_card_details")
        tool = "cards.get_card_details"
        await self._record_tool_call(tool, card_id)
        try:
            result = await self._inner.get_card_details(card_id)
        except Exception as exc:
            await self._record_error(tool, card_id, exc)
            raise
        await self._record("tool_result", {"tool": tool, "card_id": card_id})
        return result

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        self.calls.append("search_transactions")
        tool = "transactions.search"
        await self._record_tool_call(tool, tx_filter.card_id)
        try:
            result = await self._inner.search_transactions(tx_filter)
        except Exception as exc:
            await self._record_error(tool, tx_filter.card_id, exc)
            raise
        await self._record("tool_result", {"tool": tool, "count": len(result)})
        return result

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        self.calls.append("get_fx_rate")
        tool = "reference.get_fx_rate"
        await self._record_tool_call(tool, None)
        try:
            result = await self._inner.get_fx_rate(source, target)
        except Exception as exc:
            await self._record_error(tool, None, exc)
            raise
        await self._record("tool_result", {"tool": tool})
        return result

    async def _record_tool_call(self, tool: str, card_id: str | None) -> None:
        """Fail closed (D15): a `tool_call` that can't be recorded means the
        read never runs."""
        payload: dict[str, JsonValue] = {"tool": tool}
        if card_id is not None:
            payload["card_id"] = card_id
        try:
            await self._audit.record("tool_call", payload)
        except Exception as exc:
            raise ToolUnavailable("audit_unavailable") from exc

    async def _record_error(self, tool: str, card_id: str | None, exc: Exception) -> None:
        if isinstance(exc, AccessDenied):
            payload: dict[str, JsonValue] = {"tool": tool}
            if card_id is not None:
                payload["card_id"] = card_id
            await self._record("access_denied", payload)
        await self._record("tool_result", {"tool": tool, "error": type(exc).__name__})

    async def _record(self, event_type: AuditType, payload: dict[str, JsonValue]) -> None:
        """Best effort past the `tool_call` gate: never turns a read that
        already ran into a failure over an audit-log hiccup."""
        try:
            await self._audit.record(event_type, payload)
        except Exception:
            pass


def turn_tools(
    ctx: ToolContext, session: Session, audit: Recorder
) -> tuple[RecordingBankTools, ConfirmedWriteTools]:
    """The read and write tools for one turn, both bound to the same `audit`
    recorder (D13, D17). `BANK=fake` shares one `FakeBankOverlay` between the
    read and write side (D7); `BANK=postgres`, the default, calls the bank
    `service` modules through `PostgresBank`/`PostgresBankWrites` (D10, D11).
    """
    read_inner: BankReadTools
    raw_writes: BankWriteTools
    if get_settings().bank == "fake":
        read_factory, write_factory = make_fakebank_factory(_DATA_DIR)
        read_inner = read_factory(ctx)
        raw_writes = write_factory(ctx)
    else:
        read_inner = PostgresBank(ctx)
        raw_writes = PostgresBankWrites(ctx)

    bundle = get_policies()
    write_tools = ConfirmedWriteTools(
        raw_writes,
        RedisConfirmationStore(ctx.customer_id, str(ctx.conversation_id)),
        SessionStepUpGate(
            session.step_up_at, timedelta(minutes=bundle.tools.step_up_window_minutes)
        ),
        step_up_rule(bundle.tools),
        tool_allowed(bundle.tools),
        audit,
    )
    return RecordingBankTools(read_inner, audit), write_tools
