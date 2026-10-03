"""Sentiment scoring for the analytics worker (ADR-033, D13, REQ-R4).

`SentimentScorer` is the seam the worker depends on; `HaikuSentimentScorer`
is the one implementation. It reads only masked customer text (R5, the
caller passes `content_masked`) and calls only `LLMClient.structured` (R7).
It adds no retry of its own: the client's two retries are the bound (R11).
Any `LLMError`, or `LLM_DISABLED`, gives `None` ("unavailable") and the worker
leaves the sentiment columns null for a later pass.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

import structlog
from pydantic import BaseModel, ConfigDict

from app.core.config import get_settings
from app.core.llm import LLMCallRecord, LLMCallSink, LLMClient, LLMError, PromptRef, get_llm_client

__all__ = ["HaikuSentimentScorer", "SentimentLabels", "SentimentResult", "SentimentScorer"]

Label = Literal["negative", "neutral", "positive"]

_PROMPT = PromptRef("sentiment", 1)
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / f"{_PROMPT.label}.md"


@dataclass(frozen=True)
class SentimentResult:
    overall: Label
    start: Label
    end: Label
    model: str
    prompt_version: str
    cost_usd: Decimal | None  # None when no attempt could be priced


class SentimentScorer(Protocol):
    async def score(
        self, conversation_id: str, messages: Sequence[str], language: str
    ) -> SentimentResult | None:
        """Score one conversation; `None` means unavailable (retry later)."""
        ...


class SentimentLabels(BaseModel):
    """The sentiment call's structured output."""

    model_config = ConfigDict(extra="forbid")

    overall: Label
    start: Label
    end: Label


class _CostSink:
    """Collects every attempt's record for one call and forwards it to the inner sink."""

    def __init__(self, inner: LLMCallSink | None) -> None:
        self._inner = inner
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)
        if self._inner is not None:
            await self._inner.record(call)


def _default_client(sink: LLMCallSink) -> LLMClient:
    return get_llm_client(sink=sink)


class HaikuSentimentScorer:
    """`SentimentScorer` on the `sentiment` step (Haiku 4.5)."""

    def __init__(
        self,
        sink: LLMCallSink | None = None,
        *,
        client_factory: Callable[[LLMCallSink], LLMClient] = _default_client,
    ) -> None:
        # `client_factory` is the test seam: it receives the per-call wrapper sink.
        self._sink = sink
        self._client_factory = client_factory

    async def score(
        self, conversation_id: str, messages: Sequence[str], language: str
    ) -> SentimentResult | None:
        if not messages or get_settings().llm_disabled:
            return None
        # One wrapper and client per call, so concurrent scores never mix costs.
        collector = _CostSink(self._sink)
        client = self._client_factory(collector)
        numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(messages, start=1))
        user = f"Language: {language}\nCustomer messages:\n```\n{numbered}\n```"
        # The client reads conversation_id from the contextvars to attribute the ledger row.
        with structlog.contextvars.bound_contextvars(conversation_id=conversation_id):
            try:
                labels = await client.structured(
                    step="sentiment",
                    prompt=_PROMPT,
                    system=_PROMPT_PATH.read_text(encoding="utf-8"),
                    user=user,
                    schema=SentimentLabels,
                )
            except LLMError:
                return None
        # One message has no start and end to tell apart (REQ-R4.4): set in code.
        start, end = (
            (labels.overall, labels.overall) if len(messages) == 1 else (labels.start, labels.end)
        )
        costs = [r.cost_usd for r in collector.records if r.cost_usd is not None]
        last = collector.records[-1] if collector.records else None
        return SentimentResult(
            overall=labels.overall,
            start=start,
            end=end,
            model=last.model_id if last is not None else "",
            prompt_version=_PROMPT.label,
            cost_usd=sum(costs, Decimal(0)) if costs else None,
        )
