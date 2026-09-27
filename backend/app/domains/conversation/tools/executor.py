"""The one place R2 is enforced: `ConfirmedWriteTools` wraps `BankWriteTools`
with the confirmation store and the step-up gate.

See `docs/solution-docs/04-contracts.md` §1, §7, ADR-027 and
`docs/specs/d2-k-write-contracts.md` §"Contracts" -> `.../executor.py`, D3,
D5, D7. `config["configurable"]["bank_write_tools"]` holds an instance of
this class, never a raw `BankWriteTools` (D5): flows call `issue_plan`,
`cancel_plan` and `is_step_up_valid` alongside the four writes, all through
the one key the R6 test guards.

Each of the four writes runs, in order: (1) if `requires_step_up` says so and
the gate says no, raise `StepUpRequired` without consuming anything; (2)
`consume_step`, letting `ConfirmationRequired` propagate untouched; (3) the
raw call; (4) on any exception, cancel the plan and re-raise, and on a
returned but unverified `ActionResult`, cancel the plan and return the result
unchanged (ADR-027: "deleted on the first failed or unverified step"). Per
the human decision for this task, only `except Exception` cancels the plan;
an `asyncio.CancelledError` does not, and is deferred to D3-A3.

The idempotency key for a confirmed step is `<token_id>:<step_index>`
(`step_index` as returned by `consume_step`), documented here for D3-A3 to
implement (D13, `01` §7, `06` §4, `07` D3-A3). This card does not implement
it: a checkpoint replay of an already-consumed step is not handled.
"""

from collections.abc import Awaitable, Callable, Sequence

from app.core.actions import ActionResult
from app.core.errors import StepUpRequired
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.write import BankWriteTools
from app.domains.identity.step_up import StepUpGate
from app.domains.policy.confirmation import ConfirmationPlan, ConfirmationStore, PlanStep, ToolArgs

__all__ = ["ConfirmedWriteTools", "StepUpRule"]

StepUpRule = Callable[[str, ToolArgs], bool]
"""`(tool, args) -> needs step-up`, injected at construction (D7). This card
ships no default: the source of truth is `policies/tools.yaml` (D3-A1), so a
default here would put policy in code (R8).
"""


class ConfirmedWriteTools:
    """What `config["configurable"]["bank_write_tools"]` holds (D5)."""

    def __init__(
        self,
        raw: BankWriteTools,
        confirmations: ConfirmationStore,
        step_up: StepUpGate,
        requires_step_up: StepUpRule,
    ) -> None:
        self._raw = raw
        self._confirmations = confirmations
        self._step_up = step_up
        self._requires_step_up = requires_step_up

    async def issue_plan(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        return await self._confirmations.issue(steps)

    async def cancel_plan(self, token_id: str) -> None:
        await self._confirmations.cancel(token_id)

    async def is_step_up_valid(self) -> bool:
        return await self._step_up.is_step_up_valid()

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        # Read-only, no token: passes through with no rule, gate or store call.
        return await self._raw.get_block_origin(card_id)

    async def lock_card(self, card_id: str, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id}
        return await self._run(
            "cards.lock_card", args, token_id, lambda: self._raw.lock_card(card_id)
        )

    async def unlock_card(self, card_id: str, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id}
        return await self._run(
            "cards.unlock_card", args, token_id, lambda: self._raw.unlock_card(card_id)
        )

    async def block_card(self, card_id: str, reason: BlockReason, token_id: str) -> ActionResult:
        args: ToolArgs = {"card_id": card_id, "reason": reason}
        return await self._run(
            "cards.block_card", args, token_id, lambda: self._raw.block_card(card_id, reason)
        )

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, token_id: str
    ) -> ActionResult:
        args: ToolArgs = {"card_id": card_id, "address_ref": address_ref}
        return await self._run(
            "cards.order_replacement",
            args,
            token_id,
            lambda: self._raw.order_replacement(card_id, address_ref),
        )

    async def _run(
        self,
        tool: str,
        args: ToolArgs,
        token_id: str,
        call: Callable[[], Awaitable[ActionResult]],
    ) -> ActionResult:
        """D3's order, shared by the four writes above."""
        if self._requires_step_up(tool, args) and not await self._step_up.is_step_up_valid():
            raise StepUpRequired
        await self._confirmations.consume_step(token_id, tool, args)
        try:
            result = await call()
        except Exception:
            await self._confirmations.cancel(token_id)
            raise
        if not result.verified:
            await self._confirmations.cancel(token_id)
            return result
        return result
