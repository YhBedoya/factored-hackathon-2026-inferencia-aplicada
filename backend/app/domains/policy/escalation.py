"""ADR-021 handoff queues, loaded from `policies/escalation.yaml` (spec D8,
D10, plan P7, R8).

Three sections today: which statuses make a customer read-only and which
actions stay allowed (D10), the queue for each `get_block_origin` bank-side
reason (D8), and the queue for an `action_unverified` handoff (P7). D4-day
adds the rest. Loaded with the `card_select.py` pattern: a frozen,
`extra="forbid"` model whose required `provenance`/`version` make a
header-less file fail to load.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.domains.localization.format import Queue

__all__ = [
    "ActionQueuesPolicy",
    "BankSideQueuesPolicy",
    "CustomerNotActivePolicy",
    "EscalationPolicy",
    "load_escalation_policy",
]

# `backend/app/domains/policy/escalation.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "escalation.yaml"


class CustomerNotActivePolicy(BaseModel):
    """The `customer_not_active` block (D10, ADR-021)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statuses: list[str]
    allowed: list[str]
    queue: Queue


class BankSideQueuesPolicy(BaseModel):
    """The `bank_side_queues` block: the queue for each `get_block_origin`
    bank-side reason (D8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    past_due: Queue
    fraud: Queue
    bank_status: Queue
    customer_status: Queue


class ActionQueuesPolicy(BaseModel):
    """The `action_queues` block: the queue for a non-`get_block_origin`
    handoff reason (plan P7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_unverified: Queue


class EscalationPolicy(BaseModel):
    """`policies/escalation.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no escalation
    rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: str
    version: int
    customer_not_active: CustomerNotActivePolicy
    bank_side_queues: BankSideQueuesPolicy
    action_queues: ActionQueuesPolicy


def load_escalation_policy(path: Path | None = None) -> EscalationPolicy:
    """Load and validate `policies/escalation.yaml` (R8).

    `path` defaults to `<repo root>/policies/escalation.yaml`; tests may pass
    another path to check the rejection rule without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return EscalationPolicy.model_validate(raw)
