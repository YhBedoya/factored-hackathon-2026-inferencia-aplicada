"""`FakeBankWrites` and `FakeBankOverlay` tests (D7, D8, B4).

See `docs/specs/d2-b-card-info-block.md` §"Test list"
(`test_fakebank_writes.py`) and §"Decisions" D7, D8. Bound to the invented
TEST FIXTURE in `backend/tests/fixtures/fakebank/`, never to `data/`.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank, FakeBankOverlay, FakeBankWrites

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fakebank"


def _ctx(customer_id: str) -> ToolContext:
    return ToolContext(
        customer_id=customer_id,
        conversation_id=uuid4(),
        actor="customer",
        trace_id="trace-test",
        policy_version="unversioned",
    )


def test_writes_read_back_and_block_origin() -> None:
    overlay = FakeBankOverlay()
    ctx = _ctx("CLI-TFMULTI00001")
    writes = FakeBankWrites(ctx, _FIXTURE_DIR, overlay)
    reads = FakeBank(ctx, _FIXTURE_DIR, overlay)
    credit_card_id = "PRD-TFM1CRED0001"

    lock_result = asyncio.run(writes.lock_card(credit_card_id))
    assert lock_result.verified is True
    assert lock_result.readback["locked"] is True

    origin_after_lock = asyncio.run(writes.get_block_origin(credit_card_id))
    assert origin_after_lock.kind == "customer_lock"
    assert origin_after_lock.reason is None

    unlock_result = asyncio.run(writes.unlock_card(credit_card_id))
    assert unlock_result.verified is True
    assert unlock_result.readback["locked"] is False

    block_result = asyncio.run(writes.block_card(credit_card_id, "lost_or_stolen"))
    assert block_result.verified is True
    assert block_result.readback["status"] == "Blocked"

    origin_after_block = asyncio.run(writes.get_block_origin(credit_card_id))
    assert origin_after_block.kind == "customer_block"
    assert origin_after_block.reason is None

    replacement_result = asyncio.run(writes.order_replacement(credit_card_id, "on_file"))
    assert replacement_result.verified is True
    assert replacement_result.readback["status"] == "ordered"
    assert replacement_result.tracking_id is not None
    assert replacement_result.tracking_id.startswith("RPL-")
    assert len(replacement_result.tracking_id) == len("RPL-") + 8

    # `list_cards` reflects the session's own lock and block (D7): unlocked
    # after the lock/unlock pair above, and blocked after `block_card`.
    cards = {card.card_id: card for card in asyncio.run(reads.list_cards())}
    assert cards[credit_card_id].locked is False
    assert cards[credit_card_id].status == "Blocked"

    # Bank-side origins, each on a customer/card untouched by this session's
    # overlay (D8's three `bank_side` reasons, checked in order, plus `none`).
    past_due_origin = asyncio.run(
        FakeBankWrites(_ctx("CLI-TFPASTD00005"), _FIXTURE_DIR, FakeBankOverlay()).get_block_origin(
            "PRD-TFP5CRED0001"
        )
    )
    assert past_due_origin.kind == "bank_side"
    assert past_due_origin.reason == "past_due"

    bank_status_origin = asyncio.run(
        FakeBankWrites(_ctx("CLI-TFBLOCKD0003"), _FIXTURE_DIR, FakeBankOverlay()).get_block_origin(
            "PRD-TFB3DEBT0001"
        )
    )
    assert bank_status_origin.kind == "bank_side"
    assert bank_status_origin.reason == "bank_status"

    customer_status_origin = asyncio.run(
        FakeBankWrites(_ctx("CLI-TFINACT00004"), _FIXTURE_DIR, FakeBankOverlay()).get_block_origin(
            "PRD-TFI4CRED0001"
        )
    )
    assert customer_status_origin.kind == "bank_side"
    assert customer_status_origin.reason == "customer_status"

    none_origin = asyncio.run(
        FakeBankWrites(_ctx("CLI-TFSINGLE0002"), _FIXTURE_DIR, FakeBankOverlay()).get_block_origin(
            "PRD-TFS2CRED0001"
        )
    )
    assert none_origin.kind == "none"
    assert none_origin.reason is None
