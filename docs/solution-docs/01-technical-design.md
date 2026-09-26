# 01 — Technical design

## 1. Problem and scope

**Workflow:** card-service support for LATAM Bank customers in Mexico, Colombia and Argentina, in Spanish (MX/CO/AR variants) and Brazilian Portuguese. The feature shortlist lives in [`features-list.md`](features-list.md). This document covers the MVP items and leaves room for the Stretch items.

**The three mandatory behaviors (S3a–c):**

| Behavior | Example in our workflow |
|---|---|
| Normal resolution | "Bloquea mi tarjeta, la perdí" → confirm card → confirm action → block → read-back → done |
| Ambiguous / unsupported | "Quiero bloquear mi tarjeta" → *pause it or cancel and replace?*; "¿Puedo pagar con Pix?" → out-of-market abstention with alternatives |
| Human required | "No reconozco estas compras" → list, block, draft claim → live takeover by a Fraudes agent with a structured packet |

**Design principle:** *LLM at the edges, rules in the middle.* The LLM understands and phrases. Code decides, acts, verifies and escalates. Permissions and policy never depend on model output (D3.4, B6).

## 2. Architecture overview

```
┌──────────────────────── frontend (React 19 + Vite + TanStack) ────────────────────────┐
│ landing · login · OTP step-up · customer chat · staff console (inbox, live takeover,  │
│ audit timeline, persona catalog, scorecard)                                           │
└──────────────┬───────────────────────────────────────────────────────▲────────────────┘
               │ HTTPS (httpOnly JWT cookie + CSRF)                    │ SSE (per conversation)
┌──────────────▼───────────────────── backend (FastAPI, modular monolith) ──────────────┐
│ identity ── session → customer_id (never from chat)                                   │
│ conversation: LangGraph turn graph                                                    │
│   load_session → mask_pii → understand (LLM) → route ─┬─► flows/* (deterministic)     │
│                                                       ├─► answer node (read-only LLM) │
│                                                       └─► handoff (live takeover)     │
│   → compose (LLM phrasing + code formatting + grounding check) → unmask → emit        │
│ policy (YAML) · safety (token vault, data fencing) · localization · audit             │
│ bank tools (customer-scoped): cards · transactions · disputes · customers             │
│ core/llm: Bedrock model registry, retries, cost, Langfuse                             │
└────────┬──────────────────────┬─────────────────────┬─────────────────────────────────┘
         │                      │                     │
   PostgreSQL 16          Redis 7                Amazon Bedrock  ── masked text only
   bank · app · audit ·   confirmation tokens,   Langfuse Cloud  ── masked text only
   identity · langgraph   OTP, pub/sub, limits   OTel → VictoriaMetrics/Logs/Traces
         ▲
   pipeline: S3 → Parquet (manifest) → Pandera → dbt-duckdb → date shift → Postgres → golden DB
```

## 3. Where AI is used and where it isn't (P3)

| Step | Implementation | Why |
|---|---|---|
| Authentication, session, customer scoping | Deterministic (identity + tool registry) | Hard rules B5/B6. A model must never be able to choose whose data it reads |
| Language detection, intent, slot extraction | **LLM**, one structured-output call per turn | Handles portuñol, voseo and regional vocabulary far better than keyword rules. Output is a closed enum, validated by Pydantic |
| Clarification and escalation decisions | Deterministic rules on NLU labels + counters | D3.3: explicit, testable rules instead of model judgment |
| Flow control (confirm → act → verify) | Deterministic LangGraph subgraphs | Enforced ordering, resumable pending step, reproducible evals |
| Policy (allowed tools, limits, min payment, decline explanations) | Versioned synthetic YAML + code | B7, D3.4. The model never invents policy |
| Natural-language transaction search | LLM extracts a filter, code validates and runs it | The LLM never writes SQL. Dates are resolved in code, in the customer's time zone |
| Informational follow-ups | **LLM answer node** with read-only tools, max 3 calls, no write tools | Flexibility for digressions without write risk |
| Reply wording | LLM composer from a fact list, with placeholders | Natural tone in the right language and register |
| Money, dates, masked card numbers | Code (Babel), filled into placeholders | No hallucinated amounts or wrong formats |
| Handoff packet | Deterministic assembly. LLM writes only the one-line request summary | D3.5 fields come from verified records |
| Learned component (D4.6) | **OPEN**: see decision-log ADR-005 | — |

## 4. Domains (bounded contexts)

Modular monolith following the deepflow conventions (used as a guide only, nothing copied): `backend/app/domains/<name>/` with `models.py`, `schemas.py`, `routes.py` and optional `repository.py`, `service.py`, `deps.py`. `backend/app/core/` holds shared infrastructure.

