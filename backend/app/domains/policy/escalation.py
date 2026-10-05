"""ADR-021 handoff queues and escalation rules, loaded from
`policies/escalation.yaml` v9 (spec D2-D7, B2, D8-H D7, S2 D29, R8).

`rules.<reason>` is the single source of each handoff reason's queue and
priority (`queue: null` means the caller picks it: bank-side origin, human
request). Legal/regulator words are a keyword list matched in code. Loaded
with the `card_select.py` pattern: a frozen, `extra="forbid"` model whose
required `provenance`/`version` make a header-less file fail to load.
"""

import re
import unicodedata
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from app.domains.localization.format import Queue

__all__ = [
    "BankSideQueuesPolicy",
    "CustomerNotActivePolicy",
    "EscalationPolicy",
    "HandoffPacketPolicy",
    "HumanRequestQueuesPolicy",
    "LegalKeywordsPolicy",
    "Resolution",
    "RulePolicy",
    "UnauthorizedAccessPolicy",
    "legal_hit",
    "load_escalation_policy",
    "resolve_escalation",
    "rule",
    "rule_queue",
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


class BankSideQueuesPolicy(BaseModel):
    """The `bank_side_queues` block: the queue for each `get_block_origin`
    bank-side reason (D8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    past_due: Queue
    fraud: Queue
    bank_status: Queue
    customer_status: Queue


class RulePolicy(BaseModel):
    """One `rules.<reason>` entry: `queue` is `None` when the caller picks it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue: Queue | None
    priority: Literal["high", "normal"]
    open_questions: list[str] = []


class HumanRequestQueuesPolicy(BaseModel):
    """`human_request_queues`: queue by paused flow, else the default (D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default: Queue
    by_flow: dict[str, Queue]


class HandoffPacketPolicy(BaseModel):
    """`handoff_packet`: how far back the packet's customer history reads (D7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    history_days: int


class UnauthorizedAccessPolicy(BaseModel):
    """`unauthorized_access`: attempts before the handoff (D6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempts_before_handoff: int


class LegalKeywordsPolicy(BaseModel):
    """`legal_keywords`: words that mean a legal/regulator escalation (D3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    es: list[str]
    pt: list[str]


_REQUIRED_REASONS = (
    "human_request",
    "clarification_exhausted",
    "legal_regulator",
    "customer_not_active",
    "bank_side_block",
    "action_unverified",
    "unauthorized_access",
    "suspected_fraud",
    "tool_failure",
    "llm_unavailable",
    "priority_claim",
    "agent_round_cap",
    "step_up_failed",
    "card_open_request",
    "card_close_request",
)

# Reasons whose null-queue rule resolves by the paused flow, like `human_request`.
_FLOW_ROUTED_REASONS = ("tool_failure", "llm_unavailable")


class EscalationPolicy(BaseModel):
    """`policies/escalation.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no escalation
    rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    customer_not_active: CustomerNotActivePolicy
    bank_side_queues: BankSideQueuesPolicy
    rules: dict[str, RulePolicy]
    human_request_queues: HumanRequestQueuesPolicy
    unauthorized_access: UnauthorizedAccessPolicy
    legal_keywords: LegalKeywordsPolicy
    handoff_packet: HandoffPacketPolicy
    # Intent names (plain str: `policy` must not import the conversation `Intent`
    # literal, `06` §2). Defaults empty so other YAMLs still load (ADR-032).
    degraded_handoff_intents: list[str] = []

    @model_validator(mode="after")
    def _all_reasons_have_a_rule(self) -> "EscalationPolicy":
        missing = [r for r in _REQUIRED_REASONS if r not in self.rules]
        if missing:
            raise ValueError(f"escalation.yaml rules missing: {missing}")
        return self


def load_escalation_policy(path: Path | None = None) -> EscalationPolicy:
    """Load and validate `policies/escalation.yaml` (R8).

    `path` defaults to `<repo root>/policies/escalation.yaml`; tests may pass
    another path to check the rejection rule without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return EscalationPolicy.model_validate(raw)


class Resolution(BaseModel):
    """The outcome of `resolve_escalation`: what to hand off and where."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str
    queue: Queue
    priority: Literal["high", "normal"]
    # How the queue was chosen (D5): rule queue | queue set by the flow |
    # human_request_queues.by_flow | .default. `flow` is set only for by_flow.
    branch: Literal["rule", "flow", "by_flow", "default"]
    flow: str | None


def _fold(text: str) -> str:
    """Lowercase and strip accents so `denúncia` matches `DENUNCIA`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def legal_hit(text: str, policy: EscalationPolicy) -> bool:
    """Whole-word or phrase match of either language's legal keywords (D3)."""
    haystack = _fold(text)
    for word in (*policy.legal_keywords.es, *policy.legal_keywords.pt):
        if re.search(rf"\b{re.escape(_fold(word))}\b", haystack):
            return True
    return False


def rule(policy: EscalationPolicy, reason: str) -> RulePolicy:
    """The `rules` entry for `reason`."""
    return policy.rules[reason]


def rule_queue(policy: EscalationPolicy, reason: str) -> Queue:
    """The fixed queue of a rule; a rule whose caller picks the queue is a bug here."""
    queue = policy.rules[reason].queue
    if queue is None:
        raise ValueError(f"escalation rule {reason!r} has no fixed queue")
    return queue


def _route_by_flow(
    hrq: HumanRequestQueuesPolicy, pending_flow: str | None
) -> tuple[Queue, Literal["by_flow", "default"], str | None]:
    """The paused flow's queue when `by_flow` has one, else the default."""
    if pending_flow and pending_flow in hrq.by_flow:
        return hrq.by_flow[pending_flow], "by_flow", pending_flow
    return hrq.default, "default", None


def resolve_escalation(
    policy: EscalationPolicy,
    *,
    reason: str | None,
    queue: str | None,
    pending_flow: str | None,
    intents: list[str],
    text: str,
) -> Resolution | None:
    """Decide whether this turn escalates, and to which queue (spec D4, D5).

    A `reason` already in state wins (queue from state, else the rule's),
    then a legal keyword, then a `human_request` intent; otherwise `None`.
    """
    branch: Literal["rule", "flow", "by_flow", "default"]
    flow: str | None = None
    hrq = policy.human_request_queues
    if reason is not None:
        resolved_reason = reason
        resolved_queue: str | None
        if queue is not None:
            resolved_queue, branch = queue, "flow"
        else:
            resolved_queue, branch = policy.rules[reason].queue, "rule"
        if resolved_queue is None and reason in _FLOW_ROUTED_REASONS:
            # Failure handoffs have no fixed queue: route like a human request.
            resolved_queue, branch, flow = _route_by_flow(hrq, pending_flow)
    elif legal_hit(text, policy):
        resolved_reason = "legal_regulator"
        resolved_queue = policy.rules[resolved_reason].queue
        branch = "rule"
    elif "human_request" in intents:
        resolved_reason = "human_request"
        resolved_queue, branch, flow = _route_by_flow(hrq, pending_flow)
    else:
        return None
    if resolved_queue is None:
        raise ValueError(f"escalation {resolved_reason!r} resolved without a queue")
    return Resolution(
        reason=resolved_reason,
        queue=resolved_queue,
        priority=policy.rules[resolved_reason].priority,
        branch=branch,
        flow=flow,
    )
