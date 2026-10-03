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
**Amended by ADR-035:** a flagged tool-calling agent proposes plans and the pipeline keeps executing them.

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

### ADR-006 — Observability: self-hosted Langfuse + OTel/Victoria stack + own audit tables · Accepted (amended 2026-09-26)
**Decision:** Langfuse for LLM generations, prompt versions, costs and eval scores (masked text only), **self-hosted with Docker on localhost** (the Langfuse compose services in our observability layer), not Langfuse Cloud. OTel → VictoriaTraces/Logs/Metrics for infrastructure. The staff traceability console reads our own `audit` tables and links to Langfuse traces.
**Amendment:** Langfuse is **not required to start**. Until it runs, the `core/llm` tracing hook is a no-op when no Langfuse host is configured, and the `audit.llm_calls` ledger is the record of every call. Whether the public deployment also runs Langfuse is **Open**, decided with the AWS setup (ADR-017). Without it, the console's Langfuse link only works locally.
**Decided 2026-09-28 (ADR-017):** the public deployment does **not** run Langfuse. Langfuse's own guidance is at least 4 cores and 16 GiB for Langfuse alone (ClickHouse 8 GiB, web and worker 4 GiB each), which doesn't fit next to our stack on the t3.xlarge. `audit.llm_calls` is the public record, and Langfuse stays local. See `08` §1.
**Alternatives:** Langfuse Cloud (the original choice; replaced to keep traces local); OTel-only (build prompt/cost/eval tracking ourselves).

### ADR-007 — Conversation state and transport · Accepted
**Decision:** LangGraph `AsyncPostgresSaver` (psycopg 3 pool next to asyncpg) keyed by conversation. Chat turns run inline and async, and results stream over SSE. TaskIQ is used only for batch jobs (ingest, eval runs, simulator).
**Alternatives:** Redis saver (needs Redis Stack, less durable); TaskIQ + polling (queue latency on every turn); plain request/response (no progress feedback).

### ADR-008 — Identity: mock IdP with password + OTP step-up, every customer can log in · Accepted
**Decision:** credentials generated at load for all customers (low-cost hash, git-ignored export, admin lookup) plus a curated persona catalog for the demo and the judges. JWT httpOnly cookie + CSRF. OTP only for step-up actions. A test-IdP endpoint for eval, disabled in prod.
**Amended 2026-09-26:** the step-up OTP is a **fixed 4-digit code** read from an env var (never committed). It only marks where stronger step-up authentication would go, and a real OTP system (delivery, expiry, retries) is out of scope and listed as remaining deployment work (S6). The tool registry still enforces the step-up gate (R2). Judges receive the persona emails, passwords and the OTP code in the submission email, never in the repo.
**Amended 2026-09-28 (D2-A):** customers log in with **document type + document number** + password, not email: dataset emails are shared by many customers (91,289 distinct over 147,016 non-null), while `document_number` is unique for all 150k. The document number is treated as PII (HMAC `login_key` in accounts, logs and rate-limit keys). There is no staff login for now: the staff panel is a separate page, and its protection is decided on the staff-panel card (D4). Judges receive persona documents and passwords in the submission email instead of emails.
**Amended 2026-09-28 (D4-A):** the staff panel is protected by **seeded staff accounts**. `identity.accounts` gains the roles `agent` and `admin` and a `username`, and `customer_id` becomes nullable (migration `0005`). One agent per handoff queue plus one admin are seeded with deterministic passwords from `CREDENTIALS_SEED`, written to the git-ignored credentials export. `POST /auth/staff/login {username, password}` issues the same httpOnly cookie + CSRF session with the staff role, and the `/staff/*` and `/admin/*` routers declare `require_role(...)` (R13). A staff session has no `customer_id` and can never build a `ToolContext` (R1). Judges receive the staff credentials in the submission email with the persona ones. See `docs/specs/d4-a-escalation-handoff-deploy.md`. This supersedes the one-shared-agent account D4-B proposed in parallel (`docs/specs/d4-b-disputes-handoff-screens.md` D3); D4-B keeps its rule that `/auth/refresh` answers a staff session with `403 forbidden_role`.
**Alternatives:** curated personas only; persona picker (weaker auth story); OTP on every login (slower demo/eval); a simulated OTP inbox page (more to build for no extra evidence).

