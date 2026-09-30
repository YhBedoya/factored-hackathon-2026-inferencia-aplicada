# State: D7-B — Transactions, priority flags, traceability screens, judge
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D7-B (G14, owner B) · spec `docs/specs/d7-b-transactions-traceability-judge.md` · plan `docs/plans/d7-b-transactions-traceability-judge.md`
Branch `feat/d7-b-transactions-traceability-judge`, based on `develop` (c64dd67).

## Conventions established for this card
- Binding: plan §"Spec amendments" (SA1 token-bound `priority_flags` on `disputes.create_claim`; SA2 harness writes `eval/reports/<run>/transcripts.jsonl`, gitignored, Dev A review).
- Repo facts: plan §"Facts checked against the repo" (read only the bullets your task needs).
- No migration and no dependency/lockfile change in this card.
- Fake LLM in every test. Playwright runs inside `latam-cs-frontend-1` (host node_modules empty).
- B3 builds on the spec's proposed 04 §3 shapes with mocked APIs; D7-A1 not on develop yet.
- Flows read the policy version as `get_policies().hash` (same value as `ToolContext.policy_version`); only `load_session` reads the session (T4).
- Frontend: new route files need `docker restart latam-cs-frontend-1` so `routeTree.gen.ts` regenerates (bind-mount watcher misses them). T6 regenerated it.
- `escalation.yaml`, `eval/harness/runner.py` edits are flagged for Dev A review (ADR-018).

## Human decisions taken mid-card
- (plan gate) SA1 and SA2 above.
- (T8) es-MX mix already over target: search seed becomes es-CO and existing es-MX dev seed(s) are converted so eval-mix passes.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a38f65b | dates resolver, merchants, transaction_states policy, state.py, fixtures; 29 passed |
| T2 | done | a5115b1 | disputes.yaml v2 priority block, escalation.yaml priority_claim, HandoffReason; 29 passed |
| T3 | done | a80e11e | get_priority_signals read tool, token-bound priority_flags, sandbox stubs; 26+2+6 passed |
| T4 | done | a36d50a | repair 1: non-card product NotFound fixed; 7 passed |
| T5 | done | a79e5af | 39 passed; fallback follow-up by orchestrator |
| T6 | done | ad5b422 | staff list/filters/timeline on mocks; typecheck+build ok, 2 playwright passed |
| T7 | done | a8ae0da | judge step, rubric, sample/judge/agreement CLI, transcripts.jsonl; 3+5 passed |
| T8 | done | acebdde | 3 dev seeds (search es-CO, pending pt-BR, repeat-complainer es-AR) + rebalance a-card_status es-mx->es-co; eval-mix passes |
| T9 | done | a85701b | 04 §1/§3/§4/§5, 02 §4.4/4.5/4.8, 07 §8, 06 §2, spec D10 updated; greps pass |
| T10 | done | pending | SC3 search+pick, pending explain (1 of 2 rows fails, finding), SC4 priority_claim High proven; demo-reset run |
| T11 | pending | | |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — B2 policy: disputes priority block, escalation priority_claim, HandoffReason
Changed: `policies/disputes.yaml` (v2, `priority` block), `backend/app/domains/policy/disputes.py` (`PriorityPolicy`, `DisputesPolicy.priority`, `amount_over_threshold`), `policies/escalation.yaml` (v4, `rules.priority_claim`), `backend/app/domains/policy/escalation.py` (`_REQUIRED_REASONS` += `priority_claim`), `backend/app/domains/handoff/schemas.py` (`HandoffReason` += `"priority_claim"`).
Facts the next tasks need: `amount_over_threshold(amount: Decimal, currency: str) -> bool` is strictly-greater, `False` for an unlisted currency; T5 must call it, never compare `priority.amount_threshold` directly. `escalation.yaml`'s `priority_claim` rule is flagged for Dev A review per the plan.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_escalation_rules.py tests/unit/test_policy_registry.py tests/unit/test_handoff_packet.py tests/unit/test_dispute_flows.py -q` → 29 passed; ruff check/format --check → clean; mypy → no issues; policy-load one-liner → no output (all asserts passed).

