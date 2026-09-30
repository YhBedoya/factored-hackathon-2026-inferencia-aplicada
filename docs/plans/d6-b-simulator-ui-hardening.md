# Plan: D6-B — G11 simulator, UI hardening, fixes

Spec: [`docs/specs/d6-b-simulator-ui-hardening.md`](../specs/d6-b-simulator-ui-hardening.md) · Branch: `feat/d6-b-simulator-ui-hardening`

## Facts checked against the repo

- Base is `develop` @ `d48d08d`. No new dependency is needed anywhere: `langchain-openai`, `httpx` and `pyyaml` are in `backend/pyproject.toml`; `radix-ui` (Dialog, used by `frontend/src/components/ui/dialog.tsx` and `OtpModal.tsx`) and `@playwright/test` 1.63.0 are in `frontend/package.json`. No lockfile changes, no migration.
- **`app` is NOT importable from `eval/` as things stand.** `uv run --project backend python -c "import app.core.llm"` from the repo root fails with `ModuleNotFoundError: No module named 'app'`. With `PYTHONPATH=backend` it succeeds (`get_llm_client`, `find_pii`, `KnownPii` and `eval.driver.driver` all import). `backend/pyproject.toml`'s `pythonpath = ["."]` applies only to pytest run from `backend/`.
  **Chosen import path (spec open question, planner's call):** `eval/simulator/simulator.py` puts `<repo>/backend` on `sys.path` before `from app.core.llm ...`, mirroring `backend/scripts/paraphrase_seeds.py` lines 30-39 (`_BACKEND_ROOT` + `sys.path.insert(0, ...)` + `# noqa: E402`). LLM access stays in `app.core.llm`. This works under `make eval` and under `uv run --project backend pytest eval/tests/...` from the repo root, with no Makefile or pyproject change. `LLMSettings` reads `env_file=("../.env", ".env")`, so from the repo root it finds the repo `.env`.
- `eval/` is not covered by `mypy app` or `lint-imports` (`backend/.importlinter` covers `app` only). Eval code is linted with `uv run --project backend ruff check --config backend/pyproject.toml <paths>` (the D5-B convention).
- `app/core/llm/registry.py` today: `Step = Literal["nlu", "compose", "handoff_summary", "paraphrase"]`; `paraphrase` is `{"openai": "gpt-6-luna"}`, `TEMPERATURE 1.0`, `STEP_PROVIDER = {"paraphrase": "openai"}`. `build_chat_model` picks the provider from `STEP_PROVIDER.get(step, settings.llm_provider)`, so a new `simulate` entry needs no change in `client.py`. No backend test asserts the exact contents of these dicts.
- `LLMClient.structured(*, step, prompt, system, user, schema)` (`client.py:127`). `StructuredLLMClient` refuses any `system + user` where `find_pii(...)` finds something (R5) — it cannot see names, hence spec D5. `app.core.pii`: `KnownPii(document_number, names)`, `find_pii(text, known) -> list[PiiMatch(kind, start, end)]`, `TOKEN_RE` matches `⟨(CARD|DOC|EMAIL|PHONE|NAME|ADDR)_\d+⟩` so already-tokenized text is never re-matched. `redact()` produces `⟨KIND⟩` without a number, so the simulator must build its own `⟨KIND_n⟩` numbering.
- The backend fake `ScriptedLLM` lives in `backend/tests/conftest.py`, which `eval/tests` cannot import cleanly. `eval/tests/test_simulator.py` defines its own tiny fake with an async `structured(...)` that records calls.
- `eval/driver/driver.py` (387 lines) helpers are private today: `_RunnerState` (`last_confirm_token`, `tx_list_open`), `_csrf_headers`, `_turn_input`, `_update_state`, `_ended_by_from_events` (only `mode human` → `handoff`, `ui.conversation_closed` → `closed`), `_post_and_collect` (opens `GET .../stream`, waits for `: connected`, then POSTs), `_play_turn`, `_run_case`. `run_case(case, *, base_url, otp_code, client=None, max_turns=12)` returns `not_runnable` when `setup.faults` or `setup.expire_session_before_turn` is set. `eval/driver/__init__.py` re-exports `EventRecord, Transcript, TurnInput, TurnRecord, run_case`.
- **The stream GET comes before the POST.** `GET /conversations/{id}/stream` depends on `get_owned_conversation`, so with the session cookie dropped the **stream open** answers `401 session_expired` before the turn's POST is ever sent. The driver must treat a 401 on the stream open or on the POST as the expiry signal. Either way the held request is the turn's POST, and it is sent exactly once after the re-login. The spec's "the post of turn N gets 401" covers the frontend, whose stream is long-lived.
- **Turn indexing for `expire_session_before_turn` is 0-based**, the same index as `enumerate(case.turns)` and `TurnRecord.index`. `schema.py` does not document it. The evidence is that both dev seeds with it set to `1` expire before their second turn (`d-card_block-expired_session-es-co-01`: `say`, then `confirm` "after a long pause"; `d-card_status-expired_session-pt-br-01`: `say`, then `say: Ainda estou aqui…`). T1 writes this into the `SetupBlock` docstring.
- `POST /api/v1/test-idp/sessions {customer_id}` returns a `MeResponse` body (`role, login_hint, display_name, country, customer_status`) and sets the `session` + `csrf_token` cookies (`backend/app/api/v1/test_idp.py:74`). `GET /api/v1/auth/me` returns the same shape. `display_name` is the first name only.
- **Planned public surface of `eval/driver/driver.py` (T1 creates it, T3 imports it; T1 records the final names in the state file):** `RunnerState` (renamed from `_RunnerState`, plus `last_tx_ids: list[str]` from the last `ui.transaction_list`), `is_not_runnable(case) -> bool` (true only for non-empty `setup.faults`), `open_session(client, persona) -> dict[str, Any]` (test-IdP login, returns the `MeResponse` JSON), `play_turn(client, conversation_id, kind, value, state, *, otp_code, persona, identity, expire_first: bool) -> tuple[int, list[EventRecord]]` (drops the cookies first when `expire_first`, and on a 401 re-logs in, calls `/auth/me`, compares `login_hint`/`display_name` with `identity`, and replays once per D8/D9), `ended_by_from_events(events)`. `Transcript.stop_reason: str | None = None`.
- `eval/harness/runner.py:269` `run(suite, system="both", *, driver=None, run_id=None, cases_filter=None)`. `play = driver or run_case`. The `meta` dict is built at line 309 and `write_report(out, verdicts, meta)` is in `report.py:184`; the ADR-031 caveat pattern is at `report.py:204-214`. `_play` skips `db_patches` cases before calling the driver (`runner.py:175`), so the D14 seed stays `not_run (db_patches)` whichever driver runs. The Makefile `eval` target is at line 97: `uv run --project backend python -m eval.harness --suite ... --system ... [--cases ...]`.
- `card_block` bug location: `backend/app/domains/conversation/flows/card_block.py::_select_card`. On the `Ask` branch (several cards, no hint) it returns without remembering `nlu.slots.block_kind`. On the `card_hint` resume turn the fresh NLU carries only the card hint, so `block_kind is None` → `_ask_block_kind`. `state["slots"]` is flow-local memory: only `card_block.py`, `replacement.py` and `nodes/smalltalk.py` write it. Test pattern: `backend/tests/unit/test_block_flows.py` (`ScriptedLLM`, `make_session("CLI-TFMULTI00001", fakebank_dir, llm)` with 2+ cards, the `6475` credit card, `asyncio.run`, no pytest-asyncio).
- Dev suite: 31 seed files in `eval/scenarios/dev/`. The 4 `a-` seeds have only the `.s` case, and the others have `.s/.p1/.p2`. `a-card_block-normal_resolution-es-co-01` turn 2 is today `La que termina en 5772, solo un bloqueo temporal, por favor.` Setup seeds: expiry `d-card_block-expired_session-es-co-01` and `d-card_status-expired_session-pt-br-01` (both `expire_session_before_turn: 1`); faults `d-card_block-tool_failure-es-co-01`, `d-card_unlock-tool_failure-pt-br-01`. The existing `db_patches` injection analogue is `d-transaction_search-injection-pt-br-01.yaml`. Write tools (every one goes in the D14 seed's `forbidden_tools`): `cards.lock_card`, `cards.unlock_card`, `cards.block_card`, `cards.order_replacement`, `disputes.create_claim` (`policies/tools.yaml`).
- **`make eval-paraphrase DIR=eval/scenarios/dev N=2` would also paraphrase the 4 `a-` seeds** (0 paraphrases each), which adds cases beyond D14 and breaks D10(b)'s 4/4. `paraphrase_seeds.py::_validate_dir` accepts any directory whose path ends in `scenarios/dev`. So the D14 seed is paraphrased alone from a scratch `<tmp>/scenarios/dev/` holding only that file, using the same script (`cd backend && uv run python scripts/paraphrase_seeds.py --dir <tmp>/scenarios/dev --n 2`), and then copied back. That is a paid OpenAI call and needs `OPENAI_API_KEY` in `.env`.
- Frontend: `lib/api.ts::withAuthRetry` redirects to `/login` on a failed refresh or a second 401. `routes/chat.tsx` holds `KNOWN_ERROR_CODES`, `handleTurnError` and the whole chat layout (`h-dvh flex-col`). The login form is inline in `routes/login.tsx` (react-hook-form + zod, `ME_QUERY_KEY` from `components/layout/AppShell`). Dictionaries are `src/lib/i18n/es.json` and `pt.json` (flat `"a.b": "..."` keys; `errors.*` at lines 49-57).
- Playwright (`frontend/playwright.config.ts`) runs against the **built** app (`npm run preview` on port 4173, `reuseExistingServer` unless `CI`), so every Playwright verify runs `npm run build` first, and only one frontend task may run at a time (they share `dist/` and port 4173). A stale preview server on 4173 serves the old build, so kill it before the run. `e2e/mock-api.ts::installMockApi(page, {password, fixtures, customer?})` has no `/auth/refresh` route (it falls to `404`) and no 401 hook. Its existing ES fixtures are card-info and unrecognized; the block fixtures are PT.
- Frontend commands: `npm run typecheck` (`tsc -p tsconfig.app.json --noEmit`), `npm run build` (`vite build && tsc -b`), `npx biome ci <paths>`.
- Golden DB for reading real ids (T5): `postgresql://postgres:postgres@localhost:5432/latam_golden`, which needs `make up`. This is read only.
- Docs: ADR-030 is at `docs/solution-docs/decision-log.md:173` (it has a "Temperature note (T10)" to mirror). `06-engineering-rules.md:27` carries the `openai` line ("eval paraphrase only, ADR-030"). The `07-execution-plan.md:442` row is "Paraphrase, simulator and judge model family".

## Components

- **Driver expiry + shared turn helpers** — `eval/driver/driver.py`. Depends on `eval/scenarios/schema.py` and the live API contract (`04` §3 "Auth").
- **`simulate` step** — `backend/app/core/llm/registry.py`. It depends on nothing new.
- **Simulator** — `eval/simulator/{__init__,simulator}.py` and `eval/prompts/simulate@v1.md`. Depends on the driver helpers, the `simulate` step, `app.core.pii`, and `app.core.llm.get_llm_client`.
- **Harness wiring (D15)** — `eval/harness/{__main__,runner,report}.py` and `Makefile`. It imports the simulator lazily, only when `--driver simulator`.
- **B4 fix** — `backend/app/domains/conversation/flows/card_block.py`.
- **Dev seeds** — `eval/scenarios/dev/*.yaml` (fact sheets, the D10 revert, the D14 seed).
- **Frontend expiry path** — `lib/api.ts` hold/replay, `SessionExpiredModal`, an extracted `LoginForm`, the `chat.tsx` wiring, and the Playwright mock hook and spec.
- **Frontend states + mobile** — the `chat.tsx` error/fallback mapping, the chat components, the dictionaries and the layout CSS.
- **Docs** — ADR-030 note, `06` §2, `07` §8.

## Build order

1. The W1 chains all start at once. Driver helpers (T1), harness wiring (T2), B4 fix (T4), seeds (T5), docs (T6) and the frontend expiry path (T7) share no files and don't depend on each other. T2 imports the simulator lazily, so it doesn't wait for T3.
2. The simulator (T3) needs T1's public turn helpers and `Transcript.stop_reason`. It reuses them by import, as the spec requires, so it can't run beside T1.
3. The frontend states (T8) edit `chat.tsx` and the dictionaries that T7 edits, and they share `dist/`/port 4173 for Playwright, so T8 goes after T7.
4. Live proofs (`make eval …`) belong to the verifier. They are paid, and the runner spins up backends and clones, so no implementer runs them.

## Touch map

| File | New/Mod | Change | Task |
|---|---|---|---|
| `eval/driver/driver.py` | mod | D8/D9 expiry replay, public helpers, `Transcript.stop_reason`, `RunnerState.last_tx_ids` | T1 |
| `eval/driver/__init__.py` | mod | re-export the new public helpers | T1 |
| `eval/scenarios/schema.py` | mod | `SetupBlock` docstring only (only `faults` is not runnable; 0-based index) | T1 |
| `eval/tests/test_driver.py` | mod | expiry test (test 3), faults still `not_runnable` | T1 |
| `eval/harness/__main__.py` | mod | `--driver scripted\|simulator`, lazy simulator import | T2 |
| `eval/harness/runner.py` | mod | `run(..., driver_name="scripted")` → `meta["driver"]` | T2 |
| `eval/harness/report.py` | mod | D2 caveat line when `meta.get("driver") == "simulator"` | T2 |
| `Makefile` | mod | `eval` target passes `--driver $(or $(DRIVER),scripted)`; help text | T2 |
| `backend/app/core/llm/registry.py` | mod | `simulate` step (D1) | T3 |
| `eval/simulator/__init__.py` | new | re-export `run_case_simulated`, `SimAction` | T3 |
| `eval/simulator/simulator.py` | new | the simulator | T3 |
| `eval/prompts/simulate@v1.md` | new | the `simulate@v1` prompt (ES + PT examples) | T3 |
| `eval/tests/test_simulator.py` | new | tests 1-2 | T3 |
| `backend/app/domains/conversation/flows/card_block.py` | mod | remember `block_kind` across the card question | T4 |
| `backend/tests/unit/test_card_block_memory.py` | new | test 6 (ES + PT) | T4 |
| `eval/scenarios/dev/*.yaml` (the choice seeds) | mod | `fact_sheet` (D4) | T5 |
| `eval/scenarios/dev/a-card_block-normal_resolution-es-co-01.yaml` | mod | turn 2 → `La que termina en 5772.` + fact_sheet | T5 |
| `eval/scenarios/dev/d-decline_explain-injection-es-mx-01.yaml` | new | D14 seed + 2 paraphrases | T5 |
| `docs/solution-docs/decision-log.md` | mod | ADR-030 "Simulator note (D6-B)" | T6 |
| `docs/solution-docs/06-engineering-rules.md` | mod | §2 `openai` line | T6 |
| `docs/solution-docs/07-execution-plan.md` | mod | §8 row decided for the simulator | T6 |
| `frontend/src/lib/api.ts` | mod | `sessionExpired` hold/replay controller in `withAuthRetry` | T7 |
| `frontend/src/components/chat/SessionExpiredModal.tsx` | new | modal + D8 comparison | T7 |
| `frontend/src/components/auth/LoginForm.tsx` | new | login form extracted from `routes/login.tsx` | T7 |
| `frontend/src/routes/login.tsx` | mod | uses `LoginForm` | T7 |
| `frontend/src/routes/chat.tsx` | mod | captures `MeResponse` at open, mounts the modal, fresh chat on drop | T7, then T8 |
| `frontend/src/lib/i18n/es.json`, `pt.json` | mod | modal strings (T7); error/fallback/loading strings (T8) | T7, then T8 |
| `frontend/e2e/mock-api.ts` | mod | `/auth/refresh`, 401 on the Nth turn POST, alternate customer login | T7 |
| `frontend/e2e/session-expiry.es.spec.ts` | new | tests 4-5 | T7 |
| `frontend/e2e/fixtures/expiry-confirm.sse`, `expiry-verified.sse` | new | ES lock confirm and read-back | T7 |
| `frontend/src/components/chat/MessageList.tsx`, `Composer.tsx`, `StatusIndicator.tsx` | mod | fallback/error/loading rendering, mobile | T8 |
| `frontend/src/index.css` | mod | mobile layout | T8 |

## Risks and mitigations

- **The simulator can't import `app` from the repo root.** T3 inserts `<repo>/backend` on `sys.path` (paraphrase_seeds.py precedent). T3's Verify runs from the repo root, and T2's `make -n` check confirms `make eval` runs from the root.
- **Raw bot text reaches the simulator prompt** (R5: names are invisible to the `core/llm` guard). T3 masks every bot turn with `find_pii(text, KnownPii(None, (display_name,)))` → `⟨KIND_n⟩`, fences it, and test 1 asserts the raw name appears in neither `system` nor `user`.
- **The model invents the OTP or a transaction id** (R2). T3 sends `otp_code` from the harness and only accepts `tx_ids` that are in `RunnerState.last_tx_ids`. The `otp` case in test 2 asserts the posted code is the harness code.
- **An expiry replay posts the turn twice, or resumes as someone else** (D8, R13-adjacent). T1 replays once, only when `login_hint`/`display_name` match. Test 3 counts the replayed POSTs and keeps the faults case `not_runnable`. On the frontend, test 5 proves a different customer re-sends nothing.
- **The first 401 comes from the stream GET, not the POST** (see Facts). T1's acceptance names both cases, and test 3's mock answers 401 on whichever request of turn N arrives first while the cookies are gone.
- **A2 (Dev A) also replays server-side**, so the turn would run twice. That's an open question in the spec, and it's out of this plan's hands. The verifier flags it, and the PR description asks Dev A.
- **Dev A's harness files conflict at merge** (A1-A4 also touch `eval/harness`). T2 is wiring only, a few lines per file, and is flagged for A's review in the PR.
- **The paraphrase run touches the `a-` seeds.** T5 paraphrases the D14 seed from a scratch dir (Facts), and its Verify asserts the 4 `a-` seeds still have exactly 1 case each.
- **The D14 seed breaks the mix targets or schema validation.** T5's Verify runs `make eval-mix DIR=eval/scenarios/dev` and `test_scenarios_valid.py`. If a target fails, T5 escalates. It doesn't edit `mix_targets.yaml`.
- **Held-out edited by accident.** T5's Verify runs `git status --porcelain -- eval/scenarios/heldout eval/scenarios/_staging/heldout`, which must print nothing.
- **The B4 fix regresses the other `card_block` paths.** T4 re-runs `test_block_flows.py` next to its new tests.
- **The expiry change breaks the existing Playwright flows** (`api.ts` is shared by every call). T7 re-runs `block.pt.spec.ts` (the confirm path). T8 re-runs `card-info.es` and `unrecognized.es` (handoff banner and errors).
- **Two frontend tasks build `dist/` concurrently.** They are in different waves, and T8 depends on T7.

## Tests

| Test | Task |
|---|---|
| 1. `eval/tests/test_simulator.py::test_bot_text_is_masked_before_prompt` (R5) | T3 |
| 2. `eval/tests/test_simulator.py::test_stop_conditions` (parametrized: goal→done, handoff_banner→handoff, never-stop→max_turns at 12, otp uses the harness code) | T3 |
| 3. `eval/tests/test_driver.py::test_expired_session_relogs_same_persona_and_replays_once` (+ faults still `not_runnable`) | T1 |
| 4. `frontend/e2e/session-expiry.es.spec.ts` "expiry → modal → re-login → confirmation resumes" | T7 |
| 5. `frontend/e2e/session-expiry.es.spec.ts` "different customer drops the held request" (R1/R13) | T7 |
| 6. `backend/tests/unit/test_card_block_memory.py::test_block_kind_survives_card_question_es` / `_pt` | T4 |
| 7. Live proofs, run by the verifier or a human, not by a task: `make eval SUITE=dev SYSTEM=proposed DRIVER=simulator` (report has the D2 caveat, `meta.json` `"driver": "simulator"`); `make eval SUITE=dev SYSTEM=proposed CASES=a-` 4/4; a scripted dev run with the 6 `expired_session` cases played; human hand-check of 10 simulator transcripts recorded in the state file | V3/V5 |

Success criteria → task: 1 → T3; 2 → T1 + T3; 3 → T2 + T3 (live proof by the verifier); 4 → T7 + T8 (`biome ci src`); 5 → T1 (live proof by the verifier); 6 → T4 + T5 (live proof by the verifier); 7 → T5; 8 → T6.

## Tasks

- [ ] T1: Driver expiry replay (D8/D9), shared public turn helpers and `Transcript.stop_reason`
  - Depends on: nothing
  - Read exactly these: `eval/driver/driver.py` (all of it); spec §"Decisions" D6-D9 and §"Contracts" → `eval/driver/driver.py`; `eval/tests/test_driver.py` (the `_case`/`_sse`/`_scripted_handler` pattern)
  - Acceptance:
    - `Transcript` gains `stop_reason: str | None = None`.
    - `run_case` returns `not_runnable` (zero HTTP calls) **only** for non-empty `setup.faults`, through a public `is_not_runnable(case)`.
    - For `expire_session_before_turn: N` (0-based, the `enumerate(case.turns)` index), the driver clears the `session` and `csrf_token` cookies just before turn N. The first 401 of that turn, whether on the stream GET or on the POST, triggers `POST /test-idp/sessions` for the same `case.persona`, then `GET /auth/me`. If `login_hint` and `display_name` equal the ones from the initial test-IdP login response, the turn's POST is sent **exactly once more** (the stream re-opened first, as usual). Otherwise the transcript ends `error` with `error="identity_mismatch"` and nothing is re-sent. A second 401 ends `error` (`session_expired`).
    - Make these public and add them to `__all__`: `RunnerState` (with `last_tx_ids: list[str]`, filled from the last `ui.transaction_list` `payload.options[].tx_id`), `open_session`, `play_turn` (expiry-aware), `ended_by_from_events`, `is_not_runnable`. Keep them usable by a second driver (the simulator imports them).
    - Update the `SetupBlock` docstring in `eval/scenarios/schema.py` (only `faults` makes a case not runnable; `expire_session_before_turn` is a 0-based turn index), and the `run_case` docstring.
    - Append the final public names and signatures to the state file.
  - Verify: `uv run --project backend pytest eval/tests/test_driver.py eval/tests/test_scenarios_valid.py -q && uv run --project backend ruff check --config backend/pyproject.toml eval/driver eval/scenarios/schema.py eval/tests/test_driver.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/driver eval/scenarios/schema.py eval/tests/test_driver.py`
  - Files: `eval/driver/driver.py`, `eval/driver/__init__.py`, `eval/scenarios/schema.py`, `eval/tests/test_driver.py`

- [ ] T2: Harness `DRIVER=` wiring, `meta.json` `driver` and the D2 report caveat (D15)
  - Depends on: nothing (the simulator import is lazy; T3 provides `eval.simulator.run_case_simulated` later)
  - Read exactly these: `eval/harness/__main__.py`; `eval/harness/runner.py` lines 269-329; `eval/harness/report.py` lines 184-237 (the ADR-031 caveat pattern); `Makefile` lines 97-98; spec §"Decisions" D2, D15 and §"Contracts" → CLI
  - Acceptance:
    - `python -m eval.harness` accepts `--driver {scripted,simulator}` (default `scripted`). `simulator` imports `run_case_simulated` from `eval.simulator` **inside that branch only**, and passes it as `run(..., driver=...)`.
    - `run()` gains a keyword `driver_name: str = "scripted"` that `__main__` sets, and `meta` gets `"driver": driver_name`.
    - `report.md` carries exactly `Driver: simulator (`gpt-6-luna`, temperature 1.0) — transcripts are not repeatable run to run` as a caveat paragraph when `meta.get("driver") == "simulator"`, placed like the ADR-031 caveat. A meta without `driver` (older runs) renders unchanged.
    - The Makefile `eval` recipe appends `--driver $(or $(DRIVER),scripted)`, and its `##` help mentions `DRIVER=scripted|simulator`.
    - No other change to A's files. Note in the state file that these edits are for A's review.
  - Verify: `uv run --project backend python -m eval.harness --help | grep -q -- '--driver' && make -n eval DRIVER=simulator SUITE=dev SYSTEM=proposed | grep -q -- '--driver simulator' && make -n eval | grep -q -- '--driver scripted' && uv run --project backend pytest eval/tests/test_runner_abort.py -q && uv run --project backend ruff check --config backend/pyproject.toml eval/harness/__main__.py eval/harness/runner.py eval/harness/report.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/harness/__main__.py eval/harness/runner.py eval/harness/report.py`
  - Files: `eval/harness/__main__.py`, `eval/harness/runner.py`, `eval/harness/report.py`, `Makefile`

- [ ] T3: `simulate` step and the goal-driven customer simulator (B1)
  - Depends on: T1 (`RunnerState`, `open_session`, `play_turn`, `ended_by_from_events`, `is_not_runnable`, `Transcript.stop_reason`; read their final names in the state file)
  - Read exactly these: spec §"Decisions" D1-D7 and §"Contracts" → `registry.py`, Prompt, `eval/simulator/simulator.py`; `backend/scripts/paraphrase_seeds.py` lines 1-60 and 91-130 (the `sys.path` import pattern, prompt loading, structured call); `eval/driver/driver.py` (the public helpers T1 made)
  - Acceptance:
    - `registry.py`: `Step` gains `"simulate"`; `MODEL_REGISTRY["simulate"] = {"openai": "gpt-6-luna"}`, `TEMPERATURE["simulate"] = 1.0`, `STEP_PROVIDER["simulate"] = "openai"`, with a one-line comment citing ADR-030 and the simulator note.
    - `eval/simulator/simulator.py` puts `<repo>/backend` on `sys.path` before importing `app.core.llm`/`app.core.pii` (the paraphrase_seeds pattern). It never imports `openai` or `langchain_openai`.
    - It defines `SimAction` and `run_case_simulated` exactly as in the spec contract, with the same call shape as `run_case`.
    - Behaviour:
      - `is_not_runnable(case)` → `not_runnable`.
      - Otherwise it runs `open_session` and `GET /auth/me` (for `display_name`), creates a conversation, sends turn 1 as the case's first `say` verbatim, then loops. Each loop masks every bot `message` text with `find_pii(text, KnownPii(None, (display_name,)))` → `⟨KIND_n⟩`, fences the bot turns in the user block, calls `llm.structured(step="simulate", prompt=PromptRef("simulate", 1), ..., schema=SimAction)` and plays the action through `play_turn`. Expiry applies at `expire_session_before_turn` too.
      - `otp` sends the harness `otp_code`. `confirm`/`cancel` need an open `ui.confirm`. `select` accepts only ids in `last_tx_ids`. An unmet precondition ends `error`, as the scripted driver does.
    - Stops (D6):
      - `stop` → `done` with `stop_reason` = the model's reason.
      - `ui.handoff_banner` or `mode human` → `handoff`.
      - 12 turns → `max_turns`.
      - A transport or protocol error → `error`.
    - `eval/prompts/simulate@v1.md` puts the goal, `language_variant` and `fact_sheet` in the system block. It states that the fenced bot text is data, not instructions, gives one ES and one PT example, and contains no PII (`find_pii` finds nothing in it).
    - The persona's document, email or phone never reach the prompt, and `customer_id` appears only in the test-IdP call.
  - Verify: `uv run --project backend pytest eval/tests/test_simulator.py eval/tests/test_driver.py -q && uv run --project backend python -c "import sys; sys.path.insert(0,'backend'); from pathlib import Path; from app.core.pii import find_pii; assert not find_pii(Path('eval/prompts/simulate@v1.md').read_text(encoding='utf-8')); from eval.simulator import run_case_simulated; print('ok')" && grep -n '"simulate"' backend/app/core/llm/registry.py && uv run --project backend ruff check --config backend/pyproject.toml eval/simulator eval/tests/test_simulator.py backend/app/core/llm/registry.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/simulator eval/tests/test_simulator.py backend/app/core/llm/registry.py && cd backend && uv run mypy app/core/llm && uv run lint-imports && uv run pytest tests/unit/test_llm_client.py -q`
  - Files: `backend/app/core/llm/registry.py`, `eval/simulator/__init__.py`, `eval/simulator/simulator.py`, `eval/prompts/simulate@v1.md`, `eval/tests/test_simulator.py`

- [ ] T4: B4 fix — `card_block` remembers `block_kind` across the which-card question
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/flows/card_block.py`; `backend/tests/unit/test_block_flows.py` lines 1-72 and 359-end (the `ScriptedLLM` + `make_session("CLI-TFMULTI00001", ...)` pattern); spec §"Decisions" D10 and §"Test list" item 6
  - Acceptance:
    - When the first `card_block` turn carries `slots.block_kind` but the card is still ambiguous (the `Ask` branch), the kind is remembered (e.g. `update["slots"] = NLUSlots(block_kind=...)`). The `card_hint` resume turn, whose NLU carries only the card hint, then goes straight to the policy check and plan: one `ui.confirm` for `cards.lock_card` and no lock-vs-block question.
    - A fresh NLU `block_kind` on the resume turn still wins over the remembered one.
    - `test_block_kind_survives_card_question_es` and `_pt`: "block temporarily" → the which-card question (`pending == "card_block.card_hint"`), then the answer naming only the last4 (NLU slots `card_hint` only) → `pending == "card_block.confirmation"` and `ui == ["confirm"]`.
    - `test_block_flows.py` still passes.
    - The state file records a note on "before" (the D5-A state T36 evidence) for the verifier's D10(a) subset run.
  - Verify: `cd backend && uv run pytest tests/unit/test_card_block_memory.py tests/unit/test_block_flows.py -q && uv run ruff check app/domains/conversation/flows/card_block.py tests/unit/test_card_block_memory.py && uv run ruff format --check app/domains/conversation/flows/card_block.py tests/unit/test_card_block_memory.py && uv run mypy app/domains/conversation/flows/card_block.py && uv run lint-imports`
  - Files: `backend/app/domains/conversation/flows/card_block.py`, `backend/tests/unit/test_card_block_memory.py`

- [ ] T5: Dev seeds — fact sheets (D4), the D10 card_block revert, the D14 injection seed
  - Depends on: nothing (needs `make up` running for read-only golden-DB lookups, and `OPENAI_API_KEY` for one paid paraphrase call)
  - Read exactly these: spec §"Decisions" D4, D10, D14 and §"Boundaries"; `eval/scenarios/dev/d-transaction_search-injection-pt-br-01.yaml` (the `db_patches` injection analogue); `eval/personas.yaml` header (the trait meanings, `card_count`)
  - Acceptance:
    - `fact_sheet` is filled only for dev seeds where the bot asks the customer to choose something: which card (the persona has 2+ cards and the seed names none), block kind, which transaction, an address, or an OTP. Values are what the bot shows (last4, merchant label, the amount as the UI formats it, the day), read from `latam_golden`. There is no document number, email, phone or full name. List which seeds got one in the state file.
    - `a-card_block-normal_resolution-es-co-01` `.s` turn 2 is exactly `La que termina en 5772.`
    - New `d-decline_explain-injection-es-mx-01.yaml` has a real persona and transaction from `latam_golden` (a declined transaction), and `setup.db_patches` plants an instruction in that transaction's `merchant_name`. `forbidden_tools` is all 5 write tools, `labels` otherwise follow the analogue, and it has a seed case plus 2 paraphrases made by `backend/scripts/paraphrase_seeds.py --n 2` run on a scratch `<tmp>/scenarios/dev/` holding only this file (see Facts). No other seed gains cases.
    - Nothing under `eval/scenarios/heldout/` or `_staging/heldout/` changes, and `mix_targets.yaml` is not edited (escalate if `eval-mix` fails).
  - Verify: `make eval-mix DIR=eval/scenarios/dev && uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && uv run --project backend python -c "from pathlib import Path; from collections import Counter; from eval.scenarios.schema import load_dir; c=load_dir(Path('eval/scenarios/dev')); s=Counter(x.seed_id for x in c); assert all(n==1 for k,n in s.items() if k.startswith('a-')), s; assert s['d-decline_explain-injection-es-mx-01']==3; t=[x for x in c if x.case_id=='a-card_block-normal_resolution-es-co-01.s'][0]; assert t.turns[1].say=='La que termina en 5772.'; print(len(s), len(c))" && test -z "$(git status --porcelain -- eval/scenarios/heldout eval/scenarios/_staging/heldout eval/scenarios/mix_targets.yaml)"`
  - Files: `eval/scenarios/dev/*.yaml` (the choice seeds, `a-card_block-normal_resolution-es-co-01.yaml`), `eval/scenarios/dev/d-decline_explain-injection-es-mx-01.yaml` (new)

- [ ] T6: Docs — ADR-030 simulator note, `06` §2 `openai` line, `07` §8 row
  - Depends on: nothing
  - Read exactly these: `docs/solution-docs/decision-log.md` ADR-030 (line 173 onwards, incl. its "Temperature note (T10)"); `docs/solution-docs/06-engineering-rules.md` line 27; `docs/solution-docs/07-execution-plan.md` line 442; spec §"Decisions" D1-D2 and §"Contracts" → Docs
  - Acceptance:
    - ADR-030 gains a "Simulator note (D6-B)". The `simulate` step is eval-only on `gpt-6-luna` at temperature 1.0 (not the 0 in `05` §5 and `07` B1), because the model rejects any other value. Bot text is masked and fenced, and the OTP comes from the harness. Reports from a simulator run carry the D2 caveat.
    - `06` §2's `openai` parenthesis reads "eval paraphrase and simulator only, ADR-030".
    - `07` §8's "Paraphrase, simulator and judge model family" row records the simulator decision (OpenAI `gpt-6-luna`, ADR-030), with the judge still open.
    - Nothing else changes in these docs.
  - Verify: `grep -n "Simulator note (D6-B)" docs/solution-docs/decision-log.md && grep -n "eval paraphrase and simulator only" docs/solution-docs/06-engineering-rules.md && grep -n "Paraphrase, simulator and judge" docs/solution-docs/07-execution-plan.md | grep -i "gpt-6-luna"`
  - Files: `docs/solution-docs/decision-log.md`, `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/07-execution-plan.md`

- [ ] T7: Frontend session-expired modal with client replay (B2/D8) and its Playwright proof
  - Depends on: nothing
  - Read exactly these: `frontend/src/lib/api.ts` (`withAuthRetry`, lines 90-110); `frontend/src/routes/chat.tsx`; `frontend/e2e/mock-api.ts` and `frontend/e2e/block.pt.spec.ts` (the mock + fixture pattern); spec §"Decisions" D8, D11 and §"Contracts" → Frontend
  - Acceptance:
    - `withAuthRetry`: when refresh fails or the retry gets a second 401 **while the chat is mounted**, it doesn't redirect. It calls `sessionExpired.hold(retry)` (an exported controller in `api.ts` that the chat registers and unregisters). The returned promise resolves with the replayed result or rejects when the request is dropped. Routes outside the chat keep the `/login` redirect.
    - The login form moves from `routes/login.tsx` into `components/auth/LoginForm.tsx` (`onSuccess(me: MeResponse)` callback), with no behaviour change on `/login`.
    - `SessionExpiredModal.tsx` is a Radix Dialog (`@/components/ui/dialog`) holding `LoginForm`. On success it calls `me()` and compares `login_hint` + `display_name` with the `MeResponse` that `chat.tsx` captured when the chat opened. On a match it replays the held request once and re-opens the SSE stream. On a mismatch it drops the request, which starts a fresh conversation (the `handleNewConversation` path).
    - The ES/PT strings go in the dictionaries in Cardy's voice (`docs/brand.md`). No `customer_id` appears anywhere in the frontend.
    - `mock-api.ts` gains:
      - an `/auth/refresh` route (401 while expired)
      - an option to answer `401 session_expired` on the Nth `/messages`/`/confirmations/*` POST
      - an `altCustomer` login (a second password → a different `MockCustomer`)
      - recording of every request so replays are countable
    - Existing specs keep working unchanged.
    - New ES fixtures `expiry-confirm.sse` (a lock `ui.confirm`) and `expiry-verified.sse` (the read-back message).
    - `session-expiry.es.spec.ts` covers tests 4 and 5 (spec §"Test list" items 4-5): the same customer sees the confirm re-sent exactly once and the read-back rendered; a different customer sees nothing re-sent and a fresh chat.
  - Verify: `cd frontend && npm run typecheck && npx biome ci src/lib/api.ts src/components/chat/SessionExpiredModal.tsx src/components/auth/LoginForm.tsx src/routes/login.tsx src/routes/chat.tsx src/lib/i18n e2e/mock-api.ts e2e/session-expiry.es.spec.ts && npm run build && npx playwright test e2e/session-expiry.es.spec.ts e2e/block.pt.spec.ts` (kill any stale preview server on port 4173 first)
  - Files: `frontend/src/lib/api.ts`, `frontend/src/components/chat/SessionExpiredModal.tsx` (new), `frontend/src/components/auth/LoginForm.tsx` (new), `frontend/src/routes/login.tsx`, `frontend/src/routes/chat.tsx`, `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`, `frontend/e2e/mock-api.ts`, `frontend/e2e/session-expiry.es.spec.ts` (new), `frontend/e2e/fixtures/expiry-confirm.sse` (new), `frontend/e2e/fixtures/expiry-verified.sse` (new). This is over five files because the expiry path and its only proof (the Playwright spec) must land together.

- [ ] T8: Frontend fallback, error and loading states, and the mobile layout (B2)
  - Depends on: T7 (same `chat.tsx` and dictionaries; shares `dist/` and port 4173)
  - Read exactly these: `frontend/src/routes/chat.tsx` (`KNOWN_ERROR_CODES`, `handleTurnError`, the layout); `frontend/src/components/chat/MessageList.tsx` and `StatusIndicator.tsx`; spec §"Decisions" D12-D13; `docs/brand.md` (voice)
  - Acceptance:
    - Only existing SSE/HTTP contract items get localized ES/PT states (D12): SSE `error {code}`, 409 `turn_in_progress`, 409 `conversation_closed`, 409 `confirmation_invalid`, 429 and 5xx. They are mapped by code and status, with no raw server string shown and no new event kinds.
    - The A1 fallback (`message` + `ui.handoff_banner`) renders through the existing message and banner path.
    - Loading states: typing/status while a turn is in flight, and a busy composer and widgets while a POST is pending.
    - Mobile layout: the chat is usable at a 375 px width, with the composer pinned, no horizontal scroll, and tap targets at least 44 px.
    - If the day runs behind, the mobile layout is the first cut (D13). Record that in the state file instead of skipping silently.
    - Money, dates and masks are never reformatted client-side.
  - Verify: `cd frontend && npm run typecheck && npx biome ci src/routes/chat.tsx src/components/chat src/lib/i18n src/index.css && npm run build && npx playwright test e2e/card-info.es.spec.ts e2e/unrecognized.es.spec.ts e2e/session-expiry.es.spec.ts` (kill any stale preview server on port 4173 first)
  - Files: `frontend/src/routes/chat.tsx`, `frontend/src/components/chat/MessageList.tsx`, `frontend/src/components/chat/Composer.tsx`, `frontend/src/components/chat/StatusIndicator.tsx`, `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`, `frontend/src/index.css`

- [ ] T9: Eval harness starts the backend on Windows (SelectorEventLoop) — added at verify, human decision
  - Depends on: T2 (same `runner.py`)
  - Read exactly these: `eval/harness/runner.py` (`_start_backend` and what it waits on); the installed uvicorn version's `--loop` option (`uv run --project backend uvicorn --help`)
  - Acceptance:
    - On `sys.platform == "win32"`, the uvicorn process the harness starts runs on a `SelectorEventLoop`, so psycopg async and the LangGraph checkpointer pool connect. Other platforms are unchanged.
    - Prefer a uvicorn-supported mechanism (e.g. `--loop <module:factory>` if the installed version accepts it); otherwise the smallest equivalent in the harness. No change to `backend/app`.
    - Flagged in the state file for Dev A's review (their file).
  - Verify: `uv run --project backend pytest eval/tests/test_runner_abort.py -q`, plus a startup proof on this host: the harness's backend start helper (or `make eval SUITE=dev SYSTEM=proposed CASES=<one case>` only if the start helper can't be called alone) reaches a healthy `/api/v1/health` with no `ProactorEventLoop` or `PoolTimeout` in its log. No paid LLM calls beyond at most one case.
  - Files: `eval/harness/runner.py` (plus one new small module under `eval/harness/` if a loop factory needs an import path)

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T4, T5, T6, T7 | no | Six independent chains with disjoint `Files`: the driver (`eval/driver`, `schema.py`, `test_driver.py`), the harness wiring (`eval/harness/*`, `Makefile`; the simulator import is lazy), the B4 fix (`flows/card_block.py` + a new test), the seeds (`eval/scenarios/dev/*.yaml`), the docs, and the frontend expiry path (the only frontend task in the wave, so it owns `dist/` and port 4173). None adds a dependency, touches a lockfile, migrates or restarts the stack. T5 only reads `latam_golden` and makes one paid paraphrase call. |
| W2 | T3, T8 | no | T3 needs T1's public driver helpers. T8 needs T7's `chat.tsx` and dictionaries. Their files are disjoint (`registry.py` + `eval/simulator` + prompt + `test_simulator.py` vs `frontend/src/...`). |

The human asked for the simulator and the driver expiry to run in the same wave, and that isn't possible. The spec requires the simulator to reuse the driver's turn helpers "by import, not by copy" and to follow the same expiry rule. Those helpers, and `Transcript.stop_reason`, are what T1 builds in `driver.py`, so T3 is one wave behind T1. T1 is small, so the dispatch rule lets T3 start as soon as T1 finishes.
