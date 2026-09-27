# 07 — Execution plan

Build plan for the submission on **Mon 2026-10-05**, for two developers plus coding agents. Scope follows ADR-019: build **Core** first and reach a submittable **MVP gate at the end of D5**. After that, add reliability, evidence and the if-time items. Every line of [`features-list.md`](features-list.md) is mapped in §5.

Agreed with the team on 2026-09-26, day by day. Items marked **(proposed)** are decided while building and recorded in §8.

## 1. How we work

### Roles
| Dev | Profile | Owns |
|---|---|---|
| **A** | Senior | The platform and the **safety guardrails**: repo, Docker, CI, data pipeline, login, tool registry, policy, confirmation tokens, write tools, PII masking, escalation and handoff backend, eval runner, reliability, deploy, frontend tooling |
| **B** | Junior, focused on agentic workflows | The **agent** and **everything the user sees**: LangGraph graph, intent detection, reply writer, all workflows, frontend design and all screens, test sets, customer simulator, LLM judge |

B's workflows reach bank data only through the tools A builds. A bug in a workflow therefore can't skip a confirmation or read another customer's data. A reviews every B PR that touches tools, and pairs with B at the fixed migration slots (D2 and D3), which also double as mentoring.

### Feature groups
| # | Group | What's inside | Owner |
|---|---|---|---|
| G1 | Platform foundation | Repo, Docker Compose, Postgres/Redis, Makefile, CI, frontend tooling, observability | A |
| G2 | Bank data platform | S3 → dbt → date shift → Postgres → golden DB; data contracts, quality, freshness, lineage | A |
| G3 | Agent core | LangGraph turn graph, intent/language/slot detection, reply writer, thin LLM client | B |
| G4 | Login & sessions | Mock login, personas, step-up OTP, session expiry and resume | A |
| G5 | Web app | Design, landing, login, chat, widgets, staff screens | B |
| G6 | Safety guardrails | Tool registry, policy YAML, confirmation tokens, write tools with read-back, audit log, PII masking, grounding check, injection hardening | A |
| G7 | Card info workflows | Card picker, status/details, balance/due date/min payment, formatting, decline explainer | B |
| G8 | Card block/unblock workflows | Lock vs block, lost/stolen block, unlock with reason check, replacement | B |
| G9 | Disputes & fraud workflow | Unrecognized charge, fraud triage, claim, priority flags | B |
| G10 | Escalation & human handoff | Escalation rules, handoff packet, abstention, live-takeover backend (A); inbox and takeover screens (B) | A + B |
| G11 | Evaluation | Runner, checks, metrics, keyword baseline, held-out report (A); scenario format, driver, test sets, simulator, judge (B) | A + B |
| G12 | Reliability & deployment | AWS deploy, retries, faults, safe fallback, cost guard | A |
| G13 | Staff traceability console | Timeline API (A), screens (B) | A + B |
| G14 | Transaction workflows | Natural-language search, pending/reversal explainer | B |
| G15 | Submission | Notebooks, README, slides, video | Both |

### Working without blocking each other
- **Contracts first.** Before each side builds, A pushes the interfaces as a small PR: tool interfaces, `NLUResult`, graph state (D1); write tools, `ActionResult`, the confirmation and step-up interfaces (D2). They follow [`04-contracts.md`](04-contracts.md).
- **B's sandbox.** B works from D1 in the agent's final folder (`backend/app/domains/conversation/`):
  - A `FakeBank` implements the tool interfaces with DuckDB over the local `data/` files (customers, products, transactions, exchange rates). Writes, confirmations and OTP are faked in memory.
  - `make chat-sandbox CUSTOMER=<id>` is a terminal chat with a debug line (intent, slots, route, tools called).
  - Moving into the app means swapping `FakeBank` for A's Postgres tools (`BANK=fake|postgres`). The graph doesn't change.
- **Order of B's work.** B builds workflows while A builds the APIs they need, and builds the screens once those APIs exist (D3).

### Daily rhythm
| When | What |
|---|---|
| Start (15–20 min) | Check that yesterday's test still passes on `main`, agree any new contract, pick tasks |
| Pairing slot | D2 late afternoon (read path), D3 afternoon (write path), then only when needed |
| End of day (30 min) | **Merge everything to `main`, run the app (`make up`; the public URL from D4), and run the day's test script together.** Record any decisions in §8 |
| If behind | Apply the day's named cut line. Never take time from the next day's MVP work |

**Git:** short branches, PRs, squash merge, self-merge after green CI (ADR-018). PRs that touch identity, tools, policy, PII or escalation need the other dev's approval first.

## 2. Timeline

