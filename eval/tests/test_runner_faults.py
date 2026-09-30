import asyncio

from eval.harness.runner import _play_groups, fault_groups
from eval.scenarios.schema import Case


class _Setup:
    def __init__(self, faults: list[str]) -> None:
        self.faults = faults


class _Case:
    def __init__(self, name: str, faults: list[str]) -> None:
        self.case_id = name
        self.setup = _Setup(faults)


def test_one_backend_per_fault_set() -> None:
    cases: list[Case] = [
        _Case("a", []),  # type: ignore[list-item]
        _Case("b", ["bedrock_timeout"]),  # type: ignore[list-item]
        _Case("c", ["bedrock_timeout"]),  # type: ignore[list-item]
        _Case("d", ["cards_write_error"]),  # type: ignore[list-item]
    ]
    starts: list[str] = []
    stops: list[str] = []
    played: list[tuple[str, str]] = []

    def start(faults: frozenset[str]) -> str:
        env = ",".join(sorted(faults))
        starts.append(env)
        return env

    async def play(handle: str, faults: frozenset[str], group: list[Case]) -> None:
        played.extend((handle, c.case_id) for c in group)

    asyncio.run(_play_groups(fault_groups(cases), start, stops.append, play))

    assert starts == ["", "bedrock_timeout", "cards_write_error"]
    assert stops == starts
    assert played == [
        ("", "a"),
        ("bedrock_timeout", "b"),
        ("bedrock_timeout", "c"),
        ("cards_write_error", "d"),
    ]
