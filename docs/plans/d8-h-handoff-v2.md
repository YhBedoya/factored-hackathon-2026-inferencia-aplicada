# Plan: D8-H — Handoff v2: G10 handoff packet and staff screens

Spec: [`docs/specs/d8-h-handoff-v2.md`](../specs/d8-h-handoff-v2.md) · Branch: `feat/d8-h-handoff-v2`

Freeze: merged before 2026-10-04 18:00 or dropped. Five tasks in three waves.

## Facts checked against the repo

**Branch and working tree**
- `feat/d8-h-handoff-v2` is at `1520f11`, the same commit as `develop` and `main`. The working tree already has the spec (untracked), a `07-execution-plan.md` edit and a line-ending-only diff on `frontend/src/lib/i18n/index.tsx`. Leave all three alone, and don't edit `index.tsx`.
- No migration. `app.handoffs.claimed_at` already exists (`backend/app/alembic/versions/0005_handoffs_staff.py:73`). The alembic head is `0010_agent_cost.py`.

**Handoff domain** (`backend/app/domains/handoff/`)
- `schemas.py`: `_Frozen` is `ConfigDict(frozen=True, extra="forbid")`. `HandoffPacket.request` is `Field(max_length=200)`. `HandoffSummary` has no `request`, `case_summary` or `claimed_at` today. `HandoffDetail.summary` is the `HandoffSummary`, which is why the new field is called `case_summary`.
- `repository.py`: `_SELECT_SQL` selects `h.id, conversation_id, queue, reason, priority, status, agent_id, created_at, packet, a.display_name AS claimed_by`, without `claimed_at`. `_detail(row)` builds `HandoffSummary` from the row plus `packet.language`. `HandoffSummary(` is built only there.
- `service.py`: `_publish(event, summary)` sends `summary.model_dump(mode="json")` on `handoff:<queue>`, so the SSE events widen with the schema and need no code change. The staff routes in `backend/app/api/v1/staff.py` return `service.list_handoffs` / `HandoffDetail` unchanged. The messages route already depends on `get_claimed_conversation` (`staff.py:247-249`), so `staff.py` needs no edit.
- `handoff` may import `disputes.service`, because the import-linter only restricts `app.domains.conversation`. The edge `conversation.tools.handoff -> handoff.service` is in `backend/.importlinter` `ignore_imports`, so a new `handoff.service -> disputes.service` edge stays legal.

**Disputes domain**
- `disputes/repository.py` reads `bank.complaints` (see `fetch_claims_by_ids`, `fetch_priority_signals`). It maps backend failures to `ToolUnavailable`. Columns include `complaint_id`, `customer_id`, `category`, `status`, `creation_date`.
- `disputes/service.py` exports `create_claims`, `get_claims` and `priority_signals`. `recent_claims` is new.

**Policy**
- `policies/escalation.yaml` is `version: 7`. `human_request_queues: {default: atencion, by_flow: {unrecognized_charge: fraudes}}`.
- `backend/app/domains/policy/escalation.py`: `EscalationPolicy` has `extra="forbid"`, so the yaml key and the model field must land together. `Resolution{reason, queue, priority}` also has `extra="forbid"`.
- `resolve_escalation` has four branches. The reason in state uses the state queue (a flow set it) or the rule's queue. For `_FLOW_ROUTED_REASONS = ("tool_failure", "llm_unavailable")` with a null rule queue it routes like a human request. Then come `legal_hit(text)` (rule queue) and the `human_request` intent (`by_flow.get(pending_flow, default)`).
- A `pending_flow` that is not a key of `by_flow` gets the default queue. That is branch `default`, not `by_flow`.
- Callers: `nodes/handoff.py`, `nodes/handoff_summary.py`, `nodes/route.py`, `baseline/template_compose.py`. All of them read only `.reason`, `.queue` and `.priority`, so the new fields don't break them.
- No unit test pins `escalation.yaml`'s version or hash (`test_policy_registry.py` only checks the `sha256:` prefix).

**Conversation: summary node** (`nodes/handoff_summary.py`)
- `HandoffSummaryDraft{request}` has `extra="forbid"`. `_PROMPT = PromptRef("handoff_summary", 1)`. `_FALLBACK[reason][language]` holds the fixed texts.
- The node writes graph-local `handoff_request`. `GraphState` (in `graph.py`, not `state.py`) declares `handoff_request: NotRequired[str]` at about line 235.
- The degraded path calls `baseline.template_compose.baseline_handoff_summary`, which returns `{"handoff_request": _fallback(...)}`.
- `HandoffSummaryDraft(request=...)` is constructed in **19 test files**: unit `test_agent_confirmation, test_agent_fallbacks, test_analytics_segments, test_block_flows, test_dispute_flows, test_escalation_rules, test_faults, test_graph, test_handoff_packet, test_non_answer, test_priority_flags, test_r3_flows, test_replacement_multi, test_sandbox_conversations`, and integration `test_analytics_worker, test_privacy_ledger, test_staff_round_trip, test_turn_caps, test_write_path_api`.
- `ScriptedLLM` (`backend/tests/conftest.py:100`) returns scripted objects as is, without validating them. A draft with required new fields therefore breaks every one of those constructors.
- Prompts are `prompts/<name>@v<n>.md`, loaded by `load_prompt(PromptRef)`. A wording change means a new file, never an in-place edit. `handoff_summary@v1.md` is the analogue for v2.

