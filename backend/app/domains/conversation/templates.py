"""Fixed ES/PT reply templates in Cardy's voice (D14, D15, `docs/brand.md`).

These strings are written by hand, never by the LLM, so `compose` skips
entirely for the routes that use them (`unsupported`, `fallback`, and the
`no_cards` outcome of `card_select`). Critical messages (confirmation,
verified result, escalation, tool error) come from here so Cardy can never
report an action that did not happen.

No template contains a digit. The ones that must carry a value
(`greeting_named`, `action_confirm`, `action_done`) use `{placeholder}` keys that code fills
with already-formatted values, the same way `compose` drafts are filled.
`get_template` returns the raw text; filling is the caller's job.

The PT texts are team-generated and pending review by a native speaker.
"""

from typing import Literal

__all__ = ["Language", "TemplateKind", "get_template"]

Language = Literal["es", "pt"]
TemplateKind = Literal[
    "greeting",
    "greeting_named",
    "out_of_market",
    "out_of_scope",
    "injection_suspected",
    "unsupported_intent",
    "fallback",
    "tool_error",
    "clarification_exhausted",
    "no_cards",
    "action_confirm",
    "action_done",
    "escalation_handoff",
    "session_expired",
]

_TEMPLATES: dict[TemplateKind, dict[Language, str]] = {
    # A lone greeting when the profile has the customer's first name.
    "greeting_named": {
        "es": "Hola, {customer_name}. Soy Cardy, de Swip. ¿Qué necesitas hoy con tu tarjeta?",
        "pt": "Oi, {customer_name}. Sou a Cardy, do Swip. Como posso ajudar com seu cartão hoje?",
    },
    # A lone greeting (intent `greeting`, nothing else asked), no name on file.
    "greeting": {
        "es": "Hola. Soy Cardy, de Swip. ¿Qué necesitas hoy con tu tarjeta?",
        "pt": "Oi. Sou a Cardy, do Swip. Como posso ajudar com seu cartão hoje?",
    },
    # D14: a real request, but for a rail/market Swip does not offer today.
    "out_of_market": {
        "es": (
            "Ese medio de pago no lo manejamos en Swip por ahora. "
            "Puedo ayudarte con tus tarjetas o conectarte con una persona del equipo."
        ),
        "pt": (
            "Essa forma de pagamento o Swip ainda não oferece. "
            "Posso ajudar com seus cartões ou te conectar com uma pessoa da equipe."
        ),
    },
    # D14: a real request, but for another product this chat does not cover.
    "out_of_scope": {
        "es": (
            "Eso no lo puedo gestionar por aquí. "
            "Puedo ayudarte con tus tarjetas o conectarte con una persona del equipo."
        ),
        "pt": (
            "Isso eu não consigo resolver por aqui. "
            "Posso ajudar com seus cartões ou te conectar com uma pessoa da equipe."
        ),
    },
    # D14: the message tried to redefine instructions or asked for someone else's data.
    "injection_suspected": {
        "es": (
            "Solo puedo ver y gestionar las tarjetas de la persona con la sesión activa. "
            "Si necesitas algo de otra cuenta, su titular debe escribirnos."
        ),
        "pt": (
            "Só posso ver e gerenciar os cartões da pessoa com a sessão ativa. "
            "Se precisar de algo de outra conta, o titular deve entrar em contato."
        ),
    },
    # D14: any intent other than card_status or a lone greeting.
    "unsupported_intent": {
        "es": (
            "Eso todavía no lo puedo gestionar por aquí. "
            "Puedo ayudarte con el estado de tus tarjetas o conectarte con una persona del equipo."
        ),
        "pt": (
            "Isso eu ainda não consigo resolver por aqui. "
            "Posso ajudar com o status dos seus cartões ou te conectar com uma pessoa da equipe."
        ),
    },
    # D15: LLMUnavailable or LLMInvalidOutput -- no tool was called.
    "fallback": {
        "es": (
            "Tuve un problema y no puedo responder eso ahora. No hice ningún cambio. "
            "¿Lo intento de nuevo o prefieres hablar con una persona?"
        ),
        "pt": (
            "Tive um problema e não consigo responder isso agora. Não fiz nenhuma alteração. "
            "Quer que eu tente de novo ou prefere falar com uma pessoa?"
        ),
    },
    # D15: ToolUnavailable while reading the card.
    "tool_error": {
        "es": (
            "No pude consultar el estado de tu tarjeta porque el sistema no respondió. "
            "No hice ningún cambio. ¿Lo intento de nuevo o prefieres hablar con una persona?"
        ),
        "pt": (
            "Não consegui consultar o status do seu cartão porque o sistema não respondeu. "
            "Não fiz nenhuma alteração. Quer que eu tente de novo ou prefere falar com uma pessoa?"
        ),
    },
    # D15: the card-choice question failed too many times. Offers a person
    # without claiming a transfer happened (the real handoff arrives with D4).
    "clarification_exhausted": {
        "es": (
            "No logré identificar de qué tarjeta me hablas. "
            "Una persona del equipo puede ayudarte a revisarlo."
        ),
        "pt": (
            "Não consegui identificar de qual cartão você está falando. "
            "Uma pessoa da equipe pode te ajudar a verificar."
        ),
    },
    # T6 NoCards: no hint, and zero cards pass the eligibility policy.
    "no_cards": {
        "es": "No encontré tarjetas activas asociadas a tu cuenta.",
        "pt": "Não encontrei cartões ativos associados à sua conta.",
    },
    # Not wired yet (card actions): before a side effect, with the fixed buttons.
    "action_confirm": {
        "es": ("Voy a {action} tu tarjeta terminada en {card_last4}. {effect} ¿Confirmas?"),
        "pt": "Vou {action} seu cartão final {card_last4}. {effect} Confirma?",
    },
    # Not wired yet: only after a verified tool read-back.
    "action_done": {
        "es": (
            "Listo: tu tarjeta terminada en {card_last4} quedó {result} a las {time}. "
            "Número de gestión: {reference}."
        ),
        "pt": (
            "Pronto: seu cartão final {card_last4} foi {result} às {time}. Protocolo: {reference}."
        ),
    },
    # Not wired yet (D4): only once the handoff is really created.
    "escalation_handoff": {
        "es": (
            "Esto lo debe revisar una persona del equipo. "
            "Ya le pasé todo lo que me contaste, así no tienes que repetirlo."
        ),
        "pt": (
            "Isso precisa ser analisado por uma pessoa da equipe. "
            "Já passei tudo o que você me contou, assim você não precisa repetir."
        ),
    },
    # Not wired yet (auth).
    "session_expired": {
        "es": (
            "Por seguridad tu sesión venció. Verifícate de nuevo con el código que te "
            "enviamos y seguimos donde quedamos."
        ),
        "pt": (
            "Por segurança, sua sessão expirou. Confirme sua identidade de novo com o "
            "código que enviamos e continuamos de onde paramos."
        ),
    },
}


def get_template(kind: TemplateKind, language: Language) -> str:
    """Look up the fixed reply for `(kind, language)` (D14, D15)."""
    return _TEMPLATES[kind][language]
