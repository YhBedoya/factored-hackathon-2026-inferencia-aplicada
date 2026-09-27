"""`app.core.llm.client` contract tests. See D4, D5 and §"Test list" -> `test_llm_client.py`.

No test touches the network: the chat-model factory is always a stub, and
`test_provider_switch_is_local` only constructs a `ChatBedrockConverse`
object (no call). `asyncio.run` drives the async client since this project
has no async test runner (only sync pytest).
"""

import asyncio
from typing import Any

import httpx
import pytest
from anthropic import APIConnectionError
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, ConfigDict
from structlog.testing import capture_logs

from app.core.llm.client import StructuredLLMClient, build_chat_model
from app.core.llm.errors import LLMInvalidOutput, LLMUnavailable
from app.core.llm.registry import MODEL_REGISTRY, PromptRef
from app.core.llm.settings import LLMSettings


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
        self, schema: type[Any], *, include_raw: bool = False
    ) -> _StubRunnable:
        self.runnable = _StubRunnable(self._outputs)
        return self.runnable


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
    assert chat_model.max_retries == settings.max_retries  # type: ignore[attr-defined]
    assert chat_model.default_request_timeout == settings.timeout_s  # type: ignore[attr-defined]

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    stub = _StubChatModel([APIConnectionError(request=request)])
    client = StructuredLLMClient(settings, chat_model_factory=lambda s, step: stub)

    user_text = "mi numero de tarjeta es 4111 1111 1111 1111"
    with capture_logs() as logs:
        with pytest.raises(LLMUnavailable):
            asyncio.run(
                client.structured(
                    step="nlu",
                    prompt=PromptRef("nlu", 1),
                    system="sys",
                    user=user_text,
                    schema=_Echo,
                )
            )

    assert len(logs) == 1
    event = logs[0]
    assert event["event"] == "llm.call"
    assert event["provider"] == "anthropic"
    assert event["model_id"] == MODEL_REGISTRY["nlu"]["anthropic"]
    assert event["prompt_version"] == "nlu@v1"
    assert event["temperature"] == 0.0
    assert event["outcome"] == "unavailable"
    assert event["attempt"] == 1

    for value in logs[0].values():
        assert user_text not in str(value)


def test_provider_switch_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2 'switching provider changes nothing outside `core/llm`' (`LLM_PROVIDER=bedrock`)."""
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    settings = _settings()
    assert settings.llm_provider == "bedrock"

    model = build_chat_model(settings, "nlu")

    assert isinstance(model, ChatBedrockConverse)
    assert model.model_id == MODEL_REGISTRY["nlu"]["bedrock"]
