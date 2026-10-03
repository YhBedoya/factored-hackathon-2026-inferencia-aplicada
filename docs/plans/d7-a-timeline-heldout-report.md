# Plan: D7-A — Timeline API and the held-out report pipeline

Spec: [`docs/specs/d7-a-timeline-heldout-report.md`](../specs/d7-a-timeline-heldout-report.md) · Branch: `feat/d7-a-timeline-heldout-report`

## Open questions (block one task each; everything else can run)

- **Q1 (blocks T7).** D19 and `ConversationSummary.created_at` name `app.conversations.created_at`, but that column does not exist. Migration `0002` created `started_at timestamptz not null default now()` and no `created_at`. Options: (a) the `date_from`/`date_to` filter and the `created_at` field both read `started_at`, with no migration and the contract field name unchanged, and D19's wording is amended (recommended); (b) add migration `0009` with a `created_at` column (an "ask first" item, and it needs `alembic upgrade` on both dev DBs); (c) rename the schema field to `started_at` too, which changes the contract that B3 builds against.
- **Q2 (blocks T4).** D9 says the report "links to B4's agreement report when that file exists", but no doc names that file. D7-B has no spec yet, and `05` §5 only names `eval/judges/rubric.md`. Options: (a) a fixed path `eval/judges/agreement.md`, which B4's card must write (recommended; it sits next to the rubric); (b) no link logic in this card: the section always reads "pending D7-B4", and B4's card adds the link; (c) the newest `eval/reports/judge-*/agreement.md`.

The orchestrator writes each answer into the state file before it dispatches T4 or T7.

## Facts checked against the repo

- **Base.** `develop` @ `c64dd67` (D6-B merge). The branch is checked out at the same commit. The alembic head is `0008` (`0008_llm_calls_temperature_nullable.py`). No migration is planned. No new dependency: `pyyaml`, `psycopg`, `httpx` and `langchain-anthropic` are already in `backend/pyproject.toml`, so no lockfile changes.
- **The dev stack is down** (`docker ps` is empty). Postgres 16 (`latam-cs-postgres-1`, host port 5432) and Redis (`127.0.0.1:6379`) only come up with `make up`, which runs `docker compose … up -d --build --wait` and so rebuilds the backend image. The containers are named `latam-cs-<service>-1`. Health through nginx: `curl -s http://localhost/api/v1/health`. The Makefile has `-include .env` + `export`, so every `make` target sees `.env`.
- **Stack-dependent work.** `backend/tests/integration/*` needs Postgres **and** Redis reachable from the host. `it_db`/`it_env` otherwise *skip*, and a skip is not a proof. `make client` reads `http://localhost/api/v1/openapi.json` through nginx (`frontend/openapi-ts.config.ts`). Run the frontend typecheck in the container: `docker exec latam-cs-frontend-1 npm run typecheck` (the host `node_modules` is incomplete). Never `npm install` on the host.
- **Tables (from migrations).** `app.conversations(id, customer_id, channel, language, mode, status, started_at, closed_at)`, with **no `created_at`** (Q1). `app.messages(id, conversation_id, turn_id, role, content [Fernet-encrypted], content_masked, ui_payload jsonb, created_at)`. Roles written today are `customer`, `bot` and `agent`. `app.handoffs(id, conversation_id, queue, reason, priority, packet, status, agent_id, created_at, claimed_at, returned_at)`. `audit.audit_events(id, at, conversation_id, turn_id, actor, type, payload jsonb, sources jsonb, policy_version, model, trace_id, langfuse_trace_id [always NULL])`. `audit.llm_calls(id, at, conversation_id, turn_id, step, provider, model_id, prompt_version, temperature [nullable since 0008], attempt, status, input_text, output_json, input_tokens, output_tokens, cost_usd numeric(12,6), latency_ms, langfuse_trace_id)`. `bank.customers(customer_id, document_number, document_type, …, country ['México'|'Colombia'|'Argentina'], segment, …)` lives in the same `latam_app` DB.
- **Audit payloads (writer: `backend/app/domains/conversation/runner.py:315-372`).** `nlu_result` = `{language, status, intents}`. `reply_sent` = `{route, ui_kinds, length, fact_values, grounding?}`. `rule_hit` = `{rule_id}`. Staff claim/return events use `actor = agent:<uuid>` and a fresh `turn_id` (`backend/app/api/v1/staff.py::_audit`).
- **Existing staff router.** `backend/app/api/v1/staff.py` declares router-level `require_role("agent", "admin")` + `require_csrf`. It exports `get_claimed_conversation` (uses `store.get_conversation` + `handoff_service.is_claimed_by`). Its `/messages` route returns decrypted `content`, which is the claimed-agent path and is left untouched. `backend/app/api/v1/admin.py` is the admin-only router pattern to mirror (`require_role("admin")` + `require_csrf`). The routers are mounted in `backend/app/api/v1/__init__.py`.
- **`backend/tests/unit/test_r13_routes.py` today** asserts that every `/api/v1/staff/…` route has the `("agent", "admin")` guard, and that every path under `/api/v1/staff/conversations/{conversation_id}` calls `get_claimed_conversation` (`>= 3` such paths). An admin-only `/staff/personas` route and the timeline route both **break it as written**, so it is edited by T8 (personas) and then by T10 (timeline).
- **Settings.** `backend/app/core/config.py::Settings` has `credentials_seed`, `app_env`, `llm_provider` and `llm_disabled`, but no `personas_path` or `git_sha`. `LANGFUSE_HOST` is `backend/app/core/llm/settings.py::LLMSettings.langfuse_host` (`str | None`), and that is "the existing setting" D20 means. `LLMSettings.llm_provider` is what the client uses to choose the provider.
- **LLM code.** `backend/app/core/llm/client.py`: `get_llm_client(settings=None, sink=None)` (line 400) → `StructuredLLMClient(settings, chat_model_factory=build_chat_model, sink, sleep)`. The factory signature is `Callable[[LLMSettings, Step], _ChatModel]`, and `tests/unit/test_llm_client.py` passes 2-arg lambdas (`lambda s, step: stub`), which must keep working. `model_id` is read from `MODEL_REGISTRY[step][provider]` in both `build_chat_model` (line 128) and `structured` (line 190). Pricing is `pricing.cost_usd(model_id, …)`, and both Sonnet 5.5 and Haiku 4.5 are priced. `TEMPERATURE["nlu"] is None`, and the override changes only the model, so both NLU models run with no temperature sent.
- **Prompt refs** are private constants: `nodes/understand.py:22` `PromptRef("nlu", 4)`, `nodes/compose.py:46` `PromptRef("compose", 6)`, `nodes/handoff_summary.py:32` `PromptRef("handoff_summary", 1)`. `.label` gives `nlu@v4`. `app.api` may import them (layer contract api → domains).
- **Policies.** `app.domains.policy.registry.get_policies()` → `PolicyBundle{hash: "sha256:…", files: [names], …}`. The directory is `registry._DEFAULT_POLICIES_DIR` (`<repo root>/policies`, which resolves to `/policies` in the dev container, bind-mounted read-only).
- **Customers.** `backend/app/domains/customers/service.py` has a private `_COUNTRY_LABELS` (`México→MX`, `Colombia→CO`, `Argentina→AR`) and no document lookup. `repository.py` has `fetch_login_profile` (document_type + last3) and `fetch_known_pii` (document_number). `generate_password(customer_id, *, seed)` is in `app/domains/identity/passwords.py:69`. `identity` has no `schemas.py`. The spec allows the persona schemas to live in the new `identity/personas.py`.
- **import-linter** (`backend/.importlinter`): the contracts are layers (`api → domains → core`), the LLM SDKs only in `app.core.llm`, `app.domains.conversation` never reaching `*.repository`, and `app.core.*` never reaching `*.repository`. `audit → customers.service` and `identity → customers.service` are allowed. `eval/` is outside import-linter and outside `mypy app`.
- **Eval harness (no `app` import in `runner.py`/`metrics.py`, D25).** `eval/simulator/simulator.py:39-47` is the pattern for eval code that must import `app`: put `<repo>/backend` on `sys.path`, then `# noqa: E402` imports. `eval/harness/__main__.py` imports the simulator lazily on its branch, and `nlu_eval` follows the same pattern.
  - `runner.run(suite, system, *, driver, driver_name, run_id, cases_filter)` creates **one clone per system** (`_run_system` → `clone.create(f"{run_id}_{system}")`) and writes `meta.clone_seconds` as a dict. `clone.clone_name` only accepts `^[a-z0-9_]+$`, so a `dev-<sha10>` folder name must be mapped to `_`. `clone.create` uses `CREATE DATABASE … TEMPLATE latam_golden` with no strategy. The golden DB is ~7.7 GB, and WAL_LOG clones took 505–1030 s (`eval/reports/dev_proposed_*/meta.json`).
  - `_clear_turn_keys(system)` and `_redis_url` already exist. Proposed uses Redis db 1 and baseline db 2.
  - `restore.restore_persona(clone, golden, customer_id)` / `verify_persona(…)` raise `RestoreDiffError` and also delete the persona's `app.handoffs`.
  - `write_report(out, verdicts_by_system, meta)` is in `eval/harness/report.py:184`. It reads `meta["clone_seconds"].items()` and uses a single `LABEL = "offline evaluation"` from `metrics.py`. `metrics.compute_all(verdicts)` → `{overall, by_language_variant, by_segment, not_run}`. `by_group` maps a missing key to `"unknown"`.
  - `checks.case_verdict` has **no `category` key**. `ev.case.category` exists (`Category` literal in `eval/scenarios/schema.py:45`).
  - `pii_check.main(["--run", <folder>])` resolves `eval/reports/<folder>` and already works for any folder name.
  - `.gitignore:37-38` already ignores `eval/reports/*/results.jsonl` and `llm_calls.jsonl`.
  - `eval/scenarios/freeze.py::check(root) -> list[str]` returns the problems it finds. `eval/scenarios/heldout/` and `heldout.lock` **do not exist** on develop (`_staging/heldout/` has 50 files), so the heldout guard refuses today.
