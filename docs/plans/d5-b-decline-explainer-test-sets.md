# Plan: D5-B — Decline explainer and G11 test sets

Spec: [`docs/specs/d5-b-decline-explainer-test-sets.md`](../specs/d5-b-decline-explainer-test-sets.md) · Branch: `feat/d5-b-decline-explainer-test-sets`

Human answers given after the spec was written (binding on every task):
- **D18 tolerances confirmed** as proposed: ±5 pp per language share, held-out 120–170 cases, dev 60–100, ≥8 held-out cases per category.
- **The public-URL deploy is postponed** to the end of D5. No task, Verify or acceptance depends on a deployed URL. The driver and every runtime proof target the local dev stack (`make up`, nginx on `http://localhost`) through a configurable `--base-url`.

Execution model: minimum tasks, in parallel waves. Tasks in the same wave run at the same time **in one shared checkout** (no worktrees, no branches, no commits; the orchestrator commits). Within a wave no two tasks touch the same file, and no Verify depends on a sibling's output.

| Wave | Tasks |
|---|---|
| W1 | T1 (decline read tool) · T2 (OpenAI paraphrase step + script) · T3 (scenario schema + driver) · T4 (persona split) |
| W2 | T5 (`decline_explain` flow) · T6 (mix report, freeze, Makefile, CI) |
| W3 | T7 (single-pick gate, frontend, `04`/`02` docs) · T8 (dev seeds) · T9 (held-out staging seeds) |
| W4 | T10 (live proofs: paraphrase run, mix, driver on the local stack) |

## Facts checked against the repo

**Baseline (HEAD `026cfdd` = `develop` = `origin/develop`, D4-A + D4-B merged, stack up):**
- `cd backend && uv run pytest tests/unit -q` → **99 passed**.
- `uv run lint-imports` → 4 kept, 0 broken.
- `uv run mypy app` → clean, 131 files.
- A new red belongs to the task that caused it.
- Working tree: only the spec is new (untracked). **None of the doc edits the spec lists exist yet** (`04` §1/§3, `02` §4.3, `06` §2, ADR-030). T2 and T7 write them.
- Alembic head is `0006`. **This card has no migration.**

**Commands and conventions (from the D2-A…D4-B state files; still true):**
- Backend commands run as `cd backend && uv run …`. There is no pytest-asyncio: drive coroutines with `asyncio.run(...)`.
- Flow tests use `make_session(customer_id, fakebank_dir, llm)` and `ScriptedLLM` from `backend/tests/conftest.py` (FakeBank over `backend/tests/fixtures/fakebank/`, `MemorySaver`, in-memory confirmation store). `make_session`'s `config["configurable"]["thread_id"]` is `str(conversation_id)` of a fresh `uuid4()`. Analogue: `backend/tests/unit/test_dispute_flows.py`.
- Tests never call a real provider.
- The fixture CSVs are UTF-8 **with BOM** and CRLF. Checkouts are CRLF (`core.autocrlf=true`).
- Windows host: integration tests through `app_client` need the selector event loop. Run them with `uv run python -c "import asyncio,sys,pytest; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); sys.exit(pytest.main([...]))"` and `REDIS_URL=redis://127.0.0.1:6379/0`. A `skipped` result is not a pass.
- `make` exists on this host (ezwinports). The Makefile does `-include .env` and `export`.
- Never `git add`, `git commit` or push.

**The `eval/` tree runs under the backend uv env, from the repo root:**
- `eval/` has no `__init__.py` today (it contains only `personas.yaml` and `nlu/`). `uv run --project backend python -c "import eval"` resolves `eval` as a namespace package from the cwd. No installed package is named `eval`.
- Pinned invocations:
  - `uv run --project backend python -m eval.<module>` for anything run as a module.
  - `uv run --project backend pytest eval/tests -q` for the eval tests.
  - `uv run --project backend ruff check --config backend/pyproject.toml <paths>` for lint, since the root `pyproject.toml` has no `[tool.ruff]`.