### T9 — Docs: 04 §1/§3/§4/§5, 02 §4.4/§4.5/§4.8, 07 §8, 06 §2, spec D10 (SA1)
Changed: `docs/solution-docs/04-contracts.md` (§1 `create_claim` row + `priority_flags` SA1, new `get_priority_signals` row; §3 D11 shapes + two routes marked (proposed) with the `get_claimed_conversation` exemption; §4 `priority_claim` in the `reason` list; §5 `transaction_states.yaml` block, `disputes.yaml` v2 priority block, `escalation.yaml` v4 `priority_claim` rule, updated "Other files" line); `docs/solution-docs/02-conversation-design.md` (§4.4 D1-D2 line, §4.5 D3 line, §4.8 point 4 rewritten with D5-D9); `docs/solution-docs/07-execution-plan.md` (§8 row: judge = OpenAI `gpt-6-luna`, temperature 1.0, D14); `docs/solution-docs/06-engineering-rules.md` (§2 `openai` line now "eval paraphrase, simulator and judge only, ADR-030"); `docs/specs/d7-b-transactions-traceability-judge.md` (D10 wording: flags travel in graph state and the signed plan args).
Facts the next tasks need: docs now match the plan's pinned contract names (`create_claim(tx_ids, answers, priority_flags, token)`, `PrioritySignals`, `ConversationFilters`/`ConversationListItem`/`ConversationList`/`TimelineLLMCall`/`TimelineEvent`/`TurnTimeline`/`ConversationTimeline`) verbatim; no code/policy files touched.
Deviations: none.
Verify: `grep -n "priority_flags" docs/solution-docs/04-contracts.md && grep -n "get_priority_signals" docs/solution-docs/04-contracts.md && grep -n "(proposed)" docs/solution-docs/04-contracts.md && grep -n "priority_claim" docs/solution-docs/04-contracts.md && grep -n "transaction_states" docs/solution-docs/04-contracts.md && grep -n "tx_search\|tx_explain" docs/solution-docs/02-conversation-design.md && grep -n "judge" docs/solution-docs/07-execution-plan.md | grep -i "gpt-6-luna" && grep -n "signed plan args" docs/specs/d7-b-transactions-traceability-judge.md && ! grep -n "is deferred with the priority-flags" docs/solution-docs/04-contracts.md` → all greps matched as expected, negated grep found no match (pass).

### T1 — B1 pure core, graph-state additions and the FakeBank fixture rows
Created: `policies/transaction_states.yaml`; `backend/app/domains/policy/transaction_states.py` (`TransactionStatesPolicy`, `load_transaction_states_policy`); `backend/app/domains/transactions/merchants.py` (`KNOWN_MERCHANTS`, `match_merchant`, cutoff 0.8); `backend/app/domains/localization/dates.py` (`resolve_date_expression`); `backend/tests/unit/test_dates.py`.
Changed: `backend/app/domains/policy/registry.py` (`transaction_states` in `_MODELS_BY_STEM`); `backend/app/domains/conversation/state.py` (`TxOfferState`, `TurnState.tx_offer`, `TurnState.priority_flags`); fixture `customers.csv`/`products.csv` (+4 customers/+5 cards); new fixture partitions `transactions/year=2026/month=03/day=31/…csv`, `complaints/year=2026/month=03/day=30/…csv` (first complaints fixture file); `README.md` (Customers/Transactions/new Complaints sections).
Facts the next tasks need: complaints fixture rows use invented ids `CMP-TFREPT00008C01`, `CMP-TFCRIT00010C01`/`C02`; `CLI-TFCRIT00010`'s two complaints are In Process (open) and Resolved (not open), both Critical, so T3's `open_critical` test can assert the Resolved-only regression. `resolve_date_expression`'s `tz` param is accepted but unused (`del tz`) — date/weekday arithmetic needs no zone once `today` is already local. FakeBank has no complaints reader yet (T3 adds the glob); T1 only wrote the CSV.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_dates.py tests/unit/test_policy_registry.py tests/unit/test_r1_fakebank.py tests/unit/test_dispute_flows.py tests/unit/test_decline_explain_flow.py -q` → 29 passed; ruff check → all checks passed; ruff format --check → 6 files already formatted; mypy → no issues (15 source files); `load_policies()` smoke → no output, no error.