- **`CASES=a-` selects 5 cases, not 4.** The spec says 4, but `a-decline_explain-injection-es-mx-01` was added in D6-A. Selected personas: `CLI-5RJITZ5VLJGY`, `CLI-0D54NQDU9AWV`, `CLI-55D0R3VIIFPT`, `CLI-UAJ81O52ZM1R`, `CLI-KX9TL8GMCQUT`. The last proposed run on 4 of them made 7 LLM calls. Estimate for the D2 proof: about 8–9 calls per proposed run × 3, plus 0 for the baseline, plus 20 × 2 = 40 NLU calls, which is **about 65–75 calls**, under the spec's "at most about 80" bound. `resets` is still 4 (one per run).
- **NLU inputs.** `eval/nlu/nlu_v1_smoke.yaml` is a list of 20 entries `{id, text, country, pending?, note, expected{language, intents, status, …}}` with no `language_variant`, so the breakdown groups them under `unknown` (the `by_group` convention). `run_nlu(llm, text, *, pending, country)` is in `app.domains.conversation.nodes.understand` (re-exported by `app.domains.conversation.nodes`). `keyword_nlu(text, language_hint=None) -> NLUResult` is in `app.domains.conversation.baseline.keyword_nlu`. `backend/scripts/nlu_smoke.py` is the in-process analogue. `LLMCallRecord` is a dataclass in `app.core.llm.sink` (`cost_usd: Decimal | None`).
- **`eval/personas.yaml`** has a top-level `personas:` list. Each entry has `customer_id`, `split`, optional `notes`, and every other key is a trait. It is 52 entries, with no PII (R10).
- **Pre-existing ruff debt in legacy harness files** (accepted by the human in D6-B, not fixed here). `ruff check` reports E501 at `checks.py:342`, `report.py:206,230` and `runner.py:57`, RUF005 at `report.py:155`, and UP047 at `runner.py:226`. `ruff format --check` fails on 11 legacy `eval/harness` files. Therefore Verify lints **touched legacy harness files** with `ruff check --config backend/pyproject.toml --ignore E501,RUF005,UP047` and no format check, and lints **new** eval files with both check and format. Don't reformat whole legacy files.
- **Eval test and lint commands** run from the repo root: `uv run --project backend pytest eval/tests/<file> -q` and `uv run --project backend ruff check --config backend/pyproject.toml <paths>`. Backend commands run from `backend/`: `uv run pytest …`, `uv run ruff check …`, `uv run mypy <paths>`, `uv run lint-imports`.
- **Planned names crossing tasks.** Each implementer records the final names in the state file.
  - T2: `customers.service.COUNTRY_LABELS` (public), `customers.service.get_document(customer_id) -> tuple[str, str]` (`(document_type, document_number)`, raises `ToolUnavailable` if missing).
  - T4: `report.write_report(out, runs: dict[str, list[list[dict]]], meta: dict, *, nlu: dict | None = None, nlu_section: list[str] | None = None)`, where `runs` maps system → one verdict list per run; `report.label_for(driver_name) -> str`.
  - T7: `audit.timeline.ConversationFilters`, `list_conversations(filters, limit, offset) -> ConversationPage`, `get_timeline(conversation: ConversationRow) -> ConversationTimeline`.
  - T9: `nlu_eval.compare(source: "smoke" | "suite", cases, *, models=NLU_MODELS) -> tuple[dict, list[dict]]` (async; the metrics dict and the ledger rows), `nlu_eval.render(nlu: dict) -> list[str]`.

## Components

