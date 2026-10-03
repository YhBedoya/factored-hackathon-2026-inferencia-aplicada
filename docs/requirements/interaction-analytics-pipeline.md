# Requirement: interaction analytics pipeline

Status: **draft for review** · Date: 2026-10-01 · Owner: to be set at spec time · Architecture: ADR-033.

This document is the input for `/wave-run`. The `spec-writer` turns it into `docs/specs/<slug>.md`. The open questions at the end are answered at that stage. It fixes what is built, why, and how "done" is judged. It does not fix implementation details.

It is card 1 of 2. Card 2 is [`interaction-analytics-dashboard.md`](interaction-analytics-dashboard.md), which reads the tables this card creates. The table schema in R2 is the contract between the two cards.

## Why

Swip has no view of how Cardy performs across conversations. The staff console shows one conversation at a time (ADR-024). Nobody can answer "what share of interactions does Cardy resolve?", "which intent fails most?", "what does an interaction cost?" or "how do customers feel when they leave?".

This card builds the data side: it turns every finished interaction with Cardy into one stored row of metrics, plus one row per intent, and keeps those rows fresh.

## Current state

Five of the six requested metrics are already captured by the platform. Only sentiment is new.

| Metric | Where it is today | Gap |
|---|---|---|
| Number of messages | `app.messages` (`role`: customer, bot, agent, system) | none |
| Resolution | `audit.audit_events`; `audit/timeline.py::compute_outcome` derives one outcome per conversation from the last reply | no per-intent outcome |
| Escalation | `app.handoffs` (`queue`, `reason`, `created_at`, `claimed_at`, `returned_at`) | none |
| Cost | `audit.llm_calls.cost_usd`, one row per LLM attempt, with `conversation_id` and `step` | none: every served step uses a priced Claude model |
| Intents | `nlu_result` audit events (`payload.intents`) | none |
| Sentiment | nothing | new |

Facts that shape the design:

- **Outcome is per conversation, not per intent.** `reply_sent` stores one `route` per turn: the first branch node the turn visited (`runner.py`). Audit events carry a `turn_id` but no intent. When a flow spans several turns, the later turns' NLU says `affirm` or `deny`, or NLU is skipped, and the flow name lives only in the graph's `pending` state.
- **Conversations almost never close.** The only trigger is the customer saying goodbye (`ui.conversation_closed`). `store.close_conversation` sets `status = 'closed'` and never writes `closed_at`. There is no idle timeout.
- **One conversation is one sitting.** The frontend keeps the conversation id in `sessionStorage`, so a new tab starts a new conversation.
- **Eval traffic is separate.** Eval runs use their own cloned databases (`latam_eval_<run_id>`), so nothing needs filtering in `latam_app`.
- **No background job exists** in the backend today.
- **`feat/learned-intent-fallback` (ADR-032) is not merged into `develop` yet** and changes the same runner and intent-queue code that R1 touches. This card branches from `develop` after that merge.

## What is built

### R1 · Capture: per-intent segments and the close time

1. `reply_sent`'s payload gains `segments`: a list with one entry per real intent the turn worked on, in order, each `{intent, route, status}`, plus `awaiting_slot` when the status is `awaiting`. `status` is one of `resolved`, `awaiting`, `handoff`, `abstained`, `cancelled` (spec D2, D17). A segment whose flow the bot offered, such as the replacement offer after a permanent block or after an unlock request on a permanently blocked card, also carries `bot_offered: true` (spec D22). It is written by code, where the graph already pops the intent queue (`nodes/next_intent.py`) and knows the paused flow (`pending.flow`). No LLM writes it. A turn relayed to an agent writes no `reply_sent`, so it has no segments. A turn routed straight to a handoff writes a `handoff` segment for each real intent in its NLU result; a degraded handoff of the queue head writes one, for the head intent only (spec D19). An unlock request on a card the customer blocked permanently is `abstained` (spec D18).
2. A turn that continues a paused flow (a card pick, a confirmation, an OTP resume) reports that flow's intent in its segment, even though its own NLU result says `affirm`, `deny` or nothing.
3. Management intents (`greeting`, `thanks_close`, `affirm`, `deny`) never produce a segment.
4. `store.close_conversation` also writes `closed_at`. The column already exists, so there is no migration.
5. `04-contracts.md` §6 documents the new payload key.

