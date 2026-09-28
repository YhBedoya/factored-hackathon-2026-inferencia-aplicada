"""The D2-K `StepUpRule` built from `policies/tools.yaml` (spec D2, R8).

`policies/tools.yaml` is provisional: it carries only the confirmation and
step-up flags of the five write tools, and D3-A1 extends this file and this
loader rather than replacing them. Loaded with the `card_select.py` pattern:
a frozen, `extra="forbid"` model whose required `provenance`/`version` make a
header-less file fail to load.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ToolPolicy",
    "ToolsPolicy",
    "load_tools_policy",
    "step_up_rule",
]

# `backend/app/domains/policy/tools_policy.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "tools.yaml"

StepUp = Literal["never", "always", "when_address_changed"]


class ToolPolicy(BaseModel):
    """One entry of the `tools` map: a single write tool's confirmation and
    step-up flags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_confirmation: bool
    step_up: StepUp


class ToolsPolicy(BaseModel):
    """`policies/tools.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no step-up rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: str
    version: int
    tools: dict[str, ToolPolicy]


def load_tools_policy(path: Path | None = None) -> ToolsPolicy:
    """Load and validate `policies/tools.yaml` (R8).

    `path` defaults to `<repo root>/policies/tools.yaml`; tests may pass
    another path to check the rejection rule without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return ToolsPolicy.model_validate(raw)


def step_up_rule(
    policy: ToolsPolicy,
) -> Callable[[str, Mapping[str, str | int | bool | None]], bool]:
    """Build the executor's `StepUpRule` from a loaded `ToolsPolicy` (D2).

    The return type matches `conversation/tools/executor.py`'s `StepUpRule`
    structurally: mypy checks a `Callable`'s shape by signature, not by
    import, so this module never imports `app.domains.conversation` (`06`
    §2). An unknown `tool` raises `KeyError`, the same way a missing
    `floors[currency]` does in `policy/min_payment.py`: a policy gap fails
    loudly instead of defaulting to "no step-up".
    """

    def rule(tool: str, args: Mapping[str, str | int | bool | None]) -> bool:
        step_up = policy.tools[tool].step_up
        if step_up == "always":
            return True
        if step_up == "never":
            return False
        # "when_address_changed" (D4): a replacement sent to the address on
        # file needs no step-up; a new address (a vaulted `⟨ADDR_n⟩` ref)
        # does.
        return args.get("address_ref") != "on_file"

    return rule
