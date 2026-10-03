"""R3: a write that comes back `verified=False` never says "done" (D11, D17).

See the spec's Test list row for `test_r3_flows.py`. `_UnverifiedLockWrites`
is a `BankWriteTools` stub (structural, like `FakeBankWrites`) whose
`lock_card` always reports `verified=False`; every other method is unused by
this test and raises if ever called.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.core.actions import ActionResult
from app.core.errors import ConfirmationRequired
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from tests.conftest import ScriptedLLM, make_session


class _UnverifiedLockWrites:
    """`BankWriteTools` whose `lock_card` never verifies (R3)."""

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        raise NotImplementedError

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        return ActionResult(
            tool="cards.lock_card",
            status="applied",
            verified=False,
            readback={"locked": False, "at": datetime.now(UTC)},
        )

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        raise NotImplementedError

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        raise NotImplementedError

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        raise NotImplementedError


def test_unverified_write_never_says_done(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["card_block"],
                        status="clear",
                        slots=NLUSlots(block_kind="temporary_lock"),
                    ),
                    NLUResult(language="es", intents=["affirm"], status="clear"),
                ],
                "handoff_summary": [
                    HandoffSummaryDraft(request="Acción sin verificar en {queue_label}.")
                ],
            }
        )
        session = make_session(
            "CLI-TFSINGLE0002", fakebank_dir, llm, raw_writes=_UnverifiedLockWrites()
        )

        await run_turn(session.graph, "bloquea mi tarjeta", config=session.config)
        state_after_plan = await session.graph.aget_state(session.config)
        token_id = state_after_plan.values["confirmation_token_id"]
        assert isinstance(token_id, str)

        reply, debug = await run_turn(session.graph, "si", config=session.config)

        assert "Listo" not in reply
        assert "Atención" in reply
        packet = session.handoff_tools.created[-1]
        assert (packet.queue, packet.reason) == ("atencion", "action_unverified")
        assert debug.pending is None

        final_state = await session.graph.aget_state(session.config)
        assert final_state.values["escalation_reason"] == "action_unverified"

        # The plan is gone: consuming the same (now stale) token again fails.
        try:
            await session.store.consume_step(
                token_id, "cards.lock_card", {"card_id": "PRD-TFS2CRED0001"}
            )
            raise AssertionError("expected ConfirmationRequired")
        except ConfirmationRequired as exc:
            assert exc.reason == "unknown_or_expired"

    asyncio.run(run())
