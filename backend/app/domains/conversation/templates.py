"""Fixed ES/PT reply templates for routes with no LLM call (D14, D15).

These strings are written by hand, never by the LLM, so `compose` skips
entirely for the routes that use them (`unsupported`, `fallback`, and the
`no_cards` outcome of `card_select`). Every template is plain prose with no
digits, since none of them ever needs to carry a formatted value.
"""

from typing import Literal

__all__ = ["Language", "TemplateKind", "get_template"]

Language = Literal["es", "pt"]
TemplateKind = Literal[
    "out_of_market",
    "out_of_scope",
    "injection_suspected",
    "unsupported_intent",
    "fallback",
    "no_cards",
]

_TEMPLATES: dict[TemplateKind, dict[Language, str]] = {
    # D14: a real request, but for a rail/market this bank does not offer today.
    "out_of_market": {
        "es": (
            "Por ahora no manejamos ese medio de pago en este chat. "
            "Te puedo ayudar con el estado de tus tarjetas de este banco."
        ),
        "pt": (
            "Por enquanto nao trabalhamos com essa forma de pagamento neste chat. "
            "Posso ajudar com o status dos seus cartoes deste banco."
        ),
    },
    # D14: a real request, but for another product this chat does not cover.
    "out_of_scope": {
        "es": (
            "Ese tema no es parte del soporte de tarjetas que puedo darte por aca. "
            "Te puedo ayudar con el estado de tus tarjetas."
        ),
        "pt": (
            "Esse assunto nao faz parte do suporte de cartoes que posso oferecer por aqui. "
            "Posso ajudar com o status dos seus cartoes."
        ),
    },
    # D14: the message tried to redefine instructions or asked for someone else's data.
    "injection_suspected": {
        "es": "No puedo ayudarte con ese pedido. Te puedo ayudar con el estado de tus tarjetas.",
        "pt": "Nao posso ajudar com esse pedido. Posso ajudar com o status dos seus cartoes.",
    },
    # D14: any intent other than card_status, including a lone greeting.
    "unsupported_intent": {
        "es": (
            "Todavia no puedo resolver ese pedido por este chat. "
            "Te puedo ayudar con el estado de tus tarjetas."
        ),
        "pt": (
            "Ainda nao consigo resolver esse pedido por este chat. "
            "Posso ajudar com o status dos seus cartoes."
        ),
    },
    # D15: LLMUnavailable, LLMInvalidOutput, ToolUnavailable or clarification exhausted.
    "fallback": {
        "es": (
            "Hubo un problema y no puedo responder ese pedido ahora mismo. "
            "Un asesor humano te puede ayudar en breve."
        ),
        "pt": (
            "Houve um problema e nao consigo responder esse pedido agora. "
            "Um atendente humano vai te ajudar em breve."
        ),
    },
    # T6 NoCards: no hint, and zero cards pass the eligibility policy.
    "no_cards": {
        "es": "No encontramos tarjetas activas asociadas a tu cuenta.",
        "pt": "Nao encontramos cartoes ativos associados a sua conta.",
    },
}


def get_template(kind: TemplateKind, language: Language) -> str:
    """Look up the fixed reply for `(kind, language)` (D14, D15)."""
    return _TEMPLATES[kind][language]
