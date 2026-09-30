"""The eval run lifecycle (D13): clone, backend subprocess, play, collect, check, report.

`run(suite, system, runs=N)` plays proposed N times, then baseline once (D4), all on one
FILE_COPY clone of the golden DB (D10); the suite personas are reset and verified before
each run. One side-by-side report per invocation.
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
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg

from eval.driver.driver import Transcript, run_case
from eval.harness import clone, patches, pii_check
from eval.harness.checks import case_verdict, run_checks
from eval.harness.evidence import collect
from eval.harness.lint import lint_suite, load_write_tools, writing_case
from eval.harness.metrics import label_for
from eval.harness.report import write_report
from eval.harness.restore import restore_persona, verify_persona
from eval.scenarios import freeze
from eval.scenarios.schema import Case, load_dir

__all__ = [
    "SYSTEMS",
    "Driver",
    "HeldoutRefusedError",
    "LLMUnreachableError",
    "heldout_refusal",
    "llm_unreachable",
    "run",
]

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


class HeldoutRefusedError(Exception):
    """`--suite heldout` without the freeze preconditions (D3, R9). The CLI exits 2."""


def heldout_refusal(suite: str) -> str | None:
    """One-line reason when `suite` is `heldout` and it isn't frozen, else None (D3)."""
    if suite != "heldout":
        return None
    reason = (
        "refusing --suite heldout: it needs eval/scenarios/heldout.lock and a passing "
        "freeze check, i.e. (1) both humans reviewed _staging/heldout/, "
        "(2) a human ran `make eval-freeze`, (3) the D1.5 targets are in 05 section 6"
    )
    if not (SCENARIOS / "heldout.lock").is_file() or freeze.check(SCENARIOS):
        return reason
    return None


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


def _prefer_loopback(url: str) -> str:
    """`localhost` -> `127.0.0.1` in `url`'s host, everything else unchanged (T9 addendum).

    win32-only caller: on this class of host, `getaddrinfo("localhost", ...)` takes
    ~2s, longer than `ping_redis`'s fixed 2s budget, so `/api/v1/health` never
    reports `redis: up` even though Redis is reachable. A literal `127.0.0.1`
    skips that lookup. A non-`localhost` host (e.g. a real DB host) is untouched.
    """
    parts = urlsplit(url)
    if parts.hostname != "localhost":
        return url
    userinfo = ""
    if parts.username:
        userinfo = parts.username + (f":{parts.password}" if parts.password else "")
        userinfo += "@"
    netloc = f"{userinfo}127.0.0.1" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


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


def _short_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "--short=10", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() or "unknown"


def _dirty() -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(out.stdout.strip())


def _folder_name(suite: str) -> str:
    """`<suite>-<sha10>`, then `-2`, `-3` when the folder exists (D6)."""
    base = f"{suite}-{_short_sha()}"
    name, k = base, 1
    while (REPORTS / name).exists():
        k += 1
        name = f"{base}-{k}"
    return name


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


def _start_backend(
    system: str, dbname: str, port: int, faults: frozenset[str]
) -> subprocess.Popen[bytes]:
    # The backend reads the async SQLAlchemy form; `clone.dsn` returns a bare psycopg one.
    database_url = clone.dsn(dbname).replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
    redis_url = _redis_url(_REDIS_INDEX[system])
    cmd = ["uv", "run", "uvicorn", "app.main:app", "--port", str(port)]
    if sys.platform == "win32":
        # uvicorn's default `--loop auto` resolves to `ProactorEventLoop` on win32
        # (`uvicorn.loops.asyncio.asyncio_loop_factory`), which psycopg async and
        # the checkpointer pool refuse (T9, `Psycopg cannot use the
        # 'ProactorEventLoop'` -> `PoolTimeout`). `--loop` also accepts any
        # `module:attribute` import string resolving to a zero-arg callable
        # (`Config.get_loop_factory`, uvicorn 0.37); `asyncio.SelectorEventLoop`
        # itself qualifies, so no new module or `sys.path` change is needed.
        cmd += ["--loop", "asyncio:SelectorEventLoop"]
        # `localhost` -> `127.0.0.1` (T9 addendum): see `_prefer_loopback`.
        database_url = _prefer_loopback(database_url)
        redis_url = _prefer_loopback(redis_url)
    env = {
        **os.environ,
        "APP_ENV": "eval",
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "AGENT_SYSTEM": system,
        "BANK": "postgres",
        # The backend arms its fault hooks from this at startup, so one backend per fault set.
        "FAULTS": ",".join(sorted(faults)),
    }
    return subprocess.Popen(
        cmd,
        cwd=ROOT / "backend",
        env=env,
    )


