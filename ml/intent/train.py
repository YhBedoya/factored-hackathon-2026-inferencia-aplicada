"""Train and cross-validate the intent candidates (spec D17, D18, D21).

Grouped 5-fold CV by `family` on the accepted training items only. The best grid
point by CV macro-F1 gives the out-of-fold probabilities, and tau comes from those
(D18 cost rule). Two runs with the same seed write identical `metrics` and
`prediction_hash`.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ml.intent import data_io
from ml.intent.candidates import CANDIDATES, NO_MATCH, Candidate, keyword_labels

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "ml" / "intent" / ".cache" / "fastembed"
FOLDS = 5
# D18: acting on the wrong side-effect intent costs 5, the wrong read-only intent 2,
# and asking a clarification question 1.
SIDE_EFFECT = frozenset({"card_block", "card_unlock", "replacement_request", "unrecognized_charge"})
COST_SIDE_EFFECT, COST_READ_ONLY, COST_CLARIFY = 5.0, 2.0, 1.0
TAUS = [round(0.05 * i, 2) for i in range(1, 20)]


def item_label(item: data_io.DataItem, class_name: str) -> str:
    """Intent label, or the scope class (topic) for items with no intent."""
    return item.intents[0] if item.intents else (item.topic or class_name)


def load_training(data_dir: Path) -> tuple[list[str], list[str], list[str]]:
    files = data_io.load_files(data_dir)
    texts: list[str] = []
    labels: list[str] = []
    groups: list[str] = []
    for f in files:
        for it in f.items:
            if it.accepted is True:
                texts.append(it.text)
                labels.append(item_label(it, f.class_))
                groups.append(it.family)
    return texts, labels, groups


def macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    from sklearn.metrics import f1_score

    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def _aligned(estimator: Any, features: Any, labels: tuple[str, ...]) -> Any:
    """predict_proba columns mapped onto the full label set (a fold may miss classes)."""
    raw = estimator.predict_proba(features)
    out = np.zeros((raw.shape[0], len(labels)))
    index = {label: i for i, label in enumerate(labels)}
    for col, cls in enumerate(estimator.classes_):
        out[:, index[cls]] = raw[:, col]
    return out


def oof_proba(
    cand: Candidate,
    params: dict[str, Any],
    features: Any,
    y: list[str],
    groups: list[str],
    labels: tuple[str, ...],
    seed: int,
) -> tuple[Any, list[float]]:
    """Out-of-fold probability matrix and the per-fold macro-F1."""
    from sklearn.model_selection import GroupKFold

    assert cand.build is not None
    y_arr = np.asarray(y)
    probs = np.zeros((len(y), len(labels)))
    fold_f1: list[float] = []
    splitter = GroupKFold(n_splits=FOLDS, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(np.zeros(len(y)), y_arr, groups):
        est = cand.build(params, seed)
        x_train = _take(features, train_idx)
        est.fit(x_train, y_arr[train_idx])
        probs[test_idx] = _aligned(est, _take(features, test_idx), labels)
        pred = [labels[i] for i in probs[test_idx].argmax(axis=1)]
        fold_f1.append(macro_f1(list(y_arr[test_idx]), pred))
    return probs, fold_f1


def _take(features: Any, idx: Any) -> Any:
    if isinstance(features, list):
        return [features[i] for i in idx]
    return features[idx]


def pick_tau(probs: Any, y: list[str], labels: tuple[str, ...]) -> tuple[float, float, float]:
    """tau minimising the D18 cost over out-of-fold rows; ties go to the higher tau.

    A row below tau is a clarification (cost 1). Above it, a wrong prediction costs
    5 when the predicted intent is a side-effect one, else 2. Returns
    (tau, total cost, abstain rate).
    """
    top = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    wrong_cost = np.array(
        [COST_SIDE_EFFECT if labels[p] in SIDE_EFFECT else COST_READ_ONLY for p in top]
    )
    wrong = np.array([labels[p] != t for p, t in zip(top, y, strict=True)])
    best = (TAUS[0], float("inf"), 0.0)
    for tau in TAUS:
        abstain = conf < tau
        cost = float(np.where(abstain, COST_CLARIFY, np.where(wrong, wrong_cost, 0.0)).sum())
        if cost <= best[1]:
            best = (tau, cost, float(abstain.mean()))
    return best


def _hash_rows(rows: list[tuple[Any, ...]]) -> str:
    payload = json.dumps(sorted(rows), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def confusion(y: list[str], pred: list[str], labels: tuple[str, ...]) -> dict[str, Any]:
    # Columns gain NO_MATCH when a rule system predicted something outside the label set.
    cols = (*labels, NO_MATCH) if NO_MATCH in pred and NO_MATCH not in labels else labels
    index = {label: i for i, label in enumerate(cols)}
    matrix = [[0] * len(cols) for _ in labels]
    row_of = {label: i for i, label in enumerate(labels)}
    for t, p in zip(y, pred, strict=True):
        matrix[row_of[t]][index[p]] += 1
    return {"rows": list(labels), "cols": list(cols), "matrix": matrix}


class Features:
    """Embeddings computed once per model and cached in memory for the run."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self._cache: dict[str, Any] = {}

    def for_candidate(self, cand: Candidate) -> Any:
        if cand.embedding_model is None:
            return self.texts
        if cand.embedding_model not in self._cache:
            from app.domains.conversation.classifier.scorers import Embedder

            self._cache[cand.embedding_model] = Embedder(cand.embedding_model, CACHE_DIR).embed(
                self.texts
            )
        return self._cache[cand.embedding_model]


