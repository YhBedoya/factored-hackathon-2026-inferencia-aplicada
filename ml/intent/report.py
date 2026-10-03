"""Write the intent classifier report (spec D21): markdown, JSON, figures, misses.

Sections 1-8 follow the requirement doc's mock. Numbers come from the `results`
dict that `compare.py` builds; nothing here computes a metric. Dev scores are
report-only: selection used grouped CV (D17, OQ3).
"""

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import yaml

__all__ = ["render_markdown", "write_report"]

NAMES = {
    "c0": "C0 majority",
    "c1": "C1 keyword_nlu",
    "c2": "C2 TF-IDF + LR",
    "c3a": "C3a e5-small + LR",
    "c3b": "C3b MiniLM + LR",
    "c4": "C4 e5-small + kNN",
}


def _rate(r: dict[str, Any] | None) -> str:
    if not r or r.get("value") is None:
        return "n/a"
    lo, hi = r["ci"]
    return f"{r['value']:.1%} [{lo:.1%}, {hi:.1%}]"


def _plain(r: dict[str, Any] | None) -> str:
    return "n/a" if not r or r.get("value") is None else f"{r['value']:.1%} ({r['k']}/{r['n']})"


def _ms(v: float | None) -> str:
    return "n/a" if v is None else ("<1" if v < 1 else f"{v:.0f}")


def _mb(n: int | None) -> str:
    return "-" if not n else f"{n / 1e6:.1f} MB"


