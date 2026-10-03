"""Pandera data contracts over the raw all-VARCHAR Parquet partitions (D17).

`run()` validates the manifest partitions that changed since the last run, writes
`<quality_root>/<run_id>/contract_report.json` and returns the exit code:
0 = validated (failures are counted, rows flow on), 2 = structural break.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import duckdb
import pandas as pd
import pandera.errors as pa_errors

from contracts.schemas import SCHEMAS, load_aliases, primary_key
from ingest import classify_relative_key

MAX_SAMPLES = 5
CACHE_NAME = "contract_cache.json"


class StructuralBreak(Exception):
    """An unreadable file or a missing PK column: the load must stop."""


def _parquet_path(raw_root: Path, table: str, key: str) -> Path:
    if PurePosixPath(key).parent.name == "":
        return raw_root / table / f"{table}.parquet"
    return raw_root / (key[: -len(".csv")] + ".parquet")


def _read(path: Path) -> pd.DataFrame:
    try:
        con = duckdb.connect()
        try:
            df = con.execute(
                "SELECT * FROM read_parquet(?, hive_partitioning = false)", [str(path)]
            ).df()
        finally:
            con.close()
    except Exception as exc:
        raise StructuralBreak(f"unreadable file {path.name}: {type(exc).__name__}") from exc
    # Blank strings are NULL, like the models' nullif(trim(x), '').
    for col in df.columns:
        s = df[col].astype("string").str.strip()
        df[col] = s.mask(s == "", pd.NA)
    return df


def _validate_partition(table: str, path: Path) -> dict[str, Any]:
    """Validate one file. Raises StructuralBreak; everything else is counted."""
    df = _read(path)
    aliased: list[str] = []
    for raw, canonical in load_aliases().get(table, {}).items():
        if raw in df.columns and canonical not in df.columns:
            df = df.rename(columns={raw: canonical})
            aliased.append(f"{raw}->{canonical}")

    schema = SCHEMAS[table]
    pk = list(primary_key(table))
    missing_pk = [c for c in pk if c not in df.columns]
    if missing_pk:
        raise StructuralBreak(f"{table}: missing PK column(s) {missing_pk}")

    known = set(schema.columns)
    unknown = sorted(set(df.columns) - known)
    missing = sorted(known - set(df.columns) - set(pk))
    checks: dict[str, int] = {}
    samples: dict[str, list[dict[str, Any]]] = {}

    def sample(check: str, column: str, idx: Any) -> None:
        rows = df.loc[idx, list(dict.fromkeys([*pk, column]))].head(MAX_SAMPLES)
        samples[check] = [
            {k: (None if pd.isna(v) else str(v)) for k, v in r.items()}
            for r in rows.to_dict("records")
        ]

    dups = df.duplicated(subset=pk, keep="first")
    if dups.any():
        checks["pk_duplicate"] = int(dups.sum())
        sample("pk_duplicate", pk[0], df.index[dups])

    present = schema.remove_columns([c for c in schema.columns if c not in df.columns])
    try:
        present.validate(df, lazy=True)
    except pa_errors.SchemaErrors as exc:
        cases = exc.failure_cases
        cases = cases[cases["column"].notna()]
        for (column, check), grp in cases.groupby(["column", "check"], sort=True):
            name = f"{column}:{check}"
            checks[name] = len(grp)
            sample(name, str(column), grp["index"].dropna().astype(int).tolist())

    return {
        "checks": checks,
        "samples": samples,
        "unknown_columns": unknown,
        "missing_columns": missing,
        "aliased": aliased,
    }


def _fingerprint(entry: dict[str, Any]) -> str:
    return str(entry.get("etag") or entry.get("sha256") or "")


def _aggregate(per_partition: dict[str, dict[str, Any]], cached_keys: set[str]) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "partitions_validated": 0,
            "partitions_cached": 0,
            "partitions_failed": 0,
            "checks": {},
            "unknown_columns": [],
            "missing_columns": [],
            "aliased": [],
            "samples": {},
        }
    )
    for key, res in sorted(per_partition.items()):
        t = tables[res["table"]]
        t["partitions_cached" if key in cached_keys else "partitions_validated"] += 1
        if res["checks"]:
            t["partitions_failed"] += 1
        for check, n in res["checks"].items():
            t["checks"][check] = t["checks"].get(check, 0) + n
            if check not in t["samples"]:
                t["samples"][check] = res["samples"].get(check, [])
        for field in ("unknown_columns", "missing_columns", "aliased"):
            t[field] = sorted({*t[field], *res[field]})
    return dict(tables)


def run(raw_root: Path, manifest: dict, quality_root: Path, run_id: str) -> int:
    """Validate changed partitions, write the report, return the exit code."""
    cache_path = quality_root / CACHE_NAME
    cache: dict[str, dict[str, Any]] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    per_partition: dict[str, dict[str, Any]] = {}
    cached_keys: set[str] = set()
    breaks: list[str] = []
    for key in sorted(manifest):
        entry = manifest[key]
        table = classify_relative_key(key)
        if table is None:
            continue
        cache_key = f"{key}|{_fingerprint(entry)}"
        if cache_key in cache:
            per_partition[key] = cache[cache_key]
            cached_keys.add(key)
            continue
        try:
            result = _validate_partition(table, _parquet_path(raw_root, table, key))
        except StructuralBreak as exc:
            breaks.append(f"{key}: {exc}")
            break
        result["table"] = table
        per_partition[key] = result
        cache[cache_key] = result

    validated = len(per_partition) - len(cached_keys)
    report = {
        "run_id": run_id,
        "validated": validated,
        "cached": len(cached_keys),
        "structural_breaks": breaks,
        "tables": _aggregate(per_partition, cached_keys),
    }
    out_dir = quality_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "contract_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    cache_path.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    print(
        f"contracts validated={validated} cached={len(cached_keys)} structural_breaks={len(breaks)}"
    )
    return 2 if breaks else 0
