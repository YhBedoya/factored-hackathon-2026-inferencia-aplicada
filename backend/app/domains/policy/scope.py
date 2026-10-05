"""ADR-026 structured abstain map, loaded from `policies/scope.yaml` (spec
D18, R8).

One entry per NLU `topic`: whether the request is outside the market or just
outside card support, the reason key (fixed ES/PT text lives in code), the
closest supported intents to offer as chips, and the queue for a human offer.
Intents are plain strings here: `policy` must not import
`app.domains.conversation` (`06` §2), which owns the `Intent` literal.
"""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from app.domains.localization.format import Queue

__all__ = ["TOPICS", "ScopePolicy", "TopicScope", "load_scope_policy"]

# `backend/app/domains/policy/scope.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "scope.yaml"

# Mirrors the NLU `Topic` literal.
TOPICS = frozenset(
    {
        "loans",
        "accounts",
        "investments",
        "insurance",
        "transfers",
        "pix_boleto",
        "other",
    }
)


class TopicScope(BaseModel):
    """How one out-of-scope topic is abstained on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["out_of_market", "out_of_scope"]
    reason_key: str
    closest_intents: list[str]
    human_queue: Queue
    # False when a person cannot help either (e.g. a new card is not offered).
    offer_human: bool = True


class ScopePolicy(BaseModel):
    """`policies/scope.yaml`, validated (`04` §5, R8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    topics: dict[str, TopicScope]

    @model_validator(mode="after")
    def _every_topic_present(self) -> Self:
        if set(self.topics) != TOPICS:
            raise ValueError(f"topics must be exactly {sorted(TOPICS)}")
        return self


def load_scope_policy(path: Path | None = None) -> ScopePolicy:
    """Load and validate `policies/scope.yaml` (R8).

    `path` defaults to `<repo root>/policies/scope.yaml`; tests may pass
    another path without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return ScopePolicy.model_validate(raw)
