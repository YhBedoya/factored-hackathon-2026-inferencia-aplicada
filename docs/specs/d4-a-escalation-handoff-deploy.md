# Spec: D4-A — G10 escalation and handoff backend, G12a AWS deploy

Card: `07-execution-plan.md` D4, Dev A track, rows A1–A5. Owner: Dev A. Branch `feat/d4-a-escalation-handoff-deploy` → `develop`. The PR touches identity, escalation and policy, so it is safety-critical and Dev B reviews it before merge (ADR-018).

## Objective

This card gives Cardy real escalation and a live human handoff, and puts the app on a public HTTPS URL. It delivers:
- **A1** Deterministic escalation rules in `policies/escalation.yaml`, checked in `route` and after every flow result. Every rule ends in a real handoff with a queue and a reason.
- **A2** Structured abstain for out-of-market and out-of-scope requests (ADR-026). No tool is called.
- **A3** A handoff packet built in code, the `app.handoffs` table, `mode = human`, Redis pub/sub, and a bot that stops replying.
- **A4** The live-takeover backend: staff login, a staff API (inbox, claim, agent message, return to bot), an inbox stream, an agent stream, and the relay of agent and customer messages.
- **A5** The AWS deploy v0 exactly as [`08-deployment.md`](../solution-docs/08-deployment.md) describes it, plus the admin demo-reset endpoint.

It serves every A1–A5 "Done when" line and the backend half of the D4 end-of-day test: step 2 (claim → packet → chat → return), step 4 (Pix, human, legal, bank-side), and the public URL for all of them. Dev B's B1–B4 rows (disputes tools, fraud flow, handoff widgets, staff screens) build against the contracts marked **(B builds against)** below. The first task ships those contracts as their own PR, so B isn't blocked (D1).

