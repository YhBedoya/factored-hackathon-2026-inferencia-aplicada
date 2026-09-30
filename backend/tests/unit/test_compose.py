"""R4/R6 compose tests. See D10 and §"Test list" -> `test_compose.py`.

`ScriptedLLM` scripts the compose call's structured output; `compose_reply`
never touches a real LLM, FakeBank or graph state -- it takes `facts` as a
plain argument (D10).
"""

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from app.core.llm import LLMUnavailable
from app.domains.conversation.nodes.compose import ComposeDraft, compose_checked, compose_reply
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import Language, get_template
from tests.conftest import ScriptedLLM

_CREDIT_FACTS = [
    Fact(key="card_mask", value="6475", source="fakebank"),
    Fact(key="card_kind", value="credit", source="fakebank"),
    Fact(key="status", value="Active", source="fakebank"),
    Fact(key="expiry", value=date(2027, 3, 31), source="fakebank"),
    Fact(key="credit_limit", value=Decimal("50000.00"), source="fakebank"),
    Fact(key="available_credit", value=Decimal("12345.67"), source="fakebank"),
    Fact(key="currency", value="USD", source="fakebank"),
]

_CARD_STATUS_ES = get_template("goal_card_status", "es").format(
    card_kind="Crédito", card_mask="•••• 6475", status="Activa", expiry="31/03/2027"
)


