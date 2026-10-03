"""CLI: `python -m eval.harness --suite dev --system both` (`make eval`)."""

import argparse
import sys
from pathlib import Path
from typing import get_args

_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    # See `eval/simulator/simulator.py`: `eval` cannot `import app...` without this.
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.config import Fault  # noqa: E402
from eval.harness.runner import HeldoutRefusedError, heldout_refusal, run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.harness", description="Run an eval suite (D13).")
    ap.add_argument("--suite", required=True, help="directory name under eval/scenarios/, e.g. dev")
    ap.add_argument("--system", default="both", choices=["proposed", "baseline", "both"])
    ap.add_argument(
        "--cases",
        default=None,
        metavar="PREFIX[,PREFIX...]",
        help="keep only cases whose seed_id starts with a prefix, e.g. a-",
    )
    ap.add_argument(
        "--driver",
        default="scripted",
        choices=["scripted", "simulator"],
        help="scripted (default) or the goal-driven LLM simulator (D6-B)",
    )
    ap.add_argument(
        "--runs",
        type=int,
        default=1,
        help="repeat the proposed system N times (baseline runs once)",
    )
    ap.add_argument(
        "--nlu",
        default="off",
        choices=["off", "smoke", "suite"],
        help="add the NLU model comparison on the smoke set or the suite's items",
    )
    ap.add_argument(
        "--faults",
        default=None,
        metavar="FAULT[,FAULT...]",
        help="inject these faults into every case, unioned with its setup.faults",
    )
    args = ap.parse_args(argv)
    if (reason := heldout_refusal(args.suite)) is not None:
        # One line and exit 2, before anything loads or clones (D3, R9).
        print(reason, file=sys.stderr)
        return 2
    if args.runs < 1:
        ap.error("--runs must be at least 1")
    prefixes = [p for p in (args.cases or "").split(",") if p] or None
    if args.cases is not None and prefixes is None:
        ap.error("--cases needs at least one non-empty prefix")
    faults = frozenset(f for f in (args.faults or "").split(",") if f)
    if unknown := sorted(faults - set(get_args(Fault))):
        ap.error(f"unknown --faults {','.join(unknown)}; known: {', '.join(get_args(Fault))}")
    driver = None
    if args.driver == "simulator":
        # Imported only on this branch: scripted runs never need the simulator's
        # LLM dependency, and it does not exist yet on every branch that builds this CLI.
        from eval.simulator import run_case_simulated

        driver = run_case_simulated
    try:
        run_id = run(
            args.suite,
            args.system,
            driver=driver,
            driver_name=args.driver,
            cases_filter=prefixes,
            runs=args.runs,
            nlu=args.nlu,
            faults=faults,
        )
    except HeldoutRefusedError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError as exc:
        # An empty selection is a usage error, reported before any clone exists.
        ap.error(str(exc))
    print(f"report: eval/reports/{run_id}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
