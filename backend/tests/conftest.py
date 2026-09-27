"""Shared pytest fixtures. See D1-B state file's T8 entry for how tasks reuse these.

`ScriptedLLM` is a fake `LLMClient`: no network, no LangChain, per-step queues
of canned outputs (or exceptions) that tests script ahead of time, and a
`calls` list recording exactly what each `structured()` call was asked --
`step`, `prompt`, `system`, `user` and `schema` -- so a test can assert what
did (and did not) reach the "model".
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from app.core.llm import LLMError, PromptRef, Step

__all__ = ["Call", "ScriptedLLM"]


@dataclass(frozen=True)
class Call:
    """One recorded `ScriptedLLM.structured()` call."""

    step: Step
    prompt: PromptRef
    system: str
    user: str
    schema: type[BaseModel]


@dataclass
class ScriptedLLM:
    """A scripted `LLMClient` fake. Construct with a queue per step.

    >>> llm = ScriptedLLM({"compose": [ComposeDraft(text="hola {card_mask}")]})
    >>> await llm.structured(step="compose", ..., schema=ComposeDraft)
    ComposeDraft(text="hola {card_mask}")
    >>> llm.calls[0].step
    'compose'
    """

    outputs: dict[Step, Sequence[BaseModel | LLMError]] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list, init=False)
    _queues: dict[Step, list[BaseModel | LLMError]] = field(init=False)

    def __post_init__(self) -> None:
        self._queues = {step: list(items) for step, items in self.outputs.items()}

    async def structured(
        self, *, step: Step, prompt: PromptRef, system: str, user: str, schema: type[Any]
    ) -> Any:
        self.calls.append(Call(step=step, prompt=prompt, system=system, user=user, schema=schema))
        queue = self._queues.get(step)
        if not queue:
            raise AssertionError(f"ScriptedLLM: no scripted output left for step {step!r}")
        result = queue.pop(0)
        if isinstance(result, LLMError):
            raise result
        return cast(Any, result)


@pytest.fixture
def scripted_llm() -> type[ScriptedLLM]:
    """A factory fixture: call it with the per-step outputs dict to build one `ScriptedLLM`."""
    return ScriptedLLM


@pytest.fixture
def fakebank_dir() -> Path:
    """The fabricated TEST FIXTURE data directory (T5), never `data/`."""
    return Path(__file__).resolve().parent / "fixtures" / "fakebank"