- T3 adds `eval/__init__.py`, `eval/scenarios/__init__.py`, `eval/driver/__init__.py` and `eval/tests/__init__.py`, all empty or re-export only, so pytest's prepend import mode puts the repo root on `sys.path`. `eval/scenarios/__init__.py` must import nothing, so that `freeze check` stays stdlib-only.
- The eval tests are **not** part of `make check` or CI (the spec doesn't add them). The verifier runs them explicitly (success criterion 1).
- `httpx` is in the backend **dev** group. `uv run --project backend` installs the dev group by default, so the driver can use it.
- `backend/tests` has `pythonpath = ["."]` (= `backend/`), so `from scripts.paraphrase_seeds import …` works in a unit test (`scripts/` is a namespace package). `eval` is **not** importable from backend unit tests. So `backend/scripts/paraphrase_seeds.py` works on raw YAML mappings (PyYAML) and does not import `eval.*`.

**Decline data and code:**
- `latam_app` has 52–53k Declined rows per code (`05`/`14`/`51`/`54`) plus **10,962 Declined rows with an empty `response_code`**. A missing or empty code is a real case, not a hypothetical one. It must hit `DeclineCodeUnknown` → `decline_unknown`.
- `app.system_metadata.load_date` = `2026-09-28`.
- Personas that exist today with `recent_declines`:
  - `CLI-F7PQP3J4AS6X` (MX, `05`)
  - `CLI-55D0R3VIIFPT` (MX, `14`)
  - `CLI-5RJITZ5VLJGY` (CO, `51`)
  - `CLI-46VRQAOC91Y6` (AR, `54`). Its card is **Blocked**, and its declines span two product ids. So it is not a good demo for success criterion 2, and T4 picks one that is.
- `transactions.service` has `search` and `get_by_ids`. `get_by_ids` raises `AccessDenied` for a foreign id. D4 needs `NotFound` for foreign, missing and non-Declined ids alike, so T1 adds `get_declined` with no existence probe.
- `FakeBank.get_transactions_by_ids` (not on the Protocol) has the same own-row SQL shape to mirror.
- `RecordingBankTools` (`tools/registry.py`) wraps every read with a `tool_call`/`tool_result` audit and appends the method name to `.calls`.
- Read tools have no `policies/tools.yaml` row. Only writes do, so `explain_decline` needs none.
- The tool error module is `backend/app/core/errors.py` (`ToolError` subclasses carry a `code: ClassVar[str]`).
- `policy/registry.py::_MODELS_BY_STEM` validates each `policies/<stem>.yaml` at startup. The analogue for an optional per-file model is `disputes` (in `_MODELS_BY_STEM`, not a required `PolicyBundle` field, loader `policy/disputes.py::load_disputes_policy`).
- In the container, `policies/` is mounted at `/policies`, which is what a `parents[4]` repo-root path from `app/domains/policy/*.py` resolves to. So new YAML needs no compose change.

**Conversation graph (what T5/T7 extend):**
- `graph.py`:
  - `_BRANCH_NODES`, `_INTENT_NODES` and `_FLOW_NODES`.
  - Five `add_conditional_edges` maps that list every flow node: after `load_session`, `understand`, `enqueue` and `next_intent`, plus a per-flow `_after_flow` block.
  - `_entry` hard-codes `_FLOW_NODES["unrecognized_charge"]` for a selection. It must become `_FLOW_NODES[pending["flow"]]`.
- `runner.py` has its own `_BRANCH_NODES` mirror, which must add `"decline_explain"`.
- `runner.checkpointed_dispute(host, conversation_id)` lives in **`runner.py`**, not in `conversations.py` as the spec's wording suggests. Its only caller is `api/v1/conversations.py::post_message`.
- `ui.TransactionListPayload.multi: Literal[True] = True`. Its only constructor call is `flows/unrecognized_charge.py:193`, which must pass `multi=True` once the default is gone.
- `QuickRepliesPayload.slot: Literal["block_kind","abstain"]`.
- `nodes/compose.py`:
  - `_PROMPT = PromptRef("compose", 5)` and `Goal = Literal["card_status","balance_due","abstain"]`.
  - The LLM sees fact **keys only**, and `_format_fact` fills every value in code.
  - `tests/unit/test_compose.py:58` asserts `"compose@v5"`.
- **Consequence of compose's existing contract (not a new decision):** D6's "the LLM only phrases `cause_key`/`next_step_key`" is built the way `abstain` already works. The flow writes facts `decline_cause` = `cause_key` and `decline_next_step` = `next_step_key`. `_format_fact` renders each one as a fixed ES/PT label (`decline_cause_<cause_key>`, `decline_next_<next_step_key>` in `templates.py`). The LLM places the placeholders inside a new `decline_explain` goal. That needs `compose@v6`. If the human wants the LLM to word the cause freely instead, T5 changes; nothing else does.
- NLU (`nlu@v4`) already has `decline_explain` in its intent list. No NLU change.
- `make graph-diagram` rewrites `docs/diagrams/turn-graph-v0.mmd`.

**Frontend:**
- `ui` events are hand-typed in `frontend/src/lib/sse.ts`, not in the generated client. `types.gen.ts` has no `multi` and no `quick_replies` type, so **`make client` is not needed** (the spec's touch map lists it; it would produce no diff).
- `TransactionList.tsx` is checkbox-only. `MessageList.tsx:87` renders it without `multi`.
- `sse.ts` has `QuickRepliesPayload.slot: "block_kind"` (already stale: `abstain` is missing).
- The existing Playwright spec `e2e/unrecognized.es.spec.ts` uses a `multi: true` fixture. It is the regression proof for the multi branch.

**LLM layer (T2):**
- `core/llm/registry.py`: `Provider = Literal["anthropic","bedrock"]`, `Step = Literal["nlu","compose","handoff_summary"]`, `MODEL_REGISTRY: dict[Step, dict[Provider, str]]`.
- `core/llm/client.py` (195 lines):
  - `build_chat_model` picks `MODEL_REGISTRY[step][settings.llm_provider]`.
  - `StructuredLLMClient.structured` sets `provider = settings.llm_provider` and catches `(anthropic.APIError, BotoCoreError, ClientError)`.
  - Those three spots are the "provider branch". The spec says to ask first before touching anything else in `client.py`.
- `core/llm/settings.py::LLMSettings` has `anthropic_api_key: SecretStr | None`.
- `.importlinter` contract `llm-sdk-only-in-core-llm` has pairs of `ignore_imports` lines (`app.core.llm -> X`, `app.core.llm.** -> X`) per SDK.
- `langchain-openai`/`openai` are **not installed** yet. Add them with `cd backend && uv add langchain-openai` (updates `backend/pyproject.toml` + `backend/uv.lock`).
- `.env.example` has an `# --- LLM (K1)` block. `.env` has **no** `OPENAI_API_KEY`, `APP_ENV` or `DEMO_OTP_CODE` line today (so `APP_ENV` defaults to `dev` and `/test-idp` is not mounted).
- The backend image is built from `backend/uv.lock`. Hot reload does **not** install new deps, so the running container crashes on `import langchain_openai` until `make up` rebuilds it (T10).

**Local stack:** `make up` serves the API through nginx at `http://localhost` (port 80). `backend/scripts/chat_api.py` is the analogue for opening a per-turn SSE stream, CSRF header `X-CSRF-Token` from the `csrf_token` cookie, OTP and `/pick`. The routes are:
- `POST /api/v1/test-idp/sessions {customer_id}`. It exists only when `APP_ENV=eval`, and returns `404 not_found` for an unknown customer.
- `POST /api/v1/auth/otp/verify`.
- SSE frames are `event: <name>\ndata: <json>\n\n`, preceded by `: connected` and interleaved with `: ping`.

**Personas:**
- `eval/personas.yaml` has 32 personas.
- Its header documents the closed trait vocabulary. `customer_id` and `notes` are the only non-trait keys (`backend/tests/integration/test_personas.py::_NON_TRAIT_KEYS`).
- That test is local-only, skips when `latam_golden` is unreachable, asserts `len >= 28` and keeps the original 10 ids.
- Each trait's predicate SQL is in that test file. New personas are found with the same predicates. Query aggregates and ids only (R10).

**Cross-task names (pinned by this plan; binding):**

| Name | Where | Owner |
|---|---|---|
| `DeclineCodeUnknown(ToolError)`, `code = "decline_code_unknown"` | `app/core/errors.py` | T1 |
| `DeclineCode{cause_key, next_step_key, self_service}`, `DeclineCodesPolicy{provenance, version, codes: dict[str, DeclineCode]}`, `load_decline_codes_policy(path=None)`, `lookup_decline_code(code: str \| None) -> DeclineCode` (raises `DeclineCodeUnknown` for `None`, `""` or an unlisted code) | `app/domains/policy/decline_codes.py` | T1 |
| `DeclineExplanation{code, cause_key, next_step_key, self_service, source}` frozen | `app/domains/transactions/schemas.py` | T1 |
| `get_declined(customer_id, tx_id) -> TxView` (`NotFound` for missing / foreign / non-Declined) | `app/domains/transactions/service.py` | T1 |
| `BankReadTools.explain_decline(tx_id) -> DeclineExplanation`; audit tool name `transactions.explain_decline`; `.calls` entry `"explain_decline"` | `tools/bank.py`, `fakebank.py`, `postgres.py`, `registry.py` | T1 |
| Fixture customer `CLI-TFDECLN00006` (Colombia), card `PRD-TFD6CRED0001` (Tarjeta Crédito, COP, Active, last4 `6666`), Declined rows `TRX-TFD6CRED0001TXN01..04` = codes `51`/`14`/`05`/`54`, merchants `Super Uno`/`Libreria Dos`/`Cine Tres`/`Viajes Cuatro`, dated 2026-03-30 09:00/10:00/11:00/12:00 (so `54` is the newest) | `backend/tests/fixtures/fakebank/` | T1 |
| `DeclineState{card_id: str, offered_tx_ids: list[str]}`; `TurnState.decline: NotRequired[DeclineState \| None]`; pause `{flow: "decline_explain", node: "pick", awaiting_slot: "transactions"}` | `conversation/state.py` | T5 |
| Graph node and `_FLOW_NODES`/`_INTENT_NODES` key `decline_explain` | `graph.py`, `runner.py` | T5 |
| Template kinds `decline_none`, `decline_unknown`, `decline_pick_ask`, `decline_replacement_option`, `decline_cause_<cause_key>` ×4, `decline_next_<next_step_key>` ×4 (ES+PT) | `conversation/templates.py` | T5 |
| Fact keys `merchant`, `amount`, `tx_date`, `card_mask`, `decline_cause`, `decline_next_step` (+ hidden `currency`); compose goal `decline_explain`; `compose@v6` | `flows/decline_explain.py`, `nodes/compose.py` | T5 |
| `checkpointed_offer(host, conversation_id) -> tuple[Pending \| None, set[str], bool]` (replaces `checkpointed_dispute`) | `conversation/runner.py` | T7 |
| `Case`, `SeedFile`, `CaseVariant`, `load_dir(path) -> list[Case]`, `ScenarioError` | `eval/scenarios/schema.py` | T3 |
| `run_case(...)`, `Transcript`, `TurnRecord` | `eval/driver/driver.py` (re-exported by `eval/driver/__init__.py`) | T3 |
| `mix_report.run(dirs…) -> int` exit code; `freeze.freeze(root, *, mix_check=…)`, `freeze.check(root) -> list[str]`, `FreezeRefused` | `eval/scenarios/` | T6 |
| Persona key `split: dev \| heldout` | `eval/personas.yaml` | T4 |
| Seed id prefix `d-` (dev) / `h-` (held-out), e.g. `d-dec-54-mx-01`, `h-blk-amb-ar-02` | scenario files | T8/T9 |

**Mix targets (`eval/scenarios/mix_targets.yaml`, T6), per suite, read from the directory name (`dev`, or `heldout` for both `_staging/heldout` and `heldout`):**
- Language-variant shares by case, each ±5 pp: `es-MX` 16.7, `es-CO` 16.7, `es-AR` 16.7, `pt-BR` 35, `mixed` 15. Also the ES total (the three `es-*` shares) is 50 ±5.
- All 10 categories present, each with ≥1 case whose `expected_language` is `es` and ≥1 whose `expected_language` is `pt`.
- Size: held-out 120–170, dev 60–100. Held-out has ≥8 cases per category.

**Paraphrase mechanics (the plan's reading of the spec; flagged for the gate):**
- A paraphrase keeps its seed case's `language_variant` and `expected_language`. The prompt asks the model to write *in that variant's register*: voseo for es-AR, CO/MX lexicon, PT-BR, portuñol for `mixed`. So the suite's language mix is fixed by the seeds.
- With `N=2`, each seed yields up to 3 cases. That is why T8 writes 27 dev seeds (≈81 cases) and T9 writes 50 held-out seeds (≈150 cases).

## Components

- **Decline read tool** (`app/domains/policy/decline_codes.py`, `policies/decline_codes.yaml`, `transactions/{schemas,service}.py`, `conversation/tools/{bank,fakebank,postgres,registry}.py`, `core/errors.py`, fixture). It depends on `transactions.repository` (existing own-row SQL) and on `ToolContext.policy_version` for `source`.
- **`decline_explain` flow** (`conversation/flows/decline_explain.py`, new). It depends on the read tool, `card_select`, `localization.format`, `templates`, `ui`, `compose`, and the graph registration.
- **Single-pick gate** (`runner.checkpointed_offer`, `api/v1/conversations.py`). It depends on the flow's `decline` state.
- **Frontend single-select** (`TransactionList.tsx`, `MessageList.tsx`, `lib/sse.ts`). It depends only on the `multi` payload shape.
- **OpenAI paraphrase step** (`core/llm/{registry,settings,client}.py`, `.importlinter`, deps). It is used only by `backend/scripts/paraphrase_seeds.py` (+ `eval/prompts/paraphrase@v1.md`).
- **Scenario contract + driver** (`eval/scenarios/schema.py`, `eval/driver/`). It depends on the spec's B2 contract and `eval/personas.yaml`.
- **Suite tooling** (`eval/scenarios/{mix_report,freeze}.py`, `mix_targets.yaml`, `.gitattributes`, Makefile, CI). It depends on `schema.load_dir` and persona `split`.
- **Test sets** (`eval/scenarios/dev/*.yaml`, `eval/scenarios/_staging/heldout/*.yaml`). They depend on the schema, persona split and mix targets.

## Build order

1. **W1:**
   - T1 (read tool), T2 (LLM step + script), T3 (schema + driver) and T4 (persona split) have no dependencies on each other.
   - T3's `load_dir` is what T6/T8/T9 build on.
   - T4's `split` is what T6's overlap check and T3's test 5 read.
2. **W2:**
   - T5 needs T1's tool and fixture.
   - T6 needs T3's `load_dir` and T4's `split`.
3. **W3:**
   - T7 needs T5's `decline` state and single-pick offer (the gate test drives the real flow).
   - T8/T9 need T3 (schema, test 5), T4 (personas) and T6 (mix targets, to know what to hit).
4. **W4:** T10 needs everything. The paraphrase run needs T2 + T8 + T9. The driver run needs T3 + T5 + T7 + the paraphrased dev set.

## Touch map

| File | New/Mod | Change | Task |
|---|---|---|---|
| `policies/decline_codes.yaml` | new | verbatim `04` §5 block | T1 |
| `backend/app/core/errors.py` | mod | `DeclineCodeUnknown` | T1 |
| `backend/app/domains/policy/decline_codes.py` | new | model, loader, `lookup_decline_code` | T1 |
| `backend/app/domains/policy/registry.py` | mod | `"decline_codes": DeclineCodesPolicy` in `_MODELS_BY_STEM` | T1 |
| `backend/app/domains/transactions/schemas.py` | mod | `DeclineExplanation` | T1 |
| `backend/app/domains/transactions/service.py` | mod | `get_declined` | T1 |
| `backend/app/domains/transactions/repository.py` | mod (only if needed) | reuse `fetch_transactions_by_ids`; add nothing unless the status filter can't be done in the service | T1 |
| `backend/app/domains/conversation/tools/{bank,fakebank,postgres,registry}.py` | mod | `explain_decline` on the Protocol, both impls, the recorder | T1 |
| `backend/tests/fixtures/fakebank/{customers,products}.csv`, `transactions/…/transactions_20260330.csv`, `README.md` | mod | one customer, one card, 4 Declined rows | T1 |
| `backend/tests/unit/test_decline_tools.py` | new | test 3 | T1 |
| `backend/app/core/llm/{registry,settings,client}.py` | mod | `openai` provider, `paraphrase` step, `STEP_PROVIDER`, `ChatOpenAI` branch | T2 |
| `backend/.importlinter` | mod | forbid `openai`/`langchain_openai` outside `app.core.llm` | T2 |
| `backend/pyproject.toml`, `backend/uv.lock` | mod | `langchain-openai` | T2 |
| `.env.example` | mod | `OPENAI_API_KEY=` | T2 |
| `backend/scripts/paraphrase_seeds.py` | new | the paraphrase script | T2 |
| `eval/prompts/paraphrase@v1.md` | new | the prompt | T2 |
| `backend/tests/unit/test_paraphrase_seeds.py` | new | test 8 | T2 |
| `docs/solution-docs/06-engineering-rules.md` §2, `docs/solution-docs/decision-log.md` | mod | the SDK list; ADR-030 | T2 |
| `eval/__init__.py`, `eval/scenarios/__init__.py`, `eval/driver/{__init__,__main__,driver}.py`, `eval/tests/__init__.py` | new | packages, driver, CLI | T3 |
| `eval/scenarios/schema.py` | new | `SeedFile`/`CaseVariant`/`Case`/`load_dir` | T3 |
| `eval/tests/test_driver.py`, `eval/tests/test_scenarios_valid.py` | new | tests 6, 5 | T3 |
| `eval/personas.yaml` | mod | `split` on every persona, new personas, header | T4 |
| `backend/tests/integration/test_personas.py` | mod | `split` is a non-trait key | T4 |
| `backend/app/domains/conversation/{state,ui,templates,graph,runner}.py` | mod | `DeclineState`, `multi: bool`, `next_step` slot, templates, node registration | T5 |
| `backend/app/domains/conversation/flows/decline_explain.py` | new | the flow | T5 |
| `backend/app/domains/conversation/flows/unrecognized_charge.py` | mod | `multi=True` explicit | T5 |
| `backend/app/domains/conversation/nodes/compose.py`, `prompts/compose@v6.md` | mod/new | `decline_explain` goal, two label facts | T5 |
| `backend/tests/unit/test_compose.py` | mod | `compose@v6` label | T5 |
| `backend/tests/unit/test_decline_explain_flow.py` | new | tests 1, 2 | T5 |
| `docs/diagrams/turn-graph-v0.mmd` | mod (generated) | new node | T5 |
| `eval/scenarios/{mix_report,freeze}.py`, `eval/scenarios/mix_targets.yaml` | new | tooling | T6 |
| `eval/tests/test_freeze.py` | new | test 7 | T6 |
| `.gitattributes` | new | `eval/scenarios/** -text` | T6 |
| `Makefile` | mod | `eval-paraphrase`, `eval-mix`, `eval-freeze`, `eval-freeze-check` | T6 |
| `.github/workflows/ci.yml` | mod | freeze-check step | T6 |
| `backend/app/domains/conversation/runner.py` | mod | `checkpointed_offer` | T7 |
| `backend/app/api/v1/conversations.py` | mod | single-pick gate | T7 |
| `backend/tests/unit/test_selection_gate.py` | new | test 4 | T7 |
| `frontend/src/components/chat/{TransactionList,MessageList}.tsx`, `frontend/src/lib/sse.ts` | mod | single-select | T7 |
| `docs/solution-docs/04-contracts.md` §1/§3, `02-conversation-design.md` §4.3 | mod | contract doc updates | T7 |
| `eval/scenarios/dev/*.yaml` | new | 27 dev seeds (+ paraphrases in T10) | T8, T10 |
| `eval/scenarios/_staging/heldout/*.yaml` | new | 50 held-out seeds (+ paraphrases in T10) | T9, T10 |
| **`eval/scenarios/heldout/`, `eval/scenarios/heldout.lock`** | **never** | human only, via `make eval-freeze` | — |

## Risks and mitigations

1. **An agent writes under `eval/scenarios/heldout/`** (R9, CLAUDE.md).
   - Every eval task's acceptance repeats the ban.
   - The paraphrase script refuses any output dir other than `…/scenarios/dev` or `…/scenarios/_staging/heldout` (T2).
   - `freeze` is only exercised on `tmp_path` in tests (T6).
   - T10's Verify ends with `git status --porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock` being empty.
2. **CRLF changes a hash between Windows and CI.** T6 adds `.gitattributes` (`eval/scenarios/** -text`) in the same commit as the first scenario file, and hashes raw bytes.
3. **A paraphrase call leaks PII or a whole file** (R5).
   - Only `say` turn text is sent. Turns with `paraphrase: false` or a PII-detector hit are copied verbatim.
   - Test 8 proves a 16-digit turn never reaches the client (T2).
4. **The new provider leaks into the served graph.**
   - `STEP_PROVIDER` binds only `paraphrase` to `openai`.
   - Import-linter forbids `openai`/`langchain_openai` outside `app.core.llm`.
   - T2's Verify checks that `nlu`/`compose` still build the Anthropic model.
5. **A1 edits `core/llm/client.py` the same day.** T2 limits `client.py` edits to the three provider-branch spots (the facts list them). Any other edit there is an escalation. Whoever merges second rebases.
6. **The running backend crashes after T2** (`langchain_openai` isn't in the image). T10 starts with `make up` (which rebuilds). No W1–W3 Verify depends on the live stack, except T7's route integration test. T7 therefore rebuilds first with `make up`.
7. **The flow explains the wrong decline, or the LLM picks the meaning.** Code does the lookup (`lookup_decline_code`). The LLM gets only placeholder keys. Test 1 asserts the facts per code (T5).
8. **A foreign or non-offered tx id is picked** (R1/R13).
   - `explain_decline` returns `NotFound` for foreign ids (test 3, T1).
   - The route gate rejects non-offered ids and 2 ids on a single pick, with no turn scheduled (test 4, T7).
   - The flow re-checks the same rule (T5).
9. **Changing `multi` breaks disputes.** T5 sets `multi=True` explicitly and runs `test_dispute_flows.py`. T7 runs the existing `unrecognized.es` Playwright spec and the existing 409 integration test.
10. **Fixture rows break existing tests.** T1 adds a brand-new customer (no existing customer gains rows) and runs the fixture-reading unit tests.
11. **The mix misses because the paraphrase returns fewer than N.** Seeds are sized so seeds × 3 lands mid-range. T10 re-runs on a shortfall and escalates if a re-run can't close it. Changing the tolerances is an ask-first item.
12. **T10 needs things only the human can provide:** `OPENAI_API_KEY`, `APP_ENV=eval` and `DEMO_OTP_CODE` in `.env`. T10 checks them first (by key presence, never printing values) and stops with an escalation if any is missing.
13. **Personas.** A persona shared across suites, or one used in the demo/tests moving to held-out, would leak tuning into held-out. T4 puts every persona referenced outside `eval/` (docs, backend tests, e2e, Makefile) on `dev`. The overlap check (T6) and test 5 (T3) enforce the split.

## Tests

| # | Test | Task |
|---|---|---|
| 1 | `backend/tests/unit/test_decline_explain_flow.py::test_explains_decline` (es/pt × 51/14/05/54) | T5 |
| 2 | `backend/tests/unit/test_decline_explain_flow.py::test_no_declines` (es/pt) | T5 |
| 3 | `backend/tests/unit/test_decline_tools.py::test_explain_decline_other_customer_is_not_found` (FakeBank only; the spec allows skipping Postgres parity) | T1 |
| 4 | `backend/tests/unit/test_selection_gate.py::test_decline_pick_rejects_unoffered_or_multiple` | T7 |
| 5 | `eval/tests/test_scenarios_valid.py` | T3 (runs for real in T8/T9/T10) |
| 6 | `eval/tests/test_driver.py::test_plays_say_confirm_otp_select` + `::test_faults_not_runnable` | T3 |
| 7 | `eval/tests/test_freeze.py` (edit → check fails; null reviewer → freeze refuses) | T6 |
| 8 | `backend/tests/unit/test_paraphrase_seeds.py::test_pii_turns_not_sent` | T2 |

The existing R6 graph test (`test_r6_no_write_tools_in_llm_nodes.py`) must still pass (T5). Success criteria 2, 3 and 4 are runtime proofs in T10. Criterion 5 (post-freeze) is proved mechanically by test 7. The human's freeze run is not an agent task.

## Tasks

- [ ] T1: Decline read tool — `policies/decline_codes.yaml`, the typed accessor, `DeclineExplanation`, `explain_decline` on both banks and the recorder, the fixture decline rows, and the R1 test
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "B1: backend" (first three bullets) and D4; `docs/solution-docs/04-contracts.md` §5 (the `policies/decline_codes.yaml` block, copy verbatim) and §1 (error contract); `backend/app/domains/policy/disputes.py` (the loader pattern to mirror); `backend/app/domains/conversation/tools/fakebank.py` `get_transactions_by_ids` (own-row SQL to mirror); `backend/tests/fixtures/fakebank/README.md`
  - Acceptance:
    - The YAML is byte-for-byte the `04` §5 block. `load_policies()` validates it through `_MODELS_BY_STEM["decline_codes"]`.
    - `lookup_decline_code` raises `DeclineCodeUnknown` for `None`, `""` or an unlisted code.
    - `explain_decline(tx_id)` takes no `customer_id` in either bank.
    - It raises `NotFound` for a missing tx, another customer's tx or a non-Declined tx. There is no `AccessDenied` and no existence probe.
    - It returns `DeclineExplanation` with `source == "policy:decline_codes@" + ctx.policy_version`.
    - `RecordingBankTools.explain_decline` audits as `transactions.explain_decline` and appends `"explain_decline"` to `.calls`.
    - Fixture rows are exactly the pinned ones (BOM + CRLF preserved), and the README lists them.
    - Test 3 covers:
      - `CLI-TFSINGLE0002` asking for `TRX-TFD6CRED0001TXN01` → `NotFound`.
      - Its own Approved `TRX-TFS2CRED0001TXN01` → `NotFound`.
      - `CLI-TFDECLN00006` on `TXN04` → code `54`, `self_service=True`.
  - Verify: `cd backend && uv run pytest tests/unit/test_decline_tools.py tests/unit/test_policy_registry.py tests/unit/test_r1_fakebank.py tests/unit/test_card_info_flows.py tests/unit/test_dispute_flows.py -q && uv run ruff check app/core/errors.py app/domains/policy app/domains/transactions app/domains/conversation/tools tests/unit/test_decline_tools.py && uv run ruff format --check app/core/errors.py app/domains/policy app/domains/transactions app/domains/conversation/tools tests/unit/test_decline_tools.py && uv run mypy app/domains/policy app/domains/transactions app/domains/conversation/tools && uv run lint-imports`
  - Files: `policies/decline_codes.yaml`, `backend/app/core/errors.py`, `backend/app/domains/policy/{decline_codes,registry}.py`, `backend/app/domains/transactions/{schemas,service}.py`, `backend/app/domains/conversation/tools/{bank,fakebank,postgres,registry}.py`, `backend/tests/fixtures/fakebank/{customers.csv,products.csv,README.md,transactions/year=2026/month=03/day=30/transactions_20260330.csv}`, `backend/tests/unit/test_decline_tools.py` (a larger task than the ~5-file norm on purpose: one component, all edits small)

- [ ] T2: OpenAI `paraphrase` step in `core/llm`, the paraphrase script and prompt, the R5 test, import-linter, `06` §2 and ADR-030
  - Depends on: nothing
  - Read exactly these: spec D13–D16, §"B3: tooling" (the `paraphrase_seeds.py` and `app/core/llm` bullets) and §"B2: scenario file" (the YAML shape the script reads and appends to); `backend/app/core/llm/client.py`; `backend/.importlinter`; `backend/tests/conftest.py` (`ScriptedLLM`)
  - Acceptance:
    - LLM layer:
      - `Provider` gains `"openai"` and `Step` gains `"paraphrase"`.
      - `MODEL_REGISTRY["paraphrase"] = {"openai": "gpt-6-luna"}` and `TEMPERATURE["paraphrase"] = 0.0`.
      - `STEP_PROVIDER = {"paraphrase": "openai"}`. Both `build_chat_model` and `structured()` resolve the provider as `STEP_PROVIDER.get(step, settings.llm_provider)`.
      - The `openai` branch builds `ChatOpenAI(model, temperature, max_retries, timeout, api_key=settings.openai_api_key)`. `openai.APIError` joins the caught transport errors.
      - No other `client.py` change. If one seems needed, escalate.
      - `LLMSettings.openai_api_key: SecretStr | None = None`. `.env.example` gains `OPENAI_API_KEY=` in the LLM block, with a comment saying eval paraphrases only.
    - `.importlinter` forbids `openai` and `langchain_openai`, with the same two `ignore_imports` lines each for `app.core.llm`.
    - Script:
      - `backend/scripts/paraphrase_seeds.py` exposes `async def paraphrase_dir(dir: Path, n: int, llm: LLMClient) -> int` and a CLI `--dir --n`.
      - It refuses any dir whose resolved path doesn't end in `scenarios/dev` or `scenarios/_staging/heldout`.
      - For each seed case (`.s`) it appends up to `n` new cases `<seed_id>.p<k>`, continuing after existing `.p*`, so a re-run adds nothing when `n` are present.
      - Each new case gets `source: paraphrase:gpt-6-luna:paraphrase@v1`, `reviewer: null`, `reviewed_at: null`, and the seed case's `language_variant`/`expected_language`.
      - Only `say` turns are sent, one structured call per turn returning `Paraphrases{items: list[str]}` of length `n`. A short list means that turn keeps the seed text for the missing variants.
      - A `say` turn with `paraphrase: false`, or one matching the PII detector (a digit run ≥6, an email, a phone number), is copied verbatim and not sent.
      - `confirm`/`cancel`/`otp`/`select` turns are copied.
      - No persona, fact sheet or labels go into the prompt.
    - `eval/prompts/paraphrase@v1.md` asks for the case's variant register (voseo es-AR, CO/MX lexicon, PT-BR, portuñol for `mixed`) and says to keep intent, slots and confirmation answers.
    - Test 8 (tmp dir at `tmp_path/"eval"/"scenarios"/"dev"`, `ScriptedLLM`): the 16-digit turn text appears in no `llm.calls[*].user`, and the new cases have the pinned `source`.
    - Docs:
      - `06` §2's SDK bullet adds `openai`/`langchain_openai` (eval paraphrase only).
      - `decision-log.md` gains ADR-030 as the spec's touch map describes it: eval-only, never in the served graph, no customer data, same R5/R7 rules; rejected alternatives: Bedrock Nova/Llama, ADR-028's plan.
  - Verify: `cd backend && uv run pytest tests/unit/test_paraphrase_seeds.py tests/unit/test_llm_client.py -q && uv run python -c "from pydantic import SecretStr; from app.core.llm.settings import LLMSettings; from app.core.llm.client import build_chat_model; s=LLMSettings(anthropic_api_key=SecretStr('x'), openai_api_key=SecretStr('x')); assert type(build_chat_model(s,'paraphrase')).__name__=='ChatOpenAI'; assert type(build_chat_model(s,'compose')).__name__=='ChatAnthropic'; print('ok')" && uv run ruff check app/core/llm scripts/paraphrase_seeds.py tests/unit/test_paraphrase_seeds.py && uv run ruff format --check app/core/llm scripts/paraphrase_seeds.py tests/unit/test_paraphrase_seeds.py && uv run mypy app/core/llm && uv run lint-imports`
  - Files: `backend/app/core/llm/{registry,settings,client}.py`, `backend/.importlinter`, `backend/pyproject.toml`, `backend/uv.lock`, `.env.example`, `backend/scripts/paraphrase_seeds.py`, `eval/prompts/paraphrase@v1.md`, `backend/tests/unit/test_paraphrase_seeds.py`, `docs/solution-docs/06-engineering-rules.md`, `docs/solution-docs/decision-log.md`

- [ ] T3: Scenario contract (`eval/scenarios/schema.py`) and the scripted HTTP driver (`eval/driver/`), with tests 5 and 6
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "B2: scenario file" and "B2: driver", and D8–D10, D17; `backend/scripts/chat_api.py` (`_csrf_headers`, `_run_turn`, `_run_otp`, `_run_confirmation`, `_run_pick`: the per-turn stream + CSRF analogue); `docs/solution-docs/04-contracts.md` §3 "SSE events" paragraph
  - Acceptance:
    - Schema:
      - `SeedFile`, `CaseVariant` and `Case` are Pydantic with `extra="forbid"`, with field names and literals exactly as the spec's YAML block.
      - `expected_db_state` items have exactly one of `expect`/`count`.
      - The `setup.faults` literals are pinned.
      - `load_dir(path)` returns `[]` for a missing or empty dir. It raises `ScenarioError` when the stem ≠ `seed_id`, on a duplicate `case_id`, on a `case_id` not matching `<seed_id>.s|.p<n>`, or on a turn with ≠1 key of `say/confirm/cancel/otp/select` (`paraphrase` is allowed only next to `say`).
    - Driver:
      - `run_case(case, *, base_url, otp_code, client=None, max_turns=12) -> Transcript`, with the `Transcript`/`TurnRecord` shapes from the spec.
      - Non-empty `setup.faults` or a set `expire_session_before_turn` gives `ended_by="not_runnable"` with zero HTTP calls.
      - It posts to test-idp → conversation, then per turn opens `GET …/stream`, waits for `: connected`, posts, and collects `event:` frames until `done`. There is a 60 s per-turn timeout (→ `error`).
      - `confirm`/`cancel` use the token of the last `ui.confirm` event seen; none gives `error="no_open_confirmation"`.
      - `select` needs an open `ui.transaction_list`; none gives `error="no_open_selection"`.
      - `otp` posts `/auth/otp/verify {code}`, then `{resume: "step_up"}`.
      - `mode{human}` → `handoff`, `ui.conversation_closed` → `closed`, and all turns played → `done`.
      - It never touches the DB.
    - CLI `python -m eval.driver --dir D [--case ID] --base-url URL --out F.jsonl` writes one JSON `Transcript` per line. `--base-url` has no default pointing at a deployed host (local stack only).
    - Test 6 uses `httpx.MockTransport` with scripted SSE per turn. Test 5 validates every file in `eval/scenarios/dev` and in `eval/scenarios/_staging/heldout` (or `eval/scenarios/heldout` if that exists; never writes there). Every persona must exist in `eval/personas.yaml` with `split` equal to the suite. It passes vacuously while the dirs are empty.
    - Nothing is created under `eval/scenarios/heldout/`.
  - Verify: `uv run --project backend pytest eval/tests/test_driver.py eval/tests/test_scenarios_valid.py -q && uv run --project backend python -m eval.driver --help && uv run --project backend ruff check --config backend/pyproject.toml eval/__init__.py eval/scenarios eval/driver eval/tests && uv run --project backend ruff format --check --config backend/pyproject.toml eval/__init__.py eval/scenarios eval/driver eval/tests`
  - Files: `eval/__init__.py`, `eval/scenarios/{__init__,schema}.py`, `eval/driver/{__init__,__main__,driver}.py`, `eval/tests/{__init__,test_driver,test_scenarios_valid}.py`

- [ ] T4: Persona split — `split: dev | heldout` on every persona, new held-out personas found by query, and the persona integration test accepts `split`
  - Depends on: nothing (needs the local `latam_golden`, which is up)
  - Read exactly these: spec D17; `eval/personas.yaml` (header + all entries); `backend/tests/integration/test_personas.py` (the predicate SQL to reuse for queries)
  - Acceptance:
    - Every persona has `split`.
    - Every persona id referenced outside `eval/` (grep `docs/`, `backend/`, `frontend/e2e`, `Makefile`, `README.md`) is `dev`.
    - New personas are added only with existing trait keys (a new trait key is ask-first) and verified by the same predicates, so each side (`dev` and `heldout`) has ≥1 persona for:
      - each decline code `05`/`14`/`51`/`54`
      - each country
      - multi-card and single-card
      - `blocked: true`
      - `customer_status` non-Active
      - `missing_income`
      - `regulator_case`
      - `has_pending_transaction`
      - `has_reversed_transaction`
      - `expiring_card`
    - One `dev` persona is marked in `notes` as the **criterion-2 demo**: its newest Declined transaction (by `transaction_date`, over all its cards) has code `54` and sits on an `Active` card. Check with SQL against `latam_app`, then add or reuse the persona.
    - Queries select ids and aggregates only (R10).
    - The header documents `split` as a non-trait key. `_NON_TRAIT_KEYS` gains `"split"`.
  - Verify: `cd backend && uv run pytest tests/integration/test_personas.py -q -rs 2>&1 | tail -1 | grep -E '^1 passed' && uv run ruff check tests/integration/test_personas.py && uv run python -c "import yaml,collections; p=yaml.safe_load(open('../eval/personas.yaml',encoding='utf-8'))['personas']; assert all(x.get('split') in ('dev','heldout') for x in p); print(collections.Counter(x['split'] for x in p))"`
  - Files: `eval/personas.yaml`, `backend/tests/integration/test_personas.py`

- [ ] T5: `decline_explain` flow — state, UI payload changes, templates, compose goal (`compose@v6`), graph registration, and the ES/PT tests for all 4 codes + no declines
  - Depends on: T1 (`explain_decline`, `DeclineCodeUnknown`, fixture `CLI-TFDECLN00006`; real names in the state file)
  - Read exactly these: spec D1–D7 and §"B1: backend" (`GraphState`, `ui.py`, templates bullets); `docs/solution-docs/02-conversation-design.md` §4.3; `backend/app/domains/conversation/flows/unrecognized_charge.py` (`_select_card`, `_offer_candidates`, `_tx_option`, `_resume_pick`: the card_select → offer → resume-pick analogue)
  - Acceptance:
    - Flow:
      - `flows/decline_explain.py` runs `card_select`, then `search_transactions(TxFilter(card_id=…, status=["Declined"]))`.
      - Picking per D2: no merchant/amount slot → the newest decline. Otherwise filter by case-insensitive merchant match or amount ±10%. One match → explain it. ≥2 → offer those. 0 → offer all. The date slot is ignored.
      - An offer is a `ui.transaction_list` with `multi=False` plus `decline_pick_ask`. It stores `decline = {card_id, offered_tx_ids}` and pauses `{flow: "decline_explain", node: "pick", awaiting_slot: "transactions"}`.
      - The resume re-checks: exactly one id, and it must be in `offered_tx_ids`. Anything else gives the fixed fallback, with no tool call.
      - `explain_decline` → facts `merchant`, `amount` (`format_money`), `tx_date` (`format_date`), `card_mask`, `decline_cause` = `cause_key`, `decline_next_step` = `next_step_key`, and hidden `currency`. Then `compose` with goal `decline_explain`.
    - `self_service` true → also a `ui.quick_replies{slot: "next_step", options: [label = decline_replacement_option]}`.
    - Zero declines → `decline_none` text. `DeclineCodeUnknown` → `decline_unknown` text. Neither makes an LLM call.
    - The flow has no write tool.
    - `ui.py`: `multi: bool` with no default, and `slot` adds `"next_step"`. `unrecognized_charge` passes `multi=True`.
    - Graph:
      - Registered in `_BRANCH_NODES`, `_INTENT_NODES`, `_FLOW_NODES`, every conditional-edge map and a `_after_flow` block.
      - `_entry` routes a selection to `_FLOW_NODES[pending["flow"]]`.
      - `runner._BRANCH_NODES` adds it.
    - `compose.py`: `Goal` adds `decline_explain`, and `_format_fact` renders `decline_cause`/`decline_next_step` via their templates. `_PROMPT` becomes v6, and `compose@v6.md` = v5 + the goal + one ES and one PT example. `test_compose.py` expects `compose@v6`.
    - `make graph-diagram` is re-run.
    - Test 1: `CLI-TFDECLN00006`, es/pt × each code via a `merchant_text` slot naming that code's merchant. It asserts `decline_cause`/`decline_next_step` values, that `amount`/`tx_date` equal the `format_money`/`format_date` output, and that the `next_step` quick reply appears iff code `54`.
    - Test 2: `CLI-TFMULTI00001` credit card (`card_hint: "credit"`), es/pt. It asserts the `decline_none` text and that `llm.calls` holds only the `nlu` call.
  - Verify: `cd backend && uv run pytest tests/unit/test_decline_explain_flow.py tests/unit/test_dispute_flows.py tests/unit/test_compose.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_checkpoint_serde.py -q && uv run ruff check app/domains/conversation tests/unit/test_decline_explain_flow.py tests/unit/test_compose.py && uv run ruff format --check app/domains/conversation tests/unit/test_decline_explain_flow.py tests/unit/test_compose.py && uv run mypy app/domains/conversation && uv run lint-imports && cd .. && make graph-diagram && grep -q decline_explain docs/diagrams/turn-graph-v0.mmd`
  - Files: `backend/app/domains/conversation/{state,ui,templates,graph,runner}.py`, `backend/app/domains/conversation/flows/{decline_explain,unrecognized_charge}.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/prompts/compose@v6.md`, `backend/tests/unit/{test_decline_explain_flow,test_compose}.py`, `docs/diagrams/turn-graph-v0.mmd`

- [ ] T6: Suite tooling — `mix_targets.yaml`, the mix report with the overlap check, the held-out freeze and check, `.gitattributes`, the four Makefile targets, the CI freeze-check step, and test 7
  - Depends on: T3 (`eval.scenarios.schema.load_dir`, `Case`), T4 (persona `split`)
  - Read exactly these: spec D11, D12, D18 and §"B3: tooling" (`mix_report.py`, `freeze.py`, `heldout.lock` bullets); this plan's §"Mix targets"; `Makefile`; `.github/workflows/ci.yml`
  - Acceptance:
    - `mix_targets.yaml` encodes exactly this plan's §"Mix targets" (the human confirmed the tolerances).
    - `python -m eval.scenarios.mix_report DIR` prints counts and shares by variant, category and category×`expected_language`, and exits 1 on any miss for the suite named by the dir.
    - `--dev D --heldout H` also checks both suites and fails on any shared `seed_id` or persona, or a persona whose `split` ≠ its suite. It prints `shared seeds: 0` / `shared personas: 0` on success.
    - `freeze`:
      - `freeze(root, *, mix_check=<default mix report on staging>)` refuses in order: `heldout/` or the lock exists; a staging case has a null `reviewer`/`reviewed_at`; the mix fails.
      - It then moves `_staging/heldout/*.yaml` into `heldout/` and writes the lock (spec JSON; `total` = sha256 over `name + "\0" + hex + "\n"` in sorted order).
      - It hashes raw bytes.
    - `check(root)`:
      - Passes when neither `heldout/` nor the lock exists.
      - Fails when exactly one of them exists, or on any added, removed or changed file or a total mismatch.
      - The CLI is `python -m eval.scenarios.freeze {freeze,check} [--root eval/scenarios]`. `check` imports stdlib only.
    - `.gitattributes` has `eval/scenarios/** -text`.
    - Makefile (added to `.PHONY`):
      - `eval-paraphrase DIR= N=`: `cd backend && uv run python scripts/paraphrase_seeds.py --dir ../$(DIR) --n $(N)`.
      - `eval-mix DIR=`.
      - `eval-freeze` (prints that a human runs it).
      - `eval-freeze-check`.
      - The last three are all `uv run --project backend python -m …` from the repo root.
    - `ci.yml`'s backend job gains a `make eval-freeze-check` step after `uv sync` (repo-root working dir).
    - Test 7 (tmp dir):
      - A freeze with `mix_check=lambda _: True`, then a one-character edit, makes `check` report failure.
      - A null `reviewer` makes `freeze` raise `FreezeRefused`.
    - Nothing is created under the real `eval/scenarios/heldout/`.
  - Verify: `uv run --project backend pytest eval/tests/test_freeze.py -q && make eval-freeze-check && make -n eval-paraphrase DIR=eval/scenarios/dev N=2 eval-mix DIR=eval/scenarios/dev && uv run --project backend ruff check --config backend/pyproject.toml eval/scenarios eval/tests/test_freeze.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/scenarios eval/tests/test_freeze.py && test ! -e eval/scenarios/heldout && test ! -e eval/scenarios/heldout.lock`
  - Files: `eval/scenarios/{mix_report,freeze}.py`, `eval/scenarios/mix_targets.yaml`, `eval/tests/test_freeze.py`, `.gitattributes`, `Makefile`, `.github/workflows/ci.yml`

- [ ] T7: Single-pick selection gate, the frontend single-select, and the `04` §1/§3 and `02` §4.3 doc updates, with test 4
  - Depends on: T5 (the `decline` state, the pause shape and the `multi=False` offer; names in the state file)
  - Read exactly these: spec D3 and §"B1: backend" (selection gate + "Update `04`…" bullets); `backend/app/api/v1/conversations.py` `post_message`; `backend/app/domains/conversation/runner.py` `checkpointed_dispute`
  - Acceptance:
    - `checkpointed_offer(host, conversation_id)` replaces `checkpointed_dispute` and returns `(pending, offered_ids, multi)`. It reads `decline` when `pending.flow == "decline_explain"` (multi False) and `dispute` otherwise (multi True). It returns `(None, set(), True)` with no checkpoint.
    - `post_message` returns `409 selection_invalid` unless: `awaiting_slot == "transactions"`, the ids are a subset of the offered ids, and `len == 1` when not multi.
    - Test 4 drives `decline_explain` to the pick with `make_session` (`CLI-TFDECLN00006`, a `merchant_text` that matches nothing → all 4 offered). It then calls `post_message` directly with a stub `request.app.state.turn_host.graph = session.graph`, a `ConversationRow` for the session's conversation id, and `start_turn` monkeypatched to a recorder. It asserts 409 for a non-offered id and for 2 offered ids, and that `start_turn` was never called.
    - Frontend:
      - `sse.ts`: `multi: boolean`, and quick-reply `slot` is `"block_kind" | "abstain" | "next_step"`.
      - `TransactionList` takes `multi`. When false it renders radio inputs (same `data-testid`s), and "Continuar" sends exactly one id.
      - `MessageList` passes `event.payload.multi`.
    - Docs:
      - `04` §1 row → `DeclineExplanation{code, cause_key, next_step_key, self_service, source}`.
      - `04` §3 → `multi: bool`, the `next_step` slot and the single-pick 409 rule.
      - `02` §4.3 → one line for D2.
  - Verify:
    ```
    make up
    cd backend
    uv run pytest tests/unit/test_selection_gate.py tests/unit/test_decline_explain_flow.py -q
    REDIS_URL=redis://127.0.0.1:6379/0 uv run python -c "import asyncio,sys,pytest; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); sys.exit(pytest.main(['tests/integration/test_confirmations_route.py','-q','-k','injected']))"
    uv run ruff check app/api/v1/conversations.py app/domains/conversation/runner.py tests/unit/test_selection_gate.py
    uv run ruff format --check app/api/v1/conversations.py app/domains/conversation/runner.py tests/unit/test_selection_gate.py
    uv run mypy app/api app/domains/conversation/runner.py
    cd ../frontend
    npx biome ci src/components/chat src/lib
    npm run typecheck
    npm run build
    npx playwright test e2e/unrecognized.es.spec.ts
    ```
    Chain every command with `&&` (`cd backend && … && cd ../frontend && …`).
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/api/v1/conversations.py`, `backend/tests/unit/test_selection_gate.py`, `frontend/src/components/chat/{TransactionList,MessageList}.tsx`, `frontend/src/lib/sse.ts`, `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`

- [ ] T8: Dev seed set — 27 seed files in `eval/scenarios/dev/`, `dev` personas only
  - Depends on: T3 (schema, test 5), T4 (`split`), T6 (`mix_targets.yaml`, mix report)
  - Read exactly these: spec §"B2: scenario file" and §"Boundaries"; `docs/solution-docs/05-evaluation-plan.md` §2–§3; `docs/solution-docs/04-contracts.md` §1 (tool names for `required_tools`/`forbidden_tools`) and §4 (handoff packet fields); `eval/personas.yaml`
  - Acceptance:
    - 27 files named `d-<intent>-<category>-<variant>-<nn>.yaml`, each with exactly one case `<seed_id>.s`, `source: seed`, `reviewer: null`.
    - Seed variants: es-MX 5, es-CO 4, es-AR 4, pt-BR 10, mixed 4.
    - Every one of the 10 categories has ≥1 seed with `expected_language: es` and ≥1 with `pt`.
    - Decline seeds cover all 4 codes.
    - At least one `decline_explain` case per code and one "no declines" case are runnable (no D6 `setup`).
    - The criterion-2 demo persona has a `decline_explain` seed that ends with `say: <the ES replacement quick-reply label>`.
    - Labels follow `02` §4 for the target behavior, including intents whose flow isn't built yet.
    - `expected_db_state` is used only for write flows.
    - Utterances are team-written with no real-looking PII, except `unauthorized` seeds, whose PII turns carry `paraphrase: false`.
    - Only `dev` personas.
    - Nothing is written outside `eval/scenarios/dev/`.
  - Verify: `uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && uv run --project backend python -c "from pathlib import Path; from collections import Counter; from eval.scenarios.schema import load_dir; c=load_dir(Path('eval/scenarios/dev')); v=Counter(x.language_variant for x in c); print(len(c), v, Counter(x.category for x in c)); assert len(c)==27 and v=={'es-MX':5,'es-CO':4,'es-AR':4,'pt-BR':10,'mixed':4}"`
  - Files: `eval/scenarios/dev/*.yaml` (27 new files)

- [ ] T9: Held-out staging seed set — 50 seed files in `eval/scenarios/_staging/heldout/`, `heldout` personas only
  - Depends on: T3 (schema, test 5), T4 (`split`), T6 (`mix_targets.yaml`, mix report)
  - Read exactly these: spec §"B2: scenario file", D11 and §"Boundaries"; `docs/solution-docs/05-evaluation-plan.md` §2–§3; `docs/solution-docs/04-contracts.md` §1 and §4; `eval/personas.yaml`
  - Acceptance:
    - 50 files named `h-<intent>-<category>-<variant>-<nn>.yaml`, one case each (`.s`, `source: seed`, `reviewer: null`, `reviewed_at: null`).
    - Seed variants: es-MX 8, es-CO 8, es-AR 9, pt-BR 18, mixed 7.
    - Exactly 5 seeds per category, each category with ≥1 `es` and ≥1 `pt` seed.
    - Decline seeds cover all 4 codes.
    - Labels, PII rule and `paraphrase: false` rule are as in the dev set.
    - Only `heldout` personas. No `seed_id` or persona is shared with `eval/scenarios/dev/` (the prefix guarantees ids).
    - **Nothing under `eval/scenarios/heldout/`**, and no lock file.
  - Verify: `uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && uv run --project backend python -c "from pathlib import Path; from collections import Counter; from eval.scenarios.schema import load_dir; c=load_dir(Path('eval/scenarios/_staging/heldout')); v=Counter(x.language_variant for x in c); k=Counter(x.category for x in c); print(len(c), v, k); assert len(c)==50 and v=={'es-MX':8,'es-CO':8,'es-AR':9,'pt-BR':18,'mixed':7} and set(k.values())=={5}" && test ! -e eval/scenarios/heldout`
  - Files: `eval/scenarios/_staging/heldout/*.yaml` (50 new files)

- [ ] T10: Live proofs on the local stack — paraphrase both suites, mix and overlap reports exit 0, and the driver plays every dev case
  - Depends on: T2 (script + step), T3 (driver), T5 + T7 (flow + gate live), T6 (mix/overlap), T8 + T9 (seeds)
  - Read exactly these: spec §"Success criteria" 2–4 and 7; this plan's §"Mix targets" and Risks 6, 11, 12; `Makefile` (`eval-*` targets)
  - Acceptance:
    - Preconditions: `.env` has non-empty `OPENAI_API_KEY`, `APP_ENV=eval` and `DEMO_OTP_CODE`. Check with `grep -c '^OPENAI_API_KEY=.\+'` and the same for the other two, never printing values. If any is missing, stop and escalate; do not edit `.env`.
    - Then `make up` rebuilds the image with `langchain-openai`.
    - `make eval-paraphrase DIR=eval/scenarios/dev N=2` and `make eval-paraphrase DIR=eval/scenarios/_staging/heldout N=2` add paraphrases.
    - `make eval-mix` exits 0 for both dirs, and the `--dev/--heldout` overlap run prints 0 shared seeds and 0 shared personas.
    - On a shortfall, re-run the paraphrase. If a miss remains, escalate: don't edit tolerances or seed labels.
    - `uv run --project backend python -m eval.driver --dir eval/scenarios/dev --base-url http://localhost --out <scratchpad>/dev.jsonl` writes one transcript per dev case. Every case without D6 `setup` ends in something other than `error`/`not_runnable`.
    - The criterion-2 demo case's transcript shows the formatted amount/date in the bot message, a `quick_replies` `next_step` event, and a later turn that reaches the `replacement` flow. The human's own `make chat-api` check stays manual.
    - Log counts per `ended_by` in the state file. A failing case is logged with its `case_id` and the first error event. Fixing it is not in scope unless it's a driver bug.
    - `git status --porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock` prints nothing.
  - Verify: `make eval-mix DIR=eval/scenarios/dev && make eval-mix DIR=eval/scenarios/_staging/heldout && uv run --project backend python -m eval.scenarios.mix_report --dev eval/scenarios/dev --heldout eval/scenarios/_staging/heldout && uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && uv run --project backend python -c "import json,sys,collections; t=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]; c=collections.Counter(x['ended_by'] for x in t); print(len(t), c)" <scratchpad>/dev.jsonl && test -z "$(git status --porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock)"`
  - Files: `eval/scenarios/dev/*.yaml`, `eval/scenarios/_staging/heldout/*.yaml` (paraphrase cases appended by the script; no hand edits)
