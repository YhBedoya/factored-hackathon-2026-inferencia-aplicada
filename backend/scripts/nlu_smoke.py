"""Local smoke gate for `nlu@v2` (D18, B4). Not a CI test.

`--dry-run` checks the smoke set and the prompt file with no network call:
every entry's `expected` block parses as an `NLUResult` (so every intent is
one of the closed 26, D18), and `prompts/nlu@v2.md` loads. Without
`--dry-run`, it calls the real NLU through `get_llm_client()` for each of
the 20 messages, prints how many came back matching their label, and flags
any of the 4 end-of-day utterances (`07` D1 step 4) that came back wrong.

Usage: `cd backend && uv run python scripts/nlu_smoke.py [--dry-run]`.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    # `uv run python scripts/nlu_smoke.py` puts `scripts/` on `sys.path`, not
    # `backend/`; add it so `import app...` resolves the same way pytest's
    # `pythonpath = ["."]` does.
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.llm import PromptRef, get_llm_client  # noqa: E402
from app.domains.conversation.nodes import run_nlu  # noqa: E402
from app.domains.conversation.prompts import load_prompt  # noqa: E402
from app.domains.conversation.schemas import NLUResult  # noqa: E402
from app.domains.conversation.state import Pending  # noqa: E402

_REPO_ROOT = _BACKEND_ROOT.parent
_SMOKE_SET = _REPO_ROOT / "eval" / "nlu" / "nlu_v1_smoke.yaml"
_EXPECTED_COUNT = 20
_END_OF_DAY_IDS = {"eod-1", "eod-2", "eod-3", "eod-4"}


def _load_entries() -> list[dict[str, Any]]:
    raw = yaml.safe_load(_SMOKE_SET.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{_SMOKE_SET} must be a YAML list of entries")
    return cast(list[dict[str, Any]], raw)


def _diff(actual: NLUResult, expected: dict[str, Any]) -> list[str]:
    """Field-by-field mismatches between `actual` and one entry's `expected` block."""
    errors: list[str] = []
    if actual.language != expected["language"]:
        errors.append(f"language: got {actual.language!r}, want {expected['language']!r}")
    if actual.intents != expected["intents"]:
        errors.append(f"intents: got {actual.intents!r}, want {expected['intents']!r}")
    if actual.status != expected["status"]:
        errors.append(f"status: got {actual.status!r}, want {expected['status']!r}")
    want_clarification = expected.get("clarification")
    if actual.clarification != want_clarification:
        errors.append(f"clarification: got {actual.clarification!r}, want {want_clarification!r}")
    for key, value in expected.get("slots", {}).items():
        got = getattr(actual.slots, key)
        if got != value:
            errors.append(f"slots.{key}: got {got!r}, want {value!r}")
    return errors


def _run_dry(entries: list[dict[str, Any]]) -> int:
    """Validate every label and the prompt file. No network (`--dry-run`)."""
    load_prompt(PromptRef("nlu", 2))  # raises if the file is missing
    valid = 0
    for entry in entries:
        try:
            NLUResult.model_validate(entry["expected"])
        except Exception as exc:
            print(f"{entry['id']}: invalid label - {exc}")
            continue
        valid += 1
    print(f"{valid}/{_EXPECTED_COUNT} labels valid")
    return 0 if valid == _EXPECTED_COUNT and len(entries) == _EXPECTED_COUNT else 1


async def _run_live(entries: list[dict[str, Any]]) -> int:
    """Call the real NLU per message and compare it against its label."""
    llm = get_llm_client()
    valid = 0
    eod_failures: list[str] = []
    for entry in entries:
        pending = cast(Pending, entry["pending"]) if entry.get("pending") else None
        actual = await run_nlu(llm, entry["text"], pending=pending, country=entry.get("country"))
        errors = _diff(actual, entry["expected"])
        if errors:
            print(f"{entry['id']}: {'; '.join(errors)}")
            if entry["id"] in _END_OF_DAY_IDS:
                eod_failures.append(entry["id"])
        else:
            valid += 1
    print(f"{valid}/{_EXPECTED_COUNT} valid")
    if eod_failures:
        print(f"end-of-day utterances mislabeled: {', '.join(eod_failures)}")
    return 0 if valid == _EXPECTED_COUNT and not eod_failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate labels, no network")
    args = parser.parse_args()

    entries = _load_entries()
    if args.dry_run:
        return _run_dry(entries)
    return asyncio.run(_run_live(entries))


if __name__ == "__main__":
    sys.exit(main())
