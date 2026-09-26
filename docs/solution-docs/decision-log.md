# Decision log

ADR-style record of the design decisions taken collaboratively on 2026-09-26. Status: **Accepted**, **Proposed** (suggested, not yet confirmed) or **Open** (needs a decision).

---

### ADR-001 — Application stack · Accepted
**Decision:** Python 3.12 + FastAPI + SQLModel/asyncpg + Alembic + Pydantic Settings + Redis + structlog/OpenTelemetry on the backend. React 19 + TypeScript + Vite + TanStack Router/Query + React Hook Form/Zod + Radix/Tailwind v4 on the frontend. Docker Compose layers + Nginx + Makefile. Ruff, Biome, pre-commit, pytest, Vitest, Playwright.
**Why:** the team already knows these tools, and they come with a coding-agent harness (VictoriaMetrics/Logs/Traces via OTel, MCP servers, layered CLAUDE.md).
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

### ADR-005 — Learned component (D4.6): pretrained LLM NLU vs keyword baseline · Accepted
**Context:** D4.6 requires at least one learned component evaluated against a baseline. The problem statement ("Architecture freedom") says training a new model is not mandatory and that pretrained solutions show ML rigor through component selection, intent labels, leakage prevention, held-out evaluation and error analysis. The data check ruled out the candidates that rely on dataset labels:
- Complaint triage: `description` has 5 templates tied 1:1 to category, and `priority` is independent of every other field.
- Fraud ranking: `is_fraud` is deterministic above `fraud_score` 30 and flat noise (~4.4/10k) below it.
- Merchant retrieval: only 24 merchant names.
- Intent from transcripts: 42 distinct `customer_text` values.

**Decision:** the learned component is the **pretrained LLM intent classifier** (the `understand` node), evaluated against the **keyword/regex router** on the frozen `eval/nlu/` held-out set: intent-set precision/recall/F1, exact-set match and status accuracy, broken down by language, with multi-intent cases as their own slice. The evidence also includes a model-selection comparison between Bedrock models, tracked runs and an error analysis.

**Keyword baseline on multi-intent messages:** split the message into clauses at connectors and punctuation (`y / e / también / además / além disso / , / ; / ?`), match each clause against the regional lexicon, keep intents in order of appearance with duplicates removed, apply precedence rules (e.g., "no reconozco" + "bloquear" → only `unrecognized_charge`) and a negation window of about 3 tokens ("no quiero bloquearla" drops `card_block`). The baseline stays a reasonable competitor. Implicit multi-intent, pronoun references and portuñol are where the LLM is expected to win.
**Alternatives:** a trained fallback classifier (embeddings + logistic regression) used when Bedrock is down; a language/variety detector vs a langid baseline. Both are optional extras if time allows.

### ADR-006 — Observability: Langfuse Cloud + OTel/Victoria stack + own audit tables · Accepted
**Decision:** Langfuse Cloud for LLM generations, prompt versions, costs and eval scores (masked text only). OTel → VictoriaTraces/Logs/Metrics for infrastructure. The staff traceability console reads our own `audit` tables and links to Langfuse traces.
**Alternatives:** OTel-only (build prompt/cost/eval tracking ourselves); self-hosted Langfuse (ClickHouse + S3 + Redis is heavy).

### ADR-007 — Conversation state and transport · Accepted
**Decision:** LangGraph `AsyncPostgresSaver` (psycopg 3 pool next to asyncpg) keyed by conversation. Chat turns run inline and async, and results stream over SSE. TaskIQ is used only for batch jobs (ingest, eval runs, simulator).
**Alternatives:** Redis saver (needs Redis Stack, less durable); TaskIQ + polling (queue latency on every turn); plain request/response (no progress feedback).

### ADR-008 — Identity: mock IdP with password + OTP step-up, every customer can log in · Accepted
**Decision:** credentials generated at load for all customers (low-cost hash, git-ignored export, admin lookup) plus a curated persona catalog for the demo and the judges. JWT httpOnly cookie + CSRF. OTP only for step-up actions. A test-IdP endpoint for eval, disabled in prod.
**Amended 2026-09-26:** the step-up OTP is a **fixed 4-digit code** read from an env var (never committed). It only marks where stronger step-up authentication would go, and a real OTP system (delivery, expiry, retries) is out of scope and listed as remaining deployment work (S6). The tool registry still enforces the step-up gate (R2). Judges receive the persona emails, passwords and the OTP code in the submission email, never in the repo.
**Alternatives:** curated personas only; persona picker (weaker auth story); OTP on every login (slower demo/eval); a simulated OTP inbox page (more to build for no extra evidence).

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
**Decision:** ~150 frozen held-out conversations (≈50% ES MX/CO/AR, 35% PT-BR, 15% mixed). Seeds + LLM paraphrases (different model family) + 100% human review of held-out, split by seed. Baseline = keyword router + templates using the same tools and policy, plus the call-center operational reference. Multi-turn driven by a goal-driven LLM customer simulator. Deterministic checks first, then an LLM judge for reply quality validated against ~50 human labels.
**Amended 2026-09-26:** sizes reduced to **~150 held-out + ~80 dev** conversations, so that two people can review 100% of held-out.

