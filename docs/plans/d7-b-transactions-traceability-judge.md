# Plan: D7-B — Transactions, priority flags, traceability screens, LLM judge

Spec: [`docs/specs/d7-b-transactions-traceability-judge.md`](../specs/d7-b-transactions-traceability-judge.md) · Branch: `feat/d7-b-transactions-traceability-judge`

## Spec amendments (human answers after the spec gate; binding on every task)

- **SA1 (planning Q1 → a): the claim priority travels in the signed plan.** `disputes.create_claim` gains a third argument, `priority_flags: list[str]`. It is sorted, may be empty, is built in code by the flow and is bound by the confirmation token like `answers` (R2). `disputes.service.create_claims` writes `priority = 'High'` when the list is non-empty and NULL otherwise. `ActionResult` is unchanged. `04` §1 is amended (the "deferred" note goes). The spec's D10 wording "the flags travel in graph state only" becomes "the flags travel in graph state and the signed plan args". T9 edits both docs.
- **SA2 (planning Q2 → a): the harness persists transcripts.** `eval/harness/runner.py` also writes `eval/reports/<run_id>/transcripts.jsonl`, one row per played case. The file is gitignored like `results.jsonl`. It is wiring only in Dev A's file, flagged for Dev A review. `python -m eval.judges sample --run <run_id>` reads it.
- **Approved readings:** "open Critical" means `status in [Open, In Process, Escalated]` (D9). On the 10 shared items the judge is compared with the first labeler's label (D17).
- **Accepted planner findings (not in the spec's touch map):**
  - the route pick gate in `runner.checkpointed_offer` covers the two new single-pick flows;
  - `compose@v7` gets two new goals;
  - `nodes/handoff.py` adds `priority_claim` to `escalation_rules_hit` on the compromise path;
  - the FakeBank fixture gains complaints and new customers;
  - a new repeat-complainer persona is added;
  - `policies/tools.yaml` does **not** change, because read tools are not gated there and no `transactions.get` tool exists.

Execution model: tasks in the same wave run at the same time **in one shared checkout** (no worktrees, no branches, no commits; the orchestrator commits). Within a wave no two tasks touch the same file.

## Facts checked against the repo

**Baseline (HEAD `c64dd67` = `develop` = `origin/develop`, D6-A + D6-B merged, stack up):**
- `cd backend && uv run pytest tests/unit -q` → **143 passed**. `uv run lint-imports` → 4 kept, 0 broken. A new red belongs to the task that caused it.
- Alembic head is `0008`. **This card has no migration.** `app.handoffs.reason` and `bank.complaints.priority` are plain `Text` columns with no enum or CHECK, so the new reason `priority_claim` and the value `'High'` need no schema change.
- Working tree: only the spec is new (untracked). None of the doc edits the spec lists exist yet (T9 writes them).

**Commands and conventions (from the D5-B/D6-B state files; still true):**
- Backend commands run as `cd backend && uv run …`. There is no pytest-asyncio: drive coroutines with `asyncio.run(...)`. Tests never call a real provider.
- Flow tests use `make_session(customer_id, fakebank_dir, llm)` and `ScriptedLLM` from `backend/tests/conftest.py`. That gives FakeBank over `backend/tests/fixtures/fakebank/`, `MemorySaver`, an in-memory confirmation store and `InMemoryHandoffTools` (`session.handoff_tools` keeps the created packets). The analogues are `backend/tests/unit/test_decline_explain_flow.py` (single-pick) and `backend/tests/unit/test_dispute_flows.py` (claim, confirm, handoff).
- Eval code runs from the repo root under the backend env:
  - tests: `uv run --project backend pytest eval/tests/<file> -q`
  - lint: `uv run --project backend ruff check --config backend/pyproject.toml <paths>` (and `ruff format --check --config backend/pyproject.toml <paths>`).
  - `app` is not importable from `eval/` by default. An eval module that needs `app.core.llm` or `app.core.pii` puts `<repo>/backend` on `sys.path` first, as `eval/simulator/simulator.py` lines ~30-50 do (`_BACKEND_ROOT` + `sys.path.insert` + `# noqa: E402`).
  - Eval prompts are read straight from `eval/prompts/<name>@v<n>.md` (the pattern is `simulator.py:70`, `_PROMPT_PATH`), not through `conversation/prompts/load_prompt`.
- Windows host:
  - Integration tests need the selector event loop: `uv run python -c "import asyncio,sys,pytest; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); sys.exit(pytest.main([...]))"`, with `REDIS_URL=redis://127.0.0.1:6379/0`. A `skipped` result is not a pass.
  - The golden DB is read with `docker exec latam-cs-postgres-1 psql -U postgres -d latam_golden -Atc "<sql>"` (read only; query aggregates and ids only, R10).
- Frontend:
  - Host `frontend/node_modules` is empty. Every frontend command runs in the container: `docker exec -w /app latam-cs-frontend-1 sh -c "…"`.
  - Playwright runs against the **built** app (`npm run build`, preview on port 4173). Kill a stale 4173 server before the run.
  - Checkouts are CRLF and biome rejects CRLF. Normalize **your own** files to LF, and pass `biome ci` explicit file paths, never a directory.
  - `src/routeTree.gen.ts` is gitignored and regenerated by the build.
  - The dictionaries are `src/lib/i18n/es.json` and `pt.json` (flat `"a.b"` keys). The staff reason labels are `staff.reason.<reason>` (line ~89).
- `make client` regenerates `frontend/src/client/types.gen.ts` from the **running** backend. It hard-codes the `HandoffReason` union at lines 154/186/226, so it runs in T10 after the backend restarts.
- Never `git add`, `git commit` or push.

**Conversation graph (what T4/T5 extend):**
- The intents `transaction_search` and `pending_reversal_explain` already exist in `conversation/schemas.py::Intent`. Today both fall to `unsupported` because `graph._INTENT_NODES` has no entry.
- To register a flow node, touch all of these in `graph.py`:
  - `_BRANCH_NODES`, `_INTENT_NODES` and `_FLOW_NODES`;
  - `graph.add_node(name, _guard_access(fn))`;
  - the flow in each of the four `add_conditional_edges` maps that list flow nodes (after `load_session`, `understand`, `enqueue`, `next_intent`);
  - its own `add_conditional_edges(name, _after_flow, {...})` block (copy the `decline_explain` one at `graph.py:566`).
  - `runner.py:79` also keeps a `_BRANCH_NODES` mirror.
- `_entry` already resumes any `pending["flow"]` through `_FLOW_NODES[...]`, so a `selection` turn reaches the new flows with no entry change.
- **Pick gate:** `runner.checkpointed_offer` (`runner.py:187`) returns `(pending, offered, multi)`. It reads `decline` for `decline_explain` (single-pick) and `dispute` otherwise (multi). `api/v1/conversations.py:242` rejects a selection whose ids were not offered with `409 selection_invalid`. The new flows keep their offer in `TurnState.tx_offer` (T1), and T4 adds a `tx_search`/`tx_explain` branch returning `multi=False`.
- `_after_flow`:
  - a `HandoffReason` in `escalation_reason`, or a non-null `handoff_queue`, → `handoff_summary` → `handoff`;
  - non-empty `facts` → `compose`;
  - otherwise the flow's own fixed segment ends the turn.
- **Compose:**
  - `nodes/compose.py` has `_PROMPT = PromptRef("compose", 6)` and `Goal = Literal["card_status","balance_due","abstain","decline_explain"]`.
  - The goal is chosen in `compose()` from `_current_intent(state)`.
  - The LLM sees fact **keys only**. `_format_fact` renders each value in code, and an unknown key raises `ValueError`.
  - Policy keys are rendered through fixed label templates (`_DECLINE_CAUSE_TEMPLATES`/`_DECLINE_NEXT_TEMPLATES` → `templates.py`).
  - `tests/unit/test_compose.py:65` asserts `"compose@v6"`.
- `decline_explain.py` (308 lines) is the analogue for `tx_explain`. It has the single-pick offer (`TransactionListPayload(options, multi=False)`), `_tx_option` (label `merchant · money · date · •••• last4`), `_resume_pick` (re-checks that the pick is exactly one offered id) and the `QuickRepliesPayload(slot="next_step", options=[PickerOption(label=...)])` offer.
- `QuickRepliesPayload.slot` already allows `"next_step"`. The overdue-pending "talk to a person" quick reply reuses it (tapping sends the label as text, so NLU routes `human_request`). **No new `awaiting_slot` or `Clarification` value** (spec "Ask first").
- `route` resolves escalation rules, including `legal_regulator` keyword hits (`policy/escalation.py::legal_hit`), **before** it looks at a paused flow (`nodes/route.py`). So a regulator mention during a paused `unrecognized_charge` already hands off to Reclamos (high) with no claim. D8 needs a test, not code.
- **Handoff node:**
  - `nodes/handoff.py:147` hard-codes `escalation_rules_hit=[reason]`.
  - `open_questions` = the rule's questions + `state["handoff_open_questions"]`.
  - It clears `handoff_evidence`/`handoff_open_questions` on handoff.
- The bank clock is the real clock. `localization.format.local_today(country, now=None)` gives today in `BANK_TZ[country]`. **Flows read an optional `config["configurable"].get("now")` (aware `datetime`), defaulting to `datetime.now(UTC)`.** Tests set `session.config["configurable"]["now"] = datetime(2026, 4, 2, 18, 0, tzinfo=UTC)` after `make_session`, so `conftest.py` doesn't change.
- `TxFilter` (`transactions/schemas.py`):
  - fields `date_from`, `date_to`, `merchant_names` (exact names), `amount_min`, `amount_max`, `currency`, `status`, `card_id`;
  - it rejects a window over 366 days;
  - `transactions.search` returns at most 10 rows, newest first;
  - `card_id=None` searches every card of the customer, in both `FakeBank.search_transactions` and `PostgresBank.search_transactions`.

**Priority flags (what T2/T3/T5 build on):**
- `unrecognized_charge.py`:
  - plan builders `_start_compromise_plan` (~331), `_start_claim_plan` (~379) and `_offer_claim_only` (~406) build `PlanStep(tool="disputes.create_claim", args={...})`;
  - confirms `_confirm_compromise_plan` (~484) and `_confirm_claim_plan` (~540) call `bank_write_tools.create_claim(tx_ids, answers, token_id)`;
  - `_single_charge_success` (~581) and `_fraud_handoff` (~611) set `escalation_reason`/`handoff_queue`.
- Write-path layers for `create_claim`:
  - `tools/write.py:56` (`BankWriteTools` Protocol)
  - `tools/executor.py:214` (`ConfirmedWriteTools.create_claim`, `args: ToolArgs = {"tx_ids", "answers"}`, token-bound)
  - `tools/postgres_writes.py:146`
  - `tools/fakebank.py:570` (`FakeBankWrites`; it has no complaints table, so it records to the overlay)
  - `disputes/service.py::create_claims` (writes `"priority": None` today)
  - `disputes/repository.py` (`_SELECT`/`_INSERT_SQL`)
  - `disputes/schemas.py::ClaimRow`
- Callers that break when the signature changes: `tests/unit/test_r2_confirmed_writes.py:378,396` (PlanStep args) and `tests/integration/test_postgres_disputes.py` (calls `create_claims`).
- `bank.complaints` in `latam_golden`:
  - statuses Open / In Process / Escalated / Resolved / Closed / Rejected;
  - priorities Low / Medium / High / Critical;
  - column `is_repeat_complainer` (bool).
- The raw CSV header (`data/complaints/year=YYYY/month=MM/day=DD/complaints_YYYYMMDD.csv`, UTF-8 BOM):
  `complaint_id,creation_date,process_date,customer_id,case_type,category,subcategory,reception_channel,affected_product_id,related_branch_id,origin_interaction_id,description,claimed_amount,currency,priority,status,assigned_agent_id,assignment_date,first_response_date,resolution_date,closing_date,sla_breached,resolution_days,resolution,compensation_granted,resolution_satisfaction,is_repeat_complainer`
- Import-linter: only `app.domains.*.repository` is forbidden from `conversation`. `disputes.service` takes `open_statuses` as a parameter, so the disputes domain never imports `policy`. The tool implementations load the policy and pass it in.
- `policy/registry.py::_MODELS_BY_STEM` validates each `policies/<stem>.yaml` at startup. `disputes` is already registered there, and a new stem is one line (the analogue is `decline_codes`). The policy hash covers every `policies/*.yaml`, so the new file changes it on its own (success criterion 5).
- `policy/escalation.py::_REQUIRED_REASONS` (line ~100) must list every reason that `escalation.yaml` has to carry. `handoff/schemas.py::HandoffReason` is the Literal the packet validates against.

**Merchants (A4):** the 24 distinct `merchant_name` values in `latam_golden.bank.transactions`, exact spelling. Business names, not PII:
Boutique Moda, Cable TV, Centro Comercial, Cine Premium, Clínica Médica, Conciertos Live, Empresa Telefónica, Estación de Servicio, Farmacia Salud, Ferretería, Gasolinera Express, Internet Plus, Laboratorio Central, Mercado Central, Óptica Visión, Restaurante El Buen Sabor, Servicios Públicos, Streaming Music, Super Ahorro, Taxi Seguro, Teatro Nacional, Tienda Don José, Tienda General, Uber.
There is no `rapidfuzz` in `backend/pyproject.toml`, so fuzzy matching uses stdlib `difflib` (**no new dependency, no lockfile change in this card**).

**Eval:**
- A `make eval` run keeps `results.jsonl` and `llm_calls.jsonl` (both gitignored in `.gitignore` lines ~37-38), plus `meta.json` (`suite`, `system`, `label: "offline evaluation"`) and `report.md`.
- The in-memory `Transcript` (`eval/driver/driver.py:130`: `case_id`, `conversation_id`, `turns[TurnRecord{index, input, events[EventRecord{event, data}]}]`, `ended_by`) is scored in `runner._play` (~line 243/261) and then dropped.
- `eval/harness/pii_check.py::_load_personas_pii(customer_ids)` reads persona PII from the golden DB. `app.core.pii` provides `KnownPii(document_number, names)`, `find_pii(text, known)` and `TOKEN_RE`. The simulator's `_Masker` (`simulator.py:~96`) is the `⟨KIND_n⟩` numbering pattern to mirror.
- `core/llm/registry.py`: `Step` is a Literal. Add `"judge"` to `Step`, `MODEL_REGISTRY` (`{"openai": "gpt-6-luna"}`), `TEMPERATURE` (1.0) and `STEP_PROVIDER` (`"openai"`). `client.py` needs no change (the `simulate` precedent). `LLMClient.structured(*, step, prompt, system, user, schema)` refuses text that `find_pii` flags (R5).
- Scenario lint (`eval/harness/lint.py`): a persona used by a **writing** case (one that requires a write tool or asserts DB state) must appear in **only one** seed of the suite. So the repeat-complainer claim seed needs a persona no other dev seed uses.
- `eval/personas.yaml`:
  - `CLI-22WQT9NBWYGS` is the only `repeat_complainer`, and its only card is bank-Blocked, so it's unfit for a claim;
  - the trait vocabulary (header) includes `repeat_complainer`, `has_pending_transaction` and `has_reversed_transaction`;
  - `customer_id`/`split`/`notes` are non-trait keys.
- The dev suite has 32 seeds / 88 cases and `make eval-mix DIR=eval/scenarios/dev` exits 0. Seeds `d-transaction_search-*` and `d-pending_reversal_explain-*` already exist (e.g. `d-transaction_search-ambiguous-pt-br-01`, which expects `clarified` and forbids `transactions.search`).
- Docs:
  - `07-execution-plan.md:442` is the row "Paraphrase, simulator and judge model family … Judge model still open".
  - `06-engineering-rules.md:27` carries the `openai` line ("eval paraphrase and simulator only, ADR-030").
  - `04-contracts.md:44` is the `create_claim` row with "`priority_flags` is deferred".

**Cross-task names (pinned by this plan; binding):**

| Name | Where | Owner |
|---|---|---|
| `TransactionStatesPolicy{provenance, version, pending: PendingStatePolicy{hold_days: int, cause_key, next_step_key, overdue_next_step_key}, reversed: ReversedStatePolicy{cause_key, next_step_key}}`, `load_transaction_states_policy(path=None)` | `app/domains/policy/transaction_states.py` | T1 |
| `KNOWN_MERCHANTS: tuple[str, ...]` (the 24 above), `match_merchant(text: str) -> list[str]` (fold case + accents, `difflib` ratio, best first, `[]` below the cutoff) | `app/domains/transactions/merchants.py` | T1 |
| `resolve_date_expression(expr: str, today: date, tz: ZoneInfo, language: Literal["es","pt"]) -> tuple[date, date] \| None` | `app/domains/localization/dates.py` | T1 |
| `TxOfferState{flow: Literal["tx_search","tx_explain"], offered_tx_ids: list[str]}`; `TurnState.tx_offer: NotRequired[TxOfferState \| None]`; `TurnState.priority_flags: NotRequired[list[str]]` | `app/domains/conversation/state.py` | T1 |
| Fixture customers/cards/rows (next table) | `backend/tests/fixtures/fakebank/` | T1 |
| `PriorityPolicy{amount_threshold: dict[str, Decimal], open_statuses: list[str], handoff: DisputesHandoffPolicy}`; `DisputesPolicy.priority`; `DisputesPolicy.amount_over_threshold(amount: Decimal, currency: str) -> bool` (a currency with no threshold → `False`) | `app/domains/policy/disputes.py` | T2 |
| `HandoffReason` gains `"priority_claim"`; `escalation.yaml` v4 `rules.priority_claim: {queue: reclamos, priority: high}` | `handoff/schemas.py`, `policy/escalation.py`, `policies/escalation.yaml` | T2 |
| `PrioritySignals{repeat_complainer: bool, open_critical: bool}` frozen | `app/domains/disputes/schemas.py` | T3 |
| `disputes.service.priority_signals(customer_id, open_statuses: list[str]) -> PrioritySignals` | `app/domains/disputes/service.py` | T3 |
| `BankReadTools.get_priority_signals() -> PrioritySignals`; audit tool name `disputes.get_priority_signals`; `.calls` entry `"get_priority_signals"` | `tools/bank.py`, `fakebank.py`, `postgres.py`, `registry.py` | T3 |
| `create_claim(tx_ids, answers, priority_flags, *, idempotency_key)` on `BankWriteTools`; `ConfirmedWriteTools.create_claim(tx_ids, answers, priority_flags, token_id)` with args `{"tx_ids", "answers", "priority_flags"}`; `create_claims(customer_id, conversation_id, tx_ids, answers, idempotency_key, priority_flags: list[str] = [])` (use a `None`-default or tuple; no mutable default); `ClaimRow.priority: Literal["High"] \| None`; `FakeBankOverlay.claim_priorities: dict[str, str \| None]` (case_id → priority) | disputes domain + write tools | T3 |
| Flag names `amount_over_threshold`, `open_critical`, `repeat_complainer` (sorted list) | `flows/unrecognized_charge.py` | T5 |
| Flow nodes / `_FLOW_NODES` / `_INTENT_NODES` keys `tx_search` (intent `transaction_search`), `tx_explain` (intent `pending_reversal_explain`); pause `{flow, node: "pick", awaiting_slot: "transactions"}` | `graph.py`, `runner.py` | T4 |
| Compose goals `tx_explain`, `tx_details`; `compose@v7`. New fact keys: `tx_state_cause`, `tx_state_next_step` (policy keys → label templates), `clear_by_date` (date), `category`, `channel`, `city` (passthrough strings) | `nodes/compose.py`, `prompts/compose@v7.md` | T4 |
| Templates (ES+PT): `tx_search_ask_criterion`, `tx_search_pick_ask`, `tx_search_none` (`{filters}`), `tx_explain_pick_ask`, `tx_explain_none`, `tx_human_option`, `goal_tx_explain`, `goal_tx_details`, `tx_cause_pending_hold`, `tx_cause_reversed_charge`, `tx_next_wait_until_date`, `tx_next_offer_human`, `tx_next_no_action_needed` | `conversation/templates.py` | T4 |
| Templates (ES+PT): `priority_flag_repeat_complainer`, `priority_flag_amount_over_threshold`, `priority_flag_open_critical` (packet open-question lines) | `conversation/templates.py` | T5 |
| `transcripts.jsonl` row: `{run_id, system, case_id, seed_id, persona, intent, language_variant, expected_language, transcript: Transcript.model_dump(mode="json")}` | `eval/harness/runner.py` | T7 |
| `JudgeVerdict{grounding, tone, clarity, register, overall: bool, note: str (≤200)}`; `build_judge_user_message(item: dict) -> str`; `mask_text(text, known: KnownPii, masker) -> str` | `eval/judges/judge.py`, `eval/judges/sample.py` | T7 |
| Item row (`items.jsonl`): `{item_id: "J-001".."J-050", run_id, case_id, turn_index, language: es\|pt, intent, context: [{role: customer\|bot, text}], reply}`, all text masked | `eval/judges/sample.py` | T7 |
| `eval/judges/labels/assignment.yaml`: `{first: <labeler>, second: <labeler>, shared: [10 ids], <first>: [20 ids], <second>: [20 ids]}`; `labels/<labeler>.yaml`: a list of the spec's label records, booleans `null` until labeled | `eval/judges/sample.py` | T7 |
| `cohen_kappa(a: list[bool], b: list[bool]) -> float \| None`, `percent_agreement(a, b) -> float`, `render_report(items, labels, verdicts, assignment) -> str` | `eval/judges/agreement.py` | T7 |

**Fixture rows (T1 writes; T3/T4/T5 tests rely on them).** All are invented (R10). They use the existing CSV conventions (UTF-8 with BOM, CRLF, `Prueba <N>`, `@example.invalid`, card numbers `000000000000NNNN`). New transactions go in a new partition, `transactions/year=2026/month=03/day=31/transactions_20260331.csv`. 2026-03-31 is a **Tuesday**, and the test clock is Thu 2026-04-02 18:00 UTC.

| Customer | Card | Rows | Used by |
|---|---|---|---|
| `CLI-TFTXSRC00007` (Mexico) | `PRD-TFT7CRED0001` credit USD Active `7777`; `PRD-TFT7DEBT0002` debit USD Active `7778` | `TRX-TFT7CRED0001TXN01` Super Ahorro 352.40 USD **Approved** 2026-03-31 16:00Z (credit); `TXN02` Uber 18.50 USD **Pending** 2026-03-31 20:00Z (credit); `TRX-TFT7DEBT0002TXN01` Mercado Central 75.00 USD **Reversed** 2026-03-31 14:00Z (debit) | T4 search/explain tests |
| `CLI-TFREPT00008` (Colombia) | `PRD-TFR8CRED0001` credit COP Active `8888` | two Approved rows (120000, 95000 COP, 2026-03-31), `fraud_score` ≤ 30; complaint `is_repeat_complainer=true`, status `Closed`, priority `Low` | T5 repeat flag + compromise (pick both) |
| `CLI-TFAMNT00009` (Argentina) | `PRD-TFA9CRED0001` credit ARS Active `9999` | one Approved row 2500000 ARS (> 1,800,000), `fraud_score` ≤ 30; no complaints | T5 amount flag |
| `CLI-TFCRIT00010` (Mexico) | `PRD-TFC0CRED0001` credit USD Active `1010` | one Approved row 40.00 USD, `fraud_score` ≤ 30; complaint priority `Critical`, status `In Process`, `is_repeat_complainer=false`; a second complaint priority `Critical`, status `Resolved` (must not count alone) | T5 critical flag |

Complaints go in `complaints/year=2026/month=03/day=30/complaints_20260330.csv`, which uses the real header above. The existing customers get no complaints (so `CLI-TFSINGLE0002` stays unflagged for the existing dispute tests).

## Components

- **B1 pure core** (`policy/transaction_states.py` + YAML, `transactions/merchants.py`, `localization/dates.py`). No I/O. The date resolver depends only on `localization.format.BANK_TZ`.
- **B2 policy** (`policies/disputes.yaml` v2, `policy/disputes.py`, `policies/escalation.yaml` v4, `policy/escalation.py`, `handoff/schemas.py`).
- **Graph state + fixture** (`conversation/state.py`, `tests/fixtures/fakebank/`). Shared by B1 and B2.
- **B2 tool layer** (the `disputes` domain, `get_priority_signals` across the four read-tool files, `priority_flags` through the write stack). It depends on the B2 policy (`open_statuses`) and the fixture complaints.
- **B1 flows** (`flows/tx_search.py`, `flows/tx_explain.py`, graph and runner registration, compose v7, templates). They depend on the B1 core, the state and the fixture.
- **B2 flow** (`flows/unrecognized_charge.py` flag check and outcome, `nodes/handoff.py` rules-hit). It depends on the tool layer, the B2 policy and the state.
- **B3 screens** (`frontend/src/routes/staff/conversations.*`, `components/staff/*`, `lib/traceability.ts`, mocks, Playwright). Independent: they build against the proposed shapes on mocks (D12).
- **B4 judge tooling** (`eval/judges/`, `judge` step, `eval/harness/runner.py` transcripts). Independent of the flows.
- **Dev seeds + persona** (`eval/scenarios/dev/`, `eval/personas.yaml`). Data only. Their tool names are pinned above.
- **Docs** (`04`, `02`, `07`, `06`, spec D10).

## Build order

1. **W1:**
   - T1 (B1 core, state, fixture), T2 (B2 policy), T6 (screens), T7 (judge tooling), T8 (seeds) and T9 (docs) depend on nothing.
   - T1 and T2 are the roots of the two backend chains.
2. **W2:**
   - T3 needs T2's `PriorityPolicy.open_statuses` and T1's complaints fixture.
   - T4 needs T1's resolver, merchants, policy, `tx_offer` state and fixture rows.
   - Their files are disjoint (T4 owns `graph.py`, `runner.py`, `compose.py`, `templates.py`; T3 owns the tools, the disputes domain and a pass-through edit of `unrecognized_charge.py`).
3. **W3:**
   - T5 needs T3's read tool and `priority_flags` arg, T2's thresholds and reason, and T1's `priority_flags` state.
   - It edits `unrecognized_charge.py` (T3's pass-through must land first) and `templates.py` (T4's).
4. **W4:** T10 (alone) restarts the backend so the new policies load, regenerates the client, runs the live B1/B2 proofs, the dev eval run, `sample` and `judge`. It needs everything above.
5. **Human gate:** both people fill in `eval/judges/labels/<labeler>.yaml` (about 1 h; not a task).
6. **W5:** T11 runs `agreement` once the labels exist.

## Touch map

| File | New/Mod | Change | Task |
|---|---|---|---|
| `policies/transaction_states.yaml` | new | the spec's B1 block verbatim | T1 |
| `backend/app/domains/policy/transaction_states.py` | new | model + loader | T1 |
| `backend/app/domains/policy/registry.py` | mod | `"transaction_states": TransactionStatesPolicy` in `_MODELS_BY_STEM` | T1 |
| `backend/app/domains/transactions/merchants.py` | new | `KNOWN_MERCHANTS`, `match_merchant` | T1 |
| `backend/app/domains/localization/dates.py` | new | `resolve_date_expression` | T1 |
| `backend/app/domains/conversation/state.py` | mod | `TxOfferState`, `tx_offer`, `priority_flags` | T1 |
| `backend/tests/fixtures/fakebank/{customers,products}.csv`, `transactions/year=2026/month=03/day=31/transactions_20260331.csv`, `complaints/year=2026/month=03/day=30/complaints_20260330.csv`, `README.md` | mod/new | fixture rows above | T1 |
| `backend/tests/unit/test_dates.py` | new | test 4 | T1 |
| `policies/disputes.yaml` | mod | v2 + `priority` block | T2 |
| `backend/app/domains/policy/disputes.py` | mod | `PriorityPolicy`, `amount_over_threshold` | T2 |
| `policies/escalation.yaml` | mod | v4 + `priority_claim` rule (A reviews) | T2 |
| `backend/app/domains/policy/escalation.py` | mod | `_REQUIRED_REASONS` + `priority_claim` | T2 |
| `backend/app/domains/handoff/schemas.py` | mod | `HandoffReason` + `priority_claim` | T2 |
| `backend/app/domains/disputes/{schemas,repository,service}.py` | mod | `PrioritySignals`, signals query, `priority` write + `ClaimRow.priority` | T3 |
| `backend/app/domains/conversation/tools/{bank,fakebank,postgres,registry}.py` | mod | `get_priority_signals` (+ FakeBank complaints glob; `FakeBankWrites.create_claim` records priority) | T3 |
| `backend/app/domains/conversation/tools/{write,executor,postgres_writes}.py` | mod | `priority_flags` arg, token-bound; verified re-read checks priority | T3 |
| `backend/app/domains/conversation/flows/unrecognized_charge.py` | mod | pass `priority_flags=[]` in plan args and confirm calls (T3); flag check + outcomes (T5) | T3, T5 |
| `backend/tests/unit/test_r1_customer_scope.py` | mod | test 10 | T3 |
| `backend/tests/unit/test_r2_confirmed_writes.py` | mod | PlanStep args gain `priority_flags` | T3 |
| `backend/tests/integration/test_postgres_disputes.py` | mod | new signature; flagged row → `'High'` | T3 |
| `backend/app/domains/conversation/flows/tx_search.py`, `tx_explain.py` | new | the two flows | T4 |
| `backend/app/domains/conversation/{graph,runner}.py` | mod | node registration, pick gate | T4 |
| `backend/app/domains/conversation/templates.py` | mod | B1 templates (T4), flag lines (T5) | T4, T5 |
| `backend/app/domains/conversation/nodes/compose.py`, `prompts/compose@v7.md` | mod/new | goals `tx_explain`/`tx_details`, fact formatters | T4 |
| `backend/tests/unit/test_compose.py` | mod | `compose@v7` label | T4 |
| `backend/tests/unit/test_tx_search_flow.py`, `test_tx_explain_flow.py` | new | tests 1-3, 5-6 | T4 |
| `docs/diagrams/turn-graph-v0.mmd` | mod (generated) | new nodes | T4 |
| `backend/app/domains/conversation/nodes/handoff.py` | mod | `priority_claim` appended to `escalation_rules_hit` when `priority_flags` is set and the reason differs; clear `priority_flags` | T5 |
| `backend/tests/unit/test_priority_flags.py` | new | tests 7-9 | T5 |
| `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` | mod | test 11 | T5 |
| `backend/tests/unit/test_dispute_flows.py` | mod (only if a new assertion breaks it) | none planned | T5 |
| `frontend/src/lib/traceability.ts` | new | hand-written D11 types + fetchers (deleted when A1 lands) | T6 |
| `frontend/src/routes/staff/conversations.index.tsx`, `conversations.$conversationId.tsx` | new | list + timeline routes | T6 |
| `frontend/src/components/staff/{ConversationFilters,ConversationTable,TurnTimeline}.tsx` | new | components | T6 |
| `frontend/src/routes/staff/index.tsx` | mod | link to `/staff/conversations` | T6 |
| `frontend/src/lib/i18n/{es,pt}.json` | mod | `staff.conversations.*`, `staff.timeline.*`, `staff.reason.priority_claim` | T6 |
| `frontend/e2e/mock-staff-api.ts` | mod | list/timeline routes + filter by `intent` | T6 |
| `frontend/e2e/traceability.es.spec.ts` | new | test 12 | T6 |
| `backend/app/core/llm/registry.py` | mod | `judge` step | T7 |
| `eval/judges/{__init__,__main__,sample,judge,agreement}.py`, `eval/judges/rubric.md`, `eval/prompts/judge@v1.md` | new | B4 tooling | T7 |
| `eval/harness/runner.py`, `.gitignore` | mod | `transcripts.jsonl` (SA2, Dev A review) | T7 |
| `eval/tests/test_judge_agreement.py` | new | test 13 (two functions) | T7 |
| `eval/scenarios/dev/d-transaction_search-normal_resolution-es-mx-01.yaml`, `d-pending_reversal_explain-normal_resolution-pt-br-01.yaml`, `d-unrecognized_charge-human_required-es-<cc>-01.yaml` | new | A11 dev seeds | T8 |
| `eval/personas.yaml` | mod | new repeat-complainer persona (and search/pending personas if none fit) | T8 |
| `docs/solution-docs/04-contracts.md` §1 §3 §4 §5, `02-conversation-design.md` §4.4 §4.5 §4.8, `07-execution-plan.md` §8, `06-engineering-rules.md` §2, `docs/specs/d7-b-transactions-traceability-judge.md` D10 | mod | deltas + SA1 | T9 |
| `frontend/src/client/types.gen.ts` | mod (generated) | `priority_claim` in the reason unions | T10 |
| `eval/judges/items.jsonl`, `items.md`, `labels/assignment.yaml`, `labels/<labeler>.yaml` ×2, `judge_verdicts.jsonl` | new (generated) | B4 data | T10 |
| `eval/judges/agreement.md` | new (generated) | the report | T11 |

## Risks and mitigations

- **An LLM-supplied value leaks into the filter or the flags** (dates, amounts, merchants, flags). T4's acceptance: the filter is built only from NLU slots passed through `resolve_date_expression`, `match_merchant` and ±10% arithmetic. T5's acceptance: the flags come only from `get_priority_signals` and `amount_over_threshold`. Test 1 asserts the exact `TxFilter`, and test 7 runs with a `ScriptedLLM` that never returns a flag.
- **The pick gate rejects the new single-pick lists in the browser** (`409 selection_invalid`), because unit tests enter through the graph, not the route. T4 extends `checkpointed_offer`, and T10 proves a real pick through the API (success criterion 3).
- **Changing the `create_claim` signature breaks the existing dispute path.** T3 threads `priority_flags=[]` through every call site and fixes `test_r2_confirmed_writes.py` and the integration test in the same task. Its Verify runs `test_dispute_flows.py` and `test_r2_confirmed_writes.py`.
- **R3: a flagged row is written without `'High'`, but still reads back as verified.** In T3, `postgres_writes._claims_match` also compares `priority` with what was asked for. T10 checks the DB row (success criterion 4).
- **R1: priority signals read by a customer id from args.** The tool takes no arguments and closes over `ToolContext` (test 10).
- **Rule and reason drift.** A `HandoffReason` without an `escalation.yaml` rule fails at startup, and so does the reverse. T2 changes both, plus `_REQUIRED_REASONS`, in one task. T2's Verify runs `test_escalation_rules.py`, `test_policy_registry.py` and `test_handoff_packet.py`.
- **An open-Critical false positive from Resolved/Closed rows.** The fixture has a Resolved Critical complaint, and T3's R1 test also asserts that the `CLI-TFCRIT00010` signals come from the In Process row. T3 tests `open_critical` with a Resolved-only variant through a tiny in-test override of `open_statuses`.
- **The judge sees PII or held-out data (R5, R6, R9).**
  - `sample` refuses a run whose `meta.json` `suite` is not `dev` or whose `system` is not `proposed`. It masks with persona PII from the golden DB.
  - `judge` fences the data and `find_pii`-checks the text before calling (test 13b).
  - `eval/scenarios/heldout/` is never read (success criterion 8, checked in T10's Verify).
- **The judge step leaks into the served graph.** It lives in `eval/judges/` only, and T5's R6 extension scans `eval/judges/judge.py` for write-tool references and asserts that no `app/` module references `step="judge"`.
- **Mix drift from the new seeds breaks `make eval-mix`.** T8's Verify runs it. If the language shares fall out of tolerance, T8 adjusts which variant each seed uses, never the targets.
- **Frontend CRLF, a stale preview on 4173 and no host Node.** The conventions are in the Facts section, and T6's Verify runs in the container.
- **The live eval run is slow or costs money.** T10 runs once, alone, as the last code wave. `judge` is a paid OpenAI call and needs `OPENAI_API_KEY` in `.env`. If the key is missing, T10 stops and reports it instead of faking verdicts.

## Tests

The spec's list (13) and the task that writes each one:

| # | Test | Task |
|---|---|---|
| 1 | `backend/tests/unit/test_tx_search_flow.py::test_super_ahorro_last_tuesday_es` | T4 |
| 2 | `backend/tests/unit/test_tx_search_flow.py::test_widen_once_then_nothing_found_pt` | T4 |
| 3 | `backend/tests/unit/test_tx_search_flow.py::test_vague_date_clarifies_without_search` | T4 |
| 4 | `backend/tests/unit/test_dates.py::test_resolve_expressions` | T1 |
| 5 | `backend/tests/unit/test_tx_explain_flow.py::test_pending_explained_pt` | T4 |
| 6 | `backend/tests/unit/test_tx_explain_flow.py::test_reversed_explained_es` | T4 |
| 7 | `backend/tests/unit/test_priority_flags.py::test_flag_hands_off_to_reclamos[6 params]` | T5 |
| 8 | `backend/tests/unit/test_priority_flags.py::test_regulator_mention_goes_to_reclamos[es, pt]` | T5 |
| 9 | `backend/tests/unit/test_priority_flags.py::test_compromise_keeps_fraudes` | T5 |
| 10 | `backend/tests/unit/test_r1_customer_scope.py::test_priority_signals_bound_to_session` | T3 |
| 11 | `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py` (extend) | T5 |
| 12 | `frontend/e2e/traceability.es.spec.ts` | T6 |
| 13 | `eval/tests/test_judge_agreement.py::test_kappa_and_weak_flag` + `::test_judge_input_masked_and_fenced` | T7 |

Success criteria that are proved by a command rather than a test:
- SC3 (browser search + pending), SC4 (repeat complainer → Reclamos, DB row), SC5 (policy loads, hash changes), SC8 (held-out untouched): T10.
- SC6 (`agreement.md`): T11.
- SC7 (docs): T9.
- SC1/SC2 (`make check`, Playwright): the verifier at the end of the card.

## Tasks

- [ ] T1: B1 pure core, graph-state additions and the FakeBank fixture rows
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "B1: policy file and NLU" and §Assumptions A2-A5; `backend/app/domains/policy/decline_codes.py` (the loader + `_MODELS_BY_STEM` analogue); `backend/tests/fixtures/fakebank/README.md` (fixture conventions)
  - Acceptance:
    - **Policy file.**
      - `policies/transaction_states.yaml` holds the spec's block verbatim (`provenance: team-generated-synthetic`, `version: 1`).
      - `policy/transaction_states.py` defines the pinned model (frozen, `extra="forbid"`, required header) and `load_transaction_states_policy(path=None)` (repo root is `parents[4]`).
      - `registry.py` registers the stem.
    - **Merchants.** `transactions/merchants.py` holds the 24 pinned names and `match_merchant`:
      - it folds case and accents (`unicodedata` NFKD) and uses `difflib.SequenceMatcher`;
      - it returns names best first and `[]` below a module constant cutoff;
      - `"super ahorro"`, `"Súper Ahorro"` and `"superahorro"` → `["Super Ahorro"]`.
      - Pure, no I/O, no LLM.
    - **Date resolver.** `localization/dates.py::resolve_date_expression` implements A3 exactly, in ES and PT:
      - hoy/hoje, ayer/ontem, anteayer/anteontem;
      - `el <día> pasado` / `<dia> passada`: the most recent such weekday **strictly before** today;
      - semana pasada/passada: Monday-Sunday of the previous week;
      - mes pasado/mês passado: the previous calendar month;
      - `hace N días` / `há N dias`;
      - `<d> de <mes>`: the most recent such date on or before today.
      - It returns an inclusive `(date_from, date_to)`, or `None` for anything else.
    - **State.** `state.py` gains the pinned `TxOfferState`, `TurnState.tx_offer` and `TurnState.priority_flags`, exported in `__all__`.
    - **Fixture.** The fixture gains exactly the rows in the plan's fixture table (new day=31 transactions partition, new complaints partition with the real header, 5 new cards, 4 new customers) plus the README sections.
    - **Test 4.** `test_dates.py::test_resolve_expressions` is parametrized with today = Thu 2026-04-02 and `America/Mexico_City`:
      - `martes pasado` → (2026-03-31, 2026-03-31)
      - `terça passada` → the same
      - `ayer` → 04-01
      - `há 3 dias` → 03-30
      - `12 de marzo` → 03-12
      - `el mes que viene` → `None`
  - Verify: `cd backend && uv run pytest tests/unit/test_dates.py tests/unit/test_policy_registry.py tests/unit/test_r1_fakebank.py tests/unit/test_dispute_flows.py tests/unit/test_decline_explain_flow.py -q && uv run ruff check app/domains/policy/transaction_states.py app/domains/policy/registry.py app/domains/transactions/merchants.py app/domains/localization/dates.py app/domains/conversation/state.py tests/unit/test_dates.py && uv run ruff format --check app/domains/policy/transaction_states.py app/domains/policy/registry.py app/domains/transactions/merchants.py app/domains/localization/dates.py app/domains/conversation/state.py tests/unit/test_dates.py && uv run mypy app/domains/policy app/domains/transactions/merchants.py app/domains/localization/dates.py app/domains/conversation/state.py && uv run python -c "from app.domains.policy.registry import load_policies; load_policies()"`
  - Files: `policies/transaction_states.yaml`, `backend/app/domains/policy/transaction_states.py`, `backend/app/domains/policy/registry.py`, `backend/app/domains/transactions/merchants.py`, `backend/app/domains/localization/dates.py`, `backend/app/domains/conversation/state.py`, `backend/tests/fixtures/fakebank/customers.csv`, `backend/tests/fixtures/fakebank/products.csv`, `backend/tests/fixtures/fakebank/transactions/year=2026/month=03/day=31/transactions_20260331.csv`, `backend/tests/fixtures/fakebank/complaints/year=2026/month=03/day=30/complaints_20260330.csv`, `backend/tests/fixtures/fakebank/README.md`, `backend/tests/unit/test_dates.py`

- [ ] T2: B2 policy: `disputes.yaml` v2 priority block, `escalation.yaml` v4 `priority_claim`, `HandoffReason`
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "B2: disputes"; `backend/app/domains/policy/disputes.py`; `backend/app/domains/policy/escalation.py` (the `_REQUIRED_REASONS` and `rules` model)
  - Acceptance:
    - **`disputes.yaml`** is `version: 2` and carries the spec's `priority` block exactly (`amount_threshold` values as quoted strings, `open_statuses: [Open, In Process, Escalated]`, `handoff: {queue: reclamos, priority: high, reason: priority_claim}`).
    - **`DisputesPolicy`** gains the pinned `PriorityPolicy` (Decimal thresholds). It also gains `amount_over_threshold(amount, currency)`: strictly greater than the currency's threshold, `False` for a currency with none. Flows call this method; they never compare the raw fields (the SC2 pattern of `triggers_compromise`).
    - **`escalation.yaml`** is `version: 4`, with `priority_claim: {queue: reclamos, priority: high}` under `rules` and nothing else changed (A reviews; spec "Ask first").
    - `_REQUIRED_REASONS` and `HandoffReason` gain `"priority_claim"`.
    - Every policy still loads.
  - Verify: `cd backend && uv run pytest tests/unit/test_escalation_rules.py tests/unit/test_policy_registry.py tests/unit/test_handoff_packet.py tests/unit/test_dispute_flows.py -q && uv run ruff check app/domains/policy/disputes.py app/domains/policy/escalation.py app/domains/handoff/schemas.py && uv run ruff format --check app/domains/policy/disputes.py app/domains/policy/escalation.py app/domains/handoff/schemas.py && uv run mypy app/domains/policy/disputes.py app/domains/policy/escalation.py app/domains/handoff/schemas.py && uv run python -c "from decimal import Decimal; from app.domains.policy.disputes import load_disputes_policy as l; p=l(); assert p.amount_over_threshold(Decimal('2500000'),'ARS') and not p.amount_over_threshold(Decimal('5000'),'USD') and not p.amount_over_threshold(Decimal('1'),'MXN'); from app.domains.policy.escalation import load_escalation_policy as e; assert e().rules['priority_claim'].queue=='reclamos'"`
  - Files: `policies/disputes.yaml`, `backend/app/domains/policy/disputes.py`, `policies/escalation.yaml`, `backend/app/domains/policy/escalation.py`, `backend/app/domains/handoff/schemas.py`

- [ ] T3: B2 tool layer: `disputes.get_priority_signals` read tool and the token-bound `priority_flags` claim arg (SA1)
  - Depends on:
    - T1: the complaints fixture for `CLI-TFREPT00008`/`CLI-TFCRIT00010`.
    - T2: `load_disputes_policy().priority.open_statuses`.
  - Read exactly these: spec §"Contracts" → "B2: disputes" and this plan's "Spec amendments" SA1; `backend/app/domains/conversation/tools/registry.py` (the `explain_decline` audited-read pattern at ~line 165); `backend/app/domains/conversation/tools/executor.py` (`create_claim` at ~214 and `_run`)
  - Acceptance:
    - **Read side.**
      - `disputes/schemas.py` gains the pinned `PrioritySignals`.
      - `disputes/repository.py` gains one customer-scoped query: `bool_or(is_repeat_complainer)` and `bool_or(priority = 'Critical' AND status = ANY(:open_statuses))` over `bank.complaints WHERE customer_id = :customer_id`, with NULL treated as false.
      - `disputes/service.py::priority_signals(customer_id, open_statuses)` wraps it.
    - **`get_priority_signals()` takes no arguments** on the `BankReadTools` Protocol (`bank.py`). Where each implementation gets the customer and statuses:
      - `PostgresBank` (`postgres.py`): the service, with `ToolContext.customer_id` and the policy's `open_statuses`;
      - `FakeBank` (`fakebank.py`): DuckDB over a new `complaints/**/*.csv` glob beside the transactions one, `WHERE customer_id = ?` bound to the context (R1). No complaints files → both flags `False`;
      - `RecordingBankTools` (`registry.py`): audited as `disputes.get_priority_signals`, appending `"get_priority_signals"` to `.calls`.
    - **Write side (SA1).**
      - `priority_flags: list[str]` is threaded through `BankWriteTools.create_claim` (`write.py`), `ConfirmedWriteTools.create_claim` (`executor.py`, with `"priority_flags"` added to the token-bound `args`), `PostgresBankWrites.create_claim` (`postgres_writes.py`), `FakeBankWrites.create_claim` (`fakebank.py`, which records each case id's priority in `FakeBankOverlay.claim_priorities`) and `disputes.service.create_claims`.
      - `create_claims` writes `priority = 'High'` when the list is non-empty, else NULL. The replay path is unchanged.
      - `ClaimRow` gains `priority`, and `_SELECT` reads it. `postgres_writes._claims_match` also requires the re-read `priority` to equal the requested one (R3).
    - **Pass-through only in `unrecognized_charge.py`:** every `PlanStep(tool="disputes.create_claim", args=…)` gains `"priority_flags": []`, and both `create_claim(...)` calls pass `[]`. No flag logic here; T5 owns it.
    - **Existing tests.** `test_r2_confirmed_writes.py`'s PlanStep args gain `"priority_flags": []`. `tests/integration/test_postgres_disputes.py` passes the new argument and gains one assertion that a flagged call writes `'High'` and an unflagged call NULL.
    - **Test 10.** `test_r1_customer_scope.py::test_priority_signals_bound_to_session`:
      - `inspect.signature(BankReadTools.get_priority_signals)` has only `self`;
      - a FakeBank bound to `CLI-TFREPT00008` returns `repeat_complainer=True, open_critical=False`;
      - one bound to `CLI-TFCRIT00010` returns `False, True`;
      - one bound to `CLI-TFSINGLE0002` returns `False, False`.
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py tests/unit/test_r2_confirmed_writes.py tests/unit/test_dispute_flows.py tests/unit/test_fakebank_writes.py tests/unit/test_r1_fakebank.py -q && uv run ruff check app/domains/disputes app/domains/conversation/tools app/domains/conversation/flows/unrecognized_charge.py tests/unit/test_r1_customer_scope.py tests/unit/test_r2_confirmed_writes.py tests/integration/test_postgres_disputes.py && uv run ruff format --check app/domains/disputes app/domains/conversation/tools app/domains/conversation/flows/unrecognized_charge.py tests/unit/test_r1_customer_scope.py tests/unit/test_r2_confirmed_writes.py tests/integration/test_postgres_disputes.py && uv run mypy app/domains/disputes app/domains/conversation/tools app/domains/conversation/flows/unrecognized_charge.py && uv run lint-imports && REDIS_URL=redis://127.0.0.1:6379/0 uv run python -c "import asyncio,sys,pytest; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); sys.exit(pytest.main(['tests/integration/test_postgres_disputes.py','-q']))"` (needs `make up`; `skipped` is not a pass)
  - Files: `backend/app/domains/disputes/schemas.py`, `backend/app/domains/disputes/repository.py`, `backend/app/domains/disputes/service.py`, `backend/app/domains/conversation/tools/bank.py`, `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/conversation/tools/postgres.py`, `backend/app/domains/conversation/tools/registry.py`, `backend/app/domains/conversation/tools/write.py`, `backend/app/domains/conversation/tools/executor.py`, `backend/app/domains/conversation/tools/postgres_writes.py`, `backend/app/domains/conversation/flows/unrecognized_charge.py`, `backend/tests/unit/test_r1_customer_scope.py`, `backend/tests/unit/test_r2_confirmed_writes.py`, `backend/tests/integration/test_postgres_disputes.py`

- [ ] T4: B1 flows: `tx_search` and `tx_explain`, graph and pick-gate registration, `compose@v7`
  - Depends on: T1 (`resolve_date_expression`, `match_merchant`, `load_transaction_states_policy`, `TxOfferState`/`tx_offer`, fixture customer `CLI-TFTXSRC00007`)
  - Read exactly these: spec §Decisions D1-D4 and §Assumptions A1-A5; `backend/app/domains/conversation/flows/decline_explain.py` (the analogue: single-pick offer, `_resume_pick`, facts, quick reply); `backend/app/domains/conversation/nodes/compose.py` (goals, `_format_fact`, label templates)
  - Acceptance:
    - **`tx_search.py`** (`transaction_search` → node `tx_search`).
      - It builds a `TxFilter` in code from the NLU slots:
        - the date comes from `resolve_date_expression(slots.date_expression, local_today(country, now), BANK_TZ[country], language)`;
        - the merchant comes from `match_merchant(slots.merchant_text)` → `merchant_names` (no match → merchant ignored);
        - the amount is `amount ×0.9 .. ×1.1`;
        - `currency` is the slot currency if given, else none (the record currency, A2);
        - `card_hint` narrows `card_id` through `list_cards` (no `card_select`);
        - the window is clamped to start no earlier than 12 months before today. With no date it is the last 12 months.
      - `now` is `config["configurable"].get("now") or datetime.now(UTC)`.
      - No merchant, amount or resolvable date (A1) → the fixed `tx_search_ask_criterion` segment and **no** search.
      - One or more rows → the single-pick `ui.transaction_list` (`multi=False`) with labels formatted in code (per-card last4 from `list_cards`, R4), plus a count in the `tx_search_pick_ask` segment. The flow pauses at `{flow: "tx_search", node: "pick", awaiting_slot: "transactions"}` with `tx_offer`.
      - Zero rows → widen the dates once by ±3 days (still clamped). Zero again → the fixed `tx_search_none` segment listing the filters used, formatted in code. The outcome is resolved, with no pause.
      - Pick resume: re-check that the pick is exactly one offered id (R1). A Pending or Reversed row → the `tx_explain` explanation. Anything else → facts for goal `tx_details` (merchant, amount, currency, tx_date, card_mask, category, channel, city) → compose.
    - **`tx_explain.py`** (`pending_reversal_explain` → node `tx_explain`).
      - It uses the same slot filter restricted to `status=["Pending","Reversed"]`:
        - one match → explain it;
        - two or more → single-pick (`tx_explain_pick_ask`, pause `flow: "tx_explain"`);
        - zero with a slot → offer every Pending or Reversed row of the last 12 months;
        - none at all → the fixed `tx_explain_none`.
      - The explanation is facts for goal `tx_explain`:
        - `tx_state_cause` = the policy `cause_key`;
        - `tx_state_next_step` = the policy `next_step_key`;
        - for Pending, `clear_by_date` = `occurred_at` local date + `hold_days`. When that date is before today, use `overdue_next_step_key`, add no `clear_by_date`, and add `QuickRepliesPayload(slot="next_step", options=[PickerOption(label=tx_human_option)])`;
        - for Reversed there is no date and no claim of a twin line (A5).
      - The source of the policy facts is `f"policy:transaction_states@{ctx.policy_version}"`. The explanation logic is one function that `tx_search`'s pick imports.
    - **Graph registration.** Both nodes are registered everywhere the Facts section lists (`graph.py` tables, `add_node` with `_guard_access`, the four maps, their own `_after_flow` block; `runner._BRANCH_NODES`).
    - **Pick gate.** `runner.checkpointed_offer` returns `(pending, set(tx_offer.offered_tx_ids), False)` when `pending["flow"] in {"tx_search", "tx_explain"}`.
    - **Compose.**
      - `compose@v7` (a copy of v6 plus the two goals' instructions) with `Goal` extended.
      - `compose()` picks `tx_explain` when the facts carry `tx_state_cause`, else `tx_details` for those two intents.
      - `_format_fact` handles the new keys: labels for `tx_state_*`, `format_date` for `clear_by_date`, passthrough for `category`/`channel`/`city`.
      - `test_compose.py` asserts `compose@v7`.
    - **Templates.** All pinned T4 templates exist in ES and PT.
    - **Diagram.** `make graph-diagram` is rerun.
    - **Tests** (clock `datetime(2026,4,2,18,0,tzinfo=UTC)`):
      - **Test 1:** customer `CLI-TFTXSRC00007`; NLU `transaction_search`, `merchant_text="Super Ahorro"`, `date_expression="martes pasado"`, `amount=350`, `amount_approx=True`, ES. Assert via a recording wrapper or FakeBank spy that the search's `TxFilter` has `date_from == date_to == 2026-03-31`, `merchant_names == ["Super Ahorro"]`, `amount_min == 315`, `amount_max == 385`, and that `TRX-TFT7CRED0001TXN01` is offered with `multi=False`.
      - **Test 2 (PT):** a merchant with no rows → two searches, the second one ±3 days, then the no-results text naming the filters.
      - **Test 3:** no criterion → the clarify text and `"search_transactions" not in bank_tools.calls`.
      - **Test 5 (PT):** pick the Pending row → the facts include `clear_by_date` = 2026-04-03 and the source starts with `policy:transaction_states@`. The reply contains `03/04/2026` (or the `format_date` form), rendered by code.
      - **Test 6 (ES):** the Reversed row → `tx_state_cause = reversed_charge`, and no fact or segment mentions a second line.
  - Verify: `cd backend && uv run pytest tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py tests/unit/test_compose.py tests/unit/test_graph.py tests/unit/test_decline_explain_flow.py tests/unit/test_selection_gate.py -q && uv run ruff check app/domains/conversation/flows/tx_search.py app/domains/conversation/flows/tx_explain.py app/domains/conversation/graph.py app/domains/conversation/runner.py app/domains/conversation/templates.py app/domains/conversation/nodes/compose.py tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py tests/unit/test_compose.py && uv run ruff format --check <same paths> && uv run mypy app/domains/conversation && uv run lint-imports`
  - Files: `backend/app/domains/conversation/flows/tx_search.py`, `backend/app/domains/conversation/flows/tx_explain.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/runner.py`, `backend/app/domains/conversation/templates.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/prompts/compose@v7.md`, `backend/tests/unit/test_compose.py`, `backend/tests/unit/test_tx_search_flow.py`, `backend/tests/unit/test_tx_explain_flow.py`, `docs/diagrams/turn-graph-v0.mmd`

- [ ] T5: B2 flow: priority flags on `unrecognized_charge`, Reclamos/Fraudes outcomes, R6 extension
  - Depends on:
    - T3: `BankReadTools.get_priority_signals()`, the `priority_flags` arg on `create_claim`, `FakeBankOverlay.claim_priorities`, and the `"priority_flags": []` placeholders in `unrecognized_charge.py`.
    - T2: `DisputesPolicy.amount_over_threshold`, `priority.handoff`, `HandoffReason "priority_claim"`.
    - T1: `TurnState.priority_flags` and the fixture customers `CLI-TFREPT00008`/`CLI-TFAMNT00009`/`CLI-TFCRIT00010`.
    - T4: `templates.py` (append only).
  - Read exactly these: spec §Decisions D5-D10 and this plan's SA1; `backend/app/domains/conversation/flows/unrecognized_charge.py`; `backend/tests/unit/test_dispute_flows.py` (the claim/confirm/handoff test pattern)
  - Acceptance:
    - **Flag check.** Before either claim plan is issued (`_start_claim_plan`, `_start_compromise_plan`, `_offer_claim_only`), code computes a sorted `priority_flags` list:
      - `repeat_complainer`/`open_critical` from one `get_priority_signals()` call;
      - `amount_over_threshold` if any picked transaction's record `amount`/`currency` passes `policy.amount_over_threshold`.
      - The list is written to `state["priority_flags"]` and into the plan's `"priority_flags"` arg, and the confirm calls pass the same list (read back from state, never from the LLM).
      - A `ToolUnavailable` on the signals read → the existing `tool_failure` path.
    - **Single-charge path (D6).** After a **verified** claim with non-empty flags, set `escalation_reason = policy.priority.handoff.reason` (`priority_claim`) and `handoff_queue = "reclamos"`. The graph goes `handoff_summary → handoff`, and the claim reply segment is kept. An unverified claim takes the existing `action_unverified` path unchanged.
    - **Compromise path (D7).** The handoff stays `suspected_fraud → fraudes`. The flag lines (`priority_flag_<name>` templates, ES/PT) are appended to `handoff_open_questions`.
    - **`nodes/handoff.py`:** when `state["priority_flags"]` is non-empty and `reason != "priority_claim"`, `escalation_rules_hit = [reason, "priority_claim"]`. It also returns `"priority_flags": []`.
    - **Test 7:** `test_priority_flags.py::test_flag_hands_off_to_reclamos`, parametrized `repeat-es` (`CLI-TFREPT00008`), `amount-pt` (`CLI-TFAMNT00009`), `critical-es`/`critical-pt` (`CLI-TFCRIT00010`), `repeat-pt`, `amount-es`. Each runs pick one tx → questions → confirm and asserts:
      - `ActionResult.verified`;
      - the plan args carry the flag;
      - `overlay.claim_priorities[case_id] == "High"`;
      - the created packet has `reason == "priority_claim"`, `queue == "reclamos"`, `priority == "high"`.
    - **Test 8:** `test_regulator_mention_goes_to_reclamos[es,pt]`. The claim is paused at a question; NLU returns a regulator keyword (`condusef`/`procon`). Asserts a `legal_regulator` packet to `reclamos` and no `create_claim` call.
    - **Test 9:** `test_compromise_keeps_fraudes`. `CLI-TFREPT00008` picks both rows → compromise plan → confirm. Asserts the `fraudes`/`suspected_fraud` packet, `"priority_claim" in escalation_rules_hit`, and the flag line in `open_questions`.
    - **Test 11 (R6 extension):**
      - `flows/tx_search.py` and `flows/tx_explain.py` exist and have no write-tool references (`_write_tool_references` on each, whether or not they import `app.core.llm`);
      - `eval/judges/judge.py` (repo root = `parents[3]` of the test file) has none either;
      - no `backend/app/**/*.py` except `app/core/llm/registry.py` contains `"judge"` as a step string (`step="judge"`).
    - `test_dispute_flows.py` still passes unchanged (`CLI-TFSINGLE0002` has no flags).
  - Verify: `cd backend && uv run pytest tests/unit/test_priority_flags.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_dispute_flows.py tests/unit/test_handoff_packet.py tests/unit/test_escalation_rules.py -q && uv run ruff check app/domains/conversation/flows/unrecognized_charge.py app/domains/conversation/nodes/handoff.py app/domains/conversation/templates.py tests/unit/test_priority_flags.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run ruff format --check <same paths> && uv run mypy app/domains/conversation && uv run lint-imports`
  - Files: `backend/app/domains/conversation/flows/unrecognized_charge.py`, `backend/app/domains/conversation/nodes/handoff.py`, `backend/app/domains/conversation/templates.py`, `backend/tests/unit/test_priority_flags.py`, `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`, `backend/tests/unit/test_dispute_flows.py` (only if an existing assertion breaks)

- [ ] T6: B3 traceability screens on mocks (list, filters, per-turn "why")
  - Depends on: nothing (builds against the spec's proposed shapes, D12)
  - Read exactly these: spec §"Contracts" → "B3: `04` §3 additions (proposed)" and D11-D13; `frontend/e2e/mock-staff-api.ts` + `frontend/e2e/staff.es.spec.ts` (mock and login pattern); `frontend/src/routes/staff/handoffs.$handoffId.tsx` (staff route guard + query pattern)
  - Acceptance:
    - **`src/lib/traceability.ts`** holds hand-written TS types matching `ConversationFilters`, `ConversationListItem`, `ConversationList`, `TimelineLLMCall`, `TimelineEvent`, `TurnTimeline` and `ConversationTimeline`. Its reason union includes `priority_claim`. A header comment says the file is deleted when A1's generated client lands (D12).
    - **Fetchers** `listConversations(filters)` and `getConversationTimeline(id)` call `GET /api/v1/staff/conversations` and `/{id}/timeline` with `credentials: "include"`. A `401` goes to `/staff/login`, as `api.ts`'s staff calls do.
    - **`/staff/conversations`** has the same `staffMe` guard as `staff/index.tsx`. It shows a table (started, language, country, intents, outcome, escalation, queue, turns, mode) with filters for language, country, intent, outcome, escalation and a date range, **held in URL search params** (TanStack `validateSearch`). Each row links to `/staff/conversations/$conversationId`.
    - **The detail route** lists the turns in order. Each turn expands to "why", showing:
      - the NLU result, rules hit, tools with results, sources, `policy_version`;
      - per LLM call: step, model, prompt version, latency, cost;
      - turn latency and cost;
      - the Langfuse link, **hidden when `langfuse_url` is null**.
      - It renders only masked payloads and has no chain-of-thought field (ADR-024).
    - `staff/index.tsx` gains a link to the list.
    - The ES/PT dictionaries gain every new key plus `staff.reason.priority_claim`.
    - **Mocks.** `mock-staff-api.ts` serves the list (≥3 conversations, two intents) and filters by `intent`, `language` and `outcome` from the query string. It serves one timeline with 2 turns: one with `langfuse_url` set, one null.
    - **Test 12.** `e2e/traceability.es.spec.ts`:
      1. staff login;
      2. open `/staff/conversations`, see N rows;
      3. filter by intent: the count changes and the URL carries the param;
      4. open a conversation and expand a turn;
      5. NLU, rules, sources, the policy hash and the Langfuse link are visible;
      6. the null-link turn shows no link.
    - `staff.es.spec.ts` still passes.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npm run typecheck && npx biome ci src/lib/traceability.ts src/routes/staff/conversations.index.tsx 'src/routes/staff/conversations.\$conversationId.tsx' src/routes/staff/index.tsx src/components/staff/ConversationFilters.tsx src/components/staff/ConversationTable.tsx src/components/staff/TurnTimeline.tsx src/lib/i18n/es.json src/lib/i18n/pt.json e2e/mock-staff-api.ts e2e/traceability.es.spec.ts && npm run build && npx playwright test e2e/traceability.es.spec.ts e2e/staff.es.spec.ts"` (kill any stale port-4173 preview first; LF line endings on your files)
  - Files: `frontend/src/lib/traceability.ts`, `frontend/src/routes/staff/conversations.index.tsx`, `frontend/src/routes/staff/conversations.$conversationId.tsx`, `frontend/src/routes/staff/index.tsx`, `frontend/src/components/staff/ConversationFilters.tsx`, `frontend/src/components/staff/ConversationTable.tsx`, `frontend/src/components/staff/TurnTimeline.tsx`, `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`, `frontend/e2e/mock-staff-api.ts`, `frontend/e2e/traceability.es.spec.ts`

- [ ] T7: B4 judge tooling: `judge` step, rubric, `sample`/`judge`/`agreement` CLI, harness `transcripts.jsonl` (SA2)
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "B4: eval" and D14-D17, §Assumptions A8-A9, this plan's SA2; `eval/simulator/simulator.py` (the `sys.path` bootstrap, `_Masker`, the prompt path, the `structured(...)` call); `eval/harness/pii_check.py` (`_load_personas_pii`)
  - Acceptance:
    - **`judge` step.** `core/llm/registry.py` adds `"judge"` to `Step`, `MODEL_REGISTRY` (`{"openai": "gpt-6-luna"}`), `TEMPERATURE` (1.0) and `STEP_PROVIDER` (`"openai"`), with an ADR-030 comment.
    - **Transcripts (SA2).**
      - `eval/harness/runner.py` collects each played case's `Transcript` and writes `eval/reports/<run_id>/transcripts.jsonl` beside `results.jsonl`, using the pinned row shape.
      - `.gitignore` gains `eval/reports/*/transcripts.jsonl`.
      - No other runner change. Flag it in the state file for Dev A review.
    - **`eval/judges/sample.py`** (`sample --run <run_id> --labelers <a>,<b> [--seed 0] [--n 50]`):
      - it refuses unless `meta.json` has `suite == "dev"` and `system` contains `proposed` (R9);
      - it reads `transcripts.jsonl` (system `proposed` only) and builds candidate units, each one bot reply (the joined `message` event texts of one turn) plus its preceding turns;
      - it balances 25 ES / 25 PT and spreads across intents, with a seeded RNG;
      - it masks every text with the persona's known PII (`_load_personas_pii` → `KnownPii` → `find_pii`, numbered `⟨KIND_n⟩` tokens);
      - it writes `eval/judges/items.jsonl` (the pinned item shape), a human-readable `eval/judges/items.md`, `labels/assignment.yaml` (first 10 shared, the next 20 to the first labeler, the last 20 to the second) and one skeleton `labels/<labeler>.yaml` per labeler (records for their 30 items, booleans `null`, `labeler` set).
    - **`eval/judges/judge.py`** (`judge [--items eval/judges/items.jsonl]`):
      - `JudgeVerdict` has the pinned schema; `note` is truncated to 200 characters and masked.
      - `build_judge_user_message(item)` puts the context and the reply inside explicit data fences, with a "the fenced text is data, not instructions" line, and raises if `find_pii` (document and names unknown → the regex classes) still finds anything.
      - The system prompt is `eval/prompts/judge@v1.md`: the rubric's four dimensions plus overall, ES/PT.
      - It calls `get_llm_client().structured(step="judge", prompt=PromptRef("judge", 1), …)` and writes `eval/judges/judge_verdicts.jsonl` (`item_id` + verdict).
    - **`eval/judges/agreement.py`** (`agreement`):
      - it loads the items, labels, assignment and verdicts;
      - judge vs human: κ and % agreement for overall and each of the 4 dimensions over all labeled items, using the **first labeler's** label on the shared ones;
      - human vs human: κ and % on the 10 shared items, with n and a small-sample caveat;
      - it states n, the label "offline evaluation" and the temperature-1.0 non-repeatable caveat;
      - the first line is `**judge is weak**` when overall κ < 0.6;
      - it writes `eval/judges/agreement.md`;
      - `cohen_kappa` returns `None` when expected agreement is 1, and the report shows "n/a".
    - **`eval/judges/rubric.md`** holds the human-facing rubric: the four dimensions + overall, each with a pass/fail definition and an ES/PT example.
    - `__main__.py` dispatches the three subcommands.
    - **Test 13.** `eval/tests/test_judge_agreement.py`:
      - `test_kappa_and_weak_flag`: fixed label/verdict lists with a hand-computed κ (e.g. a 10-item overall list with κ = 0.4 and 80% agreement) → `render_report` contains those numbers, starts with "judge is weak", and contains "offline evaluation" and n;
      - `test_judge_input_masked_and_fenced`: an item text carrying a fake persona name and document → after `mask_text` with that `KnownPii`, neither value appears, and `build_judge_user_message` wraps the text in the fences.
      - No LLM call; a tiny local fake if needed.
  - Verify: `uv run --project backend pytest eval/tests/test_judge_agreement.py eval/tests/test_runner_abort.py -q && uv run --project backend ruff check --config backend/pyproject.toml eval/judges eval/tests/test_judge_agreement.py && uv run --project backend ruff format --check --config backend/pyproject.toml eval/judges eval/tests/test_judge_agreement.py && uv run --project backend python -m eval.judges --help && cd backend && uv run mypy app/core/llm && uv run pytest tests/unit/test_llm_client.py -q` (runner.py carries accepted pre-existing ruff debt, D6-B T2: lint it with `ruff check` only for **new** findings versus `git stash`)
  - Files: `backend/app/core/llm/registry.py`, `eval/judges/__init__.py`, `eval/judges/__main__.py`, `eval/judges/sample.py`, `eval/judges/judge.py`, `eval/judges/agreement.py`, `eval/judges/rubric.md`, `eval/prompts/judge@v1.md`, `eval/harness/runner.py`, `.gitignore`, `eval/tests/test_judge_agreement.py`

- [ ] T8: Dev seeds for the new behaviors and a repeat-complainer persona (A11)
  - Depends on: nothing (tool names are pinned in this plan: `transactions.search`, `disputes.get_priority_signals`, `disputes.create_claim`; outcome for the claim seed `handoff:reclamos`)
  - Read exactly these: `eval/scenarios/schema.py` (seed shape, `Category`, `expected_outcome` pattern); `eval/scenarios/dev/d-transaction_search-ambiguous-pt-br-01.yaml` (seed example); `eval/personas.yaml` header (trait vocabulary and predicates)
  - Acceptance:
    - **Seeds.** Three new seed files, each with an `.s` case only (no paraphrase run):
      1. `d-transaction_search-normal_resolution-es-mx-01`: a MX persona that has a `Super Ahorro` transaction in `latam_golden`; the turn names merchant, weekday and approximate amount taken from a real row; `required_tools: [transactions.search]`; `resolved`.
      2. `d-pending_reversal_explain-normal_resolution-pt-br-01`: a persona with `has_pending_transaction`; `required_tools: [transactions.search]`; `resolved`.
      3. `d-unrecognized_charge-human_required-es-<cc>-01`: a **new** persona with `repeat_complainer: true`, at least one card in an eligible status and at least one Approved/Pending transaction. Nobody else uses it in the dev suite, per the lint rule on writing personas. It has `required_tools: [transactions.search, disputes.get_priority_signals, disputes.create_claim]`, `expected_outcome: handoff:reclamos`, `required_handoff_fields` including `reason`, and a `fact_sheet` naming the transaction to pick.
    - **Personas.** New personas are added to `eval/personas.yaml` with `split: dev` and only traits verified by the header's predicates against `latam_golden` (aggregates and ids only, R10).
    - `eval/scenarios/heldout/` and `_staging/` are untouched.
  - Verify: `make eval-mix DIR=eval/scenarios/dev && uv run --project backend pytest eval/tests/test_scenarios_valid.py -q && uv run --project backend python -c "from pathlib import Path; from eval.scenarios.schema import load_dir; from eval.harness.lint import lint_suite; lint_suite(load_dir(Path('eval/scenarios/dev')))" && git diff --quiet -- eval/scenarios/heldout eval/scenarios/_staging && cd backend && REDIS_URL=redis://127.0.0.1:6379/0 uv run python -c "import asyncio,sys,pytest; asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); sys.exit(pytest.main(['tests/integration/test_personas.py','-q']))"`
  - Files: `eval/scenarios/dev/d-transaction_search-normal_resolution-es-mx-01.yaml`, `eval/scenarios/dev/d-pending_reversal_explain-normal_resolution-pt-br-01.yaml`, `eval/scenarios/dev/d-unrecognized_charge-human_required-es-<cc>-01.yaml`, `eval/personas.yaml`

- [ ] T9: Docs: `04` §1/§3/§4/§5, `02` §4.4/§4.5/§4.8, `07` §8, `06` §2, spec D10 (SA1)
  - Depends on: nothing (documents the pinned contracts in this plan)
  - Read exactly these: spec §"Touch map" → Docs, §Contracts and §Decisions D1-D17; this plan's "Spec amendments" and "Cross-task names"; `docs/solution-docs/04-contracts.md` §1 (line ~44), §3, §4, §5
  - Acceptance:
    - **`04` §1:**
      - the `create_claim` row becomes `disputes.create_claim(tx_ids, answers, priority_flags, token)`, with `priority_flags` code-built and token-bound, and `'High'` when non-empty (SA1); the "deferred" note is removed;
      - a new read row: `disputes.get_priority_signals()` → `PrioritySignals`.
    - **`04` §3:** the D11 shapes and the two routes, marked **(proposed)**, with the `get_claimed_conversation` exemption (agent/admin only, masked data).
    - **`04` §4:** `priority_claim` in the `reason` list.
    - **`04` §5:**
      - the `transaction_states.yaml` block;
      - the `disputes.yaml` v2 priority block;
      - the `escalation.yaml` v4 `priority_claim` rule;
      - the "Other files" line is updated.
    - **`02`:** §4.4 gets D1-D2, §4.5 gets D3 (one line each), and §4.8 gets D5-D9.
    - **`07` §8 row (line ~442):** the judge is OpenAI `gpt-6-luna`, temperature 1.0 (D14).
    - **`06` §2 `openai` line:** "eval paraphrase, simulator and judge only, ADR-030".
    - **Spec D10:** "the flags travel in graph state only" → "the flags travel in graph state and the signed plan args (`create_claim.priority_flags`)".
  - Verify: `grep -n "priority_flags" docs/solution-docs/04-contracts.md && grep -n "get_priority_signals" docs/solution-docs/04-contracts.md && grep -n "(proposed)" docs/solution-docs/04-contracts.md && grep -n "priority_claim" docs/solution-docs/04-contracts.md && grep -n "transaction_states" docs/solution-docs/04-contracts.md && grep -n "tx_search\|tx_explain" docs/solution-docs/02-conversation-design.md && grep -n "judge" docs/solution-docs/07-execution-plan.md | grep -i "gpt-6-luna" && grep -n "signed plan args" docs/specs/d7-b-transactions-traceability-judge.md && ! grep -n "is deferred with the priority-flags" docs/solution-docs/04-contracts.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/07-execution-plan.md`, `docs/solution-docs/06-engineering-rules.md`, `docs/specs/d7-b-transactions-traceability-judge.md`

- [ ] T10: Live proofs: backend restart, client regen, browser search/pending, repeat complainer → Reclamos, dev eval run, `sample`, `judge`
  - Depends on: T1-T9 (all code, seeds and personas)
  - Read exactly these: spec §"Success criteria" 3, 4, 5, 8; `backend/scripts/chat_api.py` (per-turn SSE, CSRF, `/pick`); this plan's "Facts checked" → Commands and Eval
  - Acceptance:
    1. **Restart and client.** Restart the backend (`make up`, or `docker compose restart backend`) so the policies reload. `GET http://localhost/api/v1/health` → 200. Record the policy hash before and after (SC5). `make client` → `types.gen.ts` gains `priority_claim`, and `npm run typecheck` is clean in the container.
    2. **SC3.** Through `backend/scripts/chat_api.py` (or the browser at `http://localhost`) as the T8 search persona:
       - "el cargo de Super Ahorro del martes pasado por unos 350" (weekday and amount adjusted to that persona's real row) → a `ui.transaction_list` containing the row;
       - `/pick` of a Pending row (the T8 pending persona) → a reply with a code-formatted date.
       - Paste the event excerpts into the state file.
    3. **SC4.** The T8 repeat-complainer persona files a single-charge claim through the API:
       - `GET /staff/handoffs` shows a `reclamos` handoff with reason `priority_claim`;
       - `SELECT priority, origin FROM bank.complaints WHERE conversation_id = '<id>'` → `High`, `app` (read-only query on the app DB).
       - Then run `make demo-reset` (or the restore the D6-A/B cards used) so the demo data is clean.
    4. **Eval and B4 data.**
       - `make eval SUITE=dev SYSTEM=proposed` finishes, and `eval/reports/<run>/transcripts.jsonl` exists;
       - `uv run --project backend python -m eval.judges sample --run <run> --labelers <a>,<b>` (the labeler names come from the orchestrator/human) → 50 items, 25 ES / 25 PT, `items.md`, the assignment and two skeletons;
       - `uv run --project backend python -m eval.judges judge` → 50 verdicts. This is a paid OpenAI call and needs `OPENAI_API_KEY`; if it is missing, stop and report.
    5. **SC8.** `git diff develop -- eval/scenarios/heldout/` is empty.
  - Verify: `curl -s -o /dev/null -w "%{http_code}" http://localhost/api/v1/health | grep -q 200 && grep -c "priority_claim" frontend/src/client/types.gen.ts && test "$(wc -l < eval/judges/items.jsonl)" -eq 50 && test "$(wc -l < eval/judges/judge_verdicts.jsonl)" -eq 50 && test -f eval/judges/labels/assignment.yaml && git diff --quiet develop -- eval/scenarios/heldout/ && git check-ignore -q eval/reports/x/transcripts.jsonl`
  - Files: `frontend/src/client/types.gen.ts`, `eval/judges/items.jsonl`, `eval/judges/items.md`, `eval/judges/labels/assignment.yaml`, `eval/judges/labels/<a>.yaml`, `eval/judges/labels/<b>.yaml`, `eval/judges/judge_verdicts.jsonl`

- [ ] T11: Agreement report from the human labels
  - Depends on: T10 (items, assignment, verdicts) and the human gate (both `labels/<labeler>.yaml` files fully filled in: no `null` booleans, `labeled_at` set)
  - Read exactly these: spec D16-D17 and success criterion 6; `eval/judges/labels/assignment.yaml`
  - Acceptance:
    - `uv run --project backend python -m eval.judges agreement` writes `eval/judges/agreement.md`. It shows:
      - n = 50;
      - judge-vs-human κ and % for overall + 4 dimensions;
      - human-vs-human κ and % on the 10 shared items, with a small-sample caveat;
      - "offline evaluation" and the temperature caveat;
      - a first line of "judge is weak" iff overall κ < 0.6.
    - If any label is still `null`, the command refuses and names the item ids. Report them; don't fill them in.
  - Verify: `uv run --project backend python -m eval.judges agreement && grep -q "offline evaluation" eval/judges/agreement.md && grep -q "n = 50\|n=50" eval/judges/agreement.md`
  - Files: `eval/judges/agreement.md`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T6, T7, T8, T9 | | No dependencies. Disjoint files: T1 is B1 core + `state.py` + fixture + `policy/registry.py`; T2 is the disputes/escalation policy + `HandoffReason`; T6 is frontend only; T7 is `eval/judges`, `core/llm/registry.py`, `eval/harness/runner.py`, `.gitignore`; T8 is seeds + `personas.yaml`; T9 is docs + the spec. No dependency or lockfile change. |
| W2 | T3, T4 | | T3 needs T1+T2 and T4 needs T1. T3 owns the tools, the disputes domain and `unrecognized_charge.py`; T4 owns `graph.py`, `runner.py`, `compose.py`, `templates.py` and the new flows. No shared path. |
| W3 | T5 | | Needs T3 (tool + arg) and T4 (`templates.py` is edited after T4). |
| W4 | T10 | alone (restarts the backend, regenerates the client, runs the live eval and paid judge calls, writes to the app DB) | Everything must be in place. |
| — | human gate | — | Both people fill in `eval/judges/labels/<labeler>.yaml` (about 1 h). |
| W5 | T11 | | Reads only the committed B4 files. |
