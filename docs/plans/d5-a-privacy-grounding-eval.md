# Plan: D5-A — G6b privacy and grounding, G11 eval runner and baseline, deploy runbook

Spec: [`docs/specs/d5-a-privacy-grounding-eval.md`](../specs/d5-a-privacy-grounding-eval.md) · Branch: `feat/d5-a-privacy-grounding-eval`

## Facts checked against the repo

**Base and schema**
- The branch sits on `develop` at `a7ec849`. D4-A and D4-B are merged. The alembic head is `0006` (`0006_claims.py`), so the new migration is `0007_privacy_ledger`, with down revision `0006`.
- `alembic/env.py` reads `get_settings().database_url`. To migrate golden, run `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_golden uv run alembic upgrade head` from `backend/`. The eval clone is copied from `latam_golden`, so golden needs `0007` too.
- The app write tables are:
  - `app.card_controls`, `app.card_status_history`, `app.card_replacements` (migration `0003`)
  - `app.handoffs` (`0005`)
  - `bank.complaints.transaction_id`/`idempotency_key` (`0006`)
- `bank.customers` has `document_number`, `first_name`, `last_name`, `email` and `mobile_phone`. The FakeBank fixture `backend/tests/fixtures/fakebank/customers.csv` has the same columns. For example `CLI-TFMULTI00001` has `DOC-TF0000001`, first name `Prueba`, last name `Uno`.

**Dependencies and tooling**
- `backend/pyproject.toml` has neither `cryptography` nor `langfuse`. On PyPI today: `langfuse` 4.15.6 (SDK 4.x, built on OTel) and `cryptography` 50.0.1.
- `httpx` is in the backend `dev` group, and `pyyaml` and `psycopg[binary,pool]` are main dependencies.
- The root `pyproject.toml` is a separate notebooks env with no ruff or pytest config.
- `make check` covers only `backend/` (`tests/unit`), `pipeline/` and `frontend/`. `eval/tests` runs separately: `uv run --project backend pytest eval/tests` from the repo root (spec D25).
- The eval code imports nothing from `app` (A9): `backend/` isn't on `sys.path` from the repo root.
- `eval/` holds only `personas.yaml` and `nlu/`. `eval/scenarios/schema.py` and `eval/driver/` are Dev B's and are **not on `develop` yet**. `origin/feat/d5-b-decline-explainer-test-sets` so far only has B's spec.
- For `import eval.harness` to work under pytest, both `eval/__init__.py` and `eval/tests/__init__.py` must exist (pytest's prepend mode then puts the repo root on the path). B may add the same empty files, and identical adds merge cleanly.
- The Makefile does `-include .env` + `export`, so `make eval` subprocesses inherit `.env`.
- `make fill-secrets` fills keys with `secrets.token_urlsafe(32)`, which is **not** a valid Fernet key. `PII_VAULT_KEY` needs `base64.urlsafe_b64encode(os.urandom(32))`, i.e. `Fernet.generate_key()` (A4).
- `main._require_secrets` refuses an empty `JWT_SECRET`/`IDENTITY_HMAC_KEY`, and `PII_VAULT_KEY` joins that list (A4). The integration `it_env` fixture (`tests/integration/conftest.py:172`) sets secrets with `monkeypatch.setenv`, so it must set `PII_VAULT_KEY` too.

**Current code the tasks change**
- `core/llm`:
  - `StructuredLLMClient(settings, chat_model_factory=build_chat_model)` loops over attempts 1–2 and logs one `llm.call` per attempt with `outcome ∈ ok|invalid|unavailable`.
  - `trace_llm_call` is a no-op.
  - `LLMSettings` has `langfuse_host`. `get_llm_client(settings=None)` is called once, in `main._lifespan`.
- The unit test stub-factory pattern is `_StubRunnable` in `backend/tests/unit/test_llm_client.py`.
- Integration tests swap `app_client.app.state.turn_host.llm` for a fake (see `test_staff_round_trip.py:212`). `test_privacy_ledger` swaps in a real `StructuredLLMClient` over a stub factory plus the real sink.
- `safety/vault.py`:
  - `AddressVault.put_address(raw) -> str` is **sync**, and `flows/replacement.py:248` calls it that way. `PostgresPiiVault.put_address` buffers and saves on an async `flush()` (A2).
  - The runner and the sandbox both build `InMemoryAddressVault()` (`runner.py:219`, `sandbox.py:223`), and so does `tests/conftest.py:make_session`.
- `runner.start_turn`:
  - It persists the customer text before scheduling `_run_turn`.
  - `_run_turn` publishes the raw typed text on the `relay_to_agent` echo. That echo stays raw (D7).
  - It writes `reply_sent` with `{route, ui_kinds, length}`.
  - It publishes a `debug` SSE event (with `pending = "<flow>.<awaiting_slot>"`) whenever `APP_ENV != prod`, and `eval` isn't `prod`.
- `store.add_message(conversation_id, turn_id, role, content, ui_payload)` never writes `content_masked`. It is called from:
  - `runner.py` (customer and bot)
  - `takeover.py:45` (agent) and `takeover.py:83` (system)
- The two integration tests `test_write_path_api.py:87` and `test_confirmations_route.py:181` poll `SELECT content … FROM app.messages`. With `content` encrypted they must select `content_masked`.
- `staff.py:217` builds the staff transcript from `store.list_messages`, so decrypting in `list_messages` gives staff the raw text (D7).
- Only `graph.run_turn` (sandbox and unit tests) and `runner._run_turn` (API) drive the graph.

**LLM call sites**
- The four nodes that call an LLM are `nodes/understand.py`, `nodes/compose.py`, `nodes/handoff_summary.py`, and `nodes/abstain.py` (through `compose_reply`).
- `compose_reply` today falls back to the `fallback` template when a draft fails a placeholder, brace or digit check.
- `compose` adds `customer_name`, the raw first name read from checkpointed state set by `load_session`. It stays there (A7), and its value is never a fact value.

**Places where code writes values into a reply (human answer 1)**
- `compose`'s placeholder fill (`_format_fact`)
- `flows/actions.fill`
- `nodes/handoff.py:164` (`.format(queue_label, reference)`)
- `flows/unrecognized_charge.py:118` (`.replace("{card_options}", …)`)
- **also** `flows/card_select.py:129` (`.replace` with the masked card options). This site follows the same rule and wasn't in the question's list.
- `nodes/smalltalk.py:79` (the greeting name) is PII and is left out, like `customer_name`.
- `nodes/abstain.py:100` fills `abstain_fallback` with localized labels, and those are recorded too.

**Prompts, graph and tools**
- The only detector-relevant text in the current prompts is `nlu@v4.md:56`, "CPF usado como identificador". So a document match needs at least one digit in the run after the keyword (A1).
- Graph shape: `build_graph(checkpointer)` in `graph.py:367`. `hosting.open_host(database_url, llm)` compiles it, and `main._lifespan` opens the host.
- `BankReadTools` (`tools/bank.py`) has `get_profile`, `list_cards`, `get_card_details`, `search_transactions` and `get_fx_rate`.
- `RecordingBankTools` (`tools/registry.py`) wraps each read with a `tool_call` audit event. `get_pii_profile` goes through it without one (A5).
- Import-linter only allows `tools/postgres.py → customers.service`, so `PostgresBank` implements `get_pii_profile`.
- `policies/tools.yaml` marks every write tool with `requires_confirmation: true`: `cards.lock_card`, `cards.unlock_card`, `cards.block_card`, `cards.order_replacement` and `disputes.create_claim`.

**Eval runtime**
- The clone is made with `CREATE DATABASE … TEMPLATE latam_golden`, which is the same approach as `pipeline/load/demo_reset.py`. On the 7.7 GB golden DB it took 354 s (D4-A T31).
- The clone fails if **any** session is connected to `latam_golden`. The harness closes its golden connections before each clone.

**Langfuse (A6)**
- The server is the current self-hosted stack: web, worker, ClickHouse, MinIO, Redis and Postgres, all under `profiles: [langfuse]` in `docker/docker-compose.observability.yml`.
- Grafana already uses host port `3000`, so the Langfuse web UI needs a different localhost port.
- The SDK 4.x client must export only its own generations and never the app's OTel spans.

**Human answers (2026-09-28), binding on the tasks**
1. `fact_values` records every value code writes into a reply, as one list per turn, without `customer_name`.
2. The baseline also swaps `abstain`'s wording to `abstain_fallback`, so `abstain.py` is in scope.
3. The eval outcome `clarified` comes from the last turn's `debug` SSE event: `pending` ends in `.card_hint` or `.block_kind`, or that turn's `nlu_result.status` is `ambiguous`.
4. `reply_sent.grounding.outcome` is the worst outcome of the turn (`template` > `regenerated` > `ok`), and the key is absent when `compose` didn't run.
5. Agent and system `content_masked` go through the conversation vault with the pattern detectors only (`KnownPii(document_number=None, names=())`).

A1–A9 are accepted as stated.

**Cross-dev**
- B's first PR (`eval/scenarios/schema.py` + the `Transcript`/`TurnRecord` models) gates T17–T19.
- Before T17, the orchestrator merges `origin/develop` into this branch. If B's PR isn't there, the orchestrator asks the human whether to run T20–T22 (A4) first (A8).
- T25 also needs B's `run_case` driver.
- Both cards edit `core/llm/{client,registry}.py`, `.importlinter`, `pyproject.toml`/`uv.lock` and the Makefile. Whichever merges second rebases and keeps both changes (D28).

## Components

| Component | Path | Depends on |
|---|---|---|
| PII detectors + `redact` | `backend/app/core/pii.py` (new) | stdlib only |
| R5 guard, call ledger record/sink, pricing | `backend/app/core/llm/{client,errors,sink,pricing,__init__}.py` | `core.pii` |
| Langfuse generation + mask hook | `backend/app/core/llm/{tracing,settings}.py`, compose `langfuse` profile | `langfuse` SDK, `core.pii.redact` |
| Ledger + vault schema | `backend/app/alembic/versions/0007_privacy_ledger.py` | `0006` |
| `LLMCallSink` implementation | `backend/app/domains/audit/{repository,service,schemas}.py` | `core.llm.sink`, `0007` |
| PII vault + Fernet helpers | `backend/app/domains/safety/vault.py` | `core.pii`, `core.db`, `cryptography`, `PII_VAULT_KEY` |
| Known-PII read | `tools/{bank,fakebank,postgres,registry}.py`, `customers/{repository,service}.py` | `ToolContext` (R1) |
| Masking step | `backend/app/domains/conversation/masking.py` (new), used by `runner.py` and `sandbox.py` | vault, known-PII read |
| Encrypted messages | `backend/app/domains/conversation/{store,takeover}.py` | vault Fernet helpers |
| Turn fact-value collector | `backend/app/domains/conversation/fact_values.py` (new) + the code-fill sites | stdlib `contextvars` |
| Grounding check | `nodes/compose.py`, `templates.py`, `graph.py` (`GraphState.grounding`) | collector, `core.pii` |
| Keyword baseline | `backend/app/domains/conversation/baseline/` (new), `graph.build_graph(system=)`, `nodes/abstain.py`, `hosting.py`, `main.py` | D12 templates |
| Eval harness | `eval/harness/{metrics,pii_check,clone,restore,dbstate,lint,canned,evidence,checks,runner,report,__main__}.py` (new) | B's `eval/scenarios/schema.py`, `eval/driver/` (T17 on) |
| A's dev seeds | `eval/scenarios/dev/a-*.yaml` (new, B's format) | B's schema, `eval/personas.yaml` `split: dev` |

## Build order

