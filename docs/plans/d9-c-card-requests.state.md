# State: D9-C — Card requests (open and close a card, staff decision)
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D9-C (G8+G10, owner A) · spec `docs/specs/d9-c-card-requests.md` · plan `docs/plans/d9-c-card-requests.md`
Branch `feat/d9-c-card-requests`, based on `develop` @ ecc9655.

## Conventions established for this card
- Facts, interfaces I1–I12 and "Decisions by the human" live in the plan (§"Facts checked against the repo"). They bind every task; read the parts your task names.
- Plan task ids are T1–T31; spec test ids are always written "spec Tn".
- All tests use a fake LLM. Run only your task's Verify, never the full suite.
- i18n placeholders (T9): `profile_form.income_hint` takes `{currency}`; `staff.card_request.credit_bounds` takes `{min}`/`{max}`. `staff.card_request.decision.not_cancelled_balance` is worded as a message.
- customers (T7): `apply_profile_changes(..., conversation_id: str|None, card_request_id: str|None)` locks the customer row FOR UPDATE, never commits, returns the fields actually changed. `PROFILE_FIELDS` in customers/schemas.py is the I7 order.
- Never stage `eval/reports/*` or `docs/plans/d7-a-timeline-heldout-report.state.md`. Don't commit.

- T12 cards: `create_open_request(customer_id, conversation_id: UUID, card_kind, changes: Mapping[ProfileField,str], *, idempotency_key) -> CardRequestView`; `read_back_open_request(request_id) -> (CardRequestView, ProfileValues)`; `get_request` raises NotFound; `pending_requests(customer_id)`; `RequestPending(Conflict)` code `request_pending` in cards/service.py.
- T13 protocol: `BankWriteTools.request_card(kind, changed_fields: list[str], *, idempotency_key) -> ActionResult`; `pending_card_requests() -> PendingCardRequests(open_pending: bool, close_card_ids: frozenset[str])`. Fake request dict keys `reference, kind, card_kind, status, changed_fields, product_id, reason_code, created_at` (close fills product_id/reason_code). Read-back carries `request_id` as str; `fields_saved` encoding: see Human decisions.
- T19 runner: `start_turn(..., resume=...|"profile_form"|"profile_form_cancel", form_changed_fields: list[str]|None)`; `graph_input["form_changed_fields"]` always set. runner.py has two marked casts that T20 (owner of `TurnInput` in graph.py) must remove — T20's Files gain runner.py.

- T14 prompt: `reason` codes come from the `propose_plan` tool description (T29, owner of the `close` action in plan.py, lists `cancel_reasons` there from policy); the prompt holds no list. `{close_balance}` is the only balance fact.

- T11: `card_request_unavailable_reply(language) -> dict` (segments + human-chip `QuickRepliesEvent`) in `nodes/abstain.py`; T15 imports it.

- T16: `check_open(kind, bank_tools, write_tools) -> str|None` in agent/card_request.py (patch `card_request.get_policies` in tests); `AGENT_PROFILE_FORM_PAUSE` in plan.py; `ProposedStep.kind` required on open. Readers of `step["card_id"]` must branch on `action`: `issue_stored_plan`, step_up.py, node.py (T20), confirm.py (T24).

- T18: `decide_request(request_id, agent_id, body: CardRequestDecision, *, decision_key, before_write) -> DecisionOutcome(request, verified, replayed)`; `build_panel(request_id, language)` (`reason_label` None — T21 fills via `cancel_reason_label`). Errors: `AlreadyDecided`/`BalanceNotZero` (Conflict→409); `DecisionNotAllowed`/`LimitRequired`/`LimitOutOfBounds`/`DeclineReasonInvalid` (ToolError→422). Repo helpers `write_decision(work)`, `lock_request`, `fetch_product_row`, `update_request_decision` for T22/T26.

- T22: `create_close_request(customer_id, conversation_id, card_id, reason_code, *, idempotency_key) -> CardRequestView` (AccessDenied/NotFound/ClosurePending); `read_back_close_request(id) -> (CardRequestView, CloseCardReadback(last4, kind, status, current_balance: Decimal, currency, country))`. It does NOT check card-not-Closed or reason_code ∈ policy — T29 `check_steps` does (already_in_state / invalid_reason).

- T20: `agent_profile_form(state, config)` in agent/card_request.py (imports plan/step_up inside the function — plan.py imports card_request.check_open). `issue_stored_plan` open step: tool `cards.request_card`, summary_key `request_card`, facts `kind_label` + one `profile_field` per field. Clearing on cancel/flag-off: pending, agent_plan_steps, confirmation_token_id, card_request_kind, profile_changed_fields.

- T24: `_accept` delegates `open` to `_accept_open` before the card_id loop — T29 adds `close` the same way. `async card_request_block(result: ActionResult, bank_tools) -> CardRequestBlock` is open-only (T29 extends: card_mask, reason_code). handoff.py `_FACTS["cards.request_card"]="card_request_filed"`; packet.card_request set from a verified action. T27: `_card_request_in_flight` in node.py matches action strings {open, close}.

## Human decisions taken mid-card
- T18 → human: keep all four — new card current_balance 0; has_linked_app NULL; non-numeric limit → limit_out_of_bounds (missing/blank → limit_required); debit approve ignores credit_limit (NULL).
- T13 → human: read-back `fields_saved` is a comma-joined string of field names (`",".join(changed_fields)`); `ReadbackValue` stays unchanged. Postgres writer (T17) matches; readers split on `,`.
- Plan Q1 (T6): form-only vault token kinds PFEMAIL/PFPHONE/PFADDR/PFOCC/PFINCOME, fresh token per submit, newest wins, TOKEN_RE unchanged.
- Plan Q2 (T27): LLM-down detection = code keyword check (fixed ES/PT lists) or an open/close plan in progress → card_request_unavailable + human chip.
- Plan Q3: implementers write unworded copy (reason/field labels, i18n, queue colours) per docs/brand.md; reviewed at the verifier gate.
- Plan Q4: card_open_request / card_close_request → cause group by_design.
- Readings R-a..R-f confirmed as written (T5 also touches pipeline/load/postgres.py).

- T29 → human: `close_balance` is registered under the exact reference `close_balance` via a new `TurnRefs.add_value`; T14 prompt unchanged (no version bump).

- T29 → human: a missing `current_balance` shows neutral code-built wording (ES 'saldo no disponible' / PT 'saldo indisponível'), never 0. Follow-up T29b after T28.

- Verify round 1 → human (2026-10-04): T27 narrows the LLM-down keyword lists to explicit open/close wording (drop "otra tarjeta", bare "dar de baja"); block / unrecognised-charge / insurance messages must not be caught.
- Verify round 1 → human: T4 guards `render_decision("not_cancelled_balance", balance=None)` with `balance_unavailable_text` (no KeyError), one unit test.
- Verify round 1 → human: T29 tightens `test_close_es_happy` / `test_close_pt_nonzero_balance_happy` to the exact code-formatted balance; T7 reuses the identity document mask instead of the duplicate. Decline reasons stay hardcoded in the panel (not served from policy) — gate note.
- Verify round 1: T30 re-opens the pending profile form on `409 form_required` (D11 "pause kept", mirror OTP) instead of cancelling it.

