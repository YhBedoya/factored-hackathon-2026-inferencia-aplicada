# 06 — Engineering rules

## 1. Non-negotiable rules

| # | Rule | Why | Enforced by |
|---|---|---|---|
| R1 | `customer_id` comes **only** from the session context. No tool, route or prompt accepts it from the LLM or the chat | B5, B6 | Tool registry signature check (unit test) + import-linter + unauthorized-access eval cases |
| R2 | No side-effecting tool runs without a server-issued, single-use confirmation token (plus OTP step-up where `tools.yaml` says so) | D3.2 | Tool executor + unit tests |
| R3 | The bot never reports an action as done without a verified read-back | D2.5 | `ActionResult.verified` required by the composer + eval check |
| R4 | Money, dates and card masks are formatted in code and inserted through placeholders. The LLM never writes them | Correctness, localization | Composer grounding check (every number must come from facts) |
| R5 | Only tokenized text goes to Bedrock or Langfuse | B3 | `core/llm` client refuses un-masked input (vault check) + Langfuse `mask` hook + unit tests |
| R6 | Tool output enters prompts only inside data fences, and LLM nodes that read tool output have **no write tools** | Injection | Graph construction test + adversarial eval suite |
| R7 | Every LLM call pins the model ID, prompt version and temperature, and is traced (Langfuse + audit `llm_calls`) | E2, D6.1 | `core/llm` is the only way to call Bedrock (import-linter) |
| R8 | Policy lives in versioned YAML with a `provenance` header. The model never decides eligibility, limits, escalation or permissions | B7, D3.4 | Startup validation + code review |
| R9 | The held-out suite is frozen. Nobody tunes prompts or flows against it | D5.1, D4.8 | Suite hash in the repo + CI check that held-out files are unchanged |
| R10 | Never commit secrets, raw data, credentials exports or the official dictionary PDF | B3, K1 | `.gitignore`, pre-commit secret scan (gitleaks), CI |
| R11 | Bounded retries only: 2 retries with backoff, then safe fallback + handoff. Never an invented answer | D6.2, D6.3 | `core/llm` and tool executor wrappers |
| R12 | Provided tables are changed only through domain services: an in-place update always writes a history row in the same transaction, and appended rows carry `origin='app'` | Lineage, audit | Repository layer + review |
| R13 | Nothing is copied from deepflow or other proprietary repos. It is a style reference only | IP (public repo) | Review |

## 2. Architecture enforcement (import-linter)

Contracts in `backend/.importlinter`, run in pre-commit and CI:
- **Layers:** `app.api` → `app.domains` → `app.core`. Core never imports domains.
- **Independence:** bank domains (`cards`, `transactions`, `disputes`, `customers`) don't import each other's repositories. They can only call each other through their `service` modules.
- `app.domains.conversation` may reach bank data **only** through `app.domains.conversation.tools` (the registry). It may not import any bank `repository`.
- Only `app.core.llm` may import `boto3` / `aioboto3` Bedrock clients and `langchain_aws`.
- `app.core.llm` does not import `app.domains.*.repository` (LLM code can't touch the DB).

## 3. Repository layout

```
backend/
  app/
    api/            router registration, deps
    core/           config, db, security, logging, telemetry, llm/, crud base
    domains/        identity, customers, cards, transactions, disputes, handoff,
                    policy, safety, localization, conversation, audit
    alembic/        migrations (all schemas)
  tests/unit/…  tests/integration/…  (integration = ephemeral DB)
frontend/
  src/pages/ components/{ui,common,layout,<domain>}/ hooks/ routes/ lib/ client/ (generated)
pipeline/           ingest/, contracts/ (Pandera), dbt/ (dbt-duckdb project), load/, fixtures/, tests/
policies/           *.yaml (team-generated synthetic)
eval/               scenarios/{dev,heldout}/, nlu/, personas.yaml, simulator/, baseline/, judges/, reports/
docker/             docker-compose.{base,dev,test,prod,observability}.yml, nginx/
notebooks/          EDA (aggregates only, no PII printed)
docs/solution-docs/ this design
Makefile  CLAUDE.md (+ backend/, frontend/, pipeline/, eval/ scoped)  .mcp.json  .env.example
```

## 4. Conventions

- **Python 3.12**, `uv`, Ruff (lint + format), mypy (strict on `core/`, `policy/`, `conversation/`) **(proposed)**. Everything async on request paths. No blocking I/O in graph nodes.
- **FastAPI:** versioned routes under `/api/v1`, Pydantic request/response schemas per domain, typed error responses.
- **LangGraph:** one subgraph per flow in `conversation/flows/<flow>.py`. Nodes are small pure-ish functions over state. Checkpoints must be idempotent: side-effecting nodes use idempotency keys.
- **Prompts:** files in `conversation/prompts/<step>@v<N>.md` with version bumps on every change. The prompt version is logged. Examples are in ES and PT.
- **Frontend:** React 19 + Vite + TanStack Router/Query, React Hook Form + Zod, Radix + Tailwind v4 (CSS-first tokens), Biome. Generated API client (`@hey-api/openapi-ts`), regenerated whenever backend schemas change. No hand-edited generated files.
- **Commits:** Conventional Commits (`feat(cards): …`, `fix(conversation): …`), enforced by a pre-commit hook.
- **Logging:** structlog JSON, never log unmasked PII. Include `request_id`, `trace_id`, `conversation_id`.

## 5. Git workflow

- Short-lived feature branches off `main` (`feat/<domain>-<topic>`), a PR for every change, **one reviewer**, green CI required, **squash merge**.
- CI: Ruff, Biome, mypy, import-linter, unit tests, integration tests (ephemeral DB), gitleaks, the held-out freeze check, `dbt build` on a sample fixture.
- `main` must always be deployable. Nobody commits directly to `main`.

## 6. Testing standards

- Unit tests for every rule R1–R6 and R11 (they are the safety case).
- Flow tests: each MVP flow has scripted-turn tests in ES and PT covering the happy path, clarification, denial and failure (fake LLM with fixed NLU outputs, so they're deterministic and free).
- Integration tests against an ephemeral Postgres + Redis started from a small fixture DB.
- E2E (Playwright): login → block card → read-back; session expiry → resume; handoff → agent takeover.
- Eval suites (`05`) run on demand and before every submission milestone. They are not part of every CI run (cost).

## 7. Definition of done (per feature)

1. Flow and tools implemented behind the policy engine, following R1–R12.
2. Unit and flow tests in ES and PT pass. At least one dev-suite scenario per behavior.
3. Audit events and traces visible in the staff console timeline.
4. Contracts (`04-contracts.md`) and the intent catalog (`02`) updated if they changed.
5. Reviewed and squash-merged with green CI.