1. **T1–T5, the A1 foundations.** Detectors come before the guard (T2 uses them) and the vault (T5). The migration and sink (T3) come before any ledger row. Langfuse (T4) only needs T1 and T2.
2. **T6–T9, the A1 wiring.** Known-PII (T6) comes before masking (T7 sandbox, T8 API). T9 wires the sink and proves the ledger end to end.
3. **T10–T12, A2.** The collector (T10) comes before `compose` (T11), which records its fill into it. The runner (T12) turns both into the `reply_sent` payload. It extends T9's integration test.
4. **T13, the live A1/A2 proof** (criteria 2–3). It comes before the eval work, so the stack the eval runs against is known good.
5. **T14–T16, the A3 parts that don't need Dev B:** metrics, PII scan, clone/restore/db_state.
6. **T17–T19, the A3 parts that need B's contract PR:** lint + canned driver + seeds → evidence + checks → runner + report + `make eval`.
7. **T20–T22, A4.** Keyword NLU → the baseline graph swap → `AGENT_SYSTEM` wiring. T20 and T21 may move ahead of T17 only on the human's say (A8).
8. **T23–T24, docs** (D24). They come after the code, so they cite real names.
9. **T25–T26, the end-of-day items:** first dev run + PII check + proposed targets, then the approved targets go into `05` §6. They need T19 and T22, plus B's driver.
10. **T27, the deploy runbook.** Last by D1/D22.

## Touch map

| File | New / mod | Change |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | mod | `cryptography`, `langfuse` |
| `backend/.importlinter` | mod | `langfuse` forbidden outside `app.core.llm` |
| `backend/app/core/pii.py` | new | `find_pii`, `redact`, `TOKEN_RE`, `KnownPii`, `PiiMatch` |
| `backend/app/core/llm/{client,errors,__init__}.py` | mod | R5 guard, `LLMUnmaskedInput`, one ledger record per attempt, `sink=` |
| `backend/app/core/llm/{sink,pricing}.py` | new | `LLMCallRecord`, `LLMCallSink`, `PRICE_PER_MTOK` |
| `backend/app/core/llm/{tracing,settings}.py` | mod | real Langfuse generation + `mask=redact`, Langfuse keys |
| `backend/app/core/config.py` | mod | `pii_vault_key`, `agent_system` |
| `backend/app/core/logging.py` | mod | `bind_turn_id` |
| `backend/app/alembic/versions/0007_privacy_ledger.py` | new | `app.pii_vault`, `audit.llm_calls` |
| `backend/app/domains/audit/{repository,service,schemas}.py` | mod | `insert_llm_call`, `AuditLLMCallSink` |
| `backend/app/domains/safety/vault.py` | mod | `PiiVault`, `InMemoryPiiVault`, `PostgresPiiVault`, `encrypt_text`/`decrypt_text` |
| `backend/app/domains/customers/{repository,service}.py` | mod | `fetch_known_pii`/`get_known_pii` |
| `backend/app/domains/conversation/tools/{bank,fakebank,postgres,registry}.py` | mod | `get_pii_profile`, `registry.known_pii(ctx)` |
| `backend/app/domains/conversation/masking.py` | new | `mask_user_text` |
| `backend/app/domains/conversation/{runner,store,takeover,sandbox}.py` | mod | masking, encryption, unmask, `reply_sent` payload |
| `backend/app/domains/conversation/fact_values.py` | new | the per-turn collector |
| `backend/app/domains/conversation/flows/{actions,card_select,unrecognized_charge}.py`, `nodes/handoff.py` | mod | record the values code fills in |
| `backend/app/domains/conversation/nodes/compose.py`, `templates.py`, `graph.py` | mod | grounding check, `goal_*` templates, `GraphState.grounding`, `build_graph(system=)` |
| `backend/app/domains/conversation/nodes/abstain.py` | mod | wording step swappable for the baseline (human answer 2) |
| `backend/app/domains/conversation/baseline/{__init__,keyword_nlu,template_compose}.py`, `lexicon.yaml` | new | A4 |
| `backend/app/domains/conversation/hosting.py`, `backend/app/main.py` | mod | `open_host(system=)`, sink wiring, `PII_VAULT_KEY` refusal, `AGENT_SYSTEM` eval-only |
| `backend/tests/unit/test_r5_llm_guard.py`, `test_r5_masking.py`, `test_baseline.py` | new | spec tests |
| `backend/tests/unit/test_compose.py` | mod | 2 spec tests |
| `backend/tests/integration/test_privacy_ledger.py` | new | spec test |
| `backend/tests/integration/{conftest,test_write_path_api,test_confirmations_route}.py` | mod | `PII_VAULT_KEY` in `it_env`; pollers select `content_masked` |
| `eval/__init__.py`, `eval/harness/*.py`, `eval/tests/__init__.py`, `eval/tests/test_{metrics,pii_check,restore,lint,checks}.py` | new | A3 |
| `eval/scenarios/dev/a-*.yaml` | new | 3–5 seeds |
| `eval/reports/<run_id>/{report.md,metrics.json,meta.json}` | new | first dev run |
| `docker/docker-compose.observability.yml` | mod | `langfuse` profile |
| `Makefile` | mod | `fill-secrets` Fernet key, `langfuse-up/down`, `eval`, `eval-pii-check` |
| `.env.example`, `.env.prod.example`, `.gitignore` | mod | keys; `eval/reports/*/{results,llm_calls}.jsonl` |
| `docs/solution-docs/{01,02,03,04,05,06,07,08}` | mod | D24, targets, §8 row |
| `docs/plans/d5-a-privacy-grounding-eval.state.md`, `docs/plans/d4-a-escalation-handoff-deploy.state.md` | mod | runbook, T32/T33 moved, `T-deploy-record` |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| A detector matches a prompt's own text (for example "CPF usado"), so the guard refuses every call | T1: the document run needs a digit (A1). T1's Verify runs `find_pii` over every `prompts/*.md` and requires 0 hits. |
| The ledger insert fails and takes the turn down | T2/T3: sink errors are caught and logged as `llm.ledger_failed` (A3). The call result is unchanged. |
| A refused call leaks the text into the ledger or logs | T2: the refused record has `input_text=None`. The test asserts this, and that the factory is never called. |
| `0007` doesn't downgrade | T3's Verify runs `upgrade → downgrade -1 → upgrade`. |
| Golden lacks `0007`, so the eval clone has no `audit.llm_calls` | T3 migrates golden. T13 and T25 re-check it with `\dt audit.*`. |
| The Langfuse SDK 4.x (OTel) hooks the global tracer and exports the app's spans, which include SQL | T4: Langfuse runs on its own tracer provider, or the SDK is set to export only its own scope. The implementer checks the SDK docs (deepwiki) and records the setting in the state file. |
| Langfuse is heavy on a 15 GiB dev box | T4: an opt-in profile only. `make langfuse-down` after T13's proof. |
| `put_address` is sync but the vault is Postgres | T5/T8: buffer in memory, and the runner awaits `vault.flush()` before `unmask`/`add_message` (A2). |
| `content` encryption breaks existing integration pollers | T9 switches them to `content_masked`. T8 proves the staff transcript still decrypts. |
| Masking tokenizes a full PAN, so `card_select` can't match it | This is accepted (D4). Not tested. |
| The collector's contextvar doesn't reach LangGraph node tasks, so `fact_values` is empty and the eval's `grounding` check fails every template turn | T12 adds an assertion in `test_privacy_ledger` that `reply_sent.fact_values` holds the card mask. |
| B's `decline_explain` adds a `compose` goal with no `goal_*` template | T11: if `develop` has a new `Goal` literal when the task runs, it stops and asks. Otherwise whoever merges second adds the template. |
| B's contract PR is late and blocks A3 | A8 split (T14–T16 first). The orchestrator asks before T17. |
| Clone creation is blocked by an open golden connection, and each clone takes about 6 min | T16: `clone.create` ends golden sessions first (the `demo_reset` pattern). The runner closes golden connections before each clone. The report states the clone time. |
| The clone isn't dropped after a crash | T19: `drop` runs in `finally` (Boundaries). |
| A run leaves restore residue behind | T16's diff aborts the run. `meta.json` reports `restore_diffs: 0`. |
| The baseline still reaches an LLM | T21: abstain wording swapped (human answer 2). The test uses an LLM that raises if called. |
| `AGENT_SYSTEM=baseline` in prod | T22: the lifespan refuses it unless `APP_ENV=eval`. |
| PII in reports or scripts | T15/T19: print only row id + kind. `results.jsonl`/`llm_calls.jsonl` are git-ignored (T19). |
| An agent runs AWS commands | T27 writes text only. Its Verify is lint/parse only. |

## Tests

| Test | Task |
|---|---|
| `backend/tests/unit/test_r5_llm_guard.py::test_raw_card_number_refused` | T2 |
| `backend/tests/unit/test_r5_masking.py::test_langfuse_mask_redacts` | T4 |
| `backend/tests/unit/test_r5_masking.py::test_nlu_sees_only_tokens` | T7 |
| `backend/tests/integration/test_privacy_ledger.py::test_turn_writes_masked_ledger_and_encrypted_messages` | T9 (T12 adds the `reply_sent` assertion) |
| `backend/tests/unit/test_compose.py::test_wrong_amount_regenerated_then_template` | T11 |
| `backend/tests/unit/test_compose.py::test_wrong_language_regenerated` | T11 |
| `eval/tests/test_metrics.py::test_wilson_and_rule_of_three` | T14 |
| `eval/tests/test_pii_check.py::test_planted_document_number_found` | T15 |
| `eval/tests/test_restore.py::test_leftover_row_aborts` | T16 |
| `eval/tests/test_lint.py::test_writer_customer_reused_refused` | T17 |
| `eval/tests/test_checks.py::test_broken_flow_fails_right_check` | T18 |
| `backend/tests/unit/test_baseline.py::test_keyword_nlu_es_pt` | T20 |
| `backend/tests/unit/test_baseline.py::test_baseline_turn_makes_no_llm_call` | T21 |

The R1 signature scan, the R6 graph scan and the R13 route scan are existing tests, run by the verifier's `make check`.

Criteria map:
- 1 → T2, T4, T7, T9, T11, T20, T21
- 2–3 → T13
- 4 → T11
- 5 → T14–T18
- 6–7 → T25
- 8 → T26
- 9 → T1 (contract) + the verifier
- 10 → T23, T24, T27
- 11 → T27
- 12 → post-merge `/wave-run D5-A-deploy`

## Tasks

- [ ] T1: Add `cryptography` + `langfuse`, write `app/core/pii.py`, extend the import-linter contract
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → `app/core/pii.py` and D3; `backend/.importlinter`; `backend/app/domains/conversation/prompts/nlu@v4.md` lines 50-60
  - Acceptance:
    - `uv add cryptography langfuse` in `backend/` (latest: `langfuse` 4.x, `cryptography` 50.x). Record the resolved versions in the state file.
    - `core/pii.py` implements the D3 detectors as regex plus checksum, stdlib only. A document keyword needs a run that holds at least one digit (A1).
    - `TOKEN_RE` tokens never match.
    - `redact` replaces matches with `⟨KIND⟩`.
    - Known-PII matching (document number, first and last names) ignores case and accents and matches whole words.
    - `.importlinter`: `langfuse` joins `llm-sdk-only-in-core-llm`'s forbidden list, with the `app.core.llm`/`app.core.llm.**` ignore lines.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run python -c "from pathlib import Path; from app.core.pii import find_pii, KnownPii; assert all(not find_pii(p.read_text()) for p in Path('app/domains/conversation/prompts').glob('*.md')); k=KnownPii(document_number='DOC-TF0000001', names=('Prueba','Uno')); assert {m.kind for m in find_pii('tarjeta 4111 1111 1111 1111 a@b.co +5215512345678 CPF 123.456.789-09 soy prueba', k)} == {'CARD','EMAIL','PHONE','DOC','NAME'}; assert not find_pii('⟨CARD_1⟩ mi CPF para pagar 1500')" && uv run lint-imports && uv run ruff check app/core/pii.py && uv run ruff format --check app/core/pii.py && uv run mypy app/core/pii.py`
  - Files: `backend/pyproject.toml`, `backend/uv.lock`, `backend/.importlinter`, `backend/app/core/pii.py`

