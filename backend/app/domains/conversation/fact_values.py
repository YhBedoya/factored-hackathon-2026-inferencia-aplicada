"""Per-turn collector for the values code writes into a reply (G6b grounding).

The grounding check needs every string that code (not the LLM) substituted
into the text the customer sees: masks, money, dates, queue labels. Call sites
`record` them; the turn wrapper opens `collecting()` around the graph run.
Outside `collecting()` (unit tests, scripts) `record` does nothing.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = ["collecting", "record"]

_VALUES: ContextVar[list[str] | None] = ContextVar("fact_values", default=None)


@contextmanager
def collecting() -> Iterator[list[str]]:
    """Yield the list that `record` appends to for the duration of the block."""
    values: list[str] = []
    token = _VALUES.set(values)
    try:
        yield values
    finally:
        _VALUES.reset(token)


def record(*values: str) -> None:
    """Note values code substituted into a reply; no-op outside `collecting()`."""
    collected = _VALUES.get()
    if collected is not None:
        collected.extend(values)
