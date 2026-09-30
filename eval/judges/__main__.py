"""CLI: `python -m eval.judges sample|judge|agreement` (D14-D17, B4).

Three offline steps, run in order by a human:

1. `sample --run <run_id> --labelers <a>,<b>` builds the 50-item pool from
   one dev/proposed eval run.
2. Both labelers fill in `eval/judges/labels/<labeler>.yaml` by hand (about
   1 h, not part of this CLI).
3. `judge` scores the same items with the `judge` LLM step.
4. `agreement` compares the two and writes `eval/judges/agreement.md`.

Run under the backend uv env from the repo root:
`uv run --project backend python -m eval.judges <command> ...`.
"""

import argparse
import sys
from pathlib import Path

from eval.judges.agreement import agreement
from eval.judges.judge import judge
from eval.judges.sample import sample


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.judges", description="B4 judge tooling.")
    sub = ap.add_subparsers(dest="command", required=True)

    sample_ap = sub.add_parser(
        "sample", help="Build the 50-item judge pool from a dev/proposed eval run."
    )
    sample_ap.add_argument("--run", required=True, help="run id under eval/reports/")
    sample_ap.add_argument("--labelers", required=True, help="two labeler names, comma-separated")
    sample_ap.add_argument("--seed", type=int, default=0)
    sample_ap.add_argument("--n", type=int, default=50)

    judge_ap = sub.add_parser(
        "judge", help="Score eval/judges/items.jsonl with the `judge` LLM step."
    )
    judge_ap.add_argument(
        "--items", default=None, help="items.jsonl path (default: eval/judges/items.jsonl)"
    )

    sub.add_parser("agreement", help="Write eval/judges/agreement.md from the filled-in labels.")

    args = ap.parse_args(argv)

    if args.command == "sample":
        labelers = tuple(name.strip() for name in args.labelers.split(","))
        if len(labelers) != 2 or not all(labelers):
            ap.error("--labelers needs exactly two comma-separated names")
        try:
            sample(args.run, (labelers[0], labelers[1]), seed=args.seed, n=args.n)
        except (ValueError, FileNotFoundError) as exc:
            ap.error(str(exc))
        print("items: eval/judges/items.jsonl")
        return 0

    if args.command == "judge":
        judge(Path(args.items) if args.items else None)
        print("verdicts: eval/judges/judge_verdicts.jsonl")
        return 0

    agreement()
    print("report: eval/judges/agreement.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
