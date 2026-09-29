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
    "replacement_declined",
    "replacement_not_eligible",
    "credit_only",
    "synthetic_footnote",
    "read_only_note",
    "handoff_transfer",
    "back_with_cardy",
    "abstain_fallback",
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
    # D16: thanks with nothing pending. Kept for callers that only need the
    # acknowledgement; `smalltalk` itself now answers with `anything_else`.
    "thanks_close": {
        "es": "¡De nada! Aquí estoy si necesitas algo más con tu tarjeta.",
        "pt": "De nada! Estou por aqui se precisar de mais alguma coisa com seu cartão.",
    },
    # Thanks (or a bare "no") with nothing pending: ask before closing, and
    # `smalltalk` opens the `anything_else` pause so the answer can close it.
    "anything_else": {
        "es": "¡Con gusto! ¿Te puedo ayudar en algo más?",
        "pt": "Por nada! Posso te ajudar em mais alguma coisa?",
    },
    # A bare "sí" with nothing pending, or "sí" to `anything_else`.
    "ask_what_else": {
        "es": "Claro, cuéntame. ¿En qué más te ayudo con tu tarjeta?",
        "pt": "Claro, me conta. Em que mais posso ajudar com seu cartão?",
    },
    # "No"/thanks/goodbye to `anything_else`: the conversation ends here.
    "farewell": {
        "es": "Gracias por escribirnos. Que tengas un buen día.",
        "pt": "Obrigada por falar com a gente. Tenha um ótimo dia.",
    },
    # Small talk while a flow is still waiting on an answer (not OTP).
    "pending_reminder": {
        "es": (
            "Todavía necesito tu respuesta a mi pregunta anterior para seguir. "
            "Si prefieres dejarlo así, dime cancelar."
        ),
        "pt": (
            "Ainda preciso da sua resposta à minha pergunta anterior para continuar. "
            "Se preferir deixar assim, é só dizer cancelar."
        ),
    },
    # D16: a button confirmation that matches no open plan (stale token).
    "nothing_pending": {
        "es": "No tengo ninguna acción pendiente por confirmar. ¿En qué más te ayudo?",
        "pt": "Não tenho nenhuma ação pendente para confirmar. Em que mais posso ajudar?",
    },
    # D12: which card, per action. `{card_options}` is `select_card`'s
    # newline-joined masked list, formatted in code (R4).
    "ask_which_card_status": {
        "es": "¿Sobre cuál tarjeta quieres saber?\n{card_options}",
        "pt": "Sobre qual cartão você quer saber?\n{card_options}",
    },
    "ask_which_card_balance": {
        "es": "¿De cuál tarjeta quieres ver el saldo?\n{card_options}",
        "pt": "De qual cartão você quer ver o saldo?\n{card_options}",
    },
    "ask_which_card_block": {
        "es": "¿Cuál tarjeta quieres bloquear?\n{card_options}",
        "pt": "Qual cartão você quer bloquear?\n{card_options}",
    },
    "ask_which_card_unlock": {
        "es": "¿Cuál tarjeta quieres desbloquear?\n{card_options}",
        "pt": "Qual cartão você quer desbloquear?\n{card_options}",
    },
    "ask_which_card_replacement": {
        "es": "¿Cuál tarjeta quieres reponer?\n{card_options}",
        "pt": "Qual cartão você quer substituir?\n{card_options}",
    },
    # D11: card_block needs to know which kind before it can plan anything.
    "clarify_lock_vs_block": {
        "es": (
            "¿Quieres bloquear tu tarjeta de forma temporal, para poder "
            "desbloquearla después, o reportarla como perdida o robada con un "
            "bloqueo permanente?"
        ),
        "pt": (
            "Você quer bloquear seu cartão temporariamente, podendo desbloqueá-lo "
            "depois, ou reportá-lo como perdido ou roubado com um bloqueio "
            "permanente?"
        ),
    },
    # D11: card_block/card_unlock, the card is already in the requested state.
    "already_in_state": {
        "es": "Tu tarjeta terminada en {card_last4} ya está {state}. No hice ningún cambio.",
        "pt": "Seu cartão final {card_last4} já está {state}. Não fiz nenhuma alteração.",
    },
    # D14: a typed "no" or /cancel on a pending plan. Nothing ran.
    "action_cancelled": {
        "es": "Cancelé la solicitud. No hice ningún cambio en tu tarjeta.",
        "pt": "Cancelei a solicitação. Não fiz nenhuma alteração no seu cartão.",
    },
    # D17: action_done without a reference (lock, unlock, block), until
    # audit_event_id exists.
    "action_done_noref": {
        "es": "Listo: tu tarjeta terminada en {card_last4} quedó {result} a las {time}.",
        "pt": "Pronto: seu cartão final {card_last4} ficou {result} às {time}.",
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
            "Tu tarjeta terminada en {card_last4} quedó bloqueada de forma "
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
        "es": (
            "¿Quieres que te pida una tarjeta nueva para reemplazar la terminada en {card_last4}?"
        ),
        "pt": "Quer que eu peça um cartão novo para substituir o final {card_last4}?",
    },
    # P4: "no" to the replacement offer. A block may already have happened,
    # so this never claims nothing changed.
    "replacement_declined": {
        "es": "Entendido, no pido la tarjeta nueva por ahora.",
        "pt": "Entendido, não peço o cartão novo por enquanto.",
    },
    # D13: replacement's precondition failed (not customer_block, not expired).
    "replacement_not_eligible": {
        "es": "Tu tarjeta no cumple las condiciones para pedir un reemplazo en este momento.",
        "pt": "Seu cartão não cumpre as condições para pedir uma substituição neste momento.",
    },
    # ADR-020: balance_due on a debit card has no balance or minimum payment.
    # No offer here: the card's status follows right away in the same reply,
    # so there is never an offer the customer has to answer.
    "credit_only": {
        "es": (
            "Esa es una tarjeta de débito, así que no tiene saldo por pagar ni "
            "fecha de vencimiento. Te dejo su información:"
        ),
        "pt": (
            "Esse é um cartão de débito, então não tem saldo a pagar nem data "
            "de vencimento. Aqui estão as informações dele:"
        ),
    },
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
        "es": "¿De cuál tarjeta son los movimientos que no reconoces?\n{card_options}",
        "pt": "De qual cartão são os movimentos que você não reconhece?\n{card_options}",
    },
    # D12: no candidate transactions at all (every one Declined, or none).
    "dispute_no_transactions": {
        "es": "No encontré movimientos recientes para revisar en esta tarjeta.",
        "pt": "Não encontrei movimentos recentes para revisar nesse cartão.",
    },
    # D12, D13: accompanies `ui.transaction_list`.
    "dispute_transactions_prompt": {
        "es": (
            "Estos son los movimientos recientes de tu tarjeta terminada en "
            "{card_last4}. Marca los que no reconoces."
        ),
        "pt": (
            "Estes são os movimentos recentes do seu cartão final {card_last4}. "
            "Marque os que você não reconhece."
        ),
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
            "Voy a bloquear tu tarjeta terminada en {card_last4} y a abrir un "
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
            "Listo: bloqueé tu tarjeta terminada en {card_last4} a las {time} "
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
        "es": "¿De cuál tarjeta es la compra rechazada que quieres revisar?\n{card_options}",
        "pt": "De qual cartão é a compra recusada que você quer revisar?\n{card_options}",
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
        "es": (
            "Estos son los rechazos recientes de tu tarjeta terminada en "
            "{card_last4}. ¿Cuál quieres que te explique?"
        ),
        "pt": (
            "Estas são as recusas recentes do seu cartão final {card_last4}. "
            "Qual você quer que eu explique?"
        ),
    },
    # D7, ADR-026: the one-tap `quick_replies` option for a self-service
    # (code 54) decline; its own label is also the text sent when tapped, so
    # NLU routes it as `replacement_request`.
    "decline_replacement_option": {
        "es": "Quiero una tarjeta nueva",
        "pt": "Quero um cartão novo",
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
    # D14: system message when the agent returns the conversation to the bot.
    "back_with_cardy": {
        "es": "Vuelves a hablar conmigo, Cardy. ¿Qué más necesitas con tu tarjeta?",
        "pt": "Você voltou a falar comigo, a Cardy. Do que mais precisa com seu cartão?",
    },
    # D18: fixed four-part abstain when the composed draft fails or is
    # rejected: topic, reason, closest action, human offer. The caller passes
    # an empty `closest_action` when there is none and collapses the
    # resulting double space.
    "abstain_fallback": {
        "es": (
            "Por aquí no puedo gestionar {topic_label}. {reason} {closest_action} {human_offer}"
        ),
        "pt": (
            "Por aqui não consigo cuidar de {topic_label}. {reason} {closest_action} {human_offer}"
        ),
    },
}


def get_template(kind: TemplateKind, language: Language) -> str:
    """Look up the fixed reply for `(kind, language)` (D14, D15)."""
    return _TEMPLATES[kind][language]
