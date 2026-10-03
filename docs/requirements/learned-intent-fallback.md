# Requirement: learned intent classifier and LLM-free degraded mode

Status: **draft for review** · Date: 2026-10-01 · Owner: Dev A (whole card, set by the human at spec time).

This document is the input for `/wave-run`. The `spec-writer` turns it into `docs/specs/<slug>.md`. The open questions at the end are answered at that stage. It does not fix implementation details. It fixes what is built, why, and how it is evaluated.

## Why

1. **D4.6 (evaluate at least one learned component against an appropriate baseline)** and **K6 (ML: model selection, optimization, implementation, tracking).** Today the only learned component is the pretrained LLM. Nothing is trained by the team.
2. **D5 (failure handling).** Today, when the LLM fails or `LLM_DISABLED` is on, every turn, including button turns, goes `fallback` → `handoff_summary` → `handoff`. Cardy stops serving and every customer lands in a human queue.

The dataset can't train this component. `call_transcripts` has 42 distinct texts and one intent value, and `complaints.description` has 5 templates (`05` §1). The other dataset targets were also reviewed: `is_fraud` carries no signal beyond `fraud_score` (AUC 0.50 without it), and credit limits don't vary with income or score within a currency. The training labels are therefore **team-generated and labeled as such** (B2), like the eval suite.

## Current state

- **`understand`** (`backend/app/domains/conversation/nodes/understand.py`): one LLM structured-output call per typed turn (`nlu@v4`, `claude-sonnet-5-5`, ADR-031). It returns an `NLUResult`: `language`, `intents[]` from the closed list in `schemas.py`, `status`, `slots`, `clarification`. On `LLMError` it writes `nlu = None` and `escalation_reason = llm_unavailable`.
- **`compose`** (`nodes/compose.py`): the LLM phrases the facts the flows already formatted in code. It falls back to the `goal_*` templates (`templates.py`) after two grounding failures, but on `LLMError` it hands off.
- **`_entry`** (`graph.py`): `escalation_reason == llm_unavailable` (set by `load_session` under `LLM_DISABLED`) goes straight to `fallback`, before buttons, picks and step-up resumes.
- **The baseline system** (`build_graph(system="baseline")`, eval only): `keyword_nlu` + `lexicon.yaml` (regex, clause split, negation window, ADR-005), `baseline_compose` (goal templates), the fixed-template `handoff_summary` and `abstain`. It runs every flow end to end with no LLM call.
- **NLU comparison** (`eval/harness/nlu_eval.py`): scores `keyword_nlu` against `run_nlu` per model on the smoke set (`eval/nlu/nlu_v1_smoke.yaml`, 20 items) and on first-turn items derived from the scenarios. The latest numbers are in the decision log (D7 proposal): keyword F1 0.635, Sonnet and Haiku F1 1.000 on n=20.

## What is built

### R1 · Intent classifier (the learned component)

A small, local, CPU-only model that maps one masked customer message to an `NLUResult`-shaped output with no LLM call.

- **Input:** the masked text (same as `understand`), plus `country` and `pending` as context.
- **Output:** an `NLUResult` that passes the existing Pydantic validation.
  - `intents`: in-scope intents from the closed list, including `affirm` / `deny` / `greeting` / `thanks_close` / `human_request`.
  - `status`:
    - `clear` when the top score is above the confidence threshold.
    - `out_of_scope` or `out_of_market`, with `slots.topic` set, when the top class is a `scope.yaml` topic.
    - `ambiguous` when below the threshold. Below the threshold the classifier never guesses.
  - `language`: reuse the existing language-marker heuristic.
- **Slots** it does not try to extract (`card_hint`, `amount`, `merchant_text`, `date_expression`) stay `None`. The flows already fall back to widgets for them (R2).
- **`block_kind`** keeps the `keyword_nlu` qualifier rule. With no qualifier, `card_block` returns `ambiguous` + `lock_vs_block`, so the lock-vs-block buttons appear.
- **Never injection:** it never returns `injection_suspected`. With no LLM in the turn there is no prompt to inject into, and tools, confirmation tokens and policy still apply (R1–R6 unchanged).
- **Loading:** the model file is versioned, loaded once at startup and pinned like a prompt version. Its version is logged on each decision, like the policy hash.
- **Location:** not under `core/llm/` (it is not an LLM). See Q1.

### R2 · Degraded mode (the role in the app)

When the LLM is unavailable, the turn runs the **no-LLM path** instead of handing off:

| Node | Normal | Degraded |
|---|---|---|
| `understand` | `run_nlu` (LLM) | R1 classifier |
| `compose` | LLM draft + grounding | `goal_*` template (as `baseline_compose`) |
| `abstain` | `compose` phrases the four facts | fixed four-part template (as `baseline_abstain`) |
| `handoff_summary` | LLM writes `request` | fixed template (exists today under `LLM_DISABLED`) |

**Triggers:**
- An `LLMError` from `understand` or `compose` on this turn. The current turn is re-served on the no-LLM path, not handed off.
- `LLM_DISABLED=true`, which today hands off every turn (see Q2).

**What still works:**
- card status, balance and due date
- lock / block (lock-vs-block via buttons) and replacement
- the dispute flow (card picker → transaction-list widget → buttons)
- `affirm` / `deny` answers to pending yes/no questions
- abstain, and handoff on request

Button, pick and step-up turns resume their flow as they do in normal mode.

**What hands off:** `transaction_search` (it needs dates and merchant from free text), `general_question`, `decline_explain` (no reply template can explain a decline, so it is not served in degraded mode), and any turn whose classifier result is `ambiguous` twice in a row (the existing `clarification_failures` counter).

**Visible to the customer and staff:**
- For the intents still served, the reply carries the same facts. Only the wording changes. Decline explanation is not served in degraded mode and hands off.
- A `degraded: true` flag goes on `reply_sent.payload` and on the ledger/trace for the turn, so the timeline and the eval report can count degraded turns.
- Whether the customer sees a notice ("estoy en modo básico") is Q3.

**Unchanged:** R1 (customer_id from session), R2 (confirmation tokens), R3 (verified read-back), R5 (formatting in code), R11 (safe fallback). The no-LLM path writes nothing that the normal path can't write.

### R3 · Training data

- **Source:** AI-generated (gpt-6-luna), human-audited. Every seed and every paraphrase is generated by the non-Claude model from ADR-030 (which avoids self-grading bias), and a person audits every item with an accept flag before it enters the set (spec `docs/specs/learned-intent-fallback.md` D19). This is a listed limitation.
- **Header:** each file carries a provenance header (`team-generated-synthetic`, like `scope.yaml`) and a version.
- **One record:**
  - `text`
  - `locale` (`es-mx`, `es-co`, `es-ar`, `pt-br`)
  - `intents` (list) and `status`
  - `topic` (for scope classes)
  - `family` (the paraphrase group, used for splits)
  - `origin` (`written` or `paraphrased`)
- **Coverage per intent and locale:**
  - plain phrasings
  - regional vocabulary (from `lexicon.yaml` and `docs/brand.md`)
  - typos and informal text
  - negations ("no quiero bloquearla")
  - short answers ("sí", "nao", "dale")
  - hard negatives between confusable pairs
- **Scope classes:** one per `scope.yaml` topic (`pix_boleto`, `loans`, `accounts`, `investments`, `insurance`, `transfers`, `other`).
- **Never in training:** no text from `eval/scenarios/` (dev or held-out) or `eval/nlu/`. A CI check fails if a training text matches a dev or held-out text after normalization (R8 below).

### R4 · Adding workflows

New intents are expected (the Stretch list and possibly new domains). Adding one must touch one place:

- An **intent registry** lists each intent with its flow, its training-data file, its lexicon entry and its tier. The graph, the NLU prompt's intent list and the classifier's label set all read from it, or are checked against it.
- **Adding an intent** = registry row + training utterances for every locale + at least 2 dev cases (`07` §6) + retrain (seconds) + rerun the offline comparison.
- **When a scope topic becomes a workflow** (e.g. `accounts`): its examples are relabeled from the scope class to the new intents, and the label-set version bumps. A model trained on an older label set refuses to load.
- **CI:** every intent in the registry has training utterances in every locale and at least one eval item. Every intent the classifier predicts exists in the registry.
- **Beyond cards:** if new workflows go beyond cards, the classifier becomes two stages (domain first, then intent). That is Q5, and is decided once the new workflows are known.
- **Credit workflows** (`limit_increase`, `prequalification`): the classifier only routes. Eligibility stays in a separate policy service (B7a).

## Experimentation

The goal is evidence for D4.6–D4.10, not a performance target. Following the current team rule, no numeric targets are set until the system is stable. The offline comparison makes no LLM calls except the LLM reference column, which `nlu_eval.py` already produces.

### Candidates (model selection)