| Day | Goal: what we test by hand at end of day | Dev A | Dev B |
|---|---|---|---|
| **D1** Sun 27 | The stack runs with real data. **In a terminal**, the agent answers card status in ES/PT | G1 Platform + frontend tooling · G2 Bank data v0 · kickoff: Anthropic API key for B, Bedrock access, contracts | G3 Agent core in the sandbox · card status workflow |
| **D2** Mon 28 | A persona logs in **through the API** and asks about their cards; answers come from Postgres. Block/lock/unlock/replacement run in the sandbox | G4 Login + personas · Postgres read tools · conversation API + streaming · host the agent | G7 Card info complete + formatting · G8 Block/unblock workflows in the sandbox |
| **D3** Tue 29 | **First day in the browser:** card info + block, lock, unlock and replacement with confirm → read-back | G6a Policy, confirmation tokens, write tools + read-back, OTP, audit log · move B's workflows onto the real write tools | G5 Design + landing, login, chat, widgets (card picker, confirm, OTP) |
| **D4** Wed 30 | **Fraud claim and human handoff on the public URL.** Pix → abstain. "Quiero un humano" → handoff | G10 Escalation rules, handoff packet, abstention, live-takeover backend · G12a AWS deploy | G9 Disputes & fraud workflow · transaction-list and handoff widgets · staff inbox + takeover screens |
| **D5** Thu 1 | **MVP gate** (§4) | G6b PII masking, LLM ledger, grounding check · G11 Eval runner, checks, metrics · keyword baseline | Decline explainer · G11 scenario format, driver, dev + held-out test sets (both review held-out) |
| **D6** Fri 2 | **Survives failures and attacks** | G12b Retries, faults, fallback, cost guard · session expiry/resume · injection hardening · G2b data quality and freshness | G11 Customer simulator · UI hardening · dev cases for new categories · fixes from the D5 report |
| **D7** Sat 3 | **Proven, and every answer explained** | G13 Timeline API · held-out runs + report | G14 Transaction workflows · priority flags · traceability screens · LLM judge |
| **D8** Sun 4 | **Ready to submit; code freeze 18:00** | G15 Notebooks, README, final deploy | G15 Error analysis, slides · video together in the evening |
| **D9** Mon 5 | Submit | Fixes only | Submission email |

---

## 3. Days

### D1 · Sun 27 Sep — Foundations and agent sandbox
**Goal:** the app stack runs with the real data, and the agent answers card-status questions in a terminal, in ES and PT, for a fixed customer.

**Kickoff (first hour, both)**
| # | What | Output |
|---|---|---|
| K1 | Anthropic API key for B in the git-ignored `.env` (never in the repo), `LLM_PROVIDER=anthropic`. B's LLM work doesn't wait for Bedrock (ADR-028) | B can call Claude from D1 |
| K2 | Bedrock: pick the region, enable models (a small Claude model such as Haiku 4.5, plus a non-Claude family for later), AWS profiles on both laptops, one test call each. A leads, and it doesn't block B. Once it passes, B's connection switches to Bedrock (ADR-028) | Both of you can call Bedrock |
| K3 | Contracts PR to `main` (A writes, B reviews): `backend/` skeleton, read-tool interfaces (`list_cards`, `get_card_details`, `search_transactions` + result models + `ToolContext`), `NLUResult`, graph state | B starts from `main` |

**Dev A: G1 platform foundation and G2 bank data v0**
| # | Task | Done when |
|---|---|---|
| A1 | Backend skeleton: FastAPI `/api/v1/health`, settings, structured logging, Alembic | Health endpoint reports whether DB and Redis are up |
| A2 | Docker Compose (Postgres 16, Redis 7, backend with hot reload) + Makefile (`setup`, `up`, `down`, `check`, `test`) | `make setup && make up` works on a fresh clone |
| A3 | CI + pre-commit: Ruff, mypy, pytest, basic import-linter rules, gitleaks | CI green; gitleaks blocks a fake key |
| A4 | Alembic migration for `bank.*` (all 13 tables) + empty `app`, `identity` and `audit` schemas | `upgrade head` / `downgrade base` both clean |
| A5 | Data v0: scripted S3 ingest with manifest → dbt-duckdb (types, enum cleanup, date shift) → COPY into Postgres → `latam_golden` + `make demo-reset` | `make data` prints row counts. The latest transaction falls within the past 7 days |
| A6 | Frontend tooling: Vite + React 19 + TanStack Router/Query + Tailwind v4 + Biome; `make client` stub; frontend service behind the Nginx dev proxy | `make up` serves an empty page at `localhost` |

