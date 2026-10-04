"""Writes the one-line `request` of a handoff packet (D9, D10, R4-R6, R11).

This is the LLM half of the handoff: it reads facts and actions and has no
write or handoff tools (R6). The user message holds only code-built keys --
reason, queue, intents, the actions' tool names and verified flags, and the
placeholder keys on offer -- never `user_text` or a fact's value (R5). The
draft's `{card_mask}`, `{tx_count}` and `{queue_label}` are filled in code
(R4). A draft with an unknown placeholder, a brace residue or a raw digit,
or an `LLMError`, is replaced by a fixed per-reason text (R11); the LLM is
never called a second time.

The node writes graph-local `handoff_request`; the code-only `handoff` node
reads it next.
"""

import re
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.llm import LLMClient, LLMError, PromptRef
from app.domains.conversation.graph import GraphState
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.templates import Language
from app.domains.localization import mask_card, queue_label
from app.domains.policy.escalation import load_escalation_policy, resolve_escalation
from app.domains.policy.registry import get_policies

__all__ = ["HandoffSummaryDraft", "handoff_summary"]

_PROMPT = PromptRef("handoff_summary", 1)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_MAX_LEN = 200

# Fixed agent-facing texts per reason, used when the draft is rejected or the
# LLM fails (R11). Digit-free on purpose: they carry no placeholders.
_FALLBACK: dict[str, dict[Language, str]] = {
    "step_up_failed": {
        "es": "El cliente no superó la verificación de identidad (código) tras varios intentos.",
        "pt": "O cliente não passou na verificação de identidade (código) após várias tentativas.",
    },
    "agent_round_cap": {
        "es": "El asistente no logró completar la solicitud tras varios intentos.",
        "pt": "O assistente não conseguiu concluir a solicitação após várias tentativas.",
    },
    "human_request": {
        "es": "El cliente pidió hablar con una persona. Revisa el contexto verificado.",
        "pt": "O cliente pediu para falar com uma pessoa. Revise o contexto verificado.",
    },
    "clarification_exhausted": {
        "es": "No pude entender la solicitud tras varios intentos. Necesita ayuda directa.",
        "pt": "Não consegui entender o pedido após várias tentativas. Precisa de ajuda direta.",
    },
    "legal_regulator": {
        "es": "El cliente mencionó una vía legal o regulatoria. Requiere atención prioritaria.",
        "pt": "O cliente mencionou uma via legal ou regulatória. Requer atenção prioritária.",
    },
    "priority_claim": {
        "es": "Reclamo registrado con marcas de prioridad. Revisa las marcas y el caso abierto.",
        "pt": "Reclamação registrada com marcas de prioridade. Revise as marcas e o caso aberto.",
    },
    "customer_not_active": {
        "es": "El cliente no está activo y no pude ayudarle con su solicitud.",
        "pt": "O cliente não está ativo e não consegui ajudá-lo com o pedido.",
    },
    "bank_side_block": {
        "es": "La tarjeta tiene un bloqueo del banco que Cardy no puede levantar.",
        "pt": "O cartão tem um bloqueio do banco que a Cardy não pode remover.",
    },
    "action_unverified": {
        "es": "Una acción no pudo verificarse tras ejecutarse. Confirma el estado real.",
        "pt": "Uma ação não pôde ser verificada após a execução. Confirme o estado real.",
    },
    "unauthorized_access": {
        "es": "El cliente intentó consultar datos de otra persona. Se rechazó y quedó auditado.",
        "pt": "O cliente tentou consultar dados de outra pessoa. Foi recusado e ficou auditado.",
    },
    "suspected_fraud": {
        "es": "El cliente reporta un posible fraude. Revisa la evidencia adjunta.",
        "pt": "O cliente relata uma possível fraude. Revise a evidência anexada.",
    },
    "tool_failure": {
        "es": "Una herramienta falló tras varios intentos. Revisa el estado real de la solicitud.",
        "pt": "Uma ferramenta falhou após várias tentativas. Revise o estado real do pedido.",
    },
    "llm_unavailable": {
        "es": "El modelo no estuvo disponible tras varios intentos. Necesita atención directa.",
        "pt": "O modelo ficou indisponível após várias tentativas. Precisa de atenção direta.",
    },
}
_DEFAULT_REASON = "human_request"


