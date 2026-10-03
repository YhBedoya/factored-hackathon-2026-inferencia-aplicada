# State: REQ-learned-intent-fallback — learned intent classifier + LLM-free degraded mode
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-learned-intent-fallback (source `docs/requirements/learned-intent-fallback.md`, owner A) · spec `docs/specs/learned-intent-fallback.md` · plan `docs/plans/learned-intent-fallback.md`
Branch `feat/learned-intent-fallback`, based on `develop`.

## Conventions established for this card
- Full repo facts: plan §"Facts checked against the repo". Read the bullets relevant to your files.
- **Binding cross-task names and contracts** (Registry, Graph, Degraded semantics, classifier via `config["configurable"]["classifier"]`, Shared parsing seams, Classifier package, Bundle, Settings `intent_model_dir`, Docker, Make targets, Run records, ml import rule, `ml` group, D10 negation) live in the plan under **"Planned names that cross tasks"**, lines 111–168: `sed -n 111,168p docs/plans/learned-intent-fallback.md`. When a task block says "in the state file" for one of these, read it there. If you use a different real name, record it in your Task log entry.
- `ml/` is new; `ml/intent/data/` must be re-included past the bare `data/` ignore; the fixture lives at `ml/intent/tests/fixtures/dataset/`; `ml/intent/models/` is git-ignored. No model artifact is ever committed.
- The `ml` dependency group (sklearn, fastembed, onnxruntime, joblib) is dev-only until T29 moves the winner's deps to runtime. The new packages need mypy `ignore_missing_imports` overrides.
- `_INTENT_NODES` rebuilt from the registry must equal today's literal; `human_request`/`general_question` have `node: null`.
- The `_entry` `llm_unavailable` → fallback shortcut STAYS for the classifier-not-loaded path.
- Baseline nodes are imported lazily (import cycle), and the degraded swaps must do the same.
- Requirement items are REQ-R1..R4; R1–R13 always mean the 06 safety rules.
- Tests use a fake LLM only; no Anthropic/Bedrock/gpt-6-luna calls, except in LIVE tasks.

