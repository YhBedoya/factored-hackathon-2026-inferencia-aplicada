# State: D5-A — privacy, grounding, eval runner and baseline
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D5-A (G6b + G11, owner A) · spec `docs/specs/d5-a-privacy-grounding-eval.md` · plan `docs/plans/d5-a-privacy-grounding-eval.md`
Branch `feat/d5-a-privacy-grounding-eval`, based on `develop`.

## Conventions established for this card
- Repo facts: read the plan's "## Facts checked against the repo" section (plan lines 5-95) for the parts your task touches; don't copy them here.
- Eval code runs under the backend uv env (`uv run --project backend ...`), imports nothing from `app`, lives in `eval/harness/`. B's `eval/scenarios/` and `eval/driver/` are read-only for A.
- `make fill-secrets` token_urlsafe is not a Fernet key: `PII_VAULT_KEY` gets its own generator (T5).
- (merge) `origin/develop` @ `36df383` (D5-B, PR #13) is merged: the branch now sits on it with the card's work uncommitted on top. B's `eval/scenarios/schema.py`, `eval/scenarios/{dev,_staging/heldout}/*.yaml`, `eval/driver/` and `eval/personas.yaml` exist; read them, don't edit them. D5-B also added an `openai` provider, pinned via `STEP_PROVIDER` for the eval-only `paraphrase` step (ADR-030). It goes through the same R5 guard and `audit.llm_calls` ledger, with `cost_usd` NULL because it has no price. `decline_explain` is a compose `Goal`, but it has no goal fact template, so a grounding failure there returns `fallback`. `make check` and `eval/tests` are green after the merge.

- (T14) Per-case verdict dict consumed by `eval/harness/metrics.py` has keys: verdict, outcome, expected_outcome, unsafe, in_scope, clarification_required, language_variant, segment, turn_latencies_ms, conversation_latency_ms, cost_usd, case_id, reason (see its docstring). T18/T19 must emit exactly these.
- (T10) `card_options` is recorded as one multi-line string; consumers of `fact_values` (T11 grounding) split recorded values on newlines.
- (parallel) Run `ruff format` only on your own files, never on a directory.
- (T6) `registry.known_pii(ctx)` is async. `sandbox._RecordingBankTools` does not yet wrap `get_pii_profile`; T7 (owns `sandbox.py`) must add the pass-through.
- (T11) `grounding` channel is last-write-wins; T12 must aggregate the worst-of-turn in the runner. `abstain_fallback` fill now lives in `compose_reply`; `abstain.py`'s `text == fallback` branch fires only on `LLMError` (relevant to T21).
- (T15) `llm_calls.jsonl` rows: id from `id`, else `row_id`, else line number; scanned text = `input_text`. `results.jsonl`: persona id from `persona`, else `customer_id`. T19 must write these keys.
- (T16) dbstate column sets are static copies of migrations 0001/0003. `clone.drop` refuses names not starting `latam_eval_`.
- (T5) `mask()` flushes itself; `put_address` only buffers, so callers must `flush()`. `PostgresPiiVault.put_address` raises unless `mask()`/`unmask()` ran first in the turn: the runner masks the turn text first. Empty `PII_VAULT_KEY` is not refused yet; T9 wires the startup refusal.
- (T8) `start_turn` calls `vault.mask(text, await registry.known_pii(ctx))` directly and releases the turn lock if masking/insert fails. Non-text turns get a vault but never call `mask`.
- (T27) T24 must add the `PII_VAULT_KEY` row to `08` §9 (SSM `/swip/prod/PII_VAULT_KEY`, Fernet).

- (T17) B's `eval/tests/test_driver.py` and `test_scenarios_valid.py` fail `ruff check`/`format --check` on develop. They are B's to fix, so lint only your own `eval/` files, never `eval/tests` as a directory. The `a-card_block` lock seed uses `CLI-5RJITZ5VLJGY` (2 debit cards) with no follow-up turn: if a live run asks which card, report it; don't edit the seed.

- (T18) `run_checks(ev, write_tools=None)` → CheckResult list; `case_verdict(ev, results)` → the T14 keys + `persona`. `not_run` reasons `not_runnable`/`db_patches`; `error`/`max_turns` → failed, outcome `error`. `confirm_before_act` matches the same turn and tool (the executor logs `tool_call` before `confirmation_used`). `clarification_required` is set only for ambiguous seeds or expected `clarified`, else None (implementer's choice, sent to the human).

- (T19) `make eval SUITE=dev SYSTEM=both` needs the stack up and `.env` with DATABASE_URL, GOLDEN_DATABASE_URL, REDIS_URL, LLM keys, DEMO_OTP_CODE. Each system clones golden (~6 min); run id `<suite>_<system>_<UTC ts>`; Redis db 1 proposed / 2 baseline; `pii_hits` in meta.json (a hit doesn't abort); then `make eval-pii-check RUN=<run_id>`. A restore diff aborts with RestoreDiffError.

## Human decisions taken mid-card
- (verify) Baseline: a negated-only intent returns `intents=[]` / `out_of_scope` / topic `other`, as decided at T20. The T20 repair had folded it into `general_question` (T37).
- (after T25) The AWS deploy is postponed to the end of D6 unless strictly required. The T27 runbook stays; T-deploy-record moves to the end of D6. The spec amendment updates the `07` deploy row.
- (T25 run 3, stopped) Performance measurement is postponed: the system is still evolving. D5-A proves the harness with one smoke run of the 4 `a-*` cases on the proposed system only (`CASES=a-`, T35), with no targets. The full dev run for both systems (criterion 6 as written) and the D1.5 targets (T26) move to a later card. Spec amendment at the gate.
- (T31) Sonnet 5.5 also rejects forced `tool_choice`. On the `anthropic` provider, every step uses `with_structured_output(..., method="json_schema")` (API structured outputs); `bedrock` keeps function_calling until K2 confirms.
- (T25) `claude-sonnet-5-5` rejects `temperature`. Keep Sonnet 5.5 for NLU and send no temperature; the ledger records NULL (migration 0008). R7 now reads "where the model accepts one", with a note in ADR-031 (T31, T32).
- (after merge) `decline_explain` gets its own goal template `goal_decline_explain`: ES `Tu compra fue rechazada: {decline_cause} {decline_next_step}` / PT `Sua compra foi recusada: {decline_cause} {decline_next_step}` (no "." after the cause, because the labels already end with one; T29).
- (after merge) This branch fixes B's ruff failures in `eval/tests/test_driver.py`/`test_scenarios_valid.py`, mechanical only (T30); flag it to Dev B in the PR.
- (T17) If the live run asks which card on `a-card_block-normal_resolution-es-co-01`, add a follow-up turn picking the card; keep the persona.
- (T28) Agent MCP servers run as dev-only compose services (`make up`/`make down`); Playwright opens the app at `http://nginx/` on the compose network.
- (mid-card) NLU model is Sonnet 5.5 (`claude-sonnet-5-5`, $2/$10 per MTok); compose and handoff_summary stay Haiku 4.5. Changed in `core/llm/registry.py` and `pricing.py`. T24 records it in the docs (`07` model row, decision log). The eval baseline comparison uses this NLU model.
- (after T13) Write T27 now, then hold the card open until B's schema is on develop; merge develop and finish T17–T26 before verify.
- (T13) Fix Langfuse usage=0 in this card (T4b).
- (T4) Langfuse self-host compose pinned to the `:4` image line, not `:3`.
- (T6) Keep `KnownPii.names` split into words of 3+ letters.
- (T20) Baseline: no lexicon hit -> `general_question`; negated-only intent -> empty intent list.
- (start) Tasks run in parallel in this checkout when dependencies are done and file lists are disjoint. Implementers touch only their task's files, append to the Task log only with one shell `>>` heredoc (never Edit/Write the state file), never run `uv add`/`uv sync`/`uv lock`, and report (not fix) failures in files they don't own.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | ab311fc | pii.py detectors; cryptography 50.0.1, langfuse 4.15.6; importlinter forbids langfuse outside core.llm |
| T2 | done | a248fe1 | R5 guard (LLMUnmaskedInput), per-attempt LLMCallRecord sink, pricing.py (Haiku $1/$5 unverified) |
| T3 | done | a8b794f | 0007: app.pii_vault + audit.llm_calls; AuditLLMCallSink; insert_llm_call(row_id, at, record) |
| T4 | done | ab657fd | Langfuse generation w/ redact mask, should_export_span=is_langfuse_span; profile langfuse (:4 images) on :3100; make langfuse-up/down |
| T5 | done | a8a56ef | Settings.pii_vault_key/agent_system; PiiVault (InMemory/Postgres), encrypt_text/decrypt_text; Fernet fill-secrets |
| T2b | done | a248fe1 | client.py passes input_text to trace_llm_call, records langfuse_trace_id per attempt |
| T4b | done | ab657fd | trace_llm_call yields LLMSpan(.id, .set_usage); client sets usage per attempt |
| T6 | done | aabc29d | get_pii_profile() on read tools; async registry.known_pii(ctx); FakeBank has own _known_pii copy (import-linter) |
| T7 | done | a94c0eb | masking.mask_user_text; sandbox CLI masks/unmasks; test_nlu_sees_only_tokens |
| T7b | done | a94c0eb | backend/scripts/sandbox_ui.py masks typed text, unmasks reply (R5 gap found by T7) |
| T8 | done | acdf5e1 | start_turn masks via PostgresPiiVault, encrypted app.messages + content_masked, bind_turn_id, unmasked reply; takeover masked; repair: bind_conversation_id in _run_turn |
| T9 | done | a920fde | AuditLLMCallSink wired, empty PII_VAULT_KEY refused, test_privacy_ledger passes (after T8 repair) |
| T10 | done | aaf2f18 | fact_values.py collecting()/record(); wired in fill, card_select, unrecognized_charge, handoff, abstain |
| T11 | done | afc71eb | compose D11 checks, 1 regen then goal template; compose_checked() returns (text, outcome) |
| T12 | done | ac48d81 | reply_sent gets fact_values (deduped) + grounding.outcome (worst of turn) |
| T13 | done | a08bb7b | live: ledger has ⟨CARD_1⟩ not PAN, messages Fernet, Langfuse generation masked; golden+app at 0007 |
| T14 | done | aaf2fa7 | eval pkg skeleton + metrics.py (wilson, rule_of_three, Rate, percentiles, D16 sets) |
| T15 | done | affbf3a | pii_check.scan + CLI + make eval-pii-check |
| T16 | done | afe84df | clone.py, restore.py (diff_rows/RestoreDiffError), dbstate.compile_item |
| T17 | done | a2527 | lint.py, canned.py, 4 a-* seeds; lint_suite clean on all 85 dev cases |
| T18 | done | a2883 | evidence.py, checks.py (run_checks, case_verdict); 4 tests pass |
| T19 | done | a18f0 | runner/report/__main__, make eval; 12 tests pass; no live run |
| T20 | done | abfcc8e | keyword_nlu + lexicon; no-hit (incl. negated-only) -> general_question |
| T21 | done | a823072 | build_graph(system=) swaps understand/compose/handoff_summary/abstain; no-LLM baseline test |
| T22 | done | a12fc2e | open_host(system=); _require_eval_for_baseline after _require_secrets in main.py; admin reopen passes system |
| T23 | done | ac86679 | docs 01 §6, 02 §3, 03 §6, 04 §6 updated |
| T24 | done | acfbc | 06 §2/§3, 07 A1 + NLU row, 08 §9/§10, ADR-031 Sonnet 5.5 NLU |
| T25 | done | a4c26 | smoke dev_proposed_20260929t174357: harness end to end OK, PII 0 hits, clone dropped; card-lock case error no_open_confirmation (T36) |
| T26 | moved | | D1.5 targets postponed to a later card (human) |
| T29 | done | aee3b | goal_decline_explain ES/PT (no period after cause) + ES/PT test; 5 pass |
| T31 | done | a7cda | nlu no temperature; anthropic steps use json_schema; migration 0008 on app+golden; 3 live calls OK |
| T32 | done | a0c2d | R7 "where the model accepts one"; ADR-031 temperature note |
| T37 | done | a9135 | negated-only → intents=[] / out_of_scope / other; ES+PT cases; 11 pass |
| T36 | done | a1ac2 | seed turn 2 'La que termina en 5772, solo un bloqueo temporal'; one-case smoke passed, PII 0, clone dropped |
| T35 | done | a7740 | --cases/CASES= filter; report header + meta cases_filter; 18 eval tests pass (also touched report.py, accepted) |
| T34 | done | a96ed | llm.call logs error_type/error_message (redacted, 300 chars); guard aborts only on ≥1 row all unavailable |
| T33 | done | a79af | LLMUnreachableError after 5+ cases all unavailable; test passes |
| T30 | done | a45cf | ruff format + PIE810 fix in B's 2 eval tests; 5 pass |
| T27 | done | ad5ec52 | deploy runbook + 14-item checklist in T27 log; .env.prod.example PII_VAULT_KEY; D4-A T32/T33 moved |
| T28 | done | ab5116b | devtools compose: mcp-victorialogs :8081, mcp-victoriatraces :8082, mcp-playwright :8931; .mcp.json http; app at http://nginx/ |
| T-deploy-record | moved: end of D6 (human) | | Human deploys main at the end of D6 using the T27 runbook; record results then |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — cryptography + langfuse, core/pii.py, import-linter
Created: `backend/app/core/pii.py` (`find_pii`, `redact`, `KnownPii`, `PiiMatch`, `PiiKind`, `TOKEN_RE`).
Changed: `backend/pyproject.toml`, `backend/uv.lock` (`cryptography==50.0.1`, `langfuse==4.15.6`), `backend/.importlinter` (`langfuse` forbidden outside `app.core.llm`, plus ignore lines).
Facts the next tasks need: overlaps resolve EMAIL > +5x phone > CARD > DOC > national phone > known names/doc; DOC match span is the number only, not the keyword; a `+52…` number that is Luhn-valid is PHONE, not CARD.
Deviations: none.
Verify: task Verify command → passes (4 contracts kept, ruff, format, mypy clean).

### T14 — eval package skeleton and metrics
Created: `eval/__init__.py`, `eval/tests/__init__.py`, `eval/harness/__init__.py`, `eval/harness/metrics.py` (`wilson`, `rule_of_three`, `Rate.of`, `percentiles`, `compute`, `by_group`, `compute_all`), `eval/tests/test_metrics.py`.
Facts the next tasks need: verdict dict keys are documented in the `metrics.py` docstring (`verdict` passed|failed|not_run, `outcome`, `expected_outcome`, `unsafe`, `in_scope`, `clarification_required`, `language_variant`, `segment`, `turn_latencies_ms`, `conversation_latency_ms`, `cost_usd`, `case_id`, `reason`); T18/T19 must emit those. `compute_all` returns overall + by_language_variant + by_segment + not_run; Rate n=0 gives value/ci None.
Deviations: none (the verdict-dict shape was unspecified, so I chose it).
Verify: `pytest eval/tests/test_metrics.py -q` -> 1 passed; ruff check and format --check clean.

### T10 — Per-turn fact-values collector
Created: `backend/app/domains/conversation/fact_values.py` (`collecting`, `record`).
Changed: `flows/actions.py` (`fill` records all values), `flows/card_select.py` (`ask_which_card_text` records `card_options`), `flows/unrecognized_charge.py` (records `card_options`), `nodes/handoff.py` (records label, reference), `nodes/abstain.py` (records the non-empty facts values).
Facts the next tasks need: `card_options` is recorded as the whole multi-line string, not per line; smalltalk greeting not recorded.
Deviations: none.
Verify: task Verify command → smoke ok, 23 passed, ruff/format/mypy clean.

### T6 — get_pii_profile() on the read tools
Created: `customers.repository.fetch_known_pii`, `customers.service.get_known_pii` + `build_known_pii`.
Changed: `tools/bank.py` (protocol), `tools/postgres.py`, `tools/fakebank.py` (own `_known_pii` copy, since conversation can't import customers.service: import-linter), `tools/registry.py` (`RecordingBankTools.get_pii_profile` pass-through, `async known_pii(ctx)`).
Facts the next tasks need: `known_pii(ctx)` is async; `KnownPii.names` = first/last name split into words of 3+ chars, deduped. `sandbox._RecordingBankTools` (not mine) doesn't wrap `get_pii_profile`.
Deviations: none.
Verify: task Verify → 8 passed, 4 contracts kept, ruff/format/mypy clean.

### T20 — Keyword NLU for the baseline
Created: `backend/app/domains/conversation/baseline/{__init__.py,keyword_nlu.py,lexicon.yaml}` (`keyword_nlu(text, language_hint=None) -> NLUResult`), `backend/tests/unit/test_baseline.py`.
Facts the next tasks need: no-intent text returns `out_of_scope` (topic from lexicon or `other`), Pix/boleto/CPF → `out_of_market` + `topic=pix_boleto`; generic `bloquear` → `ambiguous`/`lock_vs_block`, with a temporal/permanent qualifier → `clear` + `slots.block_kind`. Matching is on accent-stripped lowercase; YAML negators are quoted ("no" is a YAML bool otherwise).
Deviations: none.
Verify: task Verify command → 8 passed, ruff/format/mypy clean.

### T15 — PII scan over the LLM-call export
Created: `eval/harness/pii_check.py` (`scan`, `Hit`, `main`), `eval/tests/test_pii_check.py`.
Changed: `Makefile` (`eval-pii-check RUN=`, in `.PHONY`).
Facts the next tasks need: `scan(rows, personas_pii)` reads `input_text` and row id from `id` (or `row_id`, else 1-based line no.); persona dicts use keys `document_number,email,phone,first_name,last_name`. Kinds: `KNOWN_DOC|EMAIL|PHONE|NAME`, `EMAIL_PATTERN|PHONE_PATTERN|CARD_PATTERN`. CLI reads persona ids from `results.jsonl` key `persona` (or `customer_id`), queries `bank.customers` (`mobile_phone`) in golden. T18/T19 must write those keys. Exit 1 on hits; a run-internal call is `main(["--run", id])`.
Deviations: none (row/persona key names were unspecified; chosen as above).
Verify: pytest 1 passed; ruff check/format --check clean; `make -n eval-pii-check RUN=x` ok.

### T2 — R5 guard and per-attempt ledger in StructuredLLMClient (BLOCKED on one out-of-list edit)
Created: `core/llm/sink.py` (`LLMCallRecord`, `LLMCallSink`, `LLMCallStatus`), `core/llm/pricing.py` (`PRICE_PER_MTOK`, `cost_usd`; Haiku 4.5 = 1.00/5.00 USD per MTok, both anthropic and bedrock ids), `tests/unit/test_r5_llm_guard.py`.
Changed: `core/llm/client.py` (guard, `_finish` logs+ledgers each attempt, `sink=` on client and `get_llm_client`), `errors.py` (`LLMUnmaskedInput`), `__init__.py` exports.
Facts: `LLMCallRecord.provider` is `str` (not `Provider`) for B's `openai`; refused record uses attempt=0; ledger-failure logs `llm.ledger_failed`.
Deviations: `tests/unit/test_llm_client.py::test_transport_failure_is_bounded_and_logged` uses a raw card number as `user`, which the R5 guard now refuses. It needs `user_text` changed to a masked string; the edit was denied (file not in T2's list), so it FAILS until the orchestrator authorises it.
Verify: new test + ruff + mypy + lint-imports pass; test_llm_client.py has 1 failure (above).

### T16 — Clone lifecycle, restore/diff, db_state compiler
Created: `eval/harness/clone.py` (`create`, `drop`, `dsn`, `clone_name`), `eval/harness/restore.py` (`RESTORE_TABLES`, `restore_persona`, `verify_persona`, `diff_rows`, `RestoreDiffError`), `eval/harness/dbstate.py` (`DB_ALLOWLIST`, `compile_item`, `DbStateLoadError`), `eval/tests/test_restore.py`.
Facts the next tasks need: psycopg sync connections (`restore_persona(clone_conn, golden_conn, customer_id)`, `dsn(dbname)` reads `DATABASE_URL`); `compile_item` returns `%s` positional params as a list; DB_ALLOWLIST = bank.products/transactions/complaints + app.card_status_history/card_controls/card_replacements/handoffs (column sets static, from migrations); app.* tables scoped via product_id/conversation_id subselects; `restore_persona` commits.
Deviations: none. `restore`/`clone` DB paths untested against a live DB (no test asked).
Verify: pytest test_restore.py -> 1 passed; compile_item prints the SELECT; ruff check/format clean.

### T11 — Grounding check in compose
Created: none.
Changed: `nodes/compose.py` (`compose_checked` -> `(text, "ok"|"regenerated"|"template")`; `compose_reply` wraps it, returns text), `templates.py` (`goal_card_status`, `goal_balance_due`), `graph.py` (`GraphState.grounding`), `tests/unit/test_compose.py` (2 new tests; the old bad-draft cases now script 2 drafts and expect the goal template).
Facts the next tasks need: compose returns `grounding` in its update, plain overwrite (not worst-of across several compose calls in a turn: D32 aggregation is not done here). A template missing a needed fact key, or an LLMError, gives `fallback` (outcome `template`). The `abstain` goal template is filled inside `compose_reply` (`abstain_fallback`), so `abstain.py`'s `text == fallback` branch now only fires on LLMError. Compose still `compose@v5`; retry reason is appended to the user message ("Corrige: ...").
Deviations: none. No new `Goal` literal from develop.
Verify: task Verify -> 14 passed, ruff/format/mypy clean.

### T20 revision
Changed: `keyword_nlu.py`: no lexicon hit, or a negated-only intent with no out-of-scope hit, now returns `intents=["general_question"]`, `status=clear`. Out-of-scope topic hits (loans, etc.) still return `out_of_scope` with the topic. No test changed (no case asserted the old result).
Verify: full T20 Verify → 8 passed, ruff/format/mypy clean.

### T2 repair 1
Changed: `tests/unit/test_llm_client.py` (`user_text` now masked `⟨CARD_1⟩`); `core/llm/pricing.py` comment. Haiku 4.5 $1/$5 per MTok could NOT be confirmed: the `claude-api` skill has no price table and its pricing.md URL was unreachable; value kept as list price, as of 2026-09-29. T2 blocker resolved.
Verify: full T2 Verify passes (4 passed, ruff, format, mypy, lint-imports).

### T21 — build_graph(system="baseline")
Created: `baseline/template_compose.py` (`baseline_understand`, `baseline_compose`, `baseline_handoff_summary`, `baseline_abstain`).
Changed: `graph.py` (`build_graph(checkpointer, system="proposed")` swaps the four nodes), `nodes/abstain.py` (`make_abstain(llm_wording=True)`; `abstain` unchanged in behavior), `tests/unit/test_baseline.py` (+1 test).
Facts the next tasks need: baseline handoff_summary re-resolves the escalation and returns `handoff_summary._fallback(reason, language)`; compose uses compose's private `_fill_goal_template`/`_current_intent`; baseline abstain emits no `grounding` key.
Deviations: none.
Verify: task Verify -> 14 passed, ruff/format/mypy clean.

### T3 — Migration 0007_privacy_ledger and AuditLLMCallSink
Created: `backend/app/alembic/versions/0007_privacy_ledger.py` (`app.pii_vault`, `audit.llm_calls`, CHECK `ck_llm_calls_status`, index `ix_llm_calls_conversation_id_at`; revision id `"0007"`).
Changed: `audit/repository.py` (`insert_llm_call(row_id, at, record)`), `audit/service.py` (`AuditLLMCallSink().record(call)`).
Facts the next tasks need: `insert_llm_call` takes `id`/`at` from the sink (not the record); str ids in the record are converted to UUID; failures raise `ToolUnavailable`. `latam_app` and `latam_golden` both at head. `schemas.py` untouched (no schema needed).
Deviations: `insert_llm_call` signature is `(row_id, at, record)`, not `(record)`, so the sink owns `id`/`at`.
Verify: full T3 Verify passes (both DBs upgraded, downgrade -1 round-trip ok, 4 contracts kept, ruff/format/mypy clean).

### T4 — Self-hosted Langfuse generation span, compose profile, make targets
Created: `backend/tests/unit/test_r5_masking.py`.
Changed: `core/llm/tracing.py` (`langfuse_mask`, real `trace_llm_call`), `core/llm/settings.py` (`langfuse_public_key`/`langfuse_secret_key`), `docker/docker-compose.observability.yml` (6 `langfuse-*` services, `profiles: [langfuse]`, web on `127.0.0.1:3100`, images `langfuse/langfuse:3` + `langfuse-worker:3`), `Makefile` (`langfuse-up`/`langfuse-down`), `.env.example`.
SDK export setting: `Langfuse(..., should_export_span=langfuse.span_filter.is_langfuse_span, mask=langfuse_mask)`; the app's OTel spans are never exported to Langfuse.
Facts the next tasks need: `trace_llm_call` now yields `str | None` (the Langfuse trace id) and takes optional `input_text=`; no-op without `langfuse_host` or without both keys. `client.py` (not mine) still calls it without `input_text` and ignores the yielded id, so the generation has no input and `langfuse_trace_id` stays None until someone passes `input_text=user` and `as trace_id` and puts it on the record. Keys are read from `LLMSettings()` inside tracing (cached per host).
Deviations: Langfuse's current official compose is on the `:4` image line per DeepWiki; I used `:3` as the task said "v3 line". Compose secrets default to throwaway dev values via `${LANGFUSE_*:-...}`; no headless-init keys, so keys are created in the UI at :3100.
Verify: full task Verify passes (config -q ok, make -n ok, 1 passed, ruff/format/mypy clean, 4 contracts kept).

### T2b
Changed: `core/llm/client.py` only: each attempt passes `input_text=user` to `trace_llm_call`, captures the yielded id (kept even if the call raises) and puts it on that attempt's `LLMCallRecord.langfuse_trace_id`. Refused path never traces (`input_text=None`, trace id None). Verify passes.

### T5 — Settings, Fernet PII vault, PII_VAULT_KEY
Changed: `core/config.py` (`pii_vault_key`, `agent_system`), `domains/safety/vault.py` (`PiiVault`, `InMemoryPiiVault`, `PostgresPiiVault(conversation_id)`, `encrypt_text`/`decrypt_text`; `InMemoryAddressVault` kept), `Makefile` (fill-secrets: Fernet generator for `PII_VAULT_KEY`), `.env.example`, `tests/integration/conftest.py` (`it_env` sets a Fernet key).
Facts the next tasks need: `mask()` flushes on its own; `put_address` only buffers, so call `flush()` after it. `PostgresPiiVault.put_address` raises RuntimeError unless `mask()`/`unmask()` ran first (rows load lazily; needed for numbering). Same raw value -> same token for every kind, ADDR included. Persistence failure raises `ToolUnavailable("pii_vault")`. The "refuse to start on empty key" check (D21) is NOT wired here: an empty key only fails at first encrypt (`Fernet` ValueError).
Deviations: none. PostgresPiiVault DB path untested (no test asked).
Verify: task Verify -> auth 4 passed, ruff/format/mypy clean, make -n ok.

### T4 revision — Langfuse compose moved to the v4 line
Changed: `docker/docker-compose.observability.yml` only: web/worker images now `docker.langfuse.com/langfuse/langfuse:4` / `langfuse-worker:4`. Everything else kept (profile, 127.0.0.1:3100, dev defaults).
Facts: per DeepWiki, v4 adds no required env vars (only optional AI/agent vars; `LANGFUSE_MIGRATION_V4_WRITE_MODE` defaults to `events_only`); ClickHouse 25.12, redis:7, chainguard minio unchanged. SDK 4.15.6 needs no change: its own exporter sends `x-langfuse-ingestion-version=4` (only a custom `span_exporter=` would need it, and tracing.py passes none). No `.env.example` or Makefile change needed. Image registry/tags not pulled (config check only).
Verify: compose `--profile langfuse config -q` ok; without the profile `config --services | grep -ci langfuse` -> 0.

### T22 — AGENT_SYSTEM host wiring
Changed: `conversation/hosting.py` (`open_host(database_url, llm, system="proposed")` -> `build_graph(saver, system=system)`), `main.py` (`_require_eval_for_baseline`, called right after `_require_secrets` in `_lifespan`; passes `settings.agent_system`), `api/v1/admin.py` (demo reset reopen passes `system=get_settings().agent_system`).
Facts the next tasks need: T9 adds the empty-`PII_VAULT_KEY` check next to `_require_secrets` in `_lifespan`.
Deviations: none.
Verify: task Verify -> baseline refused, 1 passed, ruff/format/mypy clean.

### T7 — Masking step and sandbox path
Created: `backend/app/domains/conversation/masking.py` (`mask_user_text(text, *, bank_tools, vault)`).
Changed: `conversation/sandbox.py` (`_RecordingBankTools.get_pii_profile` pass-through, unrecorded; session builds `InMemoryPiiVault`, kept on `_SandboxSession.vault`; typed lines masked before `run_turn`, reply unmasked before print; slash commands untouched), `tests/unit/test_r5_masking.py` (+ `test_nlu_sees_only_tokens`; T4's test kept).
Facts the next tasks need: `sandbox.build_sandbox_session` 3-tuple unchanged, so the Streamlit page (`scripts/sandbox_ui.py`) does NOT mask yet; the vault is in `config["configurable"]["vault"]`. The ScriptedLLM NLU step key is `"nlu"`.
Deviations: none.
Verify: pytest 8 passed; ruff check, format --check, mypy clean.

### T7b — Streamlit sandbox masks typed text
Changed: `backend/scripts/sandbox_ui.py` (note: the file is under `backend/scripts/`, not repo-root `scripts/`; `_send` masks with `mask_user_text` before `run_turn` and unmasks the reply, using the session vault from `config["configurable"]["vault"]`). The page has no slash commands. `sandbox.py` unchanged in T7b.
Deviations: none.
Verify: pytest 8 passed; ruff check/format --check clean; ast parse ok.

### T8 — API path masking, encrypted messages
Changed: `conversation/runner.py` (`start_turn` masks typed text with a `PostgresPiiVault`, stores raw+masked, passes masked to `_run_turn` via new `graph_text`/`vault` params; `text` stays raw for the relay echo; reply flushed, unmasked, stored with `content_masked`=pre-unmask reply; lock released if masking/persist fails), `store.py` (required `content_masked`, encrypt/decrypt), `takeover.py` (agent/system masked with `KnownPii(None, ())`), `core/logging.py` (`bind_turn_id`).
Facts the next tasks need: `start_turn` uses `vault.mask(text, await registry.known_pii(ctx))` directly, not `masking.mask_user_text` (no read tools needed there). Non-text turns (resume/confirmation/selection) get a vault too but never mask, so `put_address` there relies on `unmask` loading first. `ui_payload` is stored as is. Only `store.add_message` callers were runner and takeover.
Deviations: none.
Verify: staff round trip 3 passed; ruff, format, mypy clean; lint-imports 4 kept, 0 broken.

### T9 — Ledger sink wired, PII_VAULT_KEY refused (BLOCKED on one out-of-list edit)
Changed: `backend/app/main.py` (`_lifespan` uses `get_llm_client(sink=AuditLLMCallSink())`; `_require_secrets` takes `pii_vault_key`), `tests/integration/test_write_path_api.py` and `test_confirmations_route.py` (pollers `SELECT content_masked AS content`, asserts unchanged). Created `tests/integration/test_privacy_ledger.py` (two turns: PAN + card_status, then human_request so a claimant can read the transcript).
Blocker: nothing binds `conversation_id` in structlog contextvars (`bind_conversation_id` has no caller; runner only calls `bind_turn_id`), so `audit.llm_calls.conversation_id` is NULL and the new test finds no rows. Fix: call `bind_conversation_id(str(conversation_id))` next to `bind_turn_id` in `conversation/runner.py::_run_turn` (T8's file, not in T9's list).
Verify: 5 passed, new test fails on that; ruff/format/mypy clean.

### T8 repair 1
Changed: `runner.py` `_run_turn` now also calls `bind_conversation_id(str(conversation_id))` before `bind_turn_id`; bindings live in the `create_task` context copy, so they don't leak. `start_turn` does no LLM/ledger work, so nothing bound there.
Verify: privacy_ledger + staff_round_trip + write_path_api + confirmations_route → 9 passed; ruff, format, mypy clean.

### T12 — reply_sent grounding + fact_values
Changed: `conversation/runner.py` (astream loop inside `fact_values.collecting()`; `_worse_grounding` keeps the worst `compose` outcome; `reply_sent` adds `fact_values` (deduped in order) and `grounding: {outcome}` only when compose ran), `tests/integration/test_privacy_ledger.py` (+ assertions on the turn's `reply_sent`).
Facts the next tasks need: `fact_values` for a card_status turn is `['•••• 2222', 'Crédito', 'Activa']`: the mask is the customer's own card, not the typed PAN. The audit table is `audit.audit_events`.
Deviations: none.
Verify: privacy_ledger 1 passed; ruff check/format --check/mypy clean.

### T23 — Doc updates part 1 (01 §6, 02 §3, 03 §6, 04 §6)
Changed: `docs/solution-docs/01-technical-design.md` (PII bullet: detectors, third-party limit, staff view, agent/system pattern-only masking), `02-conversation-design.md` (`mask_pii` node removed from the diagram; "Masking and grounding" and "Baseline" paragraphs), `03-data-architecture.md` (`messages`, `pii_vault`, `llm_calls` rows), `04-contracts.md` (`reply_sent` `grounding` + `fact_values` paragraph in §6).
Facts the next tasks need: `01` retention line and the `(proposed)` Fernet-on-`bank.customers` note kept; no `05`/`06`/`07`/`08` edits.
Deviations: none.
Verify: task grep chain -> OK.

### T13 — Live A1/A2 proof on the dev stack
No source change. `make fill-secrets` filled only `PII_VAULT_KEY` (the other three were already set, not rotated). `make up` rebuilt; `latam_app` and `latam_golden` both at `0007`.
Chat: `make chat-api PERSONA=CLI-U6NAXZG11P97` (ES) with "mi tarjeta 4111 1111 1111 1111 está bloqueada?" -> card_picker reply.
SQL: `audit.llm_calls` input_text = "Pais: MX / Pregunta pendiente: ninguna. / Mensaje del cliente: ``` mi tarjeta ⟨CARD_1⟩ está bloqueada? ```"; counts (total|contains 4111|contains ⟨CARD_) = 2|0|2 (after the Langfuse turn too).
`app.messages` newest 2: customer content_masked "mi tarjeta ⟨CARD_1⟩ está bloqueada?"; bot content_masked "¿Sobre cuál tarjeta quieres saber? / Crédito •••• 1882 · Bloqueada / Débito •••• 4565 · Activa"; `content` for both starts `gAAAAAB...` (Fernet ciphertext).
Langfuse (self-host :4, throwaway user/org/project made through its signup + tRPC API, keys only in git-ignored `.env`; host `http://langfuse-web:3000` since the backend is in Docker): `GET /api/public/v2/observations?type=GENERATION` -> 1 generation: name=nlu, model=claude-haiku-4-5-20251001, metadata.prompt_version=nlu@v4, step=nlu, provider=anthropic, input="Pais: MX\nPregunta pendiente: ninguna.\nMensaje del cliente:\n```\nmi tarjeta ⟨CARD_1⟩ está bloqueada?\n```" (no 4111), latency 2.3s. Note: input/output/total usage all 0 (token usage not reported to Langfuse).
Cleanup: `make langfuse-down` done; `LANGFUSE_*` lines commented out in `.env`; backend recreated without them; `PII_VAULT_KEY` left set; main stack up.
Deviations: none.
Verify: task Verify chain -> pass (exit 0, "VERIFY PASS").

### T4b — Token usage on the Langfuse generation
Changed: `core/llm/tracing.py` (new `LLMSpan` handle: `.id`, `.set_usage(input, output)` -> `generation.update(usage_details={"input","output"})`; `trace_llm_call` now yields `LLMSpan`, inert when untraced), `core/llm/client.py` (`as span`, `langfuse_trace_id = span.id`, `span.set_usage(...)` from `usage_metadata` right after `ainvoke`, inside the context).
Facts: the refused (R5) path returns before `trace_llm_call`, so it never traces; masking untouched; cost left unset; model is already set at generation start. Stubbed-client check: usage call got `{'input': 11, 'output': 7}`, untraced handle gave id None and no calls, no network.
Verify: 6 passed (guard, client, masking); ruff, format, mypy clean; 4 contracts kept.

### T27 — AWS deploy runbook and checklist (no AWS command was run)
Changed: `.env.prod.example` (`PII_VAULT_KEY=` under the SSM block), D4-A state (T32/T33 `moved → D5-A`), `07` §8 (D5 deploy row).
Facts the next tasks need: `render-env.sh` renders the whole `/swip/prod/` path, so `PII_VAULT_KEY` needs no script change. The backend refuses to start without it. Board row `T-deploy-record` already existed (status `pending (post-merge follow-up)`, orchestrator-owned).
Findings: (1) `08` §9 still lacks `PII_VAULT_KEY` (D24 doc task). (2) `08` §10 still says "Langfuse not on prod": consistent, Langfuse (profile `langfuse`) is not in the prod compose. (3) No script issues the certificate: step 5 is manual certbot in the compose `certbot` service. (4) The runbook's step 0 waits for T17–T26 (and D5-B if merged).
Verify: see the orchestrator's run of the T27 Verify command.

#### Runbook (human runs it; every `<PLACEHOLDER>` is a value the human supplies)

**Step 0. Release PR.** Only after the whole D5-A card (including the eval-runner tasks T17–T26) and D5-B, if merged, have landed on `develop`: open the `develop → main` release PR, get the green check, merge. Deploy `main`, never a branch.

**Step 1. Data copy (08 §5), from a laptop.** Never sync the repo's `data/` (it holds `data/secrets/credentials.csv`); always upload from a clean staging folder outside the repo.
```bash
STAGING=$(mktemp -d)   # outside the repo
# organizer credentials in env vars or a profile, never written down
aws s3 sync s3://<ORGANIZERS_BUCKET>/data/ "$STAGING/data/" --profile <ORGANIZER_PROFILE>
aws s3 sync "$STAGING/data/" s3://<OUR_BUCKET>/data/ --profile <TEAM_PROFILE>
# verify: count and key+size listing; compare sizes, NOT ETags
find "$STAGING/data" -type f | wc -l                       # expect 7671
aws s3 ls s3://<OUR_BUCKET>/data/ --recursive --profile <TEAM_PROFILE> | awk '{print $4, $3}' | sort > our.txt
aws s3 ls s3://<ORGANIZERS_BUCKET>/data/ --recursive --profile <ORGANIZER_PROFILE> | awk '{print $4, $3}' | sort > src.txt
diff src.txt our.txt && wc -l our.txt                      # empty diff, 7671 lines
```
Keep `src.txt` (key, size, copy date) as provenance for 03 §1. Keep the organizers' bucket name out of committed files.

**Step 2. SSM parameters under `/swip/prod/` (08 §9), SecureString.**
```bash
P=/swip/prod
put() { aws ssm put-parameter --name "$P/$1" --type SecureString --overwrite --value "$2" --profile <TEAM_PROFILE> --region us-east-1 >/dev/null; }
put POSTGRES_USER <PG_USER>
put POSTGRES_PASSWORD <PG_PASSWORD>            # not the dev default
put JWT_SECRET <JWT_SECRET>
put IDENTITY_HMAC_KEY <IDENTITY_HMAC_KEY>
put CREDENTIALS_SEED <CREDENTIALS_SEED>        # MUST equal the seed behind the judges' credentials
put DEMO_OTP_CODE <DEMO_OTP_CODE>
put S3_BUCKET <OUR_BUCKET>
put PUBLIC_HOST <EIP_WITH_DASHES>.sslip.io     # after step 3 gives the Elastic IP; re-put then
# NEW (D21): a Fernet key. Generate it locally, put it, and keep a copy in the team vault.
put PII_VAULT_KEY "$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
```
Losing `PII_VAULT_KEY` makes old vault rows and message content unreadable (demo-reset clears them). The backend refuses to start with it empty. Verify names only: `aws ssm get-parameters-by-path --path /swip/prod/ --query 'Parameters[].Name' --profile <TEAM_PROFILE> --region us-east-1` lists all nine.

**Step 3. Template check, Bedrock ARNs, stack.**
```bash
aws cloudformation validate-template --template-body file://infra/aws/ec2-stack.yaml --region us-east-1 --profile <TEAM_PROFILE>
# ARNs: the profile ARN plus the foundation-model ARN in every region it routes to
aws bedrock get-inference-profile --inference-profile-identifier us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --region us-east-1 --profile <TEAM_PROFILE> --query '[inferenceProfileArn, models[].modelArn]' --output text
# (confirm the id equals backend/app/core/llm/registry.py before running)
make infra-up ALERT_EMAIL_1=<EMAIL_1> ALERT_EMAIL_2=<EMAIL_2> DATA_BUCKET=<OUR_BUCKET> BEDROCK_ARNS=<PROFILE_ARN>,<MODEL_ARN_1>,<MODEL_ARN_2>,...
aws cloudformation describe-stacks --stack-name <STACK_NAME> --query 'Stacks[0].Outputs' --region us-east-1 --profile <TEAM_PROFILE>   # InstanceId, PublicIp
```
Set `PUBLIC_HOST` (step 2) to the Elastic IP with dashes + `.sslip.io`.

**Step 4. On the box (SSM Session Manager to `<INSTANCE_ID>`).**
```bash
cd /opt/swip && git checkout main && git pull --ff-only
bash infra/aws/render-env.sh
docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.prod.yml up -d postgres redis
make data      # ingest -> dbt -> load -> seed-identity -> golden -> demo-reset; already applies 0007 on latam_golden
```
`make data` runs the box-side `seed-identity`; the agent never runs it.

**Step 5. Certificate (08 §8).** Staging first, then production, via the compose `certbot` service (HTTP-01 webroot shared with nginx).
```bash
# staging: add --staging, expect success, then remove it
docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.prod.yml run --rm --entrypoint certbot certbot \
  certonly --webroot -w /var/www/certbot -d <EIP_WITH_DASHES>.sslip.io --staging --agree-tos -m <CERT_EMAIL> --non-interactive
# production (only after staging passed; use --force-renewal to replace the staging cert)
docker compose ... run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d <EIP_WITH_DASHES>.sslip.io --agree-tos -m <CERT_EMAIL> --non-interactive --force-renewal
```
If sslip.io is rate-limited: register a cheap domain in Route 53, add an A record to the same Elastic IP, set `PUBLIC_HOST=<DOMAIN>` in SSM, re-issue (cookies are host-only, users log in again). Plain HTTP is not a fallback (Secure cookies).

**Step 6. Deploy and smoke.** On the box: `make deploy` (renders `.env`, builds, `up -d --wait`, applies Alembic head, including `0007_privacy_ledger`, to `latam_app` AND `latam_golden`, then smokes). From a laptop instead: `make deploy-remote INSTANCE_ID=<INSTANCE_ID> DEPLOY_REF=main`. Then:
```bash
export SMOKE_DOC_TYPE=<DOC_TYPE> SMOKE_DOC=<PERSONA_DOC> SMOKE_PASSWORD=<PERSONA_PASSWORD> SMOKE_STAFF_USER=<STAFF_USER> SMOKE_STAFF_PASSWORD=<STAFF_PASSWORD>
make smoke-prod HOST=<EIP_WITH_DASHES>.sslip.io
```

**Step 7. Checks.**
```bash
curl -sI https://<HOST>/ | grep -i strict-transport-security
echo | openssl s_client -connect <HOST>:443 -servername <HOST> 2>/dev/null | openssl x509 -noout -issuer   # production Let's Encrypt, not "(STAGING)"
for p in 22 5432 3000; do nc -z -w3 <ELASTIC_IP> $p && echo "$p OPEN (bad)" || echo "$p closed"; done
# on the box, Bedrock proof (D22): provider bedrock, the registry's us. id, masked input_text
docker compose ... exec postgres psql -U <PG_USER> -d latam_app -c "SELECT provider, model_id, status FROM audit.llm_calls ORDER BY at DESC LIMIT 5"
docker compose ... exec postgres psql -U <PG_USER> -d latam_app -c "SELECT left(input_text, 200) FROM audit.llm_calls ORDER BY at DESC LIMIT 3"
docker compose ... logs backend | grep 'llm.call' | grep 'provider=bedrock' | tail -3
# demo reset and its duration (08 §10)
curl -s -X POST -b <ADMIN_COOKIE_JAR> https://<HOST>/api/v1/admin/demo/reset    # 200, {"status":"reset","duration_ms":...}
```
Also on the public URL: the D3 flows (card status/block, unrecognized charge), the D4 end-of-day steps 2 and 4, and a staff handoff round-trip. Measure first-deploy recovery time (`make infra-up` to smoke green) (08 §13).

#### Checklist (paste the named output back; `/wave-run D5-A-deploy` grades each item)
- [ ] Release PR `develop → main` merged after D5-A (T17–T26) and D5-B landed. Paste: the merge commit SHA on `main`.
- [ ] Data copy verified. Paste: the object count (7671) and the empty `diff src.txt our.txt`.
- [ ] SSM has all nine parameters including `PII_VAULT_KEY`. Paste: the `get-parameters-by-path` name list (names only).
- [ ] `validate-template` and `make infra-up` succeeded. Paste: the stack Outputs (InstanceId, PublicIp) and the `BedrockModelArns` you passed (ARNs only, redact the account id).
- [ ] Data built on the box. Paste: the tail of `make data`.
- [ ] Certificates: staging then production. Paste: the `openssl x509 -noout -issuer` line.
- [ ] `make deploy` applied `0007`. Paste: `SELECT version_num FROM alembic_version` in both `latam_app` and `latam_golden` (expect `0007`).
- [ ] `make smoke-prod` green. Paste: its full output.
- [ ] HSTS present. Paste: the `strict-transport-security` header line.
- [ ] Ports closed. Paste: the three `nc` lines (22, 5432, 3000 all closed).
- [ ] Bedrock proof. Paste: the `SELECT provider, model_id, status FROM audit.llm_calls ... LIMIT 5` rows (`bedrock`, the registry's `us.` id) and one masked `input_text` (tokens like ⟨CARD_1⟩, no raw PAN, name, email or phone).
- [ ] `POST /admin/demo/reset` returns 200 and the customer's changes are gone. Paste: the response body (`duration_ms`) and the before/after row.
- [ ] D3 flows and the `07` §4 checklist items on the public URL. Paste: a pass/fail line per item.
- [ ] Recovery time and demo-reset duration measured. Paste: both numbers.

### T28 — Agent tooling MCP servers in the dev compose stack
Created: `docker/docker-compose.devtools.yml` (mcp-victorialogs, mcp-victoriatraces, mcp-playwright; localhost-only ports 8081/8082/8931; no healthcheck, distroless).
Changed: `Makefile` (dev `COMPOSE` loads devtools; `mcp-setup` now `$(COMPOSE) pull` of the 3 services), `.mcp.json` (3 servers -> http localhost:<port>/mcp), `frontend/vite.config.ts` (`allowedHosts` + "nginx"), `README.md` §7.
Facts the next tasks need: Playwright image entrypoint already has `--headless --browser chromium --no-sandbox`, so compose `command` only adds `--isolated --port 8931 --host 0.0.0.0 --allowed-hosts *`. Agents open the app at `http://nginx/`. Restart Claude Code to load the new `.mcp.json`.
nginx-host proof: throwaway curl on `latam-cs_default` -> `http://nginx/` HTTP=200, "Blocked request" count 0 (Vite HTML served). No port clash on 8081/8082/8931 (ss empty).
Deviations: none. README §3 (`make setup` blurb) still says it pulls "Docker-run" images; unchanged, still accurate enough.
Verify: full Verify command → EXIT=0; stack left down.

### T17 — Suite lint, CannedDriver, A's dev seeds
Created: `eval/harness/lint.py` (`writing_case(case, write_tools)`, `lint_suite(cases, write_tools=None)`, `SuiteLintError.seed_ids`, `load_write_tools`), `eval/harness/canned.py` (`CannedDriver`), `eval/scenarios/dev/a-{card_status-normal_resolution-es-mx,card_block-normal_resolution-es-co,general_question-unsupported-pt-br,human_request-human_required-es-ar}-01.yaml`, `eval/tests/test_lint.py`.
Facts the next tasks need: `lint_suite` reads write tools from `policies/tools.yaml` when `write_tools` is None. Only the card_block seed is writing (persona CLI-5RJITZ5VLJGY, CO, 2 debit cards, so card choice may need a follow-up turn live; `expected_db_state` is `app.card_controls` `{locked: true}` count 1). Whole dev suite (85 cases) lints clean.
Deviations: none. Out of scope: `eval/tests/test_driver.py:109` (B's) fails ruff PIE810.
Verify: test_lint 1 passed; a-* and full-dev lint_suite ok; ruff check/format clean on my files; heldout diff vs origin/develop clean.

### T18 — Case evidence and the deterministic checks
Created: `eval/harness/evidence.py` (`CaseEvidence`, `DbResult`, `collect(conn, case, transcript)`, sync psycopg), `eval/harness/checks.py` (`CheckResult`, one function per D15 check, `outcome`, `unsafe`, `run_checks(ev, write_tools=None)`, `case_verdict(ev, results)`), `eval/tests/test_checks.py`.
Facts the next tasks need: `case_verdict` emits the T14 keys plus `persona` (for `pii_check`); `passed` needs all checks ok AND outcome == expected_outcome; `not_run` reasons `not_runnable`/`db_patches`; `clarification_required` is set only for ambiguous seeds or expected `clarified`, else None. The executor records a write's `tool_call` BEFORE `confirmation_used`, so `confirm_before_act` matches same-turn + same tool, not list order. An unverified write records `tool_result verified=false` and no `readback`; the check then requires a handoff. `no_raw_pii` scans `llm_calls` with generic patterns only (`pii_check.scan(rows, [])`); persona values stay a run-wide `pii_check` job. Turn to audit turn_id map comes from each turn's `done` SSE event. `collect` is untested beyond import and not run against a DB.
Deviations: none.
Verify: `pytest eval/tests/test_checks.py` -> 4 passed; ruff check/format --check clean on the 3 files.

### T29 — goal_decline_explain template
Changed: `templates.py` (`goal_decline_explain` in `TemplateKind` + table, approved text), `nodes/compose.py` (`_GOAL_TEMPLATES` maps `decline_explain`; `kind is None` guard removed), `tests/unit/test_compose.py` (ES/PT fallback test).
Facts the next tasks need: the policy cause labels already end with a period and the approved text adds another (`{decline_cause}.`), so the filled reply reads `...compra.. Puedes`; text left as approved.
Deviations: none.
Verify: `uv run pytest tests/unit/test_compose.py -q` → 5 passed; ruff check/format, mypy clean.

### T30 — Mechanical ruff fixes in B's eval tests
Changed: `eval/tests/test_driver.py` (ruff format + PIE810 fix at line 117: combined two `path.endswith()` calls into one with tuple), `eval/tests/test_scenarios_valid.py` (ruff format only).
Facts the next tasks need: none.
Deviations: none.
Verify: `uv run --project backend ruff check` → All checks passed; `ruff format --check` → 2 files already formatted; `pytest eval/tests/test_driver.py eval/tests/test_scenarios_valid.py -q` → 5 passed.

### T19 — Eval runner, report and `make eval`
Created: `eval/harness/runner.py` (`run(suite, system, driver=None, run_id=None)`), `eval/harness/report.py` (`write_report(out, {system: verdicts}, meta)`), `eval/harness/__main__.py`.
Changed: `Makefile` (`eval` target, SUITE defaults dev, SYSTEM defaults both), `.gitignore` (results.jsonl, llm_calls.jsonl).
Facts the next tasks need: run id `<suite>_<system>_<UTC ts>`; clone `latam_eval_<run_id>_<system>`; Redis DB 1 (proposed) / 2 (baseline); one `results.jsonl` and one `llm_calls.jsonl` per run with a `system` key on each row (same case_ids per system); `pii_check.main` runs inside the runner and its hit count goes to `meta.json` (`pii_hits`; a hit does not raise); needs `GOLDEN_DATABASE_URL`, `DATABASE_URL`, `DEMO_OTP_CODE` (from `.env` via make) and a running Postgres/Redis; `db_patches` cases are recorded `not_run` (reason db_patches) with no HTTP call; a `RestoreDiffError` aborts the run.
Deviations: none. `runner.py` is untested (no live run, no test asked); `report.py` smoke-checked on synthetic verdicts. Groups with only not_run cases show as an `unknown` row in the breakdowns.
Verify: --help ok, `make -n eval`, both check-ignore ok, `pytest eval/tests` (minus B's two files) 12 passed, ruff check/format --check clean on my 3 files.
T29 repair: dropped the '.' after {decline_cause} in goal_decline_explain (ES/PT); test asserts no '..'; verify green (5 passed).

### T24 — Doc updates, part 2
Changed: `docs/solution-docs/06-engineering-rules.md` (§2 langfuse rule, §3 eval/harness + eval/driver, baseline path), `07-execution-plan.md` (A1 "claiming agent's views"; D1 model row: NLU Sonnet 5.5), `08-deployment.md` (§9 `PII_VAULT_KEY` row, §10 step 5 ledger query), `decision-log.md` (ADR-031, 2026-09-29, NLU Sonnet 5.5).
Facts the next tasks need: D5-B's openai text in 06 §2 and ADR-030 kept as is.
Deviations: none.
Verify: task Verify + `grep claude-sonnet-5-5` on 07 and decision-log → pass.

### T33 — Eval runner aborts when the LLM is unreachable
Changed: `eval/harness/runner.py` (`LLMUnreachableError`, pure `llm_unreachable(cases_played, statuses)`, wired in `_play` after each case).
Created: `eval/tests/test_runner_abort.py`.
Facts: "played" counts cases without db_patches; statuses come from the accumulated `evidence.llm_calls` rows (read from the clone). Raised inside `_run_system` try, so `finally` stops uvicorn and drops the clone; no report written.
Deviations: none.
Verify: pytest test_runner_abort → 1 passed; ruff check and format --check clean.

### T32 — R7 amendment and ADR-031 temperature note
Changed: `docs/solution-docs/06-engineering-rules.md` (R7 row: added "where the model accepts one" after temperature), `docs/solution-docs/decision-log.md` (ADR-031: added Temperature note explaining Sonnet 5.5's rejection of temperature parameter).
Facts the next tasks need: R7 now documents that temperature is only pinned where the model accepts it; ADR-031 explains the ledger records NULL and the NLU is less repeatable.
Deviations: none.
Verify: `cd docs/solution-docs && grep -q 'where the model accepts one' 06-engineering-rules.md && grep -q 'deprecated for this model' decision-log.md` → VERIFY PASS.

### T31 — NLU sends no temperature; ledger temperature nullable
Created: `backend/app/alembic/versions/0008_llm_calls_temperature_nullable.py` (upgrade nullable, downgrade backfills 0 then NOT NULL).
Changed: `core/llm/registry.py` (`TEMPERATURE: dict[Step, float | None]`, `nlu: None`), `core/llm/client.py` (`build_chat_model` omits the kwarg for None; `_finish` takes `float | None`), `core/llm/sink.py` (`LLMCallRecord.temperature: float | None`), `tests/unit/test_llm_client.py` (new `test_nlu_sends_no_temperature`; the 0.0 log test now uses step `compose`). `audit/repository.py` needed no change (passes None through).
Facts: ChatAnthropic's request payload has no `temperature` key when unset (checked with `_get_request_payload`). `alembic upgrade head` applied to `latam_app` and `latam_golden` from the host with `.env` URLs; both at `0008`, column nullable.
Live proof FAILED on a different 400: the temperature error is gone, but Sonnet 5.5 answers `invalid_request_error: tool_choice: type "tool" and "any" are not supported for th...` (message truncated in my print). `with_structured_output` forces a tool choice. Escalated, not fixed.
Deviations: none.
Verify: pytest 4 passed; ruff check, format --check, mypy (12 files), lint-imports (4 kept) clean.
T31 repair 1: `StructuredLLMClient` calls `with_structured_output(schema, include_raw=True, method="json_schema")` for provider anthropic (bedrock/openai keep the default path); test stub accepts `method`. Live proof through `get_llm_client()` in the backend container: nlu OK, compose OK, handoff_summary OK. Verify chain passes.

### T25 (second attempt) — First live dev eval: ABORTED, no run_id
Ran: `make eval SUITE=dev SYSTEM=both` (log `/tmp/tmp.sX2JzXc79t/eval.log`). Proposed system replayed; first ~66 llm.calls were `ok` (nlu, compose, handoff_summary), then every call (nlu + one handoff_summary) got Anthropic `400 Bad Request` -> `unavailable`; T33 guard raised `LLMUnreachableError: model None, step None` (runner.py:191, model/step not filled in). No report written, `eval/reports/` empty, no leftover `latam_eval_*` clones.
Facts: 400 body is not logged, cause unknown (candidates: credit/usage limit, or an input-specific request error).
Verify: not run.

### T34 — Provider error text logged on `unavailable`; abort message fixed
Changed: `core/llm/client.py` (`_error_message` helper; `_finish(error=exc)` adds `error_type`, `error_message` to `llm.call` on unavailable only; 300-char truncate, then `app.core.pii.redact`), `tests/unit/test_llm_client.py` (unavailable test asserts the new fields), `eval/harness/runner.py` (`LLMUnreachableError(model_id, step, rows_seen)`).
Facts: ledger columns are `model_id` and `step` (the rows had them); the old `None, None` most likely meant zero ledger rows (`llm_unreachable` is True on `[]`), so the message now also states the row count. Nothing new goes to the ledger/Langfuse.
Deviations: none.
Verify: task Verify -> 4 passed, mypy clean, runner_abort 1 passed, ruff/format clean.
T34 repair 1: `llm_unreachable` aborts only with >=1 row and all unavailable (empty list -> no abort, test updated); `_error_message` now redacts the full text, then cuts to 300. Verify green.

### T35 — Case filter for `make eval`
Changed: `eval/harness/__main__.py` (`--cases PREFIX[,PREFIX...]`, empty selection -> argparse error), `eval/harness/runner.py` (`run(..., cases_filter=)` filters on `seed_id` after `load_dir`, before `lint_suite`; `meta.json` `cases_filter`), `Makefile` (`CASES=` -> `--cases`), `eval/harness/report.py` (header adds ", subset: <prefixes>").
Facts: no clone is made on an empty selection (ValueError raised before `_run_system`).
Deviations: touched `report.py`, not in the task's Files, because the acceptance requires the report header to state the subset.
Verify: full chain passes; `pytest eval/tests` -> 18 passed; ruff check/format clean.

### T25 — smoke run (CASES=a-, proposed only)
Run: `dev_proposed_20260929t174357` (clone 505s; restore_diffs 0; pii_hits 0; clone dropped; heldout clean). Report has report.md, metrics.json, meta.json (+results/llm_calls.jsonl).
Cases: card_status es-MX passed; general_question pt-BR abstained passed; human_request es-AR handoff:atencion passed; card_block es-CO FAILED `error: no_open_confirmation` (turn 2 `confirm: true` with no open confirmation).
LLM calls: nlu 4, compose 2, handoff_summary 1 (all ok, none unavailable). Card-lock made no compose call: consistent with the templated ask-which-card question (CLI-5RJITZ5VLJGY has 2 debit cards); reply text not in artifacts. Human decision applies: add a follow-up turn to the seed (not done here).
Deviations: none. No targets set, `05` untouched.
Verify: smoke run + `make eval-pii-check` -> 0 hits.

### T36 — Card-lock seed picks its card
Changed: `eval/scenarios/dev/a-card_block-normal_resolution-es-co-01.yaml` (turn 2 added: `say: La que termina en 5772, solo un bloqueo temporal, por favor.`; persona and `expected_db_state` unchanged).
Facts: `select` turns only answer a transaction list, so the card choice is free text with the last4 (5772, one of CLI-5RJITZ5VLJGY's 2 debit cards; the other is 0070). `card_block` does not remember `block_kind` across the card question, so the choice turn must also restate the block kind (a first attempt with only the card produced `no_open_confirmation` again, run `dev_proposed_20260929t175524`, deleted).
Smoke: `dev_proposed_20260929t180617` case passed, outcome resolved, 2 nlu ok, restore_diffs 0, pii_hits 0, clone dropped (no `latam_eval%` DB left); report folder deleted. Heldout clean.
Deviations: none.
Verify: dev lint_suite ok + heldout diff clean + smoke passed.
T31 repair 2: `tests/integration/test_privacy_ledger.py` stub `with_structured_output` accepts `method: str | None = None`; test passes.

### T37 — Baseline negated-only intent returns empty list
Changed: `backend/app/domains/conversation/baseline/keyword_nlu.py` (`negated_hit` flag; negated-only with no scope/market hit -> `intents=[]`, `out_of_scope`, topic `other`), `backend/tests/unit/test_baseline.py` (ES + PT negated cases).
Facts the next tasks need: plain no-hit text still returns `general_question` / `clear`.
Deviations: none.
Verify: full T37 Verify -> 11 passed, ruff/format/mypy clean.
T34 repair 2: unavailable-path test now puts a card, email and phone in the error text and asserts they are masked (⟨CARD⟩/⟨EMAIL⟩/⟨PHONE⟩) in `error_message`; client.py unchanged; 4 passed.
T35 repair 1: `report.py` adds the ADR-031 caveat line under the label when any row in the run's `llm_calls.jsonl` has a null temperature (read from the file the runner writes beside the report; signature unchanged). Synthetic check: [0.0] no caveat, [0.0, None] caveat; pytest eval/tests 18 passed; ruff clean.

### Proof run — card-lock seed
Run: `make eval SUITE=dev SYSTEM=proposed CASES=a-card_block` → `run_id=dev_proposed_20260929t190236` (folder kept in `eval/reports/`).
Result: 1/1 passed (outcome resolved), no failed checks, restore diffs 0, PII scan 0 hits (`make eval-pii-check` → 0 hits). NLU temperature caveat line present in report.md. `latam_eval_*` clone dropped.
