# 03 — Data architecture

## 1. Sources and provenance (B1, B2)

| Input | Provenance | Used for |
|---|---|---|
| S3 `data/` (13 tables, uploaded 2026-08-31) | **Synthetic**, organizer-approved | Serving DB (all tables), grounding, demand analysis, operational baseline |
| S3 `data_backup_20260831/`, root `marketing_campaigns.csv` | Synthetic, older partial copies | **Not used**. Documented as excluded |
| `policies/*.yaml` | **Team-generated synthetic** policy | Decline codes, min payment, limits, dispute questions, escalation thresholds |
| `eval/scenarios/**` | **Team-generated** (seeds + LLM paraphrases, human-reviewed) | Evaluation and dev tuning |
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
         ──(4) load: DuckDB postgres extension → COPY into bank.* (DDL owned by Alembic)
         ──(5) provision identity: credentials for all customers → identity.accounts; export to data/secrets/credentials.csv (git-ignored)
         ──(6) snapshot: golden database `latam_golden` (CREATE DATABASE … TEMPLATE)
```

- **Orchestration:** `make data` runs steps 1–6. Each step is idempotent and keyed by a `run_id`. dbt `docs generate` produces the **lineage graph** (D4.4). Artifacts are kept under `data/lineage/`.
- **Determinism (D4.1):** given the same manifest and `load_date`, the output is identical. Fixed seeds are used for credential generation.

## 3. Contracts and quality (D4.2, D4.3)

- Contracts are defined from the **observed** schema, with deviations from the dictionary documented: Spanish enum values ("Tarjeta Crédito", "Transaccional"…), missing transcript columns (`full_text`, `agent_text`), row counts 84–156% of documented.
- Pandera checks per raw partition: column presence and types, nullability, enum domains, ranges (`fraud_score` 0–100, `credit_score` 300–850), PK uniqueness.
- dbt tests on staging and serving: PK uniqueness, FK relationships (orphans are counted and flagged, never silently dropped), accepted values, semantic checks from the EDA (transactions before card opening or after expiry, future `last_updated`, the `process_date` UTC/local shift).
- D1.3 finding: `process_date` follows UTC−6 in all three countries (MX, CO, AR); rows stamped 00:00–05:59 carry the previous day (D1-A D1).
- Output: a quality report per run (counts, rates, failing rows sample) that feeds the D1.3 analysis.

## 4. Freshness and update policy (D4.5)

- The delivery is a single static snapshot. The **policy**: ingest is incremental by daily partition. A partition is (re)processed when its manifest entry (size/ETag) changes. Serving tables are rebuilt with dbt incremental models on `process_date`.
- **Labeled test fixtures** (`pipeline/fixtures/`, clearly marked TEST FIXTURE):
  1. A late-arriving partition for an already-processed day, with corrected rows.
  2. A schema-evolved partition with an added column and a renamed column.
  3. A duplicate batch, re-delivering an already-loaded partition.
  Expected results are asserted in `pipeline/tests/` (idempotent row counts, the new column mapped, dups rejected).

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

Indexes **(proposed)**: `products(customer_id, product_type)`, `transactions(customer_id, product_id, transaction_date desc)`, `transactions(product_id, transaction_status, transaction_date desc)`, `complaints(customer_id, creation_date desc)`.

### `app`: complementary operational tables
| Table | Purpose |
|---|---|
| `card_status_history` | (migration `0003`, D3-A3) `id, product_id, old_status, new_status, reason, actor (customer/agent/system), conversation_id, trace_id, at, idempotency_key` (unique nullable, D3-A D11); index `(product_id, at desc)` |
| `card_controls` | (migration `0003`) Temporary lock: `product_id` (pk), `locked, locked_by, locked_at, updated_at, idempotency_key` (unique nullable). Channel toggles and spending limits are Stretch, not yet columns |
| `card_replacements` | (migration `0003`) Order: `id, product_id, address_ref` (PII-vault token, never a raw address), `address_changed, tracking_id` (unique, `RPL-` + 8 hex upper), `status, conversation_id, created_at, idempotency_key` (unique nullable). No address snapshot until D5-A1 encrypts one |
| `travel_notices` | Stretch |
| `conversations` | `id, customer_id, channel, language, mode (bot/human), status, started_at, closed_at` |
| `messages` | `conversation_id, role (customer/bot/agent/system), content (unmasked, encrypted), content_masked, ui_payload, created_at` |
| `handoffs` | (`app.handoffs`, migration `0005`) `id, conversation_id` (fk), `queue, reason, priority, packet jsonb, status` (`queued`/`claimed`/`returned`, default `queued`), `agent_id` (fk `identity.accounts`, null), `created_at, claimed_at, returned_at`; index `(status, queue, created_at desc)` and a partial unique index on `conversation_id WHERE status IN ('queued','claimed')`: one open handoff per conversation |
| `pii_vault` | Per-conversation token map (Fernet-encrypted), `expires_at` |
| `system_metadata` | `load_date`, `date_offset_days`, dataset manifest hash, policy hash |

### `identity`
`accounts` (`customer_id`, `login_key` = HMAC of the login identifier (never the plain document number), password hash, role, status), `revoked_tokens`. Staff accounts (D4-A, ADR-008 amended): role `agent` or `admin`, a unique `username`, `display_name`, `staff_queue`, and `customer_id` null (migration `0005` makes it nullable and adds `CHECK (role IN ('customer','agent','admin'))` and `CHECK ((role = 'customer') = (customer_id IS NOT NULL))`; staff `login_key` = HMAC of `staff:<username>`); names are Laura (atencion), Diego (cobranza), Sofía (fraudes), Mateo (reclamos) and "Swip Admin"; one agent per handoff queue plus one admin, seeded by `make seed-identity`. There is no OTP storage: the step-up OTP is a fixed demo code (ADR-008), and the time of the last successful step-up is kept in the session.

### `audit`
`audit_events` (migration `0004`, D3-A5, append-only, no update or delete path: `id, at, conversation_id, turn_id, actor, type, payload jsonb, sources jsonb, policy_version, model jsonb, trace_id, langfuse_trace_id`; index `(conversation_id, at)`; see `04-contracts.md` §6 for the full shape), `llm_calls` (`step, model_id, prompt_version, input/output tokens, cost_usd, latency_ms, langfuse_trace_id, status`).

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