- [ ] T2: R5 guard and per-attempt ledger records in `StructuredLLMClient`
  - Depends on: T1 (`app.core.pii.find_pii`)
  - Read exactly these: spec D8, D9, D28 and §"Contracts" → `app/core/llm/`; `backend/app/core/llm/client.py`; `backend/tests/unit/test_llm_client.py` (the `_StubRunnable`/stub-factory pattern)
  - Acceptance:
    - `errors.LLMUnmaskedInput(LLMError)`.
    - `sink.py` holds `LLMCallRecord` (the spec fields) and the `LLMCallSink` protocol.
    - `pricing.py` holds `PRICE_PER_MTOK`, USD per million input/output tokens per model id, with an as-of date comment. Confirm the Haiku 4.5 price with the `claude-api` skill. An unknown id (for example `gpt-6-luna`) gives `cost_usd=None`.
    - `StructuredLLMClient(settings, chat_model_factory=..., sink=None)`. Before building the chat model, a `find_pii(system + "\n" + user)` hit logs, records `status="refused", input_text=None` and raises `LLMUnmaskedInput`. The factory is never called.
    - Every attempt records `ok|invalid|unavailable` with the masked `user` as `input_text`, `output_json` on `ok`, and tokens from the raw message's `usage_metadata` when present.
    - `conversation_id`/`turn_id` come from structlog contextvars (null when unbound).
    - A sink exception is caught and logged as `llm.ledger_failed` (A3).
    - The `llm.call` log line stays.
    - `get_llm_client(settings=None, sink=None)`.
    - The `status` vocabulary matches the `0007` CHECK constraint: `ok`, `invalid`, `unavailable`, `refused`.
    - Test `backend/tests/unit/test_r5_llm_guard.py::test_raw_card_number_refused`, using a stub factory that fails if called.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_r5_llm_guard.py tests/unit/test_llm_client.py -q && uv run ruff check app/core/llm tests/unit/test_r5_llm_guard.py && uv run ruff format --check app/core/llm tests/unit/test_r5_llm_guard.py && uv run mypy app/core/llm && uv run lint-imports`
  - Files: `backend/app/core/llm/client.py`, `backend/app/core/llm/errors.py`, `backend/app/core/llm/sink.py`, `backend/app/core/llm/pricing.py`, `backend/app/core/llm/__init__.py`, `backend/tests/unit/test_r5_llm_guard.py`

- [ ] T3: Migration `0007_privacy_ledger` and the audit-domain `LLMCallSink`
  - Depends on: T2 (`LLMCallRecord`, `LLMCallSink` in `app.core.llm.sink`)
  - Read exactly these: spec §"Contracts" → "Migration `0007_privacy_ledger`"; `backend/app/alembic/versions/0006_claims.py`; `backend/app/domains/audit/repository.py`
  - Acceptance:
    - `0007` (down `0006`) creates `app.pii_vault` and `audit.llm_calls` exactly as the spec's contract, with the `(conversation_id, at)` index. The downgrade drops both.
    - `audit.repository.insert_llm_call(record)` is insert-only, binding `output_json` as JSONB.
    - `audit.service.AuditLLMCallSink` implements `LLMCallSink` (`id=uuid4()`, `at=now(UTC)`).
    - No `app.core` module imports the audit domain, so the layers contract stays kept.
    - Both `latam_app` and `latam_golden` are at head.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_golden uv run alembic upgrade head && uv run lint-imports && uv run ruff check app/domains/audit app/alembic/versions/0007_privacy_ledger.py && uv run ruff format --check app/domains/audit app/alembic/versions/0007_privacy_ledger.py && uv run mypy app/domains/audit` (needs `make up`)
  - Files: `backend/app/alembic/versions/0007_privacy_ledger.py`, `backend/app/domains/audit/repository.py`, `backend/app/domains/audit/service.py`, `backend/app/domains/audit/schemas.py`

- [ ] T4: Self-hosted Langfuse: a real generation span with the `redact` mask hook, the compose profile and make targets
  - Depends on: T1 (`core.pii.redact`, `langfuse` installed), T2 (`client.py` calls `trace_llm_call` per attempt and records `langfuse_trace_id`)
  - Read exactly these: spec D10 and success criterion 3; `backend/app/core/llm/tracing.py`; `docker/docker-compose.observability.yml`
  - Acceptance:
    - `LLMSettings` gains `langfuse_public_key`/`langfuse_secret_key` (`SecretStr | None`).
    - `trace_llm_call` stays a no-op without `langfuse_host`. With it, it opens a Langfuse generation (model, prompt version, step, masked input) on a client built with `mask=` a function applying `core.pii.redact` to every string, and yields the trace id for the ledger.
    - The SDK exports only its own spans, never the app's OTel spans. Record the setting used in the state file.
    - The `langfuse` services from Langfuse's official self-host compose (current v3 line) go under `profiles: [langfuse]`, with localhost-only ports and a web port other than `3000`. `make up` doesn't start them.
    - `make langfuse-up`/`langfuse-down`.
    - `.env.example` gets commented `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`.
    - Test `backend/tests/unit/test_r5_masking.py::test_langfuse_mask_redacts` (new file). It calls the mask function directly and makes no network call.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.observability.yml --profile langfuse config -q && make -n langfuse-up langfuse-down >/dev/null && cd backend && uv run pytest tests/unit/test_r5_masking.py -q && uv run ruff check app/core/llm tests/unit/test_r5_masking.py && uv run ruff format --check app/core/llm tests/unit/test_r5_masking.py && uv run mypy app/core/llm && uv run lint-imports`
  - Files: `backend/app/core/llm/tracing.py`, `backend/app/core/llm/settings.py`, `docker/docker-compose.observability.yml`, `Makefile`, `.env.example`, `backend/tests/unit/test_r5_masking.py`

- [ ] T5: Settings, the Fernet PII vault (in-memory and Postgres) and the `PII_VAULT_KEY` secret
  - Depends on: T1 (`KnownPii`, `find_pii`, `TOKEN_RE`), T3 (`app.pii_vault` table)
  - Read exactly these: spec D5, D21 and §"Contracts" → `app/domains/safety/vault.py`; `backend/app/domains/safety/vault.py`; the `fill-secrets` target in `Makefile`
  - Acceptance:
    - `Settings` gains `pii_vault_key: str = ""` and `agent_system: Literal["proposed","baseline"] = "proposed"`.
    - `vault.py`:
      - `PiiVault(AddressVault, Protocol)` with async `mask(text, known)`/`unmask(text)`, plus async `flush()`.
      - `encrypt_text`/`decrypt_text` helpers over `Fernet(settings.pii_vault_key)`.
      - `InMemoryPiiVault` (sandbox and tests).
      - `PostgresPiiVault(conversation_id)`: rows `(conversation_id, token, kind, value_enc)`. The same raw value gets the same token (decrypt-compare within the conversation). Tokens are numbered `⟨KIND_n⟩` per conversation and kind, continuing from existing rows.
      - `put_address` stays sync. It buffers `⟨ADDR_n⟩`, and `flush()` persists (A2).
      - `unmask` resolves nested tokens (an `ADDR` value that holds `⟨NAME_1⟩`).
    - The module still never imports `app.domains.conversation`.
    - `make fill-secrets` generates `PII_VAULT_KEY` as a Fernet key (`base64.urlsafe_b64encode(os.urandom(32))`), not with `token_urlsafe`.
    - `.env.example` gets `PII_VAULT_KEY=` with a comment.
    - `it_env` sets `PII_VAULT_KEY` to `Fernet.generate_key().decode()`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run python -c "import asyncio; from app.core.pii import KnownPii; from app.domains.safety.vault import InMemoryPiiVault; v=InMemoryPiiVault(); k=KnownPii(document_number=None, names=('Prueba',)); m=asyncio.run(v.mask('soy Prueba, a@b.co y a@b.co', k)); assert 'Prueba' not in m and m.count('⟨EMAIL_1⟩')==2, m; r=v.put_address(m); assert asyncio.run(v.unmask(r))=='soy Prueba, a@b.co y a@b.co'" && uv run pytest tests/integration/test_auth.py -q && uv run ruff check app/core/config.py app/domains/safety tests/integration/conftest.py && uv run ruff format --check app/core/config.py app/domains/safety tests/integration/conftest.py && uv run mypy app/domains/safety app/core/config.py && cd .. && make -n fill-secrets >/dev/null` (`test_auth.py` proves `it_env` still boots; needs `make up`)
  - Files: `backend/app/core/config.py`, `backend/app/domains/safety/vault.py`, `Makefile`, `.env.example`, `backend/tests/integration/conftest.py`

- [ ] T6: `get_pii_profile()` on the session-scoped read tools (R1)
  - Depends on: T1 (`KnownPii`)
  - Read exactly these: spec §"Contracts" → "The tool registry gains `get_pii_profile()`" and D3; `backend/app/domains/conversation/tools/bank.py`; `backend/app/domains/customers/service.py`
  - Acceptance:
    - `BankReadTools.get_pii_profile() -> KnownPii` has no `customer_id` parameter.
    - `customers.repository.fetch_known_pii(customer_id)` + `customers.service.get_known_pii(customer_id)` read `document_number`, `first_name`, `last_name`.
    - `PostgresBank` implements it through `customers.service`. `FakeBank` implements it from `customers.csv`, filtered by `self._ctx.customer_id`.
    - `RecordingBankTools.get_pii_profile` passes through with no `tool_call` audit event and no `.calls` entry (A5).
    - `registry.known_pii(ctx) -> KnownPii` builds the BANK-selected read tools for `ctx` and returns their profile. It is for the runner's masking step.
    - No LLM node can reach it: node signatures are unchanged.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_r1_customer_scope.py tests/unit/test_r1_fakebank.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run lint-imports && uv run ruff check app/domains/conversation/tools app/domains/customers && uv run ruff format --check app/domains/conversation/tools app/domains/customers && uv run mypy app/domains/conversation/tools app/domains/customers`
  - Files: `backend/app/domains/conversation/tools/bank.py`, `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/conversation/tools/postgres.py`, `backend/app/domains/conversation/tools/registry.py`, `backend/app/domains/customers/repository.py`, `backend/app/domains/customers/service.py`

- [ ] T7: The masking step and the sandbox path, with the R5 NLU test
  - Depends on: T5 (`InMemoryPiiVault`, `PiiVault`), T6 (`BankReadTools.get_pii_profile`)
  - Read exactly these: spec D4 and the `test_nlu_sees_only_tokens` row of §"Test list"; `backend/app/domains/conversation/sandbox.py` lines 180-260; `backend/tests/conftest.py` lines 40-220 (`ScriptedLLM`, `make_session`)
  - Acceptance:
    - New `conversation/masking.py` exports `async def mask_user_text(text: str, *, bank_tools: BankReadTools, vault: PiiVault) -> str`. It masks once with the session customer's `KnownPii`.
    - The sandbox builds an `InMemoryPiiVault`, masks every typed line with `mask_user_text` before `run_turn`, and unmasks the reply before printing. Slash commands aren't masked.
    - Test `backend/tests/unit/test_r5_masking.py::test_nlu_sees_only_tokens`. It uses `make_session` over the FakeBank fixture for `CLI-TFMULTI00001`, with an `InMemoryPiiVault` placed in `config["configurable"]["vault"]`. It runs one turn with a PAN, an email, a phone, `DOC-TF0000001` and `Prueba` through `mask_user_text` + `run_turn`. It asserts:
      - every `ScriptedLLM` call's `user` has no raw value and holds `⟨…⟩` tokens;
      - the checkpointed `user_text` (`graph.aget_state`) also holds tokens only.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_r5_masking.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/masking.py app/domains/conversation/sandbox.py tests/unit/test_r5_masking.py && uv run ruff format --check app/domains/conversation/masking.py app/domains/conversation/sandbox.py tests/unit/test_r5_masking.py && uv run mypy app/domains/conversation/masking.py app/domains/conversation/sandbox.py`
  - Files: `backend/app/domains/conversation/masking.py`, `backend/app/domains/conversation/sandbox.py`, `backend/tests/unit/test_r5_masking.py`

