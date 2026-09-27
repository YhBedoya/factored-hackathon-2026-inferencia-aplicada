"""R1 (`customer_id` comes only from the session) tests for `FakeBank`.

See `docs/specs/d1-b-agent-sandbox.md` §"Test list" (`test_r1_fakebank.py`)
and §"Decisions" D1, D17. `FakeBank` is bound to the invented TEST FIXTURE in
`backend/tests/fixtures/fakebank/`, never to `data/`.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.errors import AccessDenied, NotFound
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.transactions.schemas import TxFilter

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fakebank"

_EXPECTED_CARD_IDS = {
    "CLI-TFMULTI00001": {"PRD-TFM1CRED0001", "PRD-TFM1DEBT0002", "PRD-TFM1DEBT0003"},
    "CLI-TFSINGLE0002": {"PRD-TFS2CRED0001"},
    "CLI-TFBLOCKD0003": {"PRD-TFB3DEBT0001"},
}


def _make_bank(customer_id: str) -> FakeBank:
    ctx = ToolContext(
        customer_id=customer_id,
        conversation_id=uuid4(),
        actor="customer",
        trace_id="trace-test",
        policy_version="unversioned",
    )
    return FakeBank(ctx, _FIXTURE_DIR)


def test_each_customer_sees_only_own_cards() -> None:
    """For every fixture customer, `list_cards()` returns exactly that
    customer's cards -- the savings account (`PRD-TFM1SAVE0004`) and every
    other customer's cards are excluded (B1, R1).
    """
    for customer_id, expected_ids in _EXPECTED_CARD_IDS.items():
        cards = asyncio.run(_make_bank(customer_id).list_cards())
        assert {card.card_id for card in cards} == expected_ids


def test_foreign_ids_are_refused() -> None:
    """Another customer's `card_id` is `AccessDenied` from both
    `get_card_details` and `search_transactions(TxFilter(card_id=...))`. An
    unknown id is `NotFound` (R1, D17).
    """
    bank = _make_bank("CLI-TFMULTI00001")
    foreign_card_id = "PRD-TFS2CRED0001"  # CLI-TFSINGLE0002's card

    with pytest.raises(AccessDenied):
        asyncio.run(bank.get_card_details(foreign_card_id))
    with pytest.raises(AccessDenied):
        asyncio.run(bank.search_transactions(TxFilter(card_id=foreign_card_id)))
    with pytest.raises(NotFound):
        asyncio.run(bank.get_card_details("PRD-DOESNOTEXIST01"))