- Verify round 1 → human: T7 option A — public `login_hint(document_type, last3)` in customers/service.py, identity `me()` and the profile form call it (identity already imports customers; no reverse import).
- Verify round 1 → human: profile-form GET gains `card_kind` (credit|debit) from the pending pause so a re-opened form has the right title; client regenerated, `04` §3 + spec GET row updated (T30 repair 2). T30 also renders null editable values as empty (income must then be entered) and mirrors OTP restore-on-mount.
- Verify round 1 → human: live proofs unblocked — orchestrator sets DEMO_QUICK_LOGIN=true in local .env for the re-run and switches it back after; the human adds the Bash rule for `docker exec latam-cs-postgres-1` themselves.

- Verify round 2 → human: MX income is MXN (AS6 stands) — staff panel formats income in the form's income currency (MXN/COP/ARS), not the card currency (T18).
- Verify round 2 → human: T27 adds exclusions — stolen/lost and negation words (robada/robaron/perdí/extravié/roubado/perdi/não quero/no quiero) are never a card request on the LLM-down path.
- Verify round 2 → human: T4 no-balance not-cancelled text is a separate sentence — ES "Todavía no podemos cancelar tu tarjeta •••• {last4}: no pudimos confirmar su saldo. Escríbenos y lo revisamos." PT "Ainda não podemos cancelar o seu cartão •••• {last4}: não conseguimos confirmar o saldo. Fale com a gente e nós verificamos."
- Verify round 2 → human: a pending profile form re-opens on page load (one GET); the 409 path stays as fallback (T30). Correction: the round-1 line "mirrors OTP restore-on-mount" was mis-worded by the orchestrator — the OTP pause is cancelled on mount.
- Verify round 2 (bugs, no decision): T31 staff panel uses newId() not crypto.randomUUID (insecure http), shows translated labels not raw codes, close reason under its own label in the staff UI language; T24 plan-card facts no duplicate React keys; T8 amendment names the card_cancel tier change.

- (2026-10-04, round 3, human-authorised beyond the two-round limit) Successful cancel 500 (`fetch_history_by_key` selects only id; `_decision_verified` reads product_id/new_status): fix it and add an integration test for a successful close+cancel (T18).
- (round 3) The staff panel shows an "outcome unknown, reload" message on 5xx/network errors; "no change" only on 4xx (T31).
- (round 3) LLM-down exclusions: whole-word matching; "no quiero"/"não quero" counts only directly before cancelar/cerrar/encerrar/fechar (T27).
- (round 3) Remove leftover test conversation b39aa65e-3b04-4689-bf5a-f1f38d0c5546 in the V5 re-run cleanup.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a3c0f8a | card_requests.yaml + loader; required on PolicyBundle |
| T2 | done | a75688a | creditos/retencion queues, Valentina/Andrés, 2 reasons, CardRequestBlock, escalation v10 |
| T3 | done | a7a7492 | tools.yaml v6; 3 new Preconditions |
| T4 | done | a7a54ee | repair 2: card_request_not_cancelled_no_balance template when balance None |
| T5 | done | a47246d | 0011 migration round-trips on a throwaway DB; make data truncates the 2 new tables |
| T6 | done | afe5f86 | vault stage_form_values/form_values, PF* kinds; pii_vault.kind has no CHECK |
| T7 | done | a624e09 | repair1: public customers.login_hint used by identity me() and profile form; test_auth integration left to V1 |
| T8 | done | a9f4375 | repair 2: amendment names card_cancel tier Stretch→Core |
| T9 | done | a449436 | I12 i18n keys in es/pt |
| T10 | done | a27074f | agent@v5 + playbooks v2 card_open; node→v5; reads scope_facts drop new_card_not_available |
| T11 | done | a185eee | scope v3 no new_card; abstain new_card → card_request_unavailable_reply + human chip; baseline legacy |
| T12 | done | a3f0e2d | cards open storage: create_open_request/read_back/get_request/pending_requests, RequestPending |
| T13 | done | ac0555e | request_card/pending_card_requests in write/executor/fake/sandbox; fields_saved comma-joined (ReadbackValue has no list) — Q pending |
| T14 | done | a6b4620 | agent@v5 close action + results; playbooks card_cancel (v2) |
| T15 | done | af53892 | card_cancel core tier (classifier false, version untouched); unsupported → C7 reply + chip; off-path test ES/PT |
| T16 | done | adab2b7 | open action + check_open eligibility (no handoff), accepted (form_required) pause, ProfileFormEvent |
| T17 | done | a845c1f | PostgresBankWrites.request_card/pending_card_requests; verified from re-read row + profile |
| T18 | done | a5d78dc | repair 3: fetch_history_by_key selects product_id,new_status; test_cancel_zero_balance_closes_card_and_replays |
| T19 | done | a2bdad7 | profile-form GET/POST, form_required gate, runner resume values + form_changed_fields; R13 cross-customer test |
| T20 | done | ac9d6fd | form pause node + graph routing; issue_stored_plan open step; runner casts gone; node.py readers; diagram regenerated |
| T21 | done | a5a488f | staff card-request GET/decision routes; /return 409 request_undecided; re-verify PASS after T18 fix |
| T22 | done | a1f2f04 | create_close_request/read_back_close_request, ClosurePending, CloseCardReadback |
| T23 | done | a110793 | 4 clearing sites also clear card_request_kind/profile_changed_fields |
| T24 | done | a771f69 | repair 2: ConfirmCard index-qualified key; plan.py unchanged |
| T25 | done | a38fb6b | request_closure in protocol/executor/fake/sandbox/postgres; close read-back keys in state file |
| T26 | done | a1c61ec | close decisions: cancel locks product, balance≠0 → BalanceNotZero before write; =0 → Closed + history in same tx; keep/not_cancelled_balance request-only |
| T27 | done | a475d13 | repair 3: _NOT_A_REQUEST regex - whole-word verbs, card-context adjectives, negation only before close verb |
| T28 | done | a9ea26f | 0011 applied, agent.creditos/retencion seeded, client regenerated, queue colours creditos bg-ok / retencion bg-foreground; P1 logins OK |
| T29 | done | a57b8cc | repair1: R4 close tests assert exact formatted balance |
| T30 | done | a14dcd9 | repair 4: mount probe GET profile-form; 200 opens with initialView, 409 ignored |
| T31 | done | a5eb90b | repair 3: error.unknown_outcome on 5xx/network; same Idempotency-Key on retry |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T5 — Migration 0011 and truncate list
Created: `backend/app/alembic/versions/0011_card_requests.py` (revision `0011`, down `0010`).
Changed: `pipeline/load/postgres.py` (`truncate_targets` + `app.card_requests`, `app.customer_profile_history`).
Facts the next tasks need: index names `uq_card_requests_pending_open_customer`, `uq_card_requests_pending_close_product`, `ix_customer_profile_history_customer_at`; CHECK names `ck_card_requests_{kind,card_kind,status,decision}`, `ck_customer_profile_history_field`; `decision` CHECK allows NULL; no FK on `bank.products.conversation_id` (spec says plain uuid).
Deviations: none; Verify DATABASE_URL credentials worked as written.
Verify: full Verify command → alembic up/down/up ok, count=5, ruff check and format passed; throwaway db dropped.

