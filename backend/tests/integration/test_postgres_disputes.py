"""B1 "Done when" (R3, R12, D14-D16): Postgres claim rows copied from the
transaction they dispute, verified from a **separate** re-read (R3), written
atomically (R12) and idempotent per row (D15); refused for a foreign
transaction (R1).

Fixture customers (`tests/fixtures/fakebank/README.md`): `CLI-TFMULTI00001`
owns `TRX-TFM1CRED0001TXN01` (150.25 USD, `PRD-TFM1CRED0001`) and
`TRX-TFM1DEBT0002TXN01` (50.00 USD, `PRD-TFM1DEBT0002`);
`TRX-TFS2CRED0001TXN01` belongs to `CLI-TFSINGLE0002`.

See `docs/specs/d4-b-disputes-handoff-screens.md` D14-D17; §"Test list" ->
`test_postgres_disputes.py`.
"""

import asyncio
import secrets
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.db import get_engine
from app.core.errors import AccessDenied
from app.domains.audit.schemas import AuditEvent
from app.domains.audit.service import AuditRecorder
from app.domains.conversation.tools import postgres_writes
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.postgres_writes import PostgresBankWrites
from app.domains.disputes.schemas import ClaimRow
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.tools_policy import load_tools_policy, tool_allowed

_OWN_CUSTOMER_ID = "CLI-TFMULTI00001"
_TX_IDS = ["TRX-TFM1CRED0001TXN01", "TRX-TFM1DEBT0002TXN01"]
_FOREIGN_TX_ID = "TRX-TFS2CRED0001TXN01"  # CLI-TFSINGLE0002's transaction


def _ctx(customer_id: str, conversation_id: UUID) -> ToolContext:
    return ToolContext(
        customer_id=customer_id,
        conversation_id=conversation_id,
        actor="customer",
        trace_id="trace-test-postgres-disputes",
        policy_version="unversioned",
    )


async def _claims_by_conversation(conversation_id: UUID) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text(
                "SELECT complaint_id, transaction_id, affected_product_id, claimed_amount, "
                "currency, priority, origin, conversation_id FROM bank.complaints "
                "WHERE conversation_id = :conversation_id"
            ),
            {"conversation_id": conversation_id},
        )
        return [dict(row) for row in result.mappings().all()]


async def _claims_by_transaction(transaction_id: str) -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text("SELECT complaint_id FROM bank.complaints WHERE transaction_id = :transaction_id"),
            {"transaction_id": transaction_id},
        )
        return [dict(row) for row in result.mappings().all()]


def test_claim_row_matches_transaction(it_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    conversation_id = uuid4()
    writes = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID, conversation_id))

    async def _run() -> None:
        first_key = secrets.token_urlsafe(8)
        result = await writes.create_claim(
            _TX_IDS, ["card_in_possession=no"], [], idempotency_key=first_key
        )
        assert result.verified is True
        assert result.readback["status"] == "Open"
        assert result.readback["count"] == 2
        assert result.case_ids is not None
        assert len(result.case_ids) == 2

        rows = await _claims_by_conversation(conversation_id)
        assert len(rows) == 2
        by_tx = {row["transaction_id"]: row for row in rows}
        assert by_tx["TRX-TFM1CRED0001TXN01"]["claimed_amount"] == Decimal("150.25")
        assert by_tx["TRX-TFM1CRED0001TXN01"]["currency"] == "USD"
        assert by_tx["TRX-TFM1CRED0001TXN01"]["affected_product_id"] == "PRD-TFM1CRED0001"
        assert by_tx["TRX-TFM1DEBT0002TXN01"]["claimed_amount"] == Decimal("50.00")
        assert by_tx["TRX-TFM1DEBT0002TXN01"]["affected_product_id"] == "PRD-TFM1DEBT0002"
        for row in rows:
            assert row["origin"] == "app"
            assert row["conversation_id"] == conversation_id
            # SA1: no `priority_flags` on this call -> NULL priority.
            assert row["priority"] is None

        # SA1: a non-empty `priority_flags` writes `priority = 'High'` on the
        # re-read row, a separate claim over the same conversation.
        flagged = await writes.create_claim(
            [_TX_IDS[0]],
            ["card_in_possession=no"],
            ["repeat_complainer"],
            idempotency_key=secrets.token_urlsafe(8),
        )
        assert flagged.case_ids is not None
        flagged_rows = await _claims_by_conversation(conversation_id)
        by_complaint = {row["complaint_id"]: row for row in flagged_rows}
        assert by_complaint[flagged.case_ids[0]]["priority"] == "High"

        # A stale re-read (the separate `get_claims` call finding nothing, as
        # if it hit a lagging replica) must not report `verified=True` (R3).
        # `get_engine` is loop-bound (state file conventions): this shares
        # the same `asyncio.run()` call as the writes above, not a second
        # one, so it reuses the connection pool they already used.
        async def _stale_get_claims(customer_id: str, ids: list[str]) -> list[ClaimRow]:
            return []

        monkeypatch.setattr(postgres_writes.disputes_service, "get_claims", _stale_get_claims)
        stale_result = await writes.create_claim(
            _TX_IDS, ["card_in_possession=no"], [], idempotency_key=secrets.token_urlsafe(8)
        )
        assert stale_result.verified is False
        monkeypatch.undo()

        # Replaying the first key writes nothing new and returns the same
        # case ids (D15).
        before = await _claims_by_conversation(conversation_id)
        replay_result = await writes.create_claim(
            _TX_IDS, ["card_in_possession=no"], [], idempotency_key=first_key
        )
        after = await _claims_by_conversation(conversation_id)
        assert len(after) == len(before)
        assert replay_result.case_ids == result.case_ids

    asyncio.run(_run())


def test_foreign_transaction_refused(it_env: None) -> None:
    conversation_id = uuid4()
    raw = PostgresBankWrites(_ctx(_OWN_CUSTOMER_ID, conversation_id))
    store = InMemoryConfirmationStore(_OWN_CUSTOMER_ID, str(conversation_id))
    gate = FakeStepUpGate("0000")
    events: list[AuditEvent] = []

    async def _insert(event: AuditEvent) -> None:
        events.append(event)

    recorder = AuditRecorder(
        conversation_id=conversation_id,
        turn_id=uuid4(),
        trace_id="trace-test-postgres-disputes",
        policy_version="unversioned",
        actor="bot",
        insert=_insert,
    )
    policy = load_tools_policy()
    executor = ConfirmedWriteTools(
        raw,
        store,
        gate,
        requires_step_up=lambda t, a: False,
        allowed=tool_allowed(policy),
        audit=recorder,
    )

    async def _run() -> None:
        step = PlanStep(
            tool="disputes.create_claim",
            args={"tx_ids": [_FOREIGN_TX_ID], "answers": [], "priority_flags": []},
        )
        plan = await executor.issue_plan([step], "unrecognized_charge")

        with pytest.raises(AccessDenied):
            await executor.create_claim([_FOREIGN_TX_ID], [], [], plan.token_id)

        assert await _claims_by_transaction(_FOREIGN_TX_ID) == []
        access_denied_events = [event for event in events if event.type == "access_denied"]
        assert len(access_denied_events) == 1

    asyncio.run(_run())
