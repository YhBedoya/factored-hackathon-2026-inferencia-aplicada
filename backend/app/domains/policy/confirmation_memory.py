"""`InMemoryConfirmationStore`: the `ConfirmationStore` contract's plan
semantics without Redis (D18: this card ships the semantics only; `04` §7's
Redis/Lua storage is a later task).

Bound to one customer + conversation at construction (R1), same as the
`ConfirmationStore` Protocol it implements structurally (`06` §2: this
module imports only the stdlib and `policy.confirmation`, never
`app.domains.conversation`).
"""

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.errors import ConfirmationRequired
from app.domains.policy.confirmation import ConfirmationPlan, PlanStep, ToolArgs, args_hash

__all__ = ["InMemoryConfirmationStore"]

_TTL = timedelta(minutes=5)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class _StoredPlan:
    """One issued plan: its owner, its steps' hashes and where the cursor is."""

    customer_id: str
    conversation_id: str
    steps: list[PlanStep]
    step_hashes: list[str]
    cursor: int
    expires_at: datetime


class InMemoryConfirmationStore:
    """A `ConfirmationStore` backed by a plain dict.

    `plans` defaults to a private dict, but a test may pass one in so a
    second store, constructed with a different owner, sees the same plan
    (the `wrong_owner` case). `clock` defaults to real UTC now; tests inject
    one to move past a plan's TTL without sleeping.
    """

    def __init__(
        self,
        customer_id: str,
        conversation_id: str,
        *,
        clock: Callable[[], datetime] = _utcnow,
        plans: dict[str, _StoredPlan] | None = None,
    ) -> None:
        self._customer_id = customer_id
        self._conversation_id = conversation_id
        self._clock = clock
        self._plans: dict[str, _StoredPlan] = plans if plans is not None else {}

    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        token_id = secrets.token_urlsafe()
        expires_at = self._clock() + _TTL
        self._plans[token_id] = _StoredPlan(
            customer_id=self._customer_id,
            conversation_id=self._conversation_id,
            steps=list(steps),
            step_hashes=[args_hash(step.tool, step.args) for step in steps],
            cursor=0,
            expires_at=expires_at,
        )
        return ConfirmationPlan(token_id=token_id, steps=list(steps), expires_at=expires_at)

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        plan = self._plans.get(token_id)
        if plan is None or self._clock() >= plan.expires_at:
            self._plans.pop(token_id, None)
            raise ConfirmationRequired("unknown_or_expired")
        if plan.customer_id != self._customer_id or plan.conversation_id != self._conversation_id:
            raise ConfirmationRequired("wrong_owner")
        step = plan.steps[plan.cursor]
        if tool != step.tool or args_hash(tool, args) != plan.step_hashes[plan.cursor]:
            raise ConfirmationRequired("step_mismatch")

        step_index = plan.cursor
        plan.cursor += 1
        if plan.cursor >= len(plan.steps):
            del self._plans[token_id]
        return step_index

    async def cancel(self, token_id: str) -> None:
        self._plans.pop(token_id, None)
