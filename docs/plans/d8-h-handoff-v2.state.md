# State: D8-H — Handoff v2: G10 handoff packet and staff screens
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D8-H (G10, owner A+B) · spec `docs/specs/d8-h-handoff-v2.md` · plan `docs/plans/d8-h-handoff-v2.md`
Branch `feat/d8-h-handoff-v2`, based on `develop` (1520f11).

## Conventions established for this card
- Leave the `07-execution-plan.md` edit, the untracked spec/plan and the line-ending-only diff on `frontend/src/lib/i18n/index.tsx` alone. Never edit `index.tsx`.
- No migration: `app.handoffs.claimed_at` already exists (head `0010_agent_cost.py`).
- The new packet field is `case_summary` (`HandoffDetail.summary` already exists).
- `EscalationPolicy` and `Resolution` are `extra="forbid"`, so the yaml key and the model field land together. `escalation.yaml` goes v7 → v8.
- Prompts: a new file `prompts/handoff_summary@v2.md`. Never edit v1 in place.
- Transcript reaches `handoff_summary` only via `config["configurable"]["transcript"]` (a session-bound loader injected by `runner.py`). Read it with `.get`; when it is absent or raises, use an empty transcript.
- The summary → packet hand-over is a plain dict (a dumped `CaseSummary`) in `GraphState.handoff_case_summary`.
- `GraphState` lives in `graph.py`, not `state.py`.
- `bank_tools` is absent in some unit configs: read it with `.get`.
- Test helpers are in `backend/tests/conftest.py` (`ScriptedLLM`, `RecordingAudit`, `make_session`). Fake LLM only.
- Integration tests and `make client` need `make up`. On this Windows host run integration tests inside `latam-cs-backend-1`: copy `backend/tests` to `/app/tests`, run `uv run --with pytest --with httpx python -m pytest tests/integration/<file> -q` from `/app`, then delete `/app/tests`. Host node is absent: frontend commands run in `latam-cs-frontend-1`.

## Human decisions taken mid-card
- T4: friction `clarifications` also counts the `understand` node (its clarification_failures bump and its own clarification_exhausted), not only wrapped flows and the agent. Spec amendment to D8.
- T5 (after live review of HO-A61DA319): the packet view shows only sections with content (no empty/"none" sections); supersedes "every null section renders a none text". EOL-only generated files and the route file are reverted.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | ab44255 | Schemas, history reads (handoffs + claims), Resolution.branch/flow, escalation.yaml v8, 04 updated; verify green |
| T2 | done | a090b6b | Draft is 4 required fields; GraphState.handoff_case_summary; 19 test files swept; 71 unit tests pass |
| T3 | done | ac0515f | handoff_summary@v2 over masked transcript, bounded placeholders, case_summary + fallback; 34 tests pass |
| T4 | done | a82e517 | Packet v2 code fields (focus card, routing, risk, history, friction); friction counter + return_to_bot reset; 18 tests pass; understand counted (degraded path), 20 pass |
| T5 | done | a090579 | Client regen, inbox preview + queue clock, packet view redesign, 25 i18n keys; integration 3 passed in backend container (host Windows Redis/Proactor issue) |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — Widen summary draft and graph channel
Changed: `handoff_summary.py` (`HandoffSummaryDraft` gains required `asked`, `did`, `unfinished`); `graph.py` (`GraphState.handoff_case_summary: NotRequired[dict[str, str] | None]`); 19 test files' draft constructors (`asked="Pidió ayuda.", did="Nada.", unfinished="Todo."`).
Facts the next tasks need: node still uses only `request`; ruff format applied to the touched test files.
Deviations: none.
Verify: 14 unit files → 71 passed; ruff check + format --check clean.

### T1 — Contracts, history reads and escalation policy v8
Created: none. Changed: `handoff/{schemas,repository,service}.py`, `disputes/{repository,service}.py`, `policy/escalation.py`, `policies/escalation.yaml` (v8), `04-contracts.md` (§3, §4, §5).
Facts the next tasks need: `Resolution` now requires `branch` and `flow`; `flow` is set only for `by_flow` (None for rule/flow/default). `repository.fetch_customer_handoffs` returns `list[HandoffDetail]`; `service.customer_history(customer_id, exclude_conversation_id, days, limit=5)`. `PastClaim` lives in `handoff/schemas.py`; `disputes.service.recent_claims` imports it from there. `HandoffSummary` now requires `request`, `case_summary`, `claimed_at` (callers/tests constructing it must pass them). `EscalationPolicy.handoff_packet.history_days`.
Deviations: none.
Verify: policy assert ok; `pytest tests/unit/test_policy_registry.py` 2 passed; lint-imports 4 kept; mypy, ruff check, ruff format clean.

