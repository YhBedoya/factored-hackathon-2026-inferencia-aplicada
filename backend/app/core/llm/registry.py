"""Model IDs, temperature and the prompt reference used to log/version calls.

See `docs/specs/d1-b-agent-sandbox.md` §"Contracts" -> `app/core/llm/`, D6,
the "Facts checked" model-ID line in `docs/plans/d1-b-agent-sandbox.md`, and
`docs/specs/d5-b-decline-explainer-test-sets.md` D13-D14 for the `paraphrase`
step (ADR-030).
"""

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "MODEL_REGISTRY",
    "STEP_PROVIDER",
    "TEMPERATURE",
    "PromptRef",
    "Provider",
    "Step",
]

Provider = Literal["anthropic", "bedrock", "openai"]
Step = Literal["nlu", "compose", "handoff_summary", "paraphrase"]

# Haiku 4.5 for every served step (D6). The Bedrock ID is a placeholder until
# Dev A's K2 confirms the inference-profile ARN/region; do not build on it
# before then. `paraphrase` is eval-only tooling (ADR-030): it has no
# Bedrock/Anthropic entry because `STEP_PROVIDER` pins it to `openai` always.
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
    "paraphrase": {"openai": "gpt-6-luna"},
}

TEMPERATURE: dict[Step, float] = {
    "nlu": 0.0,
    "compose": 0.0,
    "handoff_summary": 0.0,
    # gpt-6-luna rejects any non-default temperature ("Only the default (1)
    # value is supported"), so `paraphrase` pins 1.0 instead of 0.0; variety
    # still comes from the request (N distinct items), not from sampling.
    "paraphrase": 1.0,
}

# Steps whose provider is pinned regardless of `LLM_PROVIDER` (ADR-030). Every
# other step falls back to `settings.llm_provider`.
STEP_PROVIDER: dict[Step, Provider] = {"paraphrase": "openai"}


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
