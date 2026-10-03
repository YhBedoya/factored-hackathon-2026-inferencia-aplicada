"""The per-attempt ledger record and the sink protocol. See D9.

`core/llm` builds one `LLMCallRecord` per attempt and hands it to an injected
`LLMCallSink`; `audit.service` implements the sink, so core imports no domain.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

__all__ = ["LLMCallRecord", "LLMCallSink", "LLMCallStatus"]

# Matches the `0007` CHECK constraint on `audit.llm_calls.status`.
LLMCallStatus = Literal["ok", "invalid", "unavailable", "refused"]


@dataclass(frozen=True)
class LLMCallRecord:
    """One LLM attempt. `input_text` is the masked user message, `None` when refused."""

    step: str
    provider: str  # a plain str: B's `paraphrase` step also uses `openai` (D28)
    model_id: str
    prompt_version: str
    temperature: float | None  # None: the step sends no temperature (model default)
    attempt: int
    status: LLMCallStatus
    input_text: str | None
    output_json: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: float
    conversation_id: str | None
    turn_id: str | None
    langfuse_trace_id: str | None


class LLMCallSink(Protocol):
    async def record(self, call: LLMCallRecord) -> None: ...
