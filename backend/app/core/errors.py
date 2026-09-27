"""Read-side tool errors.

See `docs/solution-docs/04-contracts.md` §1 for the error contract. K3 ships
the read-side subset (`NotFound`, `AccessDenied`, `ToolUnavailable`); D2 adds
`PolicyDenied`, `ConfirmationRequired`, `StepUpRequired` and `Conflict`.
"""

from typing import ClassVar

__all__ = ["AccessDenied", "NotFound", "ToolError", "ToolUnavailable"]


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