| ID | Representation | Classifier | Why it is a candidate |
|---|---|---|---|
| C0 | — | majority class | Floor |
| C1 | keyword rules (`keyword_nlu`) | — | **Baseline** (existing, ADR-005) |
| C2 | TF-IDF char 2–5-grams | logistic regression | Robust to typos and accents, tiny, no model download |
| C3 | multilingual sentence embeddings (two small models, e.g. `multilingual-e5-small`, `paraphrase-multilingual-MiniLM-L12-v2`, ONNX via `fastembed`, no torch) | logistic regression | Handles paraphrase and ES/PT transfer |
| C4 | same embeddings as C3 | k-nearest neighbours | New examples work without retraining (relevant to R4) |
| Ref | `nlu@v4` on Sonnet 5.5 | — | **Ceiling**, not a competitor: the system we fall back from |

C2–C4 tune only a small grid (regularization, k, n-gram range) with cross-validation on the training set. The selected model is the simplest one within the CI of the best on validation.

### Splits (leakage prevention, D4.8)

- **Train / validation:** grouped by `family`, so paraphrases of one sentence never sit on both sides (GroupKFold). Validation is used for model selection and thresholds only.
- **Test:**
  - **Dev:** `eval/nlu/nlu_v1_smoke.yaml` plus first-turn items from the dev scenarios (`derive_suite_items`). Used during development.
  - **Held-out:** first-turn items from the frozen held-out scenarios. Run **once**, on the frozen commit, like the D7 held-out run. Never used for tuning.
- **Locale slice:** at least one locale is held out of training once, to measure ES → PT and MX → AR transfer.

### Metrics and threshold (D4.9)

- **Intent:** macro-F1 and exact-set match, with 95% CIs: Wilson for rates (`eval/harness/metrics.py`), bootstrap for macro-F1.
- **Status:** accuracy, plus **out-of-scope recall** and **in-scope false-abstain rate** (a supported request wrongly declined).
- **Results per slice:** locale, multi-intent, negation, short answer.
- **Calibration:** reliability curve. The confidence threshold is picked on validation to keep wrong side-effect intents low. A wrong `card_block` costs more than a clarification. The rationale is written down with the chosen value.
- **Operational:** p50/p95 latency on CPU, model size, startup time, and cost (zero per call).

### Tracking (K6)

- Each training run writes a run record to `ml_runs/` or `eval/reports/`. Location: Q1. The record holds:
  - data version and hash
  - label-set version
  - candidate and hyperparameters
  - seed
  - metrics
  - the confusion matrix
- MLflow is not required. A JSON + Markdown report per run, like the eval reports, is enough.
- A short model card covers data, intended use (degraded mode only), limits and the chosen threshold.

### Error analysis (D4.10)

- Failure categories with examples: confusable pairs, regional terms, negation, multi-intent, very short messages, PT/ES mixing.
- Each category gets a decision: add data, add a lexicon rule, or accept and route to `ambiguous`.

### End-to-end check of degraded mode

- With `LLM_DISABLED=true`, or a fault-injected `LLMError` (the D6-A fault hooks), a smoke subset of dev scenarios runs on the proposed system. The subset is small, per the team rule.
- It reports which cases are still resolved safely, which hand off, and **0 unsafe outcomes**.
- Compared with today's behavior (everything hands off), it is a direct before/after for D5.

## Expected report (mock)

> **Illustrative only.** Every number below is invented to show the layout and how the systems are read side by side. Nothing has been run. The real report is written per run to `eval/reports/<run_id>/nlu_classifier.md` + `.json`, with `figures/` (calibration curve, one confusion matrix per system) and the full list of misses alongside.

**Intent classifier report — run 20261002t1530**

Commit `abc1234` · data `intent-data@v1` (sha256 `3f9a…`) · label set `v1` (26 intents + 7 scope topics) · seed 42
Selected model `intent_clf@v1` = C3a (e5-small + LR, C=4) · τ = 0.55
Test set: dev (n = 56: smoke 20 + scenario first turns 36). Held-out: not run.

### 1. Training data

| Locale | Utterances | Families | Intents covered |
|---|---|---|---|
| es-mx | 410 | 118 | 33/33 |
| es-co | 395 | 112 | 33/33 |
| es-ar | 388 | 109 | 33/33 |
| pt-br | 402 | 115 | 33/33 |

Origin: written 62%, paraphrased + audited 38%. Leakage check: 0 matches against dev / held-out.

### 2. Model selection (grouped 5-fold CV on training data)

