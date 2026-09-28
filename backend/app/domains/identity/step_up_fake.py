"""`FakeStepUpGate`: the `StepUpGate` contract with a fixed demo code, no OTP
service (ADR-008, D8).

Real OTP verification (`POST /auth/otp/verify`) is outside this Protocol
(D3-A4); this fake models only the effect the executor's step-up rule
checks. This module imports only the stdlib: it must never import
`app.domains.conversation` (`06` §2).
"""

__all__ = ["FakeStepUpGate"]


class FakeStepUpGate:
    """`StepUpGate` bound to one configured demo code, in-memory only.

    Once `verify` matches, the gate stays valid: this fake has no expiry
    window (the validity-window question is D8's deferred item, not this
    fake's job to answer). An empty configured code (no `DEMO_OTP_CODE` set)
    never matches, so an unconfigured demo box fails closed.
    """

    def __init__(self, code: str) -> None:
        self._code = code
        self._verified = False

    def verify(self, code: str) -> bool:
        """Check `code` against the configured one; return whether it matched."""
        matched = bool(self._code) and code == self._code
        if matched:
            self._verified = True
        return matched

    async def is_step_up_valid(self) -> bool:
        return self._verified