### ADR-017 — Deployment target: AWS, setup decided at the midpoint · Accepted (partially)
**Decision:** we deploy on **AWS**. The concrete setup (simple or more sophisticated) is decided at the sprint midpoint (~2026-09-30 / 10-01), once the tool's shape and the remaining time are clearer. An **AWS smoke test** runs on day 1–2: Bedrock model access and quotas in the chosen region, one IAM role, and one Bedrock call from a small instance.
**Constraints:** public URL (K2), Bedrock access through an IAM role, Postgres big enough for all 13 tables (`digital_events` ≈ 10M rows), Docker Compose prod layer. Candidates: a single EC2 instance with Compose, or ECS Fargate + RDS.

### ADR-018 — Engineering governance · Accepted
**Decision:** import-linter architecture contracts + unit tests for the safety rules, in pre-commit and CI. Short feature branches, PRs, squash merge, Conventional Commits. The design is kept as Markdown in `docs/solution-docs/`.
**Amended 2026-09-26 (2 people + coding agents):** the author may self-merge after green CI. The other person reviews safety-critical PRs (tools, policy, identity).

### ADR-019 — Scope: Core first, then if-time items in a fixed order · Accepted
**Context:** about 9 working days (submission ≈ 2026-10-05) and 2 people plus coding agents. The feature list has about 33 MVP items.
**Decision:** build and evaluate **Core** first. Take **if-time** items only after Core passes its evals, in this order.
- **Core:** mock IdP login + session expiry/resume; the safety rules R1–R12 (customer scoping, confirmation tokens, read-back, PII vault, policy YAML); `card_select`; `card_info` (status, balance, minimum payment); `card_block` (lock vs block) + `replacement`; `decline_explain` (51/14/05/54); `unrecognized_charge` → block + claim → Fraudes live takeover; out-of-market / out-of-scope abstention; ES (MX/CO/AR) + PT-BR + portuñol; the pipeline (S3 → Pandera → dbt → Postgres) + freshness fixture + golden DB; the eval (held-out + keyword baseline + simulator + metrics report); staff console (ADR-024).
- **If-time, in order:** (1) `card_unlock` with bank-side reason check, (2) natural-language `tx_search`, (3) claim priority flags → Reclamos, (4) pending / reversal explainer, (5) answer node for digressions, (6) Stretch items.
- The demo and video are **not** planned now. They show the strongest features once they're built, so build order follows Core priority, not a demo script.
**Alternatives:** the full MVP list (high risk of shallow coverage and a rushed eval); Core only.

### ADR-020 — Debit cards: card facts only · Accepted
**Context:** 39.9K of 140K cards (29%) are debit. They have no credit limit and no days past due (structural nulls).
**Decision:** for debit cards, `card_info` shows the masked number, status, expiry and recent transactions. Balance, due date and minimum payment are credit-only, and the bot says so plainly and offers what it can show. Block, lock, replacement and claims work the same for both card types.
**Alternatives:** show the linked savings/checking account balance (pulls account inquiries into scope); credit cards only.

### ADR-021 — Customer status takes precedence over card status · Accepted
**Context:** 17.5K Active cards belong to Closed, Suspended or Inactive customers.
**Decision:** if the customer is Closed, Suspended or Inactive, their cards are treated as not usable. Information stays read-only and blocking is still allowed (a safety action), but unlock and replacement are not offered, and the case goes to a handoff (Atención). The rule lives in `policies/`, and the inconsistency is reported in the data-quality analysis (D1.3).
**Alternatives:** card status wins (a suspended customer could order a replacement); blocking logins for those customers (loses the bank-side handoff case).

### ADR-022 — UI language: ES/PT toggle · Accepted
**Decision:** the UI chrome (landing, menus, buttons) defaults to the browser language and has a visible ES | PT switch backed by a small i18n dictionary. Bot replies still follow the customer's current turn language (`02` §7).
**Alternatives:** Spanish-only UI; UI that follows the detected conversation language (flickers on portuñol turns).

### ADR-023 — Cost guard for the public deployment · Accepted
**Decision:** a maximum number of turns per conversation and per account per day, a login rate limit, an AWS Budgets alarm, and an `LLM_DISABLED` kill switch that routes every turn to the safe-fallback template + handoff (which also demonstrates D6.3). Limit values are set in config.
**Alternatives:** Budgets alarm only; nothing.

