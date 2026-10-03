"""Writes the `request` line and the `case_summary` of a handoff packet (D1-D4, R4-R6, R11).

This is the LLM half of the handoff: it has no write or handoff tools (R6). The
user message carries the masked transcript (`content_masked` only, R5), code-built
keys and the placeholder keys on offer, all inside one data fence. Numbers come
only from placeholders filled in code (R4): `{card_mask}`, `{tx_count}`,
`{plan_card_mask}` and `{queue_label}`. A draft with an unknown placeholder, a
brace residue or a raw digit in any of its four fields, or an `LLMError`, is
replaced by a fixed per-reason `request` and no case summary (R11); the LLM is
never called a second time.

The node writes graph-local `handoff_request` and `handoff_case_summary`; the
code-only `handoff` node reads them next.
"""

import re
from collections.abc import Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.llm import LLMClient, LLMError, PromptRef
from app.domains.conversation.graph import GraphState
from app.domains.conversation.prompts import load_prompt
from app.domains.conversation.store import MessageRow
from app.domains.conversation.templates import Language
from app.domains.handoff.schemas import CaseSummary
from app.domains.localization import mask_card, queue_label
from app.domains.policy.escalation import load_escalation_policy, resolve_escalation

__all__ = ["HandoffSummaryDraft", "handoff_summary"]

_PROMPT = PromptRef("handoff_summary", 2)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_MAX_LEN = 200
_CASE_MAX_LEN = 280
_TRANSCRIPT_ROWS = 30
_TRANSCRIPT_ROW_LEN = 500

# Fixed agent-facing texts per reason, used when the draft is rejected or the
# LLM fails (R11). Digit-free on purpose: they carry no placeholders.
_FALLBACK: dict[str, dict[Language, str]] = {
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
    asked: str
    did: str
    unfinished: str


def _fallback(reason: str | None, language: Language) -> str:
    return _FALLBACK.get(reason or _DEFAULT_REASON, _FALLBACK[_DEFAULT_REASON])[language]


async def _load_transcript(configurable: dict[str, Any]) -> list[MessageRow]:
    """The session-bound transcript loader's rows; empty when absent or failing."""
    loader = configurable.get("transcript")
    if loader is None:
        return []
    try:
        return list(await loader())
    except Exception:  # the transcript is optional context; the summary must not fail on it
        return []


def _transcript_lines(rows: Sequence[MessageRow]) -> list[str]:
    """Last 30 rows as `role: masked text`; never reads the raw `content` (R5)."""
    return [
        f"{row.role}: {row.content_masked[:_TRANSCRIPT_ROW_LEN]}"
        for row in rows[-_TRANSCRIPT_ROWS:]
        if row.content_masked
    ]


def _unanswered_confirm_facts(rows: Sequence[MessageRow]) -> dict[str, str]:
    """Step facts of the last `confirm` the customer has not answered yet (D3).

    A button decision runs without text, so it persists a bot row in a turn with
    no customer row; any such row after the confirm means it was answered.
    """
    index: int | None = None
    events: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        payload = row.ui_payload
        if row.role != "bot" or not isinstance(payload, list):
            continue
        confirms = [event for event in payload if event.get("kind") == "confirm"]
        if confirms:
            index, events = i, confirms
    if index is None:
        return {}
    customer_turns = {row.turn_id for row in rows if row.role == "customer"}
    if any(row.role == "bot" and row.turn_id not in customer_turns for row in rows[index + 1 :]):
        return {}
    facts: dict[str, str] = {}
    for event in events:
        for step in event.get("payload", {}).get("steps", []):
            for fact in step.get("facts", []):
                if fact.get("value") is not None:
                    facts.setdefault(str(fact.get("key")), str(fact["value"]))
    return facts


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
        return {"handoff_request": _fallback(None, language), "handoff_case_summary": None}
    reason, queue = resolution.reason, resolution.queue
    fallback = _fallback(reason, language)
    # Under LLM_DISABLED there is no model to ask; `llm_unavailable` with the LLM
    # enabled still tries it (retries included) and falls back on `LLMError`.
    failed: dict[str, Any] = {"handoff_request": fallback, "handoff_case_summary": None}
    if get_settings().llm_disabled:
        return failed

    rows = await _load_transcript(configurable)
    confirm_facts = _unanswered_confirm_facts(rows)
    # Each placeholder is offered only when it has a value (AS3).
    values: dict[str, str] = {"queue_label": queue_label(queue, language)}
    evidence = state.get("handoff_evidence") or []
    if evidence:
        values["tx_count"] = str(len(evidence))
    elif "tx_count" in confirm_facts:
        values["tx_count"] = confirm_facts["tx_count"]
    if "card_mask" in confirm_facts:
        values["plan_card_mask"] = confirm_facts["card_mask"]
    # `card_mask` is offered only when the selected card's last4 can be read.
    card_id = state.get("selected_card_id")
    if card_id:
        try:
            details = await configurable["bank_tools"].get_card_details(card_id)
            values["card_mask"] = mask_card(details.last4)
        except Exception:  # the mask is optional; the summary must not fail on it
            pass

    actions = [f"{a.tool} verified={str(a.verified).lower()}" for a in state.get("actions", [])]
    user = "\n".join(
        [
            f"Idioma de la solicitud: {language}",
            f"Motivo: {reason}",
            f"Cola: {queue}",
            "```",
            f"intents: {', '.join(intents) or '-'}",
            f"acciones: {'; '.join(actions) or '-'}",
            f"placeholders: {', '.join('{' + k + '}' for k in values)}",
            "conversación:",
            *(_transcript_lines(rows) or ["-"]),
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
        return failed

    for text in (draft.request, draft.asked, draft.did, draft.unfinished):
        if any(key not in values for key in _PLACEHOLDER.findall(text)):
            return failed
        residual = _PLACEHOLDER.sub("", text)
        if "{" in residual or "}" in residual or any(c.isdigit() for c in residual):
            return failed

    def fill(text: str, limit: int) -> str:
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], text)[:limit]

    case = CaseSummary(
        asked=fill(draft.asked, _CASE_MAX_LEN),
        did=fill(draft.did, _CASE_MAX_LEN),
        unfinished=fill(draft.unfinished, _CASE_MAX_LEN),
    )
    return {
        "handoff_request": fill(draft.request, _MAX_LEN),
        "handoff_case_summary": case.model_dump(),
    }
