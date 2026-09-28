"""R4/R6 compose tests. See D10 and §"Test list" -> `test_compose.py`.

`ScriptedLLM` scripts the compose call's structured output; `compose_reply`
never touches a real LLM, FakeBank or graph state -- it takes `facts` as a
plain argument (D10).
"""

import asyncio
from datetime import date
from decimal import Decimal

from app.core.llm import LLMUnavailable
from app.domains.conversation.nodes.compose import ComposeDraft, compose_reply
from app.domains.conversation.state import Fact
from app.domains.conversation.templates import get_template
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


def test_facts_fenced_placeholders_filled_in_code() -> None:
    """R4, R6: fact keys (not values) reach the LLM; code fills every value.

    A draft with a raw digit or an unknown placeholder is rejected in code
    and replaced by the fallback template, same as an `LLMError`.
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
    assert call.prompt.label == "compose@v3"
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

    # An unknown placeholder -> the fallback template, no repair attempt.
    llm_unknown = ScriptedLLM({"compose": [ComposeDraft(text="Tu tarjeta es {mystery_key}.")]})
    reply_unknown = asyncio.run(
        compose_reply(
            llm_unknown, language="es", country="MX", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_unknown == get_template("fallback", "es")

    # A malformed placeholder (attribute access, not a bare `{key}`) doesn't
    # match the known-key regex either, so it must not fall through to
    # `str.format`-style substitution -> the fallback template.
    llm_malformed = ScriptedLLM({"compose": [ComposeDraft(text="Tu tarjeta {card_mask.upper}")]})
    reply_malformed = asyncio.run(
        compose_reply(
            llm_malformed, language="es", country="MX", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_malformed == get_template("fallback", "es")

    # A raw digit outside any placeholder -> the fallback template.
    llm_digit = ScriptedLLM(
        {"compose": [ComposeDraft(text="Tu tarjeta vence en 30 dias. Mira {expiry}.")]}
    )
    reply_digit = asyncio.run(
        compose_reply(
            llm_digit, language="pt", country="CO", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_digit == get_template("fallback", "pt")

    # `LLMError` (e.g. transport exhausted) -> the fallback template too.
    llm_unavailable = ScriptedLLM({"compose": [LLMUnavailable("boom")]})
    reply_unavailable = asyncio.run(
        compose_reply(
            llm_unavailable, language="es", country="AR", goal="card_status", facts=_CREDIT_FACTS
        )
    )
    assert reply_unavailable == get_template("fallback", "es")
