# 07 — Execution plan

Build plan for the submission on **Mon 2026-10-05**, for two people plus coding agents. Scope follows ADR-019: build **Core** first and reach a submittable **MVP gate on D5**. After that, layer on reliability, evidence and the if-time items in the fixed order. Every line of [`features-list.md`](features-list.md) is mapped to a feature card or to the backlog in §5.

Status: **(proposed)**. Confirmed so far: weekends are working days, and the A/B track split below.

## 1. How we work

### Tracks
| Track | Owner | Owns (directories) | Theme |
|---|---|---|---|
| **A: Agent core** | Person A | `backend/app/core/llm/`, `backend/app/domains/{conversation,policy,safety,cards,transactions,disputes,handoff,audit,localization,customers}/`, `policies/` | What the bot understands, decides, does and verifies |
| **B: Platform & proof** | Person B | `pipeline/`, `backend/app/domains/identity/`, `backend/app/alembic/` (bank/identity schemas), `frontend/`, `docker/`, deploy, `eval/`, `notebooks/` | Data, login, UI, deploy, and the evidence that it works |

**Rules that keep the tracks independent:**
- Tracks talk only through the contracts in [`04-contracts.md`](04-contracts.md): tool signatures, NLU schema, HTTP/SSE API, handoff packet and audit event. A change to a contract is its own small PR, and the other person is tagged on it.
- Each side works against a stub until the real piece lands. The `FakeLLM` (fixed NLU outputs), the fixture DB (~50 customers) and the SSE fixture page make this possible.
- Each person runs several coding-agent sessions in parallel on cards from **their own track**. Cards that share a directory are never assigned to parallel agents on the same day.
- Shared files (`Makefile`, `docker-compose.*.yml`, `pyproject.toml`) take small additive edits only, and are rebased often.

### Daily rhythm
| When | What |
|---|---|
| Start (15 min) | Pick the day's cards, and confirm what each track needs from the other and by when |
| Midday (10 min) | Check the cross-track handoff: is the stub replaced? Any contract changes? |
| End of day (30 min) | Everything merged to `main`, `make check` green. Joint **smoke test** of the day goal on the running stack (on AWS from D4). Short note in §7 |
| If behind | Apply the day's named cut line (below). Never borrow from the next day's MVP work |

**PR review:** the author self-merges after green CI (ADR-018). Cards marked **Review: yes** (safety-critical: identity, tool registry, policy, PII, escalation) need the other person's approval first.

### Card format
Each card has:
- a header: track, day, tier, dependencies, and whether it needs review
- **Goal:** one user-visible sentence
- **Workflow / scope:** what gets built, in order
- **Acceptance criteria:** testable checkboxes
- **Covers:** feature-list items and requirement IDs
- **Paths:** where the code goes

Tiers:
- **MVP:** needed for the D5 gate.
- **Better:** production quality and evidence (D6–D8).
- **If-time:** ADR-019 order.
- **Stretch:** the §5 backlog.

## 2. Timeline at a glance

| Day | Date | Day goal | Track A | Track B |
|---|---|---|---|---|
| D1 | Sun 27 Sep | Stack runs, data lands, Bedrock answers | F01 Backend skeleton + harness · F02 LLM gateway + AWS smoke test | F03 Bank schema + ingest · F04 dbt serving + date shift + load + golden DB |
| D2 | Mon 28 Sep | **Walking skeleton:** a persona logs in and asks for card status/balance in ES and PT | F05 Turn graph + NLU + composer · F06 Card read tools + `card_select` + `card_info` + localization | F07 Identity + personas · F08 Frontend shell + chat + all UI widgets |
| D3 | Tue 29 Sep | **The bot acts safely:** lock vs block with confirmation and verified read-back | F09 Policy engine + tool registry + confirmation tokens + audit · F10 `card_block` flow | F11 Eval harness v0 + ~30 dev scenarios · F12 Keyword baseline router + NLU set |
| D4 | Wed 30 Sep | **All three required behaviors** work locally, and the first AWS deploy is live | F13 Escalation rules + handoff packet + abstention · F14 `unrecognized_charge` flow | F15 Staff console v0: inbox + live takeover · F16 AWS deploy v0 (midpoint decision) |
| D5 | Thu 1 Oct | **MVP GATE** (§4) | F17 `decline_explain` · F18 `replacement` + step-up · F19 PII vault + grounding check | F20 Dev + held-out suites authored, reviewed and frozen · F21 First measured run: proposed vs baseline |
| D6 | Fri 2 Oct | Production-grade reliability and data rigor | F22 Session expiry + resume · F23 Retries, faults, safe fallback, cost guard · F24 Injection hardening | F25 Pipeline contracts, quality, lineage, freshness · F26 Traceability console |
| D7 | Sat 3 Oct | Results proven, plus if-time (1)–(2) | F27 `card_unlock` with reason check · F28 `tx_search` | F29 Customer simulator + LLM judge · F30 Held-out runs + learned-component report |
| D8 | Sun 4 Oct | Ready to submit; **code freeze at 18:00** | F31 Priority flags · F32 Pending/reversal explainer · bug fixes | F33 Data analysis (D1.x) · F34 README, slides, video |
| D9 | Mon 5 Oct | Submit | Buffer: fix only what breaks | Final held-out rerun if code changed after D7, deploy check, submission email |

**Critical path:** F01 → F05 → F09 → F10 → F13/F14 → MVP gate, and F03 → F04 → F07 → F11 → F20 → F21. On Track B, F16 (deploy) is the riskiest item, so it starts on D4 and not later.

---

## 3. Feature cards by day

### D1 · Sun 27 Sep — Foundations
**Day goal:** `make up` starts Postgres, Redis and the backend locally. `make data` fills Postgres with all 13 tables and snapshots `latam_golden`. A Bedrock call works through `core/llm` and shows up in Langfuse.
**Cross-track:** A needs B's bank schema (F03) by midday to point repositories at it. Until then, A uses a 50-customer fixture DB built from `data/_parquet`.
**If behind:** leave CI caching and Grafana dashboards for later. Load `digital_events` last, since it's big and not used by flows.

#### F01 · Backend skeleton and engineering harness
Track A · D1 · MVP · Depends: — · Review: no
**Goal:** a clean monolith that enforces the architecture from the first commit.
**Scope:**
- `uv` project, Python 3.12.
- FastAPI app with `/api/v1/health`, Pydantic Settings, SQLModel/asyncpg session, Alembic env for all schemas (`bank`, `app`, `identity`, `audit`).
- structlog JSON with `request_id`, and OTel instrumentation.
- `docker/docker-compose.{base,dev,observability}.yml`: Postgres 16, Redis 7, backend with hot reload, and VictoriaMetrics/Logs/Traces.
- `Makefile` targets `setup / up / down / check / test`.
- pre-commit: Ruff, gitleaks, Conventional Commits, held-out freeze check stub.
- `backend/.importlinter` with the contracts from `06` §2.
- GitHub Actions CI.
- Layered `CLAUDE.md` for `backend/`, and `.mcp.json`.

**Acceptance criteria:**
- [ ] `make setup && make up` on a clean clone → `GET /api/v1/health` returns 200 with the DB and Redis both OK
- [ ] `make check` runs Ruff, mypy, import-linter and pytest, and CI runs the same on every PR
- [ ] An import-linter test proves a forbidden import fails (e.g., `conversation` → `cards.repository`)
- [ ] gitleaks blocks a committed fake AWS key. `.env.example` is committed and `.env` is ignored

**Covers:** D6.4, ADR-018 · **Paths:** `backend/`, `docker/`, `Makefile`, `.github/workflows/`