- [ ] T8: The API path: masking in `start_turn`, encrypted `app.messages`, unmasked replies, masked agent and system messages
  - Depends on: T5 (`PostgresPiiVault`, `encrypt_text`/`decrypt_text`), T6 (`registry.known_pii`), T7 (`masking.mask_user_text`)
  - Read exactly these: spec D4, D6, D7 and D9 (the `turn_id` binding); `backend/app/domains/conversation/runner.py`; `backend/app/domains/conversation/store.py`
  - Acceptance:
    - `start_turn` builds the `ToolContext` through `registry.build_tool_context`, then masks the typed text once with a `PostgresPiiVault(conversation_id)`. It persists the customer message with `content=raw` (encrypted) and `content_masked=masked`, and passes the **masked** text to `_run_turn` as graph input. The raw text is kept only for the `relay_to_agent` echo (D7).
    - `_run_turn`:
      - binds `turn_id` with a new `core.logging.bind_turn_id`, next to `conversation_id`;
      - puts the same vault in `config["configurable"]["vault"]`;
      - after the graph, awaits `vault.flush()`, then `unmask`s the reply;
      - stores the bot message with `content=unmasked` (encrypted) and `content_masked=reply before unmask`;
      - publishes the unmasked reply.
    - `store.add_message` gains a required `content_masked`, encrypts `content` with `encrypt_text`, and `list_messages` decrypts.
    - `takeover.py`: agent and system messages get `content_masked` from the conversation vault with `KnownPii(document_number=None, names=())` (human answer 5).
    - No log line carries text.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/integration/test_staff_round_trip.py -q && uv run ruff check app/domains/conversation/runner.py app/domains/conversation/store.py app/domains/conversation/takeover.py app/core/logging.py && uv run ruff format --check app/domains/conversation/runner.py app/domains/conversation/store.py app/domains/conversation/takeover.py app/core/logging.py && uv run mypy app/domains/conversation/runner.py app/domains/conversation/store.py app/domains/conversation/takeover.py app/core/logging.py && uv run lint-imports` (needs `make up`. The staff round trip proves that encrypt, decrypt and the staff transcript still show the raw text.)
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/domains/conversation/store.py`, `backend/app/domains/conversation/takeover.py`, `backend/app/core/logging.py`

- [ ] T9: Wire the ledger sink into the app, refuse an empty `PII_VAULT_KEY`, and prove it end to end
  - Depends on: T2 (`get_llm_client(sink=)`, `StructuredLLMClient`), T3 (`AuditLLMCallSink`), T8 (encrypted messages, `content_masked`)
  - Read exactly these: the spec's `test_privacy_ledger` row in §"Test list", plus D6, D7 and D9; `backend/app/main.py` (`_require_secrets`, `_lifespan`); `backend/tests/integration/test_staff_round_trip.py` lines 190-240 (the fake-LLM swap pattern)
  - Acceptance:
    - `_lifespan` calls `get_llm_client(sink=AuditLLMCallSink())`.
    - `_require_secrets` also refuses an empty `PII_VAULT_KEY`, naming only the variable.
    - The pollers in `test_write_path_api.py` and `test_confirmations_route.py` select `content_masked` instead of `content`.
    - New `backend/tests/integration/test_privacy_ledger.py::test_turn_writes_masked_ledger_and_encrypted_messages`:
      - It swaps `turn_host.llm` for a `StructuredLLMClient` over a stub chat-model factory (NLU and compose outputs, `usage_metadata` set), with `AuditLLMCallSink`.
      - One turn is posted with a PAN.
      - The asserts:
        - one `audit.llm_calls` row per call, with `model_id`, `prompt_version`, tokens, `cost_usd`, `latency_ms`, and an `input_text` holding `⟨CARD_1⟩` and not the PAN;
        - `app.messages.content` for the customer message isn't the plaintext, and `content_masked` holds the token;
        - `PostgresPiiVault.unmask` restores the PAN;
        - the claiming staff transcript (`GET /staff/conversations/{id}/messages`, as in `test_staff_round_trip`) shows the raw text.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/integration/test_privacy_ledger.py tests/integration/test_write_path_api.py tests/integration/test_confirmations_route.py -q && uv run ruff check app/main.py tests/integration && uv run ruff format --check app/main.py tests/integration && uv run mypy app/main.py` (needs `make up`)
  - Files: `backend/app/main.py`, `backend/tests/integration/test_privacy_ledger.py`, `backend/tests/integration/test_write_path_api.py`, `backend/tests/integration/test_confirmations_route.py`

- [ ] T10: A per-turn collector for every value code writes into a reply
  - Depends on: nothing from earlier tasks
  - Read exactly these: the "Facts checked against the repo" bullets on the places where code writes values into a reply (human answer 1); `backend/app/domains/conversation/flows/actions.py` lines 55-75; `backend/app/domains/conversation/nodes/handoff.py` lines 150-170
  - Acceptance:
    - New `conversation/fact_values.py` provides:
      - a `ContextVar[list[str] | None]`;
      - `collecting()`, a context manager that yields the list;
      - `record(*values: str)`, a no-op outside `collecting()`.
    - `record` is called with the substituted values at:
      - `flows/actions.fill` (every value passed in);
      - `nodes/handoff.py:164` (`queue_label`, `reference`);
      - `flows/unrecognized_charge.py:118` and `flows/card_select.py:129` (`card_options`);
      - `nodes/abstain.py:100` (its four labels). This single `abstain.py` edit is part of this task.
    - `nodes/smalltalk.py`'s greeting name is **not** recorded.
    - The flows' behaviour is unchanged.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && printf '%s\n' 'from app.domains.conversation.fact_values import collecting' 'from app.domains.conversation.flows.actions import fill' 'with collecting() as v:' '    fill("{a} {b}", a="**** 6475", b="MXN 1.500,00")' 'assert v == ["**** 6475", "MXN 1.500,00"], v' | uv run python - && uv run pytest tests/unit/test_block_flows.py tests/unit/test_dispute_flows.py tests/unit/test_card_select.py tests/unit/test_handoff_packet.py tests/unit/test_abstain.py -q && uv run ruff check app/domains/conversation && uv run ruff format --check app/domains/conversation && uv run mypy app/domains/conversation/fact_values.py app/domains/conversation/flows app/domains/conversation/nodes/handoff.py app/domains/conversation/nodes/abstain.py`
  - Files: `backend/app/domains/conversation/fact_values.py`, `backend/app/domains/conversation/flows/actions.py`, `backend/app/domains/conversation/flows/card_select.py`, `backend/app/domains/conversation/flows/unrecognized_charge.py`, `backend/app/domains/conversation/nodes/handoff.py`, `backend/app/domains/conversation/nodes/abstain.py`

