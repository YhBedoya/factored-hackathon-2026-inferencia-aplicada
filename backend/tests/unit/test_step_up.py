"""R2 step-up contract test: `ConfirmedWriteTools` refuses an unlock whose
`SessionStepUpGate` isn't valid, before the confirmation store is touched.

See `docs/specs/d3-a-guardrails-write-path.md` D4, D16, §"Test list".
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.actions import ActionResult
from app.core.errors import StepUpRequired
from app.domains.audit.schemas import AuditType
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.identity.step_up_session import SessionStepUpGate
from app.domains.policy.confirmation import ConfirmationPlan, PlanStep, ToolArgs
from app.domains.policy.tools_policy import load_tools_policy, step_up_rule, tool_allowed

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _now() -> datetime:
    return _NOW


class _StubStore:
    """`consume_step` must never be reached: a `StepUpRequired` refusal stops
    the executor before the store is touched."""

    def __init__(self) -> None:
        self.consumed = False

    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        raise NotImplementedError

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        self.consumed = True
        return 0

    async def cancel(self, token_id: str) -> None:
        pass


class _StubRawWrites:
    """`unlock_card` must never be reached either."""

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        raise NotImplementedError

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        raise NotImplementedError

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        raise AssertionError("unlock_card must not run without a valid step-up")

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        raise NotImplementedError

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        raise NotImplementedError


class _ListRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[AuditType, dict[str, Any]]] = []

    async def record(
        self, type: AuditType, payload: dict[str, Any], sources: Sequence[str] = ()
    ) -> UUID:
        self.events.append((type, payload))
        return uuid4()


@pytest.mark.parametrize("step_up_at", [None, _NOW - timedelta(minutes=6)])
def test_unlock_without_valid_step_up_refused(step_up_at: datetime | None) -> None:
    """D4: neither no `step_up_at` nor one older than the policy's
    `step_up_window_minutes` (5) passes `SessionStepUpGate`. `unlock_card`
    raises `StepUpRequired` before `consume_step` runs, and records exactly
    one `rule_hit step_up_required`.
    """

    async def _run() -> None:
        policy = load_tools_policy()
        window = timedelta(minutes=policy.step_up_window_minutes)
        gate = SessionStepUpGate(step_up_at, window, now=_now)
        store = _StubStore()
        recorder = _ListRecorder()
        executor = ConfirmedWriteTools(
            _StubRawWrites(),
            store,
            gate,
            step_up_rule(policy),
            tool_allowed(policy),
            recorder,
        )

        with pytest.raises(StepUpRequired):
            await executor.unlock_card("PRD-1", "tok-1")

        assert store.consumed is False
        rule_hits = [payload for event, payload in recorder.events if event == "rule_hit"]
        assert rule_hits == [{"rule_id": "step_up_required", "tool": "cards.unlock_card"}]

    asyncio.run(_run())
