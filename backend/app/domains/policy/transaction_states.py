"""Pending/reversed explainer policy, loaded from
`policies/transaction_states.yaml` (spec `d7-b-transactions-traceability-judge.md`
B1 Contracts, A5, R8).

`tx_explain` is the only flow that reads this file: the cause, next step and
hold days for a Pending or Reversed row come only from here, never from an
invented LLM guess (R11). Loaded with the `disputes.py`/`decline_codes.py`
pattern: a frozen, `extra="forbid"` model whose required `provenance`/
`version` make a header-less file fail to load.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = [
    "PendingStatePolicy",
    "ReversedStatePolicy",
    "TransactionStatesPolicy",
    "load_transaction_states_policy",
]

# `backend/app/domains/policy/transaction_states.py` -> repo root is four
# parents up (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "transaction_states.yaml"


class PendingStatePolicy(BaseModel):
    """The `pending` block: hold window and the two next-step keys (A5).

    `overdue_next_step_key` is used instead of `next_step_key` once
    `occurred_at + hold_days` has already passed (D3's "past the usual
    window" branch); `next_step_key` is used while the hold is still open.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hold_days: int
    cause_key: str
    next_step_key: str
    overdue_next_step_key: str


class ReversedStatePolicy(BaseModel):
    """The `reversed` block: a Reversed row has no hold window, and the data
    has no twin row to describe (A5), so there is only a cause and one next
    step.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cause_key: str
    next_step_key: str


class TransactionStatesPolicy(BaseModel):
    """`policies/transaction_states.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no explainer
    policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    pending: PendingStatePolicy
    reversed: ReversedStatePolicy


def load_transaction_states_policy(path: Path | None = None) -> TransactionStatesPolicy:
    """Load and validate `policies/transaction_states.yaml` (R8).

    `path` defaults to `<repo root>/policies/transaction_states.yaml`; tests
    may pass another path to check the rejection rule without touching the
    real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return TransactionStatesPolicy.model_validate(raw)