### ADR-009 — Data platform · Accepted
**Decision:** **all** 13 provided tables are loaded into Postgres. Pipeline: S3 → Parquet + manifest → Pandera contracts → dbt-duckdb (staging / intermediate / serving, tests, lineage) → Postgres (DDL owned by Alembic) → golden DB. Freshness is demonstrated with labeled fixtures (late partition, schema change, duplicate batch).
**Alternatives:** a curated subset or last 12 months only; a plain Python pipeline; Polars.

### ADR-010 — Simulated "now": whole-week date shift at load · Accepted
**Decision:** `date_offset_days = 7 × floor((load_date − 2026-06-17) / 7)`, applied to every temporal column in the dbt serving layer. The data ends on deploy/load day. The real clock is used afterwards.
**Alternatives:** a frozen business clock; exact-day shift (breaks weekday patterns).
**Amendment (D1-A D1):** time zone semantics of `transaction_date` are decided: every TIMESTAMP column in `bank.*` is interpreted as UTC and stored as `timestamptz`; local display and relative-date resolution use `BANK_TZ` per country (MX `America/Mexico_City`, CO `America/Bogota`, AR `America/Argentina/Buenos_Aires`).

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

### ADR-017 — Deployment target: AWS, single EC2 + Compose · Accepted (setup decided 2026-09-28)
**Decision:** we deploy on **AWS**. The concrete setup (simple or more sophisticated) is decided at the sprint midpoint (~2026-09-30 / 10-01), once the tool's shape and the remaining time are clearer. An **AWS smoke test** runs on day 1–2: Bedrock model access and quotas in the chosen region, one IAM role, and one Bedrock call from a small instance.
**Constraints:** public URL (K2), Bedrock access through an IAM role, Postgres big enough for all 13 tables (`digital_events` ≈ 10M rows), Docker Compose prod layer. Candidates: a single EC2 instance with Compose, or ECS Fargate + RDS.
**Decided 2026-09-28:** **one EC2 t3.xlarge in us-east-1 running the prod Compose layer** (layered base → observability → prod, so prod's `!override` ports win), with an IAM instance role for S3 and Bedrock, SSM Session Manager instead of SSH, secrets in SSM Parameter Store, and a `<ip>.sslip.io` hostname with a Let's Encrypt certificate (a Route 53 domain as the fallback if sslip.io's shared rate limit is exhausted). The organizers' `data/` prefix is copied once into **our own S3 bucket** in us-east-1, and the golden DB is built **on the box** with `make data`, so the date shift lands on the deploy date. Full design, runbook and cost: [`08-deployment.md`](08-deployment.md).
**Why:** measured footprint (prod services ≈ 1.1 GiB RAM, 15.5 GB of Postgres data); the same Compose artifact as dev and the README (D6.4); demo-reset (`CREATE DATABASE … TEMPLATE`, `DROP … WITH (FORCE)`) and the Victoria stack work unchanged; ≈ $131/month against ≈ $135–150 for ECS Fargate + RDS + ElastiCache; it fits in one D4 task. The rubric judges "it works" first and does not expect a live banking service, and ECS + RDS is documented as the path to production (S6).
**Alternatives:** ECS Fargate (Express Mode) + RDS + ElastiCache (a second deploy path, the RDS master user is not a true superuser for demo-reset, 1–2 days of setup); EC2 + RDS hybrid (B's demo-reset and restore risks without B's HA); App Runner (closed to new customers since 2026-04-30); Lightsail (no instance profiles, so Bedrock would need static keys); restoring a golden `pg_dump` instead of building on the box (fast, but freezes the date offset at dump time); a t3.large (8 GiB, no headroom for `make data` on the box).
**Amended 2026-10-03:** the deployment moves to the team's AWS project (the "new AWS experience", profile `swip-hackathon`). That project allows Regional resources **only in us-east-2** and is on the **Free plan** (USD 100 in credits), which allows only small EC2 types. So the box is an **m7i-flex.large (2 vCPU, 8 GiB) in us-east-2**, and the data bucket, SSM parameters and Bedrock calls (through the `us.` inference profiles) are in us-east-2 too. The 8 GiB objection above no longer holds: the pipeline already caps DuckDB at 3 GB and `make data` runs with only Postgres and Redis up. Cost drops to ≈ $80/month (≈ 5 weeks of the credits), and the budget alarm moves to $90 (above the forecast so the forecast alert means real overspend, and the 80% actual alert fires at $72, before the credits run out). Everything else in the decision stands. `DEPLOY_REGION`, `INSTANCE_TYPE` and `MONTHLY_BUDGET_USD` in the Makefile bring back the original setup on a paid account. See `08` §1.

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

### ADR-020 — Debit cards: card facts only · Superseded by ADR-034
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
**Amended 2026-09-28 (D2-A, D24):** `get_owned_conversation()` lives in the API layer (`app/api/v1/conversations.py`), not in `conversation/deps.py`. `identity.deps` → `identity.service` statically reaches `identity.repository`/`customers.repository`, so conversation-domain code importing it would break the import-linter contract that keeps `conversation` away from repositories. Conversation-domain code never imports `identity.deps` or `identity.service`. The test-IdP router is added with `include_router` under `/api/v1` only when `APP_ENV=eval`.
**Enforced by:** R13 (`06`): a route-introspection unit test and a cross-customer integration test.
**Alternatives:** per-route `Depends` only (easy to forget on a new route); ASGI middleware that checks the cookie (no typed session object, and still no ownership check); a public anonymous mode for general questions (more surface area, and no Core feature needs it).

### ADR-026 — Structured abstain replies · Accepted
**Context:** out-of-scope and out-of-market questions, and every `general_question` until the answer node exists (if-time 5), got "I can help with: …". That is the most robotic moment in the conversation.
**Decision:** every abstain reply has four parts. Code assembles them as facts and `compose` phrases them:
1. **Acknowledge** what was asked, using the NLU `topic` label ("Entiendo que quieres saber sobre un préstamo").
2. **Say why** this chat can't do it (this chat handles cards; the bank doesn't operate Pix or boleto in MX, CO or AR), from a `reason_key`.
3. **Offer the closest supported action** when one exists, as a one-tap suggestion (e.g. a failed payment → `decline_explain`).
4. **Offer a human.** It's an offer, not an automatic handoff. After two abstains in a row it becomes a button **(proposed)**.

The NLU gets a new slot `topic`, a closed enum from `policies/scope.yaml`. That file replaces `out_of_market.yaml`, covers both `out_of_scope` and `out_of_market` topics, and maps each topic to `{kind, reason_key, closest_intents[], human_queue}`. The composer may only use those keys. It never names channels, phone numbers or products that aren't in the YAML, and the grounding check applies. An abstain during a pending flow keeps `pending` and restates the pending question, the same as a digression. The answer node stays at if-time 5. Once it exists, `general_question` goes to it, and structured abstain remains for `out_of_scope` and `out_of_market`.
**Alternatives:** a plain list of topics (the previous design); moving a minimal answer node up to if-time 1 (more natural sooner, but it adds tool-calling LLM work ahead of the other if-time items); a free LLM reply to out-of-scope questions (risks invented banking information).
**Amendment (naturalidad-cardy):** `policies/scope.yaml` entries gain an optional `offer_human` field (default true). The `new_card` topic (a request for a new card, which is not a replacement) sets it to false: its reply is a fixed template that skips `compose`, offers no human and shows no human chip, because neither the chat nor a person can issue a new card. Every other topic keeps the four-part reply.

### ADR-027 — Plan confirmation: one confirmation for a multi-step action · Accepted
**Context:** the suspected-compromise path asked for a confirmation per write (block, then claim), which felt bureaucratic at a stressful moment.
**Decision:** every confirmation token is a **plan**: an ordered list of steps. A single action is a plan of one, so there's only one token format. When a flow needs several side-effecting steps back to back, the policy domain issues **one** token for all of them:
- Redis `conf:<id>` = `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor, expires_at}`, TTL 5 minutes.
- `ui.confirm` lists every step in plain language ("Bloquear tu crédito •••• 6475 · Abrir un reclamo por 3 compras"). One "sí" or button tap authorizes exactly those steps, in that order.
- The executor checks each call against the step at `cursor` (same tool, same args hash, same session customer) and advances the cursor atomically (Lua script). The key is deleted after the last step, on the first failure, or at TTL.
- Every step keeps its own read-back. Execution stops at the first failed or unverified step and hands off (`action_unverified`), listing which steps were applied and verified. There is no automatic rollback, because a block is a safety action.
- All arguments must be known when the plan is issued. If any step needs step-up, the step-up happens before the plan is shown. `handoff.create` is internal and never a plan step.

First user: `unrecognized_charge` with suspected compromise, where the plan is `[cards.block_card, disputes.create_claim]` followed by the handoff to Fraudes. Other flows keep one-step plans unless they chain writes the same way.
**Alternatives:** one token per write (the previous design; safest but repetitive); a blanket consent for the rest of the session (too broad, weakens R2); confirming only the first step (the later writes would be unconfirmed).

### ADR-028 — LLM provider during the build: Anthropic API first, then Bedrock · Accepted
**Context:** Bedrock access (region, model enablement, AWS profiles, quotas) takes time to set up, and Dev B needs a real LLM from D1 to build the agent.
**Decision:** while Bedrock is being configured, Dev B calls Claude models through the **Anthropic API** with a personal API key (`ANTHROPIC_API_KEY` in the git-ignored `.env`, never in the repo). The connection then **migrates to Amazon Bedrock**, which stays the target for the deployed system (ADR-017). `core/llm` hides the provider behind one setting (`LLM_PROVIDER=anthropic|bedrock`, **proposed** name), and its model registry maps each step to a model ID per provider. Graph nodes, prompts and tests don't change when the provider switches. All the rules still apply to both providers: masked text only (R5), pinned model and prompt version (R7), `core/llm` as the only place that imports an LLM SDK (`06` §2).
**When to switch (proposed):** as soon as the Bedrock kickoff check (K2 in `07`) passes, and before the D4 deploy at the latest, since the deploy's IAM role is for Bedrock. The non-Claude model family for paraphrases, the simulator and the judge comes from Bedrock, so Bedrock must work by D5.
**Alternatives:** wait for Bedrock before any LLM work (blocks B on D1); build only on the Anthropic API (the deployment plan and the model comparison assume Bedrock).

### ADR-029 — Brand: Cardy, from Swip · Accepted
**Context:** the prompt, templates, UI, handoff and pitch had no shared voice, and the product was only "the synthetic LATAM Bank".
**Decision:** the product is **Swip**, a fictional card fintech built on the LATAM Bank dataset. Its assistant is **Cardy**, grammatically feminine in ES and PT. The full identity lives in [`../brand.md`](../brand.md). The voice enters in three places: the persona block of `compose@v2`, the fixed ES/PT templates in `conversation/templates.py` (greeting, tool error, clarification exhausted, and the not-yet-wired confirmation, verified result, handoff and session-expired texts), and later the UI dictionaries (B1). Personality never changes permissions: if the prompt and the policy clash, the policy wins. The alert color is `#FF6B6B` (7.1:1 on `#070B1A`). The promise and the tagline stay proposals. The PT texts are pending native review. Cardy addresses the customer by the registered `first_name` (the full name, including compound names): it is stored in the graph state as `customer_name`, used in the greeting template, and offered to `compose` only as the `{customer_name}` key, which code fills in (R5).
**Alternatives:** keep the dataset name as the brand (no personality for the pitch); let the LLM write critical messages in the persona's voice (could report actions that didn't happen).

