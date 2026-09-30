"""R11 (bounded retries) on the tool wrappers (D6-A D4, D5): a write retries
with the same idempotency key and one `consume_step`, then cancels the plan;
a read that times out is retried, then surfaces `ToolUnavailable`.
"""

import asyncio
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.actions import ActionResult
from app.core.config import get_settings
from app.core.errors import ConfirmationRequired, ToolUnavailable
from app.domains.audit.schemas import AuditType
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.registry import RecordingBankTools
from app.domains.policy.confirmation import PlanStep, ToolArgs
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore


@pytest.fixture
def reset_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _no_sleep(delay: float) -> None:
    return None


class _ListRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[AuditType, dict[str, Any]]] = []

    async def record(
        self, type: AuditType, payload: dict[str, Any], sources: Sequence[str] = ()
    ) -> UUID:
        self.events.append((type, payload))
        return uuid4()


class _CountingStore(InMemoryConfirmationStore):
    consumed = 0

    async def consume_step(self, token_id: str, tool: str, args: ToolArgs) -> int:
        self.consumed += 1
        return await super().consume_step(token_id, tool, args)


class _DownRaw:
    """Every lock attempt fails, and remembers the key it was given."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        self.keys.append(idempotency_key)
        raise ToolUnavailable("down")


def test_write_retried_same_key_then_plan_cancelled(reset_settings: None) -> None:
    async def _run() -> None:
        raw = _DownRaw()
        store = _CountingStore("CLI-1", "conv-1")
        rec = _ListRecorder()
        executor = ConfirmedWriteTools(
            raw,  # type: ignore[arg-type]
            store,
            _AlwaysValid(),  # type: ignore[arg-type]
            requires_step_up=lambda t, a: False,
            allowed=lambda i, t: True,
            audit=rec,
            sleep=_no_sleep,
        )
        plan = await executor.issue_plan(
            [PlanStep(tool="cards.lock_card", args={"card_id": "PRD-1"})], "card_lock"
        )

        with pytest.raises(ToolUnavailable):
            await executor.lock_card("PRD-1", plan.token_id)

        assert raw.keys == [f"{plan.token_id}:0"] * 3
        assert store.consumed == 1
        attempts = [p["attempt"] for t, p in rec.events if t == "tool_result"]
        assert attempts == [1, 2, 3]
        # Cancelled: the token is gone, so a replay is refused.
        with pytest.raises(ConfirmationRequired):
            await store.consume_step(plan.token_id, "cards.lock_card", {"card_id": "PRD-1"})

    asyncio.run(_run())


class _AlwaysValid:
    async def is_step_up_valid(self) -> bool:
        return True


class _SlowInner:
    def __init__(self) -> None:
        self.attempts = 0

    async def list_cards(self) -> list[Any]:
        self.attempts += 1
        await asyncio.sleep(1)
        return []


def test_read_timeout_retried(reset_settings: None) -> None:
    async def _run() -> None:
        inner = _SlowInner()
        reads = RecordingBankTools(
            inner,  # type: ignore[arg-type]
            _ListRecorder(),
            sleep=_no_sleep,
            timeout_s=0.01,
        )

        with pytest.raises(ToolUnavailable):
            await reads.list_cards()

        assert inner.attempts == 3
        assert reads.calls == ["list_cards"]

    asyncio.run(_run())
