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
Step = Literal[
    "nlu",
    "agent",
    "compose",
    "handoff_summary",
    "summary",
    "sentiment",
    "paraphrase",
    "simulate",
    "judge",
    "intent_gen",
]

# Sonnet 5.5 for NLU (human decision, D5-A); Haiku 4.5 for the other served steps (D6).
# The Bedrock IDs are placeholders until Dev A's K2 confirms the inference-profile
# ARN/region; do not build on them before then. `paraphrase` is eval-only tooling
# (ADR-030): it has no Bedrock/Anthropic entry because `STEP_PROVIDER` pins it to
# `openai` always.
MODEL_REGISTRY: dict[Step, dict[Provider, str]] = {
    "nlu": {
        "anthropic": "claude-sonnet-5-5",
        "bedrock": "us.anthropic.claude-sonnet-5-5",  # unconfirmed until K2
    },
    # The tool-using conversation agent (cardy-agent-s1 D2): same model as `nlu`.
    "agent": {
        "anthropic": "claude-sonnet-5-5",
        "bedrock": "us.anthropic.claude-sonnet-5-5",  # unconfirmed until K2
    },
    "compose": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    "handoff_summary": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    # Folds the messages that left the 6-message window into a masked summary
    # (naturalidad-cardy D3).
    "summary": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    # Offline analytics worker (ADR-033, D13): scores customer-message sentiment.
    "sentiment": {
        "anthropic": "claude-haiku-4-5-20251001",
        "bedrock": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # unconfirmed until K2
    },
    "paraphrase": {"openai": "gpt-6-luna"},
    # Same eval-only tooling and model as `paraphrase` (ADR-030 "Simulator note",
    # D6-B): the goal-driven customer simulator, `eval/simulator/simulator.py`.
    "simulate": {"openai": "gpt-6-luna"},
    # Same eval-only tooling and model, ADR-030 pattern (D7-B D14): the offline
    # reply-quality judge, `eval/judges/judge.py`. Scores dev-suite transcripts
    # only, never the served graph.
    "judge": {"openai": "gpt-6-luna"},
    # Same eval-only tooling and model (ADR-032, extending ADR-030's list):
    # offline training-data generation, `ml/intent/generate.py`. Never runs in
    # the served graph.
    "intent_gen": {"openai": "gpt-6-luna"},
}

# `None` means "send no temperature" (the model default). claude-sonnet-5-5 answers
# `400 invalid_request_error: "temperature" is deprecated for this model` to any
# value, so `nlu` omits it; the ledger records NULL for those calls.
TEMPERATURE: dict[Step, float | None] = {
    "nlu": None,
    "agent": None,  # same Sonnet 5.5 constraint as `nlu`
    "compose": 0.0,
    "handoff_summary": 0.0,
    "summary": 0.0,
    "sentiment": 0.0,
    # gpt-6-luna rejects any non-default temperature ("Only the default (1)
    # value is supported"), so `paraphrase` pins 1.0 instead of 0.0; variety
    # still comes from the request (N distinct items), not from sampling.
    "paraphrase": 1.0,
    # Same gpt-6-luna constraint as `paraphrase`; the card and `05` §5 say
    # "temperature 0" for the simulator, but it runs at 1.0 (D6-B D2).
    "simulate": 1.0,
    # Same gpt-6-luna constraint again; D14 pins 1.0 as "the only value the
    # model accepts", so `agreement.md` carries a non-repeatable caveat instead
    # of relying on a low temperature for reproducibility.
    "judge": 1.0,
    # Same gpt-6-luna constraint (ADR-032, eval-only).
    "intent_gen": 1.0,
}

# Steps whose provider is pinned regardless of `LLM_PROVIDER` (ADR-030). Every
# other step falls back to `settings.llm_provider`.
STEP_PROVIDER: dict[Step, Provider] = {
    "paraphrase": "openai",
    "simulate": "openai",
    "judge": "openai",
    "intent_gen": "openai",  # ADR-032, eval-only
}


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
