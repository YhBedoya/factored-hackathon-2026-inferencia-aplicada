# Plan: REQ-learned-intent-fallback — learned intent classifier and LLM-free degraded mode

Spec: [`docs/specs/learned-intent-fallback.md`](../specs/learned-intent-fallback.md) · Branch: `feat/learned-intent-fallback` (base `develop` @ `db8b7c5`) · Owner: Dev A

## Facts checked against the repo

**Where things are today (develop @ db8b7c5)**
- `ml/` does not exist. Every `ml/intent/**` path below is new.
- `.gitignore` has a bare `data/` line. It matches *any* directory called `data`, so `ml/intent/data/` is ignored until a `!ml/intent/data/` line is added (T1). The training fixture is therefore named `ml/intent/tests/fixtures/dataset/`, not `data/`.
- `backend/pyproject.toml` has `[dependency-groups] dev = [...]` and `[tool.uv] package = false`. It has no `default-groups`, and no scikit-learn, fastembed, onnxruntime, joblib or matplotlib. numpy is only a transitive dependency in `uv.lock`.
- mypy is strict for `app.core.*`, `app.domains.conversation.*` and `app.domains.policy.*`. The new classifier package falls under it, so the untyped sklearn, fastembed, onnxruntime and joblib need `ignore_missing_imports` overrides (T1).
- `backend/.importlinter` forbids the LLM SDKs outside `app.core.llm`. fastembed, onnxruntime and sklearn are not forbidden.

**Docker**
- `backend/Dockerfile` does `uv sync --frozen --no-install-project`, then `COPY . .`, then `uv sync --frozen`.
- It copies personas via `COPY --from=eval personas.yaml /app/eval/personas.yaml`. That named context comes from `docker/docker-compose.base.yml`, where the `backend:` build has `context: ../backend` and `additional_contexts: eval: ../eval`.
- The CMD and the dev compose `command:` both use `uv run uvicorn ...`. Plain `uv run` syncs the default groups at start, so excluding the `ml` group from the image needs care at run time too (T24).

**Conversation graph (`backend/app/domains/conversation/graph.py`)**
- It holds the literal tables:
  - `_MANAGEMENT_INTENTS = frozenset({"greeting","thanks_close","affirm","deny"})`
  - `_INTENT_NODES`: card_status and balance_due → card_info; card_block → card_block; card_unlock → card_unlock; replacement_request → replacement; unrecognized_charge → unrecognized_charge; decline_explain → decline_explain; transaction_search → tx_search; pending_reversal_explain → tx_explain
  - `_FLOW_NODES`
- `human_request` and `general_question` are **not** in `_INTENT_NODES`.
  - `human_request` reaches `handoff_summary` through the escalation rule in `nodes/route.py`.
  - `general_question` falls to `"unsupported"` via `_dispatch` (line 313).
  - So the registry gives these two `node: null`, and `_INTENT_NODES` must be rebuilt **exactly equal** to today's literal.
- `_entry` (line 269) sends `escalation_reason == "llm_unavailable"` to `fallback`. Per the accepted planner assumption this shortcut **stays**, for the classifier-not-loaded kill-switch path.
- The edge maps after `enqueue` and `next_intent` have no `"fallback"` key.
- The diagram `docs/diagrams/turn-graph-v0.mmd` is checked by `tests/unit/test_graph.py::test_graph_compiles_and_diagram_is_current`. Regenerate it with `make graph-diagram`.
- `DebugInfo` (line 194) is a frozen pydantic model. `run_turn` (line 658) returns `(str, DebugInfo)`.

**Conversation nodes**
- `nodes/load_session.py` sets `escalation_reason="llm_unavailable"` when `get_settings().llm_disabled` and `mode != "human"`. `_guess_language(text)` lives there and is imported by `tests/unit/test_faults.py`.
- `nodes/understand.py::understand`: on `LLMError` it returns `{"nlu": None, "language": previous, "escalation_reason": "llm_unavailable"}`.
- `nodes/compose.py::compose` (line 347): on `LLMError` (line 403) it returns `{"escalation_reason":"llm_unavailable","grounding":"template"}`.
- `nodes/route.py::route` is an edge function. It imports `_FLOW_NODES`, `_INTENT_NODES` and `_MANAGEMENT_INTENTS` from graph. It **ignores** an `escalation_reason` already in state ("only a rule hit this turn escalates from here").
- `nodes/smalltalk.py` gives `ask_what_else` to an ambiguous result with no intents (around line 89) and resets `clarification_failures`.
- `clarification_failures` already exists in `TurnState` (`state.py`) and is used by the flows. `clarification_exhausted` is a template kind and an `escalation.yaml` rule (`queue: atencion`).
- `baseline/template_compose.py` defines `baseline_understand`, `baseline_compose` and `baseline_handoff_summary`. `build_graph` imports those and `baseline_abstain` **lazily** inside the function, which is the sign of an import cycle. The degraded swaps must import them lazily too.
- `runner.py`:
  - builds `configurable` around line 276 with thread_id, session, bank_tools, llm, bank_write_tools, vault, handoff_tools and audit. There is no `classifier` key yet.
  - records `nlu_result` `{language,status,intents}` only when `nlu is not None` (around line 333).
  - records `reply_sent` `{route, ui_kinds, length, fact_values, grounding?}` (around line 381).
- `hosting.py`: `TurnHost(graph, pool, llm, tasks)` and `open_host(database_url, llm, system)`. `main.py::_lifespan` calls `load_card_select_policy()` and then `open_host`.
- `app/core/telemetry.py` instruments FastAPI. There is no app-level span code, so `cardy.degraded` goes on `trace.get_current_span()`.
- `core/config.py`:
  - Settings has `faults` and `llm_disabled`. `_REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"`.
  - The eval harness starts the backend with `cwd=backend/` and `env={**os.environ, ...}` (`eval/harness/runner.py::_start_backend`), so `INTENT_MODEL_DIR` from the shell passes through.

**Parsing sources the classifier reuses**
- `localization/format.py::mask_card(last4)` returns `"•••• {last4}"` (four U+2022, one space).
- `app/core/pii.py` masks 13–19-digit card numbers only, so the 4 digits survive masking.
- `flows/card_block.py` has private `_TEMPORARY_LOCK_LABEL` (line 87: es "Bloqueo temporal", pt "Bloqueio temporário") and `_PERMANENT_BLOCK_LABEL` (line 91: es "Reportar pérdida o robo", pt "Reportar perda ou roubo"). Both are used as `PickerOption(label=...)`. The frontend `QuickReplies.tsx` sends a chip's label as typed text.
- `baseline/keyword_nlu.py` helpers are private:
  - `_CLAUSE_SPLIT`, `_normalize`, `_lexicon()` (keys negators, window, exempt, intents, qualifiers, market, scope, markers), `_negated(clause, start, lex)`, `_hits`, `_exclusive`
  - The block-qualifier rule is inline in `keyword_nlu()`.

**Policies and the LLM registry**
- `policies/escalation.yaml` is `version: 4` and has `llm_unavailable: {queue: null, priority: normal}`. `app/domains/policy/escalation.py` models are frozen with `extra="forbid"`, so a new YAML key needs a model field. Policies load through `app/domains/policy/registry.py::get_policies()`.
- `policies/scope.yaml` topics are `pix_boleto` (out_of_market), and `loans`, `accounts`, `investments`, `insurance`, `transfers`, `other` (all out_of_scope).
- `Intent` Literal (`schemas.py`):
  - 11 core: card_status, balance_due, decline_explain, transaction_search, pending_reversal_explain, card_block, card_unlock, unrecognized_charge, replacement_request, human_request, general_question
  - 4 management
  - 11 stretch
  - Label set = 15 + 7 topics = **22 classes**.
- The `nlu@v4.md` intent list is under "## Lista cerrada de intents (26)" in lines starting `Core:`, `Gestion de la conversacion:` and `Stretch`.
- `app/core/llm/registry.py`:
  - `Step = Literal["nlu","compose","handoff_summary","paraphrase","simulate","judge"]`.
  - `paraphrase` is the model for an eval-only openai step: `MODEL_REGISTRY {"openai": "gpt-6-luna"}`, `TEMPERATURE 1.0`, `STEP_PROVIDER "openai"`.
  - `backend/scripts/paraphrase_seeds.py` shows the call: `PromptRef("paraphrase", 1)`, the prompt file read from disk as `system`, `llm.structured(step=, prompt=, system=, user=, schema=)`, client from `get_llm_client()`.

**Eval harness**
- `eval/harness/runner.py::fault_groups(cases)` (line 263) groups by `frozenset(case.setup.faults)`.
- `eval/harness/__main__.py --cases` takes comma-separated seed_id prefixes, and each seed brings its variants.
- `eval/tests/test_runner_faults.py` exists, with `_Case`/`_Setup` stubs and `test_one_backend_per_fault_set`.
- `eval/harness/nlu_eval.py` has:
  - `NluItem(id, text, country, pending, expected_intents, expected_language, language_variant, expected_status)`
  - `derive_suite_items(cases, personas_path)`, `load_smoke_items(path)`, `score(items, predictions)`, `async compare(...)`, `render`
  - `SMOKE_PATH` and `PERSONAS_PATH`, plus the backend `sys.path` pattern
- `eval/harness/metrics.py` has `wilson`, `Rate`, `percentiles`.
- **Dev NLU items today:** `load_smoke_items` gives 20, and `derive_suite_items(load_dir(eval/scenarios/dev))` gives 92 (36 seed `.s` cases plus 56 paraphrase `.pN` cases).
  - Seeds-only gives 20 + 36 = **56**, the spec's "about 56".
  - All cases gives **112** (see the open question in the reply).
  - Every one of the 15 `classifier: true` intents has at least one dev or `eval/nlu` item today: greeting, thanks_close, affirm and deny have 1 each, unrecognized_charge has 2, and the rest have more.
- D23 cases:
  - `eval/scenarios/dev/d-card_block-tool_failure-es-co-01.yaml` has `setup.faults: [bedrock_timeout]`, `expected_outcome: handoff:atencion`, 3 cases, and `reviewer: null` already. Its label model to mirror is `eval/scenarios/dev/d-card_block-ambiguous-es-co-01.yaml`.
  - The 5 staging files are `eval/scenarios/_staging/heldout/h-balance_due-tool_failure-es-mx-02.yaml`, `h-card_status-tool_failure-es-ar-01.yaml`, `h-card_status-tool_failure-pt-br-04.yaml`, `h-decline_explain-tool_failure-pt-br-05.yaml` and `h-pending_reversal_explain-tool_failure-pt-br-03.yaml`.
- Criterion-8 dev case set, exactly 8 cases: `CASES=d-card_block-tool_failure-es-co-01,a-card_status-normal_resolution-es-co-01,d-pending_reversal_explain-normal_resolution-pt-br-01,d-decline_explain-normal_resolution-pt-br-01` (3 + 1 + 1 + 3).

**Docs**
- The last ADR in `docs/solution-docs/decision-log.md` is ADR-031, so this card adds ADR-032.
- `06` R11 row is at line 17.
- `02` lines 126 and 141 are the `LLM_DISABLED` and "Tool / LLM failure" texts.
- `01` line 105 is the cost guard.
- `04` §5 shows `escalation.yaml v4` at line 239, and §6 covers audit events.
- `05` line 48 is the "Learned component" row.
- `README.md` has no "Where AI is used" section.
- The requirement doc's Source line already says "AI-generated (gpt-6-luna), human-audited" and its Owner line says Dev A, so no edit is needed there.

**Commands that exist today**
- Backend commands run from `backend/`: `uv run pytest ...`, `uv run ruff check <paths>`, `uv run ruff format --check <paths>`, `uv run mypy <paths>`, `uv run lint-imports`.
- Eval and ml commands run from the repo root:
  - tests: `uv run --project backend pytest eval/tests/<file> -q`
  - lint: `uv run --project backend ruff check --config backend/pyproject.toml <paths>` and the matching `ruff format --check --config backend/pyproject.toml <paths>`
  - legacy harness files add `--ignore E501,RUF005,UP047`
- `.env` is loaded into a shell with `set -a; . ./.env; set +a`.
- `make check` (Makefile lines 62–71) does not touch `ml/` or `eval/`.
- Ignore the `uv` warning "VIRTUAL_ENV ... does not match"; it is harmless.

**Planned names that cross tasks**
Each implementer records the real name in the state file if it differs.
- **Registry** (`backend/app/domains/conversation/intent_registry.py`, T2):
  - `IntentRow` (pydantic: intent, node, tier, classifier, training_dir, lexicon_key) and `load_registry() -> Registry` (`label_set_version`, `intents`), cached.
  - `classifier_labels() -> tuple[str, ...]`: the `classifier: true` intents in registry order, then the `scope.yaml` topics in file order.
  - `intent_nodes() -> dict[str, str]`: rows with a non-null node and tier ≠ management.
  - `management_intents() -> frozenset[str]`.
  - Row values: management rows have `node: smalltalk`; human_request, general_question and every stretch row have `node: null`.
- **Graph** (T2):
  - `GraphState.degraded: NotRequired[bool]` and `DebugInfo.degraded: bool = False`.
  - `_dispatch` returns `"fallback"` when `state.get("escalation_reason") == "llm_unavailable"`.
- **Degraded semantics** (D2 + D11 read together):
  - `degraded` is True **only when a classifier is loaded** (`configurable.get("classifier") is not None`) **and** either an LLM call raised `LLMError` this turn or `LLM_DISABLED` is on.
  - With no classifier, every node behaves exactly as today. The existing tests `test_bedrock_timeout_fallback_handoff_es`, `test_cards_write_error_fallback_handoff_pt` and `test_readback_mismatch_action_unverified_es` in `tests/unit/test_faults.py` stay unchanged and must keep passing, because `make_session` passes no classifier.
