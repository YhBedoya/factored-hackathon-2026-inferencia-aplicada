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
from typing import Any, Protocol, TypeVar, cast

import anthropic
import openai
import structlog
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.llm.errors import LLMInvalidOutput, LLMUnavailable, LLMUnmaskedInput
from app.core.llm.pricing import cost_usd
from app.core.llm.registry import (
    MODEL_REGISTRY,
    STEP_PROVIDER,
    TEMPERATURE,
    PromptRef,
    Provider,
    Step,
)
from app.core.llm.settings import LLMSettings
from app.core.llm.sink import LLMCallRecord, LLMCallSink, LLMCallStatus
from app.core.llm.tracing import trace_llm_call
from app.core.pii import find_pii, redact

__all__ = ["LLMClient", "StructuredLLMClient", "build_chat_model", "get_llm_client"]

T = TypeVar("T", bound=BaseModel)

_logger = structlog.get_logger()

_ERROR_MESSAGE_MAX = 300


def _error_message(exc: BaseException) -> str:
    """Provider error text for the log: status and API error type for HTTP errors,
    PII-masked, then truncated (R5: an error body can echo the input)."""
    text = str(exc)
    if isinstance(exc, anthropic.APIStatusError | openai.APIStatusError):
        body = exc.body
        err = body.get("error", body) if isinstance(body, dict) else {}
        api_type = err.get("type") if isinstance(err, dict) else None
        api_msg = err.get("message") if isinstance(err, dict) else None
        text = f"{exc.status_code} {api_type or ''}: {api_msg or text}"
    # Mask the full text first so a match is never split at the cut, then truncate.
    return redact(text)[:_ERROR_MESSAGE_MAX]


class _ChatModel(Protocol):
    """The one capability the wrapper needs from a chat model.

    Narrow on purpose: it is what the test seam (a stub factory) must offer,
    and it is what both `ChatAnthropic` and `ChatBedrockConverse` satisfy.
    """

    def with_structured_output(
        self,
        schema: type[Any],
        *,
        include_raw: bool = False,
        method: Any = ...,
    ) -> Any: ...


ChatModelFactory = Callable[[LLMSettings, Step], _ChatModel]


