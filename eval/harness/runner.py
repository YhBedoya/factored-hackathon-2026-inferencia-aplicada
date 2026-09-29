"""The eval run lifecycle (D13): clone, backend subprocess, play, collect, check, report.

`run(suite, system)` runs one system after the other (`both` = proposed, then baseline),
each on its own fresh clone of the golden DB, and writes a single side-by-side report.
The driver is injectable so tests can replay canned transcripts; the default is B's
`run_case`. Nothing here imports `app` (D25).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import os
import socket
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg

from eval.driver.driver import Transcript, run_case
from eval.harness import clone, pii_check
from eval.harness.checks import case_verdict, run_checks
from eval.harness.evidence import collect
from eval.harness.lint import lint_suite, load_write_tools, writing_case
from eval.harness.report import write_report
from eval.harness.restore import restore_persona, verify_persona
from eval.scenarios.schema import Case, load_dir

__all__ = ["SYSTEMS", "Driver", "LLMUnreachableError", "llm_unreachable", "run"]

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "eval" / "reports"
SCENARIOS = ROOT / "eval" / "scenarios"
POLICIES = ROOT / "policies"
SYSTEMS = ("proposed", "baseline")
# One Redis DB per system, apart from the dev stack's index 0 (D13 step 2).
_REDIS_INDEX = {"proposed": 1, "baseline": 2}
_HEALTH_TIMEOUT_SECONDS = 90.0

Driver = Callable[..., Awaitable[Transcript]]

# Cases to play before "every call failed" counts as an outage, not a bad first case.
_MIN_CASES_BEFORE_ABORT = 5


class LLMUnreachableError(Exception):
    """Every LLM call so far was `unavailable`. Aborts the run, no report (like `RestoreDiffError`)."""

    def __init__(
        self, model_id: str | None, step: str | None, rows_seen: int = 0
    ) -> None:
        super().__init__(
            f"LLM unreachable: model {model_id!r}, step {step!r}, {rows_seen} ledger rows seen"
        )
        self.model_id = model_id
        self.step = step
        self.rows_seen = rows_seen


def llm_unreachable(cases_played: int, statuses: list[str]) -> bool:
    """Pure abort decision: enough cases played, at least one call ledgered, none succeeded.

    No rows at all is not an outage: the baseline (keyword NLU, fixed templates) can
    play several cases without any LLM call."""
    if cases_played < _MIN_CASES_BEFORE_ABORT or not statuses:
        return False
    return all(s == "unavailable" for s in statuses)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _redis_url(index: int) -> str:
    parts = urlsplit(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{index}", parts.query, parts.fragment)
    )


def _sha256_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() or "unknown"


def _wait_healthy(base_url: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn exited early with code {proc.returncode}")
        try:
            if httpx.get(f"{base_url}/api/v1/health", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"backend not healthy after {_HEALTH_TIMEOUT_SECONDS:.0f}s")


def _start_backend(system: str, dbname: str, port: int) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "APP_ENV": "eval",
        # The backend reads the async SQLAlchemy form; `clone.dsn` returns a bare psycopg one.
        "DATABASE_URL": clone.dsn(dbname).replace(
            "postgresql://", "postgresql+asyncpg://", 1
        ),
        "REDIS_URL": _redis_url(_REDIS_INDEX[system]),
        "AGENT_SYSTEM": system,
        "BANK": "postgres",
    }
    return subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT / "backend",
        env=env,
    )


def _stop_backend(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _skipped(case: Case) -> Transcript:
    # `ended_by="done"` with no turns: `case_verdict` labels it `not_run` from `db_patches` (D27).
    return Transcript(
        case_id=case.case_id, conversation_id=None, turns=[], ended_by="done"
    )


async def _play(
    cases: list[Case],
    base_url: str,
    clone_conn: psycopg.Connection[Any],
    golden_conn: psycopg.Connection[Any],
    driver: Driver,
    system: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    write_tools = load_write_tools()
    otp = os.environ.get("DEMO_OTP_CODE", "")
    verdicts: list[dict[str, Any]] = []
    llm_rows: list[dict[str, Any]] = []
    restores = 0
    played = 0
    for case in cases:
        if case.setup.db_patches:
            transcript = _skipped(case)
        else:
            played += 1
            transcript = await driver(case, base_url=base_url, otp_code=otp)
        evidence = collect(clone_conn, case, transcript)
        if writing_case(case, write_tools) and transcript.conversation_id is not None:
            # A diff after the restore raises `RestoreDiffError`, which aborts the run (D14).
            restore_persona(clone_conn, golden_conn, case.persona)
            verify_persona(clone_conn, golden_conn, case.persona)
            restores += 1
        verdict = case_verdict(evidence, run_checks(evidence, write_tools))
        if verdict["verdict"] == "not_run":
            verdict["unsafe"] = (
                False  # nothing was played, so nothing can have been unsafe
            )
        verdict["system"] = system
        verdicts.append(verdict)
        llm_rows.extend(
            {**c, "system": system, "case_id": case.case_id} for c in evidence.llm_calls
        )
        # The rows are this system's `audit.llm_calls` from the clone, read by `collect`.
        if llm_unreachable(played, [str(r.get("status")) for r in llm_rows]):
            # `audit.llm_calls` columns are `model_id` and `step`; None only if no row was ledgered.
            first = llm_rows[0] if llm_rows else {}
            raise LLMUnreachableError(
                first.get("model_id"), first.get("step"), len(llm_rows)
            )
    return verdicts, llm_rows, restores


async def _run_system(
    system: str, run_id: str, cases: list[Case], driver: Driver
) -> dict[str, Any]:
    dbname, clone_seconds = clone.create(f"{run_id}_{system}")
    proc: subprocess.Popen[bytes] | None = None
    conns: list[psycopg.Connection[Any]] = []
    try:
        port = _free_port()
        proc = _start_backend(system, dbname, port)
        base_url = f"http://127.0.0.1:{port}"
        _wait_healthy(base_url, proc)
        # Golden connections open after the clone exists: `clone.create` ends golden sessions.
        golden_conn = psycopg.connect(clone.dsn(clone.GOLDEN_DB))
        conns.append(golden_conn)
        clone_conn = psycopg.connect(clone.dsn(dbname))
        conns.append(clone_conn)
        verdicts, llm_rows, restores = await _play(
            cases, base_url, clone_conn, golden_conn, driver, system
        )
    finally:
        if proc is not None:
            _stop_backend(proc)
        # Golden connections close before any clone is dropped.
        for conn in conns:
            with contextlib.suppress(Exception):
                conn.close()
        clone.drop(dbname)
    ledger = sorted(
        {
            (r["step"], r["provider"], r["model_id"], r["prompt_version"])
            for r in llm_rows
            if r.get("step")
        }
    )
    return {
        "system": system,
        "verdicts": verdicts,
        "llm_rows": llm_rows,
        "restores": restores,
        "clone_seconds": round(clone_seconds, 1),
        "providers": sorted({row[1] for row in ledger}),
        "models": [
            {"step": s, "provider": p, "model_id": m, "prompt_version": v}
            for s, p, m, v in ledger
        ],
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _pii_scan(run_id: str) -> int:
    """The run-internal PII scan (D20): `pii_check.main` prints `<n> hits`."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        pii_check.main(["--run", run_id])
    last = buffer.getvalue().strip().splitlines()[-1]
    return int(last.split()[0])


