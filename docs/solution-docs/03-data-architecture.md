# 03 — Data architecture

## 1. Sources and provenance (B1, B2)

| Input | Provenance | Used for |
|---|---|---|
| S3 `data/` (13 tables, uploaded 2026-08-31) | **Synthetic**, organizer-approved | Serving DB (all tables), grounding, demand analysis, operational baseline |
| S3 `data_backup_20260831/`, root `marketing_campaigns.csv` | Synthetic, older partial copies | **Not used**. Documented as excluded |
| `policies/*.yaml` | **Team-generated synthetic** policy | Decline codes, min payment, limits, dispute questions, escalation thresholds |
| `eval/scenarios/**` | **Team-generated** (seeds + LLM paraphrases, human-reviewed) | Evaluation and dev tuning |
| `analytics.*` rows with `source = 'mock'` | **Team-generated synthetic** (seeded by the analytics worker from a fixed profile) | Dashboard demo data; never mixed with `source = 'real'` rows |
| Demo credentials, fixed step-up OTP | **Team-generated** (credentials at load; the OTP is a fixed code in an env var) | Mock IdP |

S3 credentials come from env vars / an AWS profile (page 2 of the data dictionary). They are never written to the repo.

The deployment reads a one-time copy of the organizers' `data/` prefix in the team's own S3 bucket (us-east-1), accessed through the EC2 instance role. The copy is checked by file count and per-key size against the source listing (see `08-deployment.md` §5).

## 2. Pipeline

```
S3 data/ ──(1) ingest──► data/raw/<table>/year=…/month=…/day=…/*.parquet   + data/raw/_manifest.json (key, size, ETag, downloaded_at)
         (step 1 also accepts `SOURCE=local:<path>`, an existing local mirror of the same layout; no AWS credentials needed then, D6)
         ──(2) contracts (Pandera, per partition) ──► data/quality/<run_id>/contract_report.json
         ──(3) dbt-duckdb
               staging/   stg_<table>: typed, renamed, enums normalized, dedup on PK (dups kept in stg_<table>__rejects)
               intermediate/ int_*: joins and derived fields (card_type, masked number, available credit, fx rates)
               serving/   srv_<table>: final column set per Postgres table, DATE SHIFT applied (var date_offset_days)
               tests: unique, not_null, accepted_values, relationships (FKs, orphans reported, not dropped), freshness
         ──(4) load: TRUNCATE bank.* + identity.accounts + app.handoffs (every table referencing identity.accounts, named explicitly, no CASCADE; D6-A D25) → COPY into bank.* (DDL owned by Alembic)
         ──(5) provision identity: credentials for all customers → identity.accounts; export to data/secrets/credentials.csv (git-ignored)
         ──(6) snapshot: golden database `latam_golden` (CREATE DATABASE … TEMPLATE)
```

- **Orchestration:** `make data` runs steps 1–6. Each step is idempotent and keyed by a `run_id`. dbt `docs generate` produces the **lineage graph** (D4.4). Artifacts are kept under `data/lineage/`.
- **Determinism (D4.1):** given the same manifest and `load_date`, the output is identical. Fixed seeds are used for credential generation.

## 3. Contracts and quality (D4.2, D4.3)

- Contracts are defined from the **observed** schema, with deviations from the dictionary documented: Spanish enum values ("Tarjeta Crédito", "Transaccional"…), missing transcript columns (`full_text`, `agent_text`), row counts 84–156% of documented.
- Pandera checks per raw partition: column presence and types, nullability, enum domains, ranges (`fraud_score` 0–100, `credit_score` 300–850), PK uniqueness. Only a **structural break** (an unreadable file, a missing PK column) stops `make data`; every other failure, and column drift, is counted in the report and the rows flow on. Only manifest entries not yet in `data/quality/contract_cache.json` (by key + ETag/SHA-256) are validated (D6-A D17).
- dbt tests on staging and serving: PK uniqueness, FK relationships (orphans are counted and flagged, never silently dropped), accepted values, semantic checks from the EDA (transactions before card opening or after expiry, future `last_updated`, the `process_date` UTC/local shift). The relationship and semantic tests run at `severity: warn`; the PK and accepted-values tests on serving stay `error` (D6-A D18).
- D1.3 finding: `process_date` follows UTC−6 in all three countries (MX, CO, AR); rows stamped 00:00–05:59 carry the previous day (D1-A D1).
- Output: a quality report per run (counts, rates, failing rows sample) that feeds the D1.3 analysis: `data/quality/<run_id>/{contract_report.json, quality_report.json, quality_report.md}`, with samples limited to the PK and the failing column (≤5 rows per check). Lineage: `dbt docs generate` → `data/lineage/<run_id>/`, plus the committed `pipeline/lineage.md` (D6-A D21).

