"""Offline NLU comparison (D12-D15): `keyword_nlu` against `run_nlu` per model.

The item set is derived at run time from the selected scenario cases (their
first `say` turn, labelled by the seed) or read from the smoke file as it
stands; no new labeled file exists (D12). `run_nlu` runs in-process through
`get_llm_client(sink=..., model_overrides=...)`, so the R5 guard, R7 pinning
and R11 retries apply unchanged (D15). Only this module imports `app`, via the
simulator's `sys.path` pattern; `runner.py` imports it lazily.
"""

import sys
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    # See `eval/simulator/simulator.py`: `eval` cannot `import app...` without this.
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.llm import LLMCallRecord, LLMClient, get_llm_client  # noqa: E402
from app.domains.conversation.baseline.keyword_nlu import keyword_nlu  # noqa: E402
from app.domains.conversation.nodes import run_nlu  # noqa: E402
from app.domains.conversation.schemas import NLUResult  # noqa: E402
from app.domains.conversation.state import Pending  # noqa: E402

from eval.harness.metrics import LABEL, Rate, percentiles  # noqa: E402
from eval.scenarios.schema import Case  # noqa: E402

__all__ = [
    "NLU_MODELS",
    "NluItem",
    "compare",
    "derive_suite_items",
    "load_smoke_items",
    "render",
    "score",
]

NLU_MODELS = ("claude-sonnet-5-5", "claude-haiku-4-5-20251001")
PERSONAS_PATH = _REPO_ROOT / "eval" / "personas.yaml"
SMOKE_PATH = _REPO_ROOT / "eval" / "nlu" / "nlu_v1_smoke.yaml"
CAVEAT = "Anthropic API; Bedrock serves the same models (ADR-028)"

NluFn = Callable[..., Awaitable[NLUResult]]
ClientFactory = Callable[..., LLMClient]


@dataclass(frozen=True)
class NluItem:
    id: str
    text: str
    country: str | None
    pending: Pending | None
    expected_intents: list[str]
    expected_language: str | None = None
    language_variant: str | None = None
    expected_status: str | None = None  # smoke only: the scenarios carry no status label


def derive_suite_items(cases: Sequence[Case], personas_path: Path) -> list[NluItem]:
    """One item per case: its first `say` turn, labelled by the seed (D12)."""
    raw = yaml.safe_load(personas_path.read_text(encoding="utf-8"))
    country = {p["customer_id"]: p.get("country") for p in raw["personas"]}
    items: list[NluItem] = []
    for case in cases:
        text = next((t.say for t in case.turns if t.say is not None), None)
        if text is None:
            continue
        items.append(
            NluItem(
                id=case.case_id,
                text=text,
                country=country.get(case.persona),
                pending=None,
                expected_intents=list(case.labels.expected_intents),
                expected_language=case.expected_language,
                language_variant=case.language_variant,
            )
        )
    return items


