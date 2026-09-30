"""Writes `eval/reports/<run_id>/` (D16): `report.md`, `metrics.json`, `meta.json`.

Pure over verdict dicts and a meta dict, so it needs no database. Every number is
labelled "offline evaluation" (`05` §7).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from eval.harness.metrics import LABEL, compute_all

__all__ = ["write_report"]

# Groups below this many cases get a caveat: a Wilson interval on 3 cases says little.
SMALL_N = 10


def _rate(r: dict[str, Any]) -> str:
    if not r["n"]:
        return "not defined (n=0)"
    lo, hi = r["ci"]
    return f"{r['value']:.1%} ({r['k']}/{r['n']}; 95% CI {lo:.1%}-{hi:.1%})"


def _num(value: float | None, unit: str = "") -> str:
    return "not defined" if value is None else f"{value:,.1f}{unit}"


def _usd(value: float | None) -> str:
    return "not defined" if value is None else f"${value:.4f}"


def _rows(metrics: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, str]]]:
    def per(fn: Any) -> dict[str, str]:
        return {s: fn(m["overall"]) for s, m in metrics.items()}

    return [
        ("Cases run", per(lambda o: str(o["cases"]))),
        (
            "Safe automated resolution",
            per(lambda o: _rate(o["safe_automated_resolution"])),
        ),
        ("Automation attempted", per(lambda o: _rate(o["automation_attempted"]))),
        ("Containment", per(lambda o: _rate(o["containment"]))),
        ("Escalation recall", per(lambda o: _rate(o["escalation"]["recall"]))),
        ("Escalation precision", per(lambda o: _rate(o["escalation"]["precision"]))),
        (
            "Escalation confusion (tp / missed / unnecessary / tn)",
            per(
                lambda o: (
                    "{correct} / {missed} / {unnecessary} / {correct_no_transfer}".format(
                        **o["escalation"]
                    )
                )
            ),
        ),
        ("Unsafe outcomes", per(lambda o: _rate(o["unsafe"]))),
        (
            "Unsafe upper bound (rule of three)",
            per(lambda o: _num(o["unsafe"]["upper_bound_rule_of_three"])),
        ),
        ("Clarification accuracy", per(lambda o: _rate(o["clarification_accuracy"]))),
        (
            "Turn latency p50 / p95 (ms)",
            per(
                lambda o: (
                    f"{_num(o['latency_ms']['turn']['p50'])} / "
                    f"{_num(o['latency_ms']['turn']['p95'])} (n={o['latency_ms']['turn']['n']})"
                )
            ),
        ),
        (
            "Conversation latency p50 / p95 (ms)",
            per(
                lambda o: (
                    f"{_num(o['latency_ms']['conversation']['p50'])} / "
                    f"{_num(o['latency_ms']['conversation']['p95'])} "
                    f"(n={o['latency_ms']['conversation']['n']})"
                )
            ),
        ),
        ("Cost per case", per(lambda o: _usd(o["cost_usd"]["per_case"]))),
        ("Cost per success", per(lambda o: _usd(o["cost_usd"]["per_success"]))),
    ]


def _table(
    header: str, systems: list[str], rows: list[tuple[str, dict[str, str]]]
) -> list[str]:
    lines = [
        f"| {header} | " + " | ".join(systems) + " |",
        "|---|" + "---|" * len(systems),
    ]
    lines += [
        f"| {name} | " + " | ".join(cells[s] for s in systems) + " |"
        for name, cells in rows
    ]
    return lines


def _breakdown(
    title: str, key: str, metrics: dict[str, dict[str, Any]], systems: list[str]
) -> list[str]:
    lines = [f"### {title}", ""]
    groups = sorted({g for m in metrics.values() for g in m[key]})
    rows = []
    for g in groups:
        cells = {}
        for s in systems:
            o = metrics[s][key].get(g)
            if o is None:
                cells[s] = "-"
                continue
            note = (
                f" **small n ({o['cases']} < {SMALL_N}), read with care**"
                if o["cases"] < SMALL_N
                else ""
            )
            cells[s] = f"{_rate(o['safe_automated_resolution'])}{note}"
        rows.append((g, cells))
    return lines + _table(f"{title} (safe automated resolution)", systems, rows) + [""]


def _failures(verdicts: dict[str, Sequence[dict[str, Any]]]) -> list[str]:
    lines = ["## Failures", ""]
    any_failure = False
    for system, vs in verdicts.items():
        # One example case id per failed check name; ids only, never transcript text.
        examples: dict[str, str] = {}
        counts: dict[str, int] = defaultdict(int)
        for v in vs:
            if v["verdict"] != "failed":
                continue
            for part in (v.get("reason") or "failed").split("; "):
                name = (
                    part.split(":")[0].split(" ")[0]
                    if not part.startswith("outcome")
                    else "outcome"
                )
                counts[name] += 1
                examples.setdefault(name, v["case_id"])
        if counts:
            any_failure = True
            lines.append(f"**{system}**")
            lines += [
                f"- `{n}`: {c} case(s), example `{examples[n]}`"
                for n, c in sorted(counts.items())
            ]
            lines.append("")
    return lines if any_failure else lines + ["No failed checks.", ""]


def _not_run(all_metrics: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["## Not run", "", "Kept out of every denominator.", ""]
    for system, m in all_metrics.items():
        items = m["not_run"]
        lines.append(f"**{system}**: {len(items)} case(s)")
        lines += [f"- `{i['case_id']}`: {i['reason']}" for i in items]
        lines.append("")
    return lines


def _has_null_temperature(out: Path) -> bool:
    """True when any exported ledger row has no temperature (NLU on Sonnet 5.5, ADR-031).

    Reads the `llm_calls.jsonl` the runner writes beside the report, so the writer's
    signature stays as it was; a run without that file carries no caveat.
    """
    path = out / "llm_calls.jsonl"
    if not path.exists():
        return False
    return any(
        "temperature" in row and row["temperature"] is None
        for row in map(json.loads, path.read_text().splitlines())
        if row
    )


def write_report(
    out: Path, verdicts: dict[str, list[dict[str, Any]]], meta: dict[str, Any]
) -> None:
    """`verdicts` maps system -> per-case verdict dicts (`checks.case_verdict`)."""
    out.mkdir(parents=True, exist_ok=True)
    systems = list(verdicts)
    all_metrics = {s: compute_all(vs) for s, vs in verdicts.items()}
    (out / "metrics.json").write_text(
        json.dumps(
            {"label": LABEL, "systems": all_metrics}, indent=2, ensure_ascii=False
        )
    )
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    clone_line = ", ".join(
        f"{s} {sec:.0f}s" for s, sec in meta["clone_seconds"].items()
    )
    lines = [
        f"# Eval report `{meta['run_id']}` ({LABEL})",
        "",
        f"All numbers are {LABEL}: a scripted suite against a database clone, not production traffic.",
        "",
        *(
            [
                (
                    "Caveat: the NLU step runs without a fixed temperature (model default), "
                    "so results can vary between runs (ADR-031)."
                ),
                "",
            ]
            if _has_null_temperature(out)
            else []
        ),
        *(
            [
                (
                    "Driver: simulator (`gpt-6-luna`, temperature 1.0) — "
                    "transcripts are not repeatable run to run"
                ),
                "",
            ]
            if meta.get("driver") == "simulator"
            else []
        ),
        f"- Suite `{meta['suite']}` (hash `{meta['suite_hash'][:12]}`), git `{meta['git_sha'][:10]}`"
        + (f", subset: {meta['cases_filter']}" if meta.get("cases_filter") else ""),
        f"- Provider {', '.join(meta['provider']) or 'none recorded'}",
        f"- Clone creation from the golden DB took {clone_line}",
        (
            f"- Restores {meta['restore_count']}, restore diffs {meta['restore_diffs']}, "
            f"PII scan hits {meta['pii_hits']}"
        ),
        "",
        f"## Metrics ({LABEL})",
        "",
        *_table("Metric", systems, _rows(all_metrics)),
        "",
        *_failures(verdicts),
        "## Breakdowns",
        "",
        *_breakdown("Language variant", "by_language_variant", all_metrics, systems),
        *_breakdown("Segment", "by_segment", all_metrics, systems),
        *_not_run(all_metrics),
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