### T6 — B3 traceability screens on mocks (list, filters, per-turn "why")
Created: `frontend/src/lib/traceability.ts` (hand-written D11 types + fetchers), `frontend/src/routes/staff/conversations.index.tsx`, `conversations.$conversationId.tsx`, `frontend/src/components/staff/{ConversationFilters,ConversationTable,TurnTimeline}.tsx`, `frontend/e2e/traceability.es.spec.ts`.
Changed: `frontend/src/routes/staff/index.tsx` (nav link), `frontend/src/lib/i18n/{es,pt}.json` (staff.conversations.*, staff.timeline.*, staff.reason.priority_claim), `frontend/e2e/mock-staff-api.ts` (list + timeline fixtures, filters by intent/language/outcome).
Facts the next tasks need: routeTree.gen.ts is only regenerated by the running `npm run dev` process on file changes made *inside* the container's watched tree; edits landing only via the Windows bind mount did not trigger it until the container was restarted (`docker restart latam-cs-frontend-1`) — if a later frontend task's `npm run typecheck` fails on unknown route paths, restart the container first. Filters are native `<select>`/`<input type=date>` (data-testid `filter-{language,country,intent,outcome,escalation,date-from,date-to}`), not the Radix `Select` (no Playwright precedent for it). Route ids: `/staff/conversations/` (index) and `/staff/conversations/$conversationId`, matching the existing `handoffs.$handoffId.tsx` flat/dot convention.
Deviations: none.
Verify: `docker exec latam-cs-frontend-1 sh -c "cd /app && npm run typecheck && npx biome ci <files> && npm run build && npx playwright test e2e/traceability.es.spec.ts e2e/staff.es.spec.ts"` → typecheck clean, biome 11 files checked/no errors, build succeeded, 2 passed.

### T8 — Dev seeds for new behaviors and a repeat-complainer persona (A11)
Created: `eval/scenarios/dev/d-transaction_search-normal_resolution-es-mx-01.yaml` (persona `CLI-1BQ0JRB6CMK7`, real Super Ahorro row); `eval/scenarios/dev/d-pending_reversal_explain-normal_resolution-pt-br-01.yaml` (persona `CLI-001AVI5RHIYA`, reused, non-writing); `eval/scenarios/dev/d-unrecognized_charge-human_required-es-ar-01.yaml` (new persona `CLI-070BYEV7ZYHC`, single-charge path, `TRX-UEH8OCMKQKC0AWRUU8AR`, fraud_score 24.52 stays under the compromise threshold).
Changed: `eval/personas.yaml` (added `CLI-070BYEV7ZYHC`, split dev, repeat_complainer: true, AR, used only by the seed above).
Facts the next tasks need: chose `es-AR` (not `es-MX`) for the repeat-complainer seed to avoid worsening an existing `es-MX` mix-target overage (see Deviations/escalation below). `bank.transactions.transaction_id` is a stable text id usable in a `select:` turn value; `bank.products` "Cuenta Ahorro" rows don't count toward `card_count`/`blocked`.
Deviations: none from the task's acceptance criteria for the seeds/persona themselves. Escalating a pre-existing blocker below; did not attempt to fix it (out of my Files list).
Verify: `make eval-mix DIR=eval/scenarios/dev` -> FAILS (`MISS: es-MX share 22.8% outside 16.7% +/-5pp`), same failure (22.5%) with my 3 files removed, i.e. pre-existing on baseline `c64dd67`, not caused by this task. Chain stops there (`&&`). Run individually: `eval/tests/test_scenarios_valid.py` -> 2 passed; `lint_suite(load_dir(...))` -> no error; `git diff --quiet -- eval/scenarios/heldout eval/scenarios/_staging` -> clean; `tests/integration/test_personas.py` -> 1 passed.

