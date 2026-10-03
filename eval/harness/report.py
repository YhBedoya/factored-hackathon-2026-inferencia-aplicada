"""Writes `eval/reports/<run_id>/` (D16): `report.md`, `metrics.json`, `meta.json`.

Pure over verdict dicts and a meta dict, so it needs no database. Every table header
carries its label: "offline evaluation" or "simulation" by driver (`05` §7, D7).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval.harness.metrics import aggregate, compute_all, label_for

__all__ = ["write_report"]

# Groups below this many cases get a caveat: a Wilson interval on 3 cases says little.
SMALL_N = 10

# Fixed by the human (plan Q2): D7-B4 writes its agreement report here, next to `rubric.md`.
JUDGE_AGREEMENT = Path(__file__).resolve().parents[1] / "judges" / "agreement.md"


def _rate(r: dict[str, Any]) -> str:
    if not r["n"]:
        return "not defined (n=0)"
    lo, hi = r["ci"]
    return f"{r['value']:.1%} ({r['k']}/{r['n']}; 95% CI {lo:.1%}-{hi:.1%})"


def _num(value: float | None, unit: str = "") -> str:
    return "not defined" if value is None else f"{value:,.1f}{unit}"


def _usd(value: float | None) -> str:
    return "not defined" if value is None else f"${value:.4f}"


def _pct(v: float | None) -> str:
    return "not defined" if v is None else f"{v:.1%}"


def _spread_cell(spread: dict[str, Any], fmt: Any) -> str:
    if spread["mean"] is None:
        return "not defined"
    return f"{fmt(spread['mean'])} ({fmt(spread['min'])}-{fmt(spread['max'])})"


def _fmt_num(v: float | None) -> str:
    return _num(v)


# (row name, per-run cell, aggregate key, aggregate formatter). No key = no mean column.
def _rows() -> list[tuple[str, Any, str | None, Any]]:
    def rate(key: str) -> Any:
        return lambda o: _rate(o[key])

    return [
        ("Cases run", lambda o: str(o["cases"]), "cases", lambda v: f"{v:g}"),
        (
            "Safe automated resolution",
            rate("safe_automated_resolution"),
            "safe_automated_resolution",
            _pct,
        ),
        (
            "Automation attempted",
            rate("automation_attempted"),
            "automation_attempted",
            _pct,
        ),
        ("Containment", rate("containment"), "containment", _pct),
        (
            "Escalation recall",
            lambda o: _rate(o["escalation"]["recall"]),
            "escalation_recall",
            _pct,
        ),
        (
            "Escalation precision",
            lambda o: _rate(o["escalation"]["precision"]),
            "escalation_precision",
            _pct,
        ),
        (
            "Escalation confusion (tp / missed / unnecessary / tn)",
            lambda o: (
                "{correct} / {missed} / {unnecessary} / {correct_no_transfer}".format(
                    **o["escalation"]
                )
            ),
            None,
            None,
        ),
        ("Unsafe outcomes", rate("unsafe"), "unsafe", _pct),
        (
            "Unsafe upper bound (rule of three)",
            lambda o: _num(o["unsafe"]["upper_bound_rule_of_three"]),
            None,
            None,
        ),
        (
            "Clarification accuracy",
            rate("clarification_accuracy"),
            "clarification_accuracy",
            _pct,
        ),
        (
            "Turn latency p50 / p95 (ms)",
            lambda o: (
                f"{_num(o['latency_ms']['turn']['p50'])} / "
                f"{_num(o['latency_ms']['turn']['p95'])} (n={o['latency_ms']['turn']['n']})"
            ),
            "turn_latency_p95",
            _fmt_num,
        ),
        (
            "Conversation latency p50 / p95 (ms)",
            lambda o: (
                f"{_num(o['latency_ms']['conversation']['p50'])} / "
                f"{_num(o['latency_ms']['conversation']['p95'])} "
                f"(n={o['latency_ms']['conversation']['n']})"
            ),
            "conversation_latency_p95",
            _fmt_num,
        ),
        (
            "Cost per case",
            lambda o: _usd(o["cost_usd"]["per_case"]),
            "cost_per_case",
            _usd,
        ),
        (
            "Cost per success",
            lambda o: _usd(o["cost_usd"]["per_success"]),
            "cost_per_success",
            _usd,
        ),
    ]


def _proposed_and_others(
    runs: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Proposed's per-run metrics, and the first (only) run of every other system."""
    proposed = runs.get("proposed", [])
    others = {s: r[0] for s, r in runs.items() if s != "proposed" and r}
    return proposed, others


