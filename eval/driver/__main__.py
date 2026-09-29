"""`python -m eval.driver --dir <suite dir> [--case <id>] --base-url <url>
--out <jsonl>`: plays every case `load_dir` finds in `--dir` (or just
`--case`) against `--base-url` and writes one JSON `Transcript` per line to
`--out` (B2 "Done when": "A runs B's scenarios in A3").

Run under the backend uv env from the repo root:
`uv run --project backend python -m eval.driver ...`. `--base-url` has no
default that points at a deployed host -- this only ever targets the local
dev stack (`make up`, nginx on `http://localhost`); the public-URL deploy is
postponed to the end of D5 (plan, human decision).

The OTP code for `otp` turns comes from `--otp-code`, defaulting to the
`DEMO_OTP_CODE` environment variable (never printed, never logged -- same
rule `chat_api.py` follows for the same value).

An unexpected exception from one case (a connection drop, a bug in this
driver, anything `run_case` itself doesn't already turn into
`ended_by="error"`) is caught per case, not let through: it's recorded as
that case's own `error` transcript, and the batch moves on to the next case.
A whole-directory run must survive one bad case.
"""

import argparse
import asyncio
import os
from pathlib import Path

from eval.driver.driver import Transcript, run_case
from eval.scenarios.schema import Case, load_dir

__all__ = ["main"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.driver",
        description="Scripted HTTP driver: play scenario cases against a running conversation API.",
    )
    parser.add_argument("--dir", required=True, type=Path, help="scenario suite directory")
    parser.add_argument("--case", default=None, help="only run this case_id")
    parser.add_argument(
        "--base-url", required=True, help="local dev stack base URL, e.g. http://localhost"
    )
    parser.add_argument("--out", required=True, type=Path, help="output .jsonl path")
    parser.add_argument(
        "--otp-code",
        default=os.environ.get("DEMO_OTP_CODE", ""),
        help="OTP code for `otp` turns (default: $DEMO_OTP_CODE)",
    )
    return parser.parse_args(argv)


async def _run_one(case: Case, *, base_url: str, otp_code: str) -> Transcript:
    """`run_case`, with any exception it doesn't already turn into a
    `Transcript` itself caught here, so one bad case can't abort `_run_all`'s
    batch (e.g. a dropped connection past `run_case`'s own 60 s watchdog)."""

    try:
        return await run_case(case, base_url=base_url, otp_code=otp_code)
    except Exception as exc:
        return Transcript(
            case_id=case.case_id,
            conversation_id=None,
            turns=[],
            ended_by="error",
            error=f"{type(exc).__name__}: {exc}",
        )


async def _run_all(args: argparse.Namespace) -> None:
    cases = load_dir(args.dir)
    if args.case is not None:
        cases = [case for case in cases if case.case_id == args.case]

    with args.out.open("w", encoding="utf-8") as handle:
        for case in cases:
            transcript = await _run_one(case, base_url=args.base_url, otp_code=args.otp_code)
            handle.write(transcript.model_dump_json())
            handle.write("\n")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(_run_all(args))


if __name__ == "__main__":
    main()