def run_candidate(
    cand: Candidate,
    feats: Features,
    y: list[str],
    groups: list[str],
    labels: tuple[str, ...],
    seed: int,
) -> dict[str, Any]:
    index = {label: i for i, label in enumerate(labels)}
    if cand.build is None:
        # C1 has nothing to fit: predictions are its own, probability 1 on the label.
        pred = keyword_labels(feats.texts)
        pred_ix = [index.get(p, -1) for p in pred]
        probs = np.zeros((len(y), len(labels)))
        for row, ix in enumerate(pred_ix):
            if ix >= 0:
                probs[row, ix] = 1.0
        # A prediction outside the label set (NO_MATCH) is never right.
        grid_rows = [{"params": {}, "cv_macro_f1_mean": macro_f1(y, pred), "cv_macro_f1_sd": 0.0}]
        best_params: dict[str, Any] = {}
        pred_labels = [p if p in index else NO_MATCH for p in pred]
        conf_labels = labels
    else:
        features = feats.for_candidate(cand)
        grid_rows = []
        best: tuple[float, dict[str, Any], Any] | None = None
        for params in cand.grid:
            probs_g, fold_f1 = oof_proba(cand, params, features, y, groups, labels, seed)
            mean = float(np.mean(fold_f1))
            grid_rows.append(
                {
                    "params": params,
                    "cv_macro_f1_mean": mean,
                    "cv_macro_f1_sd": float(np.std(fold_f1)),
                }
            )
            if best is None or mean > best[0]:  # first of equals wins: grid order is fixed
                best = (mean, params, probs_g)
        assert best is not None
        best_params, probs = best[1], best[2]
        pred_labels = [labels[i] for i in probs.argmax(axis=1)]
        conf_labels = labels

    tau, cost, abstain_rate = pick_tau(probs, y, conf_labels)
    metrics = {
        "grid": grid_rows,
        "best_params": best_params,
        "cv_macro_f1_mean": max(r["cv_macro_f1_mean"] for r in grid_rows),
        "oof_macro_f1": macro_f1(y, pred_labels),
        "oof_accuracy": float(np.mean([a == b for a, b in zip(y, pred_labels, strict=True)])),
        "tau": tau,
        "tau_cost": cost,
        "tau_abstain_rate": round(abstain_rate, 6),
    }
    rows = [
        (t, p, [round(float(v), 6) for v in prob])
        for t, p, prob in zip(y, pred_labels, probs, strict=True)
    ]
    return {
        "candidate": cand.name,
        "description": cand.description,
        "hyperparameters": best_params,
        "embedding_model": cand.embedding_model,
        "metrics": metrics,
        "prediction_hash": _hash_rows(rows),
        "confusion_matrix": confusion(y, pred_labels, labels),
    }


def label_universe(y: list[str]) -> tuple[str, ...]:
    # Sorted so column order never depends on item order. C1's NO_MATCH is not a class.
    return tuple(sorted(set(y)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ml.intent.train")
    ap.add_argument("--candidate", choices=[*CANDIDATES, "all"], default="all")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", type=Path, default=Path("ml/intent/data"))
    ap.add_argument("--runs-dir", type=Path, default=Path("ml/intent/runs"))
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    texts, y, groups = load_training(args.data_dir)
    if not texts:
        print(f"no accepted items under {args.data_dir}", file=sys.stderr)
        return 1
    labels = label_universe(y)
    np.random.seed(args.seed)
    names = list(CANDIDATES) if args.candidate == "all" else [args.candidate]
    feats = Features(texts)
    records = {n: run_candidate(CANDIDATES[n], feats, y, groups, labels, args.seed) for n in names}

    files = data_io.load_files(args.data_dir)
    try:
        from app.domains.conversation.intent_registry import load_registry

        label_set_version: int | None = load_registry().label_set_version
    except Exception:  # registry not importable in a stripped checkout: keep the run usable
        label_set_version = None
    head: dict[str, Any] = {
        "data_version": max((f.version for f in files), default=0),
        "data_sha256": data_io.data_sha256(args.data_dir),
        "label_set_version": label_set_version,
        "seed": args.seed,
        "n_items": len(texts),
    }
    if len(names) == 1:
        rec = records[names[0]]
        out = {**head, **rec}
    else:
        out = {
            **head,
            "candidate": "all",
            "hyperparameters": {n: r["hyperparameters"] for n, r in records.items()},
            "metrics": {n: r["metrics"] for n, r in records.items()},
            "prediction_hash": _hash_rows([(n, r["prediction_hash"]) for n, r in records.items()]),
            "confusion_matrix": {n: r["confusion_matrix"] for n, r in records.items()},
            "candidates": records,
        }
    run_id = args.run_id or f"train_{args.candidate}_s{args.seed}"
    path = args.runs_dir / run_id / "train.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True), "utf-8")
    for n, r in records.items():
        m = r["metrics"]
        print(
            f"{n}: cv_f1={m['cv_macro_f1_mean']:.3f} tau={m['tau']} "
            f"hash={r['prediction_hash'][:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