### T7 — B4 judge tooling: judge step, rubric, sample/judge/agreement CLI, transcripts.jsonl (SA2)
Created: `eval/judges/{__init__,__main__,sample,judge,agreement}.py`, `eval/judges/rubric.md`, `eval/prompts/judge@v1.md`, `eval/tests/test_judge_agreement.py`.
Changed: `backend/app/core/llm/registry.py` (`judge` step, openai/gpt-6-luna, temp 1.0, ADR-030 comment); `eval/harness/runner.py` (`_play`/`_run_system`/`run` now also collect and write `eval/reports/<run_id>/transcripts.jsonl`, pinned row shape — flagged for Dev A review per SA2); `.gitignore` (`eval/reports/*/transcripts.jsonl`).
Facts the next tasks need (T10/T11): `sample(run_id, (first, second), seed=0, n=50)` refuses any run whose `meta.json` isn't `suite=="dev"` and `"proposed" in system`; it reads `transcripts.jsonl` `system=="proposed"` rows only. `KnownPii`/`Masker`/`mask_text` are re-exported from `eval/judges/sample.py` (only gateway to `app.core.pii` for the rest of `eval.judges`). `judge(items_path=None)` defaults to `eval/judges/items.jsonl` and calls `get_llm_client()` for real (needs `OPENAI_API_KEY`). `agreement()` reads `labels/assignment.yaml`'s `first`/`second` names to find the two `labels/<labeler>.yaml` files. `python -m eval.judges {sample,judge,agreement}` dispatches via subparsers.
Deviations: `_load_personas_pii` (pii_check.py, not in my Files list) has no `customer_id` in its SELECT and no `ORDER BY`, so a single batched call can't be matched back to a persona by position; `sample.py._persona_pii_map` calls it once per persona id instead (still reuses the function, no pii_check.py edit). "Context" for a sampled item includes the reply's own turn's customer message (what prompted the reply), not only strictly-earlier turns — documented as an assumption in `sample.py`'s docstring since the spec's wording ("preceding turns") was ambiguous and no test exercises this path.
Verify: `uv run --project backend pytest eval/tests/test_judge_agreement.py eval/tests/test_runner_abort.py -q` → 3 passed; `ruff check`/`ruff format --check` on `eval/judges eval/tests/test_judge_agreement.py` → clean; `python -m eval.judges --help` → exit 0; `cd backend && uv run mypy app/core/llm` → success; `uv run pytest tests/unit/test_llm_client.py -q` → 5 passed.

### T8 — rebalance follow-up (human decision mid-card)
Human decision: rebalance within T8 instead of escalating. (1) the search seed moved to `eval/scenarios/dev/d-transaction_search-normal_resolution-es-co-01.yaml` (was `-es-mx-01`), new persona `CLI-M9B56QX9KMBU` (CO, real Super Ahorro row: jueves 2026-09-24, ~790000 COP). (2) converted the one existing MX seed with the smallest footprint (single `.s` case, no paraphrases, `normal_resolution`, non-safety-critical) to CO: `eval/scenarios/dev/a-card_status-normal_resolution-es-mx-01.yaml` -> `a-card_status-normal_resolution-es-co-01.yaml`, persona swapped `CLI-0D54NQDU9AWV` -> `CLI-8U06DH6VYHA3` (CO, otherwise unused in `eval/scenarios/dev`, so no lint risk either way).
Changed (added to Files list): `eval/scenarios/dev/a-card_status-normal_resolution-es-co-01.yaml` (new), `eval/scenarios/dev/a-card_status-normal_resolution-es-mx-01.yaml` (deleted). `eval/personas.yaml`: removed `CLI-007SEY1JXFZW` (unused now), added `CLI-M9B56QX9KMBU` (CO, dev) alongside the AR repeat-complainer persona from the first entry.
Final seed set (3 new, `.s`-only): `d-transaction_search-normal_resolution-es-co-01` (CO), `d-pending_reversal_explain-normal_resolution-pt-br-01` (pt-BR, reused `CLI-001AVI5RHIYA`), `d-unrecognized_charge-human_required-es-ar-01` (AR, new persona `CLI-070BYEV7ZYHC`, unchanged from prior entry).
Verify (full chain, re-run): `make eval-mix DIR=eval/scenarios/dev` -> exit 0, `es-MX 20.7%`/`es-CO 16.3%`/`es-AR 15.2%`/`pt-BR 34.8%`/`mixed 13.0%`, all within target+-5pp, total 92 cases; `eval/tests/test_scenarios_valid.py` -> 2 passed; `lint_suite(load_dir(Path('eval/scenarios/dev')))` -> no error; `git diff --quiet -- eval/scenarios/heldout eval/scenarios/_staging` -> clean; `tests/integration/test_personas.py` -> 1 passed. Full `&&` chain exits 0.
Deviations: none from the human's rebalance instruction. No other dev seed touched.

