"""Leakage check between training texts and evaluation texts (spec D16, D19).

Read-only over `eval/`: nothing here writes, and a missing directory (the
held-out set is not frozen yet) counts as empty.
"""

import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

import yaml

from ml.intent.data_io import BACKEND_ROOT  # noqa: F401  (puts backend/ on sys.path)

__all__ = ["eval_texts", "find_leaks", "normalize"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCENARIO_DIRS = (
    _REPO_ROOT / "eval" / "scenarios" / "dev",
    _REPO_ROOT / "eval" / "scenarios" / "heldout",
    _REPO_ROOT / "eval" / "scenarios" / "_staging" / "heldout",
)
_NLU_DIR = _REPO_ROOT / "eval" / "nlu"
_NON_WORD = re.compile(r"[^\w]+")


def normalize(text: str) -> str:
    """Casefold, strip accents, turn punctuation into spaces and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD.sub(" ", bare.replace("_", " ")).strip()


def eval_texts() -> list[str]:
    """Every customer turn text in the dev, held-out and staged held-out scenarios
    plus the `eval/nlu/*.yaml` items."""
    from eval.scenarios.schema import load_dir

    texts: list[str] = []
    for directory in _SCENARIO_DIRS:
        for case in load_dir(directory):
            texts.extend(t.say for t in case.turns if t.say is not None)
    for path in sorted(_NLU_DIR.glob("*.yaml")):
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        texts.extend(e["text"] for e in entries if isinstance(e, dict) and "text" in e)
    return texts


def find_leaks(train_texts: Iterable[str], eval_texts: Iterable[str]) -> list[tuple[str, str]]:
    """(train text, eval text) pairs equal after `normalize`."""
    by_norm: dict[str, list[str]] = {}
    for text in eval_texts:
        key = normalize(text)
        if key:
            by_norm.setdefault(key, []).append(text)
    leaks: list[tuple[str, str]] = []
    for text in train_texts:
        for match in by_norm.get(normalize(text), []):
            leaks.append((text, match))
    return leaks
