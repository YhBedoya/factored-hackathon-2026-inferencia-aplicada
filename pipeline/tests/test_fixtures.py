"""D20: labeled TEST FIXTURE trees run through ingest, contracts and dbt in a tmp dir.

Nothing here touches the repo's `data/`: raw, manifest, DuckDB and dbt's target/log all
live under `tmp_path`.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import duckdb
import pytest

import ingest
import ingest.local
from contracts import run as run_contracts
from contracts.schemas import load_aliases

PIPELINE = Path(__file__).resolve().parents[1]
FIXTURES = PIPELINE / "fixtures"
DBT_DIR = PIPELINE / "dbt"


@pytest.fixture
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(ingest, "MANIFEST_PATH", tmp_path / "raw" / "_manifest.json")
    return tmp_path / "raw"


def _ingest(fixture: str) -> dict:
    manifest = ingest.load_manifest()
    changed, _, _ = ingest.local.ingest(str(FIXTURES / fixture), manifest)
    manifest.update(changed)
    ingest.save_manifest(manifest)
    return manifest


def _dbt(tmp_path: Path, raw: Path) -> Path:
    db = tmp_path / "pipeline.duckdb"
    aliases = load_aliases()
    variables = {"date_offset_days": 0, "raw_root": str(raw), "column_aliases": aliases}
    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            "..",
            "dbt",
            "build",
            "--select",
            "stg_transactions+",
            "stg_transactions__rejects",
            "--indirect-selection",
            "cautious",
            # cautious alone does not skip these: the other parent (srv_customers,
            # srv_products) is absent from the tmp DuckDB, so they error instead.
            "--exclude",
            "test_name:relationships",
            "test_type:singular",
            "--project-dir",
            ".",
            "--profiles-dir",
            ".",
            "--target-path",
            str(tmp_path / "dbt_target"),
            "--log-path",
            str(tmp_path / "dbt_logs"),
            "--vars",
            json.dumps(variables),
        ],
        cwd=DBT_DIR,
        env={**os.environ, "PIPELINE_DUCKDB_PATH": str(db)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return db


def _query(db: Path, sql: str) -> list[tuple]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_late_partition_corrected_rows_win(tmp_path: Path, raw: Path) -> None:
    _ingest("test_fixture_late_partition/v1")
    db = _dbt(tmp_path, raw)
    (before,) = _query(db, "select count(*) from srv_transactions")[0:1]

    _ingest("test_fixture_late_partition/v2")
    _dbt(tmp_path, raw)
    rows = _query(
        db, "select amount from srv_transactions where transaction_id = 'TRX-TESTFIXTURE00001'"
    )
    assert [float(r[0]) for r in rows] == [99.0]
    assert _query(db, "select count(*) from srv_transactions")[0] == before


def test_duplicate_batch_rejected(tmp_path: Path, raw: Path) -> None:
    _ingest("test_fixture_duplicate_batch")
    db = _dbt(tmp_path, raw)
    base_rows = 3
    assert _query(db, "select count(*) from stg_transactions")[0][0] == base_rows
    assert _query(db, "select count(*) from stg_transactions__rejects")[0][0] == base_rows


def test_schema_change_mapped(tmp_path: Path, raw: Path) -> None:
    manifest = _ingest("test_fixture_schema_change")
    quality = tmp_path / "quality"
    assert run_contracts(raw, manifest, quality, "fixture") == 0
    table = json.loads((quality / "fixture" / "contract_report.json").read_text())["tables"][
        "transactions"
    ]
    assert "installments" in table["unknown_columns"]
    assert "merchant->merchant_name" in table["aliased"]

    db = _dbt(tmp_path, raw)
    merchants = {r[0] for r in _query(db, "select merchant_name from srv_transactions")}
    assert merchants == {"Test Fixture Shop", "Renamed Shop"}
    columns = {r[0] for r in _query(db, "describe srv_transactions")}
    assert "installments" not in columns
