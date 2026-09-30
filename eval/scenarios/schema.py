"""The B2 scenario-file contract (spec `d5-b-decline-explainer-test-sets.md`
"Contracts" -> "B2: scenario file", D8-D10): one YAML per seed under
`eval/scenarios/<suite>/<seed_id>.yaml`, with the seed's labels once and its
paraphrase variants flattened into `cases:`. `SeedFile`/`CaseVariant` mirror
the file's own two levels; `Case` is what every consumer (the driver, A3,
the mix report) actually iterates over -- the seed fields duplicated onto
each variant so a case is self-contained (D8).

`load_dir` is the only way anything in this repo reads a scenario directory:
it validates each file through `SeedFile`, flattens it, and checks the two
things a lone Pydantic model can't (D9/D10 give it a raised `ScenarioError`,
not a crash, for a human/CI to read):
- the file's stem matches its own `seed_id` (so a copy-pasted file can't
  silently answer to the wrong id), and
- `case_id` is unique across the whole directory and matches
  `<seed_id>.s` for the seed or `<seed_id>.p<n>` for a paraphrase (D16).

A turn's own "exactly one of say/confirm/cancel/otp/select, `paraphrase`
only next to `say`" rule (D15) is `Turn`'s own model validator, so it fires
for every construction path (YAML load, a test building a `Case` by hand,
T2's paraphrase script appending a case) and not just this loader's.
"""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "Case",
    "CaseVariant",
    "DbPatch",
    "DbStateAssertion",
    "LabelsBlock",
    "ScenarioError",
    "SeedFile",
    "SetupBlock",
    "Turn",
    "load_dir",
]

# `05` §2, in that order (the mix report reads categories in this order too).
Category = Literal[
    "normal_resolution",
    "ambiguous",
    "unsupported",
    "human_required",
    "bad_data",
    "expired_session",
    "unauthorized",
    "injection",
    "tool_failure",
    "multilingual",
]

LanguageVariant = Literal["es-MX", "es-CO", "es-AR", "pt-BR", "mixed"]
ExpectedLanguage = Literal["es", "pt"]

# D10: pinned now; the driver treats any of these as `not_runnable` until D6
# (`07` D6-B3) lands.
Fault = Literal["bedrock_timeout", "cards_write_error", "readback_mismatch"]

_CASE_ID_SUFFIX = re.compile(r"\.(s|p\d+)$")


class ScenarioError(Exception):
    """A scenario file or directory doesn't satisfy the B2 contract (bad
    stem/`seed_id`, a duplicate or malformed `case_id`, or a `SeedFile`/
    `CaseVariant`/`Turn` that fails its own Pydantic validation)."""


class DbStateAssertion(BaseModel):
    """One `expected_db_state` row-assertion (D9). Exactly one of `expect`
    (an in-place check) or `count` (a row-count check) -- A3 compiles this
    into parameterized SQL against a table it allowlists; this model only
    pins the shape."""

    model_config = ConfigDict(extra="forbid")

    table: str
    where: dict[str, Any]
    expect: dict[str, Any] | None = None
    count: int | None = None

    @model_validator(mode="after")
    def _exactly_one_check(self) -> "DbStateAssertion":
        if (self.expect is None) == (self.count is None):
            raise ValueError("expected_db_state item needs exactly one of expect or count")
        return self


class DbPatch(BaseModel):
    """One `setup.db_patches` row-patch (D10). Applied by A3's runner on the
    DB clone, never by this driver."""

    model_config = ConfigDict(extra="forbid")

    table: str
    where: dict[str, Any]
    set: dict[str, Any]


class SetupBlock(BaseModel):
    """`setup:` block (D10). Only a non-empty `faults` makes the driver
    return `ended_by: not_runnable` with zero HTTP calls -- `db_patches` is
    A3-only. `expire_session_before_turn` is a 0-based index, the same one
    `enumerate(case.turns)`/`TurnRecord.index` use: the driver drops the
    session cookies right before that turn and replays it per D8/D9 (a set
    value is played, not skipped)."""

    model_config = ConfigDict(extra="forbid")

    faults: list[Fault] = Field(default_factory=list)
    expire_session_before_turn: int | None = None
    db_patches: list[DbPatch] = Field(default_factory=list)


class LabelsBlock(BaseModel):
    """`labels:` block (`05` §3). Field names verbatim from the spec's YAML
    block; A3 owns turning these into pass/fail checks against a
    `Transcript` and the DB clone."""

    model_config = ConfigDict(extra="forbid")

    expected_intents: list[str]
    expected_outcome: str = Field(pattern=r"^(resolved|clarified|abstained|handoff:.+)$")
    required_tools: list[str]
    forbidden_tools: list[str]
    expected_db_state: list[DbStateAssertion] = Field(default_factory=list)
    required_handoff_fields: list[str] = Field(default_factory=list)
    eligible_for_automation: bool