def build_chat_model(settings: LLMSettings, step: Step) -> _ChatModel:
    """Build the provider chat model for one step, pinned per D4/D5(b)/D6.

    The provider is `STEP_PROVIDER.get(step, settings.llm_provider)`: most
    steps follow `LLM_PROVIDER`, but `paraphrase` is pinned to `openai`
    regardless (ADR-030). Anthropic and OpenAI: `max_retries`/`timeout` come
    straight from `settings` (R11, `01` §7). Bedrock: the same bound is
    expressed as a botocore `Config` since `ChatBedrockConverse` has no
    `max_retries`/`timeout` kwargs.
    """
    provider: Provider = STEP_PROVIDER.get(step, settings.llm_provider)
    model_id = MODEL_REGISTRY[step][provider]
    temperature = TEMPERATURE[step]
    # Omit the kwarg entirely for `None`; passing it would send a value the model rejects.
    extra: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
    if provider == "anthropic":
        return ChatAnthropic(
            model=model_id,
            **extra,
            max_retries=settings.max_retries,
            timeout=settings.timeout_s,
            api_key=settings.anthropic_api_key,
        )
    if provider == "openai":
        return ChatOpenAI(
            model=model_id,
            **extra,
            max_retries=settings.max_retries,
            timeout=settings.timeout_s,
            api_key=settings.openai_api_key,
        )
    config = Config(
        retries={"max_attempts": settings.max_retries},
        read_timeout=int(settings.timeout_s),
    )
    return ChatBedrockConverse(
        model_id=model_id,
        region_name=settings.aws_region,
        credentials_profile_name=settings.aws_profile,
        **extra,
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
        sink: LLMCallSink | None = None,
    ) -> None:
        self._settings = settings
        self._chat_model_factory = chat_model_factory
        self._sink = sink

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[T]
    ) -> T:
        settings = self._settings
        provider: Provider = STEP_PROVIDER.get(step, settings.llm_provider)
        model_id = MODEL_REGISTRY[step][provider]
        temperature = TEMPERATURE[step]

        # R5: refuse before any provider object exists. The guard can't see the
        # customer's own names (no session in core); D4 masks those upstream.
        if find_pii(system + "\n" + user):
            await self._finish(
                provider,
                model_id,
                step,
                prompt,
                temperature,
                0,
                "refused",
                time.perf_counter(),
                user=None,
                parsed=None,
                raw=None,
            )
            raise LLMUnmaskedInput(f"unmasked PII in the prompt for step {step!r}")

        chat_model = self._chat_model_factory(settings, step)
        # Anthropic: API structured outputs (`output_config.format`), which never force
        # `tool_choice` (Sonnet 5.5 rejects it). Bedrock keeps function_calling until
        # K2 confirms structured-output support there (its default path), and so does OpenAI.
        if provider == "anthropic":
            structured_model = chat_model.with_structured_output(
                schema, include_raw=True, method="json_schema"
            )
        else:
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
            langfuse_trace_id: str | None = None
            try:
                async with trace_llm_call(
                    langfuse_host=settings.langfuse_host,
                    provider=provider,
                    model_id=model_id,
                    step=step,
                    prompt_version=prompt.label,
                    input_text=user,
                ) as span:
                    langfuse_trace_id = span.id
                    raw_result = cast(dict[str, Any], await structured_model.ainvoke(request))
                    usage = getattr(raw_result.get("raw"), "usage_metadata", None) or {}
                    span.set_usage(usage.get("input_tokens"), usage.get("output_tokens"))
            except (anthropic.APIError, openai.APIError, BotoCoreError, ClientError) as exc:
                await self._finish(
                    provider,
                    model_id,
                    step,
                    prompt,
                    temperature,
                    attempt,
                    "unavailable",
                    started,
                    user=user,
                    parsed=None,
                    raw=None,
                    langfuse_trace_id=langfuse_trace_id,
                    error=exc,
                )
                raise LLMUnavailable(f"{provider} transport failed on step {step!r}") from exc

            raw = raw_result.get("raw")
            parsed = raw_result.get("parsed")
            parsing_error = raw_result.get("parsing_error")
            if parsing_error is not None or parsed is None or not isinstance(parsed, schema):
                await self._finish(
                    provider,
                    model_id,
                    step,
                    prompt,
                    temperature,
                    attempt,
                    "invalid",
                    started,
                    user=user,
                    parsed=None,
                    raw=raw,
                    langfuse_trace_id=langfuse_trace_id,
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

            await self._finish(
                provider,
                model_id,
                step,
                prompt,
                temperature,
                attempt,
                "ok",
                started,
                user=user,
                parsed=parsed,
                raw=raw,
                langfuse_trace_id=langfuse_trace_id,
            )
            return parsed

        # Unreachable: the loop above always returns or raises within 2 attempts.
        raise LLMInvalidOutput(f"invalid structured output for step {step!r}")

    async def _finish(
        self,
        provider: Provider,
        model_id: str,
        step: Step,
        prompt: PromptRef,
        temperature: float | None,
        attempt: int,
        status: LLMCallStatus,
        started: float,
        *,
        user: str | None,
        parsed: BaseModel | None,
        raw: Any,
        langfuse_trace_id: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Log `llm.call`, then ledger the attempt. A sink failure never breaks the call."""
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        ctx = structlog.contextvars.get_contextvars()
        trace_id = ctx.get("trace_id")
        # Only on `unavailable`; log-only, the ledger and Langfuse never see it.
        error_fields = (
            {"error_type": type(error).__name__, "error_message": _error_message(error)}
            if error is not None
            else {}
        )
        _logger.info(
            "llm.call",
            provider=provider,
            model_id=model_id,
            step=step,
            prompt_version=prompt.label,
            temperature=temperature,
            attempt=attempt,
            outcome=status,
            latency_ms=latency_ms,
            trace_id=trace_id,
            **error_fields,
        )
        if self._sink is None:
            return
        usage = getattr(raw, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        conversation_id = ctx.get("conversation_id")
        turn_id = ctx.get("turn_id")
        record = LLMCallRecord(
            step=step,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt.label,
            temperature=temperature,
            attempt=attempt,
            status=status,
            input_text=user,
            output_json=parsed.model_dump(mode="json") if parsed is not None else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd(model_id, input_tokens, output_tokens),
            latency_ms=latency_ms,
            conversation_id=str(conversation_id) if conversation_id is not None else None,
            turn_id=str(turn_id) if turn_id is not None else None,
            langfuse_trace_id=langfuse_trace_id,
        )
        try:
            await self._sink.record(record)
        except Exception:
            _logger.warning("llm.ledger_failed", step=step, attempt=attempt, exc_info=True)


def get_llm_client(
    settings: LLMSettings | None = None, sink: LLMCallSink | None = None
) -> LLMClient:
    """Build the default `LLMClient` for this process. See §"Contracts"."""
    return StructuredLLMClient(settings or LLMSettings(), sink=sink)
