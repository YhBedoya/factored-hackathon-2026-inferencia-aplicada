"""B4 judge tooling: compare the judge's verdicts with the human labels
(spec §"Contracts" -> "B4: eval", D17).

`agreement()` loads `items.jsonl`, `labels/assignment.yaml`,
`labels/<labeler>.yaml` (both labelers) and `judge_verdicts.jsonl`, then
writes `eval/judges/agreement.md` (T11). `cohen_kappa`, `percent_agreement`
and `render_report` are pure and take no I/O, so they're the seam the unit
test drives directly, with no LLM call and no file on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

__all__ = ["agreement", "cohen_kappa", "percent_agreement", "render_report"]

_JUDGES_DIR = Path(__file__).resolve().parent
_DIMENSIONS = ("grounding", "tone", "clarity", "register", "overall")
_WEAK_KAPPA = 0.6
_SHARED_N = 10


def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Cohen's kappa for two same-length boolean rating lists, or `None`
    when the expected chance agreement is 1 (both raters gave the same
    single value every time, so `1 - pe` is 0 and kappa is undefined)."""

    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("cohen_kappa needs two equal-length, non-empty lists")
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    p_a_true = sum(a) / n
    p_b_true = sum(b) / n
    expected = p_a_true * p_b_true + (1 - p_a_true) * (1 - p_b_true)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def percent_agreement(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("percent_agreement needs two equal-length, non-empty lists")
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / n


def _kappa_row(a: list[bool], b: list[bool]) -> tuple[float | None, float, int]:
    if not a:
        return None, 0.0, 0
    return cohen_kappa(a, b), percent_agreement(a, b), len(a)


def _table(rows: dict[str, tuple[float | None, float, int]]) -> list[str]:
    lines = ["| Dimension | n | % agreement | Cohen's kappa |", "|---|---|---|---|"]
    for dim in _DIMENSIONS:
        kappa, pct, n = rows[dim]
        kappa_str = "n/a" if kappa is None else f"{kappa:.2f}"
        lines.append(f"| {dim} | {n} | {pct * 100:.1f}% | {kappa_str} |")
    return lines


def render_report(
    items: list[dict[str, Any]],
    labels: dict[str, list[dict[str, Any]]],
    verdicts: list[dict[str, Any]],
    assignment: dict[str, Any],
) -> str:
    """D17: judge-vs-human on every labeled item (the first labeler's label
    on the 10 shared ones), human-vs-human on those same 10 shared items.
    `"**judge is weak**"` opens the report when overall judge-vs-human kappa
    is below 0.6; the label "offline evaluation" and the temperature-1.0
    non-repeatable caveat (D14) are always stated."""

    verdict_by_item = {row["item_id"]: row["verdict"] for row in verdicts}
    first, second = assignment["first"], assignment["second"]
    shared_ids = set(assignment.get("shared", []))
    first_records = {r["item_id"]: r for r in labels.get(first, [])}
    second_records = {r["item_id"]: r for r in labels.get(second, [])}

    # D17: the first labeler's label wins on the 10 shared items; each
    # labeler's own label stands on their own 20.
    human_label_by_item: dict[str, dict[str, Any]] = {}
    for item_id in shared_ids & set(first_records):
        human_label_by_item[item_id] = first_records[item_id]
    for item_id, record in first_records.items():
        human_label_by_item.setdefault(item_id, record)
    for item_id, record in second_records.items():
        human_label_by_item.setdefault(item_id, record)

    common_ids = sorted(set(human_label_by_item) & set(verdict_by_item))
    shared_common = sorted(shared_ids & set(first_records) & set(second_records))

    judge_human = {
        dim: _kappa_row(
            [bool(verdict_by_item[i][dim]) for i in common_ids],
            [bool(human_label_by_item[i][dim]) for i in common_ids],
        )
        for dim in _DIMENSIONS
    }
    human_human = {
        dim: _kappa_row(
            [bool(first_records[i][dim]) for i in shared_common],
            [bool(second_records[i][dim]) for i in shared_common],
        )
        for dim in _DIMENSIONS
    }

    overall_kappa, _overall_pct, overall_n = judge_human["overall"]

    lines: list[str] = []
    if overall_kappa is not None and overall_kappa < _WEAK_KAPPA:
        lines.append("**judge is weak**")
        lines.append("")
    lines.append("# Judge agreement report")
    lines.append("")
    lines.append(
        "Label: offline evaluation. The `judge` step runs at temperature 1.0 "
        "(D14, the only value `gpt-6-luna` accepts), so re-running `judge` "
        "will not reproduce these exact verdicts -- read this report as one "
        "sample, not a fixed baseline."
    )
    lines.append("")
    lines.append(f"n = {overall_n} labeled items, {len(items)} sampled.")
    lines.append("")
    lines.append("## Judge vs human")
    lines.append("")
    lines.extend(_table(judge_human))
    lines.append("")
    lines.append(f"## Human vs human ({_SHARED_N} shared items)")
    lines.append("")
    lines.append(
        f"n = {len(shared_common)}. Small-sample caveat: {_SHARED_N} items is too "
        "few to estimate agreement precisely -- read this as a sanity check on "
        "the rubric's clarity, not a stable rate."
    )
    lines.append("")
    lines.extend(_table(human_human))
    lines.append("")
    return "\n".join(lines)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def agreement() -> None:
    """Load the items, the assignment, both labelers' files and the judge's
    verdicts, and write `eval/judges/agreement.md`."""

    labels_dir = _JUDGES_DIR / "labels"
    items = _read_jsonl(_JUDGES_DIR / "items.jsonl")
    verdicts = _read_jsonl(_JUDGES_DIR / "judge_verdicts.jsonl")
    assignment = yaml.safe_load((labels_dir / "assignment.yaml").read_text(encoding="utf-8"))
    labels = {
        labeler: yaml.safe_load((labels_dir / f"{labeler}.yaml").read_text(encoding="utf-8"))
        for labeler in (assignment["first"], assignment["second"])
    }
    report = render_report(items, labels, verdicts, assignment)
    (_JUDGES_DIR / "agreement.md").write_text(report, encoding="utf-8")