def render_markdown(r: dict[str, Any]) -> str:
    sysm: dict[str, Any] = r["systems"]
    served = r["model_id"]
    served_key = r["winner_system"]
    cols = list(sysm)
    sel = r["selection"]
    t = r["test_set"]
    L: list[str] = [
        f"**Intent classifier report - run {r['run_id']}**",
        "",
        f"Commit `{r['commit']}` · data `intent-data@v{r['data_version']}` "
        f"(sha256 `{r['data_sha256'][:8]}`) · label set `v{r['label_set_version']}` "
        f"({r['n_labels']} classifier labels) · seed {r['seed']}",
        f"Selected model `{served}` = {NAMES[r['winner']]} "
        f"(params {json.dumps(r['winner_hyperparameters'])}) · tau = {r['tau']}",
        f"Test set: dev (n = {t['n']}, "
        f"{'seeds only' if t['seeds_only'] else 'all language variants'}). "
        f"Held-out: not run. Reference (Ref) {'run' if t['ref_run'] else 'not run (--no-ref)'}.",
        "",
        "### 1. Training data",
        "",
        "| Locale | Utterances | Families | Intents covered |",
        "|---|---|---|---|",
    ]
    for s in r["training"]["per_locale"]:
        L.append(
            f"| {s['locale']} | {s['utterances']} | {s['families']} | "
            f"{s['intents_covered']}/{s['intents_total']} |"
        )
    o = r["training"]["origin"]
    total = max(r["training"]["n"], 1)
    L += [
        "",
        f"Origin: seed {o.get('seed', 0) / total:.0%}, "
        f"paraphrase {o.get('paraphrase', 0) / total:.0%}. "
        f"Leakage check vs dev: {r['training']['leakage_vs_dev']} matches.",
        "",
        "### 2. Model selection (grouped 5-fold CV on training data)",
        "",
        "| ID | Model | Macro-F1 (CV, mean ± sd) | p95 latency CPU (dev) | Bundle size |",
        "|---|---|---|---|---|",
    ]
    for k, c in r["cv"].items():
        L.append(
            f"| {k.upper()} | {c['description']} | {c['mean']:.3f} ± {c['sd']:.3f} | "
            f"{_ms(c['p95_ms'])} ms | {_mb(c['size_bytes'])} |"
        )
    L += [
        "",
        f"Rule (D17): the smallest served bundle within the 95% CI of the best "
        f"grouped-CV macro-F1. "
        f"Best was {sel['best_cv'].upper()} at {sel['best_cv_macro_f1']:.3f}; CI "
        f"[{sel['ci_low']:.3f}, {sel['ci_high']:.3f}]. Inside the CI: "
        f"{', '.join(n.upper() for n in sel['inside_ci'])}. "
        f"Selected **{r['winner'].upper()}**. Dev scores were not used to choose.",
        "",
        "### 3. Threshold",
        "",
        "Reliability curve: `figures/reliability.png`. Cost rule (D18): "
        "wrong side-effect intent = 5, "
        "wrong read-only intent = 2, clarification = 1. tau minimises the total cost over the "
        "out-of-fold predictions; ties go to the higher tau.",
        "",
        f"Counts are out-of-fold over the {r['threshold']['n_oof']} training utterances.",
        "",
        "| tau | Coverage (not ambiguous) | Wrong side-effect (x5) | Wrong read-only (x2) "
        "| Clarifications (x1) | Total cost |",
        "|---|---|---|---|---|---|",
    ]
    for row in r["threshold"]["rows"]:
        b = "**" if row["chosen"] else ""
        L.append(
            f"| {b}{row['tau']:.2f}{b} | {b}{row['coverage']:.1%}{b} "
            f"| {b}{row['wrong_side_effect']}{b} | {b}{row['wrong_read_only']}{b} "
            f"| {b}{row['clarifications']}{b} | {b}{row['cost']:.0f}{b} |"
        )
    L += [
        "",
        f"### 4. Comparison on dev (n = {t['n']}, same items, same scorer)",
        "",
        "| System | Macro-F1 [95% bootstrap CI] | Exact-set match [95% CI] | Status acc. [95% CI] "
        "| OOS recall | False abstain | p50 / p95 ms | Cost / call |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for n in cols:
        s = sysm[n]
        mark = "**" if n == served_key else ""
        cost = "n/a" if s["cost_per_call"] is None else f"${s['cost_per_call']:.4f}"
        L.append(
            f"| {mark}{n}{' = ' + served if n == served_key else ''}{mark} "
            f"| {s['f1']:.2f} [{s['f1_ci'][0]:.2f}, {s['f1_ci'][1]:.2f}] "
            f"| {_rate(s['exact_set'])} | {_rate(s['status_accuracy'])} "
            f"| {_plain(s['oos_recall'])} | {_plain(s['false_abstain'])} "
            f"| {_ms(s['p50_ms'])} / {_ms(s['p95_ms'])} | {cost} |"
        )
    L.append("")
    for n in cols:
        if n == "C1":
            continue
        m = sysm[n]["mcnemar_vs_c1"]
        L.append(
            f"Paired test, {n} vs keyword (exact-set): {n} right and keyword wrong = {m['b']}, "
            f"the reverse = {m['c']}, McNemar p = {m['p']:.3f}."
        )
    ref = ["C1", served_key] + (["Ref"] if "Ref" in sysm else [])
    L += [
        "",
        "**4b. F1 per intent (dev)**",
        "",
        f"| Intent | n | {' | '.join(ref)} |",
        f"|---|---|{'---|' * len(ref)}",
    ]
    intents = sorted({i for n in ref for i in sysm[n]["per_intent_f1"]})
    for i in intents:
        n_i = next(sysm[n]["per_intent_f1"][i]["n"] for n in ref if i in sysm[n]["per_intent_f1"])
        cells = [
            f"{sysm[n]['per_intent_f1'][i]['f1']:.2f}" if i in sysm[n]["per_intent_f1"] else "-"
            for n in ref
        ]
        L.append(f"| `{i}` | {n_i} | {' | '.join(cells)} |")
    cm = r["confusions"][served_key]
    L += [
        "",
        f"**4c. Confusion matrix, {served} (dev)**",
        "",
        "Rows are gold, columns the prediction (`ambiguous` is safe: the bot asks). "
        "One matrix per system is in `figures/`.",
        "",
        "| gold ↓ / pred → | " + " | ".join(f"`{c}`" for c in cm["cols"]) + " |",
        "|---|" + "---|" * len(cm["cols"]),
    ]
    for lab, row in zip(cm["rows"], cm["matrix"], strict=True):
        L.append(f"| `{lab}` | " + " | ".join(str(v) if v else "" for v in row) + " |")
    L += [
        "",
        "### 5. Results per locale and per item type (exact-set match)",
        "",
        f"Locale is the item's `language_variant` (smoke items have none: `unknown`). "
        f"Slice rules: negation = {r['slice_rules']['negation']}; multi-intent = "
        f"{r['slice_rules']['multi-intent']}; short answer = {r['slice_rules']['short answer']}.",
        "",
        f"| Slice | n | {' | '.join(cols)} |",
        f"|---|---|{'---|' * len(cols)}",
    ]
    for group in (r["per_locale"], r["per_slice"]):
        for name, cells in group.items():
            n_item = cells[cols[0]]["n"]
            L.append(f"| {name} | {n_item} | " + " | ".join(_plain(cells[c]) for c in cols) + " |")
    tr = r["transfer"]
    L.append("")
    if tr:
        L.append(
            f"Locale transfer ({tr['held_out_locale']} removed from training, then tested on "
            f"{tr['held_out_locale']}): {_plain(tr['exact_set'])}, against "
            f"{_plain(tr['in_locale_exact_set'])} when {tr['held_out_locale']} is in training."
        )
    else:
        L.append("Locale transfer: not run (no es-ar training rows or dev items).")
    L += [
        "",
        "### 6. Where it fails",
        "",
        f"Misses of {served}, by category. The full list is `misses.yaml`.",
        "",
    ]
    cats: dict[str, list[dict[str, Any]]] = {}
    for m in r["misses"]:
        cats.setdefault(m["category"], []).append(m)
    L += ["| Category | Count | Example | Gold → predicted |", "|---|---|---|---|"]
    if not cats:
        L.append("| none | 0 | | |")
    for cat, ms in sorted(cats.items(), key=lambda kv: -len(kv[1])):
        e = ms[0]
        L.append(
            f'| {cat} | {len(ms)} | "{e["text"]}" | {e["gold"] or e["status"]} → '
            f"{e['predicted'] or e['status']} |"
        )
    L += [
        "",
        "### 7. Degraded mode, end to end",
        "",
        "To be filled by the degraded e2e run.",
        "",
        "| | Today (handoff on LLM failure) | Degraded mode |",
        "|---|---|---|",
        "| Resolved safely | | |",
        "| Handed off | | |",
        "| Unsafe outcomes | | |",
        "",
        "### 8. Limitations",
        "",
        "- AI-generated (gpt-6-luna), human-audited labels. Synthetic, not real customer text.",
        f"- n = {t['n']} dev items, so the CIs are wide. The paired test is the stronger evidence.",
        "- Dev scores are report-only. Selection and tau used grouped CV on training data (OQ3).",
        "- The Ref column runs without a fixed temperature (ADR-031)."
        if t["ref_run"]
        else "- The Ref column was not run (`--no-ref`).",
        "- Degraded-mode replies are template-worded. This report scores routing, not wording.",
        "",
    ]
    return "\n".join(L)


def _figures(r: dict[str, Any], fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    bins = r["threshold"]["reliability"]
    fig, ax = plt.subplots(figsize=(4, 4))
    ax.plot([0, 1], [0, 1], "--", color="grey")
    ax.plot([b["confidence"] for b in bins], [b["accuracy"] for b in bins], "o-")
    ax.set(xlabel="confidence", ylabel="accuracy", title="Reliability (out-of-fold)")
    fig.tight_layout()
    fig.savefig(fig_dir / "reliability.png", dpi=120)
    plt.close(fig)
    for name, cm in r["confusions"].items():
        size = max(4, 0.5 * len(cm["cols"]))
        fig, ax = plt.subplots(figsize=(size, size))
        ax.imshow(cm["matrix"], cmap="Blues")
        ax.set_xticks(range(len(cm["cols"])), cm["cols"], rotation=90, fontsize=6)
        ax.set_yticks(range(len(cm["rows"])), cm["rows"], fontsize=6)
        ax.set(xlabel="predicted", ylabel="gold", title=f"{name} (dev)")
        fig.tight_layout()
        fig.savefig(fig_dir / f"confusion_{name}.png", dpi=100)
        plt.close(fig)


def write_report(results: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nlu_classifier.md").write_text(render_markdown(results), "utf-8")
    (out_dir / "nlu_classifier.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True, default=str), "utf-8"
    )
    (out_dir / "misses.yaml").write_text(
        yaml.safe_dump(results["misses"], allow_unicode=True, sort_keys=False), "utf-8"
    )
    _figures(results, out_dir / "figures")