- **Settings + image wiring.** `backend/app/core/config.py` (`personas_path`, `git_sha`), `backend/Dockerfile` (`ARG GIT_SHA=unknown` → `ENV GIT_SHA`, `COPY --from=eval personas.yaml /app/eval/personas.yaml`), and compose `additional_contexts` + a dev read-only bind mount. It depends on nothing.
- **Customers seam.** `customers/service.py` + `repository.py`: the public country map and the document lookup. It depends on nothing.
- **LLM override seam.** `core/llm/client.py` `model_overrides` (D15). It depends on nothing.
- **Timeline domain.** `audit/schemas.py` (D23 schemas), `audit/repository.py` (read queries), and the new `audit/timeline.py` (filters, D18 outcome, turn assembly, D20 link). It depends on the customers seam.
- **Personas + admin router.** The new `identity/personas.py` (catalog loader, `PersonaEntry`, `PersonaCredentials`, credentials via `generate_password`), the new `api/v1/staff_admin.py`, and the mount in `api/v1/__init__.py`. It depends on the settings and customers seams.
- **Staff routes.** `api/v1/staff.py`: list, timeline and system routes, plus `get_any_conversation`. It depends on the timeline domain and settings.
- **Report layer.** `eval/harness/metrics.py` (per-run aggregate), `report.py` (per-run columns, mean, min–max, baseline, labels, error analysis, R9 redaction, judge section, NLU section slot), and `checks.py` (`category` in the verdict). It depends on nothing.
- **NLU comparison.** The new `eval/harness/nlu_eval.py` (D12 derivation, D13 metrics, in-memory sink, `render`). It depends on the LLM override seam.
- **Runner.** `eval/harness/runner.py`, `clone.py`, `__main__.py` and the `Makefile`: one FILE_COPY clone, per-run resets, `RUNS`, `NLU`, the folder naming, the heldout guard and the new meta. It depends on the report layer and the NLU comparison.
- **Generated client.** `frontend/src/client/*` via `make client`. It depends on the staff routes, the admin router and the running stack.
- **Docs.** `04` §3, `05` §4 and §7, `07` §8 (T5), and `decision-log.md` (T13, after the smoke result exists).

## Build order

1. The seams with no dependencies go first (T1 settings/image, T2 customers, T3 LLM override), next to the two chains that need nothing (T4 report layer, T5 docs).
2. The stack comes up once (T6, alone). It needs T1's Dockerfile and compose changes so the rebuilt image carries them. The FILE_COPY clone time is measured then (D11), because the timeline integration test and `make client` need Postgres, Redis and nginx.
3. The timeline domain (T7) needs T2's country map and the running stack for its integration test. The personas router (T8) needs T1 and T2. The NLU comparison (T9) needs T3's `model_overrides`. The three touch disjoint files.
4. The staff routes (T10) need T7's schemas and functions, and T8's edit of `test_r13_routes.py` (the same file, so they are chained). The runner (T11) needs T4's `write_report` signature and T9's `compare`/`render`.
5. `make client` (T12) needs every new route mounted (T8, T10).
6. The live proof (T13, alone) needs the complete runner (T11) and runs last, after the human's go-ahead.

## Touch map

| File | New / modified | Change | Task |
|---|---|---|---|
| `backend/app/core/config.py` | modified | `personas_path`, `git_sha` | T1 |
| `backend/Dockerfile` | modified | `ARG GIT_SHA=unknown` → `ENV`, `COPY --from=eval personas.yaml` | T1 |
| `docker/docker-compose.base.yml` | modified | backend `build.additional_contexts: {eval: ../eval}` | T1 |
| `docker/docker-compose.dev.yml` | modified | `../eval/personas.yaml:/app/eval/personas.yaml:ro` | T1 |
| `backend/app/domains/customers/service.py` | modified | public `COUNTRY_LABELS`, `get_document` | T2 |
| `backend/app/domains/customers/repository.py` | modified | `fetch_document` | T2 |
| `backend/app/core/llm/client.py` | modified | `model_overrides` seam | T3 |
| `eval/harness/metrics.py` | modified | per-run aggregate (mean, min–max) | T4 |
| `eval/harness/report.py` | modified | new `write_report`, labels, error analysis, R9, judge, NLU slot | T4 |
| `eval/harness/checks.py` | modified | `category` in `case_verdict` | T4 |
| `eval/tests/test_aggregate.py` | new | test 3 | T4 |
| `docs/solution-docs/04-contracts.md` | modified | §3 rows + `get_any_conversation` exception | T5 |
| `docs/solution-docs/05-evaluation-plan.md` | modified | §4 isolation sentence, §7 command/preconditions/folder | T5 |
| `docs/solution-docs/07-execution-plan.md` | modified | §8 D7 row → decision-log entry | T5 |
| `backend/app/domains/audit/schemas.py` | modified | D23 schemas | T7 |
| `backend/app/domains/audit/repository.py` | modified | read queries (events, llm_calls, messages by conversation) | T7 |
| `backend/app/domains/audit/timeline.py` | new | filters, D18 outcome, list, turn assembly, D20 | T7 |
| `backend/tests/integration/test_staff_timeline.py` | new | test 2 | T7 |
| `backend/app/domains/identity/personas.py` | new | catalog loader, schemas, credentials | T8 |
| `backend/app/api/v1/staff_admin.py` | new | admin router: personas + credentials | T8 |
| `backend/app/api/v1/__init__.py` | modified | mount `staff_admin` | T8 |
| `backend/tests/unit/test_r13_routes.py` | modified | admin rule for `/staff/personas*` (T8); `get_any_conversation` exception (T10) | T8, T10 |
| `eval/harness/nlu_eval.py` | new | D12, D13, D15 | T9 |
| `eval/tests/test_nlu_eval.py` | new | test 4 | T9 |
| `backend/app/api/v1/staff.py` | modified | list, timeline, system routes; `get_any_conversation` | T10 |
| `eval/harness/runner.py` | modified | one clone, resets, RUNS, NLU, folder, meta, guard | T11 |
| `eval/harness/clone.py` | modified | `STRATEGY FILE_COPY`, clone name from folder | T11 |
| `eval/harness/__main__.py` | modified | `--runs`, `--nlu`, exit 2 on the heldout guard | T11 |
| `Makefile` | modified | `RUNS`, `NLU` on `eval`; `eval-pii-check` help text | T11 |
| `frontend/src/client/*.gen.ts` | regenerated | `make client` only | T12 |
| `docs/solution-docs/decision-log.md` | modified | "Model per step (D7)", Proposed | T13 |
| `eval/reports/dev-<sha10>/{report.md,metrics.json,meta.json}` | new (generated) | D2 proof artifact | T13 |

Read only: `eval/scenarios/**` (every `heldout` path included), `eval/driver/`, `eval/simulator/`, `eval/nlu/nlu_v1_smoke.yaml`, `eval/personas.yaml`, `pipeline/load/demo_reset.py`.

## Risks and mitigations

