"""Fold the messages that left the 6-message window into a masked summary.

Runs before `understand` (naturalidad-cardy D3). With 6 messages or fewer it
makes no call. A failed or unsafe summary degrades quietly (D5, R11): the
window is still trimmed, the previous summary is kept, and there is no
handoff. Reads only `config["configurable"]["llm"]`: no write tool (R6).
"""

from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMClient, LLMError, PromptRef
from app.core.pii import find_pii
from app.domains.conversation.context import WINDOW
from app.domains.conversation.graph import GraphState
from app.domains.conversation.prompts import load_prompt

__all__ = ["SummaryDraft", "summarize"]

_PROMPT = PromptRef("summary", 1)


class SummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


def _build_user_message(summary: str | None, overflow: list[str], language: str) -> str:
    """Previous summary and overflow messages, inside one data fence (R6)."""
    lines = [f"Idioma: {language}", "Datos:", "```"]
    lines.append(f"Resumen previo: {summary or 'ninguno'}")
    lines.append("Mensajes:")
    lines.extend(overflow)
    lines.append("```")
    return "\n".join(lines)


async def summarize(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    history = state.get("history") or []
    if len(history) <= WINDOW:
        return {}
    kept = history[-WINDOW:]
    overflow = [f"{m['role']}: {m['text']}" for m in history[:-WINDOW]]
    llm: LLMClient = config["configurable"]["llm"]
    try:
        draft = await llm.structured(
            step="summary",
            prompt=_PROMPT,
            system=load_prompt(_PROMPT),
            user=_build_user_message(state.get("summary"), overflow, state.get("language", "es")),
            schema=SummaryDraft,
        )
    except LLMError:
        return {"history": kept}
    if find_pii(draft.text):
        return {"history": kept}
    return {"history": kept, "summary": draft.text}