### ADR-030 — Paraphrase model: OpenAI `gpt-6-luna` via `langchain-openai` · Accepted
**Context:** the eval harness needs regional-variant paraphrases (voseo es-AR, CO/MX lexicon, PT-BR, portuñol) for the D5-B dev and held-out scenario sets, and reusing a served Claude model would risk the same self-grading bias already flagged for the simulator and judge.
**Decision:** `app/core/llm` gains a third provider, `openai`, used **only** by a new `paraphrase` step and called through `langchain-openai`'s `ChatOpenAI`. It is pinned like every other step (model ID `gpt-6-luna`, prompt `paraphrase@v1`, temperature pinned per below) and follows the same R5/R7 rules: the key (`OPENAI_API_KEY`) lives only in `LLMSettings`, no module outside `app.core.llm` imports `openai`/`langchain_openai` (`.importlinter`), and the caller (`backend/scripts/paraphrase_seeds.py`) sends only individual `say`-turn text, never a whole seed file, persona data or DB rows. This step is eval-only tooling: it never runs inside the served conversation graph and never sees real customer data.
**Alternatives:** Bedrock Nova or Llama (avoids a third SDK, but Bedrock model access wasn't confirmed at build time — ADR-028's plan — and a paraphrase script has no served-latency reason to wait on it); reusing ADR-028's Anthropic-then-Bedrock plan for this step too (keeps the SDK surface to two providers, but self-grades paraphrase variety against the same model family the flows, and eventually the judge, use).
**Temperature note (T10):** `paraphrase` runs at temperature 1.0, not 0 like every other step, because `gpt-6-luna` rejects any non-default value ("Only the default (1) value is supported"); variety still comes from the request (N distinct items per call), not from sampling.