### R2 · Fact tables

A new Postgres schema `analytics`, owned by Alembic like every other schema. Two tables. Neither holds message text or a customer identifier.

**`analytics.interactions`**: one row per finished interaction, primary key `conversation_id`.

| Group | Columns |
|---|---|
| Identity and time | `conversation_id`, `source` (`real` or `mock`), `started_at`, `ended_at`, `end_reason` (`customer_closed`, `idle`, `handoff_returned`), `duration_s` |
| Dimensions | `language`, `country`, `channel` |
| Volume | `customer_messages`, `bot_messages`, `agent_messages`, `turns` |
| Outcome | `real_intent_count`, `resolved` (null when there was no real intent or no segments), `abandoned`, `abstained`, `degraded` |
| Escalation | `escalated`, `handoff_count`, `handoff_queue`, `handoff_reason`, `handoff_cause_group`, `time_to_claim_s` |
| Cost | `cost_usd`, `cost_nlu_usd`, `cost_compose_usd`, `cost_handoff_summary_usd`, `llm_call_count` |
| Sentiment | `sentiment_overall`, `sentiment_start`, `sentiment_end`, `sentiment_model`, `sentiment_prompt_version`, `sentiment_cost_usd`, `sentiment_scored_at` |
| Bookkeeping | `computed_at`, `metrics_version` |

**`analytics.interaction_intents`**: one row per intent occurrence, primary key `(conversation_id, seq)`.

`conversation_id`, `seq`, `intent`, `outcome` (`resolved`, `handoff`, `abstained`, `abandoned`, `cancelled`), `needed_clarification`, `turns`, `bot_offered` (true when the bot offered the intent and the customer did not ask for it; spec D22).

Rules:

- `conversation_id` has **no foreign key** to `app.conversations`, because mock rows (R5) have no conversation behind them.
- An index on `ended_at` supports the dashboard's date filter.
- `make demo-reset` wipes the schema together with the conversations. That is intended.

### R3 · The worker

A job that finds interactions that just finished, computes their rows and upserts them.

**When an interaction is finished.** One of:

- the customer closed it (`status = 'closed'`) → `end_reason = customer_closed`;
- there has been no message for the idle threshold (30 minutes) and no handoff is open → `idle`, or `handoff_returned` when its last handoff was returned;
- a conversation with a `queued` or `claimed` handoff is **not** finished.

Chat behaviour does not change: the worker never closes a conversation.

**Metric definitions.**

| Metric | Definition |
|---|---|
| Messages | counts from `app.messages` by role; `turns` is the number of distinct turn ids |
| Duration | first message to last message |
| Intent rows | one per intent occurrence, built from `reply_sent.segments`; `outcome` is the occurrence's last status, where a last status of `awaiting` becomes `abandoned`. A write the customer cancels at the confirmation is `cancelled`. `needed_clarification` is true when the occurrence waited on a slot other than `confirmation` or `otp`. Endings outside these rules map by kind (spec D18): a grounded "nothing to do / nothing found" answer is `resolved`, something Cardy cannot serve is `abstained`, a declined offer is `cancelled` |
| `resolved` | true when every real intent ended `resolved` and the interaction has no handoff. A read is resolved when Cardy answered with facts. A write is resolved only after the verified read-back, or when the card was already in the requested state and no write was needed. An intent the bot offered and the customer declined is not a real intent: it is left out of `resolved` and `real_intent_count`. In every other outcome a bot-offered intent counts like any other (spec D22) |
| `abandoned` | ended `idle` while a flow was still waiting on the customer |
| `abstained` | at least one intent ended `abstained`, or at least one `reply_sent` has `route = abstain` (a turn with no real intent writes no segment) |
| `degraded` | at least one `reply_sent` with `degraded: true` |
| Escalation | from `app.handoffs`. The **first** handoff sets queue, reason and cause group; `handoff_count` records the rest |
| Cause group | a constant in the analytics domain, not a policy file: **by design** (`suspected_fraud`, `priority_claim`, `legal_regulator`, `customer_not_active`, `bank_side_block`), **customer choice** (`human_request`), **bot failure** (`clarification_exhausted`, `tool_failure`, `llm_unavailable`, `action_unverified`), **security** (`unauthorized_access`) |
| Cost | sum of `audit.llm_calls.cost_usd` for the conversation, also split by step. The sentiment call is excluded and stored in `sentiment_cost_usd` |