**Conversation: transcript source**
- `store.list_messages(conversation_id) -> list[MessageRow]` (`conversation/store.py:172`) returns rows oldest first with `role, turn_id, content` (decrypted raw), `content_masked`, `ui_payload` and `created_at`.
- `ui_payload` is the list `[event.model_dump(mode="json")]` the runner stores on bot rows (`runner.py:515`).
- A `confirm` event is `{"kind": "confirm", "payload": {"token_id", "steps": [{"tool", "summary_key", "facts": [{"key", "value", "source"}]}], "labels"}}`.
- In `unrecognized_charge` the plan steps carry `Fact(key="card_mask", value=mask_card(last4))`, already shaped like `•••• 9118`, and `Fact(key="tx_count", value=<int>)` (`flows/unrecognized_charge.py:362-364`).
- Unit tests have no DB, and the graph is also run from `conversation/sandbox.py` with no messages. **Plan choice (mechanism, not behaviour):** the runner injects a session-bound async loader as `config["configurable"]["transcript"]` (`functools.partial(store.list_messages, conversation_id)`, next to `"handoff_tools"` in `runner.py:361-372`). `handoff_summary` reads it with `.get`. If it is absent or raises, the node uses an empty transcript, and only `{queue_label}` / `{card_mask}` / evidence `{tx_count}` stay on offer. This keeps the node off the DB in unit tests and keeps `store` out of an LLM node.

**Conversation: packet node and state**
- `nodes/handoff.py` is code-only (R6). It calls `resolve_escalation`, builds `HandoffPacket`, then returns `priority_flags: []`. It does not reset `unauthorized_attempts` today; `return_to_bot` does.
- Snapshot `priority_flags` and `unauthorized_attempts` from the incoming state, before the return dict.
- Focus card: `configurable["bank_tools"].get_card_details(state["selected_card_id"])`, then `f"{kind_label(details.<kind>, lang)} {mask_card(details.last4)}"`, using `kind_label` and `mask_card` from `app.domains.localization.format`. The `bank_tools` key is absent in some unit configs, so read it with `.get`.
- `legal_hit(text, policy)` lives in `policy/escalation.py`.
- `tools/handoff.py`: `HandoffTools` Protocol, `InMemoryHandoffTools` and `ServiceHandoffTools(ctx)`. The only other implementer is `_ExistingHandoffTools(InMemoryHandoffTools)` in `test_handoff_packet.py`, which inherits.
- Friction counters:
  - `clarification_failures` is set inside every flow in `flows/*.py` and in `agent/node.py`. `non_answer_failures` is set in `graph.py::_keep_open_question` and `agent/confirm.py`.
  - Wrapper nesting in `build_graph`: a flow node is `_track_segments(name, _keep_open_question(name, _guard_access(flow)))`, and `abstain` is `_track_segments("abstain", ...)`.
  - When clarification is exhausted, a flow returns `escalation_reason: "clarification_exhausted"` with `clarification_failures: 0`. The second non-answer in `_keep_open_question` also returns `clarification_exhausted` with `non_answer_failures: 0`. A "new > old" diff alone therefore misses the exhausting step.
- `takeover.py::return_to_bot` resets the handoff channels in one `aupdate_state` dict (`takeover.py:73-90`).

**Tests and commands**
- Unit-test harness helpers live in `backend/tests/conftest.py`: `ScriptedLLM`, `RecordingAudit`, `make_session`, `fakebank_dir`, and the monkeypatch pattern for `runner.store` / `events` / `get_redis` at about lines 370-392.
- Graph-driving analogues: `tests/unit/test_non_answer.py` and `tests/unit/test_block_flows.py`.
- The R6 guard is `tests/unit/test_r6_no_write_tools_in_llm_nodes.py`.
- Integration tests use FastAPI `TestClient` against `make up`'s Postgres/Redis: `cd backend && uv run pytest tests/integration/<file> -q`.
- `make client` = `cd frontend && npx @hey-api/openapi-ts`, which reads `http://localhost/api/v1/openapi.json`, so the dev stack must be up with the new backend code. It writes `frontend/src/client/`.
- Frontend checks: `cd frontend && npm run typecheck` (whole app) and `npx biome check <paths>`.
- i18n keys live in `frontend/src/lib/i18n/{es,pt}.json` (`staff.inbox.*`, `staff.packet.*`, `staff.detail.*`).
- Fixture dir: `backend/tests/fixtures/` (holds `fakebank/`).

## Components

1. **Contracts, data and policy (backend, below conversation).**
   - `handoff/schemas.py` (new models, widened `HandoffPacket` and `HandoffSummary`).
   - `handoff/repository.py` (summary fields, `customer_history` query over `app.handoffs ⋈ app.conversations`) and `handoff/service.py` (`customer_history`).
   - `disputes/repository.py` + `disputes/service.py` (`recent_claims`).
   - `policy/escalation.py` (`Resolution.branch/flow`, `HandoffPacketPolicy`) and `policies/escalation.yaml` v8.
   - `docs/solution-docs/04-contracts.md` §3, §4, §5.
   - Depends on nothing.
