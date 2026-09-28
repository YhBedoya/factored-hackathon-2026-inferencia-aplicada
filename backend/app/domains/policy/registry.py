"""The startup policy registry: loads every `policies/*.yaml` file, validates
each one and combines them into a single hash that reaches every downstream
decision (spec D1, D2, R8).

`tools`, `escalation`, `min_payment` and `scope` are validated against their own
domain models -- the same ones their existing per-file loaders
(`tools_policy.py`, `escalation.py`, `min_payment.py`) use. This module
doesn't replace those loaders; it adds the combined view the lifespan logs
and every `ToolContext.policy_version` carries. Any other stem
(`card_select` today) is validated here against a header-only model only:
`policy` must not import `app.domains.conversation` (`06` §2), so
`card_select.yaml`'s own shape stays checked by its own loader, called
separately by the lifespan right after this one.
"""

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from app.domains.policy.escalation import EscalationPolicy
from app.domains.policy.min_payment import MinPaymentPolicy
from app.domains.policy.scope import ScopePolicy
from app.domains.policy.tools_policy import ToolsPolicy

__all__ = [
    "PolicyBundle",
    "PolicyLoadError",
    "get_policies",
    "load_policies",
]

# `backend/app/domains/policy/registry.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICIES_DIR = _REPO_ROOT / "policies"

_MODELS_BY_STEM: dict[str, type[BaseModel]] = {
    "tools": ToolsPolicy,
    "escalation": EscalationPolicy,
    "min_payment": MinPaymentPolicy,
    "scope": ScopePolicy,
}


class _HeaderOnlyPolicy(BaseModel):
    """The stems with no domain model of their own (`card_select` today).

    Only the shared header is checked here; the file's own fields are
    validated by its own loader, called separately.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    provenance: Literal["team-generated-synthetic"]
    version: int


class PolicyLoadError(RuntimeError):
    """Raised for any YAML or validation error, naming the offending file."""


class PolicyBundle(BaseModel):
    """Every policy file loaded and validated once at startup (D1)."""

    model_config = ConfigDict(frozen=True)

    hash: str
    tools: ToolsPolicy
    escalation: EscalationPolicy
    min_payment: MinPaymentPolicy
    scope: ScopePolicy
    files: list[str]


def load_policies(directory: Path | None = None) -> PolicyBundle:
    """Load and validate every `*.yaml` file in `directory` (default
    `<repo root>/policies`), and combine them into one hashed `PolicyBundle`
    (D1).

    Files are read and hashed in sorted-name order, so the hash is
    deterministic regardless of directory listing order and covers every
    file's raw bytes -- not only the ones with their own model, so a change
    to `card_select.yaml` also moves `policy.loaded hash=`.
    """
    target_dir = directory if directory is not None else _DEFAULT_POLICIES_DIR
    paths = sorted(target_dir.glob("*.yaml"), key=lambda path: path.name)

    validated: dict[str, BaseModel] = {}
    hasher = hashlib.sha256()
    for path in paths:
        raw_bytes = path.read_bytes()
        hasher.update(path.name.encode())
        hasher.update(b"\0")
        hasher.update(raw_bytes)
        hasher.update(b"\0")
        model = _MODELS_BY_STEM.get(path.stem, _HeaderOnlyPolicy)
        try:
            raw = yaml.safe_load(raw_bytes)
            validated[path.stem] = model.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise PolicyLoadError(f"invalid policy file: {path.name}") from exc

    tools = validated.get("tools")
    escalation = validated.get("escalation")
    min_payment = validated.get("min_payment")
    scope = validated.get("scope")
    if (
        not isinstance(tools, ToolsPolicy)
        or not isinstance(escalation, EscalationPolicy)
        or not isinstance(min_payment, MinPaymentPolicy)
        or not isinstance(scope, ScopePolicy)
    ):
        missing = [
            stem
            for stem, value in (
                ("tools", tools),
                ("escalation", escalation),
                ("min_payment", min_payment),
                ("scope", scope),
            )
            if value is None
        ]
        raise PolicyLoadError(f"missing required policy file(s): {', '.join(missing)}.yaml")

    return PolicyBundle(
        hash=f"sha256:{hasher.hexdigest()}",
        tools=tools,
        escalation=escalation,
        min_payment=min_payment,
        scope=scope,
        files=[path.stem for path in paths],
    )


@lru_cache
def get_policies() -> PolicyBundle:
    """Cached: the lifespan calls this once, and every request downstream
    reuses the same `PolicyBundle` and hash (D2)."""
    return load_policies()