class HandoffSummaryDraft(BaseModel):
    """The handoff-summary call's structured output (D10)."""

    model_config = ConfigDict(extra="forbid")

    request: str


def _fallback(reason: str | None, language: Language) -> str:
    return _FALLBACK.get(reason or _DEFAULT_REASON, _FALLBACK[_DEFAULT_REASON])[language]


async def handoff_summary(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Draft `handoff_request` for this turn's handoff; never raises on LLM failure."""
    configurable = config["configurable"]
    has_classifier = configurable.get("classifier") is not None
    if has_classifier and state.get("degraded"):
        # D4: degraded turns take the fixed per-reason text, no LLM call. Lazy
        # import: the baseline module imports this one.
        from app.domains.conversation.baseline.template_compose import baseline_handoff_summary

        return await baseline_handoff_summary(state, config)
    llm: LLMClient = configurable["llm"]
    language: Language = state["language"]

    nlu = state.get("nlu")
    intents = list(nlu.intents) if nlu is not None else []
    pending = state.get("pending")
    resolution = resolve_escalation(
        load_escalation_policy(),
        reason=state.get("escalation_reason"),
        queue=state.get("handoff_queue"),
        pending_flow=pending["flow"] if pending else None,
        intents=list(intents),
        text=state.get("user_text", ""),
    )
    if resolution is None:
        return {"handoff_request": _fallback(None, language)}
    reason, queue = resolution.reason, resolution.queue
    fallback = _fallback(reason, language)
    # Under LLM_DISABLED there is no model to ask; `llm_unavailable` with the LLM
    # enabled still tries it (retries included) and falls back on `LLMError`.
    if get_settings().llm_disabled:
        return {"handoff_request": fallback}

    # `card_mask` is offered only when the selected card's last4 can be read.
    values: dict[str, str] = {
        "tx_count": str(len(state.get("handoff_evidence") or [])),
        "queue_label": queue_label(queue, language),
    }
    card_id = state.get("selected_card_id")
    if card_id:
        try:
            details = await configurable["bank_tools"].get_card_details(card_id)
            values["card_mask"] = mask_card(details.last4)
        except Exception:  # the mask is optional; the summary must not fail on it
            pass

    # step_up_failed facts are written in code (D28): the wrong-code count is the
    # policy limit, offered as a placeholder so the model never types a digit (R4),
    # and the paused action is stated as not executed.
    facts: list[str] = []
    if reason == "step_up_failed":
        values["failed_codes"] = str(get_policies().tools.step_up_max_failures)
        facts = [
            "hecho: el cliente ingresó {failed_codes} códigos incorrectos y falló la "
            "verificación de identidad",
            "hecho: la acción solicitada (pausada) NO se ejecutó; "
            "el estado de la tarjeta no cambió",
        ]

    actions = [f"{a.tool} verified={str(a.verified).lower()}" for a in state.get("actions", [])]
    user = "\n".join(
        [
            f"Idioma de la solicitud: {language}",
            f"Motivo: {reason}",
            f"Cola: {queue}",
            "Datos (solo claves y etiquetas; no hay valores del cliente):",
            "```",
            f"intents: {', '.join(intents) or '-'}",
            f"acciones: {'; '.join(actions) or '-'}",
            *facts,
            f"placeholders: {', '.join('{' + k + '}' for k in values)}",
            "```",
        ]
    )
    try:
        draft = await llm.structured(
            step="handoff_summary",
            prompt=_PROMPT,
            system=load_prompt(_PROMPT),
            user=user,
            schema=HandoffSummaryDraft,
        )
    except LLMError:
        if has_classifier:
            from app.domains.conversation.baseline.template_compose import (
                baseline_handoff_summary,
            )

            return {**await baseline_handoff_summary(state, config), "degraded": True}
        return {"handoff_request": fallback}

    text = draft.request
    if any(key not in values for key in _PLACEHOLDER.findall(text)):
        return {"handoff_request": fallback}
    residual = _PLACEHOLDER.sub("", text)
    if "{" in residual or "}" in residual or any(c.isdigit() for c in residual):
        return {"handoff_request": fallback}
    filled = _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)
    return {"handoff_request": filled[:_MAX_LEN]}
