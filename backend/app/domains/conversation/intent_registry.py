"""The intent registry (ADR-032, D13): `intents.yaml` plus its loader.

`graph.py` builds its dispatch tables from it and the learned classifier's
label set is read off it. The `Intent` Literal in `schemas.py` and the
`nlu@v6` prompt's closed list stay check-only (`test_registry_consistency`).
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.domains.policy.registry import get_policies

__all__ = [
    "IntentRow",
    "Registry",
    "classifier_labels",
    "intent_nodes",
    "load_registry",
    "management_intents",
]

_REGISTRY_PATH = Path(__file__).with_name("intents.yaml")


class IntentRow(BaseModel):
    """One registry row: where an intent goes and whether the classifier learns it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: str
    node: str | None
    tier: Literal["core", "management", "stretch"]
    classifier: bool
    training_dir: str | None
    lexicon_key: str | None


class Registry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label_set_version: int
    intents: tuple[IntentRow, ...]


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    raw = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return Registry.model_validate(raw)


def classifier_labels() -> tuple[str, ...]:
    """`classifier: true` intents in registry order, then the `scope.yaml` topics in file order."""
    intents = tuple(r.intent for r in load_registry().intents if r.classifier)
    return intents + tuple(get_policies().scope.topics)


def intent_nodes() -> dict[str, str]:
    """Intent -> flow node, for rows with a node that are not conversation management."""
    return {
        r.intent: r.node
        for r in load_registry().intents
        if r.node is not None and r.tier != "management"
    }


def management_intents() -> frozenset[str]:
    return frozenset(r.intent for r in load_registry().intents if r.tier == "management")
