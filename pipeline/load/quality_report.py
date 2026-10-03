"""Per-run data-quality report: `data/quality/<run_id>/quality_report.{json,md}` (D21).

Pulls four things together: `bank.*` row counts (the `copy_all` counts),
`stg_<t>__rejects` counts (DuckDB), dbt test results (`run_results.json` +
`manifest.json`) and the Pandera summary (`contract_report.json`). It holds no
row values beyond what the contract report already carries (PK + failing
column, A7).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from load.postgres import TABLES

REPO_ROOT = Path(__file__).resolve().parents[2]
QUALITY_ROOT = REPO_ROOT / "data" / "quality"
DBT_TARGET = REPO_ROOT / "pipeline" / "dbt" / "target"


def _reject_counts(warehouse_path: str) -> dict[str, int]:
    con = duckdb.connect(warehouse_path, read_only=True)
    try:
        return {
            t: int(con.execute(f"select count(*) from stg_{t}__rejects").fetchone()[0])  # type: ignore[index]
            for t in TABLES
        }
    finally:
        con.close()


def _dbt_tests(target: Path) -> list[dict[str, Any]]:
    """Name, severity, status and failures per dbt test; relationship tests flag orphans."""
    run_results = target / "run_results.json"
    manifest_path = target / "manifest.json"
    if not (run_results.exists() and manifest_path.exists()):
        return []
    nodes = json.loads(manifest_path.read_text(encoding="utf-8")).get("nodes", {})
    tests: list[dict[str, Any]] = []
    for result in json.loads(run_results.read_text(encoding="utf-8")).get("results", []):
        node = nodes.get(result["unique_id"])
        if node is None or node.get("resource_type") != "test":
            continue
        kind = (node.get("test_metadata") or {}).get("name")
        tests.append(
            {
                "name": node["name"],
                "kind": kind,
                "severity": (node.get("config") or {}).get("severity", "error"),
                "status": result["status"],
                "failures": int(result.get("failures") or 0),
                "orphans": kind == "relationships",
            }
        )
    return sorted(tests, key=lambda t: t["name"])


def _contract_summary(quality_dir: Path) -> dict[str, Any]:
    path = quality_dir / "contract_report.json"
    if not path.exists():
        return {}
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "validated": report.get("validated", 0),
        "cached": report.get("cached", 0),
        "structural_breaks": report.get("structural_breaks", []),
        "tables": {
            table: {
                "partitions_failed": info.get("partitions_failed", 0),
                "checks": info.get("checks", {}),
                "unknown_columns": info.get("unknown_columns", []),
                "missing_columns": info.get("missing_columns", []),
                "aliased": info.get("aliased", []),
            }
            for table, info in report.get("tables", {}).items()
        },
    }


def _render_md(report: dict[str, Any]) -> str:
    lines = [f"# Quality report `{report['run_id']}`", ""]
    lines += ["## Row counts and rejects", "", "| table | bank rows | rejects |", "|---|---:|---:|"]
    for t in TABLES:
        lines.append(f"| {t} | {report['row_counts'][t]} | {report['rejects'][t]} |")

    tests = report["dbt_tests"]
    orphans = [t for t in tests if t["orphans"]]
    lines += ["", "## Orphans (relationship tests)", ""]
    if orphans:
        lines += ["| test | severity | status | orphans |", "|---|---|---|---:|"]
        lines += [
            f"| {t['name']} | {t['severity']} | {t['status']} | {t['failures']} |" for t in orphans
        ]
    else:
        lines.append("No relationship tests were run.")

    # Relationship tests are listed once, in the Orphans table above.
    tests = [t for t in tests if not t["orphans"]]
    lines += ["", "## dbt tests", ""]
    if tests:
        lines += ["| test | severity | status | failures |", "|---|---|---|---:|"]
        lines += [
            f"| {t['name']} | {t['severity']} | {t['status']} | {t['failures']} |" for t in tests
        ]
    else:
        lines.append("No dbt test results found.")

    contracts = report["contracts"]
    lines += ["", "## Contracts (Pandera)", ""]
    if contracts:
        lines.append(
            f"Validated {contracts['validated']} partitions, cached {contracts['cached']}, "
            f"structural breaks: {', '.join(contracts['structural_breaks']) or 'none'}."
        )
        lines.append("")
        for table, info in contracts["tables"].items():
            if info["partitions_failed"] or info["unknown_columns"] or info["missing_columns"]:
                lines.append(
                    f"- {table}: failed partitions {info['partitions_failed']}, "
                    f"unknown {info['unknown_columns']}, missing {info['missing_columns']}, "
                    f"checks {info['checks']}"
                )
    else:
        lines.append("No contract report for this run.")
    return "\n".join(lines) + "\n"


def write(
    run_id: str,
    row_counts: dict[str, int],
    warehouse_path: str,
    *,
    quality_root: Path = QUALITY_ROOT,
    dbt_target: Path = DBT_TARGET,
) -> Path:
    """Write the JSON and Markdown reports; returns the run's quality directory."""
    quality_dir = quality_root / run_id
    quality_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": run_id,
        "row_counts": row_counts,
        "rejects": _reject_counts(warehouse_path),
        "dbt_tests": _dbt_tests(dbt_target),
        "contracts": _contract_summary(quality_dir),
    }
    (quality_dir / "quality_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (quality_dir / "quality_report.md").write_text(_render_md(report), encoding="utf-8")
    return quality_dir
