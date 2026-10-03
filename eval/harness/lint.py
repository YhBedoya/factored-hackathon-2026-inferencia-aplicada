"""Suite lint (D14): no two seeds in a suite share a writing persona.

A seed's own cases (the seed case and its paraphrases) may share the persona:
B's format puts `persona` at seed level, so they always do. What the lint
refuses is two *different* seeds, one of them writing, on the same customer,
because the restore after a writing case would otherwise race another seed.
"""

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

import yaml

from eval.scenarios.schema import Case

__all__ = ["SuiteLintError", "lint_suite", "load_write_tools", "writing_case"]

_TOOLS_YAML = Path(__file__).resolve().parents[2] / "policies" / "tools.yaml"


class SuiteLintError(Exception):
    """Two seeds share a writing persona. `seed_ids` lists every offender."""

    def __init__(self, seed_ids: list[str]) -> None:
        self.seed_ids = seed_ids
        super().__init__(f"seeds share a writing persona: {', '.join(seed_ids)}")


def load_write_tools(path: Path = _TOOLS_YAML) -> frozenset[str]:
    """Tools whose `requires_confirmation` is true (policy, R8: not a code constant)."""
    tools = yaml.safe_load(path.read_text(encoding="utf-8"))["tools"]
    return frozenset(
        name for name, spec in tools.items() if spec.get("requires_confirmation")
    )


def writing_case(case: Case, write_tools: Iterable[str]) -> bool:
    """A case is writing when it requires a write tool or asserts DB state."""
    return bool(set(case.labels.required_tools) & set(write_tools)) or bool(
        case.labels.expected_db_state
    )


def lint_suite(cases: Iterable[Case], write_tools: Iterable[str] | None = None) -> None:
    tools = load_write_tools() if write_tools is None else frozenset(write_tools)
    by_persona: dict[str, set[str]] = defaultdict(set)
    writers: set[str] = set()
    for case in cases:
        by_persona[case.persona].add(case.seed_id)
        if writing_case(case, tools):
            writers.add(case.persona)
    offenders = sorted(
        {
            sid
            for persona in writers
            if len(by_persona[persona]) > 1
            for sid in by_persona[persona]
        }
    )
    if offenders:
        raise SuiteLintError(offenders)