## 4. Freshness and update policy (D4.5)

- The delivery is a single static snapshot. The **policy**: ingest is incremental by daily partition. A partition is (re)processed when its manifest entry (size/ETag) changes. dbt then rebuilds staging and serving in full on every run, which is deterministic for a given manifest (amended D6-A D19: no dbt incremental models).
- **Labeled test fixtures** (`pipeline/fixtures/test_fixture_{late_partition,schema_change,duplicate_batch}/`, clearly marked TEST FIXTURE):
  1. A late-arriving partition for an already-processed day, with corrected rows.
  2. A schema-evolved partition with an added column and a renamed column.
  3. A duplicate batch, re-delivering an already-loaded partition.
  Expected results are asserted in `pipeline/tests/` (idempotent row counts, the new column mapped, dups rejected). Semantics (D6-A D20): (1) is the same key with a new ETag, re-ingested over the old file, so the corrected values win and the count is unchanged; (2) renames `merchant_name` → `merchant` (mapped back through one alias map read by Pandera and dbt) and adds `installments` (reported as drift, not loaded into Postgres); (3) is the same rows under a new key in the same partition, which land in `stg_<t>__rejects`. The fixture tests run `dbt build --select stg_transactions+ stg_transactions__rejects --indirect-selection cautious --exclude test_name:relationships test_type:singular` on a tmp DuckDB (the other parents of those tests aren't there; dbt 1.12 rejects `test_type:relationships`).

## 5. Date shift (simulated "now")

- `max_data_date = 2026-06-17` (last partition). At load: `date_offset_days = 7 × floor((load_date − max_data_date) / 7)`. The whole-week offset keeps weekday patterns and relative expressions like "el martes pasado" consistent.
- Applied in the dbt `serving` layer to **every** DATE/TIMESTAMP column (including `date_of_birth`, expiration dates, exchange-rate dates, partition columns), so ages and intervals are unchanged. Raw and staging are never shifted.
- The offset and `load_date` are recorded in `app.system_metadata` and shown in the staff console.
- After load, the app uses the real clock (`BANK_TZ` per country). Data ages naturally after deploy day.
- Time zone (D1-A D1): every `bank.*` TIMESTAMP column is UTC, stored as `timestamptz`. Local display and relative-date resolution use `BANK_TZ` per country: MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`.

## 6. Postgres schemas

DDL for **all** schemas is owned by Alembic, including the provided tables. The loader only `COPY`s. The LangGraph checkpointer manages its own tables in schema `langgraph`.

### `bank`: provided tables (all 13, including unused ones)
`customers`, `products`, `transactions`, `complaints`, `call_center_interactions`, `call_transcripts`, `satisfaction_surveys`, `digital_events`, `campaign_sends`, `branches`, `service_agents`, `marketing_campaigns`, `daily_exchange_rates`.

Additions to provided tables:
- `origin text not null default 'dataset'` (`dataset` or `app`), `created_at`, and `conversation_id` (nullable) on tables the app appends to (`complaints`; `digital_events` for logins **(proposed)**).
- Columns updated in place by the app (e.g., `products.product_status`) always get a history row in the same transaction.
- `complaints` also gets `transaction_id` (nullable, the disputed transaction) and `idempotency_key` (unique nullable, `<token_id>:<step_index>:<tx_id>`) in migration `0006` (D4-B D14–D15). An app claim is one row per transaction: `complaint_id = CLM-` + 8 upper hex, `case_type='Claim'`, `category='Transactions'`, `subcategory='Cargo no reconocido'`, `reception_channel='App'`, `status='Open'`, with amount, currency and product copied from the transaction.

Indexes **(proposed)**: `products(customer_id, product_type)`, `transactions(customer_id, product_id, transaction_date desc)`, `transactions(product_id, transaction_status, transaction_date desc)`, `complaints(customer_id, creation_date desc)`.

### `app`: complementary operational tables
| Table | Purpose |
|---|---|
| `card_status_history` | (migration `0003`, D3-A3) `id, product_id, old_status, new_status, reason, actor (customer/agent/system), conversation_id, trace_id, at, idempotency_key` (unique nullable, D3-A D11); index `(product_id, at desc)` |
| `card_controls` | (migration `0003`) Temporary lock: `product_id` (pk), `locked, locked_by, locked_at, updated_at, idempotency_key` (unique nullable). Channel toggles and spending limits are Stretch, not yet columns |
| `card_replacements` | (migration `0003`) Order: `id, product_id, address_ref` (PII-vault token, never a raw address), `address_changed, tracking_id` (unique, `RPL-` + 8 hex upper), `status, conversation_id, created_at, idempotency_key` (unique nullable). No address snapshot until D5-A1 encrypts one |
| `travel_notices` | Stretch |
| `conversations` | `id, customer_id, channel, language, mode (bot/human), status, started_at, closed_at` |
| `messages` | `conversation_id, role (customer/bot/agent/system), content` (raw text, Fernet ciphertext under `PII_VAULT_KEY`; rows written before migration `0007` stay plaintext until `make demo-reset`, because `0007` doesn't backfill), `content_masked` (always set, on every insert: customer, bot, agent, system), `ui_payload, created_at` |
| `handoffs` | (`app.handoffs`, migration `0005`) `id, conversation_id` (fk), `queue, reason, priority, packet jsonb, status` (`queued`/`claimed`/`returned`, default `queued`), `agent_id` (fk `identity.accounts`, null), `created_at, claimed_at, returned_at`; index `(status, queue, created_at desc)` and a partial unique index on `conversation_id WHERE status IN ('queued','claimed')`: one open handoff per conversation |
| `pii_vault` | (migration `0007`) `conversation_id, token` (`⟨KIND_n⟩`, KIND in CARD/DOC/EMAIL/PHONE/NAME/ADDR), `kind, value_enc` (Fernet), `created_at, expires_at` (null; the purge job is not built). Primary key `(conversation_id, token)`; the same raw value in a conversation gets the same token |
| `system_metadata` | `load_date`, `date_offset_days`, dataset manifest hash, policy hash |

### `identity`
`accounts` (`customer_id`, `login_key` = HMAC of the login identifier (never the plain document number), password hash, role, status), `revoked_tokens`. Staff accounts (D4-A, ADR-008 amended): role `agent` or `admin`, a unique `username`, `display_name`, `staff_queue`, and `customer_id` null (migration `0005` makes it nullable and adds `CHECK (role IN ('customer','agent','admin'))` and `CHECK ((role = 'customer') = (customer_id IS NOT NULL))`; staff `login_key` = HMAC of `staff:<username>`); names are Laura (atencion), Diego (cobranza), Sofía (fraudes), Mateo (reclamos) and "Swip Admin"; one agent per handoff queue plus one admin, seeded by `make seed-identity`. There is no OTP storage: the step-up OTP is a fixed demo code (ADR-008), and the time of the last successful step-up is kept in the session.

### `audit`
`audit_events` (migration `0004`, D3-A5, append-only, no update or delete path: `id, at, conversation_id, turn_id, actor, type, payload jsonb, sources jsonb, policy_version, model jsonb, trace_id, langfuse_trace_id`; index `(conversation_id, at)`; see `04-contracts.md` §6 for the full shape), `llm_calls` (migration `0007`, append-only, one row per LLM attempt: `id, at, conversation_id, turn_id` (both null-able, from the log context), `step, provider, model_id, prompt_version, temperature` (nullable since migration `0008`: null when the model takes no temperature, e.g. Sonnet 5.5 for NLU), `attempt, status` (`CHECK` in `ok`, `invalid`, `unavailable`, `refused`), `input_text` (masked; null when refused), `output_json, input_tokens, output_tokens, cost_usd, latency_ms, langfuse_trace_id`; index `(conversation_id, at)`).

### `analytics`
(migration `0009`) Derived interaction metrics, written by the analytics worker and read by the dashboard. The tables hold no message text and no customer identifier. `conversation_id` has no foreign key, because mock rows have no conversation behind them. Created and owned by Alembic like every other schema.

| Table | Columns |
|---|---|
| `analytics.interactions` | Primary key `conversation_id` (uuid). Time: `source` (`real` or `mock`), `started_at`, `ended_at`, `end_reason` (`customer_closed`, `idle`, `handoff_returned`), `duration_s`. Dimensions: `language`, `country`, `channel`. Volume: `customer_messages`, `bot_messages`, `agent_messages`, `turns`. Outcome: `real_intent_count`, `resolved` (null when there was no real intent or no segments), `abandoned`, `abstained`, `degraded`. Escalation: `escalated`, `handoff_count`, `handoff_queue`, `handoff_reason`, `handoff_cause_group`, `time_to_claim_s`. Cost (`numeric(12,6)`): `cost_usd`, `cost_nlu_usd`, `cost_compose_usd`, `cost_handoff_summary_usd`, plus `llm_call_count`. Sentiment (all nullable): `sentiment_overall`, `sentiment_start`, `sentiment_end` (`negative`, `neutral`, `positive`), `sentiment_model`, `sentiment_prompt_version`, `sentiment_cost_usd`, `sentiment_scored_at`. Bookkeeping: `computed_at`, `metrics_version`. Index on `ended_at`. Checks on `source`, `end_reason` and the sentiment labels |
| `analytics.interaction_intents` | Primary key `(conversation_id, seq)`. `intent`, `outcome`, `needed_clarification`, `turns`, `bot_offered` (boolean, not null, default false) |
| `analytics.worker_state` | One row (`id = 1`): `watermark` (timestamptz, null) and `mock_seeded_through` (date, null) |

- `outcome` is one of `resolved`, `handoff`, `abstained`, `abandoned`, `cancelled`.
- `source = 'mock'` marks team-generated synthetic rows (see §1). `source = 'real'` rows come from conversations in `app`.
- Migration `0009` also adds the index `ix_messages_created_at` on `app.messages(created_at)`, which the worker uses to find conversations with recent activity. It also creates an index on `app.conversations(closed_at)`, from which the worker reads candidate conversations.
- Role `analytics_worker` (`LOGIN`, created only if missing; its password comes from `ANALYTICS_DB_PASSWORD`, and an empty value creates the role without a password). Grants, and nothing else: `USAGE` on schemas `app`, `audit`, `bank` and `analytics`; `SELECT` on all tables of `app`, `audit` and `bank`; `SELECT, INSERT, UPDATE, DELETE` on all tables of `analytics`; `INSERT` on `audit.llm_calls`. The worker process uses this role for everything, including the LLM ledger write for sentiment.
- `make demo-reset` wipes the `analytics` schema together with the conversations.

### Redis
Confirmation tokens (`conf:<id>`, TTL 5 min, single-use plans with a step cursor, ADR-027), idempotency keys, rate limits and turn caps (ADR-023), pub/sub channels `conv:<id>` (customer and claimed-agent streams) and `handoff:<queue>` (`handoff_created`/`handoff_updated` for the staff inbox).

## 7. Golden DB and isolation

- After `make data`: `latam_golden` is the pristine post-load database.
- `make demo-reset`: drop and recreate the app DB from `latam_golden` (`CREATE DATABASE latam_app TEMPLATE latam_golden`).
- Eval runs: each run creates `latam_eval_<run_id>` from the golden DB, runs, exports results, then drops it. Baseline and system runs start from identical state (E1).

## 8. Identity provisioning

- For all 150k customers: login = **document type + document number** + password (amended 2026-09-28, D2-A: dataset emails are not unique, while `document_number` is non-null and unique for every customer). The document number is PII: accounts, logs, traces, rate-limit keys and audit only ever hold `login_key` = HMAC-SHA256(`IDENTITY_HMAC_KEY`, `doc:<TYPE>:<NUMBER>`). Password = a deterministic random string from a seeded generator (`CREDENTIALS_SEED`, never committed), stored with a low-cost hash (PBKDF2-SHA256, low iteration count). Staff accounts (one agent per handoff queue plus one admin) are seeded by the same step with passwords from the same seed, written to a separate git-ignored export (D4-A). See `docs/specs/d2-a-login-read-tools-api.md` D1–D5.
- `data/secrets/credentials.csv` (git-ignored) and an admin-only persona lookup in the staff console.
- **Persona catalog** (`eval/personas.yaml`, ~30 curated customers), selected by query to cover: several cards, a bank-blocked card, a suspended customer, missing income, a repeat complainer, a regulator case, recent declines per code, pending/reversed transactions, expiring cards, and MX/CO/AR plus USD-card customers.
