"""R1 tests for `transactions.explain_decline` (spec D4).

FakeBank only, per the spec ("Postgres-repo parity, if that is cheap;
FakeBank at minimum"). See
`docs/specs/d5-b-decline-explainer-test-sets.md` §"Test list" #3.
"""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.errors import NotFound
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "fakebank"


def _make_bank(customer_id: str) -> FakeBank:
    ctx = ToolContext(
        customer_id=customer_id,
        conversation_id=uuid4(),
        actor="customer",
        trace_id="trace-test",
        policy_version="unversioned",
    )
    return FakeBank(ctx, _FIXTURE_DIR)


def test_explain_decline_other_customer_is_not_found() -> None:
    """Another customer's Declined transaction and one's own non-Declined
    transaction are both `NotFound` (R1, D4) -- no `AccessDenied` and no
    existence probe. A customer's own Declined row maps to its policy entry,
    with `source` naming the policy version.
    """
    other_customer = _make_bank("CLI-TFSINGLE0002")
    with pytest.raises(NotFound):
        # CLI-TFDECLN00006's Declined transaction: belongs to another
        # customer.
        asyncio.run(other_customer.explain_decline("TRX-TFD6CRED0001TXN01"))
    with pytest.raises(NotFound):
        # CLI-TFSINGLE0002's own transaction, but it is Approved.
        asyncio.run(other_customer.explain_decline("TRX-TFS2CRED0001TXN01"))

    owner = _make_bank("CLI-TFDECLN00006")
    explanation = asyncio.run(owner.explain_decline("TRX-TFD6CRED0001TXN04"))
    assert explanation.code == "54"
    assert explanation.self_service is True
    assert explanation.source == "policy:decline_codes@unversioned"