2. **Draft contract widening (conversation).** `HandoffSummaryDraft` gains `asked/did/unfinished`. `GraphState` gains `handoff_case_summary`. The mechanical sweep goes through the 19 test files. Depends on nothing.
3. **Summary v2 (LLM node).**
   - `nodes/handoff_summary.py` covers the transcript, the placeholders, the four-field validation and the fallback, and adds `prompts/handoff_summary@v2.md`.
   - `baseline/template_compose.py` makes the degraded path return a null summary, and `runner.py` injects the transcript loader.
   - New `tests/unit/test_handoff_summary_v2.py` + a masked fixture.
   - Depends on 1 (`CaseSummary`) and 2 (draft, channel).
4. **Packet v2 code fields (code-only node).**
   - `nodes/handoff.py`: focus card, routing, risk snapshot, history, friction, case summary into the packet.
   - `tools/handoff.py`: `history()`.
   - `state.py`: `friction`. `graph.py`: friction increments. `takeover.py`: clear friction.
   - Tests in `test_handoff_packet.py`.
   - Depends on 1 (schemas, policy, `service.customer_history`) and 2 (channel, swept test file).
5. **Staff API proof + client + screens.**
   - Extend `tests/integration/test_staff_round_trip.py` (H2).
   - `make client`.
   - `InboxList.tsx`, `PacketView.tsx`, `handoffs.$handoffId.tsx`, i18n.
   - Depends on 1-4, and needs the running stack.

## Build order

1. **T1 ∥ T2.** T1 fixes the shapes every other task imports: `CaseSummary`, `Routing`, `Resolution.branch`, `policy.handoff_packet`, `service.customer_history`. T2 makes the draft four-field before anyone writes v2 logic, and does the 19-file sweep once. That way no later task's test run races against a half-swept draft. Their files are disjoint.
2. **T3 ∥ T4.** T3 writes `handoff_case_summary` and T4 reads it, through the channel T2 already declared. Neither edits the other's files. T4's routing and history need T1, and T3's `CaseSummary` needs T1.
3. **T5 alone.** The client must be regenerated from the final backend (after T1 widens `HandoffSummary`/`HandoffPacket`). The integration test exercises the full handoff (T3 + T4). Both need the dev stack up.

## Touch map

| File | New / modified | Change | Task |
|---|---|---|---|
| `backend/app/domains/handoff/schemas.py` | modified | `CaseSummary, Routing, RiskSignals, PastHandoff, PastClaim, CustomerHistory, Friction`; six optional packet fields; `HandoffSummary += request, case_summary, claimed_at`; docstring "only LLM-written" updated | T1 |
| `backend/app/domains/handoff/repository.py` | modified | `_SELECT_SQL` adds `h.claimed_at`; `_detail` fills the 3 summary fields; new `fetch_customer_handoffs(customer_id, exclude_conversation_id, since, limit)` | T1 |
| `backend/app/domains/handoff/service.py` | modified | `customer_history(customer_id, exclude_conversation_id, days, limit) -> CustomerHistory` | T1 |
| `backend/app/domains/disputes/repository.py` | modified | `fetch_recent_claims(customer_id, since, limit)` | T1 |
| `backend/app/domains/disputes/service.py` | modified | `recent_claims(customer_id, since, limit) -> list[PastClaim]` | T1 |
| `backend/app/domains/policy/escalation.py` | modified | `Resolution += branch, flow`; `resolve_escalation` sets them; `EscalationPolicy += handoff_packet: HandoffPacketPolicy{history_days}` | T1 |
| `policies/escalation.yaml` | modified | `version: 8`, `handoff_packet: {history_days: 90}` | T1 |
| `docs/solution-docs/04-contracts.md` | modified | §3 `HandoffSummary` shape; §4 new fields + "only LLM-written" sentence; §5 escalation.yaml v8 header + key | T1 |
| `backend/app/domains/conversation/nodes/handoff_summary.py` | modified | T2: draft fields. T3: v2 logic, `_PROMPT` v2, transcript, placeholders, validation, `handoff_case_summary` on every return | T2, T3 |
| `backend/app/domains/conversation/graph.py` | modified | T2: `GraphState.handoff_case_summary` (dumped `CaseSummary` dict). T4: friction increments in the wrappers | T2, T4 |
| 19 test files listed in Facts | modified | add `asked=…, did=…, unfinished=…` to each `HandoffSummaryDraft(...)` | T2 |
| `backend/app/domains/conversation/prompts/handoff_summary@v2.md` | new | v2 prompt, ES + PT examples, placeholder rules, data fence | T3 |
| `backend/app/domains/conversation/baseline/template_compose.py` | modified | `baseline_handoff_summary` also returns `handoff_case_summary: None` | T3 |
| `backend/app/domains/conversation/runner.py` | modified | `"transcript": functools.partial(store.list_messages, conversation_id)` in `configurable` | T3 |
| `backend/tests/fixtures/handoff_ho293fb42e.json` | new | hand-written masked transcript rows of the motivating case | T3 |
| `backend/tests/unit/test_handoff_summary_v2.py` | new | 5 tests | T3 |
| `backend/app/domains/conversation/nodes/handoff.py` | modified | focus card, routing, risk, history, friction, `case_summary` | T4 |
| `backend/app/domains/conversation/tools/handoff.py` | modified | `history(days)` on Protocol, InMemory, Service | T4 |
| `backend/app/domains/conversation/state.py` | modified | `friction: NotRequired[dict[str, int]]` | T4 |
| `backend/app/domains/conversation/takeover.py` | modified | `return_to_bot` sets `friction` to zeros | T4 |
| `backend/tests/unit/test_handoff_packet.py` | modified | T2: sweep. T4: 2 new tests | T2, T4 |
| `backend/tests/integration/test_staff_round_trip.py` | modified | T2: sweep. T5: H2 asserts | T2, T5 |
| `frontend/src/client/*` | regenerated | `make client` | T5 |
| `frontend/src/components/staff/InboxList.tsx` | modified | summary preview + running time in queue | T5 |
| `frontend/src/components/staff/PacketView.tsx` | modified | redesign: summary, focus card, routing, risk, history, friction, conversation link; fall back to `request` | T5 |
| `frontend/src/routes/staff/handoffs.$handoffId.tsx` | modified | layout: packet view next to the conversation | T5 |
| `frontend/src/lib/i18n/es.json`, `pt.json` | modified | new `staff.packet.*` / `staff.inbox.*` keys | T5 |

