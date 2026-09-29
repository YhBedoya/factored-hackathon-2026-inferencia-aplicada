"""Test 5 (B2 contract): every scenario file under `eval/scenarios/dev/`
and the held-out side (`_staging/heldout/` pre-freeze, `heldout/` once a
human has run `make eval-freeze`) must parse through `load_dir`, and every
persona a case references must exist in `eval/personas.yaml` with a `split`
matching its suite (D17).

Both directories are empty until T8/T9 (and the human freeze) land, so
`load_dir` returns `[]` and the persona check loops run zero times -- this
passes vacuously today, and becomes a real check the moment seed files
exist. Never writes anywhere, and never touches `eval/scenarios/heldout/`.
"""

from pathlib import Path
from typing import Any

import yaml

from eval.scenarios.schema import Case, load_dir

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_DIR = _REPO_ROOT / "eval" / "scenarios" / "dev"
_HELDOUT_FROZEN_DIR = _REPO_ROOT / "eval" / "scenarios" / "heldout"
_HELDOUT_STAGING_DIR = _REPO_ROOT / "eval" / "scenarios" / "_staging" / "heldout"
_PERSONAS_FILE = _REPO_ROOT / "eval" / "personas.yaml"


def _heldout_dir() -> Path:
    """The frozen dir is authoritative once it exists; before that, the
    staging dir is what's under review (D11)."""

    return _HELDOUT_FROZEN_DIR if _HELDOUT_FROZEN_DIR.is_dir() else _HELDOUT_STAGING_DIR


def _persona_splits() -> dict[str, str | None]:
    if not _PERSONAS_FILE.exists():
        return {}
    raw: dict[str, Any] = (
        yaml.safe_load(_PERSONAS_FILE.read_text(encoding="utf-8")) or {}
    )
    return {
        persona["customer_id"]: persona.get("split")
        for persona in raw.get("personas", [])
    }


def _assert_personas_match_suite(cases: list[Case], suite: str) -> None:
    splits = _persona_splits()
    for case in cases:
        assert case.persona in splits, (
            f"{case.case_id}: unknown persona {case.persona!r}"
        )
        assert splits[case.persona] == suite, (
            f"{case.case_id}: persona {case.persona!r} has split "
            f"{splits[case.persona]!r}, expected {suite!r}"
        )


def test_dev_scenarios_are_valid() -> None:
    _assert_personas_match_suite(load_dir(_DEV_DIR), "dev")


def test_heldout_scenarios_are_valid() -> None:
    _assert_personas_match_suite(load_dir(_heldout_dir()), "heldout")