**Dev B: G3 agent core in the sandbox**
| # | Task | Done when |
|---|---|---|
| B1 | `FakeBank` on DuckDB over local `data/`, always filtered by the customer in `ToolContext`. ~10 hand-picked test customers (several cards, debit only, blocked card, MX/CO/AR) | Tests return the right cards per customer and never another customer's |
| B2 | Thin LLM client in `core/llm`: structured output (Pydantic in, validated object out, one retry on invalid output), provider behind `LLM_PROVIDER=anthropic\|bedrock` (Anthropic API first, ADR-028), and a tracing hook that is a no-op until self-hosted Langfuse runs (ADR-006) | A call through the Anthropic API returns a validated object. Switching the provider changes nothing outside `core/llm` |
| B3 | Turn graph v0: `load_session → understand → route → flow → compose`, in-memory state | Graph compiles; a picture of it is exported |
| B4 | Intent-detection prompt `nlu@v1`: closed intent list, statuses, slots, ES/PT/voseo/portuñol examples | 20 hand-written messages → 20 valid outputs |
| B5 | Card status workflow: one card is used directly; several → masked options; "la de crédito" / "termina en 6475" resolved in code | Works for one-card and multi-card customers |
| B6 | Reply writer `compose@v1`: facts as placeholders, reply in the current turn's language | ES → ES, PT → PT |
| B7 | `make chat-sandbox CUSTOMER=<id>` with the debug line | Used in the end-of-day test |
| B8 | 3 scripted conversations with a fake LLM in pytest | Green in CI |

**End-of-day test**
1. Fresh clone → `make setup && make up` → health 200. The empty frontend page loads.
2. `make data` → row counts for 13 tables. `latam_golden` exists. `make demo-reset` works.
3. `make check` passes locally and in CI.
4. `make chat-sandbox CUSTOMER=<multi-card>`:
   - "hola, ¿cuál es el estado de mi tarjeta?" → the bot asks which card → "la de crédito" → status, expiry, limit, available credit
   - "qual é o status do meu cartão?" → the answer comes back in PT
   - "¿me podés decir si mi tarjeta está activa?" → understood
   - "quiero pagar con Pix" → the debug line shows `out_of_market`
5. The log lines for those turns show each LLM call's provider, model ID and prompt version (Langfuse isn't needed yet).

**If behind:** A leaves the observability stack and CI caching for later, and loads `digital_events` on D2. B moves the card-hint resolution to D2 morning.

---

### D2 · Mon 28 Sep — The agent runs inside the app
**Goal:** a persona logs in through the API and asks about their cards. The agent answers from Postgres and streams the reply. Block, lock, unlock and replacement run end to end in the sandbox.

**Kickoff (20 min):** check D1 on `main`. A pushes the **write-side contracts** PR:
- write tools: `lock_card`, `unlock_card`, `block_card`, `get_block_origin`, `order_replacement`
- `ActionResult{verified, readback}`
- the confirmation interface: `issue(tool, args) → token`, `consume(token)`
- `is_step_up_valid()`
- how the graph pauses for a confirmation: the `ui.confirm` event + pending state

**Dev A: G4 login, read tools and hosting the agent**
| # | Task | Done when |
|---|---|---|
| A1 | Login: credentials for every customer (seeded, low-cost hash, git-ignored export) + staff accounts. `/auth/login`, `/logout`, `/me`, JWT httpOnly cookie + CSRF, roles. `/test-idp/sessions` (off in prod). Login rate limit | `/me` returns only the logged-in customer's masked profile |
| A2 | Personas: B's ~10 + ~20 more found by query → `eval/personas.yaml`, each checked against the golden DB | The persona test passes |
| A3 | Postgres read tools, always filtered by `customer_id`. Tool registry v0 injects `customer_id` from the session (R1) | Another customer's card → refused + logged |
| A4 | Conversation API: `POST /conversations`, `POST /messages` (202), `GET /stream` (`status`, `message`, `ui`, `done`), `conversations` and `messages` tables, Postgres checkpointer | A restart mid-conversation loses nothing |
| A5 | Host B's graph with `BANK=postgres`. **Pairing with B, ~1 h, late afternoon** | Same answers as the sandbox, from Postgres |
| A6 | `make client` generates the TypeScript client. `make chat-api PERSONA=…` = B's CLI in API mode | B can start the frontend on D3 |

**Dev B: G7 card info and G8 block/unblock in the sandbox**
| # | Task | Done when |
|---|---|---|
| B1 | Card info complete: balance, due date, min payment (`policies/min_payment.yaml`, labeled synthetic), available credit computed in code. Debit → credit-only message + what it can show. Inactive customer → read-only note | ES/PT tests for credit, debit and inactive customers |
| B2 | Formatting in code: MX in USD + labeled MXN estimate with the rate's date, `COP $1.234.567`, `ARS $ 1.234,50`, day-first dates, masked cards | Format tests for all 3 countries |
| B3 | Conversation basics: greeting, thanks, yes/no, and a queue for several requests in one message | "bloquea mi tarjeta y dime mi saldo" → both handled, in order |
| B4 | FakeBank write tools + fake confirmation and OTP, using the new interfaces | Unit tests |
| B5 | Block/unblock workflows:<br>• pause vs cancel clarification → confirm → lock/block → read-back<br>• unlock: own lock → OTP → unlock; own permanent block → offer replacement; bank-side → handoff placeholder<br>• replacement: confirm address, OTP only for a change of address, tracking ID | ES/PT scripted tests: happy path, clarification, "no", bank-side block |
| B6 | *Optional:* rough wireframes for landing, login and chat | Photos in the PR |