**Simulator note (D6-B):** the goal-driven customer simulator (`05` §5) is a second `eval`-only step on the same provider, `simulate` (`eval/simulator/simulator.py`, prompt `simulate@v1`), also called only through `get_llm_client()`. Like `paraphrase`, it runs at temperature 1.0 for the same reason (`gpt-6-luna` rejects any other value), even though the card and `05` §5 call for temperature 0; a run with `DRIVER=simulator` carries a report caveat that its transcripts aren't repeatable run to run. Bot text is masked with the persona's known PII before it reaches the prompt, and enters it only inside data fences (R5, R6). The OTP step-up value always comes from the harness's `otp_code`, never from the model (R2). `simulate` never runs inside the served conversation graph and never sees real customer data, the same boundary as `paraphrase`.

### ADR-031 — NLU model: Sonnet 5.5 · Accepted (2026-09-29)
**Context:** the `07` D1 row started with Haiku 4.5 for intent detection and replies. Intent detection drives routing and slots, so it gets the stronger model.
**Decision:** the `nlu` step is pinned to `claude-sonnet-5-5` ($2/$10 per MTok); Bedrock uses `us.anthropic.claude-sonnet-5-5-v1:0`, unconfirmed until K2. `compose` and `handoff_summary` stay on Haiku 4.5. The eval baseline comparison (proposed vs keyword baseline) uses this NLU model.
**Temperature note (T32):** `claude-sonnet-5-5` rejects `temperature` ("deprecated for this model"), so the `nlu` step sends none and uses the model default; the ledger records NULL. This makes the NLU slightly less repeatable from run to run, and eval reports carry that caveat.
**Structured output note (T31):** `claude-sonnet-5-5` also rejects forced `tool_choice` (`any`/`tool`), so on the `anthropic` provider every step uses `with_structured_output(..., method="json_schema")` (API structured outputs, supported on Sonnet 5.5 and Haiku 4.5). `bedrock` keeps function calling until K2 confirms.

