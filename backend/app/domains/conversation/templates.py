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

__all__ = [
    "WELCOME_BODIES",
    "WELCOME_SALUTATIONS",
    "Language",
    "TemplateKind",
    "get_template",
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
        "es": "Encontré {count} movimiento(s) que podrían coincidir. ¿Cuál es?",
        "pt": "Encontrei {count} movimentação(ões) que podem corresponder. Qual é?",
    },
    # D1, A2: two searches came back empty; `{filters}` is code-formatted (R4).
    "tx_search_none": {
        "es": "No encontré movimientos con estos datos: {filters}.",
        "pt": "Não encontrei movimentações com estes dados: {filters}.",
    },
    # D3: two or more Pending/Reversed matches, or the "zero with a slot"
    # broadened offer -- the same single-pick list `tx_search_pick_ask` uses.
    "tx_explain_pick_ask": {
        "es": (
            "Tienes {count} movimiento(s) pendiente(s) o revertido(s). "
            "¿Cuál quieres que te explique?"
        ),
        "pt": (
            "Você tem {count} movimentação(ões) pendente(s) ou revertida(s). "
            "Qual quer que eu explique?"
        ),
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
        "es": (
            "Tuve un problema y no puedo seguir con esto ahora. No hice ningún cambio. "
            "Una persona del equipo va a tomar tu caso."
        ),
        "pt": (
            "Tive um problema e não consigo continuar com isso agora. Não fiz nenhuma alteração. "
            "Uma pessoa da equipe vai assumir o seu caso."
        ),
    },
    # D9: same, but an action already ran, so it never claims nothing changed.
    # Dev B reviews this copy.
    "failure_handoff_after_action": {
        "es": (
            "Tuve un problema y no puedo seguir con esto ahora. "
            "Una persona del equipo va a tomar tu caso."
        ),
        "pt": (
            "Tive um problema e não consigo continuar com isso agora. "
            "Uma pessoa da equipe vai assumir o seu caso."
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


def get_template(kind: TemplateKind, language: Language) -> str:
    """Look up the fixed reply for `(kind, language)` (D14, D15)."""
    return _TEMPLATES[kind][language]
