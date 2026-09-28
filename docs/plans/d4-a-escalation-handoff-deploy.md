# Plan: D4-A — G10 escalation and handoff backend, G12a AWS deploy

Spec: [`docs/specs/d4-a-escalation-handoff-deploy.md`](../specs/d4-a-escalation-handoff-deploy.md) · Deploy design: [`08-deployment.md`](../solution-docs/08-deployment.md) · Branch: `feat/d4-a-escalation-handoff-deploy`

The human answered the planner's three questions on 2026-09-28 (§"Human decisions" at the end). They are folded into T4, T12, T32/T33 and "Facts checked". Every task can be dispatched as written.

Execution model (human requirement): tasks in the same wave run **in parallel in the same checkout**. Inside a wave, no two tasks edit the same file (migrations, `.importlinter`, `Makefile`, `tests/conftest.py`, `api/v1/__init__.py`, `graph.py`, `templates.py` and `registry.py` included), and no task needs another same-wave task's output. Waves run in order, W1 → W6. Because the checkout is shared, a sibling's half-finished edit can turn your Verify red on a file you don't own. When that happens, wait for the sibling to finish and rerun. Never edit another task's file, and never run `git checkout/stash/reset/commit`.

**Contracts PR (spec D1):** once W1 is done, the orchestrator ships **T1 + T2 + T5** (schemas, SSE deltas, `HandoffTools` protocol, `TurnState` delta, migration `0005`, `Session`/`StaffMeResponse`) as their own PR to `develop`, together with the spec and the spec-time doc edits that are uncommitted in the working tree. `flows.actions.handoff` keeps its call shape `(queue, reason, language)`. Its `reason` is narrowed to `HandoffReason` in T21, so the contract B builds against doesn't change.

## Facts checked against the repo

**Baseline (`a199c1a`, dev stack up):**
- `cd backend && uv run pytest tests/unit -q` gives 65 passed.
- `uv run lint-imports` gives 4 contracts kept.
- `uv run mypy app` is clean (108 files).
- A new red belongs to the task that caused it, except the known-red window after W3 (see Risks).

**Commands and conventions (same as D3-A):**
- Run everything as `cd backend && uv run …`.
- There is no pytest-asyncio. Drive coroutines with `asyncio.run`.
- `get_settings`, `get_engine` and `get_redis` are `lru_cache`d and loop-bound. `cache_clear()` all three when a test changes the loop or DB.
- Alembic always runs as a subprocess with `DATABASE_URL` in its env.
- Integration tests use `it_env`/`it_db`/`it_accounts`/`app_client` from `backend/tests/integration/conftest.py`. `it_db` is session-scoped. An integration Verify must fail on a skip, so pipe it through `tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in'`.
- Errors are `HTTPException(status, detail="<code>")`. Dependencies use the `Annotated[X, Depends(...)]` style.
- Tests always use `ScriptedLLM` (`backend/tests/conftest.py`). It raises `AssertionError` (not `LLMError`) when a step has no scripted output left, so any test that now reaches `handoff_summary` must script an output or an `LLMError` for that step.

**Tooling:**
- mypy strict covers only `app.core.*`, `app.domains.conversation.*` and `app.domains.policy.*`. Other code is type-checked normally: an annotated function passing `str | None` to a `str` parameter still fails `mypy app`.
- import-linter is 2.15. `conversation-no-repository` forbids `app.domains.*.repository` from `app.domains.conversation`, and that includes indirect chains. Its ignore list alerts on unmatched edges, so **every new ignore edge lands in the same task that creates the import**. The one new edge is `app.domains.conversation.tools.handoff -> app.domains.handoff.service` (T22).
- `test_graph.py` asserts that `docs/diagrams/turn-graph-v0.mmd` equals the compiled graph's mermaid. Any graph change must run `make graph-diagram` in the same task.
- `aws` CLI v2 and `jq` are installed. `cfn-lint` is not, so use `uvx cfn-lint`. **There are no AWS credentials on this machine** (`aws sts get-caller-identity` exits 253). `aws cloudformation validate-template` and every live AWS step are run by the human with their own profile (human decision).
- Docker Compose is v5.1.3, so `!override`/`!reset` are supported. Frontend `npm run build` is `vite build && tsc -b`.

**Database:**
- `latam_app` and `latam_golden` are both at alembic `0004`. Revision ids are strings (`"0004"`). The last file is `backend/app/alembic/versions/0004_audit_events.py`.
- `identity.accounts` (`0002`) columns: `account_id uuid pk, role text default 'customer', customer_id text NOT NULL fk bank.customers, login_key text NOT NULL UNIQUE, password_hash, status default 'active', created_at`. It has 150000 rows, all `customer`.
- `app.conversations.mode text default 'bot'` already exists. `app.messages.role` is free text, so `agent` and `system` need no migration.
- Migration Verify pattern (D2-A T2): create `latam_mig_check` in container `latam-cs-postgres-1`, upgrade head, downgrade to the previous revision, upgrade again, check, drop.
- `make seed-identity` upgrades `latam_golden` to head, runs `app.domains.identity.provision` (TRUNCATE + COPY into golden), then `pipeline/load/demo_reset.py`, which drops `latam_app` and recreates it from the template.

**Redis:**
- Keys are `turn:<conv>` (turn lock, 120 s, released by a compare-and-delete Lua script in `runner.py`), `conf:*`, `rl:login:*` and `rl:otp:*`.
- `core/events.py` has only `channel/publish/subscribe` for `conv:<id>`, and it uses `get_redis().pubsub()`.
- The integration conftest deletes `rl:login:* turn:* conv:* conf:* rl:otp:*` after each test.

**Code that exists and is reused (real names):**
- `graph.py`:
  - `_entry`, `_dispatch`, `_after_flow` (routes `tool_unavailable|no_cards|clarification_exhausted` to `fallback`) and `_after_segment`.
  - Tables `_BRANCH_NODES`, `_INTENT_NODES`, `_FLOW_NODES`.
  - `GraphState` has graph-local `segments`/`ui`/`user_text`.
  - `run_turn` builds `DebugInfo`. `build_graph` imports node modules inside its body.
- `nodes/route.py` is a **pure conditional-edge function** (it cannot write state). It imports `_FLOW_NODES`/`_INTENT_NODES`/`_MANAGEMENT_INTENTS` from `graph`, and sends `out_of_market|out_of_scope|injection_suspected` to `unsupported`.
- `nodes/unsupported.py` maps those statuses to templates. `nodes/fallback.py` maps `no_cards|tool_unavailable|clarification_exhausted`.
- `nodes/load_session.py` resets `facts`, `segments`, `nlu`, `escalation_reason` and `ui` every turn. It calls `bank_tools.get_profile()`. It does **not** touch `mode`.
- `flows/actions.py`:
  - `handoff(queue, reason: str, language)` fills `handoff_placeholder`.
  - `_action_unverified_handoff` reads `load_escalation_policy().action_queues.action_unverified`.
  - `fill(template, **values)` is the placeholder filler.
- Escalation v1 readers that v2 breaks:
  - `flows/card_unlock.py` ~L139-141 and `flows/replacement.py` ~L165-170 read `escalation.customer_not_active.queue`.
  - `card_unlock.py` ~L170-177 reads `bank_side_queues` (unchanged in v2).
  - `flows/card_info.py` ~L261 reads `customer_not_active.statuses` (unchanged).
- `select_card` returns `Fallback()` at 2 failures. Four flows then set `escalation_reason="clarification_exhausted"` with no queue.
- `compose.py`:
  - `_PROMPT = PromptRef("compose", 4)`, `Goal = Literal["card_status","balance_due"]`.
  - `compose_reply(llm, *, language, country, goal, facts)` does the digit/brace rejection, and falls back to the `fallback` template on `LLMError`.
- `prompts/load_prompt(PromptRef)` reads `prompts/<name>@v<n>.md`.
- `core/llm/registry.py`:
  - `Step = Literal["nlu","compose"]`, `MODEL_REGISTRY[step][provider]`, `TEMPERATURE`.
  - The Bedrock IDs are `us.anthropic.claude-haiku-4-5-20251001-v1:0` with the comment `# unconfirmed until K2`.
- `ui.py`: `QuickRepliesPayload.slot: Literal["block_kind"]`, the `UIEvent` discriminated union, `PickerOption{label}`.
- `templates.py`: `TemplateKind` Literal + `_TEMPLATES`. The rule is that no template contains a digit. It has `handoff_placeholder`, `out_of_market`, `out_of_scope` and `injection_suspected`.
- `localization/format.py`: `Queue = Literal["atencion","cobranza","fraudes"]`, `_QUEUE_LABELS[language][queue]`, `queue_label()`.
- `runner.py`:
  - `start_turn` takes the lock and persists the customer text. `_run_turn` builds the config (`thread_id, session, bank_tools, llm, bank_write_tools, vault`) through `registry`.
  - It publishes `status` per node, records `rule_hit` for any `escalation_reason`, publishes `ui`, persists and publishes the bot `message`, `debug` (non-prod) and `done`.
  - It mirrors `_BRANCH_NODES`.
- `conversation/store.py`: `create_conversation`, `close_conversation`, `get_conversation → ConversationRow{id, customer_id, language, mode, status}`, `add_message(conversation_id, turn_id, role, content, ui_payload)`, `list_messages`.
- `hosting.py`: `TurnHost{graph, pool, llm, tasks}`, `open_host(database_url, llm)`, `close_host(host)`.
- `tools/registry.py`:
  - `build_tool_context(session, conversation_id, trace_id)` uses `session.customer_id`.
  - Also `audit_recorder_for`, `turn_tools`, `RecordingBankTools` (records `access_denied` and re-raises `AccessDenied`). **No flow catches `AccessDenied` today**, so it surfaces as `turn.failed`.
- Identity:
  - `Session{account_id, role: Literal["customer"], customer_id: str, step_up_at}`. `TokenClaims` mirrors it.
  - `AccountRow{account_id, role, customer_id: str, password_hash, status}`.
  - `service.login` uses the limiter key `rl:login:<login_key>`. `service.me` calls `customers_service.get_login_profile(session.customer_id)`.
  - `passwords.login_key(document_type, number, hmac_key)` and `generate_password(customer_id, seed)`.
  - `provision.main()` writes `data/secrets/credentials.csv` at 0600.
  - `deps.RoleGuard(roles)`, `require_role(*roles)`, `require_csrf`, `get_session`.
- API:
  - `api/v1/__init__.py` includes `health`, `auth.public_router`, `auth.router` and `conversations.router`. `test_idp` is mounted in `main.create_app` only when `APP_ENV=eval`.
  - `auth.py` has `_set_auth_cookies(response, token=, csrf_token=, settings=)`.
  - `conversations.py` has `get_owned_conversation`, `_sse_stream(stream)` (`: connected`, frames, `: ping` every 15 s) and the stream route pattern (subscribe before returning).
  - `session.customer_id` is used at `create_conversation` and `RedisConfirmationStore(...)`.
- Audit: `audit/schemas.py` has `AuditType` (no `handoff`), `AuditActor = Literal["bot","customer","system"]`, `Recorder` Protocol, `NullAuditRecorder`. `audit/service.AuditRecorder(conversation_id=, turn_id=, trace_id=, policy_version=, actor=)`.
- Policy:
  - `policy/registry.py` `_MODELS_BY_STEM` validates `tools/escalation/min_payment` with their own models, and every other stem header-only.
  - `PolicyBundle{hash, tools, escalation, min_payment, files}`.
  - Loaders resolve `_REPO_ROOT = parents[4]` (in the container that is `/`; dev compose mounts `../policies:/policies:ro`).
  - `policy` must not import `app.domains.conversation` (`06` §2), so policy code uses plain `str` literals, not `Intent`/`Topic`.
- NLU schema (`conversation/schemas.py`): `Intent` includes `human_request`. `NLUStatus` includes `injection_suspected`. `Topic = loans|accounts|investments|insurance|transfers|pix_boleto|other`, and `NLUSlots.topic`.
- Fixtures (`tests/fixtures/fakebank`):
  - `CLI-TFINACT00004` is an Inactive customer (customer_not_active).
  - `CLI-TFBLOCKD0003` has a bank-side-blocked card (bank_side_block → fraudes).
  - `CLI-TFSINGLE0002` has one Active card.
  - `CLI-TFMULTI00001` has several cards.