### ADR-032 — Trained intent classifier and LLM-free degraded mode · Accepted (2026-10-01)
**Context:** ADR-023's kill switch and R11's last step sent every LLM failure straight to the safe-fallback handoff, so an LLM outage ended every conversation, including the ones the keyword baseline could serve. The judge checklist D6.3 asks for a defined degraded mode, not only a handoff.
**Decision:**
- **Second learned component.** A small trained intent classifier (TF-IDF character n-grams plus logistic regression in scikit-learn, selected by grouped cross-validation; the embedding models were candidates and are not in the served bundle) sits next to ADR-005's keyword baseline, which is unchanged. It is never used while the LLM is up.
- **Degraded role (amends ADR-023, R11, `02` §5, `01` §7).** An `LLMError` after the 2 retries, or `LLM_DISABLED`, moves the rest of the turn onto the no-LLM path: the classifier replaces `understand`, and `baseline_compose`, `baseline_abstain` and `baseline_handoff_summary` replace the LLM nodes. Under `LLM_DISABLED` this makes zero LLM calls, so ADR-023's cost purpose holds. A turn hands off (`llm_unavailable`) only when no classifier is loaded, when the intent is in `degraded_handoff_intents` (`policies/escalation.yaml`), or after two ambiguous turns in a row. Recovery is per turn. No customer notice; the trace carries `degraded: true`.
- **Registry.** `conversation/intents.yaml` is the single intent registry. The graph's routing tables and the classifier's label set are read from it. The `Intent` Literal and the `nlu@v4` intent list are checked against it by a unit test and not edited.
- **Artifact delivery.** The bundle is a local, git-ignored tarball in `ml/intent/models/`, pinned by sha256 in the committed `ml/intent/model.lock`. The loader refuses to load on a missing bundle, a sha256 mismatch or a `label_set_version` mismatch, and the app still starts. No model file is committed and no network call happens at startup. S3 storage (publish, fetch, `INTENT_MODEL_S3_URI`) is deferred to the deploy, when a bucket exists.
- **`intent_gen` step.** Training data is generated through `app.core.llm` by a new eval-only step `intent_gen` (provider `openai`, `gpt-6-luna`, temperature 1.0, prompts `intent_gen@v1`–`v3`), audited by a human. This extends ADR-030's eval-only list (`paraphrase`, `simulate`). It never runs in the served graph.
**Alternatives:** keep the safe-fallback handoff only (simple, but D6.3 shows only a handoff); serve the keyword baseline as the degraded NLU (no training, but its F1 on the smoke set is 0.635, ADR-031's table); fetch the model from S3 at startup (needs credentials and a bucket the project doesn't have yet).

