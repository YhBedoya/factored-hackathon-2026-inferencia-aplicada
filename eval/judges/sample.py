"""B4 judge tooling: sample dev-run replies into a labeling/scoring pool
(spec `d7-b-transactions-traceability-judge.md` §"Contracts" -> "B4: eval",
D15-D16).

`sample(run_id, labelers)` reads one `make eval SUITE=dev SYSTEM=proposed`
run's `transcripts.jsonl` (SA2, `eval/harness/runner.py`), refuses anything
that isn't a dev/proposed run (R9), builds one candidate unit per bot reply
(the turn's joined `message` event texts, with the conversation up to and
including that turn's own customer message as context), masks every text
with that case's persona PII (R5), balances 25 ES / 25 PT and spreads across
intents with a seeded RNG, and writes `items.jsonl`/`items.md` plus the
labeling assignment and two label skeletons (D16).

`app` is not importable from `eval/` without help (state file "Facts
checked against the repo"): this module puts `<repo>/backend` on `sys.path`
before the `app...` import, mirroring `eval/simulator/simulator.py`. It also
re-exports `KnownPii` so the rest of `eval.judges` (and its tests) never
need their own `app.core.pii` import/sys.path dance.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    # See module docstring: `eval` cannot `import app...` without this.
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.pii import KnownPii, find_pii  # noqa: E402

from eval.harness.pii_check import _load_personas_pii  # noqa: E402

__all__ = [
    "JUDGES_DIR",
    "KnownPii",
    "Masker",
    "build_items",
    "mask_text",
    "sample",
]

REPORTS = _REPO_ROOT / "eval" / "reports"
JUDGES_DIR = Path(__file__).resolve().parent
_N_ITEMS = 50
_N_SHARED = 10
_LANGUAGES: tuple[Literal["es", "pt"], ...] = ("es", "pt")


class Masker:
    """Numbers PII tokens per kind, stable for one sampling run: the same
    raw value always gets the same `⟨KIND_n⟩` token (mirrors
    `eval/simulator/simulator.py`'s private `_Masker` -- this module may
    only import `app.core.pii`, not a domain vault, R7/D5)."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def mask(self, text: str, known: KnownPii) -> str:
        out = text
        for match in reversed(find_pii(text, known)):
            token = self._token_for(match.kind, text[match.start : match.end])
            out = f"{out[: match.start]}{token}{out[match.end :]}"
        return out

    def _token_for(self, kind: str, raw: str) -> str:
        for token, value in self._values.items():
            if value == raw and token.startswith(f"⟨{kind}_"):
                return token
        number = 1 + sum(1 for token in self._values if token.startswith(f"⟨{kind}_"))
        token = f"⟨{kind}_{number}⟩"
        self._values[token] = raw
        return token


def mask_text(text: str, known: KnownPii, masker: Masker) -> str:
    """`text` with every match of `known`'s persona PII replaced by a
    numbered token through `masker` (R5)."""
    return masker.mask(text, known)


@dataclass(frozen=True)
class _Candidate:
    case_id: str
    persona: str
    intent: str
    language: Literal["es", "pt"]
    turn_index: int
    context: list[dict[str, str]]
    reply: str


def _customer_text(turn_input: dict[str, Any]) -> str:
    kind = turn_input.get("kind")
    value = turn_input.get("value")
    if kind == "say":
        return str(value)
    if kind == "select":
        ids = ", ".join(value) if isinstance(value, list) else str(value)
        return f"[selects: {ids}]"
    if kind == "otp":
        return "[verification code]"
    if kind == "confirm":
        return "[confirms]"
    return "[cancels]"


def _bot_text(events: list[dict[str, Any]]) -> str:
    texts = [
        str(event["data"].get("text", ""))
        for event in events
        if event.get("event") == "message" and event.get("data", {}).get("role") == "bot"
    ]
    return " ".join(text for text in texts if text)


def _candidates_from_transcript(row: dict[str, Any]) -> list[_Candidate]:
    """One candidate per turn with at least one bot `message` event. Context
    is every turn up to and including this one's own customer message (what
    prompted the reply); the reply itself is excluded from its own context."""

    language = row["expected_language"]
    if language not in _LANGUAGES:
        return []
    turns = row["transcript"].get("turns", [])
    out: list[_Candidate] = []
    context: list[dict[str, str]] = []
    for turn in turns:
        context = [*context, {"role": "customer", "text": _customer_text(turn["input"])}]
        reply = _bot_text(turn.get("events", []))
        if reply:
            out.append(
                _Candidate(
                    case_id=row["case_id"],
                    persona=row["persona"],
                    intent=row["intent"],
                    language=language,
                    turn_index=turn["index"],
                    context=context,
                    reply=reply,
                )
            )
            context = [*context, {"role": "bot", "text": reply}]
    return out