def run(
    suite: str,
    system: str = "both",
    *,
    driver: Driver | None = None,
    run_id: str | None = None,
    cases_filter: list[str] | None = None,
) -> str:
    """Play `suite` on `system` (`proposed`, `baseline` or `both`); returns the run id.

    `cases_filter` keeps only cases whose `seed_id` starts with one of the prefixes.
    """
    systems = list(SYSTEMS) if system == "both" else [system]
    if any(s not in SYSTEMS for s in systems):
        raise ValueError(f"system must be one of {SYSTEMS} or 'both': {system!r}")
    suite_dir = SCENARIOS / suite
    cases = load_dir(suite_dir)
    if not cases:
        raise ValueError(f"no cases under {suite_dir}")
    if cases_filter:
        # Before lint and before any clone: an empty selection must cost nothing.
        prefixes = tuple(cases_filter)
        cases = [c for c in cases if c.seed_id.startswith(prefixes)]
        if not cases:
            raise ValueError(f"no case matches --cases {','.join(cases_filter)}")
    lint_suite(cases)
    started = datetime.now(UTC)
    run_id = run_id or f"{suite}_{system}_{started:%Y%m%dt%H%M%S}"
    play = driver or run_case
    results = [asyncio.run(_run_system(s, run_id, cases, play)) for s in systems]

    out = REPORTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    verdicts = [v for r in results for v in r["verdicts"]]
    _write_jsonl(out / "results.jsonl", verdicts)
    _write_jsonl(
        out / "llm_calls.jsonl", [row for r in results for row in r["llm_rows"]]
    )
    pii_hits = _pii_scan(run_id)

    meta = {
        "run_id": run_id,
        "label": "offline evaluation",
        "git_sha": _git_sha(),
        "system": system,
        "suite": suite,
        "cases_filter": ",".join(cases_filter) if cases_filter else None,
        "suite_hash": _sha256_files(list(suite_dir.glob("*.yaml"))),
        "policy_hash": _sha256_files(list(POLICIES.glob("*.yaml"))),
        "started": started.isoformat(),
        "finished": datetime.now(UTC).isoformat(),
        "provider": sorted({p for r in results for p in r["providers"]}),
        "clone_seconds": {r["system"]: r["clone_seconds"] for r in results},
        "models": {r["system"]: r["models"] for r in results},
        "restore_count": sum(r["restores"] for r in results),
        # Any diff aborts the run, so a finished run has none.
        "restore_diffs": 0,
        "pii_hits": pii_hits,
    }
    write_report(out, {r["system"]: r["verdicts"] for r in results}, meta)
    return run_id
