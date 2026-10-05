# Plan: D9-C — Card requests: open and close a card, staff decision (G8 + G10)

Spec: [`docs/specs/d9-c-card-requests.md`](../specs/d9-c-card-requests.md) · Branch: `feat/d9-c-card-requests` (on `develop` @ ecc9655)

The spec is approved as written. "Dn", "ASn", "§n", "C1–C7" and "spec Tn"/"Pn" refer to the spec. **Task ids T1–T31 in this plan are not spec test ids**: a spec test is always written "spec T7". This plan adds no decision. Where it fixes a name or a data shape ("Interfaces fixed by this plan", I1–I12), it is only so that tasks built at the same time agree. The four choices the spec left open (Q1 vault lookup, Q2 LLM-down detection, Q3 unworded copy, Q4 analytics cause group) were answered by the human on 2026-10-04. See "Decisions by the human" under the facts. No task is blocked.

## Facts checked against the repo

**Environment**

- The working tree already has the untracked spec, a modified `docs/solution-docs/07-execution-plan.md`, an untracked `docs/plans/d7-a-timeline-heldout-report.state.md` and untracked `eval/reports/dev*` folders. **Leave all of them alone.** Don't commit.
- `.env` sets `AGENT_ENABLED=true` (line 90). **Every backend Verify sets `AGENT_ENABLED=false` on the command line.** Agent tests turn the flag on with the `agent_on` fixture (`backend/tests/conftest.py`).
- The full check runs once, at verification: `make check AGENT_ENABLED=false`. No task runs it.
- The dev stack (`latam-cs-*` containers, all up) mounts `backend/app` and `policies/` and hot-reloads.
- Integration tests (`backend/tests/integration/`) need the stack's Postgres and Redis. `it_db` creates a throwaway `latam_it_<hex>` database and runs `alembic upgrade head` on it, so **integration tests see migration 0011 without touching the dev databases**. An integration Verify must prove the tests ran and did not skip: pipe through `2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in'`.
- Both dev databases (`latam_app`, `latam_golden`) are at alembic `0010`. Migrations live in `backend/app/alembic/versions/` (`0010_agent_cost.py` is the head; header style: docstring, `revision: str = "0010"`, `down_revision: str | None = "0009"`).
- `make seed-identity` = `alembic upgrade head` on golden → `python -m app.domains.identity.provision` → `pipeline load.demo_reset` (app DB recreated from golden as a template) → backend restart. Staff passwords land in `data/secrets/staff_credentials.csv` (git-ignored; columns `username,role,queue,password`). Never commit it.
- `make data` (`pipeline/load/postgres.py` `copy_all`) runs `TRUNCATE TABLE bank.<13 tables>, identity.accounts, app.handoffs`. Postgres refuses to truncate a table that another table references by FK unless the referencing table is also listed. 0011 adds FKs from `app.card_requests` to `app.handoffs` and `identity.accounts`, and from `app.customer_profile_history` to `app.card_requests`. **Both new tables must join that list, or `make data` breaks** (T5).
- `make client` = `cd frontend && npx @hey-api/openapi-ts`. It reads `http://localhost/api/v1/openapi.json` (the backend must be up with the final API code) and rewrites `frontend/src/client/*.gen.ts`.
- `<FE-TYPECHECK>` = `docker exec latam-cs-frontend-1 npm run typecheck --silent`. It exits 0 on `develop` today (checked). The host `node_modules` is incomplete; don't type-check on the host.
- Integration test helpers (`backend/tests/integration/conftest.py`): `it_db`, `it_env` (sets `PII_VAULT_KEY` to a fresh Fernet key, `BANK=postgres`), `it_accounts`, `restore_cards`, `app_client`, `it_staff`. `it_staff` builds agents from `_STAFF` (line 362: `it.atencion`/Laura/atencion, `it.fraudes`/Sofia/fraudes) and yields them keyed by queue.
- If the sandbox refuses a long `&&` chain, run each part of a Verify as its own command. All parts must pass. Tasks in one wave share the checkout: a red run caused by a sibling's half-saved file is re-run once before it counts as the task's own failure.

**What exists on the branch**

- Policies: `tools.yaml` v5, `escalation.yaml` v9, `scope.yaml` v2 (line 12: `new_card: {kind: out_of_scope, reason_key: new_card_not_available, closest_intents: [], human_queue: atencion, offer_human: false}`), `playbooks.yaml` v1 (Spanish `>-` text keyed by intent), `disputes.yaml` (decimal strings, provenance header, the loader style to mirror). No test pins a policy version.
- `backend/app/domains/policy/`: one module per file (`disputes.py`, `escalation.py`, `scope.py`, `tools_policy.py`, `playbooks.py`, …) plus `registry.py` (`get_policies()`). `Preconditions` in `tools_policy.py` is frozen with `extra="forbid"` and today has `status_not_in`, `locked`, `block_origin_in`, `replacement_eligible`, `tx_owned`, `answers_complete`. `escalation.py` `_REQUIRED_REASONS` (line 109) lists every reason the file must define. `scope.py` `TOPICS` (line 25) includes `new_card`.
- `backend/app/domains/analytics/cause_groups.py` `CAUSE_GROUPS` maps handoff reasons to a group; an unmapped reason gets `None` (Q4).
- `localization/format.py`: `Queue` (line 42), `_QUEUE_LABELS`, `format_money(amount: Decimal, currency, country)`, `mask_card(last4)` → `•••• 1234`, `kind_label(kind, language)`, `queue_label(queue, language)`, `local_today`.
- `identity/provision.py` `_AGENT_NAMES: dict[Queue, str]` (line 52); line 161 iterates `get_args(Queue)`, so a new queue without a name fails provisioning.
- `handoff/schemas.py`: `HandoffReason` Literal (line 39), `VerifiedFact{fact: str, value, source}`, `HandoffPacket` (line 143; optional blocks `case_summary`, `focus_card`, `routing`, `risk`, `history`, `friction` default `None`).
- Vault: `backend/app/domains/safety/vault.py` (not under `conversation/`). `encrypt_text`/`decrypt_text` (Fernet, `PII_VAULT_KEY`), `InMemoryAddressVault.put_address` → `⟨ADDR_n⟩`, `InMemoryPiiVault` (`_values`, `_pending`, `_token_for(kind, raw, fresh)` reuses a token for an equal value, `put_address`, `mask`, `unmask`, `flush`), `PostgresPiiVault(conversation_id)` (`_load`, `_require_loaded`, `_persist` derives `kind` from the token). `core/pii.py` `TOKEN_RE` unmasks only `CARD|DOC|EMAIL|PHONE|NAME|ADDR`.
- `ToolContext` (`conversation/tools/context.py`): `customer_id`, `conversation_id`, `actor`, `trace_id`, `policy_version`. `postgres_writes.py` can build `PostgresPiiVault(ctx.conversation_id)` (the runner and `takeover.py` already do).
- Write tools: `tools/write.py` Protocol `BankWriteTools`; `tools/executor.py` `ConfirmedWriteTools(raw, confirmations, step_up, requires_step_up, allowed, audit, *, sleep, timeout_s, has_preconditions)` with `issue_plan`, the audited read `get_block_origin`, and writes through `_run(tool, args, token_id, lambda key: raw...)`; `tools/fakebank.py` `FakeBankOverlay` (line 64: `locked`, `blocked`, `replacements`, `results`, `claim_priorities`), `FakeBank`, `FakeBankWrites` (line 499); `conversation/sandbox.py` `_RecordingWriteTools` implements every write-protocol method.
- Import-linter `conversation-no-repository`: `tools.postgres_writes` may import `cards.service` and `disputes.service`, **not** `customers.service`. So the postgres writer reaches profile writes and read-backs only through `cards.service` (I8). Other domains may import each other's services (e.g. `handoff.service` → `disputes.service`). `app.api` may import any domain service.
- Agent: `agent/plan.py` (`_TOOL_BY_ACTION`, `_SUMMARY_BY_ACTION`, `_INTENT_BY_ACTION`, `AGENT_OTP_PAUSE`, `AGENT_ADDRESS_PAUSE` (line 86), `ProposedStep`, `check_steps` (line 273; the `customer_not_active` handoff runs first, lines 288–295), `otp_pause_update`, `address_pause_update`, `cancel_open_plan` (line 355), `issue_stored_plan` (line 364; reads `step["card_id"]`), `propose_plan` (line 398), `_rejected` (prints `step.card or 'claim'`)). `agent/step_up.py` (`agent_step_up`, `agent_address` (line 135, the analogue for the form node), `_CLEARED`, `_otp_again`, `_plan_issued`; line ~130 rebuilds `agent_plan_result.steps` as `{action, card_id}`). `agent/confirm.py` (`agent_plan`, `_accept`, `_decline`, `_CLEARED` line 58). `agent/node.py` `_PROMPT = PromptRef("agent", 4)` (line 75). `agent/reads.py` `scope_facts` (line ~320) has a `new_card_not_available` branch.
- `state.py`: `Pending.awaiting_slot: str | None`; `AgentPlanStep` (line 270: `action` Literal of five, `card_id: str`, `address_ref: NotRequired[str]`); `TurnState` (line 284). `graph.py`: `TurnInput` (line 163; `resume: Literal["step_up","step_up_cancel","step_up_failed"]`), `_entry` (lines ~340–380), `_agent_pause` (line 382), `_after_agent_pause`, `_dispatch`, lazy agent imports (line 916), node registration (line ~978), baseline map (line 1074, agent nodes → `smalltalk`), `run_turn` (line 1259).
- `runner.py`: `start_turn(host, *, session, conversation_id, trace_id, text, resume, confirmation, selection, card_selection)`, `checkpointed_otp_pause` (line 303, the analogue for the form gate), the `agent_ran` node tuple (line ~467).
- `confirmation_token_id: None` is cleared at: `takeover.py:79` (`return_to_bot`), `agent/plan.py:355`, `agent/step_up.py:37`, `agent/confirm.py:58`, `nodes/handoff.py:233`, `nodes/step_up_exit.py:35` and `:56`, `nodes/smalltalk.py:123`, `agent/dispute.py:67`.
- Pipeline C7 paths: `nodes/abstain.py` `_abstain` (line 109) looks up `get_policies().scope.topics[topic]` (a `KeyError` once `new_card` leaves scope) and returns `new_card_not_available` with no chip; the human chip is `QuickRepliesEvent(slot="abstain", options=[PickerOption(label=_HUMAN_OFFERS[...])])`. `baseline/template_compose.py:34` `baseline_abstain = make_abstain(llm_wording=False)`. `nodes/unsupported.py` gives `unsupported_intent` to any queued intent with no node; `intents.yaml` line 28 has `card_cancel` `node: null, tier: stretch`.
- Served classifier `intent_clf@v4` has **no** `new_card` and **no** `card_cancel` label. With the LLM down, the agent's `LLMError` turns the turn `degraded`, `_routes_to_agent` is false, and `understand` uses the classifier (or `llm_unavailable` → `fallback` without one). Nothing on that path can tell a card request apart today (decided in Q2). The agent's `LLMError` branch (`agent/node.py` lines ~425–457) returns `degraded: True` with no segments, and `graph.py` `_after_agent` then sends the turn to `understand`. If that branch returns segments instead, `_after_agent` ends the turn at `finish`. So the Q2 check fits inside `node.py`, and `graph.py` needs no change. A turn with `LLM_DISABLED` never enters the agent (`_routes_to_agent` is false), so it keeps today's pipeline behaviour.
- `tests/unit/test_registry_consistency.py`: line ~66 lists the `Topic` literal (unchanged by this card); `_NOT_YET_TRAINED = {"new_card"}` (line 98) excludes a scope topic from the training-data check. `tests/unit/test_abstain_warm.py` `test_new_card_not_replacement` pins today's `new_card_not_available` reply with no chip. `tests/unit/test_templates.py` lists every template key explicitly (line ~40). No eval scenario uses `new_card` or `card_cancel`.
- Unit harness (`backend/tests/conftest.py`): `make_session(customer_id, fakebank_dir, llm, *, otp_code, raw_writes, ...)` builds one `FakeBankOverlay()` shared by `FakeBank`/`FakeBankWrites`, `ConfirmedWriteTools`, `build_graph(MemorySaver())`; `Session.overlay`, `.handoff_tools.created`, `.store`; `ScriptedLLM` (`llm.calls`), `AgentScript(rounds, finals)`, `agent_on`, `run_recorded_turn`, `RecordingAudit`. The R3 analogue is `test_r3_unverified_claim_is_replaced` in `tests/unit/test_agent_confirmation.py` (`raw_writes=` a subclass whose write returns `verified=False`).
- Fixture customers (`tests/fixtures/fakebank`): `CLI-TFMULTI00001` (MX, Active, cards `PRD-TFM1CRED0001` credit USD balance 1234.50 limit 5000 last4 6475, `PRD-TFM1DEBT0002` debit 850.00 last4 1203, `PRD-TFM1DEBT0003` debit Closed), `CLI-TFINACT00004` (CO, Inactive), `CLI-TFPASTD00005` (AR, `PRD-TFP5CRED0001` with `days_past_due` 30). No fixture customer is at a card cap.
- Frontend: flat i18n keys in `frontend/src/lib/i18n/{es,pt}.json` (`confirm.steps.<summary_key>` lines 85–89, `staff.queue.*` lines 124–127). `components/chat/ConfirmCard.tsx` renders `t("confirm.steps.<summary_key>")` plus the code-built facts. `components/chat/ChatView.tsx` handles `otp_required` (lines ~166, ~299). `lib/sse.ts` registers named `EventSource` listeners (`status`, `message`, `ui`, …) and declares a `Queue` type (line 59). `lib/api.ts` wraps the OTP resume posts (lines ~326, ~341). `components/home/queries.tsx`: `CARDS_KEY = ["home","cards"]`, `cardKey(id) = ["home","card",id]`. `components/staff/queueStyles.ts` (`QUEUE_BAR`/`QUEUE_CHIP: Record<HandoffSummary["queue"], string>`) and `ConversationFilters.tsx` (`Queue`, `QUEUES`, lines 8/42) break the typecheck as soon as the generated `Queue` gains values. `routes/staff/handoffs.$handoffId.tsx` has the return button (`data-testid="return-handoff"`). UI kit: `components/ui/{button,card,dialog,input,label,select}`. No email-validator dependency exists (validate with a regex).