Outside the spec's touch map are `runner.py` (one config line, the transcript loader) and the 19-file draft sweep. Both are forced by the contracts the spec defines.

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| Requiring the three new draft fields breaks 19 test files, and parallel tasks race on them | T2 sweeps them once, in W1, before any v2 logic exists. W2 tasks then see a stable draft. |
| The summary node reads the DB in unit tests (no DB) or imports `store` into an LLM node | The transcript arrives as an injected `configurable["transcript"]` loader. Absent or failing → empty transcript (T3). |
| Raw customer text reaches the LLM (R5) | T3 reads only `content_masked` and skips rows where it is null. `test_r5_only_masked_text_sent` puts a name in `content` and asserts it is absent from `llm.calls[0].user`. |
| `{tx_count}` offered with a meaningless 0 (the HO-293FB42E bug) | T3 offers `{tx_count}` only from non-empty evidence or from the last unanswered confirm's `tx_count` fact. The regression assert is in `test_replay_ho293fb42e_es`. |
| LLM writes a digit or a stray brace in `asked/did/unfinished` (R4) | T3 validates all four fields with the existing rule. Any failure → fixed `request` + `case_summary=None`, with no second call (R11). `test_r4_raw_digit_falls_back`, `test_r11_llm_error_one_call`. |
| A filled field exceeds 280 or 200 chars, and `CaseSummary` raises `ValidationError` inside the handoff | T3 cuts each field after filling, the way `request[:200]` already does. A summary must never block the handoff. |
| `handoff_summary` gains a tool or token (R6) | T3 adds no write/handoff tool. `test_r6_no_write_tools_in_llm_nodes.py` + `test_graph.py` run in T3's Verify. |
| History read fails, or reads another customer (R1) | T4: `HandoffTools.history(days)` has no customer parameter. `ServiceHandoffTools` passes `self._ctx.customer_id` and `self._ctx.conversation_id`, and the node wraps the call so `history=None` on any exception. `test_r1_history_session_bound`, `test_packet_v2_code_fields`. |
| History SQL (`app.handoffs ⋈ app.conversations`, `bank.complaints`) only runs live | T1 maps failures to `ToolUnavailable`. The verifier's live replay asserts `history` non-null (criterion 4). T5's integration run exercises the handoff path end to end on the real DB. |
| Friction double-counts (nested wrappers) or misses the exhausting step (counter reset to 0) | T4 counts at one level: non-answers where `_keep_open_question` detects them (replay and hand-off branches), clarifications by update-vs-state diff plus a flow's `clarification_exhausted`, and abstain in `_track_segments("abstain")`. The test drives two flows and asserts exact counts. |
| Packet friction reset by a flow or by `load_session` | T4 adds `friction` to no reset path except `return_to_bot`. The test asserts it survives across two flows. |
| Stored v1 packets stop validating | T1 gives every new packet field a `None` default. `HandoffSummary.request` comes from `packet.request`, which exists on every stored packet. |
| `escalation.yaml` key added without the model field (`extra="forbid"`) or the reverse | Both are in T1, which checks with a `load_escalation_policy()` assert. |
| Client regenerated against a stale backend | T5 runs alone after T1-T4, with the stack up (hot reload). Verify greps the new types in `types.gen.ts`. |
| UI crashes on old packets with null fields | T5: every new section renders "none" on `null`, and the summary area falls back to `request` (AS9). |

## Tests

| Test (spec) | Task |
|---|---|
| `unit/test_handoff_summary_v2.py::test_replay_ho293fb42e_es` | T3 |
| `unit/test_handoff_summary_v2.py::test_pt_happy_path` | T3 |
| `unit/test_handoff_summary_v2.py::test_r4_raw_digit_falls_back` | T3 |
| `unit/test_handoff_summary_v2.py::test_r5_only_masked_text_sent` | T3 |
| `unit/test_handoff_summary_v2.py::test_r11_llm_error_one_call` | T3 |
| `unit/test_graph.py` (existing R6 check, run, not extended unless it misses the node) | T3 (Verify) |
| `unit/test_handoff_packet.py::test_packet_v2_code_fields` | T4 |
| `unit/test_handoff_packet.py::test_r1_history_session_bound` | T4 |
| `integration/test_staff_round_trip.py` (extend: H2 fields + `404` unclaimed) | T5 |
| Live replay, real model (verifier) | verifier, on T1-T5 |
| Browser check ES + PT (verifier) | verifier, on T5 |

