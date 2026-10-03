"""`make check` gate for the intent training data (spec D16, D19, criterion 5).

Exits non-zero with one reason per line when the data breaks the contract.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from ml.intent.data_io import LOCALES, DataFile, accepted_items, load_files
from ml.intent.leakage import eval_texts, find_leaks
from ml.intent.train import item_label

PROVENANCE = "ai-generated-human-audited"


def duplicate_findings(files: list[DataFile]) -> tuple[list[str], list[str]]:
    """(problems, warnings) for repeated accepted texts.

    Fails: a text twice in one file, or one text under two different labels.
    Warns: the same text under the same label in more than one file.
    """
    out: list[str] = []
    warns: list[str] = []
    labels_by_text: dict[str, set[str]] = {}
    files_by_text: dict[str, list[str]] = {}
    for f in files:
        name = f"{f.locale}/{f.class_}"
        accepted = [i for i in f.items if i.accepted is True]
        for text, n in Counter(i.text for i in accepted).items():
            if n > 1:
                out.append(f"{name}: duplicate training text {text!r} inside the file")
        for i in accepted:
            labels_by_text.setdefault(i.text, set()).add(item_label(i, f.class_))
        for text in {i.text for i in accepted}:
            files_by_text.setdefault(text, []).append(name)
    for text, labels in labels_by_text.items():
        if len(labels) > 1:
            out.append(f"training text {text!r} has different labels {sorted(labels)}")
        elif len(files_by_text[text]) > 1:
            warns.append(f"duplicate training text {text!r} in {', '.join(files_by_text[text])}")
    return out, warns


def cell_size_problems(files: list[DataFile], per_cell: int) -> list[str]:
    """A cell needs `per_cell - 1` or more accepted items (T36 one short, T41 card_type extras)."""
    minimum = per_cell - 1
    out: list[str] = []
    for f in files:
        count = sum(1 for i in f.items if i.accepted is True)
        if count < minimum:
            out.append(f"{f.locale}/{f.class_}: {count} accepted, expected {minimum} or more")
    return out


def problems(data_dir: Path, per_cell: int, warnings: list[str] | None = None) -> list[str]:
    from app.domains.conversation.intent_registry import classifier_labels

    labels = classifier_labels()
    files = load_files(data_dir)
    out: list[str] = []
    seen = {(f.locale, f.class_) for f in files}

    for f in files:
        if f.class_ not in labels:
            out.append(f"{f.locale}/{f.class_}: unknown class")
        if f.provenance != PROVENANCE:
            out.append(f"{f.locale}/{f.class_}: provenance {f.provenance!r} != {PROVENANCE!r}")
        pending = sum(1 for i in f.items if i.accepted is None)
        if pending:
            out.append(f"{f.locale}/{f.class_}: {pending} item(s) not audited (accepted: null)")
    for label in labels:
        for locale in LOCALES:
            if (locale, label) not in seen:
                out.append(f"{locale}/{label}: missing file")
    out.extend(cell_size_problems(files, per_cell))

    texts = [i.text for i in accepted_items(files)]
    for train, ev in find_leaks(texts, eval_texts()):
        out.append(f"leak: training text {train!r} equals eval text {ev!r}")
    dup_problems, dup_warnings = duplicate_findings(files)
    out.extend(dup_problems)
    if warnings is not None:
        warnings.extend(dup_warnings)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=Path("ml/intent/data"))
    ap.add_argument("--per-cell", type=int, default=30)
    args = ap.parse_args()
    warned: list[str] = []
    found = problems(args.data_dir, args.per_cell, warned)
    for line in warned:
        print(f"WARN {line}", file=sys.stderr)
    for line in found:
        print(f"FAIL {line}", file=sys.stderr)
    if found:
        print(f"{len(found)} problem(s)", file=sys.stderr)
        return 1
    print(f"intent data OK ({len(warned)} duplicate warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
