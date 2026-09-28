"""R1 + D12: a foreign card is refused by `PostgresBank`, and logged exactly
once. A3 "Done when".

Fixture customers (`tests/fixtures/fakebank/README.md`): `CLI-TFMULTI00001`
owns `PRD-TFM1CRED0001` (credit, last4 `6475`); `CLI-TFSINGLE0002` owns
`PRD-TFS2CRED0001`. Bound to the first, both reads of the second card must
raise `AccessDenied` and log `tool.access_denied` exactly once each -- never
a card number, only the opaque `product_id`.

See `docs/specs/d2-a-login-read-tools-api.md` D11, D12; §"Test list" ->
`test_r1_postgres_tools.py`.
"""

import asyncio
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from app.core.errors import AccessDenied
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.postgres import PostgresBank
from app.domains.transactions.schemas import TxFilter

_OWN_CUSTOMER_ID = "CLI-TFMULTI00001"
_OWN_CARD_ID = "PRD-TFM1CRED0001"
_FOREIGN_CARD_ID = "PRD-TFS2CRED0001"  # CLI-TFSINGLE0002's card


def test_foreign_card_refused_and_logged(it_env: None) -> None:
    ctx = ToolContext(
        customer_id=_OWN_CUSTOMER_ID,
        conversation_id=uuid4(),
        actor="customer",
        trace_id="trace-test-r1",
        policy_version="unversioned",
    )
    bank = PostgresBank(ctx)

    async def _run() -> None:
        with capture_logs() as logs:
            with pytest.raises(AccessDenied):
                await bank.get_card_details(_FOREIGN_CARD_ID)
        assert len(logs) == 1
        event = logs[0]
        assert event["event"] == "tool.access_denied"
        assert event["tool"] == "cards.get_card_details"
        assert event["requested_id"] == _FOREIGN_CARD_ID
        assert event["conversation_id"] == str(ctx.conversation_id)
        assert event["trace_id"] == ctx.trace_id

        with capture_logs() as logs:
            with pytest.raises(AccessDenied):
                await bank.search_transactions(TxFilter(card_id=_FOREIGN_CARD_ID))
        assert len(logs) == 1
        assert logs[0]["event"] == "tool.access_denied"
        assert logs[0]["tool"] == "transactions.search"
        assert logs[0]["requested_id"] == _FOREIGN_CARD_ID

        details = await bank.get_card_details(_OWN_CARD_ID)
        assert details.kind == "credit"
        assert details.last4 == "6475"

    asyncio.run(_run())