### T1 — Contracts, history reads and escalation policy v8
Created: none. Changed: `handoff/{schemas,repository,service}.py`, `disputes/{repository,service}.py`, `policy/escalation.py`, `policies/escalation.yaml` (v8), `04-contracts.md` (§3, §4, §5).
Facts the next tasks need: `Resolution` now requires `branch` and `flow`; `flow` is set only for `by_flow` (None for rule/flow/default). `repository.fetch_customer_handoffs` returns `list[HandoffDetail]`; `service.customer_history(customer_id, exclude_conversation_id, days, limit=5)`. `PastClaim` lives in `handoff/schemas.py`; `disputes.service.recent_claims` imports it from there. `HandoffSummary` now requires `request`, `case_summary`, `claimed_at` (callers/tests constructing it must pass them). `EscalationPolicy.handoff_packet.history_days`.
Deviations: none.
Verify: policy assert ok; `pytest tests/unit/test_policy_registry.py` 2 passed; lint-imports 4 kept; mypy, ruff check, ruff format clean.

### T3 — handoff_summary@v2
Created: `prompts/handoff_summary@v2.md`, `tests/unit/test_handoff_summary_v2.py`, `tests/fixtures/handoff_ho293fb42e.json`.
Changed: `nodes/handoff_summary.py` (transcript loader, `{tx_count}`/`{plan_card_mask}`, 4-field validation, returns `handoff_case_summary` dict), `baseline/template_compose.py` (`handoff_case_summary: None`), `runner.py` (`configurable["transcript"]`).
Facts the next tasks need: message roles are `"customer"`/`"bot"`; every non-success path returns `handoff_case_summary: None`; the `handoff` node should read `state.get("handoff_case_summary")`.
Deviations: none.
Verify: 4 test files → 34 passed; ruff check + format --check clean (mypy on the node clean).

### T4 — Packet v2 code-built fields
Changed: `nodes/handoff.py` (focus_card via `get_card_details`, routing, risk snapshot, history, friction, case_summary), `tools/handoff.py` (`history`), `state.py` (`friction`), `graph.py` (`_bump_friction`, `_clarified`, `_count_clarifications` on `agent`; non_answers/clarifications counted in `_keep_open_question`, abstentions in `_segment_update("abstain")`), `takeover.py` (zeroes friction), `test_handoff_packet.py` (2 tests).
Facts the next tasks need: `understand`'s own clarification_failures are not counted (spec names flows/agent only); friction is a plain dict channel, whole value per update.
Deviations: none.
Verify: 18 passed; ruff check + format --check clean.

### T4 follow-up — count `understand` clarifications
Changed: `graph.py` (`understand` node wrapped in `_count_clarifications`, also covers the baseline); `test_handoff_packet.py` (degraded ambiguous turn → `friction.clarifications == 1`).
Facts: the ambiguity counter exists only in `understand`'s classifier path (degraded turn); the LLM path never raises `clarification_failures`. No double count: `understand` and flows/agent are separate nodes.
Verify: handoff_packet + non_answer + block_flows + graph → 20 passed; ruff check + format --check clean.

### T5 — Staff API proof, client, inbox preview and packet view
Changed: `test_staff_round_trip.py` (`test_handoff_claim_chat_return`: inbox row `request`/`case_summary`/`claimed_at` null→set, `404` on queued transcript); `frontend/src/client/*` (regenerated); `InboxList.tsx` (preview + ticking clock); `PacketView.tsx` (summary, focus card, routing, risk, history, friction, conversation link); `es.json`/`pt.json` (25 keys each). `handoffs.$handoffId.tsx` unchanged (already lays packet beside `AgentChat`).
Facts: host has no node; client generated in the frontend container: `docker exec latam-cs-frontend-1 npx @hey-api/openapi-ts -i http://nginx/api/v1/openapi.json`. Host pytest needs `REDIS_URL=redis://127.0.0.1:6379/0` (localhost ping times out) and a Selector event loop on Windows (psycopg pool).
Deviations: none.
Verify: typecheck + biome clean, mypy/lint-imports green; integration: my new asserts pass, but `test_handoff_claim_chat_return` fails at step 7 (bot answer after return; mode stays human) on this host, apparently pre-existing; other 2 tests pass.

### T5 follow-up — integration verify in the Linux container
Facts: step 7 failure was a Windows-host artifact (Selector-loop hack / host Redis), not this card. In `latam-cs-backend-1` (live branch code, tests copied to `/app/tests`, removed after): `uv run --with pytest --with httpx python -m pytest tests/integration/test_staff_round_trip.py -q` → 3 passed. Recipe: `docker cp backend/tests latam-cs-backend-1:/app/tests` (needs `/app/tests` for the alembic cwd), run from `/app`.
Deviations: none; no code changed.

### T5 follow-up 2 — hide empty packet sections, revert EOL-only files
Human decision (supersedes the T5 acceptance line "every null section renders a none text"): `PacketView.tsx` renders no section, heading included, when it has no content. Only non-empty signals/counters/sublists are listed; routing shows always when set (flow only if set); case_summary skips empty fields, `request` only when it is null. i18n: removed `staff.packet.yes`/`no` (es+pt); `staff.packet.none` kept (TurnTimeline uses it).
Changed: `PacketView.tsx` rewritten; restored 13 EOL-only `client/{client.gen,client/*,core/*}` files and `handoffs.$handoffId.tsx` from the index. `index.tsx` untouched.
Verify: container `npm run typecheck` clean; biome check on 4 files clean; `git diff --stat develop -- frontend` equals the `--ignore-cr-at-eol` one (7 files).