### ADR-033 — Interaction analytics: fact tables, worker and admin dashboard · Accepted (2026-10-02)
**Context:** The staff console shows one conversation at a time (ADR-024). Nothing answers questions across conversations: resolution rate, escalation rate, cost per interaction, customer sentiment, intent volume. Messages, handoffs, intents and LLM cost are already captured in `app.*` and `audit.*`; sentiment is not, outcomes exist only per conversation, and conversations almost never close. Requirements: `docs/requirements/interaction-analytics-pipeline.md` and `interaction-analytics-dashboard.md`.
**Decision:**
- **Grain.** One row per finished interaction (a conversation) in `analytics.interactions`, and one row per intent occurrence in `analytics.interaction_intents`. No message text and no customer identifier in either.
- **Per-intent outcome.** `reply_sent`'s payload gains `segments: [{intent, route, status}]`, written by code where the graph pops the intent queue. Extends `04` §6; no migration. `status` is `resolved`, `awaiting`, `handoff`, `abstained` or `cancelled`, and an `awaiting` segment also carries `awaiting_slot`. An intent occurrence's outcome is its last status: `resolved`, `handoff`, `abstained`, `cancelled` (the customer declined a write at the confirmation), or `abandoned` (the last status was `awaiting`). Clarification is a flag on the occurrence, not an outcome. Other endings map by kind: a grounded "nothing to do / nothing found" answer is `resolved`, something Cardy cannot serve is `abstained`, a declined offer is `cancelled`. A turn routed straight to a handoff writes a `handoff` segment for each real intent in its NLU result.
- **Abstained.** An interaction is abstained when an intent ended `abstained` or any turn's route was `abstain`. A turn with no real intent writes no segment.
- **End of interaction.** Derived in analytics; chat behaviour is unchanged. Finished means the customer closed it, or 30 minutes passed with no message and no open handoff. A queued or claimed handoff keeps it in progress. `close_conversation` also writes `closed_at`.
- **Resolution is strict.** An interaction is resolved when every real intent ended resolved and there was no handoff. A write counts only after its verified read-back, or when the card was already in the requested state and no write was needed. An intent the bot offered (the replacement offer after a permanent block, or after an unlock request on a permanently blocked card, which itself ends abstained) is marked `bot_offered` on its segment and its stored row; when the customer declines it, it is not a real intent and does not count against resolution; in every other outcome, including a customer who goes silent on the offer, it counts like any other intent. Interactions with no real intent are left out of the rate.
- **Escalation cause groups** (by design, customer choice, bot failure, security) are a constant in the analytics domain. They are a reporting label, not policy, so they are not in `policies/`.
- **Sentiment.** One call per finished interaction through a new `sentiment` step (Haiku 4.5), on masked customer messages only, returning an overall, a start and an end label. Its cost is stored apart from the interaction's cost. Code calls a `SentimentScorer` interface and each row stores model id and prompt version, so the model or provider can change and old rows can be re-scored.
- **Storage and compute.** A new Postgres schema `analytics`, owned by Alembic, filled in Python by a separate `analytics-worker` Compose service (backend image) that runs every 2 minutes on the same EC2 instance, with a 512 MiB memory limit and a pool of 3 connections. It connects with its own Postgres role, created in the migration: read-only on `app`, `audit` and `bank`, read-write on `analytics`, and `INSERT` on `audit.llm_calls` only, so the sentiment call is recorded. The role's password comes from `ANALYTICS_DB_PASSWORD`; when it is empty the role cannot log in. Candidates come from a watermark row plus indexes on `app.messages(created_at)`, `app.handoffs` (`created_at`, `claimed_at`, `returned_at`) and `app.conversations(closed_at)`. Upserts are keyed by conversation id. The dashboard reads only this schema.
- **Dashboard.** A page `/staff/analytics` in the staff console, admin only (ADR-025 pattern), fed by one endpoint `GET /api/v1/staff/analytics/summary`. Charts use Recharts through shadcn.
- **Mock data.** The worker seeds simulated interactions daily, with a 30-day backfill, deterministic per date, into the same tables with `source = 'mock'`. The page shows a badge and a real/simulated switch (B2). The profile is one file marked `provenance: team-generated-synthetic`. Seeding makes no LLM call and is off by default.
**Alternatives:** per-turn or per-message grain (more rows, and every metric asked for is per interaction or per intent); closing idle conversations in the product (changes chat behaviour for a reporting need); a lexicon or trained sentiment model (no LLM cost, but weaker on four language variants and nothing to train on); SQL views or dbt over live tables (no stored sentiment, and every dashboard load scans raw tables); the job inside the API process (competes with the chat); Superset or Metabase in a container (a second login and about 1–2 GiB of RAM for one page); a public Grafana dashboard (Grafana stays private, `08`); a separate mock table (two code paths in the dashboard).
**Growth path, not built:** daily rollup tables, monthly partitions, a read replica, a columnar export.