### T1 — Policy card_requests.yaml v1 and loader
Created: `policies/card_requests.yaml`, `backend/app/domains/policy/card_requests.py` (`CardRequestsPolicy`, `CreditLimitBounds`, `load_card_requests_policy`), `backend/tests/unit/test_card_requests_policy.py`.
Changed: `backend/app/domains/policy/registry.py` (`card_requests` in `_MODELS_BY_STEM`; required field on `PolicyBundle`, so `get_policies().card_requests` is typed non-optional).
Facts the next tasks need: bounds are `policy.credit_limit_bounds[cur].min/.max` (Decimal); rates `interest_rate_by_country[country]` (Decimal); `max_cards_per_kind` keys are "credit"/"debit"; load errors are pydantic `ValidationError` from the standalone loader, `PolicyLoadError` via the registry.
Deviations: none.
Verify: pytest 3 passed; ruff check, ruff format --check and mypy clean.

### T3 — tools.yaml v6 and the three Preconditions fields
Changed: `policies/tools.yaml` (version 6, `cards.request_card`, `cards.request_closure` verbatim), `backend/app/domains/policy/tools_policy.py` (`Preconditions.request_eligible/closure_pending/reason_in_policy`, documented with rejection codes).
Facts the next tasks need: `has_preconditions(policy)` returns a callable `(tool)`; `allowed_intents: []` so `tool_allowed` is False for every intent; `step_up_rule` is True for both.
Deviations: none.
Verify: pytest r2_confirmation_store + policy_registry → 5 passed; has_preconditions/step_up/tool_allowed check ok; ruff check/format, mypy clean.

### T9 — Frontend i18n keys (I12)
Changed: `frontend/src/lib/i18n/es.json`, `pt.json` (all I12 keys added, 63 lines each; no existing key changed, last line only gained a comma).
Facts the next tasks need: placeholders are `{currency}` (profile_form.income_hint) and `{min}`/`{max}` (staff.card_request.credit_bounds). `confirm.steps.*` and `staff.queue.*` sit next to their siblings; profile_form.* and staff.card_request.* appended at the end. Wording is unreviewed brand-voice copy (Q3), PT is team-generated.
Deviations: none.
Verify: node key-set check + `npx biome check` on both files → "Checked 2 files... No fixes applied" (host biome worked).

### T2 — Queues, reasons, packet block, escalation v10, staff names
Changed: `localization/format.py` (`Queue` + labels), `identity/provision.py` (`_AGENT_NAMES`), `handoff/schemas.py` (2 reasons, `CardRequestBlock`, `HandoffPacket.card_request`), `policies/escalation.yaml` (v10, two rules), `policy/escalation.py` (`_REQUIRED_REASONS`), `analytics/cause_groups.py` (both `by_design`).
Facts the next tasks need: `rules` is a dict keyed by reason (python -c unchanged); `CardRequestBlock` exported in `handoff/schemas.py` `__all__`.
Deviations: none.
Verify: pytest test_escalation_rules + test_policy_registry → 17 passed; python -c, ruff check/format, mypy all clean.

### T6 — Vault form-value staging (I6)
Changed: `backend/app/domains/safety/vault.py` (`InMemoryPiiVault.stage_form_values`, `form_values`, `_max_number`, `_FORM_KINDS`; Postgres inherits, `_persist` already stores kind from the token).
Facts the next tasks need: field keys are the `ProfileField` strings; unknown field raises KeyError; both methods call `_load()` first. Rows land in `app.pii_vault` with kinds PFEMAIL/PFPHONE/PFADDR/PFOCC/PFINCOME: T5's migration must not constrain `kind` to the old set (not checked).
Deviations: none.
Verify: test_r5_masking 3 passed; inline vault check, ruff check/format, mypy all clean.

### T8 — Docs 02, 03, 04
Changed: `docs/solution-docs/02-conversation-design.md` (§1 `card_cancel` Core row, §3 `agent/profile_form` pause, §5 queues + `card_request_unavailable` text, §6 decision panel as item 4, one-click actions renumbered 4a), `03-data-architecture.md` (§6 `products` columns, `card_requests`, `customer_profile_history`, PF* vault kinds, staff names), `04-contracts.md` (§1 two tools + `propose_plan` open/close, §3 routes/gate/SSE, §4 reasons/`card_request`/`Queue`, §5 policy files incl. `customer_not_active` override for openings).
Facts the next tasks need: docs only, spec values copied verbatim.
Deviations: none. Added the Q1 PF* vault kinds and Q4 `by_design` cause group (from state file) to `03`/`04`.
Verify: grep counts 02/04 profile_form, 03 customer_profile_history, 04 cards_changed|... all ≥ 1.

### T7 — Customers: profile values, form view, writes with history, decision profile
Changed: `backend/app/domains/customers/{schemas,repository,service}.py` (I7 names; `PROFILE_FIELDS` order tuple; `ProfileFormReadOnly`).
Facts: `apply_profile_changes(conn, customer_id, changes, *, actor, conversation_id: str|None, card_request_id: str|None) -> list[ProfileField]` locks the row (FOR UPDATE), skips unchanged values, never commits; `get_profile_form(customer_id, language)` ignores `language` (date is dd/mm/yyyy via `localization.format.format_date`); `DecisionProfile` fields: credit_score, segment, tenure_years, occupation, estimated_monthly_income, country; tenure from `registration_date` in SQL.
Deviations: login-hint mask duplicated in customers (identity imports customers, so no reverse import); customers imports `safety.vault.encrypt_text` and `localization.format`.
Verify: task Verify command → imports OK, lint-imports 4 kept, ruff check/format clean, mypy no issues.

### T4 — Seven templates and decision messages
Created: `backend/app/domains/conversation/card_request_messages.py` (`render_decision`, `announce_decision`, `cancel_reason_label`, `profile_field_label`, `Decision`, `CardKind`), `backend/tests/unit/test_card_request_messages.py`.
Changed: `conversation/templates.py` (seven `card_request_*` keys in `TemplateKind` and `_TEMPLATES`, verbatim §8).
Facts the next tasks need: `announce_decision` publishes through `app.core.events.publish` (module attr `crm.events`) and relays via `takeover.relay_agent_message`; unit tests here are sync (no async plugin), use `asyncio.run`.
Deviations: `test_templates.py` NOT changed: its key list `_VARIED` demands >=3 variants per kind, but §8 gives one verbatim text per key.
Verify: pytest 6 passed; ruff check, ruff format --check and mypy clean.

