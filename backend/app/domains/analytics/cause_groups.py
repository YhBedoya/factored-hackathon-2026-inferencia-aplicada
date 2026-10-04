"""Handoff reason -> cause group (REQ-R3 "Cause group").

A constant in the analytics domain, not a policy file: the grouping describes
how the dashboard reads a handoff, it does not change what the bot does.
"""

from typing import Final, Literal

CauseGroup = Literal["by_design", "customer_choice", "bot_failure", "security"]

CAUSE_GROUPS: Final[dict[str, CauseGroup]] = {
    "suspected_fraud": "by_design",
    "priority_claim": "by_design",
    "legal_regulator": "by_design",
    "customer_not_active": "by_design",
    "bank_side_block": "by_design",
    "human_request": "customer_choice",
    "clarification_exhausted": "bot_failure",
    "tool_failure": "bot_failure",
    "llm_unavailable": "bot_failure",
    "action_unverified": "bot_failure",
    "agent_round_cap": "bot_failure",
    "unauthorized_access": "security",
    "step_up_failed": "security",
}


def cause_group(reason: str) -> CauseGroup | None:
    """The group for a handoff reason, or `None` for a reason nobody mapped."""
    return CAUSE_GROUPS.get(reason)