### ADR-034 — Debit cards show their available balance · Accepted (2026-10-01)
**Context:** the new banking home ("Swip Panel" design) shows every card with its balance, and customers ask Cardy how much money is in their debit card. `bank.products.current_balance` is filled for debit cards too, and `cards.get_card_details` already returns it.
**Decision:** supersedes ADR-020 for the balance. A debit card's `current_balance` is shown as its **available balance**, both in `GET /me/cards/{id}` (`current_balance`/`current_balance_display`) and in the chat: `balance_due` on a debit card answers with the `debit_balance` compose goal (fact `available_balance`, formatted in code, R4) instead of the fixed `credit_only` text. Credit limit, available credit, due date, minimum payment and days past due stay credit-only.
**Alternatives:** keep ADR-020 (the home would show an empty balance for 29% of cards); show the linked savings account balance (pulls account inquiries into scope).

### ADR-035 — Tool-calling agent for conversation and reads, behind a flag · Accepted (2026-10-03)
**Context:** ADR-002 keeps every turn on deterministic flows and a read-only answer node. Card S1 of the Cardy agent requirement (`docs/requirements/cardy-agent.md`) adds a tool-calling agent for conversation and reads, and for proposing a lock or block. Spec: `docs/specs/cardy-agent-s1-conversation-reads-block.md`.
**Decision:** amends ADR-002. With `AGENT_ENABLED` on, one `agent` step (`claude-sonnet-5-5`, at most 6 tool rounds per turn) takes the turn first. The deterministic pipeline stays, as the path for flows not yet migrated and for degraded turns. With the flag off the graph behaves as before.
- **Passing a turn (spec D7).** The agent calls `pass_to_flow`. Code discards the loop's work and runs the unchanged pipeline on the same message in the same turn. A message that mixes a migrated and a non-migrated request passes whole. While a pipeline flow's question is open, every later turn skips the agent. *Why:* a half-migrated message would otherwise split one request across two paths, and an open flow question must be answered by the flow that asked it.
- **Propose, never execute (D8).** The agent's only write capability is `propose_plan`, and its steps name card references from the turn's tool results, never a card id from the chat. Code validates and issues the plan, and the token never reaches the agent. *Why:* R1, R2 and R6 hold only if a node that reads tool output can't execute a write or see a token.
- **Button only (D12).** An agent plan is confirmed only by the card's buttons ("Acepto / No acepto"). No typed text confirms it, including on a degraded turn. Pipeline plans keep "Confirmar / Cancelar" and a typed "sí". *Why:* a free-text "sí" is the one signal the model's own reading could misjudge, and a button click is unambiguous.
- **Round cap (D3).** When the loop uses its 6 rounds, code cancels any open plan and hands off with the new reason `agent_round_cap`, which shows the existing `handoff_transfer` text. *Why:* a bounded loop (R11) must end in a safe fallback and a handoff, never an invented answer.
**Alternatives:** keep ADR-002 unchanged (no free conversation across flows); let the agent hold the write tools behind a confirmation prompt (breaks R6); confirm by typed text on the agent path (ambiguous); retry past the cap (unbounded).

### D3-A D4 — Step-up validity window · Resolved
**Decision:** `policies/tools.yaml`'s `step_up_window_minutes: 5` sets `SessionStepUpGate`'s window (valid when `now - session.step_up_at <= window`). An open confirmation plan is not tied to the session: it dies at its own 5-minute Redis TTL (ADR-027) regardless of session state, and `POST /conversations/{id}/confirmations/{token_id}` returns `401` once the session itself has expired, before the plan is even looked at.
**Why:** resolves the "Step-up validity window" item below, decided while building the D3-A step-up flow (ADR-025) as planned. See spec `docs/specs/d3-a-guardrails-write-path.md` D4.