| Domain | Owns | Depends on |
|---|---|---|
| `identity` | Login, JWT cookie sessions, session expiry/resume, OTP step-up, roles (`customer`, `agent`, `admin`), test-IdP endpoint for eval (disabled in prod) | `core` |
| `customers` | Masked customer profile read model | `core` |
| `cards` | Card read model, temporary lock / permanent block / unlock, replacement, `card_status_history`, `card_controls`; Stretch: activation, PIN-reset link, travel notices, limits | `policy`, `audit` |
| `transactions` | Structured search, decline / pending / reversal explanations, duplicate detector (Stretch) | `policy` |
| `disputes` | Claim intake (appends to `bank.complaints` with `origin='app'`), priority flags | `transactions`, `policy`, `audit` |
| `handoff` | Packet assembly, queues, agent inbox, live takeover, return-to-bot | `audit`, `conversation` events |
| `policy` | Loads `policies/*.yaml`; intent→tool allowlist, confirmation / step-up requirements, escalation rules, synthetic formulas; issues and consumes confirmation tokens | `core` |
| `safety` | Per-conversation reversible PII token vault, data fencing for tool output, injection heuristics | `core` |
| `localization` | Money / date / card-mask formatting per country, regional lexicon, MXN estimate | `core` |
| `conversation` | Conversations, messages, LangGraph turn graph, SSE endpoint, tool registry | everything above, **only through public service interfaces and the tool registry** |
| `audit` | Append-only audit events, timeline API for the staff console, `llm_calls` ledger | `core` |
| `core/llm` | Bedrock model registry (per-step model IDs), bounded retries, cost accounting, Langfuse client | `core` |

Outside `backend/`: `pipeline/` (data), `policies/` (synthetic YAML), `eval/` (suite, simulator, baseline, judges), `frontend/`. See [`06-engineering-rules.md`](06-engineering-rules.md) for the layout and the import contracts that enforce these boundaries.

## 5. Request lifecycle (one customer turn)

1. `POST /api/v1/conversations/{id}/messages`. `identity` validates the cookie. If the session has expired, the API returns `401 session_expired`, the pending graph state stays in the checkpointer, and after re-login **as the same customer** the turn is replayed and the flow resumes at its pending node.
2. The graph runs inline (async) and streams events over `GET /conversations/{id}/stream` (SSE): `status` → `message` → `ui` (card picker, confirmation buttons) → `done`.
3. `mask_pii` replaces PII with per-conversation tokens (`⟨CARD_1⟩`, `⟨DOC_1⟩`…) held in the Fernet-encrypted vault.
4. `understand`: one Bedrock call returns `{language, intents[], status, slots, clarification}` (schema in `04-contracts.md`).
5. `route`: deterministic rules decide between continuing the pending flow, starting a new flow (intent queue for multi-intent turns), the answer node, clarification, or escalation.
6. Flow / answer node calls **bank tools** through the tool registry. The registry injects `customer_id` from the session, checks the policy allowlist, and requires a confirmation token (plus OTP step-up where configured) for side effects.
7. Side effects are followed by a **verified read-back**. A mismatch leads to handoff with `action_unverified`, never "done".
8. `compose`: the LLM writes the reply from a fact list with placeholders. Code fills money, dates and masks, and runs grounding checks (every number in the reply must come from a fact, the reply language must match, no raw PII). Tokens are re-hydrated server-side only for the customer's view.
9. The message is persisted and audit events are written (rule hits, tool calls + results, sources, policy version, model + prompt versions, Langfuse trace ID).

Latency target **(proposed)**: p50 ≤ 3 s, p95 ≤ 8 s end-to-end per turn, with at most 2 LLM calls on flow turns and at most 5 on answer-node turns.

## 6. Security and privacy (P1, B3–B6, D6.5)

- **Identity (B5):** mock IdP. Credentials are generated for every customer at load time (low-cost hash, exported only to a git-ignored file and the admin-only persona lookup). Email + password gives a JWT in an httpOnly cookie with CSRF double-submit. A simulated OTP (delivered to a dev inbox page) is required for step-up actions: address change, activation, unlock, travel notice. A document number or customer ID alone never authenticates anyone.
- **Record isolation (B6):** tools never accept `customer_id`. The registry binds it from the session. Every repository query filters by it. A request for another customer's card returns a refusal and writes an `access_denied` audit event.
- **PII minimization (B3):** only tokenized text goes to Bedrock and Langfuse. The Langfuse SDK `mask` hook redacts again as a second line of defense. Sensitive columns (document number, email, phone, address) are Fernet-encrypted at rest **(proposed)**.
- **Prompt injection:** user text only selects a flow, and flows enforce policy on their own. Tool output (e.g., `merchant_name`, complaint text) goes into prompts inside explicit data fences, and **LLM nodes that read tool output have no write tools**. An adversarial suite covers direct and data-field injection.
- **Secrets:** AWS access through an IAM role / profile, never keys in code. `.env` stays local, with `.env.example` committed. The official data-dictionary PDF is git-ignored.
- **Retention (proposed):** vault entries are purged 24 h after a conversation closes. Conversations and audit are kept 30 days in the demo environment. Langfuse project retention is set to 30 days. The eval DB clones are dropped after each run.

## 7. Reliability (D6.2, D6.3)

