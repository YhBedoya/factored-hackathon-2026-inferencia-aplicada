"""Tool errors, read-side and write-side.

See `docs/solution-docs/04-contracts.md` §1 for the error contract.
"""

from typing import ClassVar, Literal

__all__ = [
    "AccessDenied",
    "ConfirmationRequired",
    "Conflict",
    "NotFound",
    "PolicyDenied",
    "StepUpRequired",
    "ToolError",
    "ToolUnavailable",
]


class ToolError(Exception):
    """Base class for exceptions raised by tools. See `04` §1."""


class NotFound(ToolError):
    """The id doesn't exist. See `04` §1."""

    code: ClassVar[str] = "not_found"


class AccessDenied(ToolError):
    """The id exists but belongs to another customer. See `04` §1."""

    code: ClassVar[str] = "access_denied"


class ToolUnavailable(ToolError):
    """Backend or data-source failure; the R11 retry wrapper keys off this class. See `04` §1."""

    code: ClassVar[str] = "tool_unavailable"


class PolicyDenied(ToolError):
    """The policy forbids it (allowlist D3-A1, ADR-021 inactive customer). See `04` §1, D14."""

    code: ClassVar[str] = "policy_denied"

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class ConfirmationRequired(ToolError):
    """`consume_step` rejects the call. See `04` §1, §7, D14.

    `reason` is `"unknown_or_expired"` (absent key: never issued, expired or
    already fully used), `"step_mismatch"` (the tool or args hash differs
    from the step at the cursor) or `"wrong_owner"` (another customer or
    conversation).
    """

    code: ClassVar[str] = "confirmation_required"

    def __init__(
        self, reason: Literal["unknown_or_expired", "step_mismatch", "wrong_owner"]
    ) -> None:
        super().__init__(reason)
        self.reason = reason


class StepUpRequired(ToolError):
    """The executor's rule says step-up and the gate says no. See `04` §1, D14."""

    code: ClassVar[str] = "step_up_required"


class Conflict(ToolError):
    """The state already matches (already locked, blocked or closed). See `04` §1, D14."""

    code: ClassVar[str] = "conflict"