- **The classifier reaches nodes through `config["configurable"]["classifier"]`** (an `IntentClassifier | None`). `runner.py` sets it from `TurnHost.classifier`. `make_session` in `backend/tests/conftest.py` gains `classifier=None` (T23).
- **Shared parsing seams** (T3):
  - `localization/format.py`: `CARD_MASK_RE` and `parse_card_mask(text) -> str | None` (returns the 4 digits), both exported from `localization/__init__.py`.
  - `flows/card_block.py`: public `TEMPORARY_LOCK_LABEL` and `PERMANENT_BLOCK_LABEL` (`dict[Language, str]`).
  - `baseline/keyword_nlu.py`:
    - `split_clauses(text) -> list[str]` (normalized clauses)
    - `qualified_block_kind(text) -> Literal["temporary_lock","permanent_block"] | None` (the qualifier rule)
    - `lexicon_hits(clause, lexicon_key) -> list[bool]` (one entry per hit; True = inside the negation window)
- **Classifier package** (`backend/app/domains/conversation/classifier/`):
  - `scorers.py` (T5):
    - `Scorer` Protocol with `labels: tuple[str, ...]` and `predict_proba(texts: Sequence[str]) -> list[dict[str, float]]`
    - `SklearnScorer(estimator, labels, embedder=None)`
    - `Embedder(model_name, cache_dir)` (fastembed, `local_files_only`)
  - `adapter.py` (T12): the `IntentClassifier` Protocol (spec contract), and `ClassifierAdapter(scorer, *, tau, version, label_set_version)` implementing D9/D10.
  - `loader.py` (T19): `load_classifier(model_dir: Path) -> tuple[IntentClassifier | None, str]` (classifier, reason).
  - Test helper `backend/tests/stub_classifier.py` (T12): `StubScorer(mapping: dict[str, dict[str, float]])` and `make_stub_classifier(mapping, tau=0.5) -> ClassifierAdapter`. It is the real adapter over a fake scorer.
- **Bundle:**
  - `ml/intent/models/intent_clf@vN.tar.gz` holds `manifest.json` (spec fields), `head.joblib` (the fitted sklearn estimator; a Pipeline for C2) and `embeddings/` (the fastembed files when `embedding_model` is set).
  - `ml/intent/model.lock` is **JSON** `{"version","sha256","label_set_version","s3_uri": null}`. T19 commits a placeholder with nulls, and the compare run overwrites it.
  - The loader reads the lock at `Path(INTENT_MODEL_DIR).parent / "model.lock"`.
  - It checks the tarball's sha256 **before** unpickling, then extracts and checks `label_set_version` against the registry.
- **Settings `intent_model_dir`:**
  - The default is `Path(__file__).resolve().parents[3] / "ml" / "intent" / "models"` (the repo path, used by the host-run eval backend).
  - The image sets `ENV INTENT_MODEL_DIR=/app/ml/intent/models`, which is outside the dev bind mount `../backend/app:/app/app`.
- **Docker:** a named context `intent: ../ml/intent`, needed so `model.lock` reaches the build next to `models/`, plus `ml/intent/.dockerignore`. The image copies `model.lock` and `models/` to `/app/ml/intent/`.
- **Make targets (T7), CLI flags the ml modules must accept:**
  - `intent-gen` → `python -m ml.intent.generate [--locale L] [--class C]`
  - `intent-train` → `python -m ml.intent.train --candidate $(or $(CANDIDATE),all) --seed $(or $(SEED),42)`
  - `intent-compare` → `python -m ml.intent.compare --seed $(or $(SEED),42)`
  - All run as `uv run --project backend python -m ...` from the repo root.
  - Every ml CLI also takes `--data-dir` (default `ml/intent/data`) and `--runs-dir` (default `ml/intent/runs`). train and compare take `--run-id`. compare also takes `--models-dir`, `--lock` and `--no-ref`, so tests and proofs never touch the real dirs.
- **Run records:**
  - `ml/intent/runs/<run_id>/train.json` holds data_version, data_sha256, label_set_version, candidate, hyperparameters, seed, `metrics`, `prediction_hash` (sha256 over the sorted out-of-fold label and probability rows, rounded to 6 dp) and the confusion matrix.
  - compare writes `nlu_classifier.md`, `nlu_classifier.json`, `figures/` and `misses.yaml` into its own run dir.
- **ml import rule:**
  - `ml/__init__.py`, `ml/intent/__init__.py` and `ml/intent/tests/__init__.py` make pytest's rootdir prepend work, the same way as `eval/`.
  - ml modules reach `app.*` with the same `sys.path` insert of `backend/` that `eval/harness/nlu_eval.py` uses.
  - Training features and heads come from the backend `classifier/scorers.py`, so train and serve share one code path.
- **`ml` dependency group:** `[tool.uv] default-groups = ["dev", "ml"]`, so every parallel agent's `uv run` sees one environment. The image excludes the group (T24). The embedding cache is `ml/intent/.cache/fastembed/` (git-ignored, docker-ignored). T1 records the two exact fastembed model ids.

**D10 negation, as this plan reads it (flag to the human if wrong)**
- A clause's prediction is dropped when its predicted label has a registry `lexicon_key` and **every** lexicon hit for that key in the clause lies inside `keyword_nlu`'s negation window.
- A clause with no lexicon hit for the predicted label keeps its prediction.

## Components

1. **Intent registry**: `backend/app/domains/conversation/intents.yaml` plus `intent_registry.py`. It depends on `schemas.py` (Literal) and `app.domains.policy` (scope topics).
2. **Graph wiring**: `graph.py` reads the registry, adds `degraded` to the state and debug info, and adds the D7 dispatch to `fallback`.
3. **Shared parsing seams**: the mask parse in `localization/format.py`, the public chip labels in `flows/card_block.py`, and the public clause/qualifier/negation helpers in `baseline/keyword_nlu.py`. There is no behavior change.
4. **Classifier package** `backend/app/domains/conversation/classifier/`:
   - `scorers.py`: features and heads, shared with training.
   - `adapter.py`: the D9/D10 `NLUResult` contract.
   - `loader.py`: the D11 lock, sha256, label-set and refusal checks.
   - It depends on 1 and 3.
5. **Degraded nodes**:
   - `understand` and `load_session` (classifier swap, D8 counter)
   - `route` and `smalltalk` (D8)
   - `templates` (`clarify_rephrase`)
   - `compose`, `abstain` and `handoff_summary` (baseline swaps)
   - `next_intent` plus the escalation policy (D7)
   - These depend on 2 and 4's Protocol.
6. **Runtime wiring**: `runner.py` (audit fields, OTel, configurable), `hosting.py`, `main.py` (startup load and log), `config.py`, `.env.example`. Depends on 4 and 5.
7. **ml/intent**:
   - `data_io.py` (data contract)
   - `generate.py` plus the `intent_gen` step in `app/core/llm/registry.py` and `prompts/intent_gen@v1.md`
   - `candidates.py`, `train.py`
   - `leakage.py`, `check.py`
   - `compare.py`, `report.py`, `export.py`
   - `model.lock`, `MODEL_CARD.md`, `runs/`, `tests/`
   - It depends on 1, 4 and the eval harness.