- `tests/conftest.py::make_session(customer_id, fakebank_dir, llm, *, raw_writes=...)` builds config keys `thread_id, session, bank_tools, bank_write_tools, vault, llm`. `sandbox.py` `_build_session` builds the same keys.
- Existing tests that the switchover in W3 changes:
  - `test_r3_flows.py` (~L76-80, "Atención" + `action_unverified`).
  - `test_block_flows.py` (~L178-182, "Fraudes").
  - `test_sandbox_conversations.py::test_pix_routes_out_of_market` (asserts the `out_of_market` template).
  - `integration/test_write_path_api.py::test_bank_blocked_unlock_handoff` (~L381-408).
- Deploy: `docker/docker-compose.{base,dev,observability}.yml` exist. Base publishes `5432:5432` and nginx `80:80`. Observability publishes `8428, 9428, 10428, 3000`. `docker/nginx/dev.conf` exists. `backend/Dockerfile` runs uvicorn without `--reload`. `infra/` does not exist. `.gitignore` ignores `.env` and `data/`, so `.env.prod.example` is committable and `data/secrets/staff_credentials.csv` is ignored.
- Makefile: `COMPOSE := docker compose --env-file .env -f base -f dev -f observability`. Targets are `setup up down test check client data demo-reset seed-identity chat-* graph-diagram test-integration`.

**Human decisions (plan questions, 2026-09-28):**
- **Staff accounts (T12), exact values.** `display_name` is what customers see in `mode{human, agent_display_name}`.

  | username | role | staff_queue | display_name |
  |---|---|---|---|
  | `agent.atencion` | agent | `atencion` | Laura |
  | `agent.cobranza` | agent | `cobranza` | Diego |
  | `agent.fraudes` | agent | `fraudes` | Sofía |
  | `agent.reclamos` | agent | `reclamos` | Mateo |
  | `admin` | admin | null | Swip Admin |

  Agent usernames are built in code as `f"agent.{queue}"` over `get_args(Queue)`, and the display names come from a queue → name mapping in `provision.py`. This mapping is seed data, not a rule's queue (success criterion 1).
- **`policies/scope.yaml` content (T4):** every topic has `human_queue: atencion`.

  | topic | kind | reason_key | closest_intents |
  |---|---|---|---|
  | `pix_boleto` | out_of_market | `market_not_served` | [balance_due] |
  | `loans` | out_of_scope | `not_card_product` | [card_status] |
  | `accounts` | out_of_scope | `not_card_product` | [card_status] |
  | `investments` | out_of_scope | `not_card_product` | [] |
  | `insurance` | out_of_scope | `not_card_product` | [] |
  | `transfers` | out_of_scope | `not_card_product` | [] |
  | `other` | out_of_scope | `outside_card_support` | [] |
- **Live AWS deploy:** the human runs every AWS command with their own profile. No agent runs `aws`, `make infra-*`, `make deploy*` or anything on the box. T32's agent writes the runbook and checklist. The human runs them and pastes the outputs. T33's agent records those outputs and makes the code edits that follow from them.

**Plan-level conventions this card sets (every task follows them):**
- New node names: `abstain`, `handoff_summary`, `handoff`, `relay_to_agent`.
  - Graph-local channel `handoff_request: NotRequired[str]` on `GraphState`: `handoff_summary` writes it, `handoff` reads it.
  - The runner recognizes a human-mode turn by the `relay_to_agent` node in the update stream, and a new handoff by the `handoff` node's update carrying `handoff_id`.
- Config keys added to `config["configurable"]`:
  - `handoff_tools`: a `HandoffTools`. Only `nodes/handoff.py` reads it.
  - `audit`: a `Recorder`. Nodes read it as `configurable.get("audit") or NullAuditRecorder()` so older test configs keep working.
- Resolving a handoff's reason, queue and priority is one pure function, `policy.escalation.resolve_escalation(...)` (T3). It is called by `route` (detection), `handoff_summary` (input keys) and `handoff` (write). Queue names never appear as literals in Python rule code (success criterion 1). Provisioning iterates `typing.get_args(Queue)`.
- `app.handoffs` writes and the matching `app.conversations.mode` update happen in **one transaction** in `handoff.repository` (create → `human`, return → `bot`). The checkpoint's `mode` is written by the `handoff` node (create) and by `takeover.return_to_bot` through `graph.aupdate_state` (return).
- `reference = "HO-" + handoff_id.hex[:8].upper()` comes from one helper, `handoff.schemas.reference_for(handoff_id)`.
- A tool `AccessDenied` is caught by a wrapper that `graph.py` puts around each flow node (T21). It counts as an unauthorized attempt with `source: tool`. The `nlu` source is counted in `unsupported` (T16).

## Components

| Component | Path | Depends on |
|---|---|---|
| Handoff contracts | `app/domains/handoff/{__init__,schemas}.py` (new) | `localization.format.Queue` |
| Handoff persistence + service | `app/domains/handoff/{repository,service}.py` (new) | `core.db`, `core.events`, migration 0005 |
| Handoff tool adapter | `app/domains/conversation/tools/handoff.py` (new: `HandoffTools` Protocol, `InMemoryHandoffTools`, later `ServiceHandoffTools`) | handoff schemas, then handoff service |
| Escalation policy v2 + resolver | `policies/escalation.yaml`, `app/domains/policy/escalation.py` | `localization.format.Queue` |
| Scope policy | `policies/scope.yaml`, `app/domains/policy/scope.py`, `policy/registry.py` | none |
| Graph nodes | `conversation/nodes/{abstain,handoff_summary,handoff,relay,unsupported,route}.py` | policies, schemas, `core.llm` (summary and compose only) |
| Graph wiring | `conversation/graph.py`, `nodes/__init__.py`, `flows/actions.py`, `docs/diagrams/turn-graph-v0.mmd` | all nodes |
| Turn runner | `conversation/runner.py` | tools/handoff, events |
| Takeover helpers | `conversation/takeover.py` (new: `return_to_bot`, `relay_agent_message`, `publish_mode`) | hosting, store, events, templates |
| Staff identity | `identity/{models,tokens,service,repository,passwords,provision}.py` | migration 0005 |
| Staff/admin API | `api/v1/{staff_auth,staff,admin}.py` (new), `api/v1/__init__.py` | identity, handoff service, takeover, `core.demo_reset` |
| Core infra | `core/events.py` (handoff channels), `core/demo_reset.py` (new), `core/llm/registry.py` | Redis, DB |
| Deploy | `docker/docker-compose.prod.yml`, `docker/nginx/{Dockerfile.prod,prod.conf}`, `.env.prod.example`, `infra/aws/*`, `Makefile` | none (runtime: AWS) |

## Build order

1. **W1: contracts and leaf changes.** Schemas, the migration, policy v2, `Session` typing, templates, event channels, the demo-reset core and the deploy artifacts have no dependencies on each other. B is unblocked by T1/T2/T5.
2. **W2: domain modules that consume W1.** The handoff service needs schemas + migration + events. Each new node needs schemas + policy + templates. Staff login needs the migration columns + `Session`. The router skeletons are registered once here, so W3 route tasks only edit their own module.
3. **W3: switchover.** One task owns `graph.py`, `route.py` and `actions.py` (they change together). The runner, staff routes and admin route are siblings with disjoint files.
4. **W4: tests and docs.** They need the real behavior. Each test task owns the old tests it must update.
5. **W5 (alone): cleanup and local end-to-end proof.** Dead templates, the live checks, `make client`, `make check`, `make test-integration`.
6. **W6 (sequential): T32 writes the deploy runbook and checklist, the human runs it with their own AWS profile, then T33 records the results and applies the Bedrock confirmation.** Cut line: D5 morning.

## Parallel waves

| Wave | Tasks (parallel, disjoint files) | Runs after |
|---|---|---|
| **W1** | T1, T2, T3, T4, T5, T6, T7, T8, T9, T10 | none |
| **W2** | T11, T12, T13, T14, T15, T16, T17, T18, T19, T20 | W1 |
| **W3** | T21, T22, T23, T24, T25 | W2 |
| **W4** | T26, T27, T28, T29, T30 | W3 |
| **W5** | T31 (alone) | W4 |
| **W6** | T32 (runbook, agent) → human runs it → T33 (record results, agent), all sequential | T31 |

Shared-file ownership:
- One task per wave for: `graph.py` T21 · `nodes/__init__.py` T21 · `route.py` T21 · `flows/actions.py` T3 (W1) and T21 (W3) · `templates.py` T6 (W1) and T31 (W5) · `unsupported.py` T16 (W2) and T31 (W5) · `tools/registry.py` T5 · `tools/handoff.py` T1 (W1) and T22 (W3).
- One task per wave for: `.importlinter` T22 · `Makefile` T10 · `tests/conftest.py` T18 · `tests/integration/conftest.py` T29 · `api/v1/__init__.py` T19 · `core/llm/registry.py` T14 (W2) and T33 (W6) · `identity/service.py` T5 (W1) and T12 (W2) · migration `0005` T2 · `pyproject.toml` not touched.

## Touch map

