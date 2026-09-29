"""Errors raised by the `app.core.llm` wrapper. See D5.

These are the only exceptions callers of `LLMClient.structured` need to
handle; a provider's own exception types never escape `core/llm`.
"""

__all__ = ["LLMError", "LLMInvalidOutput", "LLMUnavailable", "LLMUnmaskedInput"]


class LLMError(Exception):
    """Base class for errors raised by `app.core.llm`."""


class LLMUnavailable(LLMError):
    """R11 transport retries exhausted (`max_retries`) without a response. See D5(b)."""


class LLMInvalidOutput(LLMError):
    """The structured output was still invalid after the one retry. See D5(a)."""


class LLMUnmaskedInput(LLMError):
    """R5: the prompt still held raw PII, so no provider call was made. See D8."""
