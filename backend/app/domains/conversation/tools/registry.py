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

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue

from app.core.config import get_settings
from app.core.errors import AccessDenied, ToolUnavailable
from app.core.pii import KnownPii
from app.core.retry import backoff_delay
from app.domains.audit.schemas import AuditType, Recorder
from app.domains.audit.service import AuditRecorder
from app.domains.cards.schemas import CardDetails, CardSummary
from app.domains.conversation.tools.bank import BankReadTools
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools, call_with_timeout
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
from app.domains.transactions.schemas import DeclineExplanation, TxFilter, TxView

__all__ = [
    "RecordingBankTools",
    "audit_recorder_for",
    "build_tool_context",
    "known_pii",
    "turn_tools",
]

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
    Only a customer session with a `customer_id` gets a context (D15): a
    staff session raises `PermissionError`.
    """
    if session.role != "customer" or session.customer_id is None:
        raise PermissionError("R1: a tool context needs a customer session with a customer_id")
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

    def __init__(
        self,
        inner: BankReadTools,
        audit: Recorder,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_s: float | None = None,
    ) -> None:
        self._inner = inner
        self._audit = audit
        self._sleep = sleep
        self._timeout_s = timeout_s
        self.calls: list[str] = []

    async def get_profile(self) -> CustomerProfile:
        self.calls.append("get_profile")
        return await self._read("customers.get_profile", {}, self._inner.get_profile)

    async def list_cards(self) -> list[CardSummary]:
        self.calls.append("list_cards")
        return await self._read(
            "cards.list_cards", {}, self._inner.list_cards, lambda r: {"count": len(r)}
        )

    async def get_card_details(self, card_id: str) -> CardDetails:
        self.calls.append("get_card_details")
        return await self._read(
            "cards.get_card_details",
            {"card_id": card_id},
            lambda: self._inner.get_card_details(card_id),
        )

    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]:
        self.calls.append("search_transactions")
        ident: dict[str, JsonValue] = {}
        if tx_filter.card_id is not None:
            ident["card_id"] = tx_filter.card_id
        return await self._read(
            "transactions.search",
            ident,
            lambda: self._inner.search_transactions(tx_filter),
            lambda r: {"count": len(r)},
            ok_ident=False,
        )

    async def explain_decline(self, tx_id: str) -> DeclineExplanation:
        self.calls.append("explain_decline")
        return await self._read(
            "transactions.explain_decline",
            {"tx_id": tx_id},
            lambda: self._inner.explain_decline(tx_id),
            deny_event=False,
        )

    async def get_fx_rate(self, source: str, target: str) -> FxRate:
        self.calls.append("get_fx_rate")
        return await self._read(
            "reference.get_fx_rate", {}, lambda: self._inner.get_fx_rate(source, target)
        )

    async def _read[T](
        self,
        tool: str,
        ident: dict[str, JsonValue],
        call: Callable[[], Awaitable[T]],
        summary: Callable[[T], dict[str, JsonValue]] | None = None,
        *,
        deny_event: bool = True,
        ok_ident: bool = True,
    ) -> T:
        """One audited read: `tool_call` once (fail closed, D15), then the
        inner call under the per-attempt timeout, retrying `ToolUnavailable`
        (D5). Each failed attempt records `tool_result {error, attempt}`.
        `ident` is the `card_id`/`tx_id` the events carry; `ok_ident` keeps
        the success `tool_result` as it was before (search never carried it).
        """
        try:
            await self._audit.record("tool_call", {"tool": tool, **ident})
        except Exception as exc:
            raise ToolUnavailable("audit_unavailable") from exc
        max_attempts = get_settings().retry_max + 1
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await call_with_timeout(call, self._timeout_s)
                break
            except Exception as exc:
                if isinstance(exc, AccessDenied) and deny_event:
                    await self._record("access_denied", {"tool": tool, **ident})
                await self._record(
                    "tool_result",
                    {"tool": tool, **ident, "error": type(exc).__name__, "attempt": attempt},
                )
                if isinstance(exc, ToolUnavailable) and attempt < max_attempts:
                    await self._sleep(backoff_delay(attempt))
                    continue
                raise
        ok: dict[str, JsonValue] = {"tool": tool, **(ident if ok_ident else {})}
        if summary is not None:
            ok.update(summary(result))
        await self._record("tool_result", ok)
        return result

    async def get_pii_profile(self) -> KnownPii:
        # Pass-through (A5, D34): the runner's masking step, not an LLM-driven
        # read, so no `tool_call` audit event and no `.calls` entry.
        return await self._inner.get_pii_profile()

    async def _record(self, event_type: AuditType, payload: dict[str, JsonValue]) -> None:
        """Best effort past the `tool_call` gate: never turns a read that
        already ran into a failure over an audit-log hiccup."""
        try:
            await self._audit.record(event_type, payload)
        except Exception:
            pass


def _bank_reads(ctx: ToolContext) -> BankReadTools:
    if get_settings().bank == "fake":
        read_factory, _ = make_fakebank_factory(_DATA_DIR)
        return read_factory(ctx)
    return PostgresBank(ctx)


async def known_pii(ctx: ToolContext) -> KnownPii:
    """The session customer's document number and names, for the runner's
    masking step (D3, D4). Built from `ctx` (R1), never audited, and not
    reachable from any LLM node."""
    return await _bank_reads(ctx).get_pii_profile()


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
