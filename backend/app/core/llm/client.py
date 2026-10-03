"""Structured-output LLM client. See D4, D5 and §"Contracts" -> `LLMClient`.

The only public surface callers need is `LLMClient` (a Protocol) and
`get_llm_client`. Everything below builds and calls a LangChain chat model,
maps its exceptions to `LLMError` subclasses, retries an invalid structured
output exactly once, and logs one `llm.call` event per attempt. Callers never
see a LangChain type, a provider exception, the prompt text or the model
output text (D5, R5).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar, cast

import anthropic
import openai
import structlog
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.faults import fault_active
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
from app.core.retry import backoff_delay

__all__ = ["LLMClient", "StructuredLLMClient", "build_chat_model", "get_llm_client"]

T = TypeVar("T", bound=BaseModel)

_logger = structlog.get_logger()

_ERROR_MESSAGE_MAX = 300

_TRANSPORT_ERRORS = (anthropic.APIError, openai.APIError, BotoCoreError, ClientError)
_BEDROCK_THROTTLING = frozenset(
    {"ThrottlingException", "TooManyRequestsException", "ProvisionedThroughputExceededException"}
)


class _SyntheticTimeout(Exception):
    """Raised by the `bedrock_timeout` fault in place of the provider call."""


def _is_retryable(exc: BaseException) -> bool:
    """Timeout, connection, 429 or 5xx are worth a retry (R11); any other error is not."""
    if isinstance(
        exc, _SyntheticTimeout | anthropic.APIConnectionError | openai.APIConnectionError
    ):
        return True  # APITimeoutError is an APIConnectionError
    if isinstance(exc, anthropic.APIStatusError | openai.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return error.get("Code") in _BEDROCK_THROTTLING or status >= 500
    return isinstance(exc, ReadTimeoutError | ConnectTimeoutError | EndpointConnectionError)


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


def _as_chat_dict(message: BaseMessage) -> dict[str, str]:
    """One sent message in Langfuse's chat shape (`role`/`content`), for the trace input."""
    role = {"system": "system", "human": "user", "ai": "assistant"}.get(message.type, message.type)
    return {"role": role, "content": str(message.content)}


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


# Called with `(settings, step)`; only an overridden step adds a third `model_id` argument,
# so a two-argument stub factory keeps working when no override is set.
ChatModelFactory = Callable[..., _ChatModel]


def build_chat_model(settings: LLMSettings, step: Step, model_id: str | None = None) -> _ChatModel:
    """Build the provider chat model for one step, pinned per D4/D5(b)/D6.

    The provider is `STEP_PROVIDER.get(step, settings.llm_provider)`: most
    steps follow `LLM_PROVIDER`, but `paraphrase` is pinned to `openai`
    regardless (ADR-030). Every SDK is built with no internal retries: the
    client's own transport loop owns the bound (R11, D3), so a retry is never
    hidden from the ledger. `timeout` applies per attempt. Bedrock expresses
    both as a botocore `Config` since `ChatBedrockConverse` has no such kwargs.
    `model_id` replaces the registry ID for the eval NLU comparison (D15); the
    provider, temperature and prompt stay the step's.
    """
    provider: Provider = STEP_PROVIDER.get(step, settings.llm_provider)
    model_id = model_id or MODEL_REGISTRY[step][provider]
    temperature = TEMPERATURE[step]
    # Omit the kwarg entirely for `None`; passing it would send a value the model rejects.
    extra: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
    if provider == "anthropic":
        return ChatAnthropic(
            model=model_id,
            **extra,
            max_retries=0,
            timeout=settings.timeout_s,
            api_key=settings.anthropic_api_key,
        )
    if provider == "openai":
        return ChatOpenAI(
            model=model_id,
            **extra,
            max_retries=0,
            timeout=settings.timeout_s,
            api_key=settings.openai_api_key,
        )
    config = Config(
        # `max_attempts` counts retries in botocore; `total_max_attempts` is the real total.
        retries={"total_max_attempts": 1, "mode": "standard"},
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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        model_overrides: Mapping[Step, str] | None = None,
    ) -> None:
        self._settings = settings
        self._chat_model_factory = chat_model_factory
        self._sink = sink
        self._sleep = sleep
        self._model_overrides = dict(model_overrides or {})

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[T]
    ) -> T:
        settings = self._settings
        provider: Provider = STEP_PROVIDER.get(step, settings.llm_provider)
        override = self._model_overrides.get(step)
        model_id = override or MODEL_REGISTRY[step][provider]
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

        chat_model = (
            self._chat_model_factory(settings, step, override)
            if override
            else self._chat_model_factory(settings, step)
        )
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
        # One counter for both retry kinds, so ledger attempts read 1, 2, 3... in call order.
        attempt = 0
        transport_failures = 0
        invalid_seen = False
        while True:
            attempt += 1
            request = (
                messages
                if not invalid_seen
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
                    messages=[_as_chat_dict(m) for m in request],
                    output_schema=schema.model_json_schema(),
                ) as span:
                    langfuse_trace_id = span.id
                    if fault_active("bedrock_timeout"):
                        raise _SyntheticTimeout("bedrock_timeout fault")
                    raw_result = cast(dict[str, Any], await structured_model.ainvoke(request))
                    usage = getattr(raw_result.get("raw"), "usage_metadata", None) or {}
                    span.set_usage(usage.get("input_tokens"), usage.get("output_tokens"))
                    span.set_output(raw_result.get("parsed"), raw_result.get("raw"))
            except (*_TRANSPORT_ERRORS, _SyntheticTimeout) as exc:
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
                transport_failures += 1
                if not _is_retryable(exc) or transport_failures > get_settings().retry_max:
                    raise LLMUnavailable(f"{provider} transport failed on step {step!r}") from exc
                await self._sleep(backoff_delay(transport_failures))
                continue

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
                if invalid_seen:
                    cause = parsing_error if isinstance(parsing_error, BaseException) else None
                    raise LLMInvalidOutput(
                        f"invalid structured output for step {step!r} after 2 invalid attempts"
                    ) from cause
                invalid_seen = True
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
    settings: LLMSettings | None = None,
    sink: LLMCallSink | None = None,
    *,
    model_overrides: Mapping[Step, str] | None = None,
) -> LLMClient:
    """Build the default `LLMClient` for this process. See §"Contracts".

    `model_overrides` swaps the model ID per step for the eval NLU comparison
    (D15); the served graph never passes it.
    """
    return StructuredLLMClient(
        settings or LLMSettings(), sink=sink, model_overrides=model_overrides
    )
