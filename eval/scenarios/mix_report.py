"""B3 mix report (spec "Contracts" -> "B3: tooling", D18): prints case
counts/shares for one scenario suite and checks them against
`eval/scenarios/mix_targets.yaml`. The suite (`dev` or `heldout`) is read
from the directory's own basename, so both `_staging/heldout/` (pre-freeze)
and the frozen `heldout/` count as suite `heldout` (plan §"Mix targets").

`make eval-mix DIR=<dir>` runs the single-suite report and exits 1 on any
miss. `--dev <dir> --heldout <dir>` additionally checks the D17 split: no
`seed_id` or `persona` shared between the two suites, and every persona's
`split` (`eval/personas.yaml`) matches the suite it's used in.

`freeze.py`'s default `mix_check` calls `mix_report`/`check_targets` here
directly on `_staging/heldout/`, so this module stays importable without a
running stack -- it only reads YAML off disk through `schema.load_dir`.
"""

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, get_args

import yaml

from eval.scenarios.schema import Case, Category, load_dir

__all__ = [
    "check_overlap",
    "check_targets",
    "load_targets",
    "mix_report",
    "print_report",
    "suite_from_dir",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TARGETS = Path(__file__).resolve().parent / "mix_targets.yaml"
_PERSONAS_FILE = _REPO_ROOT / "eval" / "personas.yaml"
_LANGUAGE_VARIANTS = ("es-MX", "es-CO", "es-AR", "pt-BR", "mixed")
_ES_VARIANTS = ("es-MX", "es-CO", "es-AR")
_LANGUAGES = ("es", "pt")


def suite_from_dir(path: Path) -> str:
    """The suite a directory names: its own basename, which must be `dev`
    or `heldout` (matches both `_staging/heldout` and the frozen
    `heldout/`)."""

    if path.name not in ("dev", "heldout"):
        raise ValueError(f"{path}: directory name must be 'dev' or 'heldout' to name a suite")
    return path.name


def load_targets(path: Path = _DEFAULT_TARGETS) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw


def mix_report(cases: list[Case]) -> dict[str, Any]:
    """Counts and shares by language variant, category and
    category x expected_language, over `cases`."""

    total = len(cases)
    variant_counts = Counter(case.language_variant for case in cases)
    category_counts = Counter(case.category for case in cases)
    category_language_counts = Counter((case.category, case.expected_language) for case in cases)

    variant_shares = {
        variant: (variant_counts.get(variant, 0) / total * 100 if total else 0.0)
        for variant in _LANGUAGE_VARIANTS
    }
    es_total_share = (
        sum(variant_counts.get(variant, 0) for variant in _ES_VARIANTS) / total * 100
        if total
        else 0.0
    )

    return {
        "total": total,
        "variant_counts": dict(variant_counts),
        "variant_shares": variant_shares,
        "es_total_share": es_total_share,
        "category_counts": dict(category_counts),
        "category_language_counts": {
            f"{category}:{language}": count
            for (category, language), count in category_language_counts.items()
        },
    }


def print_report(report: dict[str, Any], suite: str) -> None:
    print(f"suite: {suite}")
    print(f"total: {report['total']}")
    print("language_variant shares:")
    for variant in _LANGUAGE_VARIANTS:
        count = report["variant_counts"].get(variant, 0)
        share = report["variant_shares"].get(variant, 0.0)
        print(f"  {variant}: {count} ({share:.1f}%)")
    print(f"  es total: {report['es_total_share']:.1f}%")
    print("category counts:")
    for category in get_args(Category):
        print(f"  {category}: {report['category_counts'].get(category, 0)}")
    print("category x expected_language:")
    for category in get_args(Category):
        for language in _LANGUAGES:
            key = f"{category}:{language}"
            print(f"  {key}: {report['category_language_counts'].get(key, 0)}")


def check_targets(report: dict[str, Any], suite: str, targets: dict[str, Any]) -> list[str]:
    """Every `mix_targets.yaml` miss for `report`'s suite, as human-readable
    strings. Empty means the suite hits its targets."""

    misses: list[str] = []

    tolerance = targets["language_variant_shares"]["tolerance_pp"]
    for variant in _LANGUAGE_VARIANTS:
        target_pct = targets["language_variant_shares"][variant]
        actual = report["variant_shares"].get(variant, 0.0)
        if abs(actual - target_pct) > tolerance:
            misses.append(f"{variant} share {actual:.1f}% outside {target_pct}% +/-{tolerance}pp")

    es_target = targets["es_total_share"]
    es_tolerance = targets["es_total_tolerance_pp"]
    if abs(report["es_total_share"] - es_target) > es_tolerance:
        misses.append(
            f"es total share {report['es_total_share']:.1f}% outside "
            f"{es_target}% +/-{es_tolerance}pp"
        )

    for category in targets["categories"]:
        for language in _LANGUAGES:
            key = f"{category}:{language}"
            if report["category_language_counts"].get(key, 0) < 1:
                misses.append(f"category {category!r} has no {language} case")

    size = targets["suite_size"][suite]
    if not (size["min"] <= report["total"] <= size["max"]):
        misses.append(
            f"{suite} suite size {report['total']} outside [{size['min']}, {size['max']}]"
        )

    if suite == "heldout":
        min_per_category = targets["heldout_min_per_category"]
        for category in targets["categories"]:
            count = report["category_counts"].get(category, 0)
            if count < min_per_category:
                misses.append(
                    f"category {category!r} has {count} heldout cases, needs >= {min_per_category}"
                )

    return misses


def _persona_splits() -> dict[str, str | None]:
    if not _PERSONAS_FILE.exists():
        return {}
    raw: dict[str, Any] = yaml.safe_load(_PERSONAS_FILE.read_text(encoding="utf-8")) or {}
    return {persona["customer_id"]: persona.get("split") for persona in raw.get("personas", [])}


def check_overlap(dev_cases: list[Case], heldout_cases: list[Case]) -> list[str]:
    """D17: dev and held-out share no seed and no persona, and every
    persona's `split` matches the suite its cases are in. Prints
    `shared seeds: N` / `shared personas: N` as a side effect (spec
    acceptance: "0"/"0" on success)."""

    problems: list[str] = []

    dev_seeds = {case.seed_id for case in dev_cases}
    heldout_seeds = {case.seed_id for case in heldout_cases}
    shared_seeds = dev_seeds & heldout_seeds

    dev_personas = {case.persona for case in dev_cases}
    heldout_personas = {case.persona for case in heldout_cases}
    shared_personas = dev_personas & heldout_personas

    print(f"shared seeds: {len(shared_seeds)}")
    print(f"shared personas: {len(shared_personas)}")

    if shared_seeds:
        problems.append(f"shared seed_ids: {sorted(shared_seeds)}")
    if shared_personas:
        problems.append(f"shared personas: {sorted(shared_personas)}")

    splits = _persona_splits()
    for suite, cases in (("dev", dev_cases), ("heldout", heldout_cases)):
        for case in cases:
            split = splits.get(case.persona)
            if split != suite:
                problems.append(
                    f"{case.case_id}: persona {case.persona!r} has split "
                    f"{split!r}, expected {suite!r}"
                )

    return problems


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.scenarios.mix_report")
    parser.add_argument("dir", nargs="?", type=Path, help="a single suite directory")
    parser.add_argument("--dev", type=Path, help="dev suite directory")
    parser.add_argument("--heldout", type=Path, help="heldout suite directory (staged or frozen)")
    args = parser.parse_args(argv)

    if args.dev is not None or args.heldout is not None:
        if args.dev is None or args.heldout is None:
            parser.error("--dev and --heldout must be given together")

        targets = load_targets()
        dev_cases = load_dir(args.dev)
        heldout_cases = load_dir(args.heldout)

        dev_report = mix_report(dev_cases)
        print_report(dev_report, "dev")
        heldout_report = mix_report(heldout_cases)
        print_report(heldout_report, "heldout")

        misses = check_targets(dev_report, "dev", targets)
        misses += check_targets(heldout_report, "heldout", targets)
        misses += check_overlap(dev_cases, heldout_cases)

        for miss in misses:
            print(f"MISS: {miss}")
        return 1 if misses else 0

    if args.dir is None:
        parser.error("a suite directory is required unless --dev/--heldout are given")

    suite = suite_from_dir(args.dir)
    targets = load_targets()
    report = mix_report(load_dir(args.dir))
    print_report(report, suite)

    misses = check_targets(report, suite, targets)
    for miss in misses:
        print(f"MISS: {miss}")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