**Interfaces fixed by this plan** (names only; behaviour is the spec's)

- **I1 Policy:** `app/domains/policy/card_requests.py` exports `CardRequestsPolicy` and `load_card_requests_policy(path=None)`; `registry.py` exposes it as `get_policies().card_requests`. Money fields are `Decimal`.
- **I2 Queues, reasons, packet:** `Queue` += `"creditos"`, `"retencion"`; `HandoffReason` += `"card_open_request"`, `"card_close_request"` (also in `_REQUIRED_REASONS`); `handoff/schemas.py` `CardRequestBlock{request_id: UUID, reference: str, kind: Literal["open","close"], card_kind: Literal["credit","debit"], card_mask: str | None, reason_code: str | None}` and `HandoffPacket.card_request: CardRequestBlock | None = None`.
- **I3 Preconditions:** `request_eligible: bool | None = None`, `closure_pending: bool | None = None`, `reason_in_policy: bool | None = None`.
- **I4 Messages:** new `app/domains/conversation/card_request_messages.py`: `render_decision(decision, language, *, last4, currency, country, card_kind, credit_limit: Decimal | None = None, balance: Decimal | None = None) -> str`; `cancel_reason_label(code, language)`; `profile_field_label(field, language)`; `async announce_decision(conversation_id, *, verified, decision, text, agent_display_name) -> UUID | None` (posts through `takeover.relay_agent_message`, then publishes `cards_changed {}` through `core.events.publish` for `approve`/`cancel`; does nothing and returns `None` when `verified` is false).
- **I5 Migration:** `0011_card_requests.py`, `revision = "0011"`, `down_revision = "0010"`, with a working `downgrade()`.
- **I6 Vault:** `InMemoryPiiVault` (so also `PostgresPiiVault`) gains `async stage_form_values(values: Mapping[str, str]) -> None` (stores and persists) and `async form_values(fields: Sequence[str]) -> dict[str, str]` (the latest staged value per field; a field never staged is absent). Field names are the `ProfileField` strings. The values are keyed as Q1 decides (see "Decisions by the human").
- **I7 Customers:** `customers/schemas.py`: `ProfileField = Literal["email","mobile_phone","address","occupation","estimated_monthly_income"]`, `ProfileValues` (the five, income as `Decimal`), `ProfileFormView` (§5 shape, plus `income_currency`), `DecisionProfile` (credit score, segment, tenure years, occupation, income, country). `customers/service.py`: `get_profile_values(customer_id)`, `get_profile_form(customer_id, language)` (document masked as the login hint, `identity/service.py:395`), `changed_fields(customer_id, submitted: ProfileValues) -> list[ProfileField]`, `apply_profile_changes(conn, customer_id, changes: Mapping[ProfileField, str], *, actor, conversation_id, card_request_id)` (updates `bank.customers` and writes one `app.customer_profile_history` row per field, Fernet via `safety.vault.encrypt_text`, on the caller's connection), `get_decision_profile(customer_id)`, `changed_fields_for_request(card_request_id) -> set[ProfileField]`.
- **I8 Cards (requests):** `cards/schemas.py` `CardRequestView` (row of `app.card_requests`), `CardRequestPanel` and its parts (§5), `CardRequestDecision` (request body), `CardRequestDecisionResult{request, verified, message_id: UUID | None}`. `cards/service.py`: `create_open_request(customer_id, conversation_id, card_kind, changes, *, idempotency_key) -> CardRequestView` (one transaction calling `customers.service.apply_profile_changes`; a duplicate `idempotency_key` re-reads and returns the existing row), `read_back_open_request(request_id) -> tuple[CardRequestView, ProfileValues]`, `get_request(request_id)`, `pending_requests(customer_id) -> list[CardRequestView]`, `build_panel(request_id, language)`, `decide_request(request_id, agent_id, body, *, decision_key, before_write) -> DecisionOutcome` (exceptions `AlreadyDecided`, `DecisionNotAllowed`, `LimitRequired`, `LimitOutOfBounds`, `DeclineReasonInvalid`, `BalanceNotZero`; a replayed `decision_key` returns the stored outcome with `replayed=True`); close only: `create_close_request(customer_id, conversation_id, card_id, reason_code, *, idempotency_key)`, `read_back_close_request(request_id)`. Reference = `"CRQ-" + secrets.token_hex(4).upper()`.
- **I9 Write tools:** `tools/write.py` `PendingCardRequests` dataclass `{open_pending: bool, close_card_ids: frozenset[str]}`; `BankWriteTools` += `request_card(kind, changed_fields, *, idempotency_key) -> ActionResult`, `pending_card_requests() -> PendingCardRequests`, and (close) `request_closure(card_id, reason, *, idempotency_key) -> ActionResult`. `ConfirmedWriteTools` += `request_card(kind, changed_fields, token_id)`, `request_closure(card_id, reason, token_id)` (through `_run`), and `pending_card_requests()` (audited read, tool name `cards.pending_card_requests`, no allowlist). Read-backs are the spec's plus `request_id` (both) and `card_id`, `card_kind`, `last4` (close).
- **I10 Fake overlay:** `FakeBankOverlay` += `vault: InMemoryPiiVault`, `card_requests: dict[UUID, dict[str, Any]]`, `profile: dict[str, str]` (overrides of fixture values), `profile_history: list[dict[str, Any]]`. Tests stage form values with `await session.overlay.vault.stage_form_values({...})`.
- **I11 Agent state and graph:** `AGENT_PROFILE_FORM_PAUSE = {"flow": "agent", "node": "profile_form", "awaiting_slot": "profile_form"}` in `agent/plan.py`. `AgentPlanStep.action` += `"open"` (and `"close"`); `card_id` becomes `NotRequired[str]`; `kind: NotRequired[Literal["credit","debit"]]`, `reason: NotRequired[str]`. `TurnState` += `card_request_kind: NotRequired[Literal["credit","debit"] | None]`, `profile_changed_fields: NotRequired[list[str] | None]` (`None` before the form). `TurnInput.resume`, `run_turn(resume=...)` and `start_turn(resume=...)` += `"profile_form"`, `"profile_form_cancel"`; `TurnInput`/`run_turn`/`start_turn` += `form_changed_fields: list[str] | None = None`. Node `agent_profile_form` in new `agent/card_request.py`. `ui.py` `ProfileFormEvent(kind="profile_form", payload=ProfileFormPayload(card_kind))` in `UIEvent`. `runner.checkpointed_form_pause(host, conversation_id) -> bool` (true only with `AGENT_ENABLED` on). Labels: open → `_INTENT_BY_ACTION ("new_card", "card_request")`, summary key `request_card`; close → `("card_cancel", "card_request")`, summary key `request_closure`.
- **I12 Frontend i18n keys** (flat, ES and PT): `confirm.steps.request_card`, `confirm.steps.request_closure`, `staff.queue.creditos`, `staff.queue.retencion`; `profile_form.title.credit`, `profile_form.title.debit`, `profile_form.field.{email,mobile_phone,address,occupation,estimated_monthly_income,full_name,document,date_of_birth}`, `profile_form.income_hint` (`{currency}`), `profile_form.submit`, `profile_form.cancel`, `profile_form.error.{email,phone,required,income,load}`; `staff.card_request.{title,reference,kind.open,kind.close,status.pending,status.decided,credit_score,segment,tenure,occupation,income,changed,cards,close_balance,credit_limit,credit_bounds,reason}`, `staff.card_request.decision.{approve,decline,cancel,keep,not_cancelled_balance}`, `staff.card_request.decline_reason.{low_credit_score,insufficient_income,high_existing_debt,inconsistent_data,other}`, `staff.card_request.review.{title,confirm,back}`, `staff.card_request.error.{limit_out_of_bounds,limit_required,balance_not_zero,already_decided,decline_reason_invalid,generic}`, `staff.card_request.result.{verified,unverified}`, `staff.card_request.return_blocked`.

**Decisions by the human** (2026-10-04, binding on every task)

- **Q1, vault keying (T6):** each field gets its own form-only token kind: `PFEMAIL`, `PFPHONE`, `PFADDR`, `PFOCC`, `PFINCOME`. Every submit mints a fresh token for each staged field, and `form_values` returns the value of the newest token per field (the highest token number). These kinds stay **out of** `core/pii.py` `TOKEN_RE`, so chat text never unmasks them.
- **Q2, LLM-down detection (T27):** this is a code check, run on agent-path turns that can't use the LLM. It matches fixed ES and PT keyword lists in code, one for "new card" and one for "close/cancel card", or it sees an `open`/`close` plan already in progress. Either way the turn answers `card_request_unavailable` plus the human chip, opens no request and writes nothing. Spec T17's `llm_down-open` and `llm_down-close` cases stay. `graph.py` is not needed (see the classifier fact above), so T27 stays in W4.
- **Q3, unworded copy (T4, T9, T28, T30, T31):** implementers write the reason labels, field labels, i18n strings and queue colours against `docs/brand.md`, and the verifier gate reviews them.
- **Q4, cause group (T2):** `card_open_request` and `card_close_request` map to `by_design`.
- **Readings R-a to R-f:** all six are confirmed as written below. Under R-e, T5 edits `pipeline/load/postgres.py`.

**Readings confirmed by the human** (built as written)

- R-a: `app.card_requests.handoff_id` is written in the decision transaction, not at handoff creation (the bot's `tools/handoff.py` `create(packet)` stays unchanged). Routes find the request through `packet.card_request.request_id` and check that its `conversation_id` matches the handoff's.
- R-b: read-backs carry `request_id` (and for close `card_id`, `card_kind`, `last4`) on top of the spec's keys, so the packet block is built from the verified result without a cross-domain read.
- R-c: spec T14 "same response": the replayed call returns the stored `request` and `verified`; `message_id` is `null` on the replay because nothing is posted again.
- R-d: the baseline keeps `new_card_not_available` through `make_abstain(..., legacy_new_card=True)`; only the proposed pipeline shows `card_request_unavailable` and the human chip.
- R-e: `make data` gains the two new tables in its `TRUNCATE` list (a forced consequence of the 0011 FKs; outside the spec's touch map).
- R-f: the cap test (spec T7 `card_cap_reached`) patches `max_cards_per_kind.debit` to 1 for `CLI-TFMULTI00001` in the test instead of adding a fixture customer.

## Components

- **Policy** — `policies/card_requests.yaml` + `policy/card_requests.py` (I1); `tools.yaml` v6 + `tools_policy.py` (I3); `escalation.yaml` v10 + `escalation.py`; `scope.yaml` v3 + `scope.py`; `playbooks.yaml` v2. Depends on nothing.
- **Shared enums** — `localization/format.py` queues and labels, `identity/provision.py` names, `handoff/schemas.py` reasons and block (I2), `analytics/cause_groups.py`.
- **Storage** — migration 0011 (I5); `customers/*` profile reads, form view, profile writes with history (I7); `cards/*` request create, read-back, pending reads, panel, decision (I8). `pipeline/load/postgres.py` truncate list.
- **Vault** — `safety/vault.py` form-value staging (I6).
- **Write tools** — `tools/write.py`, `executor.py`, `fakebank.py`, `sandbox.py`, `postgres_writes.py` (I9, I10).
- **Agent** — `agent/plan.py` (actions, eligibility hook, form result, plan card facts), new `agent/card_request.py` (eligibility checks, `agent_profile_form`, packet block, close balance fact), `agent/confirm.py` (Acepto → handoff), `agent/step_up.py`, `state.py`, `ui.py`, `graph.py` (I11); prompt `agent@v5.md`, `agent/node.py`, `agent/reads.py`.
- **Pipeline C7** — `nodes/abstain.py`, `baseline/template_compose.py`, `nodes/unsupported.py`, `intents.yaml`.
- **Messages** — `templates.py` (seven keys), `card_request_messages.py` (I4).
- **API** — `api/v1/conversations.py` (profile-form routes, `form_required` gate) + `runner.py`; `api/v1/staff.py` (panel, decision, return gate).
- **Frontend** — `ProfileForm.tsx`, `ChatView.tsx`, `sse.ts`, `api.ts` (chat); `CardRequestPanel.tsx`, `handoffs.$handoffId.tsx` (staff); queue types; i18n (I12); generated client.
- **Docs** — `02`, `03`, `04`.

## Build order

1. Contracts with no dependency first, all at once (W1): policies, enums and packet schema, templates and the decision messages, the migration file, the vault staging, the customers functions, docs, i18n keys, the prompt. Everything later imports these names.
2. Storage and tool plumbing (W2): the cards open-request service needs the customers functions; the write protocol and fake need the vault; the pipeline abstain change needs the template.
3. The agent's open proposal, the postgres writer and the decision service (W3): each needs one W2 piece. The customer form API needs only W1 pieces and builds in W2.
4. The form pause node (needs the proposal and the runner's resume values), the staff API (needs the decision service), the close storage, the clearing sites, the LLM-down text (W4).
5. Acepto → handoff for opening, close tools, close decisions (W5).
6. One environment step, alone (W6): apply 0011 to golden and app, restart, regenerate the client, fix the queue types, P1.
7. Agent close and both frontends (W7): they need the generated client and the close tools.

## Touch map

| File | New/mod | Change | Tasks |
|---|---|---|---|
| `policies/card_requests.yaml` | new | §1 content | T1 |
| `backend/app/domains/policy/card_requests.py` | new | loader and validation | T1 |
| `backend/app/domains/policy/registry.py` | mod | `card_requests` | T1 |
| `policies/escalation.yaml` | mod | v10, two rules | T2 |
| `backend/app/domains/policy/escalation.py` | mod | `_REQUIRED_REASONS` | T2 |
| `backend/app/domains/localization/format.py` | mod | `Queue`, labels | T2 |
| `backend/app/domains/identity/provision.py` | mod | `_AGENT_NAMES` | T2 |
| `backend/app/domains/handoff/schemas.py` | mod | reasons, `CardRequestBlock`, packet field | T2 |
| `backend/app/domains/analytics/cause_groups.py` | mod | two reasons → `by_design` (Q4) | T2 |
| `policies/tools.yaml` | mod | v6, two tools | T3 |
| `backend/app/domains/policy/tools_policy.py` | mod | three `Preconditions` fields | T3 |
| `backend/app/domains/conversation/templates.py` | mod | seven keys | T4 |
| `backend/app/domains/conversation/card_request_messages.py` | new | I4 | T4 |
| `backend/app/alembic/versions/0011_card_requests.py` | new | §4 | T5 |
| `pipeline/load/postgres.py` | mod | truncate list | T5 |
| `backend/app/domains/safety/vault.py` | mod | I6 | T6 |
| `backend/app/domains/customers/{schemas,repository,service}.py` | mod | I7 | T7 |
| `docs/solution-docs/02-conversation-design.md`, `03-data-architecture.md`, `04-contracts.md` | mod | spec touch map "Docs" | T8 |
| `frontend/src/lib/i18n/{es,pt}.json` | mod | I12 | T9 |
| `backend/app/domains/conversation/prompts/agent@v5.md` | new | open action (T10), close action (T14) | T10, T14 |
| `policies/playbooks.yaml` | mod | v2: `card_open` (T10), `card_cancel` (T14) | T10, T14 |
| `backend/app/domains/conversation/agent/node.py` | mod | prompt v5 (T10); LLM-down text (T27) | T10, T27 |
| `backend/app/domains/conversation/agent/reads.py` | mod | drop the `new_card` branch | T10 |
| `policies/scope.yaml`, `backend/app/domains/policy/scope.py` | mod | v3, no `new_card` | T11 |
| `backend/app/domains/conversation/nodes/abstain.py`, `baseline/template_compose.py` | mod | C7 text + chip; baseline legacy | T11 |
| `backend/app/domains/cards/{schemas,repository,service}.py` | mod | I8 open (T12), decision (T18), close (T22, T26) | T12, T18, T22, T26 |
| `backend/app/domains/conversation/tools/{write,executor,fakebank}.py`, `conversation/sandbox.py` | mod | I9/I10 open (T13), close (T25) | T13, T25 |
| `backend/app/domains/conversation/tools/postgres_writes.py` | mod | open (T17), close (T25) | T17, T25 |
| `backend/app/domains/conversation/intents.yaml`, `nodes/unsupported.py` | mod | `card_cancel` core; C7 branch | T15 |
| `backend/app/domains/conversation/agent/plan.py` | mod | open (T16, T20), close (T29) | T16, T20, T29 |
| `backend/app/domains/conversation/state.py` | mod | I11 open (T16), close (T29) | T16, T29 |
| `backend/app/domains/conversation/ui.py` | mod | `ProfileFormEvent` | T16 |
| `backend/app/domains/conversation/agent/card_request.py` | new | checks (T16), form node (T20), block (T24), close (T29) | T16, T20, T24, T29 |
| `backend/app/api/v1/conversations.py`, `conversation/runner.py` | mod | form routes, gate, resume values | T19 |
| `backend/app/domains/conversation/graph.py`, `agent/step_up.py` | mod | form pause routing; step keys | T20 |
| `backend/app/api/v1/staff.py` | mod | panel, decision, return gate | T21 |
| `backend/app/domains/conversation/takeover.py`, `nodes/step_up_exit.py`, `nodes/smalltalk.py`, `agent/dispute.py` | mod | clear the new keys | T23 |
| `backend/app/domains/conversation/agent/confirm.py`, `nodes/handoff.py` | mod | Acepto → handoff, block, fact, clearing (T24); close (T29) | T24, T29 |
| `frontend/src/components/staff/queueStyles.ts`, `ConversationFilters.tsx`, `frontend/src/client/*.gen.ts` | mod | queues; regenerated client | T28 |
| `frontend/src/lib/sse.ts` | mod | `Queue` (T28); `cards_changed`, `profile_form` (T30) | T28, T30 |
| `frontend/src/components/chat/ProfileForm.tsx` | new | form widget | T30 |
| `frontend/src/components/chat/ChatView.tsx`, `frontend/src/lib/api.ts` | mod | form wiring, invalidation | T30 |
| `frontend/src/components/staff/CardRequestPanel.tsx` | new | panel + review dialog | T31 |
| `frontend/src/routes/staff/handoffs.$handoffId.tsx` | mod | mount panel; return disabled while pending | T31 |
| Tests (unit) | new/mod | `test_card_requests_policy.py` (T1), `test_card_request_messages.py` + `test_templates.py` (T4), `test_abstain_warm.py` + `test_registry_consistency.py` (T11), `test_card_requests_off_path.py` (T15, T27), `test_card_request_eligibility.py` (T16), `test_profile_form_r5.py` (T20), `test_card_request_open.py` (T24), `test_card_request_close.py` (T29) | |
| Tests (integration) | new/mod | `test_r13_ownership.py` (T19), `conftest.py` + `test_card_request_decision.py` (T21, T26) | |

## Risks and mitigations

- **`make data` breaks on the new FKs** (TRUNCATE refuses). → T5 adds both tables to the truncate list and checks it.
- **`KeyError: 'new_card'`** in `_abstain` and `scope_facts` once scope drops the topic. → T11 branches on the topic before the scope lookup; T10 removes the `reads.py` branch.
- **Baseline silently changes** if the new C7 text reaches `baseline_abstain`. → T11's `legacy_new_card=True` on the baseline instance; `test_abstain_warm.py` pins both.
- **`card_id` KeyError** in every `AgentPlanStep` reader once `open` has no card (`step_up.py:130`, `confirm.py:154/242`, `node.py:299/311`, `plan.py:369/371`). → T16 makes `card_id` `NotRequired` and mypy flags each reader; T16, T20, T24 branch them on `action` (their Files list the readers).
- **Form values leaking into the LLM, a UI payload or the checkpoint** (R5). → Values live only in the vault (I6); state holds field names; the UI event carries only `card_kind`; T20 writes spec T2 against all three sinks.
- **Form values unmasked into chat** if their vault kind is in `TOKEN_RE`. → Q1 decision: the form-only `PF*` kinds stay outside `TOKEN_RE`, and T6's Verify checks that `unmask` leaves them alone.
- **A write before Acepto** (R2): the API stages values in the vault only; `request_card` runs only through `_run` with a confirmation token. → spec T6 (T24) checks all three stores at each pause and after No acepto.
- **`customer_id` from the model** (R1): `request_card`/`request_closure` take no customer argument; the form routes use `get_owned_conversation`; the panel finds the customer through the request row. → spec T3 (T19), spec T11 (T21).
- **The open step's `customer_not_active` handoff** would fire before eligibility (`check_steps` lines 288–295). → T16 excludes `open` steps from that handoff (D9) and spec T7 covers the param.
- **Protocol drift**: `sandbox.py` `_RecordingWriteTools` and `postgres_writes.py` must implement every new `BankWriteTools` method, or mypy fails in the final check. → T13 (fake + sandbox), T17 (postgres), T25 (close, all five files).
- **Generated client lags the API**: `make client` before T21 would miss the panel. → T28 runs after every API task and is alone.
- **Queue literal breaks the typecheck** in `queueStyles.ts`/`ConversationFilters.tsx`. → T28 fixes both in the same task as `make client`.
- **Staff decision double-write** on a retried click. → unique `decision_key` + row lock (T18); spec T14 (T21).
- **A message before a verified read-back** (R3). → `announce_decision` checks `verified` (T4, spec T15); the route calls it only after `decide_request`'s read-back (T21).
- **The LLM-down C7 path has no classifier label to rely on.** → Q2 decision: T27 adds a keyword and plan-state check in the agent's `LLMError` branch. The flag-off half of spec T17 is built in T15.

## Tests

| Spec test | Task | File |
|---|---|---|
| spec T1 `test_card_requests_policy_loads` | T1 | `backend/tests/unit/test_card_requests_policy.py` |
| P1 (make check, seed-identity, logins) | T28 (logins); verifier (`make check`) | — |
| spec T2 `test_profile_form_values_never_reach_llm_ui_or_checkpoint` | T20 | `backend/tests/unit/test_profile_form_r5.py` |
| spec T3 `test_profile_form_cross_customer_404` | T19 | `backend/tests/integration/test_r13_ownership.py` |
| spec T4 `test_open_credit_es_happy` | T24 | `backend/tests/unit/test_card_request_open.py` |
| spec T5 `test_open_debit_pt_happy` | T24 | same |
| spec T6 `test_open_nothing_written_before_accept` | T24 | same |
| spec T7 `test_open_failed_check_no_handoff[4]` | T16 | `backend/tests/unit/test_card_request_eligibility.py` |
| spec T8 `test_request_card_unverified_readback` | T24 | `backend/tests/unit/test_card_request_open.py` |
| spec T9 `test_close_es_happy` | T29 | `backend/tests/unit/test_card_request_close.py` |
| spec T10 `test_close_pt_nonzero_balance_happy` | T29 | same |
| spec T11 `test_decision_non_claimant_refused` | T21 | `backend/tests/integration/test_card_request_decision.py` |
| spec T12 `test_decision_limit_out_of_bounds` | T21 | same |
| spec T13 `test_cancel_nonzero_balance_writes_nothing` | T26 | same |
| spec T14 `test_decision_idempotency_key_writes_once` | T21 | same |
| spec T15 `test_decision_message_only_after_verified_readback` | T4 | `backend/tests/unit/test_card_request_messages.py` |
| spec T16 `test_decision_templates_fill_in_code[es, pt]` | T4 | same |
| P2, P3 (browser) | verifier | — |
| spec T17 `test_card_requests_off_path[flag_off-open, flag_off-close]` | T15 | `backend/tests/unit/test_card_requests_off_path.py` |
| spec T17 `[llm_down-open, llm_down-close]` | T27 | same |

## Verification map

| Success criterion | Proven by |
|---|---|
| 1 C1: `make check` 0; provenance header; staff logins and `/staff/me` queues; no `new_card` in scope; fresh-DB tables and columns | verifier `make check AGENT_ENABLED=false`; T1 Verify; T28 Verify (P1); T11 Verify; T5 Verify |
| 2 C2: spec T2, T3 | T20, T19 |
| 3 C3: spec T4–T8 | T24, T16 |
| 4 C4: spec T9, T10 | T29 |
| 5 C5: spec T11–T15 | T21, T26, T4 |
| 6 C6: spec T16; P2, P3 | T4; verifier in the browser (`AGENT_ENABLED=true`, persona per spec "Open questions") after T30, T31 |
| 7 C7: spec T17; legacy and baseline tests unchanged | T15, T27; verifier's full run |
| 8 Docs | T8 |

## Cut line ("If behind": opening only, needs the human's go, spec Boundaries)

Tasks marked **[close]** belong only to C4 and its parts of C5/C6: **T14, T22, T25, T26, T29**. Dropping them leaves opening complete. What stays inert after the cut: the `cards.request_closure` line in `tools.yaml` v6 and its three `Preconditions` fields (T3; `allowed_intents: []`, and no executor method answers it), the `close` decisions in the panel's request schema (they get `422 decision_not_allowed` on an open request), the three close templates (still tested by spec T16), and queue `retencion` with Andrés (C1). Spec tests dropped by the cut: T9, T10, T13, and P3.

## Tasks

- [ ] T1: Policy `card_requests.yaml` v1, its loader and spec T1
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → 1 (the `card_requests.yaml` block and the "Validation" sentence); `backend/app/domains/policy/disputes.py` (the loader to mirror: provenance check, decimal strings); `backend/app/domains/policy/registry.py`
  - Acceptance:
    - `policies/card_requests.yaml` is the §1 block verbatim, starting with `provenance: team-generated-synthetic`.
    - `policy/card_requests.py` exports `CardRequestsPolicy` and `load_card_requests_policy(path=None)` (I1). It refuses a file with no provenance header, a country without a currency or rate, a currency without bounds, `min >= max`, and a reason list that is empty or lacks `other`.
    - `get_policies().card_requests` returns it, and the registry's hash covers the file as it covers the others.
    - `test_card_requests_policy.py` has `test_card_requests_policy_loads`: the real file loads; copies under `tmp_path` without provenance and with `min >= max` raise at load.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_requests_policy.py tests/unit/test_policy_registry.py -q && uv run ruff check app/domains/policy/card_requests.py app/domains/policy/registry.py tests/unit/test_card_requests_policy.py && uv run ruff format --check app/domains/policy/card_requests.py app/domains/policy/registry.py tests/unit/test_card_requests_policy.py && uv run mypy app/domains/policy/card_requests.py app/domains/policy/registry.py --follow-imports=silent`
  - Files: `policies/card_requests.yaml`, `backend/app/domains/policy/card_requests.py`, `backend/app/domains/policy/registry.py`, `backend/tests/unit/test_card_requests_policy.py`

- [ ] T2: Queues `creditos`/`retencion`, the two handoff reasons, the packet block, `escalation.yaml` v10, staff names
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → 1 (the `escalation.yaml` v10 sentence), 6 and 7; `backend/app/domains/handoff/schemas.py` (`HandoffReason`, `HandoffPacket`); `backend/app/domains/localization/format.py` (`Queue`, `_QUEUE_LABELS`)
  - Acceptance:
    - `Queue` gains `creditos` and `retencion`; `_QUEUE_LABELS` gives ES "Créditos"/"Retención" and PT "Crédito"/"Retenção".
    - `_AGENT_NAMES` gains `"creditos": "Valentina"`, `"retencion": "Andrés"`.
    - `HandoffReason` gains `card_open_request`, `card_close_request`; `CardRequestBlock` and `HandoffPacket.card_request` exist exactly as I2.
    - `escalation.yaml` is `version: 10` with `rules.card_open_request: {queue: creditos, priority: normal}` and `rules.card_close_request: {queue: retencion, priority: normal}`; both reasons are in `_REQUIRED_REASONS`.
    - `CAUSE_GROUPS` maps both reasons to `by_design` (Q4 decision).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_escalation_rules.py tests/unit/test_policy_registry.py -q && uv run python -c "from app.domains.policy.registry import get_policies as g; r=g().escalation.rules; assert r['card_open_request'].queue=='creditos' and r['card_close_request'].queue=='retencion'" && uv run ruff check app/domains/localization/format.py app/domains/identity/provision.py app/domains/handoff/schemas.py app/domains/policy/escalation.py app/domains/analytics/cause_groups.py && uv run ruff format --check app/domains/localization/format.py app/domains/identity/provision.py app/domains/handoff/schemas.py app/domains/policy/escalation.py app/domains/analytics/cause_groups.py && uv run mypy app/domains/localization/format.py app/domains/identity/provision.py app/domains/handoff/schemas.py app/domains/policy/escalation.py app/domains/analytics/cause_groups.py --follow-imports=silent` (if `rules` is not a dict keyed by reason, adapt the `python -c` to the real shape and note it in the task log)
  - Files: `backend/app/domains/localization/format.py`, `backend/app/domains/identity/provision.py`, `backend/app/domains/handoff/schemas.py`, `policies/escalation.yaml`, `backend/app/domains/policy/escalation.py`, `backend/app/domains/analytics/cause_groups.py`

- [ ] T3: `tools.yaml` v6 and the three `Preconditions` fields
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → 1 (the `tools.yaml` v6 block and the paragraph after it); `backend/app/domains/policy/tools_policy.py` (`Preconditions`); `policies/tools.yaml`
  - Acceptance:
    - `tools.yaml` is `version: 6` and adds the two lines of §1 verbatim.
    - `Preconditions` gains `request_eligible`, `closure_pending`, `reason_in_policy` (I3), each documented in the class docstring with the rejection code §1 gives it.
    - `has_preconditions("cards.request_card")` and `has_preconditions("cards.request_closure")` are true; `step_up_rule` says `always` for both; `tool_allowed` refuses both for every pipeline intent.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_r2_confirmation_store.py tests/unit/test_policy_registry.py -q && uv run python -c "from app.domains.policy.registry import get_policies as g; from app.domains.policy.tools_policy import has_preconditions as h; p=g().tools; assert h(p,'cards.request_card') and h(p,'cards.request_closure')"` (adapt the `has_preconditions` call to its real signature) `&& uv run ruff check app/domains/policy/tools_policy.py && uv run ruff format --check app/domains/policy/tools_policy.py && uv run mypy app/domains/policy/tools_policy.py --follow-imports=silent`
  - Files: `policies/tools.yaml`, `backend/app/domains/policy/tools_policy.py`

- [ ] T4: The seven templates, the decision messages module, spec T15 and T16
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → 8 and the "Steps" paragraph of 5 (step 5); `backend/app/domains/conversation/takeover.py` (`relay_agent_message`); `backend/app/domains/localization/format.py` (`format_money`, `mask_card`)
  - Acceptance:
    - `templates.py` gains the seven §8 keys with the ES/PT text verbatim, in `TemplateKind` and `_TEMPLATES`; `test_templates.py`'s key list gains them.
    - `card_request_messages.py` implements I4. `render_decision` fills `{card_mask}` with `mask_card(last4)` and `{credit_limit}`/`{balance}` with `format_money(..., currency, country)`; `approve` picks `_debit`/`_credit` by `card_kind`. `cancel_reason_label` covers the six `cancel_reasons` codes and `profile_field_label` the five fields, ES and PT, per `docs/brand.md` (Q3 decision, reviewed at the verifier gate). It reads no policy value except to know the codes.
    - `announce_decision` returns `None` and calls nothing when `verified` is false; when true it calls `relay_agent_message` once and, only for `approve`/`cancel`, `publish(conversation_id, "cards_changed", {})`.
    - `test_card_request_messages.py`: `test_decision_message_only_after_verified_readback` (monkeypatch `relay_agent_message` and `publish` in the module; unverified → no call; verified approve → one relay and one `cards_changed`; verified `keep` → relay only) and `test_decision_templates_fill_in_code[es, pt]` (all six decision templates render for an MX USD card and a CO COP card; no `{`/`}` left; the mask and amounts equal the formatters' output).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_request_messages.py tests/unit/test_templates.py -q && uv run ruff check app/domains/conversation/templates.py app/domains/conversation/card_request_messages.py tests/unit/test_card_request_messages.py tests/unit/test_templates.py && uv run ruff format --check app/domains/conversation/templates.py app/domains/conversation/card_request_messages.py tests/unit/test_card_request_messages.py tests/unit/test_templates.py && uv run mypy app/domains/conversation/card_request_messages.py app/domains/conversation/templates.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/templates.py`, `backend/app/domains/conversation/card_request_messages.py`, `backend/tests/unit/test_card_request_messages.py`, `backend/tests/unit/test_templates.py`

- [ ] T5: Migration `0011_card_requests.py` and the `make data` truncate list
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → 4; `backend/app/alembic/versions/0005_handoffs_staff.py` (FK and schema style); `pipeline/load/postgres.py` lines 60–72
  - Acceptance:
    - `0011_card_requests.py` (I5) creates exactly §4: the three `bank.products` columns, `app.card_requests` with its CHECKs, uniques and the two partial unique indexes, `app.customer_profile_history` with its CHECK and the `(customer_id, at desc)` index. `downgrade()` drops all of it.
    - `copy_all`'s `truncate_targets` also lists `app.card_requests` and `app.customer_profile_history`.
    - The dev databases are not touched (T28 applies the migration).
  - Verify: `cd backend && docker exec latam-cs-postgres-1 psql -U postgres -qc 'create database latam_it_mig0011' && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_it_mig0011 sh -c 'uv run alembic upgrade head && uv run alembic downgrade 0010 && uv run alembic upgrade head' && test "$(docker exec latam-cs-postgres-1 psql -U postgres -d latam_it_mig0011 -tAc "select count(*) from information_schema.columns where (table_schema='bank' and table_name='products' and column_name in ('origin','created_at','conversation_id')) or (table_schema='app' and table_name in ('card_requests','customer_profile_history') and column_name='id')")" = 5; rc=$?; docker exec latam-cs-postgres-1 psql -U postgres -qc 'drop database if exists latam_it_mig0011'; test $rc -eq 0 && grep -q 'app.card_requests' ../pipeline/load/postgres.py && grep -q 'app.customer_profile_history' ../pipeline/load/postgres.py && uv run ruff check app/alembic/versions/0011_card_requests.py ../pipeline/load/postgres.py && uv run ruff format --check app/alembic/versions/0011_card_requests.py`
  - Files: `backend/app/alembic/versions/0011_card_requests.py`, `pipeline/load/postgres.py`

- [ ] T6: Vault form-value staging (I6) with form-only token kinds
  - Depends on: nothing. Follow the Q1 decision under "Decisions by the human" in the plan, which is also seeded into the state file.
  - Read exactly these: `backend/app/domains/safety/vault.py`; `backend/app/core/pii.py` (`TOKEN_RE`); spec AS5 and §"Contracts" → 5 (`POST /conversations/{id}/profile-form`)
  - Acceptance:
    - `stage_form_values` and `form_values` exist on `InMemoryPiiVault` with the I6 signatures and work on `PostgresPiiVault` after its load (persisted rows, encrypted as today).
    - Staging the same field twice returns the second value; a field never staged is absent; a staged value never appears in `mask(...)`/`unmask(...)` output for any chat text. Keying follows Q1:
      - each field has its own kind (`email`→`PFEMAIL`, `mobile_phone`→`PFPHONE`, `address`→`PFADDR`, `occupation`→`PFOCC`, `estimated_monthly_income`→`PFINCOME`);
      - every staged value mints a fresh token (no reuse for an equal value);
      - `form_values` returns, for each field, the value of its highest-numbered token;
      - `PostgresPiiVault._persist` stores the new kinds;
      - `core/pii.py` `TOKEN_RE` is not changed, so `unmask("⟨PFEMAIL_1⟩")` returns the text unchanged.
    - No existing vault behaviour changes.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_r5_masking.py -q && uv run python -c "import asyncio; from app.domains.safety.vault import InMemoryPiiVault as V
async def m():
    v=V(); await v.stage_form_values({'email':'a@b.co'}); await v.stage_form_values({'email':'c@d.co','occupation':'Docente'})
    assert await v.form_values(['email','occupation','address'])=={'email':'c@d.co','occupation':'Docente'}
    assert await v.unmask('x ⟨PFEMAIL_1⟩ ⟨PFEMAIL_2⟩') == 'x ⟨PFEMAIL_1⟩ ⟨PFEMAIL_2⟩'
asyncio.run(m())" && uv run ruff check app/domains/safety/vault.py && uv run ruff format --check app/domains/safety/vault.py && uv run mypy app/domains/safety/vault.py --follow-imports=silent`
  - Files: `backend/app/domains/safety/vault.py`

- [ ] T7: Customers: profile values, form view, profile writes with history, decision profile (I7)
  - Depends on: nothing (writes SQL against the 0011 tables named in spec §4; nothing runs it until T12/T19/T21)
  - Read exactly these: spec AS5, AS6, D6 and §"Contracts" → 4 (`app.customer_profile_history`) and 5 (`ProfileFormView`); `backend/app/domains/customers/service.py`; `backend/app/domains/identity/service.py` around line 395 (the login hint mask)
  - Acceptance:
    - Every I7 name exists with that signature. `apply_profile_changes` runs on the caller's `AsyncConnection` (no commit of its own), updates only the changed `bank.customers` columns and writes one history row per changed field with `old_value_enc`/`new_value_enc` from `safety.vault.encrypt_text`.
    - `get_profile_form` shows the document masked as the login hint, the date of birth formatted in code, and `income_currency` from the customer's country (MXN/COP/ARS, AS6).
    - `changed_fields` compares normalised values (trimmed strings, `Decimal` income) and returns fields in the I7 order.
    - `customers` imports no other domain's repository; `lint-imports` passes.
  - Verify: `cd backend && uv run python -c "import app.domains.customers.service as s; [getattr(s,n) for n in ('get_profile_values','get_profile_form','changed_fields','apply_profile_changes','get_decision_profile','changed_fields_for_request')]" && uv run lint-imports && uv run ruff check app/domains/customers && uv run ruff format --check app/domains/customers && uv run mypy app/domains/customers --follow-imports=silent`
  - Files: `backend/app/domains/customers/schemas.py`, `backend/app/domains/customers/repository.py`, `backend/app/domains/customers/service.py`

- [ ] T8: Docs `02`, `03`, `04`
  - Depends on: nothing
  - Read exactly these: spec §"Touch map" → "Docs" and §"Contracts" (all of it); the named sections of `docs/solution-docs/02-conversation-design.md`, `03-data-architecture.md`, `04-contracts.md`
  - Acceptance:
    - `02` §1 (`card_cancel` tier core; `new_card` no longer an abstain), §3 (pause `agent/profile_form`), §5 (`creditos`/`retencion` no longer Stretch; the `card_request_unavailable` text), §6 (the decision panel).
    - `03` §6: 0011 tables and columns; staff names Valentina/Andrés.
    - `04` §1 (`propose_plan` `open`/`close`, `cards.request_card`, `cards.request_closure`), §3 (both profile-form routes, the `form_required` gate, the two staff routes, the return `409 request_undecided`, SSE `cards_changed` and `ui profile_form`), §4 (two reasons, `card_request` block, `card_request_filed`), §5 (`card_requests.yaml`, `tools.yaml` v6, `escalation.yaml` v10, `scope.yaml` v3, `playbooks.yaml` v2).
    - Contract text copies the spec; it does not reword a value.
  - Verify: `grep -c 'profile_form' docs/solution-docs/02-conversation-design.md docs/solution-docs/04-contracts.md && grep -c 'customer_profile_history' docs/solution-docs/03-data-architecture.md && grep -c 'cards_changed\|request_undecided\|card_request_filed\|request_closure' docs/solution-docs/04-contracts.md` (every count ≥ 1)
  - Files: `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/03-data-architecture.md`, `docs/solution-docs/04-contracts.md`

- [ ] T9: Frontend i18n keys (I12)
  - Depends on: nothing
  - Read exactly these: this plan's "Interfaces fixed by this plan" → I12; `docs/brand.md`; `frontend/src/lib/i18n/es.json` lines 80–130
  - Acceptance:
    - Every I12 key exists in both `es.json` and `pt.json`, with brand-voice text (Q3 decision, reviewed at the verifier gate). `staff.queue.creditos`/`retencion` are "Créditos"/"Retención" (ES) and "Crédito"/"Retenção" (PT). Decline-reason labels are staff-only wording.
    - No existing key changes. Both files stay valid JSON with the same key set.
  - Verify: `cd frontend && node -e "const a=require('./src/lib/i18n/es.json'),b=require('./src/lib/i18n/pt.json');const ka=Object.keys(a).sort().join(),kb=Object.keys(b).sort().join();if(ka!==kb)process.exit(1);for(const k of ['confirm.steps.request_card','confirm.steps.request_closure','staff.queue.creditos','staff.queue.retencion','profile_form.submit','staff.card_request.decision.not_cancelled_balance','staff.card_request.return_blocked'])if(!(k in a))process.exit(2)" && npx biome check src/lib/i18n/es.json src/lib/i18n/pt.json`
  - Files: `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`

- [ ] T10: Prompt `agent@v5` (open action), playbook `card_open`, node and reads wiring
  - Depends on: nothing
  - Read exactly these: spec D2, D3, D9, §"Contracts" → 1 (the `playbooks.yaml` v2 sentence) and 2, §"Boundaries" → "Never"; `backend/app/domains/conversation/prompts/agent@v4.md`; `policies/playbooks.yaml`
  - Acceptance:
    - `agent@v5.md` is `agent@v4.md` (title `agent@v5`) plus: `propose_plan` action `open` with `kind` (`credit`/`debit`) and no `card`, standing alone (`request_alone`); results `accepted (form_required)` (the system shows a form; say so, never ask for the data in chat), `accepted (step_up_required)`, `rejected (open: <code>)` with `customer_not_active`, `card_past_due`, `card_cap_reached`, `request_pending` explained without promising anything and with no handoff offer. A new-card request is no longer passed or refused as out of scope. `agent@v4.md` is not edited.
    - `playbooks.yaml` is `version: 2` with `card_open` (Spanish, `>-`): ask debit or credit; the form, the OTP and the plan card come from the system; never promise approval or a limit. No policy value.
    - The prompt and playbook never contain a cap number, a bound, an interest rate, a decline reason or a queue name.
    - `node.py` uses `PromptRef("agent", 5)`. `reads.py` `scope_facts` loses the `new_card_not_available` branch.
  - Verify: `test -f backend/app/domains/conversation/prompts/agent@v5.md && grep -c '<<PLAYBOOKS>>' backend/app/domains/conversation/prompts/agent@v5.md && grep -n 'form_required' backend/app/domains/conversation/prompts/agent@v5.md && grep -n 'card_open:' policies/playbooks.yaml && ! grep -n -i 'creditos\|50000\|31\.5\|low_credit_score\|insufficient_income' backend/app/domains/conversation/prompts/agent@v5.md && git diff --quiet -- 'backend/app/domains/conversation/prompts/agent@v4.md' && cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_happy.py tests/unit/test_policy_registry.py -q && uv run ruff check app/domains/conversation/agent/node.py app/domains/conversation/agent/reads.py && uv run ruff format --check app/domains/conversation/agent/node.py app/domains/conversation/agent/reads.py && uv run mypy app/domains/conversation/agent/node.py app/domains/conversation/agent/reads.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/prompts/agent@v5.md`, `policies/playbooks.yaml`, `backend/app/domains/conversation/agent/node.py`, `backend/app/domains/conversation/agent/reads.py`

- [ ] T11: `scope.yaml` v3 without `new_card`, and the pipeline's C7 text for topic `new_card`
  - Depends on: T4 (template `card_request_unavailable`)
  - Read exactly these: spec D3 and §"Contracts" → 8 (row `card_request_unavailable`); `backend/app/domains/conversation/nodes/abstain.py`; `backend/tests/unit/test_abstain_warm.py` (`test_new_card_not_replacement`)
  - Acceptance:
    - `scope.yaml` is `version: 3` with no `new_card` key; `scope.py` `TOPICS` drops `new_card`.
    - `make_abstain` gains `legacy_new_card: bool = False`; `baseline_abstain = make_abstain(llm_wording=False, legacy_new_card=True)`.
    - In `_abstain`, topic `new_card` is handled before the scope lookup: legacy → the old `new_card_not_available` reply, no chip (baseline unchanged); otherwise → `card_request_unavailable` plus the human chip (the same `QuickRepliesEvent` the abstain uses for `offer_human`), no LLM call, no write. The chip-building lives in one helper that T15 imports (name it `card_request_unavailable_reply(language) -> dict[str, Any]` and record the real name in the task log).
    - `test_new_card_not_replacement` asserts the new text and the chip on the proposed node, and keeps a baseline assertion for the old text. `test_registry_consistency.py` drops `new_card` from `_NOT_YET_TRAINED` if the set must only list scope topics (keep the `Topic` literal tuple).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_abstain_warm.py tests/unit/test_abstain.py tests/unit/test_registry_consistency.py tests/unit/test_policy_registry.py -q && ! grep -n 'new_card' ../policies/scope.yaml && uv run ruff check app/domains/policy/scope.py app/domains/conversation/nodes/abstain.py app/domains/conversation/baseline/template_compose.py tests/unit/test_abstain_warm.py tests/unit/test_registry_consistency.py && uv run ruff format --check app/domains/policy/scope.py app/domains/conversation/nodes/abstain.py app/domains/conversation/baseline/template_compose.py tests/unit/test_abstain_warm.py tests/unit/test_registry_consistency.py && uv run mypy app/domains/policy/scope.py app/domains/conversation/nodes/abstain.py app/domains/conversation/baseline/template_compose.py --follow-imports=silent`
  - Files: `policies/scope.yaml`, `backend/app/domains/policy/scope.py`, `backend/app/domains/conversation/nodes/abstain.py`, `backend/app/domains/conversation/baseline/template_compose.py`, `backend/tests/unit/test_abstain_warm.py`, `backend/tests/unit/test_registry_consistency.py`

- [ ] T12: Cards domain: open-request storage and reads (I8, open part)
  - Depends on: T7 (`customers.service.apply_profile_changes`, `get_profile_values`); the 0011 table shapes from spec §4 (T5)
  - Read exactly these: spec AS4, AS7, D10 and §"Contracts" → 3 and 4; `backend/app/domains/cards/service.py`; this plan's I7 and I8
  - Acceptance:
    - `CardRequestView`, `create_open_request`, `read_back_open_request`, `get_request`, `pending_requests` exist with the I8 signatures. `create_open_request` writes the request (`kind='open'`, `status='pending'`, `changed_fields`, `idempotency_key`, `reference` `CRQ-` + 8 upper hex) and calls `apply_profile_changes` in the same `get_engine().begin()` transaction; a duplicate `idempotency_key` re-reads the stored row. A second pending open for the customer raises a typed error (`RequestPending`) from the partial unique index.
    - `read_back_open_request` re-reads the request and the customer's current profile values.
    - `pending_requests` lists the customer's `pending` rows of both kinds.
  - Verify: `cd backend && uv run python -c "import app.domains.cards.service as s; [getattr(s,n) for n in ('create_open_request','read_back_open_request','get_request','pending_requests')]" && uv run lint-imports && uv run ruff check app/domains/cards && uv run ruff format --check app/domains/cards && uv run mypy app/domains/cards --follow-imports=silent`
  - Files: `backend/app/domains/cards/schemas.py`, `backend/app/domains/cards/repository.py`, `backend/app/domains/cards/service.py`

- [ ] T13: Write protocol, executor, fake bank and sandbox: `request_card` and `pending_card_requests` (I9, I10)
  - Depends on: T6 (`InMemoryPiiVault.stage_form_values`/`form_values`)
  - Read exactly these: spec §"Contracts" → 3; `backend/app/domains/conversation/tools/executor.py` (`_run`, `get_block_origin`); `backend/app/domains/conversation/tools/fakebank.py` (`FakeBankOverlay`, `FakeBankWrites.order_replacement`)
  - Acceptance:
    - `write.py` gains `PendingCardRequests` and the two protocol methods; `ConfirmedWriteTools.request_card(kind, changed_fields, token_id)` goes through `_run` with tool `cards.request_card`; `pending_card_requests()` is an audited read (tool `cards.pending_card_requests`) like `get_block_origin`, without an allowlist check.
    - `FakeBankOverlay` gains the I10 fields. `FakeBankWrites.request_card` reads the changed values from `overlay.vault.form_values(changed_fields)`, applies them to `overlay.profile`, appends one `overlay.profile_history` entry per field, stores a pending open in `overlay.card_requests`, and returns an `ActionResult` with `tracking_id` = reference, `verified` true only if every changed value and the request read back equal what was written, and the I9 read-back. `pending_card_requests` reads `overlay.card_requests`. The fake's profile reads (if any) apply `overlay.profile` over the fixture.
    - `sandbox.py` `_RecordingWriteTools` implements both methods.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_fakebank_writes.py tests/unit/test_sandbox_conversations.py tests/unit/test_r2_confirmed_writes.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py && uv run ruff format --check app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py && uv run mypy app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/tools/write.py`, `backend/app/domains/conversation/tools/executor.py`, `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/conversation/sandbox.py`

- [ ] T14: [close] Prompt `agent@v5` close action and playbook `card_cancel`
  - Depends on: T10 (`agent@v5.md` and `playbooks.yaml` v2 exist)
  - Read exactly these: spec D4 and §"Contracts" → 1 (the `playbooks.yaml` v2 sentence) and 2; `backend/app/domains/conversation/prompts/agent@v5.md`; `policies/playbooks.yaml`
  - Acceptance:
    - `agent@v5.md` gains `propose_plan` action `close` (`card` required, `reason` one code from the list the tool description gives; ask when unclear, `other` as the fallback; stands alone); results `accepted (step_up_required)` with the `{close_balance}` fact, `rejected (<card>: already_in_state | closure_pending | invalid_reason)`. Cardy states the zero-balance condition and the balance only through `{close_balance}` and never promises a closure.
    - `playbooks.yaml` gains `card_cancel` (Spanish, `>-`): ask which card and why; state the zero-balance condition and the balance through `{close_balance}`; never promise. `version` stays 2.
    - Neither file contains a reason code list, a decline reason or a queue name.
  - Verify: `grep -n 'close_balance' backend/app/domains/conversation/prompts/agent@v5.md && grep -n 'card_cancel:' policies/playbooks.yaml && ! grep -n -i 'retencion\|no_longer_needed\|low_credit_score' backend/app/domains/conversation/prompts/agent@v5.md policies/playbooks.yaml && cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_policy_registry.py -q`
  - Files: `backend/app/domains/conversation/prompts/agent@v5.md`, `policies/playbooks.yaml`

- [ ] T15: `card_cancel` on the pipeline: intent row, `unsupported` C7 branch, spec T17 flag-off params
  - Depends on: T4 (template), T11 (the C7 reply helper in `nodes/abstain.py`, real name in the state file)
  - Read exactly these: spec D3, C7 row and §"Contracts" → 2 (the `intents.yaml` sentence); `backend/app/domains/conversation/nodes/unsupported.py`; `backend/tests/unit/test_abstain_warm.py` (a pipeline turn with a scripted NLU result)
  - Acceptance:
    - `intents.yaml` `card_cancel` row: `tier: core`, `node: null`; nothing else in the file changes.
    - `unsupported` answers a queued `card_cancel` (head of `intent_queue`, not an injection or language case) with T11's C7 helper: `card_request_unavailable` plus the human chip, no LLM call.
    - `test_card_requests_off_path.py` has `test_card_requests_off_path` parametrized with `flag_off-open` (NLU topic `new_card`) and `flag_off-close` (NLU intent `card_cancel`), `AGENT_ENABLED` off, fake LLM, customer `CLI-TFMULTI00001`: the reply is the template text, the chip is offered, `session.overlay.card_requests` is empty and no handoff exists. Leave a `# llm_down params: T27` marker where T27 adds two params.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_requests_off_path.py tests/unit/test_registry_consistency.py -q && uv run ruff check app/domains/conversation/nodes/unsupported.py tests/unit/test_card_requests_off_path.py && uv run ruff format --check app/domains/conversation/nodes/unsupported.py tests/unit/test_card_requests_off_path.py && uv run mypy app/domains/conversation/nodes/unsupported.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/intents.yaml`, `backend/app/domains/conversation/nodes/unsupported.py`, `backend/tests/unit/test_card_requests_off_path.py`

- [ ] T16: Agent: the `open` action, eligibility in code, `accepted (form_required)`, spec T7
  - Depends on: T1 (`get_policies().card_requests`), T3 (`request_eligible`), T13 (`pending_card_requests`, fake overlay)
  - Read exactly these: spec AS7, D2, D9 and §"Contracts" → 1 (the `request_eligible` order) and 2; `backend/app/domains/conversation/agent/plan.py` (`ProposedStep`, `check_steps`, `otp_pause_update`, `propose_plan`, `_rejected`); this plan's I11
  - Acceptance:
    - `state.py`: `AgentPlanStep` gains `"open"`, `card_id` becomes `NotRequired`, plus `kind`/`reason` (I11); `TurnState` gains `card_request_kind`, `profile_changed_fields`. Every reader of `step["card_id"]` that mypy flags in `plan.py` branches on `action` (`step_up.py`, `confirm.py`, `node.py` readers are fixed by T20/T24; leave a `# T20`/`# T24` note only if mypy passes on this task's paths).
    - `ui.py`: `ProfileFormPayload{card_kind}` and `ProfileFormEvent(kind="profile_form")` join `UIEvent`.
    - `plan.py`: `ProposedStep.action` += `"open"`, `kind` field; an `open` step with a `card`, or with any other step, is `rejected (open: request_alone)`; `_TOOL_BY_ACTION`/`_SUMMARY_BY_ACTION`/`_INTENT_BY_ACTION` per I11; `AGENT_PROFILE_FORM_PAUSE`; `_rejected` prints `open` for an open step; the `customer_not_active` handoff in `check_steps` skips `open` steps (D9).
    - `agent/card_request.py` (new): `check_open(kind, ...) -> str | None` runs, in order, `customer_not_active`, `card_past_due` (any non-Closed card with `days_past_due > 0`), `card_cap_reached` (non-Closed cards of `kind` ≥ `max_cards_per_kind[kind]`), `request_pending` (`pending_card_requests().open_pending`), reading only `get_policies()` and the read/write tools; `check_steps` calls it for `request_eligible: true`.
    - An accepted open plan: `cancel_open_plan`, then `box.pause(...)` with `agent_plan_steps=[{action: "open", kind}]`, `pending=AGENT_PROFILE_FORM_PAUSE`, `card_request_kind=kind`, `profile_changed_fields=None`, `ui=[ProfileFormEvent]`, `asked_ui` as `otp_pause_update` does, segments `plan_segments(steps, "awaiting", "profile_form")`; result `accepted (form_required)`.
    - `test_card_request_eligibility.py`: `test_open_failed_check_no_handoff[customer_not_active, card_past_due, card_cap_reached, request_pending]` with `agent_on` and a scripted `propose_plan(open)`: `CLI-TFINACT00004`, `CLI-TFPASTD00005`, `CLI-TFMULTI00001` with `max_cards_per_kind.debit` patched to 1 asking `debit`, and `CLI-TFMULTI00001` with a pending open seeded in `session.overlay.card_requests`. Each: the tool result contains `rejected (open: <code>)`, no handoff, no `profile_form` UI event, `overlay.card_requests`/`profile`/`profile_history` unchanged.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_request_eligibility.py tests/unit/test_agent_plan_check.py tests/unit/test_agent_unlock_replace.py -q && uv run ruff check app/domains/conversation/agent/plan.py app/domains/conversation/agent/card_request.py app/domains/conversation/state.py app/domains/conversation/ui.py tests/unit/test_card_request_eligibility.py && uv run ruff format --check app/domains/conversation/agent/plan.py app/domains/conversation/agent/card_request.py app/domains/conversation/state.py app/domains/conversation/ui.py tests/unit/test_card_request_eligibility.py && uv run mypy app/domains/conversation/agent/plan.py app/domains/conversation/agent/card_request.py app/domains/conversation/state.py app/domains/conversation/ui.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/plan.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/agent/card_request.py`, `backend/app/domains/conversation/ui.py`, `backend/tests/unit/test_card_request_eligibility.py`

- [ ] T17: Postgres writer: `request_card` and `pending_card_requests`
  - Depends on: T6 (`PostgresPiiVault.form_values`), T12 (`cards.service` open functions), T13 (protocol)
  - Read exactly these: spec D10 and §"Contracts" → 3; `backend/app/domains/conversation/tools/postgres_writes.py` (`order_replacement`: idempotency key, read-back, `verified`); this plan's I8 and I9
  - Acceptance:
    - `request_card(kind, changed_fields, *, idempotency_key)` loads `PostgresPiiVault(ctx.conversation_id)`, reads `form_values(changed_fields)` (a missing field is `verified=false`, nothing written), calls `cards.service.create_open_request` with `ctx.customer_id`, then `read_back_open_request`; `verified` only when every changed field and the request row match. `tracking_id` = reference; read-back per I9.
    - `pending_card_requests()` maps `cards.service.pending_requests(ctx.customer_id)` to `PendingCardRequests`.
    - No import of `customers.service`; `lint-imports` passes.
  - Verify: `cd backend && uv run lint-imports && AGENT_ENABLED=false uv run pytest tests/integration/test_postgres_writes.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/domains/conversation/tools/postgres_writes.py && uv run ruff format --check app/domains/conversation/tools/postgres_writes.py && uv run mypy app/domains/conversation/tools/postgres_writes.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/tools/postgres_writes.py`

- [ ] T18: Cards domain: the decision service (open decisions) and the panel (I8)
  - Depends on: T1 (`credit_limit_bounds`, `currency_by_country`, `interest_rate_by_country`, `expiry_years`, `decline_reasons`), T7 (`get_decision_profile`, `changed_fields_for_request`), T12 (request storage)
  - Read exactly these: spec AS3, AS4, AS8, D5, D12 and §"Contracts" → 4 and 5 (`CardRequestPanel`, decision errors, the five steps); `backend/app/domains/cards/service.py`; `backend/app/domains/cards/repository.py`
  - Acceptance:
    - `CardRequestPanel`, `CardRequestDecision{decision: Literal[5], credit_limit: str | None, decline_reason: str | None}`, `CardRequestDecisionResult`, `build_panel` and `decide_request` exist (I8). The panel fills money and masks in code, `*_changed` from `changed_fields_for_request`, `credit_bounds` only for an open credit request, `close_balance_display` only for close.
    - `decide_request` locks the request row (`FOR UPDATE`), returns the stored outcome with `replayed=True` for a known `decision_key`, validates (`AlreadyDecided`, `DecisionNotAllowed` for close decisions on open and vice versa, `LimitRequired`/`LimitOutOfBounds` for credit approve, `DeclineReasonInvalid`), calls `before_write()`, then in one transaction writes: approve → a `bank.products` row per AS4 (`PRD-` + 12 upper alphanumerics, unique 16-digit Luhn `product_number`, `origin='app'`, `created_at`, `conversation_id`, `opening_channel='App'`, `opening_date`/`expiration_date` from `local_today` and `expiry_years`, currency and rate from policy, debit rate 0 and `credit_limit` NULL); decline → no bank row; and the request update (`status`, `decision`, `decline_reason`, `credit_limit`, `agent_id`, `decided_at`, `decision_key`, `handoff_id`, `product_id` on approve). Then it re-reads and sets `verified`.
    - Close decisions raise `DecisionNotAllowed` until T26 adds them.
  - Verify: `cd backend && uv run python -c "import app.domains.cards.service as s; [getattr(s,n) for n in ('build_panel','decide_request','AlreadyDecided','DecisionNotAllowed','LimitRequired','LimitOutOfBounds','DeclineReasonInvalid','BalanceNotZero')]" && uv run lint-imports && uv run ruff check app/domains/cards && uv run ruff format --check app/domains/cards && uv run mypy app/domains/cards --follow-imports=silent`
  - Files: `backend/app/domains/cards/schemas.py`, `backend/app/domains/cards/repository.py`, `backend/app/domains/cards/service.py`

- [ ] T19: Customer API: profile-form routes, the `form_required` gate, runner resume values, spec T3
  - Depends on: T6 (`stage_form_values`), T7 (`get_profile_form`, `get_profile_values`, `changed_fields`)
  - Read exactly these: spec D11 and §"Contracts" → 5 (the three conversation rows); `backend/app/api/v1/conversations.py` (the OTP gate lines ~287–294, `post_message`); `backend/app/domains/conversation/runner.py` (`checkpointed_otp_pause`, `start_turn`)
  - Acceptance:
    - `runner.py`: `checkpointed_form_pause` (I11; `pending.awaiting_slot == "profile_form"` and `flow == "agent"`, only with `AGENT_ENABLED` on); `start_turn` accepts `resume` `"profile_form"`/`"profile_form_cancel"` and `form_changed_fields`, and passes both into the graph input; the `agent_ran` node tuple gains `"agent_profile_form"`.
    - `GET /conversations/{id}/profile-form` (`get_owned_conversation`, `Cache-Control: no-store`, `409 form_not_open`) returns `ProfileFormView` for the session's customer.
    - `POST /conversations/{id}/profile-form` takes `{action: "submit", values}` (Pydantic: email regex, phone, non-empty address/occupation, income > 0) or `{action: "cancel"}`; submit computes `changed_fields`, stages only those in `PostgresPiiVault(conversation_id)`, and starts a turn with `resume="profile_form"`; cancel starts `resume="profile_form_cancel"`; `409 form_not_open`, `409 turn_in_progress`, `429 turn_cap_reached` as on `/messages`; `202 {turn_id}`. Neither value is accepted on `/messages` (the existing `PostMessageRequest.resume` Literal stays).
    - `/messages` with `text` at an open form pause → `409 form_required`, after the OTP gate.
    - `test_r13_ownership.py` gains `test_profile_form_cross_customer_404`: customer B's GET and POST on A's conversation get `404`; A's `bank.customers` row is unchanged.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/integration/test_r13_ownership.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && AGENT_ENABLED=false uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration/test_r13_ownership.py && uv run ruff format --check app/api/v1/conversations.py app/domains/conversation/runner.py tests/integration/test_r13_ownership.py && uv run mypy app/api/v1/conversations.py app/domains/conversation/runner.py --follow-imports=silent`
  - Files: `backend/app/api/v1/conversations.py`, `backend/app/domains/conversation/runner.py`, `backend/tests/integration/test_r13_ownership.py`

- [ ] T20: The form pause: `agent_profile_form`, graph routing, step-up hand-off, plan card facts, spec T2
  - Depends on: T13 (fake `request_card`, overlay vault), T16 (`AGENT_PROFILE_FORM_PAUSE`, open step, `ProfileFormEvent`, `agent/card_request.py`), T19 (`start_turn` resume values; the graph-input key name `form_changed_fields`)
  - Read exactly these: spec AS5, D11 and §"Contracts" → 2 (pause and plan card facts); `backend/app/domains/conversation/agent/step_up.py` (`agent_address`, `agent_step_up`, `_otp_again`, `_plan_issued`); `backend/app/domains/conversation/graph.py` lines 340–445 and 900–1080
  - Acceptance:
    - `graph.py`: `TurnInput`/`run_turn` gain the I11 resume values and `form_changed_fields`; `_agent_pause` returns `"profile_form"` at that pause; `_entry` sends every turn at that pause to `agent_profile_form` (mirror the address pause, including its kill-switch branch); node registered and baseline-mapped to `smalltalk` like `agent_address`; `_after_agent_pause` after it.
    - `agent/card_request.py` `agent_profile_form`: `resume="profile_form"` → `profile_changed_fields = form_changed_fields` (names only), then `issue_stored_plan`; `StepUpRequired` → `otp_pause_update` (the OTP pause, as `agent_address` does). `resume="profile_form_cancel"` → `action_cancelled`, steps and keys cleared, no LLM call. Anything else (typed text, flag off) → the form event again, or with the flag off the address-pause kill-switch behaviour. It never reads form values.
    - `plan.py` `issue_stored_plan` builds the open step: tool `cards.request_card`, args `kind` and `changed_fields` from state, `ConfirmStepView(tool, "request_card", facts=[kind_label, *profile_field_label(f) for f in changed])` (names only).
    - `step_up.py` keeps every step key when it rebuilds steps and reports `agent_plan_result.steps` without assuming `card_id`.
    - `test_profile_form_r5.py` `test_profile_form_values_never_reach_llm_ui_or_checkpoint`: `agent_on`, `CLI-TFMULTI00001`, scripted `propose_plan(open, credit)`; stage `{"email": "<unique>", "occupation": "<unique>"}` in `session.overlay.vault`; resume `profile_form` with those field names; resume `step_up` with the OTP; then the plan card. No staged value appears in any `llm.calls` input, in any UI event payload of any turn (serialised), or in `graph.aget_state(...)` values (serialised); state holds `profile_changed_fields == ["email", "occupation"]`.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_profile_form_r5.py tests/unit/test_agent_step_up.py tests/unit/test_agent_unlock_replace.py tests/unit/test_graph.py -q && uv run ruff check app/domains/conversation/graph.py app/domains/conversation/agent/card_request.py app/domains/conversation/agent/step_up.py app/domains/conversation/agent/plan.py tests/unit/test_profile_form_r5.py && uv run ruff format --check app/domains/conversation/graph.py app/domains/conversation/agent/card_request.py app/domains/conversation/agent/step_up.py app/domains/conversation/agent/plan.py tests/unit/test_profile_form_r5.py && uv run mypy app/domains/conversation/graph.py app/domains/conversation/agent/card_request.py app/domains/conversation/agent/step_up.py app/domains/conversation/agent/plan.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/agent/card_request.py`, `backend/app/domains/conversation/agent/step_up.py`, `backend/app/domains/conversation/agent/plan.py`, `backend/tests/unit/test_profile_form_r5.py`

- [ ] T21: Staff API: panel, decision, return gate; spec T11, T12, T14
  - Depends on: T2 (queues, `CardRequestBlock`), T4 (`render_decision`, `announce_decision`), T18 (`build_panel`, `decide_request`, exceptions)
  - Read exactly these: spec AS3, AS9, D12 and §"Contracts" → 5 (the three staff rows, errors, steps); `backend/app/api/v1/staff.py` (claimant checks and `return_handoff`, line 212); `backend/tests/integration/test_staff_round_trip.py` (how a handoff is created and claimed in a test)
  - Acceptance:
    - `GET /staff/handoffs/{id}/card-request` (claimant only, else `404 not_found`; `404` when the packet has no `card_request` or the request's conversation differs) returns `build_panel(...)` in the handoff's language.
    - `POST /staff/handoffs/{id}/card-request/decision` requires `Idempotency-Key`; non-claimant → `409 not_claimant` and nothing written. It maps the service exceptions to §5's codes; `before_write` records audit `tool_call` (tool `cards.decide_card_request`, `actor = agent:<account_id>`), then `readback` and `tool_result` after; when verified and not replayed it renders the template and calls `announce_decision` with the claimant's display name; returns `CardRequestDecisionResult`.
    - `POST /staff/handoffs/{id}/return` → `409 request_undecided` while the linked request is `pending`.
    - `tests/integration/conftest.py` `_STAFF` gains `("it.creditos", "Valentina", "creditos")` and `("it.retencion", "Andres", "retencion")`.
    - `test_card_request_decision.py`: seed a conversation through the API as `CLI-TFMULTI00001`, a pending open credit request through `cards.service.create_open_request`, and a `creditos` handoff whose packet carries the block; claim as `it.creditos`. `test_decision_non_claimant_refused` (`it.retencion` → refused, no product row, request still `pending`; return as the claimant → `409 request_undecided`), `test_decision_limit_out_of_bounds` (approve `"999"` → `422 limit_out_of_bounds`, no product row), `test_decision_idempotency_key_writes_once` (two approves, same key → one new product row, one request update, equal `request` and `verified`; the second `message_id` is `null`, R-c).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/integration/test_card_request_decision.py tests/integration/test_staff_round_trip.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && AGENT_ENABLED=false uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/staff.py tests/integration/conftest.py tests/integration/test_card_request_decision.py && uv run ruff format --check app/api/v1/staff.py tests/integration/conftest.py tests/integration/test_card_request_decision.py && uv run mypy app/api/v1/staff.py --follow-imports=silent`
  - Files: `backend/app/api/v1/staff.py`, `backend/tests/integration/conftest.py`, `backend/tests/integration/test_card_request_decision.py`

- [ ] T22: [close] Cards domain: close-request storage
  - Depends on: T12 (open storage), T18 (cards files last edited there)
  - Read exactly these: spec AS7, AS8 and §"Contracts" → 3 and 4; `backend/app/domains/cards/service.py` (`create_open_request`, `read_back_open_request`); this plan's I8
  - Acceptance:
    - `create_close_request(customer_id, conversation_id, card_id, reason_code, *, idempotency_key)` checks the card belongs to the customer, writes `kind='close'`, `card_kind` from the card, `product_id`, `reason_code`; a duplicate key re-reads; a second pending close on the card raises `ClosurePending`.
    - `read_back_close_request(request_id)` returns the request and the card (`last4`, kind, status, `current_balance`, currency, country).
    - `pending_requests` already lists close rows (check it).
  - Verify: `cd backend && uv run python -c "import app.domains.cards.service as s; s.create_close_request, s.read_back_close_request" && uv run lint-imports && uv run ruff check app/domains/cards && uv run ruff format --check app/domains/cards && uv run mypy app/domains/cards --follow-imports=silent`
  - Files: `backend/app/domains/cards/service.py`, `backend/app/domains/cards/repository.py`, `backend/app/domains/cards/schemas.py`

- [ ] T23: Clear the new state keys at the remaining clearing sites
  - Depends on: T16 (`card_request_kind`, `profile_changed_fields` in `TurnState`)
  - Read exactly these: spec §"Contracts" → 2 ("All are cleared with `confirmation_token_id`, at handoff and at `return_to_bot`"); this plan's "Facts" → the clearing-site list
  - Acceptance: wherever these four files set `confirmation_token_id: None` (`takeover.py:79`, `nodes/step_up_exit.py:35` and `:56`, `nodes/smalltalk.py:123`, `agent/dispute.py:67`), the same update also sets `card_request_kind: None` and `profile_changed_fields: None`. (`plan.py`, `step_up.py`, `confirm.py`, `nodes/handoff.py` are done by T16/T20/T24.)
  - Verify: `cd backend && for f in app/domains/conversation/takeover.py app/domains/conversation/nodes/step_up_exit.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/agent/dispute.py; do test "$(grep -c '"confirmation_token_id": None' $f)" -le "$(grep -c '"profile_changed_fields": None' $f)" || exit 1; done && AGENT_ENABLED=false uv run pytest tests/unit/test_agent_dispute.py tests/unit/test_agent_step_up.py -q && uv run ruff check app/domains/conversation/takeover.py app/domains/conversation/nodes/step_up_exit.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/agent/dispute.py && uv run ruff format --check app/domains/conversation/takeover.py app/domains/conversation/nodes/step_up_exit.py app/domains/conversation/nodes/smalltalk.py app/domains/conversation/agent/dispute.py`
  - Files: `backend/app/domains/conversation/takeover.py`, `backend/app/domains/conversation/nodes/step_up_exit.py`, `backend/app/domains/conversation/nodes/smalltalk.py`, `backend/app/domains/conversation/agent/dispute.py`

- [ ] T24: Opening on Acepto: execute, packet block, handoff to Créditos; spec T4, T5, T6, T8
  - Depends on: T2 (`CardRequestBlock`, reason `card_open_request`), T13 (fake `request_card`), T16 (open step), T20 (form pause, plan card)
  - Read exactly these: spec D10, D13 and §"Contracts" → 3 (last paragraph) and 6; `backend/app/domains/conversation/agent/confirm.py` (`_accept`, `_decline`, `_CLEARED`); `backend/tests/unit/test_agent_dispute.py` (how S3 sets the handoff after a verified Acepto and reads `session.handoff_tools.created`)
  - Acceptance:
    - `confirm.py`: Acepto on an open plan calls `request_card(kind, changed_fields, token_id)`; verified → `escalation_reason="card_open_request"`, `handoff_queue="creditos"` and graph → `handoff_summary → handoff` as S3; unverified → the existing `action_unverified` path (R3). No acepto → `action_cancelled`, nothing written. Readers of `step["card_id"]` branch on `action`. `_CLEARED` includes the two new keys.
    - `agent/card_request.py` `card_request_block(result, bank_tools) -> CardRequestBlock` from the verified result (I9 read-back).
    - `nodes/handoff.py` attaches `card_request` to the packet and appends `VerifiedFact(fact="card_request_filed", value=reference)` when such a result exists; every other packet has `card_request=None`; its clearing update includes the two new keys.
    - `test_card_request_open.py`: `test_open_credit_es_happy` (ES, credit, `email` changed; form → OTP → Acepto → one `creditos` handoff, `packet.card_request.kind == "open"`, `overlay.profile["email"]` set, one history entry, request `pending`), `test_open_debit_pt_happy` (PT, debit, no field changed), `test_open_nothing_written_before_accept` (at the form, OTP and plan-card pauses and after No acepto: `overlay.profile`, `card_requests`, `profile_history` unchanged, no handoff), `test_request_card_unverified_readback` (`raw_writes=` a `FakeBankWrites` subclass whose `request_card` returns `verified=False`; no "done" text, `action_unverified` handoff).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_request_open.py tests/unit/test_agent_confirmation.py tests/unit/test_agent_dispute.py -q && uv run ruff check app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py app/domains/conversation/nodes/handoff.py tests/unit/test_card_request_open.py && uv run ruff format --check app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py app/domains/conversation/nodes/handoff.py tests/unit/test_card_request_open.py && uv run mypy app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py app/domains/conversation/nodes/handoff.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/confirm.py`, `backend/app/domains/conversation/agent/card_request.py`, `backend/app/domains/conversation/nodes/handoff.py`, `backend/tests/unit/test_card_request_open.py`

- [ ] T25: [close] Write tools: `request_closure` in the protocol, executor, fake, sandbox and postgres writer
  - Depends on: T13 (open protocol), T17 (postgres writer), T22 (`create_close_request`, `read_back_close_request`)
  - Read exactly these: spec §"Contracts" → 3; `backend/app/domains/conversation/tools/fakebank.py` (`FakeBankWrites.request_card`); `backend/app/domains/conversation/tools/postgres_writes.py` (`request_card`)
  - Acceptance:
    - `request_closure(card_id, reason, *, idempotency_key)` in `BankWriteTools`; `ConfirmedWriteTools.request_closure(card_id, reason, token_id)` via `_run`, tool `cards.request_closure`; `_RecordingWriteTools` implements it.
    - Fake: stores a pending close in `overlay.card_requests`, `pending_card_requests().close_card_ids` includes the card. Postgres: `create_close_request` then `read_back_close_request` with `ctx.customer_id`. Both return `tracking_id` = reference and the I9 close read-back; `verified` only when the row matches.
  - Verify: `cd backend && uv run lint-imports && AGENT_ENABLED=false uv run pytest tests/unit/test_fakebank_writes.py tests/unit/test_sandbox_conversations.py tests/unit/test_r2_confirmed_writes.py -q && uv run ruff check app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py app/domains/conversation/tools/postgres_writes.py && uv run ruff format --check app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py app/domains/conversation/tools/postgres_writes.py && uv run mypy app/domains/conversation/tools/write.py app/domains/conversation/tools/executor.py app/domains/conversation/tools/fakebank.py app/domains/conversation/sandbox.py app/domains/conversation/tools/postgres_writes.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/tools/write.py`, `backend/app/domains/conversation/tools/executor.py`, `backend/app/domains/conversation/tools/fakebank.py`, `backend/app/domains/conversation/sandbox.py`, `backend/app/domains/conversation/tools/postgres_writes.py`

- [ ] T26: [close] Close decisions in the service, spec T13
  - Depends on: T18 (`decide_request`), T21 (route, test file, `it.retencion`), T22 (close storage)
  - Read exactly these: spec AS4, AS8, D5 and §"Contracts" → 5 (errors and steps); `backend/app/domains/cards/service.py` (`decide_request`); `backend/tests/integration/test_card_request_decision.py`
  - Acceptance:
    - `decide_request` handles `cancel` (reads `current_balance` fresh under the lock; ≠ 0 → `BalanceNotZero` before `before_write`, nothing written; = 0 → `product_status='Closed'` plus a `card_status_history` row in the same transaction as the request update), `keep` and `not_cancelled_balance` (request update only). Approve/decline on a close request → `DecisionNotAllowed`.
    - The panel's `close_balance_display` and `reason_label` (from `card_request_messages.cancel_reason_label`) are filled for close.
    - `test_card_request_decision.py` gains `test_cancel_nonzero_balance_writes_nothing`: a pending close on `PRD-TFM1CRED0001` (balance 1234.50) claimed by `it.retencion`; cancel → `409 balance_not_zero`; product status, `card_status_history` count, request row and audit events for `cards.decide_card_request` are unchanged.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/integration/test_card_request_decision.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check app/domains/cards tests/integration/test_card_request_decision.py && uv run ruff format --check app/domains/cards tests/integration/test_card_request_decision.py && uv run mypy app/domains/cards --follow-imports=silent`
  - Files: `backend/app/domains/cards/service.py`, `backend/app/domains/cards/repository.py`, `backend/tests/integration/test_card_request_decision.py`

- [ ] T27: LLM-down C7 text and spec T17 `llm_down` params
  - Depends on: T11 (the C7 reply helper in `nodes/abstain.py`; its real name is in the state file), T15 (test file). Follow the Q2 decision under "Decisions by the human" in the plan.
  - Read exactly these: spec C7 row and §"Contracts" → 8 (`card_request_unavailable`); `backend/app/domains/conversation/agent/node.py` (the `LLMError` branch, lines ~425–457); `backend/tests/unit/test_card_requests_off_path.py`
  - Acceptance:
    - In the agent's `LLMError` branch in `node.py`, a code check runs after the round-cap and pause branches and before the open-plan reminder and the `degraded` return. It fires when:
      - the customer's text matches a fixed keyword list in code (ES and PT, one list for "new card", one for "close/cancel card"); or
      - an `open`/`close` plan is already in progress.
    - When it fires, it cancels any open plan and returns T11's C7 helper reply: `card_request_unavailable` plus the human chip. The turn is not `degraded`, so `_after_agent` ends it at `finish`. No request, no write, no handoff.
    - `graph.py` is not touched.
    - `test_card_requests_off_path` gains `llm_down-open` and `llm_down-close`, with `agent_on` and a fake LLM that raises `LLMError` for the agent step. Each asserts: the template text, the chip, an empty `overlay.card_requests` and no handoff.
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_requests_off_path.py tests/unit/test_agent_fallbacks.py -q && uv run ruff check app/domains/conversation/agent/node.py tests/unit/test_card_requests_off_path.py && uv run ruff format --check app/domains/conversation/agent/node.py tests/unit/test_card_requests_off_path.py && uv run mypy app/domains/conversation/agent/node.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/node.py`, `backend/tests/unit/test_card_requests_off_path.py`

- [ ] T28: Environment: apply 0011, seed the staff, regenerate the client, queue types, P1 — **runs alone**
  - Depends on: T2 (queues, names), T5 (migration), T9 (i18n queue labels), T16 (`ProfileFormEvent`), T19 (form routes), T21 (staff routes and schemas)
  - Read exactly these: this plan's "Facts" → Environment (`make seed-identity`, `make client`, `<FE-TYPECHECK>`); `frontend/src/components/staff/queueStyles.ts`; `frontend/src/components/staff/ConversationFilters.tsx`
  - Acceptance:
    - `make seed-identity` succeeds: both dev databases are at `0011`, `agent.creditos` and `agent.retencion` exist, the backend restarted.
    - `make client` regenerated `frontend/src/client/` with the profile-form and card-request operations and the new `Queue` values.
    - `queueStyles.ts` gives `creditos` and `retencion` bar and chip colours from the existing palette (Q3 decision, reviewed at the verifier gate); `ConversationFilters.tsx` `Queue`/`QUEUES` and `lib/sse.ts` `Queue` include both.
    - P1: each new agent logs in, `/auth/staff/login` answers its queue, and `GET /staff/handoffs` is `200`.
  - Verify: `make seed-identity && docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -tAc 'select version_num from alembic_version' | grep -qx 0011 && make client && grep -q 'creditos' frontend/src/client/types.gen.ts && grep -qi 'card_request\|cardRequest' frontend/src/client/sdk.gen.ts && for q in creditos retencion; do pw=$(awk -F, -v u="agent.$q" '$1==u{print $4}' data/secrets/staff_credentials.csv); jar=$(mktemp); curl -sf -c "$jar" -H 'content-type: application/json' -d "{\"username\":\"agent.$q\",\"password\":\"$pw\"}" http://localhost/api/v1/auth/staff/login | grep -q "\"queue\":\"$q\"" && curl -sf -b "$jar" -o /dev/null http://localhost/api/v1/staff/handoffs; rc=$?; rm -f "$jar"; test $rc -eq 0 || exit 1; done && cd frontend && npx biome check src/components/staff/queueStyles.ts src/components/staff/ConversationFilters.tsx src/lib/sse.ts && docker exec latam-cs-frontend-1 npm run typecheck --silent`
  - Files: `frontend/src/client/` (generated), `frontend/src/components/staff/queueStyles.ts`, `frontend/src/components/staff/ConversationFilters.tsx`, `frontend/src/lib/sse.ts`

- [ ] T29: [close] Agent: the `close` action, `close_balance`, Acepto → Retención; spec T9, T10
  - Depends on: T3 (close preconditions), T14 (prompt), T16 (open action shape), T20 (plan card facts), T24 (Acepto → handoff, block), T25 (`request_closure`, `pending_card_requests().close_card_ids`)
  - Read exactly these: spec D4, D9 and §"Contracts" → 1 (the `request_closure` codes) and 2; `backend/app/domains/conversation/agent/card_request.py`; `backend/tests/unit/test_card_request_open.py` (the open happy path to mirror)
  - Acceptance:
    - `ProposedStep.action` += `"close"`, `reason` field; `AgentPlanStep` += `"close"`; a close step needs `card`, stands alone (`request_alone`). `check_steps` for `cards.request_closure`: `status_not_in: [Closed]` → `already_in_state`, `closure_pending` → `closure_pending`, `reason_in_policy` → `invalid_reason` (the code is checked against `cancel_reasons`); the existing `customer_not_active` handoff still applies (D9).
    - An accepted close goes straight to `accepted (step_up_required)` and returns the code-built fact `close_balance` (`format_money` of the card's balance, R4); plan card facts: card mask, `cancel_reason_label`, `close_balance`; summary key `request_closure`.
    - Acepto → `request_closure`; verified → `card_close_request`, `retencion`, packet block with `card_mask` and `reason_code`; unverified → `action_unverified`.
    - `test_card_request_close.py`: `test_close_es_happy` (ES, `CLI-TFMULTI00001`, `PRD-TFM1DEBT0002`, reason `high_cost`: `close_balance` in the result, OTP, Acepto → one `retencion` handoff whose `packet.card_request.reason_code == "high_cost"`) and `test_close_pt_nonzero_balance_happy` (PT, `PRD-TFM1CRED0001`, balance 1234.50: the same handoff with `reason_code`).
  - Verify: `cd backend && AGENT_ENABLED=false uv run pytest tests/unit/test_card_request_close.py tests/unit/test_card_request_open.py tests/unit/test_agent_plan_check.py -q && uv run ruff check app/domains/conversation/agent/plan.py app/domains/conversation/state.py app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py tests/unit/test_card_request_close.py && uv run ruff format --check app/domains/conversation/agent/plan.py app/domains/conversation/state.py app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py tests/unit/test_card_request_close.py && uv run mypy app/domains/conversation/agent/plan.py app/domains/conversation/state.py app/domains/conversation/agent/confirm.py app/domains/conversation/agent/card_request.py --follow-imports=silent`
  - Files: `backend/app/domains/conversation/agent/plan.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/agent/confirm.py`, `backend/app/domains/conversation/agent/card_request.py`, `backend/tests/unit/test_card_request_close.py`

- [ ] T30: Chat frontend: the profile form widget and `cards_changed` refresh
  - Depends on: T9 (i18n keys), T28 (generated client, `Queue` in `sse.ts`)
  - Read exactly these: spec AS10, D11 and §"Contracts" → 5 (the two profile-form rows, the two SSE rows); `frontend/src/components/chat/ChatView.tsx` (the `otp_required` handling); `frontend/src/lib/sse.ts`
  - Acceptance:
    - `sse.ts` registers `cards_changed` (no payload) and types the `profile_form` UI kind (`{card_kind}`).
    - `ProfileForm.tsx` (new): on the `profile_form` event, GET the form view; editable inputs for the five fields, read-only name/document/date of birth, income labelled with `income_currency`; client-side checks mirror the server's; Send posts `{action: "submit", values}`, Cancel posts `{action: "cancel"}` (wrappers in `api.ts`); the values never go into chat history or local storage.
    - `ChatView.tsx` renders the form at the pause, blocks the text box while it is open (the server answers `409 form_required`), and on `cards_changed` invalidates `CARDS_KEY` and every `["home","card", *]` query.
    - The plan card shows `confirm.steps.request_card`/`request_closure` through the existing `ConfirmCard` (no change there).
  - Verify: `cd frontend && npx biome check src/components/chat/ProfileForm.tsx src/components/chat/ChatView.tsx src/lib/sse.ts src/lib/api.ts && grep -n 'cards_changed' src/lib/sse.ts src/components/chat/ChatView.tsx && grep -n 'profile_form' src/components/chat/ChatView.tsx && docker exec latam-cs-frontend-1 npm run typecheck --silent`
  - Files: `frontend/src/components/chat/ProfileForm.tsx`, `frontend/src/components/chat/ChatView.tsx`, `frontend/src/lib/sse.ts`, `frontend/src/lib/api.ts`

- [ ] T31: Staff frontend: the card-request panel and the return gate
  - Depends on: T9 (i18n keys), T28 (generated client)
  - Read exactly these: spec AS3, AS9, D5 and §"Contracts" → 5 (`CardRequestPanel`, decision errors); `frontend/src/routes/staff/handoffs.$handoffId.tsx`; `frontend/src/components/ui/dialog.tsx`
  - Acceptance:
    - `CardRequestPanel.tsx` (new), mounted on the handoff page when `packet.card_request` is set and the viewer is the claimant: shows the request, customer (with the "changed" badge), cards, `credit_bounds` (open credit) or `close_balance_display` (close), all as server-formatted strings.
    - Decisions by `request.kind`: open → approve (credit: limit input with the bounds shown) and decline (reason select from `staff.card_request.decline_reason.*`); close → cancel, keep, not cancelled because of the balance. Every decision opens a review dialog; confirm posts with a fresh `crypto.randomUUID()` `Idempotency-Key`, reused on a retry of the same dialog. Error codes map to `staff.card_request.error.*`; `409 balance_not_zero` keeps the dialog open and points to "not cancelled because of the balance". After a decision the panel shows the result and refetches.
    - The return button (`data-testid="return-handoff"`) is disabled with `staff.card_request.return_blocked` while the request is `pending`.
    - No decline reason, bound or token reaches the customer UI.
  - Verify: `cd frontend && npx biome check src/components/staff/CardRequestPanel.tsx "src/routes/staff/handoffs.\$handoffId.tsx" && grep -n 'Idempotency-Key\|idempotency' src/components/staff/CardRequestPanel.tsx && grep -n 'CardRequestPanel' "src/routes/staff/handoffs.\$handoffId.tsx" && docker exec latam-cs-frontend-1 npm run typecheck --silent`
  - Files: `frontend/src/components/staff/CardRequestPanel.tsx`, `frontend/src/routes/staff/handoffs.$handoffId.tsx`

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1, T2, T3, T4, T5, T6, T7, T8, T9, T10 | | No dependencies; disjoint files (policy modules, enums, templates, migration, vault, customers, docs, i18n, prompt). T5's Verify uses a throwaway database only |
| W2 | T11, T12, T13, T14 [close], T19 | | Each needs only W1 pieces (T4, T7, T6, T10, T6+T7); files disjoint (abstain/scope, `cards/*`, write tools, prompt, conversations API/runner/R13 test) |
| W3 | T15, T16, T17, T18 | | T15 abstain helper (T11); T16 needs T13; T17 needs T12+T13; T18 needs T12. Files disjoint: intents/unsupported, plan/state/ui/card_request, postgres_writes, `cards/*` |
| W4 | T20, T21, T22 [close], T23, T27 | | T20 needs T16+T19; T21 needs T18; T22 needs `cards/*` free after T18; T23 needs T16; T27 needs T15. Files disjoint: graph/step_up/plan/card_request, staff API + integration conftest, `cards/*`, four clearing sites, agent node.py + off-path test (Q2 needs no `graph.py`, so T27 stays here) |
| W5 | T24, T25 [close], T26 [close] | | T24 needs T20; T25 needs T17+T22; T26 needs T21+T22. Files disjoint: confirm/card_request/handoff node, write tools, `cards/*` + decision test |
| W6 | T28 | **alone** (migrates both dev databases, restarts the backend, regenerates the client) | Needs every API task (T19, T21) done |
| W7 | T29 [close], T30, T31 | | T29 backend agent close (needs T24, T25); T30 chat FE and T31 staff FE need T28's client; files disjoint (`api.ts` and `sse.ts` only in T30) |

After W7 the verifier runs `make check AGENT_ENABLED=false` once, then P2 and P3 in the browser with `AGENT_ENABLED=true`. Under the cut, drop T14, T22, T25, T26, T29; the waves keep their order.