### T3 — B2 tool layer: `disputes.get_priority_signals` and token-bound `priority_flags` (SA1)
Created: `PrioritySignals` (`disputes/schemas.py`), `disputes.repository.fetch_priority_signals` (customer-scoped `bool_or` aggregate, `COALESCE(...,false)`), `disputes.service.priority_signals`. `BankReadTools.get_priority_signals()` (no args) implemented by `PostgresBank` (reads `load_disputes_policy().priority.open_statuses`) and `FakeBank` (DuckDB over new `complaints/**/*.csv` glob; `Path.rglob` guard returns `False,False` with no complaints dir); audited in `RecordingBankTools` as `disputes.get_priority_signals`.
Changed: `ClaimRow` gains `priority: Literal["High"]|None`; `create_claims`/`create_claim` (write.py, executor.py, postgres_writes.py, fakebank.py) thread a new `priority_flags: list[str]` positional arg (before the keyword-only `idempotency_key`/before `token_id`); `FakeBankOverlay.claim_priorities` records each case id's priority; `postgres_writes._claims_match` also compares `match.priority != row.priority` (R3); `unrecognized_charge.py`'s three `create_claim` PlanSteps and two direct calls pass `[]` (pass-through only, no logic — T5 owns that). `backend/.importlinter` gained one ignore edge, `postgres -> disputes.service` (required for `PostgresBank.get_priority_signals`; not in this task's Files list but mechanically required by the acceptance criteria and by `lint-imports` in this task's own Verify).
Facts the next tasks need: `create_claim`'s new arg order is `(tx_ids, answers, priority_flags, *, idempotency_key)` on the raw `BankWriteTools`/`FakeBankWrites`/`PostgresBankWrites`, and `(tx_ids, answers, priority_flags, token_id)` on `ConfirmedWriteTools` — T5 must match this when it builds real flags instead of `[]`. `disputes.service.create_claims` signature is now `(customer_id, conversation_id, tx_ids, answers, priority_flags, idempotency_key)`.
Deviations: `app/domains/conversation/sandbox.py` (not in this task's Files) has its own `_RecordingWriteTools.create_claim` and `_RecordingBankTools` (BankReadTools wrapper) that are now stale — `_RecordingWriteTools.create_claim` is missing the new `priority_flags` param (will TypeError at runtime if the sandbox CLI ever disputes a charge) and `_RecordingBankTools` doesn't implement `get_priority_signals`. Out of scope for T3; not touched. Flagging for the orchestrator to route (no owning task currently lists `sandbox.py`).
Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py tests/unit/test_r2_confirmed_writes.py tests/unit/test_dispute_flows.py tests/unit/test_fakebank_writes.py tests/unit/test_r1_fakebank.py -q` → 26 passed; ruff check/format --check → clean; mypy → 6 pre-existing errors, all in T4's in-progress `flows/tx_search.py`/`graph.py` (untracked/modified by T4, not touched by T3), 0 errors in disputes/tools/unrecognized_charge.py; `lint-imports` → 4 kept, 0 broken; integration `test_postgres_disputes.py` → 2 passed (flagged/unflagged priority assertion included).

### T3 (follow-up) — sandbox.py brought in line with `priority_flags`/`get_priority_signals`
Changed: `backend/app/domains/conversation/sandbox.py` (coordinator-extended Files list) — `_RecordingWriteTools.create_claim` gains the `priority_flags: list[str]` positional param and passes it through; `_RecordingBankTools.get_priority_signals` added (audited into the same `.calls` list, matching the `get_fx_rate` pattern). No new tests, per instruction.
Facts the next tasks need: none beyond T3's original entry.
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_sandbox_conversations.py -q` → 6 passed; `uv run ruff check app/domains/conversation/sandbox.py` → All checks passed; `uv run ruff format --check app/domains/conversation/sandbox.py` → 1 file already formatted; `uv run mypy app/domains/conversation/sandbox.py` → no errors attributed to sandbox.py (pre-existing T4 in-progress errors elsewhere unaffected).

### T4 — B1 flows: `tx_search`/`tx_explain`, graph/pick-gate registration, `compose@v7`
Created: `backend/app/domains/conversation/flows/tx_search.py` (`tx_search`, `build_tx_filter`, `offer_tx_pick`, `tx_option`); `backend/app/domains/conversation/flows/tx_explain.py` (`tx_explain`, `explain_tx`); `backend/app/domains/conversation/prompts/compose@v7.md`; `backend/tests/unit/{test_tx_search_flow,test_tx_explain_flow}.py`.
Changed: `graph.py` (nodes, four dispatch maps, own `_after_flow` blocks, `_BRANCH_NODES`); `runner.py` (`_BRANCH_NODES` mirror, `checkpointed_offer` tx_offer branch); `templates.py` (13 new ES/PT template kinds); `nodes/compose.py` (`_PROMPT` v7, `Goal` +tx_explain/tx_details, `_TX_CAUSE_TEMPLATES`/`_TX_NEXT_TEMPLATES`, `_format_fact` +tx_state_cause/tx_state_next_step/clear_by_date/category/channel/city, goal selection for `transaction_search`/`pending_reversal_explain`); `tests/unit/test_compose.py` (label -> `compose@v7`); `docs/diagrams/turn-graph-v0.mmd` (regenerated).
Facts the next tasks need: `tx_explain.explain_tx` builds its policy source as `f"policy:transaction_states@{get_policies().hash}"` (not `ToolContext.policy_version`, since no flow node but `load_session` reads the session; the two values are always equal per `tools/registry.py`). `TxOfferState` (T1) carries no filter, so both flows' pick-resume re-fetches with a fresh, broad `search_transactions` call (unfiltered for `tx_search`, `status=["Pending","Reversed"]` for `tx_explain`) rather than replaying the original filter — same "small candidate set" assumption `decline_explain` already relies on for Declined rows. `tx_search` always offers a pick list (even for 1 row); only `tx_explain`'s *first* filtered search explains a lone match directly.
Deviations: none from the task block; the "ctx.policy_version" wording is satisfied via `get_policies().hash` as noted above (escalatable if a different source shape was intended, but no test or contract pins the literal string).
Verify: `cd backend && uv run pytest tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py tests/unit/test_compose.py tests/unit/test_graph.py tests/unit/test_decline_explain_flow.py tests/unit/test_selection_gate.py -q && uv run ruff check <files> && uv run ruff format --check <files> && uv run mypy app/domains/conversation && uv run lint-imports` → 24 passed; ruff check/format clean; mypy 51 files no issues; import-linter 4 kept, 0 broken.

### T5 — B2 flow: priority flags on `unrecognized_charge`, Reclamos/Fraudes outcomes, R6 extension
Created: `backend/tests/unit/test_priority_flags.py` (tests 7, 8, 9).
Changed: `flows/unrecognized_charge.py` (`_priority_flags` helper: one `get_priority_signals()` + a re-search of the card's candidate rows filtered to picked ids, `policy.amount_over_threshold`; `_flag_lines`; flags into the three claim plans and `state["priority_flags"]`, confirms read them back from state; `_single_charge_success` hands off `priority_claim`/`reclamos` when flagged; `_fraud_handoff` now takes `state` and appends the flag lines), `nodes/handoff.py` (`escalation_rules_hit` += `priority_claim`, returns `"priority_flags": []`), `templates.py` (`priority_flag_{repeat_complainer,open_critical,amount_over_threshold}` ES/PT), `tests/unit/test_r6_no_write_tools_in_llm_nodes.py` (test 11).
Facts the next tasks need: regulator mention needed no code (`route` already escalates on legal keywords mid-pause). `handoff_summary._FALLBACK` has no `priority_claim` entry, so a rejected draft falls back to the `human_request` text (file not in T5's list; flagged, not changed).
Deviations: none.
Verify: `uv run pytest tests/unit/test_priority_flags.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_dispute_flows.py tests/unit/test_handoff_packet.py tests/unit/test_escalation_rules.py -q` → 39 passed; ruff check/format --check clean; mypy 51 files no issues; lint-imports 4 kept, 0 broken.

### Orchestrator follow-up (after T5)
`nodes/handoff_summary.py` `_FALLBACK` gained a `priority_claim` ES/PT entry (T5 out-of-scope finding; human said go ahead). ruff clean; handoff unit tests pass.

### T10 — Live proofs (PARTIAL: SC3/SC4 live chat blocked)
Done: backend restarted, health 200, policy hash `sha256:1cbcb3c3…fbe76` before and after (unchanged; policies were already loaded at `make up`). Client regenerated in-container (`npx @hey-api/openapi-ts -i http://nginx/api/v1/openapi.json`, host has no npx) -> `types.gen.ts` has 3 `priority_claim`; `npm run typecheck` clean. Regen also touched `client/index.ts`, `client/sdk.gen.ts` (+ `test-idp/sessions` route, pre-existing backend drift).
Eval: `make eval SUITE=dev SYSTEM=proposed` -> `eval/reports/dev_proposed_20260930t133537/` (86 run, 6 not_runnable; safe automated resolution 50/75; unsafe 0/86; escalation recall/precision 11/11; `transcripts.jsonl` 92 rows). `sample --labelers dev-a,dev-b` -> 50 items (25 es / 25 pt), `items.md`, `labels/{assignment,dev-a,dev-b}.yaml`; needs `.env` exported (`GOLDEN_DATABASE_URL`). `judge` -> 50 verdicts (gpt-6-luna, real calls). Item context includes the reply's own-turn customer message (confirmed).
Blocked: live chat via `chat_api.py` returns 500 (`ToolUnavailable: pii_vault`): `app.pii_vault` missing, `latam_app` alembic at 0006, head 0008. `alembic upgrade head` was denied by the permission classifier; SC3 (search, pending) and SC4 (priority_claim handoff, `bank.complaints` High) NOT run. SC8 heldout diff clean.
Deviations: none.
Verify: health 200; grep priority_claim=3; items 50; verdicts 50; assignment.yaml exists; heldout clean; transcripts gitignored (all checked individually, pass).

### Human decisions after T10 (partial)
- App DB migrated 0006 -> 0008 (`alembic upgrade head` in latam-cs-backend-1, human-authorized; environment setup, no new migration).
- B1 "Done when" phrase amended: the fixture has no Tuesday ~350 Super Ahorro charge; the proof uses "el cargo de Super Ahorro del jueves pasado por unos 790 mil" (persona CLI-M9B56QX9KMBU, row 2026-09-24 ~790000 COP). Human-approved.
- Keep regenerated `frontend/src/client/index.ts` and `sdk.gen.ts` (include the existing `test-idp/sessions` route; match the running API). Human-approved.

### T10 (rerun) — Live chat proofs (via `backend/scripts/chat_api.py`, real login, not the browser)
SC3 search: CLI-M9B56QX9KMBU "el cargo de Super Ahorro del jueves pasado por unos 790 mil" -> `ui transaction_list` 1 row `Super Ahorro · COP $787.390 · 24/09/2026 · •••• 2621`; `/pick 1` -> reply "...movimiento en Super Ahorro por COP $787.390 del 24/09/2026 ... fue una compra de Food por POS en Barranquilla" (no 409).
SC3 pending: CLI-001AVI5RHIYA (pt-BR) -> list of 2 pending/reversed; `/pick 2` -> "...Centro Comercial de COP $1.066.427 no dia 06/12/2025 ... Seu pagamento está em processo de confirmação... uma pessoa da equipe pode revisar". FINDING: `/pick 1` (Estabelecimento, mask •••• 0000, 18/03/2026) -> `error turn_failed`, backend `turn.failed error_type=NotFound` (tx_explain calls `get_card_details(tx.card_id)`, only `ToolUnavailable` caught). Also minor: `debug language=es` on pt turn; missing period before "Seu pagamento". Not fixed.
SC4: CLI-070BYEV7ZYHC claim+confirm -> `ui handoff_banner HO-6C85AD50 Reclamos`; `app.handoffs`: queue=reclamos reason=priority_claim; `bank.complaints` CLM-5904B87E priority=High origin=app (is_repeat_complainer NULL). `make demo-reset` run afterwards.
Deviations: pending proof via API, not browser UI.

### T4 repair 1 — pending pick on a non-card product
Root cause: CLI-001AVI5RHIYA's Pending row TRX-2GNKDRNJ0DQBCIEI8LEV sits on PRD-JOSIXQNH55XI (Cuenta Ahorro, not a card) -> `get_card_details` raises `NotFound`, uncaught in `explain_tx`; the "0000" mask came from `tx_option`'s `last4_by_card.get(..., "0000")` fallback.
Changed: `flows/tx_search.py` (new `card_mask_fact` -> `Fact | None`, catches `NotFound`; used by `_tx_details`; `tx_option` omits the mask when the product isn't a card), `flows/tx_explain.py` (uses `card_mask_fact`; no `card_mask` fact when None), `templates.py` (`goal_tx_explain` no longer prefixes "Tu movimiento está" before an already-full-sentence cause), `tests/unit/test_tx_explain_flow.py` (+1 regression test).
Not fixed (outside allowed files): (a) `debug language=es` on a pick turn is `runner.py` DebugInfo using the default language when no NLU runs (reply itself is pt); (b) missing period before "Seu pagamento" is the LLM's compose draft (`{tx_date} {tx_state_cause}` juxtaposed; `compose@v7.md`/compose.py), not a template join.
Verify: `pytest tests/unit/test_tx_search_flow.py tests/unit/test_tx_explain_flow.py -q` -> 7 passed; ruff clean; mypy 51 files no issues; lint-imports 4 kept. Live: both picks return replies; `make demo-reset` run.

### Human decisions after T4 repair 1
- Fixed (orchestrator, human-chosen): `runner.py` DebugInfo now reads `language` from the checkpointed final state, so a pick turn (no NLU) reports the conversation's language. Live: CLI-001AVI5RHIYA pt pick shows `debug language=pt`. ruff/mypy clean. `runner.py` edit → Dev A review.
- Known issues, not fixed (human chose): (a) compose draft joins `{tx_date}` and `{tx_state_cause}` without a period in pt/es; (b) `goal_tx_details` fallback template needs `{card_mask}`, so a non-card Approved row falls back to the generic `fallback` if the LLM draft fails grounding twice.

### Verification (V1–V5) merged
- PASS: V2 safety R1–R13 (R3 High read-back closed by V1's integration subset 7/7), V3 criteria (B1 rules, B2 ES/PT per flag, B4 rubric/items/assignment/verdicts, κ<0.6 rule, docs/contracts, client), V4 B3 screens + e2e + why-view on mocks, V5 live: search, both pending picks (pt, debug language=pt), priority_claim → Reclamos + complaints High, browser pending explained, logs clean, demo-reset.
- FAIL (not card-caused): `make check` frontend step — host has no npx; in-container biome: 47 CRLF format errors in files the card did not touch (card's 11 files pass).
- UNVERIFIABLE: full backend integration suite on Windows host (psycopg ProactorEventLoop); T11 agreement report (awaits labels).
- Open at commit: stray `frontend/openapi-ts-error-1790775270071.log`; `eval/reports/dev_proposed_20260930t133537/{meta,metrics,report}`; 13 client *.gen.ts EOL-only changes.
- For T11: agreement.py should refuse unfilled (null) labels and treat undefined κ as weak.
- Observations (pre-existing, not card): crypto.randomUUID crash over http; customer on /staff shows forbidden_role error; conversation lock released ~50 ms after `done` (409 on immediate next pick); no custom route spans in backend.

### Gate
- Human approved the verification gate (B1–B3 + B4 evidence). T11 pending human labels (with the two agreement.py fixes).
- Commit files: human selected none of the cleanup actions — leave the stray log, the eval report dir and the 13 EOL-only client files out of any commit and untouched.
