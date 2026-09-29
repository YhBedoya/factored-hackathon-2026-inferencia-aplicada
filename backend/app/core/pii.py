"""PII detectors: regex plus checksum, stdlib only (R5, spec D3).

Shared by `core/llm` (the refuse-raw-PII guard and the Langfuse mask hook),
the safety vault and the log redactor, so it sits in core and imports no
domain. Known limit: third-party names typed freely and unlabelled
third-party document numbers are not detected (no NER).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

PiiKind = Literal["CARD", "DOC", "EMAIL", "PHONE", "NAME"]

TOKEN_RE = re.compile(r"⟨(?:CARD|DOC|EMAIL|PHONE|NAME|ADDR)_\d+⟩")

_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# +52 / +57 / +54 prefixed numbers, or a 10-digit national number (3-3-4 groups allowed).
_PHONE_INTL_RE = re.compile(r"(?<![\w+])\+(?:52|57|54)(?:[ .-]?\d){8,11}(?!\d)")
_PHONE_NATIONAL_RE = re.compile(r"(?<![\d+])\d{3}[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
# A keyword then a run that holds at least one digit (A1: "CPF para pagar" is not a document).
_DOC_RE = re.compile(
    r"(?<!\w)(?:dni|c[eé]dula|cc|ce|pasaporte|passaporte|cpf|rg)(?!\w)[\s:.#-]*"
    r"(?P<num>(?=[\w.-]*\d)[\w.-]*\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KnownPii:
    document_number: str | None
    names: tuple[str, ...]


@dataclass(frozen=True)
class PiiMatch:
    kind: PiiKind
    start: int
    end: int


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _fold(text: str) -> str:
    """Lowercase and strip accents, one output char per input char (offsets are kept)."""
    out: list[str] = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1] or ch
        out.append(base.lower() if len(base.lower()) == 1 else base)
    return "".join(out)


def _known_matches(text: str, known: KnownPii) -> list[PiiMatch]:
    folded = _fold(text)
    found: list[PiiMatch] = []
    targets: list[tuple[PiiKind, str]] = []
    if known.document_number:
        targets.append(("DOC", known.document_number))
    targets.extend(("NAME", n) for n in known.names)
    for kind, value in targets:
        needle = _fold(value.strip())
        if len(needle) < 2:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
        found.extend(PiiMatch(kind, m.start(), m.end()) for m in pattern.finditer(folded))
    return found


def find_pii(text: str, known: KnownPii | None = None) -> list[PiiMatch]:
    """Return non-overlapping PII matches sorted by position. Tokens never match."""
    # Earlier groups win an overlap. A +52/+57/+54 number can be Luhn-valid, so it beats CARD.
    candidates: list[PiiMatch] = []
    candidates.extend(PiiMatch("EMAIL", m.start(), m.end()) for m in _EMAIL_RE.finditer(text))
    candidates.extend(PiiMatch("PHONE", m.start(), m.end()) for m in _PHONE_INTL_RE.finditer(text))
    candidates.extend(
        PiiMatch("CARD", m.start(), m.end())
        for m in _CARD_RE.finditer(text)
        if _luhn_ok(re.sub(r"\D", "", m.group()))
    )
    candidates.extend(PiiMatch("DOC", m.start("num"), m.end("num")) for m in _DOC_RE.finditer(text))
    candidates.extend(
        PiiMatch("PHONE", m.start(), m.end()) for m in _PHONE_NATIONAL_RE.finditer(text)
    )
    if known is not None:
        candidates.extend(_known_matches(text, known))

    blocked = [(t.start(), t.end()) for t in TOKEN_RE.finditer(text)]
    candidates = [c for c in candidates if not any(c.start < e and s < c.end for s, e in blocked)]
    kept: list[PiiMatch] = []
    for c in candidates:  # already in priority order
        if not any(c.start < k.end and k.start < c.end for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda c: c.start)


def redact(text: str) -> str:
    """Replace every match with ⟨KIND⟩ (Langfuse mask hook, logs)."""
    out = text
    for m in reversed(find_pii(text)):
        out = f"{out[: m.start]}⟨{m.kind}⟩{out[m.end :]}"
    return out