### ADR-024 — Staff traceability console: Core scope · Accepted
**Decision:** the "Control and traceability of LLM" feature is, for Core: the handoff inbox with live takeover; a conversation list filterable by language, country, intent, outcome, escalation and date; and a per-turn timeline (NLU result, rule hits, tool calls and results, sources, policy hash, model and prompt version, latency, cost, Langfuse link). It never shows chain-of-thought.
**Alternatives:** also flag and annotate conversations and export them to the dev set (≈1 extra day); timeline only, with browsing in the Langfuse UI.

### ADR-025 — Auth enforcement: router-level FastAPI dependencies + session passed into the graph · Accepted
**Context:** the design said "`identity` validates the cookie" without naming the mechanism, and nothing checked that a conversation belongs to the session's customer (`conversations.customer_id`).
**Decision:** the whole chat is behind login; there is no anonymous conversation mode. Enforcement has three layers:
- **HTTP (FastAPI dependencies).** `identity/deps.py` provides `get_session()` (decodes the JWT cookie, checks CSRF on writes and `revoked_tokens`, returns `Session{account_id, role, customer_id, step_up_at}` or `401 session_expired`) and `require_role(...)` (`403` on the wrong role). Every router declares its role at router level (`APIRouter(dependencies=[Depends(require_role("customer"))])`), so a new route can't forget it. `conversation/deps.py` provides `get_owned_conversation()`, used by every `/conversations/{id}/…` route, which returns `404` unless `conversation.customer_id == session.customer_id` (404, not 403, so it doesn't reveal that the conversation exists). The test-IdP router is only mounted when the environment is `eval`.
- **Graph.** LangGraph nodes are not FastAPI routes, so `Depends` can't reach them. The route passes the validated session in the run config (`config["configurable"]["session"]`), `load_session` copies `customer_id` into read-only state, and the tool registry builds `ToolContext` from it (R1). The registry is the second gate because it's also used by agent one-click actions and eval, where there's no customer request.
- **Step-up** is not a route dependency. It's decided per tool (`requires_step_up`) in the middle of a flow, so the registry checks `session.step_up_at` and raises `StepUpRequired`.
The SSE stream runs its dependencies once, when it opens; expiry while it stays open is not re-checked. That's acceptable because the stream is read-only and ownership-scoped, and every write (`/messages`, `/confirmations`) re-checks.
**Enforced by:** R13 (`06`): a route-introspection unit test and a cross-customer integration test.
**Alternatives:** per-route `Depends` only (easy to forget on a new route); ASGI middleware that checks the cookie (no typed session object, and still no ownership check); a public anonymous mode for general questions (more surface area, and no Core feature needs it).

---

## Deferred to implementation

These are known and owned, and they're decided while building the related feature:

| Item | Decided when |
|---|---|
| Suspected-compromise rule and threshold for `unrecognized_charge` (count, possession, `fraud_score`) | Building the `unrecognized_charge` flow |
| Numeric targets for the D1.5 outcome metrics (the metrics themselves are defined in `05` §6) | After the first dev eval run, before freezing held-out |
| Model family for the customer simulator, paraphrases and LLM judge (non-Claude, to avoid self-grading bias) | Building the eval harness |
| Exact Bedrock model IDs per step | Benchmark on the dev set |
| Step-up validity window (N minutes after a successful OTP) and what happens to an open confirmation token when the session expires during it | Building identity + the first step-up flow (ADR-025) |
| Concrete AWS setup | Sprint midpoint (ADR-017) |
| Time zone semantics of `transaction_date` | Building the pipeline |
| Demo and video script | After Core is built (ADR-019) |

---

## Feature-list amendments from the data review

| Feature | Amendment | Reason |
|---|---|---|
| Natural-language transaction search | The example "el cargo de Oxxo…" becomes a real merchant, e.g., "el cargo de Super Ahorro del martes pasado por unos 350" | Only 24 merchant names exist, and Oxxo is not one of them |
| Localized money and dates | MX cards are shown in USD with a labeled MXN estimate | All Mexican cards are USD in the data (ADR-014) |
| Suspected-fraud triage | `fraud_score` is shown as a data field only. It is not presented as a reliable model | `is_fraud` vs `fraud_score` is circular above 30 and noise below it |
| Intent classifier vs keyword baseline (MVP · ML) | Now **MVP · LLM**. This pretrained LLM classifier vs the keyword baseline is the learned component (ADR-005) | ADR-004, ADR-005 |
| Unblock with reason check | A customer lock is undone only after step-up (fixed demo OTP), not just by being logged in. Moved to if-time | `02` §4.7, ADR-008, ADR-019 |
| Card status and details; balance, due date and minimum payment | Balance, due date and minimum payment apply to credit cards only | ADR-020 |
| Mock identity provider and session token | The OTP is a fixed demo code shared with judges; a real OTP system is out of scope | ADR-008 |
| Control and traceability of LLM | Core scope defined | ADR-024 |
