"""The masked conversation context the NLU and `compose` read (naturalidad-cardy D3, D7).

Pure: no I/O. `build_context` slices the checkpointed history to the window;
`redact_values` strips every figure so history never becomes a source of
amounts, dates or masks (R4: those come from this turn's facts only).
"""

import re
from dataclasses import dataclass

from app.domains.conversation.state import HistoryMessage

__all__ = ["WINDOW", "ConversationContext", "HistoryMessage", "build_context", "redact_values"]

WINDOW = 6
_MARKER = "⟨valor⟩"

# Order matters: the wider shapes first, so a mask or a dated figure becomes one
# marker rather than several. The last pattern is the catch-all.
_CARD_MASK_RE = re.compile(r"[•·*xX]{2,}\s*\d{2,4}")
_DATE_RE = re.compile(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b")
_MONEY_RE = re.compile(r"(?:[A-Za-z]{2,3}\s*)?(?:R\$|[$€])\s*\d[\d.,]*|\d[\d.,]*\d")
_DIGITS_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class ConversationContext:
    messages: list[HistoryMessage]
    summary: str | None


def build_context(history: list[HistoryMessage], summary: str | None) -> ConversationContext:
    """The last `WINDOW` messages plus the summary of the older ones."""
    return ConversationContext(messages=list(history[-WINDOW:]), summary=summary)


def redact_values(text: str) -> str:
    """Replace every card mask, date, money figure and digit run with one marker.

    The output has no digit, so a figure in an old message can never be echoed
    as if it were a current fact.
    """
    out = _CARD_MASK_RE.sub(_MARKER, text)
    out = _DATE_RE.sub(_MARKER, out)
    out = _MONEY_RE.sub(_MARKER, out)
    return _DIGITS_RE.sub(_MARKER, out)
