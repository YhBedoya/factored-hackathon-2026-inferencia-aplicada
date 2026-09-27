"""The plan-token confirmation contract every confirmed write goes through.

See `docs/solution-docs/04-contracts.md` §7, ADR-027, D1, D2 and R2. A single
confirmation token is a plan of one or more steps: the customer confirms the
whole plan once, and each step is consumed in order as the executor
(`conversation/tools/executor.py`) runs it. This module imports only the
stdlib, pydantic and `app.core.errors`: it must never import
`app.domains.conversation`, or the executor's eager import of this package
would create a cycle (`06` §2).
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ConfirmationPlan",
    "ConfirmationStore",
    "PlanStep",
    "ToolArg",
    "ToolArgs",
    "args_hash",
]

ToolArg = str | int | bool | None
"""One value of a `PlanStep.args` entry. Never a PII-vault token's raw value (R5)."""

ToolArgs = Mapping[str, ToolArg]
"""The keyword args of a raw write call, exactly as `args_hash` and `consume_step` see them."""


def args_hash(tool: str, args: ToolArgs) -> str:
    """The hex SHA-256 that binds a confirmed step to its tool and args (D2).

    Canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`)
    of `{"tool": tool, "args": args}`, so key order never changes the hash and any
    changed arg value does.
    """
    payload = json.dumps(
        {"tool": tool, "args": dict(args)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PlanStep(BaseModel):
    """One step of a `ConfirmationPlan`: the raw call the executor will run.

    `args` is exactly the raw call's keyword args (never a token, never
    `customer_id`, R1/R5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    """Registry name, e.g. `"cards.lock_card"`."""
    args: dict[str, ToolArg]


class ConfirmationPlan(BaseModel):
    """What `ConfirmationStore.issue` returns and the `ui.confirm` event carries."""

    model_config = ConfigDict(frozen=True)

    token_id: str
    """Opaque, unguessable."""
    steps: list[PlanStep] = Field(min_length=1)
    expires_at: datetime
    """Aware UTC; issue time + 5 min (`04` §7)."""


class ConfirmationStore(Protocol):
    """Issues, consumes and cancels confirmation plans.

    Bound to one customer and one conversation at construction, so no method
    below takes `customer_id` (R1). Storage semantics (Redis `conf:<id>`, the
    atomic cursor, deletion after the last step) are `04` §7's job, not this
    Protocol's: this card ships the contract only (D18).
    """

    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        # May raise: ToolUnavailable.
        ...

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        """Check the step at the cursor, advance it, and return the consumed
        step's 0-based index.

        Raises `ConfirmationRequired` with reason `"unknown_or_expired"` (absent
        key: never issued, expired or already fully used), `"step_mismatch"`
        (the tool or `args_hash` differs from the step at the cursor) or
        `"wrong_owner"` (another customer or conversation), per D14.
        """
        ...

    async def cancel(self, token_id: str) -> None:
        """Idempotent: cancelling an unknown or already-cancelled `token_id` is a no-op."""
        ...
