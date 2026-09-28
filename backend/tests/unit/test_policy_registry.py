"""D1/A1: the combined policy registry fails startup on a header-less file,
and its hash is stable across a clean reload and moves on any byte change.
No FakeBank, no LLM."""

import shutil
from pathlib import Path

import pytest

from app.domains.policy.registry import PolicyLoadError, load_policies

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_POLICIES_DIR = _REPO_ROOT / "policies"


def _copy_real_policies(target: Path) -> None:
    for path in _REAL_POLICIES_DIR.glob("*.yaml"):
        shutil.copy(path, target / path.name)


def test_headerless_file_fails_startup(tmp_path: Path) -> None:
    _copy_real_policies(tmp_path)

    victim = tmp_path / "escalation.yaml"
    text = victim.read_text(encoding="utf-8")
    victim.write_text(
        "\n".join(line for line in text.splitlines() if not line.startswith("provenance")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PolicyLoadError, match=r"escalation\.yaml"):
        load_policies(tmp_path)


def test_hash_stable_and_moves_on_a_byte_change(tmp_path: Path) -> None:
    _copy_real_policies(tmp_path)

    first = load_policies(tmp_path)
    second = load_policies(tmp_path)
    assert first.hash == second.hash
    assert first.hash.startswith("sha256:")

    victim = tmp_path / "min_payment.yaml"
    victim.write_text(victim.read_text(encoding="utf-8") + "# one extra byte\n", encoding="utf-8")

    changed = load_policies(tmp_path)
    assert changed.hash != first.hash
