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
import types
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar, cast, get_args

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
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.faults import fault_active
from app.core.llm.errors import (
    LLMInvalidOutput,
    LLMRoundCap,
    LLMUnavailable,
    LLMUnmaskedInput,
)
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

__all__ = [
    "LLMClient",
    "LoopMessage",
    "LoopTool",
    "StructuredLLMClient",
    "build_chat_model",
    "get_llm_client",
]

T = TypeVar("T", bound=BaseModel)

_logger = structlog.get_logger()

_ERROR_MESSAGE_MAX = 300

# The schema is offered to the model as this tool; calling it is how the loop ends.
_OUTPUT_TOOL = "final_answer"


@dataclass(frozen=True)
class LoopMessage:
    """One masked history entry (or this turn's message) handed to `tool_loop`."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LoopTool:
    """A tool the model may call in `tool_loop`.

    The handler gets the validated `args_schema` instance and returns the tool
    result text (already fenced and masked by the caller). It never sees a
    provider type.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[str]]


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


def _blank_to_none(schema: type[BaseModel], args: Any) -> Any:
    """`""` becomes `None` on the top-level fields that accept `None`.

    Sonnet 4.6 on Bedrock fills an absent optional field with an empty string,
    which a `Literal[...] | None` or a pattern-checked `str | None` rejects.
    """
    if not isinstance(args, dict):
        return args
    fields = schema.model_fields
    return {
        key: None
        if value == "" and key in fields and types.NoneType in get_args(fields[key].annotation)
        else value
        for key, value in args.items()
    }