Success criteria coverage:
- Criterion 1: T3 + T4.
- Criterion 2: the verifier's `make check`.
- Criterion 3: T5.
- Criterion 4: the verifier, using T1/T3/T4.
- Criterion 5: the verifier, using T5.
- Criterion 6: T1.

## Tasks

- [ ] T1: Contracts, history reads and escalation policy v8 (handoff + disputes + policy domains, `04` doc)
  - Depends on: nothing
  - Read exactly these: spec `docs/specs/d8-h-handoff-v2.md` §"Contracts", D5-D7, D9; `backend/app/domains/handoff/repository.py` (`_SELECT_SQL`, `_detail`, `list_handoffs` as the query analogue); `backend/app/domains/policy/escalation.py` (`Resolution`, `resolve_escalation`)
  - Acceptance:
    - **Schemas** (`handoff/schemas.py`): `CaseSummary`, `Routing`, `RiskSignals`, `PastHandoff`, `PastClaim`, `CustomerHistory` and `Friction` exist exactly as in the spec's "Contracts" block, all `_Frozen`, and are exported in `__all__`.
      - `HandoffPacket` gains `case_summary, focus_card, routing, risk, history, friction`, each defaulting to `None`. A v1 packet dict (no new keys) still validates.
      - `HandoffSummary` gains `request: str`, `case_summary: CaseSummary | None`, `claimed_at: datetime | None`.
      - The `HandoffPacket` docstring says `request` and `case_summary` are the LLM-written fields.
    - **Repository:**
      - `_SELECT_SQL` selects `h.claimed_at`. `_detail` fills `request=packet.request`, `case_summary=packet.case_summary`, `claimed_at=row["claimed_at"]`.
      - New `fetch_customer_handoffs(customer_id, exclude_conversation_id, since, limit)` reads `app.handoffs h JOIN app.conversations c ON c.id = h.conversation_id WHERE c.customer_id = :customer_id AND h.conversation_id <> :exclude AND h.created_at >= :since ORDER BY h.created_at DESC LIMIT :limit`. It maps errors to `ToolUnavailable`.
    - **Handoff service:** `customer_history(customer_id, exclude_conversation_id, days, limit=5) -> CustomerHistory` builds `PastHandoff`s (with `reference_for(id)`) and calls `disputes.service.recent_claims(customer_id, since, limit)`.
    - **Disputes:** `repository.fetch_recent_claims` and `service.recent_claims -> list[PastClaim]` read `bank.complaints` for the customer, newest first, at most `limit`, with `creation_date >= since`. They are customer-scoped (R1).
    - **Escalation:**
      - `Resolution` gains `branch: Literal["rule","flow","by_flow","default"]` and `flow: str | None`.
      - `resolve_escalation` sets them:
        - `flow` when a reason in state comes with a queue from state.
        - `rule` when the queue comes from `rules.<reason>.queue`, legal keyword included.
        - `by_flow` when the queue came from a `human_request_queues.by_flow` entry, with `flow=pending_flow`.
        - `default` otherwise, with `flow=None`.
      - `EscalationPolicy` gains `handoff_packet: HandoffPacketPolicy{history_days: int}`.
    - **`policies/escalation.yaml`:** `version: 8` and `handoff_packet: {history_days: 90}`.
    - **`04-contracts.md`:** §3 `HandoffSummary` lists the three new fields. §4 lists the six packet fields and says "`request` and `case_summary` are the only LLM-written fields". §5's escalation.yaml header reads v8 (D8-H adds `handoff_packet`) and shows the key.
  - Verify: `cd backend && uv run python -c "from app.domains.policy.escalation import load_escalation_policy as l; p=l(); assert p.version==8 and p.handoff_packet.history_days==90" && uv run pytest tests/unit/test_policy_registry.py -q && uv run lint-imports && uv run mypy app/domains/handoff app/domains/disputes app/domains/policy && uv run ruff check app/domains/handoff app/domains/disputes app/domains/policy && uv run ruff format --check app/domains/handoff app/domains/disputes app/domains/policy`
  - Files: `backend/app/domains/handoff/schemas.py`, `backend/app/domains/handoff/repository.py`, `backend/app/domains/handoff/service.py`, `backend/app/domains/disputes/repository.py`, `backend/app/domains/disputes/service.py`, `backend/app/domains/policy/escalation.py`, `policies/escalation.yaml`, `docs/solution-docs/04-contracts.md`