**Behaviour.**

- Runs every 2 minutes. Upserts are keyed by `conversation_id`, so a rerun is safe.
- Finding candidates must not scan every conversation: it keeps a watermark row in the `analytics` schema and uses an index on `app.messages(created_at)`.
- A run-once mode recomputes rows whose `metrics_version` is older than the current one. It does not re-score sentiment unless asked.
- Conversations from before R1 have no segments: they get an `interactions` row with `resolved` null and no intent rows.

### R4 · Sentiment

1. A new LLM step `sentiment` in `core/llm/registry.py`, on Haiku 4.5 for both providers. It runs once per finished interaction and returns three labels from `negative`, `neutral`, `positive`: overall, at the start, and at the end.
2. Input is the customer's messages only, taken from `content_masked`. Raw text never reaches the provider (R4 of `06` §1).
3. **Swappable.** The analytics code calls a `SentimentScorer` interface; the Haiku scorer is its first implementation. Changing model or provider is a registry edit. Each row stores `sentiment_model` and `sentiment_prompt_version`, and masked messages are retained, so old interactions can be re-scored after a switch.
4. With a single customer message, start and end take the same label.
5. When the LLM is disabled (`LLM_DISABLED`) or unavailable, the other metrics are still written, sentiment stays null, and a later pass retries it.
6. The call is recorded in `audit.llm_calls` under its own step.

### R5 · Mock data seeder

Development and the judged deployment have little real traffic. The seeder fills the fact tables with simulated interactions so the dashboard shows how it looks in production, and keeps that data fresh every day.

1. Mock rows go into the same two tables with `source = 'mock'`. This labelling is required (B2: inputs are labelled real, synthetic or team-generated; an unlabeled mix fails).
2. The worker does the seeding; there is no cron and no second scheduler. On each pass it creates today's batch if it is missing.
3. On first run, after `make demo-reset`, or after downtime, it backfills the missing days, up to the last 30.
4. Each day's batch is generated from its date as the random seed, with deterministic conversation ids, so the same day always gives the same rows.
5. A day's rows are spread across the whole day. Rows whose `ended_at` is in the future exist in the table but are not shown (the dashboard card filters them).
6. Seeding makes no LLM call: sentiment labels and costs are generated values.
7. The day boundary uses one time zone setting, default `America/Bogota`.
8. A setting enables it. It is off by default, and on in development and in the judged deployment.
9. The profile lives in one file in the analytics domain with the header `provenance: team-generated-synthetic`. Starting values:

| Aspect | Value |
|---|---|
| Volume | about 120 interactions on weekdays and 70 at weekends, ±15% daily noise; peaks late morning and early evening |
| Language | Spanish 80%, Portuguese 20% |
| Country | MX 45%, CO 30%, AR 25% |
| Intents | the 11 core intents of `conversation/intents.yaml`, led by `balance_due`, `card_status`, `transaction_search`, `decline_explain`; about 1.3 intents per interaction |
| Outcomes | resolved about 72%, escalated 16%, abandoned 8%, abstained 4%; no `cancelled` intents until the dashboard card decides where they show |
| Escalation causes | by design 8%, customer choice 4%, bot failure 3%, security 1% |
| Resolution by intent | reads 85–92%, card actions 75–85%, `unrecognized_charge` mostly handed to fraud, `human_request` always handed off |
| Messages | median 6, between 2 and 20 |
| Cost | measured unit costs (about $0.017 per NLU call, $0.005 per compose call) times the turns |
| Sentiment | negative 18%, neutral 55%, positive 27%; 30% end better than they started, 10% worse |
| Degraded share | 2% |

