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
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Preconditions",
    "ToolPolicy",
    "ToolsPolicy",
    "has_preconditions",
    "load_tools_policy",
    "step_up_rule",
    "tool_allowed",
]

# `backend/app/domains/policy/tools_policy.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "tools.yaml"

StepUp = Literal["never", "always", "when_address_changed"]


class Preconditions(BaseModel):
    """The card-state rules a write must pass before it is proposed (D9, S2 D5).

    - `status_not_in`: a status in the list rejects with `already_in_state`.
    - `locked: false`: also rejects an already-locked card with `already_locked`.
    - `block_origin_in`: the card's block origin must be in the list, else
      `not_locked` (origin `none`) or `permanent_block` (`customer_block`);
      a bank-side origin is a handoff, not a reason code.
    - `replacement_eligible: true`: the block origin must be one that
      `card_select.yaml` lists as replacement-eligible, or the card expired,
      else `not_eligible`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_not_in: list[str] = Field(default_factory=list)
    locked: bool | None = None
    block_origin_in: list[str] | None = None
    replacement_eligible: bool | None = None


class ToolPolicy(BaseModel):
    """One entry of the `tools` map: a single write tool's confirmation and
    step-up flags."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requires_confirmation: bool
    step_up: StepUp
    allowed_intents: list[str]
    preconditions: Preconditions | None = None


class ToolsPolicy(BaseModel):
    """`policies/tools.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no step-up rule.
    `step_up_max_failures` has no default either: a file without it fails to
    load rather than running with an unlimited OTP retry count.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    step_up_window_minutes: int = Field(ge=1)
    step_up_max_failures: int = Field(ge=1)
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
) -> Callable[[str, Mapping[str, str | int | bool | list[str] | None]], bool]:
    """Build the executor's `StepUpRule` from a loaded `ToolsPolicy` (D2).

    The return type matches `conversation/tools/executor.py`'s `StepUpRule`
    structurally: mypy checks a `Callable`'s shape by signature, not by
    import, so this module never imports `app.domains.conversation` (`06`
    §2). The `list[str]` arm (D4-B D17, matching `policy.confirmation.ToolArg`)
    is inlined rather than imported for the same reason: it widens the
    signature `create_claim`'s `tx_ids`/`answers` args need without pulling
    in anything beyond this module's existing `Mapping` import. An unknown
    `tool` raises `KeyError`, the same way a missing `floors[currency]` does
    in `policy/min_payment.py`: a policy gap fails loudly instead of
    defaulting to "no step-up".
    """

    def rule(tool: str, args: Mapping[str, str | int | bool | list[str] | None]) -> bool:
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


def tool_allowed(policy: ToolsPolicy) -> Callable[[str, str], bool]:
    """Build the executor's `IntentAllowlist` from a loaded `ToolsPolicy` (D3).

    Called as `(intent, tool)`, matching `ConfirmedWriteTools.issue_plan` and
    `get_block_origin`. An unknown tool or an intent not in that tool's
    `allowed_intents` both return `False` rather than raising: unlike
    `step_up_rule`, an allowlist gap is a normal "not allowed" outcome, not a
    policy-authoring bug worth failing loudly over.
    """

    def allowed(intent: str, tool: str) -> bool:
        entry = policy.tools.get(tool)
        if entry is None:
            return False
        return intent in entry.allowed_intents

    return allowed


def has_preconditions(policy: ToolsPolicy) -> Callable[[str], bool]:
    """Build the executor's `HasPreconditions` from a loaded `ToolsPolicy` (D10).

    `issue_plan(intent=None)` (the agent path) passes only for a tool that
    carries a `preconditions` block; an unknown tool returns `False`.
    """

    def has(tool: str) -> bool:
        entry = policy.tools.get(tool)
        return entry is not None and entry.preconditions is not None

    return has
