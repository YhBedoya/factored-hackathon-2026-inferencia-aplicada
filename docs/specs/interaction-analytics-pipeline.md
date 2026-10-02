# Spec: REQ-interaction-analytics-pipeline — fact tables, worker, sentiment and mock seeder

Card source: `docs/requirements/interaction-analytics-pipeline.md` (not a `07` row; card 1 of 2) · architecture: ADR-033 (Accepted) · owner **Dev A** · branch `feat/interaction-analytics-pipeline`, stacked on `feat/learned-intent-fallback` (human) · spec date 2026-10-02.

Naming: the requirement doc's items are **REQ-R1..REQ-R6**, its open questions **REQ-Q1..REQ-Q7**, its acceptance lines **DW1..DW8**. Bare **R1–R13** always means the safety rules in `06` §1. Pass-1 questions are **Q1–Q6**; their answers are the human's. **P1–P6** are the planner's gaps, answered by the human after the spec was approved (amendment of 2026-10-02).

## Objective

Turn every finished interaction with Cardy into one stored row of metrics plus one row per intent occurrence, keep those rows fresh with a separate worker, score sentiment once per interaction on masked text, and seed labelled mock rows so card 2 (`interaction-analytics-dashboard.md`) has data to show. The card delivers REQ-R1..REQ-R6 as written in the requirement doc, with the amendments in D2–D5 and D8. It serves DW1–DW8. The table schema (REQ-R2, as amended here) is the contract with card 2.