class Turn(BaseModel):
    """One scripted turn. Exactly one of `say`/`confirm`/`cancel`/`otp`/
    `select` (D15); `paraphrase: false` (opt out of the paraphrase script,
    T2) is only meaningful next to `say`."""

    model_config = ConfigDict(extra="forbid")

    say: str | None = None
    confirm: bool | None = None
    cancel: bool | None = None
    otp: bool | None = None
    select: list[str] | None = None
    paraphrase: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_action(self) -> "Turn":
        actions = (self.say, self.confirm, self.cancel, self.otp, self.select)
        if sum(action is not None for action in actions) != 1:
            raise ValueError("a turn must set exactly one of say/confirm/cancel/otp/select")
        if self.paraphrase is not None and self.say is None:
            raise ValueError("paraphrase is only allowed alongside `say`")
        return self


class CaseVariant(BaseModel):
    """One `cases:` entry: a seed case (`source: seed`) or a paraphrase of
    it (D16), sharing the seed's `labels`/`setup`/persona."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    language_variant: LanguageVariant
    expected_language: ExpectedLanguage
    source: str = Field(pattern=r"^(seed|paraphrase:.+:.+)$")
    turns: list[Turn]
    reviewer: str | None = None
    reviewed_at: str | None = None


class SeedFile(BaseModel):
    """One `eval/scenarios/<suite>/<seed_id>.yaml` file, as written on disk:
    the seed's own fields plus its `cases:` variants, unflattened."""

    model_config = ConfigDict(extra="forbid")

    seed_id: str
    intent: str
    category: Category
    persona: str
    goal: str
    fact_sheet: dict[str, Any] = Field(default_factory=dict)
    setup: SetupBlock
    labels: LabelsBlock
    cases: list[CaseVariant]


class Case(BaseModel):
    """A `SeedFile` flattened with one of its `CaseVariant`s (D8): what
    `load_dir` returns, and what the driver, the mix report and A3 all
    iterate over. Self-contained -- no caller needs to reach back into the
    seed file for a label or the persona."""

    model_config = ConfigDict(extra="forbid")

    seed_id: str
    intent: str
    category: Category
    persona: str
    goal: str
    fact_sheet: dict[str, Any]
    setup: SetupBlock
    labels: LabelsBlock
    case_id: str
    language_variant: LanguageVariant
    expected_language: ExpectedLanguage
    source: str
    turns: list[Turn]
    reviewer: str | None
    reviewed_at: str | None


def _flatten(seed: SeedFile, variant: CaseVariant) -> Case:
    return Case(
        seed_id=seed.seed_id,
        intent=seed.intent,
        category=seed.category,
        persona=seed.persona,
        goal=seed.goal,
        fact_sheet=seed.fact_sheet,
        setup=seed.setup,
        labels=seed.labels,
        case_id=variant.case_id,
        language_variant=variant.language_variant,
        expected_language=variant.expected_language,
        source=variant.source,
        turns=variant.turns,
        reviewer=variant.reviewer,
        reviewed_at=variant.reviewed_at,
    )


def load_dir(path: Path) -> list[Case]:
    """Every `Case` in `path`'s `*.yaml` files (sorted by filename, for a
    deterministic order), or `[]` if `path` is missing or has no scenario
    files. Raises `ScenarioError` -- never lets a `pydantic.ValidationError`
    or a `yaml` error escape -- for a file that fails the B2 contract."""

    if not path.is_dir():
        return []

    cases: list[Case] = []
    seen_case_ids: set[str] = set()

    for file_path in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        try:
            seed = SeedFile.model_validate(raw)
        except ValidationError as exc:
            raise ScenarioError(f"{file_path.name}: {exc}") from exc

        if seed.seed_id != file_path.stem:
            raise ScenarioError(
                f"{file_path.name}: seed_id {seed.seed_id!r} does not match the file stem"
            )

        for variant in seed.cases:
            if variant.case_id in seen_case_ids:
                raise ScenarioError(f"{file_path.name}: duplicate case_id {variant.case_id!r}")
            seen_case_ids.add(variant.case_id)

            match = _CASE_ID_SUFFIX.search(variant.case_id)
            if match is None or variant.case_id[: match.start()] != seed.seed_id:
                raise ScenarioError(
                    f"{file_path.name}: case_id {variant.case_id!r} must be "
                    f"'{seed.seed_id}.s' or '{seed.seed_id}.p<n>'"
                )

            cases.append(_flatten(seed, variant))

    return cases
