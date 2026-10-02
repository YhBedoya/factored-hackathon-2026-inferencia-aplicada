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

import random
from typing import Literal, Protocol

__all__ = [
    "WELCOME_BODIES",
    "WELCOME_SALUTATIONS",
    "Language",
    "TemplateKind",
    "get_template",
    "template_variants",
]

Language = Literal["es", "pt"]
TemplateKind = Literal[
    "greeting",
    "greeting_named",
    "injection_suspected",
    "unsupported_intent",
    "unsupported_language",
    "fallback",
    "tool_error",
    "clarification_exhausted",
    "no_cards",
    "action_confirm",
    "action_done",
    "escalation_handoff",
    "session_expired",
    "thanks_close",
    "anything_else",
    "ask_what_else",
    "farewell",
    "pending_reminder",
    "nothing_pending",
    "ask_which_card_status",
    "ask_which_card_balance",
    "ask_which_card_block",
    "ask_which_card_unlock",
    "ask_which_card_replacement",
    "clarify_lock_vs_block",
    "already_in_state",
    "action_cancelled",
    "action_done_noref",
    "otp_required",
    "address_confirm",
    "address_ask",
    "not_blocked",
    "block_permanent_no_undo",
    "offer_replacement",
    "offer_unlock",
    "offer_human",
    "replacement_needs_block",
    "new_card_not_available",
    "closing_suggest_transaction_search",
    "closing_suggest_unrecognized_charge",
    "closing_generic",
    "greeting_again",
    "greeting_again_plain",
    "block_none_eligible",
    "replacement_declined",
    "replacement_not_eligible",
    "synthetic_footnote",
    "read_only_note",
    "handoff_transfer",
    "failure_handoff",
    "failure_handoff_after_action",
    "back_with_cardy",
    "abstain_fallback",
    "goal_card_status",
    "goal_balance_due",
    "goal_debit_balance",
    "goal_decline_explain",
    "ask_which_card_dispute",
    "dispute_no_transactions",
    "dispute_transactions_prompt",
    "dispute_q_card_in_possession",
    "dispute_q_contacted_merchant",
    "dispute_confirm_compromise",
    "dispute_confirm_claim",
    "dispute_block_refused_offer_claim",
    "dispute_claim_opened",
    "dispute_claim_opened_single",
    "dispute_handoff_no_claim",
    "dispute_open_question_card_active",
    "dispute_open_question_claim_refused",
    "ask_which_card_decline",
    "decline_none",
    "decline_unknown",
    "decline_pick_ask",
    "decline_replacement_option",
    "decline_cause_insufficient_funds",
    "decline_cause_invalid_card_number",
    "decline_cause_do_not_honor",
    "decline_cause_expired_card",
    "decline_next_pay_or_use_other_card",
    "decline_next_check_card_number",
    "decline_next_contact_or_retry",
    "decline_next_offer_replacement",
    "tx_search_ask_criterion",
    "tx_search_pick_ask",
    "tx_search_none",
    "tx_explain_pick_ask",
    "tx_explain_none",
    "tx_human_option",
    "goal_tx_explain",
    "goal_tx_details",
    "tx_cause_pending_hold",
    "tx_cause_reversed_charge",
    "tx_next_wait_until_date",
    "tx_next_offer_human",
    "tx_next_no_action_needed",
    "priority_flag_repeat_complainer",
    "priority_flag_open_critical",
    "priority_flag_amount_over_threshold",
]

