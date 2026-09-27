"""Structured-output LLM client. See D4, D5 and §"Contracts" -> `LLMClient`.

The only public surface callers need is `LLMClient` (a Protocol) and
`get_llm_client`. Everything below builds and calls a LangChain chat model,
maps its exceptions to `LLMError` subclasses, retries an invalid structured
output exactly once, and logs one `llm.call` event per attempt. Callers never
see a LangChain type, a provider exception, the prompt text or the model
output text (D5, R5).
"""

import time
from collections.abc import Callable
from typing import Any, Literal, Protocol, TypeVar, cast

import anthropic
import structlog
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.llm.errors import LLMInvalidOutput, LLMUnavailable
from app.core.llm.registry import MODEL_REGISTRY, TEMPERATURE, PromptRef, Provider, Step
from app.core.llm.settings import LLMSettings
from app.core.llm.tracing import trace_llm_call

__all__ = ["LLMClient", "StructuredLLMClient", "build_chat_model", "get_llm_client"]

T = TypeVar("T", bound=BaseModel)

_Outcome = Literal["ok", "invalid", "unavailable"]

_logger = structlog.get_logger()


class _ChatModel(Protocol):
    """The one capability the wrapper needs from a chat model.

    Narrow on purpose: it is what the test seam (a stub factory) must offer,
    and it is what both `ChatAnthropic` and `ChatBedrockConverse` satisfy.
    """

    def with_structured_output(self, schema: type[Any], *, include_raw: bool = False) -> Any: ...


ChatModelFactory = Callable[[LLMSettings, Step], _ChatModel]


def build_chat_model(settings: LLMSettings, step: Step) -> _ChatModel:
    """Build the provider chat model for one step, pinned per D4/D5(b)/D6.

    Anthropic: `max_retries`/`timeout` come straight from `settings` (R11,
    `01` §7). Bedrock: the same bound is expressed as a botocore `Config`
    since `ChatBedrockConverse` has no `max_retries`/`timeout` kwargs.
    """
    model_id = MODEL_REGISTRY[step][settings.llm_provider]
    temperature = TEMPERATURE[step]
    if settings.llm_provider == "anthropic":
        return ChatAnthropic(
            model=model_id,
            temperature=temperature,
            max_retries=settings.max_retries,
            timeout=settings.timeout_s,
            api_key=settings.anthropic_api_key,
        )
    config = Config(
        retries={"max_attempts": settings.max_retries},
        read_timeout=int(settings.timeout_s),
    )
    return ChatBedrockConverse(
        model_id=model_id,
        region_name=settings.aws_region,
        credentials_profile_name=settings.aws_profile,
        temperature=temperature,
        config=config,
    )


class LLMClient(Protocol):
    """Provider-agnostic structured-output call. See §"Contracts"."""

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[T]
    ) -> T: ...


class StructuredLLMClient:
    """The concrete `LLMClient`. Takes an injectable chat-model factory (test seam)."""

    def __init__(
        self,
        settings: LLMSettings,
        chat_model_factory: ChatModelFactory = build_chat_model,
    ) -> None:
        self._settings = settings
        self._chat_model_factory = chat_model_factory

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[T]
    ) -> T:
        settings = self._settings
        provider: Provider = settings.llm_provider
        model_id = MODEL_REGISTRY[step][provider]
        temperature = TEMPERATURE[step]
        chat_model = self._chat_model_factory(settings, step)
        structured_model = chat_model.with_structured_output(schema, include_raw=True)

        messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=user)]
        last_error = ""
        for attempt in (1, 2):
            request = (
                messages
                if attempt == 1
                else [
                    *messages,
                    HumanMessage(
                        content=(
                            f"Your previous answer was invalid: {last_error}. "
                            "Reply again, matching the schema exactly."
                        )
                    ),
                ]
            )
            started = time.perf_counter()
            try:
                async with trace_llm_call(
                    langfuse_host=settings.langfuse_host,
                    provider=provider,
                    model_id=model_id,
                    step=step,
                    prompt_version=prompt.label,
                ):
                    raw_result = cast(dict[str, Any], await structured_model.ainvoke(request))
            except (anthropic.APIError, BotoCoreError, ClientError) as exc:
                self._log(
                    provider, model_id, step, prompt, temperature, attempt, "unavailable", started
                )
                raise LLMUnavailable(f"{provider} transport failed on step {step!r}") from exc

            parsed = raw_result.get("parsed")
            parsing_error = raw_result.get("parsing_error")
            if parsing_error is not None or parsed is None or not isinstance(parsed, schema):
                self._log(
                    provider, model_id, step, prompt, temperature, attempt, "invalid", started
                )
                if attempt == 2:
                    cause = parsing_error if isinstance(parsing_error, BaseException) else None
                    raise LLMInvalidOutput(
                        f"invalid structured output for step {step!r} after 2 attempts"
                    ) from cause
                last_error = (
                    str(parsing_error)
                    if parsing_error is not None
                    else "the response had no parsed output"
                )
                continue

            self._log(provider, model_id, step, prompt, temperature, attempt, "ok", started)
            return parsed

        # Unreachable: the loop above always returns or raises within 2 attempts.
        raise LLMInvalidOutput(f"invalid structured output for step {step!r}")

    def _log(
        self,
        provider: Provider,
        model_id: str,
        step: Step,
        prompt: PromptRef,
        temperature: float,
        attempt: int,
        outcome: _Outcome,
        started: float,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        trace_id = structlog.contextvars.get_contextvars().get("trace_id")
        _logger.info(
            "llm.call",
            provider=provider,
            model_id=model_id,
            step=step,
            prompt_version=prompt.label,
            temperature=temperature,
            attempt=attempt,
            outcome=outcome,
            latency_ms=latency_ms,
            trace_id=trace_id,
        )


def get_llm_client(settings: LLMSettings | None = None) -> LLMClient:
    """Build the default `LLMClient` for this process. See §"Contracts"."""
    return StructuredLLMClient(settings or LLMSettings())
