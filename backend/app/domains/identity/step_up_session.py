"""`SessionStepUpGate`: the `StepUpGate` contract backed by the session's own
`step_up_at`, checked against a validity window (D3-A4, D4).

`POST /auth/otp/verify` (`identity/service.py`) is what sets `step_up_at`;
this gate only reads it back. Matches `step_up.py`'s own constraint: stdlib
only, so it can never import `app.domains.conversation` and create a cycle
with the executor's eager import of this package (`06` §2).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

__all__ = ["SessionStepUpGate"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SessionStepUpGate:
    """`StepUpGate` bound to one session's `step_up_at` and a `window` (D4).

    Valid iff `step_up_at` is set and no older than `window`. `now` is
    injectable so a test doesn't need to wait out the window.
    """

    def __init__(
        self,
        step_up_at: datetime | None,
        window: timedelta,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._step_up_at = step_up_at
        self._window = window
        self._now = now

    async def is_step_up_valid(self) -> bool:
        if self._step_up_at is None:
            return False
        return self._now() - self._step_up_at <= self._window
