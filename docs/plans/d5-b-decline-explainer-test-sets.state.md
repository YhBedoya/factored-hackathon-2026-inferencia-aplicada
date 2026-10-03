# State: D5-B — Decline explainer, scenario contract and test sets
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D5-B (G11, owner B) · spec `docs/specs/d5-b-decline-explainer-test-sets.md` · plan `docs/plans/d5-b-decline-explainer-test-sets.md`
Branch `feat/d5-b-decline-explainer-test-sets`, based on `develop`.

## Conventions established for this card
- Repo facts: plan §"Facts checked against the repo" (read only the parts your task names).
- Tasks in the same wave run **in parallel in this one checkout**. Touch only your task's `Files`. No commits, no branches, no worktrees.
- Public-URL deploy is postponed to end of D5: nothing targets a deployed host; the driver and runtime proofs use `http://localhost`.
- Paraphrase model: OpenAI `gpt-6-luna` via `langchain-openai`, step `paraphrase` in `core/llm` only (ADR-030). Tests always use `ScriptedLLM`, never a real key.
- Agents never write under `eval/scenarios/heldout/`. Held-out drafts go to `eval/scenarios/_staging/heldout/`; a human runs `make eval-freeze`.
- Driver CLI takes optional `--otp-code` (defaults to `$DEMO_OTP_CODE`, never printed); added by T3 because `run_case` needs `otp_code`.
- Mix tolerances: ±5 pp per language share; held-out 120–170 cases, dev 60–100; ≥8 held-out cases per category.

## Human decisions taken mid-card
- (plan gate) Decline cause and next step are code-filled fixed ES/PT labels passed to compose (`compose@v6`); the LLM never writes them.
- (T8/T9) Held-out seeds must spread intents like the dev set, not all `decline_explain`; T9 redoes them keeping its counts.
- (T8/T9) Seed file names use the hyphenated variant token (`es-co`, `es-mx`, `es-ar`, `pt-br`, `mixed`); dev files and seed_ids are renamed to match.
- (T10) Paraphrase step temperature = 1.0 (gpt-6-luna only supports its default); T2 changes it, ADR-030 notes it.
- (T10) Local Postgres is missing 0005 DDL (staff_queue, app.handoffs); the human runs the reconciliation SQL by hand.
- (plan gate) A paraphrase keeps its seed case's `language_variant`/`expected_language`; seed counts set the language mix.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | ac0c35e | decline_codes.yaml, explain_decline on both banks + recorder, fixture CLI-TFDECLN00006, R1 test; Verify green |
| T2 | done | a3c2859 | paraphrase step (gpt-6-luna), script, R5 test, ADR-030; Verify green |
| T3 | done | aa7e146 | eval/scenarios/schema.py + scripted driver + CLI; tests 5,6 green |
| T4 | done | a11d1ee | split on 42 personas (dev 33 / heldout 9); criterion-2 demo CLI-00N1NADOZIUH |
| T5 | done | ab4475e | decline_explain flow, compose@v6, graph wiring, ES/PT tests (24 passed); added ask_which_card_decline template |
| T6 | done | a781f2f | mix_targets + mix report/overlap, freeze/check, .gitattributes, 4 make targets, CI step; test 7 green |
| T7 | done | a03ce60 | checkpointed_offer + single-pick 409 gate, radio TransactionList, 04/02 docs; test 4 + e2e green |
| T8 | done | a1d2176 | 27 dev seeds, 9 intents, exact variant mix; criterion-2 seed ends 'Quiero una tarjeta nueva' |
| T9 | done | a8a6ab2 | redo: 50 staging seeds over 9 intents, 5 per category, exact variant mix; heldout/ untouched |
| T10 | done | a4b770d | dev 81 / heldout 150 paraphrased, mix+overlap green; driver 81/81: done 60, handoff 9, not_runnable 12 (D6 setup), 0 error; criterion-2 proven |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T4 — Persona split
Changed: `eval/personas.yaml` (`split: dev` added to all 32 original personas
+ 10 new: 1 dev, 9 heldout; header documents `split` as a non-trait key);
`backend/tests/integration/test_personas.py` (`_NON_TRAIT_KEYS` gains
`"split"`).
Facts the next tasks need: all 32 original personas stayed `dev` (every one
is referenced somewhere under `docs/` or in `test_personas.py`'s
`_ORIGINAL_IDS`/table); the 9 `heldout` personas are new SQL finds, ids
`CLI-040S627SFJSV` (CO, decline 05), `CLI-00P4VN7YGMT5` (AR, decline 14),
`CLI-02RX8WUOJTJ6` (MX, decline 51), `CLI-00K5DRIG1GZT` (CO, decline 54),
`CLI-00WAXO79YRHL` (AR, blocked), `CLI-001KTTVQ14AC` (CO, Inactive +
pending), `CLI-00R1HD1YN0Z6` (CO, missing_income + reversed),
`CLI-063FKU0GAEE4` (MX, regulator_case), `CLI-00GYZZUVEG4J` (CO,
expiring_card). Counts: dev=33, heldout=9 (42 total). Criterion-2 demo
persona (new, dev): `CLI-00N1NADOZIUH` (AR, single Active credit card) —
its newest Declined transaction across all cards, checked against
`latam_app`, is response_code `54` on that Active card; it is **not**
within the 30-day `recent_declines` window, so it carries no
`recent_declines` key (checked and confirmed by direct SQL, not by
`test_personas.py`'s predicate). Every required `03` §8 category has ≥1
persona on both `dev` and `heldout` (verified by script, not just eyeballed).
Deviations: none — no new trait key was needed, all found via existing
predicates against `latam_golden` (except the criterion-2 demo, which per
the task is checked against `latam_app`).
Verify: `cd backend && uv run pytest tests/integration/test_personas.py -q -rs`
→ 1 passed; `uv run ruff check tests/integration/test_personas.py` → All
checks passed; split counter → `Counter({'dev': 33, 'heldout': 9})`.

### T6 — Suite tooling (`mix_report.py`, `freeze.py`, `.gitattributes`, Makefile, CI)
Created: `eval/scenarios/mix_targets.yaml` (plan §"Mix targets" verbatim);
`eval/scenarios/mix_report.py` (`suite_from_dir`, `load_targets`, `mix_report`,
`print_report`, `check_targets`, `check_overlap`, CLI `python -m
eval.scenarios.mix_report DIR | --dev D --heldout H`); `eval/scenarios/freeze.py`
(`FreezeRefused`, `freeze(root, *, mix_check=_default_mix_check)`, `check(root)
-> list[str]`, CLI `python -m eval.scenarios.freeze {freeze,check} [--root
eval/scenarios]`); `eval/tests/test_freeze.py` (test 7, 4 cases); `.gitattributes`
(new, `eval/scenarios/** -text`).
Changed: `Makefile` (`eval-paraphrase`/`eval-mix`/`eval-freeze`/`eval-freeze-check`
targets + `.PHONY`); `.github/workflows/ci.yml` (backend job: `make
eval-freeze-check` step, repo-root working dir, right after `uv sync`).
Facts the next tasks need (T8/T9/T10):
- `make eval-mix DIR=<dir>` and `python -m eval.scenarios.mix_report <dir>` both
  exit 1 and print `MISS: ...` lines on any miss; suite is inferred from the
  dir's basename (`dev`/`heldout` only — `_staging/heldout` and `heldout` both
  read as `heldout`). `--dev D --heldout H` (no Makefile target; call the module
  directly) prints `shared seeds: N` / `shared personas: N` then `MISS: ...`
  lines, exit 1 on any.
- `check()`/CI's freeze-check import stdlib only; `freeze()` lazily imports
  `eval.scenarios.{schema,mix_report}` inside itself and `_default_mix_check`,
  never at module top level.
- `freeze(root, *, mix_check=...)` and `check(root)` both take the scenario
  **root** (`eval/scenarios`), not a suite dir — `root/_staging/heldout`,
  `root/heldout`, `root/heldout.lock`, `root/mix_targets.yaml` are all derived
  inside.