def _invalid_reason(exc: ValidationError) -> str:
    """Field paths and messages for the log, without the rejected input values (R5)."""
    return "; ".join(
        f"{'.'.join(map(str, err['loc']))}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )


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

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any: ...


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

    async def tool_loop(
        self,
        *,
        step: Step,
        prompt: PromptRef,
        system: str,
        messages: Sequence[LoopMessage],
        tools: Sequence[LoopTool],
        schema: type[T],
        max_rounds: int,
        validate: Callable[[T], str | None] | None = None,
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

    async def tool_loop(
        self,
        *,
        step: Step,
        prompt: PromptRef,
        system: str,
        messages: Sequence[LoopMessage],
        tools: Sequence[LoopTool],
        schema: type[T],
        max_rounds: int,
        validate: Callable[[T], str | None] | None = None,
    ) -> T:
        """Let the model call `tools` until it answers through the `schema` tool.

        A round is one response that asks for tools other than the output tool.
        After `max_rounds` rounds the model gets one more call; if it still asks
        for a tool, `LLMRoundCap`. Handler exceptions propagate untouched.
        """
        settings = self._settings
        provider: Provider = STEP_PROVIDER.get(step, settings.llm_provider)
        override = self._model_overrides.get(step)
        model_id = override or MODEL_REGISTRY[step][provider]
        temperature = TEMPERATURE[step]

        by_name = {tool.name: tool for tool in tools}
        chat_model = (
            self._chat_model_factory(settings, step, override)
            if override
            else self._chat_model_factory(settings, step)
        )
        # Automatic tool choice: Sonnet 5.5 rejects a forced `tool_choice` (ADR-031), so the
        # output schema is one more tool and the prompt tells the model to end with it.
        bound = chat_model.bind_tools(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema.model_json_schema(),
                }
                for tool in tools
            ]
            + [
                {
                    "name": _OUTPUT_TOOL,
                    "description": "Give the final answer for this turn. Call it alone, once.",
                    "parameters": schema.model_json_schema(),
                }
            ]
        )

        history: list[BaseMessage] = [
            HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
            for m in messages
        ]
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), None)
        attempt = 0
        rounds = 0
        invalid_seen = False
        while True:
            attempt += 1
            request: list[BaseMessage] = [SystemMessage(content=system), *history]
            # R5: system, every message and every tool result, before each provider call.
            if any(find_pii(str(m.content)) for m in request):
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

            ai, call_started, trace_id, attempt = await self._loop_call(
                bound,
                request,
                provider=provider,
                model_id=model_id,
                step=step,
                prompt=prompt,
                temperature=temperature,
                attempt=attempt,
                user=last_user,
                schema=schema,
            )
            calls = list(ai.tool_calls)
            output_calls = [c for c in calls if c["name"] == _OUTPUT_TOOL]
            other_calls = [c for c in calls if c["name"] != _OUTPUT_TOOL]

            reason: str | None = None
            log_reason: str | None = None
            if not calls:
                reason = "the response had no tool call; end with the final_answer tool"
            elif output_calls and other_calls:
                reason = "call final_answer alone, without other tools"
            elif len(output_calls) > 1:
                reason = "call final_answer once"
            elif output_calls:
                try:
                    candidate = schema.model_validate(
                        _blank_to_none(schema, output_calls[0]["args"])
                    )
                except ValidationError as exc:
                    reason = str(exc)
                    log_reason = _invalid_reason(exc)
                else:
                    reason = validate(candidate) if validate is not None else None
                    if reason is None:
                        await self._finish(
                            provider,
                            model_id,
                            step,
                            prompt,
                            temperature,
                            attempt,
                            "ok",
                            call_started,
                            user=last_user,
                            parsed=candidate,
                            raw=ai,
                            langfuse_trace_id=trace_id,
                        )
                        return candidate
            if reason is not None:
                await self._finish(
                    provider,
                    model_id,
                    step,
                    prompt,
                    temperature,
                    attempt,
                    "invalid",
                    call_started,
                    user=last_user,
                    parsed=None,
                    raw=ai,
                    langfuse_trace_id=trace_id,
                    reason=log_reason or reason,
                )
                if invalid_seen:
                    raise LLMInvalidOutput(
                        f"invalid output for step {step!r} after 2 invalid attempts"
                    )
                invalid_seen = True
                text = f"Your previous answer was invalid: {reason}. Answer again."
                history.append(ai)
                # Every tool call needs a result; the reason rides on the first one.
                if calls:
                    history.extend(
                        ToolMessage(content=text, tool_call_id=c["id"] or "") for c in calls
                    )
                else:
                    history.append(HumanMessage(content=text))
                continue

            await self._finish(
                provider,
                model_id,
                step,
                prompt,
                temperature,
                attempt,
                "ok",
                call_started,
                user=last_user,
                parsed=None,
                raw=ai,
                langfuse_trace_id=trace_id,
            )
            if rounds >= max_rounds:
                raise LLMRoundCap(f"step {step!r} still asked for tools after {max_rounds} rounds")
            rounds += 1
            history.append(ai)
            for call in other_calls:
                tool = by_name.get(call["name"])
                if tool is None:
                    result = f"unknown tool {call['name']!r}"
                else:
                    try:
                        args = tool.args_schema.model_validate(
                            _blank_to_none(tool.args_schema, call["args"])
                        )
                    except ValidationError as exc:
                        result = f"invalid arguments: {exc}"
                    else:
                        result = await tool.handler(args)
                history.append(ToolMessage(content=result, tool_call_id=call["id"] or ""))

    async def _loop_call(
        self,
        bound: Any,
        request: list[BaseMessage],
        *,
        provider: Provider,
        model_id: str,
        step: Step,
        prompt: PromptRef,
        temperature: float | None,
        attempt: int,
        user: str | None,
        schema: type[BaseModel],
    ) -> tuple[AIMessage, float, str | None, int]:
        """One provider call of `tool_loop`, with the transport retries of `structured`.

        Returns the answer, its start time, trace id and the last attempt number used
        (each transport retry is its own ledger row, so the numbers stay in call order).
        """
        settings = self._settings
        transport_failures = 0
        while True:
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
                    ai = cast(AIMessage, await bound.ainvoke(request))
                    usage = getattr(ai, "usage_metadata", None) or {}
                    span.set_usage(usage.get("input_tokens"), usage.get("output_tokens"))
                    span.set_output(None, ai)
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
                attempt += 1
                continue
            return ai, started, langfuse_trace_id, attempt

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
        reason: str | None = None,
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
        # Only on `invalid`; log-only, why the output was rejected (masked, truncated).
        if reason is not None:
            error_fields["invalid_reason"] = redact(reason)[:_ERROR_MESSAGE_MAX]
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
