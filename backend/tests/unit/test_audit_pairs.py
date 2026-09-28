"""D13/D14: every tool call this turn's `RecordingBankTools`/
`ConfirmedWriteTools` make leaves a `tool_call`/`tool_result` pair, every
event carries the turn's policy hash, and no payload ever smuggles free text.

See `docs/specs/d3-a-guardrails-write-path.md` D2, D13, D14; §"Test list" ->
`test_audit_pairs.py`.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.errors import AccessDenied, StepUpRequired
from app.domains.audit.schemas import AuditEvent
from app.domains.audit.service import AuditRecorder
from app.domains.conversation.tools.executor import ConfirmedWriteTools
from app.domains.conversation.tools.fakebank import FakeBank, FakeBankOverlay, FakeBankWrites
from app.domains.conversation.tools.registry import RecordingBankTools, build_tool_context
from app.domains.identity.models import Session
from app.domains.identity.step_up_fake import FakeStepUpGate
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.registry import get_policies
from app.domains.policy.tools_policy import step_up_rule, tool_allowed

_OWN_CUSTOMER_ID = "CLI-TFMULTI00001"  # owns PRD-TFM1CRED0001 (fixtures README)
_OWN_CARD_ID = "PRD-TFM1CRED0001"
_FOREIGN_CARD_ID = "PRD-TFS2CRED0001"  # CLI-TFSINGLE0002's card

# Structural keys only (R5, D13): every event's payload must be a subset of
# this allowlist -- no user text, no reply text, ever.
_ALLOWED_PAYLOAD_KEYS = {
    "tool",
    "card_id",
    "count",
    "args_hash",
    "error",
    "rule_id",
    "intent",
    "tools",
    "step_count",
    "step_index",
    "verified",
    "readback",
    "kind",
    "reason",
}


def test_every_tool_call_leaves_a_pair_with_policy_hash(fakebank_dir: Path) -> None:
    async def _run() -> None:
        session = Session(
            account_id=uuid4(), role="customer", customer_id=_OWN_CUSTOMER_ID, step_up_at=None
        )
        ctx = build_tool_context(session, uuid4(), "t")
        turn_id = uuid4()

        events: list[AuditEvent] = []

        async def _insert(event: AuditEvent) -> None:
            events.append(event)

        rec = AuditRecorder(
            conversation_id=ctx.conversation_id,
            turn_id=turn_id,
            trace_id=ctx.trace_id,
            policy_version=ctx.policy_version,
            actor="bot",
            insert=_insert,
        )

        overlay = FakeBankOverlay()
        reads = RecordingBankTools(FakeBank(ctx, fakebank_dir, overlay), rec)
        await reads.list_cards()

        raw = FakeBankWrites(ctx, fakebank_dir, overlay)
        store = InMemoryConfirmationStore(_OWN_CUSTOMER_ID, str(ctx.conversation_id))
        gate = FakeStepUpGate("0000")  # never verified: unlock_card's step-up stays invalid
        policy = get_policies().tools
        write_tools = ConfirmedWriteTools(
            raw, store, gate, step_up_rule(policy), tool_allowed(policy), rec
        )

        with pytest.raises(StepUpRequired):
            await write_tools.unlock_card(_OWN_CARD_ID, "unused-token")

        plan = await write_tools.issue_plan(
            [PlanStep(tool="cards.lock_card", args={"card_id": _OWN_CARD_ID})], "card_block"
        )
        lock_result = await write_tools.lock_card(_OWN_CARD_ID, plan.token_id)
        assert lock_result.verified

        with pytest.raises(AccessDenied):
            await write_tools.get_block_origin(_FOREIGN_CARD_ID, "card_unlock")

        # One tool_call/tool_result pair per call: list_cards (read),
        # unlock_card (refused), lock_card (verified), get_block_origin
        # (foreign card) -- 4 calls, 4 pairs.
        by_type: dict[str, int] = {}
        for event in events:
            by_type[event.type] = by_type.get(event.type, 0) + 1
        assert by_type["tool_call"] == 4
        assert by_type["tool_result"] == 4
        assert by_type["access_denied"] == 1

        for event in events:
            assert event.policy_version == get_policies().hash
            assert set(event.payload) <= _ALLOWED_PAYLOAD_KEYS

        readback_event = next(event for event in events if event.type == "readback")
        assert lock_result.audit_event_id == readback_event.id

    asyncio.run(_run())