### T10 — Prompt agent@v5, playbook card_open, node/reads wiring
Created: `backend/app/domains/conversation/prompts/agent@v5.md` (v4 + `open` action, `form_required`, `rejected (open: <code>)`, "Una tarjeta nueva" section).
Changed: `policies/playbooks.yaml` (v2, `card_open`), `agent/node.py` (`PromptRef("agent", 5)`), `agent/reads.py` (`new_card_not_available` branch and unused `get_template` import removed).
Facts the next tasks need: `close` / `card_cancel` not added (T14). `agent@v4.md` untouched.
Deviations: none.
Verify: full Verify chain passed (7 passed; ruff, format, mypy clean).

### T12 — Cards: open-request storage and reads (I8, open part)
Changed: `cards/schemas.py` (`CardRequestView`), `cards/repository.py` (`fetch_request_by_id/by_key`, `fetch_pending_requests`, `insert_open_request`, `update_changed_fields`, `write_open_request(work)` one `get_engine().begin()`), `cards/service.py`.
Facts the next tasks need: `create_open_request(customer_id, conversation_id: UUID, card_kind, changes: Mapping[ProfileField,str], *, idempotency_key) -> CardRequestView` (actor="customer"; `changed_fields` ends as the fields actually changed); `read_back_open_request(request_id: UUID) -> tuple[CardRequestView, ProfileValues]`; `get_request(request_id: UUID)` raises `NotFound`; `pending_requests(customer_id)`. `RequestPending(Conflict)` code `request_pending`, in `cards/service.py`. `CardRequestView` mirrors all table columns except the two keys. Not tested against a DB (Verify has no test).
Deviations: none.
Verify: full Verify → import ok, lint-imports 4 kept, ruff check/format clean, mypy no issues.

### T13 — Write protocol, executor, fake bank, sandbox: request_card / pending_card_requests
Changed: `tools/write.py` (`PendingCardRequests` frozen dataclass, 2 protocol methods), `tools/executor.py` (`request_card(kind, changed_fields, token_id)` via `_run` as `cards.request_card`, added to `_CARDS_WRITES`; `pending_card_requests()` audited read `cards.pending_card_requests`, no allowlist), `tools/fakebank.py` (I10 overlay fields; `FakeBankWrites.request_card`/`pending_card_requests`), `sandbox.py` (recording wrapper).
Facts the next tasks need: `ReadbackValue` has no list member, so the fake's read-back `fields_saved` is a comma-joined string (Postgres T16 and any reader must match, or ReadbackValue must widen); read-back also has `request_id` (str). Fake: missing staged field -> verified=False, nothing written; history entries `{field, old, new, actor:"customer", at}`; request dict keys `reference, kind, card_kind, status, changed_fields, product_id, reason_code, created_at`. `request_closure` not added (T25).
Deviations: `fields_saved` as comma-joined string (see above).
Verify: 21 passed; ruff check, format --check, mypy clean.

### T19 — Customer API: profile-form routes, form_required gate, runner resume values
Changed: `backend/app/api/v1/conversations.py` (GET/POST `/{id}/profile-form`, `ProfileFormValues`, `ProfileFormSubmit/Cancel`, `form_required` gate after the OTP gate), `backend/app/domains/conversation/runner.py` (`checkpointed_form_pause(host, conversation_id) -> bool`; `start_turn`/`_run_turn` take `resume` "profile_form"/"profile_form_cancel" and `form_changed_fields: list[str] | None`; `agent_profile_form` in the `agent_ran` tuple), `backend/tests/integration/test_r13_ownership.py` (`test_profile_form_cross_customer_404`).
Facts the next tasks need: graph input gets `"form_changed_fields"` (None on every other turn); `TurnInput` in graph.py lacks the new keys until T18, so runner uses `cast(Any, resume)` and `cast(dict[str, Any], graph_input)[...]`: drop both casts when T18 lands. POST stages only changed fields via `PostgresPiiVault(conversation.id).stage_form_values`; cancel passes `form_changed_fields=None`.
Deviations: none.
Verify: r13_ownership 2 passed; test_r13_routes 1 passed; ruff check/format and mypy clean.

### T14 — Prompt agent@v5 close action and playbook card_cancel
Changed: `backend/app/domains/conversation/prompts/agent@v5.md` (`close` in propose_plan, close results, "Cerrar una tarjeta" section), `policies/playbooks.yaml` (`card_cancel`, version stays 2).
Facts the next tasks need: prompt says `reason` is one code from the tool description list (T25 must put the list there); `{close_balance}` is the only way to state the zero-balance condition and balance; rejects `already_in_state|closure_pending|invalid_reason`.
Deviations: none.
Verify: grep chain ok; test_policy_registry 2 passed.

### T11 — scope.yaml v3 and the pipeline's `new_card` reply
Changed: `policies/scope.yaml` (v3, no `new_card`), `policy/scope.py` (`TOPICS` drops it), `nodes/abstain.py` (`card_request_unavailable_reply(language) -> dict[str, Any]` returns `{"segments", "ui"}` with the human chip; `make_abstain(..., legacy_new_card=False)`; `new_card` handled before the scope lookup), `baseline/template_compose.py` (`legacy_new_card=True`), `test_abstain_warm.py`, `test_registry_consistency.py`.
Facts the next tasks need: T15 imports `card_request_unavailable_reply` from `app.domains.conversation.nodes.abstain`. `classifier_labels()` now lacks `new_card` (it derives from scope topics), so the tuple in `test_classifier_labels` dropped it; `_NOT_YET_TRAINED` is now an empty set. Unused `_TOPIC_LABELS["new_card"]` removed.
Deviations: none.
Verify: 15 passed; grep clean; ruff check/format, mypy clean.

### T17 — Postgres writer: request_card / pending_card_requests
Changed: `backend/app/domains/conversation/tools/postgres_writes.py` (`PostgresBankWrites.request_card`, `pending_card_requests`, `_profile_matches`).
Facts the next tasks need: values via `PostgresPiiVault(ctx.conversation_id).form_values`; missing field -> `verified=False`, readback `{status:"unknown",kind,at}`, no tracking_id, nothing written. Verified readback: `status, kind, fields_saved` (comma-joined, requested order), `request_id` (str), `at`=row `created_at`; `tracking_id`=reference. Imports `customers.schemas` types only (not `customers.service`); no importlinter change needed. `request_closure` not added (T26).
Deviations: none. Migration 0011 not applied by me; the integration test did not need it (4 passed).
Verify: lint-imports 4 kept; test_postgres_writes 4 passed; ruff check/format, mypy clean.

### T16 — Agent: the `open` action and eligibility in code
Created: `agent/card_request.py` (`check_open(kind, bank_tools, write_tools: ConfirmedWriteTools) -> str | None`), `tests/unit/test_card_request_eligibility.py`.
Changed: `agent/plan.py` (`open` action, `ProposedStep.kind`, `AGENT_PROFILE_FORM_PAUSE`, `request_alone` in `check_steps`, `open` skips the customer_not_active handoff, accepted open -> `box.pause` + `accepted (form_required)`), `state.py` (`AgentPlanStep` open/kind/reason, `card_id` NotRequired; `TurnState.card_request_kind`, `profile_changed_fields`), `ui.py` (`ProfileFormEvent`/`ProfileFormPayload`).
Facts the next tasks need: `check_steps` returns `["request_alone"]*len(steps)` for open+anything else or open with a card; `issue_stored_plan`/`step_up.py`/`confirm.py` still index `step["card_id"]` (mypy does not flag NotRequired reads; T20/T24 must branch on `action == "open"`). `ProposedStep` validator requires `kind` on open, rejects kind on other actions. Tests patch `card_request.get_policies` to cap debit at 1.
Deviations: none.
Verify: 11 passed; ruff check/format and mypy clean.

