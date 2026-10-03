"""Keyword/regex NLU for the baseline system (ADR-005, spec D17).

Deterministic and LLM-free: the only I/O is loading `lexicon.yaml` once.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots, Topic

__all__ = ["keyword_nlu", "lexicon_hits", "qualified_block_kind", "split_clauses"]

_LEXICON_PATH = Path(__file__).with_name("lexicon.yaml")
_CLAUSE_SPLIT = re.compile(r"\s+(?:y|e|tambien|ademas|alem disso)\s+|[,;?]")
_Lang = Literal["es", "pt"]
_LANGS: tuple[_Lang, ...] = ("es", "pt")


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped if unicodedata.category(c) != "Mn")


def _compile(terms: dict[str, list[str]]) -> dict[_Lang, re.Pattern[str]]:
    return {lang: re.compile(r"\b(?:" + "|".join(terms.get(lang, [])) + r")\b") for lang in _LANGS}


@lru_cache(maxsize=1)
def _lexicon() -> dict[str, Any]:
    raw = yaml.safe_load(_LEXICON_PATH.read_text(encoding="utf-8"))
    return {
        "negators": set(raw["negators"]),
        "window": int(raw["negation_window"]),
        "exempt": set(raw["negation_exempt"]),
        "intents": {name: _compile(t) for name, t in raw["intents"].items()},
        "qualifiers": {name: _compile(t) for name, t in raw["block_qualifiers"].items()},
        "market": _compile(raw["out_of_market"]),
        "scope": {name: _compile(t) for name, t in raw["out_of_scope"].items()},
        "markers": _compile(raw["language_markers"]),
    }


def _negated(clause: str, start: int, lex: dict[str, Any]) -> bool:
    """True when a negator sits within the window of tokens before `start`."""
    before = re.findall(r"\w+", clause[:start])[-lex["window"] :]
    return any(tok in lex["negators"] for tok in before)


def _hits(patterns: dict[_Lang, re.Pattern[str]], text: str) -> list[tuple[_Lang, re.Match[str]]]:
    """Every match with its language. A term both lists match (saldo, Pix) is
    shared, so it carries no language signal and is reported as such below."""
    return [(lang, m) for lang, p in patterns.items() for m in p.finditer(text)]


def _exclusive(patterns: dict[_Lang, re.Pattern[str]], lang: _Lang, m: re.Match[str]) -> bool:
    other = patterns["pt" if lang == "es" else "es"]
    return other.fullmatch(m.group()) is None


def split_clauses(text: str) -> list[str]:
    """Normalized clauses, split the way `keyword_nlu` reads them."""
    return _CLAUSE_SPLIT.split(_normalize(text))


def qualified_block_kind(text: str) -> Literal["temporary_lock", "permanent_block"] | None:
    """The block qualifier ("temporal", "definitivo") found in `text`, if any."""
    norm = _normalize(text)
    kinds = [k for k, p in _lexicon()["qualifiers"].items() if _hits(p, norm)]
    return cast("Any", kinds[0]) if kinds else None


def lexicon_hits(clause: str, lexicon_key: str) -> list[bool]:
    """One entry per lexicon hit of `lexicon_key` in a normalized `clause`.

    True means the hit sits inside the negation window; negation-exempt keys
    are never negated, as in `keyword_nlu`.
    """
    lex = _lexicon()
    patterns = lex["intents"].get(lexicon_key)
    if patterns is None:
        return []
    exempt = lexicon_key in lex["exempt"]
    return [not exempt and _negated(clause, m.start(), lex) for _, m in _hits(patterns, clause)]


def keyword_nlu(text: str, language_hint: str | None = None) -> NLUResult:
    lex = _lexicon()
    norm = _normalize(text)
    langs: set[_Lang] = set()
    intents: list[str] = []
    negated_hit = False

    for clause in split_clauses(text):
        found: list[tuple[int, str]] = []
        for name, patterns in lex["intents"].items():
            for lang, m in _hits(patterns, clause):
                if _exclusive(patterns, lang, m):
                    langs.add(lang)
                if name in lex["exempt"] or not _negated(clause, m.start(), lex):
                    found.append((m.start(), name))
                else:
                    negated_hit = True
        # "desbloquear" also matches the bare block pattern's prefix only via \w*;
        # an unlock hit in the same clause supersedes the block hit.
        names = {n for _, n in found}
        for _, name in sorted(found):
            if name == "card_block" and "card_unlock" in names:
                continue
            if name not in intents:
                intents.append(name)

    # Precedence: an unrecognized charge outranks a block request (ADR-005).
    if "unrecognized_charge" in intents:
        intents = ["unrecognized_charge"]

    market = _hits(lex["market"], norm)
    scope = [(t, lang) for t, p in lex["scope"].items() for lang, _ in _hits(p, norm)]
    langs.update(lang for lang, m in market if _exclusive(lex["market"], lang, m))
    for p in lex["scope"].values():
        langs.update(lang for lang, m in _hits(p, norm) if _exclusive(p, lang, m))
    if not langs:
        langs.update(lang for lang, _ in _hits(lex["markers"], norm))

    language: Literal["es", "pt", "mixed"]
    if len(langs) == 2:
        language = "mixed"
    elif langs:
        language = next(iter(langs))
    else:
        language = "pt" if language_hint == "pt" else "es"

    typed = cast("list[Intent]", intents)
    if market:
        return NLUResult(
            language=language,
            intents=[],
            status="out_of_market",
            slots=NLUSlots(topic="pix_boleto"),
        )
    if not intents:
        if not scope and negated_hit:
            # Every intent keyword was negated (D47): an empty intent list, not a question.
            return NLUResult(
                language=language,
                intents=[],
                status="out_of_scope",
                slots=NLUSlots(topic="other"),
            )
        if not scope:
            # No lexicon hit at all: the plain-question fallback.
            return NLUResult(language=language, intents=["general_question"], status="clear")
        return NLUResult(
            language=language,
            intents=[],
            status="out_of_scope",
            slots=NLUSlots(topic=cast("Topic", scope[0][0])),
        )

    if "card_block" in intents:
        kind = qualified_block_kind(text)
        if kind:
            return NLUResult(
                language=language,
                intents=typed,
                status="clear",
                slots=NLUSlots(block_kind=kind),
            )
        return NLUResult(
            language=language,
            intents=typed,
            status="ambiguous",
            clarification="lock_vs_block",
        )
    return NLUResult(language=language, intents=typed, status="clear")