#### F02 · LLM gateway (`core/llm`) and AWS smoke test
Track A · D1 · MVP · Depends: — · Review: no
**Goal:** one audited way to call Bedrock, proven on AWS.
**Scope:**
- Bedrock client using the AWS profile locally and the IAM role on AWS.
- Model registry per step (`nlu`, `compose`, `summary`, `sim`, `judge`), set in config.
- Structured-output helper (Pydantic in, validated object out, one retry that includes the validation error).
- 2 retries with exponential backoff and jitter, plus per-call timeouts (R11).
- Langfuse client with a `mask` hook.
- `audit.llm_calls` ledger (tokens, cost, latency, trace IDs).
- Pinned model ID, prompt version and temperature on every call (R7).
- `LLM_DISABLED` flag, and a `FakeLLM` for tests.
- An `assert_masked()` hook point, which F19 fills in.
- **AWS smoke test:** confirm model access and quotas in the chosen region for a small Claude model (NLU/compose), a larger Claude model (later answer node), and a non-Claude family (simulator/paraphrase/judge). Then make one call from a small EC2 instance using an IAM role.

**Acceptance criteria:**
- [ ] `python -m app.core.llm.smoke` returns a validated structured object. The trace shows in Langfuse, and a row lands in `audit.llm_calls` with cost
- [ ] A unit test shows 2 retries then `LLMUnavailable` with a fake timeout, and no third call
- [ ] Only `core/llm` imports boto3 / `langchain_aws` (import-linter)
- [ ] The smoke-test result (region, model IDs, quotas, IAM role) is written in §7

**Covers:** D6.1, D6.2, R7, R11, ADR-003, ADR-017 · **Paths:** `backend/app/core/llm/`

#### F03 · Bank schema and ingest
Track B · D1 · MVP · Depends: — · Review: no
**Goal:** the raw data is reproducibly downloaded, and all 13 tables have a DDL.
**Scope:**
- `pipeline/ingest`: S3 `data/` → `data/raw/<table>/…parquet` plus `_manifest.json` (key, size, ETag, `downloaded_at`), using credentials from env/profile. It skips partitions whose ETag hasn't changed.
- An Alembic migration for `bank.*` (13 tables, observed types, `origin` / `created_at` / `conversation_id` on the tables the app appends to, and the §6 indexes from `03`).
- Alembic migrations for `app.*`, `identity.*` and `audit.*`.
- A 50-customer fixture DB for tests and for Track A.

**Acceptance criteria:**
- [ ] `make ingest` on a clean machine downloads everything, and a second run downloads 0 bytes
- [ ] `alembic upgrade head` creates all schemas. `alembic downgrade base` is clean
- [ ] `make fixture-db` builds a small DB that Track A's tests use

**Covers:** D4.1, D6.4 · **Paths:** `pipeline/ingest/`, `backend/app/alembic/`, `pipeline/fixtures/`

#### F04 · dbt serving layer, date shift, load and golden DB
Track B · D1 · MVP · Depends: F03 · Review: no
**Goal:** `make data` goes from S3 to a golden Postgres DB with one command.
**Scope:**
- dbt-duckdb project: `staging` (types, renames, enum normalization, PK dedup with a rejects table) → `intermediate` (card_type, masked number, available credit, FX) → `serving` (column sets per Postgres table, and the date shift `date_offset_days = 7 × floor((load_date − 2026-06-17)/7)` applied to every date column).
- Load through the DuckDB postgres extension → `COPY` into `bank.*`.
- `app.system_metadata` (`load_date`, offset, manifest hash).
- `CREATE DATABASE latam_golden TEMPLATE …`, plus `make demo-reset`.
- Basic dbt tests: unique and not_null on PKs. The full tests come in F25.
- Decide the time zone semantics of `transaction_date`, and write the decision in §7.

**Acceptance criteria:**
- [ ] `make data` runs end to end. Row counts per table match the Parquet counts minus the rejects, which are reported
- [ ] Max `transaction_date` in serving is within the last 7 days of the load date. Weekdays are preserved (sample check)
- [ ] Running it twice gives identical row counts and checksums (determinism, D4.1)
- [ ] `make demo-reset` restores the app DB from the golden DB in under 2 min

**Covers:** D4.1, D4.4 (lineage via dbt docs), ADR-009/010/011 · **Paths:** `pipeline/dbt/`, `pipeline/load/`

---

### D2 · Mon 28 Sep — Walking skeleton
**Day goal (smoke test):** log in as a persona with 2 cards and write "¿cuánto debo de mi tarjeta?" → the card picker appears → pick credit → get the balance, due date, synthetic minimum payment and available credit, formatted for the persona's country. Repeat in PT ("quanto devo no meu cartão?") and on a debit card (the bot says it's credit-only).
**Cross-track:** B's frontend consumes A's SSE events. Both follow the `04` §3 contract. B uses a fixture SSE page until A's stream is live. A uses `POST /test-idp/sessions` from B's F07 (available by midday) and a hard-coded session until then.
**If behind:** leave the refresh endpoint and the ES/PT UI toggle polish for D3.

#### F05 · Turn graph, NLU and composer
Track A · D2 · MVP · Depends: F01, F02 · Review: no
**Goal:** a real multi-turn conversation that is checkpointed, streamed and in the customer's language.
**Workflow:** `load_session → understand → route → [flow] → compose → persist → END`, streaming `status → message → ui → done`. `mask_pii` is a no-op until F19.
**Scope:**
- `app.conversations` and `app.messages`, plus `POST /conversations`, `POST /conversations/{id}/messages` (202) and `GET /conversations/{id}/stream` (SSE).
- `AsyncPostgresSaver` keyed by conversation.
- Graph state as in `02` §3.
- NLU prompt `nlu@v1`: closed intent enum, statuses and slots from `04` §2, ES/PT/voseo/portuñol examples, and the regional lexicon v0 (`localization/lexicon/*.yaml`, which B extends in F12).
- Composer prompt `compose@v1`: a fact list with placeholders, and the reply language taken from the current turn.
- Router for `greeting`, `thanks_close`, `affirm` and `deny`, and an intent queue for multi-intent turns.

**Acceptance criteria:**
- [ ] A scripted conversation with the FakeLLM goes through 3 turns, and the state survives a backend restart (checkpointer)
- [ ] With real Bedrock: 20 hand-written ES/PT/portuñol utterances give valid NLU JSON 20/20 (schema-valid; accuracy is measured later)
- [ ] The reply language follows the latest turn (ES → PT switch test)
- [ ] "bloquea mi tarjeta y dime mi saldo" queues `[card_block, balance_due]`

**Covers:** "Per-turn language detection and code-switching", "ES and PT-BR with a regional lexicon" (v0), S4, D2.1 · **Paths:** `domains/conversation/{graph.py,nodes/,prompts/}`

#### F06 · Card read tools, `card_select`, `card_info` and localization
Track A · D2 · MVP · Depends: F01, F03 · Review: **yes** (tool registry binding, R1)
**Goal:** trusted card facts, cited to the record and formatted in code.
**Workflow (`card_info`):**
1. `card_select`: `cards.list_cards()`. If there's one card, use it. If there are several, emit `ui.card_picker` ("Crédito •••• 6475 · Activa"). A hint like "la de crédito" or "termina en 6475" is resolved in code. If it's still unclear, ask again (`clarification_failures++`).
2. `cards.get_card_details(card_id)`.
3. Facts: mask, status, expiry, limit, available credit (limit − balance, in code), rate, balance, `days_past_due` bucket, and the minimum payment from `policies/min_payment.yaml` (labeled synthetic). Each fact has a source.
4. Debit: mask, status, expiry, last 5 transactions. `balance_due` on a debit card → "that applies to credit cards" + an offer of what it can show (ADR-020).
5. A Closed/Suspended/Inactive customer → read-only facts, and the reply notes the limitation (ADR-021). The handoff comes in F13.

