import json

import pytest

from eval.harness.metrics import compute_all
from eval.harness.report import write_report

META = {
    "run_id": "dev-abc",
    "suite": "dev",
    "suite_hash": "0" * 12,
    "git_sha": "a" * 10,
    "dirty": False,
    "runs": 3,
    "provider": [],
    "clone_strategy": "FILE_COPY",
    "clone_seconds": 12.0,
    "resets": 3,
    "reset_diffs": 0,
    "pii_hits": 0,
    "driver": "scripted",
}


def _run(passed: int, total: int = 4) -> list[dict]:
    return [
        {
            "case_id": f"c{i}",
            "category": "happy",
            "verdict": "passed" if i < passed else "failed",
            "reason": None if i < passed else "no_pii",
            "outcome": "resolved",
            "expected_outcome": "resolved",
            "language_variant": "es-MX",
            "segment": "s",
        }
        for i in range(total)
    ]


def test_proposed_runs_aggregate(tmp_path):
    runs = {"proposed": [_run(2), _run(3), _run(4)], "baseline": [_run(1)]}
    write_report(tmp_path, runs, META)
    m = json.loads((tmp_path / "metrics.json").read_text())

    sar = m["aggregate"]["proposed"]["overall"]["safe_automated_resolution"]
    assert sar["per_run"] == [0.5, 0.75, 1.0]
    assert sar["mean"] == pytest.approx(0.75)
    assert (sar["min"], sar["max"]) == (0.5, 1.0)
    assert len(m["runs"]["proposed"]) == 3
    assert m["runs"]["baseline"] == json.loads(json.dumps([compute_all(_run(1))]))
    assert m["aggregate"]["baseline"]["overall"]["safe_automated_resolution"]["mean"] == 0.25

    md = (tmp_path / "report.md").read_text()
    row = next(x for x in md.splitlines() if x.startswith("| Safe automated resolution"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1].startswith("50.0% (2/4")
    assert cells[4] == "75.0% (50.0%-100.0%)"
    assert cells[5].startswith("25.0% (1/4")
    assert "offline evaluation" in md
    assert "pending D7-B4" in md


def test_heldout_failure_lines_carry_only_check_names(tmp_path):
    bad = {
        **_run(0, 1)[0],
        "case_id": "h-003",
        "reason": "error: boom; SECRETWORD in transcript",
        "failed_checks": ["error"],
    }
    write_report(tmp_path, {"proposed": [[bad]]}, {**META, "suite": "heldout", "runs": 1})
    md = (tmp_path / "report.md").read_text()
    assert "`h-003` (run 1): `error`" in md
    assert "SECRETWORD" not in md
    assert "boom" not in md