**End-of-day test**
1. `make up` → `/docs`. Log in as a persona → `/me` shows only their data. 5 wrong passwords → 429.
2. `make chat-api PERSONA=<multi-card>`:
   - "¿cuánto debo de mi tarjeta de crédito?" → balance, due date, synthetic min payment, in that country's format
   - The same in PT
   - A debit-only persona → the credit-only message
3. Ask about another customer's card number → refused and logged.
4. Restart the backend mid-conversation → the next message continues where it left off.
5. `make chat-sandbox`:
   - lock → confirm → read-back
   - unlock → OTP
   - "la perdí" → block → replacement → tracking ID
   - A bank-blocked customer → handoff placeholder

**If behind:** A moves the refresh endpoint and the rate limit to D3. B moves replacement to D3 morning, since it only needs the sandbox.

---

### D3 · Tue 29 Sep — First day in the browser
**Goal:** in the browser, a persona logs in, asks about their cards, and blocks, locks, unlocks and replaces a card. Each action goes confirm → action → read-back, and the change is visible in the DB.

**Dev A: G6a guardrails and moving the write path**
| # | Task | Done when |
|---|---|---|
| A1 | Policy loader: `policies/*.yaml` with a required `provenance` header, validated at startup, combined hash logged on every decision. `tools.yaml`: intent → allowed tools, confirmation and step-up flags | Startup fails on a file with no header; an intent calling a tool it isn't allowed → refused |
| A2 | Confirmation tokens in Redis (single use, 5 min, bound to customer + tool + arguments) + `POST /conversations/{id}/confirmations/{token}` | Reused, expired or someone else's token → rejected |
| A3 | Postgres write tools with read-back: lock/unlock (`card_controls`), block (`products.product_status` + `card_status_history` in the same transaction), `get_block_origin`, `order_replacement` (`card_replacements`), idempotency keys | Each returns `verified = true` only after re-reading the record |
| A4 | Step-up: `POST /auth/otp/verify` checks the fixed code from env and opens a step-up window in the session | Unlock without OTP → refused |
| A5 | Audit log v0: NLU result, rule hits, tool calls and results, confirmations, read-backs, access denied, reply sent | Every tool call leaves a pair of events with the policy hash |
| A6 | **Pairing with B, afternoon:** switch the block/unblock workflows to the real tools. "Done" only when `verified = true` (R3) | Unit tests for R1, R2, R3 and R12 pass |

**Dev B: G5 design and customer screens**
| # | Task | Done when |
|---|---|---|
| B1 | Design (~2 h): shadcn/ui, theme for the synthetic "LATAM Bank" brand, layouts for landing, login and chat, ES/PT text dictionary, browser-language default + ES \| PT toggle | Screens reviewed by A at the midday check |
| B2 | Landing + login on the generated client: cookie session, error messages | Log in / log out in the browser |
| B3 | Chat page: start a conversation, send a message, render the stream, status indicator, reconnect | The D2 card-info questions work in the browser |
| B4 | Widgets: card picker, quick-reply chips (pause / cancel), confirm buttons, OTP modal | Clicking works the same as typing "sí" or the card name |
| B5 | Playwright: login → card question → answer, and login → block → confirm → done | Green in CI |

**End-of-day test (browser)**
1. Log in as a persona. A browser in ES shows the ES UI, and the toggle switches to PT.
2. Card info as on D2, picking the card with a click.
3. "Quiero bloquear mi tarjeta" → pause/cancel chips → pause → confirm → "pausada". `card_controls.locked` is true in the DB.
4. "Desbloquéala" → OTP modal → unlocked.
5. "La perdí" → confirm → blocked. `product_status = Blocked` plus a history row → replacement → changed address asks for OTP → tracking ID.
6. Replay a used confirmation token with curl → rejected.
7. A bank-blocked persona asks to unlock → refused, with the handoff placeholder.

**If behind:** A moves idempotency keys and the extra audit event types to D4. B leaves visual polish for later, and moves the OTP modal to D4 morning (unlock and replacement can still be tested through `chat-api`).

---

### D4 · Wed 30 Sep — Fraud, human handoff, public URL
**Goal:** on the public URL, a customer reports charges they don't recognize → the card is blocked → a claim is filed → a Fraudes agent takes over live in the staff console and hands the conversation back to the bot. Out-of-market and human requests are handled.

**Morning decision (30 min, both):** the concrete AWS setup (ADR-017). Proposal: a single EC2 instance running the Compose prod layer + Nginx + TLS, with Postgres on an EBS volume and an IAM instance role for Bedrock. The alternative is ECS Fargate + RDS.

