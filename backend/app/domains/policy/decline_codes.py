"""Decline-code policy, loaded from `policies/decline_codes.yaml` (spec
`d5-b-decline-explainer-test-sets.md` D4, R8).

`lookup_decline_code` is the only way a bank tool or a flow reads what a
`response_code` means: it loads and validates the file fresh on every call,
the same as `load_disputes_policy`/`load_escalation_policy` (no caching --
these files are small and read rarely enough per turn that staleness isn't
worth the complexity). Loaded with the `disputes.py` pattern: a frozen,
`extra="forbid"` model whose required `provenance`/`version` make a
header-less file fail to load.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.core.errors import DeclineCodeUnknown

__all__ = [
    "DeclineCode",
    "DeclineCodesPolicy",
    "load_decline_codes_policy",
    "lookup_decline_code",
]

# `backend/app/domains/policy/decline_codes.py` -> repo root is four parents
# up (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "decline_codes.yaml"


class DeclineCode(BaseModel):
    """One `codes.<response_code>` entry (D4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cause_key: str
    next_step_key: str
    self_service: bool


class DeclineCodesPolicy(BaseModel):
    """`policies/decline_codes.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no decline-code
    policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    codes: dict[str, DeclineCode]


def load_decline_codes_policy(path: Path | None = None) -> DeclineCodesPolicy:
    """Load and validate `policies/decline_codes.yaml` (R8).

    `path` defaults to `<repo root>/policies/decline_codes.yaml`; tests may
    pass another path to check the rejection rule without touching the real
    file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return DeclineCodesPolicy.model_validate(raw)


def lookup_decline_code(code: str | None) -> DeclineCode:
    """Map a `TxView.response_code` to its `cause_key`/`next_step_key`/
    `self_service` entry (D4).

    Raises `DeclineCodeUnknown` for `None` or `""` (both mean "no response
    code on this transaction") and for a code with no policy entry: the
    flow answers with the fixed `decline_unknown` template either way,
    never an invented meaning (R11). The LLM never picks the code's
    meaning -- this is the one place that does.
    """
    if not code:
        raise DeclineCodeUnknown("no response code on this transaction")
    entry = load_decline_codes_policy().codes.get(code)
    if entry is None:
        raise DeclineCodeUnknown(f"no policy entry for decline code {code!r}")
    return entry
