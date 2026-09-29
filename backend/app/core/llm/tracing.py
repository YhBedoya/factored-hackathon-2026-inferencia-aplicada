"""Langfuse tracing hook.

D7 (ADR-006 amendment): tracing is a no-op until `LANGFUSE_HOST` is set. D10:
with it set, each call attempt opens a Langfuse generation on a self-hosted
instance. Callers wrap every attempt in this context manager, so the span
touches no call site.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from langfuse import Langfuse
from langfuse.span_filter import is_langfuse_span

from app.core.llm.settings import LLMSettings
from app.core.pii import redact

__all__ = ["LLMSpan", "langfuse_mask", "trace_llm_call"]


class LLMSpan:
    """Handle yielded by `trace_llm_call`: the trace id and a usage reporter.

    Both are inert (`id` None, `set_usage` does nothing) when the call isn't traced.
    """

    def __init__(self, generation: Any | None = None) -> None:
        self._generation = generation
        self.id: str | None = generation.trace_id if generation is not None else None

    def set_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        """Report the attempt's token counts on the generation (cost is left to Langfuse)."""
        if self._generation is None or input_tokens is None or output_tokens is None:
            return
        self._generation.update(usage_details={"input": input_tokens, "output": output_tokens})


def langfuse_mask(*, data: Any, **_: Any) -> Any:
    """Second line of defence (R5): redact every string in what Langfuse records.

    The SDK calls the mask with `data=` for input, output and metadata, which may be
    nested dicts and lists.
    """
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, dict):
        return {key: langfuse_mask(data=value) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [langfuse_mask(data=item) for item in data]
    return data


@lru_cache(maxsize=1)
def _client(host: str) -> Langfuse | None:
    settings = LLMSettings()
    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        return None
    return Langfuse(
        public_key=settings.langfuse_public_key.get_secret_value(),
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=host,
        mask=langfuse_mask,
        # Only the SDK's own spans: the app's OTel spans (FastAPI, asyncpg, ...) go
        # to the collector and must never reach Langfuse (D34).
        should_export_span=is_langfuse_span,
    )


@asynccontextmanager
async def trace_llm_call(
    *,
    langfuse_host: str | None,
    provider: str,
    model_id: str,
    step: str,
    prompt_version: str,
    input_text: str | None = None,
) -> AsyncIterator[LLMSpan]:
    """Span one LLM call attempt and yield an `LLMSpan` (trace id, usage reporter).

    Does nothing while `langfuse_host` or the keys are unset (D7).
    """
    client = _client(langfuse_host) if langfuse_host else None
    if client is None:
        yield LLMSpan()
        return
    with client.start_as_current_observation(
        name=step,
        as_type="generation",
        model=model_id,
        input=input_text,
        metadata={"provider": provider, "step": step, "prompt_version": prompt_version},
    ) as generation:
        yield LLMSpan(generation)
