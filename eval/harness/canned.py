"""A driver that replays prepared transcripts, for tests only."""

from typing import Any

from eval.driver.driver import Transcript
from eval.scenarios.schema import Case

__all__ = ["CannedDriver"]


class CannedDriver:
    def __init__(self, transcripts: dict[str, Transcript]) -> None:
        self._transcripts = transcripts

    async def run_case(self, case: Case, **_: Any) -> Transcript:
        return self._transcripts[case.case_id]