**Scope:**
- Tool registry v0 (read tools only). `ToolContext` is built from the session, and tools never accept `customer_id` (R1).
- `customers` and `cards` repositories with every query filtered by `customer_id`.
- `localization`: Babel money per account country (MX `US$…` + labeled MXN estimate from `daily_exchange_rates` with its date, CO `COP $1.234.567`, AR `ARS $ 1.234,50`), day-first dates, card masks.

**Acceptance criteria:**
- [ ] Unit test: no registered tool signature includes `customer_id`. Asking for another customer's `card_id` → `AccessDenied` + an `access_denied` audit event
- [ ] Formatting tests for MX (with the MXN estimate label), CO and AR, in ES and PT replies
- [ ] Flow tests in ES and PT: one card, several cards with a picker, a hint, a debit `balance_due`, a suspended customer
- [ ] No number in the reply is written by the LLM: the composer gets placeholders only

**Covers:** "Card picker", "Card status and details", "Balance, due date and minimum payment", "Localized money and dates", "Customer-scoped tools" (read side), D2.3, B6, R1, R4 · **Paths:** `domains/{cards,customers,localization}/`, `domains/conversation/{tools/,flows/card_select.py,flows/card_info.py}`, `policies/min_payment.yaml`

#### F07 · Identity and personas
Track B · D2 · MVP · Depends: F03, F04 · Review: **yes**
**Goal:** every customer can log in, and the session is the only source of `customer_id`.
**Scope:**
- Provision credentials for all customers (seeded generator, low-cost hash, `data/secrets/credentials.csv` git-ignored) plus staff accounts (`agent`, `admin`).
- `POST /auth/login|logout|refresh`, `GET /auth/me`, a JWT httpOnly cookie, CSRF double-submit, and roles.
- `POST /test-idp/sessions` (enabled only when `ENV != prod`).
- Login rate limit (ADR-023).
- Persona catalog: ~30 curated customers selected by SQL in `eval/personas.yaml`, covering several cards, a bank-blocked card, a suspended customer, a repeat complainer, a regulator case, each decline code, pending/reversed transactions, expiring cards, MX/CO/AR, and USD cards.

**Acceptance criteria:**
- [ ] Log in as any customer from `credentials.csv` → `/auth/me` returns only their own masked profile
- [ ] Wrong password × N → 429. Missing CSRF on a POST → 403
- [ ] `/test-idp/sessions` returns 404 when `ENV=prod` (test)
- [ ] Each persona in `personas.yaml` has its query and the trait it covers. Each is checked against the golden DB by a test

**Covers:** "Mock identity provider and session token", B5, ADR-008 · **Paths:** `domains/identity/`, `pipeline/load/identity.py`, `eval/personas.yaml`