**Cut line (`07` D4 "If behind"):** A finishes the deploy (A5) on D5 morning, and the D4 end-of-day test runs locally with `make up`. A1–A4 are not cut.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **Contracts first.** Task 1 is a small PR to `develop` with everything marked (B builds against) in §Contracts: the `HandoffPacket` and staff API schemas, the SSE deltas, the flow-side `handoff()` contract, the `TurnState` delta and migration `0005`. It lands before any behavior | Assumption 1. `07` §1 "Contracts first" |
| D2 | **`escalation.yaml` v2 is the single source of each rule's queue and priority.** `rules.<reason>` carries `queue` (or `null` when the caller picks it: bank-side origin, human request) and `priority` (`high`/`normal`), plus optional `open_questions` keys. It replaces v1's `action_queues` and `customer_not_active.queue`, and `bank_side_queues` stays. The priority values are policy defaults, reviewed in the PR | Assumption 2. `07` D4-A1, `02` §5, R8, ADR-012 |
| D3 | **Legal and regulator words are a keyword list in `escalation.yaml`** (`legal_keywords.es/pt`). They are matched in code on the raw user text: lowercased, accent-folded, whole words or phrases. There is no new NLU field, and `nlu@v4` is untouched | Assumption 2. `02` §5 ("keywords or NLU flag") |
| D4 | **Order in `route`**, following the `02` §3 diagram: (1) the human-mode relay happens earlier, in `_entry` (D13); (2) an escalation hit (legal keyword, `human_request`, unauthorized access at threshold) goes to the handoff; (3) `out_of_market`/`out_of_scope` go to abstain; (4) everything else as today. An escalation hit wins over any other intent in the same message, and queued intents are dropped | Assumption 2. `02` §3, §6 ("the bot stops replying") |
| D5 | **`human_request` picks its queue from the paused flow** through `human_request_queues.by_flow` (`unrecognized_charge → fraudes`), otherwise `default: atencion` | Assumption 2. `02` §5 "queue chosen by the current flow, otherwise Atención" |
| D6 | **Another customer's data.** An attempt is a turn whose NLU status is `injection_suspected` (`nlu@v4` defines it as including "dato de otra persona"), or a turn where a tool raised `AccessDenied`. Every attempt is refused and audited as `access_denied{source: nlu\|tool, attempt}`. The first attempt gets the existing `injection_suspected` template. When `unauthorized_attempts` reaches `unauthorized_access.attempts_before_handoff` (2) in the same conversation, it hands off to Atención with reason `unauthorized_access` | Human Q5(a). `02` §5, `07` D4-A1 |
| D7 | **Flow-raised handoffs become real.** The existing `flows/actions.handoff(queue, reason, language)` keeps its signature. It now sets `escalation_reason`, `handoff_queue`, clears `pending`/`confirmation_token_id`, and routes to the handoff nodes instead of writing the placeholder. This covers bank-side block, customer not active and `action_unverified`. `clarification_exhausted` moves from `fallback` to a handoff to Atención. `no_cards` and `tool_unavailable` stay on `fallback`, because the R11 fallback + handoff is D6-A1 | `07` D4-A1 ("replaces B's placeholder"), `02` §5 |
| D8 | **`Queue` gains `reclamos`** (`localization.format.Queue` plus ES/PT labels). `retencion` and `creditos` are not added, because no rule routes to them yet | `02` §5 (legal → Reclamos) |
| D9 | **Two handoff nodes, for R6.** `handoff_summary` (an LLM node: reads facts and actions, has no write or handoff tools) runs first, then `handoff` (code only, no `app.core.llm` import), which cancels any open plan and calls `handoff.create`. The R6 scan adds `handoff_tools`/`HandoffTools` to its forbidden names | R6. `07` D4-A3 |
| D10 | **The packet is assembled in code** (`04` §4 shape). `request` is the only LLM field. It is one `core/llm` call (step `handoff_summary`, prompt `handoff_summary@v1`, Haiku 4.5, temperature 0) whose input is only code-built keys: reason, queue, intents, the actions' tool names and verified flags. Its draft uses `{card_mask}`, `{tx_count}` and `{queue_label}` placeholders that code fills, and it is capped at 200 characters. A draft with a raw digit outside a placeholder, an `LLMError` or an invalid output falls back to a fixed ES/PT template per reason. `sentiment` is `null` (not assessed). `verified_facts` and `actions_taken` come only from `TurnState.actions` entries with `verified = true`. It never includes a transcript | Assumption 3. `04` §4, R3, R4, R5, R11 |
| D11 | **New `handoff` domain** (`app/domains/handoff/`: schemas, repository, service) owns `app.handoffs`. The conversation domain reaches it only through `conversation/tools/handoff.py` (`HandoffTools`, bound to the `ToolContext`), injected as `config["configurable"]["handoff_tools"]`. The staff API calls `handoff.service` directly. **`create` returns the persisted id: D32** | Assumption 3. `06` §2, §3, `04` §1 `handoff.create` |
| D12 | **What a handoff does.** In one step it inserts the `app.handoffs` row (`status = queued`), sets `mode = human` in the checkpoint and in `app.conversations.mode`, publishes `handoff_created` on `handoff:<queue>`, and emits `mode{human}` and `ui.handoff_banner` on `conv:<id>`. The reply is the fixed `handoff_transfer` ES/PT template naming the queue and the reference. It replaces `handoff_placeholder` | Assumption 3. `02` §6 steps 1–2, ADR-015 |
| D13 | **Human mode is checked in `_entry`, before `understand`.** A turn with `mode == human` goes `load_session → relay_to_agent → finish`. There is no LLM call and no bot reply. The runner publishes the customer's text as `message{role: customer}` on `conv:<id>` and skips the bot `message` and `reply_sent`. This amends the `02` §3 diagram, which checks mode after `understand` | Assumption 4 |
| D14 | **Return to bot.** The claimant's `POST /staff/handoffs/{id}/return` takes the conversation's turn lock, sets `mode = bot` through `graph.aupdate_state`, and clears `pending`, `intent_queue`, `confirmation_token_id`, `escalation_reason`, `handoff_queue`, `clarification_failures` and `unauthorized_attempts`. It also sets `app.conversations.mode = bot` and the handoff `status = returned`, persists and emits the fixed `back_with_cardy` system message, and emits `mode{bot}`. **No summary fact is written:** `facts` are reset every turn by `load_session`, so a fact written between turns would never reach `compose`, and agent one-click actions (the only thing to summarize) are out of scope. `02` §6 step 5 is amended to say so. **Amended by D27, D28** (order, 409s, full list of cleared fields) | Assumption 4, amended by built fact (`state.py` `RESET_FACTS`). `02` §6, ADR-015 |
| D15 | **Staff access.** Seeded staff accounts: `identity.accounts` gains `username`, `display_name` and `staff_queue`, and `customer_id` becomes nullable (migration `0005`). One `agent` per queue (`atencion`, `cobranza`, `fraudes`, `reclamos`) plus one `admin` are seeded by `make seed-identity`, with passwords from `CREDENTIALS_SEED`, written to the git-ignored `data/secrets/staff_credentials.csv` (0600). `POST /auth/staff/login` issues the same cookie + CSRF session. `Session.role` becomes `customer \| agent \| admin` and `customer_id: str \| None`. `registry.build_tool_context` raises unless `role == "customer"` and `customer_id` is set (R1). The login limiter applies to staff logins, keyed by HMAC of the username. **Display names: D29. Seeding is run by the human: D31** | Human Q2(a). ADR-008 (amended 2026-09-28), R1, R13, ADR-023 |
| D16 | **Staff routes are their own routers.** `/staff/*` requires `agent` or `admin`, and `/admin/*` requires `admin`. Every `/staff/conversations/{id}/…` route depends on `get_claimed_conversation`: the conversation must have an open handoff claimed by the caller, otherwise `404 not_found`. **The agent stream is `GET /staff/conversations/{id}/stream`**, over the same `conv:<id>` channel, so `/conversations/{id}/stream` stays customer-only as R13 requires. This amends `04` §3's `customer, agent` stream row | Assumption 5. R13 (non-negotiable) over `04` §3 (field names proposed) |
| D17 | **Live inbox over SSE:** `GET /staff/handoffs/stream[?queue=]` pattern-subscribes to `handoff:*` and emits `handoff_created`/`handoff_updated`. The list endpoint seeds the screen | Assumption 5. `02` §6 step 1, `03` §6 Redis channels |
| D18 | **Structured abstain (ADR-026)** replaces `unsupported`'s `out_of_market`/`out_of_scope` templates. A new `policies/scope.yaml` maps each NLU `topic` to `{kind, reason_key, closest_intents[], human_queue}`. Code builds four facts (topic label, reason text, closest action label, human offer), and `compose` phrases them under a new `abstain` goal (`compose@v5`). A failed or rejected draft uses a fixed ES/PT four-part template. A `quick_replies{slot: "abstain"}` event offers the closest action and "talk to a person" as chips. `pending` is kept. No tool is called. `injection_suspected` keeps its own template (D6). **Topic mapping: D30** | Assumption 6. ADR-026, `02` §5, `07` D4-A2 |
| D19 | **The deploy follows `08-deployment.md` as written:** one t3.xlarge on Ubuntu 24.04, 80 GB gp3, default VPC, Elastic IP, IMDSv2 with hop limit 2; our us-east-1 bucket; the golden DB built on the box with `make data`; an IAM role for S3, Bedrock and SSM; SSM Session Manager and no SSH; SSM Parameter Store under `/swip/prod/` rendered to a 0600 `.env`; sslip.io + Let's Encrypt (staging first, Route 53 fallback); `LLM_PROVIDER=bedrock` with a `us.` profile; the Victoria/Grafana overlay on 127.0.0.1; no Langfuse; a $150 Budget. Every **(proposed)** default in `08` §1–§10 is **confirmed**: `docker/nginx/Dockerfile.prod` + `prod.conf`, `shared_buffers` 2 GB, `PUBLIC_HOST`, `.env.prod.example`, `infra/aws/ec2-stack.yaml`, `make infra-up`/`infra-down`/`deploy`/`deploy-remote`, the SSM path, and the bucket name kept out of the repo. **Layer order and who runs AWS: D26, D31** | Human (deploy answer). ADR-017 (decided 2026-09-28), `08` |
| D20 | **`08` §15 items confirmed:** 1 uvicorn worker; DuckDB `memory_limit` only if the first run is OOM-killed; deploy ref `main` on D4 and a release tag at the D8 freeze; CloudFormation; $150 per month; IAM model ARNs follow the `core/llm` registry. Staff protection is decided (D15). `08` §15 is updated | Human (deploy answer), `08` §15 |
| D21 | **`POST /admin/demo/reset`** (role `admin`) does what `make demo-reset` does, from inside the backend. It disposes the SQLAlchemy engine and the checkpointer pool, connects to the `postgres` maintenance DB, runs `DROP DATABASE latam_app WITH (FORCE)` + `CREATE DATABASE latam_app TEMPLATE latam_golden`, deletes the Redis keys `conf:*` and `turn:*`, reopens the pools, and returns `200 {status: "reset", duration_ms}` synchronously. Nginx's `/api/` `proxy_read_timeout` (≥ 300 s, set for SSE) covers it. It lives in `app/core/demo_reset.py` (core: DB and Redis only, no domain import) | `07` D4-A5, `08` §10 "Demo reset" |
| D22 | **Bedrock in prod.** The registry's Bedrock model ID for `nlu`, `compose` and `handoff_summary` is confirmed by one real call from the box. The "unconfirmed until K2" comment is then removed, and the IAM policy lists exactly those profile and foundation-model ARNs. Until D5-A1 creates `audit.llm_calls`, the proof is the backend's `llm.call provider=bedrock` log line. `08` §10 step 5 now says so | Human (deploy answer). ADR-028, `08` §4 |
| D23 | **Audit.** `AuditType` gains `handoff`, with payload `{action: created\|claimed\|returned, handoff_id, queue, reason}`. `AuditActor` gains `agent:<account_id>` for claim, return and agent messages. Agent messages are persisted in `app.messages` with `role = agent`, and the return message with `role = system` | `04` §6, `02` §6.4 |
| D24 | **Out of scope for this card:** `POST /staff/actions/{tool}` (agent one-click actions), the traceability timeline (D7-A1), per-queue claim permissions (any agent may claim any queue), and D6's turn caps and `LLM_DISABLED` | `07` D4-A4 lists none of them |
| D25 | **Doc updates.** *Already made at spec time:* ADR-008 amendment (staff accounts); `01` §6 and `03` §6/§8 identity text; `04` §3 staff line; `07` D4-A5 row (golden DB built on the box); `08` §10 step 5, §11 and §15. *In this card's PR:* `04` §3 (staff routes, streams, SSE deltas), §4 (`sentiment: null`, reason list, `reference`), §5 (`escalation.yaml` v2, `scope.yaml`); `02` §3 (mode check in `_entry`, handoff nodes), §5 (the unauthorized-access rule, D6), §6 step 5 (D14); `03` §6 (`app.handoffs` columns, `identity.accounts` staff columns); `06` §3 (`infra/`) | `06` §7.4 |