| File | New/mod | Task | Change |
|---|---|---|---|
| `backend/app/domains/handoff/__init__.py` | new | T1 | docstring only, no imports |
| `backend/app/domains/handoff/schemas.py` | new | T1 | `HandoffReason`, `Priority`, `HandoffStatus`, `HandoffEvidence`, `VerifiedFact`, `ActionTaken`, `HandoffPacket`, `HandoffSummary`, `HandoffDetail`, `TranscriptMessage`, `reference_for` |
| `backend/app/domains/conversation/ui.py` | mod | T1 | `HandoffBannerEvent`, `quick_replies.slot` gets `"abstain"`, `ModePayload`, `MessagePayload` |
| `backend/app/domains/conversation/state.py` | mod | T1 | `TurnState` delta |
| `backend/app/domains/conversation/tools/handoff.py` | new, then mod | T1, T22 | Protocol + in-memory fake; then `ServiceHandoffTools` |
| `backend/app/domains/audit/schemas.py` | mod | T1 | `AuditType` gets `handoff`; `AuditActor` gets `agent:<id>` |
| `backend/app/alembic/versions/0005_handoffs_staff.py` | new | T2 | migration |
| `policies/escalation.yaml` | mod | T3 | v2 |
| `backend/app/domains/policy/escalation.py` | mod | T3 | v2 model + `resolve_escalation`, `legal_hit`, `rule` |
| `backend/app/domains/localization/format.py` | mod | T3 | `reclamos` + labels |
| `backend/app/domains/conversation/flows/{actions,card_unlock,replacement}.py` | mod | T3 | read queues from `rules.*` (not in the spec's touch map; forced by v2 dropping `customer_not_active.queue` and `action_queues`) |
| `policies/scope.yaml`, `backend/app/domains/policy/scope.py` | new | T4 | ADR-026 scope map |
| `backend/app/domains/policy/registry.py` | mod | T4 | `scope` in bundle |
| `backend/app/domains/identity/{models,tokens,service}.py` | mod | T5 | `Session.role`/`customer_id` optional, `StaffMeResponse`, `StaffLoginRequest` |
| `backend/app/api/v1/conversations.py` | mod | T5 | narrow `session.customer_id` |
| `backend/app/domains/conversation/tools/registry.py` | mod | T5 | R1 guard in `build_tool_context` |
| `backend/tests/unit/test_r1_customer_scope.py` | mod | T5 | `test_staff_session_cannot_build_tool_context` |
| `backend/app/domains/conversation/templates.py` | mod | T6, T31 | add `handoff_transfer`, `back_with_cardy`, `abstain_fallback`; then delete dead kinds |
| `backend/app/core/events.py` | mod | T7 | `handoff:<queue>` publish + subscribe/psubscribe |
| `backend/app/core/demo_reset.py` | new | T8 | DB reset + Redis key purge |
| `docker/docker-compose.prod.yml`, `docker/nginx/{Dockerfile.prod,prod.conf}`, `.env.prod.example` | new | T9 | prod layer |
| `infra/aws/{ec2-stack.yaml,render-env.sh,deploy.sh,smoke.sh}`, `Makefile` | new/mod | T10 | IaC + targets; T33 edits the stack only if the human's run forced a fix |
| `backend/app/domains/handoff/{repository,service}.py` | new | T11 | persistence + pub/sub |
| `backend/app/domains/identity/{repository,passwords,service,provision}.py` | mod | T12 | staff lookup, staff login, seeding |
| `backend/app/domains/conversation/nodes/abstain.py`, `nodes/compose.py`, `prompts/compose@v5.md` | new/mod | T13 | structured abstain |
| `backend/app/domains/conversation/nodes/handoff_summary.py`, `prompts/handoff_summary@v1.md`, `backend/app/core/llm/registry.py` | new/mod | T14 | LLM `request` drafting |
| `backend/app/domains/conversation/nodes/handoff.py` | new | T15 | packet + `handoff.create` |
| `backend/app/domains/conversation/nodes/unsupported.py` | mod | T16, T31 | unauthorized counting |
| `backend/app/domains/conversation/takeover.py` | new | T17 | return to bot, agent relay |
| `backend/tests/conftest.py`, `backend/app/domains/conversation/sandbox.py` | mod | T18 | `handoff_tools` + `audit` config keys |
| `backend/app/api/v1/{staff_auth,staff,admin}.py` | new | T19, then T23/T24/T25 | skeleton routers, then routes |
| `backend/app/api/v1/__init__.py` | mod | T19 | register routers |
| `backend/scripts/chat_api.py` | mod | T20 | print `mode`/`handoff_banner`/`message{role}` |
| `backend/app/domains/conversation/{graph.py,nodes/route.py,nodes/relay.py,nodes/__init__.py}`, `docs/diagrams/turn-graph-v0.mmd` | mod/new | T21 | wiring |
| `backend/app/domains/conversation/runner.py`, `backend/.importlinter` | mod | T22 | human mode, handoff events |
| `backend/tests/unit/test_r13_routes.py` | mod | T24 | staff/admin guards |
| `backend/tests/unit/test_escalation_rules.py` (new), `test_r3_flows.py`, `test_block_flows.py` | new/mod | T26 | |
| `backend/tests/unit/test_abstain.py` (new), `test_sandbox_conversations.py` | new/mod | T27 | |
| `backend/tests/unit/test_handoff_packet.py` (new), `test_graph.py`, `test_r6_no_write_tools_in_llm_nodes.py` | new/mod | T28 | |
| `backend/tests/integration/{conftest.py,test_staff_round_trip.py,test_write_path_api.py}` | new/mod | T29 | |
| `docs/solution-docs/{02,03,04,06}-*.md` | mod | T30 | D25 |
| `frontend/src/client/*` (generated) | mod | T31 | `make client` |

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| Escalation v2 drops `customer_not_active.queue`/`action_queues` and breaks three flows at import/type level | T3 owns the YAML, the model and all three call sites in one task. It verifies with the flow tests |
| `Session.customer_id: str \| None` ripples into mypy errors in `conversations.py`, `service.me` and `registry` | T5 owns every ripple site and verifies with `mypy app` |
| A staff session reaches bank tools (R1) | T5: `build_tool_context` raises unless `role == "customer"` and `customer_id` is set. The R1 unit test proves it |
| A staff route without a role guard, or an agent reading an unclaimed conversation (R13) | T19 declares guards on the routers at creation. T24 adds `get_claimed_conversation` and extends `test_r13_routes.py`. T29 proves it across actors |
| `handoff_summary` gets write/handoff tools (R6) | T14 reads no tool keys. T28 extends the R6 scan with `handoff_tools`/`HandoffTools` and a non-vacuity snippet |
| The customer's text or PII reaches the summary LLM (R5), or a raw digit reaches the reply (R4) | T14: the input is only code-built keys. The draft is rejected on a raw digit, an unknown placeholder or a brace, and is capped at 200. T28 asserts the typed text isn't in the packet and tests the fallback |
| "Done" or verified facts without a read-back in the packet (R3) | T15 takes `verified_facts`/`actions_taken` only from `actions` with `verified=True`. T28 tests it |
| Summary LLM failure blocks the handoff (R11) | T14 falls back to a fixed ES/PT template per reason on `LLMError`/invalid output. T28 tests it |
| Import-linter: conversation → `handoff.service` → `handoff.repository` | T22 adds the single ignore edge in the task that creates the import. Nothing else in conversation imports `app.domains.handoff.service` |
| The graph diagram test goes red on any graph change | T21 runs `make graph-diagram` |
| **Known-red window between W3 and W4:** `test_r3_flows`, `test_block_flows`, `test_sandbox_conversations::test_pix_routes_out_of_market` and `test_write_path_api::test_bank_blocked_unlock_handoff` fail after T21 (new route/LLM step) | Each is owned by one W4 task (T26, T27, T29). W3 Verify commands don't run them. The verifier's `make check` runs after W5 |
| Two handoffs for one conversation | The partial unique index in T2. T11 maps the unique violation to a no-op (returns the existing open handoff) |
| Return to bot races a customer turn | T17 takes the same `turn:<id>` lock (`SET NX EX 120`) and raises a busy error the route maps to `409 turn_in_progress` |
| `make seed-identity` (T12) drops `latam_app` while siblings run | W2 siblings use only throwaway `latam_it_*`/`latam_mig_check` DBs, never `latam_app` |
| Demo reset from inside the backend while the engine/checkpointer hold connections | T8 disposes the engine. T25 closes the turn host before and reopens it after. T8 is verified on throwaway DBs, never on `latam_app` |
| Prod overlay leaves a port on `0.0.0.0` | T9 uses `!override` port lists. Its Verify is the spec's `compose config \| jq` proof (only `80`, `443`) |
| A secret is echoed during deploy, or `data/` is synced to S3 | T10: `render-env.sh` uses `umask 077`, writes the file and never prints values; there is no `aws s3 sync` in any script. T10 Verify greps for `set -x`/`echo \$` |
| Let's Encrypt rate limit on sslip.io | T10 `deploy.sh`/runbook issues the staging certificate first. The Route 53 fallback is documented in `08` §8. T32 follows it |
| No AWS credentials on this machine | By human decision, only the human runs AWS commands. T32 writes a runbook whose every local step is dry-run-checked, and T33 records the human's outputs. T10 validates the template offline with `uvx cfn-lint` |

## Tests

| Test | Task |
|---|---|
| `unit/test_escalation_rules.py::test_rule_hands_off[rule×es\|pt]` | T26 |
| `unit/test_escalation_rules.py::test_unauthorized_second_attempt_hands_off` | T26 |
| `unit/test_abstain.py::test_abstains_without_tools[es-pix\|pt-loans]` | T27 |
| `unit/test_handoff_packet.py::test_packet_from_readbacks_only` | T28 |
| `unit/test_handoff_packet.py::test_summary_fallback` | T28 |
| `unit/test_graph.py::test_human_mode_relays_without_llm` | T28 |
| `unit/test_r6_no_write_tools_in_llm_nodes.py` (extended) | T28 |
| `unit/test_r13_routes.py` (extended) | T24 |
| `unit/test_r1_customer_scope.py::test_staff_session_cannot_build_tool_context` | T5 |
| `integration/test_staff_round_trip.py::test_handoff_claim_chat_return` | T29 |
| `integration/test_staff_round_trip.py::test_pt_handoff_happy_path` | T29 |
| `integration/test_staff_round_trip.py::test_staff_access_boundaries` | T29 |
| A5 runnable proofs 1–3 (validate-template, compose ports, `make smoke-prod`) | T10 (cfn-lint offline), T9 (ports), the human's run of the T32 runbook (validate-template, smoke), recorded by T33 |

Success criteria map:
- SC1: T26 + grep in T31.
- SC2: T27 + `make chat-api` in T31.
- SC3: T28 + SQL in T31.
- SC4: T29 + `make seed-identity` in T12.
- SC5: T5, T24, T28 + `make check` in T31.
- SC6, SC7: the human's run of the T32 runbook, recorded by T33.
- SC8: local in T31, public in the human's run, recorded by T33.
- SC9: T30.

## Tasks

- [ ] T1: Handoff contracts — schemas, SSE deltas, `TurnState` delta, `HandoffTools` protocol, audit literals (W1)
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" (SSE deltas, `HandoffPacket`, `TurnState` delta, Staff API `HandoffSummary`), spec D10, D11 and D23; `docs/solution-docs/04-contracts.md` §4 (packet shape); `backend/app/domains/conversation/ui.py` (the event pattern to mirror)
  - Acceptance:
    - `handoff/__init__.py` is docstring-only. `handoff/schemas.py` imports only stdlib, pydantic and `app.domains.localization.format.Queue`. All models are frozen with `extra="forbid"`. It defines:
      - `HandoffReason`: the spec's 8 values.
      - `Priority`: `high|normal`. `HandoffStatus`: `queued|claimed|returned`.
      - `HandoffEvidence{type: Literal["transaction"], ref, fraud_score: int|None}`.
      - `VerifiedFact{fact, value, source}`.
      - `ActionTaken{tool, result: Literal["applied"], verified: Literal[True], audit_event_id, at, tracking_id?, case_id?}`.
      - `HandoffPacket`: the `04` §4 fields, with `sentiment: None`, `request: str` (max 200) and `created_at`.
      - `HandoffSummary`, `HandoffDetail`, `TranscriptMessage{role, text, created_at}`, exactly as spec §"Staff API".
      - `reference_for(handoff_id: UUID) -> str`.
    - `ui.py`:
      - Adds `HandoffBannerPayload{handoff_id, reference, queue, queue_label}` and `HandoffBannerEvent(kind="handoff_banner")` to the `UIEvent` union.
      - `QuickRepliesPayload.slot` becomes `Literal["block_kind","abstain"]`.
      - Adds `ModePayload{mode: Literal["bot","human"], agent_display_name: str|None}` and `MessagePayload{role: Literal["bot","customer","agent","system"], text, sources: list[str], agent_display_name: str|None = None}`.
    - `state.py` `TurnState` gains `handoff_queue`, `handoff_id`, `unauthorized_attempts` and `handoff_evidence` (all `NotRequired`, types per the spec).
    - `tools/handoff.py`:
      - `HandoffTools` Protocol with `async def create(self, packet: HandoffPacket) -> None` (no `customer_id` or `ctx` parameter).
      - `InMemoryHandoffTools` with `.created: list[HandoffPacket]`.
      - No import of `app.domains.handoff.service` yet.
    - `audit/schemas.py`: `AuditType` gains `"handoff"`, and `AuditActor` accepts `"bot"|"customer"|"system"` or a string matching `agent:<uuid>` (still no DB import).
  - Verify: `cd backend && uv run ruff check app/domains/handoff app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/tools/handoff.py app/domains/audit/schemas.py && uv run ruff format --check app/domains/handoff app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/tools/handoff.py app/domains/audit/schemas.py && uv run mypy app/domains/handoff app/domains/conversation/ui.py app/domains/conversation/state.py app/domains/conversation/tools/handoff.py app/domains/audit/schemas.py && uv run lint-imports && uv run pytest tests/unit/test_audit_pairs.py tests/unit/test_card_select.py -q`
  - Files: `backend/app/domains/handoff/__init__.py`, `backend/app/domains/handoff/schemas.py`, `backend/app/domains/conversation/ui.py`, `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/tools/handoff.py`, `backend/app/domains/audit/schemas.py`

- [ ] T2: Migration `0005_handoffs_staff` (W1)
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "Migration `0005_handoffs_staff`"; `backend/app/alembic/versions/0004_audit_events.py` (style, revision ids); `backend/app/alembic/versions/0002_identity_conversations.py` lines 30-80 (current `identity.accounts`/`app.conversations`)
  - Acceptance:
    - Revision `"0005"`, down `"0004"`. It does exactly the spec's DDL:
      - `customer_id` becomes nullable.
      - Adds `username text unique null`, `display_name text null`, `staff_queue text null`.
      - Two CHECKs.
      - `app.handoffs` with its FKs, index `(status, queue, created_at desc)` and a partial unique index on `conversation_id WHERE status IN ('queued','claimed')`.
    - `downgrade()` reverses it all (drop the table, drop the CHECKs/columns, `customer_id` NOT NULL again).
    - No existing migration is edited.
  - Verify: `docker exec latam-cs-postgres-1 psql -U postgres -c 'DROP DATABASE IF EXISTS latam_mig_check' -c 'CREATE DATABASE latam_mig_check' && cd backend && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check uv run alembic upgrade head && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check uv run alembic downgrade 0004 && DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/latam_mig_check uv run alembic upgrade head && docker exec latam-cs-postgres-1 psql -U postgres -d latam_mig_check -Atc "select count(*) from pg_indexes where tablename='handoffs'" && docker exec latam-cs-postgres-1 psql -U postgres -c 'DROP DATABASE latam_mig_check' && uv run ruff check app/alembic/versions && uv run ruff format --check app/alembic/versions` (the index count is ≥ 3: pk, status index, partial unique). Use the `.env` Postgres credentials if they differ from `postgres:postgres`, and never print them.
  - Files: `backend/app/alembic/versions/0005_handoffs_staff.py`

- [ ] T3: `escalation.yaml` v2, its model and resolver, `reclamos` queue, and the three v1 call sites (W1)
  - Depends on: nothing
  - Read exactly these: spec §"Contracts" → "`policies/escalation.yaml` v2", spec D2–D7; `backend/app/domains/policy/escalation.py`; `backend/app/domains/localization/format.py` lines 30-100 and 170-183
  - Acceptance:
    - `policies/escalation.yaml` is byte-for-byte the spec's v2 block (comment line allowed).
    - `EscalationPolicy`:
      - Drops `action_queues` and `customer_not_active.queue`.
      - Adds `rules: dict[str, RulePolicy{queue: Queue|None, priority: Literal["high","normal"], open_questions: list[str] = []}]`, `human_request_queues{default: Queue, by_flow: dict[str, Queue]}`, `unauthorized_access{attempts_before_handoff: int}` and `legal_keywords{es: list[str], pt: list[str]}`.
      - Keeps `bank_side_queues`.
      - A model validator requires a `rules` entry for each of the 8 spec reasons.
    - Pure helpers in the same module, typed with `str`, with no conversation import:
      - `legal_hit(text, policy) -> bool`: lowercase, strip accents via `unicodedata` NFKD on both sides, whole-word or phrase match with `\b` boundaries, checking both languages' lists.
      - `rule(policy, reason) -> RulePolicy`.
      - `resolve_escalation(policy, *, reason: str|None, queue: str|None, pending_flow: str|None, intents: list[str], text: str) -> Resolution{reason, queue: Queue, priority} | None`. Order:
        1. A `reason` already in state → queue from state, else `rules[reason].queue`.
        2. Else `legal_hit` → `legal_regulator`.
        3. Else `"human_request" in intents` → `human_request_queues.by_flow.get(pending_flow, default)`.
        4. Else `None`.
      - A resolution whose queue ends up `None` raises `ValueError` (a caller bug, e.g. bank_side without a queue).
    - `format.Queue` gains `"reclamos"`, with ES and PT labels in `_QUEUE_LABELS`.
    - `flows/actions.py` `_action_unverified_handoff`, and `flows/card_unlock.py`/`flows/replacement.py` `customer_not_active` handoffs, read the queue from `rule(policy, "<reason>").queue`. Their behavior is otherwise unchanged (they still produce the placeholder reply until T21).
  - Verify: `cd backend && uv run pytest tests/unit/test_policy_registry.py tests/unit/test_r2_confirmation_store.py tests/unit/test_block_flows.py tests/unit/test_r3_flows.py tests/unit/test_format.py tests/unit/test_card_info_flows.py -q && uv run python -c "from app.domains.policy.escalation import load_escalation_policy as l, legal_hit as h; p=l(); assert h('voy a poner una DENUNCIA', p) and h('falar com a Procon', p) and not h('sicario', p)" && uv run ruff check app/domains/policy app/domains/localization app/domains/conversation/flows && uv run ruff format --check app/domains/policy app/domains/localization app/domains/conversation/flows && uv run mypy app/domains/policy app/domains/localization app/domains/conversation/flows`
  - Files: `policies/escalation.yaml`, `backend/app/domains/policy/escalation.py`, `backend/app/domains/localization/format.py`, `backend/app/domains/conversation/flows/actions.py`, `backend/app/domains/conversation/flows/card_unlock.py`, `backend/app/domains/conversation/flows/replacement.py`

- [ ] T4: `policies/scope.yaml` and its loader in the policy bundle (W1)
  - Depends on: nothing
  - Read exactly these: spec D18 and §"Contracts" → "`policies/scope.yaml` (new)"; `backend/app/domains/policy/registry.py`; `backend/app/domains/policy/escalation.py` (loader pattern only)
  - Acceptance:
    - `policies/scope.yaml` has `provenance`/`version` and one `topics.<Topic>` entry for each of the 7 topics, with exactly these values (human decision; every `human_queue` is `atencion`):
      - `pix_boleto`: `out_of_market`, `market_not_served`, `[balance_due]`.
      - `loans` and `accounts`: `out_of_scope`, `not_card_product`, `[card_status]`.
      - `investments`, `insurance` and `transfers`: `out_of_scope`, `not_card_product`, `[]`.
      - `other`: `out_of_scope`, `outside_card_support`, `[]`.
    - `policy/scope.py`: `ScopePolicy` (frozen, `extra="forbid"`) with `TopicScope{kind: Literal["out_of_market","out_of_scope"], reason_key: str, closest_intents: list[str], human_queue: Queue}`. A validator requires exactly the 7 topic keys. Also `load_scope_policy(path=None)`.
    - `registry.py`:
      - Adds `"scope": ScopePolicy` to `_MODELS_BY_STEM` and `scope: ScopePolicy` to `PolicyBundle`.
      - A missing `scope.yaml` is a `PolicyLoadError`.
      - The hash rule is unchanged.
  - Verify: `cd backend && uv run pytest tests/unit/test_policy_registry.py -q && uv run python -c "from app.domains.policy.registry import load_policies; b=load_policies(); t=b.scope.topics; assert t['pix_boleto'].kind=='out_of_market' and t['pix_boleto'].closest_intents==['balance_due'] and t['loans'].closest_intents==['card_status'] and t['other'].closest_intents==[] and {v.human_queue for v in t.values()}=={'atencion'}" && uv run ruff check app/domains/policy && uv run ruff format --check app/domains/policy && uv run mypy app/domains/policy`
  - Files: `policies/scope.yaml`, `backend/app/domains/policy/scope.py`, `backend/app/domains/policy/registry.py`

- [ ] T5: Staff-capable `Session`, `StaffMeResponse`, and the R1 guard on `build_tool_context` (W1)
  - Depends on: nothing
  - Read exactly these: spec D15 and §"Contracts" → "Staff auth"; `backend/app/domains/identity/models.py`; `backend/app/domains/conversation/tools/registry.py` lines 55-75
  - Acceptance:
    - `Session.role: Literal["customer","agent","admin"]` and `customer_id: str | None`. `TokenClaims` mirrors both, and a token without `customer_id` decodes.
    - `identity/models.py` adds `StaffMeResponse{role: Literal["agent","admin"], username, display_name, queue: Queue | None}` and `StaffLoginRequest{username, password}` (frozen, `extra="forbid"`).
    - `service.me` raises if `customer_id` is `None`.
    - `api/v1/conversations.py` narrows `session.customer_id` (a `None` there is a 403 `forbidden_role`; unreachable behind `require_role("customer")`).
    - `registry.build_tool_context` raises `PermissionError` (or a named subclass) unless `session.role == "customer"` and `customer_id` is set.
    - New test `test_staff_session_cannot_build_tool_context`: an `agent` `Session` with `customer_id=None` → raises; a `customer` role with `customer_id=None` → raises.
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py tests/unit/test_login_pii.py tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py tests/unit/test_step_up.py -q && uv run ruff check app/domains/identity app/api/v1/conversations.py app/domains/conversation/tools/registry.py tests/unit/test_r1_customer_scope.py && uv run ruff format --check app/domains/identity app/api/v1/conversations.py app/domains/conversation/tools/registry.py tests/unit/test_r1_customer_scope.py && uv run mypy app`
  - Files: `backend/app/domains/identity/models.py`, `backend/app/domains/identity/tokens.py`, `backend/app/domains/identity/service.py`, `backend/app/api/v1/conversations.py`, `backend/app/domains/conversation/tools/registry.py`, `backend/tests/unit/test_r1_customer_scope.py`

- [ ] T6: Fixed ES/PT texts — `handoff_transfer`, `back_with_cardy`, `abstain_fallback` (W1)
  - Depends on: nothing
  - Read exactly these: spec D12, D14 and D18; `docs/brand.md`; `backend/app/domains/conversation/templates.py` lines 1-80 and 340-400
  - Acceptance:
    - Three new `TemplateKind`s with ES and PT texts in Cardy's voice, with no digit in any text:
      - `handoff_transfer`: placeholders `{queue_label}` and `{reference}`. It says the transfer is happening and the bot stops (`02` §6 step 2).
      - `back_with_cardy`: the return-to-bot system message.
      - `abstain_fallback`: the four-part fixed abstain, with placeholders `{topic_label}`, `{reason}`, `{closest_action}` and `{human_offer}`. A missing closest action is handled by the caller passing an empty string, so the text must read well with it empty.
    - No existing kind is removed (T31 does that).
  - Verify: `cd backend && uv run python -c "from app.domains.conversation.templates import get_template as g; [g(k,l) for k in ('handoff_transfer','back_with_cardy','abstain_fallback') for l in ('es','pt')]; import app.domains.conversation.templates as t; assert not any(c.isdigit() for v in t._TEMPLATES.values() for s in v.values() for c in s)" && uv run pytest tests/unit/test_conversation_basics.py -q && uv run ruff check app/domains/conversation/templates.py && uv run ruff format --check app/domains/conversation/templates.py && uv run mypy app/domains/conversation/templates.py`
  - Files: `backend/app/domains/conversation/templates.py`

- [ ] T7: Handoff channels on Redis pub/sub in `core/events.py` (W1)
  - Depends on: nothing
  - Read exactly these: spec D12 and D17; `backend/app/core/events.py`; `docs/solution-docs/03-data-architecture.md` §6 "Redis"
  - Acceptance:
    - Adds `handoff_channel(queue: str) -> str` (`handoff:<queue>`) and `publish_handoff(queue, event, data)` (same JSON envelope).
    - Adds `subscribe_handoffs(queue: str | None)`, an async context manager like `subscribe`: `subscribe` to one queue channel, or `psubscribe("handoff:*")` when `queue is None`. It yields `(event, data)`, skips the pattern-ack messages (`type` not in `message|pmessage`), and always unsubscribes and closes.
    - No domain import (core stays below domains).
  - Verify: `cd backend && uv run python - <<'EOF'
import asyncio
from app.core import events
async def main():
    async with events.subscribe_handoffs(None) as stream:
        await events.publish_handoff("atencion", "handoff_created", {"x": 1})
        ev, data = await asyncio.wait_for(anext(stream), 5)
        assert ev == "handoff_created" and data == {"x": 1}
asyncio.run(main())
EOF
uv run ruff check app/core/events.py && uv run ruff format --check app/core/events.py && uv run mypy app/core/events.py` (needs the dev Redis on 127.0.0.1:6379 from `make up`)
  - Files: `backend/app/core/events.py`

- [ ] T8: `core/demo_reset.py` — reset `latam_app` from golden inside the backend (W1)
  - Depends on: nothing
  - Read exactly these: spec D21; `pipeline/load/demo_reset.py`; `backend/app/core/db.py`
  - Acceptance:
    - `async def reset_app_database(*, app_db: str = "latam_app", golden_db: str = "latam_golden") -> int` (returns `duration_ms`):
      - Disposes `get_engine()` and clears its cache.
      - Connects with psycopg (async or `asyncio.to_thread` over sync, autocommit) to the `postgres` maintenance DB derived from `get_settings().database_url`.
      - Terminates the other backends on both DBs, then runs `DROP DATABASE {app_db} WITH (FORCE)` + `CREATE DATABASE {app_db} TEMPLATE {golden_db}`.
      - Deletes the Redis keys `conf:*` and `turn:*` with `scan_iter`.
    - Identifiers are validated against `^[a-z_][a-z0-9_]*$` before interpolation.
    - Imports only `app.core.*`. It does not touch the checkpointer pool (the T25 route does).
  - Verify: `docker exec latam-cs-postgres-1 psql -U postgres -c 'DROP DATABASE IF EXISTS latam_rst_g' -c 'DROP DATABASE IF EXISTS latam_rst_a' -c 'CREATE DATABASE latam_rst_g' && docker exec latam-cs-postgres-1 psql -U postgres -d latam_rst_g -c 'CREATE TABLE marker(x int)' && cd backend && uv run python -c "import asyncio; from app.core.demo_reset import reset_app_database as r; print(asyncio.run(r(app_db='latam_rst_a', golden_db='latam_rst_g')))" && docker exec latam-cs-postgres-1 psql -U postgres -d latam_rst_a -Atc "select to_regclass('public.marker') is not null" | grep -x t && docker exec latam-cs-postgres-1 psql -U postgres -c 'DROP DATABASE latam_rst_a' -c 'DROP DATABASE latam_rst_g' && uv run ruff check app/core/demo_reset.py && uv run ruff format --check app/core/demo_reset.py && uv run mypy app/core/demo_reset.py`
  - Files: `backend/app/core/demo_reset.py`

- [ ] T9: Prod Compose layer, prod Nginx image and config, `.env.prod.example` (W1)
  - Depends on: nothing
  - Read exactly these: `docs/solution-docs/08-deployment.md` §7, §8 and §9; spec D19 and §"Contracts" → "Deploy artifacts"; `docker/docker-compose.base.yml`
  - Acceptance:
    - `docker/docker-compose.prod.yml` (layered as base + prod + observability):
      - `backend`: no reload, `APP_ENV=prod`, `LLM_PROVIDER=bedrock`, `AWS_REGION=us-east-1`, `../policies:/policies:ro`, `restart: unless-stopped`, 1 worker.
      - `nginx` builds `docker/nginx/Dockerfile.prod`, publishes `80` and `443`, and mounts the certbot webroot + `letsencrypt` volume.
      - `postgres` binds to `127.0.0.1:5432` (`!override`) with `shared_buffers=2GB`. `redis` has no ports.
      - Every observability port is rebound to `127.0.0.1` with `!override`. `frontend` is not run.
      - A `certbot` service shares the webroot.
    - `Dockerfile.prod` is multi-stage: `node:22` `npm ci && npm run build`, then `nginx:1.27-alpine` with `dist/`.
    - `prod.conf`:
      - `:80` serves `/.well-known/acme-challenge/` and 301s the rest.
      - `:443` terminates TLS for `${PUBLIC_HOST}` (envsubst template) and serves the SPA with `try_files $uri /index.html`.
      - `/api/` has `proxy_http_version 1.1`, `Connection ""`, `proxy_buffering off`, `proxy_cache off` and `proxy_read_timeout 300s`.
      - HSTS and basic security headers.
    - `.env.prod.example` holds the plain values from `08` §9 and names every SSM-sourced variable with an empty value. No secret, bucket name or email.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && PUBLIC_HOST=1-2-3-4.sslip.io POSTGRES_USER=u POSTGRES_PASSWORD=p docker compose --env-file .env.prod.example -f docker/docker-compose.base.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.observability.yml config --format json | jq -c '[.services[] | .ports[]? | select(.host_ip != "127.0.0.1") | .published] | sort' | grep -x '\["443","80"\]' && docker build -q -f docker/nginx/Dockerfile.prod -t swip-nginx-prod-check . >/dev/null && docker image rm swip-nginx-prod-check >/dev/null`
  - Files: `docker/docker-compose.prod.yml`, `docker/nginx/Dockerfile.prod`, `docker/nginx/prod.conf`, `.env.prod.example`

- [ ] T10: `infra/aws` CloudFormation stack and scripts, plus every new Makefile target (W1)
  - Depends on: nothing
  - Read exactly these: `docs/solution-docs/08-deployment.md` §4, §5, §9, §10 and §11; spec D19, D20 and §"Contracts" → "Deploy artifacts"; `Makefile`
  - Acceptance:
    - `infra/aws/ec2-stack.yaml` has parameters: alert emails (no default), `InstanceType` default `t3.xlarge`, `DataBucketName`, `BedrockModelArns` (CommaDelimitedList, filled in T32). It creates:
      - SG 80/443 only.
      - Role with `AmazonSSMManagedInstanceCore` + S3 read on `data/*` + `bedrock:InvokeModel*` on the parameter ARNs + `ssm:GetParametersByPath` on `/swip/prod/*`.
      - Instance profile.
      - Ubuntu 24.04 instance: IMDSv2 required, hop limit 2, 80 GB gp3, termination protection, user data installing Docker + compose/buildx, git, make and uv, and cloning the public repo.
      - Elastic IP.
      - `AWS::Budgets::Budget` $150 with actual + forecast alerts.
    - `render-env.sh`: `umask 077`, `aws ssm get-parameters-by-path --with-decryption --path /swip/prod/`, merged with `.env.prod.example` into `.env` at 0600. It never echoes values and never uses `set -x`.
    - `deploy.sh`:
      1. `git fetch` and check out `${DEPLOY_REF:-main}`.
      2. `render-env.sh`.
      3. `docker compose -f base -f prod -f observability build` and `up -d --wait`.
      4. `alembic upgrade head` on `latam_app` and `latam_golden`.
      5. `smoke.sh`.
    - `smoke.sh HOST`, over HTTPS:
      - health 200;
      - persona login (`SMOKE_DOC_TYPE`/`SMOKE_DOC`/`SMOKE_PASSWORD` from env);
      - one chat turn streamed until `done`;
      - `/api/v1/test-idp/sessions` → 404;
      - staff login (`SMOKE_STAFF_USER`/`SMOKE_STAFF_PASSWORD`).
    - Makefile: `COMPOSE_PROD`, `infra-up`, `infra-down`, `deploy`, `deploy-remote` (`aws ssm send-command`), `smoke-prod HOST=`, added to `.PHONY`. The existing targets are unchanged.
    - No bucket name, email or account id is committed. No `aws s3 sync` anywhere.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uvx cfn-lint infra/aws/ec2-stack.yaml && bash -n infra/aws/render-env.sh infra/aws/deploy.sh infra/aws/smoke.sh && ! grep -nE 'set -x|s3 sync|echo .*\$\{?(JWT|IDENTITY|CREDENTIALS|POSTGRES_PASSWORD|DEMO_OTP)' infra/aws/*.sh && make -n infra-up deploy smoke-prod HOST=x.sslip.io >/dev/null`
  - Files: `infra/aws/ec2-stack.yaml`, `infra/aws/render-env.sh`, `infra/aws/deploy.sh`, `infra/aws/smoke.sh`, `Makefile`

- [ ] T11: Handoff domain — repository and service (W2)
  - Depends on: T1 (`HandoffPacket`, `HandoffSummary`, `HandoffDetail`, `reference_for`, `TranscriptMessage`), T2 (`app.handoffs`, staff columns), T7 (`publish_handoff`)
  - Read exactly these: spec D11, D12, D14, D17 and §"Contracts" → "Staff API"; `backend/app/domains/audit/repository.py` (error mapping + JSONB bindparam pattern); the state file's T1/T2/T7 entries
  - Acceptance:
    - `repository.py` (SQLAlchemy `text()` over `core.db`, `SQLAlchemyError|OSError → ToolUnavailable`):
      - `insert_handoff(packet, priority)`: in **one transaction**, insert the row (`status='queued'`) and `UPDATE app.conversations SET mode='human'`. If there is already an open handoff for the conversation (partial unique violation), return the existing id and change nothing.
      - `list_handoffs(queues, statuses)`: newest first, with `claimed_by` = `identity.accounts.display_name`.
      - `get_handoff(id)`.
      - `claim(id, agent_id)`: idempotent for the same agent. Another claimant → `AlreadyClaimed`; returned → `HandoffClosed`.
      - `return_handoff(id, agent_id)`: in one transaction, `status='returned'`, `returned_at`, and `app.conversations.mode='bot'`. Not the claimant → `NotClaimant`.
      - `open_claim_for(conversation_id, agent_id) -> bool`.
    - `service.py` wraps these, maps rows to `HandoffSummary`/`HandoffDetail`, and publishes `handoff_created`/`handoff_updated` (`HandoffSummary` JSON) through `events.publish_handoff`.
    - Never imports `app.domains.conversation`.
  - Verify: `cd backend && uv run python -c "import app.domains.handoff.service as s; assert all(hasattr(s,n) for n in ('create','list_handoffs','get_detail','claim','return_handoff','is_claimed_by'))" && uv run ruff check app/domains/handoff && uv run ruff format --check app/domains/handoff && uv run mypy app/domains/handoff && uv run lint-imports` (behavior is proven end to end in T29)
  - Files: `backend/app/domains/handoff/repository.py`, `backend/app/domains/handoff/service.py`

- [ ] T12: Staff identity — lookup, `staff_login`, seeding 4 agents + 1 admin (W2)
  - Depends on: T2 (columns), T5 (`Session` roles, `StaffMeResponse`)
  - Read exactly these: spec D15 and §"Contracts" → "Staff auth" and "Migration 0005" (the `login_key` rule); `backend/app/domains/identity/provision.py`; `backend/app/domains/identity/service.py` lines 100-205 (`login` + limiter)
  - Acceptance:
    - `passwords.staff_login_key(username, *, hmac_key)` = hex HMAC-SHA256 of `staff:<username>`.
    - `AccountRow.customer_id: str | None` plus `username`, `display_name` and `staff_queue` (all optional).
    - `service.staff_login(req: StaffLoginRequest)`:
      - Same limiter shape, keyed `rl:login:<staff_login_key>`, checked first.
      - Same `InvalidCredentials`/`TooManyAttempts`.
      - Requires role `agent|admin` and `status == "active"`.
      - Returns `Session(role=..., customer_id=None)`.
    - `service.staff_me(session) -> StaffMeResponse`.
    - `provision.main()`, after the customer COPY and in the same transaction, inserts one `agent` per `get_args(Queue)` plus one `admin`, with these exact values (human decision):
      - `agent.atencion` → Laura, `agent.cobranza` → Diego, `agent.fraudes` → Sofía, `agent.reclamos` → Mateo. Each has `staff_queue` = its queue.
      - `admin` → "Swip Admin", `staff_queue` null.
      - Usernames are built as `f"agent.{queue}"`. Display names come from a `dict[Queue, str]` in `provision.py`, and a missing queue key fails the run.
      - Password: `generate_password("staff:<username>", seed=CREDENTIALS_SEED)`.
      - It writes `data/secrets/staff_credentials.csv` (`username,role,queue,password`) at mode 0600.
      - No queue literal appears in the code.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && make seed-identity >/dev/null && docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select role, count(*) from identity.accounts where role <> 'customer' group by role order by role" | tr '\n' ' ' | grep -x 'admin|1 agent|4 ' && docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select username||'='||display_name from identity.accounts where role <> 'customer' order by username" | tr '\n' ' ' | grep -x 'admin=Swip Admin agent.atencion=Laura agent.cobranza=Diego agent.fraudes=Sofía agent.reclamos=Mateo ' && test "$(stat -c %a data/secrets/staff_credentials.csv)" = 600 && test "$(wc -l < data/secrets/staff_credentials.csv)" = 6 && git check-ignore -q data/secrets/staff_credentials.csv && cd backend && uv run pytest tests/unit/test_login_pii.py -q && uv run ruff check app/domains/identity && uv run ruff format --check app/domains/identity && uv run mypy app/domains/identity`
  - Files: `backend/app/domains/identity/repository.py`, `backend/app/domains/identity/passwords.py`, `backend/app/domains/identity/service.py`, `backend/app/domains/identity/provision.py`

- [ ] T13: Structured abstain — `abstain` node, `compose` goal `abstain`, `compose@v5` (W2)
  - Depends on: T1 (`QuickRepliesPayload.slot="abstain"`), T4 (`ScopePolicy`, `get_policies().scope`), T6 (`abstain_fallback`)
  - Read exactly these: spec D18 and ADR-026 in `docs/solution-docs/02-conversation-design.md` §5 ("Structured abstain"); `backend/app/domains/conversation/nodes/compose.py`; `backend/app/domains/conversation/prompts/compose@v4.md`
  - Acceptance:
    - `prompts/compose@v5.md` = v4 plus the `abstain` goal. `compose.py` uses `PromptRef("compose", 5)` and `Goal` gains `"abstain"`.
    - New fact keys `topic_label`, `abstain_reason`, `closest_action` and `human_offer`. `_format_fact` returns their already-localized string values unchanged.
    - `nodes/abstain.py` (async node `abstain(state, config)`):
      - Reads `nlu.slots.topic` (default `other`) and `get_policies().scope`.
      - Builds the four facts from fixed ES/PT dicts in this module (topic labels, `reason_key` texts, intent → action labels, human offer).
      - Calls `compose_reply(..., goal="abstain", facts=...)`. If the result is the generic `fallback` template, it uses `abstain_fallback` filled from the same four values.
      - Emits `QuickRepliesEvent(slot="abstain", options=[closest action label (if any), human offer label])`.
      - Returns `segments` + `ui` and **never touches `pending`**.
      - Reads no `bank_tools`, `bank_write_tools` or `handoff_tools`.
  - Verify: `cd backend && uv run pytest tests/unit/test_compose.py -q && uv run python -c "import app.domains.conversation.nodes.abstain as a; assert callable(a.abstain)" && uv run ruff check app/domains/conversation/nodes/abstain.py app/domains/conversation/nodes/compose.py && uv run ruff format --check app/domains/conversation/nodes/abstain.py app/domains/conversation/nodes/compose.py && uv run mypy app/domains/conversation/nodes/abstain.py app/domains/conversation/nodes/compose.py`
  - Files: `backend/app/domains/conversation/nodes/abstain.py`, `backend/app/domains/conversation/nodes/compose.py`, `backend/app/domains/conversation/prompts/compose@v5.md`

- [ ] T14: `handoff_summary` LLM node, its prompt and the `core/llm` step (W2)
  - Depends on: T1 (`HandoffReason`), T3 (`resolve_escalation`, `load_escalation_policy`)
  - Read exactly these: spec D9, D10 and §"Contracts" → "`core/llm`"; `backend/app/core/llm/registry.py`; `backend/app/domains/conversation/nodes/compose.py` lines 60-110 (draft validation to mirror)
  - Acceptance:
    - `Step` gains `"handoff_summary"`, with the same model IDs as `compose` and temperature 0.
    - `prompts/handoff_summary@v1.md` asks for a ≤200-character agent-facing request that uses only the `{card_mask}`, `{tx_count}` and `{queue_label}` placeholders.
    - `nodes/handoff_summary.py`: `HandoffSummaryDraft{request: str}` (`extra="forbid"`) and an async node `handoff_summary(state, config)`:
      - Resolves `(reason, queue)` with `resolve_escalation` from state (`escalation_reason`, `handoff_queue`, `pending.flow`, `nlu.intents`, `user_text`).
      - The user message holds **only** reason, queue, intents, the `actions` tool names and verified flags, and the available placeholder keys. Never `user_text` or facts' values.
      - A draft with an unknown placeholder, a brace residue or a raw digit outside a placeholder, or an `LLMError`, uses a fixed ES/PT per-reason text from a dict in this module.
      - Fills placeholders in code (`card_mask` via `mask_card` on the selected card's last4, read by `bank_tools.get_card_details`, or the placeholder is not offered; `tx_count` = `len(handoff_evidence)`; `queue_label` via `queue_label`) and truncates to 200.
      - Writes graph-local `handoff_request`.
    - The module imports `app.core.llm` and references no `handoff_tools`, `HandoffTools` or write tool.
  - Verify: `cd backend && uv run pytest tests/unit/test_r6_no_write_tools_in_llm_nodes.py tests/unit/test_llm_client.py -q && uv run python -c "import app.domains.conversation.nodes.handoff_summary as h; assert callable(h.handoff_summary)" && uv run ruff check app/core/llm app/domains/conversation/nodes/handoff_summary.py && uv run ruff format --check app/core/llm app/domains/conversation/nodes/handoff_summary.py && uv run mypy app/core/llm app/domains/conversation/nodes/handoff_summary.py && uv run lint-imports`
  - Files: `backend/app/core/llm/registry.py`, `backend/app/domains/conversation/nodes/handoff_summary.py`, `backend/app/domains/conversation/prompts/handoff_summary@v1.md`

- [ ] T15: `handoff` code node — packet in code, `handoff_tools.create`, `mode = human` (W2)
  - Depends on: T1 (`HandoffPacket`, `HandoffTools`, `HandoffBannerEvent`, `reference_for`, `TurnState` delta, audit `handoff` type), T3 (`resolve_escalation`, `rule`), T6 (`handoff_transfer`)
  - Read exactly these: spec D9, D10, D12 and §"Contracts" → "`HandoffPacket`"; `docs/solution-docs/04-contracts.md` §4; `backend/app/core/actions.py` (`ActionResult`)
  - Acceptance:
    - Async node `handoff(state, config)` in `nodes/handoff.py` that **does not import `app.core.llm`**.
    - Resolves `(reason, queue, priority)` with `resolve_escalation`, then:
      - `handoff_id = uuid4()`.
      - `verified_facts` and `actions_taken` only from `state["actions"]` with `verified=True`. Tool → fact mapping: lock → `card_locked`, unlock → `card_unlocked`, block → `card_status`, order_replacement → `replacement_ordered`, `disputes.*` → `claim_filed`. Source is `audit:<id>` or `"<tool> read-back"`.
      - `evidence` from `handoff_evidence`.
      - `open_questions` rendered from `rule(...).open_questions` keys via a fixed ES/PT dict here.
      - `escalation_rules_hit=[reason]`, `policy_version` from the session `ToolContext`, `sentiment=None`, `request=state["handoff_request"]`.
    - Awaits `config["configurable"]["handoff_tools"].create(packet)` and records `audit.record("handoff", {action: "created", handoff_id, queue, reason})`.
    - Returns:
      - `mode="human"`, `handoff_id`, `handoff_queue=queue`, `escalation_reason=reason`;
      - `pending=None`, `confirmation_token_id=None`, `intent_queue=[]`, `handoff_evidence=[]`;
      - `ui=[HandoffBannerEvent]` (reference + localized `queue_label`);
      - `segments=[handoff_transfer filled]`.
  - Verify: `cd backend && uv run python -c "import app.domains.conversation.nodes.handoff as h; import inspect; src=inspect.getsource(h); assert 'app.core.llm' not in src and callable(h.handoff)" && uv run ruff check app/domains/conversation/nodes/handoff.py && uv run ruff format --check app/domains/conversation/nodes/handoff.py && uv run mypy app/domains/conversation/nodes/handoff.py && uv run lint-imports`
  - Files: `backend/app/domains/conversation/nodes/handoff.py`

- [ ] T16: `unsupported` counts unauthorized attempts and escalates at the threshold (W2)
  - Depends on: T1 (`unauthorized_attempts`, audit literals), T3 (`unauthorized_access.attempts_before_handoff`)
  - Read exactly these: spec D6; `backend/app/domains/conversation/nodes/unsupported.py`; `backend/app/domains/audit/schemas.py` (`Recorder`, `NullAuditRecorder`)
  - Acceptance:
    - `unsupported` becomes `async (state, config)`. On `nlu.status == "injection_suspected"`:
      - `attempt = state.get("unauthorized_attempts", 0) + 1`.
      - Records `access_denied {source: "nlu", attempt}` through `configurable.get("audit") or NullAuditRecorder()`.
      - Below the threshold, it returns the `injection_suspected` segment + `unauthorized_attempts`.
      - At or above the threshold, it returns `unauthorized_attempts`, `escalation_reason="unauthorized_access"` and **no segment** (the handoff nodes reply).
    - The other statuses are unchanged (`out_of_market`/`out_of_scope` template branches stay until T31).
  - Verify: `cd backend && uv run pytest tests/unit/test_conversation_basics.py -q && uv run ruff check app/domains/conversation/nodes/unsupported.py && uv run ruff format --check app/domains/conversation/nodes/unsupported.py && uv run mypy app/domains/conversation/nodes/unsupported.py`
  - Files: `backend/app/domains/conversation/nodes/unsupported.py`

- [ ] T17: Takeover helpers — return to bot, agent message relay, mode events (W2)
  - Depends on: T1 (`ModePayload`, `MessagePayload`, `TurnState` fields), T6 (`back_with_cardy`)
  - Read exactly these: spec D13, D14, D16 and §"Contracts" → "SSE deltas"; `backend/app/domains/conversation/runner.py` lines 60-125 (lock key, TTL, release script); `backend/app/domains/conversation/hosting.py`
  - Acceptance:
    - New `conversation/takeover.py`.
    - `publish_mode(conversation_id, mode, agent_display_name)` publishes `mode` on `conv:<id>`.
    - `relay_agent_message(conversation_id, text, agent_display_name) -> UUID`:
      - Persists `role="agent"` with a fresh `turn_id`.
      - Publishes `message{role:"agent", text, sources:[], agent_display_name}`.
    - `return_to_bot(host, conversation_id, language) -> None`:
      - Takes `turn:<id>` with `SET NX EX 120`, else raises `TurnBusy`.
      - `host.graph.aupdate_state(...)` sets `mode="bot"` and clears `pending`, `intent_queue`, `confirmation_token_id`, `escalation_reason`, `handoff_queue`, `clarification_failures` and `unauthorized_attempts`.
      - Persists and publishes the `back_with_cardy` `system` message, then publishes `mode{bot, null}`.
      - Releases the lock with a compare-and-delete.
    - It does **not** touch `app.handoffs` or `app.conversations.mode`; the T24 route calls `handoff.service.return_handoff` for that. No bank tools.
  - Verify: `cd backend && uv run python -c "import app.domains.conversation.takeover as t; assert all(hasattr(t,n) for n in ('return_to_bot','relay_agent_message','publish_mode','TurnBusy'))" && uv run ruff check app/domains/conversation/takeover.py && uv run ruff format --check app/domains/conversation/takeover.py && uv run mypy app/domains/conversation/takeover.py && uv run lint-imports`
  - Files: `backend/app/domains/conversation/takeover.py`

- [ ] T18: Test harness and sandbox get `handoff_tools` and `audit` config keys (W2)
  - Depends on: T1 (`InMemoryHandoffTools`)
  - Read exactly these: `backend/tests/conftest.py`; `backend/app/domains/conversation/sandbox.py` lines 160-222; the plan's §"Plan-level conventions" bullet on config keys
  - Acceptance:
    - `make_session` adds `handoff_tools: InMemoryHandoffTools` and `audit` to the config and to the `Session` dataclass (`handoff_tools`, `audit`).
    - `audit` is a new in-file `RecordingAudit` fake that implements `Recorder` and keeps `events: list[tuple[type, payload]]`. Export it in `__all__`.
    - `sandbox._build_session` adds `InMemoryHandoffTools()` and `NullAuditRecorder()`.
    - No other test file changes.
  - Verify: `cd backend && uv run pytest tests/unit/test_block_flows.py tests/unit/test_sandbox_conversations.py tests/unit/test_fakebank_writes.py -q && uv run ruff check tests/conftest.py app/domains/conversation/sandbox.py && uv run ruff format --check tests/conftest.py app/domains/conversation/sandbox.py && uv run mypy app/domains/conversation/sandbox.py`
  - Files: `backend/tests/conftest.py`, `backend/app/domains/conversation/sandbox.py`

- [ ] T19: Staff and admin router skeletons with role guards, registered once (W2)
  - Depends on: T5 (roles `agent|admin`)
  - Read exactly these: spec D16 and §"Contracts" → "Staff auth" and "Staff API"; `backend/app/api/v1/__init__.py`; `backend/app/api/v1/auth.py` lines 60-70 (router declaration pattern)
  - Acceptance:
    - `api/v1/staff_auth.py`: `public_router` (no routes yet) and `router = APIRouter(dependencies=[Depends(require_role("agent","admin")), Depends(require_csrf)])`.
    - `api/v1/staff.py`: `router = APIRouter(prefix="/staff", dependencies=[require_role("agent","admin"), require_csrf])`.
    - `api/v1/admin.py`: `router = APIRouter(prefix="/admin", dependencies=[require_role("admin"), require_csrf])`.
    - Each has a module docstring naming the routes that T23/T24/T25 will add.
    - `v1_router` includes all four routers.
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py tests/unit/test_r1_routes.py tests/unit/test_health.py -q && uv run ruff check app/api && uv run ruff format --check app/api && uv run mypy app/api && uv run lint-imports`
  - Files: `backend/app/api/v1/staff_auth.py`, `backend/app/api/v1/staff.py`, `backend/app/api/v1/admin.py`, `backend/app/api/v1/__init__.py`

- [ ] T20: `make chat-api` prints mode, handoff banner and relayed messages (W2)
  - Depends on: T1 (event payload shapes)
  - Read exactly these: spec §"Contracts" → "SSE deltas"; `backend/scripts/chat_api.py` lines 134-215
  - Acceptance:
    - `_handle_event` prints `mode: <mode> (<agent>)`.
    - `ui handoff_banner <reference> <queue_label>`.
    - `agent: <text>` / `system: <text>` for `message` with those roles, and ignores `role == "customer"` echoes.
    - `ui quick_replies abstain: <labels>`.
    - The existing lines are unchanged.
  - Verify: `cd backend && uv run python scripts/chat_api.py --help >/dev/null && uv run ruff check scripts/chat_api.py && uv run ruff format --check scripts/chat_api.py`
  - Files: `backend/scripts/chat_api.py`

- [ ] T21: Graph switchover — `_entry` human mode, `route` escalation/abstain, handoff nodes, AccessDenied guard, real flow handoffs (W3)
  - Depends on: T3 (`resolve_escalation`, `legal_hit`), T13 (`abstain`), T14 (`handoff_summary`), T15 (`handoff`), T16 (`unsupported` escalates at the threshold)
  - Read exactly these: `backend/app/domains/conversation/graph.py`; `backend/app/domains/conversation/nodes/route.py`; spec D4, D6, D7 and D13
  - Acceptance:
    - `nodes/relay.py`: `relay_to_agent(state) -> {}`, code only. Export it with `abstain`, `handoff_summary` and `handoff` from `nodes/__init__.py`. Add `handoff_request: NotRequired[str]` to `GraphState`.
    - `_entry`: `state.get("mode") == "human"` → `relay_to_agent` **before** any other check. `relay_to_agent` → `finish`.
    - `route`, after the `nlu is None` check:
      1. `resolve_escalation(...)` with no state reason, or `injection_suspected` → `unsupported` (which counts).
      2. A legal hit or a `human_request` intent → `handoff_summary`.
      3. `out_of_market|out_of_scope` → `abstain`.
      4. The rest unchanged.
    - `_after_flow`: an `escalation_reason` in `HandoffReason` (incl. `clarification_exhausted`) or a set `handoff_queue` → `handoff_summary`. `tool_unavailable`/`no_cards` → `fallback`.
    - An edge after `unsupported`: `escalation_reason == "unauthorized_access"` → `handoff_summary`, else `_after_segment`. `abstain` → `_after_segment`. `handoff_summary` → `handoff` → `finish`.
    - Every flow node is added through a wrapper (`functools.wraps`, keeping the `config` parameter) that catches `AccessDenied`. It then:
      - increments `unauthorized_attempts`;
      - records `access_denied{source:"tool", attempt}`;
      - returns the `injection_suspected` segment, or `escalation_reason="unauthorized_access"` at the threshold (→ `handoff_summary`).
    - `flows/actions.handoff(queue: Queue, reason: HandoffReason, language)` returns `{escalation_reason, handoff_queue, pending: None, confirmation_token_id: None}` with no segment. Callers are unchanged.
    - `_BRANCH_NODES` includes `abstain`, `handoff_summary` and `relay_to_agent`.
    - Regenerate the diagram with `make graph-diagram`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && make graph-diagram && cd backend && uv run pytest tests/unit/test_graph.py tests/unit/test_card_info_flows.py tests/unit/test_conversation_basics.py -q && uv run ruff check app/domains/conversation && uv run ruff format --check app/domains/conversation && uv run mypy app/domains/conversation && uv run lint-imports` (`test_r3_flows`, `test_block_flows` and `test_sandbox_conversations` are expected red until W4, and are not run here)
  - Files: `backend/app/domains/conversation/graph.py`, `backend/app/domains/conversation/nodes/route.py`, `backend/app/domains/conversation/nodes/relay.py`, `backend/app/domains/conversation/nodes/__init__.py`, `backend/app/domains/conversation/flows/actions.py`, `docs/diagrams/turn-graph-v0.mmd`

- [ ] T22: Runner — human-mode relay, handoff events, `ServiceHandoffTools` and the import-linter edge (W3)
  - Depends on: T1 (payloads, `HandoffTools`), T11 (`handoff.service.create`)
  - Read exactly these: `backend/app/domains/conversation/runner.py`; spec D12, D13 and §"Contracts" → "SSE deltas"; `backend/.importlinter`
  - Acceptance:
    - `tools/handoff.py` gains `ServiceHandoffTools(ctx: ToolContext)`. `create(packet)` checks `packet.conversation_id == ctx.conversation_id`, then calls `handoff.service.create(packet, priority)`.
    - `.importlinter` gains exactly one ignore line: `app.domains.conversation.tools.handoff -> app.domains.handoff.service`.
    - `_run_turn` adds `"handoff_tools": ServiceHandoffTools(ctx)` and `"audit": audit` to the config.
    - When the `relay_to_agent` node appears, the runner publishes `message{role:"customer", text}` (typed text) and then `done`. It skips the `ui`/bot `message`/`reply_sent`/`debug` steps and persists nothing more (the customer message was already persisted by `start_turn`).
    - When the `handoff` node's update carries `handoff_id`, it publishes `mode{human, null}` after the `ui` events (which include the banner).
    - `_BRANCH_NODES` mirror updated.
  - Verify: `cd backend && uv run ruff check app/domains/conversation/runner.py app/domains/conversation/tools/handoff.py && uv run ruff format --check app/domains/conversation/runner.py app/domains/conversation/tools/handoff.py && uv run mypy app/domains/conversation && uv run lint-imports` (behavior proven in T29)
  - Files: `backend/app/domains/conversation/runner.py`, `backend/app/domains/conversation/tools/handoff.py`, `backend/.importlinter`

- [ ] T23: Staff auth routes — `POST /auth/staff/login`, `GET /staff/me`, `POST /staff/logout` (W3)
  - Depends on: T12 (`staff_login`, `staff_me`), T19 (routers in `staff_auth.py`)
  - Read exactly these: spec §"Contracts" → "Staff auth"; `backend/app/api/v1/auth.py`; `backend/app/api/v1/staff_auth.py`
  - Acceptance:
    - `public_router.post("/auth/staff/login", response_model=StaffMeResponse)`: `429 too_many_attempts` before `401 invalid_credentials`. Issues the token + CSRF with `auth._set_auth_cookies`.
    - `router.get("/staff/me")` and `router.post("/staff/logout", 204)` (revokes the `jti`, clears the cookies).
    - No route takes `customer_id`.
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/staff_auth.py && uv run ruff format --check app/api/v1/staff_auth.py && uv run mypy app/api/v1/staff_auth.py`
  - Files: `backend/app/api/v1/staff_auth.py`

- [ ] T24: Staff handoff and conversation API, `get_claimed_conversation`, R13 extension (W3)
  - Depends on: T7 (`subscribe_handoffs`), T11 (handoff service), T17 (`relay_agent_message`, `return_to_bot`, `publish_mode`, `TurnBusy`), T19 (`staff.router`)
  - Read exactly these: spec D14, D16, D17 and §"Contracts" → "Staff API"; `backend/app/api/v1/conversations.py` lines 70-90 and 228-269 (ownership dependency + SSE); `backend/tests/unit/test_r13_routes.py`
  - Acceptance:
    - All nine staff rows of the spec's table exist on `staff.router`, with their bodies, status codes and errors:
      - `GET /handoffs` (`status` default `queued,claimed`).
      - `GET /handoffs/stream`: subscribe before returning, reusing `conversations._sse_stream`.
      - `GET /handoffs/{id}`.
      - `POST /handoffs/{id}/claim`: `publish_mode(human, display_name)`, plus audit `handoff{claimed}` with actor `agent:<account_id>`.
      - `POST /handoffs/{id}/return`: `return_handoff`, then `return_to_bot`; `TurnBusy` → `409 turn_in_progress`; audit `handoff{returned}`.
      - `GET|POST /conversations/{id}/messages`: POST calls `relay_agent_message` and returns `201 {message_id}`.
      - `GET /conversations/{id}/stream`.
    - `get_claimed_conversation(conversation_id, session)` → `404 not_found` unless an open handoff is claimed by `session.account_id`. Every `/staff/conversations/{id}/…` route depends on it.
    - `test_r13_routes.py`:
      - Exempts `/api/v1/auth/staff/login`.
      - Asserts that `/staff/*` routes carry a `RoleGuard` whose `roles == ("agent","admin")` and `/admin/*` routes `("admin",)`.
      - Asserts that every `/api/v1/staff/conversations/{conversation_id}` route calls `get_claimed_conversation`.
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/staff.py tests/unit/test_r13_routes.py && uv run ruff format --check app/api/v1/staff.py tests/unit/test_r13_routes.py && uv run mypy app/api/v1/staff.py && uv run lint-imports`
  - Files: `backend/app/api/v1/staff.py`, `backend/tests/unit/test_r13_routes.py`

- [ ] T25: `POST /admin/demo/reset` (W3)
  - Depends on: T8 (`reset_app_database`), T19 (`admin.router`)
  - Read exactly these: spec D21; `backend/app/api/v1/admin.py`; `backend/app/domains/conversation/hosting.py`
  - Acceptance:
    - The route runs `close_host(app.state.turn_host)`, then `await reset_app_database()`, then `app.state.turn_host = await open_host(settings.database_url, <previous host's llm>)`.
    - It returns `200 {status: "reset", duration_ms}`.
    - The host is reopened in `finally` even if the reset fails, and the failure re-raises as a 500.
  - Verify: `cd backend && uv run pytest tests/unit/test_r13_routes.py -q && uv run ruff check app/api/v1/admin.py && uv run ruff format --check app/api/v1/admin.py && uv run mypy app/api/v1/admin.py && uv run lint-imports` (the live call is in T31)
  - Files: `backend/app/api/v1/admin.py`

- [ ] T26: Escalation rule tests (7 rules × ES/PT, unauthorized) and the flow tests the switchover changed (W4)
  - Depends on: T18 (`make_session` with `handoff_tools`/`audit`), T21 (graph)
  - Read exactly these: spec §"Test list" rows `test_escalation_rules.py`; `backend/tests/conftest.py`; `backend/tests/unit/test_r3_flows.py`
  - Acceptance:
    - `test_rule_hands_off` is parametrized over 7 rules × `es|pt`. Each case:
      - drives `make_session` graphs with `ScriptedLLM` (NLU outputs plus one `handoff_summary` draft);
      - uses the fixture customers (`TFINACT00004` not active, `TFBLOCKD0003` bank-side, an unverified `raw_writes` stub for `action_unverified`, two unresolvable card hints for `clarification_exhausted`, a legal keyword text, a `human_request` intent, two `injection_suspected` turns);
      - asserts `handoff_tools.created[-1].queue/reason` equal the YAML's, the final state `mode == "human"`, and that the reply contains the `handoff_transfer` text for that language.
    - `test_unauthorized_second_attempt_hands_off`:
      - Attempt 1: reply = `injection_suspected` template and an `access_denied` event in `audit.events`.
      - Attempt 2: another `access_denied` + a handoff to `atencion` with reason `unauthorized_access`.
    - `test_r3_flows.py` and `test_block_flows.py` are updated to script a `handoff_summary` output and assert the new handoff (queue name still present in the reply).
  - Verify: `cd backend && uv run pytest tests/unit/test_escalation_rules.py tests/unit/test_r3_flows.py tests/unit/test_block_flows.py -q && uv run ruff check tests/unit && uv run ruff format --check tests/unit/test_escalation_rules.py tests/unit/test_r3_flows.py tests/unit/test_block_flows.py`
  - Files: `backend/tests/unit/test_escalation_rules.py`, `backend/tests/unit/test_r3_flows.py`, `backend/tests/unit/test_block_flows.py`

- [ ] T27: Abstain tests and the old Pix test (W4)
  - Depends on: T13, T21, T4 (the scope content is in the state file)
  - Read exactly these: spec §"Test list" row `test_abstain.py`; `backend/tests/unit/test_sandbox_conversations.py` lines 1-130
  - Acceptance:
    - `test_abstains_without_tools[es-pix|pt-loans]`:
      - `ScriptedLLM` gives NLU `out_of_market`/`topic=pix_boleto` (ES) and `out_of_scope`/`topic=loans` (PT), plus a `compose` draft using the four keys.
      - The test starts with a pending clarification (`pending` set by a prior turn), so it can assert `pending` is kept.
      - It asserts: `bank_tools.calls`, the write tools and `handoff_tools.created` are all empty; the compose call's user message offers exactly the four keys; `ui` has one `quick_replies` with `slot == "abstain"`.
    - `test_pix_routes_out_of_market` is rewritten to expect route `abstain`.
  - Verify: `cd backend && uv run pytest tests/unit/test_abstain.py tests/unit/test_sandbox_conversations.py -q && uv run ruff check tests/unit/test_abstain.py tests/unit/test_sandbox_conversations.py && uv run ruff format --check tests/unit/test_abstain.py tests/unit/test_sandbox_conversations.py`
  - Files: `backend/tests/unit/test_abstain.py`, `backend/tests/unit/test_sandbox_conversations.py`

- [ ] T28: Packet, summary fallback, human-mode and R6 tests (W4)
  - Depends on: T14, T15, T18, T21
  - Read exactly these: spec §"Test list" rows `test_handoff_packet.py`, `test_graph.py::test_human_mode_relays_without_llm` and `test_r6_…`; `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`; `backend/tests/unit/test_graph.py`
  - Acceptance:
    - `test_packet_from_readbacks_only`:
      - The state has one verified and one unverified `ActionResult`, and the customer typed a distinctive string.
      - After the handoff, the packet has every `04` §4 field, only the verified action in `verified_facts`/`actions_taken`, and the typed string is not a substring of `packet.model_dump_json()`.
      - `sentiment is None`, `len(request) <= 200`, and no `{` remains.
    - `test_summary_fallback`: a draft with a raw digit, and a separate `LLMUnavailable`, each give the fixed per-reason text.
    - `test_human_mode_relays_without_llm`: after a handoff, the next turn makes 0 new `ScriptedLLM` calls, the reply is empty and the route is `relay_to_agent`.
    - R6: `_FORBIDDEN_NAMES` adds `handoff_tools` and `HandoffTools`, `_FORBIDDEN_MODULES` adds `app.domains.conversation.tools.handoff`, and the test asserts `nodes/handoff_summary.py` is among the scanned LLM modules, with a non-vacuity snippet for the new names.
  - Verify: `cd backend && uv run pytest tests/unit/test_handoff_packet.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q && uv run ruff check tests/unit/test_handoff_packet.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py && uv run ruff format --check tests/unit/test_handoff_packet.py tests/unit/test_graph.py tests/unit/test_r6_no_write_tools_in_llm_nodes.py`
  - Files: `backend/tests/unit/test_handoff_packet.py`, `backend/tests/unit/test_graph.py`, `backend/tests/unit/test_r6_no_write_tools_in_llm_nodes.py`

- [ ] T29: Staff round-trip integration tests (ES, PT, access boundaries) and the bank-blocked test (W4)
  - Depends on: T11, T12, T21–T25 (the whole backend path)
  - Read exactly these: spec §"Test list" rows `integration/test_staff_round_trip.py`; `backend/tests/integration/conftest.py`; `backend/tests/integration/test_write_path_api.py` lines 1-130 and 381-421
  - Acceptance:
    - The conftest gains an `it_staff` fixture that inserts two agents (for example `atencion` and `fraudes`) with `staff_login_key` and known passwords, and deletes them on teardown.
    - `test_handoff_claim_chat_return` (ES) walks the spec's chain in order, reading both SSE streams with a bounded reader:
      1. "Quiero hablar con una persona".
      2. An `app.handoffs` row appears, and `handoff_created` arrives on `/staff/handoffs/stream`.
      3. Claim, then `mode{human, name}` on the customer stream.
      4. An agent message reaches the customer stream.
      5. A customer message reaches the agent stream with no bot `message`.
      6. Return, then the `system` message + `mode{bot}`.
      7. The next customer message gets a bot reply.
    - `test_pt_handoff_happy_path`: "Quero falar com uma pessoa" → handoff to `atencion` with the PT transfer text.
    - `test_staff_access_boundaries`:
      - customer → `/api/v1/staff/handoffs` 403;
      - agent → `/api/v1/conversations` 403;
      - agent B on agent A's claimed conversation → 404 on messages and stream;
      - wrong staff password → 401.
    - `test_bank_blocked_unlock_handoff` scripts a `handoff_summary` output and asserts the handoff row.
  - Verify: `cd backend && uv run pytest tests/integration/test_staff_round_trip.py tests/integration/test_write_path_api.py -q 2>&1 | tail -1 | grep -E '^[0-9]+ passed(, [0-9]+ warnings?)? in' && uv run ruff check tests/integration && uv run ruff format --check tests/integration` (needs `make up`)
  - Files: `backend/tests/integration/conftest.py`, `backend/tests/integration/test_staff_round_trip.py`, `backend/tests/integration/test_write_path_api.py`

- [ ] T30: Design doc updates (D25, in this PR) (W4)
  - Depends on: T21–T25 (the real names), plus the state file log
  - Read exactly these: spec D25, D13, D14, D16 and §"Contracts"; `docs/solution-docs/04-contracts.md` §3–§5; `docs/solution-docs/02-conversation-design.md` §3, §5 and §6
  - Acceptance:
    - `04` §3:
      - Staff routes, streams and SSE deltas; the stream row becomes customer-only, with the staff stream added.
      - `ui` kinds gain `quick_replies`; the `mode` and `message` roles.
      - The staff-shapes sentence pointing to the spec is replaced by the shapes.
    - `04` §4: `sentiment: null`, the reason list, `reference`.
    - `04` §5: `escalation.yaml` v2 and `scope.yaml`.
    - `02` §3: the mode check in `_entry`, the handoff nodes, abstain. `02` §5: the unauthorized-access rule per D6. `02` §6 step 5 per D14.
    - `03` §6: the `app.handoffs` columns, the `identity.accounts` staff columns, the `handoff:<queue>` channel.
    - `06` §3: `infra/` in the layout.
    - Prose follows the existing style, and no content is duplicated from the spec beyond the contract.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && grep -q 'staff/conversations/{id}/stream' docs/solution-docs/04-contracts.md && grep -q 'scope.yaml' docs/solution-docs/04-contracts.md && grep -q 'app.handoffs' docs/solution-docs/03-data-architecture.md && grep -q 'infra/' docs/solution-docs/06-engineering-rules.md && grep -q 'relay_to_agent' docs/solution-docs/02-conversation-design.md`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`, `docs/solution-docs/03-data-architecture.md`, `docs/solution-docs/06-engineering-rules.md`

- [ ] T31: Cleanup, local end-to-end proof, `make client`, `make check` (W5, runs alone)
  - Depends on: every W1–W4 task
  - Read exactly these: spec §"Success criteria" 1–5 and 8; `backend/app/domains/conversation/nodes/unsupported.py`; `backend/app/domains/conversation/templates.py` lines 1-80
  - Acceptance:
    - `handoff_placeholder`, `out_of_market` and `out_of_scope` are deleted from `templates.py`, along with the matching branches in `unsupported.py`. Nothing references them.
    - On a fresh `make up` + `make seed-identity`:
      - `make chat-api PERSONA=<any>` with "¿Puedo pagar con Pix?" prints a four-part abstain and `tools_called=[]`.
      - After "quiero hablar con una persona", `SELECT status, queue, reason, packet->>'sentiment' FROM app.handoffs` shows `queued|atencion|human_request|` and `app.conversations.mode = 'human'`.
      - `POST /api/v1/admin/demo/reset` as the seeded admin returns 200, and `app.handoffs` is empty afterwards.
    - Success criterion 1's grep shows queue names only in the `Queue` literal, labels and tests.
    - `make client` regenerates `frontend/src/client`.
    - `make check` and `make test-integration` are green.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && ! grep -rn 'handoff_placeholder\|"out_of_market"\|"out_of_scope"' backend/app/domains/conversation/templates.py && grep -rn "atencion\|reclamos\|fraudes\|cobranza" backend/app --include=*.py && make client && make check && make test-integration`. Review the grep output by hand against success criterion 1, and record the live `chat-api`, SQL and curl outputs in the task log.
  - Files: `backend/app/domains/conversation/templates.py`, `backend/app/domains/conversation/nodes/unsupported.py`, `frontend/src/client/*` (generated)

- [ ] T32: AWS deploy runbook and checklist for the human (W6, runs alone; no AWS command is run by the agent)
  - Depends on: T31 (green branch), T9 and T10 (the artifacts the runbook calls)
  - Read exactly these: `docs/solution-docs/08-deployment.md` §5, §8, §10 and §13; spec D19–D22 and success criteria 6–8; `infra/aws/ec2-stack.yaml` and `Makefile` (the `infra-*`, `deploy*` and `smoke-prod` targets)
  - Acceptance: the agent appends a **runbook + checklist** to its T32 entry in the state file (`docs/plans/d4-a-escalation-handoff-deploy.state.md`), and writes no committed file. The agent **never runs** `aws`, `make infra-up/infra-down/deploy/deploy-remote/smoke-prod`, SSM sessions or certbot. The runbook is ordered, copy-pasteable, with `<PLACEHOLDER>` for every value the human supplies (profile, bucket, alert emails, EIP, host). It contains no secret, bucket name or email.
    1. Data copy (`08` §5): download from the organizers into a clean staging folder outside the repo, then upload to our bucket. Verify the count (7,671) and the key + size listing, comparing sizes, not ETags. Include the "never sync the repo's `data/`" warning.
    2. SSM parameters under `/swip/prod/` (the `08` §9 list, `put-parameter --type SecureString`). `CREDENTIALS_SEED` must equal the one behind the judges' credentials.
    3. `aws cloudformation validate-template`, then `make infra-up`. `BedrockModelArns` holds the us-east-1 inference-profile ARN plus the foundation-model ARNs in every region the profile routes to, for the model id in `core/llm/registry.py`. The runbook includes the exact `aws bedrock get-inference-profile` command that lists them.
    4. On the box through SSM: render `.env`, start only `postgres` + `redis`, run `make data`.
    5. Staging certificate, then the production certificate. Route 53 fallback steps per `08` §8.
    6. `make deploy`, then `make smoke-prod HOST=<ip>.sslip.io`.
    7. Checks: `curl -sI https://<host>/` shows HSTS and a production Let's Encrypt issuer; `nc -z <eip> 22`, `5432` and `3000` all fail; the backend logs contain `llm.call provider=bedrock` with the registry's `us.` id; `POST /admin/demo/reset` as admin returns 200 and the customer's changes are gone; D4 end-of-day steps 2 and 4 pass on the public URL with Dev B's screens; demo-reset duration and first-deploy recovery time are measured (`08` §10, §13).
    - The checklist has one checkbox per success criterion 6–8 item, each naming the exact output the human pastes back.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && uvx cfn-lint infra/aws/ec2-stack.yaml && bash -n infra/aws/render-env.sh infra/aws/deploy.sh infra/aws/smoke.sh && make -n infra-up deploy deploy-remote smoke-prod HOST=x.sslip.io >/dev/null && grep -q 'T32' docs/plans/d4-a-escalation-handoff-deploy.state.md && ! grep -nE '(AKIA|arn:aws:iam::[0-9]{12}|@[a-z0-9-]+\.[a-z]{2,})' docs/plans/d4-a-escalation-handoff-deploy.state.md` (every command the runbook names exists and parses locally; the runbook itself carries no account id, key or email)
  - Files: `docs/plans/d4-a-escalation-handoff-deploy.state.md` (T32 log entry only)

- [ ] T33: Record the human's deploy results and apply the Bedrock confirmation (W6, after the human has run T32's runbook)
  - Depends on: T32 (runbook). The human's pasted outputs for every checklist item are in the orchestrator's dispatch message or in the state file.
  - Read exactly these: the T32 entry in `docs/plans/d4-a-escalation-handoff-deploy.state.md`; spec D22 and success criteria 6–8; `backend/app/core/llm/registry.py`
  - Acceptance:
    - Every checklist item is marked pass or fail in the T33 log entry, with the human's pasted evidence (redacted of IPs only if the human asks). The agent runs no AWS command.
    - If the logs show `llm.call provider=bedrock` with the registry's `us.` id, the `# unconfirmed until K2` comments are removed from `core/llm/registry.py`. If they don't, the comments stay, and the task reports the failure to the orchestrator instead of guessing a fix.
    - If the human's run forced a change to `infra/aws/ec2-stack.yaml` (for example an ARN list), that change is applied exactly as reported.
    - Any failed item is listed as an open item for the verifier. The D5-morning cut line applies.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada && ! grep -n 'unconfirmed until K2' backend/app/core/llm/registry.py && uvx cfn-lint infra/aws/ec2-stack.yaml && cd backend && uv run ruff check app/core/llm && uv run ruff format --check app/core/llm && uv run mypy app/core/llm`
  - Files: `backend/app/core/llm/registry.py`, `infra/aws/ec2-stack.yaml` (only if the human's run forced a fix), `docs/plans/d4-a-escalation-handoff-deploy.state.md` (T33 log entry)

## Human decisions

The planner's three questions were answered on 2026-09-28. The values are pinned in "Facts checked against the repo" → "Human decisions" and in T4, T12, T32 and T33.
1. Staff accounts: option (a), with exact names per username.
2. `scope.yaml`: option (a).
3. Live deploy: option (a). The human runs every AWS command, T32 writes the runbook and checklist, and T33 records the results.