### D4-B D8 — Suspected-compromise rule for `unrecognized_charge` · Resolved
**Decision:** a pick is a suspected compromise when ≥ 2 transactions are picked, or any picked `fraud_score` > 30, or the customer answers "no" to the possession question. That question is asked right after the pick, and only if count and score haven't already triggered. Both thresholds live in `policies/disputes.yaml`. A compromise runs one ADR-027 plan (`block_card` then `create_claim`) and hands off to Fraudes. A refused block writes nothing, offers the claim alone, and still hands off to Fraudes.
**Why:** resolves the deferred item "Suspected-compromise rule and threshold", decided while building the flow as planned. `fraud_score` > 30 covers about 0.07% of transactions, so the demo uses a picked persona. See spec `docs/specs/d4-b-disputes-handoff-screens.md` D8–D10.

### D7 — Model per step (D7) · **Proposed**
**Context:** `07` §8 D7 asks for the model per step, chosen from the dev-set benchmark. The first live run is `eval/reports/dev-c64dd67067/` (offline evaluation, `CASES=a-`, 5 cases, 3 proposed runs, Anthropic API; Bedrock serves the same models, ADR-028). The `nlu` step runs without a fixed temperature, so results can vary between runs (ADR-031).
**Proposal:** `nlu` stays on `claude-sonnet-5-5` (ADR-031). `compose` and `handoff_summary` stay on `claude-haiku-4-5-20251001`. The smoke NLU comparison (offline evaluation, n=20, `failed_calls` 0 for both models):

| System | F1 | Exact-set match | Status acc. | p50 / p95 ms | Mean cost/call |
|---|---|---|---|---|---|
| keyword_nlu | 0.635 | 60.0% (12/20) | 90.0% (18/20) | n/a | n/a |
| claude-sonnet-5-5 | 1.000 | 100.0% (20/20) | 100.0% (20/20) | 1335 / 2904 | $0.01601 |
| claude-haiku-4-5-20251001 | 1.000 | 100.0% (20/20) | 95.0% (19/20) | 1424 / 2032 | $0.00620 |

**Why not decided yet:** both models tie on intent (F1 1.000). Haiku costs about 39% of Sonnet per call and misses one status on n=20, so the smoke set cannot separate them (the 95% intervals overlap widely). Proposed pass rate on the 5 `a-` cases was 100% (safe automated resolution 4/4) in every run, against 75% (3/4) for the baseline, which is also n-limited.
**Status:** final after the held-out NLU comparison.
**Amendment (naturalidad-cardy):** a new `summary` step summarizes the messages that leave the 6-message window. It runs on `claude-haiku-4-5-20251001` at temperature 0 with prompt `summary@v1`, because it only condenses already-masked text and Haiku is the cheapest model that does it. It adds at most one call per turn and never blocks a reply: on an `LLMError` the turn continues with the last 6 messages.

---

## Deferred to implementation

These are known and owned, and they're decided while building the related feature:

| Item | Decided when |
|---|---|
| Numeric targets for the D1.5 outcome metrics (the metrics themselves are defined in `05` §6) | After the first dev eval run, before freezing held-out |
| Model family for the customer simulator, paraphrases and LLM judge (non-Claude, to avoid self-grading bias) | Building the eval harness |
| Exact Bedrock model IDs per step | Benchmark on the dev set |
| Moment of the Anthropic API → Bedrock switch (ADR-028) | When K2 in `07` passes; before the D4 deploy at the latest |
| Whether the public deployment runs Langfuse (ADR-006) | **Decided 2026-09-28:** no, see ADR-006 |
| Concrete AWS setup | **Decided 2026-09-28:** single EC2 + Compose, see ADR-017 and `08-deployment.md`. **Amended 2026-10-03:** m7i-flex.large in us-east-2 (Free plan project) |
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
| Card status and details; balance, due date and minimum payment | Due date and minimum payment apply to credit cards only; a debit card shows its available balance | ADR-020, ADR-034 |
| Mock identity provider and session token | The OTP is a fixed demo code shared with judges; a real OTP system is out of scope | ADR-008 |
| Control and traceability of LLM | Core scope defined | ADR-024 |
| Out-of-market requests (and out-of-scope replies) | Structured abstain: acknowledge the topic, say why, offer the closest supported action and a human | ADR-026 |
