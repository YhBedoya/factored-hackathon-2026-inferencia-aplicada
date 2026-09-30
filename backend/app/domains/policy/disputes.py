"""ADR-027 dispute/fraud policy, loaded from `policies/disputes.yaml` (spec
D8, D9, D12, B2, R8).

Two decisions live here and nowhere else in Python: which picked candidates
count as a suspected compromise (`compromise.min_picked`,
`compromise.fraud_score_gt`), and which transaction statuses are offered as
candidates at all (`candidate_statuses`). `triggers_compromise` is the only
way a flow reads the two thresholds -- SC2 greps the codebase for their
names outside this model, so a flow must call the method, never compare the
raw fields itself. `amount_over_threshold` is the same pattern for the B2
priority-claim rule: a flow calls the method, never compares
`priority.amount_threshold` itself. Loaded with the `escalation.py` pattern:
a frozen, `extra="forbid"` model whose required `provenance`/`version` make
a header-less file fail to load.
"""

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.domains.localization.format import Queue

__all__ = [
    "CompromisePolicy",
    "DisputesHandoffPolicy",
    "DisputesPolicy",
    "PriorityPolicy",
    "load_disputes_policy",
]

# `backend/app/domains/policy/disputes.py` -> repo root is four parents up
# (policy, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "disputes.yaml"


class CompromisePolicy(BaseModel):
    """The `compromise` block: the suspected-compromise rule (D8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_picked: int
    fraud_score_gt: Decimal
    block_reason: str


class DisputesHandoffPolicy(BaseModel):
    """The `handoff` block: where a suspected compromise is sent (D9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue: Queue
    priority: Literal["normal", "high"]
    reason: str


class PriorityPolicy(BaseModel):
    """The `priority` block: the B2 priority-claim rule (spec B2).

    `amount_threshold` keys are ISO currency codes; a currency with no entry
    never triggers the amount flag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_threshold: dict[str, Decimal]
    open_statuses: list[str]
    handoff: DisputesHandoffPolicy


class DisputesPolicy(BaseModel):
    """`policies/disputes.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no dispute
    policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    candidate_statuses: list[str]
    compromise: CompromisePolicy
    possession_question: str
    questions: list[str]
    handoff: DisputesHandoffPolicy
    priority: PriorityPolicy

    def triggers_compromise(self, picked_count: int, max_fraud_score: Decimal | None) -> bool:
        """D8's compromise rule: the picked count alone, or any picked
        transaction's `fraud_score` above the threshold.

        `max_fraud_score` is the highest `fraud_score` among the picked
        transactions, or `None` when none of them carries one -- a missing
        score never triggers on its own.
        """
        if picked_count >= self.compromise.min_picked:
            return True
        if max_fraud_score is not None and max_fraud_score > self.compromise.fraud_score_gt:
            return True
        return False

    def amount_over_threshold(self, amount: Decimal, currency: str) -> bool:
        """B2's amount-priority rule: strictly greater than the currency's
        threshold. A currency with no threshold never triggers (`False`)."""
        threshold = self.priority.amount_threshold.get(currency)
        if threshold is None:
            return False
        return amount > threshold


def load_disputes_policy(path: Path | None = None) -> DisputesPolicy:
    """Load and validate `policies/disputes.yaml` (R8).

    `path` defaults to `<repo root>/policies/disputes.yaml`; tests may pass
    another path to check the rejection rule without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return DisputesPolicy.model_validate(raw)