- [ ] T2: Widen the summary draft and graph channel, and sweep the draft constructors in tests
  - Depends on: nothing
  - Read exactly these: `backend/app/domains/conversation/nodes/handoff_summary.py` (`HandoffSummaryDraft`); `backend/app/domains/conversation/graph.py` `GraphState` (the `handoff_request` line); spec §"Contracts" → "LLM step"
  - Acceptance:
    - `HandoffSummaryDraft` is `{request: str, asked: str, did: str, unfinished: str}`, all required, still `extra="forbid"`. The node's behaviour is unchanged in this task: it still uses only `request`.
    - `GraphState` declares `handoff_case_summary: NotRequired[dict[str, str] | None]`. The value is a `CaseSummary.model_dump()` (`{asked, did, unfinished}`) or `None`. It is a plain dict on purpose: LangGraph resolves `GraphState` hints at runtime, so no forward reference, and this task doesn't depend on T1. Add a one-line comment: written by `handoff_summary` (dumped `CaseSummary`), read and re-validated by `handoff`.
    - Every `HandoffSummaryDraft(...)` in the 19 test files listed under Files gains digit-free, brace-free `asked="…", did="…", unfinished="…"` arguments (e.g. `asked="Pidió ayuda.", did="Nada.", unfinished="Todo."`). No other test change.
  - Verify: `cd backend && uv run pytest tests/unit/test_agent_confirmation.py tests/unit/test_agent_fallbacks.py tests/unit/test_analytics_segments.py tests/unit/test_block_flows.py tests/unit/test_dispute_flows.py tests/unit/test_escalation_rules.py tests/unit/test_faults.py tests/unit/test_graph.py tests/unit/test_handoff_packet.py tests/unit/test_non_answer.py tests/unit/test_priority_flags.py tests/unit/test_r3_flows.py tests/unit/test_replacement_multi.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check app/domains/conversation/nodes/handoff_summary.py app/domains/conversation/graph.py tests/unit tests/integration && uv run ruff format --check app/domains/conversation/nodes/handoff_summary.py app/domains/conversation/graph.py tests/unit tests/integration`. The 5 integration files are only lint-checked here; T5 runs the round trip.
  - Files: `backend/app/domains/conversation/nodes/handoff_summary.py`, `backend/app/domains/conversation/graph.py`, `backend/tests/unit/{test_agent_confirmation,test_agent_fallbacks,test_analytics_segments,test_block_flows,test_dispute_flows,test_escalation_rules,test_faults,test_graph,test_handoff_packet,test_non_answer,test_priority_flags,test_r3_flows,test_replacement_multi,test_sandbox_conversations}.py`, `backend/tests/integration/{test_analytics_worker,test_privacy_ledger,test_staff_round_trip,test_turn_caps,test_write_path_api}.py` (mechanical sweep; 2 source files)

- [ ] T3: `handoff_summary@v2`: masked transcript, bounded placeholders, case summary with one-call fallback
  - Depends on: T1 (`CaseSummary` in `app.domains.handoff.schemas`); T2 (four-field `HandoffSummaryDraft`, `GraphState.handoff_case_summary`)
  - Read exactly these: spec §"Decisions" D1-D4 and §"Test list" (the 5 `test_handoff_summary_v2.py` rows); `backend/app/domains/conversation/nodes/handoff_summary.py`; `backend/tests/unit/test_handoff_packet.py` (`test_summary_fallback`, as the fake-LLM test analogue)
  - Acceptance:
    - **Transcript:** `_PROMPT = PromptRef("handoff_summary", 2)`. The node takes the transcript from `config["configurable"].get("transcript")`, an async callable returning `MessageRow`s. If it is absent or raises → `[]`.
      - It uses the last 30 rows, oldest first, and only `content_masked`, each cut to 500 chars. It skips rows whose `content_masked` is empty. It never reads `.content`.
    - **Placeholders**, offered only when there is a value (AS3):
      - `{queue_label}` always.
      - `{card_mask}` from the selected card, the existing logic.
      - `{tx_count}`: `len(handoff_evidence)` when evidence is non-empty, else the `tx_count` step fact of the **last unanswered confirm**.
      - `{plan_card_mask}`: the `card_mask` step fact of that confirm.
      - "Last unanswered confirm" follows D3. Take the last bot row whose `ui_payload` has a `kind == "confirm"` event. It is answered if any later bot row's `turn_id` has no customer row with the same `turn_id`.
    - **User message** (R6): language, reason, queue, the placeholder keys on offer, and the transcript as `role: masked text` lines, all inside one fenced block. `prompts/handoff_summary@v2.md` (new) says this, gives ES and PT examples, and bans digits outside placeholders.
    - **Validation and fill:**
      - The unknown-placeholder / brace-residue / raw-digit check runs on **all four** draft fields. Any failure, or `LLMError` → `handoff_request` = fixed per-reason text, `handoff_case_summary = None`, and no second call (R11).
      - Keep the existing degraded and classifier branches. On success, fill the placeholders in code, cut `request` to 200 and each case field to 280, and return `{"handoff_request": ..., "handoff_case_summary": CaseSummary(...).model_dump()}`. The channel is a plain dict (T2).
      - The `LLM_DISABLED`, degraded and `resolution is None` paths all return `handoff_case_summary: None`.
    - **Degraded path:** `baseline_handoff_summary` in `template_compose.py` also returns `handoff_case_summary: None`.
    - **Runner:** `runner.py` adds `"transcript": functools.partial(store.list_messages, conversation_id)` to `configurable`.
    - **Fixture:** new `backend/tests/fixtures/handoff_ho293fb42e.json` holds hand-written, masked rows of the spec's criterion-4 turn sequence. The confirm bot row has `ui_payload` steps with facts `card_mask: "•••• 9118"` and `tx_count: 2`, and customer rows carry `turn_id`s. No real export, no real names (R10).
    - **Tests:** new `backend/tests/unit/test_handoff_summary_v2.py` has the 5 spec tests, all with `ScriptedLLM`.
      - The replay test asserts the filled `case_summary` contains `2` and `•••• 9118`, and that no field contains `0 transacciones`.
      - It also asserts `{tx_count}` is not offered with no evidence and no unanswered confirm.
  - Verify: `cd backend && uv run pytest tests/unit/test_handoff_summary_v2.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_escalation_rules.py -q && uv run ruff check app/domains/conversation/nodes/handoff_summary.py app/domains/conversation/baseline/template_compose.py app/domains/conversation/runner.py tests/unit/test_handoff_summary_v2.py && uv run ruff format --check app/domains/conversation/nodes/handoff_summary.py app/domains/conversation/baseline/template_compose.py app/domains/conversation/runner.py tests/unit/test_handoff_summary_v2.py`
  - Files: `backend/app/domains/conversation/nodes/handoff_summary.py`, `backend/app/domains/conversation/prompts/handoff_summary@v2.md` (new), `backend/app/domains/conversation/baseline/template_compose.py`, `backend/app/domains/conversation/runner.py`, `backend/tests/unit/test_handoff_summary_v2.py` (new), `backend/tests/fixtures/handoff_ho293fb42e.json` (new)