### T18 — Cards: decision service and panel (I8, open decisions)
Changed: `cards/schemas.py` (`CardRequestPanel`+`PanelRequest/Customer/Card/CreditBounds`, `CardRequestDecision`, `CardRequestDecisionResult`, `DecisionOutcome{request, verified, replayed}`, `DecisionName`), `cards/repository.py` (`lock_request`, `fetch_request_by_decision_key`, `fetch_product_row`, `fetch_customer_cards_panel`, `insert_app_product`, `update_request_decision`, `write_decision[T](work)`), `cards/service.py`.
Facts: `decide_request(request_id, agent_id: UUID, body, *, decision_key, before_write: Callable[[], Awaitable[None]]) -> DecisionOutcome`; `before_write` runs inside the locked transaction after validation; errors `AlreadyDecided`/`BalanceNotZero` (Conflict), `DecisionNotAllowed`/`LimitRequired`/`LimitOutOfBounds`/`DeclineReasonInvalid` (ToolError, codes = snake names). `build_panel(request_id, language)` leaves `reason_label` None (cards can't import conversation; T21 fills it from `cancel_reason_label`). `handoff_id` is set from the conversation's queued/claimed handoff. Key reused on another request -> `AlreadyDecided`. New card: balance 0, `has_linked_app` NULL, status Active. Close decisions raise `DecisionNotAllowed` (T26 replaces; `BalanceNotZero` defined, unused). Not run against a DB.
Deviations: none.
Verify: full Verify → import ok, lint-imports 4 kept, ruff check/format clean, mypy no issues.

### T15 — card_cancel on the pipeline (intents row, unsupported C7 branch, flag-off test)
Changed: `intents.yaml` (`card_cancel` tier stretch→core; node stays null, classifier false, version untouched), `nodes/unsupported.py` (head of `intent_queue` == `card_cancel`, not injection/`other` language → `card_request_unavailable_reply(language)`).
Created: `backend/tests/unit/test_card_requests_off_path.py` (`test_card_requests_off_path`, ids `flag_off-open`/`flag_off-close`; helper `_nlu(case, language)`; `# llm_down params: T27` marker in the params list, ids list needs two more).
Facts the next tasks need: the test asserts only the `nlu` LLM step ran, `overlay.card_requests == {}`, `handoff_tools.created == []`; sets `AGENT_ENABLED=false` via monkeypatch.
Deviations: none.
Verify: 7 passed; ruff check/format and mypy clean.

### T23 — Clear card-request state keys at remaining sites
Changed: `takeover.py`, `nodes/step_up_exit.py` (both sites), `nodes/smalltalk.py`, `agent/dispute.py` (`_CLEARED`): each `confirmation_token_id: None` now followed by `card_request_kind: None` and `profile_changed_fields: None`.
Deviations: none.
Verify: grep check ok; `pytest test_agent_dispute.py test_agent_step_up.py` → 12 passed; ruff check/format clean.

### T22 — Cards: close-request storage (I8, close part)
Changed: `cards/schemas.py` (`CloseCardReadback{last4, kind, status, current_balance: Decimal, currency, country}`), `cards/repository.py` (`insert_close_request`, `write_close_request(work)`), `cards/service.py`.
Facts the next tasks need: `create_close_request(customer_id, conversation_id: UUID, card_id, reason_code, *, idempotency_key) -> CardRequestView` (card ownership via `get_card_details`: other's card -> existing `AccessDenied`, unknown/non-card -> `NotFound`; writes kind='close', card_kind, product_id, reason_code); `read_back_close_request(request_id: UUID) -> tuple[CardRequestView, CloseCardReadback]` (country from `customers.get_decision_profile`); `ClosurePending(Conflict)` code `closure_pending` from index `uq_card_requests_pending_close_product`. `pending_requests` already lists close rows (no kind filter). No Closed-card or reason-in-policy check here (T25/T26 precondition). Not run against a DB.
Deviations: none.
Verify: full Verify → import ok, lint-imports 4 kept, ruff check/format clean, mypy no issues.

### T25 — Write tools: request_closure
Changed: `tools/write.py` (protocol), `tools/executor.py` (`ConfirmedWriteTools.request_closure(card_id, reason, token_id)` via `_run`, `cards.request_closure` in `_CARDS_WRITES`), `tools/fakebank.py`, `sandbox.py` (recording wrapper, call name `request_closure`), `tools/postgres_writes.py`.
Facts the next tasks need: read-back keys `status` ("pending"|"unknown"), `reason`, `request_id` (str), `card_id`, `card_kind`, `last4`, `current_balance` (raw Decimal; fake: None for a card without one), `currency`, `at`; `tracking_id` = reference. Fake stores `{kind:"close", product_id: card_id, reason_code: reason, card_kind, changed_fields: []}`; `pending_card_requests().close_card_ids` includes it. Fake does not raise on a duplicate pending close (T29 `closure_pending` check handles it); Postgres raises `ClosurePending` from the service.
Deviations: none.
Verify: lint-imports 4 kept; 16 passed; ruff check/format, mypy clean.

### T21 — Staff API: panel, decision, return gate
Changed: `backend/app/api/v1/staff.py` (`GET /staff/handoffs/{id}/card-request`, `POST .../card-request/decision`, `request_undecided` gate in `return_handoff`), `backend/tests/integration/conftest.py` (`_STAFF` + creditos/retencion). Created: `backend/tests/integration/test_card_request_decision.py` (3 tests).
Facts: GET non-claimant/no block/other conversation → 404 `not_found`; POST non-claimant → 409 `not_claimant` (before anything is read or written). `Idempotency-Key` header typed UUID (missing/invalid → 422). Audit via `_audit(...)`: `tool_call` in `before_write`, then `readback` + `tool_result` (failures there are logged, not raised); a replayed key audits/announces nothing. `_announce` takes last4/balance/currency from `cards_service.get_card_details(request.customer_id, request.product_id)` and country from `customers_service.get_decision_profile`.
Deviations: none.
BLOCKER (T18 code, not my file): `cards/service.py::_replayed(row)` reads `row["decision_key"]`, but `repository.fetch_request_by_decision_key` selects `_REQUEST_COLUMNS` (no `decision_key`) → `NoSuchColumnError` on every replay. Fix: pass the key in (`_replayed(row, decision_key)`) or select the column.
Verify: pytest decision+round_trip → 1 failed (idempotency test, the blocker above), 5 passed; test_r13_routes 1 passed; ruff check/format and mypy on my files clean; lint-imports 4 kept. Migration 0011 applied only by the suite's own throwaway DB (alembic upgrade head worked).

### T20 — The form pause: agent_profile_form, graph routing, plan card facts
Created: `backend/tests/unit/test_profile_form_r5.py`. Changed: `graph.py` (`TurnInput`/`GraphState`/`run_turn` get the two resume values + `form_changed_fields`; `_agent_pause` "profile_form"; `_flag_off_form_pause`; `_entry` → `agent_profile_form`; node + baseline map), `agent/card_request.py` (`agent_profile_form`), `agent/plan.py` (`issue_stored_plan` open step), `agent/step_up.py` (result steps w/o `card_id`), `agent/node.py` (open step in results lines), `runner.py` (both casts removed), `docs/diagrams/turn-graph-v0.mmd` (regenerated, test_graph compares it).
Facts the next tasks need: card_request.py imports plan/step_up inside the node (plan imports card_request for `check_open`: circular). Open plan card step: tool `cards.request_card`, args `kind`, `changed_fields` (names); facts `kind_label` then one `profile_field` per field. "Again" branch replays `open_question["text"]` + a new form event. Cancel/flag-off clear `pending`, `agent_plan_steps`, `confirmation_token_id`, `card_request_kind`, `profile_changed_fields`.
Deviations: step_up.py needed no rebuild change (`AgentPlanStep(**step)` already keeps keys).
Out of scope: `AgentTurn.intents` has no new-card intent (test uses `general_question`); `confirm.py` still indexes `card_id` (T24).
Verify: 11 passed; ruff check/format and mypy (incl. runner, node) clean.

### T18 repair — replay NoSuchColumnError
Changed: `cards/service.py` (`_replayed(row, decision_key)` takes the key from the caller; the fetch already filters on it, so `row["decision_key"]` is no longer read).
Facts: behaviour unchanged (same request → stored outcome, replayed=True, fresh verified; other request → AlreadyDecided).
Verify: T18 Verify clean; `AGENT_ENABLED=false uv run pytest tests/integration/test_card_request_decision.py -q` → 3 passed.
T21 re-verify: after the T18 `_replayed` fix, full Verify passed (6 passed; r13_routes 1 passed; ruff check/format and mypy clean). The BLOCKER above is resolved.

### T27 — LLM-down C7 text (agent `LLMError` branch)
Changed: `agent/node.py` (`_card_request_in_flight(state)`, keyword tuples `_NEW_CARD_WORDS`/`_CLOSE_CARD_WORDS` accent-folded; check sits after round-cap and pause branches, before the open-plan reminder; returns `cancel_open_plan` + `card_request_kind`/`profile_changed_fields` None + `card_request_unavailable_reply(previous)`), `tests/unit/test_card_requests_off_path.py` (`llm_down-open`, `llm_down-close`).
Facts the next tasks need: open/close plan detected via `agent_plan_steps[*]["action"]` matched as a string, so T29 adding `close` needs no change here. Applies to any `LLMError` subclass (incl. `LLMInvalidOutput`). Text is matched, never logged.
Deviations: none.
Verify: pytest test_card_requests_off_path + test_agent_fallbacks → 5 passed; ruff check/format/mypy clean.

### T24 — Opening on Acepto: execute, packet block, handoff to Créditos
Created: `backend/tests/unit/test_card_request_open.py` (4 tests). Changed: `agent/confirm.py` (`_accept_open`; `_CLEARED` + `card_request_kind`, `profile_changed_fields`), `agent/card_request.py` (`card_request_block`), `nodes/handoff.py`.
Facts the next tasks need: `async card_request_block(result: ActionResult, bank_tools: BankReadTools | None) -> CardRequestBlock` is open-only today (kind="open", card_mask/reason_code None; bank_tools unused) — T29 extends it for close. `confirm._accept` delegates to `_accept_open` when `steps[0]["action"]=="open"` BEFORE the card_id loop; T29 adds its `close` branch the same way. Acepto: `request_card(kind, profile_changed_fields, token_id)` via `execute_plan`; verified → `escalation_reason="card_open_request"`, `handoff_queue=rule_queue(...)` (creditos), no segment (the handoff node's transfer text is the reply). handoff.py: `_FACTS["cards.request_card"]="card_request_filed"` (value = reference), block built from any verified `cards.request_card` in `actions`; packet `card_request` None otherwise; clearing update adds the two keys.
Deviations: none. `_UnverifiedWrites` test stub subclasses `FakeBankWrites` with its own `FakeBankOverlay` (only eligibility reads it).
Verify: 15 passed; ruff check/format, mypy clean; lint-imports run.

### T26 — Close decisions in the service
Changed: `cards/service.py` (`decide_request` close branch: `cancel` locks product, `current_balance != 0` -> `BalanceNotZero` before `before_write`; `= 0` -> `Closed` + `card_status_history` row (actor `staff:<agent_id>`, reason = request `reason_code`, idempotency_key = `decision_key`) in the request-update transaction; `keep`/`not_cancelled_balance` request update only; approve/decline on close -> `DecisionNotAllowed`; `_decision_verified` reads back Closed + history by key for cancel), `cards/repository.py` (`lock_product(conn, product_id)`, `set_product_closed(conn, product_id)`), `tests/integration/test_card_request_decision.py` (`close_case` fixture, `test_cancel_nonzero_balance_writes_nothing`).
Facts: `build_panel` already filled `close_balance_display` (T18); `reason_label` is still filled by the staff route via `cancel_reason_label` (cards can't import conversation), not in the service. Cancel success path (zero balance) is not exercised by a test.
Deviations: none.
Verify: `AGENT_ENABLED=false uv run pytest tests/integration/test_card_request_decision.py -q` -> 4 passed; ruff check/format and mypy clean.

### T29 — Agent: the close action, close_balance, Acepto → Retención
Created: `backend/tests/unit/test_card_request_close.py` (`test_close_es_happy`, `test_close_pt_nonzero_balance_happy`). Changed: `agent/plan.py` (`close` action, `ProposedStep.reason`, `close_balance_text`, plan-card facts card_mask/cancel_reason_label/close_balance, summary `request_closure`, intent `card_cancel`/route `card_request`), `state.py`, `agent/card_request.py` (`check_close`, `card_request_block` close branch), `agent/confirm.py` (`_accept_close`), `agent/refs.py` (`TurnRefs.add_value(fact)`, ref = fact key), `agent/node.py` (tool description lists `cancel_reasons` from policy; `names["close"]`), `nodes/compose.py` (`close_balance` str pass-through), `nodes/handoff.py` (block gate + `_FACTS` for `cards.request_closure` → `card_request_filed`).
Facts the next tasks need: accepted close returns `accepted (step_up_required)` + a fenced `close_balance` reference line; a card with `current_balance` None reads as zero. `check_close(card_id, reason, bank_tools, write_tools, pre)` order already_in_state, closure_pending, invalid_reason; close with other steps → all `request_alone`. Close after Acepto: `escalation_reason="card_close_request"`, queue from policy.
Deviations: none.
Verify: 21 passed; ruff check/format and mypy clean.

### T28 — Environment: 0011, staff seed, client, queue types, P1
Changed: `backend/app/domains/identity/provision.py` (TRUNCATE now also lists `app.card_requests`, `app.customer_profile_history`; 0011 FKs blocked the seed), `frontend/src/components/staff/queueStyles.ts` (creditos `ok` green, retencion `foreground`), `ConversationFilters.tsx` and `lib/sse.ts` (`Queue`/`QUEUES` with both), `frontend/src/client/` regenerated.
Facts: the running stack was bind-mounted from the `-v2` checkout (main); `make up` recreated it from this checkout. Both DBs at 0011. SDK: `getProfileFormApiV1ConversationsConversationIdProfileFormGet`, `postProfileFormApiV1ConversationsConversationIdProfileFormPost`, `getCardRequestApiV1StaffHandoffsHandoffIdCardRequestGet`, `decideCardRequestApiV1StaffHandoffsHandoffIdCardRequestDecisionPost`. Types: `ProfileFormView/Submit/Cancel/ReadOnly/Values`, `CardRequestPanel/Decision/DecisionResult/View/Block`; Queue is an inline union incl. 'creditos' | 'retencion'.
Verify: full chain → login-ok, biome clean, typecheck rc=0.

### T29b — close_balance when the balance is unknown
Changed: `agent/plan.py` (`close_balance_text(details, country, language)`: `current_balance is None` → neutral text, else `format_money`), `card_request_messages.py` (`balance_unavailable_text(language)`: ES "saldo no disponible", PT "saldo indisponível"), `tests/unit/test_card_request_close.py` (`test_close_balance_text_none_is_not_zero`). Fact key stays `close_balance`; `check_close` untouched.
Deviations: none.
Verify: close + open tests pass; ruff check/format and mypy clean.

### T30 — Chat frontend: profile form widget and `cards_changed` refresh
Created: `frontend/src/components/chat/ProfileForm.tsx` (Dialog; GET view on mount, local state only, Send/Cancel/X/Esc).
Changed: `lib/sse.ts` (`ProfileFormUiEvent {card_kind}`, `onCardsChanged` handler, `cards_changed` listener; now required in `ConversationStreamHandlers`), `lib/api.ts` (`getProfileForm`, `postProfileFormSubmit`, `postProfileFormCancel`), `ChatView.tsx` (`formKind` state, form rendered, composer disabled, `form_required` handled, invalidates `CARDS_KEY` + `["home","card"]`).
Facts: client checks mirror the server regexes; income sent as a string with "," -> "."; `form_required` added to KNOWN_ERROR_CODES but `errors.form_required` is NOT in the locale files (falls back to the key lookup; T9 gap, not edited). A reload at the pause (no form on screen) cancels via profile-form cancel on a `form_required` 409.
Deviations: none.
Verify: biome check clean, greps match, typecheck rc=0.

### T31 — Staff card-request panel and return gate
Created: `frontend/src/components/staff/CardRequestPanel.tsx` (props `handoffId`, `onPendingChange`; calls generated SDK directly).
Changed: `frontend/src/routes/staff/handoffs.$handoffId.tsx` (mounts panel when `packet.card_request`; `return-handoff` disabled + `return_blocked` while pending).
Facts: claimant check = GET card-request 404 -> no panel, pending=false. Key from `crypto.randomUUID()` per dialog open, reused on retry. `balance_not_zero` keeps dialog open with a button switching to a new `not_cancelled_balance` dialog. Testids: `card-request-panel`, `-status`, `-changed`, `-decision`, `-result`, `-limit`, `-reason`, `-approve`, `-decline`, `-cancel`, `-keep`, `-not-cancelled`, `-dialog`, `-error`, `-use-not-cancelled`, `-dialog-back`, `-dialog-confirm` (all prefixed `card-request-`).
Deviations: none.
Verify: biome clean; grep hits; container typecheck no errors.
### T30b — `errors.form_required` added to es.json/pt.json after `errors.selection_required` (copy unreviewed). Verify: biome clean, typecheck rc=0.

### T8 repair 1 — Docs numbering and ADR-026 amendment
Changed: `docs/solution-docs/02-conversation-design.md` §6 (one-click actions restored as `4.`, decision panel now `4a.`), `decision-log.md` (dated 2026-10-04 D9-C amendment appended under ADR-026).
Deviations: amendment follows spec D3 (Topic/Intent literals unchanged), not "classifier labels removed" from the repair message.
Verify: grep of `^4\.|^4a\.` in 02 shows 4 then 4a; diff stat lists 02, 03, 04, decision-log.

### T29 repair 1 — R4 assertions tightened
Changed: `backend/tests/unit/test_card_request_close.py` only (ES and PT happy tests assert the exact `format_money(...)` string for 850.00 / 1234.50 and that the raw number is absent once it is removed). No source change.
Verify: test_card_request_close.py → 4 passed; ruff check/format clean.

### T30 repair 1 — form_required re-opens the form; untouched income
Changed: `ChatView.tsx` (409 `form_required` with no form now re-opens it via `setFormKind`, no cancel post; kind from `lastFormKindRef`, else credit, since the GET has no card kind), `ProfileForm.tsx` (`normalizeIncome` drops trailing zeros on prefill and on send; an income still equal to the loaded value skips the income check).
Facts: `bank.customers.estimated_monthly_income` is unconstrained numeric; in latam_app 0 of 150000 rows have a nonzero 3rd decimal (30033 are null). `apply_profile_changes` compares income as `Decimal`, so "32904211.53" == "32904211.530" is not a change. No backend change.
Verify: biome clean, typecheck rc=0 (reasoned read, no new test).

### T4 repair 1 — not_cancelled_balance with no balance
Changed: `card_request_messages.py` (`render_decision` uses `balance_unavailable_text(language)` when `balance` is None for `not_cancelled_balance`, no KeyError, never 0); `test_card_request_messages.py` (+1 test, ES/PT).
Verify: test file, ruff check, mypy clean.

### T27 repair 1 — narrower LLM-down keyword lists
Changed: `agent/node.py` (`_NEW_CARD_WORDS` now explicit open wording only: "quiero una tarjeta nueva/nueva tarjeta", "pedir/solicitar una tarjeta", PT "quero um cartao novo/novo cartao", "pedir/solicitar um cartao"; dropped "otra tarjeta"/"outro cartao", bare "dar de baja"; added "dar de baja mi/la tarjeta"), `tests/unit/test_card_requests_off_path.py` (`test_llm_down_other_messages_are_not_card_requests`, 5 ES/PT block/claim/insurance texts).
Facts: those texts reach the degraded pipeline (agent, nlu and handoff_summary scripted to raise `LLMError`). Plan-in-progress branch unchanged.
Verify: off_path + test_r6_no_write_tools_in_llm_nodes → 14 passed; ruff and mypy clean.

### T7 repair 1 — single login-hint mask
Changed: `customers/service.py` (public `login_hint(document_type, last3)`, used by `get_profile_form`); `identity/service.py` (`me()` calls `customers_service.login_hint`; `_FOUR_BULLETS` removed there).
Facts: output byte-identical (same 4 U+2022 bullets). Dependency stays identity -> customers.
Verify: lint-imports 4 kept; ruff, mypy clean on both files; import check OK; `tests/unit/test_profile_form_r5.py` 1 passed. `tests/integration/test_auth.py` (login_hint) needs a DB, not run.

### T30 repair 2 — card_kind on the GET, null values, mount restore
Changed: `customers/schemas.py` (`ProfileFormView.card_kind` default "credit"), `api/v1/conversations.py` (GET `model_copy`s `card_kind` from the checkpoint's `card_request_kind`), `04` §3 + spec GET row (one field), `frontend/src/client/types.gen.ts` (regenerated; only `card_kind?` added), `ProfileForm.tsx` (title from `view.card_kind`; `orEmpty` for the five fields; empty income is never "untouched", so it shows the income error).
Facts: OTP is NOT restored on mount (the mount effect cancels the OTP pause, D16), so the form restore stays as is (re-opened on a typed message). `ProfileValues` fields are non-null in the schema: if the service sends null the GET may fail before the UI (T7's file, not checked).
Verify: ruff/mypy clean, test_profile_form_r5 1 passed, r13 profile_form 1 passed, biome clean, typecheck rc=0.

### T30 repair 3 — loaded income <= 0 is "no value"
Changed: `ProfileForm.tsx` (`loadedIncome`: a loaded income <= 0 gives an empty field and an empty "untouched" value, so the income error fires until one is entered; text-field `orEmpty` unchanged).
Facts: a POST failure of any kind (incl. 422) shows only `errors.generic` as an alert and re-enables the form; no per-field message.
Verify: biome clean, typecheck rc=0.

### T8 repair 2 — ADR-026 amendment wording
Changed: `docs/solution-docs/decision-log.md` (amendment now says the only `intents.yaml` change is the `card_cancel` tier, Stretch to Core, per spec D3 as amended).
Verify: grep of the amendment line.

### T24 repair 2 — duplicate React key "profile_field"
Changed: `frontend/src/components/chat/ConfirmCard.tsx` (fact `<li key>` is now `${fact.key}-${index}`, one biome-ignore for noArrayIndexKey).
Facts: `fact.key` was only the React key (the `<li>` renders `String(fact.value)`, no label/i18n lookup), so plan.py keeps `key="profile_field"`; labels and values unchanged.
Verify: biome check clean; `npm run typecheck` in latam-cs-frontend-1 clean.

### T31 repair 2 — insecure context, raw codes, close reason
Changed: `CardRequestPanel.tsx` (`newId()` from `lib/uuid` replaces `crypto.randomUUID`; card kind/status via `home.cards.kind.*`/`home.cards.status.*`; close reason translated in the frontend from `reason_code`, ignoring `reason_label`); `lib/i18n/{es,pt}.json` (+7 `staff.card_request.close_reason*` keys).
Deviations: `staff.py` not touched (panel already carries `reason_code`). Verify: biome clean; container typecheck no errors.

### T30 repair 4 — profile form restored on mount
Changed: `ChatView.tsx` (mount probe: one `getProfileForm`; success sets `formView` + `formKind` from `view.card_kind`; any error ignored; stale "GET carries no card kind" comment replaced; `formView` cleared on close/new conversation), `ProfileForm.tsx` (optional `initialView` prop skips its own GET).
Facts: pending is detected by the GET itself: it answers 200 only while paused at `agent/profile_form`, else `409 form_not_open`, which the probe ignores (nothing shown). OTP mount cancel unchanged. The `409 form_required` re-open stays as fallback (form does its own GET).
Verify: biome clean; typecheck: only error in `CardRequestPanel.tsx` (other task's file) on first run.

### T18 repair 2 — panel income in the local currency
Created: `backend/tests/unit/test_card_panel_income.py` (MX income_display starts with MXN, no US$).
Changed: `customers/service.py` (public `income_currency(country)` over the single `_INCOME_CURRENCY`), `cards/service.py` (`build_panel` income uses it; card currency kept for limits/balances/bounds).
Facts: `format_money` handles MXN generically ("MXN $…").
Verify: ruff, mypy, lint-imports clean; new test 1 passed; test_card_request_decision.py 4 passed (REDIS db 15, AGENT_ENABLED=false).

### T4 repair 2 — separate no-balance sentence
Changed: `templates.py` (new key `card_request_not_cancelled_no_balance`, uses `{card_mask}`); `card_request_messages.py` (`render_decision` picks it when `balance` is None; `balance_unavailable_text` kept); test asserts exact ES/PT text.
Verify: both test files, ruff, mypy clean.

### T27 repair 2 — stolen/lost and negation exclusions
Changed: `agent/node.py` (`_NOT_A_REQUEST_WORDS`: robad, robaron, roubad, perdi, extravie, extraviad, no quiero, nao quero; checked on the folded text before the keyword lists; plan-in-progress branch unchanged), `tests/unit/test_card_requests_off_path.py` (5 more texts in `test_llm_down_other_messages_are_not_card_requests`).
Facts: matching is by substring of the accent-folded text, so "perdi" covers perdida/perdido.
Verify: off_path + test_r6_no_write_tools_in_llm_nodes → 19 passed; ruff and mypy clean.

### T31 repair 3 — unknown decision outcome
Changed: `CardRequestPanel.tsx` (5xx / no response / thrown -> `unknown_outcome`; 4xx keeps server code or generic "no change"; dialog stays open, retry reuses the same key); `i18n/{es,pt}.json` (+`staff.card_request.error.unknown_outcome`).
Verify: biome clean; container typecheck no errors.

### T18 repair 3 — cancel read-back selected too few columns
Changed: `cards/repository.py` (`fetch_history_by_key` now selects `id, product_id, new_status`; block/unblock callers only test `is not None`/read the row as a replay marker, so extra columns are safe), `backend/tests/integration/test_card_request_decision.py` (`test_cancel_zero_balance_closes_card_and_replays`: 200 verified, card Closed, one history row, tool_call/readback/tool_result audit, message posted, same-key replay verified with no second write; test restores balance/status).
Checked: other `_decision_verified` branches read only columns their queries select (`fetch_request_by_decision_key` -> id; `fetch_product_row` -> customer_id, product_status, product_type, conversation_id, credit_limit, origin; `view` fields). decline/open-approve/keep/not_cancelled_balance fine.
Verify: ruff, mypy, lint-imports clean; test_card_request_decision.py 5 passed; test_postgres_writes.py run too (block idempotency).

### T27 repair 3 — whole-word exclusions
Changed: `agent/node.py` (`_NOT_A_REQUEST` regex replaces `_NOT_A_REQUEST_WORDS`; `import re`), `tests/unit/test_card_requests_off_path.py` (`test_llm_down_whole_word_exclusions_keep_real_requests`, 4 texts).
Facts: verbs robaron/roubaram/perdi/extravie whole-word alone; adjectives robada/o, roubada/o, perdida/o, extraviada/o only right after "tarjeta|cartao" (at most one word between); negation only as "no quiero|nao quero" + cancelar/cerrar/dar de baja|encerrar/fechar. Probe2: all 17 as wanted.
Verify: off_path + test_r6_no_write_tools_in_llm_nodes pass; ruff and mypy clean.