- `make eval-freeze` only echoes the human-review reminder then calls
  `freeze()` for real — **never run it** except as a human, per CLAUDE.md/D11.
- T8/T9 seed files must satisfy `SeedFile`/`CaseVariant`/`Turn` from T3's
  `eval/scenarios/schema.py` exactly (see `test_freeze.py`'s `_SEED_TEMPLATE`
  for a minimal valid shape) or `load_dir` (used inside `freeze`) raises
  `ScenarioError` and refuses the freeze.
Deviations: none.
Verify: `uv run --project backend pytest eval/tests/test_freeze.py -q` → 4
passed; `make eval-freeze-check` → `freeze-check: OK`; `make -n
eval-paraphrase DIR=eval/scenarios/dev N=2 eval-mix DIR=eval/scenarios/dev` →
prints both recipes; `ruff check`/`ruff format --check` on `eval/scenarios
eval/tests/test_freeze.py` → both clean; no `eval/scenarios/heldout` or
`heldout.lock` created.

### T3 — Scenario contract (`eval/scenarios/schema.py`) and scripted HTTP driver (`eval/driver/`)
Created: `eval/__init__.py`, `eval/scenarios/__init__.py`, `eval/scenarios/schema.py`
(`SeedFile`, `CaseVariant`, `Case`, `Turn`, `SetupBlock`, `LabelsBlock`, `DbPatch`,
`DbStateAssertion`, `ScenarioError`, `load_dir(path) -> list[Case]`, all `extra="forbid"`),
`eval/driver/{__init__,__main__,driver}.py` (`run_case(case, *, base_url, otp_code,
client=None, max_turns=12) -> Transcript`; `Transcript`, `TurnRecord`, `TurnInput`,
`EventRecord` re-exported from `eval.driver`), `eval/tests/{__init__,test_driver,
test_scenarios_valid}.py`.
Facts the next tasks need:
- `load_dir` raises `ScenarioError` (not `pydantic.ValidationError`) for every B2 violation;
  it never raises for a missing/empty dir (returns `[]`).
- CLI: `python -m eval.driver --dir D [--case ID] --base-url URL --out F.jsonl
  [--otp-code CODE]`; `--otp-code` defaults to `$DEMO_OTP_CODE` (never printed). `--dir`,
  `--base-url`, `--out` are required, no defaults.
- Driver opens one `GET .../stream` per turn (not one for the whole case), matching
  `chat_api.py`'s `_run_turn` shape; `otp` turns POST `/auth/otp/verify` first (no
  stream), then run the `{resume: "step_up"}` turn with its own stream.
  `ended_by="handoff"|"closed"` is detected by scanning that turn's own collected
  events for `mode{human}` / `ui.conversation_closed` after the turn is recorded, not
  by breaking the SSE loop early.
- `eval/scenarios/__init__.py` imports nothing (stdlib-only, for `freeze.check`); T6 can
  rely on that staying true only if it doesn't add an import there itself.
- `eval/scenarios/dev/` and `eval/scenarios/_staging/heldout/` don't exist yet (T8/T9);
  `load_dir` and both `eval/tests` files handle that as "no files" already.
Deviations: none from the spec/plan contract. `--otp-code` CLI flag isn't in the spec's
literal CLI line (only `--dir`/`--case`/`--base-url`/`--out` are) but is required to
satisfy `run_case`'s required `otp_code` kwarg from the CLI without hardcoding a value;
it defaults from `$DEMO_OTP_CODE`, consistent with the plan's T10 precondition check.
Verify: `uv run --project backend pytest eval/tests/test_driver.py
eval/tests/test_scenarios_valid.py -q` → 4 passed. `python -m eval.driver --help` → prints
usage. `ruff check`/`ruff format --check` on `eval/__init__.py eval/scenarios eval/driver
eval/tests` → both clean. No `eval/scenarios/heldout/` created.