- **Bounded retries:** Bedrock and tool calls get 2 retries with exponential backoff and jitter, plus per-call timeouts **(proposed: LLM 20 s, tools 3 s)**. Write tools carry idempotency keys, so retries can't double-apply.
- **Safe fallback:** when retries are exhausted, a template message in the customer's language (no LLM involved) plus a handoff packet with `reason = tool_failure | llm_unavailable`. The system never invents an answer.
- **Verification:** "done" only after a read-back matches the expected state.
- **Tool-failure fixtures:** fault injection via a config flag (`FAULTS=bedrock_timeout,cards_write_error`) for eval scenarios.

## 8. Observability and audit (D6.1, D6.6)

| Signal | Where | Content |
|---|---|---|
| LLM generations | Langfuse Cloud | Masked prompts/outputs, model ID, prompt version, tokens, cost, latency, eval scores |
| Infra traces, logs, metrics | OTel → VictoriaTraces / VictoriaLogs / VictoriaMetrics (+ Grafana) | FastAPI, SQLAlchemy, Redis, httpx spans; structlog JSON with `request_id` / `trace_id` / `conversation_id` |
| Business audit | Postgres `audit.audit_events`, `audit.llm_calls` | Rule hits, policy version hash, tool calls + results, confirmations, read-backs, handoffs, sources cited per reply |
| Staff console | Frontend `/staff/*` | "Why did the bot say this?" timeline built from audit events plus a link to the Langfuse trace, **never chain-of-thought** |

MCP servers (VictoriaLogs, VictoriaTraces, Playwright, DeepWiki) in `.mcp.json` let coding agents query the running system during development.

## 9. Operations (D6.4, D6.5)

- **Reproducible setup:** `make setup` → `make data` (S3 sync with credentials from env/profile → pipeline → golden DB) → `make up`. Versions pinned (uv.lock, package-lock), seeds fixed.
- **Environments:** Docker Compose layers `base / dev / test / prod / observability`.
- **Deployment target: OPEN** (decision-log ADR-017). Must provide a public URL (K2) and Bedrock access through an IAM role.
- **Capacity:** to be measured with the eval harness (turns/s per worker, DB size ≈ all 13 tables + indexes). `digital_events` (10M rows) dominates storage.
- **Remaining work before real deployment** (kept honest for S6): a real IdP and fraud-grade authentication, security review / pentest, regulatory review of dispute handling, load testing, multi-region, human-agent workforce integration, real PT-BR market data.

## 10. Data and language limitations (S5)

- All LatAm Bank data is **synthetic**. Evaluation utterances, Portuguese content and policies are **team-generated** (B2).
- **No Portuguese** in the data. PT-BR speakers are modeled as customers of MX/CO/AR accounts. Brazil-only products (Pix, boleto) are out of market.
- Text fields are templated: `complaints.description` has 5 distinct values and `call_transcripts.customer_text` has 42. They're unusable for intent labels.
- Labels carry almost no signal: `priority` is independent of every other field, and `is_fraud` is deterministic above `fraud_score` 30 and random noise below it.
- Only 24 merchant names, and 77% of transactions have none.
- All Mexican cards are denominated in **USD**. MXN is shown only as a labeled estimate.
- Observed values deviate from the dictionary: Spanish enum values ("Tarjeta Crédito"), missing transcript columns, row counts 84–156% of documented.
- Dates are shifted at load (whole weeks) so the data ends on deploy day. All "now" behavior is simulated.

## 11. Open items

| ID | Item | Blocks |
|---|---|---|
| ADR-005 | Learned component evaluated against a baseline (D4.6). Candidate: local fallback intent classifier | Hard ML requirement |
| ADR-017 | Deployment target | K2 |
| — | Exact Bedrock model IDs per step (benchmark on the dev set) | Latency/cost numbers |
| — | Time zone semantics of `transaction_date` (EDA saw a UTC-vs-local `process_date` shift) | Relative-date search correctness |

## 12. Requirements traceability

| Req | Covered by |
|---|---|
| S1–S3 | §1, `02-conversation-design.md` flows |
| S4, S5 | ES/PT NLU + composer, PT eval share (`05`), §10 |
| P1–P3 | §3, §6, §7, decision log |
| D1.1–D1.6 | EDA notebooks + call-center operational baseline (`05` §3) |
| D2.1–D2.5 | Checkpointed flows, clarification rules, grounded composer, typed tools, read-back |
| D3.1–D3.5 | Intent catalog, confirmation tokens, escalation rules, policy engine, handoff packet (`04`) |
| D4.1–D4.5 | `03-data-architecture.md` (dbt, Pandera, lineage, freshness fixture) |
| D4.6–D4.10 | LLM NLU vs keyword baseline, **learned component OPEN**, seed-grouped splits, error analysis |
| D5.1–D5.3 | `05-evaluation-plan.md` suite categories |
| D6.1–D6.6 | §7, §8, §9 |
| B1–B8 | §6, §10; B7 applies only if the Stretch credit features are built |
| E1–E11 | `05-evaluation-plan.md` §5 |
| K1–K6 | Public repo, deployment (OPEN), slides and video (outside these docs) |