- **A staff route leaks raw text or the LLM input/output (R5 spirit, D17).** T7 selects only `content_masked` and never `content`, `input_text` or `output_json`, and the integration test seeds a distinct raw `content` and asserts it is absent from the timeline. See T7.
- **The timeline route loses its scoping, or another claimed route switches to `get_any_conversation` (R13).** T10 amends `test_r13_routes.py` so exactly one path may use `get_any_conversation`, and it demonstrates the failure once with the dependency removed. See T10.
- **Admin-only routes under `/staff` break the existing R13 rule.** T8 changes the rule for `/staff/personas*` in the same task that adds them, so the suite never goes red between tasks. See T8.
- **Credentials are logged or cached (R10).** T8 returns `Cache-Control: no-store`, adds no log line carrying the values, and never opens `data/secrets/credentials.csv`. Its Verify greps the new files for `credentials.csv` and for `log` calls near the values.
- **A migration sneaks in for `created_at`.** Q1 is resolved before T7, and no task lists `backend/app/alembic/versions/`.
- **The FILE_COPY clone is slow or fails on this host.** T6 measures it once and records it before any eval code depends on it. If `STRATEGY FILE_COPY` errors, T6 stops and reports to the human instead of proceeding.
- **One clone reused across runs leaks state between runs.** T11 restores and verifies every distinct persona before every run and clears that system's `turns:*` keys. Any diff aborts with `RestoreDiffError`. The per-case restore stays.
- **The NLU comparison bypasses R5/R7/R11.** T3 adds the override only inside `StructuredLLMClient`, so `find_pii`, the retry loop and the ledger run unchanged. T3's Verify runs `test_llm_client.py` and `test_r5_llm_guard.py`. The served graph never passes `model_overrides` (T3 acceptance, checked with grep).
- **A held-out run happens by accident, or R9 leaks.** T11's guard runs before case loading and before any clone, and exits 2. T4's report prints only case ids and check names for `suite == "heldout"`. No task writes under `eval/scenarios/heldout*` or `_staging/heldout`, and T13 checks the git diff of those paths is empty.
- **`write_report`'s signature changes before the runner catches up.** T4 changes the writer, and T11 (the next eval wave) updates its only caller. Nothing runs `make eval` between them, because T13 is last.
- **Live calls without consent.** Only T13 makes live LLM calls (about 65–75, stated in the task), and it runs alone after the human's go-ahead. T6 and T12 need the stack but make 0 LLM calls. Every test uses a fake LLM or none.
- **Stale ruff debt makes a Verify fail for reasons outside the task.** Touched legacy harness files are linted with `--ignore E501,RUF005,UP047` and are not format-checked (see Facts).

## Tests

1. `backend/tests/unit/test_r13_routes.py` (amended, R13). The admin part is written by **T8** and the `get_any_conversation` exception by **T10**.
2. `backend/tests/integration/test_staff_timeline.py::test_filter_counts_match_sql` (A1 Done-when). Written by **T7**.
3. `eval/tests/test_aggregate.py::test_proposed_runs_aggregate`. Written by **T4**.
4. `eval/tests/test_nlu_eval.py::test_derive_and_score`. Written by **T9**.

No other test. The runner's clone and reset logic, the heldout guard and the report contents are proved by the CLI checks in T11 and the live run in T13.

Success criteria → task: SC1 → T10 (T8), SC2 → T7, SC3 → T4 + T9, SC4 → T13 (built by T4, T9, T11), SC5 → T11 (re-checked in T13), SC6 → T6, SC7 → T5 + T13, SC8 → verifier `make check` + T12, SC9 → T13.

## Tasks

- [ ] T1: Settings and image wiring for personas and git SHA
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "Backend internals" (the `config.py`, `Dockerfile` and compose bullets) and D21, D22; `backend/app/core/config.py`; `backend/Dockerfile`.
  - Acceptance: `Settings` has `personas_path: Path = Path("/app/eval/personas.yaml")` (env `PERSONAS_PATH`) and `git_sha: str = "unknown"` (env `GIT_SHA`). The Dockerfile declares `ARG GIT_SHA=unknown` and `ENV GIT_SHA=$GIT_SHA`, and `COPY --from=eval personas.yaml /app/eval/personas.yaml` (the named context). Base compose backend `build.additional_contexts: {eval: ../eval}`. The dev overlay adds the read-only bind mount `../eval/personas.yaml:/app/eval/personas.yaml:ro` to the backend's `volumes`. No image is built and the stack is not started (T6 does that).
  - Verify: `cd backend && uv run python -c "from app.core.config import Settings; s=Settings(); assert str(s.personas_path)=='/app/eval/personas.yaml' and s.git_sha=='unknown'" && PERSONAS_PATH=/tmp/p.yaml GIT_SHA=abc uv run python -c "from app.core.config import Settings; s=Settings(); assert str(s.personas_path)=='/tmp/p.yaml' and s.git_sha=='abc'" && uv run ruff check app/core/config.py && uv run ruff format --check app/core/config.py && uv run mypy app/core/config.py && cd .. && docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml config | grep -E "additional_contexts|eval/personas.yaml" && grep -nE "ARG GIT_SHA=unknown|COPY --from=eval personas.yaml" backend/Dockerfile`
  - Files: `backend/app/core/config.py`, `backend/Dockerfile`, `docker/docker-compose.base.yml`, `docker/docker-compose.dev.yml`

