"""Decision messages (D9-C spec T15, T16): R3 posting gate and R4 formatting in code."""

import asyncio
import re
from decimal import Decimal
from uuid import uuid4

import pytest

from app.domains.conversation import card_request_messages as crm
from app.domains.conversation.card_request_messages import Decision
from app.domains.localization.format import Country, Language, format_money, mask_card


def test_decision_message_only_after_verified_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relayed: list[str] = []
    published: list[tuple[str, object]] = []

    async def fake_relay(conversation_id, text, agent_display_name):  # type: ignore[no-untyped-def]
        relayed.append(text)
        return uuid4()

    async def fake_publish(conversation_id, event, data):  # type: ignore[no-untyped-def]
        published.append((event, data))

    monkeypatch.setattr(crm, "relay_agent_message", fake_relay)
    monkeypatch.setattr(crm.events, "publish", fake_publish)
    conv = uuid4()

    async def run(verified: bool, decision: Decision):  # type: ignore[no-untyped-def]
        return await crm.announce_decision(
            conv, verified=verified, decision=decision, text="hi", agent_display_name="Ana"
        )

    def call(verified: bool, decision: Decision):  # type: ignore[no-untyped-def]
        return asyncio.run(run(verified, decision))

    assert call(False, "approve") is None
    assert relayed == [] and published == []

    assert call(True, "approve") is not None
    assert relayed == ["hi"] and published == [("cards_changed", {})]

    relayed.clear()
    published.clear()
    assert call(True, "keep") is not None
    assert relayed == ["hi"] and published == []


@pytest.mark.parametrize("language", ["es", "pt"])
def test_decision_templates_fill_in_code(language: Language) -> None:
    cases: list[tuple[str, Country, str, Decimal, Decimal]] = [
        ("1234", "MX", "USD", Decimal("5000"), Decimal("120.50")),
        ("9876", "CO", "COP", Decimal("8000000"), Decimal("350000")),
    ]
    for last4, country, currency, limit, balance in cases:
        for decision, card_kind in (
            ("approve", "debit"),
            ("approve", "credit"),
            ("decline", "debit"),
            ("cancel", "credit"),
            ("keep", "credit"),
            ("not_cancelled_balance", "credit"),
        ):
            text = crm.render_decision(
                decision,  # type: ignore[arg-type]
                language,
                last4=last4,
                currency=currency,
                country=country,
                card_kind=card_kind,  # type: ignore[arg-type]
                credit_limit=limit,
                balance=balance,
            )
            assert not re.search(r"[{}]", text), text
            if decision != "decline":
                assert mask_card(last4) in text
            if (decision, card_kind) == ("approve", "credit"):
                assert format_money(limit, currency, country) in text
            if decision == "not_cancelled_balance":
                assert format_money(balance, currency, country) in text


@pytest.mark.parametrize("language", ["es", "pt"])
def test_not_cancelled_balance_without_balance_uses_neutral_wording(language: Language) -> None:
    text = crm.render_decision(
        "not_cancelled_balance",
        language,
        last4="1234",
        currency="USD",
        country="MX",
        card_kind="credit",
        balance=None,
    )
    expected = {
        "es": (
            "Todavía no podemos cancelar tu tarjeta •••• 1234: no pudimos confirmar su saldo. "
            "Escríbenos y lo revisamos."
        ),
        "pt": (
            "Ainda não podemos cancelar o seu cartão •••• 1234: não conseguimos confirmar o "
            "saldo. Fale com a gente e nós verificamos."
        ),
    }
    assert text == expected[language]
    assert "saldo de saldo" not in text