8. **Eval harness deltas**: `--faults` (in `__main__.py` and `runner.py`), and bootstrap CI, McNemar and the prediction hook (in `metrics.py` and `nlu_eval.py`).
9. **Packaging**: `backend/pyproject.toml` and `uv.lock` (the `ml` group, then the winner's runtime deps), `backend/Dockerfile`, `docker/docker-compose.base.yml` and `docker-compose.dev.yml`, `.gitignore`, the `Makefile`.
10. **Docs and data labels**: ADR-032 and `01`/`02`/`04`/`05`/`06`, README, MODEL_CARD, and the D23 scenario relabels.

## Build order

1. **Dependencies first (T1).** The scorers, training and loader import sklearn and fastembed, and mypy needs the overrides. The lockfile change must land before any parallel agent runs `uv run`.
2. **Foundations in parallel (T2–T11).** These are the registry and graph tables, the parsing seams, the ml data contract and fixture, the scorers, the generation step and prompt, the harness `--faults` and Makefile targets, metrics, the D23 relabels and the docs. None needs another.
3. **Contracts on top (T12–T17):**
   - The adapter needs the registry (T2), the seams (T3) and the `Scorer` Protocol (T5).
   - `generate.py` needs the data contract (T4), the step (T6) and the registry labels (T2).
   - `train.py` needs T4 and T5.
   - The leakage check needs T4 and T2.
   - The compose/abstain/handoff and policy/next_intent swaps need `GraphState.degraded` (T2).
4. **Then (T18–T20):**
   - The LIVE generation needs `generate.py` (T13) and `make intent-gen` (T7).
   - The loader needs the adapter (T12) and the scorers (T5).
   - `understand` and the D8 work need the `IntentClassifier` Protocol (T12).
5. **Then (T21, T22):** the runtime wiring needs the loader (T19). compare needs train (T14), metrics (T8) and the loader for the parity check (T19).
6. **T23:** the degraded tests need every degraded node (T16, T17, T20), the runtime fields (T21) and the stub (T12).
7. **T24:** the Docker change needs the lock placeholder (T19) and the `ml` group (T1). It runs alone because it rebuilds images.
8. **The HUMAN audit (T25)** starts once T18 has written data. It runs beside W5–W7 and blocks nothing before W8.
9. **Post-audit, strictly in order:**
   - check wiring (T26), which proves the data is complete and leak-free **before** training
   - final training twice (T27)
   - the real compare with Ref (T28), which selects the winner and writes the bundle and lock
   - the winner's runtime deps (T29), which needs T28's choice
   - the image proof (T30)
   - the end-to-end degraded eval (T31), which needs the bundle and deps
   - the final report and model card (T32), which need T31's numbers

## Touch map

| File | New / modified | Change |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modified | `ml` group (scikit-learn, fastembed, onnxruntime, joblib, matplotlib), `default-groups`, mypy overrides (T1); winner's deps to runtime (T29) |
| `.gitignore` | modified | `!ml/intent/data/`, `ml/intent/models/*` + `!ml/intent/models/.gitkeep`, `ml/intent/.cache/` |
| `ml/intent/models/.gitkeep` | new | keeps the Docker context present |
| `backend/app/domains/conversation/intents.yaml`, `intent_registry.py` | new | registry (D13) |
| `backend/app/domains/conversation/graph.py` | modified | tables from registry, `degraded` fields, `_dispatch`→fallback + edge-map keys |
| `docs/diagrams/turn-graph-v0.mmd` | modified | regenerated |
| `backend/app/domains/localization/format.py`, `localization/__init__.py` | modified | `CARD_MASK_RE`, `parse_card_mask` |
| `backend/app/domains/conversation/flows/card_block.py` | modified | chip labels public |
| `backend/app/domains/conversation/baseline/keyword_nlu.py` | modified | public helpers, behavior unchanged |
| `backend/app/domains/conversation/classifier/__init__.py`, `scorers.py`, `adapter.py`, `loader.py` | new | inference |
| `backend/app/domains/conversation/nodes/understand.py`, `load_session.py`, `route.py`, `smalltalk.py` | modified | classifier swap, D8 |
| `backend/app/domains/conversation/templates.py` | modified | `clarify_rephrase` |
| `backend/app/domains/conversation/nodes/compose.py`, `abstain.py`, `handoff_summary.py` | modified | baseline swaps |
| `backend/app/domains/conversation/nodes/next_intent.py` | modified | D7 |
| `backend/app/domains/policy/escalation.py`, `policies/escalation.yaml` | modified | `degraded_handoff_intents`, version 5 |
| `backend/app/domains/conversation/runner.py`, `hosting.py`, `backend/app/main.py`, `backend/app/core/config.py`, `.env.example` | modified | classifier load and plumbing, audit fields, OTel attr |
| `backend/app/core/llm/registry.py` | modified | `intent_gen` step |
| `backend/tests/stub_classifier.py` | new | stub scorer behind the real adapter |
| `backend/tests/conftest.py` | modified | `make_session(classifier=)`, autouse empty `INTENT_MODEL_DIR` |
| `backend/tests/unit/test_registry_consistency.py`, `test_classifier_contract.py`, `test_degraded.py` | new | spec tests |
| `backend/tests/unit/test_faults.py` | modified | kill-switch test rewritten |
| `backend/Dockerfile`, `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml`, `ml/intent/.dockerignore` | modified / new | bundle into image, sha256 re-check, no `ml` group |
| `Makefile` | modified | `intent-gen`, `intent-train`, `intent-compare`, `eval FAULTS=` (T7); `check` runs `ml.intent.check` + ml tests (T26) |
| `eval/harness/__main__.py`, `eval/harness/runner.py`, `eval/tests/test_runner_faults.py` | modified | `--faults` union |
| `eval/harness/metrics.py`, `eval/harness/nlu_eval.py` | modified | bootstrap CI, McNemar, prediction hook, dev-item selector, OOS/false-abstain rates |
| `eval/scenarios/dev/d-card_block-tool_failure-es-co-01.yaml` + 5 `_staging/heldout/h-*-tool_failure-*.yaml` | modified | D23 |
| `ml/__init__.py`, `ml/intent/__init__.py`, `data_io.py`, `generate.py`, `candidates.py`, `train.py`, `leakage.py`, `check.py`, `compare.py`, `report.py`, `export.py` | new | training side |
| `ml/intent/prompts/intent_gen@v1.md` | new | generation prompt |
| `ml/intent/tests/__init__.py`, `tests/test_leakage.py`, `tests/fixtures/dataset/**` | new | leakage test, fixture |
| `ml/intent/data/<locale>/<class>.yaml` (88 files) | new | generated + audited data |
| `ml/intent/model.lock` | new | placeholder → real pin |
| `ml/intent/runs/<run_id>/**`, `ml/intent/MODEL_CARD.md` | new | run records, report, model card |
| `docs/solution-docs/decision-log.md`, `01-technical-design.md`, `02-conversation-design.md`, `06-engineering-rules.md` | modified | ADR-032, D2 wording, layout |
| `docs/solution-docs/04-contracts.md`, `05-evaluation-plan.md`, `README.md` | modified | audit fields, escalation YAML, learned-component row, "Where AI is used" |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| fastembed downloads a model at load time. That is a network call at startup and breaks D11 | The `Embedder` always passes `cache_dir` plus `local_files_only=True` (T5). The bundle carries the ONNX files (T22). T30 loads the bundle in a container with `--network none` |
| Embeddings or CV are not deterministic, which breaks criterion 1 | Fixed seed and sorted file and item order (T4, T14). ONNX runs single-threaded if needed (T5). T14 proves two identical runs on the fixture, and T27 proves it on real data |
| Unpickling an untrusted `head.joblib` | The loader checks the sha256 against the committed lock **before** extraction or unpickling (T19). The test covers a wrong sha256 |
| Import cycles: classifier ↔ `nodes.load_session` / `flows.card_block` / graph | Lazy imports inside functions, as `build_graph` already does (T12, T16, T19). Each verify runs `lint-imports` plus an import of the module |
| A degraded swap changes behavior when no classifier is loaded | "degraded only with a classifier" is a fact in the state file. T16, T17 and T20 each run the unchanged `tests/unit/test_faults.py` |
| Unit tests that build `create_app()` pick up a real local bundle once one exists | T23 adds an autouse fixture that sets `INTENT_MODEL_DIR` to an empty tmp dir and clears the settings cache |
| The graph diagram drifts | Only T2 changes edges and regenerates the diagram. T20's `route` may return only targets already in the `understand` edge map, and its verify runs `test_graph.py` |
| `data/` in `.gitignore` silently drops the training data | Negation line plus a `git check-ignore` proof (T1). The fixture dir is named `dataset/` |
| Leakage check reads or edits the frozen held-out set | It opens files read-only. T15 and T26 verify with `git diff --exit-code eval/scenarios/heldout` and `make eval-freeze-check` (T9) |
| D23 relabel breaks the freeze | Only `_staging/heldout/` and dev are edited, and T9 runs `make eval-freeze-check` |
| The model is fitted in ml but scored differently in the backend | One scorer code path (T5). compare reloads the exported bundle through `load_classifier` and asserts the predictions equal the in-process ones (T22, T28) |
| `uv run` in the container syncs the `ml` group, causing a network install and a large image | T24 excludes the group at sync **and** at run, proved by a `--network none` start |
| A bundle present with a stale sha256 ships | Dockerfile `RUN` check (T24). T24 proves a fake tarball fails, and T30 proves the real one |
| The live LLM runs cost money and need keys | They are isolated LIVE tasks (T18, T28). Ref runs once over the dev items, and T13 has a `--plan` dry run |
| The degraded path gains a tool or write the normal path lacks (R2/R6) | The swaps reuse baseline functions only (T16, T20). The R2/R3 degraded tests are in T23. `test_r6_no_write_tools_in_llm_nodes.py` runs in T23's verify |
| The classifier sees raw PII | It takes `state["user_text"]` (already masked), and the training text uses `⟨KIND_n⟩` tokens (T13 prompt, T20) |
| The audit drags on and blocks code | The HUMAN task runs in the background from W5. Only W8+ waits for it |

## Tests

| Test | Written by |
|---|---|
| `backend/tests/unit/test_registry_consistency.py`: registry == Literal == `nlu@v4` list; labels ⊆ registry ∪ topics; built tables == today's; every classifier intent has a dev or `eval/nlu` item | T2 |
| same file, data coverage (every label has data in all 4 locales) | T26 |
| `backend/tests/unit/test_classifier_contract.py`: below τ, scope class, bare card_block, `•••• NNNN`, four chip labels, never `injection_suspected` | T12 |
| same file, stale `label_set_version` and wrong sha256 refuse to load | T19 |
| `eval/tests/test_runner_faults.py::test_cli_faults_merge` | T7 |
| `ml/intent/tests/test_leakage.py` | T15 |
| `backend/tests/unit/test_degraded.py::test_degraded_write_needs_token` (R2) | T23 |
| `backend/tests/unit/test_degraded.py::test_degraded_done_requires_readback` (R3) | T23 |
| `backend/tests/unit/test_degraded.py::test_degraded_paths[es]`, `[pt]` | T23 |
| `backend/tests/unit/test_faults.py::test_kill_switch_degraded` (replaces `test_llm_disabled_every_turn_falls_back`) | T23 |
| Command: `make intent-train` twice → identical `metrics` and `prediction_hash` | T14 (fixture), T27 (real data) |
| Command: `ml.intent.check` passes, and fails on the two mutations; `make check` wiring | T26 (the final `make check` is the verifier's) |

Success criteria → tasks:
1. T14, T27
2. T22, T28, T32
3. T23
4. T23
5. T15, T26
6. T11 (README), T32 (MODEL_CARD)
7. T24, T28, T30
8. T7, T9, T31
9. T10, T11

## Tasks

- [ ] T1: Add the `ml` dependency group, mypy overrides and git-ignore rules; pre-fetch the two embedding models (ALONE)
  - Depends on: nothing
  - Read exactly these: `backend/pyproject.toml`; `.gitignore`; spec §Decisions D12, D14, D15
  - Acceptance:
    - `backend/pyproject.toml` has a `[dependency-groups] ml` group with scikit-learn, fastembed, onnxruntime, joblib and matplotlib. Runtime `dependencies` are unchanged.
    - `[tool.uv]` gains `default-groups = ["dev", "ml"]`.
    - A `[[tool.mypy.overrides]]` sets `ignore_missing_imports = true` for `sklearn.*`, `fastembed.*`, `onnxruntime.*`, `joblib.*` and `matplotlib.*`.
    - `uv.lock` is updated.
    - `.gitignore` gains `!ml/intent/data/`, `ml/intent/models/*`, `!ml/intent/models/.gitkeep` and `ml/intent/.cache/`.
    - The empty file `ml/intent/models/.gitkeep` exists.
    - Both C3 embedding models (multilingual e5-small and paraphrase-multilingual-MiniLM-L12-v2) are downloaded through fastembed into `ml/intent/.cache/fastembed/`. Use `TextEmbedding.add_custom_model` if a model is not in fastembed's list.
    - The state file records the exact model ids, any custom-model registration code, and that a second load works with `local_files_only=True`.
  - Verify:
    ```
    cd backend && uv sync && uv run python -c "import sklearn, fastembed, onnxruntime, joblib, matplotlib" && uv run mypy app/core/config.py
    cd .. && git check-ignore -q ml/intent/data/es-ar/x.yaml; test $? -eq 1 && git check-ignore -q ml/intent/models/a.tar.gz && git check-ignore -q ml/intent/models/.gitkeep; test $? -eq 1
    ```
  - Files: `backend/pyproject.toml`, `backend/uv.lock`, `.gitignore`, `ml/intent/models/.gitkeep`

- [ ] T2: Intent registry, registry-built graph tables, `degraded` state and debug fields, D7 dispatch edge, static `test_registry_consistency`
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/graph.py` (tables, `GraphState`, `DebugInfo`, `_dispatch`, the `enqueue`/`next_intent` edge maps, `run_turn`); `backend/app/domains/conversation/schemas.py` (`Intent`); spec §Contracts "intents.yaml (registry)" and D13
  - Acceptance:
    - `intents.yaml` has `label_set_version: 1` and one row per `Intent` member (26), using the node values in "Planned names" (state file).
    - `intent_registry.py` provides `load_registry`, `classifier_labels`, `intent_nodes` and `management_intents`. Scope topics come from `get_policies().scope`.
    - `graph.py` builds `_INTENT_NODES` and `_MANAGEMENT_INTENTS` from the registry, and they are equal to today's literals.
    - `GraphState` gains `degraded: NotRequired[bool]`, and `DebugInfo` gains `degraded: bool = False`, filled by `run_turn` from the final state.
    - `_dispatch` returns `"fallback"` when `escalation_reason == "llm_unavailable"`, and both the `enqueue` and `next_intent` conditional edge maps gain `"fallback": "fallback"`.
    - The diagram is regenerated.
    - `test_registry_consistency.py` asserts:
      - the registry intent set == `get_args(Intent)` == the 26 backticked names in `prompts/nlu@v4.md`'s "Lista cerrada de intents (26)" section (parsed, never edited)
      - `classifier_labels()` == the 15 core and management intents followed by the 7 scope topics
      - the built tables equal the literal values copied into the test
      - every `classifier: true` intent appears in at least one `eval/nlu` smoke item or one dev scenario item. Use `eval/harness/nlu_eval.py`'s `load_smoke_items(SMOKE_PATH)` and `derive_suite_items(load_dir(eval/scenarios/dev), PERSONAS_PATH)`, imported with `sys.path` pointing at the repo root.
  - Verify:
    ```
    cd backend && make -C .. graph-diagram && uv run pytest tests/unit/test_registry_consistency.py tests/unit/test_graph.py -q && uv run ruff check app/domains/conversation/graph.py app/domains/conversation/intent_registry.py tests/unit/test_registry_consistency.py && uv run ruff format --check app/domains/conversation/graph.py app/domains/conversation/intent_registry.py tests/unit/test_registry_consistency.py && uv run mypy app/domains/conversation/graph.py app/domains/conversation/intent_registry.py && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/intents.yaml`, `backend/app/domains/conversation/intent_registry.py`, `backend/app/domains/conversation/graph.py`, `docs/diagrams/turn-graph-v0.mmd`, `backend/tests/unit/test_registry_consistency.py`

- [ ] T3: Shared parsing seams: card-mask parse next to `mask_card`, public chip labels, public keyword helpers (no behavior change)
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/localization/format.py` (`mask_card`); `backend/app/domains/conversation/flows/card_block.py` (lines 80–200, the two label dicts and `PickerOption`); `backend/app/domains/conversation/baseline/keyword_nlu.py`
  - Acceptance:
    - `format.py` defines `CARD_MASK_RE` (four U+2022 bullets, one space, 4 digits, the exact output of `mask_card`) and `parse_card_mask(text) -> str | None`. Both are exported from `localization/__init__.py`, and `parse_card_mask(f"Crédito {mask_card('6475')} · Activa") == "6475"`.
    - `card_block.py` renames the two dicts to public `TEMPORARY_LOCK_LABEL` and `PERMANENT_BLOCK_LABEL` and uses them.
    - `keyword_nlu.py` exposes `split_clauses`, `qualified_block_kind` and `lexicon_hits` (contracts in the state file), and `keyword_nlu()` itself uses them.
    - The output of `keyword_nlu` is unchanged.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_baseline.py tests/unit/test_format.py tests/unit/test_block_flows.py -q && uv run python -c "from app.domains.localization import parse_card_mask, mask_card; assert parse_card_mask('Crédito '+mask_card('6475')+' · Activa')=='6475'" && uv run ruff check app/domains/localization app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/keyword_nlu.py && uv run ruff format --check app/domains/localization app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/keyword_nlu.py && uv run mypy app/domains/localization app/domains/conversation/flows/card_block.py app/domains/conversation/baseline/keyword_nlu.py
    ```
  - Files: `backend/app/domains/localization/format.py`, `backend/app/domains/localization/__init__.py`, `backend/app/domains/conversation/flows/card_block.py`, `backend/app/domains/conversation/baseline/keyword_nlu.py`

- [ ] T4: `ml` package skeleton, training-data contract loader and a tiny fixture dataset
  - Depends on: nothing
  - Read exactly these: spec §Contracts "`ml/intent/data/<locale>/<class>.yaml`" and D19; `eval/harness/nlu_eval.py` lines 1–50 (the `sys.path` pattern to copy)
  - Acceptance:
    - `ml/__init__.py`, `ml/intent/__init__.py` and `ml/intent/tests/__init__.py` exist.
    - `ml/intent/data_io.py` defines:
      - pydantic models `DataItem` and `DataFile` (the spec contract, `extra="forbid"`)
      - `LOCALES = ("es-mx","es-co","es-ar","pt-br")`
      - `SLOT_MIX = {"plain":2,"regional":2,"typo_informal":2,"hard_negative":2,"negation":1,"short_answer":1}`
      - `load_files(data_dir) -> list[DataFile]` (sorted by locale, then class)
      - `accepted_items(files)`, `data_sha256(data_dir)` (sha256 over the sorted file bytes), `write_file(path, DataFile)`
      - `BACKEND_ROOT` plus the `sys.path` insert for later modules
    - The fixture `ml/intent/tests/fixtures/dataset/` holds 3 classes (`card_block`, `card_status`, `loans`) × 2 locales (`es-ar`, `pt-br`) × 5 families × 3 items (seed plus 2 paraphrases).
      - The items are hand-written, with `generator: fixture`, all `accepted: true` and slots from `SLOT_MIX` order.
      - The items are short and do not copy any text under `eval/`.
  - Verify:
    ```
    uv run --project backend python -c "from ml.intent.data_io import load_files, accepted_items, data_sha256; from pathlib import Path; d=Path('ml/intent/tests/fixtures/dataset'); f=load_files(d); assert len(f)==6 and len(accepted_items(f))==90; print(data_sha256(d))" && uv run --project backend ruff check --config backend/pyproject.toml ml/__init__.py ml/intent/__init__.py ml/intent/data_io.py ml/intent/tests/__init__.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/__init__.py ml/intent/__init__.py ml/intent/data_io.py ml/intent/tests/__init__.py
    ```
  - Files: `ml/__init__.py`, `ml/intent/__init__.py`, `ml/intent/data_io.py`, `ml/intent/tests/__init__.py`, `ml/intent/tests/fixtures/dataset/**`

- [ ] T5: Classifier scorers shared by training and serving (embedder + sklearn head)
  - Depends on: T1 (sklearn, fastembed and joblib installed; model ids and cache path in the state file)
  - Read exactly these: spec D9, D11, D14, D15; the state file's T1 entry (fastembed model ids and custom-model code)
  - Acceptance:
    - `backend/app/domains/conversation/classifier/__init__.py` exists (docstring, exports `Scorer`).
    - `classifier/scorers.py` defines:
      - `Scorer` (Protocol: `labels`, `predict_proba(texts) -> list[dict[str, float]]`)
      - `Embedder(model_name: str, cache_dir: Path)`, which wraps fastembed with `local_files_only=True` and registers the custom model the way T1 recorded, and has `embed(texts) -> numpy array`
      - `SklearnScorer(estimator, labels, embedder: Embedder | None)`, which embeds first when an embedder is given and returns probabilities keyed by label in `labels` order
    - sklearn and fastembed are imported inside functions, so `import app.domains.conversation.classifier` works without them.
    - No network access happens.
    - Passes mypy strict.
  - Verify:
    ```
    cd backend && uv run python -c "
    from sklearn.linear_model import LogisticRegression; from sklearn.pipeline import make_pipeline; from sklearn.feature_extraction.text import TfidfVectorizer
    from app.domains.conversation.classifier.scorers import SklearnScorer
    p=make_pipeline(TfidfVectorizer(analyzer='char_wb',ngram_range=(2,5)),LogisticRegression()).fit(['bloquear tarjeta','estado tarjeta','bloqueia cartao','status cartao'],['card_block','card_status','card_block','card_status'])
    s=SklearnScorer(p,tuple(p.classes_),None); r=s.predict_proba(['bloquear']); assert abs(sum(r[0].values())-1)<1e-6" && uv run ruff check app/domains/conversation/classifier && uv run ruff format --check app/domains/conversation/classifier && uv run mypy app/domains/conversation/classifier && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/classifier/__init__.py`, `backend/app/domains/conversation/classifier/scorers.py`

- [ ] T6: `intent_gen` eval-only LLM step and the `intent_gen@v1` prompt
  - Depends on: nothing
  - Read exactly these: `backend/app/core/llm/registry.py` (the `paraphrase` entries); `backend/scripts/paraphrase_seeds.py` (how a prompt file is read and passed); spec D19, D20
  - Acceptance:
    - `Step` gains `"intent_gen"` with `MODEL_REGISTRY {"openai": "gpt-6-luna"}`, `TEMPERATURE 1.0` and `STEP_PROVIDER "openai"`, with a comment citing ADR-032 and eval-only use.
    - `ml/intent/prompts/intent_gen@v1.md` (Spanish/Portuguese-aware, English instructions are fine) asks for, per cell (locale, class, class description, 10 slots in `SLOT_MIX` order):
      - 10 families, each a seed plus 2 paraphrases
      - written in that locale's register
      - PII only as `⟨CARD_1⟩`/`⟨NAME_1⟩`-style tokens (`app.core.pii.TOKEN_RE` kinds)
      - hard negatives that mention the class's words without that intent
      - negation items that negate it
      - short answers of 1–3 words
      - no bank names or real data
    - It is only used outside the served graph.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_llm_client.py tests/unit/test_r6_data_fields.py -q && uv run python -c "from app.core.llm.registry import MODEL_REGISTRY, STEP_PROVIDER; assert STEP_PROVIDER['intent_gen']=='openai'" && uv run ruff check app/core/llm/registry.py && uv run ruff format --check app/core/llm/registry.py && uv run mypy app/core/llm/registry.py && test -s ../ml/intent/prompts/intent_gen@v1.md
    ```
  - Files: `backend/app/core/llm/registry.py`, `ml/intent/prompts/intent_gen@v1.md`

- [ ] T7: Eval harness `--faults` union, and every new Make target (`eval FAULTS=`, `intent-gen`, `intent-train`, `intent-compare`)
  - Depends on: nothing
  - Read exactly these: `eval/harness/runner.py` (`fault_groups`, line 263, and where it is called); `eval/harness/__main__.py`; `eval/tests/test_runner_faults.py`
  - Acceptance:
    - `python -m eval.harness` accepts `--faults a,b` (validated against `app.core.config.Fault`).
    - The CLI set is unioned into every case's `setup.faults` where the fault groups are built, so `_start_backend` gets the union.
    - With no `--faults`, grouping is unchanged.
    - New `test_cli_faults_merge` (same `_Case`/`_Setup` stubs): a case with no faults and a case with `cards_write_error`, under `bedrock_timeout`, both land in groups whose fault set contains `bedrock_timeout`.
    - The `Makefile` `eval` line gains `$(if $(FAULTS),--faults $(FAULTS))`, and three targets are added with `##` help (exact recipes in the state file "Make targets"):
      - `intent-gen` (`LOCALE=`, `CLASS=` optional)
      - `intent-train` (`CANDIDATE=`, `SEED=42`)
      - `intent-compare`
  - Verify:
    ```
    uv run --project backend pytest eval/tests/test_runner_faults.py -q && make -n eval FAULTS=bedrock_timeout CASES=x | grep -q -- '--faults bedrock_timeout' && make -n intent-train SEED=42 | grep -q 'ml.intent.train' && make -n intent-gen LOCALE=es-ar CLASS=card_block | grep -q -- '--locale es-ar' && uv run --project backend ruff check --config backend/pyproject.toml --ignore E501,RUF005,UP047 eval/harness/__main__.py eval/harness/runner.py eval/tests/test_runner_faults.py
    ```
  - Files: `eval/harness/__main__.py`, `eval/harness/runner.py`, `eval/tests/test_runner_faults.py`, `Makefile`

- [ ] T8: Eval metrics for the classifier report: bootstrap macro-F1 CI, McNemar, prediction hook, dev-item selector, abstain rates
  - Depends on: nothing
  - Read exactly these: `eval/harness/metrics.py` (`wilson`, `Rate`); `eval/harness/nlu_eval.py` (`NluItem`, `derive_suite_items`, `load_smoke_items`, `_macro_prf`, `score`); spec D21
  - Acceptance:
    - `metrics.py` gains:
      - `bootstrap_ci(n_items, statistic, *, resamples=1000, seed=42) -> tuple[float, float]` (resamples item indices)
      - `mcnemar(a_correct, b_correct) -> dict` (`b`, `c`, exact two-sided binomial `p`, pure Python)
    - `nlu_eval.py` gains:
      - `dev_items(*, seeds_only: bool) -> list[NluItem]` (smoke plus the derived items from `eval/scenarios/dev`; `seeds_only` keeps suite items whose id ends in `.s`, giving 56; otherwise 112)
      - `predict_items(items, predict: Callable[[NluItem], NLUResult | None]) -> list[NLUResult | None]`
      - `abstain_rates(items, predictions) -> dict` (OOS recall over items whose expected status is out_of_*, and false abstain over in-scope items, each a `Rate` with Wilson CI)
    - `score` and `render` are unchanged.
  - Verify:
    ```
    uv run --project backend pytest eval/tests/test_metrics.py eval/tests/test_nlu_eval.py -q && uv run --project backend python -c "from eval.harness.metrics import mcnemar, bootstrap_ci; assert mcnemar([1,1,0,0],[1,0,1,0])['b']==1; lo,hi=bootstrap_ci(10, lambda idx: sum(idx)/len(idx)); assert lo<=hi; from eval.harness.nlu_eval import dev_items; assert len(dev_items(seeds_only=True))==56" && uv run --project backend ruff check --config backend/pyproject.toml --ignore E501,RUF005,UP047 eval/harness/metrics.py eval/harness/nlu_eval.py
    ```
  - Files: `eval/harness/metrics.py`, `eval/harness/nlu_eval.py`

- [ ] T9: Relabel the D23 `tool_failure` cases to their degraded outcome
  - Depends on: nothing
  - Read exactly these: spec D23; `eval/scenarios/dev/d-card_block-ambiguous-es-co-01.yaml` (the label shape of a lock_vs_block clarification); `eval/scenarios/dev/d-card_block-tool_failure-es-co-01.yaml`
  - Acceptance:
    - The dev case `d-card_block-tool_failure-es-co-01` expects the lock-vs-block clarification (mirror the ambiguous case's `expected_outcome`, tools and handoff fields) and keeps `setup.faults: [bedrock_timeout]`.
    - The five staging files keep their faults and get the outcome that the degraded path serves: the read-only intent answered, no handoff. Their every `reviewer`/`reviewed_at` is set to `null`. Note in each file's header comment that it was relabeled under ADR-032.
      - `eval/scenarios/_staging/heldout/h-balance_due-tool_failure-es-mx-02.yaml`
      - `h-card_status-tool_failure-es-ar-01.yaml`
      - `h-card_status-tool_failure-pt-br-04.yaml`
      - `h-decline_explain-tool_failure-pt-br-05.yaml`
      - `h-pending_reversal_explain-tool_failure-pt-br-03.yaml`
    - No file under `eval/scenarios/heldout/` changes.
  - Verify:
    ```
    uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && make eval-freeze-check && git diff --exit-code eval/scenarios/heldout && grep -c "reviewer: null" eval/scenarios/_staging/heldout/h-*-tool_failure-*.yaml
    ```
  - Files: `eval/scenarios/dev/d-card_block-tool_failure-es-co-01.yaml`, `eval/scenarios/_staging/heldout/h-balance_due-tool_failure-es-mx-02.yaml`, `eval/scenarios/_staging/heldout/h-card_status-tool_failure-es-ar-01.yaml`, `eval/scenarios/_staging/heldout/h-card_status-tool_failure-pt-br-04.yaml`, `eval/scenarios/_staging/heldout/h-decline_explain-tool_failure-pt-br-05.yaml`, `eval/scenarios/_staging/heldout/h-pending_reversal_explain-tool_failure-pt-br-03.yaml`

- [ ] T10: Docs A: ADR-032 and the D2 wording in `06`, `02`, `01`, plus the `06` §3 layout
  - Depends on: nothing
  - Read exactly these: spec §Decisions (D2, D5–D7, D11–D15, D20, D22); `docs/solution-docs/decision-log.md` (ADR-031's format); `docs/solution-docs/06-engineering-rules.md` §1 R11 and §3
  - Acceptance:
    - ADR-032 is "Trained intent classifier and LLM-free degraded mode". It covers:
      - the second learned component next to ADR-005
      - the degraded role and that it amends ADR-023
      - the registry
      - a local git-ignored bundle pinned by sha256 in `model.lock`, with S3 deferred to the deploy
      - the `intent_gen` step extending ADR-030's eval-only list
      - status Accepted, dated 2026-10-01
    - `06` R11 reads "2 retries with backoff, then the degraded path, then safe fallback + handoff".
    - `06` §3 layout adds `ml/intent/` and `conversation/classifier/` plus `intents.yaml`.
    - `02` line 126 and the "Tool / LLM failure" row (line 141) describe D2, D7 and D8.
    - `01` §7 cost guard (line 105) says `LLM_DISABLED` routes turns to the degraded path, with zero LLM calls, and hands off when no classifier is loaded.
  - Verify: `grep -q "ADR-032" docs/solution-docs/decision-log.md docs/solution-docs/06-engineering-rules.md docs/solution-docs/02-conversation-design.md docs/solution-docs/01-technical-design.md && grep -q "ml/intent" docs/solution-docs/06-engineering-rules.md`
  - Files: `docs/solution-docs/decision-log.md`, `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/01-technical-design.md`

- [ ] T11: Docs B: `04` audit fields and escalation YAML, `05` learned-component row, README "Where AI is used"
  - Depends on: nothing
  - Read exactly these: spec §Contracts "Audit" and "Graph state and policy", D5–D7, D21; `docs/solution-docs/04-contracts.md` §5 (escalation.yaml block, line 239) and §6; `README.md` headings
  - Acceptance:
    - `04` §6 documents `reply_sent.payload.degraded` (always present) and the `nlu_result.payload.source` fields (`classifier_version`, `label_set_version`).
    - `04` §5 shows `escalation.yaml v5` with `degraded_handoff_intents: [transaction_search, general_question]`.
    - `05` "Learned component" row (line 48) adds the trained classifier vs keyword vs Ref comparison on dev, with the report path `ml/intent/runs/<run_id>/nlu_classifier.md`.
    - `README.md` gains a "Where AI is used" section:
      - Cardy's LLM (understand/compose/handoff summary)
      - the gpt-6-luna eval/data-generation steps
      - the trained intent classifier, used **only** in degraded mode when the LLM fails or `LLM_DISABLED` is on
      - links to ADR-032 and `ml/intent/MODEL_CARD.md`
  - Verify: `grep -q "Where AI is used" README.md && grep -q "degraded_handoff_intents" docs/solution-docs/04-contracts.md && grep -q "classifier_version" docs/solution-docs/04-contracts.md && grep -q "nlu_classifier.md" docs/solution-docs/05-evaluation-plan.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/05-evaluation-plan.md`, `README.md`

- [ ] T12: Classifier adapter (D9/D10 `NLUResult` contract), `IntentClassifier` Protocol, stub helper, and `test_classifier_contract` (adapter part)
  - Depends on:
    - T2 (`classifier_labels`, `IntentRow.lexicon_key`)
    - T3 (`parse_card_mask`, `TEMPORARY_LOCK_LABEL`/`PERMANENT_BLOCK_LABEL`, `split_clauses`, `qualified_block_kind`, `lexicon_hits`)
    - T5 (`Scorer` Protocol)
    - Real names are in the state file.
  - Read exactly these: spec D9, D10 and §Contracts "Classifier (inference)"; `backend/app/domains/conversation/schemas.py` (`NLUResult`, `NLUSlots`); the state file's "D10 negation" fact
  - Acceptance:
    - `classifier/adapter.py` defines `IntentClassifier` (Protocol, spec contract) and `ClassifierAdapter(scorer, *, tau, version, label_set_version)`. Its `predict(text, *, pending, country, previous_language) -> NLUResult` does the following:
      - Scores each `split_clauses` clause. A clause at or above τ contributes its label, dropped per the D10 negation fact.
      - Merges per D10: out_of_market topic wins, then in-scope intents (unrecognized_charge precedence; unlock supersedes block in a clause), then out_of_scope topic.
      - No clause at or above τ gives `ambiguous`, intents `[]`.
      - `language` comes from `_guess_language` (lazy import from `nodes.load_session`).
      - Only `block_kind` and `card_hint` are filled:
        - With `pending` awaiting `block_kind`, the text is first compared exactly to the four chip labels, then `qualified_block_kind`, whatever the class.
        - A bare `card_block` with no qualifier gives `ambiguous` plus `clarification="lock_vs_block"`.
        - `parse_card_mask` sets `card_hint="last4:NNNN"`.
      - It never returns `injection_suspected`.
    - `classifier/__init__.py` exports `IntentClassifier` and `ClassifierAdapter`.
    - `backend/tests/stub_classifier.py` has `StubScorer` and `make_stub_classifier`.
    - `test_classifier_contract.py` covers:
      - below τ
      - a scope class (pix_boleto → out_of_market, loans → out_of_scope, plus the topic)
      - bare card_block
      - a label built with `mask_card`
      - the four chip labels under `awaiting_slot="block_kind"`
      - `injection_suspected` never appears over the 22 labels
      - output is valid `NLUResult`
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_classifier_contract.py -q && uv run ruff check app/domains/conversation/classifier/adapter.py app/domains/conversation/classifier/__init__.py tests/stub_classifier.py tests/unit/test_classifier_contract.py && uv run ruff format --check app/domains/conversation/classifier/adapter.py app/domains/conversation/classifier/__init__.py tests/stub_classifier.py tests/unit/test_classifier_contract.py && uv run mypy app/domains/conversation/classifier && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/classifier/adapter.py`, `backend/app/domains/conversation/classifier/__init__.py`, `backend/tests/stub_classifier.py`, `backend/tests/unit/test_classifier_contract.py`

- [ ] T13: `ml/intent/generate.py`: fill each locale × class cell up to 30 accepted items through `intent_gen`
  - Depends on:
    - T4 (`data_io`: `DataFile`, `LOCALES`, `SLOT_MIX`, `write_file`)
    - T6 (`intent_gen` step and prompt path)
    - T2 (`classifier_labels`)
  - Read exactly these: `backend/scripts/paraphrase_seeds.py` (LLM call pattern, `PromptRef`, client); spec D19, D20; `ml/intent/data_io.py`
  - Acceptance:
    - `python -m ml.intent.generate [--locale] [--class] [--data-dir] [--plan]` walks the 22 classes × 4 locales.
    - A missing cell gets one structured call returning 10 families × (seed + 2 paraphrases), with slots assigned by family index in `SLOT_MIX` order. Items are written with `generator: gpt-6-luna:intent_gen@v1` and `accepted: null`, and family ids are `<class>-<locale>-NN`.
    - A cell with fewer than 30 items whose `accepted` is true or null gets one call per family that has rejected items, regenerating only those items. Rejected items stay with `accepted: false`.
    - Scope classes write `intents: []`, `status` from `scope.yaml` kind, and `topic`.
    - Each file starts with `provenance: ai-generated-human-audited`, `version: 1`, `locale` and `class`.
    - Text containing a raw digit run of 13 or more, or an email, is dropped before writing (R5 hygiene).
    - `--plan` prints per cell how many calls it would make and makes none.
  - Verify:
    ```
    uv run --project backend python -m ml.intent.generate --plan --data-dir "$(mktemp -d)" | tail -3 && uv run --project backend python -m ml.intent.generate --plan --data-dir ml/intent/tests/fixtures/dataset --locale es-ar --class card_block && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/generate.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/generate.py
    ```
    The first command should report 88 cells × 1 call. The second reports a top-up for the 15-item fixture cell.
  - Files: `ml/intent/generate.py`

- [ ] T14: Candidates C0–C4 and `ml/intent/train.py` (grouped CV, out-of-fold τ, deterministic run record)
  - Depends on: T4 (`data_io`), T5 (`Embedder`, `SklearnScorer`; fastembed ids and cache path in the state file)
  - Read exactly these: spec D17, D18, D21; the requirement doc's candidate table, `docs/requirements/learned-intent-fallback.md` lines 110–125; `backend/app/domains/conversation/classifier/scorers.py`
  - Acceptance:
    - `candidates.py` defines:
      - C0 (majority)
      - C1 (`keyword_nlu`, wrapped to a label)
      - C2 (TF-IDF char_wb 2–5 + LR; grid over C and ngram range)
      - C3a and C3b (the two embedding models + LR; grid over C)
      - C4 (e5-small embeddings + kNN; grid over k)
      - each with a fixed seed
    - `train.py --candidate {c0..c4,c3a,c3b,all} --seed --data-dir --runs-dir --run-id` does the following:
      - Loads accepted items only.
      - Runs 5-fold `GroupKFold` by `family`, on training data only.
      - Records CV macro-F1 mean ± sd per grid point and the best point.
      - Computes out-of-fold probabilities and picks τ by the D18 cost rule: wrong side-effect intent (card_block, card_unlock, replacement_request, unrecognized_charge) = 5, wrong read-only = 2, clarification = 1.
      - Writes `<runs-dir>/<run-id>/train.json` (fields in the state file "Run records"), including `prediction_hash`.
    - Embeddings are computed once per model and cached in memory per run.
    - Two runs with the same seed give identical `metrics` and `prediction_hash`.
  - Verify:
    ```
    D=$(mktemp -d) && for r in a b; do uv run --project backend python -m ml.intent.train --candidate all --seed 42 --data-dir ml/intent/tests/fixtures/dataset --runs-dir $D --run-id $r; done && uv run --project backend python -c "import json,sys; a,b=[json.load(open(f'$D/{r}/train.json')) for r in 'ab']; assert a['metrics']==b['metrics'] and a['prediction_hash']==b['prediction_hash']" && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/candidates.py ml/intent/train.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/candidates.py ml/intent/train.py
    ```
  - Files: `ml/intent/candidates.py`, `ml/intent/train.py`

- [ ] T15: Leakage check, `ml/intent/check.py`, and `test_leakage`
  - Depends on: T4 (`data_io`), T2 (`classifier_labels`)
  - Read exactly these: spec D16, D19, criterion 5 and the test list row for `test_leakage`; `ml/intent/data_io.py`; `eval/harness/nlu_eval.py` (`load_smoke_items`, `derive_suite_items`, and how cases load via `eval.scenarios.schema.load_dir`)
  - Acceptance:
    - `leakage.py` defines:
      - `normalize(text)` (casefold, strip accents, collapse whitespace and punctuation)
      - `eval_texts()`: every customer turn text in `eval/scenarios/dev`, `eval/scenarios/heldout`, `eval/scenarios/_staging/heldout` and `eval/nlu/*.yaml`, opened read-only
      - `find_leaks(train_texts, eval_texts) -> list[tuple[str, str]]`
    - `check.py --data-dir [--per-cell 30]` exits non-zero and prints a reason when:
      - any training text leaks
      - a label in `classifier_labels()` lacks a file in any of the 4 locales, or a file names an unknown class
      - a cell's accepted count ≠ `--per-cell`
      - any item has `accepted: null`
      - a file header's provenance ≠ `ai-generated-human-audited`
    - `test_leakage.py` builds a tmp copy of the fixture, adds a dev text with changed case and accents, and asserts `find_leaks` flags it. The clean fixture has no leaks.
    - Nothing under `eval/` is written.
  - Verify:
    ```
    uv run --project backend pytest ml/intent/tests/test_leakage.py -q && uv run --project backend python -m ml.intent.check --data-dir ml/intent/tests/fixtures/dataset --per-cell 15; test $? -ne 0 && git diff --exit-code eval/ && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/leakage.py ml/intent/check.py ml/intent/tests/test_leakage.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/leakage.py ml/intent/check.py ml/intent/tests/test_leakage.py
    ```
    The fixture fails coverage (3 of 22 classes), which proves the non-zero exit.
  - Files: `ml/intent/leakage.py`, `ml/intent/check.py`, `ml/intent/tests/test_leakage.py`

- [ ] T16: Degraded swaps in `compose`, `abstain`, `handoff_summary`
  - Depends on: T2 (`GraphState.degraded`)
  - Read exactly these: `backend/app/domains/conversation/nodes/compose.py` (the `compose` node, line 347, and its `LLMError` branch, line 403); `backend/app/domains/conversation/baseline/template_compose.py`; spec D2, D4 and the state file's "Degraded semantics" fact
  - Acceptance:
    - With a classifier loaded (`config["configurable"].get("classifier") is not None`):
      - If `state["degraded"]` is true, each of the three nodes returns its baseline counterpart (`baseline_compose`, `baseline_abstain`, `baseline_handoff_summary`, imported lazily inside the function) and makes no LLM call.
      - If the node's own LLM call raises `LLMError`, it returns the baseline result plus `"degraded": True`, not `llm_unavailable`.
    - Without a classifier, behavior is byte-for-byte today's.
    - `compose_reply` and `compose_checked` are untouched.
    - No new tool or write is reachable.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_compose.py tests/unit/test_abstain.py tests/unit/test_handoff_packet.py tests/unit/test_faults.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/nodes/compose.py app/domains/conversation/nodes/abstain.py app/domains/conversation/nodes/handoff_summary.py && uv run ruff format --check app/domains/conversation/nodes/compose.py app/domains/conversation/nodes/abstain.py app/domains/conversation/nodes/handoff_summary.py && uv run mypy app/domains/conversation/nodes && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/nodes/abstain.py`, `backend/app/domains/conversation/nodes/handoff_summary.py`

- [ ] T17: D7: `degraded_handoff_intents` in the escalation policy, enforced at `enqueue` / `next_intent`
  - Depends on: T2 (`GraphState.degraded`; `_dispatch` already routes `llm_unavailable` to `fallback`)
  - Read exactly these: `backend/app/domains/policy/escalation.py`; `policies/escalation.yaml`; `backend/app/domains/conversation/nodes/next_intent.py`
  - Acceptance:
    - `EscalationPolicy` gains `degraded_handoff_intents: list[Intent]`, defaulting to empty, so other YAMLs still load.
    - `policies/escalation.yaml` gets `version: 5`, the key `degraded_handoff_intents: [transaction_search, general_question]`, a comment citing ADR-032, and unchanged provenance.
    - `enqueue` and `next_intent` set `escalation_reason="llm_unavailable"` when `state.get("degraded")` is true and the queue head is in `get_policies().escalation.degraded_handoff_intents`. Otherwise they are unchanged.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_policy_registry.py tests/unit/test_escalation_rules.py tests/unit/test_conversation_basics.py -q && uv run python -c "from app.domains.policy.registry import get_policies; assert get_policies().escalation.degraded_handoff_intents==['transaction_search','general_question']" && uv run ruff check app/domains/policy/escalation.py app/domains/conversation/nodes/next_intent.py && uv run ruff format --check app/domains/policy/escalation.py app/domains/conversation/nodes/next_intent.py && uv run mypy app/domains/policy/escalation.py app/domains/conversation/nodes/next_intent.py
    ```
  - Files: `backend/app/domains/policy/escalation.py`, `policies/escalation.yaml`, `backend/app/domains/conversation/nodes/next_intent.py`

- [ ] T18: LIVE: generate the training data with gpt-6-luna (`make intent-gen`)
  - Depends on: T13 (`ml.intent.generate`), T7 (`make intent-gen`)
  - Read exactly these: spec D19, D20; `ml/intent/generate.py` (`--plan` output)
  - Acceptance:
    - The `.env` OpenAI key is loaded (`set -a; . ./.env; set +a`).
    - `make intent-gen` runs once for all 88 cells. It may be re-run per `LOCALE=`/`CLASS=` after transient errors.
    - `ml/intent/data/<locale>/<class>.yaml` exists for all 88 cells, each with 30 items and `accepted: null`.
    - `git status` shows only `ml/intent/data/**`.
    - The state file records the call count and any cell that needed a retry.
    - Nothing is accepted by the agent: auditing is the human's job.
  - Verify:
    ```
    uv run --project backend python -c "from ml.intent.data_io import load_files; from pathlib import Path; f=load_files(Path('ml/intent/data')); assert len(f)==88 and all(len(x.items)>=30 for x in f)" && git status --porcelain | grep -v '^?? ml/intent/data/' | grep -c . | grep -q '^0$'
    ```
  - Files: `ml/intent/data/**`

- [ ] T19: Bundle loader with refuse-to-load checks, placeholder `model.lock`, loader tests appended to `test_classifier_contract`
  - Depends on: T12 (`ClassifierAdapter`, `IntentClassifier`, `test_classifier_contract.py` exists), T5 (`SklearnScorer`, `Embedder`), T2 (`load_registry().label_set_version`)
  - Read exactly these: spec D11, D14 and §Contracts "Classifier (inference)"; the state file's "Bundle" and "Settings `intent_model_dir`" facts; `backend/app/domains/conversation/classifier/adapter.py`
  - Acceptance:
    - `classifier/loader.py::load_classifier(model_dir) -> (IntentClassifier | None, reason)`. It refuses with a reason in each of these cases:
      - the lock is missing or has a null version
      - `<version>.tar.gz` is missing
      - the sha256 differs (checked before any extraction or unpickling)
      - `manifest.label_set_version` ≠ the lock's or the registry's
      - the manifest labels are not ⊆ `classifier_labels()`
    - Otherwise it extracts to a private temp dir, `joblib.load`s `head.joblib`, builds an `Embedder` over `embeddings/` when `embedding_model` is set, and returns a `ClassifierAdapter` with `version = manifest.model_id` and the manifest τ.
    - No network access happens.
    - `ml/intent/model.lock` is committed as `{"version": null, "sha256": null, "label_set_version": null, "s3_uri": null}`.
    - `classifier/__init__.py` exports `load_classifier`.
    - Tests appended to `test_classifier_contract.py`:
      - one builds a tiny bundle in `tmp_path` (C2 pipeline on 4 texts) and asserts a stale `label_set_version` refuses
      - one asserts a wrong sha256 refuses
      - one asserts a good bundle loads and predicts
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_classifier_contract.py -q && uv run python -c "from pathlib import Path; from app.domains.conversation.classifier import load_classifier; c,r=load_classifier(Path('../ml/intent/models')); assert c is None; print(r)" && uv run ruff check app/domains/conversation/classifier tests/unit/test_classifier_contract.py && uv run ruff format --check app/domains/conversation/classifier tests/unit/test_classifier_contract.py && uv run mypy app/domains/conversation/classifier && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/classifier/loader.py`, `backend/app/domains/conversation/classifier/__init__.py`, `ml/intent/model.lock`, `backend/tests/unit/test_classifier_contract.py`

- [ ] T20: Degraded NLU: classifier in `understand`/`load_session`, D8 ambiguous-twice in `route`/`smalltalk`, `clarify_rephrase` template
  - Depends on: T2 (`GraphState.degraded`), T12 (`IntentClassifier` Protocol; `make_stub_classifier` in `backend/tests/stub_classifier.py`)
  - Read exactly these: `backend/app/domains/conversation/nodes/understand.py`; `backend/app/domains/conversation/nodes/load_session.py`; spec D2, D3, D8 and the state file's "Degraded semantics" fact
  - Acceptance:
    - `load_session`:
      - sets `degraded = llm_disabled and mode != "human" and classifier is not None`
      - sets `escalation_reason="llm_unavailable"` only when `llm_disabled` and **no** classifier (the `_entry` shortcut stays)
      - otherwise sets `degraded: False`
    - `understand`:
      - if `degraded`, calls `classifier.predict(state["user_text"], pending=, country=, previous_language=)` with no LLM call
      - else on `LLMError` with a classifier, does the same and returns `"degraded": True`
      - with no classifier, behaves as today
    - D8, degraded only:
      - A classifier result `ambiguous` with no `clarification` and no fitting pending answer increments `clarification_failures`.
      - At 1, `route` sends the turn to `smalltalk` and it replies `clarify_rephrase`.
      - At 2, `understand` sets `escalation_reason="clarification_exhausted"`, and `route` sends a degraded turn carrying that reason to `handoff_summary`.
      - Any other degraded result resets the counter.
    - `route` returns only targets that already exist in the `understand` edge map.
    - The new `clarify_rephrase` template has es and pt text. It asks the customer to say it another way, with no mode mention, in Cardy's voice (`docs/brand.md`).
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_faults.py tests/unit/test_graph.py tests/unit/test_conversation_basics.py tests/unit/test_classifier_contract.py -q && uv run ruff check app/domains/conversation/nodes/understand.py app/domains/conversation/nodes/load_session.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/templates.py && uv run ruff format --check app/domains/conversation/nodes/understand.py app/domains/conversation/nodes/load_session.py app/domains/conversation/nodes/route.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/templates.py && uv run mypy app/domains/conversation/nodes app/domains/conversation/templates.py && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/nodes/understand.py`, `backend/app/domains/conversation/nodes/load_session.py`, `backend/app/domains/conversation/nodes/route.py`, `backend/app/domains/conversation/nodes/smalltalk.py`, `backend/app/domains/conversation/templates.py`

- [ ] T21: Runtime wiring: load at startup, classifier in `configurable`, audit fields, OTel attribute, `INTENT_MODEL_DIR`
  - Depends on: T19 (`load_classifier`), T2 (`degraded` in state)
  - Read exactly these: `backend/app/domains/conversation/runner.py` (configurable around line 276, `nlu_result` around 333, `reply_sent` around 381); `backend/app/domains/conversation/hosting.py`; spec D5, D6, D11 and §Contracts "Audit"
  - Acceptance:
    - `Settings.intent_model_dir: Path`, with the default from the state file.
    - `.env.example` gets a commented `# INTENT_MODEL_DIR=` with a one-line note.
    - `TurnHost` gains `classifier: IntentClassifier | None = None`, and `open_host(..., classifier=None)` accepts it.
    - `main._lifespan` calls `load_classifier(settings.intent_model_dir)` once. It logs `intent_classifier.loaded classifier_version=<v> label_set_version=<n>`, or `intent_classifier.unavailable reason=<r>` at error level, and the app starts either way.
    - `runner.py`:
      - puts `"classifier": host.classifier` in `configurable`
      - tracks `degraded` from any node update
      - `nlu_result` gains `source` (`"classifier"` when the understand update had `degraded: True`, else `"llm"`) and, for the classifier, `classifier_version` and `label_set_version`
      - `reply_sent` always has `degraded: bool`
      - sets `trace.get_current_span().set_attribute("cardy.degraded", degraded)`
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_audit_pairs.py tests/unit/test_r1_routes.py tests/unit/test_r13_routes.py tests/unit/test_login_pii.py tests/unit/test_health.py -q && uv run ruff check app/domains/conversation/runner.py app/domains/conversation/hosting.py app/main.py app/core/config.py && uv run ruff format --check app/domains/conversation/runner.py app/domains/conversation/hosting.py app/main.py app/core/config.py && uv run mypy app && uv run lint-imports
    ```
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/domains/conversation/hosting.py`, `backend/app/main.py`, `backend/app/core/config.py`, `.env.example`

- [ ] T22: `compare.py`, `report.py`, `export.py`: selection, τ, bundle + lock export with parity check, dev comparison and report (proved on the fixture, no Ref)
  - Depends on:
    - T14 (`train.py` CV and τ API)
    - T8 (`dev_items`, `predict_items`, `abstain_rates`, `bootstrap_ci`, `mcnemar`)
    - T19 (`load_classifier`)
    - T12 (`ClassifierAdapter`)
  - Read exactly these: spec D14, D17, D18, D21 and criterion 2; the requirement doc's "Expected report (mock)", `docs/requirements/learned-intent-fallback.md` from line 160 to the end of the mock; the state file's T8, T14 and T19 entries
  - Acceptance:
    - `compare.py --seed --data-dir --runs-dir --run-id --models-dir --lock [--no-ref] [--all-dev-items]`:
      1. Runs CV for C2–C4 grids via `train.py` and picks the D17 winner (smallest served bundle within the 95% CI of the best grouped-CV macro-F1).
      2. Takes τ from that winner's out-of-fold predictions.
      3. Refits on all training data.
      4. `export.py` writes `intent_clf@vN.tar.gz` (N = 1 + the lock's version number, or 1) with the manifest fields, `head.joblib` and the `embeddings/` copied from the fastembed cache, and rewrites the lock JSON.
      5. Reloads via `load_classifier` and asserts the predictions on all dev items equal the in-process adapter's (parity).
      6. Scores C0, C1 (`keyword_nlu`), C2, C3a, C3b, C4 and (unless `--no-ref`) Ref (`run_nlu` with `nlu@v4` through `get_llm_client()`) on `dev_items(seeds_only=True)` (the `--all-dev-items` flag switches to 112), all as `NLUResult` through `ClassifierAdapter` for C2–C4, using `score`, `abstain_rates`, Wilson CIs, bootstrap macro-F1 CI, McNemar vs C1, and p50/p95 latency.
      7. Breaks results down per locale (`language_variant`) and per slice (negation, multi-intent, short answer, by the item's text and expected intents; the rules are written in the report).
      8. Locale transfer: trains the winner without es-ar and tests on the es-ar dev items.
    - `report.py` writes `nlu_classifier.md` (sections 1–8 as in the mock; section 6 lists misses by category; section 7 is a placeholder table "to be filled by the degraded e2e run"; section 8 limitations include "AI-generated (gpt-6-luna), human-audited labels"), `nlu_classifier.json`, `figures/reliability.png`, one confusion matrix per system and `misses.yaml`.
    - Run on the fixture, it completes without Ref and without touching `ml/intent/models` or `ml/intent/model.lock`.
  - Verify:
    ```
    D=$(mktemp -d) && uv run --project backend python -m ml.intent.compare --seed 42 --data-dir ml/intent/tests/fixtures/dataset --runs-dir $D/runs --run-id fx --models-dir $D/models --lock $D/model.lock --no-ref && test -s $D/runs/fx/nlu_classifier.md && ls $D/models/*.tar.gz && git diff --exit-code ml/intent/model.lock && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/compare.py ml/intent/report.py ml/intent/export.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/compare.py ml/intent/report.py ml/intent/export.py
    ```
  - Files: `ml/intent/compare.py`, `ml/intent/report.py`, `ml/intent/export.py`

- [ ] T23: Degraded-mode safety and happy-path tests (R2, R3, ES/PT paths, kill switch)
  - Depends on: T12 (`make_stub_classifier`), T16 (baseline swaps), T17 (D7), T20 (classifier in understand, D8), T21 (`configurable["classifier"]`, `reply_sent.degraded`, `Settings.intent_model_dir`)
  - Read exactly these: `backend/tests/conftest.py` (`make_session`, `ScriptedLLM`); `backend/tests/unit/test_faults.py` (`test_llm_disabled_every_turn_falls_back`, line 50); spec §Test list and D24
  - Acceptance:
    - `make_session(..., classifier=None)` puts the classifier in `configurable`.
    - An autouse fixture sets `INTENT_MODEL_DIR` to an empty `tmp_path` and clears `get_settings` cache.
    - `test_degraded.py` uses a fake LLM whose every `structured` call raises `LLMUnavailable`, plus `make_stub_classifier` with text → label maps:
      - `test_degraded_write_needs_token` (R2): card_block with a missing, stale or replayed token runs no write tool. Mirror the token cases in `tests/unit/test_r2_confirmed_writes.py`.
      - `test_degraded_done_requires_readback` (R3): `verified` false gives no "done" text. Use the `readback_mismatch` fault the way `test_readback_mismatch_action_unverified_es` does.
      - `test_degraded_paths[es|pt]`:
        - card status served
        - card block → lock-vs-block chip label → confirm → verified read-back
        - affirm/deny on a pending yes/no
        - Pix → abstain
        - transaction_search → handoff `llm_unavailable`
        - every turn `DebugInfo.degraded` is True
        - the audit `reply_sent` has `degraded: true` where the session records audit
    - In `test_faults.py`, `test_llm_disabled_every_turn_falls_back` is replaced by `test_kill_switch_degraded`: `LLM_DISABLED=true` with the stub gives zero LLM calls and card status served, and with no classifier it gives today's fallback handoff. The other tests in the file are unchanged.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_degraded.py tests/unit/test_faults.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check tests/conftest.py tests/unit/test_degraded.py tests/unit/test_faults.py && uv run ruff format --check tests/conftest.py tests/unit/test_degraded.py tests/unit/test_faults.py
    ```
  - Files: `backend/tests/conftest.py`, `backend/tests/unit/test_degraded.py`, `backend/tests/unit/test_faults.py`

- [ ] T24: Docker: bundle into the backend image via a named context, sha256 re-check, `ml` group excluded (ALONE)
  - Depends on: T1 (`ml` group, `.gitkeep`), T19 (`ml/intent/model.lock` placeholder, lock JSON format), T21 (startup log lines)
  - Read exactly these: `backend/Dockerfile`; `docker/docker-compose.base.yml` (backend `additional_contexts`) and `docker/docker-compose.dev.yml` (backend `command`); spec D14 and criterion 7
  - Acceptance:
    - The compose backend build adds `additional_contexts: intent: ../ml/intent`.
    - `ml/intent/.dockerignore` excludes `data/`, `runs/`, `tests/`, `prompts/`, `.cache/` and `*.py`.
    - The Dockerfile:
      - copies `model.lock` and `models/` from `intent` to `/app/ml/intent/`
      - in a `RUN` step (python, no network), fails the build if any `*.tar.gz` is present and its name or sha256 differs from the lock; it passes when there is no tarball
      - sets `ENV INTENT_MODEL_DIR=/app/ml/intent/models`
      - syncs with `--no-group ml`
    - Neither the image CMD nor the dev compose command re-syncs at start (`--no-sync` or `UV_NO_SYNC=1`).
    - No credentials or build args are added.
    - Proofs:
      - an empty models dir builds
      - a backend container starts with `--network none` and logs `intent_classifier.unavailable`
      - a fake `models/intent_clf@v1.tar.gz` with the placeholder lock fails the build (then delete it)
    - Restore the dev stack with `make up` at the end.
  - Verify:
    ```
    docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml build backend && docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml run --rm --no-deps --network none backend uv run --no-sync python -c "from pathlib import Path; from app.domains.conversation.classifier import load_classifier; import os; print(load_classifier(Path(os.environ['INTENT_MODEL_DIR'])))" && echo x > ml/intent/models/intent_clf@v1.tar.gz && ! docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml build backend; rm -f ml/intent/models/intent_clf@v1.tar.gz
    ```
  - Files: `backend/Dockerfile`, `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml`, `ml/intent/.dockerignore`

- [ ] T25: HUMAN checkpoint: audit every generated item (no implementer)
  - Depends on: T18 (data written), T15 (`ml.intent.check`), T13 (top-up generation)
  - Read exactly these: spec D19; `ml/intent/prompts/intent_gen@v1.md`; `ml/intent/data/<locale>/<class>.yaml`
  - Acceptance:
    - A person sets `accepted: true|false` on every item. Expect about 2,640 accepted out of more generated.
    - The loop is: audit, then `make intent-gen` (tops up only rejected families), then audit the new items, repeated until every cell has exactly 30 accepted and none is null.
    - The orchestrator does not dispatch an agent for this. It starts after W4 and runs beside W5–W7. W8 waits for it.
    - The human commits the data, or tells the orchestrator to.
  - Verify: `uv run --project backend python -m ml.intent.check --data-dir ml/intent/data` exits 0
  - Files: `ml/intent/data/**`

- [ ] T26: Wire `ml.intent.check` and the ml tests into `make check`; data coverage in `test_registry_consistency`; prove the two criterion-5 mutations fail
  - Depends on: T25 (audited data), T15 (`check.py`), T7 (the Makefile owner before this), T2 (`test_registry_consistency.py`)
  - Read exactly these: `Makefile` `check` target (lines 62–71); `backend/tests/unit/test_registry_consistency.py`; spec criterion 5
  - Acceptance:
    - `make check` gains `cd .. && uv run --project backend python -m ml.intent.check`, `uv run --project backend pytest ml/intent/tests -q`, and ruff check/format on `ml/`. Match the target's existing `cd` structure.
    - `test_registry_consistency.py` gains: every `classifier_labels()` entry has a file in all 4 locales under `ml/intent/data`.
    - Mutation proofs on tmp copies of `ml/intent/data` (never the real dir) make `check` exit non-zero:
      - (a) a dev scenario text appended as an accepted item
      - (b) one accepted item removed from a cell
  - Verify:
    ```
    uv run --project backend python -m ml.intent.check && cd backend && uv run pytest tests/unit/test_registry_consistency.py -q && cd .. && T=$(mktemp -d) && cp -r ml/intent/data $T/a && cp -r ml/intent/data $T/b && uv run --project backend python - "$T" <<'EOF'
    import sys, yaml; from pathlib import Path; t=Path(sys.argv[1])
    p=t/'a/es-co/card_block.yaml'; d=yaml.safe_load(p.read_text()); it=dict(d['items'][0]); it['text']='Necesito bloquear mi tarjeta de crédito ahora mismo.'; d['items'].append(it); p.write_text(yaml.safe_dump(d, allow_unicode=True))
    p=t/'b/pt-br/card_status.yaml'; d=yaml.safe_load(p.read_text()); i=next(k for k,x in enumerate(d['items']) if x['accepted']); d['items'].pop(i); p.write_text(yaml.safe_dump(d, allow_unicode=True))
    EOF
    ! uv run --project backend python -m ml.intent.check --data-dir $T/a && ! uv run --project backend python -m ml.intent.check --data-dir $T/b && make -n check | grep -q ml.intent.check
    ```
  - Files: `Makefile`, `backend/tests/unit/test_registry_consistency.py`

- [ ] T27: Final training on the audited data, run twice (ALONE)
  - Depends on: T26 (data proven complete and leak-free), T14 (`train.py`)
  - Read exactly these: spec criterion 1; `ml/intent/train.py` CLI (`--help`)
  - Acceptance:
    - `make intent-train SEED=42` runs twice, writing two run records under `ml/intent/runs/`.
    - Their `metrics` and `prediction_hash` are identical.
    - Both run dirs are committed (no model files).
    - The state file records both run ids, the per-candidate CV macro-F1 and the out-of-fold τ.
  - Verify:
    ```
    make intent-train SEED=42 && make intent-train SEED=42 && uv run --project backend python -c "import json,glob,os; r=sorted(glob.glob('ml/intent/runs/*/train.json'), key=os.path.getmtime)[-2:]; a,b=[json.load(open(x)) for x in r]; assert a['metrics']==b['metrics'] and a['prediction_hash']==b['prediction_hash']; print(r)"
    ```
  - Files: `ml/intent/runs/**`

- [ ] T28: LIVE: the real comparison with Ref, model selection, bundle and lock (ALONE)
  - Depends on: T27 (training validated), T22 (`compare.py`), T26
  - Read exactly these: spec D14, D17, D18, D21 and criteria 2 and 7; `ml/intent/compare.py` (`--help`); the state file's answer to the dev-item-set question (56 seeds or 112)
  - Acceptance:
    - With `.env` loaded, `make intent-compare SEED=42` (plus `--all-dev-items` only if the human chose 112) does the following:
      - Ref calls `nlu@v4` once per dev item.
      - It writes `ml/intent/runs/<run_id>/nlu_classifier.{md,json}`, `figures/` and `misses.yaml`.
      - It writes `ml/intent/models/intent_clf@v1.tar.gz` (git-ignored) and the real `ml/intent/model.lock`.
      - The parity assertion passes.
    - The report has the C0, C1, C2, C3a, C3b, C4 and Ref rows, the CIs, the per-locale and per-slice tables, the transfer line, McNemar, the selected model and τ with rationale, and the limitations.
    - The state file records the winner, τ, `model_id`, sha256 and whether the winner needs fastembed and onnxruntime.
  - Verify:
    ```
    uv run --project backend python -c "import json,hashlib; l=json.load(open('ml/intent/model.lock')); h=hashlib.sha256(open(f\"ml/intent/models/{l['version']}.tar.gz\",'rb').read()).hexdigest(); assert h==l['sha256'], (h,l)" && git status --porcelain ml/intent/models | grep -c . | grep -q '^0$' && grep -q "Ref" ml/intent/runs/*/nlu_classifier.md
    ```
  - Files: `ml/intent/runs/**`, `ml/intent/model.lock`, `ml/intent/models/` (git-ignored)

- [ ] T29: Move the served winner's dependencies to backend runtime (ALONE)
  - Depends on: T28 (the winner and its needs, in the state file)
  - Read exactly these: `backend/pyproject.toml`; spec D15; the state file's T28 entry
  - Acceptance:
    - scikit-learn and joblib (every C2–C4 head is a joblib-pickled sklearn estimator) move from the `ml` group to `[project] dependencies`.
    - If the winner is C3a, C3b or C4, fastembed and onnxruntime move too.
    - matplotlib and anything not served stay in `ml`.
    - `uv.lock` is updated.
    - The backend imports and loads the bundle with the `ml` group excluded.
  - Verify:
    ```
    cd backend && uv lock && uv run --no-group ml python -c "from pathlib import Path; from app.domains.conversation.classifier import load_classifier; c,r=load_classifier(Path('../ml/intent/models')); assert c is not None, r; print(c.version)" && uv sync
    ```
  - Files: `backend/pyproject.toml`, `backend/uv.lock`

- [ ] T30: Image proof for criterion 7 (ALONE)
  - Depends on: T24 (Docker), T28 (bundle and lock), T29 (runtime deps)
  - Read exactly these: spec criterion 7; `backend/Dockerfile`
  - Acceptance:
    - `docker compose build backend` copies the bundle and passes the sha256 check.
    - A container with no AWS variables, started with `--network none`, loads it and prints the `classifier_version`.
    - After `make up`, the backend logs `intent_classifier.loaded classifier_version=intent_clf@v1`.
    - Re-proved here: an altered copy of the tarball fails the build. Restore it after.
    - `git status` shows nothing under `ml/intent/models/`.
    - The outputs are pasted into the state file.
  - Verify:
    ```
    docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml build backend && docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml run --rm --no-deps --network none -e AWS_ACCESS_KEY_ID= -e AWS_SECRET_ACCESS_KEY= -e AWS_PROFILE= backend uv run --no-sync python -c "from pathlib import Path; import os; from app.domains.conversation.classifier import load_classifier; c,r=load_classifier(Path(os.environ['INTENT_MODEL_DIR'])); assert c is not None, r; print(c.version)" && make up && docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml logs backend | grep -m1 "intent_classifier.loaded"
    ```
  - Files: none (proof only; outputs go to the state file)

- [ ] T31: LIVE runtime: degraded end-to-end on 8 dev cases, with and without the classifier (ALONE)
  - Depends on: T28 (bundle), T29 (runtime deps), T7 (`FAULTS=`), T9 (relabeled dev case), T23 (degraded path tested)
  - Read exactly these: spec criterion 8 and D16; the state file's "Criterion-8 dev case set"; `README.md` §6 "Daily commands" (eval prerequisites)
  - Acceptance:
    - With the dev stack's Postgres and Redis up, run `make eval SUITE=dev SYSTEM=proposed CASES=<the 8-case list> FAULTS=bedrock_timeout` twice:
      - (1) with the default `INTENT_MODEL_DIR` (bundle loaded)
      - (2) with `INTENT_MODEL_DIR=$(mktemp -d)` exported in the shell (classifier unloaded)
    - Both report resolved / handed off / unsafe, with **0 unsafe**.
    - The state file records both report dirs and the three counts per run.
    - The relabeled dev case resolves as the clarification in run 1.
    - No held-out run.
  - Verify: `ls -d eval/reports/dev_proposed_* | tail -2` and in each `metrics.json` the unsafe count is 0. The exact `jq`/python read is recorded in the state file.
  - Files: `eval/reports/dev_proposed_<run1>/`, `eval/reports/dev_proposed_<run2>/` (only report.md, metrics.json and meta.json are committed)

- [ ] T32: Final report sections 6–7 and `ml/intent/MODEL_CARD.md`
  - Depends on: T28 (report run, winner, τ), T31 (e2e counts)
  - Read exactly these: the report `ml/intent/runs/<T28 run_id>/nlu_classifier.md`; spec criteria 2 and 6, D18, D19; the state file's T28 and T31 entries
  - Acceptance:
    - The report's section 7 shows "today vs degraded" with the two T31 runs' resolved / handed off / unsafe counts and their report paths.
    - Section 6's "decision" column is filled with one line per miss category.
    - `ml/intent/MODEL_CARD.md` covers:
      - data: 2,640 items, 22 classes × 4 locales, AI-generated (gpt-6-luna) and human-audited, the slot mix, the token format
      - intended use: degraded mode only
      - out of scope
      - the selected candidate and hyperparameters
      - τ and the D18 cost rationale
      - metrics with CIs, linking the report
      - limitations: AI-generated labels, synthetic register, no held-out run
      - how to retrain and pin (`make intent-train`, `make intent-compare`, `model.lock`)
      - that S3 is deferred
  - Verify: `test -s ml/intent/MODEL_CARD.md && grep -q "τ\|tau" ml/intent/MODEL_CARD.md && grep -q "gpt-6-luna" ml/intent/MODEL_CARD.md && grep -c "unsafe" ml/intent/runs/*/nlu_classifier.md`
  - Files: `ml/intent/runs/<T28 run_id>/nlu_classifier.md`, `ml/intent/MODEL_CARD.md`

- [ ] T33: `abstain` marks `degraded` when its own LLM call fails (human decision, raised by T16)
  - Depends on: T16 (degraded swaps in `compose`/`abstain`)
  - Read exactly these: `backend/app/domains/conversation/nodes/compose.py` (`compose_reply` and its `LLMError` handling); `backend/app/domains/conversation/nodes/abstain.py`; spec D2, D4
  - Acceptance:
    - `compose_reply` exposes whether its LLM call failed, for example an extra returned flag or a keyword-only option. Its reply wording and every existing caller's behavior stay byte-for-byte the same.
    - With a classifier loaded, when `abstain`'s own LLM call raises `LLMError`, `abstain` returns the same fallback reply as today plus `"degraded": True`.
    - Without a classifier, `abstain` behaves exactly as today.
    - One unit test in `test_abstain.py` with a fake LLM that raises `LLMError` and a stub classifier (`make_stub_classifier`) asserts `degraded` is True. A second asserts that with no classifier, `degraded` is absent.
    - No new tool or write is reachable.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_abstain.py tests/unit/test_compose.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/nodes/compose.py app/domains/conversation/nodes/abstain.py tests/unit/test_abstain.py && uv run ruff format --check app/domains/conversation/nodes/compose.py app/domains/conversation/nodes/abstain.py tests/unit/test_abstain.py && uv run mypy app/domains/conversation/nodes/compose.py app/domains/conversation/nodes/abstain.py
    ```
  - Files: `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/nodes/abstain.py`, `backend/tests/unit/test_abstain.py`

- [ ] T34: Fix task (human decision): redefine the `negation` and `hard_negative` slots so their items express the cell's class (`intent_gen@v2`)
  - Depends on: T6 (`intent_gen` step, prompt v1), T13 (`generate.py`), T18 (data written)
  - Read exactly these: `ml/intent/prompts/intent_gen@v1.md`; `ml/intent/generate.py`; the state file's T6, T13 and T18 entries and the "Human decisions" line for T34
  - Acceptance:
    - `ml/intent/prompts/intent_gen@v2.md` is a copy of v1 with only these changes. v1 stays in the repo unchanged.
      - `negation`: the customer rules out a DIFFERENT intent or topic and asks for this class ("no quiero bloquearla, solo ver cuánto debo" for `balance_due`). The item MUST express the class.
      - `hard_negative`: the text uses words typical of ANOTHER class but the customer wants this class. The item MUST express the class.
      - The rule "Hard negative and negation items must not be labeled as the class" is replaced by: every item, in every slot, must be labeled as the class by a reasonable reader.
      - For scope classes (`intents: []`), the same idea applies with the topic: the item must be about this topic.
    - `generate.py` uses prompt version 2, so new items carry `generator: gpt-6-luna:intent_gen@v2`. Items already in the files keep their v1 stamp.
    - `generate.py` gains a flag `--retire-slots negation,hard_negative --retire-generator-version 1` that sets `accepted: false` on every item of those slots whose `generator` ends in `@v1`, and changes nothing else in the files (other items' `accepted` values, order and text are preserved). It prints how many items it retired per cell. It makes no LLM call.
    - With retired items in a cell, the existing top-up logic regenerates those families (3 per cell) and no other family. `--plan` shows this without calling the LLM.
    - Do NOT run the retire flag or any live generation on `ml/intent/data` in this task. Prove both on a temp copy of the fixture dataset or of one data cell (`mktemp -d`).
  - Verify:
    ```
    D=$(mktemp -d) && cp -r ml/intent/data/es-ar $D/ && uv run --project backend python -m ml.intent.generate --data-dir $D --locale es-ar --class balance_due --retire-slots negation,hard_negative --retire-generator-version 1 && uv run --project backend python -m ml.intent.generate --data-dir $D --locale es-ar --class balance_due --plan && git status --porcelain -- ml/intent/data | head -1 && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/generate.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/generate.py
    ```
    (The cell must show 9 retired items and a plan that regenerates exactly 3 families. `ml/intent/data` must be byte-identical before and after: compare `find ml/intent/data -type f | sort | xargs sha256sum | sha256sum`.)
  - Files: `ml/intent/prompts/intent_gen@v2.md`, `ml/intent/generate.py`

- [ ] T35: LIVE: retire and regenerate the `negation` and `hard_negative` families in all 88 cells (ALONE on `ml/intent/data/**`; needs the human's go, since the human is auditing these files)
  - Depends on: T34
  - Acceptance:
    - Run the retire flag on `ml/intent/data`, then `make intent-gen` until `--plan` shows 0 calls.
    - Every cell has 30 items that are not `accepted: false`; the 9 retired v1 items per cell stay in the file with `accepted: false`; every `accepted` value the human had set on other items is unchanged.
    - New items carry `intent_gen@v2` and `accepted: null`.
  - Verify: counts per cell, per slot and per generator version, plus a before/after diff showing only negation and hard_negative families changed
  - Files: `ml/intent/data/**`

- [ ] T36: Fix task (human decision): relax the data check to allow cross-file duplicate texts and cells of 29 or 30
  - Depends on: T15 (`check.py`, `leakage.py`), T35 (data state)
  - Read exactly these: `ml/intent/check.py`; `ml/intent/leakage.py`; `ml/intent/tests/test_leakage.py`; the state file's T15 and T35 entries and the "Human decisions" line for T36
  - Acceptance:
    - A text that appears in more than one file under the SAME label is no longer a failure. The check prints it as a `WARN` line and counts it separately from problems.
    - A text that appears under two DIFFERENT labels still fails.
    - A duplicate inside one file still fails.
    - A cell passes with 29 or 30 accepted items; fewer than 29 or more than 30 fails. Null items still fail.
    - Leaks against eval text still fail. Nothing else in the check changes.
    - `uv run --project backend python -m ml.intent.check --data-dir ml/intent/data` exits 0 on the current data, with 7 duplicate warnings.
    - `test_leakage.py` is updated only where it asserts the old duplicate or count rule, and gains at most one test for "same text, different labels fails".
    - Do not edit anything under `ml/intent/data`.
  - Verify:
    ```
    uv run --project backend python -m ml.intent.check --data-dir ml/intent/data && uv run --project backend pytest ml/intent/tests/test_leakage.py -q && uv run --project backend ruff check --config backend/pyproject.toml ml/intent/check.py ml/intent/leakage.py ml/intent/tests/test_leakage.py && uv run --project backend ruff format --check --config backend/pyproject.toml ml/intent/check.py ml/intent/leakage.py ml/intent/tests/test_leakage.py
    ```
  - Files: `ml/intent/check.py`, `ml/intent/leakage.py`, `ml/intent/tests/test_leakage.py`

- [ ] T37: Fix the locale-transfer case mismatch in `compare.py`, then rerun the live comparison (LIVE, ALONE)
  - Depends on: T28
  - Why: dev items carry `es-AR`; training rows and `HELD_OUT_LOCALE` carry `es-ar`. The transfer block never runs and the report says "not run".
  - Acceptance:
    - `compare.py` matches the held-out locale case-insensitively for the dev items and for the `by_language_variant` lookup.
    - `make intent-compare SEED=42` rerun once: `nlu_classifier.json` has a non-null `transfer` with n = 6 es-AR dev items; the report prints the transfer line.
    - Winner, tau and bundle sha256 are unchanged from the T28 run, or the change is reported.
  - Verify:
    ```
    uv run --project backend python -c "import json,hashlib; r=json.load(open('ml/intent/runs/compare_s42/nlu_classifier.json')); assert r['transfer'] and r['transfer']['exact_set']['n']==6, r['transfer']; l=json.load(open('ml/intent/model.lock')); h=hashlib.sha256(open(f\"ml/intent/models/{l['version']}.tar.gz\",'rb').read()).hexdigest(); assert h==l['sha256']" && grep -q "Locale transfer (" ml/intent/runs/compare_s42/nlu_classifier.md && uv run --project backend pytest ml/intent/tests -q
    ```
  - Files: `ml/intent/compare.py`, `ml/intent/runs/compare_s42/**`, `ml/intent/model.lock`, `ml/intent/models/`

- [ ] T38: Fix two defects found by the degraded e2e run: runner drops `degraded` from `DebugInfo`; `make eval` cannot import `app`
  - Depends on: T31
  - Why: (1) `runner.py` builds `DebugInfo(...)` without `degraded=`, so the per-turn flag is always False through the real runner (only `graph.run_turn` sets it). (2) `eval/harness/__main__.py:7` imports `app.core.config.Fault` (T7) and `make eval` fails with `No module named 'app'` unless `PYTHONPATH=backend`.
  - Acceptance:
    - A turn through the real runner that used the fallback has `DebugInfo.degraded` True; a normal LLM turn and a template-only button turn have False (human decision: per-turn).
    - One unit test drives the runner (not the `make_session` shortcut) with a fake LLM that raises `LLMError` and a fake classifier, and asserts `DebugInfo.degraded` and the `reply_sent` audit payload's `degraded` are both True.
    - `make eval` works from the repo root with no `PYTHONPATH` exported.
  - Verify:
    ```
    cd backend && uv run pytest tests/unit/test_degraded.py -q && cd .. && env -u PYTHONPATH make -n eval SUITE=dev SYSTEM=proposed >/dev/null && env -u PYTHONPATH uv run --project backend python -c "import runpy,sys; sys.argv=['eval.harness','--help']; runpy.run_module('eval.harness', run_name='__main__')" >/dev/null
    ```
  - Files: `backend/app/domains/conversation/runner.py`, `backend/tests/unit/test_degraded.py`, `Makefile` and/or `eval/harness/__main__.py`

- [ ] T39: Make the card-block dev case runnable, then rerun the degraded e2e (LIVE runtime)
  - Depends on: T31, T38
  - Human decision: drop `setup.faults` from the dev case only; the 5 `_staging/heldout` files stay as they are.
  - Acceptance:
    - `eval/scenarios/dev/` case `d-card_block-tool_failure-es-co-01` has no `setup.faults`; nothing else in it changes.
    - Both T31 runs are repeated with the same `CASES=` and `FAULTS=bedrock_timeout`, with no `PYTHONPATH` exported; 8 variants play in each; unsafe is 0 in both.
    - Run 1: the card-block case ends as the clarification. The state file has the per-case table and counts for both runs.
  - Verify: in both report dirs, `metrics.json` unsafe is 0 and `results.jsonl` has no `not_run` row (exact read command recorded in the state file).
  - Files: the one dev scenario file, `eval/reports/dev-*-run1-classifier/`, `eval/reports/dev-*-run2-no-classifier/`

- [ ] T40: Export removes older bundles so the image build keeps passing
  - Depends on: T30
  - Human decision: after a successful export, older `intent_clf@v*.tar.gz` files in the models dir are deleted; the strict Docker check stays.
  - Acceptance:
    - After a successful export of `intent_clf@vN`, the models dir holds only `intent_clf@vN.tar.gz` (and `.gitkeep`). Nothing is deleted when the export or the parity check fails. Only files matching `intent_clf@v<int>.tar.gz` are ever removed.
    - One test in `ml/intent/tests/` proves both halves with a tmp dir.
  - Verify: `cd backend && uv run pytest ../ml/intent/tests -q`
  - Files: `ml/intent/export.py` and/or `ml/intent/compare.py`, `ml/intent/tests/test_export.py`

- [ ] T41: Generator and check support "card-type" top-up families
  - Depends on: T39 (finding), T36
  - Human decision: add training data that names the card type ("tarjeta de crédito/débito", "cartão de crédito/débito") for the card intents, then retrain.
  - Acceptance:
    - New prompt `ml/intent/prompts/intent_gen@v3.md` (v1, v2 kept): for one in-scope intent class and locale, produce K families (seed + 2 paraphrases) that each name the card type in the locale's own wording, half credit and half debit, and clearly ask for that class.
    - `generate.py` gains a mode (flag) that adds K such families to each in-scope intent cell (not the scope classes), with slot `card_type`, `generator` stamped `intent_gen@v3`, appended to the existing files without touching existing items. Default K = 2.
    - `check.py`: a cell passes with 29 or more accepted items (was 29 or 30); every other rule is unchanged.
    - Existing tests still pass; at most one new or changed test for the cell-size rule.
  - Verify: `cd backend && uv run pytest ../ml/intent/tests -q && cd .. && uv run --project backend python -m ml.intent.check --data-dir ml/intent/data`
  - Files: `ml/intent/prompts/intent_gen@v3.md`, `ml/intent/generate.py`, `ml/intent/check.py`, `ml/intent/tests/test_leakage.py`

- [ ] T42: LIVE: generate the card-type families and accept them (ALONE)
  - Depends on: T41
  - Acceptance: every in-scope intent cell (15 classes x 4 locales, confirm the count) gains 2 families (6 items) with `accepted: true`; items that duplicate or leak are rejected, not kept; the data check exits 0; the state file records the new totals and 12 sample items (3 per locale).
  - Verify: `uv run --project backend python -m ml.intent.check --data-dir ml/intent/data`
  - Files: `ml/intent/data/**`

- [ ] T43: LIVE: retrain, compare, bundle, image (ALONE)
  - Depends on: T42, T40
  - Acceptance: `make intent-train SEED=42` and `make intent-compare SEED=42` run once each; winner, tau, version, sha256 and the dev table are recorded; the old tarball is removed by the export step; the new bundle classifies "Necesito bloquear mi tarjeta de crédito ahora mismo." as `card_block`; the backend image builds and the stack logs `intent_classifier.loaded` with the new version. Stop and report if the winner is not c2.
  - Verify: lock sha256 equals the tarball's; `docker compose ... build backend` exits 0; the log line is present.
  - Files: `ml/intent/runs/**`, `ml/intent/model.lock`, `ml/intent/models/`

- [ ] T44: LIVE runtime: repeat the degraded e2e on the new bundle (ALONE)
  - Depends on: T43
  - Acceptance: both runs as in T39; 8 played, 0 unsafe in each; the card-block case's outcome in run 1 is recorded (expected: clarified).
  - Verify: as T39.
  - Files: `eval/reports/dev-*-run1-classifier/`, `eval/reports/dev-*-run2-no-classifier/`

- [ ] T45: `decline_explain` hands off in degraded mode (human decision at the verify gate)
  - Depends on: T44
  - Acceptance:
    - `decline_explain` is in `degraded_handoff_intents` in `policies/escalation.yaml` (version bumped); no prompt or template change.
    - One test in `backend/tests/unit/test_degraded.py`: a degraded `decline_explain` turn hands off, runs no tool and sends no canned apology.
    - `eval/scenarios/_staging/heldout/h-decline_explain-tool_failure-pt-br-05.yaml` relabeled to handoff, `reviewer: null`.
    - `docs/requirements/learned-intent-fallback.md` and the escalation YAML mirror in `docs/solution-docs/04-contracts.md` say decline explanation is not served in degraded mode.
    - Degraded e2e rerun (classifier loaded) saved as `eval/reports/dev-db8b7c5706-run3-classifier-decline-handoff/`, 0 unsafe.
  - Verify: `cd backend && uv run pytest tests/unit/test_degraded.py tests/unit/test_abstain.py -q`
  - Files: `policies/escalation.yaml`, `backend/tests/unit/test_degraded.py`, the staging case, `docs/requirements/learned-intent-fallback.md`, `docs/solution-docs/04-contracts.md`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1 | alone (adds deps, lockfile, downloads models) | Every later `uv run` and the scorers need the `ml` group |
| W2 | T2, T3, T4, T5, T6, T7, T8, T9, T10, T11 | | No mutual dependencies. Files are disjoint: graph and registry / localization and keyword / `ml/intent/data_io` and fixture / `classifier/scorers` / `core/llm/registry` and prompt / harness and `Makefile` / metrics and nlu_eval / scenario yamls / docs A / docs B |
| W3 | T12, T13, T14, T15, T16, T17 | | Each depends only on W2 tasks. Files are disjoint: `classifier/adapter`+stub+contract test / `generate.py` / `candidates`+`train` / `leakage`+`check`+test / compose, abstain, handoff_summary / policy and next_intent |
| W4 | T18 (LIVE), T19, T20 | | T18 writes only `ml/intent/data/**` and needs no service restart. T19 (loader, lock, contract test) and T20 (understand, load_session, route, smalltalk, templates) share no file |
| W5 | T21, T22 | | T21 is backend runtime files, T22 is `ml/intent/compare`, `report` and `export`. **T25 (HUMAN) starts here, after T18, and runs in the background through W7** |
| W6 | T23 | | Needs T21. Owns `conftest.py`, `test_degraded.py` and `test_faults.py` |
| W7 | T24 | alone (rebuilds images, restarts the stack) | Docker build proofs |
| — | T25 | HUMAN, background from W5 | Gate: W8 does not start until `ml.intent.check` passes on the audited data |
| W8 | T26 | | Proves the data is complete and leak-free before training. Sole owner of `Makefile` and `test_registry_consistency.py` at this point |
| W9 | T27 | alone (final training) | Criterion 1 on real data |
| W10 | T28 | alone (LIVE Ref calls, writes bundle and lock) | Needs T27 |
| W11 | T29 | alone (lockfile) | Needs T28's winner |
| W12 | T30 | alone (image rebuild, `make up`) | Needs T24, T28 and T29 |
| W13 | T31 | alone (live runtime eval, starts backends) | Needs the bundle, runtime deps and the relabeled case |
| W14 | T32 | | Needs T28's report and T31's counts |
