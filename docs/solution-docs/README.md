# Solution docs — LATAM Bank Card Support

Technical design for our Factored AI & Data Hackathon 2026 submission: an AI-first **card-support** service for the synthetic LATAM Bank (Spanish + Portuguese).

Decisions were taken collaboratively in design rounds on 2026-09-26. Anything marked **(proposed)** has not been confirmed by the team yet. Anything marked **OPEN** is a known gap that still needs a decision.

| Doc | What it answers |
|---|---|
| [`features-list.md`](features-list.md) | *What* we build: the feature shortlist (MVP / Stretch, Rules / Hybrid / LLM / ML) |
| [`01-technical-design.md`](01-technical-design.md) | *How* it fits together: architecture, components, domains, security, reliability, operations, limitations |
| [`02-conversation-design.md`](02-conversation-design.md) | Intent catalog, NLU output, LangGraph graph, per-feature flows, clarification and escalation rules |
| [`03-data-architecture.md`](03-data-architecture.md) | Pipeline (S3 → dbt-duckdb → Postgres), contracts, quality, lineage, date shift, database schemas |
| [`04-contracts.md`](04-contracts.md) | Tool signatures, HTTP/SSE API, handoff packet, policy YAML, audit events, confirmation tokens |
| [`05-evaluation-plan.md`](05-evaluation-plan.md) | Held-out suite, labels, baseline, simulator, judges, metric definitions |
| [`06-engineering-rules.md`](06-engineering-rules.md) | Non-negotiable rules, enforcement, repo layout, git workflow, definition of done |
| [`decision-log.md`](decision-log.md) | Every design decision (ADR-style) with alternatives considered |

Official sources: `docs/official-docs/` (the data-dictionary PDF is git-ignored because it contains the organizers' S3 keys) and the `hackathon-judge` skill's references under `.claude/skills/hackathon-judge/references/`. Requirement IDs such as `D3.4` or `B5` refer to `requirements-checklist.md` there.
