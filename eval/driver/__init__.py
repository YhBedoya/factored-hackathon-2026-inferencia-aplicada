"""Scripted HTTP driver package (B2, D5-B): `run_case` replays one `Case`
against a running conversation API and returns a `Transcript`. Re-exported
here so callers do `from eval.driver import run_case, Transcript,
TurnRecord` without reaching into `driver.py` directly.

The rest of the public surface (`RunnerState`, `open_session`, `play_turn`,
`ended_by_from_events`, `is_not_runnable`) exists so a second driver -- the
simulator (B3) -- can reuse the D8/D9 session-expiry replay and per-turn
HTTP helpers by import, not by copy.
"""

from eval.driver.driver import (
    EventRecord,
    RunnerState,
    Transcript,
    TurnInput,
    TurnRecord,
    ended_by_from_events,
    is_not_runnable,
    open_session,
    play_turn,
    run_case,
)

__all__ = [
    "EventRecord",
    "RunnerState",
    "Transcript",
    "TurnInput",
    "TurnRecord",
    "ended_by_from_events",
    "is_not_runnable",
    "open_session",
    "play_turn",
    "run_case",
]