## Human decisions taken mid-card
- (spec) Card-picker parse reads `•••• NNNN`, built next to `mask_card`; block_kind chips are matched exactly to the flow's labels; `make eval FAULTS=` → `--faults` merge.
- (plan) T28's live comparison uses seeds only: 20 smoke + 36 seed = 56 items.
- (plan) D10 negation: drop a clause's prediction only when every keyword hit for the predicted label is inside the negation window; no hit → keep.
- T16 gap: add T33 so `abstain` marks degraded when its own LLM call fails (human chose fix task).
- T23: `degraded` keeps its per-turn meaning. It is True only when the turn used the fallback (an LLM call failed, or the kill switch is on). A template-only button turn stays False. No code change; the spec and plan wording "every turn is True" is corrected at the end.
- T34/T35 (human, during the audit): the `negation` and `hard_negative` slots are redefined so their items express the cell's class (`intent_gen@v2`). v1 stamped the cell's class on items the prompt said must NOT express it (792 items). Those are retired (`accepted: false`) and regenerated.
- T35 (human): "In general is ok, just fix the hard negatives, and go ahead, I didnt mark every sample take it as accepted". Read as: regenerate both redefined slots; every unmarked v1 item in the other slots is set to `accepted: true`. New v2 items stay null until the human says. CORRECTION (human): the audit of the v1 items was total. The human read every item and only skipped setting the flag on each one. Do not describe the audit as partial in the report or model card.
- T35 follow-up (human): accept all 792 v2 negation/hard_negative items without reading them (the report and model card must say these 792 were not human-read). Reject and regenerate the 3 eval leaks and the extra copies of the 30 duplicate texts; the human reviews the replacements.
- T35/T36 (human): generation stopped at 44 of 45 replacements, all 44 accepted. The human chose to allow cross-file duplicate texts and one cell at 29 (es-mx/unrecognized_charge). Final data: 2,639 accepted, 837 rejected. The same text can sit in two CV groups, so reported CV scores are slightly optimistic: say so in the report limitations (T32).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a253750 | ml group + ignores + 2 embedding models cached (e5-small custom-registered) |
| T2 | done | a41e14d | intents.yaml (26 rows) + registry; graph tables from registry; degraded state/debug; llm_unavailable→fallback (before empty-queue check) |
| T3 | done | a25a370 | CARD_MASK_RE/parse_card_mask; public chip labels; split_clauses/qualified_block_kind/lexicon_hits |
| T4 | done | a3da5cd | ml skeleton, data_io, fixture 6 files/90 items |
| T5 | done | a2bf406 | Scorer/Embedder/SklearnScorer; e5 'query: ' prefix added inside Embedder |
| T6 | done | a12dda7 | intent_gen step (openai gpt-6-luna) + intent_gen@v1.md prompt |
| T7 | done | ab7b168 | --faults union in harness; eval FAULTS=, intent-gen/train/compare targets |
| T8 | done | a948821 | bootstrap_ci, mcnemar, dev_items (56/112), predict_items, abstain_rates |
| T9 | done | a44f4eb | dev case → clarified; 5 staging → resolved (required_tools judgment, see notes) |
| T10 | done | a897f03 | ADR-032 + R11/§3 layout + 02/01 D2 wording |
| T11 | done | ad78ffd | 04 audit+escalation v5, 05 learned row, README 'Where AI is used' |
| T12 | done | a326049 | ClassifierAdapter + IntentClassifier + stub; exact chip label wins under block_kind; all-negated → ambiguous |
| T13 | done | ab6d9f6 | generate.py; --plan 88 calls; regen per family reuses 10-family prompt (keeps 1) |
| T14 | done | aca590c | C0–C4 + train.py; fixture CV F1 c2 .96 c3a .99; GroupKFold(shuffle) needs sklearn≥1.6 |
| T15 | done | a0916eb | leakage + check.py; fixture leaks fixed (T4 repair), test asserts no leaks |
| T16 | done | aa775c6 | compose/abstain/handoff_summary baseline swaps when degraded; abstain LLMError doesn't set degraded (open Q) |
| T17 | done | a2c397c | escalation v5 degraded_handoff_intents (list[str]: policy can't import Intent, 06 §2); enforced at enqueue/next_intent |
| T18 | done | ac1b472 | 88 cells x 30 = 2,640 items (660 per locale, 120 per class), all accepted: null; 1 regen (es-mx deny), 4 client timeouts retried |
| T19 | done | a8825d0 | load_classifier (sha256 before unpickle, filter=data, lock at model_dir.parent); null model.lock |
| T20 | done | acce547 | classifier in load_session/understand; D8 ambiguous-twice → clarify_rephrase then handoff; shared _answer_fits |
| T21 | done | ad0a5ae | Settings.intent_model_dir, TurnHost.classifier, lifespan load+log, configurable classifier, nlu_result.source, reply_sent.degraded, OTel cardy.degraded; +admin demo_reset keeps classifier |
| T22 | done | a906d15 | compare.py, report.py, export.py; fixture run --no-ref: intent_clf@v1 = c2, tau 0.7, parity ok over 112 dev items; --lock must be <models-dir>/../model.lock (exit 2 otherwise); compare.py adds backend/ to sys.path |
| T23 | done | afb5f97 | test_degraded.py (R2, R3, ES/PT paths), test_kill_switch_degraded, make_session(classifier=); 14 passed. Open: DebugInfo.degraded False on button turns; reply_sent.degraded not asserted (make_session skips runner) |
| T24 | done | a88fd61 | named context `intent`, build-time sha256 check, --no-group ml, INTENT_MODEL_DIR=/app/ml/intent/models; empty build ok, fake tarball fails build; offline proof via `docker run --network none` (compose run lacks the flag) |
| T25 | done (HUMAN) | | human read all v1 items; 792 v2 items accepted unread; 44 replacements accepted from the list |
| T26 | done | a2d8f78 | `make check` runs ml.intent.check, ml tests, ruff on ml with `--config backend/pyproject.toml` (both rc 0); data coverage test, 5 passed; mutation proofs (leak at 30, cell cut to 28) both exit 1 |
| T27 | done | a5a9c0c | runs train_all_s42 and train_all_s42_b, 2,639 rows, metrics and prediction_hash identical; CV macro-F1: c2 0.9300, c3a 0.9376, c3b 0.8987, c4 0.8385, c1 0.4481, c0 0.0016. Deviation: second run via CLI `--run-id` because `make intent-train` overwrites its run dir |
| T28 | done | a43231b | run compare_s42; winner c2 tau 0.30, sha256 9ecf7a5d…, 2.2 MB, no fastembed/onnxruntime; dev macro-F1 c2 0.65, Ref 0.86; 56 Ref calls, $0.0163. Open: transfer line not run (case mismatch) -> T37; Verify git-status clause fails only because ml/ is untracked |
| T37 | done | a9e5e7d | compare.py transfer block case-insensitive; transfer 3/6 vs 3/6 in-locale; winner c2 tau 0.30 unchanged; bundle now intent_clf@v3 sha256 ce0fb351… (version bumps per run); stale v1 tarball still in models/ |
| T29 | done | a84bb57 | runtime: scikit-learn>=1.6, joblib>=1.4, numpy>=2 (scorers.py imports it); ml group keeps fastembed, onnxruntime, matplotlib; no locked version changed; loads intent_clf@v3 with --no-group ml; 13 passed. Open: sklearn pin vs load-time check |
| T30 | done | ae95be4 | build + sha256 check pass; offline load prints intent_clf@v3 (`docker run --network none`, policies mounted); `intent_classifier.loaded` v3 after make up; tampered tarball fails build; image lacks fastembed/onnxruntime/matplotlib. Not proven: full app lifespan offline. Open: old tarballs left by each compare run break the build |
| T31 | blocked (HUMAN) | a57a5ba | 2 runs, 0 unsafe both; run1 4 resolved + 1 clarified, run2 5 handoff; card_block case (3 variants) not_run in both: driver skips `setup.faults` cases; defects -> T38 |
| T38 | done | ae04a2b | runner.py:435 passes `degraded` to DebugInfo; eval/harness/__main__.py inserts backend/ in sys.path; new test drives the real runner and asserts DebugInfo.degraded and reply_sent.degraded True; 7 passed |
| T39 | done (finding -> T41–T44) | a049d76 | dev card-block case runnable (`faults: []`); both runs 8 played, 0 unsafe; run1 4 resolved, 1 clarified, 3 abstained; run2 8 handoff. Card-block abstains: classifier says `loans` (out_of_scope) for "bloquear mi tarjeta de crédito" |
| T40 | done | a62a5fe | `export.remove_older_bundles`, called at compare.py:509 after parity check and lock write; removes only `intent_clf@v<int>.tar.gz` other than the locked one; 1 test, ml tests 3 passed; failure path covered by code position only |
| T32 | pending | | |
| T33 | done | aec5cd8 | compose_reply_flagged → (text, llm_failed); abstain sets degraded on own LLMError with classifier |
| T34 | done | a3f561a | intent_gen@v2 (negation and hard_negative now express the class); generate.py --retire-slots/--retire-generator-version; temp-copy proof: 9 retired, plan = 3 regen calls; data untouched |
| T35 | done | a7b63a5 | v2 slots regenerated and accepted; dups and leaks replaced (44 of 45, agent stopped by the human); 2,639 accepted, 837 rejected, es-mx/unrecognized_charge at 29; 7 cross-file duplicates remain by decision |
| T36 | done | a386d9b | check.py: same-label cross-file duplicates are WARN, cells pass at 29 or 30; different-label and in-file duplicates still fail; check exits 0 with 7 warnings |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — `ml` dependency group, mypy overrides, ignore rules, model pre-fetch
Created: `ml/intent/models/.gitkeep`; cache `ml/intent/.cache/fastembed/` (706M, git-ignored).
Changed: `backend/pyproject.toml` (`ml` group: scikit-learn>=1.5, fastembed>=0.4, onnxruntime>=1.18, joblib>=1.4, matplotlib>=3.9; `default-groups=["dev","ml"]`; mypy ignore_missing_imports override), `backend/uv.lock`, `.gitignore`.
Facts: model ids `intfloat/multilingual-e5-small` (NOT in fastembed's list, custom-registered) and `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (built in, fastembed pulls the quantized `qdrant/...-onnx-Q`). Both dim 384. Installed sklearn 1.9.1.
Custom registration (must run before constructing it, every process):
`from fastembed.common.model_description import ModelSource, PoolingType`
`TextEmbedding.add_custom_model(model="intfloat/multilingual-e5-small", pooling=PoolingType.MEAN, normalization=True, sources=ModelSource(hf="intfloat/multilingual-e5-small"), dim=384, model_file="onnx/model.onnx")`
Load: `TextEmbedding(m, cache_dir="ml/intent/.cache/fastembed", local_files_only=...)`. e5 needs "query: "/"passage: " prefixes added by us (fastembed does not).
local_files_only proof: second process load of both models with `local_files_only=True` succeeded, embedding dim 384 each.
Deviations: none. uv warns VIRTUAL_ENV mismatch (harmless).
Verify: uv sync + import + `mypy app/core/config.py` → "Success: no issues found"; git check-ignore checks → pass.

### T11 — Docs B: 04, 05, README
Changed: `docs/solution-docs/04-contracts.md` (escalation.yaml v5 + `degraded_handoff_intents`; §6 `reply_sent.degraded`, `nlu_result.source`/`classifier_version`/`label_set_version`), `docs/solution-docs/05-evaluation-plan.md` (Learned component row), `README.md` (new "Where AI is used" section before "1. Prerequisites").
Facts the next tasks need: README links `docs/solution-docs/decision-log.md` (ADR-032, T10) and `ml/intent/MODEL_CARD.md` (not yet written).
Deviations: none.
Verify: the four-grep command → OK.

### T10 — Docs A: ADR-032 and D2 wording
Changed: `docs/solution-docs/decision-log.md` (ADR-032 after ADR-031), `06-engineering-rules.md` (R11 wording, §3 layout adds `ml/intent/` with `conversation/classifier/` and `intents.yaml` noted), `02-conversation-design.md` (§5 intro and "Tool / LLM failure" row), `01-technical-design.md` (§7 cost guard).
Facts the next tasks need: ADR-032 is dated 2026-10-01; each of the four files contains "ADR-032" (checked individually).
Deviations: none.
Verify: the grep command → exit 0.

### T9 — Relabel D23 tool_failure cases
Changed: dev `d-card_block-tool_failure-es-co-01` (outcome `clarified`, required `cards.list_cards`, no handoff fields, automation true, faults kept); five `_staging/heldout/h-*-tool_failure-*` (outcome `resolved`, no handoff fields, automation true, faults kept, header comment citing ADR-032; reviewer/reviewed_at already null).
Facts: required_tools copied from resolved analogues: card_status/balance_due `cards.list_cards`+`cards.get_card_details`; decline_explain/pending_reversal `transactions.search` only (analogue's card tools omitted since degraded path may not need them).
Deviations: `eval/scenarios/heldout/` does not exist yet, so the Verify's `git diff --exit-code eval/scenarios/heldout` (no `--`) errors "unknown revision"; with `--` it passes (rc 0).
Verify: test_scenarios_valid 2 passed; freeze-check OK; reviewer null count 3 per staging file.

### T7 — Eval `--faults` union and Make targets
Changed: `eval/harness/runner.py` (`fault_groups(cases, extra_faults=frozenset())`; `run(..., faults=frozenset())` threaded via `_run_all`/`_run_system`), `eval/harness/__main__.py` (`--faults a,b`, validated against `Fault`, `ap.error` on unknown), `eval/tests/test_runner_faults.py` (`test_cli_faults_merge`), `Makefile` (`eval` gains `$(if $(FAULTS),--faults $(FAULTS))`; new `intent-gen`, `intent-train`, `intent-compare`, added to `.PHONY`).
Facts: recipes call `uv run --project backend python -m ml.intent.{generate,train,compare}`; `intent-gen` passes `--locale`/`--class` only when set.
Deviations: none.
Verify: pytest 2 passed; the three `make -n` greps and ruff check pass.

### T4 — `ml` skeleton, data contract loader, fixture dataset
Created: `ml/__init__.py`, `ml/intent/__init__.py`, `ml/intent/tests/__init__.py`, `ml/intent/data_io.py`, `ml/intent/tests/fixtures/dataset/{es-ar,pt-br}/{card_block,card_status,loans}.yaml`.
Facts the next tasks need: `DataFile.class_` holds the YAML key `class` (Python keyword); `load_files`/`write_file` map it. `DataItem.accepted: bool | None`. `data_io` exports `BACKEND_ROOT`, `LOCALES`, `SLOT_MIX`, `load_files`, `accepted_items`, `data_sha256`, `write_file`, and inserts `backend/` into `sys.path`. `write_file` uses `yaml.safe_dump(sort_keys=False)`. Fixture slots per cell: plain, plain, regional, regional, typo_informal (5 families x 3).
Deviations: none.
Verify: fixture load → 6 files, 90 accepted, sha256 33f802fe...d520; ruff check and format --check pass.

### T5 — Classifier scorers (embedder + sklearn head)
Created: `backend/app/domains/conversation/classifier/__init__.py` (exports `Scorer`), `classifier/scorers.py` (`Scorer`, `Embedder`, `SklearnScorer`).
Facts the next tasks need: `Embedder(model_name, cache_dir).embed(texts)` is lazy (model loads on first call), `local_files_only=True`, registers e5 itself (ignores repeat-registration ValueError) and adds the `"query: "` prefix for e5 only, so callers pass raw text. `SklearnScorer(estimator, labels, embedder=None)` feeds raw texts to the estimator when no embedder (Pipeline case); `labels` must match the estimator's `classes_` order. numpy/sklearn/fastembed imported inside functions only.
Deviations: none.
Verify: task Verify → assert passed, ruff check/format clean, mypy "no issues in 2 source files", lint-imports 4 kept 0 broken.

### T3 — Shared parsing seams
Changed: `localization/format.py` + `__init__.py` (`CARD_MASK_RE = r"•{4} (\d{4})"`, `parse_card_mask`), `flows/card_block.py` (public `TEMPORARY_LOCK_LABEL`, `PERMANENT_BLOCK_LABEL`), `baseline/keyword_nlu.py` (`split_clauses`, `qualified_block_kind`, `lexicon_hits`; `keyword_nlu` uses them).
Facts: `lexicon_hits(clause, key)` expects an already-normalized clause (from `split_clauses`), returns [] for an unknown key, and never reports negation for negation-exempt keys (same as `keyword_nlu`). `qualified_block_kind` normalizes its own input. `CARD_MASK_RE` has one capture group (the digits).
Deviations: none.
Verify: pytest baseline/format/block_flows → 20 passed; parse_card_mask assert, ruff check/format, mypy → clean.

### T6 — intent_gen eval-only step and prompt
Changed: `backend/app/core/llm/registry.py` (`Step` + `MODEL_REGISTRY`/`TEMPERATURE`/`STEP_PROVIDER` entries for `intent_gen`, openai gpt-6-luna, 1.0, ADR-032 comments).
Created: `ml/intent/prompts/intent_gen@v1.md` (placeholders `{locale}`, `{class_name}`, `{class_description}`, `{slots}`; output JSON `{"families":[{"slot","seed","paraphrases":[2]}]}`, 10 entries in slot order).
Facts the next tasks need: slot names in the prompt are plain, regional, typo_informal, hard_negative, negation, short_answer; generate.py must fill the braces and parse that JSON.
Deviations: none.
Verify: pytest 6 passed (one earlier run hit T3's mid-edit `format.py` NameError, transient); registry assert, ruff, format, mypy, test -s all OK.

### T8 — Eval metrics for the classifier report
Changed: `eval/harness/metrics.py` (`bootstrap_ci`, `mcnemar`), `eval/harness/nlu_eval.py` (`dev_items`, `predict_items`, `abstain_rates`, `DEV_DIR`; exported in `__all__`).
Facts the next tasks need: `bootstrap_ci` statistic gets the resampled index list; `mcnemar` returns `{b, c, p}` (b = only A right). `dev_items(seeds_only=True)` = 56, False = 112 (T9 relabel did not change the count). `abstain_rates` returns `{oos_recall, false_abstain}` Rate dicts; in-scope = items with a status label that isn't out_of_*. `predict_items` maps exceptions to None.
Deviations: none.
Verify: pytest test_metrics+test_nlu_eval → 2 passed; python check OK (56/112); ruff check clean.

### T2 — Intent registry, registry-built tables, `degraded` field, D7 dispatch edge
Created: `backend/app/domains/conversation/intents.yaml` (26 rows, `label_set_version: 1`), `intent_registry.py` (`IntentRow`, `Registry`, `load_registry`, `classifier_labels`, `intent_nodes`, `management_intents`), `backend/tests/unit/test_registry_consistency.py` (4 tests).
Changed: `graph.py` (tables from registry via `cast`; `GraphState.degraded`; `DebugInfo.degraded=False` filled from final state; `_dispatch` returns "fallback" on `llm_unavailable`, checked BEFORE the empty-queue check; `"fallback"` added to the `enqueue` and `next_intent` maps), `docs/diagrams/turn-graph-v0.mmd` regenerated.
Facts: all 15 core+management rows are `classifier: true` (training_dir `ml/intent/data`); lexicon_key is set for the 11 intents present in `baseline/lexicon.yaml`, null for pending_reversal_explain, general_question, affirm, deny and stretch. Scope topics come from `get_policies().scope.topics` (file order, pix_boleto first).
Deviations: none.
Verify: full Verify chain → 6 passed; ruff check/format clean, mypy clean, lint-imports 4 kept.

### T16 — Degraded swaps in compose, abstain, handoff_summary
Changed: `nodes/compose.py` (`compose`), `nodes/abstain.py` (`abstain`), `nodes/handoff_summary.py` (`handoff_summary`).
Facts the next tasks need: gate is `config["configurable"].get("classifier") is not None`; `state["degraded"]` true -> lazy-imported `baseline_compose`/`baseline_abstain`/`baseline_handoff_summary`, no LLM call. `compose` and `handoff_summary` on `LLMError` return the baseline result + `"degraded": True` (with a classifier); no classifier -> unchanged.
Deviations: `abstain` has no LLMError branch to mark degraded, because `compose_reply` (untouched per task) already swallows `LLMError` into the fixed template; abstain swaps only on `state["degraded"]`. Under LLM_DISABLED without `degraded` set, handoff_summary keeps its existing early return.
Verify: 19 passed; ruff check/format, mypy (13 files), lint-imports 4 kept 0 broken.

### T17 — D7 degraded_handoff_intents
Changed: `backend/app/domains/policy/escalation.py` (`degraded_handoff_intents: list[str] = []`), `policies/escalation.yaml` (version 5, key + ADR-032 comment), `backend/app/domains/conversation/nodes/next_intent.py` (`_degraded_handoff` helper; `enqueue` checks the new queue head, `next_intent` the head after the pop; both set `escalation_reason="llm_unavailable"`).
Facts the next tasks need: no new test covers this branch (none named in the task).
Deviations: field typed `list[str]`, not `list[Intent]`, because `policy` must not import `app.domains.conversation` (06 §2); values are Intent names.
Verify: 20 passed; policy assert ok; ruff check/format clean; mypy clean.

### T12 — Classifier adapter, stub helper, contract test
Created: `classifier/adapter.py` (`IntentClassifier`, `ClassifierAdapter`), `backend/tests/stub_classifier.py` (`StubScorer(mapping)`, `make_stub_classifier(mapping, tau=0.5)`), `backend/tests/unit/test_classifier_contract.py` (8 tests).
Changed: `classifier/__init__.py` (exports `ClassifierAdapter`, `IntentClassifier`, `Scorer`).
Facts the next tasks need: `ClassifierAdapter.version`/`.label_set_version` are public attrs. A single clause is scored on the original text, multi-clause on the normalized clauses. `StubScorer` keys on exact scored text; unknown text gets a flat (below-τ) distribution. An exact chip label under `awaiting_slot="block_kind"` returns `["card_block"]`, `clear`, with `block_kind`, regardless of scores. `country`/`previous_language` are accepted but unused (D9: language from `_guess_language` alone). When all clauses are dropped or below τ, result is `ambiguous` (not keyword_nlu's out_of_scope/other).
Deviations: none. Bundle stale-version/sha256 cases of `test_classifier_contract` belong to the loader (T19), not this task.
Verify: pytest 8 passed; ruff check/format clean; mypy classifier 3 files clean; lint-imports 4 kept 0 broken.

### T14 — Candidates C0–C4 and `ml/intent/train.py`
Created: `ml/intent/candidates.py` (`CANDIDATES` dict c0,c1,c2,c3a,c3b,c4; `Candidate(name, description, grid, build, embedding_model)`; `keyword_label`, `NO_MATCH="unrecognized"`), `ml/intent/train.py`.
Facts the next tasks need: label = `intents[0]` else `topic` else file class. Labels sorted. Folds: `GroupKFold(5, shuffle=True, random_state=seed)` by family. Embeddings cached per model in `Features`; cache dir `ml/intent/.cache/fastembed`. Best grid point = max CV macro-F1 (first of ties). τ grid 0.05..0.95, ties go to higher τ; cost counted on the predicted intent (5 side-effect / 2 read-only), abstain = 1.
`train.json` single candidate: data_version, data_sha256, label_set_version, seed, n_items, candidate, hyperparameters, embedding_model, metrics{grid[{params,cv_macro_f1_mean,cv_macro_f1_sd}],best_params,cv_macro_f1_mean,oof_macro_f1,oof_accuracy,tau,tau_cost,tau_abstain_rate}, prediction_hash, confusion_matrix{rows,cols,matrix}.
With `--candidate all` (default run-id `train_<cand>_s<seed>`): top-level `metrics`/`hyperparameters`/`confusion_matrix` are dicts keyed by candidate, `prediction_hash` combines them, full per-candidate records under `candidates`. Fixture CV F1: c0 .12, c1 .37, c2 .96, c3a .99, c3b .94, c4 .89.
Deviations: none.
Verify: two runs identical (same), ruff check + format --check clean.

### T15 — Leakage check and `test_leakage`
Created: `ml/intent/leakage.py` (`normalize`, `eval_texts`, `find_leaks`), `ml/intent/check.py` (`problems(data_dir, per_cell)`, CLI `--data-dir --per-cell`), `ml/intent/tests/test_leakage.py`.
Facts: `eval_texts()` uses `load_dir` (returns [] for a missing dir) plus `eval/nlu/*.yaml` `text`; `find_leaks` returns (train, eval) pairs equal after `normalize`. `check.py` also flags duplicate training texts and prints `FAIL <reason>` lines to stderr, rc 1.
Deviations: T4's fixture is NOT leak-free: es-ar card_block "necesito bloquear mi tarjeta" and es-ar card_status "¿mi tarjeta está activa?" equal dev/smoke texts. Not my file, so `test_leakage` compares against that baseline instead of asserting an empty list. Verify's `git diff --exit-code eval/` replaced by `git status --porcelain -- eval/` before/after (identical).
Verify: pytest 1 passed; `check` on fixture rc=1 (85 problems); ruff check/format clean.

### T13 — `ml/intent/generate.py`
Created: `ml/intent/generate.py` (`plan_cell(file) -> (missing family idx, regen family idx)`, `fill_cell`, CLI `--locale --class --data-dir --plan`).
Facts the next tasks need: `app.*` is imported inside functions (ruff isort would otherwise put it before the `data_io` sys.path insert). A cell with 0 items or families absent gets ONE full 10-family call and only the absent family indices are kept (fixture top-up = 1 call, "new 5"). A family with <3 live items (rejected or hygiene-dropped) gets one call each: prompt slots = that family's slot x10, only the first family is used (prompt is fixed at 10 families). Dedupe by casefolded text within the cell. Scope classes: `intents: []`, status = scope kind, `topic`=class. Default data dir `ml/intent/data`. Plan summary last line: `88 cells, would make 88 call(s)`.
Deviations: none. Regeneration of rejected items is not exercised live (T18).
Verify: plan on empty dir -> "88 cells, would make 88 call(s)"; fixture es-ar card_block -> "1 call(s) (new 5, regen 0)"; ruff check and format --check clean.

### T4 repair 1 — fixture items no longer copy eval text
Changed: `ml/intent/tests/fixtures/dataset/es-ar/card_block.yaml` and `card_status.yaml` (one item each reworded; class, family, slot unchanged).
Facts: new `data_sha256` of the fixture is ad7d8db664d6e83dd8e8842b7ef19c93ef5fded8f486379d70d8199dd3f88cc3 (supersedes 33f802fe...).
Verify: original Verify → 6 files, 90 accepted; `find_leaks(...)` → `[]`.

### T15 repair 1 — clean-fixture assertion
Changed: `ml/intent/tests/test_leakage.py` now asserts `find_leaks(fixture, eval_texts()) == []` (T4 reworded the two leaking items) and still checks the injected case/accent-mangled dev text is flagged.
Verify: pytest 1 passed; check on fixture rc=1; ruff clean; `git status -- eval/` unchanged.

### T33 — abstain marks degraded on its own LLMError
Created: `compose_reply_flagged(...) -> tuple[str, bool]` in `nodes/compose.py` (text identical to `compose_reply`; flag = LLMError raised). `compose_reply`/`compose_checked` untouched.
Changed: `nodes/abstain.py` (`_abstain` now returns `(update, llm_failed)`; `abstain` adds `"degraded": True` only with a classifier loaded; `make_abstain`/baseline ignores the flag), `tests/unit/test_abstain.py` (one parametrized test: classifier -> degraded True, no classifier -> key absent).
Facts the next tasks need: the T16 gap is closed; a degraded abstain reply is still the same `abstain_fallback` text.
Deviations: new helper instead of changing `compose_reply`'s signature (zero effect on existing callers).
Verify: 12 passed; ruff check/format clean; mypy 2 files clean.

### T19 — Bundle loader with refuse-to-load checks
Created: `classifier/loader.py` (`load_classifier(model_dir) -> (IntentClassifier | None, reason)`; reason `"ok"` on success), `ml/intent/model.lock` (null placeholder).
Changed: `classifier/__init__.py` (exports `load_classifier`), `tests/unit/test_classifier_contract.py` (+3 tests, helper `_build_bundle(root, label_set_version=, sha256=)`; now 11 tests).
Facts the next tasks need: lock read at `model_dir.parent/"model.lock"`. Order: lock -> tarball exists -> sha256 -> lock label_set_version vs registry -> extract (`filter="data"`, private mkdtemp removed at exit, kept alive because Embedder reads lazily) -> manifest label_set_version, labels ⊆ `classifier_labels()` -> joblib. Corrupt bundle (OSError/ValueError/KeyError/TarError) returns a reason, never raises. Labels order for the scorer = `manifest["labels"]`. Embedder cache dir = `<tmp>/embeddings`. Bundle `manifest` needs keys model_id, tau, labels, label_set_version, embedding_model.
Deviations: none.
Verify: pytest 11 passed; empty models dir prints "model.lock missing or unreadable"... (lock placeholder has null version -> "model.lock has no pinned version"); ruff check/format clean, mypy 4 files clean, lint-imports 4 kept 0 broken.

### T20 — Degraded NLU: classifier in understand/load_session, D8 in route/smalltalk
Changed: `nodes/load_session.py` (`degraded` = kill switch and classifier; `llm_unavailable` only with no classifier), `nodes/understand.py` (`_classify` helper; degraded or LLMError+classifier -> `classifier.predict`, LLMError path returns `degraded: True`), `nodes/route.py` (degraded+`clarification_exhausted` -> handoff_summary; degraded ambiguous w/o clarification and no fitting answer -> smalltalk; `_answer_fits` now accepts `pending=None`), `nodes/smalltalk.py` (degraded ambiguous no-intents -> `clarify_rephrase`), `templates.py` (`clarify_rephrase` es/pt, TemplateKind).
Facts the next tasks need: `understand` imports `_answer_fits` from `route` (shared fit rule). Counter: 1st ambiguous miss sets `clarification_failures=1`; 2nd sets `escalation_reason="clarification_exhausted"` and counter 0; any other degraded result writes 0. Runs of route never emit a new target.
Deviations: none. Existing test_faults tests (no classifier) pass unchanged.
Verify: 21 passed; ruff check/format, mypy (14 files), lint-imports 4 kept 0 broken.

### T21 — Runtime wiring
Changed: `core/config.py` (`Settings.intent_model_dir`), `.env.example` (commented `INTENT_MODEL_DIR`), `hosting.py` (`TurnHost.classifier`, `open_host(..., classifier=None)`), `main.py` (`_lifespan` calls `load_classifier`, logs `intent_classifier.loaded`/`.unavailable`(error)), `runner.py` (`configurable["classifier"]`, `degraded` tracked from any node update, `_nlu_source` adds `source`/`classifier_version`/`label_set_version` to `nlu_result`, `reply_sent.degraded` always, OTel `cardy.degraded` bool set before the message publish).
Facts the next tasks need: `nlu_result.source` is "classifier" only when the understand update had degraded True and a classifier is loaded.
Deviations: none. OPEN GAP: `backend/app/api/v1/admin.py` `demo_reset` reopens the host via `open_host(...)` without `classifier=old_host.classifier`, so a demo reset silently drops the classifier. Not in T21's Files; needs a one-line fix there.
Verify: 6 passed; ruff check/format clean; mypy 160 files clean; lint-imports 4 kept 0 broken.

### T21 addendum — demo_reset keeps the classifier
Changed: `backend/app/api/v1/admin.py` (`demo_reset` passes `classifier=old_host.classifier` to `open_host`). Closes the gap noted in T21.
Verify: ruff check/format clean, mypy 160 files clean; no existing demo-reset test.

### T23 — Degraded-mode safety and happy-path tests
Created: `backend/tests/unit/test_degraded.py` (`test_degraded_write_needs_token[missing|stale|replayed]`, `test_degraded_done_requires_readback`, `test_degraded_paths[es|pt]`; `_DownLLM` raises `LLMUnavailable`).
Changed: `backend/tests/conftest.py` (`make_session(classifier=None)` -> `configurable["classifier"]`; autouse `_empty_intent_model_dir`), `backend/tests/unit/test_faults.py` (`test_llm_disabled_every_turn_falls_back` renamed `test_kill_switch_degraded`, new stub-classifier leg (0); old no-classifier legs kept).
Facts: a button confirmation turn runs no NLU, so `DebugInfo.degraded` is False there; typed turns assert True. `run_turn` writes no audit, so `reply_sent.degraded` (runner.py) is not asserted. "missing token" = bare "si" with no plan pending.
Deviations: reply_sent audit assertion omitted (needs the runner/host, outside make_session).
Verify: 14 passed; ruff check/format clean.

### T22 — compare, report, export
Created: `ml/intent/compare.py` (CLI; `select_winner`, `slice_flags`), `ml/intent/report.py` (`write_report(results, out_dir)`, `render_markdown`; Agg backend), `ml/intent/export.py` (`export_bundle`, `next_version`, `head_bytes`, `embedding_bytes`).
Facts the next tasks need: compare requires `--lock == <models-dir>/../model.lock` (exit 2 otherwise, because the loader reads it there). Bundle tar is deterministic (zeroed headers); `embeddings/` holds the cache's `refs/` + `snapshots/` of the winner's model (symlinks resolved). D17 CI = best mean ± 2.776*sd/sqrt(5) over per-fold F1; size = head.joblib bytes + embedding files. Parity is a hard SystemExit on all 112 dev items and, on failure, removes the new tarball and restores the lock. Run dir gets `nlu_classifier.{md,json}`, `misses.yaml`, `figures/{reliability,confusion_<C0..Ref>}.png`. Section 7 is a placeholder table. Slice rules: negation = negator word list, short answer = pending or <=3 words.
Deviations: none. Fixture run picks C2 (smallest in CI), tau 0.7. ruff isort would reorder `app` imports above `ml`, so compare.py inserts `backend/` into sys.path itself before them.
Verify: full Verify → rc=0 ("intent_clf@v1 = c2 tau=0.7 parity=ok", tarball listed, ruff check/format clean); `ml/intent/model.lock` sha256 0e6a8c1f... and `ml/intent/models` listing (.gitkeep only) identical before and after.

### T18 — LIVE: generate the training data (gpt-6-luna)
Created: `ml/intent/data/<locale>/<class>.yaml`, all 88 cells, 30 items each (660 per locale, 120 per class), `accepted: null` on every item. Nothing accepted by the agent.
Facts: ~88 cells + 1 regen (es-mx deny) = 89 needed calls; logs show 88 `llm.call` lines, 84 ok and 4 `OpenAITimeoutError` (20 s client timeout; 3 in a row on one cell aborted a run, then a re-run resumed). Runs were cut by shell timeouts/session limit and resumed via `make intent-gen` (resumable). Cell that needed retry/re-run: the cell after es-mx deny in the first resumed run (timeouts x3) plus one earlier timeout; es-mx deny needed 1 regen call. Final `--plan`: "88 cells, would make 0 call(s)". Hygiene drops/duplicates are not recorded in the files, so not countable; no cell ended below 30.
Deviations: none; no utterance edited by hand.
Verify: python assert (88 files, all >=30 items) passed; git status diff vs before: only new `ml/intent/data/**` from this task; other changes belong to parallel tasks (T19/T20/T22/T23/T33).

### T24 — Docker bundle via named context
Created: `ml/intent/.dockerignore`.
Changed: `backend/Dockerfile` (`COPY --from=intent` model.lock + models/ to `/app/ml/intent/`, python sha256/name re-check RUN, `ENV INTENT_MODEL_DIR=/app/ml/intent/models`, both syncs `--no-group ml`, CMD `uv run --no-sync`), `docker/docker-compose.base.yml` (`additional_contexts: intent: ../ml/intent`), `docker/docker-compose.dev.yml` (command `uv run --no-sync`).
Facts: lock `version` is the file stem (`intent_clf@vN`), tarball is `<version>.tar.gz` (same as loader). Dev bind mount is only `../backend/app:/app/app`, so `/app/ml/intent` stays visible and `INTENT_MODEL_DIR` resolves to `/app/ml/intent/models` in dev. `docker compose run` has no `--network` flag here; offline proof used `docker run --rm --network none latam-cs-backend:latest ...`. Image has no scikit/fastembed.
Deviations: offline proof via `docker run` instead of `compose run`.
Verify: build exit 0 (empty models); offline load_classifier -> `(None, 'model.lock has no pinned version')` exit 0; fake tarball build exit 1 (lock mismatch). `make up` healthy, log `intent_classifier.unavailable` reason "model.lock has no pinned version".

### T34 — intent_gen@v2 + `--retire-slots`
Created: `ml/intent/prompts/intent_gen@v2.md` (v1 untouched; negation/hard_negative now express the class; the "must not be labeled" rule replaced by "every item must be labeled as the class", scope classes by topic).
Changed: `ml/intent/generate.py` (`_PROMPT_VERSION = 2`; flags `--retire-slots a,b --retire-generator-version N`, `_retire()` sets `accepted: false` only on matching items not already false, prints per-cell and total counts, no LLM call; honours `--locale/--class`).
Facts: the top-up regenerates per FAMILY only for items missing: with all 3 items of a family retired it regenerates seed + 2 paraphrases; if only one item of a family is rejected, only that item (seed if seed missing, paraphrases up to 2). Per-family call (slot x10) works with v2 slot text. Prompt loader picks version by file name; no outside change needed. Already-false items are not counted as retired.
Deviations: none. No live call; `ml/intent/data` untouched (sha256 of all files identical before/after).
Verify: temp copy es-ar balance_due -> retired 9; plan "3 call(s) (new 0, regen 3)"; only 9 `accepted: null -> false` lines differ; ruff check and format --check clean.

### T35 — LIVE: retire + regenerate negation/hard_negative (intent_gen@v2)
Changed: `ml/intent/data/**` only. Retired 789 v1 items (negation, hard_negative; the human's 3 earlier `false` were in those slots, so 792 false total). Set `accepted: true` on 1848 v1 items (plain, regional, typo_informal, short_answer) via data_io. Regenerated 792 v2 items (264 negation, 528 hard_negative), all `accepted: null`.
Facts: counts true 1848 / false 792 / null 792; all 88 cells have 30 non-false. No text outside the retired slots changed; no human `false` changed. ~6 resume runs (OpenAI 20 s timeouts abort after 3 in a row). `ml.intent.check` rc=1: 209 problems = 88 cells x "9 not audited" + 88 "21 accepted, expected 30" + 30 duplicate training texts across cells (v1 items) + 3 leaks vs eval text; the v1 duplicates/leaks are not from this task.
Deviations: none.
Verify: `--plan` last line "88 cells, would make 0 call(s)".

### T36 — Relax data check (cross-file duplicates, cells of 29 or 30)
Changed: `ml/intent/check.py` (`duplicate_findings`; `problems(..., warnings=None)`; cell passes with `per_cell-1` or `per_cell`; `WARN` lines on stderr; OK line shows the warning count), `ml/intent/tests/test_leakage.py` (+1 test, different labels fails).
Facts the next tasks need: dup in one file or same text under two labels (`item_label` from `train.py`) still fails; same label across files only warns. `leakage.py` unchanged. Stale "30" mentions (not edited): `ml/intent/generate.py:3,6,118`, `Makefile:105`.
Deviations: none.
Verify: check exits 0 with 7 WARN lines; `pytest test_leakage.py` → 2 passed; ruff check and format clean.

### T26 — `make check` wiring, data coverage test, mutation proofs
Changed: `Makefile` (`check` gains `python -m ml.intent.check`, `pytest ml/intent/tests -q`, `ruff check ml`, `ruff format --check ml`; no `cd ..`: each recipe line already starts at the repo root); `backend/tests/unit/test_registry_consistency.py` (+1 test: every `classifier_labels()` entry has a file in all 4 locales).
Facts the next tasks need: `ruff check ml` fails (26 errors) and `ruff format --check ml` fails (10 files) in files not owned by T26: candidates, compare, export, generate, report, train (`ml/intent/*.py`). `make check` will fail until those are fixed.
Mutations (tmp copies): (a) dev text appended + one accepted set false -> `FAIL leak: ...` rc=1; (b) two accepted removed (T36 relaxed rule) -> `FAIL pt-br/card_status: 28 accepted, expected 29 or 30` rc=1.
Deviations: no `cd ..` in the Makefile lines; mutation (b) removes 2 items, (a) also un-accepts one item.
Verify: real check rc=0 (7 WARN); registry test 5 passed; both mutations rc=1; `make -n check | grep ml.intent.check` ok.

### T26 addendum — ruff config
Changed: `Makefile` ruff lines on `ml` now pass `--config backend/pyproject.toml`. The earlier "26 errors / 10 files" were from default ruff config, not real failures; the T26 entry's "make check will fail" fact is void.
Verify: `ruff check --config backend/pyproject.toml ml` rc=0; `ruff format --check ... ml` rc=0 (15 files already formatted); `make -n check | grep ml.intent.check` ok.

### T27 — Final training on the audited data, run twice
Created: `ml/intent/runs/train_all_s42/train.json`, `ml/intent/runs/train_all_s42_b/train.json` (only files; no model files; not git-ignored; uncommitted per instruction).
Facts the next tasks need: `train.py` filters `accepted is True` and has no 30/2640 assertion; it loaded n_items=2639. Run id defaults to `train_<candidate>_s<seed>`, so a second `make intent-train SEED=42` OVERWRITES the first; the second record was made with `--run-id train_all_s42_b`. prediction_hash (all) = be28e31bc0b9...; metrics identical across both records, and per-candidate hashes also matched the first make run. Wall time: 10m37s, 8m23s, 8m02s.
CV macro-F1 (best grid, sd) / OOF tau: c0 0.0016 (0.0002) / 0.95; c1 0.4481 (0.0) / 0.95; c2 0.9300 (0.0141) / 0.30; c3a 0.9376 (0.0224) / 0.30; c3b 0.8987 (0.0198) / 0.50; c4 0.8385 (0.0355) / 0.60. No CI in the record, only mean and sd over folds.
Deviations: second run used `--run-id` via uv directly (same command otherwise); Verify's literal two-make form was not run as written, since it would overwrite one dir. The equivalent assert passed. No earlier dirs existed under `ml/intent/runs/`.
Verify: equivalent assert -> exit 0, printed both train.json paths.

### T28 — LIVE: real comparison with Ref, selection, bundle, lock
Created: `ml/intent/runs/compare_s42/` (`nlu_classifier.{md,json}`, `misses.yaml`, `figures/` 8 png), `ml/intent/models/intent_clf@v1.tar.gz` (git-ignored), real `ml/intent/model.lock`.
Result: winner C2 (TF-IDF char_wb + LR, C=100, ngram (2,5)), tau 0.30, model_id `intent_clf@v1`, label_set_version 1. Code rationale (D17): best CV was C3a 0.938, CI [0.910, 0.965], inside CI = C2, C3a, C2 smaller (3.5 MB vs 487 MB). Lock sha256 `9ecf7a5d8e604baccd13bbed0455172a3e69d2591d5ee6c544946522ed9ed203` (matches tarball, 2,217,647 bytes; head+embeddings 3,463,308 bytes uncompressed); before the run the lock was all-null and models/ held only .gitkeep (not the fixture state the brief described).
Runtime deps of winner: sklearn 1.9.1 + joblib 1.6.0 (numpy 2.5.3, scipy 1.18.1). NO fastembed, NO onnxruntime (`embedding_model` null, no `embeddings/` in the tar). Backend image excludes the ml group, so T24/T30 must make sure scikit-learn/joblib/numpy are in the image deps.
Dev (56 seeds) macro-F1: C0 0.00, C1 0.52, C2 0.65 [0.48, 0.74], C3a 0.58, C3b 0.66, C4 0.68, Ref 0.86 [0.73, 0.91]. Ref: 56 nlu@v4 calls logged = 54 ok + 2 `refused` (attempt 0, no provider call, injection items), $0.0163 total, p50 1542 ms / p95 4240 ms. One live run, no rerun. Ref goes through `get_llm_client` + `run_nlu` (core/llm), not a direct SDK.
Facts for T29-T32: report McNemar is only vs keyword (C2 vs keyword p 0.549; Ref vs keyword p 0.001); there is NO McNemar winner-vs-Ref line. Section 7 is still the placeholder; transfer line says "not run". Report has no per-slice table beyond section 5. `git status --porcelain ml/intent/models` shows `?? ml/intent/models/` because `.gitkeep` is untracked (pre-existing), so the Verify's `grep -c .` check fails (rc 1) for that reason, not the tarball (ignored).
Deviations: none to code. Verify: python sha256 assert passes; git-status clause fails as above.

### T37 — Locale-transfer case fix + live rerun
Changed: `ml/intent/compare.py` (transfer block, ~14 lines): dev items and training locales compared via `.lower()` (`(it.language_variant or "").lower()`, since some dev items have `language_variant` None; first attempt crashed on that after the bundle step), `in_locale_exact_set` found by case-insensitive scan of `by_language_variant`.
Transfer: es-ar held out 50.0% (3/6) vs in-locale 50.0% (3/6), n_train 1979. Report line: "Locale transfer (es-ar removed from training, then tested on es-ar): 50.0% (3/6), against 50.0% (3/6) when es-ar is in training."
Winner C2 and tau 0.30 unchanged. Bundle is now `intent_clf@v3` (each run bumps the version via `next_version`), sha256 `ce0fb351337fbc5771978c91f2e11f816edfc9698f4438d2d82b8113625a351f` (T28: v1 `9ecf7a5d...`; tarballs are not byte-reproducible). Stale `intent_clf@v2.tar.gz` from the crashed run deleted; v1 tarball still in models/.
Dev macro-F1 unchanged: C1 0.52, C2 0.65, C3a 0.58, C3b 0.66, C4 0.68, Ref 0.86.
Ref: 2 live runs of 56 `nlu@v4` calls each (first crashed after Ref; no Ref cache), last run 54 ok + 2 refused; report cost/call $0.0164.
Verify: sha256+transfer assert rc 0, `Locale transfer (` grep found, `pytest ml/intent/tests -q` 2 passed.

### T29 — Serving deps to backend runtime
Changed: `backend/pyproject.toml`, `backend/uv.lock`. Moved scikit-learn and joblib from `ml` group to `[project] dependencies`; added `numpy>=2` explicitly (backend `classifier/scorers.py` imports numpy directly). Runtime lines: `scikit-learn>=1.6`, `joblib>=1.4`, `numpy>=2`. `ml` group now: fastembed>=0.4, onnxruntime>=1.18, matplotlib>=3.9. scipy left transitive (not imported by backend). mypy overrides untouched.
Lock diff vs pre-T29 file: no package added/removed/version-changed (164 resolved); only dependency-edge lines moved (joblib/numpy/scikit-learn now in the project's runtime deps, `ml` group shrank). Locked: sklearn 1.9.1, joblib 1.6.0, numpy 2.5.3, scipy 1.18.1 (match bundle).
Verify: `uv lock && uv run --no-group ml python ... load_classifier` printed `intent_clf@v3`, rc 0; `uv sync` rc 0. ml group still installed after sync (fastembed, matplotlib, onnxruntime import OK).
Extra: ml/intent/tests + test_classifier_contract.py -> 13 passed (run from `backend/`; from repo root `--project backend` fails with `No module named 'app'` because pythonpath ini isn't picked up).
Facts for T30: no pin tighter than `>=1.6` applied (D15 silent); the bundle manifest/lock records training versions if a runtime sklearn-version check is wanted.
Deviations: none.

### T30 — Image proof for criterion 7 (BLOCKED, nothing else run)
Changed: none.
Blocker: `docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml build backend` exits 1 at the Dockerfile sha256 re-check RUN:
`model.lock mismatch for intent_clf@v1.tar.gz: expected intent_clf@v3.tar.gz / ce0fb351...625a351f, got 9ecf7a5d...ed203`
Cause: the stale `ml/intent/models/intent_clf@v1.tar.gz` (2,217,647 bytes) is copied by `COPY --from=intent models/` and the check requires EVERY `*.tar.gz` to match the lock (name and sha256). The v3 tarball itself is fine (sha256 on host equals the lock).
Options: (a) move/delete the stale v1 tarball (untracked, git-ignored artifact; recommended, nothing else changes); (b) change the Dockerfile check to test only the locked file and ignore others (source change, and would bake the stale 2.2 MB file into the image unless `.dockerignore` also excludes it); (c) add `ml/intent/.dockerignore` rule for non-locked tarballs (does not scale across versions).
Not run: offline load, tamper proof, make up, image dep check. Stack left as it was.

### T30 — result
Changed: none (state file only). Moved untracked stale `ml/intent/models/intent_clf@v1.tar.gz` to the scratchpad (`stale-intent_clf@v1.tar.gz`) per orchestrator decision (a); `models/` = `.gitkeep` + `intent_clf@v3.tar.gz`, v3 sha256 = lock `ce0fb351...625a351f`.
Build: `docker compose ... build backend` rc 0 (sha256 RUN passes silently; no output on success). The v1 file was NOT in the final image (`ls /app/ml/intent/models` -> only `intent_clf@v3.tar.gz`, 2217647 B).
Offline load (`docker run --rm --network none`, empty AWS vars, `-v policies:/policies:ro`): `intent_clf@v3`, rc 0. Without the policies mount it fails `PolicyLoadError: missing required policy file(s)` (the image has no `policies/`; compose mounts it).
Offline full app: NOT proven. `uvicorn app.main:app --network none` stops in lifespan `_require_secrets`: `refusing to start: empty JWT_SECRET, IDENTITY_HMAC_KEY, PII_VAULT_KEY`; and it needs Postgres/Redis. Only the classifier load itself was proven offline.
Image deps: sklearn/joblib/numpy True; fastembed/onnxruntime/matplotlib False.
Tamper: appended 1 byte -> build rc 1: `model.lock mismatch for intent_clf@v3.tar.gz: expected intent_clf@v3.tar.gz / ce0fb351...625a351f, got 4111c7aa...cad505`. Restored from backup: sha256 `ce0fb351...625a351f` = lock.
`git check-ignore -v`: `.gitignore:13:ml/intent/models/*	ml/intent/models/intent_clf@v3.tar.gz`. `git status --porcelain ml/intent/models` -> `?? ml/intent/models/` (untracked `ml/` tree, expected).
make up: all healthy; backend log `{"classifier_version": "intent_clf@v3", "label_set_version": 1, "event": "intent_classifier.loaded"}`; backend `Up (healthy)`.
Finding (not fixed): `ml/intent/compare.py:467` takes `export.next_version(args.lock)` (`export.py:40`, lock version + 1) each run and nothing deletes older tarballs (`compare.py:502` only unlinks the new bundle on parity failure). Each successful `make intent-compare` leaves the previous `intent_clf@vN.tar.gz`, which breaks the next image build (Dockerfile requires every tarball to match the lock).
Deviations: offline step via `docker run` (not `compose run --network none`); policies mounted for offline load; v1 moved out.

### T31 — LIVE: degraded end-to-end, 8 dev cases, with and without the classifier
Changed: none (source untouched). Report dirs (renamed after each run because the run folder name is `dev-<git sha>` and run 2 would overwrite run 1): run 1 `eval/reports/dev-db8b7c5706-run1-classifier/`, run 2 `eval/reports/dev-db8b7c5706-run2-no-classifier/` (`meta.json` `run_id` still says `dev-db8b7c5706` in both). A first, discarded run 1 (same result, no log kept) was moved to the scratchpad.
Commands: `export PYTHONPATH=$PWD/backend` (needed, see Findings), then `make eval SUITE=dev SYSTEM=proposed CASES=d-card_block-tool_failure-es-co-01,a-card_status-normal_resolution-es-co-01,d-pending_reversal_explain-normal_resolution-pt-br-01,d-decline_explain-normal_resolution-pt-br-01 FAULTS=bedrock_timeout`; run 2 adds `INTENT_MODEL_DIR=$(mktemp -d)` exported. CASES are seed-id PREFIXES; they expand to 8 case variants (card_block s,p1,p2; card_status s; pending_reversal s; decline_explain s,p1,p2).
Where it runs: `make eval` plays the backend as a host subprocess (uvicorn started by the harness, inheriting the shell env, reading `settings.intent_model_dir`); NOT the compose backend container. So the shell export reaches the code under test; the dev stack was not restarted or touched (backend container still Up healthy, one `intent_classifier.loaded` line).
Counts read with: `python3 -c "import json;m=json.load(open('<dir>/metrics.json'))['runs']['proposed'][0]['overall'];print(m['cases'],m['safe_automated_resolution'],m['escalation'],m['unsafe']['k'])"` plus per-case `outcome` from `results.jsonl`.
- Run 1 (classifier): 8 cases = 5 played + 3 not_runnable. resolved 4, clarified 1, handed off 0, unsafe 0/5.
- Run 2 (unloaded): 5 played + 3 not_runnable. resolved 0, handed off 5 (all `handoff:atencion`, `escalation unnecessary 5`), unsafe 0/5.
Per case (run 1 / run 2): card_block s,p1,p2: not_run / not_run | card_status s: clarified (verdict failed: want resolved) / handoff | pending_reversal s: resolved / handoff | decline_explain s,p1,p2: resolved / handoff.
Evidence: run 1 log has `intent_classifier.loaded classifier_version=intent_clf@v3` and, with all 3 NLU attempts failing per turn (`_SyntheticTimeout`), the turns still got `status clear` + intent (card_status, decline_explain, pending_reversal) and no handoff. Run 2 log has `intent_classifier.unavailable reason=model.lock missing or unreadable at <empty dir>/model.lock`, turns got `status None`, intents [], route `fallback`, fixed handoff text.
Provider calls: 0 real. All NLU calls `outcome: unavailable`, `_SyntheticTimeout`, ~0.1 ms (15 in run 1, 30 in run 2, 3 attempts each); run 2 meta also lists a `handoff_summary` model but no completed call. PII scan hits 0 in both.
Findings (not fixed):
1. `make eval` fails with `ModuleNotFoundError: No module named 'app'` at `eval/harness/__main__.py:7` (`from app.core.config import Fault`, added by T7); worked only with `PYTHONPATH=backend` exported.
2. The relabeled dev case `d-card_block-tool_failure-es-co-01` did NOT resolve as the clarification: all 3 variants are `not_runnable` in both runs, because `eval/driver/driver.py::is_not_runnable` skips any case with non-empty `setup.faults` (its own YAML keeps `faults: [bedrock_timeout]`). Its `required_tools: [cards.list_cards]` then shows as failed check `tools_required`, and `expected_outcome: clarified`. Criterion "relabeled case resolves as the clarification in run 1" is NOT proven.
3. `debug.degraded` is False on every turn through the real runner, including run 1 turns that used the classifier after LLM failure: `runner.py` builds `DebugInfo(...)` without `degraded=degraded` (only `graph.run_turn` sets it). `reply_sent.degraded` is written from the real flag but lives in the dropped clone DB and is not logged, so no `reply_sent degraded=true` line was captured (T23 open item stays open).
4. Run 1 `card_status` ends `clarified` (card picker, "which card?") and the case wants `resolved` -> verdict failed (not unsafe). Run 1 decline_explain x3 pass with the canned "Tive um problema ... Quer que eu tente de novo" reply (outcome `resolved` by harness checks), so "resolved" there is not a data answer.
Numbers for T32 section 7: run 1 resolved 4 / handed off 0 / unsafe 0 of 5 played (3 not run); run 2 resolved 0 / handed off 5 / unsafe 0 of 5 played (3 not run). Clone took 319 s / 213 s.
Deviations: report folders renamed (see above); PYTHONPATH export.
Verify: `ls -d eval/reports/dev_proposed_* | tail -2` does not match (run folders are `dev-<sha>`); unsafe count 0 in both `metrics.json`.

### T38 — Runner `degraded` in DebugInfo; `make eval` imports `app`
Changed: `backend/app/domains/conversation/runner.py` (`DebugInfo(..., degraded=degraded)`, same per-turn variable as `reply_sent.degraded` and `cardy.degraded`); `eval/harness/__main__.py` (puts `<repo>/backend` on `sys.path` before `from app.core.config import Fault`, `# noqa: E402`).
Precedent for the import fix: the `_BACKEND_ROOT` `sys.path.insert` block in `eval/harness/nlu_eval.py`, `eval/simulator/simulator.py`, `eval/judges/*.py`. Makefile unchanged.
Test: `backend/tests/unit/test_degraded.py::test_runner_marks_degraded_in_debug_and_audit` drives `runner._run_turn` (registry, events, store, redis monkeypatched; real graph, `LLMError` LLM, stub classifier); asserts the published `debug` event's `degraded` and `reply_sent.degraded` are True. 7 passed in the file.
Deviations: none. Verify: exit 0.

### Human decisions after T31
- Card-block dev case: drop `setup.faults` from the dev scenario only; the 5 `_staging/heldout` files stay untouched (T39).
- Old tarballs: the export step deletes older `intent_clf@v*.tar.gz` after a successful run; the strict Docker check stays (T40).

### T40 — Delete older intent bundles after export
Changed: `ml/intent/export.py` (`remove_older_bundles(models_dir, model_id)`, prints `removed old bundle <name>` per file); `ml/intent/compare.py:509` (call).
Created: `ml/intent/tests/test_export.py` (`test_cleanup_keeps_only_locked_bundle_and_unrelated_files`, `test_failure_path_removes_nothing`).
Flow: runs right after the parity try/except (which re-raises on failure), i.e. after bundle written, parity ok, lock written; parity failure never reaches it.
Pattern: regular files fully matching `intent_clf@v\d+\.tar.gz`, not the locked version. No recursion.
Deviations: failure-path test is a structural stand-in (cleanup is only called after parity), not an end-to-end compare run.
Verify: `cd backend && uv run pytest ../ml/intent/tests -q` -> 4 passed; ruff check/format clean.

### T40 addendum
Removed `test_failure_path_removes_nothing`; the failure path is covered by code position only (cleanup at `compare.py:509`, after the parity try/except), not by a test.

### T39 — Card-block dev case runnable; degraded e2e rerun (LIVE)
Changed: `eval/scenarios/dev/d-card_block-tool_failure-es-co-01.yaml` (`setup.faults: [bedrock_timeout]` -> `faults: []`, same form as the other dev cases; the file's other lines were already the T9 relabel; s/p1/p2 live in this one file). `_staging/heldout` and `heldout/` untouched. `make eval-freeze-check` covers only `heldout/` vs `heldout.lock`, no dev manifest.
Report dirs (moved T31's two to scratchpad `t31-reports/`): `eval/reports/dev-db8b7c5706-run1-classifier/`, `eval/reports/dev-db8b7c5706-run2-no-classifier/`. Same commands as T31, NO `PYTHONPATH` (T38 import fix works). Logs in scratchpad `t31-reports/run1.log`, `run2.log`.
Counts read with: `python3 -c "import json;m=json.load(open('<dir>/metrics.json'))['runs']['proposed'][0]['overall'];print(m['cases'],m['safe_automated_resolution'],m['escalation'],m['unsafe']['k'])"` plus `outcome`/`verdict` per row of `results.jsonl`.
- Run 1 (classifier): 8 played, 0 not_run; resolved 4, clarified 1, abstained 3, handed off 0, unsafe 0/8.
- Run 2 (unloaded): 8 played, 0 not_run; resolved 0, handed off 8 (`handoff:atencion`, escalation unnecessary 8), unsafe 0/8.
Per case (run 1 outcome/verdict | run 2): card_block s,p1,p2: abstained/failed | handoff/failed; card_status s: clarified/failed | handoff/failed; pending_reversal s: resolved/passed | handoff/failed; decline_explain s,p1,p2: resolved/passed | handoff/failed.
Evidence: run1.log `intent_classifier.loaded classifier_version=intent_clf@v3`; run2.log `intent_classifier.unavailable reason=model.lock missing or unreadable at /tmp/model.lock`.
Answers:
1. Run 1 card-block does NOT end as the clarification: all 3 end `abstained`, failed checks `tools_required` + `outcome`. Debug: `status out_of_scope`, intents [], `topic loans`, route `abstain`, tools_called [get_profile], reply "Por aquí no puedo gestionar préstamos..." with quick replies. The classifier mislabels "Necesito bloquear mi tarjeta de crédito..." as the loans scope class (credit-card wording). Real defect of the classifier path, not of the harness. `required_tools: [cards.list_cards]` would also be wrong for a degraded block turn: with the classifier giving a bare card_block the expected D11 path is ambiguous/lock_vs_block, which may not call list_cards before the chip question (T9 open item, unproven here since no turn reached it).
2. card_status `clarified`: `card_info` asks the card picker when `select_card` has 2 cards (both Bloqueada) and no `card_hint`; that is independent of the LLM, so the `resolved` expectation does not hold for this 2-card persona even in normal mode (not run here). Not a degraded-mode defect; scenario expectation / persona.
3. decline_explain reply (run 1): "Tive um problema e não consigo responder isso agora. Não fiz nenhuma alteração. Quer que eu tente de novo ou prefere falar com uma pessoa?" (tools incl. explain_decline ran; compose LLM failed, canned text). `checks.outcome()` returns `resolved` whenever there is no handoff, last reply route is not `abstain`, and the last debug `pending` has no clarify suffix and no `ambiguous` nlu_result: it does not look at reply content.
4. Harness keeps debug per turn (8 turns each): `degraded` true on 8/8 in run 1, 0/8 in run 2 (run 2 turns take the no-LLM handoff route, so the flag stays False).
5. LLM calls: 24 in run 1 (all nlu `unavailable`), 48 in run 2 (24 nlu + 24 handoff_summary, all `unavailable`); 0 real provider completions. PII scan hits 0 in both (`meta.json` pii_hits).
Numbers for T32 section 7 (replace T31's): run 1 played 8, resolved 4 / clarified 1 / abstained 3 / handed off 0 / unsafe 0 of 8; run 2 played 8, resolved 0 / handed off 8 / unsafe 0 of 8. Verdicts: run 1 4 passed 4 failed; run 2 0 passed 8 failed.
Deviations: criterion "run 1 card-block ends as clarification" NOT met (see answer 1); the plan Verify (unsafe 0, no not_run row) is met.
Verify: both `metrics.json` unsafe k=0; `results.jsonl` 8 rows each, 0 not_run.
- T39 finding ("tarjeta de crédito" read as loans): add data and retrain. 2 families (6 items) per in-scope intent cell that name the card type, prompt `intent_gen@v3`, slot `card_type`, accepted without a human read; a cell passes the check with 29 or more accepted items (T41–T44).

Board additions: T41 in progress; T42, T43, T44 pending (T32 waits for T44).

### T41 — Generator and check support "card-type" top-up families
Created: `ml/intent/prompts/intent_gen@v3.md` (placeholders {locale} {class_name} {class_description} {count} {items} {card_types}; same JSON output as v2, slot "card_type").
Changed: `generate.py` (flags `--card-type-topup`, `--card-type-families K` default 2; `card_type_plan`, `topup_card_type`; `_PROMPTS_DIR`, `_generator(version)`; docstring lines 3-6 reworded), `check.py` (`cell_size_problems`: cell passes with per_cell-1 or more accepted; no slot/family-count rule existed), `tests/test_leakage.py` (+1 test: 31 and 29 pass, 28 fails).
T42 command (live): `uv run --project backend python -m ml.intent.generate --card-type-topup` (add `--locale L --class C` to limit; `--plan` = dry run). Cells: 60 (15 in-scope classes x 4 locales), 60 calls (one per cell, 2 families = 6 items each, 360 new items, all accepted: null, slot card_type, generator `<model>:intent_gen@v3`, family ids continue after the file's highest index, i.e. -11, -12). Credit first, then debit (alternates by existing card_type family count).
Re-runs: cell with K live card_type families (>=1 non-rejected item each) is skipped; fewer -> one call for the missing count only; items are appended, never reordered or edited. Interrupted runs resume per cell. Aborts/timeouts: unchanged (client 20 s, 3 in a row).
BLOCKER for T42: `ml/intent/data_io.py` `Slot = Literal[...]` (line 46, used by `DataItem.slot`) has no "card_type" -> writing/loading any card_type item fails validation. Not in my Files; needs a one-line change (add "card_type" to Slot; SLOT_MIX stays, it only drives the original 10 families). Not changed by me.
Read-only checks: train.py never reads `slot` (grep: none); `load_training` groups by `it.family` (train.py:46) and GroupKFold uses it (train.py:76-83), so new families stay together. Only unknown-slot rejection is data_io. `check.py` has no slot-mix or family-count rule. `generate.plan_cell` (normal mode) counts only 10 families by index 1..10 and `_slot_name` is index-based: a normal run on a cell with family 11/12 would count them in the 30-live total (>=30 -> nothing), fine; but it would not regenerate if a v1 slot family later is rejected while total stays >=30.
Deviations: none.
Verify: pytest ml/intent/tests -> 4 passed; check -> "intent data OK (7 duplicate warning(s))" rc 0; `--card-type-topup --plan` -> "60 cells, would make 60 call(s)"; ruff check/format clean.

### T41 addendum
Changed: `ml/intent/data_io.py:46-48` `Slot` now includes "card_type" (SLOT_MIX untouched). `generate.py`: `_CARD_TYPE_EXCLUDED` (greeting, thanks_close, affirm, deny) skipped next to the scope-class skip in `_run`; docstring updated. Supersedes the T41 BLOCKER and the 60-cell numbers above.
Cells: 44 (11 classes x 4 locales: balance_due, card_block, card_status, card_unlock, decline_explain, general_question, human_request, pending_reversal_explain, replacement_request, transaction_search, unrecognized_charge), 44 calls, 264 new items.
T42 command (live): `uv run --project backend python -m ml.intent.generate --card-type-topup` (`--plan` first to confirm "44 cells, would make 44 call(s)").
Write-path proof (fake client, tmp copy of es-co/card_block.yaml): topup wrote 6 items (-11 credit, -12 debit, slot card_type, `gpt-6-luna:intent_gen@v3`, accepted null), reload validates (47 items), re-plan needs 0, first 41 items byte-identical prefix of the file.
Other slot enumerations: none found in ml/, backend/, eval/ (only generate.py/data_io.py SLOT_MIX use; `_retire` takes slot names from the CLI).
Board update: T41 done (a309a82): 44 cells, 264 items planned, `--card-type-topup`. T42 in progress.

### T42 — LIVE: card-type families (intent_gen@v3), 44 cells
Changed: `ml/intent/data/**` only (44 files appended; no code change). Backup: scratchpad `data-before-cardtype/`.
Calls: `--plan` "44 cells, would make 44 call(s)"; one live run, 44 calls, 44 ok, 0 timeouts, 0 reruns; re-plan "would make 0 call(s)".
Items: 264 generated (slot card_type, families -11/-12) -> 263 accepted, 1 rejected. Reject reasons: no card type named 0; leak vs eval text 1 (es-mx/decline_explain "¿Por qué rechazaron mi compra con la tarjeta de débito?"); in-file dup 0; cross-file dup with a different label 0. Same-label cross-file dups left as WARN (4 new). Credit/debit split of accepted: 132 / 131.
Totals: 2,902 accepted, 838 rejected, 0 null. Cells under 6 new accepted: es-mx/decline_explain (5; cell still passes, >=29).
Check: `uv run --project backend python -m ml.intent.check --data-dir ml/intent/data` -> "intent data OK (11 duplicate warning(s))", rc 0. Prefix check: all 88 files start with the backup bytes (items changed only inside the appended block).
Read of 6 cells (es-co and pt-br card_block, human_request, general_question): all 36 items fit their class, no mislabelled; general_question items are generic ("¿Qué debería tener en cuenta sobre la tarjeta de crédito?" is vague but fine). Accepted all.
Samples (accepted): es-mx balance_due "¿Cuánto debo pagar de mi tarjeta de crédito este mes?"; es-mx card_block "Quiero bloquear mi tarjeta de crédito porque la perdí."; es-mx card_status "¿Mi tarjeta de crédito está activa?"; es-co balance_due "¿Cuánto debo pagar de mi tarjeta de crédito?"; es-co card_block "Perdí mi tarjeta de crédito, ¿me la puedes bloquear?"; es-co card_status "¿Me confirmas si mi tarjeta de crédito está activa?"; es-ar balance_due "¿Cuánto tengo que pagar de mi tarjeta de crédito este mes?"; es-ar card_block "Perdí mi tarjeta de crédito, ¿me la pueden bloquear?"; es-ar card_status "¿Está activa mi tarjeta de crédito?"; pt-br balance_due "Qual é o valor que eu tenho que pagar na fatura do meu cartão de crédito?"; pt-br card_block "Quero bloquear meu cartão de crédito, por favor."; pt-br card_status "Meu cartão de crédito está ativo?"
Deviations: none. The 263 new items were not human-read (same as the 792).
Board update: T42 done (abdf49a): 263 card_type items accepted, 1 rejected; totals 2,902 accepted / 838 rejected / 0 null; check OK with 11 WARN. T43 in progress.

### T43 — LIVE: retrain, compare, bundle, image (card-type data)
Changed: `ml/intent/runs/**` (train_all_s42, train_all_s42_b, compare_s42 overwritten), `ml/intent/model.lock`, `ml/intent/models/` (v3 tarball removed, v4 added). No source change. Backup of v3 state in scratchpad `bundle-v3-backup/`.
Train: run 1 `make intent-train SEED=42` -> `train_all_s42`; run 2 CLI `--run-id train_all_s42_b`. n_items 2902 both; metrics and prediction_hash identical (all = e6ad4f720f0b78f3...). CV macro-F1 (mean, sd) / OOF tau: c0 0.0026/0.0002/0.95; c1 0.4589/0.0/0.95; c2 0.9411/0.0136/0.35; c3a 0.938/-/0.55; c3b 0.912/-/0.70; c4 0.854/-/0.60 (sd for c3a/c3b/c4 in report section 2: 0.020/0.012/0.022).
Compare `compare_s42` (one live run, rc 0): winner C2 (C=100, ngram (2,5)), tau 0.35, `intent_clf@v4`, sha256 `7e5b03af27f01dbe28814ef994e56709e85019b0437665985bf1ac0f0e45f725` (= tarball), 2,239,717 B, parity ok. Rationale (D17): best CV C2 0.941, CI [0.924, 0.958]; inside CI C2, C3A; C2 smallest (3.5 MB vs 487 MB). Printed `removed old bundle intent_clf@v3.tar.gz`; models/ holds only v4 (+ .gitkeep).
Dev (56) macro-F1 [CI] / exact-set [CI]: C0 0.00 [0.00,0.01] / 3.6%; C1 0.52 [0.39,0.62] / 55.4% [42.4,67.6]; C2 0.67 [0.51,0.75] / 64.3% (36/56) [51.2,75.5]; C3a 0.68 [0.53,0.73] / 26.8% [17.0,39.6]; C3b 0.66 [0.50,0.72] / 53.6% [40.7,66.0]; C4 0.66 [0.47,0.71] / 50.0% [37.3,62.7]; Ref 0.86 [0.73,0.91] / 82.1% [70.2,90.0]. C2 status acc 85.0%, OOS recall 2/2, false abstain 0/18, p95 3 ms.
Per-locale exact-set C2: es-AR 3/6, es-CO 5/7, es-MX 6/7, pt-BR 4/12, mixed 3/4, unknown 15/20. Ref: 3/6, 7/7, 6/7, 7/12, 3/4, 20/20. Transfer: es-ar held out 3/6 vs in-locale 3/6.
McNemar vs keyword (exact-set): C2 +8/-3 p 0.227; Ref +18/-3 p 0.001 (C3a p 0.002 against, C3b 1.000, C4 0.664).
Ref: 56 nlu@v4 calls (54 ok, 2 refused), report cost/call $0.0162 (about $0.016 per run total... 56 calls, a few cents at most); p50 1395 ms / p95 3717 ms.
Probes (v4, tau 0.35, backend `load_classifier`, raw top class/score): "Necesito bloquear mi tarjeta de crédito ahora mismo." card_block 0.979 above; "Quero bloquear meu cartão de crédito" card_block 0.990 above; "¿Cuánto debo de mi tarjeta de crédito?" balance_due 0.996 above; "Quiero pedir un préstamo" loans 1.000 above (out of scope); "Quiero un crédito de libre inversión" loans 0.524 above (out of scope); "Perdí mi tarjeta de débito" card_block 0.746 above.
Image: `docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml build backend` rc 0 (sha256 check passed). `make up` all Healthy; backend log `{"classifier_version": "intent_clf@v4", "label_set_version": 1, "event": "intent_classifier.loaded"}`; backend Up (healthy). `git check-ignore -v`: `.gitignore:13:ml/intent/models/* ml/intent/models/intent_clf@v4.tar.gz`.
Deviations: none. Tamper and offline proofs not repeated, per brief.
Verify: lock sha256 == tarball sha256; build rc 0; log line present.
Board update: T43 done (a9847f9): winner c2, tau 0.35, intent_clf@v4 sha256 7e5b03af…; dev C2 0.67 / 36 of 56, Ref 0.86; card-block credit probe -> card_block 0.979; image rebuilt, stack on v4. T44 in progress.

### T44 — LIVE: degraded e2e rerun on intent_clf@v4 (ALONE)
Changed: none (source untouched). T39's two report dirs moved to scratchpad `t39-reports/`. New dirs: `eval/reports/dev-db8b7c5706-run1-classifier/`, `eval/reports/dev-db8b7c5706-run2-no-classifier/` (renamed after each run). Logs in scratchpad `t44-run1.log`, `t44-run2.log`. Same commands as T39, no `PYTHONPATH`; run 2 with `INTENT_MODEL_DIR=$(mktemp -d)` exported. Both rc 0.
Counts read with: `python3 -c "import json;m=json.load(open('<dir>/metrics.json'))['runs']['proposed'][0]['overall'];print(m['cases'],m['safe_automated_resolution'],m['escalation'],m['unsafe']['k'])"` plus `outcome`/`verdict` per row of `results.jsonl`.
- Run 1 (classifier): 8 played, 0 not run; resolved 4, clarified 4, abstained 0, handed off 0, unsafe 0/8. Verdicts 7 passed, 1 failed.
- Run 2 (unloaded): 8 played, 0 not run; resolved 0, handed off 8 (`handoff:atencion`), unsafe 0/8. Verdicts 0 passed, 8 failed.
Per case (run 1 outcome/verdict | run 2): card_block s,p1,p2: clarified/passed | handoff/failed; card_status s: clarified/failed (want resolved: 2-card persona, picker, same as T39) | handoff/failed; pending_reversal s: resolved/passed | handoff/failed; decline_explain s,p1,p2: resolved/passed | handoff/failed.
Evidence: run1.log `intent_classifier.loaded classifier_version=intent_clf@v4`; run2.log `intent_classifier.unavailable reason=model.lock missing or unreadable at /tmp/model.lock`.
Card-block (run 1, all 3 variants identical): debug status `ambiguous`, intents [card_block], route `card_block`, pending `card_block.card_hint`, tools_called [get_profile, list_cards], ui card_picker, degraded true. Reply: "¿Cuál tarjeta quieres bloquear?\nCrédito •••• 2096 · Activa\nDébito •••• 6730 · Activa". No block executed, no token issued. `required_tools: [cards.list_cards]` is satisfied (list_cards was called), so T9's open item is closed: the expectation is right. Changed against T39: abstained/failed (misread as loans) -> clarified/passed.
Other 5 variants: same outcome/verdict as T39 in both runs. Run 1 decline_explain: status clear, tools incl. explain_decline, canned reply as in T39 (outcome `resolved` by harness rule).
Degraded true per run (debug of the 8 turns): run 1 8/8, run 2 0/8 (no-LLM handoff route). LLM calls: run 1 24 nlu, run 2 24 nlu + 24 handoff_summary, all status `unavailable`; 0 real provider completions. PII hits 0 in both.
Numbers for report section 7 (replace T31 and T39): run 1 played 8, resolved 4 / clarified 4 / abstained 0 / handed off 0 / unsafe 0; run 2 played 8, resolved 0 / handed off 8 / unsafe 0.
Deviations: none.
Verify: both `metrics.json` unsafe k=0; `results.jsonl` 8 rows each, none not_run.
Board update: T44 done (a38bbfb): run1 4 resolved + 4 clarified, 0 unsafe; run2 8 handoff, 0 unsafe; card-block clarified/passed on v4. T32 in progress.

### T32 — Final report sections 6-8 and MODEL_CARD
Created: `ml/intent/MODEL_CARD.md`. Changed: `ml/intent/runs/compare_s42/nlu_classifier.md` (section 6 decision column, section 7 table + 3 caveats + both report paths, section 8 extended with 13 limitations). Sections 1-5 untouched.
Numbers checked: data 2,902 accepted / 838 rejected (counted from `ml/intent/data`, matches report); run1/run2 counts match `metrics.json` (7/8 passed run1, 0/8 run2, unsafe 0).
Disagreements: brief said 2,640 items (that is D19's target; files hold 2,902). T43 entry says Ref cost "about $0.016 per run total"; `compare.py::_ref_predict` returns the mean of per-call `cost_usd`, so $0.0162 is per call (about $0.91 for 56 calls); card and section 8 say per call.
Open: section 6 rows "Scope mismatch" and "Multi-intent" decisions say open (scenario-labelling vs data). Section 7 table needed the word "unsafe" for Verify; it is in the row label and in a sentence.
Verify: `test -s ... && grep ... && grep -c "unsafe" ml/intent/runs/*/nlu_classifier.md` -> compare_s42 count 2 (only that run dir has the report).
Board update: T32 done (a64e3dc). All implementation tasks done; verification next.

### T32 repair 1
Changed: `ml/intent/MODEL_CARD.md` (CI kinds labelled: macro-F1 bootstrap, exact-set/status/recall Wilson per `Rate` in `eval/harness/metrics.py`; size 3.5 MB uncompressed head vs 2,239,717 B tarball; e2e line says 3 of 4 resolved are decline_explain canned apology; Ref cost = mean over 54 paid calls, run about $0.87; limitations 13 and 14 added: manifest has no library versions, no training item has a mask token). `nlu_classifier.md` sections 7-8: same cost, 3-of-4 note, two new limitations. Sections 1-5 untouched (the report's "3.5 MB" and header CI wording are there, so unchanged).
Checked: run1 `results.jsonl` resolved = 3 decline_explain + 1 pending_reversal; `grep '⟨' ml/intent/data` returns nothing; no text said 7 duplicate warnings.
Disagreements: none. Note: the report's section 2 "3.5 MB" and section 4 "[95% CI]" headers are written by compare.py and cannot be relabelled here.
Verify: same command -> 2.

### T19 repair 1 — loader never raises
Changed: `classifier/loader.py` (the post-sha256 `try` now catches `Exception`, reason carries the type name; sha256 check still precedes extraction), `tests/unit/test_classifier_contract.py` (+1 test: truncated `head.joblib` with matching sha256 returns `(None, reason)`; 12 tests).
Deviations: none.
Verify: pytest 12 passed; real bundle loads `intent_clf@v4`; ruff check/format, mypy (4 files), lint-imports 4 kept 0 broken.

## Human decisions at the verify gate (2026-10-01)
- `decline_explain` in degraded mode: amend the requirement. It is not served in degraded mode; it hands off instead of replying with the canned apology and counting as resolved. Relabel the staging case. No new template (D4 stands).
- `backend/app/api/v1/admin.py` (`demo_reset` passes `classifier=old_host.classifier`): approved; add to the spec touch map.
- Live-stack proof (V5): the human allows the verifier to read `data/secrets/credentials.csv` for one ES and one PT persona ("those credentials are dummy not real").
- scikit-learn: rely on the loader fix (any unpickle failure refuses the bundle). No pin change, no manifest version check.
Board update: T19 repair 1 PASS; T32 repair 1 done; T45 (decline_explain hands off in degraded mode) in progress.

### T45 — decline_explain hands off in degraded mode
Changed: `policies/escalation.yaml` (`decline_explain` added to `degraded_handoff_intents`, version 5 -> 6, comment extended); `backend/tests/unit/test_degraded.py` (+`test_degraded_decline_explain_hands_off`, ES text added to `_TEXTS`/stub); staging `h-decline_explain-tool_failure-pt-br-05.yaml` relabeled `handoff:atencion` (required_tools [], handoff fields as other staging handoff cases, eligible_for_automation false, reviewer/reviewed_at null); `docs/requirements/learned-intent-fallback.md`; `docs/solution-docs/04-contracts.md` (escalation mirror v6 + list, SSE debug gains `degraded`).
Facts: the list alone suffices (next_intent.py `enqueue` sets llm_unavailable before any flow node), no node code touched. No test or doc pinned version 5 except the 04 header (updated). Other staging files and heldout/ untouched; `make eval-freeze-check` OK.
Verify: `cd backend && uv run pytest tests/unit/test_degraded.py tests/unit/test_abstain.py -q` -> 12 passed.
Run 3 (`eval/reports/dev-db8b7c5706-run3-classifier-decline-handoff`, PYTHONPATH=backend, classifier intent_clf@v4 loaded, log scratchpad t45-run3.log): played 8, resolved 1, clarified 4, abstained 0, handoff 3, unsafe 0/8. Verdicts 4 passed (3 card_block, pending_reversal), 4 failed: decline_explain s,p1,p2 (handoff:atencion vs normal-mode label resolved; expected) and a-card_status s (clarified, want resolved; known 2-card persona picker). Degraded 8/8; 24 nlu LLM calls all unavailable, 0 provider completions; PII hits 0.
Open: dev decline_explain scenario label still says resolved (out of scope, would need relabel/fault split); heldout report counts unchanged.
Board update: T45 done (a49e294): decline_explain hands off in degraded mode, run 3 = 1 resolved / 4 clarified / 3 handoff / 0 unsafe. T32 repair 2 and V5 in progress.

### T32 repair 2
Changed: `nlu_classifier.md` section 7 (degraded column = run 3 `eval/reports/dev-db8b7c5706-run3-classifier-decline-handoff/`: 1 resolved, 4 clarified, 0 abstained, 3 handoff, 0 unsafe, 4 passed / 4 failed, degraded 8/8; run 2 kept as today; run 1 listed as record; caveats rewritten) and section 8 (scikit-learn limitation). `MODEL_CARD.md`: intended use and out of scope name the degraded handoff intents (transaction_search, general_question, decline_explain, from `policies/escalation.yaml` v6), e2e line uses run 3, scikit-learn limitation added, limitation numbering now 1-15; the old open scikit-learn item merged into the decided one.
Checked against run 3 files: results.jsonl outcomes (1 resolved, 4 clarified, 3 handoff:atencion), metrics unsafe k=0, transcripts degraded true 8/8, llm_calls 24 all unavailable.
Disagreements: none. Note: metrics.json `safe_automated_resolution` k=4 counts passed verdicts, not resolved outcomes; I used results.jsonl outcomes.
Verify: same command -> 2.
Board update: V5 done: live degraded turns pass; FAIL cardy.degraded span attribute never recorded (request span already ended). T21 repair 1 in progress.

### T46 (T21 repair 1)
Changed: `backend/app/domains/conversation/runner.py` (new `_run_turn_traced` wraps `_run_turn` in span `cardy.turn`; `start_turn` creates the task from it; the existing `set_attribute("cardy.degraded", degraded)` in `_run_turn` now lands on that live span), `backend/tests/unit/test_degraded.py` (runner test asserts span + attribute via in-memory exporter, no new fixtures).
Facts the next tasks need: no other span/tracer in `app/` existed; tests call `runner._run_turn_traced`. The attribute is only set on the success path (not on `turn.failed`).
Deviations: none.
Verify: `pytest tests/unit/test_degraded.py -q` → 8 passed; ruff check/format, mypy, lint-imports clean.
Board update: T46 done (span cardy.turn carries cardy.degraded; unit-tested, not re-proven live). Final make check running; no second verify round (human: card over-extended).
