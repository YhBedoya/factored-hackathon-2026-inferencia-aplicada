"""D17: a structural break stops the run; every other failure is counted and flows on."""

from __future__ import annotations

import json
from pathlib import Path

from contracts import run
from ingest import csv_to_parquet

KEY = "transactions/year=2026/month=01/day=01/part.csv"


def _partition(tmp_path: Path, header: str, rows: list[str]) -> tuple[Path, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw = tmp_path / "raw"
    csv = tmp_path / "src.csv"
    csv.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    csv_to_parquet(csv, raw / KEY.replace(".csv", ".parquet"))
    return raw, {KEY: {"source": "local", "key": KEY, "sha256": "abc"}}


def test_structural_break_stops_other_failures_reported(tmp_path: Path, capsys) -> None:
    quality = tmp_path / "quality"

    raw, manifest = _partition(tmp_path / "a", "amount,fraud_score", ["10,5"])
    assert run(raw, manifest, quality, "r0") == 2

    raw, manifest = _partition(
        tmp_path / "b",
        "transaction_id,merchant,fraud_score,extra",
        ["t1,Shop,150,x", "t1,Shop,5,x", "t2,Shop,7,x"],
    )
    assert run(raw, manifest, quality, "r1") == 0
    table = json.loads((quality / "r1" / "contract_report.json").read_text())["tables"][
        "transactions"
    ]
    assert table["checks"]["fraud_score:range"] == 1
    assert table["checks"]["pk_duplicate"] == 1
    assert table["aliased"] == ["merchant->merchant_name"]
    assert table["unknown_columns"] == ["extra"]
    assert set(table["samples"]["fraud_score:range"][0]) == {"transaction_id", "fraud_score"}

    capsys.readouterr()
    assert run(raw, manifest, quality, "r2") == 0
    assert "contracts validated=0 cached=1 structural_breaks=0" in capsys.readouterr().out