- [ ] T4: Packet v2 code-built fields: focus card, routing, risk, history, friction
  - Depends on: T1 (`Routing`, `RiskSignals`, `CustomerHistory`, `Friction`, `HandoffPacket` fields, `Resolution.branch/flow`, `policy.handoff_packet.history_days`, `handoff.service.customer_history`); T2 (`GraphState.handoff_case_summary`, the swept `test_handoff_packet.py`)
  - Read exactly these: spec §"Decisions" D5, D6, D8 and §"Contracts" → "Graph state", "Tools"; `backend/app/domains/conversation/nodes/handoff.py`; `backend/app/domains/conversation/graph.py` `_keep_open_question` / `_segment_update` / `_track_segments` / `build_graph` node wrapping
  - Acceptance:
    - **Tools** (`tools/handoff.py`): `HandoffTools.history(self, days: int) -> CustomerHistory | None`, with no customer parameter (R1).
      - `InMemoryHandoffTools.__init__(history: CustomerHistory | None = None, history_error: Exception | None = None)` returns or raises accordingly.
      - `ServiceHandoffTools.history` calls `service.customer_history(self._ctx.customer_id, self._ctx.conversation_id, days, 5)`.
    - **Packet** (`nodes/handoff.py`): the packet carries these fields.
      - `case_summary=CaseSummary.model_validate(v) if (v := state.get("handoff_case_summary")) else None`. The channel holds a dumped dict (T2).
      - `focus_card`: `kind_label + mask_card` of `selected_card_id` through `configurable.get("bank_tools")`, or `None` when there is no card, no tools or the read fails.
      - `routing=Routing(reason, queue, branch, flow)` from the resolution.
      - `risk=RiskSignals(priority_flags=state priority_flags, legal_keyword=legal_hit(user_text) or reason=="legal_regulator", unauthorized_attempts=state value)`, snapshotted from the incoming state.
      - `history`: `await handoff_tools.history(policy.handoff_packet.history_days)`, or `None` on any exception (the handoff still goes ahead).
      - `friction=Friction(**state friction or zeros)`.
    - **State and counting:**
      - `state.py` `TurnState` declares `friction: NotRequired[dict[str, int]]` with keys `clarifications, abstentions, non_answers`.
      - `graph.py` increments it at one level only, with no double count through nested wrappers:
        - +1 `non_answers` on each non-answer `_keep_open_question` detects, the replay and the hand-off branch.
        - +1 `clarifications` when a wrapped flow / agent update raises `clarification_failures` above the state's value, or a flow update exhausts clarification (`escalation_reason == "clarification_exhausted"` not produced by the non-answer branch).
        - +1 `abstentions` once per turn routed to `abstain`.
      - No flow and no `load_session` reset touches `friction`.
    - **Takeover:** `return_to_bot` in `takeover.py` adds `"friction": {"clarifications": 0, "abstentions": 0, "non_answers": 0}` to its `aupdate_state` dict.
    - **Tests:** `test_handoff_packet.py` gains the 2 spec tests.
      - `test_packet_v2_code_fields`:
        - The routing branch is `by_flow` with pending `unrecognized_charge` and `default` without one.
        - The risk snapshot shows the flags and attempts that the node's return resets.
        - Friction is counted across two flows, by driving the graph with `make_session`/`run_turn` as in `test_non_answer.py`.
        - Friction is cleared by `return_to_bot`, using a fake host whose `graph.aupdate_state` records the dict, with `get_redis`/`store`/`events`/`PostgresPiiVault`/`publish_mode` monkeypatched as in `tests/conftest.py` ~370-392.
        - History comes from `InMemoryHandoffTools(history=...)`, and `history is None` when it raises.
      - `test_r1_history_session_bound`:
        - `inspect.signature(HandoffTools.history)` has only `days`.
        - `ServiceHandoffTools(ctx).history(90)` calls a monkeypatched `service.customer_history` with `ctx.customer_id` and `ctx.conversation_id`.
  - Verify: `cd backend && uv run pytest tests/unit/test_handoff_packet.py tests/unit/test_non_answer.py tests/unit/test_block_flows.py -q && uv run ruff check app/domains/conversation/nodes/handoff.py app/domains/conversation/tools/handoff.py app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/takeover.py tests/unit/test_handoff_packet.py && uv run ruff format --check app/domains/conversation/nodes/handoff.py app/domains/conversation/tools/handoff.py app/domains/conversation/state.py app/domains/conversation/graph.py app/domains/conversation/takeover.py tests/unit/test_handoff_packet.py`
  - Files: `backend/app/domains/conversation/nodes/handoff.py`, `backend/app/domains/conversation/tools/handoff.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/takeover.py`, `backend/tests/unit/test_handoff_packet.py`