### Mid-card human decisions (verification gate)

| # | Decision | Why / trace |
|---|---|---|
| D26 | **Prod Compose layer order is base → observability → prod** (`COMPOSE_PROD`, `infra/aws/deploy.sh`, runnable proof 2). Prod comes last so its `!override` port lists win: with observability last, Compose merges ports by target and re-adds `8428/9428/10428/3000` on `0.0.0.0`. Amends D19 and §Contracts "Deploy artifacts" | Human, mid-card (T-compose escalation). `08` §7 |
| D27 | **Return-to-bot order (amends D14).** The claimant check runs first: a non-claimant gets `409 not_claimant` with nothing changed. Then `return_to_bot` sets `mode = bot` under the turn lock; a busy lock gets `409 turn_in_progress` with nothing changed. Only after that succeeds is the handoff marked `returned` and the `back_with_cardy` message and `mode{bot}` emitted | Human, mid-card |
| D28 | **`return_to_bot` clears all handoff state (amends D14):** `pending`, `intent_queue`, `confirmation_token_id`, `clarification_failures`, `escalation_reason`, `handoff_queue`, `unauthorized_attempts`, `handoff_id`, `handoff_evidence` and `handoff_request` | Human, mid-card |
| D29 | **Staff roster (amends D15):** `agent.atencion` = Laura, `agent.cobranza` = Diego, `agent.fraudes` = Sofía, `agent.reclamos` = Mateo, `admin` = "Swip Admin". These are the `display_name`s shown in `mode{agent_display_name}` and `claimed_by` | Human, mid-card |
| D30 | **`scope.yaml` mapping (amends D18):** every topic's `human_queue` is `atencion`. `loans` and `accounts` get a `card_status` chip, `pix_boleto` gets a `balance_due` chip, and `investments`, `insurance`, `transfers` and `other` get none (`closest_intents: []`, so only the human-offer chip) | Human, mid-card |
| D31 | **Who runs what.** The human runs the T32 deploy runbook (`make infra-up`, SSM parameters, `make deploy`/`deploy-remote`, the certificate) with their own AWS profile, and runs `make seed-identity`. Agents never run AWS commands or `make seed-identity`; they build and verify the artifacts only. Success criteria 4 (seeding) and 6–8 (deploy) are checked by the human | Human, mid-card |
| D32 | **The handoff uses the persisted id (amends D11, D12).** `HandoffTools.create(packet) -> UUID` returns the stored handoff id. When a handoff is already open for the conversation (the partial unique index), no second row or event is created: the customer is attached to the open one and the `handoff_transfer` reply and `ui.handoff_banner` carry that handoff's real `reference`. The checkpoint's `handoff_id` is the returned id, never the packet's candidate id (R3: a reference the customer sees is a real row) | Human, mid-card. `04` §1 updated |
| D33 | **`MessageRow.ui_payload` accepts a list of UI events** (`list[dict] \| dict \| None`), which is what the runner writes. It fixes the `500` on `GET /staff/conversations/{id}/messages` for a transcript that contains UI events. No contract change: `TranscriptMessage` still returns `{role, text, created_at}` | Human, mid-card (verifier finding) |
| D34 | **SC2 amended.** The Pix `make chat-api` debug line shows `tools=['get_profile']`. That is only `load_session`'s per-turn profile read: the request itself triggers no tool and no handoff, which meets `07` D4-A2 "Pix → no tool called". No product change | Human, mid-card |

