# CLAUDE.md

AI-first **card-support** service for **Swip**, a fictional card fintech built on the synthetic LATAM Bank dataset (Factored AI & Data Hackathon 2026). The assistant is **Cardy**; voice and visual identity live in [`docs/brand.md`](docs/brand.md). It speaks Spanish (MX/CO/AR) and Brazilian Portuguese. The repo is **public**.

**Status:** implementation in progress. The D1-A platform (`make setup`, `up`, `down`, `data`, `demo-reset`, `client`, `check`, `test`) exists — see [`README.md`](README.md) for the steps to run it. `make eval` is still planned.

## Read first
- Design index: [`docs/solution-docs/README.md`](docs/solution-docs/README.md)
- Rules you must follow: [`docs/solution-docs/06-engineering-rules.md`](docs/solution-docs/06-engineering-rules.md)
- Hackathon rules and requirement IDs: the `hackathon-judge` skill (`.claude/skills/hackathon-judge/`)

## Critical rules (summary; the full list is in 06)
- `customer_id` comes only from the session, never from the LLM or the chat.
- Side effects need a server-issued confirmation token. Say "done" only after a verified read-back.
- Money, dates and card masks are formatted in code. Only tokenized (PII-masked) text goes to the LLM provider or Langfuse.
- LLM nodes that read tool output have no write tools. Policy lives in `policies/*.yaml`, never in prompts.
- Never commit secrets, `data/`, credential exports or `docs/official-docs/LATAM_Bank_Complete_Data_Dictionary.pdf` (it contains S3 keys).
- Never edit `eval/scenarios/heldout/`. It is frozen.

## Stack
FastAPI + SQLModel/asyncpg + Alembic + Redis · LangGraph (Postgres checkpointer) + Amazon Bedrock (Anthropic API until Bedrock is set up, ADR-028) · React 19 + Vite + TanStack · dbt-duckdb + Pandera · Docker Compose + Nginx · OTel → VictoriaMetrics/Logs/Traces · Langfuse self-hosted in Docker (not needed to start, ADR-006).

## Planned commands
See [`README.md`](README.md) for prerequisites, `.env` setup and what each command does.
```bash
make setup      # install toolchains, pre-commit
make data       # S3 → pipeline → Postgres → golden DB (AWS creds from env/profile)
make up         # dev stack with hot reload + observability
make check      # lint + types + import-linter + unit tests
make eval SUITE=dev SYSTEM=proposed
```

## Development flow
Build work runs through `/wave-run <card>` (`.claude/skills/wave-run/`). A card is a task row (`D1-A5`) or a day track (`D2-B`) of [`07-execution-plan.md`](docs/solution-docs/07-execution-plan.md). The flow is spec (gate) → plan → one fresh implementer per task → independent verifier (gate), with specs in `docs/specs/` and plans in `docs/plans/`. To reproduce the dev environment a task runs against, see [`README.md`](README.md).
- **Keep tests minimal.** We need to pivot fast. Test only the safety rules a change touches (R1–R6, R11, R13) and the card's "Done when" lines, plus one ES and one PT happy path per flow, always with a fake LLM. Each task runs only its own tests. The full suite runs once per card.
- When a choice isn't settled by the docs, ask. Don't pick the plausible option.

## Where code goes
Backend domains: `backend/app/domains/<name>/` · shared: `backend/app/core/` · LLM access only via `backend/app/core/llm/` · flows: `backend/app/domains/conversation/flows/` · policies: `policies/` · pipeline: `pipeline/` · eval: `eval/`.