#### F08 · Frontend shell, chat and UI widgets
Track B · D2 · MVP · Depends: F01 · Review: no
**Goal:** a customer-facing app that can render everything the bot will ever emit, built once against the contract.
**Scope:**
- Vite + React 19 + TanStack Router/Query, Tailwind v4 + Radix, Biome, and the generated OpenAPI client.
- ES | PT toggle, defaulting to the browser language (ADR-022).
- Routes: landing, login, chat.
- SSE client with reconnect.
- **All SSE `ui` widgets from `04` §3**, built now on a fixture page: `card_picker`, `confirm` (buttons → `POST /confirmations/{token}`), `transaction_list` (multi-select), `otp_required` (4-digit modal → `/auth/otp/verify`), `handoff_banner`, `mode` (bot/human with the agent's display name).
- A global `401 session_expired` handler: re-login modal → retry the last turn. It is used for resume in F22.
- Nginx dev proxy.

**Acceptance criteria:**
- [ ] Landing → login → chat works against the real backend. Logout clears the cookie
- [ ] The fixture page renders every widget in ES and PT. Playwright covers login → send a message → receive the streamed reply
- [ ] The generated client is regenerated by `make client`, and CI fails if it's stale

**Covers:** "Mock identity provider" (landing + login note), "Card picker" (UI), ADR-022 · **Paths:** `frontend/`

---

### D3 · Tue 29 Sep — The bot acts safely
**Day goal (smoke test):**
- "Quiero bloquear mi tarjeta" → picker → "¿pausarla o cancelarla y pedir una nueva?" → "pausarla" → confirm button → locked → read-back → done.
- "Perdí mi tarjeta, bloquéala" → permanent block → `product_status = Blocked` read back, and a history row written.
- The same in PT ("travar o cartão"). `make eval SUITE=dev SYSTEM=proposed` runs the ~30 scenarios that exist so far.

**Cross-track:** B's eval runner calls A's API through test-IdP sessions. A's side-effect flows need a golden clone per test run (the F04 template).
**If behind:** A ships `card_block` with the permanent block only, and the lock follows on D4 morning. B ships the baseline for single-intent only, and the multi-intent clause splitting follows on D4.

#### F09 · Policy engine, tool registry (side effects), confirmation tokens and audit
Track A · D3 · MVP · Depends: F06 · Review: **yes**
**Goal:** permissions and confirmations live in code and YAML, never in the prompt.
**Scope:**
- `policies/*.yaml` loader: a `provenance: team-generated-synthetic` header is required, validated with Pydantic at startup, and a combined sha256 is logged on every decision (R8).
- `tools.yaml`: intent → allowed tools, plus confirmation and step-up flags.
- Registry executor, in order: check allowlist → check confirmation token (Redis `conf:<id>`, `GETDEL`, TTL 5 min, bound to tool + args hash + customer) → step-up check (fixed OTP window) → run with an idempotency key → return `ActionResult{verified}`.
- Typed errors (`04` §1).
- `audit.audit_events` writer: `nlu_result`, `rule_hit`, `tool_call`, `tool_result`, `confirmation_issued`, `confirmation_used`, `readback`, `access_denied`, `reply_sent`.
- The composer refuses "done" wording unless `ActionResult.verified = true` (R3).
- R12 helper: update plus history row in one transaction.

**Acceptance criteria:**
- [ ] Unit tests for R1, R2, R3 and R12:
  - A side-effect tool without a token → `ConfirmationRequired`
  - A reused token → rejected
  - A token for another customer, tool or args → rejected
  - An intent not on the allowlist → `PolicyDenied`
  - An unverified result → the composer can't produce "done"
- [ ] Startup fails on a policy file with no provenance header
- [ ] Every tool call produces paired `tool_call` / `tool_result` audit events with `policy_version`

**Covers:** "Policy engine outside the model", "Verified read-back" (mechanism), "Customer-scoped tools" (write side), "Tracing and audit timeline" (events), D3.2, D3.4, D6.6, R2, R3, R8, R12 · **Paths:** `domains/policy/`, `domains/audit/`, `domains/conversation/tools/registry.py`, `policies/tools.yaml`

#### F10 · `card_block` flow (lock vs block)
Track A · D3 · MVP · Depends: F09 · Review: **yes**
**Goal:** the MVP centerpiece, covering S3a (normal) and S3b (ambiguous).
**Workflow:**
1. `card_select`.
2. No `block_kind` → clarify `lock_vs_block`.
3. Policy precheck: already Blocked/Closed → `Conflict` → explain. A customer that is not active can still block (ADR-021).
4. Issue a token and emit `ui.confirm`.
5. The customer affirms (button or "sí"/"sim"):
   - `temporary_lock` → `cards.lock_card` → verify `card_controls.locked`
   - `permanent_block` → `cards.block_card(reason)` → verify `product_status = Blocked` + `card_status_history` row → offer `replacement`
6. Deny → cancel politely.
7. Read-back mismatch → `action_unverified` (the handoff stub is replaced by F13).

**Acceptance criteria:**
- [ ] Flow tests in ES and PT: happy lock, happy block, ambiguous → clarified, deny, already blocked, write failure, read-back mismatch
- [ ] Voseo ("¿me podés bloquear la tarjeta?") and "travar" are both understood (manual Bedrock check, then added to dev scenarios)
- [ ] The DB state after a block matches the expected state in the eval clone. History row with `actor = customer`, `conversation_id` and `trace_id`

**Covers:** "Instant lost/stolen block", "Temporary lock vs permanent block", "Verified read-back", S3a, S3b, D2.2, D2.5 · **Paths:** `domains/cards/`, `domains/conversation/flows/card_block.py`

#### F11 · Eval harness v0 and first dev scenarios
Track B · D3 · MVP · Depends: F04, F07 · Review: no
**Goal:** from now on, every flow can be measured the same way.
**Scope:**
- Scenario YAML schema with the `05` §3 labels: `expected_intents`, `expected_outcome`, `required_tools`, `forbidden_tools`, `expected_db_state`, `required_handoff_fields`, `expected_language`, `eligible_for_automation`, plus persona, seed ID, variant and reviewer.
- A scripted multi-turn driver (fixed customer turns; the LLM simulator comes in F29).
- A runner that creates `latam_eval_<run_id>` from the golden DB, starts the app against it, mints test-IdP sessions, runs the scenarios and drops the clone.
- Deterministic checks: tools called and forbidden, final DB state, confirm before act, read-back before "done", reply language, grounding (numbers ⊆ facts), handoff fields.
- Run metadata: git SHA, model IDs, prompt versions, policy hash, suite hash.
- `results.jsonl` + `metrics.json`.
- `make eval SUITE= SYSTEM= RUNS=`.
- ~30 dev scenarios for `card_info` and `card_block` in ES-MX/CO/AR, PT and mixed.

**Acceptance criteria:**
- [ ] `make eval SUITE=dev SYSTEM=proposed` runs start to finish on a fresh clone and leaves no DB behind
- [ ] A deliberately broken flow (a "done" with no read-back) fails the right check
- [ ] Two runs on the same SHA produce the same deterministic-check results (the FakeLLM path)

**Covers:** "Evaluation harness" (v0), E1, E2 · **Paths:** `eval/{runner,checks,scenarios/dev}/`

#### F12 · Keyword baseline router and NLU set
Track B · D3 · MVP · Depends: F05 (NLU schema) · Review: no
**Goal:** a fair, reasonable competitor to the LLM NLU (the D4.6 learned-component comparison), on the same tools, flows and policy.
**Scope:**
- Regional lexicon YAML, extending A's v0 (tarjeta/cartão, bloquear/travar, compra no reconocida/não reconhecida, voseo, MX/CO terms, out-of-market terms).
- Clause split at `y / e / también / además / além disso / , / ; / ?`, a per-clause match, and intents kept in order of appearance.
- Precedence rules ("no reconozco" + "bloquear" → `unrecognized_charge`) and a ~3-token negation window.
- Slot regexes (last4, credit/debit, block kind).
- ES/PT template replies.
- Plugged in as `SYSTEM=baseline`: it replaces `understand` and `compose` only.
- `eval/nlu/` format and ~80 dev utterances labeled from the seeds.

**Acceptance criteria:**
- [ ] `make eval SUITE=dev SYSTEM=baseline` runs on the same scenarios as the proposed system
- [ ] Unit tests: multi-intent split, precedence, negation ("no quiero bloquearla" drops `card_block`)
- [ ] `make eval-nlu SPLIT=dev` prints P/R/F1, exact-set match and status accuracy for the baseline and the LLM

**Covers:** "Intent classifier vs keyword baseline", D4.6, D1.6, E1, ADR-005 · **Paths:** `eval/baseline/`, `eval/nlu/`, `backend/app/domains/localization/lexicon/`

---

### D4 · Wed 30 Sep — All three required behaviors
**Day goal (smoke test):**
- "No reconozco estas compras" → transaction list with `fraud_score` → pick 2 → suspected compromise → block (confirm + read-back) → claim `CLM-…` → "Te transfiero con Fraudes". An agent claims it in the staff console, sees the packet, chats live and returns the conversation to the bot.
- "¿Puedo pagar con Pix?" → out-of-market abstention with alternatives.
- "Quiero hablar con una persona" → handoff to Atención.
- The **D3 build of `main` is reachable on the public AWS URL.**

**Midpoint decision (start of D4, 30 min, both):** the concrete AWS setup (ADR-017), based on the F02 smoke test and the remaining time. The default proposal is a single EC2 instance running the Compose prod layer + Nginx + TLS, with containerized Postgres on an EBS volume and an IAM instance role for Bedrock. The alternative is ECS Fargate + RDS.
**Cross-track:** B's staff console needs A's `handoffs` table, the `handoff:<queue>` pub/sub and the packet schema. Both are fixed by `04` §4, and B mocks them until A merges F13 around midday.
**If behind:** A ships the suspected-compromise path only, and the single-charge questionnaire moves to D5 morning. B ships the inbox + claim + agent reply, and return-to-bot moves to D6.

#### F13 · Escalation rules, handoff packet and abstention
Track A · D4 · MVP · Depends: F09 · Review: **yes**
**Goal:** the bot knows when not to act and hands off with verified facts, not transcripts.
**Scope:**
- `policies/escalation.yaml` rules evaluated in `route` and after each tool result:
  - `human_request`
  - clarification exhausted (≥ 2) → Atención
  - legal/regulator keywords (demanda, abogado, Condusef, SIC, BCRA, Procon…) → Reclamos
  - customer not active → Atención
  - unauthorized access → refuse + `access_denied` audit
  - `action_unverified`
- Handoff node: packet assembled in code (`04` §4), with `request` as the only LLM-written field (masked, length-capped). It writes the `app.handoffs` row, sets `mode = human`, publishes to Redis `handoff:<queue>`, emits `ui.handoff_banner` + `mode`, and the bot stops replying. `relay_to_agent` handles customer turns while `mode = human`.
- Abstention nodes:
  - `out_of_market` (`policies/out_of_market.yaml`: Pix, boleto, CPF, a Brazilian account) → say so + offer what it can do
  - `out_of_scope` → list the supported card topics

**Acceptance criteria:**
- [ ] One flow test per escalation rule in ES and PT, each asserting the queue, reason and `escalation_rules_hit`
- [ ] Packet completeness test: every required field is present. `verified_facts` only contain read-back values. There's no raw transcript
- [ ] Pix / boleto / "conta no Brasil" → abstain, with no tool calls (the eval `forbidden_tools` check)

**Covers:** "Structured handoff packet", "Explicit escalation rules", "Out-of-market requests", S3b, S3c, D3.3, D3.5 · **Paths:** `domains/handoff/`, `domains/conversation/nodes/{route,abstain,handoff}.py`, `policies/{escalation,out_of_market}.yaml`

#### F14 · `unrecognized_charge` flow (claim intake and fraud triage)
Track A · D4 · MVP · Depends: F09, F10, F13 · Review: **yes**
**Goal:** the S3c showcase: block, claim and a Fraudes takeover.
**Workflow:**
1. `card_select`.
2. `transactions.search(recent, include fraud_score)` → `ui.transaction_list` → the customer picks one or more.
3. **Decide today and write down (§7):** the suspected-compromise rule. Proposed: ≥ 2 transactions picked, or card not in the customer's possession, or any picked `fraud_score` > 30 (the threshold goes in `escalation.yaml`, and `fraud_score` is shown as a data field only).
4. Suspected compromise → offer a permanent block (confirm + read-back, reusing F10) → draft the claim → confirm → `disputes.create_claim` (appends `bank.complaints`, `origin='app'`, amount/currency/date from the record) → read back the case ID → handoff to **Fraudes** with evidence.
5. Single charge → questions from `policies/disputes.yaml` (card in possession? contacted the merchant?) → confirm → create claim → read back → case ID → done.

**Acceptance criteria:**
- [ ] Flow tests in ES and PT for both paths, plus: no transactions, and the customer declines the block
- [ ] The claim row has `origin='app'` and `conversation_id`. Its amount matches the source transaction exactly, and the customer never typed it
- [ ] The Fraudes packet contains the block and claim `actions_taken` with `verified: true` and the evidence transaction refs

**Covers:** "Suspected-fraud triage", "Unrecognized-charge intake", S3c, D2.4, D3.5 · **Paths:** `domains/{disputes,transactions}/`, `domains/conversation/flows/unrecognized_charge.py`, `policies/disputes.yaml`

#### F15 · Staff console v0: handoff inbox and live takeover
Track B · D4 · MVP · Depends: F07, F08 (F13 contract) · Review: no
**Goal:** a human can take over a live conversation (ADR-015).
**Scope:**
- Staff login (`agent` role) → `/staff/inbox` per queue with live updates (SSE on `handoff:<queue>`).
- Claim → the packet view (request, verified facts, actions, evidence, open questions, rules hit) and the role-gated conversation.
- Agent reply: `POST /staff/conversations/{id}/messages` → Redis `conv:<id>` → the customer's SSE.
- Return to bot: `mode = bot`, with a summary fact appended to the graph state.
- The customer's chat shows the `mode` banner with the agent's display name.

**Acceptance criteria:**
- [ ] Playwright E2E test: customer triggers a human request → the agent sees it in the inbox in under 2 s → claims it → messages flow both ways → return to bot → the next customer turn is answered by the bot
- [ ] A customer role can't reach `/staff/*` (403 test)

**Covers:** "Structured handoff packet" (agent view), "Control and traceability of LLM" (inbox part), ADR-024 · **Paths:** `frontend/src/pages/staff/`, `backend/app/domains/handoff/routes.py` (staff API; B builds the routes on A's service interface)

#### F16 · AWS deploy v0
Track B · D4 · MVP · Depends: F02 smoke test, midpoint decision · Review: no
**Goal:** a public URL from day 4, so deployment never blocks the submission.
**Scope:**
- `docker-compose.prod.yml` + Nginx + TLS.
- Provision the chosen setup. Bedrock through the IAM role, with no keys.
- `make data` on AWS, or a golden-DB dump/restore.
- Secrets through the env / Parameter Store.
- `POST /admin/demo/reset`.
- AWS Budgets alarm.
- `make deploy` redeploys `main`.
- Langfuse prod project with 30-day retention.

**Acceptance criteria:**
- [ ] The public HTTPS URL serves landing → login → a `card_info` conversation using Bedrock through the role
- [ ] `make deploy` from `main` works in under 10 min. `/test-idp` returns 404 in prod
- [ ] The Budgets alarm is set. The reset endpoint restores the golden state

**Covers:** K2, D6.4, ADR-017, ADR-023 (budget) · **Paths:** `docker/`, `deploy/`

---

### D5 · Thu 1 Oct — MVP gate
**Day goal:** pass every item in the §4 checklist on the **public URL**.
**Cross-track:** held-out authoring needs **both people for about 2 h in the afternoon** (100% human review). Block that time on both calendars. A's `replacement` needs B's `otp_required` widget, which already exists from F08.
**If behind:** the gate items win over everything else. D6 morning is used to close gate gaps before any "Better" card starts.

#### F17 · `decline_explain` flow
Track A · D5 · MVP · Depends: F06, F09 · Review: no
**Goal:** a rule-picked explanation of why the card was declined, which the LLM only phrases.
**Workflow:**
1. `card_select`.
2. `transactions.search(status=Declined)`: the most recent by default, otherwise `ui.transaction_list` to pick.
3. `transactions.explain_decline(tx_id)` from `policies/decline_codes.yaml`: 51 insufficient funds, 14 invalid number, 05 do not honor, 54 expired.
4. Compose the cause + next step.
5. 54 → offer `replacement`.

**Acceptance criteria:**
- [ ] ES and PT flow tests for all 4 codes, plus a case with no declines
- [ ] The reply cites `policy:decline_codes@<hash>` and the transaction source. No cause text is invented (the grounding check)

**Covers:** "Decline explainer", D2.3, R8 · **Paths:** `domains/transactions/`, `flows/decline_explain.py`, `policies/decline_codes.yaml`

#### F18 · `replacement` flow with step-up
Track A · D5 · MVP · Depends: F10 · Review: **yes**
**Goal:** after a block (or a code-54 decline), order a new card safely.
**Workflow:**
1. Precondition: the card is permanently blocked or expired, and the customer is active (ADR-021).
2. Confirm the masked delivery address.
3. An address change → `ui.otp_required` → `POST /auth/otp/verify` (fixed demo code from env) → step-up window.
4. Confirm → `cards.order_replacement` → verify the `app.card_replacements` row → simulated tracking ID.

**Acceptance criteria:**
- [ ] Flow tests: same address, changed address without OTP (blocked), changed address with OTP, card not eligible, customer not active → handoff
- [ ] The OTP value never appears in logs, LLM input or audit payloads

**Covers:** "Replacement and reissue", ADR-008 · **Paths:** `domains/cards/`, `flows/replacement.py`, `domains/identity/otp.py` (tiny, reviewed by B)

#### F19 · PII vault and grounding check
Track A · D5 · MVP · Depends: F05 · Review: **yes**
**Goal:** only tokenized text reaches Bedrock or Langfuse, and every reply is grounded.
**Scope:**
- `mask_pii` node: card numbers, document numbers, emails, phones and names → `⟨CARD_1⟩`, `⟨DOC_1⟩`… in an `app.pii_vault` per conversation, Fernet-encrypted.
- `unmask` only when rendering the customer's view.
- `core/llm.assert_masked()` refuses input that contains unmasked PII patterns (R5).
- Langfuse `mask` hook as the second line of defense.
- Composer grounding check: every number in the reply comes from a fact, the language matches, and there's no raw PII. On failure → regenerate once → otherwise the safe fallback template.

**Acceptance criteria:**
- [ ] Unit tests: masking a full card number, a CO/MX/AR document number, an email and a phone; the round trip; `assert_masked` raising on a raw PAN
- [ ] Every `audit.llm_calls` input for a dev run passes the "no raw PII" check (an eval deterministic check)
- [ ] An injected hallucinated amount in the composer output is caught and never sent

**Covers:** "PII minimization", B3, R4, R5, D2.3 · **Paths:** `domains/safety/`, `domains/conversation/nodes/{mask_pii,compose}.py`, `core/llm/`

#### F20 · Dev and held-out suites (authoring, review and freeze)
Track B · D5 · MVP · Depends: F07, F11 · Review: n/a (both people review cases)
**Goal:** a trustworthy frozen test set before anyone tunes against it.
**Scope:**
- Seed scenarios per intent × variant × category (`05` §2), ES-MX/CO/AR, PT-BR and portuñol, covering all 10 categories. Categories for features that don't exist yet (expired session, tool failures, injection) are authored now anyway.
- Paraphrases by a **non-Claude** Bedrock family.
- Split grouped by seed. Personas are not shared between dev and held-out.
- 100% human review of held-out (reviewer + date per case).
- ~80 dev + ~150 held-out conversations, and the `eval/nlu/` held-out split.
- Commit the suite hash, and a CI check that `eval/scenarios/heldout/` is unchanged (R9).

**Acceptance criteria:**
- [ ] The mix report matches the targets (±5 pp) by language and category
- [ ] Every held-out case has `reviewed_by` and `reviewed_at`. There's no seed or persona overlap with dev (a script checks this)
- [ ] The freeze check fails CI on a one-character change to held-out

**Covers:** "Evaluation harness" (suites), D4.7, D4.8, D5.1, D5.2a–f, R9 · **Paths:** `eval/scenarios/`, `eval/nlu/`, `eval/tools/paraphrase.py`

#### F21 · First measured run: proposed vs baseline (dev)
Track B · D5 · MVP · Depends: F11, F12, F20 · Review: no
**Goal:** the first real numbers, and the D1.5 targets set from them.
**Scope:**
- `make eval SUITE=dev` for both systems.
- Metrics from `05` §6: safe automated resolution, containment, escalation confusion matrix, unsafe outcomes (rule of three), clarification accuracy, NLU P/R/F1, latency, cost.
- Wilson 95% CIs and n on every rate.
- `report.md` with failures included.
- Numeric D1.5 targets written into `05` §6.
- A bug list handed to Track A for D6.

**Acceptance criteria:**
- [ ] `eval/reports/<run_id>/report.md` has a side-by-side table (same cases), CIs and a failures section
- [ ] The targets are recorded **before** any held-out run

**Covers:** E1, E3, E5–E9, D1.5, D1.6 · **Paths:** `eval/metrics/`, `eval/reports/`

---

### D6 · Fri 2 Oct — Production-grade reliability and data rigor
**Day goal (smoke test):**
- Expire the token in the middle of a block → re-login → the flow resumes at the confirmation step without asking again.
- With `FAULTS=bedrock_timeout` → 2 retries → safe-fallback template + handoff.
- A `merchant_name` carrying instructions is treated as data.
- `make data` produces a quality report and lineage.
- The staff console answers "why did the bot say this?" for any turn.

**If behind:** leave the per-account/day turn cap and the fixture for renamed columns in schema evolution for later.

#### F22 · Session expiry and resume
Track A · D6 · Better · Depends: F05, F08 · Review: **yes**
**Workflow:**
1. An expired JWT on `POST /messages` → `401 session_expired`. The pending graph state stays in the checkpointer.
2. The F08 modal → re-login.
3. The backend checks that it's the **same customer**, then replays the turn and resumes at the pending node.
4. A different customer → a new conversation, with no state leaking between them.

**Acceptance criteria:**
- [ ] Playwright: expire in the middle of `card_block` after the card is picked → re-login → the confirmation is shown next, and the card isn't asked for again
- [ ] Re-login as another customer can't resume the conversation (test + audit event)

**Covers:** "Session expiry and resume", D5.2b · **Paths:** `domains/identity/`, `domains/conversation/`

#### F23 · Retries, fault injection, safe fallback and cost guard
Track A · D6 · Better · Depends: F02, F09, F13 · Review: no
**Scope:**
- Tool retries (2, with backoff) and timeouts (LLM 20 s, tools 3 s).
- `FAULTS=bedrock_timeout,cards_write_error,readback_mismatch`.
- A safe-fallback template in ES/PT (no LLM) + handoff with `reason = llm_unavailable | tool_failure`.
- The `LLM_DISABLED` kill switch routes every turn to the fallback.
- Turn caps per conversation and per account per day (Redis), set in config.

**Acceptance criteria:**
- [ ] One test per fault flag: the expected retry count in the audit log, fallback text in the right language, a handoff packet with the reason, and never an invented answer
- [ ] The tool-failure scenarios in the dev suite pass

**Covers:** "Bounded retries and safe fallback", D6.2, D6.3, D5.2e, ADR-023, R11 · **Paths:** `core/llm/`, `domains/conversation/tools/`, `domains/conversation/nodes/fallback.py`

#### F24 · Injection hardening
Track A · D6 · Better · Depends: F05, F14 · Review: **yes**
**Scope:**
- Tool output enters prompts only inside explicit data fences.
- NLU status `injection_suspected` → treated as out of scope + audit.
- A graph-construction test: nodes that read tool output have no write tools (R6).
- The eval clone seeder injects instructions into `merchant_name` and complaint text.
- ~10 direct and data-field injection scenarios in dev.

**Acceptance criteria:**
- [ ] The graph test fails if a write tool is added to a node that reads tool output
- [ ] Dev injection scenarios: 0 unauthorized actions and 0 policy bypasses

**Covers:** "Injection hardening, including data fields", D5.2d, R6 · **Paths:** `domains/safety/`, `domains/conversation/`, `eval/seeders/`

#### F25 · Pipeline contracts, quality, lineage and freshness
Track B · D6 · Better · Depends: F04 · Review: no
**Scope:**
- Pandera contracts per raw partition, taken from the **observed** schema (types, nullability, enums, ranges, PK uniqueness), with deviations from the dictionary documented.
- dbt tests: FK relationships (orphans counted and flagged), accepted values, and the semantic checks from the EDA (transactions outside the card's life, future `last_updated`, the `process_date` shift, and active cards of inactive customers under ADR-021).
- A quality report per run.
- `dbt docs` lineage published under `data/lineage/`.
- Incremental processing by partition ETag.
- The 3 labeled **TEST FIXTURE** partitions (late arrival, schema evolution, duplicate batch), with asserted outcomes.
- `dbt build` on the sample in CI.

**Acceptance criteria:**
- [ ] `make data` writes `data/quality/<run_id>/contract_report.json` with counts and rates
- [ ] `pytest pipeline/tests` shows: the late partition corrects rows idempotently, the new column is mapped, and the duplicate batch is rejected
- [ ] The lineage graph shows raw → staging → serving for every bank table

**Covers:** D4.1–D4.5, D1.3 (inputs) · **Paths:** `pipeline/{contracts,dbt,fixtures,tests}/`

#### F26 · Traceability console
Track B · D6 · Better · Depends: F09, F15 · Review: no
**Scope:**
- A conversation list filterable by language, country, intent, outcome, escalation and date.
- A per-turn timeline built from `audit_events` + `llm_calls`: NLU result, rule hits, tool calls and results, sources, policy hash, model and prompt version, latency, cost, and a Langfuse link. No chain-of-thought.
- `system_metadata` (load date, offset, policy hash).
- An admin persona catalog with credential lookup.

**Acceptance criteria:**
- [ ] For any turn of a dev run, the timeline shows why the bot said it (sources + rules), and it opens the matching Langfuse trace
- [ ] The filters return correct counts against a SQL check

**Covers:** "Tracing and audit timeline" (view), "Control and traceability of LLM", D6.1, D6.6, ADR-024 · **Paths:** `frontend/src/pages/staff/`, `domains/audit/routes.py`

---

### D7 · Sat 3 Oct — Prove it, plus if-time (1)–(2)
**Day goal:** a held-out report (3 runs, proposed vs baseline, with CIs, breakdowns and error analysis) plus `card_unlock` and `tx_search` working on dev.
**Rule:** Track A fixes bugs found in **dev** results only. Nobody opens held-out failures to tune prompts (R9).
**If behind:** keep F29 and F30 (the evidence) and drop F28 (`tx_search`).

#### F27 · `card_unlock` with reason check (if-time 1)
Track A · D7 · If-time · Depends: F10, F13, F18 · Review: **yes**
**Workflow:**
1. `card_select`.
2. `cards.get_block_origin`, then branch on the origin:
   - Customer temporary lock → step-up OTP → confirm → `unlock_card` → verify → done
   - Customer permanent block → cannot be undone → offer `replacement`
   - Bank-side (dataset Blocked/Suspended, `days_past_due > 0`, fraud, customer Suspended) → handoff to **Cobranza** (days past due) or **Fraudes** (other), with the reason stated

**Acceptance criteria:**
- [ ] ES/PT flow tests for each origin. A bank-side block is never unlocked by the bot (the eval `forbidden_tools` check)

**Covers:** "Unblock with reason check", "Explicit escalation rules" (bank-side block) · **Paths:** `flows/card_unlock.py`

#### F28 · Natural-language `tx_search` (if-time 2)
Track A · D7 · If-time · Depends: F06 · Review: no
**Workflow:**
1. Take the NLU slots (date expression, merchant, amount, currency).
2. **Code** resolves:
   - dates in the account's time zone (MX/CO/AR) against the bank clock
   - fuzzy merchant match against the 24 known names
   - amount ±10%
   - a maximum 12-month window
3. `transactions.search` → up to 10 results in `ui.transaction_list`.
4. With 0 results → widen by ±3 days once → otherwise say nothing was found and show the filters used.

**Acceptance criteria:**
- [ ] Tests for "el cargo de Super Ahorro del martes pasado por unos 350", "a compra de ontem", and vague dates → clarify
- [ ] The LLM never produces SQL or dates: the filter is validated by Pydantic

**Covers:** "Natural-language transaction search" · **Paths:** `domains/transactions/`, `flows/tx_search.py`

#### F29 · Customer simulator and LLM judge
Track B · D7 · Better · Depends: F11, F20 · Review: no
**Scope:**
- A goal-driven simulator on a **non-Claude** family at temperature 0, playing the persona and fact sheet (card, charge, OTP, confirmations). It stops at goal reached, handoff, abstention or 12 turns.
- A hand check of 10 transcripts for persona adherence.
- An LLM judge for reply quality (grounding, tone, clarity, register) with `eval/judges/rubric.md`.
- **~50 human labels (both people, ~1 h)** → Cohen's κ and % agreement.

**Acceptance criteria:**
- [ ] `make eval DRIVER=simulator` runs the dev suite end to end
- [ ] The judge agreement report exists. If κ < 0.6, the judge is reported as a weak signal, not dropped silently

**Covers:** "Customer simulator", E4, ADR-016 · **Paths:** `eval/{simulator,judges}/`

#### F30 · Held-out runs and learned-component report
Track B · D7 · Better · Depends: F21, F29 · Review: no
**Scope:**
- Held-out: proposed ×3 and baseline ×1 on the same cases, with variability reported.
- `eval/nlu/` held-out: LLM NLU vs the keyword router, plus a model-selection comparison of 2 Bedrock models for NLU (quality, latency, cost).
- Breakdowns by language (ES-MX, ES-CO, ES-AR, PT-BR, mixed) and by segment, with small-sample caveats (E10).
- Error analysis by category with failure examples.
- Every number labeled offline, simulation or projection (E11).

**Acceptance criteria:**
- [ ] `eval/reports/heldout-<sha>/report.md` contains all of the above, with metadata: SHA, model IDs, prompt versions, policy hash, suite hash
- [ ] The chosen Bedrock model per step is written back into the decision log (it resolves a deferred item)

**Covers:** "Evaluation harness" (held-out), "Intent classifier vs keyword baseline" (report), "Ops scorecard" (report form), D4.6, D4.9, D4.10, E1–E3, E5–E11 · **Paths:** `eval/reports/`

---

### D8 · Sun 4 Oct — Submission-ready (code freeze at 18:00)
**Day goal:** `main` is frozen and deployed. The README, slides and video are done. The evening is for both people to record the video.
**Rule:** A starts F31/F32 only if the D7 held-out report shows 0 unsafe outcomes. Otherwise the whole day goes to fixing issues found on **dev**.

#### F31 · Claim priority flags (if-time 3)
Track A · D8 · If-time · Depends: F14 · Review: **yes**
**Scope:** `is_repeat_complainer`, a regulator channel or mention, amount > a threshold per currency (`disputes.yaml`), and Critical priority → the claim is created, then **always** handed off to **Reclamos** with `priority_flags` in the packet.
**Acceptance criteria:**
- [ ] One ES/PT test per flag, using personas from `personas.yaml` (repeat complainer, regulator case)

**Covers:** "Priority flags" · **Paths:** `domains/disputes/`, `policies/disputes.yaml`

#### F32 · Pending and reversal explainer (if-time 4)
Track A · D8 · If-time · Depends: F17 · Review: no
**Scope:** rules from `policies/transaction_states.yaml`: why a hold shows up, the expected drop date (synthetic), and why a reversal shows as two lines. `transactions.get(tx_id)`.
**Acceptance criteria:**
- [ ] ES/PT tests on the Pending and Reversed persona transactions

**Covers:** "Pending and reversed explainer" · **Paths:** `flows/tx_explain.py`, `policies/transaction_states.yaml`

#### F33 · Data analysis for workflow selection and the operational baseline
Track B · D8 · Better · Depends: F04, F25 · Review: no
**Scope:** reproducible notebooks (aggregates only, no PII), extending `notebooks/01_card_customer_eda.ipynb`:
- D1.1 contact reasons and complaint categories → why Card Support
- D1.2 demand over time, channel, country and hour, plus FCR and escalation
- D1.3 data quality from the F25 report (including the ADR-021 inconsistency)
- D1.4 SLA breaches, handle time and agent languages
- D1.6 the call-center operational reference for card reasons (labeled historical synthetic)
- Cost per resolution as a **projection**

**Acceptance criteria:**
- [ ] `make notebooks` re-executes them from the golden DB with no manual steps. The key charts are exported for the slides

**Covers:** D1.1–D1.6, E11 · **Paths:** `notebooks/`

#### F34 · README, slides and video
Track B (A joins in the evening) · D8 · MVP (deliverable) · Depends: everything · Review: both
**Scope:**
- README: what it is, the public URL, quickstart (`make setup/data/up/eval`), architecture, where AI is used and where it isn't, safety rules, eval results with links, limitations (`01` §10), remaining work (S6/D6.5: capacity, monitoring, access controls, retention, deployment), and the repo name check (K1).
- 4–6 slides.
- A video script built from the strongest built features (ADR-019), then recording.

**Acceptance criteria:**
- [ ] A fresh clone following only the README reaches a working local stack
- [ ] The slides and video are exported, and their links are ready for the submission email

**Covers:** K1, K3, K4, S6, D6.5, P1–P3 · **Paths:** `README.md`, `docs/`

### D9 · Mon 5 Oct — Submit
- Morning: if any code changed after the D7 held-out run, rerun held-out once on the frozen SHA and update the report. Run a final `make demo-reset` on prod and do a smoke test of all three behaviors in ES and PT.
- Submission email to hackathon.admin@factored.ai (K5): repo link, deployed URL, slides, video, persona emails/passwords and the OTP code. **These credentials go in the email, never in the repo.**
- No feature work.

---

## 4. MVP gate checklist (end of D5)

If everything after D5 failed, this is what we'd submit.

- [ ] Public HTTPS URL. Landing → login as a curated persona works (K2, B5)
- [ ] ES (MX/CO/AR), PT-BR and portuñol conversations for:
  - `card_info` (status, balance, due date, min payment; debit says credit-only)
  - `card_block` (lock vs block, confirm, read-back)
  - `decline_explain`
  - `replacement` (with step-up on an address change)
  - `unrecognized_charge` → block + claim → Fraudes takeover
  - out-of-market / out-of-scope abstention
  - human request
- [ ] A staff agent can claim a handoff, chat live and return the conversation to the bot
- [ ] R1–R5 and R12 unit tests green. Only masked text in `audit.llm_calls` for a dev run
- [ ] `make data` reproduces the golden DB. Langfuse and the audit tables record every turn
- [ ] Held-out frozen (hash committed, CI check on). Dev report for proposed vs baseline exists, with CIs. D1.5 targets recorded
- [ ] The README quickstart works on a fresh clone

## 5. Feature-list coverage

Every line of [`features-list.md`](features-list.md), and where it's built. "Backlog" means Stretch, taken only after F31–F32, in the order listed after the tables.

| Section | Feature | Tier | Card(s) | Day · Track |
|---|---|---|---|---|
| Identity & session | Mock identity provider and session token | MVP | F07 (IdP), F06/F09 (session-bound tools), F08 (landing + login) | D2 · B, D2–D3 · A |
| | Session expiry and resume | MVP | F08 (modal), F22 (resume) | D2 · B, D6 · A |
| | Card picker | MVP | F06 (logic), F08 (widget) | D2 · A + B |
| Transactions | Decline explainer | MVP | F17 | D5 · A |
| | Natural-language transaction search | If-time (2) | F28 | D7 · A |
| | Pending and reversed explainer | If-time (4) | F32 | D8 · A |
| | Duplicate-charge detector | Stretch | Backlog | — |
| Blocks & card controls | Instant lost/stolen block | MVP | F10 | D3 · A |
| | Temporary lock vs permanent block | MVP | F10 | D3 · A |
| | Unblock with reason check | If-time (1) | F27 | D7 · A |
| | Suspected-fraud triage | MVP | F14 | D4 · A |
| | Travel notice | Stretch | Backlog | — |
| | Spending limits | Stretch | Backlog | — |
| Card information | Card Doctor | Stretch | Backlog | — |
| | Card status and details | MVP | F06 | D2 · A |
| | Balance, due date and minimum payment | MVP | F06 | D2 · A |
| | Expiry and renewal | Stretch | Backlog | — |
| | Benefits by segment | Stretch | Backlog | — |
| Card lifecycle | Replacement and reissue | MVP | F18 | D5 · A |
| | New card activation | Stretch | Backlog | — |
| | PIN reset | Stretch | Backlog | — |
| | Cancel with a retention offer | Stretch | Backlog | — |
| | Credit limit increase request | Stretch | Backlog | — |
| Ask for a credit card | Card finder | Stretch | Backlog | — |
| | Pre-qualification through a policy service | Stretch | Backlog | — |
| | Missing-income path | Stretch | Backlog | — |
| Disputes & claims | Unrecognized-charge intake | MVP | F14 | D4 · A |
| | Priority flags | If-time (3) | F31 | D8 · A |
| | Recognize before you dispute | Stretch | Backlog (first: a small add-on to F14) | — |
| Handoff & agent assist | Structured handoff packet | MVP | F13 (assembly), F15 (agent view) | D4 · A + B |
| | Explicit escalation rules | MVP | F13 (+ bank-side block in F27) | D4 · A |
| | Agent copilot panel | Stretch | Backlog (F15 already shows the packet) | — |
| Language & channels | ES and PT-BR with a regional lexicon | MVP | F05 (NLU + lexicon v0), F12 (lexicon for the baseline), F20 (regional cases) | D2 · A, D3 · B, D5 · B |
| | Per-turn language detection and code-switching | MVP | F05, tested in F20 (multilingual category) | D2 · A, D5 · B |
| | Out-of-market requests | MVP | F13 | D4 · A |
| | Localized money and dates | MVP | F06 | D2 · A |
| | Channel-aware replies | Stretch | Backlog | — |
| | Plain-language mode | Stretch | Backlog | — |
| Safety, eval & ops | Policy engine outside the model | MVP | F09 | D3 · A |
| | Customer-scoped tools | MVP | F06 (reads, R1), F09 (writes), F13 (refusal) | D2–D4 · A |
| | Verified read-back | MVP | F09 (mechanism), F10/F14/F18 (per flow) | D3–D5 · A |
| | PII minimization | MVP | F19 | D5 · A |
| | Injection hardening, including data fields | MVP (hardening on D6) | F24 (+ data fences) | D6 · A |
| | Tracing and audit timeline | MVP | F02 (Langfuse), F09 (audit events), F26 (timeline view) | D1 · A, D3 · A, D6 · B |
| | Bounded retries and safe fallback | MVP | F02 (LLM), F23 (tools + fallback) | D1 · A, D6 · A |
| | Evaluation harness | MVP | F11, F20, F21, F30 | D3–D7 · B |
| | Intent classifier vs keyword baseline | MVP (as LLM vs keyword, ADR-005) | F12, F21, F30 | D3, D5, D7 · B |
| | Customer simulator | Stretch → Core (ADR-016) | F29 | D7 · B |
| | Ops scorecard | Stretch | F30 (report form); UI in the backlog | D7 · B |
| Others | Control and traceability of LLM | Core (ADR-024) | F15 (inbox + takeover), F26 (list + timeline) | D4 · B, D6 · B |

**Not in the feature list but required by the hackathon:**

| Item | Card(s) |
|---|---|
| Data pipeline | F03, F04, F25 |
| Deployment | F16 |
| Cost guard | F07 (login rate limit), F16 (Budgets alarm), F23 (turn caps + kill switch) |
| Data analysis D1.x | F33 |
| Deliverables K1–K5 | F34, D9 |

**Backlog after F32 (Stretch, in order).** Taken only when the D7 report is clean and there's more than half a day of slack. Each one needs a new flow, a policy file and ≥ 2 dev scenarios, or it doesn't ship.
1. Answer node for digressions (if-time 5, ADR-019): read-only, max 3 tool calls, no write tools.
2. Recognize before you dispute: show the decoded merchant, city, channel and date before `unrecognized_charge` files the claim.
3. Card Doctor: combines the `card_info` checks with the last decline code.
4. Expiry and renewal: the ≤ 60-day expiry persona.
5. Agent copilot panel: a suggested reply + policy citations next to the F15 packet.
6. Everything else in the Stretch list (travel notice, spending limits, activation, PIN reset, retention, limit increase, card finder, pre-qualification, missing income, channel-aware replies, plain-language mode, benefits, duplicate detector, ops scorecard UI).

## 6. Risks and mitigations

| Risk | Signal | Mitigation |
|---|---|---|
| Bedrock access or quotas are missing in the region | F02 smoke test fails on D1 | Switch region on D1, and request quota the same day. FakeLLM keeps both tracks moving |
| `digital_events` (10M rows) makes loading slow | F04 takes more than 30 min | Load it last, in parallel, with COPY. On AWS, restore the golden dump instead of rerunning the pipeline |
| Deploy slips | F16 not live by the end of D4 | D5 morning: B keeps working on F16, and F20 authoring moves to the afternoon. The MVP gate needs the URL |
| Held-out review takes longer than 2 h per person | F20 behind at 16:00 on D5 | Shrink held-out to ~120 while keeping the category mix. Never skip review |
| LLM latency above target | p95 > 8 s in F21 | Smaller NLU model, cached prompt prefix, fewer composer tokens. Report it honestly |
| Scope creep from if-time items | D7 held-out shows unsafe outcomes | The D8 rule: fix only, no F31/F32 |

## 7. Execution log

Decisions taken while building (the deferred items from the decision log) are recorded here, with the date and the card.

| Date | Card | Decision / note |
|---|---|---|
| | F02 | AWS region, Bedrock model access, quotas, IAM role |
| | F04 | Time zone semantics of `transaction_date` |
| | D4 | Concrete AWS setup (ADR-017) |
| | F14 | Suspected-compromise rule and threshold |
| | F21 | Numeric D1.5 targets |
| | F29 | Simulator, paraphrase and judge model family |
| | F30 | Bedrock model per step |
