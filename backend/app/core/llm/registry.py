"""Model IDs, temperature and the prompt reference used to log/version calls.

See `docs/specs/d1-b-agent-sandbox.md` §"Contracts" -> `app/core/llm/`, D6 and
the "Facts checked" model-ID line in `docs/plans/d1-b-agent-sandbox.md`.
"""

from dataclasses import dataclass
from typing import Literal

__all__ = ["MODEL_REGISTRY", "TEMPERATURE", "PromptRef", "Provider", "Step"]

Provider = Literal["anthropic", "bedrock"]
Step = Literal["nlu", "compose", "handoff_summary"]

# Haiku 4.5 for every step (D6). The Bedrock ID is a placeholder until Dev A's
# K2 confirms the inference-profile ARN/region; do not build on it before then.
MODEL_REGISTRY: dict[Step, dict[Provider, str]] = {
    "nlu": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    "compose": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    "handoff_summary": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
}

TEMPERATURE: dict[Step, float] = {"nlu": 0.0, "compose": 0.0, "handoff_summary": 0.0}


@dataclass(frozen=True)
class PromptRef:
    """A prompt file's name and version, e.g. `prompts/nlu@v1.md`.

    `label` is what the `llm.call` log line and Langfuse carry as
    `prompt_version` (D7, end-of-day step 5) -- never the prompt text itself.
    """

    name: str
    version: int

    @property
    def label(self) -> str:
        return f"{self.name}@v{self.version}"
