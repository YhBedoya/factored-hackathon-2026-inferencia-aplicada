"""`app.core.llm.client` contract tests. See D4, D5 and §"Test list" -> `test_llm_client.py`.

No test touches the network: the chat-model factory is always a stub, and
`test_provider_switch_is_local` only constructs a `ChatBedrockConverse`
object (no call). `asyncio.run` drives the async client since this project
has no async test runner (only sync pytest).
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from anthropic import APIConnectionError, BadRequestError
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict
from structlog.testing import capture_logs

from app.core.config import get_settings
from app.core.llm.client import LoopMessage, LoopTool, StructuredLLMClient, build_chat_model
from app.core.llm.errors import LLMInvalidOutput, LLMUnavailable, LLMUnmaskedInput
from app.core.llm.registry import MODEL_REGISTRY, PromptRef
from app.core.llm.settings import LLMSettings
from app.core.llm.sink import LLMCallRecord


class _Echo(BaseModel):
    """A minimal structured-output schema, standing in for `NLUResult`/`ComposeDraft`."""

    model_config = ConfigDict(extra="forbid")

    text: str


class _StubRunnable:
    """Stands in for `with_structured_output(...)`'s return value. No network."""

    def __init__(self, outputs: list[dict[str, Any] | BaseException]) -> None:
        self._outputs = list(outputs)
        self.calls: list[Any] = []

    async def ainvoke(self, messages: Any) -> dict[str, Any]:
        self.calls.append(messages)
        result = self._outputs.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _StubChatModel:
    """Stands in for a LangChain chat model: the client's injectable test seam."""

    def __init__(self, outputs: list[dict[str, Any] | BaseException]) -> None:
        self._outputs = outputs
        self.runnable: _StubRunnable | None = None

    def with_structured_output(
        self, schema: type[Any], *, include_raw: bool = False, method: str | None = None
    ) -> _StubRunnable:
        assert method in (None, "json_schema")  # anthropic must use API structured outputs
        self.runnable = _StubRunnable(self._outputs)
        return self.runnable


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def reset_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings() -> LLMSettings:
    return LLMSettings(_env_file=None)


def test_invalid_output_retried_once() -> None:
    """B2, R11: invalid then valid -> a validated object after 2 calls.

    Invalid twice -> `LLMInvalidOutput`.
    """
    invalid = {"raw": None, "parsed": None, "parsing_error": ValueError("bad json")}
    valid = {"raw": None, "parsed": _Echo(text="ok"), "parsing_error": None}

    stub = _StubChatModel([invalid, valid])
    client = StructuredLLMClient(_settings(), chat_model_factory=lambda s, step: stub)

    result = asyncio.run(
        client.structured(
            step="nlu", prompt=PromptRef("nlu", 1), system="sys", user="hola", schema=_Echo
        )
    )

    assert result == _Echo(text="ok")
    assert stub.runnable is not None
    assert len(stub.runnable.calls) == 2

    stub_always_invalid = _StubChatModel([invalid, invalid])
    client_always_invalid = StructuredLLMClient(
        _settings(), chat_model_factory=lambda s, step: stub_always_invalid
    )
    with pytest.raises(LLMInvalidOutput):
        asyncio.run(
            client_always_invalid.structured(
                step="nlu", prompt=PromptRef("nlu", 1), system="sys", user="hola", schema=_Echo
            )
        )


def test_transport_failure_is_bounded_and_logged() -> None:
    """R11, R7, step 5: a provider exception -> `LLMUnavailable`, logged, no prompt text."""
    settings = _settings()
    chat_model = build_chat_model(settings, "nlu")
    assert chat_model.max_retries == 0  # type: ignore[attr-defined]
    # botocore: one total attempt, else a hidden retry escapes the ledger (D3).
    bedrock = build_chat_model(
        LLMSettings(_env_file=None, llm_provider="bedrock", aws_region="us-east-1"), "nlu"
    )
    retries = bedrock.client.meta.config.retries  # type: ignore[attr-defined]
    assert retries["total_max_attempts"] == 1
    assert chat_model.default_request_timeout == settings.timeout_s  # type: ignore[attr-defined]

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    raw_pii = ("4111111111111111", "ana.perez@example.com", "+52 55 1234 5678")
    error = APIConnectionError(message="echoed input: " + " ".join(raw_pii), request=request)
    stub = _StubChatModel([error, error, error])
    client = StructuredLLMClient(settings, chat_model_factory=lambda s, step: stub, sleep=_no_sleep)

    user_text = "mi tarjeta es ⟨CARD_1⟩ y quiero bloquearla"
    with capture_logs() as logs:
        with pytest.raises(LLMUnavailable):
            asyncio.run(
                client.structured(
                    step="compose",
                    prompt=PromptRef("nlu", 1),
                    system="sys",
                    user=user_text,
                    schema=_Echo,
                )
            )

    assert len(logs) == 3
    assert [log["attempt"] for log in logs] == [1, 2, 3]
    event = logs[0]
    assert event["event"] == "llm.call"
    assert event["provider"] == "anthropic"
    assert event["model_id"] == MODEL_REGISTRY["compose"]["anthropic"]
    assert event["prompt_version"] == "nlu@v1"
    assert event["temperature"] == 0.0
    assert event["outcome"] == "unavailable"
    assert event["error_type"] == "APIConnectionError"
    assert len(event["error_message"]) <= 300
    # R5: an error body can echo the input, so the logged text is masked.
    for log in logs:
        for value in raw_pii:
            assert value not in log["error_message"]
        for kind in ("CARD", "EMAIL", "PHONE"):
            assert f"⟨{kind}⟩" in log["error_message"]
        for value in log.values():
            assert user_text not in str(value)


