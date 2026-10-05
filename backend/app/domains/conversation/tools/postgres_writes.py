"""`PostgresBankWrites`: `BankWriteTools` over Postgres, via `cards.service`
(D9-D11) and `disputes.service` (D4-B D14-D16).

Each of the four card writes -- and `get_block_origin` -- first runs
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

`create_claim` calls `disputes.service.create_claims` (which does its own
own-row check on every `tx_id` through `transactions.service`, R1), then a
**separate** `disputes.service.get_claims` re-read: `verified` is `True`
only when every re-read row matches the value `create_claims` just wrote
(amount, currency, product, `transaction_id`, `origin`, `priority`) for
every case id (D16, R3, SA1).

Imports `cards.service` and `disputes.service` only, never a `repository`
directly (import-linter's `conversation-no-repository` contract -- see the
ignore edges this module keeps, mirroring `postgres.py`'s existing four).
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

from app.core.actions import ActionResult
from app.domains.cards import service as cards_service
from app.domains.cards.schemas import AddressRef, BlockOrigin, BlockReason
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.postgres import PostgresBank
from app.domains.conversation.tools.write import PendingCardRequests
from app.domains.customers.schemas import ProfileField, ProfileValues
from app.domains.disputes import service as disputes_service
from app.domains.disputes.schemas import ClaimRow
from app.domains.safety.vault import PostgresPiiVault

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

    async def create_claim(
        self,
        tx_ids: list[str],
        answers: list[str],
        priority_flags: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        written = await disputes_service.create_claims(
            self._ctx.customer_id,
            self._ctx.conversation_id,
            tx_ids,
            answers,
            priority_flags,
            idempotency_key,
        )
        case_ids = [row.complaint_id for row in written]
        reread = await disputes_service.get_claims(self._ctx.customer_id, case_ids)  # re-read (R3)
        return ActionResult(
            tool="disputes.create_claim",
            status="applied",
            verified=_claims_match(written, reread),
            readback={"status": "Open", "count": len(written), "at": datetime.now(UTC)},
            case_ids=case_ids,
        )

    async def request_card(
        self,
        kind: Literal["credit", "debit"],
        changed_fields: list[str],
        *,
        idempotency_key: str,
    ) -> ActionResult:
        """D10: save the staged profile values and create the pending open request
        in one `cards.service` call, then re-read both (R3). Values come only from
        the conversation's vault (R5) and never reach the read-back or a log: the
        read-back carries field names only. `customer_id` is the session's (R1).
        """
        vault = PostgresPiiVault(self._ctx.conversation_id)
        values = await vault.form_values(changed_fields)
        if set(values) != set(changed_fields):
            # A field the form never staged: nothing is written (R3).
            return ActionResult(
                tool="cards.request_card",
                status="applied",
                verified=False,
                readback={"status": "unknown", "kind": kind, "at": datetime.now(UTC)},
            )
        changes = cast("dict[ProfileField, str]", values)
        view = await cards_service.create_open_request(
            self._ctx.customer_id,
            self._ctx.conversation_id,
            kind,
            changes,
            idempotency_key=idempotency_key,
        )
        stored, profile = await cards_service.read_back_open_request(view.id)  # re-read (R3)
        verified = (
            stored.kind == "open"
            and stored.status == "pending"
            and stored.card_kind == kind
            and stored.reference == view.reference
            and stored.customer_id == self._ctx.customer_id
            and all(_profile_matches(profile, field, value) for field, value in changes.items())
        )
        return ActionResult(
            tool="cards.request_card",
            status="applied",
            verified=verified,
            # `ReadbackValue` has no list member: `fields_saved` is comma-joined.
            readback={
                "status": "pending" if verified else "unknown",
                "kind": kind,
                "fields_saved": ",".join(changed_fields),
                "request_id": str(stored.id),
                "at": stored.created_at,
            },
            tracking_id=stored.reference,
        )

    async def request_closure(
        self, card_id: str, reason: str, *, idempotency_key: str
    ) -> ActionResult:
        """Create the pending close request, then re-read it with the card (R3).
        `create_close_request` does the ownership check (R1: another customer's
        card raises `AccessDenied`); the read-back is scoped by the request id the
        write just returned. Balance stays a raw `Decimal` (R4)."""
        view = await cards_service.create_close_request(
            self._ctx.customer_id,
            self._ctx.conversation_id,
            card_id,
            reason,
            idempotency_key=idempotency_key,
        )
        stored, card = await cards_service.read_back_close_request(view.id)  # re-read (R3)
        verified = (
            stored.kind == "close"
            and stored.status == "pending"
            and stored.reference == view.reference
            and stored.customer_id == self._ctx.customer_id
            and stored.product_id == card_id
            and stored.reason_code == reason
        )
        return ActionResult(
            tool="cards.request_closure",
            status="applied",
            verified=verified,
            readback={
                "status": "pending" if verified else "unknown",
                "reason": reason,
                "request_id": str(stored.id),
                "card_id": card_id,
                "card_kind": card.kind,
                "last4": card.last4,
                "current_balance": card.current_balance,
                "currency": card.currency,
                "at": stored.created_at,
            },
            tracking_id=stored.reference,
        )

    async def pending_card_requests(self) -> PendingCardRequests:
        pending = await cards_service.pending_requests(self._ctx.customer_id)
        return PendingCardRequests(
            open_pending=any(r.kind == "open" for r in pending),
            close_card_ids=frozenset(
                r.product_id for r in pending if r.kind == "close" and r.product_id
            ),
        )


def _profile_matches(profile: ProfileValues, field: str, value: str) -> bool:
    """Whether the re-read profile holds `value` for `field`; income compares as a
    `Decimal`, the rest as trimmed text (the same normalisation the write used)."""
    current = getattr(profile, field)
    if field == "estimated_monthly_income":
        try:
            return bool(current == Decimal(value.strip()))
        except InvalidOperation:
            return False
    return bool(current == value.strip())


def _claims_match(written: list[ClaimRow], reread: list[ClaimRow]) -> bool:
    """`True` only when every `written` row's amount, currency, product,
    transaction id, `origin` and `priority` reappear in `reread`, keyed by
    `complaint_id` (D16, R3, SA1). `disputes.service.get_claims` already
    scopes `reread` to the session's customer (R1), so a row that came back
    for someone else, or didn't come back at all, fails the match here.
    `written`'s `priority` is already the one `create_claims` requested
    (`'High'` or `None`), so comparing it to the re-read row is enough --
    no separate "requested priority" argument is needed.
    """
    if len(written) != len(reread):
        return False
    by_id = {row.complaint_id: row for row in reread}
    for row in written:
        match = by_id.get(row.complaint_id)
        if match is None:
            return False
        if (
            match.claimed_amount != row.claimed_amount
            or match.currency != row.currency
            or match.affected_product_id != row.affected_product_id
            or match.transaction_id != row.transaction_id
            or match.origin != "app"
            or match.priority != row.priority
        ):
            return False
    return True