def load_smoke_items(path: Path) -> list[NluItem]:
    """`eval/nlu/nlu_v1_smoke.yaml` as it stands, with its status labels."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    items: list[NluItem] = []
    for e in entries:
        exp = e["expected"]
        lang = exp.get("language")
        items.append(
            NluItem(
                id=e["id"],
                text=e["text"],
                country=e.get("country"),
                pending=e.get("pending") or None,
                expected_intents=list(exp["intents"]),
                expected_language=lang,
                language_variant=None,
                expected_status=exp.get("status"),
            )
        )
    return items


def _macro_prf(gold: list[set[str]], pred: list[set[str]]) -> tuple[float, float, float]:
    """Macro over every intent seen in gold or predictions; a 0/0 term counts as 0."""
    intents = set().union(*gold, *pred)
    if not intents:
        return (0.0, 0.0, 0.0)
    ps, rs, fs = [], [], []
    for intent in intents:
        tp = sum(intent in g and intent in p for g, p in zip(gold, pred, strict=True))
        fp = sum(intent not in g and intent in p for g, p in zip(gold, pred, strict=True))
        fn = sum(intent in g and intent not in p for g, p in zip(gold, pred, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        ps.append(prec)
        rs.append(rec)
        fs.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    n = len(intents)
    return (sum(ps) / n, sum(rs) / n, sum(fs) / n)


def score(items: Sequence[NluItem], predictions: Sequence[NLUResult | None]) -> dict[str, Any]:
    """D13 metrics. A `None` prediction (the call failed) counts as no intents."""
    gold = [set(i.expected_intents) for i in items]
    pred = [set(p.intents) if p else set() for p in predictions]
    exact = [g == p for g, p in zip(gold, pred, strict=True)]
    precision, recall, f1 = _macro_prf(gold, pred)

    multi = [ok for g, ok in zip(gold, exact, strict=True) if len(g) >= 2]
    by_variant: dict[str, list[bool]] = defaultdict(list)
    for item, ok in zip(items, exact, strict=True):
        by_variant[item.language_variant or "unknown"].append(ok)

    status = [
        p.status == i.expected_status
        for i, p in zip(items, predictions, strict=True)
        if i.expected_status is not None and p is not None
    ]
    n_status = sum(i.expected_status is not None for i in items)
    return {
        "n": len(items),
        "failed_calls": sum(p is None for p in predictions),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "exact_set": Rate.of(sum(exact), len(exact)).model_dump(),
        "multi_intent": Rate.of(sum(multi), len(multi)).model_dump(),
        "by_language_variant": {
            v: Rate.of(sum(oks), len(oks)).model_dump() for v, oks in sorted(by_variant.items())
        },
        "status_accuracy": Rate.of(sum(status), n_status).model_dump() if n_status else None,
    }


@dataclass
class _ListSink:
    records: list[LLMCallRecord] = field(default_factory=list)

    async def record(self, call: LLMCallRecord) -> None:
        self.records.append(call)


def _row(record: LLMCallRecord, system: str) -> dict[str, Any]:
    row = asdict(record)
    if isinstance(record.cost_usd, Decimal):
        row["cost_usd"] = str(record.cost_usd)
    row["system"] = system
    return row


async def compare(
    source: str,
    cases: Sequence[Case],
    *,
    models: Sequence[str] = NLU_MODELS,
    nlu_fn: NluFn = run_nlu,
    client_factory: ClientFactory = get_llm_client,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score `keyword_nlu` and `run_nlu` per model on the `suite` or `smoke` set (D12-D15)."""
    if source == "suite":
        items = derive_suite_items(cases, PERSONAS_PATH)
    elif source == "smoke":
        items = load_smoke_items(SMOKE_PATH)
    else:
        raise ValueError(f"unknown NLU source {source!r} (expected 'suite' or 'smoke')")

    systems: dict[str, Any] = {
        "keyword_nlu": {
            **score(items, [keyword_nlu(i.text) for i in items]),
            "calls": 0,
        }
    }
    ledger: list[dict[str, Any]] = []
    for model in models:
        sink = _ListSink()
        client = client_factory(sink=sink, model_overrides={"nlu": model})
        preds: list[NLUResult | None] = []
        for item in items:
            try:
                preds.append(
                    await nlu_fn(client, item.text, pending=item.pending, country=item.country)
                )
            except Exception:  # R11: the client already retried; count it as a miss
                preds.append(None)
        lat = percentiles([r.latency_ms for r in sink.records])
        costs = [r.cost_usd for r in sink.records if r.cost_usd is not None]
        systems[model] = {
            **score(items, preds),
            "calls": len(sink.records),
            "latency_ms_p50": lat[50],
            "latency_ms_p95": lat[95],
            "mean_cost_usd_per_call": float(sum(costs) / len(costs)) if costs else None,
        }
        ledger.extend(_row(r, f"nlu:{model}") for r in sink.records)
    nlu = {
        "label": LABEL,
        "source": source,
        "n": len(items),
        "caveat": CAVEAT,
        "systems": systems,
    }
    return nlu, ledger


def _pct(rate: dict[str, Any] | None) -> str:
    if not rate or rate["value"] is None:
        return "n/a"
    lo, hi = rate["ci"]
    return f"{rate['value']:.1%} [{lo:.1%}-{hi:.1%}] ({rate['k']}/{rate['n']})"


def _num(value: float | None, fmt: str) -> str:
    return "n/a" if value is None else format(value, fmt)


def render(nlu: dict[str, Any]) -> list[str]:
    """Markdown for the report: the comparison table, then the language-variant breakdown."""
    systems: dict[str, dict[str, Any]] = nlu["systems"]
    lines = [
        f"Label: {nlu['label']}; {nlu['source']} set, n={nlu['n']}.",
        "",
        f"{CAVEAT}.",
        "",
        "| System | Failed calls | Precision | Recall | F1 | Exact-set match | Multi-intent "
        "| Status acc. | p50 ms | p95 ms | Mean cost/call (USD) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, m in systems.items():
        lines.append(
            f"| {name} | {m['failed_calls']} | {m['precision']:.3f} | {m['recall']:.3f} "
            f"| {m['f1']:.3f} "
            f"| {_pct(m['exact_set'])} | {_pct(m['multi_intent'])} | {_pct(m['status_accuracy'])} "
            f"| {_num(m.get('latency_ms_p50'), '.0f')} | {_num(m.get('latency_ms_p95'), '.0f')} "
            f"| {_num(m.get('mean_cost_usd_per_call'), '.5f')} |"
        )
    variants = sorted({v for m in systems.values() for v in m["by_language_variant"]})
    lines += [
        "",
        f"Exact-set match by language variant ({nlu['label']}):",
        "",
        "| System | " + " | ".join(variants) + " |",
        "|---|" + "---|" * len(variants),
    ]
    for name, m in systems.items():
        cells = [_pct(m["by_language_variant"].get(v)) for v in variants]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines
