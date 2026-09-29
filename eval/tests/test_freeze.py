"""Test 7 (B3 Done-when): the held-out freeze round-trip on a tmp scenario
root, never the real `eval/scenarios/heldout/` (CLAUDE.md, D11). `mix_check`
is stubbed so this test never needs a real mix -- `mix_report`'s own targets
are covered by `eval.scenarios.mix_report`, not here.
"""

from pathlib import Path

import pytest

from eval.scenarios.freeze import FreezeRefused, check, freeze

_SEED_TEMPLATE = """\
seed_id: {seed_id}
intent: decline_explain
category: normal_resolution
persona: CLI-000000000001
goal: "Entender por que rechazaron su compra"
fact_sheet: {{}}
setup:
  faults: []
  expire_session_before_turn: null
  db_patches: []
labels:
  expected_intents: [decline_explain]
  expected_outcome: resolved
  required_tools: [transactions.search]
  forbidden_tools: []
  expected_db_state: []
  required_handoff_fields: []
  eligible_for_automation: true
cases:
  - case_id: {seed_id}.s
    language_variant: es-MX
    expected_language: es
    source: seed
    turns:
      - say: "por que me rechazaron la compra"
    reviewer: {reviewer}
    reviewed_at: {reviewed_at}
"""


def _write_staging_seed(
    root: Path,
    seed_id: str,
    *,
    reviewer: str | None = "ana",
    reviewed_at: str | None = "2026-09-29",
) -> Path:
    staging = root / "_staging" / "heldout"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / f"{seed_id}.yaml"
    path.write_text(
        _SEED_TEMPLATE.format(
            seed_id=seed_id,
            reviewer="null" if reviewer is None else f'"{reviewer}"',
            reviewed_at="null" if reviewed_at is None else f'"{reviewed_at}"',
        ),
        encoding="utf-8",
    )
    return path


def test_freeze_then_edit_fails_check(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    _write_staging_seed(root, "dec-54-mx-01")

    assert check(root) == []  # pre-freeze: neither heldout/ nor the lock exists

    freeze(root, mix_check=lambda _: True)
    assert check(root) == []  # frozen and untouched

    frozen_file = root / "heldout" / "dec-54-mx-01.yaml"
    original = frozen_file.read_text(encoding="utf-8")
    frozen_file.write_text(
        original[:-1] + ("x" if not original.endswith("x") else "y"), encoding="utf-8"
    )

    problems = check(root)
    assert problems != []
    assert any("changed" in problem for problem in problems)


def test_freeze_refuses_null_reviewer(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    _write_staging_seed(root, "dec-54-mx-01", reviewer=None)

    with pytest.raises(FreezeRefused):
        freeze(root, mix_check=lambda _: True)

    assert not (root / "heldout").exists()
    assert not (root / "heldout.lock").exists()


def test_freeze_refuses_when_heldout_already_exists(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    (root / "heldout").mkdir(parents=True)

    with pytest.raises(FreezeRefused):
        freeze(root, mix_check=lambda _: True)


def test_freeze_refuses_on_failing_mix_check(tmp_path: Path) -> None:
    root = tmp_path / "scenarios"
    _write_staging_seed(root, "dec-54-mx-01")

    with pytest.raises(FreezeRefused):
        freeze(root, mix_check=lambda _: False)