def _stop_backend(proc: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        # `uv run` doesn't forward termination to the uvicorn/python descendants
        # it spawns on Windows (T9 addendum): `proc.terminate()` alone leaves them
        # running, leaking the clone DB behind. `taskkill /T` kills the whole tree.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def fault_groups(cases: list[Case]) -> list[tuple[frozenset[str], list[Case]]]:
    """Group cases by fault set: the empty set first, the rest in first-seen order."""
    groups: dict[frozenset[str], list[Case]] = {frozenset(): []}
    for case in cases:
        groups.setdefault(frozenset(case.setup.faults), []).append(case)
    return [(faults, group) for faults, group in groups.items() if group]


def _clear_turn_keys(system: str) -> None:
    """Drop stale `turns:*` keys in this system's eval Redis db, never db 0."""
    import redis  # local: only the eval runner needs it

    client = redis.Redis.from_url(_redis_url(_REDIS_INDEX[system]))
    try:
        for key in client.scan_iter("turns:*"):
            client.delete(key)
    finally:
        client.close()


_Handle = TypeVar("_Handle")
_Result = TypeVar("_Result")


async def _play_groups(
    groups: list[tuple[frozenset[str], list[Case]]],
    start: Callable[[frozenset[str]], _Handle],
    stop: Callable[[_Handle], None],
    play_group: Callable[[_Handle, frozenset[str], list[Case]], Awaitable[_Result]],
) -> list[_Result]:
    """One backend per fault group on the same clone: start, play, always stop."""
    results: list[_Result] = []
    for faults, group in groups:
        handle = start(faults)
        try:
            results.append(await play_group(handle, faults, group))
        finally:
            stop(handle)
    return results


async def _play(
    cases: list[Case],
    base_url: str,
    clone_conn: psycopg.Connection[Any],
    golden_conn: psycopg.Connection[Any],
    driver: Driver,
    system: str,
    faults: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    write_tools = load_write_tools()
    otp = os.environ.get("DEMO_OTP_CODE", "")
    verdicts: list[dict[str, Any]] = []
    llm_rows: list[dict[str, Any]] = []
    restores = 0
    for played, case in enumerate(cases, start=1):
        db_patches = case.setup.db_patches
        if db_patches:
            patches.apply(clone_conn, db_patches)
        transcript = await driver(case, base_url=base_url, otp_code=otp)
        evidence = collect(clone_conn, case, transcript)
        if db_patches:
            # A diff raises `PatchDiffError`, which aborts the run like `RestoreDiffError`.
            patches.revert_and_verify(clone_conn, golden_conn, db_patches)
        if writing_case(case, write_tools) and transcript.conversation_id is not None:
            # A diff after the restore raises `RestoreDiffError`, which aborts the run (D14).
            restore_persona(clone_conn, golden_conn, case.persona)
            verify_persona(clone_conn, golden_conn, case.persona)
            restores += 1
        verdict = case_verdict(evidence, run_checks(evidence, write_tools))
        if verdict["verdict"] == "not_run":
            verdict["unsafe"] = False  # `not_runnable`: nothing was played
        verdict["system"] = system
        verdicts.append(verdict)
        llm_rows.extend(
            {**c, "system": system, "case_id": case.case_id} for c in evidence.llm_calls
        )
        # The rows are this system's `audit.llm_calls` from the clone, read by `collect`.
        # A `bedrock_timeout` group makes every call unavailable on purpose: not an outage.
        if "bedrock_timeout" not in faults and llm_unreachable(
            played, [str(r.get("status")) for r in llm_rows]
        ):
            # `audit.llm_calls` columns are `model_id` and `step`; None only if no row was ledgered.
            first = llm_rows[0] if llm_rows else {}
            raise LLMUnreachableError(
                first.get("model_id"), first.get("step"), len(llm_rows)
            )
    return verdicts, llm_rows, restores


def _reset_personas(
    clone_conn: psycopg.Connection[Any],
    golden_conn: psycopg.Connection[Any],
    cases: list[Case],
    system: str,
) -> int:
    """Before a run (D10): every distinct suite persona back to golden, then clear `turns:*`.

    A diff raises `RestoreDiffError` and aborts the invocation. Returns the persona count."""
    personas = sorted({c.persona for c in cases})
    for persona in personas:
        restore_persona(clone_conn, golden_conn, persona)
        verify_persona(clone_conn, golden_conn, persona)
    # `verify_persona` only reads, which leaves both connections idle in a transaction
    # holding table locks. The backend's checkpointer `setup()` runs DDL on the clone and
    # would wait on them until the health timeout; end the transactions before it starts.
    clone_conn.rollback()
    golden_conn.rollback()
    _clear_turn_keys(system)
    return len(personas)


async def _run_system(
    system: str, dbname: str, cases: list[Case], driver: Driver
) -> dict[str, Any]:
    """One run of `system` on the shared clone `dbname` (created and dropped by `run`)."""
    conns: list[psycopg.Connection[Any]] = []
    try:
        golden_conn = psycopg.connect(clone.dsn(clone.GOLDEN_DB))
        conns.append(golden_conn)
        clone_conn = psycopg.connect(clone.dsn(dbname))
        conns.append(clone_conn)
        resets = _reset_personas(clone_conn, golden_conn, cases, system)

        def start(faults: frozenset[str]) -> tuple[subprocess.Popen[bytes], str]:
            _clear_turn_keys(system)
            port = _free_port()
            proc = _start_backend(system, dbname, port, faults)
            base_url = f"http://127.0.0.1:{port}"
            try:
                _wait_healthy(base_url, proc)
            except BaseException:
                _stop_backend(proc)
                raise
            return proc, base_url

        async def play_group(
            handle: tuple[subprocess.Popen[bytes], str],
            faults: frozenset[str],
            group: list[Case],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
            return await _play(
                group, handle[1], clone_conn, golden_conn, driver, system, faults
            )

        group_results = await _play_groups(
            fault_groups(cases), start, lambda h: _stop_backend(h[0]), play_group
        )
        verdicts = [v for r in group_results for v in r[0]]
        llm_rows = [row for r in group_results for row in r[1]]
        restores = sum(r[2] for r in group_results)
    finally:
        for conn in conns:
            with contextlib.suppress(Exception):
                conn.close()
    return {
        "system": system,
        "verdicts": verdicts,
        "llm_rows": llm_rows,
        "restores": restores,
        "resets": resets,
    }


def _model_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger = sorted(
        {
            (r["step"], r["provider"], r["model_id"], r["prompt_version"])
            for r in rows
            if r.get("step")
        }
    )
    return [
        {"step": s, "provider": p, "model_id": m, "prompt_version": v}
        for s, p, m, v in ledger
    ]


async def _run_all(
    systems: list[str],
    runs: int,
    dbname: str,
    cases: list[Case],
    driver: Driver,
) -> list[dict[str, Any]]:
    """Proposed x`runs`, baseline x1 (D4), sequentially on the one clone."""
    results: list[dict[str, Any]] = []
    for system in systems:
        for _ in range(runs if system == "proposed" else 1):
            results.append(await _run_system(system, dbname, cases, driver))
    return results


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
    driver_name: str = "scripted",
    run_id: str | None = None,
    cases_filter: list[str] | None = None,
    runs: int = 1,
    nlu: str = "off",
) -> str:
    """Play `suite` on `system` (`proposed`, `baseline` or `both`); returns the folder name.

    `runs` repeats only the proposed system (D4). `nlu` is `off`, `smoke` or `suite` (D12).
    `cases_filter` keeps only cases whose `seed_id` starts with one of the prefixes.
    `driver_name` is recorded in `meta.json` (D15); it does not select the driver itself,
    `driver` does — `__main__` keeps the two in sync.
    """
    # First, before loading, linting or cloning: held-out stays frozen (R9, D3).
    if (reason := heldout_refusal(suite)) is not None:
        raise HeldoutRefusedError(reason)
    systems = list(SYSTEMS) if system == "both" else [system]
    if any(s not in SYSTEMS for s in systems):
        raise ValueError(f"system must be one of {SYSTEMS} or 'both': {system!r}")
    if runs < 1:
        raise ValueError(f"runs must be >= 1: {runs}")
    if nlu not in ("off", "smoke", "suite"):
        raise ValueError(f"nlu must be off, smoke or suite: {nlu!r}")
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
    run_id = run_id or _folder_name(suite)
    play = driver or run_case

    # One clone per invocation (D10); the name is the folder name with `-` -> `_`.
    dbname, clone_seconds = clone.create(run_id.replace("-", "_").lower())
    try:
        results = asyncio.run(_run_all(systems, runs, dbname, cases, play))
    finally:
        clone.drop(dbname)

    nlu_result: dict[str, Any] | None = None
    nlu_ledger: list[dict[str, Any]] = []
    nlu_section: list[str] | None = None
    if nlu != "off":
        # Lazy: it imports `app`, which the runner itself never does.
        from eval.harness import nlu_eval

        nlu_result, nlu_ledger = asyncio.run(nlu_eval.compare(nlu, cases))
        nlu_section = nlu_eval.render(nlu_result)

    out = REPORTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    verdicts = [v for r in results for v in r["verdicts"]]
    _write_jsonl(out / "results.jsonl", verdicts)
    # The NLU rows go in before the PII scan reads the file (D20).
    llm_rows = [row for r in results for row in r["llm_rows"]] + nlu_ledger
    _write_jsonl(out / "llm_calls.jsonl", llm_rows)
    pii_hits = _pii_scan(run_id)

    by_system: dict[str, list[list[dict[str, Any]]]] = {}
    for r in results:
        by_system.setdefault(r["system"], []).append(r["verdicts"])
    meta = {
        "run_id": run_id,
        "label": label_for(driver_name),
        "git_sha": _git_sha(),
        "dirty": _dirty(),
        "system": system,
        "suite": suite,
        "cases_filter": ",".join(cases_filter) if cases_filter else None,
        "suite_hash": _sha256_files(list(suite_dir.glob("*.yaml"))),
        "policy_hash": _sha256_files(list(POLICIES.glob("*.yaml"))),
        "started": started.isoformat(),
        "finished": datetime.now(UTC).isoformat(),
        "runs": runs,
        "provider": sorted({m["provider"] for m in _model_ledger(llm_rows)}),
        "clone_strategy": "FILE_COPY",
        "clone_seconds": round(clone_seconds, 1),
        "resets": sum(r["resets"] for r in results),
        # Any diff aborts the run, so a finished run has none.
        "reset_diffs": 0,
        "models": {
            s: _model_ledger([row for r in results if r["system"] == s for row in r["llm_rows"]])
            for s in by_system
        },
        "restore_count": sum(r["restores"] for r in results),
        "restore_diffs": 0,
        "pii_hits": pii_hits,
        "driver": driver_name,
        "nlu": (
            {
                "source": nlu,
                "n": nlu_result["n"],
                "models": [m for m in nlu_result["systems"] if m != "keyword_nlu"],
            }
            if nlu_result
            else None
        ),
    }
    write_report(
        out,
        by_system,
        meta,
        nlu=nlu_result,
        nlu_section=nlu_section,
    )
    return run_id

