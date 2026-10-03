"""The `PlaybooksPolicy` built from `policies/playbooks.yaml` (spec D22, R8).

Playbooks only guide the agent: one text per request type saying what to ask
and which tool to read with. They hold no policy value. Loaded with the
`tools_policy.py` pattern: a frozen, `extra="forbid"` model whose required
`provenance`/`version` make a header-less file fail to load.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = ["PlaybooksPolicy", "load_playbooks_policy"]

# `backend/app/domains/policy/playbooks.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "playbooks.yaml"


class PlaybooksPolicy(BaseModel):
    """`policies/playbooks.yaml`, validated (`04` §5, R8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    playbooks: dict[str, str]


def load_playbooks_policy(path: Path | None = None) -> PlaybooksPolicy:
    """Load and validate `policies/playbooks.yaml` (R8).

    `path` defaults to `<repo root>/policies/playbooks.yaml`; tests may pass
    another path without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return PlaybooksPolicy.model_validate(raw)