Apart from the unit costs, these values are invented to look plausible. They are not derived from data and make no claim about a trend.

### R6 · Runtime

1. A Compose service `analytics-worker` runs the backend image with its own entrypoint, in dev and prod, on the same EC2 instance. It restarts like the other services.
2. Guard rails, so it never competes with the chat: a container memory limit of 512 MiB, a database pool of 3 connections, one sentiment call at a time with back-off.
   The worker connects with its own Postgres role, created in the migration: read-only on `app`, `audit` and `bank`, read-write on `analytics`, and `INSERT` on `audit.llm_calls` only (for R4.6). Its password is a new secret in every environment and in the deploy runbook. The migration reads it from `ANALYTICS_DB_PASSWORD`: when it is empty the role is created without a password and cannot log in. `make fill-secrets` generates the dev value and prod reads SSM.
3. `make analytics` runs one pass on demand (compute, and seed when enabled).
4. Settings (proposed names): `ANALYTICS_IDLE_MINUTES=30`, `ANALYTICS_WORKER_INTERVAL_S=120`, `ANALYTICS_TIMEZONE=America/Bogota`, `ANALYTICS_MOCK_ENABLED=false`, `ANALYTICS_MOCK_BACKFILL_DAYS=30`. The demo environment may set a short idle threshold (for example 2 minutes) so a demo conversation reaches the dashboard quickly.
5. Docs: `03-data-architecture.md` §6 gains the `analytics` schema; the README gains the worker, the make target and the mock data's provenance.

## Build order

The migration (R2) and the seeder (R5) come first, so the dashboard card can start against seeded rows while R1, R3 and R4 are still in progress.

## Done when

1. A multi-intent conversation where one intent resolves and one hands off produces two `interaction_intents` rows with different outcomes, and `resolved = false` on the interaction.
2. A write intent counts as resolved only after its read-back; a flow continued by a confirmation turn is attributed to the flow's intent.
3. A conversation with no message for the idle threshold gets a row with `end_reason = idle`; one with an open handoff gets no row; a closed one has `closed_at` set.
4. The sentiment call receives only masked text (a test asserts no raw value from the vault is in the request), and its cost is stored apart from the interaction's cost.
5. With the LLM disabled, a pass still writes the rows, with sentiment null.
6. One Spanish and one Portuguese interaction run end to end with a fake LLM and produce correct rows.
7. With mock enabled on an empty schema, one pass creates 30 days of `source = 'mock'` rows; a second pass adds nothing; a rebuild gives the same rows.
8. `make up` starts the worker; `make analytics` runs one pass; `make check` passes.

Tests stay minimal (CLAUDE.md): the lines above and the safety rules this card touches, always with a fake LLM.

## Out of scope

- The dashboard page and its endpoint (card 2).
- Closing idle conversations in the product.
- Per-message sentiment, and a trained sentiment model.
- Daily rollup tables, partitions, a read replica or a columnar export. They are the growth path if volume gets much larger, and none is needed now.
- A CSAT survey.
- Retention or purge of fact rows.

## Open questions

All answered at spec time; see `docs/specs/interaction-analytics-pipeline.md` (Q1 → D2, D3, D17; Q2 → D5; Q3 → D7; Q4 → D10; Q5 → D11; Q6 → D8; Q7 → Dev A). The original wording is kept below.

- **Q1 · Segment vocabulary.** The exact `status` values a segment can carry, and how each maps to the five intent outcomes. In particular: is an interaction that ends on an unanswered clarifying question `clarified` or `abandoned`?
- **Q2 · Intent occurrence.** When does a repeated intent start a new occurrence instead of continuing the previous one?
- **Q3 · Candidate lookup.** A watermark table, or a `last_message_at` column on `app.conversations`?
- **Q4 · Late handoff costs.** `handoff_summary` calls and agent messages can arrive after the bot's last turn. Confirm they belong to the interaction's cost and message counts.
- **Q5 · Country source.** Confirm country comes from the customer record at compute time, as the staff conversation list does.
- **Q6 · Database role.** Does the worker use the app's role, or its own?
- **Q7 · Owner.** Which developer takes this card.