| ID | Model | Macro-F1 (CV, mean ± sd) | p95 latency CPU | Size |
|---|---|---|---|---|
| C0 | majority | 0.03 ± 0.00 | <1 ms | — |
| C2 | TF-IDF char 2–5 + LR | 0.81 ± 0.03 | 2 ms | 4 MB |
| C3a | e5-small + LR | 0.87 ± 0.02 | 11 ms | 120 MB |
| C3b | MiniLM-L12 + LR | 0.86 ± 0.03 | 14 ms | 470 MB |
| C4 | e5-small + kNN (k=5) | 0.83 ± 0.03 | 12 ms | 122 MB |

Selected: C3a. C3b is within its CI but four times larger; C2 is smaller but outside the CI.

### 3. Threshold

Reliability curve: `figures/calibration.png`. Cost rule (to be fixed in the spec): wrong side-effect intent = 5, wrong read-only intent = 2, clarification = 1.

Counts are out-of-fold over the 1,595 training utterances.

| τ | Coverage (not ambiguous) | Wrong side-effect intents (×5) | Wrong read-only intents (×2) | Clarifications (×1) | Total cost |
|---|---|---|---|---|---|
| 0.40 | 97.5% | 14 | 30 | 40 | 170 |
| **0.55** | **94.4%** | **6** | **14** | **90** | **148** |
| 0.70 | 86.8% | 3 | 6 | 210 | 237 |

### 4. Comparison on dev (n = 56, same items, same scorer)

| System | Macro-F1 | Exact-set match [95% CI] | Status acc. [95% CI] | OOS recall | False abstain | p50 / p95 ms | Cost / call |
|---|---|---|---|---|---|---|---|
| Majority (`card_status`) | 0.04 | 14.3% [7.4, 25.7] | 64.3% [51.2, 75.5] | 0.0% | 0.0% | <1 / <1 | $0 |
| keyword_nlu (baseline) | 0.61 | 57.1% [44.1, 69.2] | 87.5% [76.4, 93.8] | 70.0% | 8.3% | <1 / 1 | $0 |
| **intent_clf@v1** | **0.84** | **80.4% [68.2, 88.7]** | **91.1% [80.7, 96.1]** | **90.0%** | **4.2%** | **6 / 11** | **$0** |
| Sonnet 5.5 (reference) | 0.97 | 94.6% [85.4, 98.2] | 96.4% [87.9, 99.0] | 100.0% | 2.1% | 1340 / 2910 | $0.0160 |

Paired test, classifier vs. keyword (exact-set): classifier right and keyword wrong = 15, the reverse = 2, McNemar p = 0.002.

**4b. F1 per intent (dev)**

| Intent | n | keyword_nlu | intent_clf@v1 | Sonnet 5.5 |
|---|---|---|---|---|
| `card_status` | 8 | 0.71 | 0.88 | 1.00 |
| `balance_due` | 6 | 0.55 | 0.83 | 1.00 |
| `decline_explain` | 5 | 0.80 | 0.91 | 1.00 |
| `card_block` | 7 | 0.67 | 0.86 | 0.93 |
| `card_unlock` | 3 | 0.50 | 0.80 | 1.00 |
| `unrecognized_charge` | 6 | 0.92 | 0.92 | 1.00 |
| `replacement_request` | 4 | 0.57 | 0.75 | 1.00 |
| `transaction_search` | 3 | 0.40 | 0.67 | 0.86 |
| `human_request` | 3 | 1.00 | 1.00 | 1.00 |
| `affirm` / `deny` | 5 | 0.33 | 0.89 | 1.00 |
| out of scope (all topics) | 6 | 0.70 | 0.90 | 1.00 |
| **Macro** | **56** | **0.61** | **0.84** | **0.97** |

Read: keyword ties the classifier on fixed phrases (`unrecognized_charge`, `human_request`) and loses most on varied wording (`affirm` / `deny`, `balance_due`).

**4c. Confusion matrix, intent_clf@v1 (dev)**

Rows are the gold intent, columns the prediction. The keyword and LLM matrices are in `figures/`.

| gold ↓ / pred → | status | balance | decline | block | unlock | unrec. | repl. | tx_search | OOS | ambiguous |
|---|---|---|---|---|---|---|---|---|---|---|
| `card_status` | **7** | 1 | | | | | | | | |
| `balance_due` | 1 | **5** | | | | | | | | |
| `decline_explain` | | | **5** | | | | | | | |
| `card_block` | | | | **6** | 1 | | | | | |
| `card_unlock` | | | | | **3** | | | | | |
| `unrecognized_charge` | | | | 1 | | **5** | | | | |
| `replacement_request` | | | | 1 | | | **3** | | | |
| `transaction_search` | | | | | | | | **2** | | 1 |
| out of scope | | | | | | | | | **5** | 1 |