- [ ] T2: Customers service seam — public country map and document lookup
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/customers/service.py`; `backend/app/domains/customers/repository.py`; spec D19 (country mapping) and D22 (document type + number).
  - Acceptance: `customers.service` exports `COUNTRY_LABELS` (the existing `México→MX / Colombia→CO / Argentina→AR` map, now public; existing callers keep working) and `async get_document(customer_id: str) -> tuple[str, str]` returning `(document_type, document_number)` as stored, raising `ToolUnavailable` for an unknown customer like its siblings. It calls a new `repository.fetch_document(customer_id)` (SQL `SELECT document_type, document_number FROM bank.customers WHERE customer_id = :customer_id`). Neither value is logged. Both names are added to `__all__`.
  - Verify: `cd backend && uv run python -c "from app.domains.customers.service import COUNTRY_LABELS, get_document; assert COUNTRY_LABELS=={'México':'MX','Colombia':'CO','Argentina':'AR'}" && uv run ruff check app/domains/customers && uv run ruff format --check app/domains/customers && uv run mypy app/domains/customers && uv run lint-imports`
  - Files: `backend/app/domains/customers/service.py`, `backend/app/domains/customers/repository.py`

- [ ] T3: `model_overrides` seam in the LLM client (D15)
  - Depends on: nothing
  - Read exactly these: `backend/app/core/llm/client.py`; `backend/app/core/llm/registry.py`; spec D15 and §"Contracts" → "Backend internals" (`client.py` bullet).
  - Acceptance: `get_llm_client(settings=None, sink=None, *, model_overrides: Mapping[Step, str] | None = None)` passes the overrides to `StructuredLLMClient`. For an overridden step, the chat model is built with the override model id, and the ledger `LLMCallRecord.model_id`, the `llm.call` log line and `cost_usd` use it. Temperature and prompt stay those of the step. With no override, behaviour is byte-for-byte unchanged, and the existing 2-arg `chat_model_factory` lambdas in `tests/unit/test_llm_client.py` keep working without edits. The `find_pii` refusal, the retry loop and the sink still run on overridden calls. No code under `backend/app/domains/` passes `model_overrides`. No new test.
  - Verify: `cd backend && uv run pytest tests/unit/test_llm_client.py tests/unit/test_r5_llm_guard.py -q && uv run python -c "import inspect; from app.core.llm import get_llm_client; p=inspect.signature(get_llm_client).parameters['model_overrides']; assert p.kind is p.KEYWORD_ONLY and p.default is None" && ! grep -rn "model_overrides" app/domains && uv run ruff check app/core/llm/client.py && uv run ruff format --check app/core/llm/client.py && uv run mypy app/core/llm && uv run lint-imports`
  - Files: `backend/app/core/llm/client.py`

- [ ] T4: Report layer — per-run aggregate, labels, error analysis, R9, judge section
  - Depends on: nothing (Q2's answer must be in the state file before dispatch)
  - Read exactly these: `eval/harness/report.py`; `eval/harness/metrics.py`; spec D5, D6, D7, D8, D9 and §"Contracts" → "Eval harness" (the `metrics.json` and `meta.json` shapes).
  - Acceptance:
    - `report.write_report(out, runs, meta, *, nlu=None, nlu_section=None)`, where `runs` maps system → a list of per-run verdict lists (proposed has N, baseline has 1).
    - `metrics.json` is `{"runs": {"proposed": [compute_all(run) …], "baseline": [compute_all(run)]}, "aggregate": {...}, "nlu": nlu or {}}`. `metrics.py` gets a pure aggregate function: for each `05` §6 metric, the per-run values, the mean and min–max across runs. Runs are never pooled into one CI.
    - `report.md`, main table: one column per proposed run (value, n, Wilson CI), then proposed mean (min–max), then baseline with its CI. The language-variant and segment breakdowns show proposed mean (min–max) and baseline, with n per group and the existing small-n caveat.
    - Every table header carries its label via `label_for(meta["driver"])` (`scripted` → "offline evaluation", `simulator` → "simulation").
    - Error analysis is counts by case `category` × failed check, per system, summed over that system's runs, with the run count in the header. `checks.case_verdict` adds `"category": ev.case.category`.
    - For `meta["suite"] == "heldout"`, failure lines carry only `case_id` and failed-check names. Dev reports keep today's examples.
    - The "Reply quality (LLM judge)" section follows the Q2 answer, and reads "pending D7-B4" when no agreement report exists.
    - `nlu_section` lines are inserted verbatim under an "NLU comparison" heading when given.
    - The header reads the new meta: one `clone_seconds` float, `clone_strategy`, `resets`, `reset_diffs`, `runs`, `dirty`.
    - `eval/tests/test_aggregate.py::test_proposed_runs_aggregate`: three fake proposed runs and one baseline run give the per-run values, the mean, the min–max and an unchanged baseline column in `metrics.json` and in the `report.md` table. No LLM.
  - Verify: `uv run --project backend pytest eval/tests/test_aggregate.py eval/tests/test_metrics.py eval/tests/test_checks.py -q && uv run --project backend ruff check --config backend/pyproject.toml eval/tests/test_aggregate.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/tests/test_aggregate.py && uv run --project backend ruff check --config backend/pyproject.toml --ignore E501,RUF005,UP047 eval/harness/metrics.py eval/harness/report.py eval/harness/checks.py`
  - Files: `eval/harness/metrics.py`, `eval/harness/report.py`, `eval/harness/checks.py`, `eval/tests/test_aggregate.py`

- [ ] T5: Contract and evaluation-plan docs (04 §3, 05 §4/§7, 07 §8)
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "HTTP" and "Docs amended by this card", D3, D6, D10, D16; `docs/solution-docs/04-contracts.md` §3 (lines 84-122); `docs/solution-docs/05-evaluation-plan.md` §4 and §7 (lines 41-52, 76-).
  - Acceptance:
    - `04` §3: the stretch row `GET /staff/conversations?filters · …/timeline` becomes the two real rows (with the filters, response schemas and `404`). A row is added for `GET /staff/system`. The `/staff/personas*` row gains the `Cache-Control: no-store` and `404` notes. The Auth paragraph states the one `get_any_conversation` exception (the timeline only, read-only, agent and admin).
    - `05` §4: "Each run starts from a fresh clone of the golden DB" becomes the D10 sentence ("each run starts from a clone whose suite personas are verified equal to golden", one FILE_COPY clone per invocation).
    - `05` §7: `make eval SUITE=heldout SYSTEM=both RUNS=3 NLU=suite` with its three human preconditions (100% review of `_staging/heldout/`, a human runs `make eval-freeze`, the D1.5 targets recorded in `05` §6), the harness refusal, the `eval/reports/<suite>-<sha10>[-k]/` layout and which files are committed.
    - `07` §8 row D7 points to `decision-log.md` "Model per step (D7)" (Proposed; the entry itself is written by T13).
  - Verify: `grep -n "get_any_conversation" docs/solution-docs/04-contracts.md && grep -n "GET /staff/system" docs/solution-docs/04-contracts.md && grep -n "verified equal to golden" docs/solution-docs/05-evaluation-plan.md && grep -n "SUITE=heldout SYSTEM=both RUNS=3 NLU=suite" docs/solution-docs/05-evaluation-plan.md && grep -n "Model per step (D7)" docs/solution-docs/07-execution-plan.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/05-evaluation-plan.md`, `docs/solution-docs/07-execution-plan.md`

- [ ] T6: Bring the dev stack up and measure one FILE_COPY clone (D11) — ALONE, needs the human's OK
  - Depends on: T1 (the Dockerfile and compose changes the rebuilt image must carry)
  - Read exactly these: `README.md` (the `make up` section); `eval/harness/clone.py`; spec D10, D11.
  - Acceptance:
    - **0 LLM calls.** The orchestrator has the human's OK to start the stack (Boundaries: "ask first").
    - `make up` finishes healthy. The backend container has `/app/eval/personas.yaml` (the bind mount) and `GIT_SHA=unknown`.
    - One `CREATE DATABASE latam_eval_measure_filecopy TEMPLATE latam_golden STRATEGY FILE_COPY` is timed from the host (end golden's other sessions first, as `clone.create` does), then the clone is dropped.
    - The measured seconds, the date and the host are appended to the state file (SC6).
    - If FILE_COPY errors, stop and report; don't fall back.
    - The stack is left **up** for T7 and T12.
  - Verify: `make up && curl -sf http://localhost/api/v1/health && docker exec latam-cs-backend-1 test -r /app/eval/personas.yaml && docker exec latam-cs-backend-1 printenv GIT_SHA && uv run --project backend python -c "import os,time,psycopg; from eval.harness.clone import dsn, _terminate, GOLDEN_DB; c=psycopg.connect(dsn('postgres'),autocommit=True); _terminate(c,GOLDEN_DB); t=time.monotonic(); c.execute('CREATE DATABASE latam_eval_measure_filecopy TEMPLATE latam_golden STRATEGY FILE_COPY'); print('clone_seconds', round(time.monotonic()-t,1)); c.execute('DROP DATABASE latam_eval_measure_filecopy WITH (FORCE)')" && docker exec latam-cs-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -Atc "select count(*) from pg_database where datname like '"'"'latam_eval_%'"'"'"'` (the last count is 0)
  - Files: `docs/plans/d7-a-timeline-heldout-report.state.md` (implementer section only)

