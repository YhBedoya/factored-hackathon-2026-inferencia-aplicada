"""Select, export and compare the intent classifier (spec D14, D17, D18, D21).

One run does, in order: grouped 5-fold CV for C0-C4 through `train.py`; the D17
winner (smallest served bundle inside the 95% CI of the best grouped-CV macro-F1,
dev never consulted); tau from the winner's out-of-fold predictions (D18); a refit
on all training data; the bundle and lock export; a hard parity check that the
reloaded bundle predicts exactly what the in-process model does on every dev item;
and the dev comparison with its report. `--no-ref` skips the live LLM column.
"""

import argparse
import asyncio
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np

_BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND not in sys.path:
    # `app.*` is imported below; see `ml/intent/data_io.py` and `eval/harness/nlu_eval.py`.
    sys.path.insert(0, _BACKEND)

from app.domains.conversation.baseline.keyword_nlu import keyword_nlu  # noqa: E402
from app.domains.conversation.classifier import ClassifierAdapter, load_classifier  # noqa: E402
from app.domains.conversation.classifier.scorers import Embedder, SklearnScorer  # noqa: E402
from app.domains.conversation.intent_registry import classifier_labels, load_registry  # noqa: E402
from app.domains.conversation.schemas import NLUResult  # noqa: E402

from eval.harness.metrics import Rate, bootstrap_ci, mcnemar, percentiles  # noqa: E402
from eval.harness.nlu_eval import (  # noqa: E402
    NluItem,
    abstain_rates,
    dev_items,
    predict_items,
    score,
)
from ml.intent import data_io, export, report, train  # noqa: E402
from ml.intent.candidates import CANDIDATES, Candidate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVED = ("c2", "c3a", "c3b", "c4")
# Two-sided 95% t quantile for 5 folds (4 degrees of freedom).
T_95_4DF = 2.776
HELD_OUT_LOCALE = "es-ar"
SYSTEM_ORDER = ("C0", "C1", "C2", "C3a", "C3b", "C4", "Ref")
REF_MODEL = "claude-sonnet-5-5"
# Slice rules (written in the report, section 5).
NEGATION_RE = re.compile(r"\b(no|nunca|jamas|jamás|ni|nao|não|nem|sin|sem)\b", re.IGNORECASE)
SHORT_ANSWER_MAX_WORDS = 3


