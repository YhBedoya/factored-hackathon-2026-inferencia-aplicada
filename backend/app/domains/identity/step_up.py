"""The step-up gate a confirmed write checks before it consumes a plan step.

See `docs/solution-docs/04-contracts.md` §1, ADR-008, ADR-025 and D8. OTP
verification itself (`POST /auth/otp/verify`) is outside this Protocol
(D3-A4); this card ships the read-only check only. This module imports only
the stdlib: it must never import `app.domains.conversation`, or the
executor's eager import of this package would create a cycle (`06` §2).
"""

from typing import Protocol

__all__ = ["StepUpGate"]


class StepUpGate(Protocol):
    """Bound to the session at construction, so `is_step_up_valid` takes no
    `customer_id` (R1). The validity window (how recent `session.step_up_at`
    must be) is not part of the contract (D8's deferred item).
    """

    async def is_step_up_valid(self) -> bool: ...