- [ ] T5: Staff API H2 proof, regenerated client, inbox preview and packet view redesign (runs alone, needs `make up`)
  - Depends on: T1 (widened `HandoffSummary`/`HandoffPacket` in the OpenAPI schema); T3 + T4 (the full handoff path the integration test drives); T2 (swept `test_staff_round_trip.py`)
  - Read exactly these: spec §"Decisions" D9 and §"Success criteria" 3, 5; `backend/tests/integration/test_staff_round_trip.py` (`test_handoff_claim_chat_return`, `test_staff_access_boundaries`); `frontend/src/components/staff/PacketView.tsx` + `InboxList.tsx`
  - Acceptance:
    - **Integration test** (`test_staff_round_trip.py`, extended):
      - `GET /api/v1/staff/handoffs` rows carry `request` (non-empty), `case_summary` (an object, or null on the fallback path) and `claimed_at` (null before claim, set after).
      - `GET /api/v1/staff/conversations/{id}/messages` answers `404` for the agent on a queued, unclaimed case (R13).
    - **Client:** with the stack up on this branch, `make client` regenerates `frontend/src/client/`. Don't hand-edit it.
    - **`InboxList.tsx`:** each row shows the summary preview before claim (`case_summary.asked`, falling back to `request`) and a time in queue that ticks. The clock runs from `created_at` to now, or to `claimed_at` once claimed (AS7). It is computed client-side. SSE-updated rows render the same.
    - **`PacketView.tsx`:**
      - It shows the case summary (asked / did / unfinished; when it is null, `request`), the focus card, routing (reason, queue, branch, flow), risk (flags, legal keyword, unauthorized attempts), history (past handoffs + claims, or "none") and friction.
      - It keeps the existing facts / actions / evidence / open questions.
      - It adds a link to `/staff/conversations/{conversation_id}`.
      - Every value is shown as the server built it (R4), and every null section renders a "none" text.
    - **Route:** `handoffs.$handoffId.tsx` lays the packet view next to the `AgentChat` conversation after claim.
    - **i18n:** all new labels exist in `es.json` and `pt.json`. `index.tsx` stays untouched.
  - Verify: `cd backend && uv run pytest tests/integration/test_staff_round_trip.py -q && uv run mypy app && uv run lint-imports && cd ../frontend && grep -q "case_summary" src/client/types.gen.ts && npm run typecheck && npx biome check src/components/staff/InboxList.tsx src/components/staff/PacketView.tsx "src/routes/staff/handoffs.\$handoffId.tsx" src/lib/i18n/es.json src/lib/i18n/pt.json`
  - Files: `backend/tests/integration/test_staff_round_trip.py`, `frontend/src/client/*` (generated), `frontend/src/components/staff/InboxList.tsx`, `frontend/src/components/staff/PacketView.tsx`, `frontend/src/routes/staff/handoffs.$handoffId.tsx`, `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2 | | Neither depends on anything. They touch different domains: T1 has handoff, disputes, policy, yaml and `04`; T2 has `handoff_summary.py`, `graph.py` and the test sweep. T2 types the channel as a plain dict, so it doesn't import T1's `CaseSummary`. T1's Verify runs no swept test file. |
| W2 | T3, T4 | | Both need T1 + T2. Their file sets are disjoint. T3 owns `handoff_summary.py`, the prompt, `template_compose.py`, `runner.py` and its new test + fixture. T4 owns `handoff.py`, `tools/handoff.py`, `state.py`, `graph.py`, `takeover.py` and `test_handoff_packet.py`. They hand over only through `GraphState.handoff_case_summary`, which T2 declared. |
| W3 | T5 | alone (client regeneration against the running stack, integration tests on the dev DB) | Needs the final backend schema and handoff path from T1-T4. |

Ownership of the shared hubs:
- `graph.py`: T2 in W1, then T4 in W2.
- `handoff_summary.py`: T2 in W1, then T3 in W2.
- `test_handoff_packet.py`: T2, then T4.
- `test_staff_round_trip.py`: T2, then T5.
- No task touches `Makefile`, `pyproject.toml`, lockfiles or `.env.example`.