def _main_table(
    label: str,
    runs: dict[str, list[dict[str, Any]]],
    agg: dict[str, dict[str, Any]],
) -> list[str]:
    proposed, others = _proposed_and_others(runs)
    cols = [f"proposed run {i + 1}" for i in range(len(proposed))]
    if proposed:
        cols.append("proposed mean (min-max)")
    cols += list(others)
    lines = [f"| Metric ({label}) | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, cell, key, fmt in _rows():
        cells = [cell(m["overall"]) for m in proposed]
        if proposed:
            cells.append(
                _spread_cell(agg["proposed"]["overall"][key], fmt) if key else "-"
            )
        cells += [cell(m["overall"]) for m in others.values()]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def _breakdown(
    title: str,
    key: str,
    label: str,
    runs: dict[str, list[dict[str, Any]]],
    agg: dict[str, dict[str, Any]],
) -> list[str]:
    proposed, others = _proposed_and_others(runs)
    cols = (["proposed mean (min-max)"] if proposed else []) + list(others)
    groups = sorted({g for rs in runs.values() for r in rs for g in r[key]})
    lines = [
        f"### {title}",
        "",
        f"| {title} (safe automated resolution, {label}) | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for g in groups:
        cells = []
        if proposed:
            ns = agg["proposed"][key][g]["cases"]
            n_txt = f"n={ns[0]}" if len(set(ns)) == 1 else f"n={'/'.join(map(str, ns))}"
            note = (
                f" **small n ({min(ns)} < {SMALL_N}), read with care**"
                if min(ns) < SMALL_N
                else ""
            )
            spread = _spread_cell(agg["proposed"][key][g]["safe_automated_resolution"], _pct)
            cells.append(f"{spread}, {n_txt}{note}")
        for m in others.values():
            o = m[key].get(g)
            if o is None:
                cells.append("-")
                continue
            note = (
                f" **small n ({o['cases']} < {SMALL_N}), read with care**"
                if o["cases"] < SMALL_N
                else ""
            )
            cells.append(f"{_rate(o['safe_automated_resolution'])}{note}")
        lines.append(f"| {g} | " + " | ".join(cells) + " |")
    return lines + [""]


def _failed_names(v: dict[str, Any]) -> list[str]:
    """Failed check names: the structured `failed_checks` when present, else `reason`.

    `reason` may carry free text (driver exception text), so the held-out report
    (R9) passes verdicts through `_structured_names` instead.
    """
    if "failed_checks" in v:
        return list(v["failed_checks"]) or ["unknown"]
    return [
        "outcome"
        if part.startswith("outcome")
        else part.split(":")[0].split(" ")[0]
        for part in (v.get("reason") or "failed").split("; ")
    ]


def _structured_names(v: dict[str, Any]) -> list[str]:
    return list(v.get("failed_checks") or ["unknown"])


def _failures(
    verdicts: dict[str, list[list[dict[str, Any]]]], heldout: bool
) -> list[str]:
    lines = ["## Failures", ""]
    any_failure = False
    for system, system_runs in verdicts.items():
        if heldout:
            # R9: case id and failed check names only, never transcript text or examples.
            # Names come from the structured `failed_checks` list, never from `reason`.
            entries = [
                f"- `{v['case_id']}` (run {i}): "
                + ", ".join(f"`{n}`" for n in _structured_names(v))
                for i, vs in enumerate(system_runs, 1)
                for v in vs
                if v["verdict"] == "failed"
            ]
            if entries:
                any_failure = True
                lines += [f"**{system}**", *entries, ""]
            continue
        # One example case id per failed check name; ids only, never transcript text.
        examples: dict[str, str] = {}
        counts: dict[str, int] = defaultdict(int)
        for vs in system_runs:
            for v in vs:
                if v["verdict"] != "failed":
                    continue
                for name in _failed_names(v):
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


def _error_analysis(
    verdicts: dict[str, list[list[dict[str, Any]]]], label: str, heldout: bool
) -> list[str]:
    """Counts by case category x failed check, summed over each system's runs."""
    lines = ["## Error analysis", ""]
    for system, system_runs in verdicts.items():
        counts: dict[tuple[str, str], int] = defaultdict(int)
        for vs in system_runs:
            for v in vs:
                if v["verdict"] == "failed":
                    for name in set(_structured_names(v) if heldout else _failed_names(v)):
                        counts[(v.get("category") or "unknown", name)] += 1
        lines.append(
            f"**{system}** ({label}; failed cases summed over {len(system_runs)} run(s))"
        )
        lines.append("")
        if not counts:
            lines += ["No failed checks.", ""]
            continue
        checks = sorted({c for _, c in counts})
        lines += [
            "| Category | " + " | ".join(f"`{c}`" for c in checks) + " |",
            "|---|" + "---|" * len(checks),
        ]
        for cat in sorted({k for k, _ in counts}):
            lines.append(
                f"| {cat} | " + " | ".join(str(counts.get((cat, c), 0)) for c in checks) + " |"
            )
        lines.append("")
    return lines


def _judge_section() -> list[str]:
    body = (
        f"See [`eval/judges/{JUDGE_AGREEMENT.name}`](../../judges/{JUDGE_AGREEMENT.name})."
        if JUDGE_AGREEMENT.exists()
        else "pending D7-B4"
    )
    return ["## Reply quality (LLM judge)", "", body, ""]


def _not_run(runs: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = ["## Not run", "", "Kept out of every denominator.", ""]
    for system, system_runs in runs.items():
        for i, m in enumerate(system_runs, 1):
            items = m["not_run"]
            tag = f" run {i}" if len(system_runs) > 1 else ""
            lines.append(f"**{system}{tag}**: {len(items)} case(s)")
            lines += [f"- `{it['case_id']}`: {it['reason']}" for it in items]
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
    out: Path,
    runs: dict[str, list[list[dict[str, Any]]]],
    meta: dict[str, Any],
    *,
    nlu: dict[str, Any] | None = None,
    nlu_section: list[str] | None = None,
) -> None:
    """`runs` maps system -> one verdict list per run (`checks.case_verdict` dicts).

    Proposed has N runs and baseline has 1 (D4). `nlu_section` lines go in verbatim.
    """
    out.mkdir(parents=True, exist_ok=True)
    label = label_for(meta.get("driver"))
    run_metrics = {s: [compute_all(vs) for vs in rs] for s, rs in runs.items()}
    agg = {s: aggregate(ms) for s, ms in run_metrics.items()}
    (out / "metrics.json").write_text(
        json.dumps(
            {
                "label": label,
                "runs": run_metrics,
                "aggregate": agg,
                "nlu": nlu or {},
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    (out / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        f"# Eval report `{meta['run_id']}` ({label})",
        "",
        f"All numbers are {label}: a {meta.get('driver', 'scripted')} suite against a database clone, not production traffic.",
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
        + (", dirty working tree" if meta["dirty"] else "")
        + (f", subset: {meta['cases_filter']}" if meta.get("cases_filter") else ""),
        f"- Proposed runs {meta['runs']} (baseline runs once, it is deterministic)",
        f"- Provider {', '.join(meta['provider']) or 'none recorded'}",
        f"- Clone ({meta['clone_strategy']}) took {meta['clone_seconds']:.0f}s, one per invocation",
        (
            f"- Persona resets {meta['resets']}, reset diffs {meta['reset_diffs']}, "
            f"PII scan hits {meta['pii_hits']}"
        ),
        "",
        f"## Metrics ({label})",
        "",
        *_main_table(label, run_metrics, agg),
        "",
        *_failures(runs, meta["suite"] == "heldout"),
        *_error_analysis(runs, label, meta["suite"] == "heldout"),
        "## Breakdowns",
        "",
        *_breakdown("Language variant", "by_language_variant", label, run_metrics, agg),
        *_breakdown("Segment", "by_segment", label, run_metrics, agg),
        *_judge_section(),
        *(["## NLU comparison", "", *nlu_section, ""] if nlu_section else []),
        *_not_run(run_metrics),
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
