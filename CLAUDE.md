# CLAUDE.md

AI-first **card-support** service for the synthetic LATAM Bank (Factored AI & Data Hackathon 2026), in Spanish (MX/CO/AR) and Brazilian Portuguese. The repo is **public**.

**Status:** design complete, implementation not started. The commands below are planned and don't exist yet.

## Read first
- Design index: [`docs/solution-docs/README.md`](docs/solution-docs/README.md)
- Rules you must follow: [`docs/solution-docs/06-engineering-rules.md`](docs/solution-docs/06-engineering-rules.md)
- Hackathon rules and requirement IDs: the `hackathon-judge` skill (`.claude/skills/hackathon-judge/`)

## Critical rules (summary; the full list is in 06)
- `customer_id` comes only from the session, never from the LLM or the chat.
- Side effects need a server-issued confirmation token. Say "done" only after a verified read-back.
- Money, dates and card masks are formatted in code. Only tokenized (PII-masked) text goes to Bedrock or Langfuse.
- LLM nodes that read tool output have no write tools. Policy lives in `policies/*.yaml`, never in prompts.
- Never commit secrets, `data/`, credential exports or `docs/official-docs/LATAM_Bank_Complete_Data_Dictionary.pdf` (it contains S3 keys).
- Never edit `eval/scenarios/heldout/`. It is frozen.

## Stack
FastAPI + SQLModel/asyncpg + Alembic + Redis · LangGraph (Postgres checkpointer) + Amazon Bedrock · React 19 + Vite + TanStack · dbt-duckdb + Pandera · Docker Compose + Nginx · OTel → VictoriaMetrics/Logs/Traces · Langfuse Cloud.

## Planned commands
```bash
make setup      # install toolchains, pre-commit
make data       # S3 → pipeline → Postgres → golden DB (AWS creds from env/profile)
make up         # dev stack with hot reload + observability
make check      # lint + types + import-linter + unit tests
make eval SUITE=dev SYSTEM=proposed
```

## Where code goes
Backend domains: `backend/app/domains/<name>/` · shared: `backend/app/core/` · LLM access only via `backend/app/core/llm/` · flows: `backend/app/domains/conversation/flows/` · policies: `policies/` · pipeline: `pipeline/` · eval: `eval/`.
