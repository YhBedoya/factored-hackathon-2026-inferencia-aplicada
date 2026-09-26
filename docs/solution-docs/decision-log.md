# Decision log

ADR-style record of the design decisions taken collaboratively on 2026-09-26. Status: **Accepted**, **Proposed** (suggested, not yet confirmed) or **Open** (needs a decision).

---

### ADR-001 — Application stack · Accepted
**Decision:** Python 3.12 + FastAPI + SQLModel/asyncpg + Alembic + Pydantic Settings + Redis + structlog/OpenTelemetry on the backend. React 19 + TypeScript + Vite + TanStack Router/Query + React Hook Form/Zod + Radix/Tailwind v4 on the frontend. Docker Compose layers + Nginx + Makefile. Ruff, Biome, pre-commit, pytest, Vitest, Playwright.
**Why:** the team already knows these tools, and they come with a coding-agent harness (VictoriaMetrics/Logs/Traces via OTel, MCP servers, layered CLAUDE.md). The deepflow project is used **as a style guide only, and nothing is copied** (it's a proprietary repo and ours must be public).
**Alternatives:** Next.js frontend (chosen at first, then replaced by Vite SPA to match the known stack); TypeScript backend (two runtimes, since ML/eval/data need Python anyway).

### ADR-002 — Orchestration: deterministic flows + read-only answer node · Accepted
**Decision:** LangGraph turn graph. Side-effecting and regulated intents run as deterministic subgraphs, and one capped, read-only LLM answer node handles informational questions and digressions. An intent queue handles multi-intent turns.
**Why:** it matches the Rules/Hybrid feature tags, enforces the confirm → act → verify ordering, gives a resumable pending step, limits prompt injection (LLM nodes that read data have no write tools), makes the eval tractable, and produces an audit trail from node paths and rule hits instead of chain-of-thought.
**Alternatives:** a tool-calling agent with policy guards (more flexible, weaker on eval, injection and audit); pure deterministic flows (too rigid for digressions).

### ADR-003 — LLM provider: Amazon Bedrock, model per step · Accepted
**Decision:** all models are served through Amazon Bedrock, accessed only via `core/llm`. The model is chosen per step by need and cost. Starting point **(proposed, to benchmark on dev)**: small/fast Claude model (e.g., Haiku 4.5) for NLU and composer; larger model (e.g., Sonnet 5) for the answer node; a different model family for the customer simulator, paraphrase generation and the judge.

### ADR-004 — Intent classification by LLM; confidence via labels and counters · Accepted
**Decision:** a single structured-output LLM call returns language + intents + status + slots from a closed enum. "Low confidence" is expressed through explicit `ambiguous` / `out_of_scope` / `out_of_market` labels plus a clarification counter (escalate after 2 failures).
**Why:** better handling of portuñol and regional vocabulary than a small trained model. Bedrock doesn't give calibrated confidence for these models.
**Alternatives:** trained classifier as the router; self-consistency voting (3× cost); keyword second opinion.

### ADR-005 — Learned component (D4.6) · **Open**
**Context:** D4.6 requires at least one learned component evaluated against a baseline. The data check ruled out the candidates that rely on dataset labels:
- Complaint triage: `description` has 5 templates tied 1:1 to category, and `priority` is independent of every other field.
- Fraud ranking: `is_fraud` is deterministic above `fraud_score` 30 and flat noise (~4.4/10k) below it.
- Merchant retrieval: only 24 merchant names.
- Intent from transcripts: 42 distinct `customer_text` values.

**Candidates:** (a) a local fallback intent classifier (multilingual embeddings + logistic regression, trained on the team-labeled NLU set) used only when Bedrock is unavailable, evaluated keyword vs trained vs LLM; (b) a language/variety detector (es-MX/es-CO/es-AR/pt-BR/mixed) vs a langid baseline. The LLM-vs-keyword NLU comparison also counts as pretrained-component evidence.
**Needed by:** before the eval suite is frozen.

### ADR-006 — Observability: Langfuse Cloud + OTel/Victoria stack + own audit tables · Accepted
**Decision:** Langfuse Cloud for LLM generations, prompt versions, costs and eval scores (masked text only). OTel → VictoriaTraces/Logs/Metrics for infrastructure. The staff traceability console reads our own `audit` tables and links to Langfuse traces.
**Alternatives:** OTel-only (build prompt/cost/eval tracking ourselves); self-hosted Langfuse (ClickHouse + S3 + Redis is heavy).

### ADR-007 — Conversation state and transport · Accepted
**Decision:** LangGraph `AsyncPostgresSaver` (psycopg 3 pool next to asyncpg) keyed by conversation. Chat turns run inline and async, and results stream over SSE. TaskIQ is used only for batch jobs (ingest, eval runs, simulator).
**Alternatives:** Redis saver (needs Redis Stack, less durable); TaskIQ + polling (queue latency on every turn); plain request/response (no progress feedback).

### ADR-008 — Identity: mock IdP with password + OTP step-up, every customer can log in · Accepted
**Decision:** credentials generated at load for all customers (low-cost hash, git-ignored export, admin lookup) plus a curated persona catalog for the demo and the judges. JWT httpOnly cookie + CSRF. Simulated OTP only for step-up actions. A test-IdP endpoint for eval, disabled in prod.
**Alternatives:** curated personas only; persona picker (weaker auth story); OTP on every login (slower demo/eval).

### ADR-009 — Data platform · Accepted
**Decision:** **all** 13 provided tables are loaded into Postgres. Pipeline: S3 → Parquet + manifest → Pandera contracts → dbt-duckdb (staging / intermediate / serving, tests, lineage) → Postgres (DDL owned by Alembic) → golden DB. Freshness is demonstrated with labeled fixtures (late partition, schema change, duplicate batch).
**Alternatives:** a curated subset or last 12 months only; a plain Python pipeline; Polars.

### ADR-010 — Simulated "now": whole-week date shift at load · Accepted
**Decision:** `date_offset_days = 7 × floor((load_date − 2026-06-17) / 7)`, applied to every temporal column in the dbt serving layer. The data ends on deploy/load day. The real clock is used afterwards.
**Alternatives:** a frozen business clock; exact-day shift (breaks weekday patterns).

### ADR-011 — Write model: update + history, append new entities, golden DB clones · Accepted
**Decision:** the app writes into the provided tables. In-place updates (e.g., `products.product_status`) always write a history row in the same transaction, and new entities (claims) are appended with `origin='app'`. Complementary tables cover what the dataset lacks (controls, replacements, conversations, handoffs, audit, vault). Demo reset and every eval run start from `CREATE DATABASE … TEMPLATE latam_golden`.
**Alternatives:** snapshot + event overlay; append-only status table; a single DB with cleanup.

### ADR-012 — Synthetic policy as versioned YAML · Accepted
**Decision:** `policies/*.yaml` with a mandatory `provenance: team-generated-synthetic` header, Pydantic-validated at startup, with the content hash logged on every decision.
**Alternatives:** DB tables editable from an admin UI (makes eval reproducibility and policy audit harder).

### ADR-013 — PII: reversible per-conversation token vault · Accepted
**Decision:** PII is replaced by tokens before any LLM call. The Fernet-encrypted vault re-hydrates tokens server-side only in the rendered reply. Langfuse `mask` hook as a second line of defense.
**Alternatives:** irreversible redaction.

### ADR-014 — Money for Mexican (USD) cards · Accepted
**Decision:** show the record amount in its currency (USD) plus a **labeled MXN estimate** using `daily_exchange_rates` and its date. Report as a data limitation. The feature list's "MXN $1,234.50" example is superseded for MX cards.
**Alternatives:** record currency only; converting to MXN (contradicts the source record).

### ADR-015 — Handoff: live takeover · Accepted
**Decision:** the handoff sets `mode = human`. An agent claims the case in the staff console (packet + timeline) and chats with the customer live (HTTP post + SSE via Redis pub/sub). Agent one-click actions go through the policy engine. The agent can return the conversation to the bot.
**Alternatives:** agent inbox with async reply; packet only.

### ADR-016 — Evaluation design · Accepted
**Decision:** ~300 frozen held-out conversations (≈50% ES MX/CO/AR, 35% PT-BR, 15% mixed). Seeds + LLM paraphrases (different model family) + 100% human review of held-out, split by seed. Baseline = keyword router + templates using the same tools and policy, plus the call-center operational reference. Multi-turn driven by a goal-driven LLM customer simulator. Deterministic checks first, then an LLM judge for reply quality validated against ~50 human labels.

### ADR-017 — Deployment target · **Open**
**Constraints:** public URL (K2), Bedrock access through an IAM role, Postgres big enough for all 13 tables (`digital_events` ≈ 10M rows), Docker Compose prod layer. Candidates: a single EC2 instance with Compose, or ECS Fargate + RDS.

### ADR-018 — Engineering governance · Accepted
**Decision:** import-linter architecture contracts + unit tests for the safety rules, in pre-commit and CI. Short feature branches, PRs with one reviewer, squash merge, Conventional Commits. The design is kept as Markdown in `docs/solution-docs/`.

---

## Feature-list amendments from the data review

| Feature | Amendment | Reason |
|---|---|---|
| Natural-language transaction search | The example "el cargo de Oxxo…" becomes a real merchant, e.g., "el cargo de Super Ahorro del martes pasado por unos 350" | Only 24 merchant names exist, and Oxxo is not one of them |
| Localized money and dates | MX cards are shown in USD with a labeled MXN estimate | All Mexican cards are USD in the data (ADR-014) |
| Suspected-fraud triage | `fraud_score` is shown as a data field only. It is not presented as a reliable model | `is_fraud` vs `fraud_score` is circular above 30 and noise below it |
| Intent classifier vs keyword baseline (MVP · ML) | Now **MVP · LLM**. The learned component moves to ADR-005 (open) | ADR-004 |