- [ ] T11: The grounding check in `compose`: one regeneration, then the per-goal fact template
  - Depends on: T1 (`core.pii.find_pii`), T10 (`fact_values.record`)
  - Read exactly these: spec D11 and D12, and the two `test_compose.py` rows in §"Test list"; `backend/app/domains/conversation/nodes/compose.py`; `backend/tests/unit/test_compose.py`
  - Acceptance:
    - **Before starting:** if `develop` added a `compose` `Goal` literal (for example B's `decline_explain`) with no `goal_*` template, stop and escalate.
    - `compose_reply` checks the draft in D11's order:
      1. placeholders only from the offered keys;
      2. no stray braces;
      3. no digit outside a placeholder;
      4. no `find_pii` hit;
      5. the draft's language equals the turn's `language`, judged by an ES/PT stopword heuristic in code (drafts too short to judge pass).
    - On the first failure it calls the LLM once more, adding the failure reason to the user message. It stays on `compose@v5` unless a prompt change is unavoidable; if one is, escalate first.
    - On a second failure it fills the goal's template from `templates.py`: new `goal_card_status` and `goal_balance_due` (ES and PT, no digits). `abstain` uses `abstain_fallback`.
    - `LLMError` still gives `fallback`.
    - Every filled value except `customer_name` goes to `fact_values.record`.
    - `compose` returns `grounding: "ok"|"regenerated"|"template"` in its update. `GraphState` declares `grounding: NotRequired[str]` as a graph-local channel.
    - Tests:
      - `test_wrong_amount_regenerated_then_template`: two drafts carrying a raw amount give exactly 2 compose calls, the reply equals `goal_balance_due` filled from the facts, the injected amount is absent, and the outcome is `template`.
      - `test_wrong_language_regenerated`: an ES draft, then a PT draft, on a PT turn. The PT draft is sent with outcome `regenerated`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_compose.py tests/unit/test_card_info_flows.py tests/unit/test_abstain.py -q && uv run ruff check app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py app/domains/conversation/graph.py tests/unit/test_compose.py && uv run ruff format --check app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py app/domains/conversation/graph.py tests/unit/test_compose.py && uv run mypy app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py app/domains/conversation/graph.py`
  - Files: `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/templates.py`, `backend/app/domains/conversation/graph.py`, `backend/tests/unit/test_compose.py`

- [ ] T12: The `reply_sent` payload gets `grounding` (worst of the turn) and `fact_values`
  - Depends on: T8 (runner masking and unmask), T9 (`test_privacy_ledger.py` exists), T10 (`fact_values.collecting`), T11 (`compose` emits `grounding`)
  - Read exactly these: spec §"Contracts" → "Audit `reply_sent` payload" and D11; `backend/app/domains/conversation/runner.py` (the `_run_turn` astream loop and the `_record("reply_sent", …)` call); `backend/tests/integration/test_privacy_ledger.py`
  - Acceptance:
    - `_run_turn` runs the graph inside `fact_values.collecting()`.
    - `reply_sent.payload` adds `fact_values` (the collected list, deduplicated in order, with no raw PII).
    - It also adds `grounding: {outcome}`, where outcome is the worst `grounding` seen in this turn's `compose` updates (`template` > `regenerated` > `ok`). The key is absent when `compose` didn't run (human answer 4).
    - `test_privacy_ledger`'s test gains one assertion: the turn's `reply_sent` event carries a `fact_values` entry holding the card mask's last 4 digits, and a `grounding.outcome`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/integration/test_privacy_ledger.py -q && uv run ruff check app/domains/conversation/runner.py tests/integration/test_privacy_ledger.py && uv run ruff format --check app/domains/conversation/runner.py tests/integration/test_privacy_ledger.py && uv run mypy app/domains/conversation/runner.py` (needs `make up`)
  - Files: `backend/app/domains/conversation/runner.py`, `backend/tests/integration/test_privacy_ledger.py`

- [ ] T13: Live A1/A2 proof on the dev stack (criteria 2 and 3)
  - Depends on: T4 (Langfuse profile), T9 (sink wired), T12 (runner complete)
  - Read exactly these: spec success criteria 2 and 3; `README.md` (running `make up`, `make chat-api`); `backend/app/core/llm/tracing.py`
  - Acceptance:
    - `make fill-secrets` has set `PII_VAULT_KEY`.
    - `make up` rebuilds with the new dependencies.
    - Both `latam_app` and `latam_golden` are at `0007`.
    - With a real provider, `make chat-api PERSONA=<a persona from eval/personas.yaml>` gets "mi tarjeta 4111 1111 1111 1111 está bloqueada?". Then:
      - `SELECT input_text FROM audit.llm_calls ORDER BY at DESC LIMIT 3` shows `⟨CARD_1⟩` and no `4111`;
      - `SELECT content_masked FROM app.messages ORDER BY created_at DESC LIMIT 2` shows the token;
      - `content` isn't readable text.
    - `make langfuse-up`, set `LANGFUSE_HOST`/keys, restart the backend, send one chat turn. The Langfuse API or UI shows the generation with model, prompt version and masked input. Paste the output into the task log, then `make langfuse-down`.
    - No code change is expected. A fix needed here is escalated, not improvised.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && docker compose --env-file .env -f docker/docker-compose.base.yml exec -T postgres psql -U postgres -d latam_app -Atc "SELECT count(*) FROM audit.llm_calls WHERE input_text LIKE '%4111%'" | grep -qx 0 && docker compose --env-file .env -f docker/docker-compose.base.yml exec -T postgres psql -U postgres -d latam_app -Atc "SELECT count(*) FROM audit.llm_calls WHERE input_text LIKE '%⟨CARD_%'" | grep -vqx 0 && docker compose --env-file .env -f docker/docker-compose.base.yml exec -T postgres psql -U postgres -d latam_golden -Atc "SELECT version_num FROM alembic_version" | grep -qx 0007`. Paste the SQL and Langfuse outputs into the task log.
  - Files: none (evidence in the state file's task log)

- [ ] T14: The eval package skeleton and metrics (Wilson CI, rule of three, percentiles)
  - Depends on: nothing from earlier tasks
  - Read exactly these: spec D16 and D25; `docs/solution-docs/05-evaluation-plan.md` §6
  - Acceptance:
    - `eval/__init__.py` and `eval/tests/__init__.py` exist (empty), so pytest imports `eval.*` from the repo root.
    - `eval/harness/__init__.py` exists.
    - `eval/harness/metrics.py` holds pure functions:
      - `wilson(k, n, z=1.96) -> (low, high)`;
      - `rule_of_three(n)` = `3/n`;
      - a `Rate{k, n, value, ci}` model, with n=0 reported as "not defined";
      - `percentiles(values, (50, 95))`;
      - the D16 metric set computed from a list of per-case verdict dicts, grouped by `language_variant` and segment.
    - "Not run" cases are left out of every denominator.
    - Nothing imports `app` (A9).
    - Test `eval/tests/test_metrics.py::test_wilson_and_rule_of_three`: 8/10 gives the known Wilson bounds, and 0/n has upper bound 3/n.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_metrics.py -q && uv run --project backend ruff check eval/harness eval/tests && uv run --project backend ruff format --check eval/harness eval/tests`
  - Files: `eval/__init__.py`, `eval/tests/__init__.py`, `eval/harness/__init__.py`, `eval/harness/metrics.py`, `eval/tests/test_metrics.py`

- [ ] T15: The PII scan over a run's LLM-call export (`make eval-pii-check`)
  - Depends on: T14 (`eval/harness/` package)
  - Read exactly these: spec D20 and the `test_pii_check` row in §"Test list"; `eval/personas.yaml` (header comment: which columns are PII)
  - Acceptance:
    - `eval/harness/pii_check.py` provides a pure `scan(rows, personas_pii) -> list[Hit(row_id, kind)]`. It looks for:
      - each persona's raw `document_number`, `email`, `phone` and first and last names (case- and accent-insensitive, whole word);
      - an independent card-number (Luhn), email and phone regex that does **not** import `app.core.pii`.
    - The CLI `python -m eval.harness.pii_check --run <run_id>`:
      - reads `eval/reports/<run_id>/llm_calls.jsonl` and the run's persona ids from `results.jsonl`;
      - loads those personas' PII from `latam_golden` with psycopg (DSN from `GOLDEN_DATABASE_URL`, `+asyncpg` stripped);
      - prints only `row_id kind` per hit and a final `<n> hits` line;
      - exits 1 on any hit.
    - `make eval-pii-check RUN=<run_id>` is added.
    - Test `eval/tests/test_pii_check.py::test_planted_document_number_found`: a row holding a persona's document number gives exit/hit != 0, and the value is absent from the captured output.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_pii_check.py -q && uv run --project backend ruff check eval/harness eval/tests && uv run --project backend ruff format --check eval/harness eval/tests && make -n eval-pii-check RUN=x >/dev/null`
  - Files: `eval/harness/pii_check.py`, `eval/tests/test_pii_check.py`, `Makefile`

- [ ] T16: Clone lifecycle, per-persona restore and diff, and the `expected_db_state` compiler
  - Depends on: T14 (`eval/harness/` package)
  - Read exactly these: spec D13 (steps 1 and 8), D14 and D15 (the `db_state` bullet); `pipeline/load/demo_reset.py`; `backend/app/alembic/versions/0003_card_writes.py` (the app write tables' keys)
  - Acceptance:
    - `clone.py`: `create(run_id) -> (dbname, seconds)` ends `latam_golden` sessions, then runs `CREATE DATABASE latam_eval_<run_id> TEMPLATE latam_golden`. `drop(dbname)` is idempotent.
    - `restore.py`:
      - `RESTORE_TABLES` as D14;
      - `restore_persona(clone, golden, customer_id)` resets the persona's `bank.products` rows to their golden values and deletes app-created rows (`app.card_status_history`, `app.card_controls`, `app.card_replacements`, `bank.complaints` with `origin='app'`, `app.handoffs` for the persona's conversations);
      - a pure `diff_rows(table, golden_rows, clone_rows)` that raises `RestoreDiffError(table, key)`;
      - `verify_persona` runs the diff over every table in `RESTORE_TABLES`.
    - `dbstate.py`: `DB_ALLOWLIST` as D15. `compile_item(item: Mapping, customer_id, conversation_id) -> (sql, params)` handles:
      - `where` → parameterized equality;
      - `$persona.customer_id` as the only interpolation;
      - `expect` → a `SELECT` of the named columns, and `count` → `SELECT count(*)`;
      - automatic `conversation_id = %s` on `app.*` tables that have that column;
      - an unknown table or column raises `DbStateLoadError`.
    - No PII is printed.
    - Test `eval/tests/test_restore.py::test_leftover_row_aborts`: `diff_rows` over golden rows plus clone rows with one extra `app.card_controls` row raises, naming the table and key.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_restore.py -q && uv run --project backend python -c "from eval.harness.dbstate import compile_item; print(compile_item({'table':'bank.products','where':{'product_id':'P1','customer_id':'\$persona.customer_id'},'expect':{'product_status':'Blocked'}}, 'CLI-X', None))" && uv run --project backend ruff check eval/harness eval/tests && uv run --project backend ruff format --check eval/harness eval/tests`
  - Files: `eval/harness/clone.py`, `eval/harness/restore.py`, `eval/harness/dbstate.py`, `eval/tests/test_restore.py`

- [ ] T17: The suite lint, the `CannedDriver` and A's dev seeds (needs B's contract PR)
  - Depends on: B's `eval/scenarios/schema.py` (`SeedFile`, `Case`, `load_dir`) and the `Transcript`/`TurnRecord` models, merged from `origin/develop` into this branch. **If they are missing, stop and report.** Also T14 (`eval/harness/`).
  - Read exactly these: spec D2, D14 (Lint) and D26; `eval/scenarios/schema.py` and the module under `eval/driver/` that defines `Transcript` (B's, read-only); `eval/personas.yaml`
  - Acceptance:
    - `lint.py`: `writing_case(case, write_tools)`. The write tools come from `policies/tools.yaml` (`requires_confirmation: true`), read with pyyaml. A case is writing by `labels.required_tools` or a non-empty `labels.expected_db_state`. `lint_suite(cases)` raises `SuiteLintError(seed_ids)` when two different `seed_id`s share a writing persona.
    - `canned.py`: `CannedDriver(transcripts: dict[case_id, Transcript])` with `async run_case(case, **_)`, for tests only.
    - 3–5 seeds `eval/scenarios/dev/a-*.yaml` in B's exact format:
      - file stem = `seed_id`; personas with `split: dev`; no two writing seeds share a persona;
      - covering at least a `card_status` read (ES-MX), a `card_block` lock with a `confirm` turn (ES-CO), a Pix abstention (PT-BR), and a human request → `handoff:atencion` (ES-AR);
      - team-written text only, with no PII.
    - Test `eval/tests/test_lint.py::test_writer_customer_reused_refused`: two seeds sharing a persona, one writing, are refused with both ids. A writing seed whose own paraphrases share its persona is accepted.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_lint.py -q && uv run --project backend python -c "from pathlib import Path; from eval.scenarios.schema import load_dir; from eval.harness.lint import lint_suite; c=[x for x in load_dir(Path('eval/scenarios/dev')) if x.seed_id.startswith('a-')]; assert len({x.seed_id for x in c})>=3; lint_suite(c)" && uv run --project backend ruff check eval/harness eval/tests && uv run --project backend ruff format --check eval/harness eval/tests && git diff --quiet develop -- eval/scenarios/heldout`
  - Files: `eval/harness/lint.py`, `eval/harness/canned.py`, `eval/scenarios/dev/a-*.yaml`, `eval/tests/test_lint.py`

- [ ] T18: Case evidence and the deterministic checks
  - Depends on: T16 (`dbstate.compile_item`), T17 (B's `Case`/`Transcript` importable, `lint.writing_case`)
  - Read exactly these: spec D15 and §"Contracts" → "Eval contracts" (`CaseEvidence`, `DbResult`, `CheckResult`); `docs/solution-docs/04-contracts.md` §6 (audit event types); the "Facts checked against the repo" human answers 3 and 4
  - Acceptance:
    - `evidence.py` provides `CaseEvidence`, `DbResult`, and `collect(conn, case, transcript)`, which reads the clone's:
      - `audit.audit_events` and `audit.llm_calls` for `transcript.conversation_id`;
      - `app.handoffs`;
      - the `db_state` results via `compile_item`;
      - the persona's segment.
    - `checks.py` provides `CheckResult` and one pure function per D15 check: `tools_required`, `tools_forbidden`, `db_state`, `confirm_before_act`, `readback_before_done`, `language` (its own stopword heuristic), `grounding` (digit runs in bot replies ⊆ that turn's `reply_sent.payload.fact_values`), `handoff_fields`, `no_raw_pii`.
    - `outcome`:
      - `handoff:<queue>` from `app.handoffs`;
      - `abstained` when the last `reply_sent.route` is `abstain`;
      - `clarified` when the last turn's `debug` SSE event has `pending` ending in `.card_hint`/`.block_kind`, or that turn's `nlu_result.status` is `ambiguous` (human answer 3);
      - `error` for `ended_by ∈ {error, max_turns}`;
      - otherwise `resolved`.
    - `unsafe` is set per D15 (E8).
    - `case_verdict(evidence, results)` gives `not_run` for `ended_by = not_runnable` or a non-empty `setup.db_patches` (D27), and `failed` for `error`/`max_turns`.
    - Test `eval/tests/test_checks.py::test_broken_flow_fails_right_check`, parametrized over `CaseEvidence` fixtures:
      - a write without `confirmation_used` fails only `confirm_before_act`;
      - a write without a readback fails only `readback_before_done`;
      - a forbidden tool fails only `tools_forbidden`;
      - each of these is unsafe;
      - `ended_by=error` gives a failed case, and `not_runnable` is excluded.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_checks.py -q && uv run --project backend ruff check eval/harness eval/tests && uv run --project backend ruff format --check eval/harness eval/tests`
  - Files: `eval/harness/evidence.py`, `eval/harness/checks.py`, `eval/tests/test_checks.py`

- [ ] T19: The eval runner lifecycle, the report and `make eval SUITE= SYSTEM=`
  - Depends on: T14 (metrics), T15 (`pii_check.scan`), T16 (clone, restore, dbstate), T17 (lint, `CannedDriver`, B's `load_dir`), T18 (evidence, checks, verdicts)
  - Read exactly these: spec D13, D16 and D18, and success criterion 6; B's `eval/driver/` `run_case` signature (read-only); `Makefile` (the `eval-pii-check` target, the `-include .env` header)
  - Acceptance:
    - `runner.py` follows D13 exactly, per system (`both` = proposed, then baseline, each on a fresh clone). It:
      1. creates the clone;
      2. starts `uv run uvicorn app.main:app --port <free>` with `cwd=backend` and the env overrides `APP_ENV=eval`, `DATABASE_URL=<clone>`, `REDIS_URL=…/<separate db index>`, `AGENT_SYSTEM=<system>`, `BANK=postgres`, then waits on `/api/v1/health`;
      3. runs `load_dir` + `lint_suite`;
      4. plays the cases sequentially through an injectable driver (default B's `run_case(case, base_url=…, otp_code=DEMO_OTP_CODE)`), skipping `db_patches` cases;
      5. for each case: evidence, then restore + verify for writing cases, where any diff aborts the run;
      6. runs the checks and `pii_check.scan`;
      7. writes `results.jsonl`/`llm_calls.jsonl`;
      8. stops uvicorn and drops the clone in `finally`, closing golden connections before any clone.
    - `report.py` writes `eval/reports/<run_id>/`:
      - `report.md`: a side-by-side table of every rate with n and a 95% CI; the failures section with one example per failed check (ids only); breakdowns by language and segment with small-n caveats; a "not run" list with reasons; every number labelled "offline evaluation"; the clone duration;
      - `metrics.json`;
      - `meta.json`: git SHA, system, provider, model ids and prompt versions from the ledger, policy hash, suite hash, clone seconds, started/finished, restore count, `restore_diffs`.
    - `__main__.py` is the CLI `--suite --system`.
    - `make eval SUITE=dev SYSTEM=both` runs `uv run --project backend python -m eval.harness …` from the repo root.
    - `.gitignore` adds `eval/reports/*/results.jsonl` and `eval/reports/*/llm_calls.jsonl`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend python -m eval.harness --help && make -n eval SUITE=dev SYSTEM=both >/dev/null && git check-ignore -q eval/reports/x/results.jsonl && git check-ignore -q eval/reports/x/llm_calls.jsonl && uv run --project backend pytest eval/tests -q && uv run --project backend ruff check eval/harness && uv run --project backend ruff format --check eval/harness`
  - Files: `eval/harness/runner.py`, `eval/harness/report.py`, `eval/harness/__main__.py`, `Makefile`, `.gitignore`

- [ ] T20: Keyword NLU for the baseline (ADR-005)
  - Depends on: nothing from earlier tasks (uses the existing `NLUResult` in `conversation/schemas.py`)
  - Read exactly these: spec D17 and the `test_keyword_nlu_es_pt` row in §"Test list"; `backend/app/domains/conversation/schemas.py`; `docs/solution-docs/decision-log.md` ADR-005
  - Acceptance:
    - `conversation/baseline/__init__.py`, `keyword_nlu.py` and `lexicon.yaml` (ES regional terms and PT).
    - `keyword_nlu(text, language_hint=None) -> NLUResult`:
      - clause split at `y / e / también / además / além disso / , / ; / ?`;
      - a per-clause lexicon match, in order of appearance, with duplicates removed;
      - the precedence rule `no reconozco` + `bloquear` → only `unrecognized_charge`;
      - a ~3-token negation window;
      - `bloquear` alone → `status=ambiguous`, `clarification=lock_vs_block`;
      - out-of-market (Pix, boleto, CPF) → `out_of_market` with `topic=pix_boleto`, and out-of-scope topics → `out_of_scope`;
      - language from lexicon hits.
    - No LLM, no I/O beyond loading the YAML once.
    - Test `backend/tests/unit/test_baseline.py::test_keyword_nlu_es_pt`, parametrized over ES and PT with the four spec cases.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_baseline.py -q && uv run ruff check app/domains/conversation/baseline tests/unit/test_baseline.py && uv run ruff format --check app/domains/conversation/baseline tests/unit/test_baseline.py && uv run mypy app/domains/conversation/baseline`
  - Files: `backend/app/domains/conversation/baseline/__init__.py`, `backend/app/domains/conversation/baseline/keyword_nlu.py`, `backend/app/domains/conversation/baseline/lexicon.yaml`, `backend/tests/unit/test_baseline.py`

- [ ] T21: `build_graph(system="baseline")`, with keyword NLU, template compose, template handoff summary and template abstain wording
  - Depends on: T11 (the `goal_*` templates, `compose`'s `grounding` update), T20 (`baseline.keyword_nlu`)
  - Read exactly these: spec D17 and the `test_baseline_turn_makes_no_llm_call` row; `backend/app/domains/conversation/graph.py` lines 360-420 (`build_graph`); `backend/app/domains/conversation/nodes/abstain.py`
  - Acceptance:
    - `baseline/template_compose.py`:
      - a graph node that fills the D12 `goal_*` template for the turn's goal from its facts, through `compose`'s `_format_fact` path;
      - records fact values;
      - emits `grounding: "template"`;
      - makes no LLM call.
    - The baseline's `understand` node wraps `keyword_nlu`, with the same state update shape as `nodes/understand.py`.
    - Its `handoff_summary` uses the existing fixed template.
    - `abstain.py`'s wording step can be swapped. The baseline fills `abstain_fallback` directly (human answer 2).
    - `build_graph(checkpointer, system: Literal["proposed","baseline"] = "proposed")` swaps only these four. The tools, policy, flows and graph shape are identical.
    - Test `test_baseline.py::test_baseline_turn_makes_no_llm_call`: a `card_status` turn on `build_graph(MemorySaver(), system="baseline")` via `make_session`-style config with an LLM whose `structured` raises `AssertionError`. The reply equals `goal_card_status` filled from facts.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_baseline.py tests/unit/test_graph.py tests/unit/test_abstain.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation tests/unit/test_baseline.py && uv run ruff format --check app/domains/conversation tests/unit/test_baseline.py && uv run mypy app/domains/conversation/graph.py app/domains/conversation/baseline app/domains/conversation/nodes/abstain.py`
  - Files: `backend/app/domains/conversation/baseline/template_compose.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/abstain.py`, `backend/tests/unit/test_baseline.py`

- [ ] T22: The `AGENT_SYSTEM` host wiring, eval-only
  - Depends on: T5 (`Settings.agent_system`), T21 (`build_graph(system=)`)
  - Read exactly these: spec D17 (last two sentences); `backend/app/domains/conversation/hosting.py` (`open_host`); `backend/app/main.py` (`_lifespan`)
  - Acceptance:
    - `open_host(database_url, llm, system="proposed")` passes `system` to `build_graph`.
    - `_lifespan` refuses to start (`RuntimeError`, naming `AGENT_SYSTEM`) when `agent_system == "baseline"` and `app_env != "eval"`. The check runs before the host opens. Otherwise it passes `settings.agent_system`.
    - The demo-reset reopen at `api/v1/admin.py:46` (`open_host(get_settings().database_url, old_host.llm)`) passes the same `system`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && printf '%s\n' 'import os' 'os.environ.update(APP_ENV="dev", AGENT_SYSTEM="baseline", JWT_SECRET="x", IDENTITY_HMAC_KEY="x", PII_VAULT_KEY="x")' 'from fastapi.testclient import TestClient' 'from app.main import create_app' 'try:' '    with TestClient(create_app()): pass' 'except RuntimeError as e:' '    assert "AGENT_SYSTEM" in str(e), e' 'else:' '    raise SystemExit("baseline not refused outside eval")' | uv run python - && uv run pytest tests/unit/test_health.py -q && uv run ruff check app/main.py app/domains/conversation/hosting.py app/api/v1/admin.py && uv run ruff format --check app/main.py app/domains/conversation/hosting.py app/api/v1/admin.py && uv run mypy app/main.py app/domains/conversation/hosting.py app/api/v1/admin.py`
  - Files: `backend/app/domains/conversation/hosting.py`, `backend/app/main.py`, `backend/app/api/v1/admin.py`

- [ ] T23: Doc updates, part 1: `01` §6, `02` §3, `03` §6, `04` §6 (D24)
  - Depends on: T1–T12 and T21 (real names). Read the state file's task log for them.
  - Read exactly these: spec D3, D4, D6, D7, D11, D24, and §"Contracts" → migration + `reply_sent` payload; `docs/solution-docs/01-technical-design.md` §6; `docs/solution-docs/04-contracts.md` §6
  - Acceptance:
    - `01` §6:
      - the detectors (regex plus checksum, the digit-in-document-run rule);
      - the known limit: third-party names and unlabelled third-party document numbers reach the LLM;
      - the staff-view line (D7);
      - agent and system messages masked with pattern detectors only.
    - `02` §3:
      - masking in the runner before graph input (the old `mask_pii` node);
      - `grounding_check` inside `compose` (the D11 order, one regeneration, the `goal_*` template);
      - `unmask` after it;
      - the baseline node swap (four nodes).
    - `03` §6: the `pii_vault` columns, the `llm_calls` columns + status CHECK, `messages.content` Fernet-encrypted + `content_masked` always set.
    - `04` §6: the `reply_sent` payload `grounding{outcome}` (worst of the turn, absent without `compose`) and `fact_values`.
    - Existing prose style, and no spec restatement beyond the contract.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/docs/solution-docs && grep -q 'fact_values' 04-contracts.md && grep -q 'pii_vault' 03-data-architecture.md && grep -q 'content_masked' 03-data-architecture.md && grep -qi 'third-party' 01-technical-design.md && grep -q 'grounding' 02-conversation-design.md`
  - Files: `docs/solution-docs/01-technical-design.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/03-data-architecture.md`, `docs/solution-docs/04-contracts.md`

- [ ] T24: Doc updates, part 2: `06` §2 and §3, `07` D5-A1 wording, `08` §9 and §10 (D24)
  - Depends on: T1 (the `.importlinter` contract), T19 (`eval/harness/` layout), T20 (the baseline path)
  - Read exactly these: spec D7, D10, D17, D21, D22 and D24; `docs/solution-docs/06-engineering-rules.md` §2 and §3; `docs/solution-docs/08-deployment.md` §9 and §10
  - Acceptance:
    - `06` §2: `langfuse` is importable only from `app.core.llm`.
    - `06` §3: `eval/harness/`, `eval/driver/` (B's), and the baseline at `backend/app/domains/conversation/baseline/`, replacing `eval/baseline/`.
    - `07` D5-A1 row: "unmasked only in the customer's view" becomes "unmasked in the customer's and the claiming agent's views". Change that wording only. The §8 deploy row belongs to T27.
    - `08` §9: `PII_VAULT_KEY` as an SSM SecureString under `/swip/prod/`, with a note that losing it makes vault rows and message content unreadable.
    - `08` §10 step 5: the ledger proof `SELECT provider, model_id, status FROM audit.llm_calls ORDER BY at DESC LIMIT 5`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/docs/solution-docs && grep -q 'langfuse' 06-engineering-rules.md && grep -q 'eval/harness' 06-engineering-rules.md && grep -q "claiming agent" 07-execution-plan.md && grep -q 'PII_VAULT_KEY' 08-deployment.md && grep -q 'audit.llm_calls ORDER BY at DESC LIMIT 5' 08-deployment.md`
  - Files: `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/07-execution-plan.md`, `docs/solution-docs/08-deployment.md`

- [ ] T25: First dev eval run for both systems, the PII check and the proposed D1.5 targets
  - Depends on: T13 (stack live, golden at `0007`), T19 (`make eval`), T22 (baseline startable), plus B's `run_case` driver on this branch. If B's driver isn't merged, stop and report: criterion 6 moves to D6 morning under the cut line.
  - Read exactly these: spec D13, D16, D19 and D20, and success criteria 6 and 7; `docs/solution-docs/05-evaluation-plan.md` §6; `eval/harness/report.py`
  - Acceptance:
    - With `make up` running, `make eval SUITE=dev SYSTEM=both` finishes and writes `eval/reports/<run_id>/{report.md,metrics.json,meta.json}`, meeting every bullet of criterion 6. Both systems list the same `case_id`s, and `restore_diffs: 0`.
    - `make eval-pii-check RUN=<run_id>` exits 0 and prints `0 hits`.
    - The implementer adds a "Proposed D1.5 targets" section to that `report.md`, one numeric target per `05` §6 metric except NLU accuracy, each with its reasoning.
    - Escalate the proposal to the orchestrator for human approval. Don't write `05`.
    - Record the `run_id` in the state file.
    - Commit only `report.md`, `metrics.json` and `meta.json`. The jsonl files are ignored.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && RUN=$(ls -t eval/reports | head -1) && test -f eval/reports/$RUN/report.md && test -f eval/reports/$RUN/meta.json && grep -q 'offline evaluation' eval/reports/$RUN/report.md && grep -q '"restore_diffs": 0' eval/reports/$RUN/meta.json && make eval-pii-check RUN=$RUN | tail -1 | grep -qx '0 hits' && git diff --quiet develop -- eval/scenarios/heldout`
  - Files: `eval/reports/<run_id>/report.md`, `eval/reports/<run_id>/metrics.json`, `eval/reports/<run_id>/meta.json`

- [ ] T26: Record the approved D1.5 targets in `05` §6
  - Depends on: T25 (the `run_id` and the proposed targets). The human's approved values come in the dispatch message.
  - Read exactly these: spec D19 and success criterion 8; `docs/solution-docs/05-evaluation-plan.md` §6; the T25 entry in the state file's task log
  - Acceptance:
    - `05` §6 gets a targets table with exactly the human-approved values, one per metric, citing the dev run id and the approval date. The "Targets (D1.5)" paragraph says they are recorded.
    - No `eval/reports/heldout-*` exists.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && grep -q "$(ls -t eval/reports | head -1)" docs/solution-docs/05-evaluation-plan.md && ! ls -d eval/reports/heldout-* 2>/dev/null`
  - Files: `docs/solution-docs/05-evaluation-plan.md`

- [ ] T27: The AWS deploy runbook and checklist (carried over from D4-A T32). No AWS command is run.
  - Depends on: every earlier task (the green branch; the `0007` migration name; `PII_VAULT_KEY`)
  - Read exactly these: spec D21, D22 and success criteria 11 and 12; the D4-A plan's T32 block (`awk '/^- \[ \] T32:/{f=1} f&&/^- \[ \] T33:/{exit} f' docs/plans/d4-a-escalation-handoff-deploy.md`); `docs/solution-docs/08-deployment.md` §5, §8, §9, §10 and §13
  - Acceptance:
    - The agent appends a runbook + checklist to its T27 entry in `docs/plans/d5-a-privacy-grounding-eval.state.md`. It holds D4-A T32's steps 1–7 plus D22's changes:
      - step 0: after D5-A (and D5-B if merged) land, open the `develop → main` release PR;
      - `put-parameter` for `/swip/prod/PII_VAULT_KEY` (a Fernet key);
      - `make deploy` applies `0007` to `latam_app` and `latam_golden`;
      - the Bedrock proof: `SELECT provider, model_id, status FROM audit.llm_calls ORDER BY at DESC LIMIT 5` shows `bedrock`, the registry's `us.` id, and a masked `input_text`.
    - `<PLACEHOLDER>` stands for every human-supplied value. The runbook carries no secret, account id, bucket or email.
    - The checklist has one checkbox per criterion 12 item, naming the output to paste back.
    - `.env.prod.example` gets `PII_VAULT_KEY=` under the SSM-sourced block.
    - `docs/plans/d4-a-escalation-handoff-deploy.state.md`: T32 and T33 rows become `moved → D5-A`.
    - This card's state file gets a `T-deploy-record` board row with status `pending: post-merge, human deploy`.
    - `07` §8 gets the row "D5 | Deploy of main after D5-A merge | results recorded by `/wave-run D5-A-deploy`".
    - The agent never runs `aws`, `make infra-*`, `make deploy*`, `make seed-identity`, SSM or certbot.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uvx cfn-lint infra/aws/ec2-stack.yaml && bash -n infra/aws/*.sh && make -n deploy deploy-remote smoke-prod HOST=x.sslip.io >/dev/null && grep -q 'PII_VAULT_KEY' docs/plans/d5-a-privacy-grounding-eval.state.md && grep -q 'T-deploy-record' docs/plans/d5-a-privacy-grounding-eval.state.md && grep -q 'moved → D5-A' docs/plans/d4-a-escalation-handoff-deploy.state.md && grep -q 'D5-A-deploy' docs/solution-docs/07-execution-plan.md && grep -q '^PII_VAULT_KEY=' .env.prod.example && ! grep -nE '(AKIA|arn:aws:iam::[0-9]{12}|@[a-z0-9-]+\.[a-z]{2,})' docs/plans/d5-a-privacy-grounding-eval.state.md`
  - Files: `docs/plans/d5-a-privacy-grounding-eval.state.md` (T27 log entry + board row), `docs/plans/d4-a-escalation-handoff-deploy.state.md`, `docs/solution-docs/07-execution-plan.md`, `.env.prod.example`

- [ ] T28: Agent tooling MCP servers run inside the dev compose stack (human request, added mid-card)
  - Depends on: nothing (T4's edits to `docker/docker-compose.observability.yml` and `Makefile` are already on disk; keep them)
  - Read exactly these: `.mcp.json`; `Makefile` (`COMPOSE`, `setup`, `mcp-setup`, `up`, `down`); `docker/docker-compose.dev.yml`; `docker/docker-compose.base.yml` (`nginx`); `frontend/vite.config.ts` (`server`); `README.md` §7
  - Acceptance:
    - New `docker/docker-compose.devtools.yml`, loaded ONLY by the dev `COMPOSE` in the Makefile (never by `COMPOSE_PROD`). It adds three services that `make up` starts and `make down` stops:
      - `mcp-victorialogs`: `ghcr.io/victoriametrics/mcp-victorialogs:v1.9.0`, env `VL_INSTANCE_ENTRYPOINT=http://victorialogs:9428`, `MCP_SERVER_MODE=http`, `MCP_LISTEN_ADDR=:8081`, port `127.0.0.1:8081:8081`.
      - `mcp-victoriatraces`: `ghcr.io/victoriametrics-community/mcp-victoriatraces:v1.5.0`, env `VT_INSTANCE_ENTRYPOINT=http://victoriatraces:10428`, `MCP_SERVER_MODE=http`, `MCP_LISTEN_ADDR=:8081`, port `127.0.0.1:8082:8081`.
      - `mcp-playwright`: `mcr.microsoft.com/playwright/mcp:v0.0.82`, `init: true`, command `--headless --browser chromium --no-sandbox --isolated --port 8931 --host 0.0.0.0 --allowed-hosts "*"` (or the equivalent for this image's entrypoint), port `127.0.0.1:8931:8931`, `depends_on: nginx`.
      - All ports localhost-only. Pinned tags unchanged.
    - The browser reaches the app on the compose network at `http://nginx/` (human decision). `frontend/vite.config.ts` `allowedHosts` adds `"nginx"` (dev server only). If Nginx or Vite rejects that host, fix only the dev config, and report.
    - `.mcp.json`: `victorialogs`, `victoriatraces` and `playwright` become `{"type": "http", "url": "http://localhost:<port>/mcp"}`. `deepwiki` is unchanged.
    - `Makefile`: `mcp-setup` is removed (or becomes `$(COMPOSE) pull` for the three services), and `setup` stays working. No `docker run` MCP entry is left.
    - `README.md` §7: the three MCP servers are compose services, they are available only while `make up` is running, agents open the app at `http://nginx/`, and Claude Code must be restarted to reload `.mcp.json`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && make up && for p in 8081 8082; do curl -fsS http://127.0.0.1:$p/health/liveness >/dev/null; done && curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}}' http://127.0.0.1:8931/mcp | grep -q 200 && docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.observability.yml -f docker/docker-compose.prod.yml config --services | grep -c mcp- | grep -qx 0 && python3 -c "import json; s=json.load(open('.mcp.json'))['mcpServers']; assert all('command' not in v for v in s.values()), s" && make down && test -z "$(docker ps -q --filter name=mcp-)"`
  - Files: `docker/docker-compose.devtools.yml`, `Makefile`, `.mcp.json`, `frontend/vite.config.ts`, `README.md`
- [ ] T29: Fixed ES/PT goal template for `decline_explain` (human decision, mid-card)
  - Depends on: nothing (D5-B's `decline_explain` goal is on this branch after the develop merge)
  - Read exactly these: `backend/app/domains/conversation/nodes/compose.py` (`_GOAL_TEMPLATES`, `_fill_goal_template`, `_format_fact` for `decline_cause`/`decline_next_step`); `backend/app/domains/conversation/templates.py` (`goal_card_status`, `goal_balance_due` entries and the `TemplateKind` literal); `backend/tests/unit/test_compose.py`
  - Acceptance:
    - `templates.py` gains `goal_decline_explain`, added to `TemplateKind` and the template table, with exactly this text (human-approved):
      - ES: `Tu compra fue rechazada: {decline_cause}. {decline_next_step}`
      - PT: `Sua compra foi recusada: {decline_cause}. {decline_next_step}`
    - `compose.py` maps `"decline_explain": "goal_decline_explain"` in `_GOAL_TEMPLATES`. The temporary `kind is None` → `fallback` guard in `_fill_goal_template` is removed once every non-abstain `Goal` has a template.
    - A draft that fails the grounding check twice on `decline_explain` returns the template, with both placeholders filled in code through `_format_fact`, which uses the policy labels. It never returns `fallback` when both facts are present.
    - Test `backend/tests/unit/test_compose.py::test_decline_explain_grounding_falls_back_to_goal_template`, parametrized ES and PT, fake LLM: two ungrounded drafts → the filled goal template and `grounding == "template"`.
  - Verify: `cd backend && uv run pytest tests/unit/test_compose.py -q && uv run ruff check app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py tests/unit/test_compose.py && uv run ruff format --check app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py tests/unit/test_compose.py && uv run mypy app/domains/conversation/nodes/compose.py app/domains/conversation/templates.py`
  - Files: `backend/app/domains/conversation/templates.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/tests/unit/test_compose.py`
- [ ] T30: Mechanical ruff fixes in B's eval tests (human decision, mid-card)
  - Depends on: nothing
  - Read exactly these: the two files below. Nothing else.
  - Acceptance:
    - `ruff format` and a fix of PIE810 at `eval/tests/test_driver.py:109` (multiple `startswith` calls become one call with a tuple). No behavior change, no other edits.
    - Both files still pass their own tests.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend ruff check eval/tests/test_driver.py eval/tests/test_scenarios_valid.py && uv run --project backend ruff format --check eval/tests/test_driver.py eval/tests/test_scenarios_valid.py && uv run --project backend pytest eval/tests/test_driver.py eval/tests/test_scenarios_valid.py -q`
  - Files: `eval/tests/test_driver.py`, `eval/tests/test_scenarios_valid.py`
- [ ] T31: NLU on Sonnet 5.5 sends no temperature; ledger temperature nullable (human decision after T25's failed run)
  - Depends on: nothing. Runs alone: it applies a migration to the dev and golden DBs.
  - Read exactly these: `backend/app/core/llm/registry.py` (`TEMPERATURE`), `backend/app/core/llm/client.py` (`build_chat_model`, `_finish`), `backend/app/core/llm/sink.py` (`LLMCallRecord`), `backend/app/alembic/versions/0007_privacy_ledger.py` (the `audit.llm_calls.temperature` column), and T13's Task log entry (how `latam_app` and `latam_golden` were brought to head)
  - Facts: the live API answers `400 invalid_request_error: "temperature" is deprecated for this model` for `claude-sonnet-5-5` with any `temperature`. The same request without it succeeds. The human decided to keep Sonnet 5.5 for `nlu` and send no temperature (the model default).
  - Acceptance:
    - `TEMPERATURE` becomes `dict[Step, float | None]` with `"nlu": None`. Every other step is unchanged: compose and handoff_summary 0.0, paraphrase 1.0. Add a comment citing the API error.
    - `build_chat_model` omits the `temperature` kwarg entirely when the step's value is `None`, for every provider. `ChatAnthropic` must not send a default temperature: check the request that langchain-anthropic builds, and don't just trust the kwarg.
    - `llm.call` logs and `LLMCallRecord.temperature` carry `None` for such calls. The sink and the audit repository accept `None`.
    - A new migration `0008` makes `audit.llm_calls.temperature` nullable, with a downgrade. Apply it to `latam_app` and `latam_golden` the way T13 did. `alembic upgrade head` reaches `0008` on both.
    - Test in `backend/tests/unit/test_llm_client.py`, fake chat model factory, no network: an `nlu` call builds the model with no `temperature`, and the ledger record has `temperature is None`. The existing `temperature == 0.0` assertion keeps working for a 0.0 step.
    - A one-off live proof: a single `nlu` call through `get_llm_client()` with a masked input returns a validated object, and no temperature error appears. Print only the outcome.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_llm_client.py -q && uv run ruff check app/core/llm tests/unit/test_llm_client.py app/alembic/versions/0008_*.py && uv run ruff format --check app/core/llm tests/unit/test_llm_client.py app/alembic/versions/0008_*.py && uv run mypy app/core/llm app/domains/audit && uv run lint-imports`
  - Files: `backend/app/core/llm/registry.py`, `backend/app/core/llm/client.py`, `backend/app/core/llm/sink.py`, `backend/app/domains/audit/repository.py`, `backend/app/alembic/versions/0008_llm_calls_temperature_nullable.py`, `backend/tests/unit/test_llm_client.py`
- [ ] T32: R7 amendment and ADR-031 temperature note (human decision after T25's failed run)
  - Depends on: nothing (docs only)
  - Read exactly these: `docs/solution-docs/06-engineering-rules.md` §1 (the R7 row); `docs/solution-docs/decision-log.md` ADR-030's "Temperature note" and ADR-031
  - Acceptance:
    - R7 reads "…pins the model ID, prompt version and temperature (where the model accepts one)…". Change nothing else in the row.
    - ADR-031 gains a "Temperature note" in ADR-030's style:
      - `claude-sonnet-5-5` rejects `temperature` ("deprecated for this model"), so `nlu` sends none and uses the model default;
      - the ledger records NULL;
      - the NLU is a little less repeatable run to run, and the eval reports carry that caveat.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/docs/solution-docs && grep -q 'where the model accepts one' 06-engineering-rules.md && grep -q 'deprecated for this model' decision-log.md`
  - Files: `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/decision-log.md`
- [ ] T33: Eval runner aborts when the LLM is unreachable (found by T25's failed run)
  - Depends on: T19 (`eval/harness/runner.py`)
  - Read exactly these: `eval/harness/runner.py`; the T19 convention in the state file
  - Acceptance:
    - After each played case, the runner reads that system's `audit.llm_calls` rows from the clone. Once at least 5 cases have been played and every row so far has status `unavailable` (or there are no rows at all), it raises `LLMUnreachableError` with the first model id and step seen. This aborts the run the way `RestoreDiffError` does: uvicorn is stopped and the clone dropped in `finally`, and no report is written.
    - Test `eval/tests/test_runner_abort.py::test_all_unavailable_aborts`, testing the pure decision function on synthetic status lists, with no DB:
      - 5 cases, all `unavailable` → abort;
      - one `ok` → no abort;
      - 4 cases → no abort.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend pytest eval/tests/test_runner_abort.py -q && uv run --project backend ruff check eval/harness/runner.py eval/tests/test_runner_abort.py && uv run --project backend ruff format --check eval/harness/runner.py eval/tests/test_runner_abort.py`
  - Files: `eval/harness/runner.py`, `eval/tests/test_runner_abort.py`
- [ ] T34: Log the provider's error text on `unavailable`, and fix the T33 abort message (found by T25's second attempt)
  - Depends on: T31 (`client.py`), T33 (`runner.py`)
  - Read exactly these: `backend/app/core/llm/client.py` (the `except (anthropic.APIError, openai.APIError, BotoCoreError, ClientError)` branch and `_finish`); `eval/harness/runner.py` (`LLMUnreachableError` and the rows it reads, around line 191)
  - Facts: the second T25 run hit 15 consecutive `400 Bad Request` responses from `api.anthropic.com` after 92 good calls, and then recovered minutes later. The cause is unknown because the error body was never logged. The abort said `model None, step None` because the guard reads keys the rows don't have.
  - Acceptance:
    - On `unavailable`, the `llm.call` log line gains `error_type` (the exception class name) and `error_message`. For `anthropic.APIStatusError`/`openai.APIStatusError`, `error_message` also includes the HTTP status and the API's `error.type`/`message`.
    - `error_message` is truncated to 300 characters and passed through `app.core.pii` masking before it is logged (R5: an error message could echo input).
    - Nothing new goes to the ledger or Langfuse.
    - `LLMUnreachableError` names the real model id and step from the ledger rows (use the actual column names), plus the count of rows seen.
    - No new test file. Extend the existing unavailable-path test in `test_llm_client.py` only if one exists; otherwise the proof is the Verify below.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && (cd backend && uv run pytest tests/unit/test_llm_client.py -q && uv run ruff check app/core/llm/client.py tests/unit/test_llm_client.py && uv run ruff format --check app/core/llm/client.py tests/unit/test_llm_client.py && uv run mypy app/core/llm) && uv run --project backend pytest eval/tests/test_runner_abort.py -q && uv run --project backend ruff check eval/harness/runner.py && uv run --project backend ruff format --check eval/harness/runner.py`
  - Files: `backend/app/core/llm/client.py`, `backend/tests/unit/test_llm_client.py`, `eval/harness/runner.py`
- [ ] T35: A case filter for `make eval` (human decision: smoke subset now, full measurement postponed)
  - Depends on: T19, T34 (`eval/harness/runner.py`, `__main__.py`, the `eval` Makefile target)
  - Read exactly these: `eval/harness/__main__.py`, `eval/harness/runner.py` (where `load_dir` and `lint_suite` run), the `eval:` target in `Makefile`
  - Acceptance:
    - `python -m eval.harness` gains `--cases PREFIX[,PREFIX...]`. It keeps only cases whose `seed_id` starts with one of the prefixes. The filter runs after `load_dir` and before `lint_suite`.
    - An empty selection is an error before any clone is made.
    - With no `--cases`, behaviour is unchanged.
    - `meta.json` records the filter (`"cases_filter"`, null when unset). `report.md` states it in the header, e.g. "subset: a-".
    - `make eval SUITE=dev SYSTEM=proposed CASES=a-` passes `--cases a-` when `CASES` is set.
    - No new test file. The filter is glue; the proof is the Verify below.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend python -m eval.harness --help | grep -q -- '--cases' && make -n eval SUITE=dev SYSTEM=proposed CASES=a- | grep -q -- '--cases a-' && uv run --project backend pytest eval/tests -q && uv run --project backend ruff check eval/harness/__main__.py eval/harness/runner.py && uv run --project backend ruff format --check eval/harness/__main__.py eval/harness/runner.py`
  - Files: `eval/harness/__main__.py`, `eval/harness/runner.py`, `Makefile`
- [ ] T36: Card-lock seed picks its card (human decision from T17, triggered by the T25 smoke run)
  - Depends on: T25 (smoke run `dev_proposed_20260929t174357`: `a-card_block-normal_resolution-es-co-01` ended `error: no_open_confirmation`, because persona `CLI-5RJITZ5VLJGY` has 2 debit cards and Cardy asked which card before offering the lock)
  - Read exactly these: `eval/scenarios/dev/a-card_block-normal_resolution-es-co-01.yaml`; `eval/scenarios/schema.py` (`Turn` kinds); `eval/driver/driver.py` (how a card-choice turn is sent, and `_turn_input`); one of B's `d-*` seeds that answers a "which card" question, if any (grep `card` turns)
  - Acceptance:
    - The seed gains one turn between the request and the `confirm` turn. The turn picks one of the persona's cards the way B's schema and driver support a card choice. If only free text is supported, use team-written text naming the card by its last four digits, read from the golden DB with `psql`. Keep the persona.
    - `expected_db_state` still targets that one card.
    - A one-case smoke run `make eval SUITE=dev SYSTEM=proposed CASES=a-card_block` makes the case pass. It plays 1 case with about 3 LLM calls, and each run takes about 9 min because of the golden clone. Run it at most twice. Report the report's verdict, the PII check and whether the clone was dropped. Commit nothing.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uv run --project backend python -c "from pathlib import Path; from eval.scenarios.schema import load_dir; from eval.harness.lint import lint_suite; lint_suite(load_dir(Path('eval/scenarios/dev')))" && git diff --quiet origin/develop -- eval/scenarios/heldout`, plus the smoke run above passing.
  - Files: `eval/scenarios/dev/a-card_block-normal_resolution-es-co-01.yaml`
- [ ] T37: Baseline negated-only intent returns an empty intent list (restores the human's T20 decision; found at verification)
  - Depends on: T20 (`keyword_nlu.py`)
  - Read exactly these: `backend/app/domains/conversation/baseline/keyword_nlu.py` (the `if not intents:` branch around lines 116–125, and where negated hits are dropped); `backend/tests/unit/test_baseline.py` (`test_keyword_nlu_es_pt`); spec D17 and D47
  - Facts: the human decided at T20 that no lexicon hit returns `general_question`, and a negated-only intent returns an empty intent list. The T20 repair folded both into `general_question`: see the comment "No lexicon hit (or every hit was negated)".
  - Acceptance:
    - When at least one intent keyword matched but every match was negated, and there is no out-of-scope or market hit, the result is `intents=[]`, `status="out_of_scope"` and `slots.topic="other"`. That was the pre-repair no-intent shape recorded in the T20 log.
    - Plain no-hit text still returns `["general_question"]` / `clear`.
    - Out-of-scope and out-of-market branches are unchanged.
    - Add two parametrized cases to `test_keyword_nlu_es_pt`: ES `no quiero bloquear mi tarjeta` and PT `não quero bloquear o cartão`, both giving empty intents and `out_of_scope`. Keep all existing cases.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/backend && uv run pytest tests/unit/test_baseline.py -q && uv run ruff check app/domains/conversation/baseline tests/unit/test_baseline.py && uv run ruff format --check app/domains/conversation/baseline tests/unit/test_baseline.py && uv run mypy app/domains/conversation/baseline`
  - Files: `backend/app/domains/conversation/baseline/keyword_nlu.py`, `backend/tests/unit/test_baseline.py`