def test_facts_fenced_placeholders_filled_in_code() -> None:
    """R4, R6: fact keys (not values) reach the LLM; code fills every value.

    A draft with a raw digit or an unknown placeholder is rejected in code,
    regenerated once, then replaced by the goal template; an `LLMError` gives
    the fallback template.
    """
    draft_text = (
        "Tu tarjeta {card_kind} {card_mask} esta {status} y vence el {expiry}. "
        "Limite {credit_limit}, disponible {available_credit}."
    )
    llm = ScriptedLLM({"compose": [ComposeDraft(text=draft_text)]})

    reply = asyncio.run(
        compose_reply(llm, language="es", country="MX", goal="card_status", facts=_CREDIT_FACTS)
    )

    # Code filled every placeholder in the account's country format (R4).
    assert reply == (
        "Tu tarjeta Crédito •••• 6475 esta Activa y vence el 31/03/2027. "
        "Limite US$50,000.00, disponible US$12,345.67."
    )

    # The call got the turn's goal/language and the fact **keys** fenced as
    # data, `currency` excluded (it is never offered as a placeholder), and
    # no tool binding at all -- `LLMClient.structured` (and its test double
    # `ScriptedLLM.structured`) simply has no parameter for one (R6).
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call.step == "compose"
    assert call.prompt.label == "compose@v7"
    assert call.schema is ComposeDraft
    assert "Idioma de la respuesta: es" in call.user
    assert "Objetivo: card_status" in call.user
    for key in (
        "card_mask",
        "card_kind",
        "status",
        "expiry",
        "credit_limit",
        "available_credit",
    ):
        assert key in call.user
    assert "currency" not in call.user

    # No fact *value* -- raw or formatted -- ever reached the system/user
    # text sent to the LLM (R6). The fenced user message carries only key
    # names, so it has no digit at all.
    assert not any(char.isdigit() for char in call.user)
    for leaked in ("6475", "2027", "50000", "12345.67", "Activa", "•••• 6475"):
        assert leaked not in call.system
        assert leaked not in call.user

    # An unknown placeholder twice -> the goal template, filled in code.
    llm_unknown = ScriptedLLM({"compose": [ComposeDraft(text="Tu tarjeta es {mystery_key}.")] * 2})
    reply_unknown = asyncio.run(
        compose_reply(
            llm_unknown, language="es", country="MX", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_unknown == _CARD_STATUS_ES

    # A malformed placeholder (attribute access, not a bare `{key}`) doesn't
    # match the known-key regex either, so it must not fall through to
    # `str.format`-style substitution -> the fallback template.
    llm_malformed = ScriptedLLM(
        {"compose": [ComposeDraft(text="Tu tarjeta {card_mask.upper}")] * 2}
    )
    reply_malformed = asyncio.run(
        compose_reply(
            llm_malformed, language="es", country="MX", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_malformed == _CARD_STATUS_ES

    # A raw digit outside any placeholder -> the fallback template.
    llm_digit = ScriptedLLM(
        {"compose": [ComposeDraft(text="Tu tarjeta vence en 30 dias. Mira {expiry}.")] * 2}
    )
    reply_digit = asyncio.run(
        compose_reply(
            llm_digit, language="pt", country="CO", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_digit == get_template("goal_card_status", "pt").format(
        card_kind="Crédito", card_mask="•••• 6475", status="Ativo", expiry="31/03/2027"
    )

    # `LLMError` (e.g. transport exhausted) -> the fallback template too.
    llm_unavailable = ScriptedLLM({"compose": [LLMUnavailable("boom")]})
    reply_unavailable = asyncio.run(
        compose_reply(
            llm_unavailable, language="es", country="AR", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_unavailable == get_template("fallback", "es")


_BALANCE_FACTS = [
    Fact(key="current_balance", value=Decimal("1234.50"), source="fakebank"),
    Fact(key="min_payment", value=Decimal("61.73"), source="policy"),
    Fact(key="due_date", value=date(2026, 10, 5), source="policy"),
    Fact(key="currency", value="USD", source="fakebank"),
]


def test_wrong_amount_regenerated_then_template() -> None:
    """R4, R11: a raw amount twice -> exactly 2 calls, then the goal template, filled in code."""
    bad = ComposeDraft(text="Tu saldo es 999.99 dolares.")
    llm = ScriptedLLM({"compose": [bad, bad]})

    text, outcome = asyncio.run(
        compose_checked(llm, language="es", country="MX", goal="balance_due", facts=_BALANCE_FACTS)
    )

    assert len(llm.calls) == 2
    assert "999.99" not in llm.calls[1].user
    assert "numero" in llm.calls[1].user  # the reason rode along on the retry
    assert outcome == "template"
    assert text == get_template("goal_balance_due", "es").format(
        current_balance="US$1,234.50", min_payment="US$61.73", due_date="05/10/2026"
    )
    assert "999.99" not in text


def test_wrong_language_regenerated() -> None:
    """D11: on a PT turn an ES draft is regenerated; the PT draft is sent."""
    es = ComposeDraft(text="Tu tarjeta {card_mask} esta {status} y vence el {expiry}.")
    pt = ComposeDraft(text="Seu cartão {card_mask} está {status} e vence em {expiry}.")
    llm = ScriptedLLM({"compose": [es, pt]})

    text, outcome = asyncio.run(
        compose_checked(llm, language="pt", country="CO", goal="card_status", facts=_CREDIT_FACTS)
    )

    assert len(llm.calls) == 2
    assert outcome == "regenerated"
    assert text.startswith("Seu cartão") and "{" not in text


@pytest.mark.parametrize("language", ["es", "pt"])
def test_decline_explain_grounding_falls_back_to_goal_template(language: Language) -> None:
    """D5-B D4: two ungrounded drafts -> the goal template, filled from policy labels."""
    facts = [
        Fact(key="decline_cause", value="insufficient_funds", source="fakebank"),
        Fact(key="decline_next_step", value="pay_or_use_other_card", source="fakebank"),
    ]
    bad = ComposeDraft(text="Rechazada por 999 motivos.")
    llm = ScriptedLLM({"compose": [bad, bad]})

    text, outcome = asyncio.run(
        compose_checked(llm, language=language, country="MX", goal="decline_explain", facts=facts)
    )

    assert len(llm.calls) == 2
    assert outcome == "template"
    assert text == get_template("goal_decline_explain", language).format(
        decline_cause=get_template("decline_cause_insufficient_funds", language),
        decline_next_step=get_template("decline_next_pay_or_use_other_card", language),
    )
    assert ".." not in text
    assert text != get_template("fallback", language)