def _pick_balanced(
    candidates: list[_Candidate], *, n_per_language: int, rng: random.Random
) -> list[_Candidate]:
    """25/25 ES/PT (D15), round-robining across intents within each language
    so no single intent dominates the pool."""

    chosen: list[_Candidate] = []
    for language in _LANGUAGES:
        by_intent: dict[str, list[_Candidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.language == language:
                by_intent[candidate.intent].append(candidate)
        for group in by_intent.values():
            rng.shuffle(group)
        intents = sorted(by_intent)
        picked: list[_Candidate] = []
        i = 0
        while len(picked) < n_per_language and intents:
            intent = intents[i % len(intents)]
            group = by_intent[intent]
            if not group:
                intents.remove(intent)
                if not intents:
                    break
                continue
            picked.append(group.pop())
            i += 1
        chosen.extend(picked)
    return chosen


def _load_meta(run_id: str) -> dict[str, Any]:
    return json.loads((REPORTS / run_id / "meta.json").read_text(encoding="utf-8"))


def _load_transcripts(run_id: str) -> list[dict[str, Any]]:
    """Only `system == "proposed"` rows of the first run (R9: the judge scores the
    proposed system's replies, never the baseline's). With `RUNS=N` the other
    proposed runs replay the same cases, so they are left out to keep items distinct."""

    rows: list[dict[str, Any]] = []
    with (REPORTS / run_id / "transcripts.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return [row for row in rows if row.get("system") == "proposed" and row.get("run", 1) == 1]


def _persona_pii_map(persona_ids: list[str]) -> dict[str, dict[str, Any]]:
    """One `_load_personas_pii` call per id.

    That helper's query has no `ORDER BY` and doesn't select `customer_id`
    (it only needs an unordered pool for `pii_check`'s aggregate scan), so a
    single batched call can't be matched back to a persona by position --
    Postgres doesn't guarantee `= ANY(...)` result order. A lone-id call
    sidesteps that: at most one `bank.customers` row per id, so there is
    nothing to line up.
    """

    out: dict[str, dict[str, Any]] = {}
    for persona_id in persona_ids:
        rows = _load_personas_pii([persona_id])
        if rows:
            out[persona_id] = rows[0]
    return out


def build_items(run_id: str, *, seed: int = 0, n: int = _N_ITEMS) -> list[dict[str, Any]]:
    """The masked item pool for `run_id` (D15). Raises `ValueError` for
    anything but a dev/proposed run (R9)."""

    meta = _load_meta(run_id)
    if meta.get("suite") != "dev" or "proposed" not in str(meta.get("system", "")):
        raise ValueError(
            f"run {run_id!r} is not a dev/proposed run "
            f"(suite={meta.get('suite')!r}, system={meta.get('system')!r}); refusing (R9)"
        )

    rows = _load_transcripts(run_id)
    candidates = [c for row in rows for c in _candidates_from_transcript(row)]

    rng = random.Random(seed)
    chosen = _pick_balanced(candidates, n_per_language=n // len(_LANGUAGES), rng=rng)
    rng.shuffle(chosen)

    persona_by_case = {row["case_id"]: row["persona"] for row in rows}
    personas_pii = _persona_pii_map(sorted({row["persona"] for row in rows}))

    masker = Masker()
    items: list[dict[str, Any]] = []
    for i, candidate in enumerate(chosen, start=1):
        persona_row = personas_pii.get(persona_by_case[candidate.case_id], {})
        name_fields = (persona_row.get("first_name"), persona_row.get("last_name"))
        known = KnownPii(
            document_number=persona_row.get("document_number"),
            names=tuple(word for word in name_fields if word),
        )
        items.append(
            {
                "item_id": f"J-{i:03d}",
                "run_id": run_id,
                "case_id": candidate.case_id,
                "turn_index": candidate.turn_index,
                "language": candidate.language,
                "intent": candidate.intent,
                "context": [
                    {"role": turn["role"], "text": mask_text(turn["text"], known, masker)}
                    for turn in candidate.context
                ],
                "reply": mask_text(candidate.reply, known, masker),
            }
        )
    return items


def _render_items_md(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Judge items",
        "",
        f"{len(items)} items sampled from a dev/proposed run, masked (R5).",
        "",
    ]
    for item in items:
        lines.append(
            f"## {item['item_id']} -- {item['language']}, {item['intent']}, "
            f"turn {item['turn_index']} (`{item['case_id']}`)"
        )
        lines.append("")
        for turn in item["context"]:
            lines.append(f"- **{turn['role']}**: {turn['text']}")
        lines.append("")
        lines.append(f"**reply**: {item['reply']}")
        lines.append("")
    return "\n".join(lines)


def _assignment(item_ids: list[str], labelers: tuple[str, str]) -> dict[str, Any]:
    """D16: the first 10 items shared, the next 20 to the first labeler, the
    last 20 to the second."""

    first, second = labelers
    shared = item_ids[:_N_SHARED]
    rest = item_ids[_N_SHARED:]
    half = len(rest) // 2
    return {
        "first": first,
        "second": second,
        "shared": shared,
        first: rest[:half],
        second: rest[half:],
    }


def _label_skeleton(
    labeler: str, item_ids: list[str], run_id: str, items_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item_id,
            "run_id": run_id,
            "case_id": items_by_id[item_id]["case_id"],
            "turn_index": items_by_id[item_id]["turn_index"],
            "labeler": labeler,
            "labeled_at": None,
            "grounding": None,
            "tone": None,
            "clarity": None,
            "register": None,
            "overall": None,
        }
        for item_id in item_ids
    ]


def sample(run_id: str, labelers: tuple[str, str], *, seed: int = 0, n: int = _N_ITEMS) -> None:
    """Write `items.jsonl`, `items.md`, `labels/assignment.yaml` and one
    `labels/<labeler>.yaml` skeleton per labeler."""

    items = build_items(run_id, seed=seed, n=n)
    items_by_id = {item["item_id"]: item for item in items}
    item_ids = list(items_by_id)

    (JUDGES_DIR / "items.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
        encoding="utf-8",
    )
    (JUDGES_DIR / "items.md").write_text(_render_items_md(items), encoding="utf-8")

    assignment = _assignment(item_ids, labelers)
    labels_dir = JUDGES_DIR / "labels"
    labels_dir.mkdir(exist_ok=True)
    (labels_dir / "assignment.yaml").write_text(
        yaml.safe_dump(assignment, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for labeler in labelers:
        their_ids = [*assignment["shared"], *assignment[labeler]]
        records = _label_skeleton(labeler, their_ids, run_id, items_by_id)
        (labels_dir / f"{labeler}.yaml").write_text(
            yaml.safe_dump(records, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