class _RecordingSink:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, record: LLMCallRecord) -> None:
        self.records.append(record)


def test_timeout_retried_twice_then_unavailable(
    monkeypatch: pytest.MonkeyPatch, reset_settings: None
) -> None:
    """R11, D3: bedrock_timeout -> 1 call + 2 retries, one row each, no provider call."""
    monkeypatch.setenv("FAULTS", "bedrock_timeout")
    get_settings.cache_clear()
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    sink = _RecordingSink()
    stub = _StubChatModel([])
    client = StructuredLLMClient(
        _settings(), chat_model_factory=lambda s, step: stub, sink=sink, sleep=record_sleep
    )
    with pytest.raises(LLMUnavailable):
        asyncio.run(
            client.structured(
                step="nlu", prompt=PromptRef("nlu", 1), system="sys", user="hola", schema=_Echo
            )
        )
    assert [(r.attempt, r.status) for r in sink.records] == [
        (1, "unavailable"),
        (2, "unavailable"),
        (3, "unavailable"),
    ]
    assert len(sleeps) == 2
    assert stub.runnable is not None
    assert stub.runnable.calls == []

    # A non-retryable 4xx is not retried: one row, no sleep.
    monkeypatch.delenv("FAULTS")
    get_settings.cache_clear()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    bad = BadRequestError("bad", response=httpx.Response(400, request=request), body=None)
    sink = _RecordingSink()
    sleeps.clear()
    client = StructuredLLMClient(
        _settings(),
        chat_model_factory=lambda s, step: _StubChatModel([bad]),
        sink=sink,
        sleep=record_sleep,
    )
    with pytest.raises(LLMUnavailable):
        asyncio.run(
            client.structured(
                step="nlu", prompt=PromptRef("nlu", 1), system="sys", user="hola", schema=_Echo
            )
        )
    assert len(sink.records) == 1
    assert sleeps == []


def test_nlu_sends_no_temperature() -> None:
    """claude-sonnet-5-5 rejects `temperature` (400): NLU omits it and the ledger stores NULL."""
    model = build_chat_model(_settings(), "nlu")
    assert model.temperature is None  # type: ignore[attr-defined]
    payload = model._get_request_payload([("human", "hola")])  # type: ignore[attr-defined]
    assert "temperature" not in payload

    valid = {"raw": None, "parsed": _Echo(text="ok"), "parsing_error": None}
    sink = _RecordingSink()
    client = StructuredLLMClient(
        _settings(), chat_model_factory=lambda s, step: _StubChatModel([valid]), sink=sink
    )
    asyncio.run(
        client.structured(
            step="nlu", prompt=PromptRef("nlu", 1), system="sys", user="hola", schema=_Echo
        )
    )
    assert [r.temperature for r in sink.records] == [None]


def test_provider_switch_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 'switching provider changes nothing outside `core/llm`' (`LLM_PROVIDER=bedrock`)."""
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    settings = _settings()
    assert settings.llm_provider == "bedrock"

    model = build_chat_model(settings, "nlu")

    assert isinstance(model, ChatBedrockConverse)
    assert model.model_id == MODEL_REGISTRY["nlu"]["bedrock"]


class _Lookup(BaseModel):
    q: str


class _ToolStubChatModel:
    """Chat model for `tool_loop`: replays AI messages and counts provider calls."""

    def __init__(self, replies: list[AIMessage]) -> None:
        self.replies = list(replies)
        self.calls = 0

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ToolStubChatModel":
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.calls += 1
        return self.replies.pop(0)


def test_r5_tool_loop_refuses_unmasked_tool_result() -> None:
    """R5: a raw email in a tool result stops the loop before the second provider call."""
    ask = AIMessage(content="", tool_calls=[{"name": "lookup", "args": {"q": "x"}, "id": "t1"}])
    stub = _ToolStubChatModel([ask, ask])

    async def leak(_: BaseModel) -> str:
        return "contact: ana.perez@example.com"

    client = StructuredLLMClient(_settings(), chat_model_factory=lambda s, step: stub)  # type: ignore[arg-type]
    with pytest.raises(LLMUnmaskedInput):
        asyncio.run(
            client.tool_loop(
                step="agent",
                prompt=PromptRef("agent", 1),
                system="sys",
                messages=[LoopMessage("user", "hola")],
                tools=[LoopTool("lookup", "look up", _Lookup, leak)],
                schema=_Echo,
                max_rounds=3,
            )
        )
    assert stub.calls == 1
