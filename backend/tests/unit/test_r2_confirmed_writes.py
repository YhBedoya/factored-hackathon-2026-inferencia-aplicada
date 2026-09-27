"""R2 (no side effect without a server-issued, single-use confirmation token)
contract tests.

See `docs/specs/d2-k-write-contracts.md` §"Test list". T2 adds
`test_args_hash_binds_tool_and_args`; T4 appends
`test_raw_write_runs_only_after_its_step_is_consumed`,
`test_step_up_checked_before_token_is_consumed` and
`test_failed_or_unverified_step_cancels_the_plan` against the
`ConfirmedWriteTools` executor.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from app.core.actions import ActionResult
from app.core.errors import ConfirmationRequired, StepUpRequired, ToolUnavailable
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.policy.confirmation import ConfirmationPlan, PlanStep, ToolArgs, args_hash


def test_args_hash_binds_tool_and_args() -> None:
    """Same hash for reordered keys; a different hash for a different tool or
    a different arg value (D2).
    """
    args = {"card_id": "PRD-1", "reason": "suspected_fraud"}
    reordered = {"reason": "suspected_fraud", "card_id": "PRD-1"}

    assert args_hash("cards.lock_card", args) == args_hash("cards.lock_card", reordered)
    assert args_hash("cards.lock_card", args) != args_hash("cards.block_card", args)
    assert args_hash("cards.lock_card", args) != args_hash(
        "cards.lock_card", {**args, "card_id": "PRD-2"}
    )


class _StubStore:
    """Records `consume_step`/`cancel` calls; raises on `consume_step` if
    constructed with an error (`ConfirmedWriteTools` never sees `issue`).
    """

    def __init__(self, consume_error: Exception | None = None) -> None:
        self._consume_error = consume_error
        self.consumed: list[tuple[str, str, ToolArgs]] = []
        self.cancelled: list[str] = []

    async def issue(self, steps: Sequence[PlanStep]) -> ConfirmationPlan:
        raise NotImplementedError

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        self.consumed.append((token_id, tool, args))
        if self._consume_error is not None:
            raise self._consume_error
        return 0

    async def cancel(self, token_id: str) -> None:
        self.cancelled.append(token_id)


class _StubGate:
    """A `StepUpGate` with a fixed, mutable answer."""

    def __init__(self, *, valid: bool) -> None:
        self.valid = valid

    async def is_step_up_valid(self) -> bool:
        return self.valid


class _StubRawWrites:
    """Records calls; returns a configurable `ActionResult` or raises."""

    def __init__(
        self, *, result: ActionResult | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        raise NotImplementedError

    async def lock_card(self, card_id: str) -> ActionResult:
        return await self._call("lock_card", card_id)

    async def unlock_card(self, card_id: str) -> ActionResult:
        return await self._call("unlock_card", card_id)

    async def block_card(self, card_id: str, reason: BlockReason) -> ActionResult:
        return await self._call("block_card", card_id, reason)

    async def order_replacement(self, card_id: str, address_ref: AddressRef) -> ActionResult:
        return await self._call("order_replacement", card_id, address_ref)

    async def _call(self, name: str, *args: Any) -> ActionResult:
        self.calls.append((name, args))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


_WRITE_CASES = [
    ("lock_card", ("PRD-1",), "cards.lock_card", {"card_id": "PRD-1"}),
    ("unlock_card", ("PRD-1",), "cards.unlock_card", {"card_id": "PRD-1"}),
    (
        "block_card",
        ("PRD-1", "suspected_fraud"),
        "cards.block_card",
        {"card_id": "PRD-1", "reason": "suspected_fraud"},
    ),
    (
        "order_replacement",
        ("PRD-1", "on_file"),
        "cards.order_replacement",
        {"card_id": "PRD-1", "address_ref": "on_file"},
    ),
]


@pytest.mark.parametrize(("method", "call_args", "tool", "expected_args"), _WRITE_CASES)
def test_raw_write_runs_only_after_its_step_is_consumed(
    method: str,
    call_args: tuple[str, ...],
    tool: str,
    expected_args: dict[str, str],
) -> None:
    """R2: the store receives exactly `(token_id, tool, args)` with no token
    in `args`, and raw is called with the same args. A `ConfirmationRequired`
    from the store stops the raw call and propagates untouched.
    """

    async def _run() -> None:
        result = ActionResult(tool=tool, status="applied", verified=True, readback={})
        raw = _StubRawWrites(result=result)
        store = _StubStore()
        gate = _StubGate(valid=True)
        executor = ConfirmedWriteTools(raw, store, gate, requires_step_up=lambda t, a: False)

        out = await getattr(executor, method)(*call_args, "tok-1")

        assert out is result
        assert store.consumed == [("tok-1", tool, expected_args)]
        assert raw.calls == [(method, call_args)]

        raw_rejected = _StubRawWrites(result=result)
        store_rejected = _StubStore(consume_error=ConfirmationRequired("step_mismatch"))
        rejected = ConfirmedWriteTools(
            raw_rejected, store_rejected, gate, requires_step_up=lambda t, a: False
        )

        with pytest.raises(ConfirmationRequired):
            await getattr(rejected, method)(*call_args, "tok-2")

        assert raw_rejected.calls == []

    asyncio.run(_run())


def test_step_up_checked_before_token_is_consumed() -> None:
    """R2 step-up: rule true and gate false raises `StepUpRequired` before
    anything is consumed or called; rule true and gate true lets it proceed.
    """

    async def _run() -> None:
        result = ActionResult(
            tool="cards.unlock_card", status="applied", verified=True, readback={"locked": False}
        )
        raw = _StubRawWrites(result=result)
        store = _StubStore()
        gate = _StubGate(valid=False)
        executor = ConfirmedWriteTools(raw, store, gate, requires_step_up=lambda t, a: True)

        with pytest.raises(StepUpRequired):
            await executor.unlock_card("PRD-1", "tok-1")

        assert store.consumed == []
        assert raw.calls == []

        gate.valid = True
        out = await executor.unlock_card("PRD-1", "tok-1")

        assert out is result

    asyncio.run(_run())


def test_failed_or_unverified_step_cancels_the_plan() -> None:
    """R2 + R3 (ADR-027): a raised `ToolUnavailable` cancels and re-raises; a
    returned `verified=False` cancels and is returned unchanged.
    """

    async def _run() -> None:
        gate = _StubGate(valid=True)

        store = _StubStore()
        raw = _StubRawWrites(error=ToolUnavailable("down"))
        executor = ConfirmedWriteTools(raw, store, gate, requires_step_up=lambda t, a: False)

        with pytest.raises(ToolUnavailable):
            await executor.lock_card("PRD-1", "tok-1")

        assert store.cancelled == ["tok-1"]

        unverified = ActionResult(
            tool="cards.lock_card", status="applied", verified=False, readback={}
        )
        store2 = _StubStore()
        raw2 = _StubRawWrites(result=unverified)
        executor2 = ConfirmedWriteTools(raw2, store2, gate, requires_step_up=lambda t, a: False)

        out = await executor2.lock_card("PRD-1", "tok-2")

        assert out is unverified
        assert store2.cancelled == ["tok-2"]

    asyncio.run(_run())
