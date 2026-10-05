"""The one place R2 is enforced: `ConfirmedWriteTools` wraps `BankWriteTools`
with the confirmation store, the step-up gate, the intent allowlist and the
audit trail.

See `docs/solution-docs/04-contracts.md` §1, §7, ADR-027 and
`docs/specs/d3-a-guardrails-write-path.md` §"Contracts" -> `.../executor.py`,
D3, D13-D16. `config["configurable"]["bank_write_tools"]` holds an instance of
this class, never a raw `BankWriteTools` (D2-K D5): flows call `issue_plan`,
`cancel_plan` and `is_step_up_valid` alongside the four writes, all through
the one key the R6 test guards.

`issue_plan` and `get_block_origin` both gate on `policies/tools.yaml`'s
`allowed_intents` before anything else runs (D3): a tool not allowed for the
given intent records `rule_hit {rule_id: "tool_not_allowed"}` (best effort)
and raises `PolicyDenied("tool_not_allowed")` before the store or the raw
call is ever touched.

Each of the five writes runs D16's order: (1) `tool_call` audit, fail closed
-- a failed record means the write never runs, before `consume_step`,
surfaced as `ToolUnavailable`; (2) the step-up check: rule true and gate
false raises `StepUpRequired` without consuming anything, recording
`rule_hit` and `tool_result` best effort; (3) `consume_step`, recording
`confirmation_used` on success, or `tool_result` and re-raising untouched on
`ConfirmationRequired`; (4) the raw call, keyed `<token_id>:<step_index>`
(`step_index` as returned by `consume_step`, D11) -- an `AccessDenied` here
(D4-B: `disputes.create_claim` on a foreign transaction, R1) additionally
records `access_denied` before the shared `tool_result`/`cancel` handling;
(5) on a raised exception or a returned but unverified `ActionResult`,
`tool_result` (best effort) then `cancel` the plan, exactly as before
(ADR-027: "deleted on the first failed or unverified step") -- on a verified
result, `readback` (the read-back made JSON-safe through
`result.model_dump(mode="json")`, never raw) then `tool_result`, whose id
becomes `ActionResult.audit_event_id` (`model_copy`). A recording failure
past that point never turns a verified write into a failure (D15, human
decision for this card): it is logged `audit.write_failed` (ids and event
type only, no payload) and `audit_event_id` stays `None`. Per the human
decision for D2-K, only `except Exception` cancels the plan; an
`asyncio.CancelledError` does not, and is deferred to D3-A3.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, cast

import structlog
from pydantic import JsonValue

from app.core.actions import ActionResult
from app.core.config import get_settings
from app.core.errors import (
    AccessDenied,
    ConfirmationRequired,
    PolicyDenied,
    StepUpRequired,
    ToolUnavailable,
)
from app.core.faults import fault_active
from app.core.retry import backoff_delay
from app.domains.audit.schemas import AuditType, Recorder
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.schemas import Intent
from app.domains.conversation.tools.write import BankWriteTools, PendingCardRequests
from app.domains.identity.step_up import StepUpGate
from app.domains.policy.confirmation import (
    ConfirmationPlan,
    ConfirmationStore,
    PlanStep,
    ToolArgs,
    args_hash,
)

__all__ = [
    "ConfirmedWriteTools",
    "HasPreconditions",
    "IntentAllowlist",
    "StepUpRule",
    "call_with_timeout",
]

_logger = structlog.get_logger()

StepUpRule = Callable[[str, ToolArgs], bool]
"""`(tool, args) -> needs step-up`, injected at construction (D7). This card
ships no default: the source of truth is `policies/tools.yaml` (D3-A1), so a
default here would put policy in code (R8).
"""

IntentAllowlist = Callable[[str, str], bool]
"""`(intent, tool) -> allowed`, built by `policy.tools_policy.tool_allowed`
from `policies/tools.yaml` (D3). No default, for the same reason as
`StepUpRule`.
"""

HasPreconditions = Callable[[str], bool]
"""`(tool) -> has a preconditions block`, built by
`policy.tools_policy.has_preconditions`. It gates `issue_plan(intent=None)`
(D10): the agent path has no intent, so a tool is allowed only if the policy
file states its preconditions.
"""

_GET_BLOCK_ORIGIN_TOOL = "cards.get_block_origin"
_PENDING_CARD_REQUESTS_TOOL = "cards.pending_card_requests"

# The writes `cards_write_error` fails (D6): every `cards.*` write, not claims.
_CARDS_WRITES = frozenset(
    {
        "cards.lock_card",
        "cards.unlock_card",
        "cards.block_card",
        "cards.order_replacement",
        "cards.request_card",
        "cards.request_closure",
    }
)


async def call_with_timeout[T](call: Callable[[], Awaitable[T]], timeout_s: float | None) -> T:
    """Run one tool attempt under the per-attempt timeout (D4). A timeout
    surfaces as `ToolUnavailable("timeout")`, so it takes the retry path.
    `timeout_s=None` reads `Settings.tool_timeout_s` at call time.
    """
    limit = get_settings().tool_timeout_s if timeout_s is None else timeout_s
    try:
        async with asyncio.timeout(limit):
            return await call()
    except TimeoutError as exc:
        raise ToolUnavailable("timeout") from exc


class ConfirmedWriteTools:
    """What `config["configurable"]["bank_write_tools"]` holds (D2-K D5)."""

    def __init__(
        self,
        raw: BankWriteTools,
        confirmations: ConfirmationStore,
        step_up: StepUpGate,
        requires_step_up: StepUpRule,
        allowed: IntentAllowlist,
        audit: Recorder,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_s: float | None = None,
        has_preconditions: HasPreconditions | None = None,
    ) -> None:
        self._sleep = sleep
        self._timeout_s = timeout_s
        self._raw = raw
        self._confirmations = confirmations
        self._step_up = step_up
        self._requires_step_up = requires_step_up
        self._allowed = allowed
        self._audit = audit
        self._has_preconditions = has_preconditions

    async def issue_plan(
        self, steps: Sequence[PlanStep], intent: Intent | None
    ) -> ConfirmationPlan:
        for step in steps:
            if intent is None:
                # Agent path (D10): no intent to allowlist, so the tool must carry
                # preconditions; a missing lookup denies, never allows.
                permitted = self._has_preconditions is not None and self._has_preconditions(
                    step.tool
                )
            else:
                permitted = self._allowed(intent, step.tool)
            if not permitted:
                await self._record(
                    "rule_hit",
                    {"rule_id": "tool_not_allowed", "tool": step.tool, "intent": intent},
                )
                raise PolicyDenied("tool_not_allowed")
        if intent is None:
            # Agent path: no flow gates step-up before the card, so refuse at issue
            # time rather than after the user confirmed (the `_run` check stays).
            for step in steps:
                if self._requires_step_up(step.tool, step.args) and not (
                    await self._step_up.is_step_up_valid()
                ):
                    await self._record(
                        "rule_hit", {"rule_id": "step_up_required", "tool": step.tool}
                    )
                    raise StepUpRequired
        plan = await self._confirmations.issue(steps)
        await self._record(
            "confirmation_issued",
            {"tools": [step.tool for step in steps], "step_count": len(steps)},
        )
        return plan

    async def cancel_plan(self, token_id: str) -> None:
        await self._confirmations.cancel(token_id)

    async def is_step_up_valid(self) -> bool:
        return await self._step_up.is_step_up_valid()

    async def get_block_origin(self, card_id: str, intent: Intent) -> BlockOrigin:
        tool = _GET_BLOCK_ORIGIN_TOOL
        if not self._allowed(intent, tool):
            await self._record(
                "rule_hit", {"rule_id": "tool_not_allowed", "tool": tool, "intent": intent}
            )
            raise PolicyDenied("tool_not_allowed")

        await self._record_tool_call({"tool": tool, "card_id": card_id})

        try:
            origin = await self._raw.get_block_origin(card_id)
        except AccessDenied:
            await self._record("access_denied", {"tool": tool, "card_id": card_id})
            await self._record("tool_result", {"tool": tool, "error": "AccessDenied"})
            raise

        await self._record(
            "tool_result", {"tool": tool, "kind": origin.kind, "reason": origin.reason}
        )
        return origin

    async def lock_card(self, card_id: str, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id}
        return await self._run(
            "cards.lock_card",
            args,
            token_id,
            lambda key: self._raw.lock_card(card_id, idempotency_key=key),
        )

    async def unlock_card(self, card_id: str, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id}
        return await self._run(
            "cards.unlock_card",
            args,
            token_id,
            lambda key: self._raw.unlock_card(card_id, idempotency_key=key),
        )

    async def block_card(self, card_id: str, reason: BlockReason, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id, "reason": reason}
        return await self._run(
            "cards.block_card",
            args,
            token_id,
            lambda key: self._raw.block_card(card_id, reason, idempotency_key=key),
        )

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, token_id: str
    ) -> ActionResult:
        args: ToolArgs = {"card_id": card_id, "address_ref": address_ref}
        return await self._run(
            "cards.order_replacement",
            args,
            token_id,
            lambda key: self._raw.order_replacement(card_id, address_ref, idempotency_key=key),
        )

    async def create_claim(
        self, tx_ids: list[str], answers: list[str], priority_flags: list[str], token_id: str
    ) -> ActionResult:
        args: ToolArgs = {"tx_ids": tx_ids, "answers": answers, "priority_flags": priority_flags}
        return await self._run(
            "disputes.create_claim",
            args,
            token_id,
            lambda key: self._raw.create_claim(
                tx_ids, answers, priority_flags, idempotency_key=key
            ),
        )

    async def request_card(
        self, kind: Literal["credit", "debit"], changed_fields: list[str], token_id: str
    ) -> ActionResult:
        args: ToolArgs = {"kind": kind, "changed_fields": changed_fields}
        return await self._run(
            "cards.request_card",
            args,
            token_id,
            lambda key: self._raw.request_card(kind, changed_fields, idempotency_key=key),
        )

    async def request_closure(self, card_id: str, reason: str, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id, "reason": reason}
        return await self._run(
            "cards.request_closure",
            args,
            token_id,
            lambda key: self._raw.request_closure(card_id, reason, idempotency_key=key),
        )

    async def pending_card_requests(self) -> PendingCardRequests:
        """An audited read like `get_block_origin`, without the allowlist
        check: the agent path has no intent, and the read changes nothing."""
        tool = _PENDING_CARD_REQUESTS_TOOL
        await self._record_tool_call({"tool": tool})
        pending = await self._raw.pending_card_requests()
        await self._record(
            "tool_result",
            {
                "tool": tool,
                "open_pending": pending.open_pending,
                "close_count": len(pending.close_card_ids),
            },
        )
        return pending

    async def _run(
        self,
        tool: str,
        args: ToolArgs,
        token_id: str,
        call: Callable[[str], Awaitable[ActionResult]],
    ) -> ActionResult:
        """D16's order, shared by the five writes above."""
        await self._record_tool_call(
            {
                "tool": tool,
                # `args.get("card_id")` is `ToolArg | None` (D4-B's `list[str]`
                # widening, D17): every payload value here is already a valid
                # `JsonValue`, but mypy's invariant `list[JsonValue]` can't see
                # a `list[str]` argument as one without this cast.
                "card_id": cast(JsonValue, args.get("card_id")),
                "args_hash": args_hash(tool, args),
            }
        )

        if self._requires_step_up(tool, args) and not await self._step_up.is_step_up_valid():
            await self._record("rule_hit", {"rule_id": "step_up_required", "tool": tool})
            await self._record("tool_result", {"tool": tool, "error": "StepUpRequired"})
            raise StepUpRequired

        try:
            step_index = await self._confirmations.consume_step(token_id, tool, args)
        except ConfirmationRequired as exc:
            await self._record("tool_result", {"tool": tool, "error": type(exc).__name__})
            raise
        await self._record("confirmation_used", {"tool": tool, "step_index": step_index})

        # D5: retries reuse the one key and the one consumed step (R2). Only
        # `ToolUnavailable` (timeout included) is retried; every other error,
        # and an unverified result (D7), takes the single-shot path.
        key = f"{token_id}:{step_index}"
        max_attempts = get_settings().retry_max + 1
        attempt = 0
        while True:
            attempt += 1
            try:
                result = await call_with_timeout(
                    lambda: self._attempt(tool, key, call), self._timeout_s
                )
                break
            except AccessDenied:
                # D4-B: a `create_claim` tx id that isn't the customer's own
                # (R1) -- audited the same way `get_block_origin`'s does, then
                # falls into the same cancel-and-reraise path below.
                await self._record("access_denied", {"tool": tool})
                await self._record(
                    "tool_result", {"tool": tool, "error": "AccessDenied", "attempt": attempt}
                )
                await self._confirmations.cancel(token_id)
                raise
            except Exception as exc:
                await self._record(
                    "tool_result", {"tool": tool, "error": type(exc).__name__, "attempt": attempt}
                )
                if isinstance(exc, ToolUnavailable) and attempt < max_attempts:
                    await self._sleep(backoff_delay(attempt))
                    continue
                await self._confirmations.cancel(token_id)
                raise

        if not result.verified:
            await self._record("tool_result", {"tool": tool, "verified": False})
            await self._confirmations.cancel(token_id)
            return result

        return await self._record_readback(tool, token_id, step_index, result)

    async def _attempt(
        self, tool: str, key: str, call: Callable[[str], Awaitable[ActionResult]]
    ) -> ActionResult:
        """One raw attempt, with the D6 faults applied here so `BANK=fake` and
        `BANK=postgres` behave the same."""
        if tool in _CARDS_WRITES and fault_active("cards_write_error"):
            raise ToolUnavailable("fault:cards_write_error")
        result = await call(key)
        if fault_active("readback_mismatch"):
            return result.model_copy(update={"verified": False})
        return result

    async def _record_readback(
        self, tool: str, token_id: str, step_index: int, result: ActionResult
    ) -> ActionResult:
        """Step 5 past the raw write: a recording failure here never turns a
        verified write into a failure (D15, human decision) -- it is logged
        and the returned result keeps `audit_event_id=None`.
        """
        try:
            readback_id = await self._audit.record(
                "readback",
                {
                    "tool": tool,
                    "verified": result.verified,
                    "readback": result.model_dump(mode="json")["readback"],
                },
            )
            await self._audit.record("tool_result", {"tool": tool, "verified": result.verified})
        except Exception:
            _logger.warning(
                "audit.write_failed",
                tool=tool,
                token_id=token_id,
                step_index=step_index,
                type="readback",
            )
            return result
        return result.model_copy(update={"audit_event_id": readback_id})

    async def _record_tool_call(self, payload: dict[str, JsonValue]) -> None:
        """Fail closed (D15): a `tool_call` that can't be recorded means the
        raw call never runs."""
        try:
            await self._audit.record("tool_call", payload)
        except Exception as exc:
            raise ToolUnavailable("audit_unavailable") from exc

    async def _record(self, event_type: AuditType, payload: dict[str, JsonValue]) -> None:
        """Best effort: every other audit event's recording failure is
        swallowed, never surfaced to the caller."""
        try:
            await self._audit.record(event_type, payload)
        except Exception:
            pass