## Contracts

Only the delta. Everything else is as in `04`, `02` and the earlier specs.

### SSE deltas on `conv:<id>` (B builds against)
- `mode {mode: "bot" | "human", agent_display_name: str | null}`. Emitted at handoff (`human`, `null`), at claim (`human`, the agent's `display_name`) and at return (`bot`, `null`).
- `message {role: "bot" | "customer" | "agent" | "system", text, sources: [], agent_display_name?}`. `customer` is published **only in human mode** (the relay for the agent), and the customer UI ignores its own echo. `agent` carries `agent_display_name`. `system` is the return-to-bot text.
- `ui.handoff_banner {handoff_id, reference, queue, queue_label}`. `reference` is `"HO-" + the first 8 hex digits of handoff_id, uppercased`, and `queue_label` is localized to the conversation language. Both are built in code.
- `ui.quick_replies`: `slot` becomes `Literal["block_kind", "abstain"]`. For `abstain`, `options` are the closest action's label and the human offer, and clicking one sends its label as text, as today.
- In human mode a customer turn emits `status`, the `message{role: customer}` echo and `done`. There is no bot `message`.

### Staff auth (B builds against)
- `POST /auth/staff/login {username, password}` is public and CSRF-exempt like `/auth/login`. It returns `StaffMeResponse{role: "agent" | "admin", username, display_name, queue: Queue | null}` plus the `session` and `csrf_token` cookies. Errors: `401 invalid_credentials`, `429 too_many_attempts`.
- `GET /staff/me` → `StaffMeResponse`. `POST /staff/logout` → `204` (revokes the `jti`).
- A customer session on any `/staff/*` or `/admin/*` route gets `403 forbidden_role`. A staff session on `/conversations/*` or `/auth/me` gets `403 forbidden_role`.

### Staff API (B builds against; routers `require_role("agent","admin")` + `require_csrf`)
| Method & path | Body → response | Errors |
|---|---|---|
| `GET /staff/handoffs?queue=&status=` | → `[HandoffSummary]`, newest first; `status` defaults to `queued,claimed` | — |
| `GET /staff/handoffs/stream?queue=` | SSE: `handoff_created {HandoffSummary}`, `handoff_updated {HandoffSummary}`, `: ping` every 15 s | — |
| `GET /staff/handoffs/{id}` | → `HandoffDetail{summary: HandoffSummary, packet: HandoffPacket}` | `404 not_found` |
| `POST /staff/handoffs/{id}/claim` | → `HandoffDetail`. Idempotent for the same agent | `404`; `409 already_claimed` (another agent); `409 handoff_closed` (returned) |
| `POST /staff/handoffs/{id}/return` | → `HandoffSummary` (`status = returned`) | `404`; `409 not_claimant` |
| `GET /staff/conversations/{id}/messages` | → `[TranscriptMessage{role, text, created_at}]`, oldest first | `404` unless claimed by the caller |
| `POST /staff/conversations/{id}/messages` | `{text: 1..2000}` → `201 {message_id}`; relayed on `conv:<id>` | `404` unless claimed by the caller |
| `GET /staff/conversations/{id}/stream` | SSE on `conv:<id>`, same framing as the customer stream | `404` unless claimed by the caller |
| `POST /admin/demo/reset` (role `admin`) | → `{status: "reset", duration_ms}` | — |

`HandoffSummary{handoff_id, reference, conversation_id, queue, priority: "high" | "normal", reason: HandoffReason, status: "queued" | "claimed" | "returned", language: "es" | "pt", created_at, claimed_by: str | null}`. `claimed_by` is the agent's `display_name`.

### `HandoffPacket` (`app/domains/handoff/schemas.py`, frozen, `extra="forbid"`; B builds against)
This is the `04` §4 shape, with these changes:
- `sentiment: None` (always, D10).
- `reason: HandoffReason` = `human_request | clarification_exhausted | legal_regulator | customer_not_active | bank_side_block | action_unverified | unauthorized_access | suspected_fraud`. D6 and D7 of the plan add `tool_failure`, `llm_unavailable` and `claim_priority`.
- `verified_facts[{fact, value, source}]`: one per verified `ActionResult`. `fact` is `card_locked` / `card_unlocked` / `card_status` / `replacement_ordered` / `claim_filed`, and `source` is `"audit:<audit_event_id>"` (or `"<tool> read-back"` when the id is `None`).
- `actions_taken[{tool, result: "applied", verified: true, audit_event_id, at, tracking_id?, case_id?}]`.
- `evidence` from `TurnState.handoff_evidence`, and `open_questions` rendered in code from `rules.<reason>.open_questions` keys.
- `escalation_rules_hit: [reason]`, `policy_version` = `ToolContext.policy_version`.

### Flow-side handoff contract (B's fraud flow builds against)
- `flows.actions.handoff(queue: Queue, reason: HandoffReason, language) -> dict` returns a state update. The graph routes it to `handoff_summary → handoff → finish`. The flow never writes the reply.
- A flow that wants evidence in the packet appends `HandoffEvidence{type: "transaction", ref: tx_id, fraud_score: int | None}` to `handoff_evidence` in the same update.
- The suspected-compromise path calls `handoff("fraudes", "suspected_fraud", language)` after its verified steps.

### `TurnState` delta (`state.py`)
`handoff_queue: NotRequired[Queue | None]`, `handoff_id: NotRequired[str | None]`, `unauthorized_attempts: NotRequired[int]`, `handoff_evidence: NotRequired[list[HandoffEvidence]]` (reset when a handoff is created). `mode` already exists and is now written. `escalation_reason` holds `HandoffReason` or one of the existing fallback reasons.

### Migration `0005_handoffs_staff` (down `0004`)
- `identity.accounts`:
  - `customer_id` becomes nullable.
  - Add `username text unique null`, `display_name text null`, `staff_queue text null`.
  - `CHECK (role IN ('customer','agent','admin'))` and `CHECK ((role = 'customer') = (customer_id IS NOT NULL))`.
  - Staff rows set `login_key` = HMAC(`staff:<username>`), so the NOT NULL unique constraint holds.
- `app.handoffs`:
  - Columns: `id uuid pk, conversation_id uuid fk app.conversations, queue text, reason text, priority text, packet jsonb, status text default 'queued', agent_id uuid null fk identity.accounts, created_at, claimed_at, returned_at`.
  - Index `(status, queue, created_at desc)`.
  - Partial unique index on `conversation_id WHERE status IN ('queued','claimed')`, so there is one open handoff per conversation.

### `policies/escalation.yaml` v2
```yaml
provenance: team-generated-synthetic
version: 2
customer_not_active: {statuses: [Closed, Suspended, Inactive], allowed: [lock_card, block_card]}
bank_side_queues:    {past_due: cobranza, fraud: fraudes, bank_status: fraudes, customer_status: atencion}
rules:
  human_request:           {queue: null,     priority: normal}
  clarification_exhausted: {queue: atencion, priority: normal}
  legal_regulator:         {queue: reclamos, priority: high}
  customer_not_active:     {queue: atencion, priority: normal}
  bank_side_block:         {queue: null,     priority: high}
  action_unverified:       {queue: atencion, priority: high}
  unauthorized_access:     {queue: atencion, priority: high}
  suspected_fraud:         {queue: fraudes,  priority: high, open_questions: [card_in_possession]}
human_request_queues: {default: atencion, by_flow: {unrecognized_charge: fraudes}}
unauthorized_access:  {attempts_before_handoff: 2}
legal_keywords:       # initial list; Dev B reviews it in the PR
  es: [demanda, demandar, abogado, abogada, condusef, superfinanciera, "superintendencia financiera", sic, bcra, "defensa del consumidor", denuncia]
  pt: [processo, processar, advogado, advogada, procon, "banco central", "reclame aqui", denúncia]
```

### `policies/scope.yaml` (new)
It has `provenance`/`version`, and `topics.<Topic>: {kind: out_of_market | out_of_scope, reason_key, closest_intents: [Intent], human_queue: Queue}` for every `Topic` literal (`loans, accounts, investments, insurance, transfers, pix_boleto, other`). `pix_boleto` is `out_of_market`. Every `human_queue` is `atencion`; chips per D30. The `reason_key`s and the closest-action labels map to fixed ES/PT texts in code.

### `core/llm`
`Step` gains `"handoff_summary"` (Haiku 4.5, temperature 0, same Bedrock/Anthropic IDs as `compose`). The prompt is `conversation/prompts/handoff_summary@v1.md`, and the output is `HandoffSummaryDraft{request: str}`. `compose` gains `Goal = "abstain"` in `compose@v5`.

### Deploy artifacts (`08` §7–§10)
- Layer order **base → observability → prod** (D26). `docker/docker-compose.prod.yml` uses `!override`/`!reset` ports so only nginx publishes on `0.0.0.0` (80 and 443), and everything else binds to `127.0.0.1`.
- `docker/nginx/Dockerfile.prod`, `docker/nginx/prod.conf`, a `certbot` service.
- `.env.prod.example`.
- `infra/aws/ec2-stack.yaml` (SG, role, profile, instance, EIP, Budget with the alert emails as stack parameters that are never committed).
- `infra/aws/render-env.sh` (SSM → 0600 `.env`, never echoes), `infra/aws/deploy.sh`, `infra/aws/smoke.sh`.
- Makefile: `COMPOSE_PROD`, `infra-up`, `infra-down`, `deploy`, `deploy-remote`, `smoke-prod HOST=`.

## Touch map

```
policies/escalation.yaml (v2), policies/scope.yaml (new)                        A1, A2
backend/app/domains/policy/{escalation,scope,registry}.py                       A1, A2
backend/app/domains/localization/format.py                                      D8 (reclamos)
backend/app/domains/conversation/{graph,state,templates,ui,runner,store}.py     A1–A4
backend/app/domains/conversation/nodes/{route,unsupported,compose}.py           A1, A2
backend/app/domains/conversation/nodes/{abstain,handoff_summary,handoff,relay}.py   new (A2, A3)
backend/app/domains/conversation/flows/{actions,card_select}.py                 D7
backend/app/domains/conversation/prompts/{handoff_summary@v1,compose@v5}.md     new
backend/app/domains/conversation/tools/{handoff,registry}.py                    new/edit (D11, D15)
backend/app/domains/handoff/{__init__,schemas,repository,service}.py            new (A3, A4)
backend/app/domains/identity/{models,tokens,service,provision}.py               D15
backend/app/domains/audit/schemas.py                                            D23
backend/app/core/{events,demo_reset}.py, core/llm/registry.py                   D17, D21, D22
backend/app/api/v1/{staff,staff_auth,admin,__init__}.py                         new (A4, A5)
backend/app/alembic/versions/0005_handoffs_staff.py                             new
backend/.importlinter                                                           handoff domain edges
backend/scripts/chat_api.py                                                     prints mode/handoff events
docker/docker-compose.prod.yml, docker/nginx/{Dockerfile.prod,prod.conf}        new (A5)
infra/aws/{ec2-stack.yaml,render-env.sh,deploy.sh,smoke.sh}                     new (A5)
.env.prod.example, Makefile                                                     A5
docs/solution-docs/{02,03,04,06}-*.md                                           D25 (in PR)
backend/tests/…                                                                 see Test list
```

## Test list

Unit tests use the fake LLM (`ScriptedLLM`) and fake handoff and bank tools. Integration tests run against `make up` (`it_env`). The deploy is proven by commands, not pytest.

| Test | Proves |
|---|---|
| `unit/test_escalation_rules.py::test_rule_hands_off[rule×es\|pt]` | A1 Done-when. For each of the 7 rules (human_request, clarification_exhausted, legal_regulator, customer_not_active, bank_side_block, action_unverified, unauthorized_access), in ES and PT: `handoff.create` is called with the YAML queue and reason, `mode = human`, and the `handoff_transfer` template is in the turn's language |
| `unit/test_escalation_rules.py::test_unauthorized_second_attempt_hands_off` | D6: attempt 1 → the refusal template and `access_denied`; attempt 2 → `access_denied` + handoff to Atención `unauthorized_access` |
| `unit/test_abstain.py::test_abstains_without_tools[es-pix\|pt-loans]` | A2 Done-when: no read, write or handoff tool is called; the four facts come from `scope.yaml`; `quick_replies{slot: abstain}`; `pending` kept |
| `unit/test_handoff_packet.py::test_packet_from_readbacks_only` | A3 Done-when, R3: every `04` §4 field is present; an unverified `ActionResult` is absent from `verified_facts`/`actions_taken`; the customer's typed text is not a substring of the packet JSON; `sentiment` is null; `request` ≤ 200 characters with placeholders filled in code |
| `unit/test_handoff_packet.py::test_summary_fallback` | R4, R11: a draft with a raw digit, and an `LLMError`, both give the fixed template |
| `unit/test_graph.py::test_human_mode_relays_without_llm` | A3 "the bot stops replying": after a handoff, a customer turn makes 0 LLM calls and returns no reply |
| `unit/test_r6_no_write_tools_in_llm_nodes.py` (extended) | R6: `handoff_tools`/`HandoffTools` are forbidden in LLM-importing modules; `nodes/handoff_summary.py` is scanned |
| `unit/test_r13_routes.py` (extended) | R13: `/staff/*` declares `RoleGuard(agent, admin)`, `/admin/*` declares `RoleGuard(admin)`, and every `/staff/conversations/{id}/…` route depends on `get_claimed_conversation`. `/auth/staff/login` is added to the public exemptions |
| `unit/test_r1_customer_scope.py::test_staff_session_cannot_build_tool_context` | R1: an `agent` session (no `customer_id`) → `build_tool_context` raises |
| `integration/test_staff_round_trip.py::test_handoff_claim_chat_return` | A4 Done-when, end-of-day step 2 (ES). "Quiero hablar con una persona" → the handoff row, then `handoff_created` on the inbox stream → claim → `mode{human, name}` on the customer stream → an agent message reaches the customer stream → a customer message reaches the agent stream with no bot reply → return → the `system` message + `mode{bot}` → the next customer message gets a bot reply |
| `integration/test_staff_round_trip.py::test_pt_handoff_happy_path` | The PT happy path: "Quero falar com uma pessoa" → handoff to Atención, transfer text in PT |
| `integration/test_staff_round_trip.py::test_staff_access_boundaries` | R13 across actors: customer → `/staff/handoffs` 403; agent → `/conversations` 403; agent B on agent A's claimed conversation → 404 on messages and stream; wrong staff password → 401 |

**Runnable proofs (A5):**
1. `aws cloudformation validate-template --template-body file://infra/aws/ec2-stack.yaml`.
2. `docker compose -f docker/docker-compose.base.yml -f docker/docker-compose.observability.yml -f docker/docker-compose.prod.yml config --format json | jq '[.services[] | .ports[]? | select(.host_ip != "127.0.0.1") | .published]'` prints only `"80"` and `"443"`.
3. `make smoke-prod HOST=<ip>.sslip.io` checks, over HTTPS: health 200, a persona login, one chat turn streamed, `/api/v1/test-idp/sessions` → 404, and a staff login.

`make check` green and `make test-integration` green locally.

## Boundaries

- **Always:**
  - Ship the contracts PR first (D1).
  - Take `customer_id` only from a customer session, and never build a `ToolContext` from a staff one (R1).
  - Keep queues, priorities and keywords in YAML (R8).
  - Build packet fields in code, with `request` from placeholders only.
  - Use the fake LLM in tests.
  - Render `.env` on the box from SSM with mode 0600.
  - Request the Let's Encrypt staging certificate before the real one.
  - Run `make data` on the box with only `postgres` and `redis` up.
- **Ask first:**
  - A new NLU field or an `nlu@v5` prompt bump.
  - Adding a queue beyond `reclamos`.
  - Changing `04` §4 packet fields beyond D10.
  - Staff one-click actions.
  - Opening any port other than 80/443, or changing the instance type or disk.
  - Changing `ActionResult` or existing `ui` payloads beyond §Contracts.
- **Never:**
  - Give `handoff_summary` or any LLM node write or handoff tools (R6).
  - Send the customer's text or the transcript to the LLM for the summary.
  - Commit the bucket name, alert emails, SSM values, `staff_credentials.csv` or any secret (R10).
  - `aws s3 sync` the repo's `data/` folder (`08` §5).
  - Open SSH, run Langfuse on prod, or expose Grafana/Victoria publicly.
  - Mount `/test-idp` in prod.
  - Edit `eval/scenarios/heldout/` or an existing migration.

## Success criteria

1. `test_escalation_rules.py` passes (7 rules × ES/PT plus the unauthorized case). `grep -rn "atencion\|reclamos\|fraudes\|cobranza" backend/app --include=*.py` shows queue names only in the `Queue` literal, the labels and tests, never as a rule's queue.
2. `test_abstains_without_tools` passes. `make chat-api PERSONA=<any>` with "¿Puedo pagar con Pix?" prints a four-part abstain, no handoff, and a debug line whose only tool is `get_profile` (`load_session`'s per-turn profile read; the request triggers no tool, D34).
3. `test_packet_from_readbacks_only`, `test_summary_fallback` and `test_human_mode_relays_without_llm` pass. After a handoff, `SELECT status, queue, reason, packet->>'sentiment' FROM app.handoffs` shows `queued`, the rule's queue and reason, and null, and `app.conversations.mode = 'human'`.
4. `test_handoff_claim_chat_return`, `test_pt_handoff_happy_path` and `test_staff_access_boundaries` pass. After the human runs `make seed-identity` (D31), it has written `data/secrets/staff_credentials.csv` (mode 0600, git-ignored) with 5 rows, and `SELECT role, count(*) FROM identity.accounts GROUP BY role` shows `agent 4`, `admin 1`, with the D29 display names.
5. The extended R1, R6 and R13 tests pass. `make check` is green.
6. (Checked by the human, D31.) `make infra-up` creates the stack. On the box, `make deploy` completes and `make smoke-prod HOST=<ip>.sslip.io` passes. `curl -sI https://<host>/` shows a Let's Encrypt (production) certificate and HSTS. `nc -z <eip> 22`, `5432` and `3000` all fail from a laptop.
7. The backend logs on the box show `llm.call provider=bedrock` with the registry's `us.` model ID, and the "unconfirmed until K2" comment is gone.
8. The D4 end-of-day test steps 2 and 4 pass on `https://<host>` in two browsers, together with Dev B's screens. `POST /admin/demo/reset` as admin returns 200, and the customer's changes are gone afterwards.
9. `02` §3/§5/§6, `03` §6, `04` §3/§4/§5 and `06` §3 are updated as D25 lists.

## Open questions

| Question | Default in this spec | Who decides |
|---|---|---|
| A message with both a safety action and an escalation ("bloquea mi tarjeta y pásame con alguien") goes straight to the handoff, and the block is not done (D4, per `02` §3) | Handoff first | Human, at the spec gate |
| Every `injection_suspected` turn counts as an unauthorized attempt, including pure instruction-injection with no data request, because the NLU status doesn't separate the two (D6) | Counts | Human, at the spec gate |
| Per-queue claim permissions (D24) | None: any agent may claim any queue | Human, if the demo needs it |
| A customer who reloads the page during human mode has no endpoint that reports the current mode; the banner comes only from live events | Not built | Dev B (B3), ask A if an endpoint is needed |
| The content of `legal_keywords` and the per-rule priorities | Initial lists above | Dev B, in the PR review |
