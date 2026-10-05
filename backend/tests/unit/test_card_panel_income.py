"""D9-C spec AS6: the staff panel shows declared income in the local currency (MX -> MXN),
not the card currency (MX -> USD). Repository and customers reads are stubbed."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domains.cards import service
from app.domains.cards.schemas import CardRequestView
from app.domains.customers.schemas import DecisionProfile


def test_mx_income_display_is_mxn_not_usd(monkeypatch: pytest.MonkeyPatch) -> None:
    rid = uuid4()
    view = CardRequestView(
        id=rid, reference="CRQ-TEST", customer_id="CLI-X", conversation_id=uuid4(),
        handoff_id=None, kind="open", card_kind="credit", product_id=None, reason_code=None,
        changed_fields=[], status="pending", decision=None, decline_reason=None,
        credit_limit=None, agent_id=None, decided_at=None, created_at=datetime.now(UTC),
    )  # fmt: skip
    profile = DecisionProfile(
        credit_score=700.0, segment="A", tenure_years=3, occupation="x",
        estimated_monthly_income=Decimal("19006.76"), country="MX",
    )  # fmt: skip

    async def get_request(_: object) -> CardRequestView:
        return view

    async def get_profile(_: str) -> DecisionProfile:
        return profile

    async def no_changes(_: str) -> set[str]:
        return set()

    async def no_cards(_: str) -> list[object]:
        return []

    monkeypatch.setattr(service, "get_request", get_request)
    monkeypatch.setattr(service.customers_service, "get_decision_profile", get_profile)
    monkeypatch.setattr(service.customers_service, "changed_fields_for_request", no_changes)
    monkeypatch.setattr(service.repository, "fetch_customer_cards_panel", no_cards)
    panel = asyncio.run(service.build_panel(rid, "es"))
    assert panel.customer.income_display is not None
    assert panel.customer.income_display.startswith("MXN")
    assert "US$" not in panel.customer.income_display