**Dev A: G10 escalation and handoff backend, and G12a deploy**
| # | Task | Done when |
|---|---|---|
| A1 | Escalation rules in `policies/escalation.yaml`, checked when routing and after each tool result:<br>• human request<br>• 2 failed clarifications → Atención<br>• legal or regulator words → Reclamos<br>• inactive customer → Atención<br>• bank-side block → Cobranza/Fraudes (replaces B's placeholder)<br>• unverified action<br>• another customer's data | One ES/PT test per rule, checking the queue and reason |
| A2 | Abstention: out of market (Pix, boleto, CPF, a Brazilian account) and out of scope → fixed facts + what the bot can offer | Pix → no tool called |
| A3 | Handoff packet built in code (the one-line request summary is the only LLM part) + `handoffs` table + `mode = human` + Redis pub/sub. The bot stops replying | Packet test: all fields present, facts only from read-backs, no transcript |
| A4 | Live-takeover backend: staff API (inbox by queue, claim, agent message, return to bot), agent stream, and agent messages relayed to the customer's stream | The API test for the round trip passes |
| A5 | AWS deploy v0: prod compose, Nginx + TLS, IAM role for Bedrock, golden DB restore, secrets, Budgets alarm, `make deploy`, demo-reset endpoint. `/test-idp` off | The public URL serves the D3 flows |

**Dev B: G9 disputes and fraud, and the handoff screens**
| # | Task | Done when |
|---|---|---|
| B1 | Postgres tools for disputes, following A's pattern (A reviews): transaction search with `fraud_score`, `create_claim` (appends to `bank.complaints` with `origin='app'`; amount, currency and date from the record) with read-back | The claim row matches the transaction exactly |
| B2 | Disputes & fraud workflow:<br>1. Choose the card → recent transactions → the customer picks.<br>2. **Suspected compromise (proposed rule):** ≥ 2 picked, or the card isn't in the customer's hands, or `fraud_score` > 30 (threshold kept in YAML). Then block (reusing G8) → claim → handoff to Fraudes.<br>3. Single charge: questions from `policies/disputes.yaml` → claim → case ID | ES/PT tests for both paths, no transactions, and a refused block |
| B3 | Customer widgets: transaction list (multi-select), handoff banner, bot/agent indicator with the agent's name | Rendered in the browser |
| B4 | Staff screens: staff login, live inbox per queue, claim, packet view, live chat, return to bot | See the end-of-day test |

**End-of-day test (public URL, two browsers)**
1. Customer: "no reconozco estas compras" → pick 2 → confirm the block → case ID → "te transfiero con Fraudes".
2. Agent: the case appears in the inbox → claim → the packet shows verified facts, actions, evidence and open questions → chat both ways → return to bot → the bot answers the next message.
3. A single unrecognized charge → case ID, and no handoff.
4. "¿Puedo pagar con Pix?" → abstains and offers alternatives. "Quiero hablar con una persona" → Atención. "Voy a demandar al banco" → Reclamos. Unlocking a bank-blocked card → Cobranza/Fraudes.
5. DB: the new complaint row has `origin = 'app'` and the transaction's exact amount.

**If behind:** A finishes the deploy on D5 morning, and today's test runs locally. B moves the single-charge questions to D5 and the return-to-bot button to D6.

---

### D5 · Thu 1 Oct — MVP gate
**Goal:** every item in the §4 checklist passes on the public URL, and `make eval` prints the first proposed-vs-baseline report.

**Dev A: G6b privacy and grounding, and G11 runner and baseline**
| # | Task | Done when |
|---|---|---|
| A1 | Harden `core/llm`:<br>• PII masking before every call (card numbers, document numbers, emails, phones, names → tokens), with an encrypted per-conversation vault that is unmasked only in the customer's view<br>• the client refuses unmasked input<br>• self-hosted Langfuse in the Compose observability layer (localhost, ADR-006) + its mask hook<br>• `audit.llm_calls` ledger (tokens, cost, latency, model, prompt version) | Unit tests; an LLM call with a raw card number raises an error |
| A2 | Grounding check in the reply writer: every number comes from a fact, the language matches, no raw PII → regenerate once → otherwise a safe template | An injected wrong amount is caught and never sent |
| A3 | Eval runner: a golden-DB clone per run, test-IdP sessions, deterministic checks (tools called and forbidden, DB state, confirm before act, read-back before "done", language, grounding, packet fields), metrics with n + Wilson CI, `report.md`, run metadata. `make eval SUITE= SYSTEM=` | A broken flow fails the right check |
| A4 | Keyword baseline (`SYSTEM=baseline`): clause split, precedence rules, negation window, ES/PT template replies, same tools and policy | Runs on the same cases as the proposed system |

**Dev B: decline explainer and G11 test sets**
| # | Task | Done when |
|---|---|---|
| B1 | Decline explainer: the most recent decline (or pick one), codes 51/14/05/54 from `policies/decline_codes.yaml`, 54 → offer replacement | ES/PT tests for all 4 codes + no declines |
| B2 | Scenario format (the labels from `05` §3) + scripted driver that plays a conversation through the API and handles the confirm/OTP events | A runs B's scenarios in A3 |
| B3 | Test sets:<br>• seeds per intent × category (the 10 categories in `05` §2), ES-MX/CO/AR, PT-BR, portuñol<br>• paraphrases by a non-Claude model<br>• ~80 dev + ~150 held-out, split by seed, no shared personas<br>• **both review 100% of held-out (~2 h each, afternoon)**<br>• freeze hash + CI check | The mix report hits the targets; a one-character change to held-out fails CI |

**End-of-day test = the MVP gate (§4)**, plus:
- `make eval SUITE=dev` for both systems → a report with a side-by-side table, CIs and failures.
- Numeric D1.5 targets are recorded in `05` §6 **before** any held-out run.
- No raw PII in any `audit.llm_calls` input from the dev run (a script checks this).

**If behind:** the gate items come first. The baseline's first run may move to D6 morning. D6 morning closes any gate gaps before new work starts.

---

### D6 · Fri 2 Oct — Survives failures and attacks
**Goal:** failures end in a safe fallback and a handoff, an expired session resumes, injected instructions in data are ignored, and the data pipeline reports its own quality.

**Dev A: G12b reliability, G4 resume, G6c injection, G2b data quality**
| # | Task | Done when |
|---|---|---|
| A1 | Retries (2, with backoff) and timeouts on LLM and tools. Fault flags `FAULTS=bedrock_timeout,cards_write_error,readback_mismatch`. Safe fallback template in ES/PT (no LLM) + handoff with the reason. `LLM_DISABLED` kill switch. Turn caps per conversation and per account/day | One test per fault: retry count in the audit log, fallback in the right language, handoff |
| A2 | Session expiry and resume: `401 session_expired` keeps the pending step. Re-login as the same customer replays the turn; another customer can't resume | API test |
| A3 | Injection hardening: tool output only inside data fences, an `injection_suspected` status, a graph test that nodes reading tool output have no write tools, and the eval-clone seeder that plants instructions in `merchant_name` and complaint text | The graph test fails if a write tool is added |
| A4 | Data quality: Pandera contracts on raw files, dbt tests (orphans flagged, accepted values, EDA semantic checks), a quality report per run, lineage docs, and 3 labeled test fixtures (late partition, schema change, duplicate batch) with tests | `make data` writes the report; the fixture tests pass |

**Dev B: G11 simulator, UI hardening, fixes**
| # | Task | Done when |
|---|---|---|
| B1 | Customer simulator: non-Claude model, temperature 0, plays the persona + fact sheet, stops at goal / handoff / abstention / 12 turns. Hand-check 10 transcripts | `make eval DRIVER=simulator SUITE=dev` runs |
| B2 | UI hardening: session-expired modal (re-login → resume), fallback and error states, loading states, mobile layout | Playwright covers expiry → resume |
| B3 | Dev cases for injection, tool failure and expired session (held-out is frozen and already has them) | Included in the dev run |
| B4 | Fix her workflows' failures from the D5 **dev** report | The dev report improves |

**End-of-day test**
1. `FAULTS=bedrock_timeout` → 2 retries in the audit log → fallback in the customer's language + handoff. `LLM_DISABLED=true` → every turn goes to the fallback.
2. Expire the session in the browser mid-block → modal → re-login → the flow resumes at the confirmation.
3. Seeded malicious `merchant_name` → shown as data; no action and no change in behavior.
4. `make data` → quality report + lineage. `pytest pipeline/tests` shows the fixtures behaving as expected.
5. `make eval DRIVER=simulator SUITE=dev` finishes.

**If behind:** A moves the turn caps and the schema-change fixture to D7. B leaves the mobile layout for later.

---

### D7 · Sat 3 Oct — Proven, and every answer explained
**Goal:** a held-out report exists (proposed ×3 vs baseline, with CIs, breakdowns and error analysis), the staff console explains any turn, and transaction search works.
**Rule:** fixes come only from **dev** failures. Nobody opens held-out failures to tune prompts (R9).

**Dev A: G13 timeline API and the held-out report**
| # | Task | Done when |
|---|---|---|
| A1 | Timeline API: conversation list with filters (language, country, intent, outcome, escalation, date). Per-turn timeline from the audit log + LLM ledger: intent result, rules hit, tools, sources, policy hash, model/prompt version, latency, cost, Langfuse link. System metadata. Admin persona lookup | Filter counts match a SQL check |
| A2 | Held-out runs:<br>• proposed ×3 + baseline on the same cases<br>• intent detection vs keyword on `eval/nlu/`, plus 2 Bedrock models compared<br>• breakdowns by language and segment<br>• every number labeled offline / simulation / projection<br>• chosen model per step recorded in the decision log | `eval/reports/heldout-<sha>/report.md` |

**Dev B: G14 transactions, priority flags, traceability screens, judge**
| # | Task | Done when |
|---|---|---|
| B1 | Transaction search. Dates are resolved in code in the customer's time zone, and merchants fuzzy-matched against the 24 known names. Amount ±10%, maximum 12 months, widen once if nothing is found. Also the pending/reversal explainer | "el cargo de Super Ahorro del martes pasado por unos 350" finds it |
| B2 | Priority flags on claims: repeat complainer, regulator, amount above the threshold, Critical → always handed off to Reclamos | ES/PT test per flag |
| B3 | Traceability screens: list + filters + per-turn timeline | See the end-of-day test |
| B4 | LLM judge + rubric. **~50 human labels, both of you (~1 h)** → agreement rate | The agreement report exists; if κ < 0.6 the judge is reported as weak |

**End-of-day test**
1. Staff console → any conversation → any turn → "why" with sources, rules and the Langfuse link.
2. Browser: transaction search by merchant, date and amount. A pending transaction is explained.
3. A repeat-complainer persona files a claim → Reclamos.
4. The held-out report is complete.

**If behind:** keep the evidence (A2, B4), and drop the pending/reversal explainer first, then transaction search.

---

### D8 · Sun 4 Oct — Ready to submit (code freeze 18:00)
**Goal:** `main` is frozen and deployed, a fresh clone works using only the README, and the slides and video are done.
**Rule:** new features (the §6 backlog) only if the D7 held-out report shows 0 unsafe outcomes. Otherwise the day goes to fixes from **dev** failures.

| Dev A | Dev B |
|---|---|
| Notebooks (D1.1–D1.6: contact reasons, demand, data quality, operational constraints, call-center baseline, projected cost per resolution), `make notebooks` | Error analysis + intent-detection-vs-keyword section of the report |
| README: what it is, URL, quickstart, architecture, where AI is used and where it isn't, safety rules, results, limitations, remaining work (S6 / D6.5) | Slides (4–6) and video script from the strongest features |
| Final deploy + demo reset, code freeze at 18:00 | **Evening, both:** record the video |

**End-of-day test:** a fresh clone following only the README → a working stack. The full §4 checklist passes on the URL in ES and PT. The slides and video are exported.

### D9 · Mon 5 Oct — Submit
- If code changed after the D7 held-out run, rerun held-out on the frozen commit and update the report.
- `make demo-reset` on prod, then a smoke test of the three behaviors in ES and PT.
- Submission email to hackathon.admin@factored.ai: repo, URL, slides, video, persona emails/passwords and the OTP code. **Credentials go in the email only, never in the repo.**

---

## 4. MVP gate checklist (end of D5)

If everything after D5 failed, this is what we'd submit.

- [ ] Public HTTPS URL. Landing → login as a persona, with an ES/PT UI
- [ ] ES (MX/CO/AR), PT-BR and portuñol conversations for:
  - card info (status, balance, due date, min payment; debit says credit-only)
  - block/lock/unlock/replacement with confirmation, read-back and OTP where needed
  - decline explainer
  - unrecognized charges → block + claim → Fraudes takeover
  - out-of-market / out-of-scope abstention
  - human request
- [ ] A staff agent claims a handoff, chats live and returns the conversation to the bot
- [ ] Unit tests for R1–R5 and R12 green. Only masked text reaches the LLM
- [ ] `make data` reproduces the golden DB. Langfuse (local) and the audit log record every turn. LLM calls go through Bedrock
- [ ] Held-out frozen (hash + CI check). Dev report for proposed vs baseline, with CIs. D1.5 targets recorded
- [ ] The README quickstart works on a fresh clone

## 5. Feature-list coverage

| Section | Feature | Group | Built on (dev) |
|---|---|---|---|
| Identity & session | Mock identity provider and session token | G4, G5 | D2 A (API), D3 B (landing + login) |
| | Session expiry and resume | G4, G5 | D6 A (backend), D6 B (modal) |
| | Card picker | G7, G5 | D1 B (logic), D3 B (widget) |
| Transactions | Decline explainer | G7 | D5 B |
| | Natural-language transaction search | G14 | D7 B |
| | Pending and reversed explainer | G14 | D7 B |
| | Duplicate-charge detector | — | Backlog |
| Blocks & card controls | Instant lost/stolen block | G8 | D2 B (sandbox), D3 A (real tools) + B (UI) |
| | Temporary lock vs permanent block | G8 | D2 B, D3 |
| | Unblock with reason check | G8, G10 | D2 B, D3 (OTP), D4 A (bank-side handoff) |
| | Suspected-fraud triage | G9 | D4 B |
| | Travel notice · Spending limits | — | Backlog |
| Card information | Card Doctor | — | Backlog |
| | Card status and details | G7 | D1 B |
| | Balance, due date and minimum payment | G7 | D2 B |
| | Expiry and renewal · Benefits by segment | — | Backlog |
| Card lifecycle | Replacement and reissue | G8 | D2 B (sandbox), D3 (real + OTP) |
| | New card activation · PIN reset · Cancel with a retention offer · Credit limit increase request | — | Backlog |
| Ask for a credit card | Card finder · Pre-qualification through a policy service · Missing-income path | — | Backlog |
| Disputes & claims | Unrecognized-charge intake | G9 | D4 B |
| | Priority flags | G9 | D7 B |
| | Recognize before you dispute | — | Backlog (#2) |
| Handoff & agent assist | Structured handoff packet | G10 | D4 A (packet), D4 B (packet view) |
| | Explicit escalation rules | G10 | D4 A |
| | Agent copilot panel | — | Backlog |
| Language & channels | ES and PT-BR with a regional lexicon | G3, G11 | D1 B (prompt), D5 A (keyword lexicon), D5 B (regional test cases) |
| | Per-turn language detection and code-switching | G3 | D1 B, tested from D5 |
| | Out-of-market requests | G10 | D4 A |
| | Localized money and dates | G7 | D2 B |
| | Channel-aware replies · Plain-language mode | — | Backlog |
| Safety, eval & ops | Policy engine outside the model | G6 | D3 A |
| | Customer-scoped tools | G6 | D2 A (reads), D3 A (writes) |
| | Verified read-back | G6 | D3 A |
| | PII minimization | G6 | D5 A |
| | Injection hardening, including data fields | G6 | D6 A |
| | Tracing and audit timeline | G3, G6, G13 | D1 B (LLM client), D3 A (audit log), D5 A (Langfuse), D7 A + B (console) |
| | Bounded retries and safe fallback | G12 | D6 A |
| | Evaluation harness | G11 | D5 A + B, D6 B, D7 A |
| | Intent classifier vs keyword baseline | G11 | D5 A (baseline), D7 A (report), D8 B (error analysis) |
| | Customer simulator | G11 | D6 B |
| | Ops scorecard | G11 | D7 A (in the report); UI in the backlog |
| Others | Control and traceability of LLM | G10, G13 | D4 (inbox + takeover), D7 (console) |

Required by the hackathon but not in the feature list: data pipeline (D1, D6 · A), deployment (D4 · A), cost guard (D2 login rate limit, D4 Budgets alarm, D6 turn caps + kill switch · A), data analysis D1.x (D8 · A), deliverables K1–K5 (D8–D9 · both).

## 6. Backlog (Stretch, in order)

Taken only on D8, and only when the D7 held-out report shows 0 unsafe outcomes. Each item needs a workflow, a policy file and at least 2 dev cases, or it doesn't ship.
1. Answer node for side questions (read-only, max 3 tool calls, no write tools)
2. Recognize before you dispute
3. Card Doctor
4. Expiry and renewal
5. Agent copilot panel
6. The rest of the Stretch list

## 7. Risks

| Risk | Signal | Mitigation |
|---|---|---|
| Bedrock access or quotas missing | K2 fails on D1 | Switch region the same day and request quota. B keeps going on the Anthropic API (ADR-028) |
| The Bedrock switch changes behavior | Sandbox answers or structured outputs differ after the switch | Switch as soon as K2 passes, not on deploy day. Rerun B's scripted conversations on both providers |
| A overloaded on D4–D6 | End-of-day tests slip twice in a row | Apply the cut lines. B already builds the disputes tools on D4; B can also take the data-quality fixtures on D6 |
| Deploy slips | No URL at the end of D4 | A finishes it on D5 morning. The gate needs the URL |
| Held-out review takes longer than 2 h | Test sets not finished at 16:00 on D5 | Shrink held-out to ~120 while keeping the mix. Never skip review |
| Slow replies | p95 > 8 s in the D5 report | Smaller model for intent detection, shorter replies. Report it honestly |
| Scope creep | Unsafe outcomes in the D7 report | The D8 rule: fixes only |

## 8. Decision log during the build

| Day | Decision | Proposal |
|---|---|---|
| D1 | Bedrock region, model per step | Haiku 4.5 for intent detection and replies to start |
| D1–D4 | When B's connection moves from the Anthropic API to Bedrock (ADR-028) | As soon as K2 passes; before the D4 deploy at the latest |
| D4 | Whether the public deployment runs Langfuse too (ADR-006) | Decided with the AWS setup |
| D5 | When self-hosted Langfuse is set up | A adds it with D5 A1 (mask hook). Earlier if the observability layer has room |
| D1 | Time zone of `transaction_date` | A decides while building A5 |
| D2 | Minimum payment formula (synthetic) | `max(5% × balance, floor)` with floors USD 10 / COP 40.000 / ARS 5.000, plus overdue amounts when `days_past_due > 0` |
| D2 | Final persona list | B's 10 + ~20 found by query |
| D4 | AWS setup (ADR-017) | Single EC2 + Compose + IAM role |
| D4 | Suspected-compromise rule | ≥ 2 transactions picked, or card not in hand, or `fraud_score` > 30 |
| D5 | D1.5 numeric targets | After the first dev run |
| D5–D6 | Paraphrase, simulator and judge model family | Non-Claude Bedrock family, picked on D5 |
| D7 | Final model per step | From the held-out model comparison |
