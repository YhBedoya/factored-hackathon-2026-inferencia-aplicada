"""B3 held-out freeze (spec "Contracts" -> "B3: tooling", D11/D12; CLAUDE.md
"Never edit `eval/scenarios/heldout/`"): **only a human runs `freeze`**, via
`make eval-freeze`, after both humans have set `reviewer`/`reviewed_at` on
every `_staging/heldout/*.yaml` case. No agent-controlled code path ever
writes under `eval/scenarios/heldout/`.

`check` is CI's `make eval-freeze-check` step: it re-hashes `heldout/` and
compares against `heldout.lock`, so a single edited byte -- CRLF/LF included,
since `.gitattributes` marks this tree `-text` and the lock hashes raw bytes
(D12) -- fails the build. `check` imports stdlib only, so CI's freeze-check
step depends on nothing this repo could later remove from `app/core/llm`'s
dependency set; `freeze` (human-run, never CI) is the only function that
reaches into `eval.scenarios.schema`/`mix_report`, and only inside its own
call, not at module import time.
"""

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

__all__ = ["FreezeRefused", "check", "freeze"]

_LOCK_NAME = "heldout.lock"
_ALGORITHM = "sha256"


class FreezeRefused(Exception):
    """`freeze` refuses: `heldout/`/the lock already exists, a staging case
    is missing `reviewer`/`reviewed_at`, or the mix report fails."""


def _staging_files(root: Path) -> list[Path]:
    staging = root / "_staging" / "heldout"
    return sorted(staging.glob("*.yaml")) if staging.is_dir() else []


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compute_total(files: dict[str, str]) -> str:
    """sha256 over `name + "\\0" + hex + "\\n"` for each file, sorted by
    name (spec "Contracts" -> "B3: tooling", `heldout.lock`)."""

    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(f"{name}\0{files[name]}\n".encode())
    return digest.hexdigest()


def _default_mix_check(root: Path) -> bool:
    """The staging heldout dir hits `mix_targets.yaml` (D18). Imported here,
    not at module level, so `check` (CI's path) never needs `pydantic`/
    `pyyaml` importable."""

    from eval.scenarios.mix_report import check_targets, load_targets, mix_report
    from eval.scenarios.schema import load_dir

    cases = load_dir(root / "_staging" / "heldout")
    targets = load_targets(root / "mix_targets.yaml")
    return not check_targets(mix_report(cases), "heldout", targets)


def freeze(root: Path, *, mix_check: Callable[[Path], bool] = _default_mix_check) -> None:
    """Moves `_staging/heldout/*.yaml` into `heldout/` and writes
    `heldout.lock`. Refuses, in order, if: `heldout/` or the lock already
    exists; a staging case has a null `reviewer`/`reviewed_at`; `mix_check`
    fails."""

    from eval.scenarios.schema import load_dir

    heldout_dir = root / "heldout"
    lock_path = root / _LOCK_NAME

    if heldout_dir.exists() or lock_path.exists():
        raise FreezeRefused(f"{heldout_dir} or {lock_path} already exists")

    for case in load_dir(root / "_staging" / "heldout"):
        if case.reviewer is None or case.reviewed_at is None:
            raise FreezeRefused(f"case {case.case_id!r} is missing reviewer/reviewed_at")

    if not mix_check(root):
        raise FreezeRefused("mix report failed for _staging/heldout")

    staging_files = _staging_files(root)
    heldout_dir.mkdir(parents=True, exist_ok=True)
    for source in staging_files:
        source.rename(heldout_dir / source.name)

    files = {
        path.name: _hash_bytes(path.read_bytes()) for path in sorted(heldout_dir.glob("*.yaml"))
    }
    lock = {"algorithm": _ALGORITHM, "files": files, "total": _compute_total(files)}
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def check(root: Path) -> list[str]:
    """Every mismatch between `heldout/` and `heldout.lock` (spec
    "Contracts" -> "B3: tooling"). Empty means: neither exists (pre-freeze),
    or both exist and match exactly. Imports stdlib only."""

    heldout_dir = root / "heldout"
    lock_path = root / _LOCK_NAME
    heldout_exists = heldout_dir.is_dir()
    lock_exists = lock_path.is_file()

    if not heldout_exists and not lock_exists:
        return []
    if heldout_exists != lock_exists:
        missing = "heldout.lock" if heldout_exists else "heldout/"
        return [f"{missing} is missing while the other exists"]

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_files: dict[str, str] = lock.get("files", {})
    problems: list[str] = []

    disk_files = {path.name: path for path in heldout_dir.glob("*.yaml")}

    for name in sorted(set(disk_files) - set(lock_files)):
        problems.append(f"added: {name}")
    for name in sorted(set(lock_files) - set(disk_files)):
        problems.append(f"removed: {name}")

    for name in sorted(set(disk_files) & set(lock_files)):
        actual = _hash_bytes(disk_files[name].read_bytes())
        if actual != lock_files[name]:
            problems.append(f"changed: {name}")

    if lock.get("total") != _compute_total(lock_files):
        problems.append("total mismatch")

    return problems


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.scenarios.freeze")
    parser.add_argument("action", choices=["freeze", "check"])
    parser.add_argument("--root", type=Path, default=Path("eval/scenarios"))
    args = parser.parse_args(argv)

    if args.action == "check":
        problems = check(args.root)
        for problem in problems:
            print(problem)
        print("freeze-check: FAIL" if problems else "freeze-check: OK")
        return 1 if problems else 0

    try:
        freeze(args.root)
    except FreezeRefused as exc:
        print(f"freeze refused: {exc}")
        return 1
    print("freeze: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
