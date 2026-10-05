"""Staff-decision messages for card requests (D9-C, spec §8).

Templates live in `templates.py`; this module fills their placeholders in code
(R4: masks and money never come from the LLM) and posts the result as an agent
message only after a verified read-back (R3). The reason and field labels are
keyed by the codes in `policies/card_requests.yaml`; the policy supplies the
codes, the wording lives here next to the templates (R8: wording, not policy).
"""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.core import events
from app.domains.conversation.takeover import relay_agent_message
from app.domains.conversation.templates import Language, TemplateKind, get_template
from app.domains.localization.format import Country, format_money, mask_card

__all__ = [
    "CardKind",
    "Decision",
    "announce_decision",
    "balance_unavailable_text",
    "cancel_reason_label",
    "profile_field_label",
    "render_decision",
]

Decision = Literal["approve", "decline", "cancel", "keep", "not_cancelled_balance"]
CardKind = Literal["credit", "debit"]

_CANCEL_REASON_LABELS: dict[str, dict[Language, str]] = {
    "no_longer_needed": {"es": "Ya no la necesito", "pt": "Não preciso mais dele"},
    "high_cost": {"es": "Cuesta demasiado", "pt": "Custa caro demais"},
    "better_offer": {"es": "Encontré una mejor oferta", "pt": "Encontrei uma oferta melhor"},
    "too_many_cards": {"es": "Tengo demasiadas tarjetas", "pt": "Tenho cartões demais"},
    "bad_experience": {"es": "Tuve una mala experiencia", "pt": "Tive uma experiência ruim"},
    "other": {"es": "Otro motivo", "pt": "Outro motivo"},
}

_PROFILE_FIELD_LABELS: dict[str, dict[Language, str]] = {
    "email": {"es": "Correo electrónico", "pt": "E-mail"},
    "mobile_phone": {"es": "Celular", "pt": "Celular"},
    "address": {"es": "Dirección", "pt": "Endereço"},
    "occupation": {"es": "Ocupación", "pt": "Ocupação"},
    "estimated_monthly_income": {
        "es": "Ingreso mensual estimado",
        "pt": "Renda mensal estimada",
    },
}


_BALANCE_UNAVAILABLE: dict[Language, str] = {
    "es": "saldo no disponible",
    "pt": "saldo indisponível",
}


def balance_unavailable_text(language: Language) -> str:
    """Neutral wording for a card with no balance on record: never shown as zero."""
    return _BALANCE_UNAVAILABLE[language]


def cancel_reason_label(code: str, language: Language) -> str:
    """The customer-facing wording of a `cancel_reasons` code."""
    return _CANCEL_REASON_LABELS[code][language]


def profile_field_label(field: str, language: Language) -> str:
    """The wording of one of the five editable profile fields."""
    return _PROFILE_FIELD_LABELS[field][language]


def render_decision(
    decision: Decision,
    language: Language,
    *,
    last4: str,
    currency: str,
    country: Country,
    card_kind: CardKind,
    credit_limit: Decimal | None = None,
    balance: Decimal | None = None,
) -> str:
    """The decision template with every placeholder filled in code (R4)."""
    kind: TemplateKind
    if decision == "approve":
        kind = (
            "card_request_approved_credit"
            if card_kind == "credit"
            else "card_request_approved_debit"
        )
    elif decision == "decline":
        kind = "card_request_declined"
    elif decision == "cancel":
        kind = "card_request_cancelled"
    elif decision == "keep":
        kind = "card_request_kept"
    else:
        kind = (
            "card_request_not_cancelled_balance"
            if balance is not None
            else "card_request_not_cancelled_no_balance"
        )
    values: dict[str, str] = {"card_mask": mask_card(last4)}
    if credit_limit is not None:
        values["credit_limit"] = format_money(credit_limit, currency, country)
    if balance is not None:
        values["balance"] = format_money(balance, currency, country)
    return get_template(kind, language).format_map(values)


async def announce_decision(
    conversation_id: UUID,
    *,
    verified: bool,
    decision: Decision,
    text: str,
    agent_display_name: str,
) -> UUID | None:
    """Post the decision text once the read-back is verified; otherwise do nothing (R3).

    Approve and cancel also tell the customer UI that its cards changed.
    """
    if not verified:
        return None
    message_id = await relay_agent_message(conversation_id, text, agent_display_name)
    if decision in ("approve", "cancel"):
        await events.publish(conversation_id, "cards_changed", {})
    return message_id
