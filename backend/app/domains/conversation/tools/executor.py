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

Each of the four writes runs D16's order: (1) `tool_call` audit, fail closed
-- a failed record means the write never runs, before `consume_step`,
surfaced as `ToolUnavailable`; (2) the step-up check: rule true and gate
false raises `StepUpRequired` without consuming anything, recording
`rule_hit` and `tool_result` best effort; (3) `consume_step`, recording
`confirmation_used` on success, or `tool_result` and re-raising untouched on
`ConfirmationRequired`; (4) the raw call, keyed `<token_id>:<step_index>`
(`step_index` as returned by `consume_step`, D11); (5) on a raised exception
or a returned but unverified `ActionResult`, `tool_result` (best effort) then
`cancel` the plan, exactly as before (ADR-027: "deleted on the first failed
or unverified step") -- on a verified result, `readback` (the read-back made
JSON-safe through `result.model_dump(mode="json")`, never raw) then
`tool_result`, whose id becomes `ActionResult.audit_event_id` (`model_copy`).
A recording failure past that point never turns a verified write into a
failure (D15, human decision for this card): it is logged
`audit.write_failed` (ids and event type only, no payload) and
`audit_event_id` stays `None`. Per the human decision for D2-K, only
`except Exception` cancels the plan; an `asyncio.CancelledError` does not,
and is deferred to D3-A3.
"""

from collections.abc import Awaitable, Callable, Sequence

import structlog
from pydantic import JsonValue

from app.core.actions import ActionResult
from app.core.errors import (
    AccessDenied,
    ConfirmationRequired,
    PolicyDenied,
    StepUpRequired,
    ToolUnavailable,
)
from app.domains.audit.schemas import AuditType, Recorder
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.schemas import Intent
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.identity.step_up import StepUpGate
from app.domains.policy.confirmation import (
    ConfirmationPlan,
    ConfirmationStore,
    PlanStep,
    ToolArgs,
    args_hash,
)

__all__ = ["ConfirmedWriteTools", "IntentAllowlist", "StepUpRule"]

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

_GET_BLOCK_ORIGIN_TOOL = "cards.get_block_origin"


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
    ) -> None:
        self._raw = raw
        self._confirmations = confirmations
        self._step_up = step_up
        self._requires_step_up = requires_step_up
        self._allowed = allowed
        self._audit = audit

    async def issue_plan(self, steps: Sequence[PlanStep], intent: Intent) -> ConfirmationPlan:
        for step in steps:
            if not self._allowed(intent, step.tool):
                await self._record(
                    "rule_hit",
                    {"rule_id": "tool_not_allowed", "tool": step.tool, "intent": intent},
                )
                raise PolicyDenied("tool_not_allowed")
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

    async def _run(
        self,
        tool: str,
        args: ToolArgs,
        token_id: str,
        call: Callable[[str], Awaitable[ActionResult]],
    ) -> ActionResult:
        """D16's order, shared by the four writes above."""
        await self._record_tool_call(
            {"tool": tool, "card_id": args.get("card_id"), "args_hash": args_hash(tool, args)}
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

        try:
            result = await call(f"{token_id}:{step_index}")
        except Exception as exc:
            await self._record("tool_result", {"tool": tool, "error": type(exc).__name__})
            await self._confirmations.cancel(token_id)
            raise

        if not result.verified:
            await self._record("tool_result", {"tool": tool, "verified": False})
            await self._confirmations.cancel(token_id)
            return result

        return await self._record_readback(tool, token_id, step_index, result)

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