A miss in the **ambiguous** column is safe: the bot asks instead of acting. Misses between side-effect intents (`card_block ↔ card_unlock`, `unrecognized_charge → card_block`) are the ones to fix first.

### 5. Results per locale and per item type (exact-set match)

| Slice | n | keyword_nlu | intent_clf@v1 | Sonnet 5.5 |
|---|---|---|---|---|
| es-mx | 15 | 60.0% | 86.7% | 93.3% |
| es-co | 14 | 57.1% | 78.6% | 92.9% |
| es-ar | 13 | 46.2% | 69.2% | 92.3% |
| pt-br | 14 | 64.3% | 85.7% | 100.0% |
| negation | 6 | 33.3% | 66.7% | 100.0% |
| multi-intent | 5 | 40.0% | 60.0% | 80.0% |
| short answer | 5 | 20.0% | 80.0% | 100.0% |

Locale transfer (es-ar removed from training, then tested on es-ar): 61.5%.

### 6. Where it fails

| Category | Count | Example (masked) | Decision |
|---|---|---|---|
| Regional term | 3 | "me clonaron la tarjeta" → `card_block` (gold `unrecognized_charge`) | add es-ar data |
| Confusable pair | 2 | "ya la puedo volver a usar?" → `card_status` (gold `card_unlock`) | add hard negatives |
| Multi-intent | 2 | "bloqueala y mandame otra" → `card_block` only (gold + `replacement_request`) | clause split (Q6) |
| Negation | 2 | "no la quiero cancelar, solo pausarla" → `card_block` permanent | lexicon qualifier rule |
| Very short | 2 | "eso" → `ambiguous` | accept (clarify) |

### 7. Degraded mode, end to end (LLM forced to fail, n = 8 dev cases)

| | Today (handoff on LLM failure) | Degraded mode |
|---|---|---|
| Resolved safely | 0/8 | 6/8 |
| Handed off | 8/8 | 2/8 (1 `transaction_search`, 1 ambiguous twice in a row) |
| Unsafe outcomes | 0 | 0 |

### 8. Caveats

- Labels are team-generated and synthetic (B2).
- n = 56, so the CIs are wide. The paired test is the stronger evidence for classifier vs. keyword.
- The LLM reference runs without a fixed temperature (ADR-031).
- Degraded-mode replies are template-worded. This report scores routing, not wording.

## Done when

1. The classifier trains from the team data with one command. The same data and seed give the same model and the same metrics.
2. The offline comparison reports C0–C4 and Ref on the dev test items, with CIs and per-locale results, and the selected model and threshold are justified in writing. The report follows the layout in "Expected report (mock)".
3. On the no-LLM path, ES and PT happy paths pass with a fake LLM that always raises `LLMError`: card status, lock via buttons, `affirm` / `deny` on a pending question, abstain on Pix. Today's handoff remains for `transaction_search`.
4. A degraded turn never writes without a confirmation token and never says "done" without a read-back (R2, R3 tests).
5. The leakage check (training vs dev/held-out) and the registry-coverage check run in `make check`.
6. The README "where AI is used" section and the model card describe the component and its limits.

## Out of scope

- Using the classifier when the LLM is up (as a scope gate or as a cross-check on side-effect intents). These are roles 2 and 3, a separate decision.
- Replacing `understand` or changing `nlu@v4`.
- Slot extraction by the classifier.
- Training on dataset fields (`detected_intents`, `contact_reason`).

## Open questions

- **Q1 · Location.**
  - Inference: proposed `backend/app/domains/conversation/classifier/`.
  - Training, data and run records: proposed a top-level `ml/intent/` with data in `ml/intent/data/`, or under `eval/`.
  - Does the model file get committed (a few MB for C2) or built by `make`?
- **Q2 · Kill switch.** Should `LLM_DISABLED` switch to degraded mode, or keep handing off as ADR-023 decided? Degraded mode under the switch is the simplest demo of R2.
- **Q3 · Customer notice.** In degraded mode, does the reply say that Cardy is in basic mode, and does the UI show a banner?
- **Q4 · Data effort.** Who writes the utterances, how many per intent and locale (proposed 30–50), and are audited LLM paraphrases allowed?
- **Q5 · New workflows.** Which ones are planned: the Stretch card intents, or new domains (accounts, loans)? This decides one-stage vs two-stage classification and the label-set plan.
- **Q6 · Multi-intent.** Reuse the `keyword_nlu` clause split and classify per clause (proposed), or train a multi-label model?
- **Q7 · Mid-conversation recovery.** When the LLM comes back, does the next turn return to the normal path automatically (proposed), or does the conversation stay degraded until it ends?
