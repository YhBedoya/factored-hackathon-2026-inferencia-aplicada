"""`PostgresBankWrites`: `BankWriteTools` over Postgres, via `cards.service`
(D9-D11).

Each of the four writes -- and `get_block_origin` -- first runs
`self._reads.get_card_details(card_id)`: the same ownership probe
`PostgresBank` uses for reads (R1), so a foreign `card_id` raises
`AccessDenied` and logs `tool.access_denied` before anything is written.
Each write then calls the matching `cards.service` write function, followed
by a **separate** re-read service call (never the same round trip):
`verified` is `True` only when that re-read shows the value the write asked
for (R3). `readback` keys are exactly `04` §1's (`locked`/`status` plus
`at`), and `order_replacement` sets `tracking_id` alongside.

`get_block_origin`'s order matches `FakeBankWrites.get_block_origin`
exactly (D10), substituting `cards.service.last_status_actor` for the
overlay's `blocked` set and `details.locked` (from the `app.card_controls`
join `PostgresBank.get_card_details` already did, D3-A3) for the overlay's
`locked` set. It never raises `Conflict` (D2-B D7).

Imports `cards.service` only, never `cards.repository` (import-linter's
`conversation-no-repository` contract -- see the ignore edge this card adds
for this module, mirroring `postgres.py`'s existing four).
"""

from app.core.actions import ActionResult
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.postgres import PostgresBank

__all__ = ["PostgresBankWrites"]


class PostgresBankWrites:
    """`BankWriteTools` bound to one `ToolContext` over Postgres (D10)."""

    def __init__(self, ctx: ToolContext) -> None:
        self._ctx = ctx
        self._reads = PostgresBank(ctx)

    async def get_block_origin(self, card_id: str) -> BlockOrigin:
        # Ownership probe first (R1); its result also feeds the bank-side
        # checks below, so it is not discarded.
        details = await self._reads.get_card_details(card_id)
        actor = await cards_service.last_status_actor(self._ctx.customer_id, card_id)
        if details.status == "Blocked" and actor == "customer":
            return BlockOrigin(kind="customer_block", reason=None)
        if details.locked:
            return BlockOrigin(kind="customer_lock", reason=None)
        profile = await self._reads.get_profile()
        if profile.customer_status != "Active":
            return BlockOrigin(kind="bank_side", reason="customer_status")
        if details.days_past_due is not None and details.days_past_due > 0:
            return BlockOrigin(kind="bank_side", reason="past_due")
        if details.status in ("Blocked", "Suspended"):
            return BlockOrigin(kind="bank_side", reason="bank_status")
        return BlockOrigin(kind="none", reason=None)

    async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        return await self._set_locked(
            card_id, locked=True, tool="cards.lock_card", idempotency_key=idempotency_key
        )

    async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult:
        return await self._set_locked(
            card_id, locked=False, tool="cards.unlock_card", idempotency_key=idempotency_key
        )

    async def _set_locked(
        self, card_id: str, *, locked: bool, tool: str, idempotency_key: str
    ) -> ActionResult:
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        await cards_service.set_locked(
            self._ctx.customer_id,
            card_id,
            locked=locked,
            actor=self._ctx.actor,
            idempotency_key=idempotency_key,
        )
        state = await cards_service.get_lock_state(self._ctx.customer_id, card_id)  # re-read (R3)
        return ActionResult(
            tool=tool,
            status="applied",
            verified=state.locked == locked,
            readback={"locked": state.locked, "at": state.at},
        )

    async def block_card(
        self, card_id: str, reason: BlockReason, *, idempotency_key: str
    ) -> ActionResult:
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        await cards_service.block_card(
            self._ctx.customer_id,
            card_id,
            reason=reason,
            actor=self._ctx.actor,
            conversation_id=self._ctx.conversation_id,
            trace_id=self._ctx.trace_id,
            idempotency_key=idempotency_key,
        )
        state = await cards_service.get_block_state(self._ctx.customer_id, card_id)  # re-read (R3)
        return ActionResult(
            tool="cards.block_card",
            status="applied",
            verified=state.status == "Blocked",
            readback={"status": state.status, "at": state.at},
        )

    async def order_replacement(
        self, card_id: str, address_ref: AddressRef, *, idempotency_key: str
    ) -> ActionResult:
        await self._reads.get_card_details(card_id)  # ownership probe (R1)
        # Never resolves or stores an address (D10): `address_ref` stays
        # opaque all the way through.
        address_changed = address_ref != "on_file"
        replacement_id = await cards_service.order_replacement(
            self._ctx.customer_id,
            card_id,
            address_ref=address_ref,
            address_changed=address_changed,
            conversation_id=self._ctx.conversation_id,
            idempotency_key=idempotency_key,
        )
        state = await cards_service.get_replacement(  # re-read (R3)
            self._ctx.customer_id, card_id, replacement_id
        )
        return ActionResult(
            tool="cards.order_replacement",
            status="applied",
            verified=state.status == "ordered",
            readback={"status": state.status, "at": state.at},
            tracking_id=state.tracking_id,
        )
