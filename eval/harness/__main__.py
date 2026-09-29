"""CLI: `python -m eval.harness --suite dev --system both` (`make eval`)."""

import argparse
import sys

from eval.harness.runner import run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval.harness", description="Run an eval suite (D13)."
    )
    ap.add_argument(
        "--suite", required=True, help="directory name under eval/scenarios/, e.g. dev"
    )
    ap.add_argument(
        "--system", default="both", choices=["proposed", "baseline", "both"]
    )
    ap.add_argument(
        "--cases",
        default=None,
        metavar="PREFIX[,PREFIX...]",
        help="keep only cases whose seed_id starts with a prefix, e.g. a-",
    )
    args = ap.parse_args(argv)
    prefixes = [p for p in (args.cases or "").split(",") if p] or None
    if args.cases is not None and prefixes is None:
        ap.error("--cases needs at least one non-empty prefix")
    try:
        run_id = run(args.suite, args.system, cases_filter=prefixes)
    except ValueError as exc:
        # An empty selection is a usage error, reported before any clone exists.
        ap.error(str(exc))
    print(f"report: eval/reports/{run_id}/report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