- [ ] T7: Timeline domain — schemas, read queries, filters, D18 outcome, and the filter-count integration test
  - Depends on: T2 (`customers.service.COUNTRY_LABELS`); T6 (Postgres + Redis up, for the integration test). Q1's answer must be in the state file.
  - Read exactly these: spec D17, D18, D19, D20, D23 and §"Contracts" → "Schemas" and "Test list" item 2; `backend/app/domains/audit/repository.py`; `backend/tests/integration/conftest.py` (`it_db`, `it_env`, the fixture customers `CLI-TFMULTI00001` MX, `CLI-TFSINGLE0002` CO, `CLI-TFBLOCKD0003` AR).
  - Acceptance:
    - `audit/schemas.py` adds the D23 schemas verbatim from the spec: `ConversationSummary`, `ConversationPage`, `LLMCallView`, `TimelineEvent`, `TurnTimeline`, `ConversationTimeline`, `SystemInfo`, `StepInfo`, `PolicyFileInfo`. It stays stdlib + pydantic only.
    - `audit/repository.py` gains read-only queries by conversation (conversation page with the joins, audit events, llm_calls, masked messages, handoffs).
    - The new `audit/timeline.py` implements:
      - D19's ANDed filters (the `country` join on `bank.customers.country` mapped through `COUNTRY_LABELS`, without importing `customers.repository`), newest first, `limit` 1–200 (default 50), `offset`, and `total` counting every match;
      - the D18 outcome precedence, with `null` when there is no `reply_sent`;
      - turn assembly: a turn = the messages + events sharing a `turn_id`, in order, with `customer_text_masked`/`bot_text_masked` from `content_masked` only, and `rules` (`rule_hit`), `tools` (`tool_call` + `tool_result`), `sources` (a union in first-seen order), `policy_version`, `llm_calls` (no `input_text`/`output_json`), `latency_ms` (`reply_sent.at` − the customer message's `created_at`) and `cost_usd` (the sum, or `None` if none is priced);
      - `langfuse_url` = `<LLMSettings().langfuse_host>/trace/<llm_calls.langfuse_trace_id>`, or `null` (D20). Record in the state file whether Langfuse v4's web route matches `/trace/<id>`. If it doesn't, report it as a spec amendment instead of changing it.
    - `backend/tests/integration/test_staff_timeline.py::test_filter_counts_match_sql`:
      - seeds about 6 conversations over the 3 fixture customers (es/pt, MX/CO/AR, 2 intents, each D18 outcome, one handoff, 2 dates), each message's `content` holding a distinct raw marker;
      - for each filter alone and one combination, `total` equals a hand-written SQL count;
      - one conversation's timeline has its turns in order, `customer_text_masked == content_masked`, the raw marker nowhere in the dumped JSON, and `llm_calls`/`cost_usd` from the seeded ledger.
    - No LLM.
  - Verify: `cd backend && uv run pytest tests/integration/test_staff_timeline.py -q -rs` (it must **pass, not skip**) `&& uv run ruff check app/domains/audit tests/integration/test_staff_timeline.py && uv run ruff format --check app/domains/audit tests/integration/test_staff_timeline.py && uv run mypy app/domains/audit && uv run lint-imports`
  - Files: `backend/app/domains/audit/schemas.py`, `backend/app/domains/audit/repository.py`, `backend/app/domains/audit/timeline.py`, `backend/tests/integration/test_staff_timeline.py`

- [ ] T8: Persona catalog and credential lookup on an admin-only router (R13 admin part)
  - Depends on: T1 (`Settings.personas_path`, `Settings.credentials_seed`); T2 (`customers.service.get_document`)
  - Read exactly these: spec D22 and §"Contracts" → "HTTP" (the two `/staff/personas` rows) and "Schemas" (`PersonaEntry`, `PersonaCredentials`); `backend/app/api/v1/admin.py` (the admin router to mirror); `backend/tests/unit/test_r13_routes.py`.
  - Acceptance:
    - The new `identity/personas.py` loads `settings.personas_path` (`personas:` list; `customer_id`, `split` and `notes` are non-traits, and every other key is a trait) into `PersonaEntry`. It defines `PersonaCredentials` and builds credentials from `generate_password(customer_id, seed=settings.credentials_seed)` + `customers.service.get_document`.
    - The new `api/v1/staff_admin.py`: `APIRouter(prefix="/staff", dependencies=[Depends(require_role("admin")), Depends(require_csrf)])` with `GET /personas` → `list[PersonaEntry]` and `GET /personas/{customer_id}/credentials` → `PersonaCredentials`. It returns `404 not_found` for an id not in the catalog, and sets `Cache-Control: no-store`.
    - It is mounted in `api/v1/__init__.py`.
    - Nothing reads `data/secrets/credentials.csv`, and no log line carries a document number or password.
    - `test_r13_routes.py`: the staff rule becomes "every `/api/v1/staff/personas…` route has `("admin",)`, every other `/api/v1/staff/…` route has `("agent", "admin")`". Everything else in the test stays as strict as today.
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py -q && ! grep -n "credentials.csv" app/domains/identity/personas.py app/api/v1/staff_admin.py && uv run ruff check app/domains/identity/personas.py app/api/v1/staff_admin.py app/api/v1/__init__.py tests/unit/test_r13_routes.py && uv run ruff format --check app/domains/identity/personas.py app/api/v1/staff_admin.py app/api/v1/__init__.py tests/unit/test_r13_routes.py && uv run mypy app/domains/identity/personas.py app/api/v1/staff_admin.py && uv run lint-imports && PERSONAS_PATH=../eval/personas.yaml uv run python -c "from app.domains.identity.personas import load_catalog; c=load_catalog(); assert len(c)==52 and all(p.customer_id.startswith('CLI-') for p in c)"` (if the loader gets another name, use it and record it in the state file)
  - Files: `backend/app/domains/identity/personas.py`, `backend/app/api/v1/staff_admin.py`, `backend/app/api/v1/__init__.py`, `backend/tests/unit/test_r13_routes.py`

- [ ] T9: NLU comparison module — derivation, metrics, in-process run, rendering
  - Depends on: T3 (`get_llm_client(..., model_overrides=...)`)
  - Read exactly these: spec D12, D13, D14, D15 and "Test list" item 4; `backend/scripts/nlu_smoke.py` (the in-process analogue); `eval/simulator/simulator.py` lines 30-50 (how eval code imports `app`).
  - Acceptance:
    - The new `eval/harness/nlu_eval.py` (imports `app` only through the simulator's `sys.path` pattern; nothing in `runner.py` imports it at module level):
      - `NLU_MODELS = ("claude-sonnet-5-5", "claude-haiku-4-5-20251001")`.
      - `derive_suite_items(cases, personas_path)` takes the first `say` turn of each case, labelled with `labels.expected_intents`, `expected_language` and `language_variant`, with the country from the persona's `country` trait and `pending=None`.
      - `load_smoke_items(path)` reads `eval/nlu/nlu_v1_smoke.yaml` as it stands, with status labels.
      - `score(items, predictions)` returns macro intent-set P/R/F1, exact-set match with a Wilson CI, a multi-intent (≥2) slice, a `language_variant` breakdown (missing → `unknown`), and status accuracy only for smoke.
      - `async compare(source, cases, *, models=NLU_MODELS, nlu_fn=run_nlu, client_factory=get_llm_client) -> (nlu_dict, ledger_rows)` scores `keyword_nlu` (0 calls) plus `run_nlu` per model through `client_factory(sink=<in-memory sink>, model_overrides={"nlu": model})`, adds p50/p95 latency and the mean cost per call per model, and returns every `LLMCallRecord` as a JSON-able dict tagged `system="nlu:<model>"`.
      - `render(nlu_dict) -> list[str]` gives the markdown table(s), labelled "offline evaluation", with the caveat "Anthropic API; Bedrock serves the same models (ADR-028)".
    - `eval/tests/test_nlu_eval.py::test_derive_and_score`: derivation from a tmp scenario dir takes the first `say` with the seed's intents, and macro P/R/F1 and exact-set match are right on a hand-computed 4-utterance fixture (keyword vs a fake `run_nlu`, one multi-intent item). No network.
  - Verify: `uv run --project backend pytest eval/tests/test_nlu_eval.py -q && uv run --project backend python -c "from pathlib import Path; from eval.harness.nlu_eval import load_smoke_items, derive_suite_items; from eval.scenarios.schema import load_dir; assert len(load_smoke_items(Path('eval/nlu/nlu_v1_smoke.yaml')))==20; print(len(derive_suite_items(load_dir(Path('eval/scenarios/dev')), Path('eval/personas.yaml'))))" && uv run --project backend ruff check --config backend/pyproject.toml eval/harness/nlu_eval.py eval/tests/test_nlu_eval.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/harness/nlu_eval.py eval/tests/test_nlu_eval.py`
  - Files: `eval/harness/nlu_eval.py`, `eval/tests/test_nlu_eval.py`

- [ ] T10: Staff list, timeline and system routes with `get_any_conversation` (R13 timeline part)
  - Depends on: T7 (`audit.schemas` + `audit.timeline` functions); T8 (`test_r13_routes.py` already carries the admin rule); T1 (`Settings.git_sha`)
  - Read exactly these: `backend/app/api/v1/staff.py`; `backend/tests/unit/test_r13_routes.py`; spec D16, D19, D21 and §"Contracts" → "HTTP".
  - Acceptance:
    - `staff.py` gains `get_any_conversation(conversation_id) -> ConversationRow`, which returns the conversation or `404 not_found`. It is exported next to `get_claimed_conversation` and used **only** by `GET /conversations/{conversation_id}/timeline` → `ConversationTimeline`.
    - `GET /conversations` → `ConversationPage`. The filters are typed query params, so an invalid value is `422`, and `limit` is `ge=1, le=200`.
    - `GET /system` → `SystemInfo`:
      - `git_sha` from settings; `app_env` and `llm_disabled` from `Settings`, `llm_provider` from `LLMSettings`;
      - for `nlu`, `compose` and `handoff_summary`: `model_id` via `MODEL_REGISTRY`/`STEP_PROVIDER`, `TEMPERATURE`, and the prompt label from each node's `_PROMPT`;
      - `get_policies().hash`, and each `policies/*.yaml` sha256 (`registry._DEFAULT_POLICIES_DIR`).
    - `/messages` and `/stream` are unchanged.
    - `test_r13_routes.py`: exactly `/api/v1/staff/conversations/{conversation_id}/timeline` calls `get_any_conversation`, and every other path under the claimed prefix still calls `get_claimed_conversation`. Also assert that the timeline does not call `get_claimed_conversation`, and that no other path calls `get_any_conversation`.
    - Demonstrate once that removing the timeline's dependency makes the test fail, revert, and note it in the state file (SC1).
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/staff.py tests/unit/test_r13_routes.py && uv run ruff format --check app/api/v1/staff.py tests/unit/test_r13_routes.py && uv run mypy app/api/v1/staff.py && uv run lint-imports`
  - Files: `backend/app/api/v1/staff.py`, `backend/tests/unit/test_r13_routes.py`

- [ ] T11: Runner — one FILE_COPY clone, per-run resets, `RUNS`/`NLU`, folder naming, heldout guard, meta
  - Depends on: T4 (`report.write_report(out, runs, meta, *, nlu, nlu_section)`, `report.label_for`); T9 (`nlu_eval.compare`, `nlu_eval.render`)
  - Read exactly these: `eval/harness/runner.py`; spec D2, D3, D4, D6, D10 and §"Contracts" → "Eval harness"; `eval/scenarios/freeze.py` (`check`).
  - Acceptance:
    - `python -m eval.harness … --runs N (default 1) --nlu off|smoke|suite (default off)`. The `Makefile` `eval` target passes `--runs $(or $(RUNS),1) --nlu $(or $(NLU),off)`, and `eval-pii-check`'s help says `RUN=<folder>`.
    - **Heldout guard.** Before loading cases, linting or cloning, `--suite heldout` needs `eval/scenarios/heldout.lock` to exist and `freeze.check(<eval/scenarios>)` to return `[]`. Otherwise it prints a one-line reason naming the freeze preconditions and exits 2 (not via `ap.error`'s usage dump).
    - **One clone per invocation.** `clone.create` uses `STRATEGY FILE_COPY` and takes a folder-derived name (`-` → `_`). It is used by every run of every system and dropped in `finally`.
    - **Resets.** Before each run (proposed ×N, then baseline ×1), `restore_persona` + `verify_persona` run for every distinct persona in the selected cases, and then that system's `turns:*` keys are cleared. A diff aborts with `RestoreDiffError`. The per-case restore after writing cases stays.
    - **NLU.** When `--nlu` isn't `off`, `nlu_eval` is imported lazily and `compare` runs once. Its ledger rows are appended to `llm_calls.jsonl` **before** the PII scan.
    - **Output.** The folder is `eval/reports/<suite>-<sha10>[-k]/` (`git rev-parse --short=10 HEAD`; `-2`, `-3` when it exists). `meta.json` adds `runs`, `clone_strategy: "FILE_COPY"`, a single `clone_seconds`, `resets`, `reset_diffs: 0`, `dirty` (`git status --porcelain` non-empty), `nlu: {source, n, models}`, and `label` via `report.label_for`. It keeps `git_sha`, `suite_hash`, `policy_hash`, `models`, `provider`, `restore_count` and `pii_hits`.
    - The existing `test_runner_faults.py`/`test_runner_abort.py` still pass. No live run in this task.
  - Verify: `uv run --project backend pytest eval/tests/test_runner_faults.py eval/tests/test_runner_abort.py -q && uv run --project backend python -m eval.harness --help | grep -q -- '--runs' && uv run --project backend python -m eval.harness --help | grep -q -- '--nlu' && make -n eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke | grep -q -- '--runs 3' && make -n eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke | grep -q -- '--nlu smoke' && make -n eval | grep -q -- '--nlu off' && grep -n "STRATEGY FILE_COPY" eval/harness/clone.py && { uv run --project backend python -m eval.harness --suite heldout --system proposed; test $? -eq 2; } && docker exec latam-cs-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -Atc "select count(*) from pg_database where datname like '"'"'latam_eval_%'"'"'"'` (0, so the guard made no clone) `&& uv run --project backend ruff check --config backend/pyproject.toml --ignore E501,RUF005,UP047 eval/harness/runner.py eval/harness/clone.py eval/harness/__main__.py`
  - Files: `eval/harness/runner.py`, `eval/harness/clone.py`, `eval/harness/__main__.py`, `Makefile`

- [ ] T12: Regenerate the frontend API client (`make client`)
  - Depends on: T8 and T10 (every new route mounted); T6 (the stack is up; the backend hot-reloads `app/`)
  - Read exactly these: `frontend/openapi-ts.config.ts`; spec D23.
  - Acceptance:
    - **0 LLM calls.** `make client` has regenerated `frontend/src/client/*.gen.ts`, and nothing there is hand-edited.
    - The generated types include `ConversationPage`, `ConversationTimeline`, `TurnTimeline`, `SystemInfo`, `PersonaEntry` and `PersonaCredentials`.
    - The frontend typecheck passes in the container.
    - No frontend source outside `src/client/` changes (B3 builds the screens).
  - Verify: `curl -sf http://localhost/api/v1/openapi.json | grep -q ConversationTimeline && make client && grep -q "ConversationTimeline" frontend/src/client/types.gen.ts && grep -q "PersonaCredentials" frontend/src/client/types.gen.ts && grep -q "SystemInfo" frontend/src/client/types.gen.ts && docker exec latam-cs-frontend-1 npm run typecheck && test -z "$(git status --porcelain -- frontend/src | grep -v '^.. frontend/src/client/')"`
  - Files: `frontend/src/client/types.gen.ts`, `frontend/src/client/sdk.gen.ts`, `frontend/src/client/index.ts`, `frontend/src/client/client.gen.ts` (whatever `make client` rewrites under `frontend/src/client/`)

- [ ] T13: Live D2 proof run and the "Model per step (D7)" decision-log entry — ALONE, needs the human's OK (about 65–75 live LLM calls)
  - Depends on: T11 (complete runner, which includes T4 and T9); T5 (`07` §8 already points to the entry); T6 (the stack is up)
  - Read exactly these: spec D2, D3, D14 and "Success criteria" 4, 5 and 9; `docs/solution-docs/decision-log.md` (the ADR-031 entry at line 181, for format).
  - Acceptance:
    - The orchestrator has stated the call count (**about 65–75 live calls, under $1, on the Anthropic API**: 5 `a-` cases × proposed ×3 ≈ 25–30, baseline 0, NLU smoke 20 × 2 models = 40) and has the human's go-ahead.
    - `make eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke` exits 0 and writes `eval/reports/dev-<sha10>[-k]/report.md` with everything SC4 lists: proposed runs 1-3 with the mean and min–max and a baseline column; the `language_variant` and segment breakdowns; error analysis by category × check; the NLU table for keyword and both models, with status accuracy; the ADR-028 caveat; a label on every table; and "pending D7-B4".
    - `meta.json` has `clone_strategy: "FILE_COPY"`, one `clone_seconds`, `resets: 4`, `reset_diffs: 0` and `pii_hits: 0`. `llm_calls.jsonl` has ≤ about 80 rows. `make eval-pii-check RUN=<folder>` reports 0 hits.
    - The heldout refusal is re-checked (exit 2, no clone).
    - `decision-log.md` gains "Model per step (D7) · **Proposed**", with the smoke NLU result for both models (the labelled numbers from the report, n=20), the ADR-028 caveat, and "final after the held-out NLU comparison".
    - No held-out path changed. If the run aborts (`LLMUnreachableError`, `RestoreDiffError`), stop and report; don't retry beyond the stated budget.
  - Verify: `make eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke && R=$(ls -td eval/reports/dev-* | head -1) && python3 -c "import json,sys; m=json.load(open('$R/meta.json')); assert m['clone_strategy']=='FILE_COPY' and isinstance(m['clone_seconds'],(int,float)) and m['resets']==4 and m['reset_diffs']==0 and m['pii_hits']==0, m" && test $(wc -l < $R/llm_calls.jsonl) -le 80 && grep -q "pending D7-B4" $R/report.md && grep -q "ADR-028" $R/report.md && grep -q "claude-haiku-4-5-20251001" $R/report.md && make eval-pii-check RUN=$(basename $R) && { uv run --project backend python -m eval.harness --suite heldout --system proposed; test $? -eq 2; } && grep -n "Model per step (D7)" docs/solution-docs/decision-log.md && test -z "$(git diff develop --stat -- eval/scenarios/heldout eval/scenarios/_staging/heldout eval/scenarios/heldout.lock)"`
  - Files: `docs/solution-docs/decision-log.md`, `eval/reports/dev-<sha10>/report.md`, `eval/reports/dev-<sha10>/metrics.json`, `eval/reports/dev-<sha10>/meta.json`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3, T4, T5 | | Nothing depends on anything yet. They cover five disjoint areas (config/Docker, customers, `core/llm`, the eval report layer, docs) with no shared file. No stack and no LLM. |
| W2 | T6 | **alone**: `make up` (image rebuild) and a 7.7 GB FILE_COPY clone on the shared Postgres. Needs the human's OK. 0 LLM calls. | Changes the shared environment. It needs T1's Dockerfile and compose changes in the image. |
| W3 | T7, T8, T9 | | T7 (audit domain + integration test, on the stack T6 left up; it creates its own throwaway `latam_it_*` DB), T8 (identity/admin router + R13 file) and T9 (eval NLU module) touch disjoint files. Their inputs (T1, T2, T3, T6) are all done. |
| W4 | T10, T11 | | T10 (`staff.py` + the R13 file after T8) and T11 (runner, clone, CLI, Makefile) share no file. T10 needs T7 and T8; T11 needs T4 and T9. |
| W5 | T12 | | Reads the running backend and rewrites only `frontend/src/client/`. 0 LLM calls. It needs every route (T8, T10). |
| W6 | T13 | **alone**: the live eval (about 65–75 LLM calls), which creates and drops a FILE_COPY clone and starts backend subprocesses. Needs the human's OK. | The end of both A2 chains. It runs last, on the complete runner. |
