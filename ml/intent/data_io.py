"""Training-data contract for the learned intent classifier (spec D19).

One YAML file per (locale, class) under `ml/intent/data/`. This module is the
only reader and writer of those files, so generation, training and the check
share one schema. Later `ml` modules import `app.*` through the `sys.path`
insert below, the same pattern `eval/harness/nlu_eval.py` uses.
"""

import hashlib
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = _REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    # `ml` cannot `import app...` without this (see `eval/harness/nlu_eval.py`).
    sys.path.insert(0, str(BACKEND_ROOT))

__all__ = [
    "BACKEND_ROOT",
    "LOCALES",
    "SLOT_MIX",
    "DataFile",
    "DataItem",
    "accepted_items",
    "data_sha256",
    "load_files",
    "write_file",
]

LOCALES = ("es-mx", "es-co", "es-ar", "pt-br")
# Variety slots per cell of 10 families (D19, human OQ5): same mix in every cell.
SLOT_MIX = {
    "plain": 2,
    "regional": 2,
    "typo_informal": 2,
    "hard_negative": 2,
    "negation": 1,
    "short_answer": 1,
}

Slot = Literal[
    "plain", "regional", "typo_informal", "negation", "hard_negative", "short_answer", "card_type"
]


class DataItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    intents: list[str]  # [] for a scope class
    status: Literal["clear", "out_of_scope", "out_of_market"]
    topic: str | None = None  # set for scope classes
    family: str
    slot: Slot
    origin: Literal["seed", "paraphrase"]
    generator: str
    accepted: bool | None = None  # None = not audited yet


class DataFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance: str
    version: int
    locale: Literal["es-mx", "es-co", "es-ar", "pt-br"]
    class_: str = ""
    items: list[DataItem]


def _parse(raw: dict[str, object]) -> DataFile:
    # `class` is a Python keyword, so the model stores it as `class_`.
    data = dict(raw)
    data["class_"] = data.pop("class")
    return DataFile.model_validate(data)


def load_files(data_dir: Path) -> list[DataFile]:
    """Every `<locale>/<class>.yaml` under `data_dir`, sorted by locale then class."""
    files = [_parse(yaml.safe_load(p.read_text("utf-8"))) for p in Path(data_dir).glob("*/*.yaml")]
    return sorted(files, key=lambda f: (f.locale, f.class_))


def accepted_items(files: list[DataFile]) -> list[DataItem]:
    return [i for f in files for i in f.items if i.accepted is True]


def data_sha256(data_dir: Path) -> str:
    """sha256 over the bytes of the sorted data files (locale/class order)."""
    digest = hashlib.sha256()
    for path in sorted(Path(data_dir).glob("*/*.yaml"), key=lambda p: (p.parent.name, p.name)):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def write_file(path: Path, file: DataFile) -> None:
    payload = file.model_dump(mode="json")
    payload["class"] = payload.pop("class_")
    ordered = {k: payload[k] for k in ("provenance", "version", "locale", "class", "items")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
