"""Langfuse tracing hook.

D7 (ADR-006 amendment): tracing is a no-op until `LANGFUSE_HOST` is set. The
`llm.call` log line is today's call record; `audit.llm_calls` and a real
Langfuse span arrive on D5. Callers still wrap every attempt in this context
manager so that wiring in the real span later touches no call site.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

__all__ = ["trace_llm_call"]


@asynccontextmanager
async def trace_llm_call(
    *,
    langfuse_host: str | None,
    provider: str,
    model_id: str,
    step: str,
    prompt_version: str,
) -> AsyncIterator[None]:
    """Span one LLM call attempt. Does nothing while `langfuse_host` is unset (D7)."""
    yield
