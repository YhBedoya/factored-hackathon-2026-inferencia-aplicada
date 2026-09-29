# State: D4-A — Escalation, handoff backend and AWS deploy v0
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D4-A (G10 + G12a, owner A) · spec `docs/specs/d4-a-escalation-handoff-deploy.md` · plan `docs/plans/d4-a-escalation-handoff-deploy.md` · deploy design `docs/solution-docs/08-deployment.md`
Branch `feat/d4-a-escalation-handoff-deploy`, based on `develop`.

## Conventions established for this card
- Repo facts: read the plan's "Facts checked against the repo" section (including its "Human decisions" subsection). Not copied here.
- Tasks run in PARALLEL WAVES in one shared checkout (plan "Parallel waves"). Touch only the files your task block lists; the shared-file ownership list in "Parallel waves" is binding.
- No git write commands (commit, stash, checkout, reset, restore, add). The working tree holds other tasks' uncommitted work and the spec-time doc edits (`docs/solution-docs/*`); never revert or reformat files you don't own.
- Append your Task log entry with ONE shell append (`cat >> <state file> <<'EOF' … EOF`), never Edit/Write on this file — other agents append concurrently.
- Don't run formatters or linters with --fix over the whole repo; lint only your own files.

- `abstain_fallback` is "… {reason} {closest_action} {human_offer}"; callers collapse whitespace after filling (empty closest_action leaves a double space) — T6.
- Flows get a rule's queue via `rule_queue(policy, reason) -> Queue` (policy/escalation.py; raises ValueError on `queue: null`), not `rule(...).queue` — T3.
- `make infra-up` takes ALERT_EMAIL_1/2, DATA_BUCKET, BEDROCK_ARNS as make vars; stack RepoUrl defaults to github.com/YhBedoya/factored-hackathon-2026-inferencia-aplicada — T10.
- Prod Compose layer order is `-f base -f observability -f prod` (prod last so its `!override` ports win) — T9, human.
- Handoff errors `AlreadyClaimed`, `HandoffClosed`, `NotClaimant` are ToolError subclasses defined in handoff/repository.py and re-exported from handoff/service.py (no `code` attr); the staff API maps them to 409 — T11.
- T21 (owns graph.py) adds `handoff_request: NotRequired[str]` to `GraphState`; `handoff_summary` returns it and `nodes/handoff.py` reads it via a `cast(dict, state).get(...)` that T31 cleanup may drop — T14/T15.
- `abstain` node omits the `closest_action` fact when the topic has no closest intent — T13.
- Return to bot: `return_to_bot` (mode=bot under the turn lock) runs FIRST; the handoff is marked `returned` only after it succeeds. `TurnBusy` → 409 `turn_in_progress` with nothing changed — human decision, T24.
- AccessDenied refusal reuses the `injection_suspected` template text (no new ES/PT text) — T21.
- T31 cleanup: drop the `cast(dict, state).get("handoff_request")` in `nodes/handoff.py` (GraphState now declares it) — T21.
- Return route checks `is_claimed_by` before flipping mode; a non-claimant gets 409 `not_claimant` with nothing changed — T24.
- `return_to_bot` clears escalation_reason, handoff_queue, unauthorized_attempts, handoff_id, handoff_evidence, handoff_request; T29's round trip (return → bot answers next message) is the proof — T17.
- Empty node updates (`{}`) stream as `None`; `graph.run_turn` and `runner` handle branch nodes before any `None` guard — T21/T22 W4 repairs.
- `handoff` node resolves reason/queue from `nlu.intents` like `handoff_summary` — T15 W4 repair.

