"""R5: the LLM client refuses un-masked input before any provider call. See D8."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.llm.client import StructuredLLMClient
from app.core.llm.errors import LLMUnmaskedInput
from app.core.llm.registry import PromptRef
from app.core.llm.settings import LLMSettings
from app.core.llm.sink import LLMCallRecord


class _Echo(BaseModel):
    text: str


class _Sink:
    def __init__(self) -> None:
        self.records: list[LLMCallRecord] = []

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


def _factory_must_not_run(*_: Any) -> Any:
    raise AssertionError("the chat-model factory ran on unmasked input")


def test_raw_card_number_refused() -> None:
    sink = _Sink()
    client = StructuredLLMClient(
        LLMSettings(_env_file=None), chat_model_factory=_factory_must_not_run, sink=sink
    )
    with pytest.raises(LLMUnmaskedInput):
        asyncio.run(
            client.structured(
                step="nlu",
                prompt=PromptRef("nlu", 1),
                system="sys",
                user="mi tarjeta es 4111 1111 1111 1111",
                schema=_Echo,
            )
        )
    assert [(r.status, r.input_text) for r in sink.records] == [("refused", None)]