This spec does not restate REQ-R2's columns, REQ-R3's metric table or REQ-R5's profile. They are binding as written unless a `D` below changes them.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Scope is REQ-R1..R6; build order is migration (R2) and seeder (R5) first**, then R1, R3, R4, R6. The requirement's "Out of scope" list holds. The line "this card branches from `develop` after that merge" is superseded: the branch is stacked on `feat/learned-intent-fallback` | Requirement "Build order", "Out of scope"; human (brief) |
| D2 | **Segment `status` vocabulary:** `resolved`, `awaiting`, `handoff`, `abstained`, `cancelled`. A turn routed to `unsupported` writes `abstained`. `resolved` on a write flow is written only on the turn whose `ActionResult.verified` read-back succeeded; on a read flow, on the turn that answered with facts. `awaiting` is any turn that leaves the flow paused on the customer. **Outcome mapping** (the occurrence's last status): `resolved`→`resolved`, `handoff`→`handoff`, `abstained`→`abstained`, `cancelled`→`cancelled`, `awaiting`→`abandoned`. **`clarified` is never an outcome** and leaves REQ-R2's list<br>**Amended (P1, human):** flow endings that fit none of the lines above map by kind, with no new value; the table is D18. This changes the write-flow sentence: `already_in_state` (`card_block`) and `not_blocked` (`card_unlock`) are `resolved` without a verified write, because no write was needed. Every write that does run is still `resolved` only after its verified read-back<br>**Amended (P2, human):** a turn that `route` sends straight to `handoff_summary` writes one `handoff` segment per non-management intent in that turn's NLU result, in order (D19)<br>**Amended (human, mid-card, T2):** the sentence "a turn routed to `unsupported` writes `abstained`" has one exception, an `injection_suspected` turn, which writes no segment (D23) | Human Q1(a); R3; `cancelled` enters the status list as the consequence of Q2(a); human P1, P2; human mid-card T2 |
| D3 | **A write the customer cancels at the confirmation is the outcome `cancelled`**; the interaction's `resolved` is then false. REQ-R2's outcome list becomes `resolved`, `handoff`, `abstained`, `abandoned`, `cancelled` | Human Q2(a); ADR-033 "resolution is strict" |
| D4 | **Turns with no real intent write no segment** (REQ-R1.1 unchanged). The interaction's `abstained` flag is true when at least one intent ended `abstained` **or** any `reply_sent` has `route = "abstain"`. This widens REQ-R3's `abstained` definition | Human Q3(a) |
| D5 | **Occurrences.** Segments are read in order across the conversation. Consecutive segments with the same intent form one occurrence while its last status is `awaiting`. After any other status, the next segment with that intent starts a new occurrence. A flow replaced by a new intent (`enqueue`'s P1) closes its occurrence at its last status, so it ends `abandoned`. `seq` is the occurrence's order, from 1. `turns` is the number of distinct turns with a segment in the occurrence | Human Q4(a) |
| D6 | **Interaction-level outcome.** `resolved` = at least one occurrence, every occurrence `resolved`, and no handoff; null when there is no real intent or no segments. `abandoned` = `end_reason = idle` and the last occurrence ended `abandoned`. `real_intent_count` = number of occurrences<br>**Amended (human, OQ2(a)):** bot-offered occurrences that end `cancelled` are left out of both `resolved` and `real_intent_count` (D22) | REQ-R3 metric table, sharpened by D2, D5; human OQ2(a) |
| D7 | **Candidate lookup:** a single watermark row in the `analytics` schema plus a new index on `app.messages(created_at)`. The worker considers conversations with message or handoff activity since the watermark minus the idle window. Nothing is added to the chat's write path<br>**Amended (human, gate V3 and V3-recheck):** candidates are conversations with `app.messages.created_at`, `app.handoffs` `created_at`/`claimed_at`/`returned_at`, or `app.conversations.closed_at` since the watermark, each index-backed: `0009` also creates `ix_conversations_closed_at` and `ix_handoffs_{created,claimed,returned}_at`. With no watermark yet, the first run reads every conversation once as a backfill. Failure handling: D26 | Human Q5(a); REQ-R3 "must not scan every conversation"; human gate V3, V3-recheck |
| D8 | **The worker has its own Postgres role**, created in the migration: read-only on `app`, `audit`, `bank`; read-write on `analytics`; **plus `INSERT` on `audit.llm_calls` only**, because the sentiment call must be recorded there. Its password is a new secret in every environment (`.env.example`, `infra/aws/render-env.sh`, SSM, `08` runbook). No password literal in the migration. The worker's process uses this role for everything, including the LLM ledger sink<br>**Amended (P4, human):** the migration reads `ANALYTICS_DB_PASSWORD` from settings. Empty: the role is created without a password (it cannot log in) and an existing role's password is left alone. Non-empty: create the role if missing, then `ALTER ROLE … PASSWORD`. `make fill-secrets` generates the dev value; prod reads SSM<br>**Amended (plan-level, accepted by the human):** `infra/aws/render-env.sh` is not edited; it already copies every `/swip/prod/*` parameter | Human Q6(c); the `INSERT` exception is forced by R7 and REQ-R4.6 and was confirmed by the human (follow-up 3(a)); human P4 |
| D9 | **One row per conversation.** A conversation that got a row, then receives a new message, keeps its row; it is recomputed when it finishes again. Rows are never deleted by the worker | Assumption 6, shown to the human and not corrected; ADR-033 "upserts keyed by conversation id" |
| D10 | **Late handoff activity belongs to the interaction.** `handoff_summary` calls and agent messages count in `cost_usd`, `cost_handoff_summary_usd`, `agent_messages` and `duration_s`: an open handoff keeps the interaction unfinished, so they always precede the finish (closes REQ-Q4) | REQ-R3 "when an interaction is finished" + metric table |
| D11 | **Country** is `bank.customers.country` at compute time, mapped with the labels the staff list uses. `customer_id` is used for the join only and never stored (closes REQ-Q5) | `audit/repository.py` list query, `audit/timeline.py::_country_code`; REQ-R2 "no customer identifier" |
| D12 | **New domain `app.domains.analytics`.** It reads other schemas with its own SQL (the `audit/repository.py` precedent) and imports no `conversation` module. The cause-group constant and the mock profile live here, not in `policies/` | Requirement ("a constant in the analytics domain", REQ-R5.9); ADR-033; `06` §2 layers |
| D13 | **Sentiment** is a new step `sentiment` in `core/llm/registry.py` (Haiku 4.5 for `anthropic` and `bedrock`, temperature 0.0 like the other Haiku steps), prompt `sentiment@v1.md`, called only through `core/llm`. Input: the customer messages' `content_masked`. After R11's two retries, or under `LLM_DISABLED`, the other metrics are written, sentiment columns stay null, and a later pass retries rows with null sentiment<br>**Amended (human, gate; T10, T11 accepted):** sentiment runs as its own step after compute, scoring at most **50** rows with null sentiment per pass, not inline per candidate. It targets only conversations with at least one non-empty `content_masked` customer message; the others keep null sentiment, and an empty string never reaches the scorer. An upsert that finds a customer message newer than `sentiment_scored_at` clears the row's sentiment columns, so the next pass re-scores it | REQ-R4; R5, R7, R11; ADR-033; human gate (T10, T11) |
| D14 | **The graph's per-intent record uses a new graph-local channel**, not `GraphState.segments` (that name already holds the turn's reply texts). Only the `reply_sent` payload key is named `segments`. No LLM writes it | REQ-R1.1; `graph.py` `GraphState` docstring |
| D15 | **Mock seeding** is REQ-R5 as written. Mock ids are deterministic from date and index<br>**Amended (P5, human; replaces the earlier "a share of `cancelled` may appear"):** the mock profile's `cancelled` share is **zero**. The profile stays exactly as REQ-R5 writes it until card 2's open question (OQ1) is answered. `clarified` never appears<br>**Amended (human, gate; T9 accepted as written):** where REQ-R5 gives no value, the profile's invented values stand: a `handoff_summary` unit cost of 0.005, a 5% share of interactions with a second handoff, and the mapping of cause groups to queues. Mock rows have `bot_offered = false` and `channel = web` (D28) | REQ-R5; D2, D3; human P5; human gate (T9) |
| D16 | **Worker guard rails:** a database pool of **3** connections and a container memory limit of **512 MiB**. One sentiment call at a time with back-off, as REQ-R6.2 says | Human follow-up 1(b); REQ-R6.2 |
| D17 | **`needed_clarification`.** Every `awaiting` segment also carries `awaiting_slot`, copied by code from `pending.awaiting_slot`. An occurrence's `needed_clarification` is true when any of its `awaiting` segments has a slot other than `confirmation` or `otp` | Human follow-up 2(a) |
| D18 | **Flow endings outside D2's base rules, by kind.**<br>• `resolved`, a grounded "nothing to do / nothing found" answer: `already_in_state` (`card_block`), `not_blocked` (`card_unlock`), `decline_none`, `decline_unknown`, `tx_search_none`, `tx_explain_none`, `dispute_no_transactions`.<br>• `abstained`, something Cardy cannot serve: `replacement_not_eligible`, `no_cards` (through `fallback`, no handoff), the `AccessDenied` refusal from `_guard_access` inside a flow.<br>• `cancelled`, a declined offer or a dead pause: `replacement_declined`, and `nothing_pending` when the pause is cleared.<br>• `awaiting`, a question asked without a pause: `tx_search_ask_criterion` (`pending` is `None`), with an `awaiting_slot` set by code.<br>**Consequence:** after a permanent block `card_block` sets `pending.flow = replacement`, a bot-made offer. The next turn's segment is therefore `replacement_request`, an intent the customer never asked for, and a "no" there is `cancelled`. *Amended (human, OQ2(a)):* the interim rule (such an interaction is `resolved = false`) is replaced by D22<br>**Amended (human, planner round 2):** `card_unlock` on a card the customer blocked permanently (the `block_permanent_no_undo` answer, which also offers a replacement) is `abstained`. The offer it makes is bot-offered (D22) | Human P1; planner finding; human OQ2(a); human planner round 2, item 2 |
| D19 | **Direct handoff turns.** When `route` sends the turn straight to `handoff_summary` (`human_request`, a legal keyword, degraded clarification exhausted), every non-management intent in that turn's NLU result gets a `handoff` segment, in order. No intent: no segment; the interaction is still escalated, from `app.handoffs`<br>**Amended (human, planner round 2):** the degraded queue-head handoff is different. When the queue head is in `degraded_handoff_intents` (`llm_unavailable` → `fallback` → `handoff_summary`, no flow node runs), the turn writes **one** `handoff` segment, for the head intent only, with `route = handoff_summary`. The other queued intents get no segment | Human P2; human planner round 2, item 1 |
| D20 | **Relayed turns write no `reply_sent`**, so they carry no segments. The runner is left as it is | Human P6 |
| D21 | **Live proofs run from the worktree in one ALONE task** that takes over the shared stack. The human copies `.env` into the worktree. The task runs `make up` there, upgrades `latam_golden` and `latam_app` in place with Alembic (no demo reset, no `make seed-identity`), and runs the proofs. The human runs `make up` from the main checkout afterwards. Both databases keep migration `0009` | Human P3 |
| D22 | **A bot-offered intent is not a real intent.** A segment whose flow was started by the bot's own offer, not by an intent in the customer's NLU result, carries `bot_offered: true` (today: `replacement_request` after `card_block`'s permanent block, and, *amended by the human in planner round 2, item 3*, after `card_unlock`'s `block_permanent_no_undo` answer). Its occurrence is stored in `interaction_intents` with `bot_offered = true`. A bot-offered occurrence that ends `cancelled` is left out of `resolved` and `real_intent_count` (this amends D6), so a verified block followed by a declined replacement offer stays `resolved = true`. **Both marks are needed**: the segment key is how the worker learns it, and the column is the mark the human asked for on the stored occurrence, which card 2 needs to tell these rows apart. The names `bot_offered` (key and column) were shown to the human and not changed. **In every status other than `cancelled`, a bot-offered occurrence counts as a real intent**, like any other occurrence. Accepted cost: a customer who goes silent on the offer itself leaves it `abandoned`, which turns a verified block into `resolved = false` and `abandoned = true`. No test is added for this rule (test budget) | Human OQ2(a); human follow-up on other statuses, option (a) |
| D23 | **`unsupported` on an `injection_suspected` turn writes no segment.** The queue head on that turn is the paused flow's intent, not the attack, so an `abstained` segment would be charged to an intent the turn never worked on. This is the one exception to D2's `unsupported` rule | Human, mid-card (T2, graph) |
| D24 | **A late `compose` failure does not rewrite a status already set.** When `compose` fails after the flow ran and the turn hands off, an `awaiting` segment and any segment a flow marked explicitly keep their status. Only the deferred read-flow segment, whose `resolved` depended on the composed answer, flips to `handoff` | Human, mid-card (T2, graph) |
| D25 | **Worker start-up checks read one parsed URL.** `analytics_database_url` is parsed with `make_url`. An empty URL is a start-up error, with no fallback to the superuser URL; a missing or empty password in it is also a start-up error, passwordless URLs included. The refusal to run against a `latam_eval_` database reads the database name from the same parsed URL. This sits beside D8: the migration may still create the role without a password, and the worker then refuses to start until one is set | Human, mid-card (T10, worker; and the accepted plan-level mechanic on the empty URL) |
| D26 | **A conversation whose compute raises is skipped, not fatal.** The worker logs `analytics.compute_failed` with the conversation id and the exception class, and the pass continues (other candidates, mock seeding, sentiment). The watermark does not advance while any conversation of the pass failed, so it is retried next pass. Accepted cost: a conversation that always fails freezes the watermark; the log event makes it visible | Human, gate (V3, V3-recheck, T10) |
| D27 | **`analytics-worker` gets an explicit `environment:` list**, only the variables it uses, with no `env_file`: no `POSTGRES_PASSWORD`, `PII_VAULT_KEY` or `JWT_SECRET`. Its logs ship to VictoriaLogs through `setup_log_export("analytics-worker")` in `core/telemetry.py` (also used by `instrument_app`); the OTel endpoint for the worker is set only in `docker-compose.observability.yml` | Human, gate (T12, V4/T16) |
| D28 | **Implementer choices accepted as written** (human, gate): T1's column types and nullability (counts and durations integer, counts not null default 0; booleans not null default false except `resolved`; `cost_*` `numeric(12,6)` not null default 0, `sentiment_cost_usd` nullable; `metrics_version` not null without default; `language`, `country`, `channel` nullable); T8's readings (`resolved` is false whenever `handoff_count > 0`; an `awaiting` segment without a slot does not set `needed_clarification`; `end_reason = handoff_returned` when the last handoff is `returned`, and an open one gives no row); T9's mock values (D15); T13: `analytics.interactions.language` comes from `app.conversations.language`, set at creation, not from the NLU | Human, gate |

## Contracts

Only the delta. Existing shapes: `04` §6 (audit event), `03` §6 (schemas).

**`reply_sent` payload (extends `04` §6):**

```json
"segments": [{"intent": "card_block", "route": "card_block", "status": "awaiting", "awaiting_slot": "confirmation"}]
```

- Present on every `reply_sent`; `[]` when the turn worked on no real intent (D4). A turn relayed to an agent writes no `reply_sent` at all, so it has no segments (D20).
- One entry per real intent the turn worked on, in order. `intent` is a non-management member of `Intent`. On a resume turn (card pick, confirmation, OTP, selection) it is the paused flow's intent (REQ-R1.2).
- `route` is the branch node that served it (a member of `_BRANCH_NODES`, or `handoff_summary`).
- `status` ∈ `resolved | awaiting | handoff | abstained | cancelled` (D2).
- `awaiting_slot` is present only when `status` is `awaiting`: the value of `pending.awaiting_slot` at the end of the turn (`confirmation`, `otp`, or a flow's own slot such as `card_id`) (D17). When the flow asked without pausing (`tx_search_ask_criterion`), code sets the slot name (D18).
- `bot_offered: true` is present only on a segment whose flow the bot offered (D22); absent otherwise.
- Endings by kind: D18. Direct handoff turns: D19. Injection turns: D23. Late `compose` failure: D24.

**Schema `analytics` (migration `0009`):**

- `analytics.interactions`: REQ-R2's columns, primary key `conversation_id`, no foreign key, index on `ended_at`. Checks: `source IN ('real','mock')`, `end_reason IN ('customer_closed','idle','handoff_returned')`, sentiment labels `IN ('negative','neutral','positive')` or null.
- `analytics.interaction_intents`: `conversation_id, seq, intent, outcome, needed_clarification, turns, bot_offered` (boolean, not null, default false; D22), primary key `(conversation_id, seq)`, `outcome IN ('resolved','handoff','abstained','abandoned','cancelled')`.
- `analytics.worker_state`: one row holding the watermark (D7) and the last seeded mock day.
- `app.messages`: new index on `(created_at)`. Also new: `ix_conversations_closed_at` and `ix_handoffs_{created,claimed,returned}_at` (D7). Column types: D28.
- Role for the worker with the grants in D8. Roles are cluster-wide while the migration runs once per database (`latam_golden`, then clones), so role creation must be idempotent.

**Worker entrypoint:** one module in the analytics domain with a loop mode (the Compose service) and a run-once mode (`make analytics`), plus a run-once flag to recompute rows with an older `metrics_version` and a separate flag to re-score sentiment (REQ-R3). `metrics_version` starts at 1.

**`SentimentScorer` interface:** takes the ordered masked customer messages and the language; returns `overall`, `start`, `end` labels plus model id, prompt version and cost; or "unavailable". One customer message: `start = end` (REQ-R4.4).

**Settings:** REQ-R6.4's five names as proposed, plus `ANALYTICS_DB_PASSWORD` (D8) and the worker's database URL, checked at start-up as D25 says. Pool 3 and memory limit 512 MiB (D16).

**Planner assumptions, shown to the human and not corrected** (assumptions, not human decisions):

- The role is named `analytics_worker`; the settings are `ANALYTICS_DATABASE_URL` and `ANALYTICS_DB_PASSWORD`.
- On a resume turn the segment's intent is the queue head when its node equals `pending.flow` (`card_status` and `balance_due` share the `card_info` node); otherwise it is the registry intent for that flow.
- A turn routed to the `abstain` node with a real intent writes `abstained`.
- Success criterion 9 is proved with `SET ROLE` from a superuser session.

**Docs this card edits when it builds:** `04` §6 (`segments`), `03` §6 (`analytics` schema, the new index, the role), `06` §3 (domain list), `08` (new secret, new service), README (worker, `make analytics`, provenance row for mock rows).

**Docs amended together with this spec:** the pipeline requirement (REQ-R1.1 `awaiting_slot`, REQ-R2 outcome list per D2/D3, REQ-R3 `abstained` per D4, REQ-R6.2 role, pool and memory per D8/D16, its open questions marked answered), ADR-033 (outcome vocabulary, `abstained`, worker role and guard rails), and the dashboard requirement (new open question Q6 on `cancelled` in the per-day stack).

## Touch map

| Path | Change |
|---|---|
| `backend/app/alembic/versions/0009_analytics.py` | new: schema, tables, index, role and grants |
| `backend/app/domains/analytics/` | new: `repository.py`, `service.py` (finish rules, occurrences, metrics), `sentiment.py`, `mock.py`, `mock_profile.yaml`, `cause_groups.py`, `worker.py`, `prompts/sentiment@v1.md` |
| `backend/app/domains/conversation/graph.py`, `nodes/next_intent.py`, flow nodes, `nodes/handoff*.py`, `abstain.py`, `unsupported.py` | per-intent status channel (D14) |
| `backend/app/domains/conversation/runner.py` | `segments` on `reply_sent` |
| `backend/app/domains/conversation/store.py` | `close_conversation` writes `closed_at` |
| `backend/app/core/llm/registry.py` | `sentiment` step |
| `backend/app/core/config.py`, `.env.example`, `Makefile` (`fill-secrets`) | settings and the new secret |
| `docker/docker-compose.{base,dev,prod,observability}.yml`, `Makefile`, `.env.prod.example` | `analytics-worker` service with its explicit environment (D27), `make analytics` |
| `backend/app/core/telemetry.py` | `setup_log_export(service_name)` (D27) |
| `backend/tests/unit/test_analytics_*.py`, `backend/tests/integration/test_analytics_worker.py` | tests below |
| `docs/solution-docs/{03,04,06,08}*.md`, `README.md` | as listed under Contracts |

## Test list

Always a fake LLM. No tests for the migration, settings, schemas or Compose glue.

| Test | Proves |
|---|---|
| `test_segments_multi_intent` (unit) | DW1, capture half: a turn with one intent that resolves and one that hands off writes two segments with different statuses |
| `test_segments_write_flow` (unit) | DW2, R3: `card_block` is `awaiting` on the ask turn; the confirmation turn's segment carries `card_block` (not `affirm`) and is `resolved` only with a verified read-back; a cancel gives `cancelled`; an unverified result is never `resolved` |
| `test_sentiment_masked_only` (unit) | DW4, R5: the request the fake LLM receives contains no raw value from the vault; the call's cost lands in `sentiment_cost_usd` and not in `cost_usd` |
| `test_sentiment_unavailable` (unit) | DW5, R11: with `LLM_DISABLED`, and with an LLM that fails, a pass writes the rows with sentiment null after at most the bounded retries |
| `test_worker_es_multi_intent` (integration) | DW1, DW6 (ES): an end-to-end conversation produces two `interaction_intents` rows with different outcomes and `resolved = false` |
| `test_worker_pt_write_happy_path` (integration) | DW6 (PT), DW2: a block with confirmation produces one occurrence, `resolved`, and `resolved = true` |
| `test_finish_rules` (integration) | DW3: idle past the threshold gives `end_reason = idle`; an open handoff gives no row; a closed conversation has `closed_at` set and `customer_closed` |
| `test_mock_seed_deterministic` (integration) | DW7: empty schema, one pass gives 30 days of `source = 'mock'` rows; a second pass adds none; wipe and rebuild gives identical rows |

DW8 is proved by commands (Success criteria 8), run in the one live-stack task (D21).

## Boundaries

**Always**
- Read `content_masked`, never `content`, in the analytics domain.
- Call the LLM only through `app.core.llm`; bind `conversation_id` so the ledger row is attributed.
- Keep message text and customer identifiers out of both fact tables.
- Label every seeded row `source = 'mock'`.

**Ask first**
- Any change to REQ-R2's columns or outcome values beyond D2/D3/D22 (it is card 2's contract).
- Any grant for the worker role beyond D8.
- Any new write on the chat's request path beyond `segments` and `closed_at`.

**Never**
- Close a conversation, or change any chat behaviour, from the worker.
- Let an LLM write `segments`, an outcome or a cause group.
- Put the cause groups or the mock profile in a prompt.
- Run the worker against an eval database, touch `eval/scenarios/heldout/`, or commit a password.

## Success criteria

1. `cd backend && uv run pytest tests/integration/test_analytics_worker.py -k es_multi_intent` passes: two intent rows with different outcomes, `resolved = false` (DW1).
2. `uv run pytest tests/unit -k segments_write_flow` and the PT integration test pass (DW2).
3. `uv run pytest tests/integration -k finish_rules` passes (DW3).
4. `uv run pytest tests/unit -k sentiment_masked_only` passes (DW4).
5. `uv run pytest tests/unit -k sentiment_unavailable` passes (DW5).
6. Both integration happy paths (ES, PT) pass (DW6).
7. `uv run pytest tests/integration -k mock_seed_deterministic` passes (DW7).
8. In the live-stack task of D21 (run from the worktree, databases upgraded in place with Alembic): `make up` shows `analytics-worker` running in `docker compose ps`; `make analytics` exits 0 and, with mock enabled, `SELECT count(DISTINCT (ended_at AT TIME ZONE 'America/Bogota')::date) FROM analytics.interactions WHERE source='mock'` covers the backfill window (the day is taken in America/Bogota, not UTC: plan-level mechanic accepted by the human); `make check` passes (DW8).
9. In the same task, from a superuser session after `SET ROLE analytics_worker`: `INSERT` into `app.messages` fails with a permission error, `INSERT` into `analytics.worker_state` succeeds, `INSERT` into `audit.audit_events` fails, and `INSERT` into `audit.llm_calls` succeeds inside a transaction that is rolled back, so no row is left (D8). These are commands in that task; no new test file.
10. `04` §6 documents `segments` with D2's vocabulary and the `awaiting_slot` and `bot_offered` keys; `03` §6 lists the `analytics` schema; the README's provenance table lists the mock rows as team-generated synthetic.

## Open questions

| # | Question | Who decides |
|---|---|---|
| OQ1 | Card 2: an interaction whose only shortfall is a `cancelled` intent is in none of the per-day stacks (resolved, escalated, abandoned, abstained). Recorded as Q6 in the dashboard requirement; not answered here | Human, at card 2's spec |
| OQ2 | *Closed by D22* (a bot-offered occurrence is left out only when it ends `cancelled`; in every other status it counts) | Answered by the human |
| OQ3 | Card 2: whether bot-offered occurrences show in the intents chart and its per-intent resolution rate. Recorded as Q7 in the dashboard requirement; not answered here | Human, at card 2's spec |