def slice_flags(item: NluItem) -> dict[str, bool]:
    return {
        "negation": bool(NEGATION_RE.search(item.text)),
        "multi-intent": len(item.expected_intents) >= 2,
        "short answer": item.pending is not None
        or len(item.text.split()) <= SHORT_ANSWER_MAX_WORDS,
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _training_rows(data_dir: Path) -> dict[str, Any]:
    """Accepted rows with their locale, in the same order `train.load_training` yields."""
    texts: list[str] = []
    y: list[str] = []
    groups: list[str] = []
    locales: list[str] = []
    origins: list[str] = []
    for f in data_io.load_files(data_dir):
        for it in f.items:
            if it.accepted is True:
                texts.append(it.text)
                y.append(train.item_label(it, f.class_))
                groups.append(it.family)
                locales.append(f.locale)
                origins.append(it.origin)
    return {"texts": texts, "y": y, "groups": groups, "locales": locales, "origins": origins}


def _best_row(record: dict[str, Any]) -> dict[str, Any]:
    grid = record["metrics"]["grid"]
    return max(grid, key=lambda r: r["cv_macro_f1_mean"])  # first of ties, like train.py


def select_winner(
    records: dict[str, dict[str, Any]], sizes: dict[str, int]
) -> tuple[str, dict[str, Any]]:
    """D17: smallest served bundle within the 95% CI of the best grouped-CV macro-F1.

    The CI is mean +/- t * sd / sqrt(folds) of the best candidate's per-fold scores.
    Ties on size go to the higher CV macro-F1.
    """
    best_name = max(SERVED, key=lambda n: _best_row(records[n])["cv_macro_f1_mean"])
    best = _best_row(records[best_name])
    half = T_95_4DF * best["cv_macro_f1_sd"] / sqrt(train.FOLDS)
    floor = best["cv_macro_f1_mean"] - half
    inside = [n for n in SERVED if _best_row(records[n])["cv_macro_f1_mean"] >= floor]
    winner = min(inside, key=lambda n: (sizes[n], -_best_row(records[n])["cv_macro_f1_mean"]))
    return winner, {
        "best_cv": best_name,
        "best_cv_macro_f1": best["cv_macro_f1_mean"],
        "ci_low": floor,
        "ci_high": best["cv_macro_f1_mean"] + half,
        "inside_ci": inside,
        "sizes_bytes": sizes,
    }


def fit_head(
    cand: Candidate, params: dict[str, Any], features: Any, y: list[str], seed: int
) -> Any:
    assert cand.build is not None
    est = cand.build(params, seed)
    est.fit(features, np.asarray(y))
    return est


def make_adapter(
    est: Any,
    labels: tuple[str, ...],
    embedding_model: str | None,
    *,
    tau: float,
    version: str,
    label_set_version: int,
) -> ClassifierAdapter:
    embedder = Embedder(embedding_model, train.CACHE_DIR) if embedding_model else None
    return ClassifierAdapter(
        SklearnScorer(est, labels, embedder),
        tau=tau,
        version=version,
        label_set_version=label_set_version,
    )


def tau_table(probs: Any, y: list[str], labels: tuple[str, ...], chosen: float) -> list[dict]:
    """D18 counts at the chosen tau and one step each side on the out-of-fold rows."""
    top = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    rows = []
    i = train.TAUS.index(chosen)
    for tau in (train.TAUS[max(i - 3, 0)], chosen, train.TAUS[min(i + 3, len(train.TAUS) - 1)]):
        abstain = conf < tau
        wrong = np.array([labels[p] != t for p, t in zip(top, y, strict=True)]) & ~abstain
        side = np.array([labels[p] in train.SIDE_EFFECT for p in top])
        w_side, w_read = int((wrong & side).sum()), int((wrong & ~side).sum())
        n_clar = int(abstain.sum())
        rows.append(
            {
                "tau": tau,
                "coverage": float(1 - abstain.mean()),
                "wrong_side_effect": w_side,
                "wrong_read_only": w_read,
                "clarifications": n_clar,
                "cost": w_side * train.COST_SIDE_EFFECT
                + w_read * train.COST_READ_ONLY
                + n_clar * train.COST_CLARIFY,
                "chosen": tau == chosen,
            }
        )
    return rows


def reliability(probs: Any, y: list[str], labels: tuple[str, ...], bins: int = 10) -> list[dict]:
    top = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    ok = np.array([labels[p] == t for p, t in zip(top, y, strict=True)])
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        mask = (conf >= lo) & ((conf < hi) if b < bins - 1 else (conf <= hi))
        if mask.any():
            out.append(
                {
                    "bin": [lo, hi],
                    "n": int(mask.sum()),
                    "confidence": float(conf[mask].mean()),
                    "accuracy": float(ok[mask].mean()),
                }
            )
    return out


def _exact(item: NluItem, pred: NLUResult | None) -> bool:
    return set(item.expected_intents) == (set(pred.intents) if pred else set())


def single_label(intents: Sequence[str], status: str | None) -> str:
    """One label per item for confusion matrices: the intents, else the status."""
    return "+".join(sorted(intents)) if intents else (status or "none")


def _per_intent_f1(
    items: Sequence[NluItem], preds: Sequence[NLUResult | None]
) -> dict[str, dict[str, Any]]:
    gold = [set(i.expected_intents) for i in items]
    pred = [set(p.intents) if p else set() for p in preds]
    out: dict[str, dict[str, Any]] = {}

    def f1(g: list[bool], p: list[bool]) -> float:
        tp = sum(a and b for a, b in zip(g, p, strict=True))
        fp = sum(b and not a for a, b in zip(g, p, strict=True))
        fn = sum(a and not b for a, b in zip(g, p, strict=True))
        return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0

    for intent in sorted(set().union(*gold)):
        g = [intent in s for s in gold]
        out[intent] = {"n": sum(g), "f1": f1(g, [intent in s for s in pred])}
    g_oos = [(i.expected_status or "").startswith("out_of_") for i in items]
    p_oos = [bool(p and p.status.startswith("out_of_")) for p in preds]
    if any(g_oos):
        out["out of scope (status)"] = {"n": sum(g_oos), "f1": f1(g_oos, p_oos)}
    return out


def _confusion(items: Sequence[NluItem], preds: Sequence[NLUResult | None]) -> dict[str, Any]:
    gold = [single_label(i.expected_intents, i.expected_status) for i in items]
    pred = [single_label(p.intents, p.status) if p else "failed" for p in preds]
    rows = sorted(set(gold))
    cols = [*rows, *sorted(set(pred) - set(rows))]
    matrix = [[0] * len(cols) for _ in rows]
    for g, p in zip(gold, pred, strict=True):
        matrix[rows.index(g)][cols.index(p)] += 1
    return {"rows": rows, "cols": cols, "matrix": matrix}


def _run_ref(items: Sequence[NluItem]) -> tuple[list[NLUResult | None], dict[str, Any]]:
    """`run_nlu` with `nlu@v4` through the pinned client; a failed call is a miss (R11)."""
    from app.core.llm import get_llm_client
    from app.domains.conversation.nodes import run_nlu

    records: list[Any] = []

    class _Sink:
        async def record(self, call: Any) -> None:
            records.append(call)

    client = get_llm_client(sink=_Sink(), model_overrides={"nlu": REF_MODEL})

    async def go() -> list[NLUResult | None]:
        out: list[NLUResult | None] = []
        for item in items:
            try:
                out.append(
                    await run_nlu(client, item.text, pending=item.pending, country=item.country)
                )
            except Exception:
                out.append(None)
        return out

    preds = asyncio.run(go())
    lat = percentiles([r.latency_ms for r in records])
    costs = [r.cost_usd for r in records if r.cost_usd is not None]
    return preds, {
        "p50": lat[50],
        "p95": lat[95],
        "cost_per_call": float(sum(costs) / len(costs)) if costs else None,
    }


def _timed(
    fn: Callable[[NluItem], NLUResult],
) -> tuple[Callable[[NluItem], NLUResult], list[float]]:
    times: list[float] = []

    def run(item: NluItem) -> NLUResult:
        t0 = time.perf_counter()
        out = fn(item)
        times.append((time.perf_counter() - t0) * 1000)
        return out

    return run, times


def _classifier_fn(clf: Any) -> Callable[[NluItem], NLUResult]:
    return lambda item: clf.predict(
        item.text, pending=item.pending, country=item.country, previous_language="es"
    )


def _score_system(
    items: Sequence[NluItem],
    preds: Sequence[NLUResult | None],
    times: Sequence[float] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sc = score(items, preds)
    lo, hi = bootstrap_ci(
        len(items),
        lambda idx: score([items[i] for i in idx], [preds[i] for i in idx])["f1"],
    )
    lat = percentiles(times) if times else {50: None, 95: None}
    out = {
        **sc,
        **abstain_rates(items, preds),
        "f1_ci": [lo, hi],
        "p50_ms": lat[50],
        "p95_ms": lat[95],
        "cost_per_call": 0.0,
        "exact_flags": [_exact(i, p) for i, p in zip(items, preds, strict=True)],
        "per_intent_f1": _per_intent_f1(items, preds),
    }
    if extra:
        out.update(extra)
    return out


def _breakdowns(
    items: Sequence[NluItem], systems: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exact-set match per locale (`language_variant`) and per slice, for each system."""
    flags = [slice_flags(i) for i in items]
    locales = sorted({i.language_variant or "unknown" for i in items})

    def cell(name: str, mask: list[bool]) -> dict[str, Any]:
        oks = [ok for ok, m in zip(systems[name]["exact_flags"], mask, strict=True) if m]
        return Rate.of(sum(oks), len(oks)).model_dump()

    per_locale = {
        loc: {
            n: cell(n, [(i.language_variant or "unknown") == loc for i in items]) for n in systems
        }
        for loc in locales
    }
    per_slice = {
        s: {n: cell(n, [f[s] for f in flags]) for n in systems}
        for s in ("negation", "multi-intent", "short answer")
    }
    return per_locale, per_slice


def _misses(items: Sequence[NluItem], preds: Sequence[NLUResult | None]) -> list[dict[str, Any]]:
    out = []
    for item, pred in zip(items, preds, strict=True):
        if _exact(item, pred):
            continue
        flags = slice_flags(item)
        got = set(pred.intents) if pred else set()
        gold = set(item.expected_intents)
        if flags["multi-intent"]:
            cat = "Multi-intent"
        elif flags["negation"]:
            cat = "Negation"
        elif flags["short answer"]:
            cat = "Very short"
        elif pred is None or (not got and pred.status in ("ambiguous", "unclear")):
            cat = "Asked to clarify (ambiguous)"
        elif not got or not gold:
            cat = "Scope mismatch (in vs out of scope)"
        else:
            cat = "Confusable pair"
        out.append(
            {
                "id": item.id,
                "category": cat,
                "text": item.text,
                "language_variant": item.language_variant,
                "gold": sorted(gold),
                "predicted": sorted(got),
                "status": pred.status if pred else "failed",
            }
        )
    return out


def _parity(
    models_dir: Path, in_process: ClassifierAdapter, items: Sequence[NluItem], version: str
) -> None:
    """Hard failure unless the reloaded bundle predicts exactly what the fitted model does."""
    loaded, reason = load_classifier(models_dir)
    if loaded is None:
        raise SystemExit(f"parity check failed: bundle did not load ({reason})")
    if loaded.version != version:
        raise SystemExit(f"parity check failed: loaded {loaded.version}, expected {version}")
    for item in items:
        kwargs = {"pending": item.pending, "country": item.country, "previous_language": "es"}
        a = in_process.predict(item.text, **kwargs).model_dump()
        b = loaded.predict(item.text, **kwargs).model_dump()
        if a != b:
            raise SystemExit(f"parity check failed on {item.id!r}: {a} != {b}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ml.intent.compare")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", type=Path, default=Path("ml/intent/data"))
    ap.add_argument("--runs-dir", type=Path, default=Path("ml/intent/runs"))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--models-dir", type=Path, default=Path("ml/intent/models"))
    ap.add_argument("--lock", type=Path, default=Path("ml/intent/model.lock"))
    ap.add_argument("--no-ref", action="store_true")
    ap.add_argument("--all-dev-items", action="store_true")
    args = ap.parse_args(argv)

    # The loader reads the lock next to the models dir, so the parity check needs this layout.
    if args.lock.resolve() != (args.models_dir.resolve().parent / "model.lock"):
        print(
            f"--lock must be <models-dir>/../model.lock ({args.models_dir.parent / 'model.lock'})",
            file=sys.stderr,
        )
        return 2

    rows = _training_rows(args.data_dir)
    texts, y, groups = rows["texts"], rows["y"], rows["groups"]
    if not texts:
        print(f"no accepted items under {args.data_dir}", file=sys.stderr)
        return 1
    labels = train.label_universe(y)
    np.random.seed(args.seed)
    registry_version = load_registry().label_set_version

    # 1. Grouped CV for every candidate (C0/C1 give the section 2 baseline rows).
    feats = train.Features(texts)
    records = {
        n: train.run_candidate(c, feats, y, groups, labels, args.seed)
        for n, c in CANDIDATES.items()
    }

    # 2. Refit on all training data with each candidate's best grid point.
    fitted: dict[str, Any] = {}
    for name in ("c0", *SERVED):
        cand = CANDIDATES[name]
        fitted[name] = fit_head(
            cand, records[name]["hyperparameters"], feats.for_candidate(cand), y, args.seed
        )
    sizes = {
        n: export.head_bytes(fitted[n])
        + export.embedding_bytes(train.CACHE_DIR, CANDIDATES[n].embedding_model)
        for n in SERVED
    }

    # 3. D17 winner on grouped CV only; tau from its out-of-fold predictions (D18).
    winner, selection = select_winner(records, sizes)
    wcand, wrec = CANDIDATES[winner], records[winner]
    tau = wrec["metrics"]["tau"]
    oof, _ = train.oof_proba(
        wcand, wrec["hyperparameters"], feats.for_candidate(wcand), y, groups, labels, args.seed
    )
    threshold = {
        "chosen": tau,
        "rows": tau_table(oof, y, labels, tau),
        "reliability": reliability(oof, y, labels),
        "n_oof": len(y),
    }

    # 4. Export, then reload and require identical predictions on every dev item.
    n_version = export.next_version(args.lock)
    model_id = f"intent_clf@v{n_version}"
    files = data_io.load_files(args.data_dir)
    manifest = {
        "model_id": model_id,
        "candidate": winner,
        "hyperparameters": wrec["hyperparameters"],
        "tau": tau,
        "labels": list(labels),
        "label_set_version": registry_version,
        "data_version": max((f.version for f in files), default=0),
        "data_sha256": data_io.data_sha256(args.data_dir),
        "seed": args.seed,
        "embedding_model": wcand.embedding_model,
    }
    old_lock = args.lock.read_text("utf-8") if args.lock.exists() else None
    bundle = export.export_bundle(
        fitted[winner],
        manifest,
        models_dir=args.models_dir,
        lock_path=args.lock,
        cache_dir=train.CACHE_DIR,
    )
    served = make_adapter(
        fitted[winner],
        labels,
        wcand.embedding_model,
        tau=tau,
        version=model_id,
        label_set_version=registry_version,
    )
    try:
        _parity(args.models_dir, served, dev_items(seeds_only=False), model_id)
    except SystemExit:
        # Leave no half-pinned bundle behind.
        bundle.path.unlink(missing_ok=True)
        if old_lock is None:
            args.lock.unlink(missing_ok=True)
        else:
            args.lock.write_text(old_lock, "utf-8")
        raise
    # Parity passed and the lock names the new version: older tarballs would fail the image build.
    export.remove_older_bundles(args.models_dir, model_id)

    # 5. Dev comparison (report only; nothing here feeds selection).
    items = dev_items(seeds_only=not args.all_dev_items)
    systems: dict[str, dict[str, Any]] = {}
    preds_by: dict[str, list[NLUResult | None]] = {}

    def run_system(name: str, fn: Callable[[NluItem], NLUResult]) -> None:
        fn(items[0])  # warm-up (model load) outside the timing
        timed, times = _timed(fn)
        preds = predict_items(items, timed)
        preds_by[name] = preds
        systems[name] = _score_system(items, preds, times)

    run_system(
        "C0",
        _classifier_fn(
            make_adapter(
                fitted["c0"],
                labels,
                None,
                tau=0.0,
                version="majority",
                label_set_version=registry_version,
            )
        ),
    )
    run_system("C1", lambda item: keyword_nlu(item.text))
    adapters = {}
    for name, key in (("C2", "c2"), ("C3a", "c3a"), ("C3b", "c3b"), ("C4", "c4")):
        c = CANDIDATES[key]
        adapters[key] = (
            served
            if key == winner
            else make_adapter(
                fitted[key],
                labels,
                c.embedding_model,
                tau=records[key]["metrics"]["tau"],
                version=f"{key}-unexported",
                label_set_version=registry_version,
            )
        )
        run_system(name, _classifier_fn(adapters[key]))
    if not args.no_ref:
        ref_preds, ref_meta = _run_ref(items)
        preds_by["Ref"] = ref_preds
        systems["Ref"] = _score_system(
            items,
            ref_preds,
            None,
            {
                "p50_ms": ref_meta["p50"],
                "p95_ms": ref_meta["p95"],
                "cost_per_call": ref_meta["cost_per_call"],
            },
        )

    base = systems["C1"]["exact_flags"]
    for name, s in systems.items():
        if name != "C1":
            s["mcnemar_vs_c1"] = mcnemar(s["exact_flags"], base)

    # 6. Locale transfer: the winner's recipe without es-ar, tested on es-ar dev items.
    keep = [i for i, loc in enumerate(rows["locales"]) if loc.lower() != HELD_OUT_LOCALE]
    target = [
        (i, it)
        for i, it in enumerate(items)
        if (it.language_variant or "").lower() == HELD_OUT_LOCALE
    ]
    transfer: dict[str, Any] | None = None
    if keep and target and len(set(y[i] for i in keep)) > 1:
        t_feats = feats.for_candidate(wcand)
        t_est = fit_head(
            wcand,
            wrec["hyperparameters"],
            train._take(t_feats, keep),
            [y[i] for i in keep],
            args.seed,
        )
        # Classes absent without es-ar are still scored; the scorer's labels follow the fit.
        t_labels = tuple(str(c) for c in t_est.classes_)
        t_clf = make_adapter(
            t_est,
            t_labels,
            wcand.embedding_model,
            tau=tau,
            version="transfer",
            label_set_version=registry_version,
        )
        t_items = [it for _, it in target]
        t_preds = predict_items(t_items, _classifier_fn(t_clf))
        ok = sum(_exact(it, p) for it, p in zip(t_items, t_preds, strict=True))
        transfer = {
            "held_out_locale": HELD_OUT_LOCALE,
            "exact_set": Rate.of(ok, len(t_items)).model_dump(),
            "in_locale_exact_set": next(
                (
                    v
                    for k, v in systems[_name_of(winner)]["by_language_variant"].items()
                    if k.lower() == HELD_OUT_LOCALE
                ),
                None,
            ),
            "n_train": len(keep),
        }

    per_locale, per_slice = _breakdowns(items, systems)
    from ml.intent.leakage import find_leaks

    loc_stats = []
    n_labels_total = len(classifier_labels())
    for loc in data_io.LOCALES:
        idx = [i for i, v in enumerate(rows["locales"]) if v == loc]
        loc_stats.append(
            {
                "locale": loc,
                "utterances": len(idx),
                "families": len({groups[i] for i in idx}),
                "intents_covered": len({y[i] for i in idx}),
                "intents_total": n_labels_total,
            }
        )
    origin = Counter(rows["origins"])
    winner_system = _name_of(winner)
    results: dict[str, Any] = {
        "run_id": args.run_id or f"compare_s{args.seed}",
        "commit": _git_commit(),
        "seed": args.seed,
        "data_version": manifest["data_version"],
        "data_sha256": manifest["data_sha256"],
        "label_set_version": registry_version,
        "n_labels": n_labels_total,
        "model_id": model_id,
        "bundle_sha256": bundle.sha256,
        "bundle_bytes": bundle.size_bytes,
        "winner": winner,
        "winner_system": winner_system,
        "winner_hyperparameters": wrec["hyperparameters"],
        "tau": tau,
        "selection": selection,
        "test_set": {
            "n": len(items),
            "seeds_only": not args.all_dev_items,
            "ref_run": not args.no_ref,
        },
        "training": {
            "per_locale": loc_stats,
            "n": len(texts),
            "origin": dict(origin),
            "leakage_vs_dev": len(find_leaks(texts, [i.text for i in dev_items(seeds_only=False)])),
        },
        "cv": {
            n: {
                "description": r["description"],
                "mean": _best_row(r)["cv_macro_f1_mean"],
                "sd": _best_row(r)["cv_macro_f1_sd"],
                "params": r["hyperparameters"],
                "tau": r["metrics"]["tau"],
                "prediction_hash": r["prediction_hash"],
                "size_bytes": sizes.get(n),
                "p95_ms": systems[_name_of(n)]["p95_ms"] if n != "c1" else systems["C1"]["p95_ms"],
            }
            for n, r in records.items()
        },
        "threshold": threshold,
        "systems": systems,
        "per_locale": per_locale,
        "per_slice": per_slice,
        "transfer": transfer,
        "confusions": {n: _confusion(items, p) for n, p in preds_by.items()},
        "misses": _misses(items, preds_by[winner_system]),
        "slice_rules": {
            "negation": "text has a negator (no, nunca, jamas, ni, sin, nao, nem, sem)",
            "multi-intent": "two or more expected intents",
            "short answer": f"a pending question, or at most {SHORT_ANSWER_MAX_WORDS} words",
        },
    }
    out_dir = args.runs_dir / results["run_id"]
    report.write_report(results, out_dir)
    print(f"{model_id} = {winner} tau={tau} sha256={bundle.sha256[:12]} parity=ok -> {out_dir}")
    return 0


def _name_of(candidate: str) -> str:
    return {"c0": "C0", "c1": "C1", "c2": "C2", "c3a": "C3a", "c3b": "C3b", "c4": "C4"}[candidate]


if __name__ == "__main__":
    raise SystemExit(main())