## Human decisions taken mid-card
- Staff access: seeded staff accounts (migration 0005, `/auth/staff/login`, `require_role`) — spec gate.
- Another customer's data: refuse + audit each time; 2nd attempt → handoff Atención, reason `unauthorized_access` — spec gate.
- Staff names: agent.atencion=Laura, agent.cobranza=Diego, agent.fraudes=Sofía, agent.reclamos=Mateo, admin="Swip Admin" — plan.
- scope.yaml: all topics → atencion; loans/accounts chip card_status, pix/boleto chip balance_due, others none — plan.
- Deploy: human runs T32's runbook with own AWS profile; agents never run AWS commands — plan.
- Prod Compose order: base → observability → prod; Makefile, deploy.sh, T9 Verify and 08 §7/§10 follow it — T9.
- T12 seed: agents may not run `make seed-identity`; the human runs it. `latam_app` and `latam_golden` are at migration 0005 — T12.
- Return to bot: flip mode first, then close the handoff; busy lock → 409 with nothing changed — T24.
- Verify gate: handoff uses the PERSISTED id (attach to an open case, real reference); `MessageRow.ui_payload` accepts a list; SC2 amended (only load_session's get_profile) — verifier round 1.
- Gate: add a `_guard_access` test (tool AccessDenied twice → refusal, audit, Atención handoff); attach-to-open audits action "attached"; register LangGraph checkpoint types (HandoffBannerEvent, QuickRepliesEvent, NLUResult); V4 skipped; other minors → notes — verifier round 2.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a69ab4c | Handoff contracts (schemas, ui events, TurnState delta, HandoffTools protocol, audit literals); lint-imports ok |
| T2 | done | a56b0c7 | Migration 0005_handoffs_staff; up/down/up clean on throwaway DB |
| T3 | done | a42c469 | escalation.yaml v2 + resolver, Queue gains reclamos, 3 call sites; 24 passed, mypy clean |
| T4 | done | a87c765 | policies/scope.yaml + loader in policy bundle; tests/lint/mypy clean |
| T5 | done | a85aa0c | Staff-capable Session, StaffMeResponse, R1 guard; 10 passed |
| T6 | done* | ab06494 | ES/PT handoff_transfer, back_with_cardy, abstain_fallback; Verify digit-assert is a plan bug (hits {card_last4} in old templates) — new kinds digit-free |
| T7 | done | a98b09d | Redis handoff channels (handoff_channel/publish_handoff/subscribe_handoffs); verify ok |
| T8 | done | a22dc98 | core/demo_reset.reset_app_database; proven on throwaway DBs (727 ms); cleared dev Redis conf:/turn: keys as side effect |
| T9 | done | a8a1151 | Prod compose + prod nginx image + .env.prod.example; only 443/80 published (base→obs→prod); nginx 6h reload loop (untested) |
| T10 | done | a23248d | infra/aws stack + render-env/deploy/smoke scripts + Makefile targets; cfn-lint/bash -n/make -n clean, no AWS calls |
| T11 | done | a63041e | handoff repository + service; lint/mypy/import-linter clean; DB behavior proven in T29 |
| T12 | done | af07c9c | staff_login/staff_me, seeds 4 agents + admin, staff_credentials.csv 0600 git-ignored; seed run by human (classifier blocked agent) |
| T13 | done | a946e3b | abstain node + compose@v5 (goal abstain); wiring in T21; also edited test_compose.py v4->v5 assert (outside touch map) |
| T14 | done | ac29bb8 | handoff_summary node + prompt v1 + core/llm step; R6 + llm_client tests 4 passed |
| T15 | done | abafd84 | nodes/handoff.py code-only node (no LLM import); not exported from nodes/__init__ (T21) |
| T16 | done | ab2df33 | unsupported audits access_denied each injection turn, sets escalation_reason=unauthorized_access at threshold; test in T26, wiring in T21 |
| T17 | done | a86796f | conversation/takeover.py (TurnBusy, publish_mode, relay_agent_message, return_to_bot); + clears all handoff state on return (W3 follow-up) |
| T18 | done | a251551 | conftest RecordingAudit + handoff_tools/audit keys; sandbox InMemoryHandoffTools/NullAuditRecorder; 15 passed |
| T19 | done | a481620 | staff_auth/staff/admin router skeletons w/ role guards + CSRF, registered in v1_router; lint-imports ok |
| T20 | done | a798be4 | chat_api prints mode/handoff_banner/agent+system msgs/abstain chips; lint+--help only, not run live |
| T21 | done | a50b255 | graph switchover (human-mode _entry, route escalation/abstain, handoff nodes, relay node, AccessDenied guard); 13 passed, mypy/lint-imports clean; diagram regenerated |
| T22 | done | adbad25 | runner human-mode relay + mode event, ServiceHandoffTools (conv-id check) + import-linter edge; behavior proven in T29 |
| T23 | done | a7cd403 | staff auth routes (login public, /staff/me + logout guarded); R13 test passes, no route collisions |
| T24 | done | ad731c5 | staff handoff + claimed-conversation API, get_claimed_conversation, R13 extension; return flips mode first (claimant check, TurnBusy→409 no change); mypy clean |
| T25 | done | a999f5d | POST /admin/demo/reset (close host, reset, reopen in finally); R13 ok; live call in T31 |
| T26 | done | a9ce8e1 | escalation rule tests (6 rules ES/PT + unauthorized_access ES/PT 2-turn) + r3/block flow updates; 23 passed (after T15 fix) |
| T27 | done | aec566b | abstain ES/PT tests + old Pix test → route abstain; 8 passed; "no tool" = only load_session's get_profile |
| T28 | done | a0db26e | packet (read-backs only, no transcript), summary fallback, human-mode relay w/o LLM, R6; 6 passed after T15+T21 fixes |
| T29 | done | a313d17 | staff round-trip ES/PT + access boundaries + bank-blocked test; 3/3 round-trip pass after T22 runner fix |
| T30 | done | ab7d438 | docs 02 §3/§5/§6, 03 §6, 04 §3–§5, 06 §3, 08 §7/§10 (compose order) reflect mid-card decisions |
| T31 | done | abbf16d | cleanup, make client, live e2e (Pix abstain, human_request handoff, admin reset 200 but ~354 s) |
| T32 | pending | | |
| T33 | pending | | |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T7 — Handoff channels on Redis pub/sub
Changed: `backend/app/core/events.py` (`handoff_channel`, `publish_handoff`, `subscribe_handoffs(queue|None)`; `_events` now also accepts `pmessage`).
Facts the next tasks need: `subscribe_handoffs(None)` psubscribes `handoff:*`; yields `(event, data)` like `subscribe`.
Deviations: none.
Verify: plan Python round-trip script → ok; ruff check, ruff format --check, mypy on events.py → clean.

### T2 — Migration 0005_handoffs_staff
Created: `backend/app/alembic/versions/0005_handoffs_staff.py` (revision "0005", down "0004").
Facts the next tasks need: constraints named `uq_accounts_username`, `ck_accounts_role`, `ck_accounts_customer_id_role`; `app.handoffs` indexes `ix_handoffs_status_queue_created_at`, `uq_handoffs_open_conversation` (partial unique); `packet`, `queue`, `reason`, `priority` are NOT NULL.
Deviations: none. Verify used credentials from `.env` (POSTGRES_USER/PASSWORD).
Verify: upgrade head / downgrade 0004 / upgrade head OK → handoffs index count 3; ruff check + format --check pass.

### T4 — scope.yaml and loader
Created: `policies/scope.yaml`, `backend/app/domains/policy/scope.py` (`ScopePolicy`, `TopicScope`, `TOPICS`, `load_scope_policy`).
Changed: `backend/app/domains/policy/registry.py` (`scope` in `_MODELS_BY_STEM` and `PolicyBundle`; missing scope.yaml -> PolicyLoadError).
Facts the next tasks need: `ScopePolicy.topics` is `dict[str, TopicScope]` (str keys, since policy can't import conversation `Topic`); `closest_intents` are plain strings; `Queue` from `localization.format`.
Deviations: none.
Verify: test_policy_registry 2 passed; scope assertions, ruff check/format, mypy all clean.

### T8 — core/demo_reset.py
Created: `backend/app/core/demo_reset.py` (`reset_app_database(*, app_db, golden_db) -> duration_ms`).
Facts the next tasks need: disposes `get_engine()` + `cache_clear()`; sync psycopg via `asyncio.to_thread`; deletes Redis `conf:*`/`turn:*`; does NOT touch the checkpointer pool (T25 route closes/reopens it around the call). Uses `DROP DATABASE IF EXISTS`.
Deviations: none.
Verify: throwaway-DB proof → returned 727, marker table copied, ruff/format/mypy clean.

### T6 — Fixed ES/PT texts
Changed: `backend/app/domains/conversation/templates.py` (kinds `handoff_transfer` {queue_label},{reference}; `back_with_cardy`; `abstain_fallback` {topic_label},{reason},{closest_action},{human_offer}).
Facts the next tasks need: `abstain_fallback` leaves a double space when `closest_action` is empty; caller should collapse whitespace. No new digits added.
Deviations: the Verify digit assertion fails on PRE-EXISTING templates because placeholder `{card_last4}` contains a digit (action_confirm, action_done, etc.), not on T6 texts. Checked digit-free for the 3 new kinds.
Verify: all other Verify parts (import/get_template, pytest, ruff, format, mypy) run; see reply.

### T5 — Staff-capable Session, StaffMeResponse, R1 guard
Changed: `identity/{models,tokens,service}.py` (Session/TokenClaims role 3-way, `customer_id: str | None`; `StaffLoginRequest`, `StaffMeResponse`; `me` raises ValueError on None), `api/v1/conversations.py` (`_customer_id()` narrowing -> 403 forbidden_role), `conversation/tools/registry.py` (`build_tool_context` raises PermissionError), test appended to `tests/unit/test_r1_customer_scope.py`.
Facts: `StaffMeResponse.queue` uses `Queue` imported from `app.domains.localization.format` (currently 3 values, no `reclamos`; whoever owns Queue must widen it). `issue_token` unchanged (passes None through).
Deviations: none.
Verify: 10 passed; ruff check/format clean; `mypy app` -> 1 error in another task's file `app/domains/policy/escalation.py:218` (unused type: ignore).

### T1 — Handoff contracts
Created: `backend/app/domains/handoff/{__init__,schemas}.py`, `backend/app/domains/conversation/tools/handoff.py` (`HandoffTools`, `InMemoryHandoffTools`).
Changed: `conversation/ui.py` (`HandoffBannerEvent`, `ModePayload`, `MessagePayload`, `abstain` slot), `conversation/state.py` (4 handoff fields), `audit/schemas.py` (`handoff` type, `agent:<uuid>` actor).
Facts the next tasks need: `HandoffReason` has the 8 spec values only (no tool_failure/llm_unavailable/claim_priority yet); `Queue` in `localization.format` still lacks `reclamos` (D8, not mine); `ActionTaken.audit_event_id` is `str | None`; `VerifiedFact.value` is `JsonValue`; `HandoffBannerPayload.handoff_id` is `str`.
Deviations: none.
Verify: ruff, ruff format, mypy, lint-imports (4 kept), pytest test_audit_pairs + test_card_select → 2 passed.

### T3 — escalation.yaml v2, resolver, reclamos queue
Changed: `policies/escalation.yaml` (v2), `backend/app/domains/policy/escalation.py`, `localization/format.py` (`Queue` + `reclamos` labels), `flows/{actions,card_unlock,replacement}.py`.
Facts the next tasks need: `escalation.py` exports `legal_hit`, `rule`, `rule_queue` (raises ValueError when a rule has `queue: null`; flows use it), `resolve_escalation(policy, *, reason, queue, pending_flow, intents, text) -> Resolution{reason, queue, priority} | None`, `RulePolicy`, `Resolution`. `customer_not_active.queue` and `action_queues` no longer exist.
Deviations: added `rule_queue` helper (non-None queue for mypy) beyond the block's `rule(...).queue`.
Verify: 24 passed; legal_hit check, ruff check/format, mypy all clean.

### T10 — infra/aws stack, scripts, Makefile targets
Created: `infra/aws/{ec2-stack.yaml,render-env.sh,deploy.sh,smoke.sh}`.
Changed: `Makefile` (`COMPOSE_PROD`, `STACK_NAME`, `infra-up`, `infra-down`, `deploy`, `deploy-remote`, `smoke-prod`; in `.PHONY`).
Facts the next tasks need: stack params `AlertEmail1/2`, `DataBucketName`, `BedrockModelArns`, `RepoUrl`; `make infra-up ALERT_EMAIL_1= ALERT_EMAIL_2= DATA_BUCKET= BEDROCK_ARNS=a,b`; repo cloned to `/opt/swip`; SSM param basename = env var name; render-env reads `.env.prod.example` (T-other) and adds host DATABASE_URL/GOLDEN_DATABASE_URL from POSTGRES_PASSWORD if absent; deploy.sh needs `docker/docker-compose.prod.yml` and `PUBLIC_HOST` in .env; smoke.sh assumes `POST /auth/staff/login {username,password}` and `/test-idp/sessions` 404.
Deviations: none.
Verify: cfn-lint + bash -n + grep guard + `make -n infra-up deploy smoke-prod HOST=x.sslip.io` → rc=0.

### T9 — Prod Compose layer, prod Nginx, .env.prod.example
Created: `docker/docker-compose.prod.yml`, `docker/nginx/Dockerfile.prod`, `docker/nginx/Dockerfile.prod.dockerignore` (extra, keeps repo-root build context small), `docker/nginx/prod.conf`, `.env.prod.example`.
Facts the next tasks need: nginx prod image is built with context `..` (repo root); PUBLIC_HOST is passed as env to nginx (envsubst template). Nginx needs the cert files to start, so the runbook must issue the cert before `up` of nginx (or with a bootstrap cert). certbot service loops `certbot renew`; no nginx reload wired (deploy.sh must do it).
Deviations: BLOCKED on layer order. With `-f base -f prod -f observability` the observability file (later) re-adds `8428/9428/10428/3000` on 0.0.0.0 (ports merge by target, later wins), so prod's `!override` cannot win. With order `base, observability, prod` the Verify's port check passes and the image builds. Escalated; T-Makefile/deploy scripts must use the same order.
Verify: as written → fails (ports list also has 10428,3000,8428,9428); with order base+observability+prod → `["443","80"]`, build ok.
T9 follow-up: layer order is base, observability, prod (human decision); Verify re-run in that order → `["443","80"]`, build ok. nginx now reloads itself every 6h via its `command` in `docker-compose.prod.yml` (no deploy.sh dependency); certbot comment updated.

### T10 follow-up
Compose order changed to base, observability, prod (prod last) in `Makefile` `COMPOSE_PROD` and `infra/aws/deploy.sh`; Verify rc=0; `docker compose config` resolves.

### T20 — chat_api prints handoff events
Changed: `backend/scripts/chat_api.py` (`_handle_event`: `mode`, `agent:`/`system:` messages, customer echo ignored, `ui handoff_banner`, `ui quick_replies abstain:`).
Deviations: none.
Verify: help + ruff check + ruff format --check → clean.

### T16 — unsupported counts unauthorized attempts
Changed: `backend/app/domains/conversation/nodes/unsupported.py` (now `async (state, config)`).
Facts the next tasks need: threshold read via `get_policies().escalation.unauthorized_access.attempts_before_handoff`; audit via `configurable.get("audit") or NullAuditRecorder()`; at threshold returns `unauthorized_attempts` + `escalation_reason="unauthorized_access"` and no `segments`.
Deviations: none.
Verify: test_conversation_basics 3 passed; ruff check/format, mypy clean.

### T18 — Test harness and sandbox config keys
Changed: `backend/tests/conftest.py` (`RecordingAudit` with `events: list[(type, payload)]`, exported; `Session.handoff_tools`/`.audit`; config keys `handoff_tools`, `audit`), `backend/app/domains/conversation/sandbox.py` (`InMemoryHandoffTools()`, `NullAuditRecorder()` in config).
Facts the next tasks need: config keys read by flows are `handoff_tools` and `audit`.
Deviations: none.
Verify: 15 passed; ruff check/format, mypy sandbox.py clean.

### T19 — Staff/admin router skeletons
Created: `backend/app/api/v1/{staff_auth,staff,admin}.py` (empty routers, role guards + CSRF at router level).
Changed: `backend/app/api/v1/__init__.py` (includes staff_auth public_router, staff_auth router, staff, admin).
Facts the next tasks need: `staff_auth.router` has no prefix (routes carry full `/auth/staff/...` or as T23 decides); `staff` prefix `/staff`, `admin` prefix `/admin`.
Deviations: none.
Verify: 3 passed; ruff check/format, mypy app/api, lint-imports (4 kept) clean.

### T17 — Takeover helpers
Created: `backend/app/domains/conversation/takeover.py` (`TurnBusy`, `publish_mode`, `relay_agent_message`, `return_to_bot`).
Facts the next tasks need: `publish_mode(cid, mode: str, name|None)`; `relay_agent_message` returns the new turn_id; `return_to_bot` resets `handoff_queue` to None, lists to [], counters to 0, and does not touch DB handoffs/conversation mode (T24 route does).
Deviations: none.
Verify: import assert, ruff check/format, mypy, lint-imports (4 kept) → clean.

### T11 — Handoff repository and service
Created: `backend/app/domains/handoff/{repository,service}.py`.
Facts the next tasks need: `AlreadyClaimed`, `HandoffClosed`, `NotClaimant` (ToolError subclasses, no `code` attr) live in `handoff/repository.py`, re-exported by `service`. `service.create(packet, priority) -> UUID` (idempotent per conversation, no 2nd event); `list_handoffs(queues|None, statuses) -> list[HandoffSummary]`; `get_detail(id) -> HandoffDetail` (NotFound); `claim(id, agent_id) -> HandoffDetail`; `return_handoff(id, agent_id) -> HandoffSummary`; `is_claimed_by(conv_id, agent_id) -> bool`. Events published: `handoff_created` on create, `handoff_updated` on real claim/return only.
Deviations: none. Behavior unexecuted against a DB (proven in T29).
Verify: import assert, ruff check/format, mypy (4 files), lint-imports (4 kept) all clean.

### T13 — Structured abstain
Created: `backend/app/domains/conversation/nodes/abstain.py` (`abstain(state, config)`), `prompts/compose@v5.md` (v4 + `abstain` goal + ES/PT examples).
Changed: `nodes/compose.py` (`PromptRef("compose", 5)`, `Goal` += `abstain`, `_format_fact` passes `topic_label`/`abstain_reason`/`closest_action`/`human_offer` through).
Facts the next tasks need: fact key for the reason is `abstain_reason` (fallback template arg is `reason`); `closest_action` fact is omitted when the topic has no closest intent; chips = [closest label?, human offer label]; node not yet wired into the graph (route T-later); fallback detected by equality with `get_template("fallback")`.
Deviations: edited `backend/tests/unit/test_compose.py` line 58 (`compose@v4` -> `compose@v5`), outside the Files list, required for Verify to pass after the version bump.
Verify: test_compose 1 passed; import, ruff check/format, mypy clean.

### T14 — handoff_summary LLM node
Created: `nodes/handoff_summary.py` (`HandoffSummaryDraft`, `handoff_summary`), `prompts/handoff_summary@v1.md`.
Changed: `core/llm/registry.py` (`Step` + MODEL_REGISTRY + TEMPERATURE gain `handoff_summary`).
Facts the next tasks need: node returns `{"handoff_request": str}`; `handoff_request` is NOT yet declared in `GraphState` (graph.py owner must add `NotRequired[str]`). Reads `config["configurable"]["bank_tools"]` only for `get_card_details` (card_mask offered only if selected_card_id resolves). Unresolvable escalation -> generic human_request fallback text.
Deviations: none.
Verify: pytest r6 + llm_client 4 passed; import ok; ruff check/format, mypy, lint-imports clean.

### T15 — handoff code node
Created: `backend/app/domains/conversation/nodes/handoff.py` (`handoff(state, config)`).
Facts the next tasks need: reads `configurable["session"|"handoff_tools"|"audit"]`; `handoff_request` read via `cast(dict, state).get(...)` because `GraphState` doesn't declare it yet (the task that adds it may drop the cast); raises ValueError if `resolve_escalation` returns None; fact value = tracking_id, else readback `status`, else True; `ActionTaken.at` = node time (ActionResult has no timestamp); not yet exported from `nodes/__init__.py`.
Deviations: none.
Verify: import/no-llm assert, ruff check, ruff format --check, mypy, lint-imports (4 kept) → all clean.

### T12 — Staff identity (code done, seed Verify NOT run)
Changed: `identity/passwords.py` (`staff_login_key`), `repository.py` (`AccountRow` staff fields, `customer_id` optional, `get_account_by_id`), `service.py` (`staff_login`, `staff_me`), `provision.py` (staff seeding + `staff_credentials.csv` 0600, `_AGENT_NAMES: dict[Queue, str]`).
Facts the next tasks need: `latam_app` and `latam_golden` were upgraded to 0005 by T12; `provision` truncates `identity.accounts, app.handoffs` together (handoffs.agent_id FK blocks a lone TRUNCATE); `staff_me` reads via `repository.get_account_by_id` directly (not on the `AccountStore` protocol).
Deviations: `make seed-identity` was blocked by the auto-mode classifier (truncate of golden tables), so the DB part of Verify was not executed and staff rows are not seeded yet.
Verify: test_login_pii 2 passed; ruff check, ruff format --check, mypy on identity clean. DB/CSV assertions pending a human-run `make seed-identity`.
T12 follow-up: after the human's `make seed-identity`, the read-only Verify parts passed (roles admin=1/agent=4, 5 username=display_name pairs, CSV mode 600, 6 lines, git-ignored).

### T22 — Runner human relay, handoff mode event, ServiceHandoffTools
Changed: `conversation/tools/handoff.py` (`ServiceHandoffTools(ctx)`; uses `packet.priority`), `.importlinter` (+1 ignore edge), `conversation/runner.py` (config `handoff_tools`/`audit`; `relay_to_agent` -> customer `message` + `done`, early return; `mode{human,null}` after `ui` when `handoff` update has `handoff_id`; `_BRANCH_NODES` += `abstain`, `handoff`).
Facts the next tasks need: `HandoffTools.create` Protocol unchanged (packet only, returns None); the relay path returns inside `try`, lock still released in `finally`.
Deviations: none.
Verify: ruff check, format --check, mypy conversation (41 files), lint-imports (4 kept) → clean.

### T23 — Staff auth routes
Changed: `backend/app/api/v1/staff_auth.py` (`POST /auth/staff/login` on public_router; `GET /staff/me`, `POST /staff/logout` 204 on guarded router; reuses `auth._set_auth_cookies`).
Facts the next tasks need: 429 before 401; `staff_me` SessionExpired -> 401 session_expired. `test_r13_routes.py` public allowlist (line ~32) must include `/api/v1/auth/staff/login` (T24 owns that file); until then the test fails on that route.
Deviations: none.
Verify: ruff check, format --check, mypy clean; `test_r13_routes.py` 1 failed ("/api/v1/auth/staff/login has no RoleGuard dependency") pending T24's allowlist edit.

### T24 — Staff handoff and conversation API
Changed: `backend/app/api/v1/staff.py` (9 routes minus me/logout; `get_claimed_conversation` exported), `backend/tests/unit/test_r13_routes.py` (staff login exempt, staff/admin RoleGuard roles, claimed-conversation dependency).
Facts the next tasks need: handoff errors map to 409 `already_claimed`/`handoff_closed`/`not_claimant`, NotFound to 404; claim/return audit `handoff` payload `{event: claimed|returned, handoff_id, queue}` with actor `agent:<account_id>`; `GET /handoffs` rejects unknown `status` with 422; return route reads `request.app.state.turn_host`; staff display name via `identity.service.staff_me`. T23 must add `/staff/me` and `/staff/logout` to the same file (routes only, keep the existing router).
Deviations: none. Routes untested against a DB (T29).
Verify: pytest test_r13_routes 1 passed; ruff check/format, lint-imports (4 kept) clean; `mypy app/api/v1/staff.py` reports 4 errors only in another task's `conversation/graph.py:360-363` (T21 mid-edit), none in staff.py.

### T21 — Graph switchover
Created: `nodes/relay.py` (`relay_to_agent`, code only).
Changed: `graph.py` (`handoff_request` in GraphState; `_entry` human mode first; `_after_flow` -> handoff_summary on HandoffReason or set handoff_queue, fallback only for tool_unavailable/no_cards; `_after_unsupported`; `_guard_access` wraps the 4 flow nodes; abstain/handoff_summary/handoff/relay_to_agent wired; `_BRANCH_NODES` extended), `nodes/route.py` (injection -> unsupported; `resolve_escalation(reason=None)` hit -> handoff_summary; out_of_market/scope -> abstain), `nodes/__init__.py` (exports), `flows/actions.py` (`handoff` sets escalation_reason/handoff_queue, no segment; `handoff_placeholder` no longer used there), `docs/diagrams/turn-graph-v0.mmd`.
Facts the next tasks need: `route` passes `state["user_text"]` and `pending.flow` to the resolver; AccessDenied guard reuses the `injection_suspected` template; `handoff.py`'s `cast(dict, ...)` for handoff_request can now be dropped.
Deviations: none.
Verify: 13 passed; ruff check/format, mypy, lint-imports (4 kept) clean.
T23 follow-up: after T24, test_r13_routes 1 passed; ruff/format/mypy clean; /staff/me + /staff/logout coexist with staff.py routes, no path collision.

### T25 — POST /admin/demo/reset
Changed: `backend/app/api/v1/admin.py` (`demo_reset` route, `DemoResetResponse`).
Facts the next tasks need: route closes `app.state.turn_host`, calls `reset_app_database()`, reopens host with the old host's `llm` in `finally`; failure propagates as an unhandled 500. Live call is T31.
Deviations: none.
Verify: test_r13_routes 1 passed (first run failed on T24's mid-edit `/auth/staff/login` exemption, passed on re-run); ruff check/format, mypy, lint-imports (4 kept) clean.
T24 follow-up (human): `POST /staff/handoffs/{id}/return` now checks claimant, runs `return_to_bot` first, then `return_handoff`; `TurnBusy` -> 409 `turn_in_progress` with nothing changed and no audit.

### T17 follow-up (T21 request)
Nothing else resets handoff state per turn; `return_to_bot` now also sets `handoff_id=None`, `handoff_evidence=[]`, `handoff_request=""` (already cleared: escalation_reason, handoff_queue, unauthorized_attempts=0). Ruff/format/mypy clean.

### T28 — Packet, summary fallback, human-mode and R6 tests
Created: `backend/tests/unit/test_handoff_packet.py` (`test_packet_from_readbacks_only`, `test_summary_fallback` raw-digit + LLMUnavailable).
Changed: `tests/unit/test_graph.py` (+`test_human_mode_relays_without_llm`), `tests/unit/test_r6_no_write_tools_in_llm_nodes.py` (handoff names/module forbidden, `handoff_summary.py` scanned, non-vacuity).
Facts the next tasks need: PRODUCT BUG found: a `human_request` intent (no legal keyword) routes `route` -> `handoff_summary` -> `handoff`, but `handoff` re-resolves from state with `escalation_reason=None` and `intent_queue=[]` (no `enqueue` ran), so it raises ValueError "handoff reached without an escalation reason". `handoff_summary` resolves from `nlu.intents` and works. Owner: T15 (`nodes/handoff.py`) / T21 (wiring); fix e.g. have `route`/`handoff_summary` write `escalation_reason`+`handoff_queue`, or have `handoff` read `nlu.intents`.
Deviations: none.
Verify: packet + R6 tests 5 passed; `test_human_mode_relays_without_llm` FAILS on that bug; ruff check/format clean.

### T30 — Design doc updates (D25)
Changed: `docs/solution-docs/{04,02,03,06}` per block; also `08` §7 and §10 step 3 (compose order base → observability → prod).
Facts the next tasks need: 04 §3 now carries the staff routes, `StaffMeResponse`/`HandoffSummary` shapes and SSE deltas; 04 §5 shows escalation v2 and scope.yaml (legal keyword lists abbreviated); 04 §4 says `reference` is derived, not a packet field; `HandoffReason` lists the 8 built values (tool_failure/llm_unavailable/claim_priority not built).
Deviations: none.
Verify: block's grep chain → rc=0.

### T27 — Abstain tests and the Pix test
Created: `backend/tests/unit/test_abstain.py` (`test_abstains_without_tools[es-pix|pt-loans]`).
Changed: `backend/tests/unit/test_sandbox_conversations.py` (`test_pix_routes_out_of_market` now expects route `abstain`, tools_called `[]`).
Facts the next tasks need: `load_session` calls `get_profile` every turn, so the "no tools" proof is `calls == ["get_profile"]` (any read, write or handoff call fails it); recording uses sandbox `_RecordingBankTools`/`_RecordingWriteTools` sharing one list.
Deviations: asserts `["get_profile"]`, not `[]` (load_session bootstrap).
Verify: `uv run pytest tests/unit/test_abstain.py tests/unit/test_sandbox_conversations.py -q` → 8 passed; ruff check + format --check clean.

### T26 — Escalation rule tests
Created: `backend/tests/unit/test_escalation_rules.py` (`test_rule_hands_off` 6 rules × es|pt, `test_unauthorized_rule_hands_off_es_pt`, `test_unauthorized_second_attempt_hands_off`).
Changed: `test_r3_flows.py` (scripts `handoff_summary`, asserts atencion/action_unverified), `test_block_flows.py` (scripts `handoff_summary`, asserts cobranza/fraudes + `ui == ["handoff_banner"]`).
Facts the next tasks need: expected queues are read from the loaded YAML; `human_request` first failed once (handoff node saw empty `intent_queue`) then passed on rerun, so product code changed under it in parallel.
Deviations: unauthorized_access is its own parametrized-by-language test (not inside `test_rule_hands_off`) because it needs two turns.
Verify: 23 passed; ruff check + format --check clean.

### T15 follow-up
`nodes/handoff.py` now resolves intents from `nlu.intents` (same as `handoff_summary`) and reads `state["handoff_request"]` directly; the ValueError on plain `human_request` is gone. `test_handoff_packet.py` 3 passed; ruff/format/mypy clean. `test_human_mode_relays_without_llm` still fails at its 2nd-turn `debug.route == "relay_to_agent"` (got "fallback"), outside handoff.py.
T21 follow-up: `run_turn` skipped `relay_to_agent` (empty update streams as None) so debug.route fell back to "fallback"; graph.py now records a None-update branch node as the route. Mode persistence and `_entry` were fine.
T28 follow-up: after the T15/T21 fixes the full Verify passes: 6 passed, ruff check clean, ruff format --check "3 files already formatted".

### T29 — Staff round-trip integration tests
Created: `backend/tests/integration/test_staff_round_trip.py` (`test_handoff_claim_chat_return`, `test_pt_handoff_happy_path`, `test_staff_access_boundaries`; `_EventTap` reads the `conv:<id>` and `handoff:*` Redis channels the SSE routes relay, since TestClient can't stream endless SSE).
Changed: `tests/integration/conftest.py` (`ItStaff`, `it_staff` keyed by queue: atencion/fraudes), `test_write_path_api.py::test_bank_blocked_unlock_handoff` (scripted `handoff_summary`, asserts banner-only ui and the fraudes/bank_side_block handoff row).
Facts the next tasks need: actors' cookies are passed as explicit headers (one TestClient, one portal loop).
FAILING (product bug, T22 runner.py): `test_handoff_claim_chat_return` step 5. `relay_to_agent` returns `{}`, LangGraph streams it as `None`, so `if values is None: continue` (runner.py ~211) skips the `relay_to_agent` branch; the customer msg is never echoed and the turn stores an empty bot message with route `fallback`. Fix: check `node_name == "relay_to_agent"` before the None guard. With steps 5's two assertions removed, steps 6-7 (return, bot answers, no second handoff = W3) pass.
Verify: 5 passed, 1 failed (the test above).
T22 follow-up: `relay_to_agent` branch moved before the `values is None` guard in runner.py; Verify clean, test_staff_round_trip 3 passed.

### T31 — Cleanup and live end-to-end proof
Changed: `conversation/templates.py` (deleted `handoff_placeholder`, `out_of_market`, `out_of_scope` kinds + entries), `nodes/unsupported.py` (only `injection_suspected` mapped; docstring updated), `frontend/src/client/*` (regenerated by `make client`).
Live (dev stack, real Anthropic): Pix ES turn -> route=abstain, status=out_of_market, chips "Ver cuánto debes…/Hablar con una persona"; debug shows tools=['get_profile'] (load_session only). "quiero hablar con una persona" -> handoff banner HO-20ACFBC7 Atención al cliente, mode human; SQL `queued|atencion|human_request|(null)`; conversations mode bot 1 / human 1.
Reset: `POST /admin/demo/reset` as admin -> 200 but took 354 s (golden DB is 7.7 GB; CREATE DATABASE TEMPLATE copies it, backend 503 during that time; T8's 727 ms was on tiny throwaway DBs). Afterwards `app.handoffs` count 0, accounts agent 4/admin 1/customer 150000, all 5 staff logins 200, health 200.
Cleanup confirmed: `cast(dict, state)` gone from nodes/handoff.py (only cast(HandoffReason) remains); new templates have no literal digits. Criterion 1 grep: queue names only in `Queue` literal/labels (format.py) and staff-name seed map (provision.py).
Deviations: `make check`/`make test-integration` not run (verifier V1, per orchestrator). Reset duration is a demo/deploy risk to flag.
Verify: template grep clean; ruff, mypy (124 files), lint-imports (4 kept), `make client` ok; 24 passed (graph, sandbox, escalation_rules, abstain).

### T29 follow-up (V3 transcript 500)
`store.py` `MessageRow.ui_payload` widened to `dict | list[dict] | None` (no other reader of `.ui_payload`); round-trip test now asserts the claimant's `GET /staff/conversations/{id}/messages` is 200 with the customer ask and handoff bot row. Verify: round_trip + restart + write_path → 7 passed (runner relay bug also fixed by then, so the round trip passes); ruff, format, mypy on store.py clean.

### T15 follow-up 2 (R3 persisted id)
`HandoffTools.create` now returns the persisted `UUID` (`ServiceHandoffTools` returns `service.create`'s id, `InMemoryHandoffTools` the packet's); `nodes/handoff.py` uses the returned id for state, banner, text and audit (packet keeps a candidate id only). `sandbox.py`/`conftest.py` needed no edit (they use `InMemoryHandoffTools`). New test `test_existing_open_handoff_reference_is_reported`; 21 passed; ruff/format/lint-imports clean; mypy only flags pre-existing `tests/conftest.py:156` (not mine).

### T15 follow-up 3
Audit `action` is `attached` when the persisted id differs from the candidate id, else `created`; both cases asserted in `test_handoff_packet.py`.

T26 follow-up: added test_tool_access_denied_second_attempt_hands_off (FakeBank subclass raising AccessDenied; tool-source audit x2, handoff atencion/unauthorized_access, mode human); 15 passed, ruff clean.
T21 follow-up 2: `conversation/hosting.py` registers checkpointed Pydantic types (`CHECKPOINT_TYPES`: UI events, NLUResult/Slots, Fact, ActionResult, HandoffEvidence, ConfirmationDecision) via `saver.with_allowlist`; round-trip shows the warning without it and none with it. New checkpointed models must be added to that list.
T21 follow-up 3: `hosting.py` builds `AsyncPostgresSaver(pool, serde=checkpoint_serde())` with a strict msgpack allowlist; `CHECKPOINT_TYPES` is derived from the UIEvent union, NLUResult, Fact, ActionResult, HandoffEvidence, ConfirmationDecision and their nested models/enums (20 types); the earlier no-op `with_allowlist` is gone. New `tests/unit/test_checkpoint_serde.py` (2 tests).