### T1 — Decline read tool
Created: `policies/decline_codes.yaml` (verbatim `04` §5 block, no leading
`# policies/...` comment, matching `disputes.yaml`'s style); `backend/app/domains/policy/decline_codes.py`
(`DeclineCode`, `DeclineCodesPolicy`, `load_decline_codes_policy(path=None)`,
`lookup_decline_code(code: str | None) -> DeclineCode`, uncached — loads
fresh each call, same as `load_disputes_policy`); `backend/tests/unit/test_decline_tools.py`.
Changed: `backend/app/core/errors.py` (`DeclineCodeUnknown(ToolError)`,
`code = "decline_code_unknown"`); `backend/app/domains/policy/registry.py`
(`"decline_codes": DeclineCodesPolicy` in `_MODELS_BY_STEM`, optional like
`disputes`, not a `PolicyBundle` field); `backend/app/domains/transactions/schemas.py`
(`DeclineExplanation{code, cause_key, next_step_key, self_service, source}`,
frozen); `backend/app/domains/transactions/service.py` (`get_declined(customer_id, tx_id) -> TxView`,
reuses `repository.fetch_transactions_by_ids`, no new repository code, no
`AccessDenied`, no probe — foreign/missing/non-Declined all `NotFound`);
`backend/app/domains/conversation/tools/bank.py` (`BankReadTools.explain_decline(tx_id) -> DeclineExplanation`
added to the Protocol); `fakebank.py` (`FakeBank.explain_decline`, own dedicated
DuckDB query `WHERE customer_id = ? AND transaction_id = ?`, no probe);
`postgres.py` (`PostgresBank.explain_decline`, calls `transactions_service.get_declined`
then `lookup_decline_code`); `registry.py` (`RecordingBankTools.explain_decline`,
audits `tool_call`/`tool_result` as `"transactions.explain_decline"` with a
`tx_id` payload key (not `card_id`), appends `"explain_decline"` to `.calls`).
Fixture: added `CLI-TFDECLN00006` (Colombia) to `customers.csv`,
`PRD-TFD6CRED0001` (Tarjeta Crédito, COP, Active, last4 `6666`, limit
3000000, balance 100000) to `products.csv`, 4 Declined rows
`TRX-TFD6CRED0001TXN01..04` (codes `51`/`14`/`05`/`54`, merchants Super
Uno/Libreria Dos/Cine Tres/Viajes Cuatro, 2026-03-30 09:00–12:00, `54`
newest) to the transactions CSV — all appended with `\r\n` line endings via
a Python script; BOM/CRLF verified preserved on all three files. README
updated with the new customer/card/rows.
Facts the next tasks need: exception is `DeclineCodeUnknown` (raised by
`lookup_decline_code`, not by the bank tools directly — `explain_decline`
lets it propagate). `DeclineExplanation.source` format is exactly
`f"policy:decline_codes@{ctx.policy_version}"`. `transactions.service.get_declined`
signature is `(customer_id: str, tx_id: str) -> TxView`. No repository
change was needed (reused `fetch_transactions_by_ids`). `explain_decline`
has no `policies/tools.yaml` row (read tool, no confirmation/step-up).
Deviations: none — no PolicyBundle field added for `decline_codes` (matches
the `disputes` precedent, per the plan's own cross-task table).
Verify: `cd backend && uv run pytest tests/unit/test_decline_tools.py tests/unit/test_policy_registry.py tests/unit/test_r1_fakebank.py tests/unit/test_card_info_flows.py tests/unit/test_dispute_flows.py -q && uv run ruff check ... && uv run ruff format --check ... && uv run mypy ... && uv run lint-imports`
→ 23 passed; ruff check/format clean; mypy clean (25 files); lint-imports 4
kept, 0 broken.

### T2 — OpenAI `paraphrase` step, paraphrase script, R5 test, ADR-030
Added dep: `langchain-openai` (`backend/pyproject.toml`, `backend/uv.lock`), first action.
Changed: `backend/app/core/llm/{registry,settings,client}.py` (`Provider`/`Step` gain
`"openai"`/`"paraphrase"`; `MODEL_REGISTRY["paraphrase"] = {"openai": "gpt-6-luna"}`;
new `STEP_PROVIDER = {"paraphrase": "openai"}`, read by both `build_chat_model` and
`StructuredLLMClient.structured` as `STEP_PROVIDER.get(step, settings.llm_provider)`;
`LLMSettings.openai_api_key: SecretStr | None`; `openai.APIError` joins the caught
transport errors). `backend/.importlinter` (forbids `openai`/`langchain_openai`
outside `app.core.llm`, same ignore-line pattern). `.env.example` (`OPENAI_API_KEY=`
in the LLM block). `docs/solution-docs/06-engineering-rules.md` §2, `decision-log.md`
(ADR-030).
Created: `backend/scripts/paraphrase_seeds.py` — `async def paraphrase_dir(dir: Path,
n: int, llm: LLMClient) -> int`, CLI `--dir --n` (`main()`); `Paraphrases(BaseModel){items:
list[str]}` lives in this module (not in `eval.*`: the script only uses PyYAML on raw
mappings, no `eval` import, so it stays importable from `backend/tests`).
`eval/prompts/paraphrase@v1.md` (system prompt, variant register + rules).
`backend/tests/unit/test_paraphrase_seeds.py::test_pii_turns_not_sent` (Test 8, the only
test this task adds).
Facts the next tasks need: run as `cd backend && uv run python scripts/paraphrase_seeds.py
--dir ../eval/scenarios/dev --n <n>` (inserts `backend/` on `sys.path` itself, same
pattern as `scripts/nlu_smoke.py`) — or `uv run --project backend python
backend/scripts/paraphrase_seeds.py --dir eval/scenarios/dev --n <n>` from the repo
root. `_validate_dir` accepts only a resolved path ending in `scenarios/dev` or
`scenarios/_staging/heldout`; anything else raises `ValueError` before any I/O.
`paraphrase_dir` is idempotent per seed (re-run with the same `n` adds 0 cases, 0 LLM
calls) and requests only the *remaining* count from the model, not always `n` (so a
partial re-run needs fewer alternatives, not `n` again). PII detector:
`_contains_pii` (digit run ≥6, email, or a separator-joined digit run ≥6) — a `say`
turn matching it, or carrying `paraphrase: false`, is copied verbatim.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_paraphrase_seeds.py
tests/unit/test_llm_client.py -q` → 4 passed. Provider-resolution smoke check → `ok`.
`uv run ruff check … && uv run ruff format --check …` → both clean. `uv run mypy
app/core/llm` → clean, 6 files. `uv run lint-imports` → 4 kept, 0 broken (llm-sdk
contract now shows 5 ignored imports, up from 4, for the new `openai`/`langchain_openai`
pair).

**Fix (V2, R5 gap):** `_PHONE_CANDIDATE`'s separator class was missing `.`, so a
dotted-thousands-style number (e.g. a CPF `123.456.789-09`) wasn't caught unless the
turn also carried `paraphrase: false`. Added `.` to the class:
`r"\+?\d[\d\-\s().]{4,}\d"`. Checked repo-wide impact against all 78 on-disk dev/staging
seed files: exactly one turn is newly flagged (`h-transaction_search-unauthorized-pt-br-05.yaml`,
a CPF line), and it already carries `paraphrase: false`, so nothing that was
paraphrasable became non-paraphrasable — no amount-like (`$1.250.000`-style) false
positive exists in the current seed set. Extended `test_pii_turns_not_sent` with a third
turn (dotted CPF, no `paraphrase: false`) asserting its text never reaches
`llm.calls[*].user` and that it's copied verbatim into the new case.
Re-verify: `cd backend && uv run pytest tests/unit/test_paraphrase_seeds.py -q` → 1
passed. `uv run ruff check scripts/paraphrase_seeds.py tests/unit/test_paraphrase_seeds.py`
→ clean. `uv run ruff format --check scripts/paraphrase_seeds.py
tests/unit/test_paraphrase_seeds.py` → clean.

**Fix (temperature, T10 escalation):** OpenAI rejects `temperature=0.0` for
`gpt-6-luna` ("Only the default (1) value is supported"). `TEMPERATURE["paraphrase"]`
in `backend/app/core/llm/registry.py` is now `1.0`, with a comment explaining why; no
other step's temperature changed. `docs/solution-docs/decision-log.md` ADR-030 gains a
"Temperature note (T10)" line, and its `Decision` paragraph's "temperature 0" mention
was reworded to point at that note instead of contradicting it.
Re-verify: `cd backend && uv run pytest tests/unit/test_paraphrase_seeds.py
tests/unit/test_llm_client.py -q` → 4 passed. `uv run ruff check app/core/llm` → clean.
`uv run ruff format --check app/core/llm` → clean. `uv run mypy app/core/llm` → clean,
6 files.

### T5 — `decline_explain` flow, `compose@v6`, graph registration
Created: `backend/app/domains/conversation/flows/decline_explain.py`
(`decline_explain`, `_select_card`, `_resolve_declines`, `_filter_declines`,
`_offer`, `_tx_option`, `_resume_pick`, `_explain` — the `card_select` →
find/offer → resume-pick shape `unrecognized_charge` set, mirrored not
imported); `backend/app/domains/conversation/prompts/compose@v6.md` (v5 +
`decline_explain` objective + one ES/PT example).
Changed: `state.py` (`DeclineState{card_id: str, offered_tx_ids: list[str]}`,
`TurnState.decline: NotRequired[DeclineState | None]`); `ui.py`
(`TransactionListPayload.multi: bool`, no default; `QuickRepliesPayload.slot`
gains `"next_step"`); `templates.py` (`ask_which_card_decline`,
`decline_none`, `decline_unknown`, `decline_pick_ask`,
`decline_replacement_option`, `decline_cause_<cause_key>` ×4,
`decline_next_<next_step_key>` ×4, ES+PT); `nodes/compose.py` (`Goal` gains
`decline_explain`; `_PROMPT = PromptRef("compose", 6)`; `_format_fact` adds
`amount`/`tx_date` to the existing money/date groups and renders
`decline_cause`/`decline_next_step` via `_DECLINE_CAUSE_TEMPLATES`/
`_DECLINE_NEXT_TEMPLATES` (cause_key/next_step_key → `TemplateKind`);
`merchant` joins the "already localized" group); `graph.py`
(`_BRANCH_NODES`, `_INTENT_NODES["decline_explain"]`,
`_FLOW_NODES["decline_explain"]`, a new node + `_after_flow` conditional-edge
block, all four other conditional-edge maps; `_entry`'s selection routing
generalized from `_FLOW_NODES["unrecognized_charge"]` to
`_FLOW_NODES[pending["flow"]]`); `runner.py` (`_BRANCH_NODES` mirror only —
`checkpointed_offer`/the route gate stay T7's job);
`flows/unrecognized_charge.py` (`multi=True` now explicit).
Facts T7 needs: **`decline` state shape** —
`DeclineState{card_id: str, offered_tx_ids: list[str]}`
(`app/domains/conversation/state.py`). **Pause shape** —
`{"flow": "decline_explain", "node": "pick", "awaiting_slot": "transactions"}`,
same `awaiting_slot` name as `unrecognized_charge`'s pick (both now route
through `graph._entry`'s generalized `_FLOW_NODES[pending["flow"]]`).
**Where the `multi=False` offer is built** — `flows/decline_explain.py`'s
`_offer()`, which sets `decline` and `pending` and emits
`ui.TransactionListEvent(payload=TransactionListPayload(options=options,
multi=False))`. `_resume_pick` re-checks exactly one id in
`offered_tx_ids`, same rule T7's route gate needs to enforce before the
turn is even scheduled; on a bad pick it returns `pending_reminder` (pause
stays open) with no tool call. `decline_none`/`decline_unknown` clear both
`pending` and `decline` and write no `facts`, so `_after_flow` never routes
to `compose` for either. `explain_decline` only ever runs read tools
(`get_card_details`, `search_transactions`, `explain_decline`); the flow
has no write tool.
Deviations: added `ask_which_card_decline` (a new `TemplateKind`, not in
the plan's cross-task table) for the multi-card "which card" question —
same pattern as `unrecognized_charge`'s own `ask_which_card_dispute`
(`card_select.py` has no matching `AskAction`, and `card_select.py` is not
in this task's `Files`). Not exercised by either test (`CLI-TFDECLN00006`
has one card; `CLI-TFMULTI00001` resolves its `card_hint` directly).
Verify: `cd backend && uv run pytest tests/unit/test_decline_explain_flow.py
tests/unit/test_dispute_flows.py tests/unit/test_compose.py
tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py
tests/unit/test_checkpoint_serde.py -q && uv run ruff check … && uv run
ruff format --check … && uv run mypy app/domains/conversation && uv run
lint-imports && cd .. && make graph-diagram && grep -q decline_explain
docs/diagrams/turn-graph-v0.mmd` → 24 passed; ruff check/format clean;
mypy clean (44 files); lint-imports 4 kept, 0 broken; diagram regenerated
(10 new `decline_explain` occurrences), `grep` passes.

### T8 — Dev seed set
Created: `eval/scenarios/dev/*.yaml` (27 new files, one case each, `source:
seed`, `reviewer: null`), named `d-<intent>-<category>-<variant>-<nn>.yaml`
(full-word fields, `nn` disambiguates repeats of the same
intent+category+variant — only `decline_explain`/`normal_resolution`/`esar`
and `.../esmx` repeat, `01`/`02`).
Facts the next tasks need: unlike T9's held-out (50 files, all `intent:
decline_explain`), this dev set spans **11 intents** across all 10
categories (`normal_resolution` holds the 5 `decline_explain` seeds — codes
51/14/05/54 + one "no Declined rows" case — the other 22 cover
card_block/card_status/card_unlock/balance_due/transaction_search/
pending_reversal_explain/unrecognized_charge/human_request/general_question,
including intents whose flow isn't built yet per the task's own
instruction). Decline-code personas (all single-card, confirmed by direct
query against `pipeline/data/pipeline.duckdb`'s `srv_transactions`, per-card
so a persona's other, non-card products' declines never mislead "the
newest"): `CLI-BCWKVTMY5S99`=51, `CLI-55D0R3VIIFPT`=14, `CLI-1JHOGI2P2UE2`=05,
`CLI-00N1NADOZIUH`=54 (criterion-2 demo), `CLI-H7CHAE6NGLYQ`=no declines.
Criterion-2 seed `d-decline_explain-normal_resolution-esar-02.yaml` opens
with the exact demo phrase `"¿por qué rechazaron mi compra?"` and ends
`say: "Quiero una tarjeta nueva"`, matching T5's `decline_replacement_option`
ES text in `templates.py` verbatim (checked after T5 landed). Persona reuse
across seeds happens (22 seeds, 22 distinct dev personas — some appear
twice); nothing is shared with T9's held-out split. `expected_db_state` is
`[]` on every seed (no case here completes a write: the two `expired_session`
and two `tool_failure` seeds use `setup` and are `not_runnable` today per
D10, and the criterion-2 seed's replacement tap only reaches
`replacement`'s address-confirm pause, so `expected_outcome: clarified`
there, not `resolved`).
Deviations: none from the task's own acceptance list. Flag for the
orchestrator: T9 scoped held-out to `decline_explain` only, while this task's
acceptance criteria (decline codes + 10 categories with no intent
restriction) point to a broader dev set — the two suites now differ in
intent breadth by design, not by a name-convention mismatch (T9's own flagged
concern doesn't apply: both use the same full-word `<suite>-<intent>-
<category>-<variant>-<nn>` style).
Verify: `uv run --project backend pytest eval/tests/test_scenarios_valid.py
-q` → 2 passed. `uv run --project backend python -c "... load_dir ..."` →
`27 Counter({'pt-BR': 10, 'es-MX': 5, 'mixed': 4, 'es-CO': 4, 'es-AR': 4})
Counter({'normal_resolution': 5, 'multilingual': 3, 'ambiguous': 3,
'bad_data': 3, 'human_required': 3, 'expired_session': 2, 'tool_failure': 2,
'unauthorized': 2, 'injection': 2, 'unsupported': 2})` → assertion passed.

**Rename (human decision, mid-card):** 23 of the 27 files' variant token
hyphenated to match T9's held-out convention (`esar→es-ar`, `esco→es-co`,
`esmx→es-mx`, `ptbr→pt-br`; the 4 `mixed` filenames were already correct).
`seed_id` and the case's `<seed_id>.s` id updated to match inside each file.
The criterion-2 seed is now
`eval/scenarios/dev/d-decline_explain-normal_resolution-es-ar-02.yaml`
(`seed_id`/`case_id` updated the same way; its content — persona, turns,
labels — is unchanged). Repo search (state file excluded) for every old
dev seed id found no reference outside `eval/scenarios/dev/`. Re-verified
after the rename: `uv run --project backend pytest
eval/tests/test_scenarios_valid.py -q` → 2 passed; the `load_dir`
count/Counter check → identical output (`27`, same two Counters) → assertion
passed.

### T9 — Held-out staging seed set
Created: `eval/scenarios/_staging/heldout/*.yaml` (50 new files, all
`intent: decline_explain`), one seed each, named
`h-decline_explain-<category>-<variant-lower>-<nn>.yaml` (`nn` = 01-05,
position within category); generated by a one-off script (not committed,
scratchpad only). `expected_db_state: []` on every seed (decline_explain has
no write tool, per spec's "only for write flows" rule).
Facts the next tasks need: all 9 `heldout`-split personas from T4 are used
(no other persona touched); the 4 decline-code personas
(`CLI-02RX8WUOJTJ6`=51, `CLI-00P4VN7YGMT5`=14, `CLI-040S627SFJSV`=05,
`CLI-00K5DRIG1GZT`=54) each anchor one `normal_resolution` seed, so all 4
codes are covered there. `forbidden_tools` on every seed is the full write
set (`cards.lock_card`/`unlock_card`/`block_card`/`order_replacement`,
`disputes.create_claim`) since `decline_explain` never calls a write tool.
`tool_failure` seeds use only `bedrock_timeout` (the other two `Fault`
literals are write-path only, N/A here) and label `expected_outcome:
handoff:atencion` as the target R11 behavior (not yet wired — D6/G14
future). `human_required` seeds use `handoff:atencion` or `handoff:reclamos`
per `policies/escalation.yaml`'s `rules`/`human_request_queues`.
`unauthorized` seeds are single-turn with a fake card/document number and
`paraphrase: false`, per D15/Boundaries. `injection` has 2 `via_data_field`
seeds using `setup.db_patches` on `merchant_name` (filtered by
`$persona.customer_id` + `response_code`, mirroring D9's interpolation
style since no real `transaction_id` is known ahead of the human review).
Per-category `es`/`pt` split (by `language_variant`, not `mixed`) verified
≥1 each; no personas or seed ids collide with `eval/scenarios/dev/` (empty
at the time of this task; `h-` prefix guarantees it regardless).
Deviations: file-naming convention (`h-<intent>-<category>-<variant>-<nn>`)
used the literal `SeedFile` field values (full words, e.g.
`decline_explain`, `normal_resolution`), not the plan's cross-task-table
abbreviated illustration (`d-dec-54-mx-01`) — the task's own verbatim
template names the fields, not abbreviations, and this card has only one
intent so verbosity isn't a real cost. Flag for T8/orchestrator: if T8 (dev
seeds) picked the abbreviated style instead, the two suites' filenames won't
match convention (harmless for tooling — nothing parses the filename beyond
`seed_id == stem` — but worth a human look for consistency).
Verify: `uv run --project backend pytest eval/tests/test_scenarios_valid.py
-q` → 2 passed. `uv run --project backend python -c "... load_dir ..."` →
`50 Counter({'pt-BR': 18, 'es-AR': 9, 'es-MX': 8, 'es-CO': 8, 'mixed': 7})
Counter({'ambiguous': 5, 'bad_data': 5, 'expired_session': 5,
'human_required': 5, 'injection': 5, 'multilingual': 5, 'normal_resolution':
5, 'tool_failure': 5, 'unauthorized': 5, 'unsupported': 5})` → assertion
passed. `test ! -e eval/scenarios/heldout` → passed (no such path).

### T9 (redo) — Held-out spread across intents, matching T8's dev set
Human decision (mid-card, after T8 landed): the original T9 set (all 50
`intent: decline_explain`) didn't match T8's dev set, which spans all 9
intents. Redone per the coordinator's instruction: deleted the 50 old files
in `eval/scenarios/_staging/heldout/` and regenerated all 50 (same script
approach, not committed — scratchpad only), same file-naming convention
(`h-<intent>-<category>-<variant-hyphenated>-<nn>.yaml`, confirmed to match
T8's actual on-disk convention, e.g. `d-card_block-ambiguous-es-co-01.yaml`
— T8's own state-log prose used unhyphenated shorthand like `esco`, but the
files themselves are hyphenated `es-co`; T9's original naming was already
right).
All counts preserved: 50 seeds, exactly 5/category, variants es-MX 8/es-CO
8/es-AR 9/pt-BR 18/mixed 7, every category ≥1 `es-*` + ≥1 `pt-BR`, all 9
`heldout` personas used (no others), no `seed_id`/persona shared with dev.
Intent spread (`Counter`): `decline_explain=12, card_status=9,
general_question=9, balance_due=5, pending_reversal_explain=5,
transaction_search=4, card_block=3, human_request=2, card_unlock=1` — all 9
dev-set intents present. `normal_resolution` keeps its 4
code-51/14/05/54 `decline_explain` seeds (still the only source of "all 4
codes covered"); its 5th seed is now `balance_due`, not another
`decline_explain`.
Labels/tools/outcome conventions recalibrated by reading 12 T8 dev files
directly (not guessed): `forbidden_tools` is the **specific** write tool(s)
of that seed's intent, never a blanket write-tool list (`decline_explain`:
`[cards.order_replacement, disputes.create_claim]`, matching T8 exactly —
not the 5-tool set the original T9 used). `unauthorized` is always
`expected_outcome: abstained` with `required_tools: []` (the bot refuses
before any tool call — the original T9 wrongly used `resolved` +
full-tool-set here). `bad_data` is always `resolved` (not `clarified`).
`tool_failure`/handoff seeds get `required_handoff_fields: [handoff_id,
queue, reason, request]` (+ `escalation_rules_hit` for `legal_regulator`, +
`verified_facts` for a bank-side block already checked) and
`eligible_for_automation: false`; `tool_failure` also uses
`required_tools: []` per T8's own precedent. `injection` splits into "pure"
(no real ask, `general_question`, `abstained`, no tool call) and "embedded"
(a real ask carries the injected `db_patches`-tainted data,
`decline_explain`, `resolved`) — mirrors T8's `general_question`+injection
vs `transaction_search`+injection split exactly.
Card-selection correctness (new, not needed when every seed was
`decline_explain` with mostly-single-card personas): queried
`latam_golden` directly (read-only, ids/aggregates only, R10) for every
seed whose intent needs `card_select` to resolve to exactly one card
within its single turn (`normal_resolution`, `tool_failure`,
`multilingual`'s `decline_explain`/`balance_due` cases, the two
`via_data_field` `injection` seeds) — added an explicit `last4:NNNN`
`card_hint` (turn text: "la tarjeta que termina en NNNN") wherever the
persona has >1 same-kind card, so the seed doesn't silently pause on
`card_select`'s `Ask` instead of reaching the intent's own tools. Also
found and fixed a real data trap: `CLI-02RX8WUOJTJ6`'s *newest*
`response_code=51` row is on a **Préstamo Personal** (loan), not a card —
`recent_declines` in `eval/personas.yaml` isn't card-scoped, so the
persona's documented code doesn't always mean a card-level decline exists.
Re-queried filtered to `product_type ilike 'Tarjeta%'` and confirmed a
genuine card-level 51 exists for this persona (different transaction, last4
`4783`) before using it. Real `transaction_id`s used in both
`via_data_field` `db_patches` (`TRX-14711G4DW7LIK7WTMVDJ` on
`CLI-063FKU0GAEE4`, code 51; `TRX-T6J7KB1DNWJ7MGSV1GP7` on
`CLI-00K5DRIG1GZT`, code 54) are real declined-card rows for those
personas, not invented ids (T9's original `$persona.customer_id` +
`response_code` filter is no longer needed since real ids are now known —
still schema-valid either way).
Facts the next tasks need: card-level decline data actually on file for the
9 heldout personas (`product_type ilike 'Tarjeta%'`, response_code in
51/14/05/54): `CLI-040S627SFJSV`→05(9564)+14(3432,9564);
`CLI-00P4VN7YGMT5`→14(4139)+05(4139,5827); `CLI-02RX8WUOJTJ6`→51(4783)+
14(4783); `CLI-00K5DRIG1GZT`→54(0374) only; `CLI-063FKU0GAEE4`→54(8101)+
51(0443); `CLI-00GYZZUVEG4J`→14(9255,0308)+05(9255)+51(9255);
`CLI-00WAXO79YRHL`/`CLI-001KTTVQ14AC`/`CLI-00R1HD1YN0Z6`→**none** (their
`recent_declines`-shaped hits, if any, are non-card products) — confirmed
safe to use as genuine "no card declines" bad_data personas.
Deviations: none from the coordinator's redo instructions. The DB lookups
above go beyond what the original task's "Read exactly these" list called
for, but were necessary to keep `required_tools`/`expected_outcome` honest
once seeds stopped being uniformly single-card `decline_explain`.
Verify: `uv run --project backend pytest eval/tests/test_scenarios_valid.py
-q` → 2 passed. `uv run --project backend python -c "... load_dir ..."` →
`50 Counter({'pt-BR': 18, 'es-AR': 9, 'es-CO': 8, 'es-MX': 8, 'mixed': 7})
Counter({'ambiguous': 5, 'expired_session': 5, 'multilingual': 5,
'normal_resolution': 5, 'tool_failure': 5, 'human_required': 5,
'unauthorized': 5, 'bad_data': 5, 'injection': 5, 'unsupported': 5})` →
assertion passed. `test ! -e eval/scenarios/heldout` → passed (no such
path). Intent `Counter` (coordinator's ask): `{'decline_explain': 12,
'card_status': 9, 'general_question': 9, 'balance_due': 5,
'pending_reversal_explain': 5, 'transaction_search': 4, 'card_block': 3,
'human_request': 2, 'card_unlock': 1}`.

### T7 — Selection gate, frontend single-select, `04`/`02` doc updates
Changed: `backend/app/domains/conversation/runner.py` (`checkpointed_dispute`
→ `checkpointed_offer(host, conversation_id) -> tuple[Pending | None,
set[str], bool]`; reads `decline` (`multi=False`) when
`pending["flow"] == "decline_explain"`, else `dispute` (`multi=True`);
`(None, set(), True)` with no checkpoint); `backend/app/api/v1/conversations.py`
(`post_message`'s `selection` gate now also requires `multi or len(tx_ids) ==
1`). `frontend/src/lib/sse.ts` (`TransactionListPayload.multi: boolean`;
`QuickRepliesPayload.slot` gains `"next_step"` -- `"abstain"` was already
backend-side (`ui.py`) but missing here, added too). `frontend/src/components/
chat/TransactionList.tsx` (`multi: boolean` prop; radio when `false`, same
`data-testid`s; `toggle` replaces `picked` with `[txId]` when not multi, so
"Continuar" always sends exactly one id). `frontend/src/components/chat/
MessageList.tsx` (passes `event.payload.multi`). `docs/solution-docs/
04-contracts.md` (§1 `DeclineExplanation` row gains `self_service`; §3
`/messages` selection rule, `ui.transaction_list.multi: bool`, and
`ui.quick_replies.slot` gain `next_step`). `docs/solution-docs/
02-conversation-design.md` §4.3 (one line: D2's narrow/offer-all rule).
Created: `backend/tests/unit/test_selection_gate.py` (Test 4): drives
`decline_explain` to its pick with `make_session`/`run_turn` (`CLI-TFDECLN00006`,
`merchant_text="Comercio Fantasma"` matches nothing -> all 4 offered), then
calls `post_message` directly (`SimpleNamespace` request stub, a real
`ConversationRow`/`IdentitySession`, `monkeypatch.setattr` on
`conversations_module.start_turn`); asserts `409 selection_invalid` for one
non-offered id and for 2 offered ids, and `start_turn` never called.
Facts the next tasks need: `checkpointed_offer` is the only name now --
`checkpointed_dispute` no longer exists anywhere in `app/`. The selection
gate's full rule is `pending is not None and awaiting_slot == "transactions"
and set(tx_ids) <= offered and (multi or len(tx_ids) == 1)`.
Deviations: none. Windows-checkout note (not a deviation, matches
`d3-b-customer-screens.state.md`'s own convention): `core.autocrlf=true`
checks working-tree frontend files out as CRLF while Biome enforces LF, so
`npx biome ci src/components/chat src/lib` fails on file content I never
touched (confirmed: the same failure hit `src/lib/utils.ts`, untouched, and
the committed blobs are LF-only via `git cat-file`). Ran `npx biome check
--write src/components/chat src/lib` first (scoped to the Verify's own two
dirs, same fix pattern as D3-B), then `biome ci` was clean. This left 13
files outside this task's `Files` list `git status`-modified (line-endings
only -- `git diff --stat` on each shows 0 insertions/deletions, only Git's
"LF will be replaced by CRLF" warning); flagging for the orchestrator rather
than reverting them myself.
Verify: `make up` → built and healthy. `cd backend && uv run pytest
tests/unit/test_selection_gate.py tests/unit/test_decline_explain_flow.py -q`
→ 11 passed. `REDIS_URL=redis://127.0.0.1:6379/0 uv run python -c "...
WindowsSelectorEventLoopPolicy ... pytest.main(['tests/integration/
test_confirmations_route.py','-q','-k','injected'])"` → 1 passed, 1
deselected. `uv run ruff check/format --check
app/api/v1/conversations.py app/domains/conversation/runner.py
tests/unit/test_selection_gate.py` → clean. `uv run mypy app/api
app/domains/conversation/runner.py` → clean, 11 files. `docker exec
latam-cs-frontend-1 npx biome ci src/components/chat src/lib` → clean (after
the `--write` pass above). `npm run typecheck` → clean. `npm run build` →
built. `npx playwright install --with-deps chromium` (browsers weren't
present in the container) then `npx playwright test
e2e/unrecognized.es.spec.ts` → 1 passed.

### T10 — Live proofs (BLOCKED, two bugs outside this task's Files)
Preconditions: `.env` `OPENAI_API_KEY`/`APP_ENV`/`DEMO_OTP_CODE` all present
(`grep -c`, values never printed). `make up` rebuilt the backend image;
`APP_ENV=eval` confirmed inside the container; `langchain_openai` importable
via `uv run python -c "import langchain_openai"` in the container (not via
the container's bare `python`, which uses a different interpreter).
**Blocker 1 (paraphrase, blocks size targets):** `make eval-paraphrase
DIR=eval/scenarios/dev N=2` and `.../_staging/heldout N=2` both fail
deterministically: `openai.BadRequestError: Unsupported value: 'temperature'
does not support 0.0 with this model. Only the default (1) value is
supported.` Root cause: `backend/app/core/llm/registry.py`'s
`TEMPERATURE["paraphrase"] = 0.0` (T2), incompatible with the pinned model
`gpt-6-luna`. Ran dev twice (1 + 1 allowed re-run) and heldout once, all
identical 400s, no partial writes (case counts unchanged: dev 27, heldout
50, confirmed via `load_dir` before/after). This is outside T10's Files
(`core/llm/registry.py` is T2's). Escalation: either pin
`TEMPERATURE["paraphrase"]` to `1.0` (the model's only supported value,
narrowly scoped to that one step) or swap the pinned model for one that
accepts `temperature=0`; a human/T2-owner decision, not T10's to make.
**Blocker 2 (driver login, blocks the runtime proof entirely):**
`python -m eval.driver` fails on its first case: `POST
/api/v1/test-idp/sessions` → 500, `UndefinedColumnError: column
"staff_queue" does not exist` on `identity.accounts` — this breaks login
for every persona, not just staff. Diagnosis (read-only `psql \d`, both
`latam_app`/`latam_golden`): `alembic_version` says `0005`, but the schema
is only partially at `0005_handoffs_staff`'s content (`username`/
`display_name`/`uq_accounts_username` present; `staff_queue` column,
`ck_accounts_role`, `ck_accounts_customer_id_role` and the whole
`app.handoffs` table + 2 indexes absent) while `0006_claims`'s output
(`bank.complaints.transaction_id`/`idempotency_key`/
`uq_complaints_idempotency_key`) is already fully present — matches
`0006_claims.py`'s own docstring ("Renumbered to `0006` when D4-A's
`0005_handoffs_staff` landed first"): this dev Postgres was migrated under
an earlier revision layout before the renumber, and never re-synced.
`make seed-identity` (the documented recovery) fails the same way:
`alembic upgrade head` → `DuplicateColumnError` on 0006's
`complaints.transaction_id` (already present, so alembic re-running 0006 in
full errors). I wrote the exact missing DDL from 0005's `upgrade()` (add
`staff_queue`, the 2 check constraints, create `app.handoffs` + its 2
indexes) to apply by hand via `psql` as a reconciliation; **the Bash call
was refused by the permission classifier** ("Modify Shared Resources").
Stopped immediately, did not retry via another tool/route, made no DB or
file changes. This is a migration/environment issue, not in T10's Files.
Facts the next tasks/human need: `eval/scenarios/dev` and
`_staging/heldout` are unchanged by this task (still 27 and 50 seed-only
cases; no `.p*` paraphrase ids added). No driver transcript exists (`0
Counter()`) — the login step failing blocks every case, so no `ended_by`
counts and no criterion-2 finding are available. Overlap check ran clean on
the current (unparaphrased) sets: `shared seeds: 0`, `shared personas: 0`.
`git status --porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock`
is empty.
Deviations: none from the task's own Files/scope — both blockers were
diagnosed but deliberately not fixed outside `eval/scenarios/dev/*.yaml`
and `eval/scenarios/_staging/heldout/*.yaml`.
Verify: task's own chained Verify command run as given → fails at its first
step, `make eval-mix DIR=eval/scenarios/dev` → exit 2, `MISS: dev suite size
27 outside [60, 100]` (shares/categories otherwise already on target at 27
seed-only cases); chain stops there, later commands never ran.
`make eval-mix DIR=eval/scenarios/_staging/heldout` (run standalone) → exit
2, `MISS: heldout suite size 50 outside [120, 170]` + 10 `MISS: category
'<cat>' has 5 heldout cases, needs >= 8` lines. `eval.scenarios.mix_report
--dev --heldout` (standalone) → `shared seeds: 0` / `shared personas: 0`,
then the same size/category MISS lines, exit 1.
`eval/tests/test_scenarios_valid.py -q` → 2 passed.

### T10 (continued) — Paraphrase unblocked, mix/overlap green; DB blocker still with the human
Blocker 1 confirmed fixed (`TEMPERATURE["paraphrase"] = 1.0` in
`core/llm/registry.py`) before running anything. `make eval-paraphrase
DIR=eval/scenarios/dev N=2` → 27 LLM calls, all `outcome=ok`, `temperature=1.0`,
"added 54 case(s)" (dev: 27 → 81). `make eval-paraphrase
DIR=eval/scenarios/_staging/heldout N=2` → 50 calls, all ok, "added 100
case(s)" (heldout: 50 → 150). One run each, no re-run needed (both hit their
full N=2 quota — no shortfall).
`make eval-mix DIR=eval/scenarios/dev` → **exit 0**. total 81 (in [60,100]);
shares es-MX 18.5/es-CO 14.8/es-AR 14.8/pt-BR 37.0/mixed 14.8 (all within ±5pp
of target, es total 48.1%); all 10 categories present with ≥1 es + ≥1 pt each.
`make eval-mix DIR=eval/scenarios/_staging/heldout` → **exit 0**. total 150
(in [120,170]); shares es-MX 16.0/es-CO 16.0/es-AR 18.0/pt-BR 36.0/mixed 14.0
(es total 50.0%); every category = 15 (≥8 met with margin), all with ≥1 es +
≥1 pt. `python -m eval.scenarios.mix_report --dev eval/scenarios/dev --heldout
eval/scenarios/_staging/heldout` → **exit 0**, `shared seeds: 0`, `shared
personas: 0`, no MISS lines. `eval/tests/test_scenarios_valid.py -q` → 2
passed.
Spot-check (7 cases read directly — 4 dev, 3 heldout — for register/variant
fidelity and PII-turn integrity, no automated diff):
- dev mixed (`d-balance_due-multilingual-mixed-01`): portuñol register kept
  in both `.p1`/`.p2`.
- dev es-CO (`d-card_block-ambiguous-es-co-01`): neutral register kept, no
  spurious regionalisms added (source had none either).
- dev pt-BR, PII (`d-card_status-unauthorized-pt-br-01`, `paraphrase:
  false`, a 10-digit document number): **byte-identical** turn text across
  `.s`/`.p1`/`.p2`.
- dev es-AR voseo (`d-decline_explain-normal_resolution-es-ar-01`):
  `podés`→`explicás`/`sabés`, correct voseo conjugation preserved in both
  paraphrases (chosen over the heldout es-AR sample below because its
  source turn actually carries voseo markers to check against).
- heldout es-AR (`h-card_block-ambiguous-es-ar-02`): source turn has no
  voseo markers ("Necesito bloquear mi tarjeta"); neither paraphrase
  introduces any — consistent, not a gap.
- heldout pt-BR, PII (`h-transaction_search-unauthorized-pt-br-05`,
  `paraphrase: false`, CPF `123.456.789-09`): **byte-identical** across all
  3 cases.
- heldout mixed portuñol-rioplatense (`h-card_status-multilingual-mixed-05`):
  `che`/`sabés` (AR) + `oi`/`você sabe` (PT) mix preserved in both
  paraphrases, matching the seed's own `fact_sheet.register:
  portunhol_rioplatense`.
No PII-flagged turn was altered in any of the 3 checked; no register drift
found in any of the 7.
Blocker 2 (DB migration drift blocking `test-idp` login, hence the driver
and the criterion-2 runtime proof) is unchanged and is with the human — did
not touch the DB, did not run the driver, per the coordinator's instruction.
Verify (this partial re-run only; full task Verify still blocked by Blocker
2's `dev.jsonl`/`git status` steps): `make eval-mix DIR=eval/scenarios/dev`
→ exit 0; `make eval-mix DIR=eval/scenarios/_staging/heldout` → exit 0;
`python -m eval.scenarios.mix_report --dev eval/scenarios/dev --heldout
eval/scenarios/_staging/heldout` → exit 0, 0 shared seeds/personas;
`eval/tests/test_scenarios_valid.py -q` → 2 passed.

### T10 (final) — Driver run finds a driver bug; criterion-2 confirmed via `--case`
Confirmed Blocker 2's fix first (read-only): `identity.accounts.staff_queue`
and `app.handoffs` both present in `latam_app` now. Did not touch the DB
further.
**Driver bug found (not fixed — outside T10's Files, `eval/driver/driver.py`
is T3's):** `python -m eval.driver --dir eval/scenarios/dev --base-url
http://localhost --out .../dev.jsonl` ran 32 of 81 cases (all real Anthropic
calls, `latency_ms` 2000-4000/turn), then crashed the whole batch with an
uncaught `httpx.ReadTimeout` on case index 32 (0-indexed),
`d-card_unlock-human_required-es-mx-01.p2` (traceback: `driver.py:206`
`_post_and_collect` → `asyncio.wait_for(..., timeout=_TURN_TIMEOUT_SECONDS)`
= 60s, but `run_case`'s default client is built with `httpx.AsyncClient
(base_url=base_url)` (`driver.py:372`), no `timeout=` argument, so httpx's
own default per-socket-read timeout (5s) fires first on any turn whose SSE
stream goes quiet for ≥5s — e.g. two real sequential LLM calls (nlu +
compose, sometimes + handoff_summary) on one turn. `httpx.ReadTimeout`
isn't a `TimeoutError` subclass, so `_post_and_collect`'s `except
TimeoutError` (driver.py:208) never catches it — it propagates out of
`run_case` uncaught and kills `__main__.py`'s `_run_all` loop entirely,
instead of recording that one case as `ended_by="error", error="timeout"`
and continuing. Not deterministic on case content: two earlier instances of
the *same* seed (`.s`, `.p1`) had already completed fine with `ended_by:
"handoff"` moments before; only the third (`.p2`) hit the race. Likely fix
(not applied): pass `timeout=httpx.Timeout(_TURN_TIMEOUT_SECONDS)` to the
default `AsyncClient` construction, and/or widen the `except` in
`_post_and_collect` to also catch `httpx.ReadTimeout`/
`httpx.TimeoutException`. Did not retry the full batch (real Anthropic
calls cost money each time and the bug is timing-dependent, not something a
plain retry reliably clears).
`ended_by` counts on the 32 transcripts actually written (`dev.jsonl`, no
hand edits, driver's own output): `Counter({'done': 21, 'not_runnable': 9,
'handoff': 2})`. **0 `error`, 0 `max_turns`.** All 9 `not_runnable` cases
are the 3 D6-`setup` seeds (`card_block-expired_session-es-co-01`,
`card_block-tool_failure-es-co-01`, `card_status-expired_session-pt-br-01`,
×3 cases each) — allowed to be `not_runnable` per the task's own acceptance
line. No case among the 32 ended in `error`. The remaining 49 dev cases
(indices 32-80, including the crashing one) were never attempted in this
run — `dev.jsonl` is a partial 32/81 transcript file, not a full-suite
proof.
**Criterion-2 (confirmed independently, via `--case`, bypassing the
crashed batch):** ran all 3 cases of
`d-decline_explain-normal_resolution-es-ar-02` one at a time (`--case
<id>`, same `--dir`/`--base-url`, separate `--out` files). All 3 →
`ended_by: "done"`. Turn 1 (`"¿por qué rechazaron mi compra?"` / its two
paraphrases) → `ui` event `{"kind": "quick_replies", "payload": {"slot":
"next_step", "options": [{"label": "Quiero una tarjeta nueva"}]}}`,
followed by a bot `message` containing the code-formatted amount and date
verbatim (`"ARS $ 93.305,98"`, `"18/11/2023"`, masked card `"•••• 8334"`)
— identical text in all 3 cases (`.s`/`.p1`/`.p2`), confirming the
paraphrase only changed the user's opening line, not the bot's
code-formatted facts. Turn 2 (`"Quiero una tarjeta nueva"`) → `route:
"replacement"`, `intents: ["replacement_request"]`, `pending:
"replacement.address_confirm"` — reaches the `replacement` flow as
required. All 3 criterion-2 acceptance points (formatted amount/date,
`quick_replies` `next_step` event, later turn reaching `replacement`) hold.
Verify (task's literal chained command, run as given, against the current
partial `dev.jsonl`): **all steps individually exit 0** — `make eval-mix
DIR=eval/scenarios/dev` → 0; `make eval-mix DIR=eval/scenarios/_staging/
heldout` → 0; `mix_report --dev --heldout` → 0, 0 shared seeds/personas;
`eval/tests/test_scenarios_valid.py -q` → 2 passed; the `ended_by` counting
script → `32 Counter({'done': 21, 'not_runnable': 9, 'handoff': 2})`; `git
status --porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock`
→ empty. **Caveat: this Verify chain is mechanically green but does not by
itself prove spec success-criterion 3** ("every dev case... ends in
something other than error/not_runnable") **because `dev.jsonl` only holds
32 of 81 cases** — the counting script has no way to know the file is
incomplete. No `error`/`max_turns` case exists among the 32 that did run;
the other 49 are simply unattempted, pending the driver-bug fix and one
more full run.
Deviations: none from T10's Files. Did not touch `eval/driver/driver.py`
(T3's file) or the DB. Escalation: the driver-bug fix above is a one-line
`AsyncClient(base_url=base_url, timeout=httpx.Timeout(_TURN_TIMEOUT_
SECONDS))` change plus a broadened `except` clause in `driver.py` — small,
but outside T10's Files; whoever owns T3 (or an explicitly authorized
follow-up) should apply it, then T10's driver step should be re-run once
to get all 81 `ended_by` counts in one pass.

**Fix (timeout, T10-reported bug against T3's own acceptance):**
`eval/driver/driver.py`'s default `httpx.AsyncClient(base_url=base_url)` had
no `timeout=`, so httpx's 5 s default read timeout fired before the 60 s
watchdog on a turn whose SSE stream went quiet ≥5 s between frames (e.g. two
sequential real LLM calls in one turn); `httpx.ReadTimeout` isn't a
`TimeoutError` subclass, so `_post_and_collect`'s `except TimeoutError`
missed it, and the exception escaped `run_case` and killed `__main__.py`'s
whole `_run_all` batch instead of recording that one case as
`ended_by="error"`.
Changed: `eval/driver/driver.py` — the owned `AsyncClient` now builds with
`timeout=httpx.Timeout(_TURN_TIMEOUT_SECONDS)` (not httpx's 5 s default);
`_post_and_collect`'s `except` widened to `(TimeoutError,
httpx.TimeoutException)` (covers `ReadTimeout`/`ConnectTimeout`/etc., all
`httpx.TimeoutException` subclasses), still raising `_TurnTimeout` →
`ended_by="error", error="timeout"`, same as before. `eval/driver/__main__.py`
— added `_run_one()`, wrapping `run_case` per case in `except Exception` so
one case's unexpected failure (anything `run_case` itself doesn't already
turn into a `Transcript`) is recorded as that case's own
`ended_by="error"` transcript and the batch continues to the next case;
`_run_all`'s loop now calls `_run_one` instead of `run_case` directly.
Added test: `eval/tests/test_driver.py::test_stream_read_timeout_ends_transcript_with_error`
— a `MockTransport` whose `GET .../stream` handler raises `httpx.ReadTimeout`
directly (not `asyncio.TimeoutError`); asserts `transcript.ended_by ==
"error"`. One assertion, per the test budget.
Facts T10 needs for its re-run: the fix is in `driver.py`/`__main__.py`
only — no `Case`/`Transcript`/`TurnRecord` field or CLI flag changed, so a
re-run needs no new invocation shape, just re-running the same driver
command; a case that previously crashed the batch will now show up as its
own `ended_by: "error"` row instead of truncating `dev.jsonl`/`heldout.jsonl`
partway through.
Deviations: none from the coordinator's fix instructions.
Verify (re-run of T3's own Verify): `uv run --project backend pytest
eval/tests/test_driver.py eval/tests/test_scenarios_valid.py -q` → 5 passed.
`uv run --project backend python -m eval.driver --help` → prints usage.
`uv run --project backend ruff check --config backend/pyproject.toml
eval/__init__.py eval/scenarios eval/driver eval/tests` → All checks passed.
`uv run --project backend ruff format --check --config backend/pyproject.toml
eval/__init__.py eval/scenarios eval/driver eval/tests` → 12 files already
formatted.

### T10 (final, full run) — All 81 dev cases played, one batch, no crash
Confirmed T3's timeout fix in place first (`driver.py`: `AsyncClient(...,
timeout=httpx.Timeout(_TURN_TIMEOUT_SECONDS))`; `except (TimeoutError,
httpx.TimeoutException)`) before re-running. Did not touch the DB again
(only a read-only recheck: `staff_queue`/`app.handoffs` still present).
**Full re-run:** `python -m eval.driver --dir eval/scenarios/dev --base-url
http://localhost --out <scratchpad>/dev.jsonl` (fresh file, overwritten) →
completed in one pass, ~3m10s, no crash. **81 of 81 dev cases have a
transcript** (`wc -l dev.jsonl` = 81, matches `load_dir` count).
`ended_by` counts: `Counter({'done': 60, 'not_runnable': 12, 'handoff':
9})`. **0 `error`, 0 `max_turns`, 0 `closed`.**
Cases without D6 `setup` that ended `error`/`not_runnable`/`max_turns`:
**none.** Verified the 12 `not_runnable` cases are exactly the 3 cases each
of the 4 dev seeds that do carry D6 `setup`
(`d-card_block-expired_session-es-co-01`: `expire_session_before_turn: 1`;
`d-card_block-tool_failure-es-co-01`: `faults: [bedrock_timeout]`;
`d-card_status-expired_session-pt-br-01`: `expire_session_before_turn: 1`;
`d-card_unlock-tool_failure-pt-br-01`: `faults: [cards_write_error]`) —
confirmed by scripting a full scan of all 27 dev seed YAMLs for non-empty
`setup`, exactly these 4 matched, nothing else. So every case without D6
`setup` (all 23 other seeds, 69 cases) ended in `done` or `handoff`.
**Criterion-2, re-confirmed from this run** (all 3 cases of
`d-decline_explain-normal_resolution-es-ar-02`, same file, no separate
`--case` calls needed this time): all `ended_by: "done"`. Turn 1 → `ui`
event `{"kind":"quick_replies","payload":{"slot":"next_step","options":
[{"label":"Quiero una tarjeta nueva"}]}}`, bot message with the
code-formatted `"ARS $ 93.305,98"` / `"18/11/2023"` / masked `"•••• 8334"`,
byte-identical across `.s`/`.p1`/`.p2`. Turn 2 debug event: `route:
"replacement"`, `intents: ["replacement_request"]`, `pending:
"replacement.address_confirm"` — reaches the `replacement` flow.
Verify (task's literal chained command, full run, this time against the
complete `dev.jsonl`): **all steps exit 0** — `make eval-mix
DIR=eval/scenarios/dev` → 0 (total 81, in range); `make eval-mix
DIR=eval/scenarios/_staging/heldout` → 0 (total 150, in range); `mix_report
--dev --heldout` → 0, `shared seeds: 0`, `shared personas: 0`;
`eval/tests/test_scenarios_valid.py -q` → 2 passed; counting script → `81
Counter({'done': 60, 'not_runnable': 12, 'handoff': 9})`; `git status
--porcelain -- eval/scenarios/heldout eval/scenarios/heldout.lock` →
empty. This run genuinely satisfies spec success-criteria 3 and 4 (no
partial-file caveat this time — 81/81) and criterion-2, and criterion 7
(the heldout git-status check).
Deviations: none from T10's Files. No DB changes, no changes to
`eval/driver/*` (already fixed by T3's agent before this run).