# A value is one text, or a list of interchangeable variants (naturalidad-cardy D12):
# `get_template` picks one, so every variant of a kind must share the same
# `{placeholders}` and carry no digit.
_TEMPLATES: dict[TemplateKind, dict[Language, str | list[str]]] = {
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
    # D14: the message tried to redefine instructions or asked for someone else's data.
    "injection_suspected": {
        "es": [
            (
                "Solo puedo ver y gestionar las tarjetas de la persona con la sesión activa. "
                "Si necesitas algo de otra cuenta, su titular debe escribirnos."
            ),
            (
                "Aquí solo puedo trabajar con las tarjetas de quien tiene la sesión activa. "
                "Si lo tuyo es de otra cuenta, su titular debe escribirnos."
            ),
            (
                "Solo gestiono las tarjetas de la persona que inició la sesión. Si necesitas "
                "algo de otra cuenta, su titular debe contactarnos."
            ),
        ],
        "pt": [
            (
                "Só posso ver e gerenciar os cartões da pessoa com a sessão ativa. Se "
                "precisar de algo de outra conta, o titular deve entrar em contato."
            ),
            (
                "Aqui só posso trabalhar com os cartões de quem está com a sessão ativa. Se "
                "for algo de outra conta, o titular deve entrar em contato."
            ),
            (
                "Só gerencio os cartões da pessoa que iniciou a sessão. Se precisar de algo "
                "de outra conta, o titular deve falar com a gente."
            ),
        ],
    },
    # The message is in neither Spanish nor Portuguese. The customer may read
    # either language, so both texts carry both versions, own language first.
    "unsupported_language": {
        "es": (
            "Solo puedo ayudarte en español o portugués. ¿Me escribes en alguno de los dos? / "
            "Só posso ajudar em espanhol ou português. Pode me escrever em um dos dois?"
        ),
        "pt": (
            "Só posso ajudar em espanhol ou português. Pode me escrever em um dos dois? / "
            "Solo puedo ayudarte en español o portugués. ¿Me escribes en alguno de los dos?"
        ),
    },
    # D14: any intent other than card_status or a lone greeting.
    "unsupported_intent": {
        "es": [
            (
                "Eso todavía no lo puedo gestionar por aquí. Puedo ayudarte con el estado de "
                "tus tarjetas o conectarte con una persona del equipo."
            ),
            (
                "Eso aún no lo resuelvo por este chat. Sí puedo ayudarte con tus tarjetas o "
                "conectarte con una persona del equipo."
            ),
            (
                "Por ahora eso no lo puedo hacer desde aquí. Puedo revisar tus tarjetas o "
                "pasarte con una persona del equipo."
            ),
        ],
        "pt": [
            (
                "Isso eu ainda não consigo resolver por aqui. Posso ajudar com o status dos "
                "seus cartões ou te conectar com uma pessoa da equipe."
            ),
            (
                "Isso eu ainda não resolvo por este chat. Posso ajudar com seus cartões ou te "
                "conectar com uma pessoa da equipe."
            ),
            (
                "Por enquanto isso não consigo fazer daqui. Posso verificar seus cartões ou "
                "passar você para uma pessoa da equipe."
            ),
        ],
    },
    # D15: LLMUnavailable or LLMInvalidOutput -- no tool was called.
    "fallback": {
        "es": [
            (
                "Tuve un problema y no puedo responder eso ahora. No hice ningún cambio. ¿Lo "
                "intento de nuevo o prefieres hablar con una persona?"
            ),
            (
                "Algo falló de mi lado y no logré responderte. No hice ningún cambio. "
                "¿Quieres que lo intente otra vez o prefieres hablar con una persona?"
            ),
            (
                "Perdona, tuve un inconveniente y no pude responder eso. No cambié nada. ¿Lo "
                "intento de nuevo o te paso con una persona?"
            ),
        ],
        "pt": [
            (
                "Tive um problema e não consigo responder isso agora. Não fiz nenhuma "
                "alteração. Quer que eu tente de novo ou prefere falar com uma pessoa?"
            ),
            (
                "Algo falhou do meu lado e não consegui responder. Não fiz nenhuma alteração. "
                "Quer que eu tente outra vez ou prefere falar com uma pessoa?"
            ),
            (
                "Desculpe, tive um imprevisto e não consegui responder isso. Não mudei nada. "
                "Tento de novo ou passo você para uma pessoa?"
            ),
        ],
    },
    # D15: ToolUnavailable while reading the card.
    "tool_error": {
        "es": [
            (
                "No pude consultar el estado de tu tarjeta porque el sistema no respondió. No "
                "hice ningún cambio. ¿Lo intento de nuevo o prefieres hablar con una persona?"
            ),
            (
                "El sistema no me respondió y no pude revisar tu tarjeta. No hice ningún "
                "cambio. ¿Quieres que lo intente otra vez o prefieres hablar con una persona?"
            ),
            (
                "No logré consultar tu tarjeta porque el sistema no respondió. No cambié "
                "nada. ¿Lo intento de nuevo o te paso con una persona?"
            ),
        ],
        "pt": [
            (
                "Não consegui consultar o status do seu cartão porque o sistema não "
                "respondeu. Não fiz nenhuma alteração. Quer que eu tente de novo ou prefere "
                "falar com uma pessoa?"
            ),
            (
                "O sistema não me respondeu e não consegui verificar seu cartão. Não fiz "
                "nenhuma alteração. Quer que eu tente outra vez ou prefere falar com uma "
                "pessoa?"
            ),
            (
                "Não consegui consultar seu cartão porque o sistema não respondeu. Não mudei "
                "nada. Tento de novo ou passo você para uma pessoa?"
            ),
        ],
    },
    # D15: the card-choice question failed too many times. Offers a person
    # without claiming a transfer happened (the real handoff arrives with D4).
    "clarification_exhausted": {
        "es": [
            (
                "No logré identificar de qué tarjeta me hablas. Una persona del equipo puede "
                "ayudarte a revisarlo."
            ),
            (
                "Sigo sin tener claro de cuál tarjeta hablas. Una persona del equipo puede "
                "ayudarte a revisarlo."
            ),
            (
                "No pude identificar la tarjeta de la que me hablas. Mejor lo revisa una "
                "persona del equipo contigo."
            ),
        ],
        "pt": [
            (
                "Não consegui identificar de qual cartão você está falando. Uma pessoa da "
                "equipe pode te ajudar a verificar."
            ),
            (
                "Continuo sem saber de qual cartão você fala. Uma pessoa da equipe pode te "
                "ajudar a verificar."
            ),
            (
                "Não consegui identificar o cartão de que você fala. Melhor uma pessoa da "
                "equipe revisar isso com você."
            ),
        ],
    },
    # T6 NoCards: no hint, and zero cards pass the eligibility policy.
    "no_cards": {
        "es": [
            "Revisé y no encontré tarjetas activas asociadas a tu cuenta.",
            "Por ahora no veo tarjetas activas en tu cuenta.",
            "No hay tarjetas activas asociadas a tu cuenta en este momento.",
        ],
        "pt": [
            "Verifiquei e não encontrei cartões ativos associados à sua conta.",
            "Por enquanto não vejo cartões ativos na sua conta.",
            "Não há cartões ativos associados à sua conta neste momento.",
        ],
    },
    # Not wired yet (card actions): before a side effect, with the fixed buttons.
    "action_confirm": {
        "es": [
            "Voy a {action} tu tarjeta que termina en {card_last4}. {effect} ¿Confirmas?",
            (
                "Con tu confirmación, voy a {action} tu tarjeta que termina en {card_last4}. "
                "{effect} ¿Lo hago?"
            ),
            (
                "Esto es lo que haré: {action} tu tarjeta que termina en {card_last4}. {effect} "
                "¿Me confirmas?"
            ),
        ],
        "pt": [
            "Vou {action} seu cartão final {card_last4}. {effect} Confirma?",
            (
                "Com a sua confirmação, vou {action} seu cartão final {card_last4}. {effect} "
                "Posso fazer?"
            ),
            (
                "Isto é o que vou fazer: {action} seu cartão final {card_last4}. {effect} "
                "Você confirma?"
            ),
        ],
    },
    # Not wired yet: only after a verified tool read-back.
    "action_done": {
        "es": [
            (
                "Listo: tu tarjeta que termina en {card_last4} quedó {result} a las {time}. "
                "Número de gestión: {reference}."
            ),
            (
                "Hecho: tu tarjeta que termina en {card_last4} quedó {result} a las {time}. Tu "
                "número de gestión es {reference}."
            ),
            (
                "Ya quedó: tu tarjeta que termina en {card_last4} está {result} desde las "
                "{time}. Gestión: {reference}."
            ),
        ],
        "pt": [
            "Pronto: seu cartão final {card_last4} foi {result} às {time}. Protocolo: {reference}.",
            (
                "Feito: seu cartão final {card_last4} ficou {result} às {time}. Seu protocolo "
                "é {reference}."
            ),
            (
                "Já está: seu cartão final {card_last4} está {result} desde as {time}. "
                "Protocolo: {reference}."
            ),
        ],
    },
    # Not wired yet (D4): only once the handoff is really created.
    "escalation_handoff": {
        "es": [
            (
                "Esto lo debe revisar una persona del equipo. Ya le pasé todo lo que me "
                "contaste, así no tienes que repetirlo."
            ),
            (
                "Esto lo tiene que ver una persona del equipo. Ya le compartí lo que me "
                "contaste para que no lo repitas."
            ),
            (
                "Una persona del equipo va a revisar esto. Ya tiene todo lo que me contaste, "
                "no tendrás que repetirlo."
            ),
        ],
        "pt": [
            (
                "Isso precisa ser analisado por uma pessoa da equipe. Já passei tudo o que "
                "você me contou, assim você não precisa repetir."
            ),
            (
                "Isso precisa ser visto por uma pessoa da equipe. Já compartilhei o que você "
                "me contou para você não repetir."
            ),
            (
                "Uma pessoa da equipe vai analisar isso. Ela já tem tudo o que você me "
                "contou, você não precisará repetir."
            ),
        ],
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
    # D16: thanks with nothing pending. Kept for callers that only need the
    # acknowledgement; `smalltalk` itself now answers with `anything_else`.
    "thanks_close": {
        "es": "¡Con mucho gusto! Aquí estoy si necesitas algo más con tu tarjeta.",
        "pt": "Com muito prazer! Estou por aqui se precisar de mais alguma coisa com seu cartão.",
    },
    # Thanks (or a bare "no") with nothing pending: ask before closing, and
    # `smalltalk` opens the `anything_else` pause so the answer can close it.
    "anything_else": {
        "es": [
            "¡Con gusto! ¿Te puedo ayudar en algo más?",
            "¡Para eso estoy! ¿Necesitas algo más?",
            "Con mucho gusto. ¿Hay algo más en lo que te ayude?",
        ],
        "pt": [
            "Por nada! Posso te ajudar em mais alguma coisa?",
            "É para isso que estou aqui! Precisa de mais alguma coisa?",
            "Com muito prazer. Há mais alguma coisa em que eu ajude?",
        ],
    },
    # A bare "sí" with nothing pending, or "sí" to `anything_else`.
    "ask_what_else": {
        "es": [
            "Claro, cuéntame. ¿En qué más te ayudo con tu tarjeta?",
            "Dime, ¿qué más necesitas con tus tarjetas?",
            "Con gusto. ¿Qué más quieres resolver con tu tarjeta?",
        ],
        "pt": [
            "Claro, me conta. Em que mais posso ajudar com seu cartão?",
            "Diga, do que mais você precisa com seus cartões?",
            "Com prazer. O que mais você quer resolver com seu cartão?",
        ],
    },
    # "No"/thanks/goodbye to `anything_else`: the conversation ends here.
    "farewell": {
        "es": [
            "Gracias por escribirnos. Que tengas un buen día.",
            "Gracias por escribir a Swip. ¡Que te vaya muy bien!",
            "Fue un gusto ayudarte. Que tengas un excelente día.",
        ],
        "pt": [
            "Obrigada por falar com a gente. Tenha um ótimo dia.",
            "Obrigada por escrever para a Swip. Tudo de bom para você!",
            "Foi um prazer ajudar. Tenha um excelente dia.",
        ],
    },
    # Small talk while a flow is still waiting on an answer (not OTP).
    "pending_reminder": {
        "es": [
            (
                "Todavía necesito tu respuesta a mi pregunta anterior para seguir. Si "
                "prefieres dejarlo así, dime cancelar."
            ),
            (
                "Para continuar necesito que me respondas lo que te pregunté antes. Si "
                "prefieres parar, dime cancelar."
            ),
            (
                "Sigo esperando tu respuesta a mi pregunta anterior. Si quieres dejarlo así, "
                "dime cancelar."
            ),
        ],
        "pt": [
            (
                "Ainda preciso da sua resposta à minha pergunta anterior para continuar. Se "
                "preferir deixar assim, é só dizer cancelar."
            ),
            (
                "Para continuar preciso que você responda o que perguntei antes. Se preferir "
                "parar, é só dizer cancelar."
            ),
            (
                "Continuo esperando sua resposta à minha pergunta anterior. Se quiser deixar "
                "assim, é só dizer cancelar."
            ),
        ],
    },
    # D16: a button confirmation that matches no open plan (stale token).
    "nothing_pending": {
        "es": [
            "No tengo ninguna acción pendiente por confirmar. ¿En qué más te ayudo?",
            "No hay nada pendiente por confirmar en este momento. ¿Qué necesitas?",
            "Ahora mismo no tengo ninguna acción esperando tu confirmación. ¿En qué te ayudo?",
        ],
        "pt": [
            "Não tenho nenhuma ação pendente para confirmar. Em que mais posso ajudar?",
            "Não há nada pendente para confirmar neste momento. Do que você precisa?",
            "Agora não tenho nenhuma ação aguardando sua confirmação. Em que posso ajudar?",
        ],
    },
    # D12: which card, per action. `{card_options}` is `select_card`'s
    # newline-joined masked list, formatted in code (R4).
    "ask_which_card_status": {
        "es": [
            "¿Sobre cuál tarjeta quieres saber?",
            "¿De cuál de tus tarjetas quieres información?",
            "¿Cuál tarjeta quieres que revise?",
        ],
        "pt": [
            "Sobre qual cartão você quer saber?",
            "De qual dos seus cartões você quer informações?",
            "Qual cartão você quer que eu verifique?",
        ],
    },
    "ask_which_card_balance": {
        "es": [
            "¿De cuál tarjeta quieres ver el saldo?",
            "¿El saldo de cuál tarjeta quieres consultar?",
            "¿Cuál tarjeta quieres que revise para el saldo?",
        ],
        "pt": [
            "De qual cartão você quer ver o saldo?",
            "O saldo de qual cartão você quer consultar?",
            "Qual cartão você quer que eu verifique para o saldo?",
        ],
    },
    "ask_which_card_block": {
        "es": [
            "¿Cuál tarjeta quieres bloquear?",
            "¿Cuál de tus tarjetas quieres bloquear?",
            "¿Qué tarjeta bloqueamos?",
        ],
        "pt": [
            "Qual cartão você quer bloquear?",
            "Qual dos seus cartões você quer bloquear?",
            "Qual cartão bloqueamos?",
        ],
    },
    "ask_which_card_unlock": {
        "es": [
            "¿Cuál tarjeta quieres desbloquear?",
            "¿Cuál de tus tarjetas quieres desbloquear?",
            "¿Qué tarjeta desbloqueamos?",
        ],
        "pt": [
            "Qual cartão você quer desbloquear?",
            "Qual dos seus cartões você quer desbloquear?",
            "Qual cartão desbloqueamos?",
        ],
    },
    "ask_which_card_replacement": {
        "es": [
            "¿Cuál tarjeta quieres reponer?",
            "¿Cuál de tus tarjetas quieres reemplazar?",
            "¿Qué tarjeta reponemos?",
        ],
        "pt": [
            "Qual cartão você quer substituir?",
            "Qual dos seus cartões você quer substituir?",
            "Qual cartão substituímos?",
        ],
    },
    # D11: card_block needs to know which kind before it can plan anything.
    "clarify_lock_vs_block": {
        "es": [
            (
                "¿Quieres bloquear tu tarjeta de forma temporal, para poder desbloquearla "
                "después, o reportarla como perdida o robada con un bloqueo permanente?"
            ),
            (
                "¿Prefieres un bloqueo temporal, que luego puedes quitar, o reportarla como "
                "perdida o robada con un bloqueo permanente?"
            ),
            (
                "¿Será un bloqueo temporal, que se puede deshacer, o un reporte de pérdida o "
                "robo con bloqueo permanente?"
            ),
        ],
        "pt": [
            (
                "Você quer bloquear seu cartão temporariamente, podendo desbloqueá-lo depois, "
                "ou reportá-lo como perdido ou roubado com um bloqueio permanente?"
            ),
            (
                "Prefere um bloqueio temporário, que depois você pode retirar, ou reportá-lo "
                "como perdido ou roubado com bloqueio permanente?"
            ),
            (
                "Será um bloqueio temporário, que pode ser desfeito, ou um reporte de perda "
                "ou roubo com bloqueio permanente?"
            ),
        ],
    },
    # D11: card_block/card_unlock, the card is already in the requested state.
    "already_in_state": {
        "es": [
            "Tu tarjeta que termina en {card_last4} ya está {state}. No hice ningún cambio.",
            "Tu tarjeta que termina en {card_last4} ya estaba {state}, así que no cambié nada.",
            "Veo que tu tarjeta que termina en {card_last4} ya está {state}. No cambié nada.",
        ],
        "pt": [
            "Seu cartão final {card_last4} já está {state}. Não fiz nenhuma alteração.",
            "Seu cartão final {card_last4} já estava {state}, então não mudei nada.",
            "Vejo que seu cartão final {card_last4} já está {state}. Não fiz nenhuma alteração.",
        ],
    },
    # D14: a typed "no" or /cancel on a pending plan. Nothing ran.
    "action_cancelled": {
        "es": [
            "Cancelé la solicitud. No hice ningún cambio en tu tarjeta.",
            "Listo, cancelé la solicitud. Tu tarjeta sigue igual.",
            "Entendido, no sigo con eso. No cambié nada en tu tarjeta.",
        ],
        "pt": [
            "Cancelei a solicitação. Não fiz nenhuma alteração no seu cartão.",
            "Pronto, cancelei a solicitação. Seu cartão continua igual.",
            "Entendido, não sigo com isso. Não mudei nada no seu cartão.",
        ],
    },
    # D17: action_done without a reference (lock, unlock, block), until
    # audit_event_id exists.
    "action_done_noref": {
        "es": [
            "Listo: tu tarjeta que termina en {card_last4} quedó {result} a las {time}.",
            "Hecho: tu tarjeta que termina en {card_last4} quedó {result} a las {time}.",
            "Ya quedó: tu tarjeta que termina en {card_last4} está {result} desde las {time}.",
        ],
        "pt": [
            "Pronto: seu cartão final {card_last4} ficou {result} às {time}.",
            "Feito: seu cartão final {card_last4} ficou {result} às {time}.",
            "Já está: seu cartão final {card_last4} está {result} desde as {time}.",
        ],
    },
    # D1: the OTP resume path, before the plan is issued.
    "otp_required": {
        "es": (
            "Por seguridad necesito que confirmes tu identidad. Ingresa el "
            "código de verificación que te enviamos."
        ),
        "pt": (
            "Por segurança preciso que você confirme sua identidade. Digite o "
            "código de verificação que enviamos."
        ),
    },
    # D13: confirms the address on file before ordering a replacement.
    "address_confirm": {
        "es": "¿Enviamos tu tarjeta nueva a {address_masked}?",
        "pt": "Enviamos seu novo cartão para {address_masked}?",
    },
    # D4/D13: asks for a new delivery address; the raw text never reaches the LLM.
    "address_ask": {
        "es": "Cuéntame la dirección completa a la que quieres que enviemos tu tarjeta nueva.",
        "pt": "Me diga o endereço completo para onde quer que enviemos seu novo cartão.",
    },
    # D12: card_unlock, get_block_origin came back "none".
    "not_blocked": {
        "es": (
            "Tu tarjeta no está bloqueada ni con un bloqueo temporal. No hay nada que desbloquear."
        ),
        "pt": (
            "Seu cartão não está bloqueado nem com um bloqueio temporário. "
            "Não há nada para desbloquear."
        ),
    },
    # D12: card_unlock, get_block_origin came back "customer_block".
    "block_permanent_no_undo": {
        "es": (
            "Tu tarjeta que termina en {card_last4} quedó bloqueada de forma "
            "permanente por un reporte de pérdida o robo. Ese bloqueo no se "
            "puede deshacer, pero puedo pedirte una tarjeta nueva."
        ),
        "pt": (
            "Seu cartão final {card_last4} ficou bloqueado de forma permanente "
            "por um reporte de perda ou roubo. Esse bloqueio não pode ser "
            "desfeito, mas posso pedir um cartão novo para você."
        ),
    },
    # D11: offered right after a verified permanent block.
    "offer_replacement": {
        "es": [
            (
                "¿Quieres que te pida una tarjeta nueva para reemplazar la que termina en "
                "{card_last4}, o te ayudo con algo más?"
            ),
            (
                "Puedo pedirte una tarjeta nueva para reemplazar la que termina en "
                "{card_last4}. ¿Quieres que lo haga, o te ayudo con algo más?"
            ),
            (
                "Si quieres, te pido una tarjeta nueva en lugar de la que termina en "
                "{card_last4}. ¿Lo hacemos, o te ayudo con algo más?"
            ),
        ],
        "pt": [
            (
                "Quer que eu peça um cartão novo para substituir o final {card_last4}, ou "
                "ajudo você com mais alguma coisa?"
            ),
            (
                "Posso pedir um cartão novo para substituir o final {card_last4}. Quer que eu "
                "faça isso, ou ajudo com mais alguma coisa?"
            ),
            (
                "Se quiser, peço um cartão novo no lugar do final {card_last4}. Fazemos isso, "
                "ou ajudo com mais alguma coisa?"
            ),
        ],
    },
    # P4: "no" to the replacement offer. A block may already have happened,
    # so this never claims nothing changed.
    # personalidad-cardy D3: the closing appended after a flow ends, with the
    # next useful step suggested. Chosen by `next_intent._closing_update`.
    "closing_suggest_transaction_search": {
        "es": [
            "¿Quieres que revisemos tus últimos movimientos o te puedo ayudar con algo adicional?",
            "Si te sirve, podemos mirar tus últimos movimientos. ¿O te ayudo con algo adicional?",
            "¿Revisamos juntas tus últimos movimientos, o hay algo adicional en lo que te ayude?",
        ],
        "pt": [
            "Quer que a gente confira suas últimas movimentações ou ajudo com algo adicional?",
            "Se ajudar, podemos olhar suas últimas movimentações. Ou ajudo com algo adicional?",
            "Conferimos juntas suas últimas movimentações, ou há algo adicional em que eu ajude?",
        ],
    },
    "closing_suggest_unrecognized_charge": {
        "es": [
            "¿Hay algún cobro que no reconozcas y quieras reportar, o te ayudo con algo adicional?",
            "Si ves un cobro que no reconoces, lo reportamos. ¿O te ayudo con algo adicional?",
            "¿Quieres reportar un cobro que no reconozcas, o te puedo ayudar con algo adicional?",
        ],
        "pt": [
            "Há alguma cobrança que você não reconhece e quer reportar, ou ajudo com outra coisa?",
            "Se vir uma cobrança que não reconhece, reportamos. Ou ajudo com algo adicional?",
            "Quer reportar uma cobrança que não reconhece, ou posso ajudar com algo adicional?",
        ],
    },
    "closing_generic": {
        "es": [
            "¿Te puedo ayudar con algo adicional?",
            "¿Hay algo adicional en lo que te pueda ayudar?",
            "¿Necesitas algo adicional con tus tarjetas?",
        ],
        "pt": [
            "Posso te ajudar com algo adicional?",
            "Há algo adicional em que eu possa ajudar?",
            "Você precisa de algo adicional com seus cartões?",
        ],
    },
    # personalidad-cardy D11: a lone greeting once Cardy already introduced herself.
    "greeting_again": {
        "es": [
            "¡Hola de nuevo, {customer_name}! Cuéntame, ¿en qué te ayudo con tus tarjetas?",
            "¡Qué bueno verte otra vez, {customer_name}! ¿Qué necesitas con tus tarjetas?",
            "Hola otra vez, {customer_name}. Dime, ¿en qué te puedo ayudar?",
        ],
        "pt": [
            "Oi de novo, {customer_name}! Me conta, em que posso ajudar com seus cartões?",
            "Que bom ver você de novo, {customer_name}! Do que você precisa com seus cartões?",
            "Olá outra vez, {customer_name}. Diga, em que posso ajudar?",
        ],
    },
    "greeting_again_plain": {
        "es": [
            "¡Hola de nuevo! Cuéntame, ¿en qué te ayudo con tus tarjetas?",
            "¡Qué bueno verte otra vez! ¿Qué necesitas con tus tarjetas?",
            "Hola otra vez. Dime, ¿en qué te puedo ayudar?",
        ],
        "pt": [
            "Oi de novo! Me conta, em que posso ajudar com seus cartões?",
            "Que bom ver você de novo! Do que você precisa com seus cartões?",
            "Olá outra vez. Diga, em que posso ajudar?",
        ],
    },
    # Block picker with no card left to block: every card is already blocked or
    # locked. No digits; the closing question follows in its own segment.
    "block_none_eligible": {
        "es": [
            "Todas tus tarjetas ya están bloqueadas, así que no hay nada más que bloquear.",
            "Veo que tus tarjetas ya están todas bloqueadas, no queda ninguna por bloquear.",
            "No tienes ninguna tarjeta por bloquear: todas ya están bloqueadas.",
        ],
        "pt": [
            "Todos os seus cartões já estão bloqueados, então não há mais nada para bloquear.",
            "Vejo que seus cartões já estão todos bloqueados, não sobrou nenhum para bloquear.",
            "Você não tem nenhum cartão para bloquear: todos já estão bloqueados.",
        ],
    },
    "offer_unlock": {
        "es": [
            "Si quieres, puedo desbloquear tu tarjeta. ¿Lo hago, o te ayudo con algo más?",
            (
                "Tu tarjeta tiene un bloqueo temporal y puedo quitarlo. ¿Quieres que lo haga, "
                "o te ayudo con algo más?"
            ),
            "Puedo desbloquear tu tarjeta ahora mismo. ¿Lo hacemos, o te ayudo con algo más?",
        ],
        "pt": [
            "Se quiser, posso desbloquear seu cartão. Faço isso, ou ajudo com mais alguma coisa?",
            (
                "Seu cartão está com um bloqueio temporário e posso retirá-lo. Quer que eu "
                "faça isso, ou ajudo com mais alguma coisa?"
            ),
            (
                "Posso desbloquear seu cartão agora mesmo. Fazemos isso, ou ajudo com mais "
                "alguma coisa?"
            ),
        ],
    },
    "offer_human": {
        "es": [
            (
                "Esto lo puede revisar una persona del equipo. ¿Quieres que te conecte, o te "
                "ayudo con algo más?"
            ),
            (
                "Para este caso lo mejor es hablar con una persona del equipo. ¿Te conecto, o "
                "te ayudo con algo más?"
            ),
            (
                "Una persona del equipo puede ayudarte con esto. ¿Quieres hablar con ella, o "
                "te ayudo con algo más?"
            ),
        ],
        "pt": [
            (
                "Isso pode ser analisado por uma pessoa da equipe. Quer que eu conecte você, "
                "ou ajudo com mais alguma coisa?"
            ),
            (
                "Para este caso o melhor é falar com uma pessoa da equipe. Conecto você, ou "
                "ajudo com mais alguma coisa?"
            ),
            (
                "Uma pessoa da equipe pode ajudar com isso. Quer falar com ela, ou ajudo com "
                "mais alguma coisa?"
            ),
        ],
    },
    "replacement_needs_block": {
        "es": [
            (
                "Para pedir una tarjeta nueva, primero hay que bloquear la actual o "
                "reportarla como perdida o robada. ¿Quieres que la bloquee?"
            ),
            (
                "Antes de pedir una tarjeta nueva necesito que la actual esté bloqueada o "
                "reportada como perdida o robada. ¿La bloqueo ahora?"
            ),
            (
                "Una tarjeta nueva se pide cuando la actual está bloqueada o reportada como "
                "perdida o robada. ¿Quieres que empiece por bloquearla?"
            ),
        ],
        "pt": [
            (
                "Para pedir um cartão novo, primeiro é preciso bloquear o atual ou reportá-lo "
                "como perdido ou roubado. Quer que eu bloqueie?"
            ),
            (
                "Antes de pedir um cartão novo, o atual precisa estar bloqueado ou reportado "
                "como perdido ou roubado. Bloqueio agora?"
            ),
            (
                "Um cartão novo é pedido quando o atual está bloqueado ou reportado como "
                "perdido ou roubado. Quer que eu comece bloqueando?"
            ),
        ],
    },
    "new_card_not_available": {
        "es": [
            (
                "¡Qué bueno que quieras otra tarjeta! Por el momento no contamos con ese "
                "servicio por este chat. ¿Te ayudo con algo de tus tarjetas actuales?"
            ),
            (
                "Gracias por pensar en nosotros para una tarjeta nueva. Por ahora no "
                "ofrecemos ese servicio por aquí. ¿En qué más te puedo ayudar con tus tarjetas?"
            ),
            (
                "Me encantaría ayudarte con eso, pero por el momento no contamos con la "
                "solicitud de tarjetas nuevas. ¿Hay algo de tus tarjetas en lo que te ayude?"
            ),
        ],
        "pt": [
            (
                "Que bom que você quer outro cartão! No momento não temos esse serviço por "
                "este chat. Posso ajudar com algo dos seus cartões atuais?"
            ),
            (
                "Obrigada por pensar na gente para um cartão novo. Por enquanto não "
                "oferecemos esse serviço por aqui. Em que mais posso ajudar com seus cartões?"
            ),
            (
                "Eu adoraria ajudar com isso, mas no momento não temos a solicitação de "
                "cartões novos. Há algo dos seus cartões em que eu possa ajudar?"
            ),
        ],
    },
    "replacement_declined": {
        "es": [
            "Entendido, no pido la tarjeta nueva por ahora. Aquí estoy si cambias de idea.",
            "Sin problema, dejo la tarjeta nueva para otro momento.",
            "De acuerdo, no pido la tarjeta nueva por ahora.",
        ],
        "pt": [
            "Entendido, não peço o cartão novo por enquanto. Estou aqui se mudar de ideia.",
            "Sem problema, deixo o cartão novo para outro momento.",
            "Certo, não peço o cartão novo por enquanto.",
        ],
    },
    # D13: replacement's precondition failed (not customer_block, not expired).
    "replacement_not_eligible": {
        "es": [
            "Tu tarjeta no cumple las condiciones para pedir un reemplazo en este momento.",
            "Por ahora tu tarjeta no cumple las condiciones para reemplazarla.",
            "Todavía no puedo pedir el reemplazo porque tu tarjeta no cumple las condiciones.",
        ],
        "pt": [
            "Seu cartão não cumpre as condições para pedir uma substituição neste momento.",
            "Por enquanto seu cartão não cumpre as condições para ser substituído.",
            "Ainda não posso pedir a substituição porque seu cartão não cumpre as condições.",
        ],
    },
    # ADR-020: balance_due on a debit card has no balance or minimum payment.
    # No offer here: the card's status follows right away in the same reply,
    # so there is never an offer the customer has to answer.
    # D5: the minimum payment and due date are a synthetic Swip policy, not
    # an official bank figure.
    "synthetic_footnote": {
        "es": (
            "El pago mínimo y la fecha de vencimiento son un estimado con la "
            "política sintética de Swip para este ejercicio, no un dato oficial "
            "del banco."
        ),
        "pt": (
            "O pagamento mínimo e a data de vencimento são uma estimativa com a "
            "política sintética do Swip para este exercício, não um dado "
            "oficial do banco."
        ),
    },
    # D10/ADR-021: card_info for a customer who isn't Active.
    "read_only_note": {
        "es": (
            "Tu cuenta no está activa en este momento, así que esta "
            "información es solo de consulta."
        ),
        "pt": "Sua conta não está ativa no momento, então esta informação é só para consulta.",
    },
    # D4-B D7: `unrecognized_charge`'s own "which card" question -- a
    # separate kind from `ask_which_card_*` above because none of those
    # actions fits "which card had the charge you don't recognize".
    "ask_which_card_dispute": {
        "es": [
            "¿De cuál tarjeta son los movimientos que no reconoces?",
            "¿En cuál tarjeta ves los movimientos que no reconoces?",
            "¿Cuál tarjeta tiene los movimientos que no reconoces?",
        ],
        "pt": [
            "De qual cartão são os movimentos que você não reconhece?",
            "Em qual cartão você vê os movimentos que não reconhece?",
            "Qual cartão tem os movimentos que você não reconhece?",
        ],
    },
    # D12: no candidate transactions at all (every one Declined, or none).
    "dispute_no_transactions": {
        "es": "No encontré movimientos recientes para revisar en esta tarjeta.",
        "pt": "Não encontrei movimentos recentes para revisar nesse cartão.",
    },
    # D12, D13: accompanies `ui.transaction_list`.
    "dispute_transactions_prompt": {
        "es": [
            (
                "Estos son los movimientos recientes de tu tarjeta que termina en {card_last4}. "
                "Marca los que no reconoces."
            ),
            (
                "Aquí están los movimientos recientes de tu tarjeta que termina en "
                "{card_last4}. Marca los que no reconozcas."
            ),
            (
                "Revisa los movimientos recientes de tu tarjeta que termina en {card_last4} y "
                "marca los que no reconoces."
            ),
        ],
        "pt": [
            (
                "Estes são os movimentos recentes do seu cartão final {card_last4}. Marque os "
                "que você não reconhece."
            ),
            (
                "Aqui estão os movimentos recentes do seu cartão final {card_last4}. Marque "
                "os que você não reconhecer."
            ),
            (
                "Confira os movimentos recentes do seu cartão final {card_last4} e marque os "
                "que você não reconhece."
            ),
        ],
    },
    # D8: the compromise-rule question, asked only when count/score haven't
    # already triggered it. "no" -> compromise.
    "dispute_q_card_in_possession": {
        "es": "¿Tienes la tarjeta contigo en este momento?",
        "pt": "Você está com o cartão em mãos neste momento?",
    },
    # D8: the single-charge path's second question.
    "dispute_q_contacted_merchant": {
        "es": "¿Ya intentaste contactar al comercio por este cobro?",
        "pt": "Você já tentou contatar o estabelecimento sobre essa cobrança?",
    },
    # D9: the two-step [block, claim] plan's confirmation.
    "dispute_confirm_compromise": {
        "es": (
            "Voy a bloquear tu tarjeta que termina en {card_last4} y a abrir un "
            "reclamo por {tx_count} movimiento(s) que no reconoces. Este "
            "bloqueo no se puede deshacer. ¿Confirmas?"
        ),
        "pt": (
            "Vou bloquear seu cartão final {card_last4} e abrir um caso para "
            "{tx_count} movimento(s) que você não reconhece. Esse bloqueio não "
            "pode ser desfeito. Confirma?"
        ),
    },
    # D11: the single-charge path's one-step claim confirmation.
    "dispute_confirm_claim": {
        "es": "Voy a abrir un reclamo por {tx_count} movimiento(s) que no reconoces. ¿Confirmas?",
        "pt": "Vou abrir um caso para {tx_count} movimento(s) que você não reconhece. Confirma?",
    },
    # D10: the block was refused (nothing written); offers the claim alone.
    "dispute_block_refused_offer_claim": {
        "es": (
            "No bloqueé tu tarjeta. Aun así, puedo abrir un reclamo por "
            "{tx_count} movimiento(s) que no reconoces. ¿Confirmas?"
        ),
        "pt": (
            "Não bloqueei seu cartão. Mesmo assim, posso abrir um caso para "
            "{tx_count} movimento(s) que você não reconhece. Confirma?"
        ),
    },
    # D9: the two-step plan, both steps verified.
    "dispute_claim_opened": {
        "es": (
            "Listo: bloqueé tu tarjeta que termina en {card_last4} a las {time} "
            "y abrí estos reclamos: {case_ids}."
        ),
        "pt": (
            "Pronto: bloqueei seu cartão final {card_last4} às {time} e abri "
            "estes casos: {case_ids}."
        ),
    },
    # D10 (claim-only, after a refused block) and D11 (single charge): the
    # claim alone, verified. No handoff mention here -- the caller decides
    # whether one follows.
    "dispute_claim_opened_single": {
        "es": (
            "Listo: abrí un reclamo por el movimiento que no reconoces a las "
            "{time}. Número de caso: {case_ids}."
        ),
        "pt": (
            "Pronto: abri um caso para o movimento que você não reconhece às "
            "{time}. Número do caso: {case_ids}."
        ),
    },
    # D10: both the block and the claim were refused. No case, still a
    # handoff: `handoff_transfer` follows and names the queue.
    "dispute_handoff_no_claim": {
        "es": "No hice ningún cambio en tu tarjeta ni abrí un reclamo.",
        "pt": "Não fiz nenhuma alteração no seu cartão nem abri um caso.",
    },
    # D10: packet `open_questions` entries (`handoff_open_questions`), code-filled, never LLM text.
    "dispute_open_question_card_active": {
        "es": "La tarjeta del cliente sigue activa porque rechazó el bloqueo.",
        "pt": "O cartão do cliente continua ativo porque ele recusou o bloqueio.",
    },
    "dispute_open_question_claim_refused": {
        "es": "El cliente también rechazó abrir el reclamo.",
        "pt": "O cliente também recusou abrir o caso.",
    },
    # D5-B D1: `decline_explain`'s own "which card" question -- a separate
    # kind from `ask_which_card_*` above, same reasoning as
    # `ask_which_card_dispute`.
    "ask_which_card_decline": {
        "es": [
            "¿De cuál tarjeta es la compra rechazada que quieres revisar?",
            "¿En cuál tarjeta fue rechazada la compra que quieres revisar?",
            "¿Cuál tarjeta tuvo la compra rechazada que quieres revisar?",
        ],
        "pt": [
            "De qual cartão é a compra recusada que você quer revisar?",
            "Em qual cartão foi recusada a compra que você quer revisar?",
            "Qual cartão teve a compra recusada que você quer revisar?",
        ],
    },
    # D5: no Declined rows at all on the selected card.
    "decline_none": {
        "es": "No encontré compras rechazadas recientes en esta tarjeta.",
        "pt": "Não encontrei compras recusadas recentes nesse cartão.",
    },
    # D5: `DeclineCodeUnknown` -- a response code with no policy entry.
    "decline_unknown": {
        "es": "No tengo el detalle del motivo de ese rechazo en este momento.",
        "pt": "Não tenho o detalhe do motivo dessa recusa neste momento.",
    },
    # D2, D3: accompanies the single-pick `ui.transaction_list`.
    "decline_pick_ask": {
        "es": [
            (
                "Estos son los rechazos recientes de tu tarjeta que termina en {card_last4}. "
                "¿Cuál quieres que te explique?"
            ),
            (
                "Estos son los rechazos recientes de tu tarjeta que termina en {card_last4}. "
                "¿Cuál te explico?"
            ),
            (
                "Aquí están los rechazos recientes de tu tarjeta que termina en {card_last4}. "
                "Elige el que quieres revisar."
            ),
        ],
        "pt": [
            (
                "Estas são as recusas recentes do seu cartão final {card_last4}. Qual você "
                "quer que eu explique?"
            ),
            "Estas são as recusas recentes do seu cartão final {card_last4}. Qual eu explico?",
            (
                "Aqui estão as recusas recentes do seu cartão final {card_last4}. Escolha a "
                "que quer revisar."
            ),
        ],
    },
    # D7, ADR-026: the one-tap `quick_replies` option for a self-service
    # (code 54) decline; its own label is also the text sent when tapped, so
    # NLU routes it as `replacement_request`.
    "decline_replacement_option": {
        "es": "Reponer mi tarjeta",
        "pt": "Repor meu cartão",
    },
    # D4, D6: `policies/decline_codes.yaml`'s `cause_key` values, one fixed
    # ES/PT label each -- `compose` places these as a `{decline_cause}`
    # placeholder, never the LLM's own wording of what the code means.
    "decline_cause_insufficient_funds": {
        "es": "No había fondos suficientes en la tarjeta al momento de la compra.",
        "pt": "Não havia saldo suficiente no cartão no momento da compra.",
    },
    "decline_cause_invalid_card_number": {
        "es": "El comercio recibió un número de tarjeta inválido en esa compra.",
        "pt": "O estabelecimento recebeu um número de cartão inválido nessa compra.",
    },
    "decline_cause_do_not_honor": {
        "es": "El banco emisor rechazó la compra sin dar un motivo específico.",
        "pt": "O banco emissor recusou a compra sem informar um motivo específico.",
    },
    "decline_cause_expired_card": {
        "es": "La tarjeta ya había vencido al momento de la compra.",
        "pt": "O cartão já estava vencido no momento da compra.",
    },
    # D4, D6: `policies/decline_codes.yaml`'s `next_step_key` values, same
    # pattern as the cause labels above -- placed as `{decline_next_step}`.
    "decline_next_pay_or_use_other_card": {
        "es": "Puedes intentar de nuevo con fondos disponibles o usando otra tarjeta.",
        "pt": "Você pode tentar de novo com saldo disponível ou usando outro cartão.",
    },
    "decline_next_check_card_number": {
        "es": "Verifica que el número de tarjeta ingresado en el comercio sea el correcto.",
        "pt": "Verifique se o número do cartão informado no estabelecimento está correto.",
    },
    "decline_next_contact_or_retry": {
        "es": "Puedes intentar de nuevo o contactar al comercio para más detalles.",
        "pt": (
            "Você pode tentar de novo ou entrar em contato com o "
            "estabelecimento para mais detalhes."
        ),
    },
    "decline_next_offer_replacement": {
        "es": "Puedo pedirte una tarjeta nueva para reemplazar la que venció.",
        "pt": "Posso pedir um cartão novo para substituir o que venceu.",
    },
    # This card's B1 (`tx_search`, D1, A1): no merchant, amount or resolvable
    # date at all -- one fixed question, no search runs.
    "tx_search_ask_criterion": {
        "es": "Cuéntame el comercio, el monto aproximado o la fecha del movimiento que buscas.",
        "pt": (
            "Me conte o estabelecimento, o valor aproximado ou a data da "
            "movimentação que você procura."
        ),
    },
    # D1: accompanies the single-pick `ui.transaction_list` a search offers.
    "tx_search_pick_ask": {
        "es": [
            "Encontré {count} movimiento(s) que podrían coincidir. ¿Cuál es?",
            "Hay {count} movimiento(s) que podrían ser el que buscas. ¿Cuál es?",
            "Estos son {count} movimiento(s) que coinciden. Elige el que buscabas.",
        ],
        "pt": [
            "Encontrei {count} movimentação(ões) que podem corresponder. Qual é?",
            "Há {count} movimentação(ões) que podem ser a que você procura. Qual é?",
            "Estas são {count} movimentação(ões) que correspondem. Escolha a que você procurava.",
        ],
    },
    # D1, A2: two searches came back empty; `{filters}` is code-formatted (R4).
    "tx_search_none": {
        "es": "No encontré movimientos con estos datos: {filters}.",
        "pt": "Não encontrei movimentações com estes dados: {filters}.",
    },
    # D3: two or more Pending/Reversed matches, or the "zero with a slot"
    # broadened offer -- the same single-pick list `tx_search_pick_ask` uses.
    "tx_explain_pick_ask": {
        "es": [
            (
                "Tienes {count} movimiento(s) pendiente(s) o revertido(s). ¿Cuál quieres que "
                "te explique?"
            ),
            "Veo {count} movimiento(s) pendiente(s) o revertido(s). ¿Cuál te explico?",
            "Hay {count} movimiento(s) pendiente(s) o revertido(s). Elige el que quieres revisar.",
        ],
        "pt": [
            (
                "Você tem {count} movimentação(ões) pendente(s) ou revertida(s). Qual quer "
                "que eu explique?"
            ),
            "Vejo {count} movimentação(ões) pendente(s) ou revertida(s). Qual eu explico?",
            "Há {count} movimentação(ões) pendente(s) ou revertida(s). Escolha a que quer revisar.",
        ],
    },
    # D3: no Pending/Reversed row at all, with or without a criterion.
    "tx_explain_none": {
        "es": "No encontré movimientos pendientes ni revertidos en tus tarjetas.",
        "pt": "Não encontrei movimentações pendentes nem revertidas nos seus cartões.",
    },
    # A5: the overdue-Pending quick reply, `slot="next_step"` (reused from
    # `decline_explain`'s self-service offer). Tapping it sends this text, so
    # NLU routes it as `human_request`.
    "tx_human_option": {
        "es": "Hablar con una persona",
        "pt": "Falar com uma pessoa",
    },
    # D3, D6: `compose`'s fact template for the `tx_explain` goal, used only
    # when the LLM's own draft fails grounding twice.
    "goal_tx_explain": {
        "es": "{tx_state_cause} {tx_state_next_step}",
        "pt": "{tx_state_cause} {tx_state_next_step}",
    },
    # D2: same, for the `tx_details` goal (an Approved/other-status pick).
    "goal_tx_details": {
        "es": (
            "Tu movimiento en {merchant} por {amount} el {tx_date} con la "
            "tarjeta {card_mask} fue por el canal {channel}."
        ),
        "pt": (
            "Sua movimentação em {merchant} de {amount} no dia {tx_date} com "
            "o cartão {card_mask} foi pelo canal {channel}."
        ),
    },
    # `policies/transaction_states.yaml`'s `cause_key` values, one fixed
    # ES/PT label each -- `compose` places these as `{tx_state_cause}`, never
    # the LLM's own wording of what the status means (A5, R8).
    "tx_cause_pending_hold": {
        "es": "Tu pago está en proceso de confirmación por el banco.",
        "pt": "Seu pagamento está em processo de confirmação pelo banco.",
    },
    "tx_cause_reversed_charge": {
        "es": "Ese movimiento fue revertido y no llegó a cobrarse.",
        "pt": "Essa movimentação foi revertida e não chegou a ser cobrada.",
    },
    # `next_step_key`/`overdue_next_step_key` values, same pattern as the
    # cause labels above -- placed as `{tx_state_next_step}`.
    "tx_next_wait_until_date": {
        "es": "Debería quedar confirmado antes de la fecha estimada.",
        "pt": "Deve ficar confirmado antes da data estimada.",
    },
    "tx_next_offer_human": {
        "es": "Como ya pasó el plazo habitual, una persona del equipo puede revisarlo contigo.",
        "pt": "Como o prazo habitual já passou, uma pessoa da equipe pode revisar isso com você.",
    },
    "tx_next_no_action_needed": {
        "es": "No necesitas hacer nada más por este movimiento.",
        "pt": "Você não precisa fazer mais nada quanto a essa movimentação.",
    },
    # B2 priority flags (`unrecognized_charge`): one agent-facing line each,
    # appended to the handoff's `open_questions`.
    "priority_flag_repeat_complainer": {
        "es": "El cliente tiene reclamos previos recientes (cliente reincidente).",
        "pt": "O cliente tem reclamações recentes anteriores (cliente reincidente).",
    },
    "priority_flag_open_critical": {
        "es": "El cliente tiene un reclamo crítico abierto.",
        "pt": "O cliente tem uma reclamação crítica em aberto.",
    },
    "priority_flag_amount_over_threshold": {
        "es": "El monto reclamado supera el umbral de prioridad.",
        "pt": "O valor contestado supera o limite de prioridade.",
    },
    # D12: the handoff happened (row, mode=human, event). `reference` is the
    # already-formatted case reference.
    "handoff_transfer": {
        "es": (
            "Te estoy transfiriendo con una persona del equipo de {queue_label}. "
            "Tu caso es {reference}. Ya tiene el contexto de lo que me contaste "
            "y, desde aquí, yo dejo de responder para que ella te atienda."
        ),
        "pt": (
            "Estou transferindo você para uma pessoa da equipe de {queue_label}. "
            "Seu caso é {reference}. Ela já tem o contexto do que você me contou "
            "e, daqui em diante, eu paro de responder para que ela atenda você."
        ),
    },
    # D9: a failure forced a handoff (tool or LLM down after bounded retries).
    # No retry offer: a person takes over. Dev B reviews this copy.
    "failure_handoff": {
        "es": [
            (
                "Tuve un problema y no puedo seguir con esto ahora. No hice ningún cambio. "
                "Una persona del equipo va a tomar tu caso."
            ),
            (
                "Algo falló y no puedo continuar ahora. No hice ningún cambio. Una persona "
                "del equipo va a atender tu caso."
            ),
            (
                "Perdona, tuve un inconveniente y no puedo seguir. No cambié nada. Una "
                "persona del equipo se hará cargo de tu caso."
            ),
        ],
        "pt": [
            (
                "Tive um problema e não consigo continuar com isso agora. Não fiz nenhuma "
                "alteração. Uma pessoa da equipe vai assumir o seu caso."
            ),
            (
                "Algo falhou e não consigo continuar agora. Não fiz nenhuma alteração. Uma "
                "pessoa da equipe vai atender o seu caso."
            ),
            (
                "Desculpe, tive um imprevisto e não consigo seguir. Não mudei nada. Uma "
                "pessoa da equipe vai cuidar do seu caso."
            ),
        ],
    },
    # D9: same, but an action already ran, so it never claims nothing changed.
    # Dev B reviews this copy.
    "failure_handoff_after_action": {
        "es": [
            (
                "Tuve un problema y no puedo seguir con esto ahora. Una persona del equipo va "
                "a tomar tu caso."
            ),
            "Algo falló y no puedo continuar ahora. Una persona del equipo va a atender tu caso.",
            (
                "Perdona, tuve un inconveniente y no puedo seguir. Una persona del equipo se "
                "hará cargo de tu caso."
            ),
        ],
        "pt": [
            (
                "Tive um problema e não consigo continuar com isso agora. Uma pessoa da "
                "equipe vai assumir o seu caso."
            ),
            (
                "Algo falhou e não consigo continuar agora. Uma pessoa da equipe vai atender "
                "o seu caso."
            ),
            (
                "Desculpe, tive um imprevisto e não consigo seguir. Uma pessoa da equipe vai "
                "cuidar do seu caso."
            ),
        ],
    },
    # D14: system message when the agent returns the conversation to the bot.
    "back_with_cardy": {
        "es": "¡Qué bueno tenerte de vuelta conmigo, Cardy! ¿Qué más necesitas con tu tarjeta?",
        "pt": "Que bom ter você de volta comigo, a Cardy! Do que mais precisa com seu cartão?",
    },
    # D18: fixed four-part abstain when the composed draft fails or is
    # rejected: topic, reason, closest action, human offer. The caller passes
    # an empty `closest_action` when there is none and collapses the
    # resulting double space.
    "abstain_fallback": {
        "es": [
            (
                "Lo siento, por aquí no puedo gestionar {topic_label}. {reason} Gracias por "
                "tu paciencia, ¿qué necesitas con tus tarjetas?"
            ),
            (
                "Perdona, no puedo ayudarte con {topic_label}. {reason} Gracias por entender, "
                "¿qué necesitas con tus tarjetas?"
            ),
            (
                "Disculpa, no puedo resolver {topic_label} por aquí. {reason} Gracias por tu "
                "comprensión, ¿en qué te ayudo con tus tarjetas?"
            ),
        ],
        "pt": [
            (
                "Sinto muito, por aqui não posso ajudar com {topic_label}. {reason} Obrigada "
                "pela paciência, do que você precisa com seus cartões?"
            ),
            (
                "Desculpe, não consigo resolver {topic_label} por aqui. {reason} Obrigada por "
                "entender, do que você precisa com seus cartões?"
            ),
            (
                "Perdão, não posso ajudar com {topic_label} neste chat. {reason} Obrigada "
                "pela compreensão, em que posso ajudar com seus cartões?"
            ),
        ],
    },
    # Per-goal fact templates (D12): what `compose` sends when the LLM's draft
    # fails the grounding check twice. Placeholders are filled in code, no digits.
    "goal_card_status": {
        "es": "Tu tarjeta {card_kind} {card_mask} está {status} y vence el {expiry}.",
        "pt": "Seu cartão {card_kind} {card_mask} está {status} e vence em {expiry}.",
    },
    "goal_balance_due": {
        "es": (
            "Tu saldo actual es {current_balance}. Tu pago mínimo estimado es "
            "{min_payment} y vence el {due_date}."
        ),
        "pt": (
            "Seu saldo atual é {current_balance}. Seu pagamento mínimo estimado é "
            "{min_payment} e vence em {due_date}."
        ),
    },
    # ADR-032: a debit card's balance is the money available in it.
    "goal_debit_balance": {
        "es": "Tu tarjeta {card_kind} {card_mask} tiene {available_balance} disponible.",
        "pt": "Seu cartão {card_kind} {card_mask} tem {available_balance} disponível.",
    },
    "goal_decline_explain": {
        "es": "Tu compra fue rechazada: {decline_cause} {decline_next_step}",
        "pt": "Sua compra foi recusada: {decline_cause} {decline_next_step}",
    },
}


# Cardy's proactive welcome (landing-home-bienvenida D3, D4). `welcome.py` picks
# one salutation and one body, and every body speaks of the Swip universe. The
# stored "last used" body index is language-agnostic, so ES and PT MUST keep the
# same number of bodies. No text carries a digit, and none is gendered: we don't
# know the customer's gender, so it is "te doy la bienvenida", never
# "bienvenido/bienvenida". The PT texts are team-generated and pending review
# by a native Brazilian speaker.
WELCOME_BODIES: dict[Language, tuple[str, ...]] = {
    "es": (
        "Soy Cardy y te doy la bienvenida a este universo de posibilidades. "
        "¿Qué quieres resolver hoy con tus tarjetas?",
        "Soy Cardy, tu copiloto en el universo Swip. Cuéntame qué necesitas con tus tarjetas "
        "y lo vemos juntas.",
        "Qué gusto tenerte de vuelta en el universo Swip. Soy Cardy, dime qué necesitas "
        "con tu tarjeta y empezamos.",
        "Soy Cardy y en este universo tus tarjetas están en buenas manos. ¿En qué te ayudo hoy?",
        "Tu universo financiero está a un mensaje de distancia. Soy Cardy, cuéntame qué "
        "necesitas con tus tarjetas.",
        "Soy Cardy, de Swip, y estoy lista para explorar contigo este universo de posibilidades. "
        "¿Qué necesitas hoy?",
        "Te doy la bienvenida al universo Swip. Soy Cardy y puedo ayudarte con tus tarjetas "
        "y tus movimientos. ¿Por dónde empezamos?",
        "Soy Cardy y cuido de tus tarjetas en todo el universo Swip. Cuando quieras, "
        "cuéntame qué necesitas.",
    ),
    "pt": (
        "Sou a Cardy e dou as boas-vindas a este universo de possibilidades. "
        "O que você quer resolver hoje com seus cartões?",
        "Sou a Cardy, sua copiloto no universo Swip. Conte o que você precisa com seus cartões "
        "e vemos juntas.",
        "Que bom ter você de volta ao universo Swip. Sou a Cardy, diga o que precisa com seu "
        "cartão e começamos.",
        "Sou a Cardy e neste universo seus cartões estão em boas mãos. Como posso ajudar hoje?",
        "Seu universo financeiro está a uma mensagem de distância. Sou a Cardy, conte o que "
        "você precisa com seus cartões.",
        "Sou a Cardy, da Swip, e estou pronta para explorar com você este universo de "
        "possibilidades. O que você precisa hoje?",
        "Boas-vindas ao universo Swip. Sou a Cardy e posso ajudar com seus cartões e suas "
        "transações. Por onde começamos?",
        "Sou a Cardy e cuido dos seus cartões em todo o universo Swip. Quando quiser, "
        "conte o que você precisa.",
    ),
}

WELCOME_SALUTATIONS: dict[Language, tuple[dict[Literal["named", "plain"], str], ...]] = {
    "es": (
        {"named": "Hola, {customer_name}.", "plain": "Hola."},
        {"named": "¡Qué bueno verte, {customer_name}!", "plain": "¡Qué bueno verte!"},
        {"named": "Hola de nuevo, {customer_name}.", "plain": "Hola de nuevo."},
        {"named": "¡Hola, {customer_name}!", "plain": "¡Hola!"},
    ),
    "pt": (
        {"named": "Olá, {customer_name}.", "plain": "Olá."},
        {"named": "Que bom ver você, {customer_name}!", "plain": "Que bom ver você!"},
        {"named": "Olá de novo, {customer_name}.", "plain": "Olá de novo."},
        {"named": "Oi, {customer_name}!", "plain": "Oi!"},
    ),
}


class _Rng(Protocol):
    def choice(self, seq: list[str], /) -> str: ...


# The test hook (D13): `conftest.py` swaps it for a picker that returns the first variant.
_RNG: _Rng = random


def template_variants(kind: TemplateKind, language: Language) -> tuple[str, ...]:
    """Every variant of `(kind, language)`; one element for a single-version kind."""
    value = _TEMPLATES[kind][language]
    return (value,) if isinstance(value, str) else tuple(value)


def get_template(kind: TemplateKind, language: Language, rng: _Rng | None = None) -> str:
    """Look up the fixed reply for `(kind, language)` (D14, D15).

    A kind with variants returns one, picked by `rng` (default: the module's
    `_RNG`), so Cardy doesn't repeat itself word for word.
    """
    value = _TEMPLATES[kind][language]
    if isinstance(value, str):
        return value
    return (rng or _RNG).choice(value)
